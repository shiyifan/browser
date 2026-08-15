import const
import math
from skia import *
from task import Task
from tags import *
from html_parser import HTMLParser
from css_parser import CSSParser
from utils import *
from layout import BlockLayout, DocumentLayout
from animation import NumericAnimation
from layout import LineLayout

# 浏览器默认样式，user agent style
DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()

# 当图片加载失败时的placeholder
BROKEN_IMAGE = Image.open("Broken_Image.png")


# 由Frame负责"style", "layout"以及scroll流程, 由Tab负责"paint"
class Frame:
    def __init__(self, tab, parent_frame, frame_element):
        self.tab = tab
        self.parent_frame = parent_frame
        self.frame_element = frame_element

        self.loaded = False  # frame的resources(html, css, javascript...)是否已加载完成

        # frame的id，同时也用于标识Frame内全局对象window。
        #
        # 由于"Frame"对象在创建之后不再更新修改"window_id", 因此在"Frame"内连续访问不同的url之后，window_id不会改变.
        # 不变的window_id可能在多个js context中的"WINDOWS"对象内作为"key"被保存, "key"
        # 对应的"value"（即window对象）可能已不再对应于某个Frame（因为Frame加载了新的url，但是
        # js context内的"WINDOWS"对象没有更新）
        self.window_id = len(self.tab.window_id_to_frame)

        self.tab.window_id_to_frame[self.window_id] = self

        self.url = None
        self.nodes = None  # HTML解析后的DOM Tree
        self.rules = None  # css解析后的rules

        self.needs_style = False  # 是否需要重新计算css style
        self.needs_layout = False  # 是否需要重新计算layout

        self.frame_width = 0
        self.frame_height = 0

        self.scroll = 0

        # 对于root frame：
        #   tab重绘时("run_animation_frame")时，scroll值是被browser更新(上下滚动页面)还是被tab更新(重新layout后导致scroll更新)
        # 对于其他frame：
        #   表示frame是否发生了滚动，可通过设置变量为"True"触发browser的composite
        #
        # 目前仅root frame支持"threaded scroll"
        self.scroll_changed_in_frame = False

    # 加载html,并解析得到DOM Tree, 保存在frame对象中
    # 加载所有"<script src>"，执行js.
    # 加载所有"<link rel=stylesheet href>", 解析并在frame对象中保存css style.
    # 加载所有"<img>", 并在"<img>"DOM对象中保存图片数据.
    # 加载所有"<iframe>", 在"<iframe>"DOM对象中保存新建的"Frame"对象，然后将该iframe的"load()" schedule
    #   至tab的event queue中.
    def load(self, url, payload=None):
        self.loaded = False

        headers, body = url.request(referer=self.url, payload=payload)
        body = body.decode("utf8", "replace")
        self.url = url
        self.nodes = HTMLParser(body).parse()  # 将HTML代码解析为DOM tree

        # 添加对"Content-Security-Policy" Response Header的支持
        # 仅支持 "default-src" directive
        self.allowed_origins = None
        if "content-security-policy" in headers:
            csp = headers["content-security-policy"].split()
            if len(csp) > 0 and csp[0] == "default-src":
                self.allowed_origins = []
                for origin in csp[1:]:
                    self.allowed_origins.append(URL(origin).origin())

        # HTML代码中，加载所有"<script src=''>"的标签
        #
        # 注意：该浏览器不实现类似于"<script>...js code...</script>"的内嵌功能，因为
        # 解析时区分HTML与js中的"<"以及">"符号较为复杂
        scripts = [
            node.attributes["src"]
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element) and node.tag == "script" and "src" in node.attributes
        ]

        if hasattr(self, "js") and self.js:
            # 废弃旧的js context, 避免后续执行queue中的旧task
            self.js.discarded = True
        self.js = self.tab.get_js(url)
        # 为当前的Frame新建全局window对象
        self.js.add_window(self)

        for script in scripts:
            script_url = url.resolve(script)

            # <script>的"src"是否满足ContentSecurityPolicy
            if not self.allowed_request(script_url):
                log.e(f"CSP script block: {script_url}")
                continue

            try:
                _, body = script_url.request(url)
                body = body.decode("utf8", "replace")
            except:
                continue

            # 将运行javascript的任务添加至任务队列，待后续执行(依赖于tab eventloop)
            task = Task(self.js.run, body, self.window_id)
            self.tab.task_runner.schedule_task(task)

        # 加载并解析所有"<link rel=stylesheet>"的css
        rules = DEFAULT_STYLE_SHEET.copy()  # 解析user agent stylesheet
        # HTML代码中，所有的"<link rel=stylesheet>"标签中的css url
        links = [
            node.attributes["href"]
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            and node.tag == "link"
            and node.attributes.get("rel") == "stylesheet"
            and "href" in node.attributes
        ]
        for link in links:
            style_url = url.resolve(link)

            if not self.allowed_request(style_url):
                log.e(f"CSP style block: {style_url}")
                continue

            try:
                _, body = style_url.request(url)
                body = body.decode("utf8", "replace")
            except:
                continue
            rules.extend(CSSParser(body).parse())  # 获取author stylesheet
        self.rules = rules

        # 加载所有"<img>"标签
        images = [
            node
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element) and node.tag == "img"
        ]
        for img in images:
            try:
                src = img.attributes.get("src", "")
                image_url = url.resolve(src)
                assert self.allowed_request(image_url), f"Block load of {str(image_url)} due to CSP"
                header, body = image_url.request(url)
                img.encoded_data = body  # a bit of hack to avoid body being recycled by GC
                data = Data.MakeWithoutCopy(body)
                img.image = Image.MakeFromEncoded(data)  # 将图片object附加至<img> DOM object中
                assert img.image, f"Failed to recognize image format for {str(image_url)}"
            except Exception as e:
                log.e(f"Image {img.attributes.get('src', '')} crashed", e)
                img.image = BROKEN_IMAGE

        # 加载当前"Frame"中的所有"<iframe>"标签
        iframes = [
            node
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            if node.tag == "iframe"
            if "src" in node.attributes
        ]
        for iframe in iframes:
            document_url = url.resolve(iframe.attributes["src"])
            if not self.allowed_request(document_url):
                log.e(f"Blocked iframe '{document_url}' due to CSP")
                iframe.frame = None
                continue
            iframe.frame = Frame(self.tab, self, iframe)
            iframe.url = document_url
            task = Task(iframe.frame.load, document_url)  # 异步加载子iframe
            self.tab.task_runner.schedule_task(task)

        self.scroll = 0
        self.scroll_changed_in_frame = True

        self.loaded = True

        self.document = DocumentLayout(self.nodes)

    # 根据CSP,是否允许请求(<script>, <style>, XHR)
    def allowed_request(self, url):
        return self.allowed_origins == None or url.origin() in self.allowed_origins

    def set_needs_render(self):
        self.needs_style = True
        self.tab.needs_accessibility = True
        self.tab.set_needs_paint()

    def set_needs_layout(self):
        self.needs_layout = True
        self.tab.needs_accessibility = True
        self.tab.set_needs_paint()

    def render(self):
        if self.needs_style:
            self.tab.browser.measure.time(f"[{self.window_id}] style")

            log.i(f"frame {self.window_id} style start")
            # 将css rules全部赋值至DOM结点的"style"属性上
            sorted_rules = sorted(self.rules if self.rules else [], key=cascade_priority)
            style(self.nodes, sorted_rules, self.tab)
            log.i(f"frame {self.window_id} style end")

            self.needs_layout = True
            self.needs_style = False

            self.tab.browser.measure.stop(f"[{self.window_id}] style")

        if self.needs_layout:
            self.tab.browser.measure.time(f"[{self.window_id}] layout")

            log.i(f"frame {self.window_id} layout start")
            self.document.layout(self.frame_width, self.tab.zoom)
            log.i(f"frame {self.window_id} layout end")

            self.tab.needs_accessibility = True
            self.tab.set_needs_paint()
            self.needs_layout = False

            self.tab.browser.measure.stop(f"[{self.window_id}] layout")

        clamped_scroll = self.clamp_scroll(self.scroll)
        if clamped_scroll != self.scroll:
            self.scroll_changed_in_frame = True
        self.scroll = clamped_scroll

    def click(self, x, y):
        # 根据绘制区域与点击坐标，在"layout tree"中找到所有被点击的layout object
        #
        # 可能会找到多个被点击的layout object,这些object位于tree中的不同层级
        # 在实际情况下，也可能出现相同层级的HTML元素被同时点击（例如"margin"为负值时），此时browser还需要
        # 根据"stacking context"机制判断最上层的被点击元素
        loc_rect = Rect.MakeXYWH(x, y, 1, 1)
        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if absolute_bounds_for_obj(obj).intersects(loc_rect)
        ]
        if not objs:
            # 没有找到被点击的layout object

            if self.tab.focus:
                # 清除之前的焦点

                self.tab.focused_frame.set_needs_render()
                self.focus_element(None)

            return const.NO_FOCUS

        # 已在当前frame中找到被点击的layout object

        # 获取最上层被点击的layout object对应的DOM node
        elt = None
        if isinstance(objs[-1], LineLayout) and objs[-1].node.tag == "iframe":
            # 根据BlockLayout的"layout()", 当layout object采用"block"布局时，
            # 所有children都将创建各自的BlockLayout. 当children中存在"<iframe>"时，同样将
            # 会创建这个"<iframe>"的BlockLayout.
            # 如果点击在这个BlockLayout中的LineLayout的空白区域(没有点击在<iframe>中), 那么
            # 应该由BlockLayout的parent负责这次点击后续流程。但由于LineLayout与BlockLayout的"self.node"
            # 均为"<iframe>"，这里取倒数第三个object。
            # 这样避免了后续滚动时滚动了<iframe>本身而不是<iframe>所在的"Frame"的问题.

            elt = objs[-3].node if objs[-3] else None
        else:
            elt = objs[-1].node

        # 根据最上层的object,依次向上查找第一个clickable html element
        while elt:
            if isinstance(elt, Text):
                pass

            elif is_focusable(elt):
                if self.js.dispatch_event("click", elt, self.window_id):
                    return

                if self.tab.focus != elt:
                    # 由于被点击的layout object在当前frame,所以无论如何当前frame都需要重新render
                    self.focus_element(elt)  # 更新焦点为当前被点击的DOM node
                    self.activate_element(elt)
                    self.set_needs_render()

                return

            elif elt.tag == "div":
                # 点击位于"non clickable"的div中

                if self.js.dispatch_event("click", elt, self.window_id):
                    return

                # 清除当前焦点
                if self.tab.focus:
                    self.focus_element(None)

                    # 虽然不需要再次schedule animation frame以更新div的绘制样式，但是更新了"tab.focused_frame",
                    # 这时需要通过animation frame将"root_frame_focused"状态同步至browser中.
                    # 如果通过"self.set_needs_render()"触发animation frame可能会产生不必要的style, layout等
                    # 过程
                    self.tab.browser.set_needs_animation_frame(self.tab)

                return const.NO_FOCUS

            elif elt.tag == "iframe":
                # 点击位置位于"<iframe>"内，需要将点击位置的绝对坐标转换为"<iframe>"内的相对坐标,
                # 然后再将点击事件委托给"<iframe>"处理.

                abs_bounds = absolute_bounds_for_obj(elt.layout_object)
                border = dpx(1, elt.layout_object.zoom.get())
                new_x = x - abs_bounds.left() - border
                new_y = y - abs_bounds.top() - border

                if elt.frame.click(new_x, new_y) == const.NO_FOCUS:
                    # 当child frame中没有元素可以接受焦点时, 在当前的frame中将该<iframe>置为焦点, 以便于滚动

                    self.focus_element(None, frame=elt.frame)
                    # 同上"elif elt.tag == 'div'"
                    self.tab.browser.set_needs_animation_frame(self.tab)

                return  # 返回后不再需要parent frame设置焦点

            elt = elt.parent

        # 虽然找到被点击的layout object,但是没有找到clickable html element。同样需要清除当前焦点.
        # 清除焦点由"root parent"完成
        if self.parent_frame is None:
            if self.tab.focus:
                self.tab.focused_frame.set_needs_render()
                self.focus_element(None)
            elif self.tab.focused_frame:
                self.tab.focused_frame = None

        return const.NO_FOCUS

    # 当html元素已获取了焦点，此时按下enter，执行不同的动作, 或者点击focusable元素时，执行不同的动作
    def activate_element(self, elt):
        if elt.tag == "input":
            # "<input>"的动作, 清空已输入的内容

            elt.attributes["value"] = ""
            self.set_needs_render()

        elif elt.tag == "a" and "href" in elt.attributes:
            # "<a>"的动作, 访问"href"指向的url

            url = self.url.resolve(elt.attributes["href"])
            self.load(url)

        elif elt.tag == "button":
            # "<button>"的动作, 提交"<button>"所在的表单

            while elt:
                if elt.tag == "form" and "action" in elt.attributes:
                    self.submit_form(elt)
                    break
                elt = elt.parent

    def submit_form(self, elt):
        if self.js.dispatch_event("submit", elt, self.window_id):
            return
        inputs = [
            node
            for node in tree_to_list(elt, [])
            if isinstance(node, Element) and node.tag == "input" and "name" in node.attributes
        ]

        # encode the "name-value" pairs
        # 采用url的"%"编码方式

        body = ""
        for input in inputs:
            name = urllib.parse.quote(input.attributes["name"])
            value = urllib.parse.quote(input.attributes.get("value", ""))
            body += f"&{name}={value}"
        body = body[1:]
        url = self.url.resolve(elt.attributes["action"])
        self.load(url, body)

    # 设置DOM node为当前焦点, 并在某些情况下触发重绘
    #
    # node: 接受焦点的DOM node
    # frame: 默认情况下(None)表示清空焦点与"tab.focused_frame". 但是当设置<iframe>本身为焦点时（当iframe内没有DOM element
    # 接收焦点时），frame应该为<iframe>对应的"Frame"对象, 注意，此时node必须为"None".
    def focus_element(self, node, frame=None):
        focus = self.tab.focus
        focused_frame = self.tab.focused_frame

        if focus:
            focus.is_focused = False

        if focus and focused_frame:
            # 只要当前焦点以及焦点所在的frame不为空，那么这个frame就需要重新render.
            #   在不同frame间切换焦点，旧焦点的frame需要render. 相同的frame间切换不同焦点，
            #   frame同样需要render。
            #
            # 当focus为空focused_frame不为空时，表示某个<iframe>获取了焦点但是没有DOM element可以接收
            # 焦点。这时的focused_frame不需要render, 即不需要重绘DOM element. 所以这种
            # 情况下不会进入到该if分支

            dirty_style(focus)  # 已获取焦点的DOM node需要更新style
            focused_frame.set_needs_render()

        if node:
            # 如果node不为空，那么"tab.focused_frame"一定是node所在的frame, 保证"tab.[focus | focused_frame]"
            # 保证两个变量的一致性
            self.tab.focused_frame = self
        else:
            # 如果node为空，那么表示清空焦点，但用户可以设置"focused_frame"用于滚动没有clickable element获取焦点的<iframe>
            self.tab.focused_frame = frame

        # self.tab.focused_frame = frame if frame else self
        self.tab.focus = node

        if node and node != focus:
            self.tab.needs_focus_scroll = True

        if node:
            node.is_focused = True

            # 目前只有"focusable"DOM node或者None被传入当前function。
            # 为了简单实现，不论是否会有focus相关的style在animation frame时应用至该node上，
            # 这里先将style置为dirty. 在animation frame时重新计算该node的style.
            dirty_style(node)

    # 在网页中通过"tab"按键浏览, 将焦点置于下一个focusable的元素
    def advance_tab(self):
        focusable_nodes = [
            node
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element) and is_focusable(node)
        ]
        focusable_nodes.sort(key=get_tabindex)  # 根据HTML的属性"tabindex"排序

        # 找到下一个待获取焦点的element
        if self.tab.focus in focusable_nodes:
            idx = focusable_nodes.index(self.tab.focus) + 1
        else:
            idx = 0

        if idx < len(focusable_nodes):
            self.focus_element(focusable_nodes[idx])
        else:
            # tab内的focusable元素均已遍历，此时将焦点移动至chrome中

            self.focus_element(None, frame=self)  # 保证chrome循环结束后仍会循环至当前的frame中
            self.tab.browser.focus_addressbar()

        # 由于移动焦点可能影响某些DOM结点的绘制（例如相比起无焦点状态，有焦点时需要多绘制一个光标、边框等）,
        # 所以不能使用之前缓存的"CompositedLayer"中的绘制结果，"browser"中需要重新"composite"
        self.set_needs_render()

    def keypress(self, char):
        focus = self.tab.focus

        if focus.tag == "input":
            if not "value" in focus.attributes:
                self.activate_element(focus)
            focus.attributes["value"] += char

        elif "contenteditable" in focus.attributes:
            # 如果在"contenteditable"DOM node中键入字符，那么在该DOM node的最后一个"Text"node中添加字符，或者新建"Text"node

            text_nodes = [t for t in tree_to_list(focus, []) if isinstance(t, Text)]
            if text_nodes:
                last_text = text_nodes[-1]
            else:
                last_text = Text("", focus)
                focus.children.append(last_text)
            last_text.text += char

            layout = focus.layout_object
            while not isinstance(layout, BlockLayout):
                layout = layout.parent
            layout.children.mark()

        self.js.dispatch_event("keydown", focus, self.window_id)
        self.set_needs_render()

    def enter(self):
        if self.js.dispatch_event("click", self.tab.focus, self.window_id):
            return
        self.activate_element(self.tab.focus)
        self.set_needs_render()

    def backspace(self):
        focus = self.tab.focus

        if focus.tag == "input" and "value" in focus.attributes:
            value = focus.attributes["value"]
            if not value or len(value) == 0:
                return
            focus.attributes["value"] = value[:-1]
        elif "contenteditable" in focus.attributes:
            text_nodes = [t for t in tree_to_list(focus, []) if isinstance(t, Text)]
            if text_nodes:
                last_text = text_nodes[-1]
                last_text.text = last_text.text[:-1]
                if len(last_text.text) == 0:
                    focus.children.remove(last_text)

        self.js.dispatch_event("keydown", self.tab.focus, self.window_id)
        self.set_needs_render()

    def scrolldown(self):
        self.scroll = self.clamp_scroll(self.scroll + const.SCROLL_STEP)

        # "若由滚动触发了重绘，那么tab.render()"之后，"browser"需要重新"composite",
        # 避免采用旧的composited_layers进行绘制, 因为"IframeLayout.paint_effects()"中
        # 更新了用于绘制滚动的"Transform"命令的参数.
        # "scrollup()"同理
        self.scroll_changed_in_frame = True

    def scrollup(self):
        self.scroll = self.clamp_scroll(self.scroll - const.SCROLL_STEP)
        self.scroll_changed_in_frame = True

    def clamp_scroll(self, scroll):
        height = math.ceil(self.document.height.get() + 2 * const.VSTEP)
        maxscroll = height - self.frame_height
        return max(0, min(scroll, maxscroll))

    def scroll_to(self, elt):
        # 这里扁平化layout tree时，通过".value"方式直接获取某些ProtectedField.
        # 在"Tab.run_animation_frame"中，先滚动至focus再执行"render"流程. 因此通过"scroll_to"滚动时
        # 某些ProtectedField仍然是dirty的. 为避免assert异常，这里直接读取ProtectedField的值.
        objs = [obj for obj in tree_to_list(self.document, [], protect=False) if obj.node == elt]

        if not objs:
            return
        obj = objs[0]

        y = obj.y.get()
        if self.scroll < y < self.scroll + self.frame_height:
            # 位于viewport中的焦点元素无需滚动
            return

        # document_height = math.ceil(self.document.height + 2 * const.VSTEP)
        new_scroll = y - const.SCROLL_STEP
        self.scroll = self.clamp_scroll(new_scroll)
        self.scroll_changed_in_frame = True

    def __repr__(self):
        return f"Frame({self.url})"


# 根据DOM结点上"style"属性、css文件的代码创建CSS对象并赋值为"style"属性
def style(node, rules, tab):
    if not node.style:
        init_style(node)

    needs_style = any([field.dirty for field in node.style.values()])

    # 仅在"node.style"中存在任意一个dirty的css property时重新计算style
    if needs_style:
        # 仅在"style"属性为"dirty"时更新

        update_style(node, rules, tab)

    # 解析并创建子结点的CSS对象
    for child in node.children:
        style(child, rules, tab)


def init_style(node):
    style = {}

    for property in const.CSS_PROPERTIES:
        if node.parent and property in const.INHERITED_PROPERTIES:
            # 创建每一个inherited css property时显式声明dependencies
            style[property] = ProtectedField(
                node, property, dependencies=[node.parent.style[property]]
            )
        else:
            # 非inherited css property没有dependencies
            style[property] = ProtectedField(node, property, dependencies=[])

    node.style = style


def update_style(node, rules, tab):
    old_style = dict([(property, field.value) for property, field in node.style.items()])
    new_style = const.CSS_PROPERTIES.copy()

    # 先解析当前节点的inherited property的值
    for property, default_value in const.INHERITED_PROPERTIES.items():
        if node.parent:
            parent_field = node.parent.style[property]
            parent_value = parent_field.read(notify=node.style[property])
            new_style[property] = parent_value
        else:
            new_style[property] = default_value

    # 解析css代码中与当前节点匹配的rule并应用至当前节点
    for media, selector, body in rules:
        if media:
            if (media == "dark") != tab.dark_mode:
                # 如果"@media(prefers-color-scheme)"声明的主题与当前不符，则忽略其中的style
                continue
        if not selector.matches(node):
            continue
        for property, value in body.items():
            new_style[property] = value

    # 解析DOM中"style"属性的样式
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            new_style[property] = value

    # 如果DOM节点的"font-size"值为百分比数值，则根据父结点的值或者默认值计算具体"px"单位的数值
    if new_style["font-size"].endswith("%"):
        if node.parent:
            parent_field = node.parent.style["font-size"]
            parent_font_size = parent_field.read(notify=node.style["font-size"])
        else:
            parent_font_size = const.INHERITED_PROPERTIES["font-size"]
        node_pct = float(new_style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        new_style["font-size"] = str(node_pct * parent_px) + "px"

    # 查找在css中"transition"声明的属性中，哪些属性的值发生了更新,
    # 并在DOM node上根据更新的属性值创建animation对象，接着触发后续的animation frame
    transitions = diff_styles(old_style, new_style)
    for property, (old_value, new_value, num_frames) in transitions.items():
        if property == "opacity":
            animation = NumericAnimation(float(old_value), float(new_value), num_frames)
            node.animations[property] = animation
            new_style[property] = animation.animate()  # animation的第一帧

            # 请求一次browser的animation frame, 以继续渲染animation后面的frame
            tab.browser.set_needs_animation_frame(tab)

    for property, field in node.style.items():
        field.set(new_style[property])


# 获取在"transition"声明的属性中，render前后属性值不同的属性。返回 "<css property>: (<旧值>, <新值>, <动画帧个数>)" 的键值对
def diff_styles(old_style, new_style):
    transitions = {}

    for property, num_frames in parse_transition(new_style.get("transition")).items():
        # 仅在重绘前后均显式声明了transition的property时才返回该property的transition
        if property not in old_style or old_style[property] is None:
            continue
        if property not in new_style:
            continue

        old_value = old_style[property]
        new_value = new_style[property]
        if old_value == new_value:
            continue

        transitions[property] = (old_value, new_value, num_frames)

    return transitions


# 解析css"transition"属性值并返回 "<css property>: <动画帧个数>" 键值对
def parse_transition(value):
    properties = {}  # { <css property>: <动画帧个数> }

    if not value:
        return properties
    for item in value.split(","):
        property, duration = item.split(" ", 1)
        frames = int(float(duration[:-1]) / const.REFRESH_RATE_SEC)  # 在预定的时间内的总帧数
        properties[property] = frames

    return properties


def cascade_priority(rule):
    _, selector, rule = rule
    return selector.priority

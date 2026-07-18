import const
import math
from skia import *
from task import Task
from tags import *
from html_parser import HTMLParser
from css_parser import CSSParser
from utils import *
from layout import DocumentLayout
from jscontext import JSContext

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

        self.window_id = len(self.tab.window_id_to_frame)  # frame的id
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

        headers, body = url.request(self.url, payload)
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
        self.js = JSContext(self.tab)  # 目前每个"Frame"单独地拥有一个js context

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
            task = Task(self.js.run, body)
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
            task = Task(iframe.frame.load, document_url)  # 异步加载子iframe
            self.tab.task_runner.schedule_task(task)

        self.scroll = 0
        self.scroll_changed_in_frame = True

        self.loaded = True

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
            self.tab.browser.measure.time(f"[{self.window_id}]style")

            # 将css rules全部赋值至DOM结点的"style"属性上
            style(
                self.nodes, sorted(self.rules if self.rules else [], key=cascade_priority), self.tab
            )

            self.needs_layout = True
            self.needs_style = False

            self.tab.browser.measure.stop(f"[{self.window_id}]style")

        if self.needs_layout:
            self.tab.browser.measure.time(f"[{self.window_id}]layout")

            self.document = DocumentLayout(self.nodes)
            self.document.layout(self.frame_width, self.tab.zoom)

            self.tab.needs_accessibility = True
            self.tab.set_needs_paint()
            self.needs_layout = False

            self.tab.browser.measure.stop(f"[{self.window_id}]layout")

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

        elt = objs[-1].node  # 获取最上层被点击的layout object对应的DOM node

        # 根据最上层的object,依次向上查找第一个clickable html element
        while elt:
            if isinstance(elt, Text):
                pass

            elif is_focusable(elt):
                if self.js.dispatch_event("click", elt):
                    return

                if self.tab.focus != elt:
                    # 由于被点击的layout object在当前frame,所以无论如何当前frame都需要重新render
                    self.focus_element(elt)  # 更新焦点为当前被点击的DOM node
                    self.activate_element(elt)
                    self.set_needs_render()

                return

            elif elt.tag == "div":
                if self.js.dispatch_event("click", elt):
                    return

                # 点击non clickable的div后清除当前焦点
                if self.tab.focus:
                    self.focus_element(None)
                    self.set_needs_render()

                return const.NO_FOCUS

            elif elt.tag == "iframe":
                # 点击位置位于"<iframe>"内，需要将点击位置的绝对坐标转换为"<iframe>"内的相对坐标,
                # 然后再将点击事件委托给"<iframe>"处理.

                abs_bounds = absolute_bounds_for_obj(elt.layout_object)
                border = dpx(1, elt.layout_object.zoom)
                new_x = x - abs_bounds.left() - border
                new_y = y - abs_bounds.top() - border

                if elt.frame.click(new_x, new_y) == const.NO_FOCUS:
                    # 当child frame中没有元素可以接受焦点时, 在当前的frame中将该<iframe>置为焦点, 以便于滚动

                    self.focus_element(elt, frame=elt.frame)
                    self.set_needs_render()

                return  # 返回后不再需要parent frame设置焦点

            elt = elt.parent

        # 虽然找到被点击的layout object,但是没有找到clickable html element。同样需要
        # 清除当前焦点
        if self.tab.focus:
            self.tab.focused_frame.set_needs_render()
            self.focus_element(None)

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
        if self.js.dispatch_event("submit", elt):
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

    # 设置DOM node为当前焦点。
    #
    # node: 接受焦点的DOM node
    # frame: 默认情况下(None)表示DOM node所在的frame. 但是当设置<iframe>本身为焦点时，DOM node为<iframe>,
    #       frame应该为<iframe>对应的"Frame"对象.
    def focus_element(self, node, frame=None):
        focus = self.tab.focus
        focused_frame = self.tab.focused_frame

        if focus:
            focus.is_focused = False

        # 如果焦点所在的frame不是当前的frame, 那么焦点所在的frame也需要"render"以清除焦点
        if focused_frame and focused_frame != self:
            focused_frame.set_needs_render()

        self.tab.focused_frame = frame if frame else self
        self.tab.focus = node

        if node and node != focus:
            self.tab.needs_focus_scroll = True

        if node:
            node.is_focused = True

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

            self.focus_element(None)
            self.tab.browser.focus_addressbar()

        # 由于移动焦点可能影响某些DOM结点的绘制（例如相比起无焦点状态，有焦点时需要多绘制一个光标、边框等）,
        # 所以不能使用之前缓存的"CompositedLayer"中的绘制结果，"browser"中需要重新"composite"
        self.set_needs_render()

    def keypress(self, char):
        focus = self.tab.focus

        if not "value" in focus.attributes:
            self.activate_element(focus)

        self.js.dispatch_event("keydown", focus)
        focus.attributes["value"] += char
        self.set_needs_render()

    def enter(self):
        if self.js.dispatch_event("click", self.tab.focus):
            return
        self.activate_element(self.tab.focus)
        self.set_needs_render()

    def backspace(self):
        value = self.tab.focus.attributes["value"]
        if not value or len(value) == 0:
            return
        self.tab.focus.attributes["value"] = value[:-1]
        self.js.dispatch_event("keydown", self.tab.focus)
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
        height = math.ceil(self.document.height + 2 * const.VSTEP)
        maxscroll = height - self.frame_height
        return max(0, min(scroll, maxscroll))

    def scroll_to(self, elt):
        objs = [obj for obj in tree_to_list(self.document, []) if obj.node == elt]
        if not objs:
            return
        obj = objs[0]

        if self.scroll < obj.y < self.scroll + self.frame_height:
            # 位于viewport中的焦点元素无需滚动
            return

        # document_height = math.ceil(self.document.height + 2 * const.VSTEP)
        new_scroll = obj.y - const.SCROLL_STEP
        self.scroll = self.clamp_scroll(new_scroll)
        self.scroll_changed_in_frame = True


# 根据DOM结点上"style"属性、css文件的代码创建CSS对象并赋值为"style"属性
def style(node, rules, tab):
    old_style = node.style if hasattr(node, "style") else None
    node.style = {}  # CSS解析后的对象

    # 先解析当前节点的inherited property的值
    for property, default_value in const.INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    # 解析css代码中与当前节点匹配的rule并应用至当前节点
    for media, selector, body in rules:
        if media:
            if (media == "dark") != tab.dark_mode:
                # 如果"@media(prefers-color-scheme)"声明的主题与当前不符，则忽略其中的style
                continue
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    # 解析DOM中"style"属性的样式
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    # 如果DOM节点的"font-size"值为百分比数值，则根据父结点的值或者默认值计算具体"px"单位的数值
    if node.style["font-size"].endswith("%"):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = const.INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    # 解析并创建子结点的CSS对象
    for child in node.children:
        style(child, rules, tab)

    if old_style:
        # 查找在css中"transition"声明的属性中，哪些属性的值发生了更新,
        # 并在DOM node上根据更新的属性值创建animation对象，接着触发后续的animation frame

        transitions = diff_styles(old_style, node.style)
        for property, (old_value, new_value, num_frames) in transitions.items():
            if property == "opacity":
                animation = NumericAnimation(float(old_value), float(new_value), num_frames)
                node.animations[property] = animation
                node.style[property] = animation.animate()  # animation的第一帧

                # 请求一次browser的animation frame, 以继续渲染animation后面的frame
                tab.browser.set_needs_animation_frame(tab)


# 获取在"transition"声明的属性中，render前后属性值不同的属性。返回 "<css property>: (<旧值>, <新值>, <动画帧个数>)" 的键值对
def diff_styles(old_style, new_style):
    transitions = {}

    for property, num_frames in parse_transition(new_style.get("transition")).items():
        if property not in old_style:
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

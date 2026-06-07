from skia import *
from html_parser import HTMLParser
import const
import urllib.parse
from layout import DocumentLayout
from tags import Element, Text
from css_parser import CSSParser
from jscontext import JSContext
from utils import tree_to_list, log, print_tree, parse_transform, map_translation
from url import URL
from task import Task, TaskRunner
from commit import CommitData
from animation import NumericAnimation
import math

# 浏览器默认样式，user agent style
DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()

tab_counter = 0  # tab id


# 浏览器标签页
# 负责url请求、DOM解析、layout tree解析
class Tab:
    def __init__(self, browser, tab_height):
        global tab_counter
        self.id = tab_counter
        tab_counter += 1

        self.scroll = 0  # 当前已向上滑动的距离

        # tab页的高度，即"canvas高度" - "canvas顶部chrome所占据的高度"
        self.tab_height = tab_height

        self.url = None
        self.history = []  # 保存访问过的url，并且当前tab页显示的网页url位于数组末尾

        self.nodes = None  # HTML解析后的DOM Tree
        self.rules = None  # css解析后的rules

        self.focus = None  # 点击后，获取到焦点的'<input>'DOM对象

        # 在tab页加载新的url前后，task queue不变
        self.task_runner = TaskRunner(self)

        self.needs_style = False  # 是否需要重新计算css style
        self.needs_layout = False  # 是否需要重新计算layout
        self.needs_paint = False  # 是否需要重新收集绘制命令

        self.browser = browser

        # 重绘时("run_animation_frame")时，scroll值是被browser更新(上下滚动页面)还是被tab更新(重新layout后导致scroll更新)
        self.scroll_changed_in_tab = False

        self.composited_updates = []  # 保存执行animation frame的node

        self.zoom = 1

        self.dark_mode = False

    def set_needs_render(self):
        self.needs_style = True
        self.browser.set_needs_animation_frame(self)

    def set_needs_layout(self):
        self.needs_layout = True
        self.browser.set_needs_animation_frame(self)

    def set_needs_paint(self):
        self.needs_paint = True
        self.browser.set_needs_animation_frame(self)

    def load(self, url, payload=None):
        self.zoom = 1
        self.history.append(url)

        headers, body = url.request(self.url, payload)
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
        self.js = JSContext(self)

        for script in scripts:
            script_url = url.resolve(script)

            # <script>的"src"是否满足ContentSecurityPolicy
            if not self.allowed_request(script_url):
                log.e(f"CSP script block: {script_url}")
                continue

            try:
                _, body = script_url.request(url)
            except:
                continue

            # 将运行javascript的任务添加至任务队列，待后续执行(依赖于mainloop)
            task = Task(self.js.run, body)
            self.task_runner.schedule_task(task)

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
            except:
                continue
            rules.extend(CSSParser(body).parse())  # 获取author stylesheet
        self.rules = rules

        self.set_needs_render()

        self.scroll = 0
        self.scroll_changed_in_tab = True

    # 计算layout并收集每个layout对象的绘制命令
    # 多数情况下由Browser的animation timer添加至task队列中，并在event loop中调用。
    def render(self):
        """根据DOM Tree构建layout tree,然后收集layout tree上每个结点的绘制command"""

        self.browser.measure.time("render")

        if self.needs_style:
            self.browser.measure.time("style")

            # 根据当前theme修改绘制HTML element的默认前景色color
            if self.dark_mode:
                const.INHERITED_PROPERTIES["color"] = "white"
            else:
                const.INHERITED_PROPERTIES["color"] = "black"

            # 将css rules全部赋值至DOM结点的"style"属性上
            style(self.nodes, sorted(self.rules if self.rules else [], key=cascade_priority), self)

            self.needs_layout = True
            self.needs_style = False

            self.browser.measure.stop("style")

        if self.needs_layout:
            self.browser.measure.time("layout")

            self.document = DocumentLayout(self.nodes)
            self.document.layout(self.zoom)  # 构建layout tree

            self.needs_paint = True
            self.needs_layout = False

            self.browser.measure.stop("layout")

        if self.needs_paint:
            # 收集layout tree上每个layout object生成的绘制command

            self.browser.measure.time("paint")

            self.display_list = []
            paint_tree(self.document, self.display_list)

            self.needs_paint = False

            self.browser.measure.stop("paint")

        clamped_scroll = self.clamp_scroll(self.scroll)
        if clamped_scroll != self.scroll:
            self.scroll_changed_in_tab = True
        self.scroll = clamped_scroll

        self.browser.measure.stop("render")

    def run_animation_frame(self, scroll, rand):
        self.browser.measure.time(
            "run animation",
            cat="debug",
            args={"tab": self.id, "changed": self.scroll_changed_in_tab, "rand": rand},
        )

        if not self.scroll_changed_in_tab:
            self.scroll = scroll

        self.browser.measure.time("__runRAFHandlers")
        # 计算layout之前执行通过"requestAnimationFrame"注册的callback
        self.js.interp.evaljs("__runRAFHandlers()")
        self.browser.measure.stop("__runRAFHandlers")

        # 在"node.style"上更新所有的css"transition"属性的下一帧属性值, 然后保存这个node
        for node in tree_to_list(self.nodes, []):
            for property_name, animation in node.animations.items():
                value = animation.animate()
                if value:
                    node.style[property_name] = value
                    self.composited_updates.append(node)
                    self.set_needs_paint()  # 不仅让"render"重新收集绘制命令，而且让browser安排下一次的animation frame

        # 在browser "raster and draw"期间，是否需要从tab display list中提取PaintCommand并创建"CompositedLayer"
        # 如果不需要，那么在"self.render()"前后仅仅是node的animation visual effect发生了变化. browser可以重用之前"CompositedLayer"的绘制结果
        # 如果需要，那么"self.render()"中重新style以及layout, browser需要重新提取PaintCommand
        needs_composite = self.needs_style or self.needs_layout

        self.render()

        composited_updates = None  # 保存已执行animation frame的node与新的Blend command
        if not needs_composite:
            # browser不需要再次"composite", 可重用PaintCommand的绘制结果，仅重新绘制visual effect即可

            composited_updates = {}
            for node in self.composited_updates:
                # "composited_updates"的结构无法适用于下面这样的display list:
                #
                # Blend: (opacity)
                #   Blend: (overflow: clip)
                #      DrawRRect
                #   Draw**
                #   Draw**
                #
                # 在"get_latest()"中获取"DrawRRect"命令的最新的parent时，如果Blend(overflow)的"node"也是当前的DOM node,
                # 那么DrawRRect的parent将会被错误地替换为animation的Blend.
                # 因此创建Blend(overflow)对象时，"node"参数设置为"None"
                composited_updates[node] = node.blend_op
        self.composited_updates = []

        commit_data = CommitData(
            self.url, self.scroll, self.document.height, self.display_list, composited_updates
        )
        self.display_list = None
        self.browser.commit(self, commit_data, rand)

        self.scroll_changed_in_tab = False

        self.browser.measure.stop("run animation", cat="debug", args={"tab": self.id, "rand": rand})

    def draw(self, canvas, display_list):
        """根据已生成的绘制command,在canvas上绘制tab内容，由Browser调用"""

        # 根据计算后页面元素的坐标、样式开始绘制
        #
        # 由于tab页先绘制在tab surface上，将tab surface内容复制到浏览器整个页面的root surface上再
        # 根据偏移量和滚动距离调整。因此绘制时不需要考虑滚动以及相对于chrome的偏移量
        for cmd in display_list:
            cmd.execute(canvas)

    def scrollup(self):
        if self.scroll <= 0:
            return

        self.scroll -= const.SCROLL_STEP

    def scrolldown(self):
        # 已显示最后一行内容后，不再继续向下滚动
        max_y = max(self.document.height + 2 * const.VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + const.SCROLL_STEP, max_y)

    def keypress(self, char):
        if self.focus:
            self.js.dispatch_event("keydown", self.focus)
            self.focus.attributes["value"] += char
            self.set_needs_render()

    def click(self, x, y):
        self.browser.measure.instant("click")
        self.render()  # 在判断点击位置之前，确保页面布局必须是最新的

        # 如果未找到被点击的layout object, 返回前是否需要重绘
        focus_lost = False

        # 判断点击位置之前先重置焦点
        if self.focus:
            self.focus.is_focused = False
            self.focus = None
            focus_lost = True

        y += self.scroll  # 使纵坐标y为相对于网页绘制内容的坐标

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
            if focus_lost:
                self.set_needs_render()
            return
        elt = objs[-1].node  # 获取最上层被点击的layout object对应的DOM node

        # 根据最上层的object,依次向上查找第一个"<a>"
        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                if self.js.dispatch_event("click", elt):
                    return
                # 找到最上层的"<a>"，加载"href"指向的链接
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elif elt.tag == "input":
                if self.js.dispatch_event("click", elt):
                    return
                self.focus = elt
                elt.attributes["value"] = ""
                elt.is_focused = True
                return self.set_needs_render()
            elif elt.tag == "button":
                if self.js.dispatch_event("click", elt):
                    return
                # 被点击的是"<button>"，准备提交表单
                while elt:
                    # 寻找上层的"<form>"
                    if elt.tag == "form" and "action" in elt.attributes:
                        return self.submit_form(elt)
                    elt = elt.parent
                break  # 如果是一个独立的"<button>",不在任何"<form>"中，则仅触发"click"事件
            elif elt.tag == "div":
                if self.js.dispatch_event("click", elt):
                    return
            elt = elt.parent
        self.set_needs_render()

    def go_back(self):
        """返回至上一个访问的url"""

        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)

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

    def backspace(self):
        if not self.focus:
            return
        value = self.focus.attributes["value"]
        if not value or len(value) == 0:
            return
        self.focus.attributes["value"] = value[:-1]
        self.js.dispatch_event("keydown", self.focus)
        self.set_needs_render()

    # 根据CSP,是否允许请求(<script>, <style>, XHR)
    def allowed_request(self, url):
        return self.allowed_origins == None or url.origin() in self.allowed_origins

    def clamp_scroll(self, scroll):
        height = math.ceil(self.document.height + 2 * const.VSTEP)
        maxscroll = height - self.tab_height
        return max(0, min(scroll, maxscroll))

    def zoom_by(self, increment):
        if increment:
            self.zoom *= 1.1
            self.scroll *= 1.1
        else:
            self.zoom *= 1 / 1.1
            self.scroll *= 1 / 1.1
        self.scroll_changed_in_tab = True
        self.set_needs_render()

    def reset_zoom(self):
        self.scroll /= self.zoom
        self.zoom = 1
        self.scroll_changed_in_tab = True
        self.set_needs_render()

    # 设置颜色主题
    def set_dark_mode(self, val):
        self.dark_mode = val
        self.set_needs_render()

    def destroy(self):
        self.js.destroy()


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
    for selector, body in rules:
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


def paint_tree(layout_object, display_list):
    """收集\"layout_object\"及其子节点的绘制命令,绘制命令保存在\"display_list\"中"""

    cmds = []
    # "layout_object"自身的绘制命令
    if layout_object.should_paint():
        cmds.extend(layout_object.paint())

    # "layout_object"的子节点的绘制命令
    for child in layout_object.children:
        paint_tree(child, cmds)

    if layout_object.should_paint() and hasattr(layout_object, "paint_effects"):
        cmds = layout_object.paint_effects(cmds)

    display_list.extend(cmds)


def cascade_priority(rule):
    selector, rule = rule
    return selector.priority


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


# 计算layout object在应用css"transform"之后的绝对绘制区域
def absolute_bounds_for_obj(obj):
    rect = Rect.MakeXYWH(obj.x, obj.y, obj.width, obj.height)

    # 顺着DOM Tree向上依次应用所有parent node上的"transform"
    cur = obj.node
    while cur:
        rect = map_translation(rect, parse_transform(cur.style.get("transform", "")))
        cur = cur.parent

    return rect

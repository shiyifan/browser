from skia import *
import const
import urllib.parse
from layout import IframeLayout
from tags import Element
from jscontext import JSContext
from utils import *
from task import TaskRunner
from commit import CommitData
from accessibility import AccessibilityNode
from frame import Frame
from fields import ProtectedField

tab_counter = 0  # tab id


# 浏览器标签页
# 负责url请求、DOM解析、layout tree解析
class Tab:
    def __init__(self, browser, tab_height):
        global tab_counter
        self.id = tab_counter
        tab_counter += 1

        # tab页的高度，即"canvas高度" - "canvas顶部chrome所占据的高度"
        self.tab_height = tab_height

        self.url = None
        self.history = []  # 保存访问过的url，并且当前tab页显示的网页url位于数组末尾

        # focus:
        #   获取到焦点的DOM对象. 或者是通过点击获取焦点，或者是通过tab获取焦点
        # focused_frame:
        #   获取到焦点的DOM对象所在的"Frame". 而当焦点为<iframe>时， 表示<iframe>对应的"Frame"对象, 此时"self.focus"为"None"
        #
        # focus与focused_frame为一对有关联的变量:
        #   focus如果不为空，那么focused_frame一定不为空，且一定是focus所在的frame.
        #   focus如果为空，那么focused_frame为空时，表示tab内没有frame获取了焦点，默认滚动的frame为root frame. focused_frame不为空时，
        #       表示某个frame获取了焦点，但是frame内没有DOM元素可以接收焦点。这时滚动的frame为该frame.
        self.focus = None
        self.focused_frame = None

        # 在tab页加载新的url前后，task queue不变
        self.task_runner = TaskRunner(self)

        self.needs_paint = False  # 是否需要重新收集绘制命令

        self.browser = browser

        self.composited_updates = []  # 保存执行animation frame的node

        self.zoom = 1

        self.dark_mode = False

        self.needs_focus_scroll = False  # 是否由于"tab"键轮换焦点而触发了animation frame

        self.needs_accessibility = False
        self.accessibility_tree = None

        self.root_frame = None

        # tab中每个"Frame"对象与frame id的关系映射.
        # Python中"dictionary"的item按照插入时的顺序排列,因此遍历时的顺序恰好对应了iframe的层次嵌套关系.
        # 先被访问的是后被访问的父结点或者同级结点，不可能是子结点
        self.window_id_to_frame = {}

        self.origin_to_js = {}  # http url origin --> js context

    def set_needs_render_all_frames(self):
        for id, frame in self.window_id_to_frame.items():
            frame.set_needs_render()

    def set_needs_paint(self):
        self.needs_paint = True
        self.browser.set_needs_animation_frame(self)

    def load(self, url, payload=None):
        self.browser.measure.time("load", args={"url": str(url)})

        self.zoom = 1
        self.history.append(url)
        self.url = url

        # 创建"root_frame"作为其他"<iframe>"的根结点, 同时也是tab的默认第一个frame
        self.root_frame = Frame(self, None, None)
        self.root_frame.frame_width = const.WIDTH
        self.root_frame.frame_height = self.tab_height
        self.root_frame.load(url, payload)

        self.root_frame.focus_element(None)

        self.set_needs_render_all_frames()

        self.browser.measure.stop("load")

    # 计算layout并收集每个layout对象的绘制命令
    # 多数情况下由Browser的animation timer添加至task队列中，并在event loop中调用。
    def render(self):
        """根据DOM Tree构建layout tree,然后收集layout tree上每个结点的绘制command"""

        self.browser.measure.time("render")

        self.browser.measure.time("frames render")
        for _, frame in self.window_id_to_frame.items():
            if frame.loaded:
                frame.render()
        self.browser.measure.stop("frames render")

        if self.needs_accessibility:
            self.browser.measure.time("accessibility")
            self.accessibility_tree = AccessibilityNode(self.root_frame.nodes)
            self.accessibility_tree.build()  # 通过DOM Tree构建Accessbility Tree
            self.needs_accessibility = False
            self.browser.measure.stop("accessibility")

        if self.needs_paint:
            # 收集layout tree上每个layout object生成的绘制command

            self.browser.measure.time("paint")

            self.display_list = []
            paint_tree(self.root_frame.document, self.display_list)

            self.needs_paint = False

            self.browser.measure.stop("paint")

        self.browser.measure.stop("render")

    def run_animation_frame(self, scroll, rand):
        # 如果由"tab"键轮换焦点引起的animation frame, 那么需要适当地滚动以确保新焦点位于窗口可视区域中
        if self.needs_focus_scroll and self.focus:
            self.scroll_to(self.focus)
        self.needs_focus_scroll = False

        if not self.root_frame.scroll_changed_in_frame:
            self.root_frame.scroll = scroll

        self.browser.measure.time("__runRAFHandlers")
        # 计算layout之前, 执行通过"requestAnimationFrame"注册的callback
        for window_id, frame in self.window_id_to_frame.items():
            if not frame.loaded:
                continue
            frame.js.dispatch_RAF(frame.window_id)
        self.browser.measure.stop("__runRAFHandlers")

        # 所有的frame中, 在所有的"node.style"上更新所有的css"transition"属性的下一帧属性值, 然后保存这个node
        loaded_frames = [f for f in list(self.window_id_to_frame.values()) if f.loaded]
        nodes = []  # all loaded frames' nodes
        for frame in loaded_frames:
            tree_to_list(frame.nodes, nodes)
        for node in nodes:
            for property_name, animation in node.animations.items():
                value = animation.animate()
                if value:
                    # 这里直接修改ProtectedField中的属性值但没有"mark"以及"notify".
                    #
                    # TODO: 由于绘制animation的过程帧时没有进行"layout"，因此这里设置的"dirty"flag将会保留至"paint"阶段，
                    # 导致读取"style"属性时发生assert异常。但是这种使用方式违反了ProtectedField的设计原则.
                    node.style.get()[property_name] = value

                    # 不仅通过"render"重新收集绘制命令，而且让browser安排下一次的animation frame
                    self.set_needs_paint()

                # 无论animation是否完成（即"value"不是None时表示未完成，是None时表示上一animation frame已是最后一帧）,
                # 这里都会保存带有animation的node。
                #
                # 当tab内有两个animation且绘制时间段有重叠时，在先结束的animation
                # 的最后一帧的下一帧时，"value"的值为None。如果此时不再保存至"self.composited_updates"时，那么
                # 在"browser.paint_draw_list()"调用"get_latest()"时，由于无法在"composited_updates"中找到node而
                # 采用旧的effect，导致animation在最后一帧后的下一帧突然又变回了animation之前的状态.
                # 如下所示:
                #
                #                                    last frame
                #                                         |
                #                                         v   back to the previous state
                #    animation 0   |----------------------|               |
                #                                         |               v
                #    animation 1                |---------+|---------------------|
                #                                          ^
                #                                          |
                #                                      the frame
                #                                   after last frame
                #
                # 为避免这个问题，无论animation是否结束，这里都将保存带有animation的node.
                self.composited_updates.append(node)

        # 在browser "raster and draw"期间，是否需要从tab display list中提取PaintCommand并创建"CompositedLayer"
        # 如果不需要，那么在"self.render()"前后仅仅是node的animation visual effect发生了变化. browser可以重用之前"CompositedLayer"的绘制结果
        # 如果需要，那么"self.render()"中重新style以及layout, browser需要重新提取PaintCommand
        #
        # 只要有一个frame需要重新"style"或者"layout",那么就需要重新"composite"
        needs_style = any([f.needs_style for f in loaded_frames])
        needs_layout = any([f.needs_layout for f in loaded_frames])
        needs_composite = needs_style or needs_layout

        self.render()

        # 在每个frame render之后，如果有一个frame更新了scroll, 那么browser需要重新"composite"
        for window_id, frame in self.window_id_to_frame.items():
            if frame == self.root_frame:
                continue

            if frame.scroll_changed_in_frame:
                needs_composite = True
                frame.scroll_changed_in_frame = False

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

        # root frame是否获取了焦点。用于实现root frame的threaded scrolling.
        root_frame_focused = not self.focused_frame or self.focused_frame == self.root_frame

        commit_data = CommitData(
            self.url,
            self.root_frame.scroll,
            root_frame_focused,
            self.root_frame.document.height.get(),
            self.display_list,
            composited_updates,
            self.accessibility_tree,
            self.focus,
        )
        self.display_list = None
        self.accessibility_tree = None
        self.browser.commit(self, commit_data, rand)

        self.root_frame.scroll_changed_in_frame = False

        self.browser.measure.stop("run animation", cat="debug", args={"tab": self.id, "rand": rand})

    def draw(self, canvas, display_list):
        """根据已生成的绘制command,在canvas上绘制tab内容，由Browser调用"""

        # 根据计算后页面元素的坐标、样式开始绘制
        #
        # 由于tab页先绘制在tab surface上，将tab surface内容复制到浏览器整个页面的root surface上再
        # 根据偏移量和滚动距离调整。因此绘制时不需要考虑滚动以及相对于chrome的偏移量
        for cmd in display_list:
            cmd.execute(canvas)

    def keypress(self, char):
        if self.focus:
            self.focused_frame.keypress(char)

    def click(self, x, y):
        self.browser.measure.instant("click")
        self.render()  # 在判断点击位置之前，确保页面布局必须是最新的

        y += self.root_frame.scroll  # 使纵坐标y为相对于网页绘制内容的坐标

        self.root_frame.click(x, y)

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
        self.focused_frame.backspace()

    def zoom_by(self, increment):
        if increment:
            self.zoom *= 1.1
            for _, frame in self.window_id_to_frame.items():
                frame.scroll *= 1.1
        else:
            self.zoom *= 1 / 1.1
            for _, frame in self.window_id_to_frame.items():
                frame.scroll *= 1.1

        self.set_needs_render_all_frames()

    def reset_zoom(self):
        for _, frame in self.window_id_to_frame.items():
            frame.scroll /= self.zoom
        self.zoom = 1
        self.set_needs_render_all_frames()

    # 设置颜色主题
    def set_dark_mode(self, val):
        self.dark_mode = val
        self.set_needs_render_all_frames()

    def advance_tab(self):
        frame = self.focused_frame or self.root_frame
        frame.advance_tab()

    def enter(self):
        if not self.focus:
            return

        self.focused_frame.enter()

    # 当html元素已获取了焦点，此时按下enter，执行不同的动作, 或者点击focusable元素时，执行不同的动作
    def activate_element(self, elt):
        if elt.tag == "input":
            # "<input>"的动作, 清空已输入的内容

            elt.attributes["value"] = ""
            self.set_needs_render_all_frames()

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

    def destroy(self):
        for id, frame in self.window_id_to_frame.items():
            frame.js.destroy()

    def blur(self):
        if self.focused_frame:
            self.focused_frame.focus_element(None)
        self.set_needs_render_all_frames()

    def scroll_to(self, elt):
        self.focused_frame.scroll_to(elt)

    def scrolldown(self):
        frame = self.focused_frame or self.root_frame
        frame.scrolldown()
        self.set_needs_paint()

    def scrollup(self):
        frame = self.focused_frame or self.root_frame
        frame.scrollup()
        self.set_needs_paint()

    def get_js(self, url):
        origin = url.origin()
        if origin not in self.origin_to_js:
            self.origin_to_js[origin] = JSContext(self, origin)
        return self.origin_to_js[origin]

    def post_message(self, message, target_window_id):
        frame = self.window_id_to_frame[target_window_id]
        frame.js.dispatch_post_message(message, target_window_id)


def paint_tree(layout_object, display_list):
    """收集\"layout_object\"及其子节点的绘制命令,绘制命令保存在\"display_list\"中"""

    cmds = []
    # "layout_object"自身的绘制命令
    if layout_object.should_paint():
        cmds.extend(layout_object.paint())

    if (
        isinstance(layout_object, IframeLayout)
        and layout_object.node.frame
        and layout_object.node.frame.loaded
    ):
        # 绘制"IframeLayout"时，应该绘制它内部的layout tree,而不是它本身
        paint_tree(layout_object.node.frame.document, cmds)
    else:
        # "layout_object"的子节点的绘制命令
        c = layout_object.children
        children = c.get() if isinstance(c, ProtectedField) else c

        for child in children:
            paint_tree(child, cmds)

    # 此时"cmds"中已包含"layout_object"以及所有子结点的绘制命令

    if layout_object.should_paint() and hasattr(layout_object, "paint_effects"):
        cmds = layout_object.paint_effects(cmds)

    display_list.extend(cmds)

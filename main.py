import ctypes
from sdl2 import *
from skia import *
import const
from chrome import Chrome
from tab import Tab
from url import URL
import math
from task import Task
from threading import Timer, current_thread, RLock
from measure import MeasureTime
from watchdog import Watchdog
import random
import sys
import OpenGL.GL
from utils import tree_to_list, local_to_absolute, speak_text
from commands import PaintCommand, DrawCompositedLayer, Blend, DrawOutline
from layer import CompositedLayer


def main():
    SDL_Init(SDL_INIT_EVENTS)
    browser = Browser()
    browser.new_tab(URL(const.HTTP_URL))
    mainloop(browser)


# 带有标签页功能的浏览器
# 负责管理窗口以及canvas，响应用户操作事件
#
# 采用SDL界面框架，负责捕获系统事件(用户的键盘、鼠标事件), 创建窗口并展示Skia的绘制结果
# 采用Skia图形库，负责实际的绘制工作，并可以将绘制结果转换为二进制的像素信息并由SDL展示
class Browser:
    def __init__(self):
        current_thread().name = "Browser Thread"

        self.tabs = []
        self.active_tab = None

        # 初始化SDL, Skia以及OpenGL
        init_sdl_skia_opengl(self)

        # 用于初步绘制的skia surface
        self.root_surface = Surface.MakeFromBackendRenderTarget(
            self.skia_context,
            GrBackendRenderTarget(
                const.WIDTH, const.HEIGHT, 0, 0, GrGLFramebufferInfo(0, OpenGL.GL.GL_RGBA8)
            ),
            kBottomLeft_GrSurfaceOrigin,
            kRGBA_8888_ColorType,
            ColorSpace.MakeSRGB(),
        )

        self.chrome = Chrome(self)

        # 用于绘制chrome以及tab页内容的skia surface
        #
        # 分别创建两者的surface可以减少不必要的绘制过程（tab更新后，chrome不必重绘，chrome更新后，tab不必重绘）。
        # 被减少的"绘制过程"具体指"通过canvas对象在surface上绘制图形", 而每次渲染时仍需要将两者的surface中的数据一同复制到
        # root surface中.
        self.chrome_surface = Surface.MakeRenderTarget(
            self.skia_context,
            Budgeted.kNo,
            ImageInfo.MakeN32Premul(const.WIDTH, math.ceil(self.chrome.bottom)),
        )

        # 点击之后焦点位于chrome中还是tab页中
        # None表示位于chrome,"content"表示位于tab中
        self.focus = None

        # 用于计算layout的timer. 注意：timer超时后仅计算layout(即调用'tab.render()')，不会在canvas中绘制
        self.animation_timer = None

        # 该随机数标识由"browser.commit()"调用发起的一次"raster and draw"。
        #
        # 随机数由"browser.schedule_animation_frame"生成，用于标识整个的渲染流程.
        # 该变量标识了整个渲染流程的最后一步"raster and draw"
        self.rand_raster_and_draw = None

        # 是否安排下一次的页面绘制的task
        self.needs_animation_frame = True

        # 统计耗时
        self.measure = MeasureTime()

        # 创建一个reenter lock(可重入的lock), 用于保证browser thread以及tab的main thread访问某些变量时是线程安全的
        self.lock = RLock()

        # 保存tab传递给browser的绘制信息
        self.active_tab_url = None
        self.active_tab_scroll = 0  # "Tab.render()"时采用的滚动距离, 用于实现"threaded scroll"
        self.active_tab_height = 0  # "Tab.render()"后计算得到的DOM总体高度（不包含上下空白边距）
        self.active_tab_display_list = None

        # 保存由(display list中的)所有的"PaintCommand"创建的composited layer, 在animation的绘制期间，
        # 这些layer的绘制结果可以在多个frame间重用
        self.composited_layers = []

        # 保存新的display list, 该list由"Blend -> ... -> DrawCompositedLayer"的结构构成,不同于由"tab.paint_tree()"
        # 得到的list, 新list的所有叶子结点均为"DrawCompositedLayer", 且在animation的绘制期间在多个frame间重用绘制结果
        self.draw_list = []

        self.needs_composite = False
        self.needs_raster = False
        self.needs_draw = False

        # 保存由"tab.commit()"传递来的"已更新animation frame"的node结点
        self.composited_updates = {}

        self.dark_mode = False

        # accessibility flags
        self.needs_accessibility = False
        self.accessibility_is_on = False
        self.has_spoken_document = False
        self.tab_focus = None
        self.last_tab_focus = None
        self.spoken_alerts = []
        self.hovered_a11y_node = None
        self.needs_speak_hovered_node = False
        self.pending_hover = None

    def set_needs_composite(self):
        self.needs_composite = True
        self.needs_raster = True
        self.needs_draw = True

    def set_needs_raster(self):
        self.needs_raster = True
        self.needs_draw = True

    def set_needs_draw(self):
        self.needs_draw = True

    def set_needs_accessibility(self):
        if not self.accessibility_is_on:
            self.needs_accessibility = False
            self.has_spoken_document = False
            self.last_tab_focus = None
            self.spoken_alerts = []
            self.hovered_a11y_node = None
            self.needs_speak_hovered_node = False
            self.pending_hover = None
            self.set_needs_draw()
            return
        self.needs_accessibility = True
        self.needs_draw = True

    # 设置当前active tab
    #
    # 这里重置了一些“active_tab_*”变量，没有直接从切换后的tab中获取这些变量值.
    # 反而将赋值委托给下一次的"schedule animation task", 并由tab调用"Browser.commit()"实现
    def set_active_tab(self, tab):
        self.active_tab = tab
        self.needs_animation_frame = True
        self.animation_timer = None
        self.clear_data()

        # 设置主题颜色
        task = Task(self.active_tab.set_dark_mode, self.dark_mode)
        self.active_tab.task_runner.schedule_task(task)

    def clamp_scroll(self, scroll):
        height = self.active_tab_height + 2 * const.VSTEP  # 需要包含上下空白边距
        # 最大可以向下滚动的距离
        maxscroll = height - (const.HEIGHT - self.chrome.bottom)

        return max(0, min(scroll, maxscroll))

    def set_needs_raster_and_draw(self):
        self.lock.acquire(blocking=True)
        self.lock.release()

    def set_needs_animation_frame(self, tab):
        self.lock.acquire(blocking=True)
        if tab == self.active_tab:
            self.needs_animation_frame = True
        self.lock.release()

    def new_tab(self, url):
        self.lock.acquire(blocking=True)
        self.new_tab_internal(url)
        self.lock.release()

    # 新建一个tab并设置为当前显示的tab
    def new_tab_internal(self, url):
        new_tab = Tab(self, const.HEIGHT - self.chrome.bottom)
        new_tab.task_runner.start_thread()
        self.set_active_tab(new_tab)
        self.tabs.append(new_tab)
        self.schedule_load(url, first_load=True)

    # 在active tab中安排一个加载新url的task
    # first_load: 是否是在新建tab页时第一次的load
    def schedule_load(self, url, body=None, first_load=False):
        if not first_load:
            # 新tab第一次load时不清空queue,避免意外删除了“set_dark_mode”的task
            self.active_tab.task_runner.clear_pending_tasks()
        task = Task(self.active_tab.load, url, body)
        self.active_tab.task_runner.schedule_task(task)

    def raster_tab(self):
        """根据tab页'layout()'之后得到的display list, 在tab canvas中清空并重新绘制tab内容"""

        for composited_layer in self.composited_layers:
            composited_layer.raster()

    def raster_chrome(self):
        """在chrome canvas上清空并重新绘制chrome"""

        if self.dark_mode:
            background_color = ColorBLACK
        else:
            background_color = ColorWHITE
        canvas = self.chrome_surface.getCanvas()
        canvas.clear(background_color)

        # 绘制browser chrome
        for cmd in self.chrome.paint():
            # 绘制时滚动距离scroll=0，确保chrome始终位于canvas上方
            cmd.execute(canvas)

    # 提取display list中的command, 并根据command创建"CompositedLayer"用于缓存绘制结果
    def composite(self):
        self.composited_layers = []

        # 创建display list中command间的父级关系，便于创建包含"DrawCompositedLayer"command的display list
        add_parent_pointers(self.active_tab_display_list)

        all_commands = []
        for cmd in self.active_tab_display_list:
            all_commands = tree_to_list(cmd, all_commands)

        # 扁平化后的"all_commands"的结构大体为:
        # [<html transform>, <head transform>, ...(<head transform> children)..., <body transform>, ...(<body transform> children)...]

        # cacheable(可缓存的)绘制command, 例如display list中的PaintCommand,
        # 没有任何effect的"Blend" command(no-op "Blend" command), 如下所示：
        #
        #   Blend (NOT cacheable!)          [0]
        #    |
        #    +->Blend (opacity: 0.5) (NOT cacheable!)   [1]
        #    |   |
        #    |   +-->DrawRRect  (cacheable) [2]
        #    |   |
        #    |   +-->DrawText   (cacheable)
        #    |
        #    |
        #    +->Blend (no-op) (cacheable)   [3]
        #    |   |
        #    |   +-->DrawRRect  (cached by parent!)     [4]
        #    |   |
        #    |   +-->DrawText   (cached by parent!)
        #    |
        #    |
        #    +->Blend (no-op) (cacheable)
        #        |
        #        +-->DrawRRect  (cached by parent!)
        #        |
        #        +-->DrawText   (cached by parent!)
        #
        # 对于Blend, 如果没有任何effect而且children中也没有effect,那么Blend及其children的绘制将被缓存，且children不再单独缓存.
        # 只要有effect或者children中任意一个有effect, 那么Blend将不会被缓存.
        # 例如:
        # [2]和[4]: [1]由于opacity将不被缓存, 但[2]可以被缓存，所以[2]将单独创建一个"CompositedLayer"。
        #          但是[3]由于没有effect, 且children也没有effect,因此[3]可以被缓存, [4]作为[3]的children之一，因此无需再单独创建"CompositedLayer",
        #          否则将产生重复绘制
        # [0]: 由于[1]将不被缓存，那么[0]也不会被缓存
        #
        # display list的树形结构中，如果某个结点不被缓存，那么该结点的直接子结点(无effect)可被缓存并单独创建"CompositedLayer", 间接子结点(无effect)
        # 不必再被缓存(在下面的循环中由"cmd.parent.needs_compositing"条件控制).
        # 树形结构中，缓存的结点与非缓存的结点是整个树的子树
        non_composited_commands = [
            cmd
            for cmd in all_commands
            if isinstance(cmd, PaintCommand) or not cmd.needs_compositing
            if not cmd.parent or cmd.parent.needs_compositing
        ]

        # "non_composited_commands"的结构大体为：
        #
        # [<transform no-op>, <draw text>, <draw rrect>, <transform no-op>, ...]
        #  -----------------  -------------------------  -----------------
        #        <div>                 <div>                   <div>
        #      no effect           opacity: 0.5              no effect
        #
        #

        # 根据cacheable commands创建layer. 具有相同parent的layer可合并为同一个layer
        # 对于上面注释中的display结构，将创建下面的layer:
        #
        # [display list]                                                       [draw list]
        #
        #     Blend                                                              Blend
        #      |                                                                  |
        #      +->Blend (opacity)        +--> layer                               +->Blend (opacity)
        #      |   |                     |      |                                 |   |
        #      |   +-->DrawRRect  ---+---+      +-->DrawRRect                     |   +--> layer
        #      |   |                 |          |                                 |          |
        #      |   +-->DrawText   ---+          +-->DrawText                      |          +-->DrawRRect
        #      |                                                                  |          |
        #      |                                                                  |          +-->DrawText
        #      +->Blend (no-op)  -----+------> layer                ------->      +-> layer
        #      |   |                  |          |                                      |
        #      |   +-->DrawRRect      |          +->Blend (no-op)                       +->Blend (no-op)
        #      |   |                  |          |   |                                  |   |
        #      |   +-->DrawText       |          |   +-->DrawRRect                      |   +-->DrawRRect
        #      |                      |          |   |                                  |   |
        #      +->Blend (no-op)  -----+          |   +-->DrawText                       |   +-->DrawText
        #          |                             |                                      |
        #          +-->DrawRRect                 +->Blend (no-op)                       +->Blend (no-op)
        #          |                                 |                                      |
        #          +-->DrawText                      +-->DrawRRect                          +-->DrawRRect
        #                                            |                                      |
        #                                            +-->DrawText                           +-->DrawText
        #
        for cmd in non_composited_commands:
            for layer in reversed(self.composited_layers):
                if layer.can_merge(cmd):
                    layer.add(cmd)
                    break
                elif Rect.Intersects(layer.absolute_bounds(), local_to_absolute(cmd, cmd.rect)):
                    #
                    # 在逆向遍历"composited_layers"的情况下，
                    # 如果command与前面的某一layer的绘制区域有交集,那么根据这个command新建一个layer.
                    # 避免该command与后面的循环中遇到的某个layer merge，而导致该command先于有交集的layer
                    # 绘制，产生视觉上的错误.
                    #
                    # 假设:
                    #
                    #      display list
                    #
                    #    Blend
                    #      |
                    #      +->Blend1 (no-op)
                    #      |   |
                    #      |   +->DrawText                           composited layers
                    #      |
                    #      |                                        [layer1,   layer2, ]
                    #      +->Blend2 (opacity: 0.5)    ----->          |         |
                    #      |   |                                       v         v
                    #      |   +->DrawRect                          [Blend1]  [DrawRect]
                    #      |
                    #      |
                    #      +->Blend3 (no-op)
                    #          |
                    #          +->DrawText
                    #
                    # 此时循环执行至'Blend3', 且Blend3与DrawRect的绘制区域有交集.
                    #
                    # 在反向遍历"composited layers"的情况下，
                    #   如果不考虑交集，那么Blend3将随后合并至Blend1所在的layer1中，绘制composited layers时，Blend3将先于DrawRect绘制，
                    #   可能导致视觉上的错误(例如不透明色的叠加等)。
                    #   如果考虑交集，那么Blend3遍历至layer2时判断有交集，那么Blend3将新建一个layer添加至composited layers中，绘制时
                    #   Blend3将后于DrawRect绘制，确保了正确的绘制顺序
                    #
                    layer = CompositedLayer(self.skia_context, cmd)
                    self.composited_layers.append(layer)
                    break

            else:
                # (仅当"for"结束循环且没有执行"break"时, 才会执行"else"代码段)
                #
                # 如果command与当前的每一个layer都不属于同一个parent,
                # 那么新建一个layer

                layer = CompositedLayer(self.skia_context, cmd)
                self.composited_layers.append(layer)

    # 用DrawCompositedLayer代替PaintCommand,
    # 并根据所有的"CompositedLayer"创建允许缓存绘制结果的display list("draw_list")
    # 一般情况下，只有VisualEffect command拥有子结点，PaintCommand没有子结点
    #
    # display list(tab):
    # Blend:
    #     Blend:
    #         DrawLine
    #         DrawText
    #
    # draw_list(tab):
    # Blend:
    #     Blend:
    #         DrawCompositedLayer(cacheable) --> DrawLine
    #         DrawCompositedLayer(cacheable) --> DrawText
    #
    def paint_draw_list(self):
        new_effects = {}  # 临时保存已经clone的parent
        self.draw_list = []

        for composited_layer in self.composited_layers:
            current_effect = DrawCompositedLayer(composited_layer)
            if not composited_layer.display_items:
                continue

            parent = composited_layer.display_items[0].parent  # 同一layer中的command属于同一parent
            while parent:
                new_parent = self.get_latest(parent)
                if new_parent in new_effects:
                    new_effects[new_parent].children.append(current_effect)
                    break
                else:
                    current_effect = new_parent.clone(current_effect)
                    new_effects[new_parent] = current_effect
                    parent = parent.parent

            if not parent:
                self.draw_list.append(current_effect)

        # 在Accessibility模式下，对光标悬停下的元素执行相关操作并绘制边框

        if self.pending_hover:
            x, y = self.pending_hover
            y += self.active_tab_scroll
            a11y_node = self.accessibility_tree.hit_test(x, y)

            if a11y_node:
                if not self.hovered_a11y_node or a11y_node.node != self.hovered_a11y_node:
                    self.hovered_a11y_node = a11y_node
                    self.needs_speak_hovered_node = True
            self.pending_hover = None

        if self.hovered_a11y_node:
            # 已找到光标悬停的accessibility node
            for bound in self.hovered_a11y_node.bounds:
                self.draw_list.append(DrawOutline(bound, "white" if self.dark_mode else "black", 2))

    def draw(self):
        canvas = self.root_surface.getCanvas()
        if self.dark_mode:
            canvas.clear(ColorBLACK)
        else:
            canvas.clear(ColorWHITE)

        # 将"draw_list"的内容绘制到"root surface"的canvas上
        tab_offset = self.chrome.bottom - self.active_tab_scroll
        canvas.save()
        canvas.translate(0, tab_offset)  # 绘制时tab页内容相对于chrome的偏移量
        for item in self.draw_list:
            item.execute(canvas)
        canvas.restore()

        # 将chrome_surface的内容绘制到"root surface"的canvas上
        chrome_rect = Rect.MakeLTRB(0, 0, const.WIDTH, self.chrome.bottom)
        canvas.save()
        canvas.clipRect(chrome_rect)  # canvas限制为chrome在root surface上的所在的区域
        self.chrome_surface.draw(canvas, 0, 0)
        canvas.restore()

        # 将最底层的surface中的数据通过GPU渲染至窗口中
        self.root_surface.flushAndSubmit()
        SDL_GL_SwapWindow(self.sdl_window)

    # 由browser eventloop调用，负责在canvas上重绘
    def composite_raster_and_draw(self):
        self.lock.acquire(blocking=True)

        if not self.needs_composite and not self.needs_raster and not self.needs_draw:
            self.lock.release()
            return

        self.measure.time("raster_draw")

        if self.rand_raster_and_draw:
            # 如果是从"browser.commit()"中发起的raster,那么添加一个"instant"事件

            self.measure.instant(
                "raster_draw_from_commit", cat="debug", args={"rand": self.rand_raster_and_draw}
            )
            self.rand_raster_and_draw = None

        if self.needs_composite:
            self.measure.time("composite")

            self.composite()
            self.needs_composite = False

            self.measure.stop("composite")

        if self.needs_raster:
            self.measure.time("raster")

            self.raster_chrome()
            self.raster_tab()
            self.needs_raster = False

            self.measure.stop("raster")

        if self.needs_accessibility:
            self.measure.time("accessibility")
            self.update_accessibility()
            self.measure.stop("accessibility")

        if self.needs_draw:
            self.measure.time("draw")

            self.paint_draw_list()
            self.draw()
            self.needs_draw = False

            self.measure.stop("draw")

        self.measure.stop("raster_draw")

        self.lock.release()

    def increment_zoom(self, increment):
        self.active_tab.task_runner.schedule_task(Task(self.active_tab.zoom_by, increment))

    def reset_zoom(self):
        self.active_tab.task_runner.schedule_task(Task(self.active_tab.reset_zoom))

    def handle_down(self):
        self.lock.acquire(blocking=True)

        if not self.active_tab_height:
            # 如果tab尚未调用"Browser.commit()"
            self.lock.release()
            return

        if self.root_frame_focused:
            # root frame当前拥有焦点的话，采用"threaded scroll"

            # 计算合理的滚动距离。滚动后不能超过tab中html document的顶部与底部.
            #
            # 这里实现了"threaded scroll": 在browser thread中直接更新"scroll". 在"mainloop"中，"composite & raster & draw"
            # 过程发生在"schedule animation frame"之前。 所以在scroll被同步至tab之前(通过animation frame同步)，browser已经
            # 通过"draw"完成了新scroll的重绘.
            self.active_tab_scroll = self.clamp_scroll(self.active_tab_scroll + const.SCROLL_STEP)
            self.set_needs_draw()
            self.needs_animation_frame = True
        else:
            # 如果其他frame拥有焦点，那么仅由tab负责scroll, browser不参与scroll流程

            task = Task(self.active_tab.scrolldown)
            self.active_tab.task_runner.schedule_task(task)

        self.lock.release()

    def handle_up(self):
        self.lock.acquire(blocking=True)

        if not self.active_tab_height:
            # 如果tab尚未调用"Browser.commit()"
            self.lock.release()
            return

        if self.root_frame_focused:
            # 计算合理的滚动距离。滚动后不能超过tab中html document的顶部与底部
            self.active_tab_scroll = self.clamp_scroll(self.active_tab_scroll - const.SCROLL_STEP)
            self.set_needs_draw()
            self.needs_animation_frame = True
        else:
            task = Task(self.active_tab.scrollup)
            self.active_tab.task_runner.schedule_task(task)

        self.lock.release()

    def handle_click(self, e):
        self.lock.acquire(blocking=True)

        tab_switched = None
        if e.y < self.chrome.bottom:
            # 点击位置位于chrome中

            if self.focus == "content":
                # 如果焦点已位于tab中，则先取消tab中的焦点
                self.active_tab.task_runner.schedule_task(Task(self.active_tab.blur))

            self.focus = None
            old_tab = self.active_tab
            self.chrome.click(e.x, e.y)

            tab_switched = old_tab != self.active_tab
        else:
            # 点击位置位于chrome下面的网页

            if self.focus is None:
                # 如果焦点已位于chrome中，则先取消chrome中的焦点
                self.chrome.blur()
                self.set_needs_raster()

            self.focus = "content"

            url = self.active_tab.url  # 保存点击前的url

            tab_y = e.y - self.chrome.bottom
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.click, e.x, tab_y))

        if tab_switched == True:
            # 如果切换了tab,切换后的tab需要触发一次"render -> raster"流程
            self.active_tab.set_needs_render_all_frames()
            # 切换tab之后，由于在"Chrome.click()"中重置了"active_tab_*"等变量，
            # 所以Browser需要tab通过"run_animation_frame"回传保存的滚动距离.
            self.active_tab.root_frame.scroll_changed_in_frame = True
            self.measure.instant("tab switched", cat="debug", args={"tab": self.active_tab.id})

            # 如果切换后恰好上一个tab设置了"needs_raster_and_draw", 那么取消该次raster
            self.needs_composite = self.needs_raster = self.needs_draw = False
        elif tab_switched == False:
            # 由于"mainloop"中"raster and draw"发生在"schedule animation frame"之前,
            # 此时"active_tab_*"的某些变量仍表示原来的tab，所以切换tab之后就不必再"raster and draw"
            self.set_needs_raster()

        # "tab_switched == None"表示点击位置在tab内，不需要考虑是否执行接下来最近的一次raster draw

        self.lock.release()

    def handle_key(self, char):
        self.lock.acquire(blocking=True)

        if len(char) == 0:
            self.lock.release()
            return
        if not (0x20 <= ord(char) <= 0x7F):
            self.lock.release()
            return

        # 如果chrome处理了<Key>事件，那么tab将不再继续处理,否则将<Key>事件发送至tab页处理
        if self.chrome.keypress(char):
            self.set_needs_raster()
        elif self.focus == "content":
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.keypress, char))
            self.set_needs_raster()

        self.lock.release()

    def handle_enter(self):
        self.lock.acquire(blocking=True)

        if self.chrome.enter():
            # 如果焦点位于chrome中
            self.set_needs_raster()
        elif self.focus == "content":
            # 如果当前焦点位于网页中
            task = Task(self.active_tab.enter)
            self.active_tab.task_runner.schedule_task(task)

        self.lock.release()

    # 按下tab时，将焦点设置在网页中，开始在网页中的focusable item中循环浏览
    def handle_tab(self):
        if not self.focus:
            # 如果焦点已经位于chrome中，则先取消这个焦点
            self.chrome.blur()

        self.focus = "content"
        task = Task(self.active_tab.advance_tab)
        self.active_tab.task_runner.schedule_task(task)

    def handle_backspace(self):
        self.lock.acquire(blocking=True)

        if self.chrome.backspace():
            self.set_needs_raster()
        elif self.focus == "content":
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.backspace))
            self.set_needs_raster()

        self.lock.release()

    def handle_hover(self, event):
        if not self.accessibility_is_on or not self.accessibility_tree:
            return
        self.pending_hover = (event.x, event.y - self.chrome.bottom)
        self.set_needs_accessibility()

    def handle_quit(self):
        # do not forget to release skia opengl backend!
        self.skia_context.flush()
        self.skia_context.submit()
        self.skia_context.abandonContext()

        # wait until GPU completes all commands
        OpenGL.GL.glFinish()

        # sdl opengl context
        SDL_GL_DeleteContext(self.gl_context)
        SDL_DestroyWindow(self.sdl_window)

        self.measure.finish()

        # 结束每个tab的eventloop
        for tab in self.tabs:
            tab.task_runner.set_needs_quit()
            tab.destroy()

    # 安排下一次重新计算layout的task.
    #
    # 注意：timer超时后仅是将"重新计算layout"的task添加至Tab eventloop中，而不是立刻执行，而task的实际执行时间点则与Queue的长度有关
    def schedule_animation_frame(self):
        self.lock.acquire(blocking=True)

        if self.needs_animation_frame and not self.animation_timer:
            # 生成一个随机数，该随机数标识着:
            # "创建Timer -> Timer超时并执行 -> 'tab.run_animation_frame' -> tab.commit -> raster and draw"
            # 的整体渲染重绘流程
            r = random.randint(0, 10000000)

            # 创建一个Timer,在"REFRESH_RATE_SEC"时长后超时并将"animation frame"添加至tab的eventloop中.
            #
            # 假设刷新率为30fps(即每0.033ms完成一次重绘). 在理想状态下，每隔0.033ms就将完成一次重绘。但是
            # 当前仅实现了每0.033ms"开始"一次重绘,而不是"完成"。而且重绘本身也需要时间，这就导致了在连续的animation
            # 渲染时，两次重绘"完成"的间隔将远大于0.033ms。在该情况下，如果在实现某些css animation（例如transition）
            # 时，先通过预定时长（总帧数 = 时长 / REFRESH_RATE_SEC）计算总帧数,然后连续地渲染每一帧（上一帧结束后立刻
            # schedule下一帧），那么总渲染时长将大大超出预定时长
            #
            #
            #           animation frame
            #                 |
            #      |          v  |             |           |
            # -----|--------|++++|--------|++++|-------|+++|------->
            #           ^                                       time
            #      ^    |        ^             ^
            #      | refresh     |             |
            #      |   gap       |             |
            #      |             |             |
            #      |-------------+-------------|
            #        whole render      next
            #          process        render
            #                        process
            #
            self.animation_timer = Timer(
                const.REFRESH_RATE_SEC, self.animation_frame_callback, [self.active_tab, r]
            )
            self.animation_timer.start()
            self.measure.instant(
                "timer start", cat="debug", args={"tab": self.active_tab.id, "rand": r}
            )

        self.lock.release()

    def animation_frame_callback(self, tab, rand):
        self.lock.acquire(blocking=True)

        if tab != self.active_tab:
            # 如果Timer启动时的tab与Timer超时执行时的tab不一致，则本次不会schedule,
            #
            # 当上一个tab的Timer（用于自身重绘）未超时的时候，这时切换tab,系统再次创建下一次的Timer(新tab的重绘).
            # 上一个tab的Timer会错误地将"run_animation_frame"添加至新tab的eventloop中。
            # 如果在这个"run_animation_frame"调用"commit"之前, 新tab的Timer超时并将又一个新的"run_animation_frame"添加至
            # 新tab的eventloop中，那么后一次的"frame"将会重置tab的"scroll"属性为0. 导致新tab渲染后的滚动距离为0
            #
            #                                                                                       will reset the "tab.scroll" to "0" !!
            #    old tab   tab     new tab
            #     Timer  switched   Timer                                   old tab scheduled                new tab scheduled
            #       |       |         |                                     "animation frame"                "animation frame"
            #       |       |         |                                +--------------------------+     +-------------------------+
            #       |       |         |                                |                          |     |                         |
            #       v       v         v                                v                          v     v                         v
            # ------+-------+---------+---------------+---------+------+-------------------+------+-----+-------------------------+-------------------
            #                                         ^         ^                          ^
            #                                         |         |                          |
            #                                         |         |                          |
            #                                         |         |                       old tab
            #                                      old tab   new tab                     commit
            #                                       Timer     Timer
            #                                      timeout   timeout
            #
            self.lock.release()
            return

        scroll = self.active_tab_scroll
        active_tab = self.active_tab
        task = Task(active_tab.run_animation_frame, scroll, rand)
        active_tab.task_runner.schedule_task(task)

        # 创建一个Timer发起的"schedule"的事件。由于Timer每次启动均新建thread,每次的thread id均不一致。因此
        # 这里记录事件时采用固定id方便日志分析
        self.measure.instant(
            "schedule",
            cat="debug",
            args={"tab": active_tab.id, "rand": rand},
            tid=const.SCHEDULE_ANIMATION_TIMER_TID,
        )

        self.needs_animation_frame = False

        self.lock.release()

    # browser中保存由tab计算layout后得到的绘制信息
    #
    # 该方法在tab的task runner eventloop中被调用,因此运行在与browser不同的线程中
    def commit(self, tab, data, rand):
        self.lock.acquire(blocking=True)

        if tab == self.active_tab:
            self.active_tab_url = data.url
            self.active_tab_scroll = data.scroll
            self.accessibility_tree = data.accessibility_tree
            self.tab_focus = data.focus
            self.root_frame_focused = data.root_frame_focused

            self.measure.instant(
                "commit", cat="debug", args={"tab": self.active_tab.id, "rand": rand}
            )
            self.active_tab_height = data.height
            if data.display_list:
                self.active_tab_display_list = data.display_list

            if data.composited_updates is None:
                # "render"时执行了"style"以及"layout"的过程, 相比上次的render，"paint"过程收集的
                # PaintCommand可能已经发生了变化，因此需要重新composite

                self.composited_updates = {}
                self.set_needs_composite()
            elif data.composited_updates:
                self.composited_updates = data.composited_updates
                self.set_needs_draw()
            # 当"data.composited_updates == {}"时，说明没有node更新animation,那么不需要重绘

            # 重置timer
            #
            # 仅当再次调用"commit"时才会重置timer, 避免browser的线程向tab eventloop添加过多的animation frame task
            self.animation_timer = None

            self.rand_raster_and_draw = rand

        self.lock.release()

    def get_latest(self, effect):
        node = effect.node
        if node not in self.composited_updates:
            return effect
        if not isinstance(effect, Blend):
            return effect

        return self.composited_updates[node]

    def clear_data(self):
        self.active_tab_scroll = 0
        self.active_tab_url = None
        self.active_tab_display_list = []
        self.draw_list = []
        self.composited_layers = []
        self.composited_updates = {}
        self.accessibility_tree = None

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode

        task = Task(self.active_tab.set_dark_mode, self.dark_mode)
        self.active_tab.task_runner.schedule_task(task)

    def toggle_accessibility(self):
        self.lock.acquire(blocking=True)
        self.accessibility_is_on = not self.accessibility_is_on
        self.set_needs_accessibility()
        self.lock.release()

    def update_accessibility(self):
        if not self.accessibility_tree:
            return

        if not self.has_spoken_document:
            self.speak_document()
            self.has_spoken_document = True

        # 根据新的"self.accessibility_tree"更新"self.spoken_alert"
        new_spoken_alerts = []
        for old_node in self.spoken_alerts:
            new_nodes = [
                node
                for node in tree_to_list(self.accessibility_tree, [])
                # 原"spoken_alerts"中的结点在新的"accessibility_tree"中依然存在, 保留这些结点.
                # 这里根据a11y node中的"node"属性值判断与DOM node对应关系
                if node.node == old_node.node and node.role == "alert"
            ]
            if new_nodes:
                new_spoken_alerts.append(new_nodes[0])
        self.spoken_alerts = new_spoken_alerts

        self.active_alerts = [
            node for node in tree_to_list(self.accessibility_tree, []) if node.role == "alert"
        ]
        for alert in self.active_alerts:
            if alert not in self.spoken_alerts:
                # 找到不在"spoken_alerts"中的"alert"a11y node, 并speak
                self.speak_node(alert, "New Alert: ")
                self.spoken_alerts.append(alert)

        if self.tab_focus and self.tab_focus != self.last_tab_focus:
            # 寻找当前tab焦点对应的a11y的结点
            nodes = [
                node
                for node in tree_to_list(self.accessibility_tree, [])
                if node.node == self.tab_focus
            ]
            if nodes:
                self.focus_a11y_node = nodes[0]
                self.speak_node(self.focus_a11y_node, "element focused: ")
            self.last_tab_focus = self.tab_focus

        if self.needs_speak_hovered_node:
            self.speak_node(self.hovered_a11y_node, "Hit test: ")
        self.needs_speak_hovered_node = False

    def speak_document(self):
        text = "Here are the document contents:"
        tree_list = tree_to_list(self.accessibility_tree, [])
        for accessibility_node in tree_list:
            new_text = accessibility_node.text
            if new_text:
                text += f"\n{new_text}"
        speak_text(text)

    # 将 a11y "node" 打印出来.
    # "node": a11y tree中的node
    def speak_node(self, node, text):
        text += node.text
        if text and node.children and node.children[0].role == "StaticText":
            text += f" {node.children[0].text}"

        if text:
            speak_text(text)

    def focus_addressbar(self):
        self.lock.acquire(blocking=True)
        self.focus = None
        self.chrome.focus_addressbar()
        self.set_needs_raster()
        self.lock.release()

    def cycle_tabs(self):
        self.lock.acquire(blocking=True)
        active_idx = self.tabs.index(self.active_tab)
        new_active_idx = (active_idx + 1) % len(self.tabs)
        self.set_active_tab(self.tabs[new_active_idx])
        self.lock.release()

    def go_back(self):
        self.active_tab.task_runner.schedule_task(Task(self.active_tab.go_back))


def mainloop(browser):
    event = SDL_Event()
    dog = Watchdog(5)

    ctrl_down = False
    # 使用SDL GUI框架需要用户自己轮询并捕获事件
    while True:
        if SDL_PollEvent(ctypes.byref(event)) != 0:
            # 轮询系统事件并捕获处理

            if event.type == SDL_QUIT:
                # 关闭所有窗口

                browser.handle_quit()
                dog.dismiss()
                SDL_Quit()
                sys.exit()

            elif event.type == SDL_MOUSEBUTTONUP:
                # 鼠标点击事件
                browser.handle_click(event.button)

            elif event.type == SDL_KEYDOWN:
                # 键盘事件

                if ctrl_down:
                    # ctrl的组合快捷键
                    handle_ctrl(event, browser, dog)

                elif event.key.keysym.sym == SDLK_RETURN:
                    # 回车
                    browser.handle_enter()
                elif event.key.keysym.sym == SDLK_TAB:
                    # tab
                    browser.handle_tab()
                elif event.key.keysym.sym == SDLK_BACKSPACE:
                    # 按下"Backspace"
                    browser.handle_backspace()
                elif event.key.keysym.sym == SDLK_DOWN:
                    # 按下向下按键
                    browser.handle_down()
                elif event.key.keysym.sym == SDLK_UP:
                    # 按下向上按键
                    browser.handle_up()
                elif event.key.keysym.sym == SDLK_RCTRL or event.key.keysym.sym == SDLK_LCTRL:
                    # 按下ctrl键
                    ctrl_down = True

            elif event.type == SDL_KEYUP:
                if event.key.keysym.sym == SDLK_RCTRL or event.key.keysym.sym == SDLK_LCTRL:
                    # 松开ctrl键
                    ctrl_down = False

            elif event.type == SDL_TEXTINPUT:
                # 文字输入事件
                browser.handle_key(event.text.text.decode("utf8"))

            elif event.type == SDL_MOUSEMOTION:
                browser.handle_hover(event.motion)

        # 在canvas上重绘
        browser.composite_raster_and_draw()

        # 安排下一次的重新布局（仅重新计算layout, 不在canvas上面绘制）
        browser.schedule_animation_frame()

        dog.feed()


def init_sdl_skia_opengl(browser):
    # 根据计算机的端序初始化surface基础颜色信息
    if SDL_BYTEORDER == SDL_BIG_ENDIAN:
        browser.RED_MASK = 0xFF000000
        browser.GREEN_MASK = 0x00FF0000
        browser.BLUE_MASK = 0x0000FF00
        browser.ALPHA_MASK = 0x000000FF
    else:
        browser.RED_MASK = 0x000000FF
        browser.GREEN_MASK = 0x0000FF00
        browser.BLUE_MASK = 0x00FF0000
        browser.ALPHA_MASK = 0xFF000000

    # 浏览器的窗口，负责接收系统事件、展示其他sdl surface的绘制结果, 该窗口通过GPU渲染
    browser.sdl_window = SDL_CreateWindow(
        b"Browser",
        SDL_WINDOWPOS_CENTERED,
        SDL_WINDOWPOS_CENTERED,
        const.WIDTH,
        const.HEIGHT,
        SDL_WINDOW_SHOWN | SDL_WINDOW_OPENGL,
    )

    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 2)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, True)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE)

    # 创建OpenGL context, 准备通过GPU渲染
    browser.gl_context = SDL_GL_CreateContext(browser.sdl_window)
    print(
        f"** OpenGL initialized: vendor={OpenGL.GL.glGetString(OpenGL.GL.GL_VENDOR)}, render={OpenGL.GL.glGetString(OpenGL.GL.GL_RENDERER)} **"
    )
    print()

    # 创建基于GPU渲染的Skia context, 后续创建的skia Surface均可利用GPU绘制
    browser.skia_context = GrDirectContext.MakeGL()


def add_parent_pointers(nodes, parent=None):
    for node in nodes:
        node.parent = parent
        add_parent_pointers(node.children, node)


def handle_ctrl(event, browser, dog):
    if event.key.keysym.sym == SDLK_EQUALS:
        # "ctrl_="放大页面
        browser.increment_zoom(True)
    elif event.key.keysym.sym == SDLK_MINUS:
        # "ctrl_-"缩小页面
        browser.increment_zoom(False)
    elif event.key.keysym.sym == SDLK_0:
        # "ctrl_0"重置页面缩放
        browser.reset_zoom()
    elif event.key.keysym.sym == SDLK_d:
        # "ctrl_d"深色/浅色主题切换
        browser.toggle_dark_mode()
    elif event.key.keysym.sym == SDLK_LEFT:
        # "ctrl_<"返回上一个网页
        browser.go_back()
    elif event.key.keysym.sym == SDLK_l:
        # "ctrl_l"地址栏获取焦点
        browser.focus_addressbar()
    elif event.key.keysym.sym == SDLK_t:
        # "ctrl_t"新建tab页
        browser.new_tab(URL(const.HTTP_URL))
    elif event.key.keysym.sym == SDLK_TAB:
        # "ctrl_tab"切换tab页
        browser.cycle_tabs()
    elif event.key.keysym.sym == SDLK_q:
        # "ctrl_q"退出浏览器
        browser.handle_quit()
        dog.dismiss()
        SDL_Quit()
        sys.exit()
    elif event.key.keysym.sym == SDLK_a:
        browser.toggle_accessibility()


# keep this being the last statement
main()

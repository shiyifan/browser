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
from utils import tree_to_list
from commands import PaintCommand, DrawCompositedLayer, Blend
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

        self.tab_surface = None

        # 点击之后焦点位于chrome中还是tab页中
        # None表示位于chrome,"content"表示位于tab中
        self.focus = None

        # 用于计算layout的timer. 注意：timer超时后仅计算layout(即调用'tab.render()')，不会在canvas中绘制
        self.animation_timer = None

        # 是否需要在canvas中重新绘制
        # self.needs_composite_raster_and_draw = False

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
        self.active_tab_scroll = 0  # "Tab.render()"时采用的滚动距离
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

    def set_needs_composite(self):
        self.needs_composite = True
        self.needs_raster = True
        self.needs_draw = True

    def set_needs_raster(self):
        self.needs_raster = True
        self.needs_draw = True

    def set_needs_draw(self):
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

    def clamp_scroll(self, scroll):
        height = self.active_tab_height + 2 * const.VSTEP  # 需要包含上下空白边距
        # 最大可以向下滚动的距离
        maxscroll = height - (const.HEIGHT - self.chrome.bottom)

        return max(0, min(scroll, maxscroll))

    def set_needs_raster_and_draw(self):
        self.lock.acquire(blocking=True)
        self.needs_composite_raster_and_draw = True
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
        self.schedule_load(url)

    def schedule_load(self, url, body=None):
        self.active_tab.task_runner.clear_pending_tasks()
        task = Task(self.active_tab.load, url, body)
        self.active_tab.task_runner.schedule_task(task)

    def raster_tab(self):
        """根据tab页'layout()'之后得到的display list, 在tab canvas中清空并重新绘制tab内容"""

        for composited_layer in self.composited_layers:
            composited_layer.raster()

    def raster_chrome(self):
        """在chrome canvas上清空并重新绘制chrome"""

        canvas = self.chrome_surface.getCanvas()
        canvas.clear(ColorWHITE)

        # 绘制browser chrome
        for cmd in self.chrome.paint():
            # 绘制时滚动距离scroll=0，确保chrome始终位于canvas上方
            cmd.execute(canvas)

    # 提取display list中所有的PaintCommand, 并根据每一个PaintCommand创建"CompositedLayer"以便于缓存绘制结果
    def composite(self):
        self.composited_layers = []

        # 创建display list中command间的父级关系，便于创建包含"DrawCompositedLayer"command的display list
        add_parent_pointers(self.active_tab_display_list)

        all_commands = []
        for cmd in self.active_tab_display_list:
            all_commands = tree_to_list(cmd, all_commands)
        paint_commands = [cmd for cmd in all_commands if isinstance(cmd, PaintCommand)]

        for cmd in paint_commands:
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

            parent = composited_layer.display_items[0].parent
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

    def draw(self):
        canvas = self.root_surface.getCanvas()
        canvas.clear(ColorWHITE)

        # 将tab_surface的内容绘制到"root surface"的canvas上
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

        # if not self.needs_composite_raster_and_draw:
        #     self.lock.release()
        #     return

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

        if self.needs_draw:
            self.measure.time("draw")

            self.paint_draw_list()
            self.draw()
            self.needs_draw = False

            self.measure.stop("draw")

        self.measure.stop("raster_draw")

        self.lock.release()

    def handle_down(self):
        self.lock.acquire(blocking=True)

        if not self.active_tab_height:
            # 如果tab尚未调用"Browser.commit()"
            self.lock.release()
            return

        # 计算合理的滚动距离。滚动后不能超过tab中html document的顶部与底部
        self.active_tab_scroll = self.clamp_scroll(self.active_tab_scroll + const.SCROLL_STEP)
        self.set_needs_draw()
        self.needs_animation_frame = True

        self.lock.release()

    def handle_up(self):
        self.lock.acquire(blocking=True)

        if not self.active_tab_height:
            # 如果tab尚未调用"Browser.commit()"
            self.lock.release()
            return

        # 计算合理的滚动距离。滚动后不能超过tab中html document的顶部与底部
        self.active_tab_scroll = self.clamp_scroll(self.active_tab_scroll - const.SCROLL_STEP)
        self.set_needs_draw()
        self.needs_animation_frame = True

        self.lock.release()

    def handle_click(self, e):
        self.lock.acquire(blocking=True)

        tab_switched = None
        if e.y < self.chrome.bottom:
            # 点击位置位于chrome中

            self.focus = None
            old_tab = self.active_tab
            self.chrome.click(e.x, e.y)

            tab_switched = old_tab != self.active_tab
        else:
            # 点击位置位于chrome下面的网页

            self.focus = "content"
            self.chrome.blur()

            url = self.active_tab.url  # 保存点击前的url

            tab_y = e.y - self.chrome.bottom
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.click, e.x, tab_y))

        if tab_switched == True:
            # 如果切换了tab,切换后的tab需要触发一次"render -> raster"流程
            self.active_tab.set_needs_render()
            # 切换tab之后，由于在"Chrome.click()"中重置了"active_tab_*"等变量，
            # 所以Browser需要tab通过"run_animation_frame"回传保存的滚动距离.
            self.active_tab.scroll_changed_in_tab = True
            self.measure.instant("tab switched", cat="debug", args={"tab": self.active_tab.id})

            # 如果切换后恰好上一个tab设置了"needs_raster_and_draw", 那么取消该次raster
            # self.needs_composite_raster_and_draw = False
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
            self.set_needs_raster()

        self.lock.release()

    def handle_backspace(self):
        self.lock.acquire(blocking=True)

        if self.chrome.backspace():
            self.set_needs_raster()
        elif self.focus == "content":
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.backspace))
            self.set_needs_raster()

        self.lock.release()

    def handle_quit(self):
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
        def callback(tab, rand):
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
            self.animation_timer = Timer(const.REFRESH_RATE_SEC, callback, [self.active_tab, r])
            self.animation_timer.start()
            self.measure.instant(
                "timer start", cat="debug", args={"tab": self.active_tab.id, "rand": r}
            )

        self.lock.release()

    # browser中保存由tab计算layout后得到的绘制信息
    #
    # 该方法在tab的task runner eventloop中被调用,因此运行在与browser不同的线程中
    def commit(self, tab, data, rand):
        self.lock.acquire(blocking=True)

        if tab == self.active_tab:
            self.active_tab_url = data.url
            self.active_tab_scroll = data.scroll
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

        # blend_ops = self.composited_updates[node]
        # for old_op, new_op in blend_ops:
        #     if old_op == effect:
        #         return new_op

        # return effect

        # for (node, old_op, new_op) in self.composited_updates:
        #     if node == effect.node and old_op == effect:
        #         return new_op

        # if node not in self.composited_updates:
        #     return effect

        return self.composited_updates[node][0][1]

    def clear_data(self):
        self.active_tab_scroll = 0
        self.active_tab_url = None
        self.active_tab_display_list = []
        self.draw_list = []
        self.composited_layers = []
        self.composited_updates = {}


def mainloop(browser):
    event = SDL_Event()
    dog = Watchdog(5)

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

                if event.key.keysym.sym == SDLK_RETURN:
                    # 回车
                    browser.handle_enter()
                elif event.key.keysym.sym == SDLK_BACKSPACE:
                    # 按下"Backspace"
                    browser.handle_backspace()
                elif event.key.keysym.sym == SDLK_DOWN:
                    # 按下向下按键
                    browser.handle_down()
                elif event.key.keysym.sym == SDLK_UP:
                    # 按下向上按键
                    browser.handle_up()

            elif event.type == SDL_TEXTINPUT:
                # 文字输入事件
                browser.handle_key(event.text.text.decode("utf8"))

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


# keep this being the last statement
main()

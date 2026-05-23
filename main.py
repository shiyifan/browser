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

        # 根据计算机的端序初始化surface基础颜色信息
        if SDL_BYTEORDER == SDL_BIG_ENDIAN:
            self.RED_MASK = 0xFF000000
            self.GREEN_MASK = 0x00FF0000
            self.BLUE_MASK = 0x0000FF00
            self.ALPHA_MASK = 0x000000FF
        else:
            self.RED_MASK = 0x000000FF
            self.GREEN_MASK = 0x0000FF00
            self.BLUE_MASK = 0x00FF0000
            self.ALPHA_MASK = 0xFF000000

        # 浏览器的窗口，负责接收系统事件、展示其他sdl surface的绘制结果
        self.sdl_window = SDL_CreateWindow(
            b"Browser",
            SDL_WINDOWPOS_CENTERED,
            SDL_WINDOWPOS_CENTERED,
            const.WIDTH,
            const.HEIGHT,
            SDL_WINDOW_SHOWN,
        )

        # 用于初步绘制的skia surface
        self.root_surface = Surface.MakeRaster(
            ImageInfo.Make(
                const.WIDTH,
                const.HEIGHT,
                ct=kRGBA_8888_ColorType,
                at=kUnpremul_AlphaType,
            )
        )

        self.chrome = Chrome(self)

        # 用于绘制chrome以及tab页内容的skia surface
        #
        # 分别创建两者的surface可以减少不必要的绘制过程（tab更新后，chrome不必重绘，chrome更新后，tab不必重绘）。
        # 被减少的"绘制过程"具体指"通过canvas对象在surface上绘制图形", 而每次渲染时仍需要将两者的surface中的数据一同复制到
        # root surface中.
        self.chrome_surface = Surface(const.WIDTH, math.ceil(self.chrome.bottom))
        self.tab_surface = None

        # 点击之后焦点位于chrome中还是tab页中
        # None表示位于chrome,"content"表示位于tab中
        self.focus = None

        # 用于计算layout的timer. 注意：timer超时后仅计算layout(即调用'tab.render()')，不会在canvas中绘制
        self.animation_timer = None

        # 是否需要在canvas中重新绘制
        self.needs_raster_and_draw = False

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

    # 设置当前active tab
    #
    # 这里重置了一些“active_tab_*”变量，没有直接从切换后的tab中获取这些变量值.
    # 反而将赋值委托给下一次的"schedule animation task", 并由tab调用"Browser.commit()"实现
    def set_active_tab(self, tab):
        self.active_tab = tab
        self.active_tab_scroll = 0
        self.active_tab_url = None
        self.needs_animation_frame = True
        self.animation_timer = None

    def clamp_scroll(self, scroll):
        height = self.active_tab_height + 2 * const.VSTEP  # 需要包含上下空白边距
        # 最大可以向下滚动的距离
        maxscroll = height - (const.HEIGHT - self.chrome.bottom)

        return max(0, min(scroll, maxscroll))

    def set_needs_raster_and_draw(self):
        self.lock.acquire(blocking=True)
        self.needs_raster_and_draw = True
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

        # 获取tab页内容的高度
        #
        # 这里的高度根据layout tree计算得到。
        # 对于某些超出parent元素边界的HTML元素，目前浏览器不支持绘制这样的元素.
        #
        # 另外，这里的高度不仅包含DOM元素总体占据的高度(active_tab_height), 而且包含了
        # 在DOM上、下额外多出的空白(2 * const.VSTEP) (另见DocumentLayout.layout())
        tab_height = math.ceil(self.active_tab_height + 2 * const.VSTEP)

        if not self.tab_surface or tab_height != self.tab_surface.height():
            # 如果tab_surface未初始化或者tab页高度发生变化，则新建一个surface.
            #
            # 该surface不仅包含DOM元素总体，而且也包含DOM总体的四周空白边距(另见DocumentLayout.layout())
            self.tab_surface = Surface(const.WIDTH, tab_height)

        canvas = self.tab_surface.getCanvas()
        canvas.clear(ColorWHITE)

        # 绘制tab页内容.
        #
        # 注意，在browser thread中rastser, 在tab main thread中render. 所以此处没有将
        # "draw()"添加到tab的eventloop中
        self.active_tab.draw(canvas, self.active_tab_display_list)

    def raster_chrome(self):
        """在chrome canvas上清空并重新绘制chrome"""

        canvas = self.chrome_surface.getCanvas()
        canvas.clear(ColorWHITE)

        # 绘制browser chrome
        for cmd in self.chrome.paint():
            # 绘制时滚动距离scroll=0，确保chrome始终位于canvas上方
            cmd.execute(canvas)

    def draw(self):
        canvas = self.root_surface.getCanvas()
        canvas.clear(ColorWHITE)

        # 将tab_surface的内容绘制到"root surface"的canvas上
        tab_rect = Rect.MakeLTRB(0, self.chrome.bottom, const.WIDTH, const.HEIGHT)
        tab_offset = self.chrome.bottom - self.active_tab_scroll
        canvas.save()
        canvas.clipRect(tab_rect)  # canvas限制为tab页内容在root surface上的所在的区域
        canvas.translate(0, tab_offset)  # 绘制时tab页内容相对于chrome的偏移量
        self.tab_surface.draw(canvas, 0, 0)
        canvas.restore()

        # 将chrome_surface的内容绘制到"root surface"的canvas上
        chrome_rect = Rect.MakeLTRB(0, 0, const.WIDTH, self.chrome.bottom)
        canvas.save()
        canvas.clipRect(chrome_rect)  # canvas限制为chrome在root surface上的所在的区域
        self.chrome_surface.draw(canvas, 0, 0)
        canvas.restore()

        # 将skia的绘制结果复制至sdl window中

        skia_image = self.root_surface.makeImageSnapshot()
        skia_bytes = skia_image.tobytes()
        depth = 32
        pitch = 4 * const.WIDTH

        # 从初步绘制的skia surface新建sdl surface
        sdl_surface = SDL_CreateRGBSurfaceFrom(
            skia_bytes,
            const.WIDTH,
            const.HEIGHT,
            depth,
            pitch,
            self.RED_MASK,
            self.GREEN_MASK,
            self.BLUE_MASK,
            self.ALPHA_MASK,
        )

        # 将新建的sdl surface绘制至窗口中
        rect = SDL_Rect(0, 0, const.WIDTH, const.HEIGHT)
        window_surface = SDL_GetWindowSurface(self.sdl_window)
        SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
        SDL_UpdateWindowSurface(self.sdl_window)

    # 由browser eventloop调用，负责在canvas上重绘
    def raster_and_draw(self):
        self.lock.acquire(blocking=True)

        if not self.needs_raster_and_draw:
            self.lock.release()
            return

        self.measure.time("raster_draw")

        if self.rand_raster_and_draw:
            # 如果是从"browser.commit()"中发起的raster,那么添加一个"instant"事件
            self.measure.instant(
                "raster_draw_from_commit", cat="debug", args={"rand": self.rand_raster_and_draw}
            )
            self.rand_raster_and_draw = None

        self.raster_chrome()
        self.raster_tab()
        self.draw()

        self.needs_raster_and_draw = False

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
        self.set_needs_raster_and_draw()
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
        self.set_needs_raster_and_draw()
        self.needs_animation_frame = True

        self.lock.release()

    def handle_click(self, e):
        self.lock.acquire(blocking=True)

        tab_switched = False
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

        if tab_switched:
            # 如果切换了tab,切换后的tab需要触发一次"render -> raster"流程
            self.active_tab.set_needs_render()
            # 切换tab之后，由于在"Chrome.click()"中重置了"active_tab_*"等变量，
            # 所以Browser需要tab通过"run_animation_frame"回传保存的滚动距离.
            self.active_tab.scroll_changed_in_tab = True
            self.measure.instant("tab switched", cat="debug", args={"tab": self.active_tab.id})

            # 如果切换后恰好上一个tab设置了"needs_raster_and_draw", 那么取消该次raster
            self.needs_raster_and_draw = False
        else:
            # 由于"mainloop"中"raster and draw"发生在"schedule animation frame"之前,
            # 此时"active_tab_*"的某些变量仍表示原来的tab，所以切换tab之后就不必再"raster and draw"
            self.set_needs_raster_and_draw()

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
            self.set_needs_raster_and_draw()
        elif self.focus == "content":
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.keypress, char))
            self.set_needs_raster_and_draw()

        self.lock.release()

    def handle_enter(self):
        self.lock.acquire(blocking=True)

        if self.chrome.enter():
            self.set_needs_raster_and_draw()

        self.lock.release()

    def handle_backspace(self):
        self.lock.acquire(blocking=True)

        if self.chrome.backspace():
            self.set_needs_raster_and_draw()
        elif self.focus == "content":
            self.active_tab.task_runner.schedule_task(Task(self.active_tab.backspace))
            self.set_needs_raster_and_draw()

        self.lock.release()

    def handle_quit(self):
        SDL_DestroyWindow(self.sdl_window)
        self.measure.finish()

        # 结束每个tab的eventloop
        for tab in self.tabs:
            tab.task_runner.set_needs_quit()

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
                "schedule", cat="debug", args={"tab": active_tab.id, "rand": rand}, tid=9999999
            )

            self.needs_animation_frame = False

            self.lock.release()

        self.lock.acquire(blocking=True)

        if self.needs_animation_frame and not self.animation_timer:
            # 生成一个随机数，该随机数标识着:
            # "创建Timer -> Timer超时并执行 -> 'tab.run_animation_frame' -> tab.commit -> raster and draw"
            # 的整体渲染重绘流程
            r = random.randint(0, 10000000)

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

            # 重置timer
            #
            # 仅当再次调用"commit"时才会重置timer, 避免browser的线程向tab eventloop添加过多的animation frame task
            self.animation_timer = None

            self.set_needs_raster_and_draw()
            self.rand_raster_and_draw = rand

        self.lock.release()


# 输出DOM Tree结构
def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


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
        browser.raster_and_draw()

        # 安排下一次的重新布局（仅重新计算layout, 不在canvas上面绘制）
        browser.schedule_animation_frame()

        dog.feed()


# keep this being the last statement
main()

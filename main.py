import ctypes
from sdl2 import *
from skia import *
import const
from chrome import Chrome
from tab import Tab
from url import URL
import math
from task import Task
from threading import Timer
from measure import MeasureTime


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

        # 是否安排下一次的页面绘制的task
        self.needs_animation_frame = True

        self.measure = MeasureTime()

    def set_needs_raster_and_draw(self):
        self.needs_raster_and_draw = True

    def set_needs_animation_frame(self, tab):
        if tab == self.active_tab:
            self.needs_animation_frame = True

    # 新建一个tab并设置为当前显示的tab
    def new_tab(self, url):
        new_tab = Tab(self, const.HEIGHT - self.chrome.bottom)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)

        self.set_needs_raster_and_draw()

    def raster_tab(self):
        """根据tab页'layout()'之后得到的display list, 在tab canvas中清空并重新绘制tab内容"""

        # 获取tab页内容的高度
        #
        # 这里的高度根据layout tree计算得到。
        # 对于某些超出parent元素边界的HTML元素，目前浏览器不支持绘制这样的元素
        tab_height = math.ceil(self.active_tab.document.height + 2 * const.VSTEP)

        if not self.tab_surface or tab_height != self.tab_surface.height():
            # 如果tab_surface未初始化或者tab页高度发生变化，则新建一个surface
            self.tab_surface = Surface(const.WIDTH, tab_height)

        canvas = self.tab_surface.getCanvas()
        canvas.clear(ColorWHITE)

        # 绘制tab页内容
        self.active_tab.draw(canvas)

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
        tab_offset = self.chrome.bottom - self.active_tab.scroll
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

    # 由event loop调用，负责在canvas上重绘
    def raster_and_draw(self):
        if not self.needs_raster_and_draw:
            return
        
        self.measure.time('raster_draw')

        self.raster_chrome()
        self.raster_tab()
        self.draw()

        self.needs_raster_and_draw = False

        self.measure.stop('raster_draw')

    def handle_down(self):
        self.active_tab.scrolldown()

        # 滚动时，由于页面内容不变，因此不需要再次raster tab页内容
        self.draw()

    def handle_up(self):
        self.active_tab.scrollup()

        # 同"handle_down"
        self.draw()

    def handle_click(self, e):
        if e.y < self.chrome.bottom:
            # 点击位置位于chrome中
            self.focus = None
            old_tab = self.active_tab
            self.chrome.click(e.x, e.y)
        else:
            # 点击位置位于chrome下面的网页
            self.focus = "content"
            self.chrome.blur()

            url = self.active_tab.url  # 保存点击前的url

            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)

        if old_tab != self.active_tab:
            # 如果切换了tab,那么还需要安排下一次页面绘制的task
            self.set_needs_animation_frame(self.active_tab)

        self.set_needs_raster_and_draw()

    def handle_key(self, char):
        if len(char) == 0:
            return
        if not (0x20 <= ord(char) <= 0x7F):
            return

        # 如果chrome处理了<Key>事件，那么tab将不再继续处理,否则将<Key>事件发送至tab页处理
        if self.chrome.keypress(char):
            self.set_needs_raster_and_draw()
        elif self.focus == "content":
            self.active_tab.keypress(char)
            self.set_needs_raster_and_draw()

    def handle_enter(self):
        if self.chrome.enter():
            self.set_needs_raster_and_draw()

    def handle_backspace(self):
        if self.chrome.backspace():
            self.set_needs_raster_and_draw()
        elif self.focus == "content":
            self.active_tab.backspace()
            self.set_needs_raster_and_draw()

    def handle_quit(self):
        SDL_DestroyWindow(self.sdl_window)
        self.measure.finish()

    # 安排下一次重新计算layout的task.
    #
    # 注意：timer超时后仅是将"重新计算layout"的task添加至Queue中，而不是立刻执行，而task的实际执行时间点则与Queue的长度有关
    def schedule_animation_frame(self):
        def callback():
            active_tab = self.active_tab
            task = Task(active_tab.render)
            active_tab.task_runner.schedule_task(task)
            self.animation_timer = None

        if self.needs_animation_frame and not self.animation_timer:
            self.animation_timer = Timer(const.REFRESH_RATE_SEC, callback)
            self.animation_timer.start()
            self.needs_animation_frame = False


# 输出DOM Tree结构
def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


def mainloop(browser):
    event = SDL_Event()

    # 使用SDL GUI框架需要用户自己轮询并捕获事件
    while True:
        if SDL_PollEvent(ctypes.byref(event)) != 0:
            # 轮询系统事件并捕获处理

            if event.type == SDL_QUIT:
                # 关闭所有窗口

                browser.handle_quit()
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

        # 系统事件处理完成后，执行tab页保存的task
        browser.active_tab.task_runner.run()

        # 在canvas上重绘
        browser.raster_and_draw()

        # 安排下一次的重新布局（仅重新计算layout, 不在canvas上面绘制）
        browser.schedule_animation_frame()


# keep this being the last statement
main()

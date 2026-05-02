import ctypes
from sdl2 import *
from skia import *
import const
from chrome import Chrome
from tab import Tab
from url import URL


def main():
    SDL_Init(SDL_INIT_EVENTS)
    browser = Browser()
    browser.new_tab(URL(const.HTTP_URL))
    mainloop(browser)


# 带有标签页功能的浏览器
# 负责管理窗口以及canvas，响应用户操作事件
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

        # self.window = tkinter.Tk()
        # self.canvas = tkinter.Canvas(
        #     self.window,
        #     width=const.WIDTH,
        #     height=const.HEIGHT,
        #     bg="white",
        # )
        # self.canvas.pack(fill=tkinter.BOTH, expand=1)  # 让canvas填充window的空间

        # self.window.bind("<Down>", self.handle_down)
        # self.window.bind("<Up>", self.handle_up)
        # self.window.bind("<Configure>", self.recfg)  # 当窗口大小更新时，重新布局
        # self.window.bind("<Button-1>", self.handle_click)
        # self.window.bind("<Key>", self.handle_key)  # 地址栏内输入url
        # self.window.bind("<Return>", self.handle_enter)  # 地址栏内按下回车后加载新url
        # self.window.bind("<BackSpace>", self.handle_backspace)

        self.chrome = Chrome(self)

        # 点击之后焦点位于chrome中还是tab页中
        # None表示位于chrome,"content"表示位于tab中
        self.focus = None

        # 将初始窗口在屏幕上居中
        # center(self.window)

    # 新建一个tab并设置为当前显示的tab
    def new_tab(self, url):
        new_tab = Tab(const.HEIGHT - self.chrome.bottom)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)
        self.draw()

    def draw(self):
        canvas = self.root_surface.getCanvas()

        self.active_tab.draw(canvas, self.chrome.bottom)

        # 绘制browser chrome
        for cmd in self.chrome.paint():
            # 绘制时滚动距离scroll=0，确保chrome始终位于canvas上方
            cmd.execute(0, canvas)

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

    def handle_down(self):
        self.active_tab.scrolldown()
        self.draw()

    def handle_up(self):
        self.active_tab.scrollup()
        self.draw()

    def handle_click(self, e):
        if e.y < self.chrome.bottom:
            # 点击位置位于chrome中
            self.focus = None
            self.chrome.click(e.x, e.y)
        else:
            # 点击位置位于chrome下面的网页
            self.focus = "content"
            self.chrome.blur()
            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)
        self.draw()

    def handle_key(self, char):
        if len(char) == 0:
            return
        if not (0x20 <= ord(char) <= 0x7F):
            return

        # 如果chrome处理了<Key>事件，那么tab将不再继续处理,否则将<Key>事件发送至tab页处理
        if self.chrome.keypress(char):
            self.draw()
        elif self.focus == "content":
            self.active_tab.keypress(char)
            self.draw()

    def handle_enter(self):
        self.chrome.enter()
        self.draw()

    def handle_backspace(self, e):
        if self.chrome.backspace():
            self.draw()
        elif self.focus == "content":
            self.active_tab.backspace()
            self.draw()

    def recfg(self, e):
        if const.WIDTH == e.width and const.HEIGHT == e.height:
            return
        const.WIDTH = e.width
        const.HEIGHT = e.height

        if self.active_tab:
            self.active_tab.reconfigure()
            self.draw()

    def handle_quit(self):
        SDL_DestroyWindow(self.sdl_window)


# 居中初始窗口
def center(window):
    window.update_idletasks()
    w = window.winfo_width()
    h = window.winfo_height()
    scr_w = window.winfo_screenwidth()
    scr_h = window.winfo_screenheight()
    x = (scr_w - w) // 2
    y = (scr_h - h) // 2
    window.geometry(f"+{x}+{y}")


# 输出DOM Tree结构
def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


def mainloop(browser):
    event = SDL_Event()
    while True:
        while SDL_PollEvent(ctypes.byref(event)) != 0:
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
                elif event.key.keysym.sym == SDLK_DOWN:
                    browser.handle_down()
                elif event.key.keysym.sym == SDLK_UP:
                    browser.handle_up()

            elif event.type == SDL_TEXTINPUT:
                # 文字输入事件
                browser.handle_key(event.text.text.decode("utf8"))


# keep this being the last statement
main()

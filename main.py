import tkinter
import const
from chrome import Chrome
from tab import Tab
from url import URL


def main():
    Browser().new_tab(URL(const.HTTP_URL))
    tkinter.mainloop()


# 带有标签页功能的浏览器
# 负责管理窗口以及canvas，响应用户操作事件
class Browser:
    def __init__(self):
        self.tabs = []
        self.active_tab = None

        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=const.WIDTH,
            height=const.HEIGHT,
            bg="white",
        )
        self.canvas.pack(fill=tkinter.BOTH, expand=1)  # 让canvas填充window的空间

        self.window.bind("<Down>", self.handle_down)
        self.window.bind("<Up>", self.handle_up)
        self.window.bind("<Configure>", self.recfg)  # 当窗口大小更新时，重新布局
        self.window.bind("<Button-1>", self.handle_click)
        self.window.bind("<Key>", self.handle_key)  # 地址栏内输入url
        self.window.bind("<Return>", self.handle_enter)  # 地址栏内按下回车后加载新url
        self.window.bind("<BackSpace>", self.handle_backspace)

        self.chrome = Chrome(self)

        # 将初始窗口在屏幕上居中
        center(self.window)

    # 新建一个tab并设置为当前显示的tab
    def new_tab(self, url):
        new_tab = Tab(const.HEIGHT - self.chrome.bottom)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        self.active_tab.draw(self.canvas, self.chrome.bottom)

        # 绘制browser chrome
        for cmd in self.chrome.paint():
            # 绘制时滚动距离scroll=0，确保chrome始终位于canvas上方
            cmd.execute(0, self.canvas)

    def handle_down(self, e):
        self.active_tab.scrolldown()
        self.draw()

    def handle_up(self, e):
        self.active_tab.scrollup()
        self.draw()

    def handle_click(self, e):
        if e.y < self.chrome.bottom:
            # 点击位置位于chrome中
            self.chrome.click(e.x, e.y)
        else:
            # 点击位置位于chrome下面的网页
            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)
        self.draw()

    def handle_key(self, e):
        if len(e.char) == 0:
            return
        if not (0x20 <= ord(e.char) <= 0x7F):
            return
        self.chrome.keypress(e.char)
        self.draw()

    def handle_enter(self, e):
        self.chrome.enter()
        self.draw()
    
    def handle_backspace(self, e):
        self.chrome.backspace()
        self.draw()

    def recfg(self, e):
        if const.WIDTH == e.width and const.HEIGHT == e.height:
            return
        const.WIDTH = e.width
        const.HEIGHT = e.height

        self.active_tab.reconfigure()
        self.draw()


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


# keep this being the last statement
main()

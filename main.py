import tkinter

from url import URL
from html_parser import HTMLParser
import const
from layout import DocumentLayout, BlockLayout


def main():
    Browser().load(URL(const.HTTP_URL))

    tkinter.mainloop()


# 浏览器
class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window, width=const.WIDTH, height=const.HEIGHT
        )
        self.canvas.pack(fill=tkinter.BOTH, expand=1)  # 让canvas填充window的空间

        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<Configure>", self.reconfigure)  # 当窗口大小更新时，重新布局

        self.scroll = 0  # 当前已向上滑动的距离
        self.loaded = False

        # 将初始窗口在屏幕上居中
        center(self.window)

    def load(self, url):
        body = url.request()
        self.nodes = HTMLParser(body).parse()

        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)
        self.draw()

        self.loaded = True

    # 在canvas上绘制
    def draw(self):
        self.canvas.delete("all")

        # 根据计算后页面元素的坐标、样式开始绘制
        for x, y, c, font in self.display_list:
            # 不绘制位于窗口可见区域之外的内容
            if y - self.scroll > const.HEIGHT:
                continue
            if y + const.VSTEP < self.scroll:
                continue

            self.canvas.create_text(x, y - self.scroll, text=c, font=font, anchor="nw")

    def scrollup(self, e):
        if self.scroll <= 0:
            return

        self.scroll -= const.SCROLL_STEP
        self.draw()

    def scrolldown(self, e):
        self.scroll += const.SCROLL_STEP
        self.draw()

    def reconfigure(self, e):
        if const.WIDTH == e.width and const.HEIGHT == e.height:
            return
        const.WIDTH = e.width
        const.HEIGHT = e.height

        if self.loaded:
            if not self.nodes:
                return
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.display_list = []
            paint_tree(self.document, self.display_list)
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


def paint_tree(layout_object, display_list):
    display_list.extend(layout_object.paint())
    for child in layout_object.children:
        paint_tree(child, display_list)


# keep this being the last statement
main()

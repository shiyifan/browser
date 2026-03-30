import tkinter

from url import URL
from html_parser import HTMLParser
import const
from layout import DocumentLayout, BlockLayout
from tags import Element
from css_parser import CSSParser

# 浏览器默认样式，user agent style
DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()


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
        self.nodes = HTMLParser(body).parse()  # 将HTML代码解析为DOM tree

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
            try:
                body = style_url.request()
            except:
                continue
            rules.extend(CSSParser(body).parse())  # 获取author stylesheet

        style(self.nodes, sorted(rules, key=cascade_priority))

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
        for cmd in self.display_list:
            # 不绘制位于窗口可见区域之外的内容
            if cmd.top > self.scroll + const.HEIGHT:
                continue
            if cmd.bottom < self.scroll:
                continue

            cmd.execute(self.scroll, self.canvas)

    def scrollup(self, e):
        if self.scroll <= 0:
            return

        self.scroll -= const.SCROLL_STEP
        self.draw()

    def scrolldown(self, e):
        # 已显示最后一行内容后，不再继续向下滚动
        max_y = max(self.document.height + 2 * const.VSTEP - const.HEIGHT, 0)
        self.scroll = min(self.scroll + const.SCROLL_STEP, max_y)

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


# 根据DOM结点上"style"属性、css文件、<style>中的代码创建CSS对象并赋值为"style"属性
def style(node, rules):
    node.style = {}  # CSS解析后的对象

    # 解析css代码中的样式
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

    # 解析并创建子结点的CSS对象
    for child in node.children:
        style(child, rules)


# 树状结构转为扁平的list结构
def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list

def cascade_priority(rule):
    selector, rule = rule
    return selector.priority

# keep this being the last statement
main()

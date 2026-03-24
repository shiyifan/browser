import tkinter
import tkinter.font
import socket
import ssl

# canvas的大小
WIDTH, HEIGHT = 1024, 768
# 在canvas上绘制文字时的间距与行距
HSTEP, VSTEP = 13, 18
# 滚动步长
SCROLL_STEP = 20

# HTTP_URL = "http://localhost:3000"
# HTTP_URL = "https://browser.engineering/examples/xiyouji.html"
HTTP_URL = "https://browser.engineering/text.html"

# 字体缓存
FONTS = {}

# 无end close tag的标签
SELF_CLOSING_TAGS = [
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
]


def main():
    Browser().load(URL(HTTP_URL))

    tkinter.mainloop()


# 浏览器
class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack(fill=tkinter.BOTH, expand=1)  # 让canvas填充window的空间

        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<Configure>", self.reconfigure)  # 当窗口大小更新时，重新布局

        self.scroll = 0  # 当前已向上滑动的距离

        # 将初始窗口在屏幕上居中
        center(self.window)

    def load(self, url):
        body = url.request()
        self.nodes = HTMLParser(body).parse()
        self.display_list = Layout(self.nodes).display_list
        self.draw()

        # print_tree(nodes)

    # 在canvas上绘制
    def draw(self):
        self.canvas.delete("all")

        # 根据计算后页面元素的坐标、样式开始绘制
        for x, y, c, font in self.display_list:
            # 不绘制位于窗口可见区域之外的内容
            if y - self.scroll > HEIGHT:
                continue
            if y + VSTEP < self.scroll:
                continue

            self.canvas.create_text(x, y - self.scroll, text=c, font=font, anchor="nw")

    def scrollup(self, e):
        if self.scroll <= 0:
            return

        self.scroll -= SCROLL_STEP
        self.draw()

    def scrolldown(self, e):
        self.scroll += SCROLL_STEP
        self.draw()

    def reconfigure(self, e):
        if not self.nodes:
            return

        global WIDTH, HEIGHT
        if WIDTH == e.width and HEIGHT == e.height:
            return
        WIDTH = e.width
        HEIGHT = e.height

        self.display_list = Layout(self.nodes).display_list
        self.draw()


# URL，根据url发送http请求并返回纯文本的http response body
class URL:
    def __init__(self, url):
        # 解析url中的scheme、host以及path
        self.scheme, url = url.split("://", 1)

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443

        if "/" not in url:
            url = url + "/"
        self.host, url = url.split("/", 1)
        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            if port:
                self.port = int(port)
        self.path = "/" + url

        print(f"host: {self.host}, scheme: {self.scheme}, path: {self.path}")

    # 请求url并获取HTTP报文
    def request(self):

        s = socket.socket(
            family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )

        # 如果请求"https"，那么额外需要tls
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        s.connect((self.host, self.port))

        request = f"GET {self.path} HTTP/1.0\r\n"  # 组建HTTP请求报文
        request += "\r\n"
        s.send(request.encode("utf8"))

        response = s.makefile("r", encoding="utf8", newline="\r\n")  # 获取HTTP响应报文

        # 读取响应报文第一行
        statusline = response.readline()
        version, status, explanation = statusline.split(" ", 2)

        # 读取响应报文中所有的Response Header
        response_headers = {}
        while True:
            line = response.readline()
            if line == "\r\n":
                break

            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        print(f"headers: {response_headers}")

        # 读取Response Body
        content = response.read()
        s.close()
        return content


# HTML代码中位于标签内外的纯文本
class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent

    def __repr__(self):
        return repr(self.text)


# HTML代码中的标签
class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.children = []
        self.attributes = attributes
        self.parent = parent

    def __repr__(self):
        return "<" + self.tag + ">"


class HTMLParser:
    def __init__(self, body):
        self.body = body
        self.unfinished = []

    # 解析HTML代码中标签与纯文本
    def parse(self):
        text = ""
        in_tag = False

        for c in self.body:
            if c == "<":
                in_tag = True
                if text:
                    # 提取标签之前（"<"字符之前）的纯文本
                    self.add_text(text)
                text = ""
            elif c == ">":
                # 读取标签结束字符">",并提取标签
                in_tag = False
                self.add_tag(text)
                text = ""
            else:
                text += c

        if not in_tag and text:
            self.add_text(text)

        return self.finish()  # 返回DOM结构

    # 在DOM树中添加text节点
    def add_text(self, text):
        if text.isspace():
            # 忽略仅空白字符构成的text结点
            return

        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    # 在DOM树中添加tag结点
    def add_tag(self, tag):
        if tag.startswith("!"):
            # 忽略"<!doctype html>"
            return

        tag, attributes = self.get_attibutes(tag)  # 解析标签名与标签属性

        if tag.startswith("/"):
            # 如果是close label"</xxxx>"，
            # 表示unfinished中最后一个label已结束，并添加至父结点中

            if len(self.unfinished) == 1:
                # 如果仅剩余最顶级标签，该标签无parent，那么直接返回
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)

        elif tag in SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            parent.children.append(Element(tag, attributes, parent))

        else:
            # 如果是open label"<xxxx>"，
            # 新建一个label,其父结点是unfinished中最后一个label,并且将该label添加至unfinished中

            # 如果是第一个标签，那么该标签无parent
            parent = self.unfinished[-1] if self.unfinished else None

            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def finish(self):
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()

    def get_attibutes(self, text):
        parts = text.split()
        tag = parts[0].casefold()
        attributes = {}

        # 解析标签的属性声明
        for attrpair in parts[1:]:
            if "=" in attrpair:
                # 形如"id=button"的属性声明
                key, value = attrpair.split("=", 1)
                # 如果属性值两侧有引号
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]

                attributes[key.casefold()] = value
            else:
                # 形如"disabled"、仅有属性名称的属性声明
                attributes[attrpair.casefold()] = ""

        return tag, attributes


# 根据页面宽度，计算每个页面元素的绘制坐标、字体等
class Layout:
    def __init__(self, nodes):
        self.display_list = []

        self.cursor_x = HSTEP
        self.cursor_y = VSTEP

        # 字体的默认值
        self.weight = "normal"
        self.style = "roman"
        self.size = 20

        # 作为buffer,临时保存一行字符，用于计算该行baseline的位置
        # line中的字符仅计算了x轴的绘制坐标，需要根据baseline的位置计算每个字符的y轴坐标
        self.line = []

        self.recurse(nodes)

        self.flush()

    def recurse(self, tree):
        if isinstance(tree, Text):
            for word in tree.text.split():
                self.word(word)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "small":
            self.size -= 4
        elif tag == "big":
            self.size += 4
        elif tag == "br":
            self.flush()
        elif tag == "p":
            self.flush()

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        elif tag == "small":
            self.size += 4
        elif tag == "big":
            self.size -= 4

    def word(self, word):
        font = get_font(self.size, self.weight, self.style)
        w = font.measure(word)

        if self.cursor_x + w > WIDTH - HSTEP:
            # 根据canvas宽度，字符已占满一行，计算该行的baseline位置并更新word的y轴绘制坐标
            self.flush()
        self.line.append((self.cursor_x, word, font))
        self.cursor_x += w + font.measure(" ")

    # 计算一行字符的baseline位置
    def flush(self):
        if not self.line:
            return

        # 根据每个字符的font,计算一行中最大的ascent
        metrics = [font.metrics() for x, word, font in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])

        # 可以直接以"max_ascent"作为baseline的位置，或者在这个基础上、在最大字符的ascent与descent之外再
        # 添加一些leading（空白区域），ascent上面添加一半leading, descent下面添加一半leading,
        # 这样，lineheight = (ascent + descent) + ascent_leading + descent_leading
        # 这里选择额外添加总共25%的leading,其中ascent上面与descent下面各占一半leading
        baseline = (
            self.cursor_y + 1.25 * max_ascent
        )  # 根据上一行的"cursor_y"坐标计算baseline坐标

        for x, word, font in self.line:
            y = baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))

        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + max_descent * 1.25

        self.cursor_x = HSTEP
        self.line = []


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


# 从"FONTS"缓存中获取字体
def get_font(size, weight, style):
    key = (size, weight, style)

    if key not in FONTS:
        font = tkinter.font.Font(family="Times", size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)

    return FONTS[key][0]


# 输出DOM Tree结构
def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


# keep this being the last statement
main()

import tkinter
import tkinter.font
import socket
import ssl

# canvas的大小
WIDTH, HEIGHT = 800, 600
# 在canvas上绘制文字时的间距与行距
HSTEP, VSTEP = 13, 18
# 滚动步长
SCROLL_STEP = 20

# HTTP_URL = "http://localhost:3000";
HTTP_URL = "https://browser.engineering/examples/xiyouji.html"


def main():
    Browser().load(URL(HTTP_URL))

    tkinter.mainloop()


# 浏览器
class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack()

        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)

        self.scroll = 0  # 当前已向上滑动的距离

        # 将初始窗口在屏幕上居中
        center(self.window)

    def load(self, url):
        body = url.request()
        tokens = lex(body)
        self.display_list = layout(tokens)
        self.draw()

    # 在canvas上绘制
    def draw(self):
        simsun = tkinter.font.Font(family="NSimSun", size=12)
        self.canvas.delete("all")

        # 根据计算后页面元素的坐标、样式开始绘制
        for x, y, c in self.display_list:
            # 不绘制位于窗口可见区域之外的内容
            if y - self.scroll > HEIGHT:
                continue
            if y + VSTEP < self.scroll:
                continue

            self.canvas.create_text(x, y - self.scroll, text=c, font=simsun)

    def scrollup(self, e):
        if self.scroll <= 0:
            return

        self.scroll -= SCROLL_STEP
        self.draw()

    def scrolldown(self, e):
        self.scroll += SCROLL_STEP
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
    def __init__(self, text):
        self.text = text


# HTML代码中的标签
class Tag:
    def __init__(self, tag):
        self.tag = tag


# 提取HTML代码中标签与纯文本
def lex(body):
    out = []
    buffer = ""  # 保存标签文本或者纯文本
    in_tag = False

    for c in body:
        if c == "<":
            in_tag = True
            if buffer:
                # 提取标签之前（"<"字符之前）的纯文本
                out.append(Text(buffer))
            buffer = ""
        elif c == ">":
            # 读取标签结束字符">",并提取标签
            in_tag = False
            out.append(Tag(buffer))
            buffer = ""
        else:
            buffer += c

    if not in_tag and buffer:
        out.append(Text(buffer))

    return out  # 返回提取后的各个tokens


# 根据页面宽度，计算每个页面元素的绘制坐标、字体等
def layout(tokens):
    cursor_x, cursor_y = HSTEP, VSTEP
    display_list = []  # 保存页面元素的绘制坐标

    for tok in tokens:
        if isinstance(tok, Text):
            for c in tok.text:
                if cursor_x + HSTEP > WIDTH:
                    cursor_x = HSTEP
                    cursor_y += VSTEP
                display_list.append((cursor_x, cursor_y, c))
                cursor_x += HSTEP

    return display_list


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


# keep this being the last statement
main()

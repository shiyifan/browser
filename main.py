import socket
import ssl


class URL:
    def __init__(self, url):
        # 解析url中的scheme、host以及path
        self.scheme, url = url.split("://", 1)

        if "/" not in url:
            url = url + "/"
        self.host, url = url.split("/", 1)
        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)
        self.path = "/" + url

        print(f"host: {self.host}, scheme: {self.scheme}, path: {self.path}")

    # 请求url并获取HTTP报文
    def request(self):

        s = socket.socket(
            family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )

        # 如果使用tls，那么需要下面的代码
        # ctx = ssl.create_default_context()
        # s = ctx.wrap_socket(s, server_hostname=self.host)

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
            line = response
            if line == "\r\n":
                break

            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        # 读取Response Body
        content = response.read()
        s.close()


# def show(body):
#   in_tag = False
#   for c in body:
#     if c == "<":
#       in_tag = True
#     elif c == ">":
#       in_tag = False
#       elif not


u = URL("http://www.baidu.com/hello")

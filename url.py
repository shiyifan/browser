import socket
import ssl

# 保存所有的Cookie
# key为host, value为cookie字符串
COOKIE_JAR = {}


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

    # 请求url并获取HTTP报文
    # referer: 发起请求的页面所在的URL
    def request(self, referer, payload=None):

        s = socket.socket(
            family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )

        method = "POST" if payload else "GET"

        # 如果请求"https"，那么额外需要tls
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        print(f"request: {self.host}:{self.port}{self.path}")

        s.connect((self.host, self.port))

        request = f"{method} {self.path} HTTP/1.0\r\n"  # 组建HTTP请求报文
        if payload:
            length = len(payload.encode("utf8"))
            request += f"Content-Length: {length}\r\n"

        # 如果保存了当前host的cookie,那么添加"Cookie"请求头
        if self.host in COOKIE_JAR:
            cookie, params = COOKIE_JAR[self.host]

            # 简单实现了"Cookie: SameSite=Lax"机制
            # 如果Cookie设置了Lax属性值，那么除"GET"请求外的其他请求必须满足same site
            # 实际上，"SameSite=Lax"的实际行为要复杂一些,另请参阅MDN
            allow_cookie = True
            if referer and params.get("samesite", "none") == "lax":
                if method != "GET":
                    allow_cookie = self.host == referer.host
            if allow_cookie:
                request += f"Cookie: {cookie}\r\n"

        request += "\r\n"
        if payload:
            request += payload

        s.send(request.encode("utf8"))

        response = s.makefile("r", encoding="utf8", newline="\r\n")  # 获取HTTP响应报文

        # 读取响应报文第一行
        statusline = response.readline()
        version, status, explanation = statusline.split(" ", 2)

        print(f"{self.path}: {status}")

        # 读取响应报文中所有的Response Header
        response_headers = {}
        while True:
            line = response.readline()
            if line == "\r\n":
                break

            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        # 保存服务器发送的cookie
        if "set-cookie" in response_headers:
            cookie = response_headers["set-cookie"]
            params = {}

            if ";" in cookie:
                # 解析Cookie中的参数

                cookie, rest = cookie.split(";", 1)
                for param in rest.split(";"):
                    if "=" in param:
                        param, value = param.split("=", 1)
                    else:
                        value = "true"
                    params[param.strip().casefold()] = value.casefold()
            COOKIE_JAR[self.host] = (cookie, params)

        # 读取Response Body
        content = response.read()
        s.close()
        return content

    # 将absolute url或者relative url根据当前URL对象，返回完整的url
    def resolve(self, url):
        # 包含"://"的url为absolute url,无需添加其他内容
        if "://" in url:
            return URL(url)

        # 以下为relative url,需要补全缺失的部分

        if not url.startswith("/"):
            # 不以"/"开头的url,默认与当前path相同

            dir, _ = self.path.rsplit("/", 1)
            while url.startswith("../"):
                _, url = url.split("/", 1)
                if "/" in dir:
                    dir, _ = dir.rsplit("/", 1)
            url = dir + "/" + url

        if url.startswith("//"):
            # 以"//"开头的url,默认与当前scheme相同
            return URL(self.scheme + ":" + url)
        else:
            # 以"/"开头的url,默认与当前scheme, host, port相同
            return URL(self.scheme + "://" + self.host + ":" + str(self.port) + url)

    # 转换为字符串的表示
    def __str__(self):
        port_part = ":" + str(self.port)
        if self.scheme == "https" and self.port == 443:
            port_part = ""
        if self.scheme == "http" and self.port == 80:
            port_part = ""
        return self.scheme + "://" + self.host + port_part + self.path

    def origin(self):
        return f"{self.scheme}://{self.host}:{self.port}"

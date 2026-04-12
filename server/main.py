# 简单的HTTP服务器

import socket
import urllib.parse

ENTRIES = ["Pavel was here"]


def main():
    s = socket.socket(
        family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )

    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind(("", 8000))
    s.listen()
    print("start listening...")

    count = 0

    while True:
        conx, addr = s.accept()
        count += 1
        print(f"new connection! {count}")
        handle_connection(conx)


def handle_connection(conx):
    req = conx.makefile("b")
    reqline = req.readline().decode("utf8")  # 读取HTTP请求报文第一行
    method, url, version = reqline.split(" ", 2)
    assert method in ["GET", "POST"]

    # 读取HTTP Request Header
    headers = {}
    while True:
        line = req.readline().decode("utf8")
        if line == "\r\n":
            break
        header, value = line.split(":", 1)
        headers[header.casefold()] = value.strip()

    # 读取HTTP Request Body
    if "content-length" in headers:
        length = int(headers["content-length"])
        body = req.read(length).decode("utf8")
    else:
        body = None

    # 生成HTTP Response
    status, body = do_request(method, url, headers, body)
    response = f"HTTP/1.0 {status}\r\n"
    response += f"Content-Length: {len(body.encode('utf8'))}\r\n"
    response += "\r\n" + body
    conx.send(response.encode("utf8"))
    conx.close()


def do_request(method, url, headers, body):
    if method == "GET" and url == "/":
        return "200 OK", show_comments()
    elif method == "POST" and url == "/add":
        params = form_decode(body)
        return "200 OK", add_entry(params)
    elif method == "GET" and url == "/comment.js":
        with open("server/comment.js") as f:
            return "200 OK", f.read()
    else:
        return "404 Not Found", not_found(url, method)


def form_decode(body):
    params = {}
    for field in body.split("&"):
        name, value = field.split("=", 1)
        name = urllib.parse.unquote_plus(name)
        value = urllib.parse.unquote_plus(value)
        params[name] = value
    return params


def show_comments():
    out = "<!doctype html>"
    for entry in ENTRIES:
        out += f"<p>{entry}</p>"
    out += """
    <form action=add method=post>
        <p><input name=guest></p>
        <p><button>Sign the book</button></p>
        <strong></strong>
    </form>
    <script src="/comment.js"></script>
    """
    return out


def add_entry(params):
    if "guest" in params:
        ENTRIES.append(params["guest"])
    return show_comments()


def not_found(url, method):
    out = f"""
    <!doctype html>
    <h1>{method} {url} not found!</h1>
    """
    return out


main()

# 简单的HTTP服务器

import socket
import urllib.parse
import random
from utils import log
import html
import ssl
from pathlib import Path

ENTRIES = [
    ("No names. We are nameless!", "cerealkiller"),
    ("HACK THE PLANET!", "crashoverride"),
]

SESSIONS = {}

LOGINS = {"admin": "1234", "scott": "1234"}

USE_HTTPS = True


def main():
    s = socket.socket(
        family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )

    if USE_HTTPS:
        dir = Path(__file__).resolve().parent
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=dir / "cert.pem", keyfile= dir / "cert-privkey.pem")
        s = ctx.wrap_socket(s, server_side=True)

    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind(("", 8000))
    s.listen()
    print("start listening...")

    count = 0

    while True:
        try: 
            conx, addr = s.accept()
        except Exception as e:
            log.e("socket accept error: ", e)
            continue
        count += 1
        print(f"new connection! {count}")
        handle_connection(conx)


def handle_connection(conx):
    req = conx.makefile("b")
    reqline = req.readline().decode("utf8")  # 读取HTTP请求报文第一行
    if not reqline:
        log.w("empty request line, close connection")
        conx.close()
        return
    try:
        method, url, version = reqline.split(" ", 2)
    except Exception as e:
        log.e(f'reqline: {reqline}, error: {e}')
        conx.close()
        return
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

    # 读取Cookie
    # 只要请求中没有"Cookie",那么就生成一个随机的token，并在Response中通过"Set-Cookie"设置token
    if "cookie" in headers:
        token = headers["cookie"][len("token=") :]
    else:
        token = str(random.random())[2:]

    session = SESSIONS.setdefault(token, {})
    # 生成HTTP Response
    status, body = do_request(session, method, url, headers, body)
    response = f"HTTP/1.0 {status}\r\n"
    response += f"Content-Length: {len(body.encode('utf8'))}\r\n"
    response += "Content-Security-Policy: default-src http://localhost:8000\r\n"

    if "cookie" not in headers:
        # 如果请求中没有cookie,则在响应中设置上面随机生成的token
        response += f"Set-Cookie: token={token}; SameSite=Lax\r\n"
        # response += f"Set-Cookie: token={token}\r\n"
        log.i(f"new request: set cookie, token={token}")

    response += "\r\n" + body
    conx.send(response.encode("utf8"))
    conx.close()


def do_request(session, method, url, headers, body):
    if method == "GET" and url == "/":
        # 主页
        return "200 OK", show_comments(session)

    elif method == "POST" and url == "/add":
        # 添加comments
        params = form_decode(body)
        add_entry(session, params)
        return "200 OK", show_comments(session)

    elif method == "GET" and url == "/comment.js":
        # serve静态资源
        with open("server/comment.js") as f:
            return "200 OK", f.read()

    elif method == "GET" and url == "/login":
        return "200 OK", login_form(session)

    elif method == "POST" and url == "/":
        params = form_decode(body)
        return do_login(session, params)

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


def show_comments(session):
    out = "<!doctype html>"

    if "user" in session:

        # 为每个<form>附带一个随机值nonce,并将该nonce关联至登陆用户的session中
        # 合法的<form>提交必须附带有效的"Cookie"与"nonce"
        nonce = str(random.random())[2:]
        session["nonce"] = nonce

        # 以"<input type=hidden>"的方式附带随机值
        out += f"""
            <h1>Hello, {session['user']}!</h1>
            <form action=add method=post>
                <p>nonce: <input name=nonce type=hidden value={nonce}></p>
                <p>Comment: <input name=guest></p>
                <p><button>Sign the book</button></p>
                <strong></strong>
            </form>
            <script src="/comment.js"></script>
            """
        for entry, who in ENTRIES:
            # 对用户输入进行HTML转译,避免执行用户输入中的某些malicious code
            out += f"<p>{html.escape(entry)}, {html.escape(who)}</p>" 
    else:
        out += f"""
                <a href=/login>Sign in to write a comment</a>
                """
    return out


def add_entry(session, params):
    if "nonce" not in params or "nonce" not in session:
        # form表单中没有“nonce”，当前session也没有"nonce"
        not_in_p = "nonce" not in params
        log.e(f"no nonce in {'params' if not_in_p else 'session'}, rejected")
        return

    if session["nonce"] != params["nonce"]:
        # session的nonce必须与请求表单中的值一致
        log.e(f"session: {session['nonce']}, form: {params['nonce']}, rejected")
        return

    if "user" not in session:
        return

    if "guest" in params:
        ENTRIES.append((params["guest"], session["user"]))
    return show_comments(session)


def not_found(url, method):
    out = f"""
        <!doctype html>
        <h1>{method} {url} not found!</h1>
        """
    return out


def login_form(session):
    body = """
        <!doctype html>
        <form action=/ method=post>
            <p>Username: <input name=username></p>
            <p>Password: <input name=password type=password></p>
            <p><button>Login</button></p>
        </form>
        """
    return body


def do_login(session, params):
    username = params.get("username")
    password = params.get("password")
    if username in LOGINS and LOGINS[username] == password:
        # 登录验证通过
        session["user"] = username
        return "200 OK", show_comments(session)
    else:
        # 登录验证失败
        out = f"""
            <!doctype html>
            <h1>Login failed! Invalid password for {username}</h1>
            """
        return "401 Unauthorized", out


main()

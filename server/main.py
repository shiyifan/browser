import socket

s = socket.socket(
    family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
)

s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

s.bind(("", 8000))
s.listen()

while True:
    conx, addr = s.accept()
    handle_connection(conx)

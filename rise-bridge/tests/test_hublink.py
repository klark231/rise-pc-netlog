"""Link client against a stand-in host that answers HELLO the way ldn.cpp's host_serve does."""
import os, socket, struct, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bridge import hublink as h


def fake_host(srv, got):
    c, _ = srv.accept()
    t, p = h.read_frame(c)
    assert t == h.HELLO and struct.unpack_from("<HHB", p) == (1, 0, 0)
    got["mac"], got["name"] = p[5:11], p[11:44].split(b"\0")[0]
    info = bytearray(h.INFO_SIZE)
    info[h.NI_NODE_MAX] = 4
    c.sendall(h.frame(h.WELCOME, bytes([2]) + struct.pack("<I", 0xA9FE6A03) + bytes(info)))
    t, p = h.read_frame(c)
    assert t == h.DATA
    got["data"] = p
    c.sendall(h.frame(h.DATA, struct.pack("<IHIH", 0xA9FE6A01, 12345, 0xA9FE6A03, 12345) + b"pong"))
    time.sleep(0.2)
    c.close()


def test_hello_welcome_data():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    got = {}
    threading.Thread(target=fake_host, args=(srv, got), daemon=True).start()
    link = h.Link(bytes.fromhex("02c99f568d1a"), "Hunter")
    rx = []
    link.on_data = lambda src, sp, dp, d: rx.append((hex(src), sp, dp, d))
    link.join_direct("127.0.0.1", srv.getsockname()[1])
    assert link.node == 2 and link.address == 0xA9FE6A03
    link.send(12345, 0xFFFFFFFF, 12345, b"ping")
    for _ in range(50):
        if rx: break
        time.sleep(0.05)
    assert rx == [("0xa9fe6a01", 12345, 12345, b"pong")]
    assert got["name"] == b"Hunter" and got["data"][12:] == b"ping"


if __name__ == "__main__":
    test_hello_welcome_data(); print("ok")

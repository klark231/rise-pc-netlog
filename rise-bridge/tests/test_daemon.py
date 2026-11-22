"""The daemon's UDP layer, against stand-ins for the hub list and the Pia station."""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import bridge_daemon as d
from bridge import hublink, joinmsgs


class FakeInfo:
    def __init__(self, *a): pass
    def nodes(self): yield {"node": 0, "name": "Hunter"}; yield {"node": 1, "name": "X"}
    @property
    def advertise(self): return bytes(16) + b"hello-advertise"


class FakeStation:
    def __init__(self, link, log=print):
        self.state, self.sent = "in", []
        FakeStation.last = self
    def start(self): pass
    def _host(self): return 0xA9FE0101, b"\0" * 6
    def send_game(self, dst, payload): self.sent.append((dst, payload))


class FakeLink:
    def __init__(self, *a, **k): pass
    def join(self, *a): pass
    def leave(self): pass


def test_daemon():
    hublink.list_hubs = lambda *a: [(0xABC, b"raw")]
    hublink.NetInfo = FakeInfo
    hublink.Link = FakeLink
    d.hublink, d.Station = hublink, FakeStation
    dm = d.Daemon(("x", 1), b"room", "PC", 0, log=lambda s: None)
    threading.Thread(target=dm.run, daemon=True).start()
    port = dm.sock.getsockname()[1]
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); c.settimeout(3)
    def ask(t): c.sendto(t.encode(), ("127.0.0.1", port)); return c.recvfrom(65535)[0].decode()
    r = ask("LIST").split("\n")
    assert r[0] == "HUBS" and r[1].split()[:4] == ["H", "0", b"Hunter".hex(), "2"], r
    assert ask("JOIN 0") == "JOINED"
    assert ask("SEND " + d.CON_REQ.hex()) == "RECV " + d.CON_ANS.hex()
    c.sendto(("SEND " + joinmsgs.steam_wrap(b"\x00\x01\x03\x02abcdefgh").hex()).encode(), ("127.0.0.1", port))
    time.sleep(0.3)
    assert FakeStation.last.sent == [(0xA9FE0101, b"\x00\x01\x03\x02abcdefgh")], FakeStation.last.sent
    dm.from_switch(0xA9FE0101, b"\x00\x01\x03\x02zzzzzzzz")
    assert c.recvfrom(65535)[0].decode() == "RECV " + joinmsgs.steam_wrap(b"\x00\x01\x03\x02zzzzzzzz").hex()


if __name__ == "__main__":
    test_daemon(); print("ok test_daemon")

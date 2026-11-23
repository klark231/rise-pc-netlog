import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import lobby, wire


def test_wire():
    host = bytes.fromhex("076ac6a6a7a5a7862f0a2b5c")      # a Switch host's platform message, as captured
    p = wire.decode(host)
    assert p == bytes.fromhex("01020221a9252177") and wire.encode(p) == host
    assert wire.decode(host[:-1] + b"\x00") is None           # the check catches a changed byte
    print("ok test_wire")


def test_pc_lobby():
    out = []
    pc = lobby.PcLobby(0x011000014B1D0000, out.append, log=lambda s: None)
    me, host = bytes.fromhex("45ba091c"), bytes.fromhex("277312e7")
    join = lobby.rec(lobby.T_JOIN, struct.pack(">Q", 0x0110000112345678) + b"\x01\x02\x03\x04\x00")
    pc.from_pc(wire.build(wire.LOBBY, me, host, 0, [(1, join)]))
    ch, s, r, ack, recs = wire.parse(wire.decode(out[-1]))
    assert (s, r, ack) == (host, me, 1)
    assert [b[:3].hex() for _, b in recs] == ["030002", "030008", "030005"] and len(recs[1][1]) == 255
    pc.from_pc(wire.build(wire.LOBBY, me, host, 3, []))       # the PC acknowledges all three
    pc.tick()
    ch, s, r, ack, recs = wire.parse(wire.decode(out[-1]))
    assert [q for q, _ in recs] == [4] and recs[0][1] == lobby.PING
    print("ok test_pc_lobby")


def test_switch_lobby():
    out = []
    sw = lobby.SwitchLobby(out.append, log=lambda s: None)
    host, me = bytes.fromhex("277312e7"), bytes.fromhex("45ba091c")
    sw.from_host(wire.build(wire.LOBBY, host, me, 0, [(1, bytes(20))]))
    assert wire.decode(out[-1]).hex() == "030145ba091c277312e70001"   # what a real Switch joiner sent back
    print("ok test_switch_lobby")


test_wire()
test_pc_lobby()
test_switch_lobby()

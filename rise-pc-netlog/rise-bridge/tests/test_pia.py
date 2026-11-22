"""Round trips through bridge/pia.py, checked against the reader in rise-pc-netlog's analysis/rise_net.py
(a copy sits next to this file; set RISE_NET to use another folder)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get("RISE_NET", os.path.dirname(__file__)))
from bridge import pia

KEY = bytes(range(16))
SESSION = bytes.fromhex("edee5e2c")
MAC = bytes.fromhex("02c99f568d1a")


def test_station_id():
    assert pia.station_id(MAC).hex() == "9f8d1a56c9020000"


def test_body_round_trip():
    msgs = [pia.Message(0x58, b"x" * 13), pia.Message(0x68, b"hello", port=1, dst=7), pia.Message(0x68, b"abc", port=1, dst=7)]
    assert [(m.ptype, m.payload, m.port, m.dst) for m in pia.parse_body(pia.build_body(msgs))] == \
        [(m.ptype, m.payload, m.port, m.dst) for m in msgs]


def test_seal_open_and_reference_reader():
    c = pia.PiaCrypto(KEY, SESSION)
    body = pia.build_body([pia.Message(0x68, b"game message")])
    h = pia.Header(b"\x11\x22\x33\x44", b"\xaa\xbb\xcc\xdd", 1, b"", (5).to_bytes(8, "big"))
    pkt = c.seal(body, MAC, h)
    assert c.open(pkt, MAC) == body
    assert c.open(pkt[:-1] + bytes([pkt[-1] ^ 1]), MAC) is None  # flipped ciphertext byte: tag fails
    try:  # the reference implementation in rise_net.py must accept what we made
        import rise_net
    except ImportError:
        return
    ref = rise_net.Pia(KEY, {"10.0.0.1": MAC}, SESSION)
    pk = {"data": bytearray(pkt), "src": "10.0.0.1"}
    assert ref.verify(pk) is True and bytes(ref.decrypt(pk)) == body


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)

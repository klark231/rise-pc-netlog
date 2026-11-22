"""The identity block of the game's member messages (types 0203 and 0302), worked out from the 2026-11-21 capture.

A member message's data (the plain body after the XOR byte, see gamemsg.seal) is
    type(2)  idS(4)  (idR[:3] ^ 03 ^ idS[3])(3)  tail
where idS / idR are the 4-byte identities of the sender / receiver (one per MAC; every id's last byte is odd), and the
tail is one byte per flag: base | flag, with base = (idS[3] ^ idR[3] ^ 02) & 0xFE.
  0203, 21 bytes: tail of 8 flags.      The joiner's own is 11001101 to the host, 11110010 to the others.
  0302, 16 bytes: the reply. Its 7 identity bytes are all XORed with 01; the tail is 3 flags: 0,0,1.
Checked against every 0203 message of the capture (31 of 31 identity blocks, 28 of 31 tails) and against the joiner's own
21- and 16-byte messages to the host, which come out byte for byte the same (tests/test_memberid.py).

Both ids of a pair can be read from the host's own 21-byte message to us: idHost = its first 4 data bytes after the type,
idStation = (its next 3 ^ 03 ^ idHost[3]) plus a 4th byte from the tail base.
"""
from . import gamemsg

T_MEMBER, T_REPLY = b"\x02\x03", b"\x03\x02"


def _base(ids: bytes, idr: bytes) -> int:
    return (ids[3] ^ idr[3] ^ 0x02) & 0xFE


def _ident(ids: bytes, idr: bytes) -> bytes:
    return ids + bytes(a ^ 0x03 ^ ids[3] for a in idr[:3])


def _tail(ids: bytes, idr: bytes, flags) -> bytes:
    base = _base(ids, idr)
    return bytes(base | (1 if f else 0) for f in flags)


def member_msg(ids: bytes, idr: bytes, flags=(1, 1, 0, 0, 1, 1, 0, 1)) -> bytes:
    """The 21-byte 0203 message of a joiner to the host (flags as seen in the capture)"""
    return gamemsg.seal(T_MEMBER + _ident(ids, idr) + _tail(ids, idr, flags))


def reply_msg(ids: bytes, idr: bytes, flags=(0, 0, 1)) -> bytes:
    """The 16-byte 0302 reply of a joiner to the host"""
    ident = bytes(b ^ 0x01 for b in _ident(ids, idr))
    return gamemsg.seal(T_REPLY + ident + _tail(ids, idr, flags))


def learn(payload: bytes):
    """From a 0203 message a host sent us: (idHost, idStation), or None if it isn't one."""
    if len(payload) < 16:
        return None
    d = gamemsg.data_of(payload)
    if d[:2] != T_MEMBER or len(d) < 10:
        return None
    id_host = d[2:6]
    st = bytes(a ^ 0x03 ^ id_host[3] for a in d[6:9])
    base = d[9] & 0xFE
    return id_host, st + bytes([base ^ 0x02 ^ id_host[3]])

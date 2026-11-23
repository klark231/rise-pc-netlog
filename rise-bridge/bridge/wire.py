"""The game's own encoding of its network messages, the same on PC and Switch.

A message is M = check (4 bytes, big endian) + payload, sent as the running XOR of M:
out[0] = M[0], out[i] = M[i] ^ out[i - 1]. The check is zlib.crc32(payload) ^ E(len(payload)), where E(0) = 0xfbbb20e3
and E(n + 1) = step(E(n)) ^ 0xf727ef8d, step being CRC-32 over one zero byte. Checked on every game message in the
captures: 34,484 from the PC logs and 8,961 from the port's (lengths up to 486), all of them byte for byte.

(This is what gamemsg's "header + XOR byte + table" was approximating: the XOR byte is the last byte of the running XOR,
and the table was the CRC seen through it.)

Payloads start with a channel: 01 02 small control messages (hello 01, platform/identity 02, counters 03/04),
02 01 member status, 03 01 the lobby, 04 02 game data. Channels 02 and 03 are numbered and acknowledged, all their
messages in the captures laid out as
    channel(2) sender id(4) receiver id(4) ack(2) [seq(2) length(2) record]...
(04 has a layout of its own, not decoded; the bridge passes it through.)
"""
import struct
import zlib

_K = 0xF727EF8D
_E = [0xFBBB20E3]


def _step(x: int) -> int:
    return zlib.crc32(b"\0", x) ^ zlib.crc32(b"\0", 0)


def _e(n: int) -> int:
    while len(_E) <= n:
        _E.append(_step(_E[-1]) ^ _K)
    return _E[n]


def check(payload: bytes) -> bytes:
    return (zlib.crc32(payload) ^ _e(len(payload))).to_bytes(4, "big")


def encode(payload: bytes) -> bytes:
    out, prev = bytearray(), 0
    for b in check(payload) + payload:
        prev ^= b
        out.append(prev)
    return bytes(out)


def decode(msg: bytes):
    """The payload, or None if it isn't a game message (too short, or the check doesn't match)"""
    if len(msg) < 4:
        return None
    m = bytes([msg[0]]) + bytes(msg[i] ^ msg[i - 1] for i in range(1, len(msg)))
    return m[4:] if m[:4] == check(m[4:]) else None


# ---- channels -------------------------------------------------------------------------------------------------------

CONTROL, MEMBER, LOBBY, GAME = b"\x01\x02", b"\x02\x01", b"\x03\x01", b"\x04\x02"
PLATFORM_PC, PLATFORM_SWITCH = 0x00, 0x21


def platform(payload: bytes):
    """(platform byte, sender id) from a 01 02 02 message, else None"""
    if len(payload) == 8 and payload[:3] == b"\x01\x02\x02":
        return payload[3], payload[4:8]
    return None


def with_platform(payload: bytes, value: int) -> bytes:
    return payload[:3] + bytes([value]) + payload[4:]


def parse(payload: bytes):
    """A numbered channel's payload: (channel, sender id, receiver id, ack, [(seq, record)]), or None"""
    if len(payload) < 12 or payload[:2] not in (MEMBER, LOBBY):
        return None
    ch, sender, receiver, ack = payload[:2], payload[2:6], payload[6:10], struct.unpack(">H", payload[10:12])[0]
    i, recs = 12, []
    while i < len(payload):
        if i + 4 > len(payload):
            return None
        seq, n = struct.unpack(">HH", payload[i:i + 4])
        if i + 4 + n > len(payload):
            return None
        recs.append((seq, payload[i + 4:i + 4 + n]))
        i += 4 + n
    return ch, sender, receiver, ack, recs


def build(ch: bytes, sender: bytes, receiver: bytes, ack: int, recs=()) -> bytes:
    out = bytearray(ch + sender + receiver + struct.pack(">H", ack & 0xFFFF))
    for seq, rec in recs:
        out += struct.pack(">HH", seq & 0xFFFF, len(rec)) + rec
    return bytes(out)

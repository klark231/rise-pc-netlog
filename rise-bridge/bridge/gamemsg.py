"""Rewriting game messages the Switch host sends, so the PC game accepts them.

A game message is 3 prefix bytes + a body XORed with one byte, and (prefix + that XOR byte) is a 32-bit value that is
an affine (XOR-linear) function of the body's bits: flipping a body bit XORs a fixed 32-bit value into it. The values
for bits 32..39 from the end of the body were solved from captured messages (and predicted 15 of 15 real 12-byte
messages in a leave-one-out test).

The use: the platform message. A Switch says 0x21 there, a PC 0x00 (as payload bytes, bridge/wire.py); the PC game
leaves as soon as it sees the Switch's, so it is turned into the PC's (and the other way for the PC's), keeping the
identity in it the same. bridge/wire.py has the exact encoding; the table below is kept for the older tools.
"""

# header delta for flipping body bit n (counted from the last bit of the body), n = 32..39
DELTA = {32: 0x855917c2, 33: 0xd0198269, 34: 0x7a98a93e, 35: 0xf531527c,
         36: 0x30c90914, 37: 0x61921228, 38: 0xc3242450, 39: 0x5ce3e54c}


def parse(msg: bytes):
    """(header 32-bit value, body) of a game message"""
    key = msg[3]
    return int.from_bytes(msg[:4], "big"), bytes(b ^ key for b in msg[3:])


def build(header: int, body: bytes) -> bytes:
    h = header.to_bytes(4, "big")
    return h + bytes(b ^ h[3] for b in body[1:])


def set_byte(msg: bytes, index: int, value: int) -> bytes:
    """The message with body byte `index` set to `value`. Only bytes 4 positions from the end of the body can be
    done (those are the bits whose effect is known): KeyError otherwise."""
    header, body = parse(msg)
    diff = body[index] ^ value
    base = (len(body) - 1 - index) * 8
    for bit in range(8):
        if diff >> bit & 1:
            header ^= DELTA[base + bit]
    body = body[:index] + bytes([value]) + body[index + 1:]
    return build(header, body)


def is_platform_msg(msg: bytes) -> bool:
    return len(msg) == 12 and parse(msg)[1][:4] == bytes.fromhex("00010301")


def _set_platform(msg: bytes, value: int) -> bytes:
    """The platform message with another platform byte and the same identity (bridge/wire.py: in the payload it's
    01 02 02 <platform> <id>, PC 00, Switch 21). Only the platform byte may change: the identity in it is the one every
    member and lobby message that player sends afterwards carries."""
    from . import wire
    p = wire.decode(msg)
    if p is None or wire.platform(p) is None or p[3] == value:
        return msg
    return wire.encode(wire.with_platform(p, value))


def to_pc(msg: bytes) -> bytes:
    """A message from a Switch host, made the way a PC sends it (only the platform message changes)"""
    from . import wire
    return _set_platform(msg, wire.PLATFORM_PC)


def to_switch(msg: bytes) -> bytes:
    """A message from the PC game, made the way a Switch sends it"""
    from . import wire
    return _set_platform(msg, wire.PLATFORM_SWITCH)


def identity(msg: bytes):
    """The sender's 4-byte identity from its platform message (None for any other message)"""
    from . import wire
    p = wire.decode(msg)
    pl = wire.platform(p) if p is not None else None
    return pl[1] if pl else None


# ---- the full checksum, from bridge/headertable.py (solved from captures) -------------------------------------------
def seal(data: bytes) -> bytes:
    """A complete game message for these data bytes (the plain body AFTER the XOR byte): header + data XOR key."""
    from .headertable import C, D
    total = 4 + len(data)
    if len(data) > len(D) // 8:
        raise KeyError("data longer than %d bytes" % (len(D) // 8))
    header, n = C[total], 0
    for byte in reversed(data):
        for i in range(8):
            if byte >> i & 1:
                header ^= D[n]
            n += 1
    h = header.to_bytes(4, "big")
    return h + bytes(b ^ h[3] for b in data)

def data_of(msg: bytes) -> bytes:
    """The data bytes (plain body after the XOR byte) of a game message"""
    return bytes(b ^ msg[3] for b in msg[4:])

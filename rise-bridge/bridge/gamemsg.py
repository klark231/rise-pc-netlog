"""Rewriting game messages the Switch host sends, so the PC game accepts them.

A game message is 3 prefix bytes + a body XORed with one byte, and (prefix + that XOR byte) is a 32-bit value that is
an affine (XOR-linear) function of the body's bits: flipping a body bit XORs a fixed 32-bit value into it. The values
for bits 32..39 from the end of the body were solved from captured messages (and predicted 15 of 15 real 12-byte
messages in a leave-one-out test).

The use: the host's 12-byte message is 00 01 03 01 <platform> <4 bytes>. A Switch sends platform 0x20, a PC 0x01; the PC
game leaves as soon as it sees 0x20, so it is turned into 0x01.
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


def to_pc(msg: bytes) -> bytes:
    """A message from a Switch host, made the way a PC sends it (only the 12-byte platform message changes)"""
    if is_platform_msg(msg) and parse(msg)[1][4] != 0x01:
        return set_byte(msg, 4, 0x01)
    return msg


def to_switch(msg: bytes) -> bytes:
    """A message from the PC game, made the way a Switch sends it (the platform message 0x01 -> 0x20)"""
    if is_platform_msg(msg) and parse(msg)[1][4] != 0x20:
        return set_byte(msg, 4, 0x20)
    return msg

"""Rewriting game messages the Switch host sends, so the PC game accepts them.

A game message is 3 prefix bytes + a body XORed with one byte, and (prefix + that XOR byte) is a 32-bit value that is
an affine (XOR-linear) function of the body's bits: flipping a body bit XORs a fixed 32-bit value into it. The values
for bits 32..39 from the end of the body were solved from captured messages (and predicted 15 of 15 real 12-byte
messages in a leave-one-out test).

The use: the host's 12-byte message is 00 01 03 01 <platform> <4 bytes>. A Switch sends platform 0x20, a PC 0x01; the PC
game leaves as soon as it sees 0x20, so it is turned into 0x01 (and the other way for the PC's), keeping the identity
in the 4 bytes the same (set_platform).
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


def set_platform(msg: bytes, platform: int) -> bytes:
    """The platform message with another platform byte, saying the same identity.

    Its data is 01 03 01 <platform> <id ^ (platform ^ 03), 4 bytes>: the sender's 4-byte identity, the one its member
    messages (0203, 0302, 0406) carry as it is, XORed with the platform byte ^ 03. Checked on both: a PC's id ^ 02
    (platform 01), a Switch's id ^ 23 (platform 20), each against the same sender's 0203 messages. So changing only
    the platform byte changes the identity the other side learns (by 0x21 per byte), and then nothing that player
    sends afterwards matches it: the id bytes have to change with it."""
    d = data_of(msg)
    flip = d[3] ^ platform
    return seal(d[:3] + bytes([platform]) + bytes(b ^ flip for b in d[4:8]))


def to_pc(msg: bytes) -> bytes:
    """A message from a Switch host, made the way a PC sends it (only the 12-byte platform message changes)"""
    if is_platform_msg(msg) and parse(msg)[1][4] != 0x01:
        return set_platform(msg, 0x01)
    return msg


def to_switch(msg: bytes) -> bytes:
    """A message from the PC game, made the way a Switch sends it (the platform message 0x01 -> 0x20)"""
    if is_platform_msg(msg) and parse(msg)[1][4] != 0x20:
        return set_platform(msg, 0x20)
    return msg


def identity(msg: bytes):
    """The sender's 4-byte identity from its platform message (None for any other message)"""
    if not is_platform_msg(msg):
        return None
    d = data_of(msg)
    return bytes(b ^ d[3] ^ 0x03 for b in d[4:8])


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

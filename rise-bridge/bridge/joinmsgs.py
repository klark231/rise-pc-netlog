"""The join messages a PC player's station sends, laid out as NOTES.md section 3 has them.

Every layout choice is tagged CERTAIN (seen with different values in two captures) or GUESS. Nothing here
has been run against a Switch host yet: tools/diff_join.py compares what this builds with a real capture,
field by field, which is how the GUESS entries should be settled.
"""
import socket
import struct

PROTOCOL_PAIRS = bytes.fromhex("1402 1803 1c00 2400 5803 6801 9401 a400")  # (type, version) x 8, as captured (CERTAIN: same in both)


def station(ip: str, port: int, sid: bytes, key: bytes, rand: bytes) -> bytes:
    """A member as 0x14 / 0x18 carry it, 0x44 bytes."""
    b = bytearray(0x44)
    b[0:4] = bytes.fromhex("02060000")        # GUESS: address family / length
    b[4:8] = socket.inet_aton(ip)              # CERTAIN
    b[8:10] = struct.pack(">H", port)          # CERTAIN
    b[0x10:0x18] = sid                         # CERTAIN
    b[0x18:0x1C] = key                         # CERTAIN: the packet header's key for this station
    b[0x1C:0x20] = rand                        # CERTAIN that it differs per station; what it means is unknown
    b[0x20:0x24] = bytes.fromhex("00000001")   # GUESS
    return bytes(b)


def connect_request(target_sid: bytes, target_key: bytes, me: bytes, session_id: bytes, name: str, seq: int) -> bytes:
    """0x14, first byte 01: 0x134 bytes. Offsets from NOTES; the name block (0x6e..0x12f) is a GUESS."""
    b = bytearray(0x134)
    b[0:3] = bytes.fromhex("010004")
    b[3:11] = target_sid
    b[11:15] = target_key
    b[0x0F] = 8
    b[0x10:0x20] = PROTOCOL_PAIRS
    b[0x20:0x22] = bytes.fromhex("0024")       # GUESS
    b[0x22:0x22 + 0x44] = me
    b[0x66:0x6A] = session_id[::-1]            # GUESS: "session ID little endian", so the 4 advertise bytes reversed
    b[0x6A:0x6E] = bytes.fromhex("01010101")
    n = name.encode("utf-8")[:0x20]
    b[0x6E] = 1                                # GUESS: "Hunter, twice, each with a 01 before"
    b[0x6F:0x6F + len(n)] = n
    b[0x8F] = 1
    b[0x90:0x90 + len(n)] = n
    b[0x130:0x134] = struct.pack("<I", seq)    # GUESS: endianness
    return bytes(b)


def connect_ack(seq: int) -> bytes:
    return bytes.fromhex("05000000") + struct.pack("<I", seq)  # CERTAIN layout, byte order GUESS


def session_ack(seq_plus_one: int) -> bytes:
    return bytes.fromhex("01fd") + struct.pack("<I", seq_plus_one)


def mesh_reply(slot_byte: int) -> bytes:
    """0x24 broadcast: 01 21, zeros, the host's per-session byte at 0x0c, 20 bytes."""
    b = bytearray(20)
    b[0:2] = bytes.fromhex("0121")
    b[0x0C] = slot_byte
    return bytes(b)


def clock_request(my_time8: bytes) -> bytes:
    return my_time8 + bytes(8)


# ---- the PC side's framing of a game message in a Steam message: u16 length, u32 length, both big endian ----

def steam_wrap(game_msg: bytes) -> bytes:
    return struct.pack(">HI", len(game_msg), len(game_msg)) + game_msg


def steam_unwrap(data: bytes):
    """The game message, or None for SteamConReq / SteamConAns and anything not framed this way."""
    if len(data) < 6 or data.startswith(b"SteamCon"):
        return None
    n = struct.unpack(">H", data[:2])[0]
    if n + 6 != len(data) or struct.unpack(">I", data[2:6])[0] != n:
        return None
    return data[6:]

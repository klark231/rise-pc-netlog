"""Pia packets as the captures show them (analysis/NOTES.md section 3): build, encrypt, decrypt, parse.

Nothing here knows how the session key is made. Give PiaCrypto the key the hosting port logged
("# AES key ..."); see README.md for how to get it to a bridge.

Fields marked (guess) are not settled by a capture yet.
"""
import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional

MAGIC = b"\x32\xab\x98\x64"
VERSION_ENCRYPTED = 0x89
HEADER = 0x20

# protocol types seen in the captures
T_LEAVE, T_CONNECT, T_SESSION, T_CLOCK, T_MESH, T_KEEPALIVE, T_GAME = 0x08, 0x14, 0x18, 0x1C, 0x24, 0x58, 0x68


def station_id(mac: bytes) -> bytes:
    """8-byte station ID from a MAC: bytes 2, 4, 5, 3, 1, 0, then two zeros (certain, from NOTES)."""
    return bytes([mac[2], mac[4], mac[5], mac[3], mac[1], mac[0], 0, 0])


@dataclass
class Message:
    ptype: int
    payload: bytes
    port: int = 0
    flags: int = 0
    dst: int = 0


def build_body(messages: List[Message]) -> bytes:
    """A message list: field mask, the fields that differ from the message before, payload padded to 4, 0xff at the end."""
    out = bytearray()
    prev = {"flags": 0, "size": 0, "ptype": 0, "port": 0, "dst": 0}
    for first, m in enumerate(messages):
        first = first == 0
        cur = {"flags": m.flags, "size": len(m.payload), "ptype": m.ptype, "port": m.port, "dst": m.dst}
        mask = 0
        fields = bytearray()
        if cur["flags"] != prev["flags"]:
            mask |= 1
            fields.append(cur["flags"])
        if cur["size"] != prev["size"]:
            mask |= 2
            fields += struct.pack(">H", cur["size"])
        if (cur["ptype"], cur["port"]) != (prev["ptype"], prev["port"]):
            mask |= 4
            fields.append(cur["ptype"])
            fields += cur["port"].to_bytes(3, "big")
        if cur["dst"] != prev["dst"]:
            mask |= 8
            fields += struct.pack(">Q", cur["dst"])
        if first:
            # CERTAIN (every packet of a capture): the first message has mask 0x7f with all four fields written.
            # Bits 0x10, 0x20, 0x40 add no bytes in anything captured; later messages' masks are still unchecked.
            mask = 0x7F
            fields = bytearray([cur["flags"]]) + struct.pack(">H", cur["size"]) + bytes([cur["ptype"]]) \
                + cur["port"].to_bytes(3, "big") + struct.pack(">Q", cur["dst"])
        out.append(mask)
        out += fields
        out += m.payload
        while len(out) % 4:  # padding is to 4 from the start of the body, as rise_net.py reads it
            out.append(0)
        prev = cur
    out.append(0xFF)
    return bytes(out)


def parse_body(pt: bytes) -> List[Message]:
    i, prev, out = 0, {"flags": 0, "size": 0, "ptype": 0, "port": 0, "dst": 0}, []
    while i < len(pt):
        mask = pt[i]
        i += 1
        if mask == 0xFF:
            break
        m = dict(prev)
        if mask & 1:
            m["flags"] = pt[i]; i += 1
        if mask & 2:
            m["size"] = struct.unpack(">H", pt[i:i + 2])[0]; i += 2
        if mask & 4:
            m["ptype"] = pt[i]; m["port"] = int.from_bytes(pt[i + 1:i + 4], "big"); i += 4
        if mask & 8:
            m["dst"] = struct.unpack(">Q", pt[i:i + 8])[0]; i += 8
        out.append(Message(m["ptype"], bytes(pt[i:i + m["size"]]), m["port"], m["flags"], m["dst"]))
        i = (i + m["size"] + 3) & ~3
        prev = m
    return out


@dataclass
class Header:
    receiver_key: bytes   # 4 bytes, zeros when the packet goes to several
    sender_key: bytes     # 4 bytes
    counter: int          # u16 per receiver (byte order: guess, big endian)
    trailer: bytes        # 2 bytes per receiver: low 16 bits of each key (order: guess)
    nonce_counter: bytes  # header 0x10..0x17, counts up


class PiaCrypto:
    def __init__(self, key: bytes, session_id: bytes):
        assert len(key) == 16 and len(session_id) == 4
        self.key, self.session_id = key, session_id

    def nonce(self, sender_mac: bytes, header: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(self.session_id + sender_mac))[:3]
        return crc + bytes([header[0x0C]]) + header[0x10:0x18]

    def seal(self, body: bytes, sender_mac: bytes, h: Header) -> bytes:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        head = bytearray(HEADER)
        head[0:4] = MAGIC
        head[4] = VERSION_ENCRYPTED
        head[5:9] = h.receiver_key
        head[9:13] = h.sender_key
        head[13:15] = struct.pack(">H", h.counter)
        head[15] = len(h.trailer)
        head[0x10:0x18] = h.nonce_counter
        enc = Cipher(algorithms.AES(self.key), modes.GCM(self.nonce(sender_mac, bytes(head)))).encryptor()
        ct = enc.update(body) + enc.finalize()
        head[0x18:0x20] = enc.tag[:8]  # an 8-byte tag is the first 8 bytes of the full one
        return bytes(head) + ct + h.trailer

    def open(self, packet: bytes, sender_mac: bytes) -> Optional[bytes]:
        """The body, or None if the tag is wrong or it isn't an encrypted Pia packet."""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        if len(packet) < HEADER or not packet.startswith(MAGIC) or not packet[4] & 0x80:
            return None
        tail = packet[0x0F]
        dec = Cipher(algorithms.AES(self.key),
                     modes.GCM(self.nonce(sender_mac, packet), packet[0x18:0x20], min_tag_length=8)).decryptor()
        try:
            pt = dec.update(packet[HEADER:len(packet) - tail])
            dec.finalize()
        except Exception:
            return None
        return pt

"""A Pia station for one PC player: joins a hub as a bridge, plays the joiner's side of the Pia join, then carries
game messages (type 0x68) in and out.

NOT RUN AGAINST A REAL HOST YET. What the captures settle is marked CERTAIN; the rest GUESS. The conventions that
tools/header_fields.py reads out of a capture are in Conventions: run it and set them before the first real join.
"""
import os
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from . import joinmsgs
from .hublink import Link, NetInfo
from .pia import (Header, Message, PiaCrypto, T_CLOCK, T_CONNECT, T_GAME, T_KEEPALIVE, T_LEAVE, T_MESH, T_SESSION,
                  build_body, parse_body, station_id)

PORT = 12345  # CERTAIN: every station's address in the captures ends in :12345


@dataclass
class Conventions:
    counter_order: str = "big"      # CERTAIN (second capture): the u16 counter counts up in its second byte
    nonce_order: str = "big"        # CERTAIN: the 8-byte nonce counter counts up in its last byte
    trailer: str = "k24"            # CERTAIN (3428 of 3428 in the second capture): key[2:4], as is
    ticks_per_second: int = 19_200_000  # CERTAIN: the keepalives' time advances by this much a second (second capture)


class Station:
    def __init__(self, link: Link, conv: Optional[Conventions] = None, log: Callable[[str], None] = print):
        self.link, self.conv, self.log = link, conv or Conventions(), log
        self.key = os.urandom(4)       # GUESS: this station's key is just random
        self.rand = os.urandom(4)
        self.crypto: Optional[PiaCrypto] = None
        self.peer_keys: Dict[int, bytes] = {}    # address -> the key in the packets it sends (CERTAIN: header 0x09..0x0c)
        self.counters: Dict[int, int] = {}
        self.nonce = int.from_bytes(os.urandom(8), "big") & ((1 << 63) - 1)  # the real ones start at random 8-byte values
        self.state = "waiting"                    # waiting -> requested -> in
        self.clock_offset: Optional[int] = None  # host ticks - ours, once the host has sent a keepalive
        self.host_ack4: Optional[bytes] = None
        self.on_game: Callable[[int, bytes], None] = lambda addr, payload: None
        self.on_leave: Callable[[int], None] = lambda addr: None
        self.ack_seq = 0
        link.on_data = self._on_data

    # ---- setup ----
    def start(self, key_timeout: float = 10.0) -> None:
        t = time.time() + key_timeout
        while self.link.key is None and time.time() < t:
            time.sleep(0.05)
        if self.link.key is None:
            raise RuntimeError("the host didn't send Pia's key: it needs netlog3.patch and Capture Local Play on at start-up")
        self.crypto = PiaCrypto(self.link.key, self.link.info.pia_session_id)
        threading.Thread(target=self._keepalives, daemon=True).start()
        self.log("station %08x ready as %s" % (self.link.address, self.link.mac.hex(":")))

    def _macs(self) -> Dict[int, bytes]:
        return {n["address"]: n["mac"] for n in self.link.info.nodes()}

    def _host(self):
        for n in self.link.info.nodes():
            if n["node"] == 0:
                return n["address"], n["mac"]
        return None, None

    # ---- sending ----
    def _trailer_entry(self, key: bytes) -> bytes:
        c = self.conv.trailer
        part = key[0:2] if c.startswith("k02") else key[2:4]
        return part[::-1] if c.endswith("r") else part

    def send(self, dst: int, messages) -> None:
        if self.crypto is None:
            return
        broadcast = (dst & 0xFF) == 0xFF
        if broadcast:  # CERTAIN: receiver key 0, the trailer lists each receiver
            rkey = bytes(4)
            trailer = b"".join(self._trailer_entry(k) for a, k in self.peer_keys.items() if a != self.link.address)
            counter = 0
        else:
            # CERTAIN (3 real captures, ~20000 packets): the receiver key is ZERO for the join-time messages
            # (0x24 reply, 0x14 request "01"/"02", 0x18, 0x58) and the peer's key for the rest (0x14 ack "05",
            # 0x1c, 0x68, 0x08). A request with the host's key in it is what the host ignored.
            zero = all(m.ptype in (T_MESH, T_SESSION, T_KEEPALIVE) or
                       (m.ptype == T_CONNECT and m.payload[:1] in (b"\x01", b"\x02")) for m in messages)
            rkey = bytes(4) if zero else self.peer_keys.get(dst, bytes(4))
            trailer = b""
            counter = self.counters[dst] = (self.counters.get(dst, 0) + 1) & 0xFFFF
        self.nonce += 1
        h = Header(rkey, self.key, counter, trailer, self.nonce.to_bytes(8, self.conv.nonce_order))
        # counter_order is applied by Header's packing (big endian); flip here if the capture says little
        pkt = self.crypto.seal(build_body(messages), self.link.mac, h)
        if self.conv.counter_order == "little":
            pkt = pkt[:13] + struct.pack("<H", counter) + pkt[15:]  # NOTE: this breaks nothing: the counter isn't in the nonce
        self.link.send(PORT, dst, PORT, pkt)

    def _node_of(self, addr: int) -> int:
        for n in self.link.info.nodes():
            if n["address"] == addr:
                return n["node"]
        return 0

    def msg(self, ptype: int, payload: bytes, to: int = 0) -> Message:
        """A message with the flags and destination its type uses (CERTAIN, second capture, every sender):
        0x24 flags 0x11 dst 0; 0x14 and 0x18 to the host dst 0; 0x58 dst 0xffffffff; 0x1c, 0x68, 0x08 dst = 1 << node."""
        flags = 0x11 if ptype == T_MESH else 1
        if ptype == T_KEEPALIVE:
            dst = 0xFFFFFFFF
        elif ptype in (T_CLOCK, T_GAME, T_LEAVE):
            dst = 1 << self._node_of(to)
        else:
            dst = 0
        return Message(ptype, payload, port=0, flags=flags, dst=dst)

    def send_game(self, dst: int, payload: bytes) -> None:
        self.send(dst, [self.msg(T_GAME, payload, dst)])

    def _ticks(self) -> int:
        return int(time.monotonic() * self.conv.ticks_per_second) + (self.clock_offset or 0)

    def _keepalives(self) -> None:
        while self.link.sock is not None and self.link.sock.fileno() != -1:
            host, _ = self._host()
            if self.state == "requested" and host and self.host_ack4 is None and getattr(self, "req_pkt", None):
                self.send(host, [self.msg(T_CONNECT, self.req_pkt)])  # a real joiner resends about every 0.5 s
            if self.state == "in" and host and self.clock_offset is not None:
                # u32 0, the time as 5 bytes of 19.2 MHz ticks, u32 0 (the plain keepalive in both captures)
                self.send(host, [self.msg(T_KEEPALIVE, bytes(4) + (self._ticks() & (2 ** 40 - 1)).to_bytes(5, "big") + bytes(4))])
            time.sleep(0.5)

    # ---- receiving ----
    def _on_data(self, src: int, sport: int, dport: int, data: bytes) -> None:
        mac = self._macs().get(src)
        if self.crypto is None or mac is None:
            self.log("ignored packet from %08x (%s)" % (src, "no key yet" if self.crypto is None else "no node with that address"))
            return
        body = self.crypto.open(data, mac)
        if body is None:
            self.log("bad tag from %08x" % src)
            return
        self.peer_keys[src] = bytes(data[9:13])
        for m in parse_body(body):
            if m.ptype != T_KEEPALIVE:  # trace everything but keepalives, to see where the join stops
                line = "rx %08x type 0x%02x len %d [%s] %s" % (src, m.ptype, len(m.payload), self.state, m.payload[:16].hex())
                if line == getattr(self, "_last_rx", None):  # the host repeats the same message: count, don't print
                    self._rx_repeats = getattr(self, "_rx_repeats", 0) + 1
                    if self._rx_repeats in (10, 100, 1000):
                        self.log("  ... same message again, %d times so far" % self._rx_repeats)
                else:
                    self._last_rx, self._rx_repeats = line, 0
                    self.log(line)
            self._message(src, m)

    def _message(self, src: int, m: Message) -> None:
        host, host_mac = self._host()
        p = m.payload
        if src != host:
            if m.ptype == T_GAME:
                self.on_game(src, p)
            elif m.ptype == T_LEAVE:
                self.on_leave(src)
            return
        if m.ptype == T_MESH and p[:2] == bytes.fromhex("0111") and self.state == "waiting":
            # the host's station list: answer it, then ask the host to connect us
            self.send((self.link.address & 0xFFFFFF00) | 0xFF, [self.msg(T_MESH, joinmsgs.mesh_reply(p[0x0C]))])
            me = joinmsgs.station(".".join(str(self.link.address >> s & 255) for s in (24, 16, 8, 0)), PORT,
                                  station_id(self.link.mac), self.key, self.rand)
            req = joinmsgs.connect_request(station_id(host_mac), self.peer_keys[host], me,
                                           self.link.info.pia_session_id, self.link.name, int.from_bytes(os.urandom(4), "little"))
            self.send(host, [self.msg(T_CONNECT, req)])
            self.req_pkt, self.req_sent = req, time.time()
            self.state = "requested"
            self.log("sent the join request")
        elif m.ptype == T_CONNECT and p[:3] == bytes.fromhex("020004") and len(p) >= 8:
            self.host_seq = p[-4:]
            self.send(host, [self.msg(T_CONNECT, joinmsgs.connect_ack(p[-4:]))])  # CERTAIN: its last 4 bytes, unchanged
        elif m.ptype == T_CONNECT and p[:4] == bytes.fromhex("05000000") and len(p) == 8:
            self.host_ack4 = p[4:8]
            self.send(host, [self.msg(T_SESSION, joinmsgs.session_ack_for(p[4:8]))])
        elif m.ptype == T_SESSION and p[:1] == b"\x02" and getattr(self, "host_seq", None):
            # CERTAIN (3 captures): the joiner acks the host's number + 1 for this message, each time it arrives
            nxt = ((int.from_bytes(self.host_seq, "big") + 1) & 0xFFFFFFFF).to_bytes(4, "big")
            self.send(host, [self.msg(T_CONNECT, joinmsgs.connect_ack(nxt))])
            if self.state == "requested":
                self.state = "in"
                self.log("in the session")
        elif m.ptype == T_KEEPALIVE and len(p) == 13:
            host_ticks = int.from_bytes(p[4:9], "big")
            self.clock_offset = (host_ticks - int(time.monotonic() * self.conv.ticks_per_second)) & (2 ** 40 - 1)
            if self.state == "in" and not getattr(self, "_clock_sent", False):
                self._clock_sent = True
                self.send(host, [self.msg(T_CLOCK, self._ticks().to_bytes(8, "big") + bytes(8), host)])
        elif m.ptype == T_GAME:
            self.on_game(src, p)
        elif m.ptype == T_LEAVE:
            self.on_leave(src)

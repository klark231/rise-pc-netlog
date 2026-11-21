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
        self.verbose = False
        self._first = True
        self._pending = None      # the join messages to repeat until the host acks (the real joiner repeats them ~every 0.4 s)
        self._pending_dst = 0
        self.key = os.urandom(4)       # GUESS: this station's key is just random
        self.rand = os.urandom(4)
        self.crypto: Optional[PiaCrypto] = None
        self.peer_keys: Dict[int, bytes] = {}    # address -> the key in the packets it sends (CERTAIN: header 0x09..0x0c)
        self.counters: Dict[int, int] = {}
        self.nonce = int.from_bytes(os.urandom(8), "big") & ((1 << 63) - 1)  # the real ones start at random 8-byte values
        self.state = "waiting"                    # waiting -> requested -> in
        self.clock_offset: Optional[int] = None  # host ticks - ours, once the host has sent a keepalive
        self.host_ack4: Optional[bytes] = None
        self.host_hello: Optional[bytes] = None   # the 8 bytes of the hello the host sent us: its value for OUR mac
        self.hello_seen = threading.Event()
        self.hello_to_send: Optional[bytes] = None  # 8 bytes: the hello value the host expects for ITS mac
        self._hello_template: Optional[bytes] = None  # the last 15-byte hello the host sent: its 3-byte prefix and scramble byte are reused
        self.hello_msg: Optional[bytes] = None   # the complete 15-byte hello to send (bridge/hello.py hello_message_for_mac)
        self.hello_answered = False
        self.echo = False                # answer the host's 12/9/8-byte game messages by sending the same bytes back (what the captured joiner does for 9 and 8)
        self._seen_game = {}
        self._rx_counts = {}
        self._echoed_at = {}
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
    def _trailer(self) -> bytes:
        """CERTAIN (second capture): key[2:4] of every member in node order, this station included."""
        keys = dict(self.peer_keys)
        keys[self.link.address] = self.key
        return b"".join(keys[a][2:4] for a in sorted(keys, key=self._node_of))

    def send(self, dst: int, messages, kind: str = "data") -> None:
        """kind, as the captured joiner does it (all unicast to the host):
        join      receiver key 0, counter 0   (0x24 reply, 0x14 request, 0x18 01fd)
        ack       receiver key = the host's, counter 0   (the 8-byte 0x14 ack)
        keepalive receiver key 0, trailer = all members' keys, counter 0   (0x58)
        data      receiver key = the host's, counter counts up   (0x1c, 0x68, 0x08)"""
        if self.crypto is None:
            return
        rkey, trailer, counter = bytes(4), b"", 0
        if kind in ("ack", "data"):
            rkey = self.peer_keys.get(dst, bytes(4))
        if kind == "keepalive":
            trailer = self._trailer()
        if kind == "data":
            counter = self.counters[dst] = (self.counters.get(dst, 0) + 1) & 0xFFFF
        sender_key = bytes(4) if self._first else self.key  # CERTAIN: the very first packet has sender key 0
        self._first = False
        self.nonce += 1
        h = Header(rkey, sender_key, counter, trailer, self.nonce.to_bytes(8, self.conv.nonce_order))
        self.link.send(PORT, dst, PORT, self.crypto.seal(build_body(messages), self.link.mac, h))

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
        self.send(dst, [self.msg(T_GAME, payload, dst)], "data")

    def _make_hello(self, value: bytes) -> bytes:
        """The 15-byte hello: 3 bytes (copied from the host's), then 00 01 03 02 + the 8-byte value, each xor-ed with the byte at 3
        (the scramble byte, also copied; its own scrambled form is that byte itself). GUESS: that the 3 prefix bytes aren't checked."""
        t = self._hello_template
        k = t[3]
        return t[:3] + bytes(b ^ k for b in bytes.fromhex("00010302") + value)

    def _ticks(self) -> int:
        return int(time.monotonic() * self.conv.ticks_per_second) + (self.clock_offset or 0)

    def _keepalives(self) -> None:
        while self.link.sock is not None and self.link.sock.fileno() != -1:
            host, _ = self._host()
            if self.state == "in" and host and self.clock_offset is not None:
                # u32 0, the time as 5 bytes of 19.2 MHz ticks, u32 0 (the plain keepalive in both captures)
                self.send(host, [self.msg(T_KEEPALIVE, bytes(4) + (self._ticks() & (2 ** 40 - 1)).to_bytes(5, "big") + bytes(4))], "keepalive")
            if self.state == "in" and host and not self.hello_answered:
                hello = self.hello_msg or (self._make_hello(self.hello_to_send) if self.hello_to_send and self._hello_template else None)
                if hello:
                    self.send(host, [self.msg(T_GAME, hello, host)], "data")
            if self.state == "requested" and self._pending:
                for m in self._pending:
                    self.send(self._pending_dst, [m], "join")
            time.sleep(0.4)

    # ---- receiving ----
    def _on_data(self, src: int, sport: int, dport: int, data: bytes) -> None:
        mac = self._macs().get(src)
        if self.crypto is None or mac is None:
            return
        body = self.crypto.open(data, mac)
        if body is None:
            self.log("bad tag from %08x (%d bytes)" % (src, len(data)))
            return
        self.peer_keys[src] = bytes(data[9:13])
        for m in parse_body(body):
            if self.verbose and m.ptype != T_KEEPALIVE:
                kk = (src, m.ptype, len(m.payload), m.payload[:6])
                n = self._rx_counts[kk] = self._rx_counts.get(kk, 0) + 1
                if n == 1:  # the first time only; the host repeats most of them many times
                    self.log("rx from %08x: type 0x%02x, %d bytes, starts %s" % (src, m.ptype, len(m.payload), m.payload[:6].hex()))
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
            # the host's station list: answer it (unicast to the host, as the captured joiner does), then ask to connect
            reply = self.msg(T_MESH, joinmsgs.mesh_reply(p[0x0C]))
            me = joinmsgs.station(".".join(str(self.link.address >> s & 255) for s in (24, 16, 8, 0)), PORT,
                                  station_id(self.link.mac), self.key, self.rand)
            req = joinmsgs.connect_request(station_id(host_mac), self.peer_keys[host], me,
                                           self.link.info.pia_session_id, self.link.name, int.from_bytes(os.urandom(4), "little"))
            self._pending = [reply, self.msg(T_CONNECT, req)]
            self._pending_dst = host
            for pm in self._pending:
                self.send(host, [pm], "join")
            self.state = "requested"
            self.log("sent the join request (repeated until the host acks)")
        elif m.ptype == T_CONNECT and p[:4] == bytes.fromhex("05000000") and len(p) == 8:
            self.host_ack4 = p[4:8]
            self._pending = None  # the host has our request
            self.send(host, [self.msg(T_SESSION, joinmsgs.session_ack_for(p[4:8]))], "join")
        elif m.ptype == T_CONNECT and p[:3] == bytes.fromhex("020004") and len(p) >= 8:
            self.send(host, [self.msg(T_CONNECT, joinmsgs.connect_ack(p[-4:]))], "ack")  # CERTAIN: its last 4 bytes, unchanged
        elif m.ptype == T_SESSION and p[:1] == b"\x20" and len(p) > 500 and not self.hello_answered:
            if self.hello_to_send or self.hello_msg:
                self.hello_answered = True
                self.log("the host moved on after our hello (0x18, %d bytes)" % len(p))
        elif m.ptype == T_SESSION and p[:1] == b"\x02" and self.state == "requested":
            self.state = "in"  # GUESS: that this (0x18 starting 02, 156 bytes) is "you're in"; the host repeats it
            self.log("in the session")
        elif m.ptype == T_KEEPALIVE and len(p) == 13:
            host_ticks = int.from_bytes(p[4:9], "big")
            self.clock_offset = (host_ticks - int(time.monotonic() * self.conv.ticks_per_second)) & (2 ** 40 - 1)
            if self.state == "in" and not getattr(self, "_clock_sent", False):
                self._clock_sent = True
                self.send(host, [self.msg(T_CLOCK, self._ticks().to_bytes(8, "big") + bytes(8), host)], "data")
        elif m.ptype == T_GAME:
            if len(p) == 15:  # the hello: 3 bytes, then a body xor-ed with byte 3 (rise_net.unscramble)
                body = bytes(b ^ p[3] for b in p[3:])
                if body[:4] == bytes.fromhex("00010302"):
                    self._hello_template = bytes(p)
                    self.host_hello = body[4:12]
                    self.hello_seen.set()
            if p not in self._seen_game:
                self._seen_game[p] = time.time()
                if self.verbose:
                    k = p[3] if len(p) > 3 else 0
                    self.log("NEW game message from the host: %d bytes, plain %s" % (len(p), bytes(b ^ k for b in p[3:]).hex()))
            if self.echo and len(p) in (8, 9, 12) and src == host and time.time() - self._echoed_at.get(p, 0) > 0.3 \
                    and self.state == "in":
                self._echoed_at[p] = time.time()
                self.send_game(host, p)
            self.on_game(src, p)
        elif m.ptype == T_LEAVE:
            self.on_leave(src)

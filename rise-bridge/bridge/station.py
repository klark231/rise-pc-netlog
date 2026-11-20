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
    counter_order: str = "big"      # GUESS: the u16 counter's byte order (header_fields.py item 2)
    nonce_order: str = "big"        # GUESS: the 8-byte nonce counter's byte order
    trailer: str = "k24"            # GUESS: which 2 bytes of a receiver's key go in the trailer: k02 k24 k02r k24r (item 1)
    game_port: int = 0              # GUESS: header_fields.py item 3
    game_flags: int = 0
    game_dst: int = 0


class Station:
    def __init__(self, link: Link, conv: Optional[Conventions] = None, log: Callable[[str], None] = print):
        self.link, self.conv, self.log = link, conv or Conventions(), log
        self.key = os.urandom(4)       # GUESS: this station's key is just random
        self.rand = os.urandom(4)
        self.crypto: Optional[PiaCrypto] = None
        self.peer_keys: Dict[int, bytes] = {}    # address -> the key in the packets it sends (CERTAIN: header 0x09..0x0c)
        self.counters: Dict[int, int] = {}
        self.nonce = int.from_bytes(os.urandom(2), "big")
        self.state = "waiting"                    # waiting -> requested -> in
        self.last_keepalive: Optional[bytes] = None
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
            rkey = self.peer_keys.get(dst, bytes(4))
            trailer = b""
            counter = self.counters[dst] = (self.counters.get(dst, 0) + 1) & 0xFFFF
        self.nonce += 1
        h = Header(rkey, self.key, counter, trailer, self.nonce.to_bytes(8, self.conv.nonce_order))
        # counter_order is applied by Header's packing (big endian); flip here if the capture says little
        pkt = self.crypto.seal(build_body(messages), self.link.mac, h)
        if self.conv.counter_order == "little":
            pkt = pkt[:13] + struct.pack("<H", counter) + pkt[15:]  # NOTE: this breaks nothing: the counter isn't in the nonce
        self.link.send(PORT, dst, PORT, pkt)

    def send_game(self, dst: int, payload: bytes) -> None:
        c = self.conv
        self.send(dst, [Message(T_GAME, payload, port=c.game_port, flags=c.game_flags, dst=c.game_dst)])

    def _keepalives(self) -> None:
        while self.link.sock is not None and self.link.sock.fileno() != -1:
            host, _ = self._host()
            if self.state == "in" and host and self.last_keepalive:
                # GUESS: the host takes a replay of what it last sent; the 13 bytes' meaning isn't worked out
                self.send(host, [Message(T_KEEPALIVE, self.last_keepalive)])
            time.sleep(0.5)

    # ---- receiving ----
    def _on_data(self, src: int, sport: int, dport: int, data: bytes) -> None:
        mac = self._macs().get(src)
        if self.crypto is None or mac is None:
            return
        body = self.crypto.open(data, mac)
        if body is None:
            self.log("bad tag from %08x" % src)
            return
        self.peer_keys[src] = bytes(data[9:13])
        for m in parse_body(body):
            self._message(src, m)

    def _message(self, src: int, m: Message) -> None:
        host, host_mac = self._host()
        p = m.payload
        if m.ptype == T_MESH and p[:2] == bytes.fromhex("0111") and self.state == "waiting" and src == host:
            # the host's station list: answer it, then ask the host to connect us
            self.send((self.link.address & 0xFFFFFF00) | 0xFF, [Message(T_MESH, joinmsgs.mesh_reply(p[0x0C]))])
            me = joinmsgs.station(".".join(str(self.link.address >> s & 255) for s in (24, 16, 8, 0)), PORT,
                                  station_id(self.link.mac), self.key, self.rand)
            req = joinmsgs.connect_request(station_id(host_mac), self.peer_keys[host], me,
                                           self.link.info.pia_session_id, self.link.name, int.from_bytes(os.urandom(4), "little"))
            self.send(host, [Message(T_CONNECT, req)])
            self.state = "requested"
            self.log("sent the join request")
        elif m.ptype == T_CONNECT and p[:3] == bytes.fromhex("020004") and len(p) >= 0x134 and src == host:
            self.ack_seq = struct.unpack("<I", p[0x130:0x134])[0]  # GUESS: that this is the number the capture's ack echoes
            self.send(host, [Message(T_CONNECT, joinmsgs.connect_ack(self.ack_seq))])
            self.send(host, [Message(T_SESSION, joinmsgs.session_ack((self.ack_seq + 1) & 0xFFFFFFFF))])
        elif m.ptype == T_SESSION and p[:2] == bytes.fromhex("0203") and self.state == "requested":
            self.state = "in"
            self.send(host, [Message(T_CLOCK, joinmsgs.clock_request(struct.pack("<Q", int(time.time() * 1000))))])
            self.log("in the session")
        elif m.ptype == T_KEEPALIVE:
            self.last_keepalive = p
        elif m.ptype == T_GAME:
            self.on_game(src, p)
        elif m.ptype == T_LEAVE:
            self.on_leave(src)

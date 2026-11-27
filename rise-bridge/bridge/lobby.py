"""The lobby channel (03 01), played by the bridge on both sides instead of passed through.

PC online and Switch Local Play run different lobbies over this channel (analysis/LOBBY.md):
  PC:     the joiner sends record 01 (its Steam ID); the host answers 02 (session), 08 (its Steam auth ticket), one 03 per
          other member, 05 (end); the joiner sends its own 08; then both send 07 every half second.
  Switch: the host sends one record with the room description; the joiner only acknowledges it.
So the bridge is the PC host toward the PC game (PcLobby) and a Switch joiner toward the port host (SwitchLobby), and
neither side's lobby messages cross. Each side keeps its own numbering.

Records start 03 00 <type>. A message carries every record the other side hasn't acknowledged yet (that's how both
games resend), and its ack is the last record number received.
"""
import os
import struct
import threading
import time

from . import wire

T_JOIN, T_SESSION, T_MEMBER, T_END, T_PING, T_TICKET = 1, 2, 3, 5, 7, 8
PING = b"\x03\x00\x07\x00"


def rec(t: int, body: bytes = b"") -> bytes:
    return bytes((0x03, 0x00, t)) + body


def fake_ticket(sid: int) -> bytes:
    """A Steam auth session ticket's layout (234 bytes, as in the PC captures) for the made-up host: its Steam ID, app
    480, now, and no signature. The PC's DLL answers the game's BeginAuthSession for this ID itself, so Steam never
    sees it."""
    t = bytearray(234)
    struct.pack_into("<I", t, 0, 0x14)
    t[4:12] = os.urandom(8)                                  # GC token (new each time on a real one)
    struct.pack_into("<QI", t, 12, sid, int(time.time()))
    struct.pack_into("<III", t, 24, 0x18, 1, 2)
    struct.pack_into("<III", t, 52, 0xB2, 0x32, 4)           # the ownership ticket: length, then the same as every real one
    struct.pack_into("<QI", t, 64, sid, 480)
    t[48] = 5                                                # a small count (5 in the real ones looked at)
    t[95:106] = bytes.fromhex("6b01000000000000000000")    # constant in all 19 real ones
    return bytes(t)


class PcLobby:
    """The PC host's side of the lobby, toward the PC game."""

    def __init__(self, host_sid: int, send, log=print, index: int = 3, quest: bool = False):
        self.host_sid, self.send, self.log = host_sid, send, log
        self.index = index  # the PC's player slot, the one the Switch host gave our station
        self.host_id = self.pc_id = None   # the 4-byte ids of the two games (from the platform messages)
        self.next_seq, self.unacked, self.last_rx = 1, [], 0
        self.answered = False
        self.quest = quest  # answering a quest lobby's join: set from the start for a lobby of its own channel, or by from_pc
        self.lock = threading.Lock()

    def ids(self, host_id: bytes, pc_id: bytes) -> None:
        self.host_id, self.pc_id = host_id, pc_id

    def _queue(self, record: bytes) -> None:
        self.unacked.append((self.next_seq, record))
        self.next_seq = (self.next_seq + 1) & 0xFFFF

    def _flush(self) -> None:
        if self.host_id is None or self.pc_id is None:
            return
        payload = wire.build(wire.LOBBY, self.host_id, self.pc_id, self.last_rx, self.unacked[-16:])
        self.send(wire.encode(payload))

    def from_pc(self, payload: bytes) -> None:
        p = wire.parse(payload)
        if p is None:
            return
        _, sender, receiver, ack, recs = p
        with self.lock:
            if self.pc_id is None:
                self.pc_id, self.host_id = sender, receiver
            # what the PC has acknowledged goes (record numbers wrap at 16 bits)
            self.unacked = [(s, r) for s, r in self.unacked if 0 < ((s - ack) & 0xFFFF) < 0x8000]
            for seq, r in recs:
                if seq == 1 and self.answered and r[:3] == bytes([3, 0, T_JOIN]):
                    # A join from the start again: the PC joining a quest's lobby (the plugin's, standing for this same
                    # session). Its numbering starts over, as it did between two PCs.
                    self.next_seq, self.unacked, self.last_rx = 1, [], 0
                    self.answered, self.quest = False, True
                if ((seq - self.last_rx) & 0xFFFF) == 0 or ((seq - self.last_rx) & 0xFFFF) > 0x8000:
                    continue  # had it already
                self.last_rx = seq
                if len(r) >= 3 and r[:2] == b"\x03\x00":
                    self._record(r)
            self._flush()

    def _record(self, r: bytes) -> None:
        t = r[2]
        if t == T_JOIN and not self.answered:
            self.answered = True
            sid = struct.pack(">Q", self.host_sid)
            # 02: the joiner's player slot (u64: a PC joining a PC host alone got 1 and set its lobby Index to 1; with 3
            # here it called itself player 3 while the Switch had it as player 1, so the Switch's copy of its hunter,
            # L_Pl1_..., never got the state the PC sent for L_Pl3_... and stayed invisible), the host's Steam ID, 4
            # bytes that stay the same for a host (meaning unknown; its lobby id here)
            self._queue(rec(T_SESSION, struct.pack(">Q", self.index) + sid + self.host_id))
            # 08: the host's Steam ID, u64 and u16 ticket length, the ticket (none in a quest's lobby, as between PCs)
            if self.quest:
                self._queue(rec(T_TICKET, sid + struct.pack(">QH", 0, 0)))
            else:
                self._queue(rec(T_TICKET, sid + struct.pack(">QH", 234, 234) + fake_ticket(self.host_sid)))
            self._queue(rec(T_END))
            self.log("[lobby] the PC asked to join %s: answered as its host (session as player %d, ticket, end of members)"
                     % ("the quest" if self.quest else "the room", self.index))
        elif t == T_TICKET:
            self.log("[lobby] the PC sent its ticket")

    def tick(self) -> None:
        """Every half second once the PC is in: a keep-alive record, and whatever it hasn't acknowledged again"""
        with self.lock:
            if self.answered:
                self._queue(PING)
                self._flush()


class SwitchLobby:
    """A Switch joiner's side of the lobby, toward the port host: acknowledge whatever it sends."""

    def __init__(self, send, log=print):
        self.send, self.log = send, log
        self.last_rx = 0
        self.room = None

    def from_host(self, payload: bytes) -> None:
        p = wire.parse(payload)
        if p is None:
            return
        _, sender, receiver, _, recs = p
        for seq, r in recs:
            self.last_rx = seq
            if self.room is None and len(r) > 13:
                self.room = r
                self.log("[lobby] the host sent its room (%d bytes): acknowledged" % len(r))
        self.send(wire.encode(wire.build(wire.LOBBY, receiver, sender, self.last_rx)))

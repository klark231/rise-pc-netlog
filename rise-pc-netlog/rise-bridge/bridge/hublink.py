"""A client for the port's hub servers and links (the protocol in mhrise-recomp's runtime/src/nnsdk/ldn.cpp header).

Frames: u32 size (of what follows), u8 type, payload; little endian. Used for both the hub server and the
link to the host once the server has spliced you to it.
"""
import hashlib
import socket
import struct
import threading
from typing import Callable, List, Optional, Tuple

SERVER_PROTOCOL = 1
LINK_PROTOCOL = 0x5201  # MH Rise's hubs
LINK_VERSION = 1
INFO_SIZE = 0x480

# server -> / <- types
LIST, HOST, ATTACH, JOIN, UPDATE, PING = 1, 2, 3, 4, 5, 6
HUBS, HOSTED, INCOMING, SPLICED, ERROR = 16, 17, 18, 19, 20
# link types
HELLO, WELCOME, INFO, DATA, BYE, LINK_PING, REJECT, KEY = 1, 2, 3, 4, 5, 6, 7, 8

# NetworkInfo offsets
NI_SESSION_ID, NI_SEC_PARAM, NI_NODE_MAX, NI_NODE_COUNT, NI_NODES, NI_ADV_SIZE, NI_ADV = 0x10, 0x50, 0x66, 0x67, 0x68, 0x26A, 0x26C
NODE_SIZE = 0x40


def room_of_key(key: str) -> bytes:
    """The matchmaking room: the first 16 bytes of SHA-256 of the key (zeros without a key)."""
    return hashlib.sha256(key.encode()).digest()[:16] if key else bytes(16)


def frame(ftype: int, payload: bytes = b"") -> bytes:
    return struct.pack("<IB", len(payload) + 1, ftype) + payload


def read_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def read_frame(s: socket.socket, max_size: int = 1 << 20) -> Tuple[int, bytes]:
    (size,) = struct.unpack("<I", read_exact(s, 4))
    if size < 1 or size > max_size + 1:
        raise ConnectionError("bad frame size %d" % size)
    body = read_exact(s, size)
    return body[0], body[1:]


def server_header(room: bytes) -> bytes:
    return b"MHGS" + struct.pack("<HH", SERVER_PROTOCOL, LINK_PROTOCOL) + room


def list_hubs(host: str, port: int, room: bytes, timeout: float = 5.0) -> List[Tuple[int, bytes]]:
    """[(hub id, NetworkInfo)] the server lists for this room."""
    with socket.create_connection((host, port), timeout) as s:
        s.sendall(frame(LIST, server_header(room)))
        t, p = read_frame(s)
    if t != HUBS:
        return []
    (count,) = struct.unpack_from("<I", p)
    out, step = [], 8 + INFO_SIZE
    for i in range(count):
        o = 4 + i * step
        if o + step > len(p):
            break
        out.append((struct.unpack_from("<Q", p, o)[0], p[o + 8:o + step]))
    return out


class NetInfo:
    """Reads a NetworkInfo (0x480 bytes) the way ldn.cpp lays it out."""

    def __init__(self, raw: bytes):
        assert len(raw) == INFO_SIZE
        self.raw = raw

    @property
    def session_id(self) -> bytes:
        return self.raw[NI_SESSION_ID:NI_SESSION_ID + 16]

    @property
    def security_parameter(self) -> bytes:
        return self.raw[NI_SEC_PARAM:NI_SEC_PARAM + 16]

    @property
    def advertise(self) -> bytes:
        n = struct.unpack_from("<H", self.raw, NI_ADV_SIZE)[0]
        return self.raw[NI_ADV:NI_ADV + n]

    @property
    def pia_session_id(self) -> bytes:
        """The first 4 bytes of the advertise data: what Pia's nonce uses (NOTES section 3)."""
        return self.advertise[:4]

    def nodes(self):
        for i in range(self.raw[NI_NODE_MAX] if self.raw[NI_NODE_MAX] else 8):
            n = self.raw[NI_NODES + i * NODE_SIZE:NI_NODES + (i + 1) * NODE_SIZE]
            if len(n) == NODE_SIZE and n[0x0B]:
                yield {"node": n[0x0A], "address": struct.unpack_from("<I", n)[0], "mac": bytes(n[4:10]),
                       "name": bytes(n[0x0C:0x0C + 32]).split(b"\0")[0].decode("utf-8", "replace")}


class Link:
    """One station's link to a hub's host. Call join(); datagrams arrive in on_data(from_addr, from_port, to_port, data)."""

    def __init__(self, mac: bytes, name: str, lcv: int = 0, bridge: bool = False):
        assert len(mac) == 6
        self.mac, self.name, self.lcv, self.bridge = mac, name, lcv, bridge
        self.key: Optional[bytes] = None  # Pia's packet key, sent by a port that has netlog3.patch when bridge=True
        self.sock: Optional[socket.socket] = None
        self.node = -1
        self.address = 0  # host byte order
        self.info: Optional[NetInfo] = None
        self.on_data: Callable[[int, int, int, bytes], None] = lambda *a: None
        self.on_info: Callable[[NetInfo], None] = lambda i: None
        self.on_close: Callable[[], None] = lambda: None
        self._lock = threading.Lock()

    def join(self, server: Tuple[str, int], hub_id: int, room: bytes, timeout: float = 15.0) -> None:
        s = socket.create_connection(server, 5.0)
        s.settimeout(timeout)
        s.sendall(frame(JOIN, server_header(room) + struct.pack("<Q", hub_id)))
        t, _ = read_frame(s)
        if t != SPLICED:
            s.close()
            raise ConnectionError("the server didn't splice us (type %d)" % t)
        self._hello(s)

    def join_direct(self, host: str, port: int, timeout: float = 15.0) -> None:
        s = socket.create_connection((host, port), 5.0)
        s.settimeout(timeout)
        self._hello(s)

    def _hello(self, s: socket.socket) -> None:
        name = self.name.encode("utf-8")[:32].ljust(33, b"\0")
        s.sendall(frame(HELLO, struct.pack("<HHB", LINK_VERSION, self.lcv, 2 if self.bridge else 0) + self.mac + name))
        t, p = read_frame(s)
        if t == REJECT:
            s.close()
            raise ConnectionError("the host turned us away (%d)" % (struct.unpack_from("<I", p)[0] if len(p) >= 4 else 0))
        if t == INFO:
            s.close()
            raise ConnectionError("that host took us for a search and sent its network info: its app doesn't have netlog3.patch")
        if t != WELCOME or len(p) != 5 + INFO_SIZE:
            s.close()
            raise ConnectionError("unexpected answer (type %d, %d bytes)" % (t, len(p)))
        self.node = p[0]
        self.address = struct.unpack_from("<I", p, 1)[0]
        self.info = NetInfo(p[5:])
        s.settimeout(None)
        self.sock = s
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            while True:
                t, p = read_frame(self.sock)
                if t == DATA and len(p) >= 12:
                    src, sport, _dst, dport = struct.unpack_from("<IHIH", p)
                    self.on_data(src, sport, dport, p[12:])
                elif t == INFO and len(p) == INFO_SIZE:
                    self.info = NetInfo(p)
                    self.on_info(self.info)
                elif t == KEY and len(p) == 17:
                    self.key = bytes(p[1:17]) if p[0] else None
                elif t == LINK_PING:
                    self._send(LINK_PING)
                elif t == BYE:
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            self.on_close()

    def _send(self, ftype: int, payload: bytes = b"") -> None:
        with self._lock:
            self.sock.sendall(frame(ftype, payload))

    def send(self, src_port: int, dst_addr: int, dst_port: int, datagram: bytes) -> None:
        """A UDP datagram to an address in the network (0xFFFFFFFF broadcasts). The host fills in our address."""
        self._send(DATA, struct.pack("<IHIH", self.address, src_port, dst_addr, dst_port) + datagram)

    def leave(self) -> None:
        try:
            self._send(BYE, struct.pack("<I", 1))
            self.sock.close()
        except OSError:
            pass

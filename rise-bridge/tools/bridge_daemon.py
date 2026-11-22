#!/usr/bin/env python3
"""The PC side's helper: the game's DLL talks to this over UDP on 127.0.0.1; this talks to the hub server and the Switch
session (a Pia bridge station), so the DLL doesn't need its own crypto or hub code.

  python3 tools/bridge_daemon.py SERVER[:PORT] [--key MATCHMAKING_KEY] [--name NAME] [--listen 39600]

One text line per datagram (hex is lower case, no spaces):
  DLL -> here:  LIST                 list the server's hubs
                JOIN <index>         join hub <index> of the last list as a Pia station
                SEND <hex>           a Steam message from the game to the Switch host (SteamConReq is answered here)
                LEAVE
  here -> DLL:  HUBS\\nH <index> <hex of name, UTF-8> <players> <base64 of the advertise data from byte 0x10>\\n...
                JOINED | ERR <text> | RECV <hex> (a Steam message for the game) | LEFT
"""
import argparse, base64, os, socket, struct, sys, threading, time, zlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import gamemsg, hellomap, hublink, joinmsgs
from bridge.station import Station

CON_REQ, CON_ANS = b"SteamConReq\x00", b"SteamConAns\x00"


class Daemon:
    def __init__(self, server, room, name, port, log=print):
        self.server, self.room, self.name, self.log = server, room, name, log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.dll = None            # where the DLL's datagrams come from (replies go there)
        self.hubs = []
        self.link = self.station = None
        here = os.path.dirname(os.path.abspath(__file__))
        self.hello_map = hellomap.find(os.getcwd(), os.path.join(here, ".."), here, os.path.dirname(os.path.abspath(sys.argv[0])))
        self.log("hello map: %s" % ("loaded" if self.hello_map else "none (the host won't answer the game's hello; run tools/hello_probe.py)"))

    def reply(self, text: str) -> None:
        if self.dll:
            self.sock.sendto(text.encode(), self.dll)

    def hub_lines(self):
        out = ["HUBS"]
        for i, (hid, info) in enumerate(self.hubs):
            ni = hublink.NetInfo(info)
            nodes = list(ni.nodes())
            host = next((n["name"] for n in nodes if n["node"] == 0), "?")
            adv = ni.advertise[0x10:]
            out.append("H %d %s %d %s" % (i, host.encode().hex(), len(nodes), base64.b64encode(adv).decode()))
        return "\n".join(out)

    def join(self, index: int) -> None:
        """Join hub <index>. The first try sometimes isn't taken (seen once in a real run: 22 s of nothing, then the next
        try worked in 3 s), so give each try 8 s and make up to 3."""
        try:
            hid = self.hubs[index][0]
            import hashlib
            mac = bytes([0x02]) + hashlib.sha1(self.name.encode()).digest()[:5]   # the same station identity every time
            state = "?"
            for attempt in range(1, 4):
                link = hublink.Link(mac, self.name, bridge=True)
                link.join(self.server, hid, self.room)
                st = Station(link, log=self.log)
                st.on_game = self.from_switch
                st.on_leave = lambda addr: self.reply("LEFT")
                st.start()
                self.link, self.station = link, st
                for _ in range(80):                # 8 s for the host to take us in
                    if st.state == "in":
                        self.reply("JOINED")
                        return
                    time.sleep(0.1)
                state = st.state
                self.log("join try %d: the host didn't take us in (state %s)%s" % (attempt, state, "; trying again" if attempt < 3 else ""))
                link.leave()
                self.link = self.station = None
                time.sleep(1.0)
            self.reply("ERR the host didn't take us in (state %s)" % state)
        except Exception as e:                 # the DLL shows nothing of this: log it here and tell it
            self.log("join failed: %s" % e)
            self.reply("ERR %s" % e)

    def from_switch(self, addr: int, payload: bytes) -> None:
        self.log("Switch host -> game: %d bytes" % len(payload))
        
        # --- PATCH: Intercept the 36-byte join reply ---
        if len(payload) == 36:
            self.log("[Bridge] Intercepted 36-byte reply. Rewriting for PC...")
            
            # Extract the 4-byte identity. 
            # If the PC still fails to join, try payload[4:8] or payload[12:16]
            identity = payload[8:12] 
            
            # Build the 16-byte packet the PC expects (Type 0x02030100)
            new_payload = struct.pack("<I", 0x02030100) # Type: 00 01 03 02
            new_payload += struct.pack("<I", 16)        # Length: 16
            new_payload += identity                     # Identity (4 bytes)
            
            # Calculate the CRC32 checksum
            checksum = zlib.crc32(new_payload) & 0xFFFFFFFF
            new_payload += struct.pack("<I", checksum)  # Append checksum
            
            self.log("[Bridge] Sent 16-byte packet: " + new_payload.hex())
            payload = new_payload
        # -----------------------------------------------
        
        fixed = gamemsg.to_pc(payload)
        if fixed != payload:
            self.log("the host's platform message made the way a PC sends it (0x20 -> 0x01)")
            payload = fixed
        self.reply("RECV " + joinmsgs.steam_wrap(payload).hex())

    def to_switch(self, data: bytes) -> None:
        if data.startswith(b"SteamCon"):
            if data == CON_REQ:
                self.reply("RECV " + CON_ANS.hex())     # answered here, as the notes say the host would
            return
        game = joinmsgs.steam_unwrap(data)
        
        # --- PATCH: Intercept the 36-byte PC message and convert to 16-byte Switch format ---
        if game is not None and len(game) == 36:
            self.log("[Bridge] Intercepted 36-byte PC message. Converting to 16-byte...")
            
            # Use the Switch's session ID as the identity
            identity = b'\x4f\x28\x18\xb9'
            
            # Build the 16-byte packet the Switch expects
            new_game = struct.pack("<I", 0x02030100) # Type: 00 01 03 02
            new_game += struct.pack("<I", 16)        # Length: 16
            new_game += identity                     # Identity (4 bytes)
            checksum = zlib.crc32(new_game) & 0xFFFFFFFF
            new_game += struct.pack("<I", checksum)  # Checksum
            
            self.log("[Bridge] Sent 16-byte packet to Switch: " + new_game.hex())
            game = new_game
        # -------------------------------------------------------------------------------------
        
        if game is not None:
            self.link.send(game)
        
        
        # --- PATCH: Intercept the 36-byte PC message and convert to 16-byte Switch format ---
        if game is not None and len(game) == 36:
            self.log("[Bridge] Intercepted 36-byte PC message. Converting to 16-byte...")
            
            # Extract identity. If the session key is available in self.link, use it.
            # Otherwise, we use a default 4-byte identity (e.g., 01 01 01 01).
            identity = getattr(self.link, 'key', b'\x01\x01\x01\x01')[:4]
            
            # Build the 16-byte packet the Switch expects
            new_game = struct.pack("<I", 0x02030100) # Type: 00 01 03 02
            new_game += struct.pack("<I", 16)        # Length: 16
            new_game += identity                     # Identity (4 bytes)
            checksum = zlib.crc32(new_game) & 0xFFFFFFFF
            new_game += struct.pack("<I", checksum)  # Checksum
            
            self.log("[Bridge] Sent 16-byte packet to Switch: " + new_game.hex())
            game = new_game
        # -------------------------------------------------------------------------------------
        
        self.log("game -> Switch host: %d bytes%s" % (len(data), "" if game is not None else " (not a game message, dropped)"))
        st = self.station
        if game is None or st is None or st.state != "in":
            return
        host, host_mac = st._host()
        if host:
            if self.hello_map and host_mac and hellomap.is_hello(game):
                game = self.hello_map.message_for(host_mac)   # the hello for THIS host's MAC, not the one for the fake host
                self.log("the game's hello replaced with the one host %s expects" % host_mac.hex(":"))
            fixed = gamemsg.to_switch(game)
            if fixed != game:
                self.log("the game's platform message made the way a Switch sends it (0x01 -> 0x20)")
                game = fixed
            st.send_game(host, game)

    def handle(self, line: str) -> None:
        cmd, _, arg = line.strip().partition(" ")
        if cmd == "LIST":
            try:
                self.hubs = hublink.list_hubs(*self.server, self.room)
                self.reply(self.hub_lines())
            except Exception as e:
                self.reply("ERR %s" % e)
        elif cmd == "JOIN":
            threading.Thread(target=self.join, args=(int(arg),), daemon=True).start()
        elif cmd == "SEND":
            self.to_switch(bytes.fromhex(arg))
        elif cmd == "LEAVE" and self.link:
            self.log("the game left the lobby")
            if self.station:
                self.station.leave_session()
                time.sleep(0.2)
            self.link.leave()
            self.link = self.station = None

    def run(self) -> None:
        self.log("bridge daemon on 127.0.0.1:%d" % self.sock.getsockname()[1])
        while True:
            data, addr = self.sock.recvfrom(65535)
            self.dll = addr
            try:
                self.handle(data.decode())
            except Exception as e:
                self.log("bad datagram %r: %s" % (data[:40], e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("--key", default="")
    ap.add_argument("--name", default="PCBridge")
    ap.add_argument("--listen", type=int, default=39600)
    a = ap.parse_args()
    host, _, port = a.server.partition(":")
    Daemon((host, int(port or 39510)), hublink.room_of_key(a.key), a.name, a.listen).run()


if __name__ == "__main__":
    main()

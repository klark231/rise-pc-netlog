#!/usr/bin/env python3
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
        self.dll = None
        self.hubs = []
        self.link = self.station = None
        here = os.path.dirname(os.path.abspath(__file__))
        self.hello_map = hellomap.find(os.getcwd(), os.path.join(here, ".."), here, os.path.dirname(os.path.abspath(sys.argv[0])))
        self.log("hello map: %s" % ("loaded" if self.hello_map else "none"))

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
        try:
            hid = self.hubs[index][0]
            import hashlib
            mac = bytes([0x02]) + hashlib.sha1(self.name.encode()).digest()[:5]
            state = "?"
            for attempt in range(1, 4):
                link = hublink.Link(mac, self.name, bridge=True)
                link.join(self.server, hid, self.room)
                st = Station(link, log=self.log)
                st.on_game = self.from_switch
                st.on_leave = lambda addr: self.reply("LEFT")
                st.start()
                self.link, self.station = link, st
                for _ in range(80):
                    if st.state == "in":
                        self.reply("JOINED")
                        return
                    time.sleep(0.1)
                state = st.state
                self.log("join try %d: state %s" % (attempt, state))
                link.leave()
                self.link = self.station = None
                time.sleep(1.0)
            self.reply("ERR the host didn't take us in (state %s)" % state)
        except Exception as e:
            self.log("join failed: %s" % e)
            self.reply("ERR %s" % e)

    def from_switch(self, addr: int, payload: bytes) -> None:
        self.log("Switch host -> game: %d bytes" % len(payload))
        fixed = gamemsg.to_pc(payload)
        if fixed != payload:
            self.log("the host's platform message made the way a PC sends it (0x20 -> 0x01), same identity %s"
                     % gamemsg.identity(fixed).hex())
            payload = fixed
        self.reply("RECV " + joinmsgs.steam_wrap(payload).hex())

    def to_switch(self, data: bytes) -> None:
        if data.startswith(b"SteamCon"):
            if data == CON_REQ:
                self.reply("RECV " + CON_ANS.hex())
            return
            
        game = joinmsgs.steam_unwrap(data)
        self.log("game -> Switch host: %d bytes" % (len(game) if game else 0))
        
        # The game's member messages (0203, 0302) go to the host as they are. They used to be replaced with made-up
        # Switch-style ones, because the host rejected the PC's: the platform message had told the host another identity
        # (see gamemsg.set_platform), so nothing the PC sent afterwards matched it.
        st = self.station
        if game is None or st is None or st.state != "in":
            return
            
        host, host_mac = st._host()
        if host:
            if self.hello_map and host_mac and hellomap.is_hello(game):
                game = self.hello_map.message_for(host_mac)
            fixed = gamemsg.to_switch(game)
            if fixed != game:
                self.log("the game's platform message made the way a Switch sends it (0x01 -> 0x20), same identity %s"
                         % gamemsg.identity(fixed).hex())
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

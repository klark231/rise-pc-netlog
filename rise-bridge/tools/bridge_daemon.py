#!/usr/bin/env python3
import argparse, base64, os, socket, struct, sys, threading, time, zlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import gamemsg, hellomap, hublink, joinmsgs, lobby, wire
from bridge.station import Station

CON_REQ, CON_ANS = b"SteamConReq\x00", b"SteamConAns\x00"
# The Steam ID the DLL gives the Switch host (src/bridge.cpp kHostId); the lobby answers name the host by it
HOST_SID = 0x0110000100000000 | 0x4B1D0000

class Daemon:
    def __init__(self, server, room, name, port, log=print):
        self.server, self.room, self.name, self.log = server, room, name, log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.dll = None
        self.hubs = []
        self.link = self.station = None
        self.pc_lobby = self.sw_lobby = None
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
                        self._lobbies(st)
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

    def _lobbies(self, st) -> None:
        """The lobby channel isn't passed through: the bridge is the PC's host there, and the Switch host's joiner
        (bridge/lobby.py). A thread sends the PC host's keep-alives while this station lasts."""
        self.pc_lobby = lobby.PcLobby(HOST_SID, lambda m: self.reply("RECV " + joinmsgs.steam_wrap(m).hex()), self.log)
        self.sw_lobby = lobby.SwitchLobby(lambda m: st.send_game(st._host()[0], m), self.log)

        def ticks(pc=self.pc_lobby):
            while self.station is st and self.pc_lobby is pc:
                time.sleep(0.5)
                try:
                    pc.tick()
                except Exception as e:
                    self.log("lobby keep-alive: %s" % e)
        threading.Thread(target=ticks, daemon=True).start()

    def from_switch(self, addr: int, payload: bytes) -> None:
        p = wire.decode(payload)
        if p is not None and p[:2] == wire.LOBBY:
            if self.sw_lobby:
                self.sw_lobby.from_host(p)
            return
        self.log("Switch host -> game: %d bytes" % len(payload))
        fixed = gamemsg.to_pc(payload)
        if fixed != payload:
            self.log("the host's platform message made the way a PC sends it, same identity %s"
                     % gamemsg.identity(fixed).hex())
            payload = fixed
        self.reply("RECV " + joinmsgs.steam_wrap(payload).hex())

    def to_switch(self, data: bytes) -> None:
        if data.startswith(b"SteamCon"):
            if data == CON_REQ:
                self.reply("RECV " + CON_ANS.hex())
            return
            
        game = joinmsgs.steam_unwrap(data)
        p = wire.decode(game) if game else None
        if p is not None and p[:2] == wire.LOBBY:
            if self.pc_lobby:
                self.pc_lobby.from_pc(p)
            return
        self.log("game -> Switch host: %d bytes" % (len(game) if game else 0))

        # Everything else goes to the host as it is, the platform message with the Switch's platform byte (and the
        # same identity: every member message the PC sends afterwards carries it).
        st = self.station
        if game is None or st is None or st.state != "in":
            return
            
        host, host_mac = st._host()
        if host:
            if self.hello_map and host_mac and hellomap.is_hello(game):
                game = self.hello_map.message_for(host_mac)
            fixed = gamemsg.to_switch(game)
            if fixed != game:
                self.log("the game's platform message made the way a Switch sends it, same identity %s"
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
            self.pc_lobby = self.sw_lobby = None

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

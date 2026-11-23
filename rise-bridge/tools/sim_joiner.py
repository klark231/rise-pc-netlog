#!/usr/bin/env python3
"""A stand-in for the PC game, for testing the bridge with no PC: joins your phone's hub as a Pia station and plays the
joiner's side of the game handshake the way a Switch joiner does (and the way the bridge helper does for the PC game).

  python3 tools/sim_joiner.py SERVER[:PORT] --key MATCHMAKING_KEY --hub 0 [--seconds 40] [--no-member]

Host side: the app build with netlog3.patch, Capture Local Play on at start-up, a hub open in Local Play (as for join_hub.py).
What it does after joining ("in the session"):
  - the host's hello (15 bytes)      -> our hello for the host's MAC (the hello map)
  - the host's 12, 9 and 8-byte ones -> echoed back
  - the host's 0203 member message   -> our 0203 member message and 0302 reply (bridge/memberid.py), every 2 s, up to 10 times
    (--no-member leaves those out: the "before" run, to compare with)
Every 2 seconds it prints what the host sent in that time, as  length/type x count. The question the run answers: does the host's
repeating of its 9, 21 and 67-byte messages stop once we answer? It prints a verdict at the end. Ctrl-C ends early.
"""
import argparse, collections, hashlib, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from bridge import gamemsg, hellomap, hublink, memberid
from bridge.station import Station


def kind(payload: bytes) -> str:
    """'length/type' of a game message, e.g. 21/0203"""
    if len(payload) < 7:
        return "%d/-" % len(payload)
    return "%d/%s" % (len(payload), gamemsg.data_of(payload)[:2].hex())


class SimJoiner:
    def __init__(self, send, host_mac, hello_map, member=True, log=print, clock=time.monotonic):
        self.send, self.host_mac, self.hello_map, self.member, self.log, self.clock = send, host_mac, hello_map, member, log, clock
        self.window = collections.Counter()      # what arrived since the last printout
        self.total = collections.Counter()
        self.history = []                        # (time, kind) of every message
        self.member_sent, self.last_member = 0, None
        self.t0 = clock()

    def handle(self, payload: bytes) -> None:
        k = kind(payload)
        self.window[k] += 1
        self.total[k] += 1
        self.history.append((self.clock() - self.t0, k))
        if hellomap.is_hello(payload):
            if self.hello_map and self.host_mac:
                self.send(self.hello_map.message_for(self.host_mac))
        elif len(payload) in (8, 9, 12):
            self.send(payload)                   # echoed, as the PC game answers these
        elif self.member and len(payload) >= 16:
            ids = memberid.learn(payload)
            now = self.clock()
            if ids and self.member_sent < 10 and (self.last_member is None or now - self.last_member >= 2.0):
                self.last_member, self.member_sent = now, self.member_sent + 1
                self.log("  [member] host id %s, our id %s: sent 0203 + 0302 (try %d)" % (ids[0].hex(), ids[1].hex(), self.member_sent))
                self.send(memberid.member_msg(ids[1], ids[0]))
                self.send(memberid.reply_msg(ids[1], ids[0]))

    def flush(self) -> None:
        if self.window:
            self.log("  %5.1fs  host sent: %s" % (self.clock() - self.t0, "  ".join("%s x%d" % kv for kv in sorted(self.window.items()))))
            self.window.clear()

    def verdict(self) -> str:
        """Compare the first and last third of the run: a host that took our answer stops repeating its messages."""
        if not self.history:
            return "the host sent no game messages at all"
        end = self.history[-1][0] or 1.0
        early = collections.Counter(k for t, k in self.history if t <= end / 3)
        late = collections.Counter(k for t, k in self.history if t > end * 2 / 3)
        new = sorted(set(late) - set(early))
        out = ["messages seen over the run: " + ", ".join("%s x%d" % kv for kv in sorted(self.total.items()))]
        # the 8 and 9-byte pings and the 0406 game data repeat in every real session; the handshake messages must not
        skip = lambda k: k.startswith(("8/", "9/")) or k.endswith("/0406")
        loop = [k for k in late if not skip(k) and late[k] >= 5 and early.get(k, 0) >= 5]
        if loop:
            out.append("STILL LOOPING: %s kept repeating to the end (the host hasn't taken our answers)" % ", ".join(sorted(loop)))
        else:
            out.append("NOT LOOPING: the handshake messages stopped repeating")
        data = sum(v for k, v in self.total.items() if k.endswith("/0406"))
        out.append("game data (type 0406) from the host: %s" % ("%d messages, so the host moved on to the game phase" % data if data else "none"))
        new = sorted(k for k in set(late) - set(early) if not skip(k))
        if new:
            out.append("new kinds of message in the last third: %s" % ", ".join(new))
        return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("--key", default="")
    ap.add_argument("--hub", type=int, required=True)
    ap.add_argument("--name", default="PCBridge")
    ap.add_argument("--seconds", type=int, default=40)
    ap.add_argument("--no-member", action="store_true", help="don't send the member replies (the 'before' run)")
    a = ap.parse_args()
    host, _, port = a.server.partition(":")
    server = (host, int(port or 39510))
    room = hublink.room_of_key(a.key)
    hubs = hublink.list_hubs(*server, room)
    for i, (hid, info) in enumerate(hubs):
        print(i, hex(hid), [n["name"] for n in hublink.NetInfo(info).nodes()])
    if not 0 <= a.hub < len(hubs):
        sys.exit("--hub must be one of the numbers above")
    try:
        hello_map = hellomap.HelloMap.load(os.path.join(HERE, "..", "hello_map.json"))
    except Exception as e:
        print("no hello map (%s): the host won't answer our hello" % e)
        hello_map = None
    mac = bytes([0x02]) + hashlib.sha1(a.name.encode()).digest()[:5]
    sim = st = link = None
    for attempt in range(1, 4):
        link = hublink.Link(mac, a.name, bridge=True)
        link.join(server, hubs[a.hub][0], room)
        st = Station(link)
        st.start()
        for _ in range(80):
            if st.state == "in":
                break
            time.sleep(0.1)
        if st.state == "in":
            break
        print("try %d: the host didn't take us in (state %s)" % (attempt, st.state))
        link.leave()
        time.sleep(1)
    else:
        sys.exit("never got in: see join_hub.py")
    host_addr, host_mac = st._host()
    sim = SimJoiner(lambda m: st.send_game(host_addr, m), host_mac, hello_map, member=not a.no_member)
    st.on_game = lambda addr, payload: sim.handle(payload)
    print("in the session; running %d s %s" % (a.seconds, "WITHOUT member replies" if a.no_member else "with member replies"))
    try:
        end = time.time() + a.seconds
        while time.time() < end:
            time.sleep(2)
            sim.flush()
    except KeyboardInterrupt:
        pass
    sim.flush()
    print("\n" + sim.verdict())
    try:
        st.leave_session()
        time.sleep(0.3)
        link.leave()
    except Exception:
        pass


if __name__ == "__main__":
    main()

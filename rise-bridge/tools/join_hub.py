#!/usr/bin/env python3
"""Lists a hub server's hubs and joins one as a bridge station (a first real test, no game involved).

  python3 tools/join_hub.py SERVER[:PORT] [--key MATCHMAKING_KEY] [--hub N]

The hosting port needs netlog3.patch and Capture Local Play on at start-up (that's what finds Pia's key).
Prints what the station sees; Ctrl-C leaves.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import hublink
from bridge.station import Station


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("--key", default="")
    ap.add_argument("--hub", type=int, required=True, help="index from the list; the list is printed first. Use your own hub (set a matchmaking key so only yours is listed)")
    ap.add_argument("--name", default="PCBridge")
    ap.add_argument("--no-auto-hello", action="store_true", help="don't compute and send the hello the host expects (bridge/hello.py)")
    ap.add_argument("--no-echo", action="store_true", help="don't echo the host's 12/9/8-byte game messages back")
    ap.add_argument("--hello", help="16 hex digits: the hello value the host expects (from --probe); the station sends it once in the session")
    ap.add_argument("--mac", help="join with this MAC (aa:bb:cc:dd:ee:ff) instead of a random one")
    ap.add_argument("-v", action="store_true", help="print every message the station receives")
    ap.add_argument("--seconds", type=int, default=20, help="how long to stay (not with --probe)")
    ap.add_argument("--probe", action="store_true", help="join with the host's own MAC, print the hello the host sends (its value for that MAC, which is the hello the host expects to RECEIVE), and leave")
    a = ap.parse_args()
    host, _, port = a.server.partition(":")
    server = (host, int(port or 39510))
    room = hublink.room_of_key(a.key)
    hubs = hublink.list_hubs(*server, room)
    for i, (hid, info) in enumerate(hubs):
        ni = hublink.NetInfo(info)
        print(i, hex(hid), [n["name"] for n in ni.nodes()])
    if not hubs:
        sys.exit("no hubs listed")
    if not 0 <= a.hub < len(hubs):
        sys.exit("--hub must be one of the numbers above")
    mac = bytes([0x02]) + os.urandom(5)  # a made-up MAC; the host doesn't check it
    if a.mac:
        mac = bytes.fromhex(a.mac.replace(":", ""))
    if a.probe:
        host_nodes = [n for n in hublink.NetInfo(hubs[a.hub][1]).nodes() if n["node"] == 0]
        if not host_nodes:
            sys.exit("that hub lists no host MAC")
        mac = host_nodes[0]["mac"]
        print("probe: joining with the host's MAC", mac.hex(":"))
    link = hublink.Link(mac, a.name, bridge=True)
    link.join(server, hubs[a.hub][0], room)
    st = Station(link)
    st.verbose = a.v
    st.echo = not a.no_echo
    if a.hello:
        st.hello_to_send = bytes.fromhex(a.hello)
    elif not a.no_auto_hello and not a.probe:
        from bridge.hello import hello_message_for_mac
        hn = [n for n in link.info.nodes() if n["node"] == 0]
        try:
            st.hello_msg = hello_message_for_mac(hn[0]["mac"])
            print("hello message for the host's MAC %s: %s" % (hn[0]["mac"].hex(":"), st.hello_msg.hex()))
        except ValueError as e:
            print("no hello computed:", e)
    st.on_game = lambda addr, payload: print("game message from %08x: %d bytes" % (addr, len(payload)))
    st.start()
    if a.probe:
        if st.hello_seen.wait(20):
            print("HELLO_FOR_HOST=%s   (the hello the game must send to this host; valid while the host keeps this MAC)" % st.host_hello.hex())
        else:
            print("no hello from the host within 20 s (state: %s)" % st.state)
        link.leave()
        return
    try:
        end = time.time() + a.seconds
        last = None
        while time.time() < end:
            time.sleep(0.5)
            if st.state != last:
                last = st.state
                print("state:", last)
            if st.hello_seen.is_set() and not getattr(st, "_said", False):
                st._said = True
                print("the host's hello for this station's MAC:", st.host_hello.hex())
        print("done; state", st.state)
        for (src, ptype, n, start), cnt in sorted(st._rx_counts.items(), key=lambda x: -x[1])[:12]:
            print("  received %3d x type 0x%02x, %d bytes, starts %s" % (cnt, ptype, n, start.hex()))
    except KeyboardInterrupt:
        pass
    link.leave()


if __name__ == "__main__":
    main()

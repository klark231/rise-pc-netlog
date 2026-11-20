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
    ap.add_argument("--hub", type=int, default=0)
    ap.add_argument("--name", default="PCBridge")
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
    mac = bytes([0x02]) + os.urandom(5)  # a made-up MAC; the host doesn't check it
    link = hublink.Link(mac, a.name, bridge=True)
    link.join(server, hubs[a.hub][0], room)
    st = Station(link)
    st.on_game = lambda addr, payload: print("game message from %08x: %d bytes" % (addr, len(payload)))
    st.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        link.leave()


if __name__ == "__main__":
    main()

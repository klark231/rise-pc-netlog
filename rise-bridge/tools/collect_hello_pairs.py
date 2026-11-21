#!/usr/bin/env python3
"""Asks a host for the hello of many different MACs: joins N times with a random MAC each, records (mac, hello).

  python3 tools/collect_hello_pairs.py SERVER[:PORT] --key KEY --hub 0 --count 60 --out ~/hello_pairs.txt

Each join takes a few seconds; the file gets one line per success ("mac hello"), so it can be stopped and resumed.
Use your own hub only (a matchmaking key so only yours is listed).
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import hublink
from bridge.station import Station


def one(server, room, hub_id, mac, name, wait=10.0):
    link = hublink.Link(mac, name, bridge=True)
    try:
        link.join(server, hub_id, room)
        st = Station(link)
        st.start()
        ok = st.hello_seen.wait(wait)
        return st.host_hello if ok else None
    finally:
        link.leave()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("--key", default="")
    ap.add_argument("--hub", type=int, required=True)
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--vary-first-byte", action="store_true", help="also vary the MAC's first byte (unicast: bit 0 clear), to extend bridge/hello.py to MACs not starting 02")
    ap.add_argument("--out", default=os.path.expanduser("~/hello_pairs.txt"))
    a = ap.parse_args()
    host, _, port = a.server.partition(":")
    server = (host, int(port or 39510))
    room = hublink.room_of_key(a.key)
    hubs = hublink.list_hubs(*server, room)
    if not 0 <= a.hub < len(hubs):
        sys.exit("--hub must be one of the listed hubs (%d found)" % len(hubs))
    have = 0
    try:
        have = sum(1 for _ in open(a.out))
    except OSError:
        pass
    print("hub", hex(hubs[a.hub][0]), "- have", have, "pairs in", a.out)
    for i in range(a.count):
        mac = bytes([(os.urandom(1)[0] & 0xFE) if a.vary_first_byte else 0x02]) + os.urandom(5)
        try:
            h = one(server, room, hubs[a.hub][0], mac, "Probe%d" % i)
        except Exception as e:
            print("join failed:", e)
            time.sleep(2)
            continue
        if h:
            with open(a.out, "a") as f:
                f.write("%s %s\n" % (mac.hex(), h.hex()))
            print("%d/%d %s %s" % (i + 1, a.count, mac.hex(":"), h.hex()))
        else:
            print("%d/%d no hello for %s" % (i + 1, a.count, mac.hex(":")))
        time.sleep(1.0)


if __name__ == "__main__":
    main()

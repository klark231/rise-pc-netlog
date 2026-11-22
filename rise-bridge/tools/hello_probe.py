#!/usr/bin/env python3
"""Probe: how does the Switch host's hello depend on the joining station's MAC?

The host sends every station that joins a 15-byte hello that is a fixed value for the station's MAC. The hello the
host EXPECTS back is the same kind of value for the HOST'S own MAC. This joins YOUR OWN host again and again with
slightly different MACs, writes down each hello, and checks whether hello(MAC) is affine over GF(2) (then the host's
own value can be computed).

  python3 tools/hello_probe.py SERVER[:PORT] [--key KEY] [--hub N] [--out hello_samples.txt]

Use only your own host (set a matchmaking key on both sides so only your hub is listed). Needs the patched port with
Capture Local Play on at start-up, like the bridge itself. Ctrl-C stops; what it has so far is saved and analysed.
"""
import argparse, os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import hublink
from bridge.station import Station

BASE = bytes.fromhex("0227a00a8d05")   # the MAC the bridge has been using: its hello is already known (3b7b5027f5de1c3c)


def hello_of(payload: bytes):
    """The 8-byte value in a 15-byte game hello: 3 prefix bytes, then 12 bytes XORed with the 4th (00 01 03 02 + 8)"""
    if len(payload) != 15:
        return None
    body = bytes(x ^ payload[3] for x in payload[3:])
    return body[4:12] if body[:4] == bytes.fromhex("00010302") else None


def one_join(server, hub_id, room, mac, name="PCBridge", timeout=12.0):
    """(the host's whole 15-byte hello message or None, host MAC) for a station with this MAC"""
    got = []
    lines = one_join.lines = []
    link = hublink.Link(mac, name, bridge=True)
    link.join(server, hub_id, room)
    st = Station(link, log=lines.append)
    st.on_game = lambda addr, payload: got.append(payload)
    try:
        st.start()
        host_mac = st._host()[1]
        t = time.time() + timeout
        while time.time() < t and not any(hello_of(p) for p in got):
            time.sleep(0.05)
    finally:
        one_join.state = st.state
        try:
            st.leave_session()
            time.sleep(0.3)
        except Exception:
            pass
        link.leave()
    for p in got:
        if hello_of(p):
            return bytes(p), host_mac
    return None, host_mac


def flip(mac, bit):
    v = int.from_bytes(mac, "big") ^ (1 << bit)
    return v.to_bytes(6, "big")


def analyse(samples, host_mac, map_path=None):
    """samples: {mac bytes: the 15-byte hello message}. Is it affine in the MAC's bits? (base, single flips, then
    multi-bit samples to check). The 8-byte hello inside is bytes 7..14 once unscrambled."""
    if BASE not in samples:
        print("no sample for the base MAC: can't analyse")
        return
    h0 = int.from_bytes(samples[BASE], "big")
    d = {}
    for bit in range(48):
        m = flip(BASE, bit)
        if m in samples:
            d[bit] = int.from_bytes(samples[m], "big") ^ h0
    print("single-bit flips known: %d of 48" % len(d))
    ok = bad = 0
    for m, h in samples.items():
        diff = int.from_bytes(m, "big") ^ int.from_bytes(BASE, "big")
        bits = [b for b in range(48) if diff >> b & 1]
        if len(bits) < 2 or any(b not in d for b in bits):
            continue
        pred = h0
        for b in bits:
            pred ^= d[b]
        if pred == int.from_bytes(h, "big"):
            ok += 1
        else:
            bad += 1
    print("multi-bit samples: predicted right %d, wrong %d" % (ok, bad))
    if ok and not bad:
        print("=> hello(MAC) is affine over GF(2) in the MAC's bits.")
        if host_mac is not None and all(b in d for b in range(48)):
            diff = int.from_bytes(host_mac, "big") ^ int.from_bytes(BASE, "big")
            pred = h0
            for b in range(48):
                if diff >> b & 1:
                    pred ^= d[b]
            msg = pred.to_bytes(15, "big")
            print("the host's MAC %s -> the hello message it expects: %s" % (host_mac.hex(":"), msg.hex()))
            print("   (the 8-byte hello in it: %s)" % bytes(b ^ msg[3] for b in msg[3:])[4:12].hex())
            if map_path:
                from bridge.hellomap import HelloMap
                HelloMap(BASE, samples[BASE], [(d[b]).to_bytes(15, "big") for b in range(48)]).save(map_path)
                print("saved the map to %s: copy it next to the bridge on the PC" % map_path)
    elif bad:
        print("=> not affine: the hello is a real hash of the MAC (the samples are still saved).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("--key", default="")
    ap.add_argument("--hub", type=int, default=None)
    ap.add_argument("--out", default="hello_samples.txt")
    ap.add_argument("--map", default="hello_map.json")
    ap.add_argument("--random", type=int, default=12, help="extra samples with 2-3 bits flipped, to check the pattern")
    a = ap.parse_args()
    host, _, port = a.server.partition(":")
    server = (host, int(port or 39510))
    room = hublink.room_of_key(a.key)
    hubs = hublink.list_hubs(*server, room)
    for i, (hid, info) in enumerate(hubs):
        print(i, hex(hid), [n["name"] for n in hublink.NetInfo(info).nodes()])
    if not hubs:
        sys.exit("no hubs listed")
    n = a.hub if a.hub is not None else int(input("YOUR hub's number: "))
    hid = hubs[n][0]
    macs = [BASE] + [flip(BASE, b) for b in range(48)]
    rnd = random.Random(1)
    for _ in range(a.random):
        m = BASE
        for b in rnd.sample(range(48), rnd.choice((2, 3))):
            m = flip(m, b)
        macs.append(m)
    macs.append(BASE)   # again, to see that it is stable
    samples, host_mac, failed = {}, None, 0
    try:
        for i, mac in enumerate(macs):
            try:
                h, hm = one_join(server, hid, room, mac)
            except Exception as e:
                print("%d/%d %s: %s" % (i + 1, len(macs), mac.hex(":"), e))
                time.sleep(1)
                continue
            host_mac = host_mac or hm
            print("%d/%d %s -> %s" % (i + 1, len(macs), mac.hex(":"), hello_of(h).hex() if h else "no hello (station state: %s)" % one_join.state))
            if not h:
                failed += 1
                print("   what the station saw:")
                for l in one_join.lines[-15:]:
                    print("     " + l)
                if failed >= 2 and not samples:
                    print("two joins in a row got no hello: stopping, send me this output")
                    break
            if h:
                if mac in samples and samples[mac] != h:
                    print("   !! the same MAC gave a different hello before: %s" % samples[mac].hex())
                samples[mac] = h
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("stopped")
    with open(a.out, "w") as f:
        f.write("# host mac %s\n" % (host_mac.hex(":") if host_mac else "?"))
        for m, h in samples.items():
            f.write("%s %s %s\n" % (m.hex(), hello_of(h).hex(), h.hex()))
    print("saved %d samples to %s" % (len(samples), a.out))
    analyse(samples, host_mac, a.map)


if __name__ == "__main__":
    main()

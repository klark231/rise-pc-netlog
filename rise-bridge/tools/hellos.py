#!/usr/bin/env python3
"""Lists the hello game messages (the 15-byte ones starting 00 01 03 02) in Switch captures:
who sent each value to whom. Give it several captures to see which values stay the same between sessions.

  python3 tools/hellos.py local_play_A.txt local_play_B.txt ...
"""
import collections, os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
sys.path.insert(0, os.environ.get("RISE_NET", os.path.join(here, "..", "tests")))
import rise_net
from bridge import pia


def main(paths):
    for path in paths:
        key, macs, session, packets = rise_net.read_switch(path)
        if not key or session is None:
            print(os.path.basename(path), "- no key or session in this capture, skipped")
            continue
        crypto = pia.PiaCrypto(key, session)
        rows = collections.OrderedDict()
        for pk in packets:
            d = bytes(pk["data"])
            mac = macs.get(pk["src"])
            body = crypto.open(d, mac) if mac and d.startswith(pia.MAGIC) and len(d) >= 32 else None
            if not body:
                continue
            for m in pia.parse_body(body):
                if m.ptype == 0x68 and len(m.payload) == 15:
                    _, b = rise_net.unscramble(m.payload)
                    if b[:4] == bytes.fromhex("00010302"):
                        k = (pk["src"].split(".")[-1], "%x" % m.dst, b[4:12].hex())
                        rows[k] = rows.get(k, 0) + 1
        print(os.path.basename(path), "- host is node 0 (dst bit 1); players:", {a.split(".")[-1]: mac.hex(":") for a, mac in macs.items()})
        for (src, dst, val), n in rows.items():
            print("   from .%s to node-mask %s: %s  (x%d)" % (src, dst, val, n))


if __name__ == "__main__":
    main(sys.argv[1:]) if len(sys.argv) > 1 else print(__doc__)

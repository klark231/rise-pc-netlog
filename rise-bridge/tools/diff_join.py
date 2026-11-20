#!/usr/bin/env python3
"""Settle the GUESS fields: compare what bridge/joinmsgs.py builds with a join in a Switch capture.

  python3 tools/diff_join.py local_play_<date>.txt

Reads the capture with rise_net.py (tests/rise_net.py, or RISE_NET), finds the first Pia 0x14 request
(payload starting 01 00 04, 308 bytes), rebuilds it from the values inside it, and prints every offset where the
two differ. Offsets that differ are the layout you still have wrong.
"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
sys.path.insert(0, os.environ.get("RISE_NET", os.path.join(here, "..", "tests")))
import rise_net
from bridge import joinmsgs


def main(path):
    for pk, m in rise_net.switch_messages(path):
        p = bytes(m["payload"])
        if m["ptype"] == 0x14 and p[:3] == bytes.fromhex("010004") and len(p) == 0x134:
            me = p[0x22:0x66]
            name = p[0x6F:0x8F].split(b"\0")[0].decode("utf-8", "replace")
            built = joinmsgs.connect_request(p[3:11], p[11:15], me, p[0x66:0x6A][::-1], name,
                                             int.from_bytes(p[0x130:0x134], "little"))
            bad = [i for i in range(len(p)) if p[i] != built[i]]
            print("first 0x14 request at %s: %d of %d bytes differ" % (pk["t"], len(bad), len(p)))
            for i in bad[:64]:
                print("  0x%03x  capture %02x  built %02x" % (i, p[i], built[i]))
            print("capture 0x6e..0x12f:", p[0x6E:0x130].hex())
            return
    print("no 0x14 request found")


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

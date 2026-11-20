#!/usr/bin/env python3
"""Checks the small joiner messages (0x24 01 21, 0x14 05, 0x18 01 fd, 0x1c) against a Switch capture:
rebuilds each from the values inside it with bridge/joinmsgs.py and says whether the bytes are the same.

  python3 tools/diff_small.py local_play_<date>.txt
"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
sys.path.insert(0, os.environ.get("RISE_NET", os.path.join(here, "..", "tests")))
import rise_net
from bridge import joinmsgs as j


def main(path):
    seen = {}
    for pk, m in rise_net.switch_messages(path):
        p, t = bytes(m["payload"]), m["ptype"]
        built = None
        if t == 0x24 and p[:2] == bytes.fromhex("0121") and len(p) == 20:
            kind, built = "0x24 mesh reply", j.mesh_reply(p[0x0C])
        elif t == 0x14 and p[:4] == bytes.fromhex("05000000") and len(p) == 8:
            kind, built = "0x14 ack", j.connect_ack(int.from_bytes(p[4:8], "little"))
        elif t == 0x18 and p[:2] == bytes.fromhex("01fd") and len(p) == 6:
            kind, built = "0x18 answer", j.session_ack(int.from_bytes(p[2:6], "little"))
        elif t == 0x1C and len(p) == 16:
            kind, built = "0x1c clock", j.clock_request(p[:8]) if p[8:] == bytes(8) else None
            if built is None:
                kind = "0x1c clock (host's reply, skipped)"
        if built is None or kind in seen:
            continue
        seen[kind] = True
        print("%-22s %s  %s" % (kind, "same" if built == p else "DIFFERENT", p.hex()))
        if built != p:
            print("%-22s built       %s" % ("", built.hex()))
    if not seen:
        print("none of those messages found")


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

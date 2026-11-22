#!/usr/bin/env python3
"""What game messages (Pia type 0x68) went between whom, by body type and length, in a phone capture.

  python3 tools/game_msgs.py local_play_X.txt

One line per (sender, receiver, length, 2-byte type): how many, first time seen. A message is 3 prefix bytes + a body
XORed with the 4th byte; the body's bytes 1..2 are its type (0103 hello/platform/ping, 0203 member info, 0302 reply,
0406 game data). Use it to compare a bridge run with a real Switch-to-Switch join: a healthy join has the host's
9/21 byte messages ONCE, not every half second.
"""
import collections, os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "tests"))
import rise_net


def main(path):
    c, first = collections.Counter(), {}
    for pk, m in rise_net.switch_messages(path):
        p = bytes(m["payload"])
        if m["ptype"] != 0x68 or len(p) < 7:
            continue
        body = bytes(b ^ p[3] for b in p[3:])
        k = (pk["src"].split(".")[-1], pk["dst"].split(".")[-1], len(p), body[1:3].hex())
        c[k] += 1
        first.setdefault(k, pk["t"])
    for k, n in sorted(c.items(), key=lambda x: first[x[0]]):
        print("%s  .%s -> .%s  %3d bytes  type %s  x%d" % (first[k], k[0], k[1], k[2], k[3], n))


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

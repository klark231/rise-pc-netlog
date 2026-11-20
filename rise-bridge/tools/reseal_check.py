#!/usr/bin/env python3
"""Takes every Pia packet of a Switch capture apart and puts it back together with bridge/pia.py.

  python3 tools/reseal_check.py local_play_<date>.txt

For each encrypted packet from a known sender: open it (tag checked), parse the message list, build the list
again, seal it again with the packet's own header values, and compare with the original bytes. Counts how many
come out identical; prints the first few that don't (what the encoder would have to do differently).
"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
sys.path.insert(0, os.environ.get("RISE_NET", os.path.join(here, "..", "tests")))
import rise_net
from bridge import pia


def main(path):
    key, macs, session, packets = rise_net.read_switch(path)
    if not key or session is None:
        sys.exit("no key or advertise data in the capture")
    crypto = pia.PiaCrypto(key, session)
    n = dict(total=0, opened=0, body_same=0, packet_same=0, skipped=0)
    shown = 0
    for pk in packets:
        d = bytes(pk["data"])
        mac = macs.get(pk["src"])
        n["total"] += 1
        if mac is None or not d.startswith(pia.MAGIC) or not d[4] & 0x80:
            n["skipped"] += 1
            continue
        body = crypto.open(d, mac)
        if body is None:
            continue
        n["opened"] += 1
        msgs = pia.parse_body(body)
        rebuilt = pia.build_body(msgs)
        same_body = body[:len(rebuilt)] == rebuilt and set(body[len(rebuilt):]) <= {0xFF}  # the rest of the packet is 0xff padding
        n["body_same"] += same_body
        tail = d[0x0F]
        h = pia.Header(d[5:9], d[9:13], int.from_bytes(d[13:15], "big"), d[len(d) - tail:] if tail else b"", d[0x10:0x18])
        again = crypto.seal(body, mac, h)
        n["packet_same"] += again == d
        if not same_body and shown < 3:
            shown += 1
            print("message list differs at %s %s -> %s" % (pk["t"], pk["src"], pk["dst"]))
            print("  original", body[:48].hex())
            print("  rebuilt ", rebuilt[:48].hex())
    print(n)


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

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


def masks(body, limit=8):
    """The field mask byte of each message, walking the list as the reader does."""
    out, i, size = [], 0, 0
    while i < len(body):
        m = body[i]
        if m == 0xFF:
            break
        out.append("%02x" % m)
        i += 1
        if m & 1: i += 1
        if m & 2: size = int.from_bytes(body[i:i + 2], "big"); i += 2
        if m & 4: i += 4
        if m & 8: i += 8
        i = (i + size + 3) & ~3
    return " ".join(out[:limit])


def main(path):
    key, macs, session, packets = rise_net.read_switch(path)
    if not key or session is None:
        sys.exit("no key or advertise data in the capture")
    crypto = pia.PiaCrypto(key, session)
    n = dict(total=0, opened=0, body_same=0, only_padding_differs=0, other_differences=0, packet_same=0, skipped=0)
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
        core = rebuilt[:-1]  # without my 0xff terminator: a body may end right after its last message
        same_body = body[:len(core)] == core and set(body[len(core):]) <= {0xFF}
        n["body_same"] += same_body
        if not same_body:
            # same message list, same masks, same length: then only bytes between a payload and the next 4 boundary differ
            padding_only = masks(body, 999) == masks(core + b"\xff", 999) and len(body) in range(len(core), len(core) + 2) \
                and [m.payload for m in pia.parse_body(body)] == [m.payload for m in msgs]
            n["only_padding_differs"] += padding_only
            n["other_differences"] += not padding_only
        tail = d[0x0F]
        h = pia.Header(d[5:9], d[9:13], int.from_bytes(d[13:15], "big"), d[len(d) - tail:] if tail else b"", d[0x10:0x18])
        again = crypto.seal(body, mac, h)
        n["packet_same"] += again == d
        if not same_body and not padding_only and shown < 4:
            shown += 1
            print("differs at %s %s -> %s: %d messages, body %d bytes, mine %d" % (
                pk["t"], pk["src"], pk["dst"], len(msgs), len(body), len(core)))
            print("  masks  original", masks(body), " mine", masks(core + b"\xff"))
            i = next((k for k in range(min(len(body), len(core))) if body[k] != core[k]), min(len(body), len(core)))
            print("  first difference at byte", i)
            print("  original", body[max(0, i - 8):i + 24].hex())
            print("  mine    ", core[max(0, i - 8):i + 24].hex())
    print(n)


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

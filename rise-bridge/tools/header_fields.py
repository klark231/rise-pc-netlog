#!/usr/bin/env python3
"""Reads the header conventions the station loop needs out of a Switch capture.

  python3 tools/header_fields.py local_play_<date>.txt

 1. trailer: how the 2-byte entries relate to the receivers' keys (which byte order)
 2. counters: the u16 counter and the 8-byte nonce counter of one sender, in a row (byte order, step)
 3. game messages (type 0x68): the distinct (flags, port, dst) they carry
 4. keepalives (type 0x58): the first few payloads from one sender
"""
import collections, os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
sys.path.insert(0, os.environ.get("RISE_NET", os.path.join(here, "..", "tests")))
import rise_net
from bridge import pia


def main(path):
    key, macs, session, packets = rise_net.read_switch(path)
    crypto = pia.PiaCrypto(key, session)
    own = {}  # source address -> its key (the sender key in its packets)
    for pk in packets:
        d = bytes(pk["data"])
        if d.startswith(pia.MAGIC) and len(d) >= 0x20:
            own[pk["src"]] = d[9:13]
    tr = collections.Counter()
    seq = collections.defaultdict(list)
    for pk in packets:
        d = bytes(pk["data"])
        if not d.startswith(pia.MAGIC) or len(d) < 0x20:
            continue
        t = d[0x0F]
        if t:
            tail = d[len(d) - t:]
            for k in range(0, t, 2):
                entry = tail[k:k + 2]
                for addr, kk in own.items():
                    for name, cand in (("key[0:2]", kk[0:2]), ("key[2:4]", kk[2:4]), ("key[0:2] reversed", kk[0:2][::-1]), ("key[2:4] reversed", kk[2:4][::-1])):
                        if entry == cand:
                            tr[name] += 1
        seq[pk["src"], d[5:9]].append((d[13:15].hex(), d[0x10:0x18].hex()))
    print("1. trailer entries match:", dict(tr) or "nothing found")
    for (src, rk), rows in list(seq.items())[:3]:
        print("2.", src, "-> receiver key", rk.hex(), "counter / nonce counter:", rows[:6])
    fields, keep = collections.Counter(), []
    for pk in packets:
        d = bytes(pk["data"])
        mac = macs.get(pk["src"])
        body = crypto.open(d, mac) if mac and d.startswith(pia.MAGIC) and len(d) >= 0x20 else None
        if not body:
            continue
        for m in pia.parse_body(body):
            if m.ptype == 0x68:
                fields[(m.flags, m.port, hex(m.dst))] += 1
            elif m.ptype == 0x58 and len(keep) < 6:
                keep.append((pk["src"], m.flags, m.port, hex(m.dst), m.payload.hex()))
    print("3. game messages (flags, port, dst):", fields.most_common(12))
    for k in keep:
        print("4. keepalive", k)


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

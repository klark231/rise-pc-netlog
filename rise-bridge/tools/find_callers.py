#!/usr/bin/env python3
"""Who calls a function in main.elf (bl / b to it)? Optionally only the callers near some other addresses.

  python3 rise-bridge/tools/find_callers.py <out>/main.elf --func 0x1ed03f0 [--near 0x34ef734 --near 0x63f2530 ...]
         [--window 0x3000] [--context 30] > callers.txt

Addresses are offsets from the start of main (`main+0x...`). Without --near it lists every caller (just the addresses
if there are more than 40). With --near it prints the code around each caller that lies within --window bytes of one
of those addresses: the idea is to find out whether the checksum function is called next to the code that builds the
game's messages. Only reads your file. Uses numpy if it is installed.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_hello import load_exec, dis, sx
from find_xrefs import function_start

try:
    import numpy as np
except ImportError:
    np = None


def calls_to(code, base, func):
    out = []
    n = len(code) // 4
    if np is not None:
        a = np.frombuffer(code[:n * 4], dtype="<u4")
        for kind, mask in (("bl", 0x94000000), ("b", 0x14000000)):
            idx = np.nonzero((a & 0xFC000000) == mask)[0]
            imm = (a[idx] & 0x3FFFFFF).astype(np.int64)
            imm -= (imm >> 25 & 1) << 26
            hit = idx[(base + (idx + imm) * 4) == func]
            out += [(int(i), kind) for i in hit]
    else:
        for i in range(n):
            w = struct.unpack_from("<I", code, i * 4)[0]
            for kind, mask in (("bl", 0x94000000), ("b", 0x14000000)):
                if (w & 0xFC000000) == mask and base + (i + sx(w & 0x3FFFFFF, 26)) * 4 == func:
                    out.append((i, kind))
    return sorted(out)


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-") or "--func" not in a:
        print(__doc__); return
    func = int(a[a.index("--func") + 1], 0)
    near = [int(a[i + 1], 0) for i in range(len(a)) if a[i] == "--near"]
    win = int(a[a.index("--window") + 1], 0) if "--window" in a else 0x3000
    ctx = int(a[a.index("--context") + 1]) if "--context" in a else 30
    for base, code in load_exec(a[0]):
        calls = calls_to(code, base, func)
        print("%d call(s) to main+0x%x" % (len(calls), func))
        if not near:
            for i, kind in (calls if len(calls) <= 40 else calls[:40]):
                print("  %s from main+0x%x" % (kind, base + i * 4))
            continue
        shown = 0
        for i, kind in calls:
            pc = base + i * 4
            close = [x for x in near if abs(pc - x) <= win]
            if not close:
                continue
            shown += 1
            fs = function_start(code, base, i)
            print("=== %s from main+0x%x (%+d bytes from main+0x%x); function starts ~main+0x%s" %
                  (kind, pc, pc - close[0], close[0], "%x" % (base + fs * 4) if fs is not None else "?"))
            for k in range(max(0, i - ctx), min(len(code) // 4, i + ctx // 2)):
                w = struct.unpack_from("<I", code, k * 4)[0]
                print("  %08x  %08x  %s%s" % (base + k * 4, w, dis(w, base + k * 4) or "", "  <--" if k == i else ""))
        if not shown:
            print("(none of the callers is within 0x%x of the addresses given)" % win)
            print("all callers:", ", ".join("main+0x%x" % (base + i * 4) for i, _ in calls[:60]))


if __name__ == "__main__":
    main()

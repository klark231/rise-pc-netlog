#!/usr/bin/env python3
"""Where is a 32-bit constant in main.elf: loaded by code (mov + movk), or sitting in data (a table)?

  python3 rise-bridge/tools/find_const.py <out>/main.elf [--const 0xdaabadec ...] [--context 30] > const.txt

Default constants: 0xdaabadec and 0xdaabaded, the reduction value the game message checksum's deltas follow
(rise-bridge/bridge/gamemsg.py). It also looks for the 256-entry lookup table such a checksum would use (the first
entries of the table for that value, MSB-first and reflected). Offsets are from the start of main (`main+0x...`).
Only reads your file.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_hello import dis


def load_all(path):
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF":
        sys.exit("not an ELF file; run tools/nso.py first and give it <out>/main.elf")
    phoff, = struct.unpack_from("<Q", d, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", d, 0x36)
    segs = []
    for i in range(phnum):
        t, fl, off, va, _, fsz, _, _ = struct.unpack_from("<IIQQQQQQ", d, phoff + i * phentsize)
        if t == 1:
            segs.append((va, fl, d[off:off + fsz]))
    return segs


def table_msb(p):
    out = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ p) & 0xFFFFFFFF if r & 0x80000000 else (r << 1) & 0xFFFFFFFF
        out.append(r)
    return out


def table_refl(p):
    rp = int("{:032b}".format(p)[::-1], 2)
    out = []
    for i in range(256):
        r = i
        for _ in range(8):
            r = (r >> 1) ^ rp if r & 1 else r >> 1
        out.append(r)
    return out


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        print(__doc__); return
    consts = [int(a[i + 1], 0) for i in range(len(a)) if a[i] == "--const"] or [0xDAABADEC, 0xDAABADED]
    ctx = int(a[a.index("--context") + 1]) if "--context" in a else 30
    segs = load_all(a[0])
    for c in consts:
        print("##### constant 0x%08x" % c)
        lo, hi = c & 0xFFFF, c >> 16
        # 1. in code: mov/movk (either order), 32-bit or 64-bit registers
        n = 0
        for va, fl, data in segs:
            if not fl & 1:
                continue
            words = struct.unpack("<%dI" % (len(data) // 4), data[:len(data) // 4 * 4])
            for i, w in enumerate(words):
                for sf in (0, 1):
                    first = (0x52800000 | sf << 31) | lo << 5          # mov w/x, #lo
                    if (w & 0xFFE0001F & ~31) == (first & 0xFFE0001F & ~31) and (w & 0xFFE00000) == (first & 0xFFE00000) and ((w >> 5) & 0xFFFF) == lo:
                        rd = w & 31
                        want = (0x72A00000 | sf << 31) | hi << 5 | rd   # movk, lsl #16
                        for j in range(i + 1, min(i + 9, len(words))):
                            if words[j] == want:
                                n += 1
                                print("=== code: main+0x%x (mov) / +0x%x (movk)" % (va + i * 4, va + j * 4))
                                for k in range(max(0, i - ctx // 2), min(len(words), j + ctx)):
                                    print("  %08x  %08x  %s%s" % (va + k * 4, words[k], dis(words[k], va + k * 4) or "", "  <--" if k in (i, j) else ""))
                                break
                if n >= 6:
                    break
            if n >= 6:
                print("(stopped at 6 code hits)"); break
        if not n:
            print("(no mov/movk pair loads it)")
        # 2. in data, as a raw 32-bit value either way round
        for name, pat in (("little-endian", struct.pack("<I", c)), ("big-endian", struct.pack(">I", c))):
            hits = []
            for va, fl, data in segs:
                at = data.find(pat)
                while at >= 0 and len(hits) < 20:
                    hits.append(va + at)
                    at = data.find(pat, at + 1)
            print("in data, %s: %s" % (name, ", ".join("main+0x%x" % h for h in hits) or "none"))
        # 3. the table
        for tname, tab in (("MSB-first", table_msb(c)), ("reflected", table_refl(c))):
            pat = struct.pack("<4I", *tab[1:5])
            pat_be = struct.pack(">4I", *tab[1:5])
            for ename, p in (("LE", pat), ("BE", pat_be)):
                for va, fl, data in segs:
                    at = data.find(p)
                    if at >= 0:
                        print("TABLE: a %s lookup table (%s entries) starts at main+0x%x" % (tname, ename, va + at - 4))
        print()


if __name__ == "__main__":
    main()

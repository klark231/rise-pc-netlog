#!/usr/bin/env python3
"""Who uses an address in main.elf? Prints the code that references it, the function around it and who calls that.

  python3 rise-bridge/tools/find_xrefs.py <out>/main.elf --addr 0xb5d5e68 [--addr 0x...] [--range 0x40] [--context 40] > xrefs.txt

Addresses are offsets from the start of main (the `main+0x...` of the logs and of find_hello.py). A reference is an
`adrp` followed within 12 instructions by an `add`/`ldr`/`ldrb`/`ldrh` on the same register whose address lands in
[addr, addr+range]. With the CRC-32 table (main+0xb5d5e68) this lists the code that computes the checksum; with the
hello bytes (main+0xb5bbde1, 0xb5f7e82, ...) use --range 0x200 to catch the table they sit in.
Only reads your file. Uses numpy if it is installed (much faster).
"""
import struct, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from find_hello import load_exec, dis, sx

try:
    import numpy as np
except ImportError:
    np = None


def adrp_targets(words, base):
    """[(index, rd, page)] for every adrp"""
    out = []
    if np is not None:
        a = np.frombuffer(words, dtype="<u4")
        idx = np.nonzero((a & 0x9F000000) == 0x90000000)[0]
        for i in idx:
            w = int(a[i])
            imm = sx(((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3), 21) << 12
            out.append((int(i), w & 31, ((base + int(i) * 4) & ~0xFFF) + imm))
    else:
        for i in range(len(words) // 4):
            w = struct.unpack_from("<I", words, i * 4)[0]
            if (w & 0x9F000000) == 0x90000000:
                imm = sx(((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3), 21) << 12
                out.append((i, w & 31, ((base + i * 4) & ~0xFFF) + imm))
    return out


def low_offset(w, rn):
    """the byte offset an add/ldr on register rn adds to the page, or None"""
    if (w >> 5) & 31 != rn:
        return None
    if (w & 0x7F800000) == 0x11000000 and not (w >> 29) & 1:           # add rd, rn, #imm  (not adds)
        return ((w >> 10) & 0xFFF) << (12 if (w >> 22) & 1 else 0)
    if (w & 0x3B000000) == 0x39000000 and not (w >> 26) & 1:           # ldr/ldrb/ldrh/str ... unsigned offset
        return ((w >> 10) & 0xFFF) << (w >> 30)
    return None


def function_start(words, base, i):
    """Walks back to the nearest instruction that looks like a function's first one: a push of registers with
    pre-decrement (stp ..., [sp, #-N]!) or a `sub sp, sp, #N`, or paciasp. A guess: callee-saved pushes can follow."""
    for k in range(i, max(-1, i - 20000), -1):
        w = struct.unpack_from("<I", words, k * 4)[0]
        if (w & 0xFFC003E0) == 0xA98003E0 or (w & 0xFF0003FF) == 0xD10003FF or w == 0xD503233F:
            if k > 0 and struct.unpack_from("<I", words, (k - 1) * 4)[0] == 0xD503233F:
                return k - 1
            return k
    return None


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        print(__doc__); return
    path, addrs = a[0], [int(a[i + 1], 0) for i in range(len(a)) if a[i] == "--addr"]
    rng = int(a[a.index("--range") + 1], 0) if "--range" in a else 0
    ctx = int(a[a.index("--context") + 1]) if "--context" in a else 40
    if not addrs:
        sys.exit("give at least one --addr")
    for base, code in load_exec(path):
        words = code[:len(code) // 4 * 4]
        ads = adrp_targets(words, base)
        by_page = {}
        for i, rd, page in ads:
            by_page.setdefault(page, []).append((i, rd))
        for addr in addrs:
            print("##### references to main+0x%x (range +0x%x)" % (addr, rng))
            n = 0
            for page in range((addr & ~0xFFF) - (0x1000 if rng else 0), ((addr + rng) & ~0xFFF) + 0x1000, 0x1000):
                for i, rd in by_page.get(page, []):
                    for j in range(i + 1, min(i + 13, len(words) // 4)):
                        w = struct.unpack_from("<I", words, j * 4)[0]
                        off = low_offset(w, rd)
                        if off is not None and addr <= page + off <= addr + rng:
                            n += 1
                            fs = function_start(words, base, i)
                            print("=== ref %d: adrp at main+0x%x, use at +0x%x -> main+0x%x; function starts ~main+0x%s" %
                                  (n, base + i * 4, base + j * 4, page + off, "%x" % (base + fs * 4) if fs is not None else "?"))
                            for k in range(max(0, i - ctx // 2), min(len(words) // 4, j + ctx)):
                                pc = base + k * 4
                                ww = struct.unpack_from("<I", words, k * 4)[0]
                                print("  %08x  %08x  %s%s" % (pc, ww, dis(ww, pc) or "", "  <--" if k in (i, j) else ""))
                            break
                    if n >= 12:
                        break
                if n >= 12:
                    print("(stopped at 12 references)"); break
            if not n:
                print("(none found: the address may be reached through a pointer table; try --range 0x400)")
            print()


if __name__ == "__main__":
    main()

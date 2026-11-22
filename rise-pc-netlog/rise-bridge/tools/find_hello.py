#!/usr/bin/env python3
"""Finds where the game builds its hello message (the bytes 00 01 03 02 = the 32-bit value 0x02030100) in main.elf.

  python3 tools/nso.py <exefs folder> <out folder>          (the recomp project's own tool; makes <out>/main.elf)
  python3 rise-bridge/tools/find_hello.py <out>/main.elf [--context N] [--max M] > hello_code.txt

Looks for `mov w?, #0x100` followed within a few instructions by `movk w?, #0x203, lsl #16`, and prints each place with
the code around it (a small disassembler: words it doesn't know are shown as raw hex). Offsets are relative to the
start of main, the same as the `main+0x24d9cb0` offsets in the capture logs.
Only reads your file and prints offsets and code; nothing is written or sent anywhere.
"""
import struct, sys


def load_exec(path):
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF":
        sys.exit("not an ELF file; run tools/nso.py first and give it <out>/main.elf")
    phoff, = struct.unpack_from("<Q", d, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", d, 0x36)
    segs = []
    for i in range(phnum):
        p_type, p_flags, p_off, p_vaddr, _, p_filesz, _, _ = struct.unpack_from("<IIQQQQQQ", d, phoff + i * phentsize)
        if p_type == 1 and p_flags & 1:
            segs.append((p_vaddr, d[p_off:p_off + p_filesz]))
    return segs


def sx(v, bits):
    return v - (1 << bits) if v >> (bits - 1) else v


def reg(n, sf=1, sp=False):
    if n == 31:
        return "sp" if sp else ("xzr" if sf else "wzr")
    return ("x%d" if sf else "w%d") % n


def dis(w, pc):
    """A small subset of AArch64; everything else comes back as None."""
    rd, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
    sf = w >> 31
    if w == 0xD65F03C0: return "ret"
    if (w & 0xFC000000) == 0x94000000: return "bl 0x%x" % (pc + sx(w & 0x3FFFFFF, 26) * 4)
    if (w & 0xFC000000) == 0x14000000: return "b 0x%x" % (pc + sx(w & 0x3FFFFFF, 26) * 4)
    if (w & 0xFFFFFC1F) == 0xD63F0000: return "blr x%d" % rn
    if (w & 0xFFFFFC1F) == 0xD61F0000: return "br x%d" % rn
    if (w & 0x7F800000) == 0x52800000:
        return "mov %s, #0x%x%s" % (reg(rd, sf), (w >> 5) & 0xFFFF, (", lsl #%d" % (16 * ((w >> 21) & 3))) if (w >> 21) & 3 else "")
    if (w & 0x7F800000) == 0x72800000:
        return "movk %s, #0x%x, lsl #%d" % (reg(rd, sf), (w >> 5) & 0xFFFF, 16 * ((w >> 21) & 3))
    if (w & 0x7F800000) == 0x12800000:
        return "movn %s, #0x%x" % (reg(rd, sf), (w >> 5) & 0xFFFF)
    if (w & 0x1F000000) == 0x11000000:
        op = "sub" if (w >> 30) & 1 else "add"
        s = "s" if (w >> 29) & 1 else ""
        imm = ((w >> 10) & 0xFFF) << (12 if (w >> 22) & 1 else 0)
        if s and rd == 31: return "cmp%s %s, #0x%x" % ("" if op == "sub" else "n", reg(rn, sf, True), imm)
        return "%s%s %s, %s, #0x%x" % (op, s, reg(rd, sf, not s), reg(rn, sf, True), imm)
    if (w & 0x1F200000) == 0x0B000000:
        op = "sub" if (w >> 30) & 1 else "add"
        s = "s" if (w >> 29) & 1 else ""
        sh = ["lsl", "lsr", "asr", "?"][(w >> 22) & 3]
        amt = (w >> 10) & 63
        return "%s%s %s, %s, %s%s" % (op, s, reg(rd, sf), reg(rn, sf), reg(rm, sf), (", %s #%d" % (sh, amt)) if amt else "")
    if (w & 0x1F000000) == 0x0A000000:
        opc = (w >> 29) & 3
        n = (w >> 21) & 1
        names = [["and", "bic"], ["orr", "orn"], ["eor", "eon"], ["ands", "bics"]][opc][n]
        amt = (w >> 10) & 63
        if names == "orr" and rn == 31 and amt == 0: return "mov %s, %s" % (reg(rd, sf), reg(rm, sf))
        return "%s %s, %s, %s%s" % (names, reg(rd, sf), reg(rn, sf), reg(rm, sf), (", %s #%d" % (["lsl", "lsr", "asr", "ror"][(w >> 22) & 3], amt)) if amt else "")
    if (w & 0x7FE08000) == 0x1B000000:
        ra = (w >> 10) & 31
        return ("mul %s, %s, %s" if ra == 31 else "madd %s, %s, %s, " + reg(ra, sf)) % (reg(rd, sf), reg(rn, sf), reg(rm, sf))
    if (w & 0x9F000000) == 0x90000000:
        imm = sx(((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3), 21) << 12
        return "adrp x%d, 0x%x" % (rd, (pc & ~0xFFF) + imm)
    if (w & 0x9F000000) == 0x10000000:
        return "adr x%d, 0x%x" % (rd, pc + sx(((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3), 21))
    if (w & 0x7E000000) == 0x34000000:
        return "%s %s, 0x%x" % ("cbnz" if (w >> 24) & 1 else "cbz", reg(rd, sf), pc + sx((w >> 5) & 0x7FFFF, 19) * 4)
    if (w & 0x7E000000) == 0x36000000:
        return "%s %s, #%d, 0x%x" % ("tbnz" if (w >> 24) & 1 else "tbz", reg(rd, 1 if w >> 31 else 0), ((w >> 31) << 5) | ((w >> 19) & 31), pc + sx((w >> 5) & 0x3FFF, 14) * 4)
    if (w & 0xFF000010) == 0x54000000:
        return "b.%s 0x%x" % (["eq", "ne", "hs", "lo", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le", "al", "nv"][w & 15], pc + sx((w >> 5) & 0x7FFFF, 19) * 4)
    if (w & 0x3B000000) == 0x39000000:  # load/store, unsigned offset
        size = w >> 30
        opc = (w >> 22) & 3
        imm = ((w >> 10) & 0xFFF) << size
        name = {(0, 0): "strb", (0, 1): "ldrb", (1, 0): "strh", (1, 1): "ldrh", (2, 0): "str", (2, 1): "ldr", (3, 0): "str", (3, 1): "ldr"}.get((size, opc))
        if name and not (w >> 26) & 1:
            return "%s %s, [%s, #0x%x]" % (name, reg(rd, 1 if size == 3 else 0), reg(rn, 1, True), imm)
    if (w & 0x3E000000) == 0x28000000:  # ldp/stp
        opc = w >> 30
        l = (w >> 22) & 1
        idx = (w >> 23) & 3
        sc = 3 if opc == 2 else 2
        imm = sx((w >> 15) & 0x7F, 7) << sc
        t2 = (w >> 10) & 31
        r = 1 if opc == 2 else 0
        base = reg(rn, 1, True)
        fmt = {1: "[%s], #%d", 2: "[%s, #%d]", 3: "[%s, #%d]!"}[idx] % (base, imm) if idx else None
        if fmt: return "%s %s, %s, %s" % ("ldp" if l else "stp", reg(rd, r), reg(t2, r), fmt)
    return None


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__); return
    ctx = int(args[args.index("--context") + 1]) if "--context" in args else 24
    mx = int(args[args.index("--max") + 1]) if "--max" in args else 12
    hits = 0
    for base, code in load_exec(args[0]):
        words = struct.unpack("<%dI" % (len(code) // 4), code[:len(code) // 4 * 4])
        for i, w in enumerate(words):
            if (w & 0xFFFFFFE0) == 0x52802000:  # mov w?, #0x100
                rd = w & 31
                for j in range(i + 1, min(i + 9, len(words))):
                    if words[j] == 0x72A04060 | rd:  # movk w?, #0x203, lsl #16
                        hits += 1
                        print("=== hit %d: main+0x%x  (mov at +0x%x, movk at +0x%x)" % (hits, base + i * 4, base + i * 4, base + j * 4))
                        lo, hi = max(0, i - ctx), min(len(words), j + ctx)
                        for k in range(lo, hi):
                            pc = base + k * 4
                            mark = "  <--" if k in (i, j) else ""
                            print("  %08x  %08x  %s%s" % (pc, words[k], dis(words[k], pc) or "", mark))
                        break
                if hits >= mx:
                    print("(stopped at --max %d)" % mx); return
    print("hits:", hits)


if __name__ == "__main__":
    main()

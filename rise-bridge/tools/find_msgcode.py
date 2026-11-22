#!/usr/bin/env python3
"""Broader search for the game's message-building code in main.elf (find_hello.py found nothing: the constant is built
some other way). Prints a short report, no code dump:

  python3 tools/find_msgcode.py <out>/main.elf > msgcode.txt

1. the ELF's loadable segments (so we can see what was read, and which are executable),
2. the 4 bytes 00 01 03 02 / 00 01 03 01 / 00 02 03 / 00 03 02 (the message types) in the raw data, by segment,
3. code that builds 0x02030100 / 0x01030100 / 0x00030200-style values with mov/movk in EITHER order, and with the
   halves 0x0100 and 0x0203 / 0x0103 appearing near each other (up to 12 instructions apart),
4. CRC-32 tables (the 0xEDB88320 and 0x04C11DB7 kinds), since the 4-byte header in front of every message looks like a
   checksum of the body: each hit says where the table is and how many code places load its address (adrp+add).
Only reads your file; nothing is written or sent anywhere.
"""
import struct, sys


def segments(path):
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF":
        sys.exit("not an ELF file")
    phoff, = struct.unpack_from("<Q", d, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", d, 0x36)
    out = []
    for i in range(phnum):
        t, fl, off, va, _, fsz, msz, _ = struct.unpack_from("<IIQQQQQQ", d, phoff + i * phentsize)
        if t == 1:
            out.append((va, fl, d[off:off + fsz]))
    return out


def find_all(hay, needle, limit=25):
    res, i = [], hay.find(needle)
    while i != -1 and len(res) < limit:
        res.append(i)
        i = hay.find(needle, i + 1)
    return res


def movz(w):   # (reg, imm16, shift) for movz/movn-free w-register moves, else None
    if (w & 0x7F800000) == 0x52800000:
        return w & 31, (w >> 5) & 0xFFFF, 16 * ((w >> 21) & 3), "z"
    if (w & 0x7F800000) == 0x72800000:
        return w & 31, (w >> 5) & 0xFFFF, 16 * ((w >> 21) & 3), "k"
    return None


def const_builds(words, base, targets, window=12):
    """targets: {value: name}. Finds a register built from mov/movk to one of the values."""
    hits = []
    for i, w in enumerate(words):
        a = movz(w)
        if not a or a[3] != "z":
            continue
        reg = a[0]
        val, got = a[1] << a[2], 1
        for j in range(i + 1, min(i + window, len(words))):
            b = movz(words[j])
            if b and b[0] == reg and b[3] == "k":
                val = (val & ~(0xFFFF << b[2])) | (b[1] << b[2])
                got += 1
                if (val & 0xFFFFFFFF) in targets and got >= 2:
                    hits.append((base + i * 4, targets[val & 0xFFFFFFFF]))
                    break
    return hits


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    segs = segments(sys.argv[1])
    print("== segments (vaddr, flags rwx, size)")
    for va, fl, data in segs:
        print("  0x%08x  %s%s%s  %d bytes" % (va, "r" if fl & 4 else "-", "w" if fl & 2 else "-", "x" if fl & 1 else "-", len(data)))

    print("\n== message type bytes in raw data (offset = main+vaddr)")
    for name, pat in (("00 01 03 02", b"\x00\x01\x03\x02"), ("00 01 03 01", b"\x00\x01\x03\x01"),
                      ("00 02 03", b"\x00\x02\x03"), ("00 03 02", b"\x00\x03\x02"), ("00 04 06", b"\x00\x04\x06")):
        tot = 0
        lines = []
        for va, fl, data in segs:
            hits = find_all(data, pat, 4000)
            tot += len(hits)
            if len(pat) == 4 and hits:
                lines.append("   %s: %d in segment 0x%x (first: %s)" % (name, len(hits), va, ", ".join("0x%x" % (va + h) for h in hits[:6])))
        print("  %s: %d total" % (name, tot))
        for l in lines:
            print(l)

    print("\n== code that builds the type values (mov/movk, either order)")
    targets = {0x02030100: "00 01 03 02 as u32", 0x01030100: "00 01 03 01 as u32", 0x00030200: "00 02 03 00 (3 bytes)",
               0x02030000: "00 00 03 02", 0x00060400: "00 04 06 00 (3 bytes)", 0x02030200: "00 02 03 02"}
    total = 0
    for va, fl, data in segs:
        if not fl & 1:
            continue
        words = struct.unpack("<%dI" % (len(data) // 4), data[:len(data) // 4 * 4])
        for addr, name in const_builds(words, va, targets)[:40]:
            print("  main+0x%x  %s" % (addr, name))
            total += 1
    print("  %d places" % total)

    print("\n== CRC-32 tables")
    tables = {"reflected 0xEDB88320": bytes.fromhex("0000000096300777 2c610eee ba51 0999".replace(" ", "")),
              "normal 0x04C11DB7": bytes.fromhex("0000000004c11db7 09823b6e 0d4326d9".replace(" ", ""))}
    for name, pat in tables.items():
        for va, fl, data in segs:
            for h in find_all(data, pat, 3):
                print("  %s table at main+0x%x" % (name, va + h))
    print("\nDone.")


if __name__ == "__main__":
    main()

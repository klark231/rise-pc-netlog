#!/usr/bin/env python3
"""Is the hello a linear (XOR-affine) function of the MAC's bits?

  python3 tools/solve_hello.py ~/hello_pairs.txt

Reads "mac hello" lines. Adds each sample to a GF(2) system, hello = A * mac_bits + b. Once the system has enough
samples, every further sample is a check: if the hello really is affine, each check agrees. Prints the verdict, and for
an affine one the constants to compute the hello of any MAC (tools/hello_affine.json).
"""
import json, sys


def bits(mac):
    return int.from_bytes(mac, "big")


def main(path):
    samples = []
    for line in open(path):
        p = line.split()
        if len(p) == 2 and len(p[0]) == 12 and len(p[1]) == 16:
            samples.append((bytes.fromhex(p[0]), bytes.fromhex(p[1])))
    seen, uniq = set(), []
    for m, h in samples:
        if m not in seen:
            seen.add(m)
            uniq.append((m, h))
    samples = uniq
    print(len(samples), "distinct MACs")
    basis = {}  # pivot bit -> (x, y), x has the constant in bit 48
    checks = agree = 0
    first_conflict = None
    for m, h in samples:
        x = (bits(m) << 1) | 1  # bit 0 = the constant term
        y = int.from_bytes(h, "big")
        while x:
            piv = x.bit_length() - 1
            if piv in basis:
                bx, by = basis[piv]
                x ^= bx
                y ^= by
            else:
                basis[piv] = (x, y)
                break
        else:
            checks += 1
            if y == 0:
                agree += 1
            elif first_conflict is None:
                first_conflict = m.hex()
    print("independent samples used:", len(basis), "| further checks:", checks, "| agree:", agree)
    if checks == 0:
        print("not enough samples to test: need more than", len(basis), "distinct MACs with varied bits")
    elif agree == checks:
        print("VERDICT: affine. Every check agreed, so the hello is a linear function of the MAC.")
        # back-substitute: solve for the columns (one 64-bit value per MAC bit, plus the constant)
        cols = {}
        for piv in sorted(basis):
            x, y = basis[piv]
            for j in range(piv):  # reduce with already solved lower pivots (free variables = 0)
                if x >> j & 1 and j in cols:
                    y ^= cols[j]
            cols[piv] = y
        out = {"constant": "%016x" % cols.get(0, 0), "bit_values": {str(k - 1): "%016x" % v for k, v in cols.items() if k > 0}}
        json.dump(out, open("hello_affine.json", "w"), indent=1)
        print("wrote hello_affine.json (free MAC bits that never varied are fixed at 0, so only use it for MACs like the samples)")
    else:
        print("VERDICT: NOT affine (%d of %d checks disagreed, first on MAC %s). It's a non-linear hash." % (checks - agree, checks, first_conflict))


if __name__ == "__main__":
    main(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__)

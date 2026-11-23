#!/usr/bin/env python3
"""Names from the game's type database (TDB 71), read out of the Switch version's main NSO.

The type, field and method names that the notes quote (snow.PlayerNetwork and its packets, via.puppet.RemoteGameObject)
come from here. Uses mhrise-recomp's tools/query_tdb.py (the NSO and TDB reading); the table layouts are REFramework's
(shared/sdk/RETypeDB.hpp, v71).

    python3 tdb_types.py <mhrise-recomp> <exefs/main> list [text]      types whose name contains text
    python3 tdb_types.py <mhrise-recomp> <exefs/main> show <name|id>   a type's fields and methods, and its parents'
"""
import struct
import sys
from pathlib import Path

ID = (1 << 19) - 1


class Tdb:
    def __init__(self, db):
        self.db = db
        self.n_types = struct.unpack_from("<I", db, 0x0C)[0]
        self.types, self.impls, self.methods, self.method_impls, self.fields, self.field_impls = \
            struct.unpack_from("<6Q", db, 0x60)
        self.pool = struct.unpack_from("<Q", db, 0xD0)[0]

    def u16(self, o): return struct.unpack_from("<H", self.db, o)[0]
    def u32(self, o): return struct.unpack_from("<I", self.db, o)[0]
    def u64(self, o): return struct.unpack_from("<Q", self.db, o)[0]

    def string(self, offset):
        start = self.pool + offset
        return self.db[start:self.db.index(b"\0", start)].decode("utf-8", "replace")

    def impl(self, t): return self.impls + ((self.u64(self.types + 72 * t + 8) >> 38) & 0x3FFFF) * 48
    def parent(self, t): return (self.u64(self.types + 72 * t) >> 19) & ID
    def declaring(self, t): return (self.u64(self.types + 72 * t) >> 38) & ID

    def name(self, t):
        outer = self.declaring(t)
        ns = self.name(outer) if outer else self.string(self.u32(self.impl(t) + 4))
        return (ns + "." if ns else "") + self.string(self.u32(self.impl(t)))

    def field_list(self, t):
        first = (self.u64(self.types + 72 * t + 32) >> 44) & ID
        for i in range(first, first + ((self.u64(self.impl(t) + 16) >> 33) & 0xFFFFFF)):
            bits = self.u64(self.fields + 8 * i)
            if bits & ID != t:
                break
            info = self.field_impls + ((bits >> 19) & ID) * 12
            yield (self.string(self.u32(info + 8) & 0xFFFFFFF), (bits >> 38) & ID, self.u32(info + 4) & 0x3FFFFFF,
                   bool((self.u16(info + 2) >> 1) & 0x10))

    def method_list(self, t):
        first = (self.u64(self.types + 72 * t + 32) >> 22) & 0x3FFFFF
        for k in range(first, first + self.u16(self.impl(t) + 24)):
            yield k, self.string(self.u32(self.method_impls + 12 * (self.u32(self.methods + 12 * k + 4) & ID) + 8))


def main(args):
    if len(args) < 3:
        sys.exit(__doc__)
    sys.path.insert(0, str(Path(args[0]) / "tools"))
    import query_tdb
    tdb = Tdb(bytes(query_tdb.read_tdb(Path(args[1]))))
    if args[2] == "list":
        text = args[3] if len(args) > 3 else ""
        for t in range(1, tdb.n_types):
            name = tdb.name(t)
            if text in name:
                print(t, name)
    elif args[2] == "show":
        wanted = args[3]
        t = int(wanted) if wanted.isdigit() else next(i for i in range(1, tdb.n_types) if tdb.name(i) == wanted)
        while t:
            print(f"[{t}] {tdb.name(t)}")
            for name, ftype, offset, static in tdb.field_list(t):
                print(f"  +{offset:#x} {name}: {tdb.name(ftype)}{' (static)' if static else ''}")
            for k, name in tdb.method_list(t):
                print(f"  method {k} {name}")
            t = tdb.parent(t)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

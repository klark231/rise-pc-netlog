"""The hello a Switch host expects from a joining game, worked out from its MAC.

Every game message starts with a hello (15 bytes). The host's hello to a station is a fixed function of the STATION'S
MAC, and the hello the host expects back is the same function of the HOST'S MAC. That function is affine over GF(2):
message(mac) = message(base) XOR (the deltas of the bits in which mac differs from base). tools/hello_probe.py measures
the base message and the 48 deltas against a real host and writes hello_map.json; this loads it.
"""
import json
import os


class HelloMap:
    def __init__(self, base_mac: bytes, base_msg: bytes, deltas):
        self.base_mac, self.base_msg, self.deltas = base_mac, base_msg, [bytes(d) for d in deltas]

    def message_for(self, mac: bytes) -> bytes:
        x = int.from_bytes(mac, "big") ^ int.from_bytes(self.base_mac, "big")
        out = int.from_bytes(self.base_msg, "big")
        for b in range(48):
            if x >> b & 1:
                out ^= int.from_bytes(self.deltas[b], "big")
        return out.to_bytes(len(self.base_msg), "big")

    @classmethod
    def load(cls, path):
        d = json.load(open(path))
        return cls(bytes.fromhex(d["base_mac"]), bytes.fromhex(d["base_msg"]), [bytes.fromhex(x) for x in d["deltas"]])

    def save(self, path):
        json.dump({"base_mac": self.base_mac.hex(), "base_msg": self.base_msg.hex(),
                   "deltas": [d.hex() for d in self.deltas]}, open(path, "w"), indent=1)


def is_hello(game: bytes) -> bool:
    """A game message that is a hello: 15 bytes, and 00 01 03 02 once its XOR byte is off"""
    return len(game) == 15 and bytes(b ^ game[3] for b in game[3:7]) == bytes.fromhex("00010302")


def find(*dirs):
    """The map from hello_map.json in the first of these folders that has one (None if none does)"""
    for d in dirs:
        p = os.path.join(d, "hello_map.json")
        if os.path.exists(p):
            try:
                return HelloMap.load(p)
            except (OSError, ValueError, KeyError):
                pass
    return None

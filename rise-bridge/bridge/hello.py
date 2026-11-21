"""The hello value for a MAC: what the game sends and expects in its first game message (00 01 03 02 + 8 bytes).

FOUND BY MEASUREMENT, NOT FROM THE GAME'S CODE: 60 hosts' answers for random MACs (tools/collect_hello_pairs.py) fit an
XOR-affine function of the MAC bits exactly (19 independent checks agreed, tools/solve_hello.py), and it predicts MACs
seen in earlier captures that weren't used to fit it. It is only valid for MACs whose first byte is 0x02, which is
what every sample had (the port makes its MACs 02:xx:xx:xx:xx:xx). For other first bytes the columns for the first
byte's bits are unknown: use tools/collect_hello_pairs.py --vary-first-byte and tools/solve_hello.py to extend it.
"""

# hello = _CONST xor (_COLUMNS[i] for each set bit i of the 40-bit integer made of MAC bytes 1..5, byte 1 the most significant)
_CONST = 0x172d56fb96bf482d
_COLUMNS = [
    0x0192e7f11264cddf,
    0x0325cfe224c99bbf,
    0x064b9fc44993377f,
    0x0c973f8893266efe,
    0x192e7f11264cddfd,
    0x325cfe224c99bbfb,
    0x64b9fc44993377f7,
    0x00d60aee8251d794,
    0x01ac15dd04a3af29,
    0x03582bba09475e52,
    0x06b05774128ebca4,
    0x0d60aee8251d7949,
    0x1ac15dd04a3af292,
    0x3582bba09475e525,
    0x6b05774128ebca4a,
    0x1faf1ce5e1e0acef,
    0x602b986a4528f3a2,
    0x09f2c2b33a66df3e,
    0x13e5856674cdbe7c,
    0x27cb0acce99b7cf8,
    0x4f961599d336f9f1,
    0x5689d954165acb98,
    0x64b640cf9c82af4a,
    0x00c973f8893266ef,
    0x3f5e39cbc3c159df,
    0x7ebc73978782b3bf,
    0x34dd1548bf325f04,
    0x69ba2a917e64be08,
    0x1ad1a7454cfe446b,
    0x35a34e8a99fc88d6,
    0x6b469d1533f911ad,
    0x1f28c84dd7c51b20,
    0x608384e7b9cf88a4,
    0x08a2fba8c3a82932,
    0x1145f75187505264,
    0x228beea30ea0a4c8,
    0x4517dd461d414991,
    0x438a48eb8ab5ab58,
    0x4eb163b0a55c6ecb,
    0x54c73506fa8fe5ec,
]


def hello_for_mac(mac: bytes) -> bytes:
    """The 8 hello bytes for this MAC (a 6-byte MAC starting 0x02)."""
    if len(mac) != 6:
        raise ValueError("a MAC is 6 bytes")
    if mac[0] != 0x02:
        raise ValueError("only MACs starting 02 are covered so far (first byte %02x)" % mac[0])
    x = int.from_bytes(mac[1:], "big")
    h = _CONST
    for i in range(40):
        if x >> i & 1:
            h ^= _COLUMNS[i]
    return h.to_bytes(8, "big")


# ---- the whole 15-byte message (prefix, scramble byte and scrambled body), also affine in the MAC ----
# Checked: the prefix and scramble byte are affine in the receiver's MAC just like the value (19 of 19 checks on 60 samples),
# and the complete message predicts every known MAC whose real message is in the captures (tests/test_hello.py).
_MSG_CONST = 0x965561adacaeafba80fb563b12e580
_MSG_COLUMNS = [
    0xbeb1af1c1c1c1c1d8efbed0e78d1c3,
    0xea14e5dfdfdfdfdcfa103dfb164460,
    0x089645d7d7d7d7d19c48139e44e0a8,
    0x618b41636363636ff45cebf0450d9d,
    0x94fc4a959595958cbbea84b3d94868,
    0x85e0d18f8f8f8fbdd371adc3163474,
    0x9873d7cacacacaae73368e53f9bd3d,
    0x0c84e3e2e2e2e2e234e80c60b33576,
    0x2152d5adadadadac01b870a90e0284,
    0x29d1be52525252510a79e85b150c00,
    0x1cae86191919191fa94e6d0b97a5bd,
    0x0426d0f5f5f5f5f8955b1dd0e88cbc,
    0xaf5fd21b1b1b1b01da46cb5121e989,
    0x21d7969c9c9c9ca91e273c08e979b9,
    0x8ae9856f6f6f6f046a182e4784a525,
    0x614c9e0d0d0d0d12a211e8eceda1e2,
    0xfe4d3447474747276cdf2d026fb4e5,
    0xaeadff5f5f5f5f56ad9dec65398061,
    0xd32e762a2a2a2a39cfaf4c5ee79456,
    0xb0912741414141668a4b8da8da3db9,
    0x3bd692010101014e971498d237f8f0,
    0x59c66c5252525204db8b06440899ca,
    0xa76d6e2a2a2a2a4e9c6ae5b6a88560,
    0x74adb3a7a7a7a7a76ed45f2e95c148,
    0x2d77974e4e4e4e711077858d8f1791,
    0x46cdd3404040403efc33d7c7c2f3ff,
    0x744557ececececd831f9a453deb3e8,
    0xe96fae444444442dfe6ed53a20fa4c,
    0xa285076969696973b8ce2c25972d02,
    0x3c761ffcfcfcfcc95fb2766500742a,
    0x970294adadadadc6eb30b89e54bc00,
    0xc436dd8d8d8d8d92a545c05a4896ad,
    0xd7ad5513131313739097f4aadc9bb7,
    0x64307febebebebe34910432843c2d9,
    0xb922348686868697c371d701d6d4e2,
    0xdd68c082828282a0096c218c22264a,
    0xfa1383dededede9bc90398c39f974f,
    0xc9a14a5757575714dd1fbcdde2fc0f,
    0xa935fb5d5d5d5d13ec3eedf8013396,
    0xc91ac93d3d3d3d69fa083bc7b2d8d1,
]


def hello_message_for_mac(mac: bytes) -> bytes:
    """The 15-byte game message (type 0x68 payload) a station sends to the station with this MAC as its hello."""
    if len(mac) != 6 or mac[0] != 0x02:
        raise ValueError("only 6-byte MACs starting 02 are covered so far")
    x = int.from_bytes(mac[1:], "big")
    y = _MSG_CONST
    for i in range(40):
        if x >> i & 1:
            y ^= _MSG_COLUMNS[i]
    return y.to_bytes(15, "big")

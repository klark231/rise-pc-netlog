"""bridge/hello.py against pairs it was NOT fitted on: MACs and hellos from the earlier Switch captures and experiments."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bridge.hello import hello_for_mac

KNOWN = """
0229ebe2fa73 5c937a792b5bd5b1
021198 7e33bd 13d29fafda4e2bc2
020503454627 683c70a841816841
0219e832d4d6 385c665901f40519
02c99f568d1a 64571dd82241622f
029234b70540 15bf67f3102afcc7
02d8883383a4 45090eeaa251930a
02809a6f91ec 66f0e537441ac6ba
02b50112c5ff 794bbdccad435674
0230ab031fa8 57422eea27b88573
02ee54da5e45 2f0b17f3420e00ac
021cb4a0e070 3dd0a15a8e0b408f
0216ba6dcc6a 2c9611affa5c6f31
021b44a4f116 44ab0af8c0a6f646
02342d0f12d2 6d6599dfa5f26c7c
020f1253308e 4c3a682b3ccc90f9
0294e10544dc 00cd7f3da43b729f
0227a00a8d05 3b7b5027f5de1c3c
021122334455 1e9b7f0648808ac0
021222334455 76ba004932e72b56
021123334455 21c546cd8b41d31f
021122344455 64a7a0b943031820
021122334555 1f376adb4c2325e9
021122334456 1c2c57157e2ddca0
02c4c1484ec1 122365b003e12dc7
"""


def test_known_pairs():
    n = 0
    for line in KNOWN.strip().splitlines():
        mac, h = line.replace(" ", "").split("\n")[0][:12], line.split()[-1]
        assert hello_for_mac(bytes.fromhex(mac)).hex() == h, (mac, hello_for_mac(bytes.fromhex(mac)).hex(), h)
        n += 1
    print(n, "pairs predicted exactly")


MESSAGES = [('021122334455', 'df4f3a757476776bee0a733df5ffb5'), ('021222334455', '6cd2108d8c8e8ffb378dc4bf6aa6db'), ('021123334455', 'f238ad3b3a38391afe7df6b07ae824'), ('021122344455', '5c81874746444523e0e7fe04445f67'), ('021122334555', 'fe1defd8d9dbdac7efb20394fbfd31'), ('021122334456', '8bea70b6b7b5b4aa9ae1a3c89b6a16'), ('021cb4a0e070', '48fa9a58595b5a6588f902d65318d7'), ('0216ba6dcc6a', '424b99212022230db7308edb7d4e10'), ('021b44a4f116', '2db0024243414006e948ba82e4b404'), ('0227a00a8d05', '5d86d86c6d6f6e57173c4b99b27050'), ('02c4c1484ec1', 'b71106abaaa8a9b988ce1ba84a866c')]


def test_whole_messages():
    from bridge.hello import hello_message_for_mac
    for mac, raw in MESSAGES:
        assert hello_message_for_mac(bytes.fromhex(mac)).hex() == raw, mac
    print(len(MESSAGES), "whole 15-byte messages predicted exactly")


if __name__ == "__main__":
    test_whole_messages()
    test_known_pairs()

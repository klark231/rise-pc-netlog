"""The member messages (0203 / 0302) a Switch joiner sends, rebuilt from identities (bridge/memberid.py). The expected
messages are real ones from the 2026-11-21 Switch capture (joiner .4 to host .1, .2, .3; and the host's own to .4)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bridge import memberid

ID = {k: bytes.fromhex(v) for k, v in {"1": "229d0667", "2": "bdcfa2a5", "3": "f54ca3e7", "4": "c3749879"}.items()}
REAL = {
    "4>1 member": "be84754042438334d83918a73c5d5d5c5c5d5d5c5d",
    "4>1 reply": "afdde4747776b601ed0c2d9209686869",
    "4>2 member": "41e1506f6d6cac1bf716a8dab7b0b0b0b0b1b1b0b1",
    "4>3 member": "4287d6d2d0d111a64aab5de40b4f4f4f4f4e4e4f4e",
    "1>4 member": "66ce9ee1e3e2c37ce78646f11dfcfcfcfcfdfdfcfd",
}


def test_memberid():
    assert memberid.member_msg(ID["4"], ID["1"]).hex() == REAL["4>1 member"]
    assert memberid.reply_msg(ID["4"], ID["1"]).hex() == REAL["4>1 reply"]
    assert memberid.member_msg(ID["4"], ID["2"], (1, 1, 1, 1, 0, 0, 1, 0)).hex() == REAL["4>2 member"]
    assert memberid.member_msg(ID["4"], ID["3"], (1, 1, 1, 1, 0, 0, 1, 0)).hex() == REAL["4>3 member"]
    assert memberid.learn(bytes.fromhex(REAL["1>4 member"])) == (ID["1"], ID["4"])
    assert memberid.learn(bytes.fromhex(REAL["4>1 reply"])) is None
    print("ok test_memberid")


if __name__ == "__main__":
    test_memberid()

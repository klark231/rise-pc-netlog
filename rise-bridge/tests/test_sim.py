"""tools/sim_joiner.py's logic against a fake host that repeats 9 and 21-byte messages until it sees a member reply."""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
sys.path.insert(0, os.path.join(here, "..", "tools"))
import sim_joiner as sj
from bridge import gamemsg, hellomap, memberid


def run(member):
    hm = hellomap.HelloMap.load(os.path.join(here, "..", "hello_map.json"))
    now, sent, logs = [0.0], [], []
    sim = sj.SimJoiner(sent.append, bytes.fromhex("021888 46f6b0".replace(" ", "")), hm, member=member, log=logs.append, clock=lambda: now[0])
    host, me = bytes.fromhex("85ee75dc"), bytes.fromhex("0a1b2c3d")
    h21, nine = memberid.member_msg(host, me), gamemsg.seal(bytes.fromhex("0103000101"))
    sim.handle(hm.message_for(bytes.fromhex("0a1b2c3d4e5f")))
    for i in range(30):
        now[0] = i * 0.5
        if not (sent and any(sj.kind(m) == "16/0302" for m in sent) and i > 12):   # a host that takes our answer stops repeating
            sim.handle(h21); sim.handle(nine)
    return sim, sent


def test_sim():
    sim, sent = run(True)
    kinds = [sj.kind(m) for m in sent]
    assert kinds[0] == "15/0103" and "21/0203" in kinds and "16/0302" in kinds, kinds
    assert "NOT LOOPING" in sim.verdict(), sim.verdict()
    sim, sent = run(False)
    assert not any(sj.kind(m) in ("21/0203", "16/0302") for m in sent)
    print("ok test_sim")


if __name__ == "__main__":
    test_sim()

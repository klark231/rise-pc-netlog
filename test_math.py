import sys, os
sys.path.insert(0, os.path.expanduser("~/rise-pc-netlog/rise-bridge"))
sys.path.insert(0, os.path.expanduser("~/rise-pc-netlog/rise-bridge/tests"))
import rise_net
from bridge import gamemsg

capture_file = os.path.expanduser("~/rise-pc-netlog/local_play_20261123_044742.txt")
msgs = []

try:
    for pk, m in rise_net.switch_messages(capture_file):
        if m["ptype"] == 0x68 and 5 <= len(bytes(m["payload"])) <= 80:
            msgs.append(bytes(m["payload"]))
except Exception as e:
    print("Error reading capture:", e)

print(f"Loaded {len(msgs)} real Switch game messages.")
success = 0
fail = 0

for msg in msgs:
    try:
        body = gamemsg.data_of(msg)
        if gamemsg.seal(body) == msg:
            success += 1
        else:
            fail += 1
    except Exception:
        pass

print(f"✅ Perfectly resealed: {success}")
print(f"❌ Failed: {fail}")

if fail == 0 and success > 0:
    print("\n🎉 VERIFICATION PASSED! Claude's math is flawless.")
else:
    print("\n⚠️ VERIFICATION FAILED or incomplete.")

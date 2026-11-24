import os, socket, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rise_bridge_app as app

with tempfile.TemporaryDirectory() as t:
    lib = os.path.join(t, "lib"); g = os.path.join(lib, "steamapps", "common", "MonsterHunterRise")
    os.makedirs(g); open(os.path.join(g, app.GAME_EXE), "w").close()
    assert app.find_game_dir([os.path.join(t, "nope"), lib]) == g
    assert not app.bridge_on(g)
    dll = os.path.join(t, "dinput8.dll"); open(dll, "wb").write(b"ours")
    plugin = os.path.join(t, app.PLUGIN); open(plugin, "wb").write(b"plugin")
    quest = os.path.join(t, app.QUEST_LUA); open(quest, "wb").write(b"-- quest")
    # no REFramework: our dinput8.dll next to the game
    app.install(g, dll, plugin, quest)
    assert app.bridge_on(g) and open(os.path.join(g, "dinput8.dll"), "rb").read() == b"ours"
    assert not os.path.exists(app.plugin_path(g))
    app.remove(g, with_dll=True); assert not os.path.exists(os.path.join(g, "dinput8.dll"))
    # an older install that set REFramework's dinput8.dll aside: it goes back and ours becomes a plugin
    open(os.path.join(g, "dinput8.dll"), "wb").write(b"ours")
    open(os.path.join(g, "dinput8.dll.bak"), "wb").write(b"reframework")
    app.install(g, dll, plugin, quest)
    assert open(os.path.join(g, "dinput8.dll"), "rb").read() == b"reframework"
    assert not os.path.exists(os.path.join(g, "dinput8.dll.bak"))
    assert open(app.plugin_path(g), "rb").read() == b"plugin" and open(app.quest_path(g), "rb").read() == b"-- quest"
    app.install(g, dll, plugin, quest)  # again: REFramework untouched, plugin up to date
    assert open(os.path.join(g, "dinput8.dll"), "rb").read() == b"reframework" and app.bridge_on(g)
    assert not app.calibrate_on(g); app.set_calibrate(g, True); assert app.calibrate_on(g)
    app.set_calibrate(g, False); assert not app.calibrate_on(g)
    app.set_calibrate(g, True); app.remove(g); assert not app.calibrate_on(g)
    app.remove(g); assert not app.bridge_on(g) and os.path.exists(app.plugin_path(g))
    app.remove(g, with_dll=True)
    assert not os.path.exists(app.plugin_path(g)) and open(os.path.join(g, "dinput8.dll"), "rb").read() == b"reframework"
    assert not os.path.exists(app.quest_path(g))
    cfgp = os.path.join(t, "c.json"); app.save_config({"server": "x:1", "key": "k", "name": "n", "game_dir": g, "junk": "z"}, cfgp)
    assert app.load_config(cfgp)["server"] == "x:1" and "junk" not in app.load_config(cfgp)
    assert app.parse_server("a.b") == ("a.b", 39510) and app.parse_server("a:5") == ("a", 5)

if app.crypto_ok():
    logs = []
    h = app.Helper("127.0.0.1:9", "k", "n", logs.append, port=39655); h.start()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
    s.sendto(b"LIST", ("127.0.0.1", 39655)); print(s.recvfrom(4096)[0][:60])
    h.stop(); assert not h.thread.is_alive()
print("ok test_app")


def test_gamemsg():
    from bridge import gamemsg as g
    host = bytes.fromhex("076ac6a6a7a5a7862f0a2b5c")        # the Switch host's 12-byte message: 00 01 03 01 20 89ac8dfa
    assert g.parse(host)[1].hex() == "000103012089ac8dfa"
    pc = g.to_pc(host)
    # payload 01 02 02 21 <id> -> 01 02 02 00 <id> (bridge/wire.py): the same identity
    assert g.parse(pc)[1].hex() == "0001030101a88dacdb"
    assert g.identity(pc) == g.identity(host) == bytes.fromhex("a9252177")
    assert g.to_switch(pc) == host and g.to_switch(host) == host      # and back
    assert g.to_pc(pc) == pc and g.to_pc(b"\x00" * 15) == b"\x00" * 15
    print("ok test_gamemsg")


if __name__ == "__main__":
    test_gamemsg()

import os, socket, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rise_bridge_app as app

with tempfile.TemporaryDirectory() as t:
    lib = os.path.join(t, "lib"); g = os.path.join(lib, "steamapps", "common", "MonsterHunterRise")
    os.makedirs(g); open(os.path.join(g, app.GAME_EXE), "w").close()
    assert app.find_game_dir([os.path.join(t, "nope"), lib]) == g
    assert not app.bridge_on(g)
    dll = os.path.join(t, "dinput8.dll"); open(dll, "wb").write(b"ours")
    open(os.path.join(g, "dinput8.dll"), "wb").write(b"reframework")
    app.install(g, dll)
    assert app.bridge_on(g) and open(os.path.join(g, "dinput8.dll"), "rb").read() == b"ours"
    assert open(os.path.join(g, "dinput8.dll.bak"), "rb").read() == b"reframework"
    app.install(g, dll)  # again: .bak untouched
    assert open(os.path.join(g, "dinput8.dll.bak"), "rb").read() == b"reframework"
    app.remove(g); assert not app.bridge_on(g)
    app.remove(g, with_dll=True); assert open(os.path.join(g, "dinput8.dll"), "rb").read() == b"reframework"
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

#!/usr/bin/env python3
"""Rise Bridge: one small window for the PC side of bridge mode.

  - finds the game folder (Steam), copies dinput8.dll in, and switches bridge mode on/off (rise_bridge.txt)
  - runs the helper (the bridge daemon) while you play, with its log in the window

Double-click RiseBridge.exe (or Start-Bridge.cmd). `--console` runs without a window (prompts in the terminal).
"""
import json, os, queue, re, shutil, socket, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE
GAME_EXE, FLAG, DLL = "MonsterHunterRise.exe", "rise_bridge.txt", "dinput8.dll"
CAL_FLAG, HELLO = "rise_bridge_calibrate.txt", "rise_hello.txt"
DEFAULTS = {"server": "meoli.viewdns.net", "key": "", "name": "PCBridge", "game_dir": ""}
CONFIG = os.path.join(APP_DIR, "RiseBridge.json")


# ---------- plain logic (no window; tested in tests/test_app.py) ----------

def load_config(path=CONFIG):
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS and isinstance(v, str)})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg, path=CONFIG):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
    except OSError:
        pass


def steam_libraries():
    """Steam library folders: the Steam install itself plus whatever libraryfolders.vdf lists."""
    roots = []
    if os.name == "nt":
        try:
            import winreg
            for hive, sub in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        val = winreg.QueryValueEx(k, "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath")[0]
                        roots.append(os.path.normpath(val))
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(os.path.join(os.environ[env], "Steam"))
    libs = list(roots)
    for r in roots:
        try:
            with open(os.path.join(r, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                libs += [os.path.normpath(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError:
            pass
    seen, out = set(), []
    for p in libs:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def find_game_dir(libraries=None):
    for lib in (steam_libraries() if libraries is None else libraries):
        d = os.path.join(lib, "steamapps", "common", "MonsterHunterRise")
        if os.path.isfile(os.path.join(d, GAME_EXE)):
            return d
    return ""


def find_dll():
    for d in (APP_DIR, HERE, getattr(sys, "_MEIPASS", HERE), os.path.join(HERE, "..", "build", "Release")):
        p = os.path.join(d, DLL)
        if os.path.isfile(p):
            return p
    return ""


def check_game_dir(game_dir):
    return bool(game_dir) and os.path.isfile(os.path.join(game_dir, GAME_EXE))


def bridge_on(game_dir):
    return check_game_dir(game_dir) and os.path.isfile(os.path.join(game_dir, FLAG))


def calibrate_on(game_dir):
    return check_game_dir(game_dir) and os.path.isfile(os.path.join(game_dir, CAL_FLAG))


def hello_saved(game_dir):
    return check_game_dir(game_dir) and os.path.isfile(os.path.join(game_dir, HELLO))


def set_calibrate(game_dir, on):
    """Calibration run: the game learns the hello it expects (writes rise_hello.txt). Switch it off afterwards."""
    flag = os.path.join(game_dir, CAL_FLAG)
    if on:
        open(flag, "w").close()
        return "calibration ON: join a hub once, then switch it off (rise_hello.txt gets written)"
    if os.path.isfile(flag):
        os.remove(flag)
    return "calibration OFF"


def install(game_dir, dll_src=None):
    """Copy dinput8.dll into the game folder and switch bridge mode on. Returns a list of log lines."""
    if not check_game_dir(game_dir):
        raise ValueError("%s not found in %r" % (GAME_EXE, game_dir))
    msgs = []
    dst = os.path.join(game_dir, DLL)
    src = dll_src if dll_src is not None else find_dll()
    if src and os.path.isfile(dst) and _same(src, dst):
        msgs.append("%s in the game folder is already up to date" % DLL)
    elif src:
        try:
            if os.path.isfile(dst) and os.path.getsize(dst) and not os.path.exists(dst + ".bak"):
                shutil.copy2(dst, dst + ".bak")
                msgs.append("kept your existing dinput8.dll as dinput8.dll.bak (REFramework? it won't load next to this one)")
            shutil.copy2(src, dst)
        except PermissionError:
            raise ValueError("can't write %s: the game (or Steam) is still using it. Close MonsterHunterRise.exe "
                             "completely (check Task Manager) and try again." % dst)
        msgs.append("copied %s into the game folder" % DLL)
    elif os.path.isfile(dst):
        msgs.append("no %s next to the app; using the one already in the game folder" % DLL)
    else:
        raise ValueError("%s is missing: put it next to this app (it comes in the same zip)" % DLL)
    open(os.path.join(game_dir, FLAG), "w").close()
    msgs.append("bridge mode ON (%s created)" % FLAG)
    return msgs


def _same(a, b):
    try:
        return os.path.getsize(a) == os.path.getsize(b) and open(a, "rb").read() == open(b, "rb").read()
    except OSError:
        return False


def remove(game_dir, with_dll=False):
    """Back to normal Steam play: delete rise_bridge.txt (and, optionally, dinput8.dll, restoring a .bak)."""
    msgs = []
    flag = os.path.join(game_dir, FLAG)
    if os.path.isfile(flag):
        os.remove(flag)
        msgs.append("bridge mode OFF (%s removed)" % FLAG)
    if os.path.isfile(os.path.join(game_dir, CAL_FLAG)):
        os.remove(os.path.join(game_dir, CAL_FLAG))
    if with_dll:
        dll = os.path.join(game_dir, DLL)
        if os.path.isfile(dll):
            os.remove(dll)
            msgs.append("removed %s" % DLL)
        if os.path.isfile(dll + ".bak"):
            os.replace(dll + ".bak", dll)
            msgs.append("restored your original dinput8.dll")
    return msgs or ["nothing to remove"]


def parse_server(text):
    host, _, port = text.strip().partition(":")
    if not host:
        raise ValueError("server is empty")
    return host, int(port or 39510)


class Helper:
    """The bridge daemon on a background thread, stoppable."""

    def __init__(self, server, key, name, log, port=39600):
        import bridge_daemon
        from bridge import hublink
        self.log = log
        self.d = bridge_daemon.Daemon(parse_server(server), hublink.room_of_key(key), name or "PCBridge", port, log=log)
        self.d.sock.settimeout(0.5)
        self.stop_flag = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        d = self.d
        self.log("helper running on 127.0.0.1:%d, server %s:%d" % ((d.sock.getsockname()[1],) + tuple(d.server)))
        while not self.stop_flag.is_set():
            try:
                data, addr = d.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            d.dll = addr
            try:
                d.handle(data.decode())
            except Exception as e:
                self.log("bad datagram %r: %s" % (data[:40], e))
        self.log("helper stopped")

    def stop(self):
        self.stop_flag.set()
        try:
            if self.d.link:
                self.d.link.leave()
        except Exception:
            pass
        self.thread.join(2)
        self.d.sock.close()


def crypto_ok():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


# ---------- window ----------

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    cfg = load_config()
    q = queue.Queue()
    log_path = os.path.join(APP_DIR, "rise_bridge_log.txt")     # the same lines, to send back after a run (overwritten at each start)
    try:
        open(log_path, "w").close()
    except OSError:
        log_path = None

    def log(s):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), s)
        q.put(line)
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
    root = tk.Tk()
    root.title("Rise Bridge")
    root.geometry("640x520")
    root.minsize(520, 420)
    vars_ = {k: tk.StringVar(value=cfg[k]) for k in DEFAULTS}
    if not check_game_dir(vars_["game_dir"].get()):
        vars_["game_dir"].set(find_game_dir())
    helper = [None]

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)
    rows = (("Server", "server"), ("Matchmaking key", "key"), ("Your name", "name"), ("Game folder", "game_dir"))
    for i, (label, k) in enumerate(rows):
        ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=vars_[k]).grid(row=i, column=1, sticky="ew", padx=6)

    def browse():
        d = filedialog.askdirectory(title="Folder with MonsterHunterRise.exe")
        if d:
            vars_["game_dir"].set(os.path.normpath(d))
            refresh()

    def autodetect():
        d = find_game_dir()
        if d:
            vars_["game_dir"].set(d)
            log("found the game: %s" % d)
        else:
            log("couldn't find the game in Steam's libraries; use Browse")
        refresh()

    bf = ttk.Frame(frm)
    bf.grid(row=3, column=2)
    ttk.Button(bf, text="Browse", command=browse).pack(side="left")
    ttk.Button(bf, text="Find", command=autodetect).pack(side="left", padx=(4, 0))

    status = tk.StringVar()
    cal_var = tk.BooleanVar(value=False)

    def do_cal():
        g = vars_["game_dir"].get().strip()
        if not check_game_dir(g):
            cal_var.set(False)
            return
        log(set_calibrate(g, cal_var.get()))
        refresh()

    ttk.Label(frm, textvariable=status, wraplength=600, justify="left").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 4))

    def settings():
        s = {k: v.get().strip() for k, v in vars_.items()}
        save_config(s)
        return s

    def refresh():
        g = vars_["game_dir"].get().strip()
        a = "game folder OK" if check_game_dir(g) else "game folder not set (needs MonsterHunterRise.exe)"
        b = "bridge mode ON" if bridge_on(g) else "bridge mode OFF"
        c = "helper RUNNING" if helper[0] else "helper stopped"
        d = "hello learned" if hello_saved(g) else "hello NOT learned yet (tick Calibrate for one run)"
        cal_var.set(calibrate_on(g))
        status.set("%s  |  %s  |  %s  |  %s" % (a, b, c, d))
        start_btn.config(text="Stop helper" if helper[0] else "2. Start helper")

    def do_install():
        s = settings()
        try:
            for m in install(s["game_dir"]):
                log(m)
        except Exception as e:
            messagebox.showerror("Rise Bridge", str(e))
        refresh()

    def do_remove():
        s = settings()
        if not check_game_dir(s["game_dir"]):
            return
        for m in remove(s["game_dir"], with_dll=messagebox.askyesno("Rise Bridge", "Also remove dinput8.dll from the game folder?")):
            log(m)
        refresh()

    def toggle():
        if helper[0]:
            helper[0].stop()
            helper[0] = None
        else:
            s = settings()
            if not crypto_ok():
                messagebox.showerror("Rise Bridge", "The 'cryptography' Python package is missing.\nRun:  pip install cryptography")
                return
            try:
                h = Helper(s["server"], s["key"], s["name"], log)
                h.start()
                helper[0] = h
            except Exception as e:
                messagebox.showerror("Rise Bridge", "Couldn't start the helper:\n%s\n(is another copy already running?)" % e)
        refresh()

    ttk.Button(frm, text="1. Install into game / bridge ON", command=do_install).grid(row=5, column=0, columnspan=2, sticky="ew", pady=2)
    start_btn = ttk.Button(frm, text="2. Start helper", command=toggle)
    start_btn.grid(row=6, column=0, columnspan=2, sticky="ew", pady=2)
    ttk.Button(frm, text="Back to normal Steam", command=do_remove).grid(row=5, column=2, rowspan=2, sticky="ns", padx=(6, 0))
    ttk.Checkbutton(frm, text="Calibrate (one run: learn the hello your game expects, then untick)", variable=cal_var,
                    command=do_cal).grid(row=7, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text="Then start the game from Steam and open the online lobby search. Keep this window open while playing.",
              wraplength=600).grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 4))

    box = scrolledtext.ScrolledText(frm, height=12, state="disabled", font=("Consolas", 9))
    box.grid(row=9, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(9, weight=1)

    def pump():
        try:
            while True:
                box.config(state="normal")
                box.insert("end", q.get_nowait() + "\n")
                box.see("end")
                box.config(state="disabled")
        except queue.Empty:
            pass
        root.after(200, pump)

    def close():
        settings()
        if helper[0]:
            helper[0].stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    if not crypto_ok():
        log("WARNING: 'cryptography' is not installed (pip install cryptography); the helper can't start without it")
    if not find_dll():
        log("note: dinput8.dll isn't next to this app, so Install can't copy it (it's in the release zip)")
    refresh()
    pump()
    root.mainloop()


def run_console():
    cfg = load_config()
    for k, label in (("server", "Server"), ("key", "Matchmaking key"), ("name", "Your name")):
        v = input("%s [%s]: " % (label, cfg[k])).strip()
        cfg[k] = v or cfg[k]
    g = cfg["game_dir"] if check_game_dir(cfg["game_dir"]) else find_game_dir()
    while not check_game_dir(g):
        g = input("Game folder (with %s): " % GAME_EXE).strip().strip('"')
    cfg["game_dir"] = g
    save_config(cfg)
    for m in install(g):
        print(m)
    h = Helper(cfg["server"], cfg["key"], cfg["name"], print)
    h.start()
    print("Start the game from Steam now. Ctrl+C here to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        h.stop()
        for m in remove(g):
            print(m)


def main():
    if "--console" in sys.argv:
        return run_console()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("tkinter isn't available; falling back to the console.")
        return run_console()
    run_gui()


if __name__ == "__main__":
    main()

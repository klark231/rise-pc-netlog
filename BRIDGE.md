# Bridge mode (PC game into a Switch-port session)

Needs: the port as host (netlog3.patch, Capture Local Play on at start-up) and the game on **real Steam**.

## Easy way: RiseBridge.exe (from the release zip / CI artifact)

1. Unzip anywhere; keep `RiseBridge.exe` and `dinput8.dll` together.
2. Run `RiseBridge.exe`. Fill in the server (default `meoli.viewdns.net`), your matchmaking key and a name.
   The game folder is found automatically from Steam (use Browse if not).
3. Click **1. Install into game / bridge ON** (copies dinput8.dll, creates `rise_bridge.txt`), then **2. Start helper**.
4. Start the game from Steam, open the online lobby search. Your hub should appear as a lobby. Leave the window open.
5. Send `rise_netlog.txt` (game folder) and the window's log.
   **Back to normal Steam** removes `rise_bridge.txt` (and optionally the DLL; your own dinput8.dll is restored from `.bak`).

Settings are remembered in `RiseBridge.json` next to the exe.

## One-time calibration (needed once per Steam account)

The game checks the first message ("hello") it gets from a peer, and that message depends on who it is addressed to, so the
Switch host's hello is wrong for your Steam ID. The DLL swaps it for the right one, which it learns like this:
1. Tick **Calibrate** in the window (or create an empty `rise_bridge_calibrate.txt` next to the exe), start the helper and the game,
   search and join a hub once. The log says `CALIBRATION: the game's hello ... saved to rise_hello.txt`.
2. Untick Calibrate (or delete the file), restart the game. From then on the host's hello is replaced with the saved one.

## No exe: Start-Bridge.cmd

Double-click `Start-Bridge.cmd` in the repo folder. It needs Python 3 for Windows, installs `cryptography` itself and opens the
same window (`Start-Bridge.cmd --console` for the terminal version). Copy `dinput8.dll` next to it first.
`Build-Exe.cmd` builds `dist\RiseBridge.exe` yourself.

## Fixes after the 2026-11-23 test (stuck after joining)

Both games kept resending the same messages and nothing moved past the member exchange. Two causes, both in the
helper:
- **The Switch compresses its larger member messages** (Pia message flag `0x20`, zlib, starting `48 4b`). The host's
  info message reached the PC still compressed, so the PC never got the host info it waits for. The helper now
  inflates them for the PC, and compresses the PC's larger `0203` / `0302` messages the Switch's way.
- **The platform message also carries the sender's identity**, as `id ^ (platform ^ 03)`. Flipping only the platform
  byte (01 <-> 20) changed the identity each side learned by 0x21 per byte, so the host rejected everything the PC sent
  afterwards (which is why the helper made up its own member replies and dropped the PC's). The flip now keeps the
  identity, and the PC's own member messages go through unchanged; the made-up replies are gone.

The helper's log now says `same identity <8 hex digits>` when it converts a platform message.

## 2026-11-23, second round: the lobby

The member exchange worked, but PC online and Switch Local Play run different lobbies (`analysis/LOBBY.md`), so each
side waited for something the other never sends. The helper now plays the PC host's lobby toward the PC game and a
Switch joiner's toward the port host. The PC game's check of the Switch host's Steam ticket passes in the DLL.
In the helper's log: `[lobby] the host sent its room`, `[lobby] the PC asked to join: answered as its host`, then
`[lobby] the PC sent its ticket`. In `rise_netlog.txt`: `BeginAuthSession for the Switch host's ID: answered OK`.

## What the log lines mean

Lines starting `bridge:` in `rise_netlog.txt` show each step:
   - `hooked Steam_BGetCallback` and `ISteamUtils call results wrapped`: the callbacks can be delivered
   - `RequestLobbyList: asking the daemon` -> `daemon: 1 hub(s)` -> `handing the game callback 703`
   - after JoinLobby: `daemon: joined the Switch session`, then `SendMessageToUser(bridge)` with `SteamConReq`

In bridge mode the lobby list shows only Switch hubs (Steam's own lobbies are replaced).

## Manual way (old)

`pip install cryptography`, then `python rise-bridge\tools\bridge_daemon.py SERVER --key KEY --name NAME`, and create an
empty `rise_bridge.txt` next to MonsterHunterRise.exe.

## One-time: the host's hello map

The Switch host only answers a game whose hello is made for the host's MAC. `hello_map.json` lets the helper make it
for any host. Make it once, on a phone with Termux (or any machine with Python 3 and `cryptography`), while your host
is in the lobby (patched port, Capture Local Play on at start-up):

    python tools/hello_probe.py meoli.viewdns.net --key YOURKEY

It joins your own host about 60 times (about 5 minutes) and saves `hello_map.json`. Put that file next to
`RiseBridge.exe` (or in the `rise-bridge` folder). The helper's log then says `hello map: loaded`.

## 2026-11-24: REFramework plugin

The DLL now also comes as a REFramework plugin, `rise_crossplay.dll` (same code, built with `RISE_PLUGIN`). RiseBridge's
**Install** picks it when the game has REFramework (a `reframework` folder, or a `dinput8.dll.bak` from an older
install): it puts REFramework's `dinput8.dll` back from the `.bak` and copies the plugin to `reframework/plugins`.
Without REFramework it installs `dinput8.dll` as before. **Back to normal Steam** with the DLL removes whichever is
there.

How it loads: REFramework loads every DLL in `reframework/plugins` while it starts, and the plugin's `DllMain` puts the
same hooks in as `dinput8.dll` does. The game creates its Steam interfaces seconds later (`rise_netlog_22`: the Steam
library at 05:27:48, `SteamClient` at 05:28:03), so nothing is missed. `reframework_plugin_initialize` checks once
more for a Steam library that showed up in between. The log says `loaded as a REFramework plugin`.

Where this is going: the helper (`RiseBridge.exe`) moves into the plugin too, so the PC side is one file in
`reframework/plugins` and nothing to start by hand. That waits until crossplay works end to end, because the helper's
Python is much quicker to change between tests. The order: the bridge rules settle in Python, then they're written again
in C++ in the plugin (Pia and its AES-GCM, the hub link, the station, the lobby), with the Python tests turned into test
vectors for the C++.

## 2026-11-24: the Switch doesn't show the PC hunter

Joining works both ways now, and the PC shows the Switch player's hunter walking around, but the Switch side never
shows the PC's. See `analysis/NOTES.md`, section 9. `probe/` has the script that finds out where the Switch game stops.

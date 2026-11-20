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

## No exe: Start-Bridge.cmd

Double-click `Start-Bridge.cmd` in the repo folder. It needs Python 3 for Windows, installs `cryptography` itself and opens the
same window (`Start-Bridge.cmd --console` for the terminal version). Copy `dinput8.dll` next to it first.
`Build-Exe.cmd` builds `dist\RiseBridge.exe` yourself.

## What the log lines mean

Lines starting `bridge:` in `rise_netlog.txt` show each step:
   - `hooked Steam_BGetCallback` and `ISteamUtils call results wrapped`: the callbacks can be delivered
   - `RequestLobbyList: asking the daemon` -> `daemon: 1 hub(s)` -> `handing the game callback 703`
   - after JoinLobby: `daemon: joined the Switch session`, then `SendMessageToUser(bridge)` with `SteamConReq`

In bridge mode the lobby list shows only Switch hubs (Steam's own lobbies are replaced).

## Manual way (old)

`pip install cryptography`, then `python rise-bridge\tools\bridge_daemon.py SERVER --key KEY --name NAME`, and create an
empty `rise_bridge.txt` next to MonsterHunterRise.exe.

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

## 2026-11-25: quests

With the PC's player slot fixed (the bridge's join answer gave it slot 3 while the Switch had it as player 1), both
sides see each other's hunters. Quests didn't work either way, because the two versions do them differently:

- PC online: posting a quest opens a quest session of its own, a Steam lobby (`CreateLobby type 3`). A joiner asks the
  poster to enter the room, and the answer carries that lobby's ID (`snow.LobbyManager.QuestIdentifier._sessionID`, a
  string), which it joins. Nothing else gives the ID away: no invite, no lobby data, and the messages it travels in are
  the game's packed ones (not plain or bit-aligned anywhere in the captures).
- Switch Local Play: the quest stays in the room's session.

The game has both ways in it, but answering its `IsInternet` / `isLocalnet` for it did nothing: neither is asked
when a quest is posted or joined. The `[xquest]` lines of that test showed the rest:

- The Switch takes the PC's quest the Local Play way, session ID and all: `requestEnterRoom`, `requestPrepareQuest`,
  the PC's member list, `funcOnGoQuest`. Only the session is missing: the PC's quest ran in its own Steam lobby.
- A Switch quest's session ID is empty (Local Play has none), so the PC has no lobby to join.

So the plugin now keeps a quest the PC posts in a Switch room inside the Switch session: `CreateLobby` type 3 makes no
Steam lobby but a made-up one standing for the same session (`bridge.cpp` `create_quest_lobby`), and leaving it
doesn't leave the room. The PC's lobby member data is kept per lobby, so its Index in the quest doesn't change its
Index in the room. `rise_crossplay_quest.lua` (installed by RiseBridge into `reframework/autorun`; also a mod for the
port) logs the quest calls on both sides, with the session IDs. The PC joining a Switch quest is next.

Second quest test (03:32): the PC's quest stayed in the Switch session, and the phone joined it mid-quest
(`requestEnterRoomInMiddle` … `funcOnGoQuest`), then retired at once (`sendLocalQuestRetire`). As the quest lobby's
maker the PC had set its Index to 0, the Switch host's slot. Handing it back its room slot for the quest lobby
instead (03:44) didn't do: the PC waits until its Index reads back as it set it, and stayed on "creating the quest
session". That's undone; the quest script now logs each side's own index, the quest host's and the member list. And for the PC joining a Switch quest: its empty
session ID is swapped (by the quest script, on PC) for the ID the PC made for the plugin's quest lobby, so the PC joins
that lobby; the helper answers that join again from record 1, with no ticket, as a PC host does for a quest.

Third quest test (04:03): the phone's quest member list had only slot 0 joined, its own slot, all the way through its
loading screen, and the PC's game-side index stayed 1 (`LobbyManager._myselfIndex`). The PC's quest lobby Index (0)
is what put it in slot 0. Now the plugin reads that Index back to the PC as it set it once (what it waits for), then
as its room slot, with a LobbyDataUpdate so the game reads it again.

## 2026-11-26: quest slots (what the logs of build 6 showed)

PC posts, phone joins: the PC's own index stayed `my quest index 0, quest host 0` for the whole quest although its quest
lobby Index was handed back as its room slot, 1 (the game keeps the first read). The phone, slot 0 in its room, read the
PC's quest as `quest host 0` and `join [true false false false]`: the PC's slot 0 landed on its own, so it never saw
the PC and sat in Now Loading. `rise_crossplay_quest.lua` now also lists the game's index/host fields
(`[xquest] fields`, 1 s after a quest is created or entered, then 5 s and 10 s later) to find which field the game keeps
its quest slot in. With `reframework/data/rise_quest_slot.txt` on the PC it also tries setting them to the room slot
(`[xquest] slot fix`); off otherwise. PC joining a Switch quest: the PC repeated its lobby join for 18 s and gave up
(`requestExitRoom`); not looked at yet.

2026-11-26 04:35 (slot fix on): the game keeps the quest slot in `LobbyManager._myselfQuestIndex` (0 on the PC when it
makes a quest, 0 on the phone); setting it to the room slot (1) held, but `getMyQuestIndex()` kept answering 0, so it is
computed elsewhere. The PC's own member list was already right (PC slot 1, phone slot 0); the phone's wasn't: it takes
itself for the quest host (`_quickMatchHost` true on the phone, false on the PC) and marks only its own slot joined.
The quest script now dumps all LobbyManager fields (arrays with their contents), logs the return types of
`getMyQuestIndex`/`getQuestHostIndex`, and with `rise_quest_slot.txt` also hooks `getMyQuestIndex` on the PC to answer
its room slot while a quest member list exists.

CORRECTION 2026-11-26 (late): setting `_myselfQuestIndex` to 1 on the PC (and the `getMyQuestIndex` hook that followed)
made **Depart impossible** on the PC: no `requestPrepareQuest`/`goQuest` in the logs of 04:23 and 04:35, while the 03:43
run (no slot fix) could depart. The game counts the PC as quest host 0, so the PC must keep quest index 0. Both
experiments are removed; `rise_quest_slot.txt` does nothing any more (delete it if an old build is still installed).
The phone side (it takes itself for the quest host and marks only its own slot) is the open problem.

2026-11-26 15:13-15:15 (PC posts, phone joins, both depart; no slot experiments): the PC could depart again and started the
quest alone. After goQuest its `_questMemberInfo` was [nil obj nil nil] (only itself), `currentQuestPlayerCount` 1,
`_questMemberList._join` [true false false false]; it sent its start notice (tryNotifyStartQuestToGuest) to nobody and
the phone, which had got the PC's member list and member info, waited in Now Loading for a start that never came. The
phone's own member info (45 and 59-byte messages at goQuest) did reach the PC's Steam layer, but the game never called
receiveQuestMemberInfo for it. Likely cause: in the quest lobby the DLL gave the Switch host Index 0, the same as the
PC's own 0, so the game could not tell the sender from itself. Change: in a quest the PC made, the Switch host is
Index 1 there (the PC stays 0). The old "read back 0 once, then the room slot" trick is gone.
getMyQuestIndex/getQuestHostIndex return System.Nullable<System.Int32> (8 bytes), not an int.

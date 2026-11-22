# rise-bridge: PC (Steam) players into a mhrise-recomp hub

Built from `rise_netlog.txt`, `analysis/NOTES.md` and the port's `ldn.cpp`. Python 3.8+, `pip install cryptography`.

    python3 tests/test_pia.py && python3 tests/test_hublink.py     # both pass

## One change to the plan

The plan has a hub-side helper (one Pia station per PC player) and a PC DLL. The port's hub protocol makes the
helper unnecessary as a separate server. A hub link is just "HELLO with a MAC and a name, get an address back, send
UDP datagrams", and the host picks the address and node, so **each PC player can be its own station, inside the
PC DLL** (or a small exe beside it). The MAC is whatever the DLL makes up, which also settles "the station ID for a
player with no MAC". Nothing needs changing on the hub server. `bridge/hublink.py` is that client (tested against a
stand-in host). If you still want it server-side later, the same modules work.

## What's here

| file | does |
|---|---|
| `bridge/pia.py` | Pia packets: header, AES-GCM (8-byte tag), message lists. Output verified by the reader in `rise_net.py`. |
| `bridge/hublink.py` | MHGS server LIST/JOIN, link HELLO/WELCOME/DATA, NetworkInfo reader. |
| `bridge/joinmsgs.py` | `0x14` / `0x18` / `0x24` / `0x1c` builders from NOTES (each field tagged CERTAIN or GUESS) and the Steam 6-byte framing. |
| `tools/diff_join.py` | Rebuilds the first `0x14` request from a Switch capture and lists the bytes that differ. This settles the GUESS fields. |

## Step 2, the Pia station: what's left

1. **The session key.** Not in the files you sent (the Switch `local_play_*.txt` capture is missing, and only that
   has `# AES key`). Two ways: (a) easiest, add a link frame to the port so the host sends the key it already logs
   (`net_log` hooks Pia's key schedule) to a bridge station; (b) derive it from NetworkInfo's security parameter
   (`NetInfo.security_parameter`) and session ID. Only a Switch capture can show whether (b) is possible.
2. Run `tools/diff_join.py local_play_<date>.txt` and fix `joinmsgs.py` until zero bytes differ. Then the same for the
   `0x18` and `0x24` messages (not written yet: they need that capture to get right).
3. Station loop: answer `0x24` with `01 21…`, send `0x14`, ack `05 00 00 00`, `01 fd`, `0x1c` clock, `0x58`
   keepalives (13 bytes, constant), and `0x68` for game data, with counters and the nonce counter going up.

## Step 3, the PC DLL

Keep the logger's `LoadLibraryExW` and `CreateInterface` hooks. Then, in order:

- **Lobby list:** on `RequestLobbyList`, call `hublink.list_hubs`. Each hub is a lobby (fake 64-bit ID), with the same
  keys the log shows: `OwnerId`, `Name`, `SlotTotalUse`, `BinarySize`, `BinaryData` = base64 of advertise data from
  byte 0x10 (the Switch's has 16 more bytes in front, which the station keeps for the session ID).
- **The hard part is call results.** `RequestLobbyList`, `JoinLobby`, `CreateLobby` answer through Steam callbacks
  (`LobbyMatchList_t`, `LobbyEnter_t`), so the DLL has to hand the game those itself (hook `SteamAPI_RunCallbacks` /
  the call-result registry, or `SteamAPI_ManualDispatch_*`). I haven't seen how the game registers them; that needs
  a look at the exe, so I haven't written this part.
- **Messages:** each Pia station = a fake Steam ID. Game to peer k goes out as `steam_unwrap` then Pia `0x68` to that
  station; in the other direction, `steam_wrap` into `ReceiveMessagesOnChannel`. Answer `SteamConReq` with `SteamConAns`
  locally. Wrapping the Switch's 0x68 payload unchanged is right: your notes show the messages are byte-identical.
- Run it with real Steam. Replacing the matchmaking and messages interfaces doesn't need OnlineFix.

## Step 4, test order

1. Offline: `diff_join.py` on a Switch capture until the join messages match.
2. A Python station (no game) joins a real port hub: check `[ldn] player N joined`, then that the port's Pia accepts
   its keepalives (no drops after 30 s).
3. Only then the DLL: lobby shows in the list, join gets past `SteamConReq`, first 15-byte `00 01 03 02` message arrives.
4. The 486-byte messages (~1000 from one peer within 15 s in your log, none on Switch, all different) are the open
   question: compare against the Switch's 270 to 460-byte ones with `rise_net.py compare`. Quests and leaving come after that.

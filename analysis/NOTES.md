# MH Rise multiplayer: PC (Steam) and Switch (Local Play) side by side

What the captures show so far, for a bridge that would let the mhrise-recomp port (Switch's Local Play, over its hub
servers) and the PC version (Steam lobbies) play together. Everything here comes from watching the traffic of each
side; no code of the game, Pia or Steam is in this repo.

Captures: `rise_netlog.txt` from this repo's `dinput8.dll`, and `local_play_<date>.txt` from mhrise-recomp's Debug →
Capture Local Play. `rise_net.py` reads both (see its help).

## 1. The game's own messages are the same on both

- **Switch:** inside Pia, protocol type `0x68`.
- **PC:** inside Steam's `ISteamNetworkingMessages::SendMessageToUser` / `ReceiveMessagesOnChannel`, always the same
  channel, behind a 6-byte header: `u16` length, then `u32` length again (both big endian).
- Hundreds of different messages appear byte for byte in captures of different sessions on the two platforms.
- A message: 3 bytes that follow from the content (the same content always has the same 3 bytes, on both platforms;
  the formula isn't known and a bridge doesn't need it), then the rest XORed with a single byte, whose first byte is 0.
  After that, two bytes that look like a kind: `01 03`, `02 03`, `03 02`, `04 06`, the same set on both.
- The first game messages after joining match too: a 15-byte one (`00 01 03 02 …`), then 12, 9 and 8-byte ones with a
  counter, on both sides.
- Differences: PC's player data on joining comes as about 500 messages of 486 bytes from one player within 15
  seconds; the Switch has nothing that size (its large ones are 270–460 bytes). PC also has 16 and 24-byte `03 02`
  messages far more often. Either the same data is cut differently, or PC sends some things the Switch handles in Pia.
  Lining these up is still to do.

So a bridge doesn't have to understand or rewrite the game's messages, only carry them. What it has to do is play
each side's session layer.

## 2. PC: how players find and join each other (Steam lobbies)

Hosting (a lobby; a second one, type 3, opens with a quest):

```
CreateLobby type 2, up to 4
SetLobbyData "OwnerId" = <host's Steam ID>    "Name" = <host's Steam name>
             "P2pVersion" = "0"  "IsPrivate" = "false"  "IsClose" = "false"  "IsEnableAuth" = "true"
             "Attribute" = "0"  "Group" = "0"
             "SearchKey0".."SearchKey14" (decimal ints), "SearchKeyNum" = "15"
             "BinaryData" = base64, "BinarySize" = "100"
SetLobbyMemberData "Index" = "0"    SetLobbyData "SlotTotalUse" = "1"
```

`BinaryData` is the room description, and it is **the same structure as the Switch's Local Play advertise data from
its byte 0x10 on**: `4f 28 18 b9`, zeros, `00 04`, then a length and the player names in UTF-16 (each with a 16-bit
length in front), a few small fields. The Switch's advertise data has 16 more bytes in front: the session ID (4 bytes,
used in Pia's nonce), zeros, `08 10 00 00` and 4 more bytes.

Searching and joining:

```
lobby filter "P2pVersion" = 0; "IsPrivate" = "false"; "IsClose" = "false"; "OwnerId" != own Steam ID
RequestLobbyList
GetLobbyData "SlotTotalUse" / "OwnerId" / "IsPrivate" / "IsClose" / "BinarySize" / "BinaryData" / "Name"
JoinLobby <lobby>
SteamConReq / SteamConAns (12 bytes each, "SteamConReq\0", both ways) with the host
the game's messages with the host (see 1)
GetLobbyMemberData <host> "Index" = "0", then SetLobbyMemberData "Index" = "3" (the joiner's slot)
SteamConReq to each of the other members, the same with each of them (a full mesh)
```

## 3. Switch: Pia, as the port captures it

- Packet: `32 ab 98 64`, version `0x89` (bit 7: encrypted). Header 0x20 bytes: `[0x09..0x0c]` the sender's key
  (4 bytes, the same one the join messages carry; its last byte goes into the nonce), `[0x0f]` how many bytes at the
  end aren't ciphertext, `[0x10..0x17]` the nonce's other 8 bytes, `[0x18..0x1f]` not decoded yet.
- AES-128 in GCM's counter mode, counter from 2. Key: from Pia's key schedule each session (the capture logs it,
  `# AES key … from main+0x24d9cb0`). Nonce: CRC32(session ID [4 bytes] + sender's MAC)'s first 3 bytes big endian,
  header byte 0x0c, header bytes 0x10–0x17. Ciphertext from 0x20 up to those last `[0x0f]` bytes. (`rise_net.py` decrypts; the tag
  isn't checked.)
- Decrypted: messages, each a field mask (1 flags, 2 size u16, 4 protocol type u8 + port u24, 8 destination u64; a
  field not in the mask is the previous message's), the payload, padded to 4. `0xff` ends the list.
- Protocol types seen: `0x68` game, `0x58` keepalive / clock (13 bytes, constantly), `0x14` connection, `0x18` session,
  `0x1c` clock sync, `0x24` mesh / station list, `0x08` leaving.

Joining (port is station .3, host .1, one more player .2):

| time | from → to | type | payload |
|---|---|---|---|
| 07.760 | host → all | 24 | `01 11 49 …` station list: each station's address `a9 fe 6a 0N 30 39` (169.254.106.N:12345) and index, `ff`-terminated empty slots (121 bytes) |
| 07.857 | joiner → broadcast | 24 | `01 21 00…` (20 bytes) |
| 08.388 | joiner → host | 14 | `01 00 04` + host's station ID (8: its MAC reordered) + host's key (4) + `08` and 8 (protocol type, version) pairs `14 02 18 03 1c 00 24 00 58 03 68 01 94 01 a4 00` + `00 24 02 06 00 00` + own address:port + own station ID + key + … the player's name (`Hunter`, UTF-8) … (308 bytes) |
| 08.456 | host → joiner | 18 | `20 02 …` the session: each member's address:port, station ID, key (556 bytes) |
| 08.953 | host → joiner | 14 | `05 00 00 00` + u32 (an acknowledgement, counting) |
| 08.979 | host → joiner | 14 | `02 00 04` + joiner's station ID + key + the same list as above, the host's side (949 bytes) |
| 09.009 | joiner → host | 14 | `05 00 00 00` + u32 |
| 09.266 | joiner → host | 18 | `01 fd` + u32 |
| 09.852 | host → joiner | 18 | `02 03 00 02 01 00 03 00 04 00 08 …` the members again (224 bytes) |
| 09.883 | host → joiner | 68 | the first game message (15 bytes, `00 01 03 02 …`, as on PC) |
| 09.906 | joiner → host | 1c | 16 bytes: `00 00 00 6a 3d 55 cd df` + 8 zero bytes; the host answers with its time in the last 8 |
| 11.360 | other member → joiner | 14 | `02 00 04 …` (949), the same as the host's: every member connects to every other |
| later | | 08 | leaving: empty payload |

The station ID is the MAC's bytes reordered: MAC `02:c9:9f:56:8d:1a` → `9f 8d 1a 56 c9 02 00 00` (bytes 2, 4, 5, 3,
1, 0).

## 4. What a bridge would be

| Switch side (Pia) | PC side (Steam) |
|---|---|
| hub listing: LDN network info + advertise data | lobby list: lobby data, `BinaryData` = advertise data from 0x10 |
| join: Pia `0x24` / `0x14` / `0x18` / `0x1c` exchange | `JoinLobby`, `SteamConReq` / `SteamConAns` |
| player = station (address, station ID, key) | player = Steam ID, lobby member `Index` |
| game message in Pia `0x68` | game message in `SendMessageToUser`, 6-byte header |

The likely shape: a PC-side DLL (built on this logger's hooks) that answers the game's lobby and message calls itself,
talking to the port's hub server; and on the hub's side, something that speaks Pia for each PC player (one station
each) and moves `0x68` payloads between the two. Open questions:

1. The fields of `0x14` / `0x18` / `0x24` in full, enough to make a PC player a station the Switch side accepts (the
   key, the nonce byte, the station ID for a player with no MAC).
2. Whether Pia's GCM tag is checked by the game (the bridge has to make a real one if so; GHASH with the same key).
3. The 486-byte PC messages against what the Switch sends on joining.
4. What the `SearchKey`s are (quest, rank, region…), to fill them for a Switch room.
5. What `SteamConReq` / `SteamConAns` lead to on the PC (whether anything else is checked: `IsEnableAuth` = true
   suggests Steam's auth tickets; with OnlineFix those may be faked already).

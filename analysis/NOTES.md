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

- Packet header, 0x20 bytes (checked against two captures):

  | bytes | what |
  |---|---|
  | 0x00–0x03 | `32 ab 98 64` |
  | 0x04 | `0x89`: version 9, bit 7 = encrypted |
  | 0x05–0x08 | the receiver's key, or 0 when the packet goes to several (then the trailer lists them) |
  | 0x09–0x0c | the sender's key (the 4 bytes after its station ID in the join messages) |
  | 0x0d–0x0e | a 16-bit counter per receiver (0 on packets to several) |
  | 0x0f | the trailer's length: 2 bytes per receiver, the low 16 bits of each one's key, after the ciphertext, not encrypted |
  | 0x10–0x17 | 8 bytes of the nonce (they count up) |
  | 0x18–0x1f | **the GCM tag**, 8 bytes |

- **Plain AES-128-GCM**, 12-byte nonce, 8-byte tag, no additional data: every packet of the capture verifies with
  Python's `cryptography` (`rise_net.py verify`). So a bridge makes valid packets with any AES-GCM library. Key: from
  Pia's key schedule, new each session (the capture logs it, `# AES key … from main+0x24d9cb0`); on the hub's side
  it's to be worked out how the key follows from the session (the port can tell us, it computes it). Nonce:
  CRC32(session ID [4 bytes] + sender's MAC), first 3 bytes big endian; header byte 0x0c (the sender key's last byte);
  header bytes 0x10–0x17. Ciphertext: from 0x20 to the trailer.
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

### The join messages' fields

From the two captures that start with a join (sessions `edee5e2c` and `ece6f000`). **Certain**: seen with the
expected different values in both. **Guess**: the same in both, or seen once.

A station (member) as these messages carry it, 0x44 bytes, used in `0x14`, `0x18`:

| offset | size | what | |
|---|---|---|---|
| 0x00 | 4 | `02 06 00 00` | guess: address family / length |
| 0x04 | 4 | IPv4 address, big endian (169.254.x.N) | certain |
| 0x08 | 2 | UDP port, big endian (12345) | certain |
| 0x0a | 6 | zeros | |
| 0x10 | 8 | station ID, little endian: the u64 `MAC[0] MAC[1] MAC[3] MAC[5] MAC[4] MAC[2]` (`0x24` has it big endian) | certain |
| 0x18 | 4 | the station's key (the packet header's sender / receiver key) | certain |
| 0x1c | 4 | another random 32-bit value per station | certain (differs per station and session), meaning unknown |
| 0x20 | 4 | `00 00 00 01` | guess |
| 0x24 | 0x20 | zeros | |

`0x14` (connection), first byte the kind:

- `01 00 04` request, 308 bytes: target's station ID (8) + target's key (4); `08` and 8 (protocol type, version) pairs
  `14 02 18 03 1c 00 24 00 58 03 68 01 94 01 a4 00`; `00 24` (guess); the sender as a station (above, at 0x22); at 0x66
  the session ID little endian (4); `01 01 01 01`; the player's name, UTF-8, zero-padded (here `Hunter`, twice, each
  with a `01` before); at the end (0x130) a 32-bit sequence number.
- `02 00 04` the same from the other side (949 bytes: the same layout, longer, padded).
- `05 00 00 00` + u32: acknowledges a sequence number.

`0x18` (session):

- `20 0N 00 00` + u32 (counts up with each version of the list) + `01 00 0M 00` (M: members listed) + the members as
  stations, 556 bytes: the host's list of who's in.
- `01 fd` + u32: the joiner's answer, the sequence number + 1.
- `02 03 00 02 01 00 03 00 04 00 08 00 00 00 00 0N` + every member as a station, ending in `02 00 0N 00` + the
  joiner's sequence number + 1, 224 bytes: guess, the confirmation that the joiner is in.

`0x24` (mesh, from the host): `01 11 49`, zeros, at 0x0c a byte that differs per session (5, 3; the joiner's `01 21`
echoes it), 12 random bytes per session, the host's station ID big endian, then per slot: slot index, address, port,
and `ff` for empty slots. The joiners send `01 21` + zeros + that byte, 20 bytes, to everyone.

`0x1c` (clock): the joiner sends 8 bytes of its time + 8 zero bytes; the host sends them back with its time in the last 8.

`0x08`: a station leaving, empty.

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
2. How the session key follows from the session (the port logs it, so a bridge inside the hosting port's runtime has
   it anyway; a bridge elsewhere needs the derivation).
3. The 486-byte PC messages against what the Switch sends on joining.
4. What the `SearchKey`s are (quest, rank, region…), to fill them for a Switch room.
5. What `SteamConReq` / `SteamConAns` lead to on the PC (whether anything else is checked: `IsEnableAuth` = true
   suggests Steam's auth tickets; with OnlineFix those may be faked already).

## 5. Joining two lobbies (PC capture of Nov 24)

One session: host a lobby and leave it, then search, join a lobby with one player, leave, join one with two.

**SearchKeys.** Each is a value plus 2^31 (so -2147483648 is 0, -2147483647 is 1), the usual way of making a signed
key sort like an unsigned one. Across three lobbies:

| key | value | what |
|---|---|---|
| 0 | 1 | always 1 (lobby kind?) |
| 1, 2, 7–10 | 0 | always 0 here, and the search asks for 0 on 7–10: filters nobody set (quest, target…?) |
| 3 | 4, 999, 335 | the host's Hunter Rank |
| 4, 5 | 1, 999 | the room's HR range, lowest and highest |
| 6 | 965861185 | the same in every lobby, and the search asks for it exactly: the game's network version |
| 11 | 0, 999, 123 | the host's Master Rank |
| 12, 13 | 0, 999 | the room's MR range |
| 14 | 965861184 | key 6 minus one |

The search: `SearchKey6` equal to its own (so only the same network version is listed), `SearchKey7`–`10` equal to 0,
the host's HR (3) and MR (11) within 1..999 / 0..999, and the room's ranges (4, 5 and 12, 13) including the searcher's
own HR and MR. Comparison codes are Steam's: -2 less or equal, 0 equal, 2 greater or equal, 3 not equal.

For the bridge: a Switch room listed on PC needs key 6 set to the PC's value (the Switch's own network version is to be
compared: if it differs, the two games may not be meant to talk, and the bridge would have to translate or refuse).

**BinaryData** (88–108 bytes): `4f 28 18 b9`, zeros, `00 04`, then the hunter's name (u16 byte length, UTF-16), then a
block with the HR (`00 04 00 04`, `03 e7` = 999 in the 999 rooms), `00 01 00 0b 00 0d`, then the Steam name (u16 byte
length, UTF-16) and the same HR block again. That is, a list of members, each with a hunter name, ranks and an account
name; on the Switch the account name would be the console's user nickname.

**Steam's auth tickets travel inside the game's messages.** On joining, after `SteamConReq` / `SteamConAns`:

```
< host   309 bytes, kind 03 02      (the host's 234-byte ticket, obfuscated like any game message)
BeginAuthSession host, 234 bytes -> 0 (OK)
GetAuthSessionTicket -> 234 bytes
> host   275 bytes, kind 03 02      (the joiner's)
SetLobbyMemberData "Index" = <slot>
```

Then the same with every other member (a full mesh: each pair exchanges tickets), `EndAuthSession` for each on leaving.
The ~480-byte messages of kind `04 06` from the host follow at once (its player data, as before), and the joiner sends
its own in 240–430-byte pieces.

For the bridge: the PC-side DLL answers `BeginAuthSession` for bridged players itself (they have no Steam ticket), and
the bridge drops the `03 02` ticket messages going to the Switch side and makes up the ones a PC player expects from a
Switch player. What the Switch sends in that place on joining is still to be lined up (a Switch capture of the same
steps).

Note: this capture's Steam client library is `OnlineFix64.dll`, not Steam's. Lobbies and messages behave as Steam's
API says, but the tickets here are OnlineFix's; the bridge shouldn't depend on either.

**The Switch's advertise data next to it** (a port capture of the same night, two rooms, no AES key logged): from 0x10
it is the same layout, member by member: the hunter's name, then the HR block (`00 04 00 01` for an HR 1 hunter,
`00 04 01 51` for HR 337, with `00 83` = MR 131 further on). Where PC has `00 04 00 01 00 0b 00 0d` and the Steam name,
the Switch has `00 04 00 00` and no name: that second block is the platform account, empty on the Switch. The 16 bytes
in front (session ID, zeros, `08 10 00 00`, then 4 bytes) change with every room, so the Switch's advertise data
carries nothing like PC's `SearchKey6` network version; if the two have a version check, it's in the join messages.

## 6. The Switch join decrypted, and the PC-only messages (port capture of Nov 24, two rooms)

`rise_net.py` now takes a capture with several networks (each with its own key and session ID): it tries every key
and session ID and remembers which one each sender's packets verify with. All but one of the 9929 packets verify. The
join messages are as in section 3.

**A second layer in the game's messages.** After the XOR byte is taken off, each byte from the second on is still
XORed with the one before it (`unchain` in `rise_net.py`). With both layers off, the messages read plainly: small
counters, lengths and IDs.

**The first messages after joining, side by side** (kind, size):

| PC | Switch | |
|---|---|---|
| `01 03`, 15 | `01 03`, 15 | the same on both |
| `01 03`, 12 | `01 03`, 12 | the same |
| `01 03`, 9 (`00 01 01`) | `01 03`, 9 | the same |
| `03 02`, 36 | — | **PC only**: carries the sender's Steam ID |
| `02 03`, 21 (`… 00 00 00 01 00 01 01`) | `02 03`, 21 | the same |
| `01 03`, 8 | `01 03`, 8 | the same |
| `03 02` / `02 03`, 16 and 24 | `03 02` / `02 03`, 16 | counters, on both |
| `03 02`, 309 / 275 | — | **PC only**: the Steam auth ticket |
| `04 06`, ~480 | `04 06`, ~440–460 | each player's data |

The 275/309-byte message, both layers off: a header, the sender's Steam ID, `ea 00 ea` (234, twice), then the
234-byte ticket (it starts `14 00 00 00`, as Steam's tickets do). The 36-byte one holds the Steam ID too. Nothing like
either goes between Switch players.

So the bridge's job at join time is clear:
- PC → Switch: drop the `03 02` messages that carry a Steam ID or a ticket.
- Switch → PC: make up both for each Switch player (an ID the PC-side DLL hands out, a dummy 234-byte ticket), and
  have the DLL's `BeginAuthSession` accept bridged players.
- Everything else at join time passes through as it is.

Still to do: line up the `04 06` player data (PC's pieces run 30–40 bytes longer, probably the account fields), and
what the PC sends in a quest that the Switch doesn't.

## 7. A quest on PC (capture of Nov 24, three players) next to the port's

PC: join a lobby of two, then the quest lobby (`CreateLobby type 3` when posting one; `Attribute` and `Group` set
again on departure), hunt, return. The port capture of section 6 has a quest between two players.

Messages per minute during the hunt, by kind:

| | `04 06` | `01 03` | `03 02` | `02 03` |
|---|---|---|---|---|
| PC, 3 players | ~5000 | ~950–1400 | ~940–1400 | a few |
| Switch, 2 players | ~800–1300 | ~420 | almost none | a few |

- `04 06` is the same traffic on both, with the same inner layout (sizes 25, 34–36, 48, 56, 68, 486…; the 486-byte
  `01 d6 0b` ones from the host on both). Scaled by players it's the same rate: nothing about the hunt itself looks
  different between the versions so far.
- **PC sends a `03 02` for nearly every `01 03`**, 16 or 24 bytes, both layers off: the sender's byte, then counters
  (`b6 00 c2`, `b6 00 c2 00 c2 00 04 03 00 07 00`) that go up per peer. That looks like the game's own acknowledgements:
  on the Switch, Pia acknowledges and resends itself (its `0x58` messages, every ~200 ms, carry counters), so the game
  sends none there. On PC, Steam's `SendMessageToUser` is unreliable as the game uses it, so the game does it.

For the bridge, the same rule as at join time: PC → Switch drops the `03 02` acknowledgements; Switch → PC makes them
up for each Switch player as it delivers that player's `01 03` messages. That needs their counters worked out: what
each number counts, against which `01 03` (to do next, from these two captures).

## 8. The `03 02` / `02 03` messages: the game's own reliable channel, on both

Both layers off, they read plainly, and they're the same on the two platforms:

```
02 03 | from (u32) | to (u32) | 00 00 00 01 00 01 01          21 bytes: opens the channel (both ends send one)
02 03 | from | to | u16 n                                     16 bytes
03 02 | from | to | u16 n                                     16 bytes
03 02 | from | to | u16 n | u16 m | 00 04 03 00 07 00          24 bytes
03 02 | from | to | 00 00 00 01 00 10 03 00 01 01 + Steam ID + 4 bytes + 00     36 bytes, PC only
03 02 | from | to | … ea 00 ea + 234-byte Steam ticket …      275/309 bytes, PC only
```

`from` and `to` are 32-bit IDs the game picks per player (random, the same for a player towards everyone; not Pia's
station keys and not the MAC). In the 24-byte one, `n` is the sender's own count and `m` the other's count plus one
(each answers with the next one it expects): the counters go up by one each round, ~2 a second per pair.

- **Switch:** these go only around joining (the opening, then `n` = 1 repeated every ~0.5 s until the other end has
  it) and stop. Pia keeps the connection alive itself.
- **PC:** the same opening, the ticket exchange, then the 16/24-byte rounds keep going at ~2 Hz for the whole session:
  the game's own keep-alive, since Steam's messages don't have Pia's.

`01 03` (8 and 9 bytes) is a separate ping on both: `03 n 00` asked and `03 n 01` answered, `04 n` a counter.

**The bridge's rules, complete for joining and hunting:**

| PC → Switch | Switch → PC |
|---|---|
| drop `03 02` with a Steam ID (36) or ticket (275/309) | make both up for each Switch player (an ID the PC-side DLL gives out, a dummy ticket the DLL accepts) |
| drop the keep-alive rounds after the opening | answer the PC's rounds for each Switch player (its own `n`, the PC's `n` + 1) and start its own |
| everything else as it is | everything else as it is |

The 32-bit `from`/`to` IDs pass through untouched: each side already uses the other's as they come.


## 9. The PC hunter that the Switch doesn't show (captures of Nov 24, 05:10 and 05:30)

The PC joins the port's room and both stay in. The PC shows the Switch player's hunter and sees it walk; the Switch
side shows only its own. The port's `log.txt` has `[ldn] player 1 joined (…), a PC player` and no errors (the game
doesn't log why it leaves a player out). Compared with two phones (`local_play_20261124_023525`, host `.1`, joiner
`.2`) and with the bridge sessions (`local_play_20261124_051029`, `local_play_20261124_053008`, the PC at `.2`).

**The `04 02` channel**, both layers off: `04 02 | sender (u32) | receiver (u32) | length (u16) | kind (u8) | body`.
`length` counts from `kind` on. The low 7 bits of `kind` are `0x1e` or `0x0b`, the top bit marks a bit-packed body
(`9e`, `8b`). The bodies of `9e`/`8b` aren't byte-aligned and aren't decoded yet.

- **`1e`, 21 bytes:** the steady stream while walking, ~5 a second each way. The PC sends them at the same rate as a
  Switch, and the port gets them all. (An earlier note here read the few `8b`/`9e` as "nothing is sent"; it was this
  stream that carries walking.)
- **`0b 08`, 18 bytes:** `0b 08 | n (u32 BE)`, repeated a few times. **`0b 02`, 482 bytes:** a big transfer in 470-byte
  pieces, `0b 02 | n + 1 (u32) | id (u32) | total size (u32) | …`. The sender announces `n`, then sends piece after
  piece of transfer `n + 1`. Between two phones only one of them sends one (id `5435c499`, 215,358 bytes, the same
  device whether host or joiner); PC to PC, ids `55de5757` (358,357 bytes) and `218c8fd7` (218,097). It goes one way
  even between phones, so it isn't what's missing. Guild cards arrive fine both ways (tested).
- **`9e`, the hunter's periodic state:** every hunter sends the same three messages over and over (several a second),
  and their sizes give the PC away:

| Sender | First (the big one) | Second | Third |
|---|---|---|---|
| the port, as host (to a phone and to the PC alike) | 452–455 | 367–370 | 60 |
| a phone joiner | 435 | 360–362 | 58 |
| the PC | **338–341** | 369–370 | **51** |

The two phones are a few bytes apart (different hunters, gear). The PC's first message is ~100 bytes shorter every time,
and in a different order (51 comes second). Reading it the other way works: the PC game draws the port's hunter from
the Switch-made messages. The Switch game, given the PC-made ones, never puts the hunter in, and the walking stream then
has nothing to move.

**Names from the game's type database** (`tdb_types.py`, read from the Switch `main`; the PC has the same types):

- `snow.PlayerNetwork` is the hunter's network component: `RefRemoteGameObject` (`via.puppet.RemoteGameObject`),
  `RefPlayerBase`, `FirstFsmPacketReceived`, `_PacketQue`; methods `sendPeriodicPacket`, `updateSendPeriodicPacket`,
  26 overloads of `receive`, one per packet type.
- Its packets: `PlayerPeriodicLobbyBasePacket` (`_Position` vec3, `_Dir`, `_InvalidDataFlags`) in the village/hub,
  `PlayerPeriodicQuestBasePacket` on a quest (adds aim, vital, condition and weapon flags), `PlayerAreaMovePacket`,
  `PlayerWarpPacket`, `PlayerConditionChangePacket` and per-weapon ones.
- `via.puppet.RemoteGameObject` is the engine's replicated object: `MessageVersion`, `SyncMode`, `MasterIndex`,
  `SyncMotion`/`SyncMotionFSM` and their variables, `CurrentPrefab`, `Instance`, events `OnNtcInstantiate`,
  `OnNtcRecvState`. The big `9e` messages look like its state sync (motion FSM and its variables), which is where a PC
  build could pack differently.
- `snow.player.PlayerManager` makes the hunters: `createPlayer` (3 overloads), `setPlayerCreateBaseData`,
  `instantiatePlayerParts`; `getPlayer(index)`. `snow.player.PlayerBase`: `isDrawPlayer`, `isMasterPlayer`,
  `deserializeNetworkCommonFlags`, `deserializeNetworkPlAttr`.

**Next:** `probe/crossplay_probe.lua` logs those calls and each player slot's state on both sides, so one session with
it shows how far the Switch game gets with the PC's hunter: no slot, a slot that isn't drawn, a network object with a
different `MessageVersion`, or `receive` calls that never come. That decides what the helper has to convert.

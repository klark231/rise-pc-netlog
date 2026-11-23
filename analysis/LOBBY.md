# The lobby layer: where PC online and Switch Local Play differ

From the PC captures (PC host, PC joiners) and the port's Local Play captures (Switch host, a Switch joiner, and the
bridge), 2026-11-20 to 2026-11-23.

## Reading the messages

`rise-bridge/bridge/wire.py` has the exact encoding, checked on every captured game message (34,484 PC, 8,961
Switch): a message is a 4-byte check (CRC-32 of the payload, adjusted by length) followed by the payload, all of it
sent as a running XOR. With that undone the payloads are plain. They start with a channel: `01 02` control (hello,
platform and identity, counters), `02 01` member status, `03 01` the lobby, `04 02` game data. The platform message
is `01 02 02 <platform> <id>`, PC `00`, Switch `21`.

The Switch compresses some of these first (Pia flag `0x20`, zlib); see `bridge/station.py`.

## The reliable channel (`03 02`)

Every message carries a sequence and an acknowledgement after the identities; most of them (16 to 72 bytes) are just
that, plus small keep-alive records (`03 00 07 00`), on both platforms. The ones that matter are the records the host
and joiner swap on joining:

| record | PC online | Switch Local Play |
|---|---|---|
| join request | joiner → host, record `01`: the joiner's Steam ID + 4 bytes (36 bytes in all) | none |
| host's answer | record `02` (session) + `08` (the host's ticket, below) + one `03` per other member (index, Steam ID, 8 bytes, Steam ID again) + `05` (end), 389 bytes for a 3-player lobby | one record with the **room description** (the same bytes as the lobby's `BinaryData` / the advertise data from 0x10), 85 to 109 bytes, sent compressed |
| joiner's answer | record `08`: the joiner's own ticket (275 bytes), then the same to every other member | nothing but acknowledgements |
| then | about 2 s of acknowledgements, then a 21-byte `02 03` and the player data on `04 06` | at once: a 21-byte `02 03`, a 16-byte `03 02`, the player data on `04 06` |

The `04 06` game data that follows uses mostly the same kinds on both (by the first bytes after the identities), so
past the lobby it is the same game talking.

## Record `08` is a Steam auth session ticket

234 bytes after `ea 00 ea`, checked on 19 records from three PC sessions:

- `14 00 00 00`, then an 8-byte GC token, **new for every ticket** (the same player's differs each time)
- the player's Steam ID (little endian), a Unix timestamp from the day of the capture
- `18 00 00 00`, `01`, `02`, two 4-byte values that look like addresses, a millisecond count
- an ownership ticket (`b2 00 00 00` = 178 bytes) for **app 480** (Spacewar, which OnlineFix plays as),
  ending in a 128-byte RSA signature from Steam

So every PC player hands the others a Steam-signed ticket, and the lobby has `IsEnableAuth = true`. The others are
expected to check it with `ISteamUser::BeginAuthSession`, and Steam answers with `ValidateAuthTicketResponse_t`
(callback 143). A Switch player can't have one, and Steam doesn't know the bridge's made-up ID.

This is local to the PC that checks: nothing about it goes to the other side. So the PC's DLL can let it through:
`BeginAuthSession` for the bridge's host ID returns OK without asking Steam, and the DLL hands the game callback 143
with OK itself (`netlog.cpp` `begin_auth`, `bridge.cpp` `auth_ok`). Any bytes will do as that host's ticket.

## What the bridge does (rise-bridge/bridge/lobby.py)

The lobby channel isn't passed through any more:
- **Toward the PC it is the PC host.** The PC's join request gets records `02` (session: `u64 3`, the made-up host's
  Steam ID, 4 bytes that stay the same per host, here the Switch host's id), `08` (that ID's ticket, the real layout
  with no signature) and `05`. Then a keep-alive record every half second, and every record the PC hasn't
  acknowledged goes again with the next one, as both games do.
- **Toward the port host it is a Switch joiner:** each lobby message is acknowledged with the 12-byte message a real
  Switch joiner sent (byte for byte the same in the test).
- The member status (`02 01`) and game data (`04 02`) go through unchanged, the platform message with the other
  side's platform byte and the same identity.

Not done yet: other players besides the host (record `03` entries), and what the PC's join-time bulk data on `04 02`
(486-byte messages) does to the Switch host.

## Next test

The DLL now logs `GetAuthSessionTicket`, `BeginAuthSession` (with its result) and `EndAuthSession`. A PC-to-PC online
join with this DLL shows when the game checks tickets, and what it does if a check fails.

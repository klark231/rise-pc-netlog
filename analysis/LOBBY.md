# The lobby layer: where PC online and Switch Local Play differ

From the PC captures (PC host, PC joiners) and the port's Local Play captures (Switch host, a Switch joiner, and the
bridge), 2026-11-20 to 2026-11-23.

## Reading the messages

A game message is `[4-byte checksum header][data]`, with the data XORed with the header's last byte
(`gamemsg.data_of`). Inside that, **each byte is also XORed with the byte before it** (as sent):

    plain[0] = data[0];  plain[i] = data[i] ^ data[i - 1]

With both undone, the member messages are readable. `data[0:2]` is the channel: `01 03` keep-alive counters, `02 03`
member status, `03 02` the reliable lobby channel, `04 06` game data. After the channel, two 4-byte identities (the
sender's and the receiver's, chain-decoded so they look different from the raw IDs).

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

## What the bridge has to do (PC joining a Switch host)

1. **Toward the PC, play the PC host's side of the lobby.** Answer the PC's join request (record `01`) with records
   `02`, `08` (a dummy ticket for the made-up host ID), `03` for any other member, `05`, in the PC host's layout.
   Still to work out: the fields of `02` (23 bytes) and `03` (36 bytes) beyond the Steam IDs.
2. **Keep the reliable channel's numbering apart on the two sides.** The bridge adds records the Switch never sent
   and drops ones the PC sends (its join request, its ticket), so each side's sequence and acknowledgement numbers
   have to be translated, for the rest of the session.
3. **Toward the Switch, play a Switch joiner:** acknowledge the room description, send the 21-byte `02 03` and the
   16-byte `03 02` (the old helper's `memberid` messages, now with the right identities), and let the PC's player
   data through on `04 06`.
4. **Check the `04 06` data** once the PC gets that far: the PC's join-time bulk data (486-byte messages, kind
   `01 d6 0b 02 00`) has no Switch counterpart.

## Next test

The DLL now logs `GetAuthSessionTicket`, `BeginAuthSession` (with its result) and `EndAuthSession`. A PC-to-PC online
join with this DLL shows when the game checks tickets, and what it does if a check fails.

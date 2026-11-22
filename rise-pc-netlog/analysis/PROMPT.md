# A prompt for continuing this with another assistant

Paste the text below, then attach `NOTES.md`, `rise_net.py`, and the captures (one `rise_netlog.txt` with a lobby
being hosted or joined, one `local_play_<date>.txt` of a Local Play join). If the assistant can't run Python, also
paste the output of `python3 rise_net.py switch <capture>` and `python3 rise_net.py pc <log>`.

---

I'm working on crossplay between two versions of Monster Hunter Rise:

- **mhrise-recomp**: my native Android port of the Switch version (my own project, GPL-3). Its Local Play runs over
  IP: players meet on hub servers (a lobby server that lists hubs and splices TCP links), and the game's Pia UDP packets
  go through that link.
- **The PC version** on Steam, online through Steam lobbies and `ISteamNetworkingMessages`. I have a DLL
  (rise-pc-netlog, a `dinput8.dll` proxy with MinHook) that wraps the Steam interfaces the game gets, which is how I
  captured the traffic.

The attached `NOTES.md` has what's established from captures of both: the game's own messages are byte-identical on
both (Pia protocol type 0x68 on Switch; a 6-byte length header on Steam), Pia's encryption is solved, and the join
sequences of both are written out. `rise_net.py` parses and decrypts the captures.

The goal is a bridge so a PC player can join a port player's hub (and the other way around later). The plan:

1. On PC, a DLL built on the logger's hooks that answers the game's `ISteamMatchmaking` and
   `ISteamNetworkingMessages` calls itself: lobby list from the hub servers, `JoinLobby` / `SteamConReq` /
   `SteamConAns` played locally, game messages carried to and from the hub.
2. On the hub side, one Pia station per PC player: the join (types 0x24, 0x14, 0x18, 0x1c), keepalives (0x58),
   encrypting with the session key, and moving 0x68 payloads.

Already worked out (in `NOTES.md`): Pia's packet header field by field, that it's plain AES-128-GCM with an 8-byte
tag (every captured packet verifies), and a first field map of the join messages, each marked certain or guess.

What I need from you now, in this order:

1. Check the join messages' field map against the captures and fill in what's marked guess or unknown (the random
   32-bit value per station, the byte at 0x0c of `0x24`, the 12 random bytes in `0x24`, the `02 03 …` `0x18` message).
   Keep marking each field certain or guess.
2. Line up the PC join's first 30 game messages with the Switch join's, and explain the 486-byte PC messages.
3. Propose the bridge's design concretely: which process does what, the messages each side sends when a PC player
   joins, and what state it keeps. One option to weigh: the Pia side living inside the hosting port's own runtime,
   which already knows the session key. Don't write the code yet.

Rules:

- Work only from the captures and public documentation (Valve's Steamworks SDK headers are fine). No code from Capcom,
  Nintendo, Pia, OnlineFix or leaked SDKs, and don't ask me to disassemble OnlineFix.
- Say when something is a guess. Don't fill gaps with what Pia "usually" does unless a capture shows it.
- Don't put Steam IDs or player names from the logs in anything you write; they're other people's.
- When code comes later: C++17, comments in plain English that read like a person wrote them, MIT or GPL-3
  compatible.

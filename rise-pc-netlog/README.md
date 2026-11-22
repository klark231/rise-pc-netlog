# rise-pc-netlog

Logs what Monster Hunter Rise on PC sends and receives through Steam's networking, to `rise_netlog.txt` next to the
game. It's for comparing the PC version's multiplayer traffic with the Switch version's Local Play, as captured by
[mhrise-recomp](https://github.com/klark231/mhrise-recomp) (Settings → Debug → Capture Local Play), to see whether the
two could be bridged.

It only reads: nothing about the game, Steam, app IDs or ownership is changed. You need your own copy of the game on
Steam.

## Use

1. Download `rise-pc-netlog.zip` from the latest release and put `dinput8.dll` in the game folder, next to
   `MonsterHunterRise.exe`. (If you use REFramework, which is also a `dinput8.dll`, take it out while testing.)
2. Start the game and play online with someone: host or join a lobby, walk around, post a quest.
3. Close the game and send `rise_netlog.txt` from the game folder.

Remove `dinput8.dll` when you're done; the log grows fast while you're online.

## What's in the log

- `Steam client library: …` and `interface …` lines: which Steam library and networking interfaces the game uses.
- Lobby lines (`CreateLobby`, `RequestLobbyList`, `lobby filter`, `JoinLobby`, `SetLobbyData`, `GetLobbyData`, …):
  how players find and join each other. A value the game reads is logged when it changes.
- A line per packet: time, `>` sent or `<` received, the Steam function, the other player (Steam ID, or the
  connection), the channel and size, then the bytes in hex with ASCII beside them.

## Analysis

`analysis/` has what the captures show so far (`NOTES.md`), a script that reads and decrypts both kinds of capture
(`rise_net.py`), and a prompt for carrying on with another assistant (`PROMPT.md`).

## How it works

The game loads `dinput8.dll` at start; this one loads the real one from System32 and passes its functions through. It
hooks `LoadLibraryExW` to catch the Steam client library as it loads, hooks its `CreateInterface`, and wraps the send and
receive functions of the networking interfaces the game asks for (`ISteamNetworking`, `ISteamNetworkingMessages`,
`ISteamNetworkingSockets`) and the lobby functions of `ISteamMatchmaking`, logging the data and calling the originals.

## Building

Windows, Visual Studio 2022 and CMake:

```
cmake -S . -B build -A x64
cmake --build build --config Release
```

GitHub Actions builds it on every push (artifact `rise-pc-netlog`) and makes a release for every `v*` tag.

## Credits

- [MinHook](https://github.com/TsudaKageyu/minhook) by Tsuda Kageyu (BSD 2-clause), fetched at build time.
- Interface layouts from Valve's public Steamworks SDK headers.

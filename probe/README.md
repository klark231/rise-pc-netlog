# Crossplay probe

`crossplay_probe.lua` logs what the game does with the other players' hunters. It's for finding out why the Switch side
doesn't show the PC player's hunter while the PC shows the Switch one (`analysis/NOTES.md`, section 9). It only reads
and counts: it changes nothing in the game.

The same script runs on both:

- **PC (REFramework):** copy `crossplay_probe.lua` into `reframework/autorun` in the game folder. The lines go to
  REFramework's log, `re2_framework_log.txt` in the game folder.
- **Android port** (a build with the Lua runtime, which the netlog build is): Settings → Mods & cheats → **Add a mod**,
  and pick `crossplay-probe.zip` (in the build's `probe` folder; it's
  `crossplay_probe.lua` in `reframework/autorun`). The lines go to `log.txt`.

Every line starts with `[xprobe]`:

| Line | Means |
|---|---|
| `ready` | the script started |
| `snow.PlayerNetwork.receive: N hooked` (and the other `hooked` lines) | which game functions it's watching; `0 hooked` or `could not hook` means that part isn't available here |
| `slot N: …` | a player slot changed: `empty`, or the hunter in it, whether it's drawn, whether it's ours, and its network object (name, master index, message version, sync mode, whether its first state packet arrived, prefab, instance) |
| `PlayerManager.createPlayer(…) args …` | the game is creating a hunter (also `setPlayerCreateBaseData`, `instantiatePlayerParts`) |
| `receive …(…) player N #count` | a hunter's network packet of that kind arrived for player N (first one, then every 200th) |
| `deserializeNetwork… player N #count` | the game read that hunter's network flags or attributes |
| `RemoteGameObject.instantiate(…)` | a network object got its instance |

What to compare: run it on both sides in the same session, standing together for a minute. On the side that shows the
other hunter, the other player's slot fills in and its `receive` lines count up. On the side that doesn't, the `slot`
and `createPlayer` lines show how far the game got with that hunter.

# Music discs

`mc.MusicDisc` creates a native jukebox item. The game handles insertion,
playback, comparator output, ejection, and the disc description tooltip.

```python
import fabricpy as mc

mod = mc.Mod("musicmod", "My Music", minecraft_version="1.20.1", loader="all")

@mod.register
class FirstSong(mc.MusicDisc):
    item_id = "first_song"
    display_name = "First Song Music Disc"
    sound = "music/first_song"
    length_seconds = 180
    comparator_output = 7
    artist = "Your Name"
    title = "First Song"
    texture = "discs/first_song"
```

Put the audio at `assets/musicmod/sounds/music/first_song.ogg` and the item
texture at `assets/musicmod/textures/item/discs/first_song.png`. Audio must already
be in OGG Vorbis format; FabricPy does not transcode MP3, WAV, or other formats.
Only distribute music and artwork you have permission to use.

Run `fabricpy build my_mod.py`. FabricPy registers the sound event and writes
streaming `sounds.json` metadata, so the whole track does not need to be loaded
into memory. You can use the ordinary crafting recipe and creative-tab APIs with
this item. The default generated creative-tab entry is the same as other items.

## Fields

| Field | Meaning |
| --- | --- |
| `sound` | Required sound resource path, such as `music/song` |
| `length_seconds` | Positive duration; defaults to 180 seconds |
| `comparator_output` | Integer between 0 and 15; defaults to 15 |
| `artist` | Optional artist text for the song description |
| `title` | Optional song title; defaults to the item display name |
| `texture`, `model` | Normal item appearance fields, including `.bbmodel` input |
| `rarity` | Normal item rarity; defaults to `rare` |
| `fireproof` | Normal fire-resistance option |

Discs have one-item stacks and no durability. Changing `max_stack_size` away
from 1 or enabling durability is rejected. A disc cannot also be food or a tool.
Item hook overrides such as `@mc.on_right_click` are rejected so that custom
callbacks cannot accidentally replace or hide native jukebox behavior.

A `.ogg` suffix on `sound` is accepted as a convenience and stripped from the
resource ID. A namespaced value such as `minecraft:music_disc.cat` references an
existing event; FabricPy does not register or copy another mod's sound. Declare
the other mod as a dependency when using its music. Unqualified paths belong to
your own mod and receive a generated sound registration.

## Minecraft versions and loaders

- Minecraft 1.20.1: Fabric/Quilt use `MusicDiscItem`; Forge uses `RecordItem` and
  its deferred sound registry. The generated `minecraft:music_discs` item tag
  includes your discs. The native API stores duration in whole seconds, so a
  fractional duration is rounded upward.
- Minecraft 1.21 and 1.21.1: discs are ordinary items with the native
  `jukebox_playable` component and a corresponding
  `data/<modid>/jukebox_song/<item_id>.json`. The song data references the
  registered sound and contains the description, duration and comparator value.
  Backends cover Fabric, Forge and NeoForge where the selected version is bundled.

Later Minecraft targets currently raise an explicit unsupported-version error for
music discs. Their item-construction APIs need separate compatibility work.

Manual JSON resources keep their entries. FabricPy merges streaming flags and
missing song descriptions into generated sound/language JSON, merges disc tags,
and preserves an existing manually supplied `jukebox_song` JSON file.

The component API is documented in [Fabric's 1.21.1 Item.Settings reference](https://maven.fabricmc.net/docs/yarn-1.21.1+build.3/net/minecraft/item/Item.Settings.html).

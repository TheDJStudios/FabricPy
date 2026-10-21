# Models And Blockstates

`fabricpy` can generate default blockstate and model JSON, and you can override those defaults from Python or from repo files.

For real moving or stretching model parts, use [animations.md](./animations.md). Static block and item JSON models do not provide that by themselves.

Repo folders:

- blockstates: `assets/<modid>/blockstates/...`
- block models: `assets/<modid>/models/block/...`
- item models: `assets/<modid>/models/item/...`

Block Python fields:

- `texture`
- `emissive_texture`
- `emissive_level`
- `textures`
- `emissive_textures`
- `model`
- `emissive_model`
- `blockstate`
- `item_model`

Item Python fields:

- `texture`
- `emissive_texture`
- `emissive_level`
- `textures`
- `model`

Default generation behavior:

- a block with only `texture = "foo/bar"` gets:
  - a default blockstate pointing to `<modid>:block/<block_id>`
  - a default block model using `minecraft:block/cube_all`
  - a default block item model with parent `<modid>:block/<block_id>`
- an item with only `texture = "foo/bar"` gets:
  - a default item model using `minecraft:item/generated`
  - `layer0` set to `<modid>:item/foo/bar`
- a block with `emissive_texture` gets:
  - an overlay block model at `<modid>:block/<block_id>__emissive`
  - an extra blockstate entry pointing at that overlay model
  - `emissive_level` mapped from `1..255` down to Minecraft light `1..15`
- an item with `emissive_texture` gets:
  - a generated `layer1` texture entry in the item model

Reference rules inside JSON:

- namespaced ids like `"mymod:block/fancy_block"` are used exactly as written
- if you are writing raw JSON yourself, always be explicit about `block/` vs `item/`
- Python `texture = ...` is path-like input; JSON `textures` values are texture ids

Example block:

```python
@mod.register
class FancyBlock(mc.Block):
    block_id = "fancy_block"
    texture = "custom/fancy_block"
    blockstate = {
        "variants": {
            "": {"model": "mymod:block/fancy_block"}
        }
    }
    model = {
        "parent": "minecraft:block/cube_all",
        "textures": {
            "all": "mymod:block/custom/fancy_block",
            "particle": "mymod:block/custom/fancy_block"
        }
    }
    item_model = {
        "parent": "mymod:block/fancy_block"
    }
```

Example item:

```python
@mod.register
class Pickle(mc.Item):
    item_id = "pickle"
    texture = "food/pickle"
    model = {
        "parent": "minecraft:item/generated",
        "textures": {
            "layer0": "mymod:item/food/pickle"
        }
    }
```

Manual override rules:

- generated defaults are written first
- repo files under `assets/<modid>/models/...` and `assets/<modid>/blockstates/...` are copied after generation
- repo files override generated JSON when the paths match

Important particle note:

- if you use a custom block model JSON, add a `particle` texture entry unless the chosen parent already handles it the way you want
- without a valid `particle` entry, block breaking particles can appear as missing textures even if the block itself renders correctly

Common mistake:

- Python says `texture = "food/pickle"` and you then write a manual item model with `"layer0": "mymod:food/pickle"`
- that is wrong for item textures
- the correct texture id is `"mymod:item/food/pickle"`

Current limitation:

- block emissive overlays are supported directly by the generated blockstate/model pipeline
- item emissive overlays are emitted as a second item model layer, but fully custom fullbright item rendering is still beyond the current Python API

Rotation handling:

- for blocks that use `variable_rotation = True`, author the model facing north
- `rotation_mode = "wall"` keeps the model upright and applies horizontal facing rotation
- `rotation_mode = "floor"` tells the compiler to use floor-placement rotation handling for that same north-authored model
- `wall_model` and `floor_model` are optional source model overrides for those two handling modes

Model-derived shapes:

- when a block model JSON contains plain `elements` cuboids, `fabricpy` can derive outline and optional collision shapes from it
- set `model_collision = True` on the block to use the model cuboids for collision
- outline shape also follows those cuboids when the generator can read them
- advanced per-element model rotations are not converted into voxel math yet

## Direct Blockbench input

```python
@mod.register
class Table(mc.Block):
    block_id = "table"
    model = "models/table.bbmodel"
    model_collision = True
```

Items and `Block.item_model` accept the same file input. A relative file path is
resolved from the project working directory (the CLI uses the Python source file's
directory). Resource-style paths such as `"machines/table.bbmodel"` are looked up
under `assets/<modid>/models/block/` or `models/item/` as appropriate.

Conversion preserves cuboids, visible faces, texture assignments, display
transforms, UV scaling and vanilla single-axis rotations. Embedded PNGs and linked
PNG files are copied into the generated textures. Missing linked textures produce
a filename-specific error; embed textures in Blockbench to make projects portable.
Blockbench 5 stores group data separately from the outliner; this is supported in
the geo converter as well as older inline groups. The upstream format notes are at
[Blockbench's format documentation](https://blockbench.net/wiki/docs/bbmodel/).

Static Minecraft models cannot represent meshes, animated bones, rotated groups,
or arbitrary cube rotations. These inputs raise an error instead of silently
losing geometry. Use the existing GeckoLib `geo_model` path for cuboid bone models;
textures and animation JSON still need their corresponding resource fields.

Files in `assets/<modid>/models/block/` and `models/item/` ending in `.bbmodel`
are also converted automatically. A JSON file supplied at the same source path
wins over that conversion. Dict model definitions are copied before modifications
and can be reused between loaders.

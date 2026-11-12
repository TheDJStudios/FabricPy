# Items

Items have three important tiers:

- ordinary generated items
- custom-model items
- items that carry appearance/runtime state on the stack

## Minimal Item

```python
@mod.register
class Gear(mc.Item):
    item_id = "gear"
    display_name = "Gear"
    texture = "parts/gear"
```

## Core Fields

- `item_id`
- `display_name`
- `max_stack_size`
- `max_damage`
- `rarity`
- `fireproof`
- `food_hunger`
- `food_saturation`
- `food_always_edible`
- `is_tool`
- `tool_type`
- `tool_material`
- `texture`
- `emissive_texture`
- `emissive_level`
- `textures`
- `model`

## Texture Resolution

This Python:

```python
texture = "food/pickle"
```

means:

- source PNG: `assets/<modid>/textures/item/food/pickle.png`
- generated model texture id: `<modid>:item/food/pickle`

Common mistake:

- writing `<modid>:food/pickle` in a manual item model

Correct value:

- `<modid>:item/food/pickle`

## Food Item Example

```python
@mod.register
class Pickle(mc.Item):
    item_id = "pickle"
    display_name = "Pickle"
    texture = "food/pickle"
    food_hunger = 4
    food_saturation = 6
    food_always_edible = True
```

## Custom Model Item Example

```python
@mod.register
class GrabPackCannon(mc.Item):
    item_id = "grabpack_cannon"
    display_name = "GrabPack Cannon"
    max_stack_size = 1
    rarity = "epic"
    model = {
        "parent": "playtime:item/tool/grabpack"
    }
```

## Right-Click Hook

Items support:

- `@mc.on_right_click`

```python
@mod.register
class TeleportAnchor(mc.Item):
    item_id = "teleport_anchor"
    texture = "tools/teleport_anchor"

    @mc.on_right_click
    def on_right_click(self, ctx):
        if not ctx.world.is_client():
            ctx.player.teleport(0, 80, 0)
            ctx.player.send_action_bar("Teleported")
```

## Stack Appearance Data

Stacks can store appearance keys:

- `ctx.stack.texture_change(texture_id)`
- `ctx.stack.model_change(model_id)`
- `ctx.stack.get_texture()`
- `ctx.stack.get_model()`

These helpers are useful for stateful items and future render systems, but they are not yet a guaranteed universal live item-render mutation path on their own.

## Inventories, attachments, discs and GUIs

Storage items automatically become unstackable. Define `inventory_size` from 1
through 54 for programmatic storage; `open_inventory_on_use = True` opens a
vanilla inventory GUI and requires 9, 18, 27, 36, 45 or 54 slots.
`inventory_title` optionally overrides its title.

Define `attachment_slots = ("scope", "battery")` for named slots. Installed
items retain their own data and render on the parent model; use
`attachment_models` to adjust each slot's position, rotation and scale.

- [Music discs](music-discs.md): native jukebox items and audio assets.
- [Item storage](item-storage.md): `ctx.stack.data`, inventory functions and typed contexts.
- [Visible attachments](item-attachments.md): installation, removal and model placement.
- [Item GUIs](item-guis.md): server inventories with persistent contents.
- [Screens](screens.md): labels/buttons and `open_screen_on_use`.

These item features target Minecraft 1.20.1 (Fabric, Forge, Quilt), 1.21
(Fabric), and 1.21.1 (Fabric, Forge, NeoForge). Newer versions need additional
native API adapters; unsupported storage/disc targets produce validation errors.
See `examples/item_features.py` for a complete mod using vanilla audio/textures.

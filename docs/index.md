# FabricPy Docs

This docs set is split into two layers:

- the everyday Python API you use to make content quickly
- the advanced compiler/runtime/interoperability systems that let you push past the hand-written surface

If you are new to the repo, read in this order:

1. [building.md](./building.md)
2. [mod.md](./mod.md)
3. [blocks.md](./blocks.md)
4. [items.md](./items.md)
5. [events.md](./events.md)
6. [context.md](./context.md)

If you are working on advanced systems, also read:

- [animations.md](./animations.md)
- [addons.md](./addons.md)
- [dependencies.md](./dependencies.md)
- [interop.md](./interop.md)
- [roadmap.md](./roadmap.md)
- [demo.md](./demo.md)

## Core Reference

- [building.md](./building.md): environment setup, compile flow, generated project layout, troubleshooting
- [mod.md](./mod.md): `mc.Mod`, registration, recipes, advancements, sounds, creative tabs, keybinds, dependencies, dimensions
- [blocks.md](./blocks.md): block properties, hooks, rotation, emissives, block data, animated blocks
- [items.md](./items.md): items, textures, models, emissive layers, right-click hooks, stack appearance data
- [entities.md](./entities.md): normal entities and block entities
- [networking.md](./networking.md): client/server packet handlers and send helpers
- [screens.md](./screens.md): simple client screens, labels, buttons, and open handlers
- [runtime-helpers.md](./runtime-helpers.md): math helpers, raycasts, and particles
- [render-hooks.md](./render-hooks.md): render-layer control and generated geo renderers
- [recipes.md](./recipes.md): shaped, shapeless, and raw recipe JSON
- [advancements.md](./advancements.md): advancement generation
- [creative-tabs.md](./creative-tabs.md): tab creation and tab item lists
- [keybinds.md](./keybinds.md): client keybind declarations and handlers
- [sounds.md](./sounds.md): sounds.json generation and sound asset layout
- [textures.md](./textures.md): texture path rules and generated path behavior
- [models.md](./models.md): manual models, generated models, overrides, particles, emissive overlays
- [events.md](./events.md): global event hooks
- [commands.md](./commands.md): slash commands
- [decorators.md](./decorators.md): block/item/mixin decorators
- [context.md](./context.md): `ctx` surface and all mapped helper calls

## Portable item features

- [music-discs.md](./music-discs.md): native jukebox music discs
- [item-storage.md](./item-storage.md): persistent item data and inventory functions
- [item-attachments.md](./item-attachments.md): named slots and visible models
- [item-guis.md](./item-guis.md): persistent storage GUIs
- [screens.md](./screens.md): client panels, buttons and labels

## Advanced / Compiler Reference

- [animations.md](./animations.md): GeckoLib-backed animated blocks
- [render-hooks.md](./render-hooks.md): generated renderers and render-layer behavior
- [dependencies.md](./dependencies.md): dependency declarations, generated metadata, jar scanning, stub generation
- [interop.md](./interop.md): current dependency interop architecture and limits
- [roadmap.md](./roadmap.md): where the compiler is heading
- [demo.md](./demo.md): walkthrough of the canonical `demo.py` showcase mod

## Source Layout

Repo-authored assets and data live in:

- `assets/<modid>/...`
- `data/<modid>/...`

These are copied into generated loader projects during compile. When the same path exists in both generated output and repo source, the repo file wins.

## Supported Matrix

- `1.20.1`: Fabric, Forge, Quilt
- `1.21`: Fabric
- `1.21.1`: Fabric, Forge, NeoForge
- `1.21.2` through `1.21.8`: Fabric

Loader support is now addon-backed.

- `loader="both"` resolves to Fabric plus Forge when those built-in addons exist for the selected Minecraft version
- `loader="all"` resolves to every built-in or external addon available for the selected Minecraft version
- `loader="all"` resolves to every discovered loader addon for the selected Minecraft version
- custom loader/version addons can be added under `fabricpy/addons/...`

# Context API

Every block hook, item hook, event handler, keybind handler, and command callback receives a generated `ctx` surface.

You write Python against `ctx`. The compiler maps those calls to the selected loader backend's Java APIs.

The important mental model is:

- `ctx` is not a generic Python object
- `ctx` is a compiler surface
- some values are available only in certain hooks/events

## IDE autocomplete with context annotations

Annotate the callback parameter with its hook's context type. For example:

```python
import fabricpy as mc

@mod.register
class Bell(mc.Block):
    block_id = "bell"

    @mc.on_use
    def interact(self, ctx: mc.BlockUseContext) -> None:
        ctx.player.send_message("dong")
```

Typing `ctx.` or `ctx.player.` now offers the appropriate fields and methods in
IDEs that support Python type hints. The installed package includes `py.typed`;
no separate stub package is needed. These are `typing.Protocol` definitions for
annotations, not objects to instantiate or a runtime context manager. Adding an
annotation does not change the generated Java or create a Python runtime context.
Use positional arguments for helper calls.

| Decorator / callback | Context annotation |
| --- | --- |
| Block `@mc.on_use` | `ctx: mc.BlockUseContext` |
| Block `@mc.on_place` | `ctx: mc.BlockPlaceContext` |
| Block `@mc.on_break` | `ctx: mc.BlockBreakContext` |
| Item `@mc.on_right_click` | `ctx: mc.ItemUseContext` |
| Block `@mc.on_tick` | `ctx: mc.BlockTickContext` |
| Entity `@mc.on_tick` | `ctx: mc.EntityTickContext` |

A placement's `ctx.player` can be `None`, since its placer may not be a player:

```python
@mc.on_place
def placed(self, ctx: mc.BlockPlaceContext) -> None:
    if ctx.player is not None:
        ctx.player.send_message("Placed")
```

For blocks with a generated block entity, use `mc.BlockEntityUseContext`,
`mc.BlockEntityPlaceContext`, or `mc.BlockEntityBreakContext` to also complete
`ctx.block_entity`. Persistent data helpers require `uses_block_data = True`;
animation helpers require the appropriate GeckoLib resources.

```python
@mod.register
class Counter(mc.Block):
    block_id = "counter"
    uses_block_data = True

    @mc.on_use
    def interact(self, ctx: mc.BlockEntityUseContext) -> None:
        count = ctx.block_entity.get_int("uses")
        ctx.block_entity.set_int("uses", count + 1)
        ctx.block_entity.sync()
```

The context types reflect hook availability: item-use contexts have no block
position, placement contexts have no hand/stack, and entity ticks have no player.
`ctx.state` and raycast hit results remain opaque because their Java types vary
by backend. The types do not validate arbitrary raw Java calls or every optional
feature. Event, packet, screen, keybind, command and mixin callback contexts are
not yet covered by these hook-specific annotations.

## Major Context Areas

- `ctx.player`
- `ctx.world`
- `ctx.stack`
- `ctx.block_entity`
- `ctx.entity`
- `ctx.server`
- `ctx.source`
- `ctx.client`
- `ctx.net`
- `ctx.math`
- raw values such as `ctx.pos`, `ctx.state`, `ctx.hand`, `ctx.message`

## Player Helpers

- `ctx.player.send_message(text)`
- `ctx.player.send_action_bar(text)`
- `ctx.player.teleport(x, y, z)`
- `ctx.player.teleport_dimension(dimension_id, x, y, z)`
- `ctx.player.give_item(item_id, count)`
- `ctx.player.remove_item(item_id, count)`
- `ctx.player.get_health()`
- `ctx.player.set_health(value)`
- `ctx.player.heal(amount)`
- `ctx.player.damage(amount)`
- `ctx.player.add_effect(effect_id, seconds, amplifier)`
- `ctx.player.remove_effect(effect_id)`
- `ctx.player.clear_effects()`
- `ctx.player.get_hunger()`
- `ctx.player.set_hunger(value)`
- `ctx.player.get_saturation()`
- `ctx.player.set_saturation(value)`
- `ctx.player.add_experience(amount)`
- `ctx.player.kill()`
- `ctx.player.get_name()`
- `ctx.player.is_creative()`
- `ctx.player.is_sneaking()`
- `ctx.player.is_sprinting()`
- `ctx.player.set_on_fire(seconds)`
- `ctx.player.get_pos_x()`
- `ctx.player.get_pos_y()`
- `ctx.player.get_pos_z()`
- `ctx.player.get_main_hand_item_id()`
- `ctx.player.get_main_hand_count()`
- `ctx.player.get_offhand_item_id()`
- `ctx.player.get_offhand_count()`
- `ctx.player.consume_main_hand_item(count)`
- `ctx.player.set_main_hand_item(item_id, count)`
- `ctx.player.has_item(item_id)`
- `ctx.player.count_item(item_id)`
- `ctx.player.has_advancement(advancement_id)`
- `ctx.player.has_advancment(advancement_id)`
- `ctx.player.add_cooldown(item_id, ticks)`

Example:

```python
@mod.event("player_join")
def on_join(ctx):
    ctx.player.give_item("minecraft:bread", 4)
    ctx.player.add_effect("minecraft:speed", 15, 0)
    ctx.player.send_message("Starter kit granted")
```

Advancement checks expect a full advancement id in `namespace:path` form:

```python
@mod.event("player_tick")
def story_check(ctx):
    if ctx.player.has_advancement("minecraft:story/mine_stone"):
        ctx.player.send_action_bar("Stone Age complete")
```

`ctx.player.has_advancment(...)` is accepted as a compatibility alias for the misspelling, but `has_advancement(...)` is the preferred spelling.

## World Helpers

- `ctx.world.is_client()`
- `ctx.world.play_sound(sound_id, volume, pitch)`
- `ctx.world.explode(x, y, z, power)`
- `ctx.world.set_block(x, y, z, block_id)`
- `ctx.world.set_block_self(block_id)`
- `ctx.world.break_block(x, y, z, drop)`
- `ctx.world.break_self(drop)`
- `ctx.world.get_block_id(x, y, z)`
- `ctx.world.get_self_block_id()`
- `ctx.world.is_air(x, y, z)`
- `ctx.world.is_self_air()`
- `ctx.world.get_time()`
- `ctx.world.is_day()`
- `ctx.world.is_raining()`
- `ctx.world.get_dimension()`
- `ctx.world.spawn_lightning()` (Fabric-specific; not part of the portable typed surface)
- `ctx.world.spawn_entity(entity_id, x, y, z)`
- `ctx.world.set_block_in_dimension(dimension_id, x, y, z, block_id)`
- `ctx.world.fill_in_dimension(dimension_id, x1, y1, z1, x2, y2, z2, block_id, mode)`
- `ctx.world.place_structure(dimension_id, structure_id, x, y, z)`
- `ctx.world.place_nbt(dimension_id, structure_id, x, y, z)`
- `ctx.world.spawn_particle(particle_id, x, y, z, dx, dy, dz, speed, count)`
- `ctx.world.spawn_particle_self(particle_id, dx, dy, dz, speed, count)`
- `ctx.world.raycast_block(start_vec, end_vec)`
- `ctx.world.raycast_block_id(start_vec, end_vec)`
- `ctx.world.raycast_block_pos_x(start_vec, end_vec)`
- `ctx.world.raycast_block_pos_y(start_vec, end_vec)`
- `ctx.world.raycast_block_pos_z(start_vec, end_vec)`

## Hand Helpers

- `ctx.hand.is_main_hand()`
- `ctx.hand.is_off_hand()`

Interaction events can represent distinct hand attempts. If only main-hand
attempts matter, explicitly check `ctx.hand.is_main_hand()` rather than treating
all offhand interactions as duplicates.

## Stack Helpers

- `ctx.stack.get_item_id()`
- `ctx.stack.get_count()`
- `ctx.stack.decrement(count)`
- `ctx.stack.increment(count)`
- `ctx.stack.is_of(item_id)`
- `ctx.stack.get_texture()`
- `ctx.stack.texture_change(texture_id)`
- `ctx.stack.get_model()`
- `ctx.stack.model_change(model_id)`

## Block Entity Helpers

- `ctx.block_entity.mark_dirty()`
- `ctx.block_entity.get_string(key)`
- `ctx.block_entity.set_string(key, value)`
- `ctx.block_entity.get_int(key)`
- `ctx.block_entity.set_int(key, value)`
- `ctx.block_entity.get_bool(key)`
- `ctx.block_entity.set_bool(key, value)`
- `ctx.block_entity.get_double(key)`
- `ctx.block_entity.set_double(key, value)`
- `ctx.block_entity.has(key)`
- `ctx.block_entity.remove(key)`
- `ctx.block_entity.sync()`
- `ctx.block_entity.get_texture()`
- `ctx.block_entity.texture_change(texture_id)`
- `ctx.block_entity.get_model()`
- `ctx.block_entity.model_change(model_id)`
- `ctx.block_entity.get_animation()`
- `ctx.block_entity.play_animation(name)`
- `ctx.block_entity.play_animation_once(name)`
- `ctx.block_entity.stop_animation()`

Example:

```python
@mc.on_use
def on_use(self, ctx):
    count = ctx.block_entity.get_int("uses")
    ctx.block_entity.set_int("uses", count + 1)
    ctx.block_entity.set_bool("powered", True)
    ctx.block_entity.play_animation_once("controller.scan")
    ctx.block_entity.sync()
```

## Entity, Server, and Source Helpers

Entity:

- `ctx.entity.get_pos_x()`
- `ctx.entity.get_pos_y()`
- `ctx.entity.get_pos_z()`
- `ctx.entity.teleport(x, y, z)`
- `ctx.entity.discard()`
- `ctx.entity.set_on_fire(seconds)`
- `ctx.entity.damage(amount)`
- `ctx.entity.get_animation()`
- `ctx.entity.play_animation(name)`
- `ctx.entity.play_animation_once(name)`
- `ctx.entity.stop_animation()`
- `ctx.entity.get_texture()`
- `ctx.entity.texture_change(resource_id)`
- `ctx.entity.get_model()`
- `ctx.entity.model_change(resource_id)`

Server:

- `ctx.server.run_command(command)`
- `ctx.server.reload_data()`

Client:

- `ctx.client.open_screen(screen_id)`
- `ctx.client.close_screen()`

Networking:

- `ctx.net.send_to_server(packet_id, message)`
- `ctx.net.send_to_player(player, packet_id, message)`
- `ctx.net.broadcast(packet_id, message)`

Math:

- `ctx.math.vec3(x, y, z)`
- `ctx.math.block_pos(x, y, z)`
- `ctx.math.clamp(value, min, max)`
- `ctx.math.lerp(start, end, delta)`
- `ctx.math.distance3(x1, y1, z1, x2, y2, z2)`
- `ctx.math.length3(x, y, z)`
- `ctx.math.normalize3(x, y, z)`
- `ctx.math.add3(x1, y1, z1, x2, y2, z2)`

Command source:

- `ctx.source.send_message(text)`
- `ctx.source.get_player()`
- `ctx.source.get_pos()`
- `ctx.source.run_command(command)`

## Availability Rules

Typical patterns:

- block hooks: `ctx.world`, `ctx.pos`, `ctx.state`, sometimes `ctx.hand`, `ctx.stack`, `ctx.player`, `ctx.block_entity`
- item right-click hooks: `ctx.player`, `ctx.world`, `ctx.hand`, `ctx.stack`
- player events: `ctx.player`
- chat events: `ctx.player`, `ctx.message`
- block-break events: `ctx.player`, `ctx.world`, `ctx.pos`, `ctx.state`
- entity events: `ctx.entity`
- server lifecycle events: `ctx.server`
- commands: `ctx.source`
- keybinds: `ctx.client`, `ctx.keybind`, and often `ctx.player`

## Advanced Interop Note

For advanced cases, `ctx` values are also emitted as real Java objects in generated source. That means advanced direct calls can be expressed when you know the loader-side API names.

See [interop.md](./interop.md) for the dependency side of that system.

## Typed item storage helpers

Use `ctx: mc.ItemUseContext` in item-use callbacks for IDE completion on
`ctx.stack.data`, `ctx.stack.inventory` and `ctx.stack.attachments`.
See [persistent item storage](item-storage.md) for their methods and
[visible attachments](item-attachments.md) for model transforms.

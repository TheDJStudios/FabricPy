# Decorators

`fabricpy` exposes these decorators at the top level:

- `@mc.on_use`
- `@mc.on_right_click`
- `@mc.on_place`
- `@mc.on_break`
- `@mc.on_tick`
- `@mc.inject(...)`

Block hook decorators:

- `@mc.on_use`: block right click
- `@mc.on_place`: block placement hook
- `@mc.on_break`: block break hook
- `@mc.on_tick`: per-tick block hook when the block has a generated block entity

Item hook decorators:

- `@mc.on_right_click`: item use hook

Entity hook decorators:

- `@mc.on_tick`: normal entity tick hook when used on an `mc.Entity` subclass

Mixin decorator:

- `@mc.inject(method, at="HEAD", cancellable=False)`

## Typed callback examples

The class after `ctx:` supplies IDE autocomplete; use the type matching the
decorator and the content class. These are annotation-only protocols, not runtime
context managers. `import fabricpy as mc` exposes each type directly.

```python
@mod.register
class Bell(mc.Block):
    block_id = "bell"

    @mc.on_use
    def interact(self, ctx: mc.BlockUseContext) -> None:
        ctx.player.send_message("dong")

    @mc.on_place
    def placed(self, ctx: mc.BlockPlaceContext) -> None:
        if ctx.player is not None:
            ctx.player.send_message("Placed")

    @mc.on_break
    def broken(self, ctx: mc.BlockBreakContext) -> None:
        ctx.player.send_message("Broken")
```

```python
@mod.register
class BeaconWand(mc.Item):
    item_id = "beacon_wand"

    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext) -> None:
        ctx.player.send_action_bar("wand used")
```

```python
@mod.register
class Counter(mc.Block):
    block_id = "counter"
    uses_block_data = True

    @mc.on_tick
    def tick(self, ctx: mc.BlockTickContext) -> None:
        count = ctx.block_entity.get_int("ticks")
        ctx.block_entity.set_int("ticks", count + 1)

@mod.register
class Sentinel(mc.Entity):
    entity_id = "sentinel"

    @mc.on_tick
    def tick(self, ctx: mc.EntityTickContext) -> None:
        if ctx.entity.get_pos_y() < 0:
            ctx.entity.discard()
```

For a block entity's use/place/break callbacks, use
`mc.BlockEntityUseContext`, `mc.BlockEntityPlaceContext`, or
`mc.BlockEntityBreakContext` to include `ctx.block_entity` autocomplete. Data and
animation helpers still require their corresponding block configuration.
See [context.md](./context.md) for availability and the helper methods.

## Logical sides

`on_use`, `on_right_click`, `on_place`, and `on_break` run Python hook logic on the
logical **server** by default. Minecraft also invokes many Java hooks on the
logical client, even in single-player; executing the same Python effects on both
sides caused duplicate messages and actions in earlier versions.

Use an explicit side for client-only effects or intentional execution on both:

```python
@mc.on_use(side="client")
def client_interaction(self, ctx: mc.BlockUseContext) -> None:
    ctx.player.send_action_bar("Local effect")
```

The options are `side="server"`, `side="client"`, and `side="both"`.
Existing bare decorators such as `@mc.on_place` now mean `side="server"`.
If an older callback checks `ctx.world.is_client()` internally, choose the matching
explicit side or `side="both"` when migrating it. Vanilla Java lifecycle calls
and interaction results are preserved; the side option controls the Python body.
`@mc.on_tick` keeps its existing side behavior and does not accept this option;
check `ctx.world.is_client()` inside tick callbacks when separating logic.

Global interaction handlers also accept the side option, for example
`@mod.event("player_use_block", side="server")`. Hand attempts remain distinct;
use `ctx.hand.is_main_hand()` when a handler should only observe the main hand.

# Persistent item data, inventories, and attachments

Each `ctx.stack` represents the actual held item stack. Data and contents travel
with that stack when it moves between inventories, drops into the world, or is
saved and reloaded. Helpers operate on copied contents internally and preserve
stack NBT/components, including names, enchantments and custom item data.

## Persistent values

```python
@mod.register
class CounterWand(mc.Item):
    item_id = "counter_wand"

    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext) -> None:
        uses = ctx.stack.data.get_int("uses")
        ctx.stack.data.set_int("uses", uses + 1)
        ctx.player.send_action_bar(f"Uses: {uses + 1}")
```

The data API works on ordinary items; it does not require an inventory:

| Operation | Result |
| --- | --- |
| `get_string(key)` / `set_string(key, value)` | String value; missing keys read as `""` |
| `get_int(key)` / `set_int(key, value)` | Integer value; missing keys read as `0` |
| `get_bool(key)` / `set_bool(key, value)` | Boolean value; missing keys read as `False` |
| `get_float(key)` / `set_float(key, value)` | Finite decimal value; missing keys read as `0.0` |
| `contains(key)` | Whether a value is stored under that key |
| `remove(key)` | Remove that value |

Keys must contain 1–256 characters. Data belongs to the stack, so all items in an
ordinary stack share its values. Stacks with different data do not merge through
normal Minecraft stacking rules.

## Item inventories

```python
@mod.register
class ToolBag(mc.Item):
    item_id = "tool_bag"
    inventory_size = 9
    inventory_title = "Tool Bag"
    open_inventory_on_use = True
```

`inventory_size` configures fixed slots, each respecting the stored item's normal
maximum stack size. This is a slot inventory, rather than vanilla bundle weight
accounting. Storage items become unstackable automatically. Explicitly setting
another `max_stack_size` is an error.

The inventory has 1–54 slots. An automatic chest-style GUI requires a multiple of
9 slots. Its backing contents are written to the held stack; the owner item is
locked while its menu is open. Set `open_inventory_on_use = True` for the automatic
menu, or call `ctx.stack.inventory.open()` from a typed item-use callback.

```python
@mc.on_right_click
def use(self, ctx: mc.ItemUseContext) -> None:
    if ctx.player.is_sneaking():
        moved = ctx.stack.inventory.insert_from_hand("off_hand", 64)
        ctx.player.send_action_bar(f"Stored {moved} items")
    else:
        ctx.stack.inventory.open()
```

Transfer methods move real stacks on the server. They do not create items from
IDs. `"main_hand"` and `"off_hand"` select the source hand; inserting the storage
item into itself is rejected. Extraction gives the item to the player, or drops
it if the player's inventory cannot accept it.

| Inventory helper | Result |
| --- | --- |
| `size()` | Configured number of slots |
| `get_item_id(slot)` | Item ID in that slot, or `""` when empty |
| `get_count(slot)` | Number of items in that slot |
| `count(item_id)` | Total matching item count across slots, regardless of metadata |
| `contains(item_id, count)` | Whether at least that many matching items are stored |
| `space(item_id)` | Remaining capacity for an **unmodified** stack of that item ID |
| `insert_from_hand(hand_name, count)` | Actual number moved from the selected hand |
| `extract_to_player(slot, count)` | Actual number removed and returned to the player |
| `open()` | Whether opening the server-backed inventory menu succeeded |

Slots are zero-based. Invalid indices and unknown item IDs are rejected. Insertions
first merge with metadata-compatible stacks and then use empty slots. A partial
insertion consumes only the moved quantity. For example, an enchanted stack does
not merge into a plain stack just because their item IDs match.

## Named attachment slots

```python
@mod.register
class Scanner(mc.Item):
    item_id = "scanner"
    attachment_slots = ("lens", "power_core")

    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext) -> None:
        if ctx.player.is_sneaking():
            ctx.stack.attachments.remove_to_player("lens")
        else:
            installed = ctx.stack.attachments.install_from_hand("lens", "off_hand")
            if installed:
                ctx.player.send_message("Lens installed")
```

Each named slot holds one real item. Installation consumes exactly one item from
the chosen hand and retains that item's metadata. Installing into an occupied
slot fails without consuming or replacing anything. Remove the existing attachment
first; `remove_to_player` returns it to the player, dropping it if necessary.

| Attachment helper | Result |
| --- | --- |
| `get_item_id(name)` | Attached item ID, or `""` when empty |
| `has(name)` | Whether the slot is occupied |
| `install_from_hand(name, hand_name)` | Whether one item was installed |
| `remove_to_player(name)` | Whether an existing attachment was removed and returned |

Names must match declared `attachment_slots`. Slot declarations describe their
names; they do not impose item-type filters. Attachment storage is independent of
the normal inventory and survives inventory saves. Ordinary item models can be
used as visible attachments through `attachment_models`; see the item-rendering
configuration for placement, rotation and scale.

## Nesting, sides, and supported targets

Configured inventory/attachment items cannot be stored in another such item or
attached to one. Vanilla bundles, non-nestable items such as shulker boxes, and
stacks carrying recognized container contents are also rejected. Unknown third
party container implementations may require their own compatibility checks.

Use server-side item callbacks for changes. The default `@mc.on_right_click`
side is already `"server"`; selecting `side="client"` does not make a client's
local state authoritative. Hand/player transfer wrappers verify the owner is
actually held by that player on the server.

The feature currently targets Minecraft 1.20.1, 1.21 and 1.21.1. Legacy targets
serialize whole stacks as NBT; modern targets use `CUSTOM_DATA` and the vanilla
container component. It does not store Python objects or run Python inside the
game. The context type `mc.ItemUseContext` provides autocomplete for
`ctx.stack.data`, `ctx.stack.inventory`, and `ctx.stack.attachments`.

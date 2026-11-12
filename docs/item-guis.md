# Item inventories and GUIs

Use an item inventory menu when players should move real item stacks into and out
of an item. These menus use Minecraft's ordinary chest GUI and slot networking,
with the server owning the contents. The inventory is stored on the held item and
moves with that item when it is traded, dropped, or saved.

## A right-click backpack

```python
import fabricpy as mc

mod = mc.Mod("example", "Example", minecraft_version="1.20.1", loader="all")

@mod.register
class Backpack(mc.Item):
    item_id = "backpack"
    texture = "backpack"
    inventory_size = 27
    inventory_title = "Backpack"
    open_inventory_on_use = True
```

The menu has three rows of storage plus the player's main inventory and hotbar.
GUI sizes are 9, 18, 27, 36, 45, or 54 slots. The contents preserve full stacks,
including their existing item data. Inventory-bearing items must be unstackable.
See [item-storage.md](./item-storage.md) for the storage and attachment APIs.

## Open from a callback

For custom conditions, leave `open_inventory_on_use` disabled and open explicitly
from the item's server-side use hook:

```python
@mod.register
class Backpack(mc.Item):
    item_id = "backpack"
    inventory_size = 27
    inventory_title = "Backpack"

    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext):
        ctx.stack.inventory.open()
```

The item must actually be held by that player. The helper runs on the server and
uses the item's configured size and title. Client keybind/screen handlers should
request server actions through the packet API rather than mutate inventory data
on the client. Automatic opening and explicit opening are alternative workflows;
use one of them for a given click.

## Inventory behavior

- Normal clicks, shift-click transfers and drag distribution use vanilla slots.
- The item containing the inventory is locked while its menu is open, including
  hotbar number-key swaps, offhand swaps, drops, and shift-clicking that item.
- If the player changes the held item, changes the selected hotbar slot, drops the
  owner, dies or disconnects, the old menu cannot keep changing that item's data.
- Writes happen during transactions, so closing does not copy an old snapshot
  over a different item. Runtime inventory-function changes are refreshed into
  the menu before the next transaction and synchronization tick.
- FabricPy storage/attachment items cannot be nested inside storage. This keeps
  recursive containers and self-insertion out of the persistence format.

The menu uses a vanilla generic chest type, so it works without a custom network
packet or custom client renderer on Fabric, Quilt, Forge and NeoForge. It does
not add custom textures, custom slot layouts, or attachment-specific visual slots.
Named attachments remain available through their item-storage functions.

## Other custom screens

`mod.screen(...)` remains the lightweight GUI API for panels, labels and buttons:

```python
panel = mod.screen("controls", "Controls", width=220, height=160)
panel.label("Machine controls", 20, 40)
button = panel.button.add("ping", "Ping", 20, 70, 100, 20)

@button.on_click
def ping(ctx):
    ctx.net.send_to_server("ping", "pressed")
```

These client screens are different from the server-backed item menu above. Use
[screen buttons](./screens.md) for controls and [packets](./networking.md) for
server actions; use an item inventory menu for moving actual stacks.

"""Portable music disc, visible attachment, storage and client panel example.

    python -m fabricpy build examples/item_features.py --loader all --minecraft-version 1.20.1
    python -m fabricpy build examples/item_features.py --loader neoforge --minecraft-version 1.21.1

Uses vanilla models/audio, so no extra assets are required. Attach a held
upgrade by putting it in your off hand and right-clicking the Tool in your main
hand. Sneak-right-click removes it. Backpack opens a persistent inventory.
Pocket stores offhand items on use and extracts slot zero when sneaking.
"""
import fabricpy as mc

mod = mc.Mod("item_features", "Python Item Features")


@mod.register
class CatDisc(mc.MusicDisc):
    item_id = "cat_disc"
    display_name = "Python Cat Disc"
    sound = "minecraft:music_disc.cat"
    length_seconds = 185
    comparator_output = 3
    artist = "C418"
    title = "Cat"
    model = {"parent": "minecraft:item/generated", "textures": {"layer0": "minecraft:item/music_disc_cat"}}


@mod.register
class Backpack(mc.Item):
    item_id = "backpack"
    display_name = "Python Backpack"
    inventory_size = 27
    inventory_title = "Backpack"
    open_inventory_on_use = True
    model = {"parent": "minecraft:item/generated", "textures": {"layer0": "minecraft:item/bundle"}}


@mod.register
class Pocket(mc.Item):
    item_id = "pocket"
    display_name = "Python Pocket"
    inventory_size = 9
    model = {"parent": "minecraft:item/generated", "textures": {"layer0": "minecraft:item/leather"}}

    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext):
        uses = ctx.stack.data.get_int("uses")
        ctx.stack.data.set_int("uses", uses + 1)
        if ctx.player.is_sneaking():
            moved = ctx.stack.inventory.extract_to_player(0, 64)
        else:
            moved = ctx.stack.inventory.insert_from_hand("off_hand", 64)
        ctx.player.send_action_bar(f"Moved {moved} items")


@mod.register
class Tool(mc.Item):
    item_id = "tool"
    display_name = "Tool with Upgrade"
    attachment_slots = ("upgrade",)
    attachment_models = {"upgrade": {"position": [0, 0.35, 0], "scale": [0.4, 0.4, 0.4]}}
    model = {"parent": "minecraft:item/handheld", "textures": {"layer0": "minecraft:item/iron_pickaxe"}}

    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext):
        if ctx.player.is_sneaking():
            ctx.stack.attachments.remove_to_player("upgrade")
        else:
            ctx.stack.attachments.install_from_hand("upgrade", "off_hand")


panel = mod.screen("help", "Python Mod Help", width=220, height=160)
panel.label("Python items, native Minecraft GUIs", 10, 40, 0x55FFFF)
close = panel.button.add("close", "Close", 10, 70, 100, 20)


@close.on_click
def close_panel(ctx):
    ctx.client.close_screen()


@mod.register
class Guide(mc.Item):
    item_id = "guide"
    display_name = "Python Guide"
    open_screen_on_use = "help"
    model = {"parent": "minecraft:item/generated", "textures": {"layer0": "minecraft:item/book"}}

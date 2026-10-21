"""
fabricpy — Write Minecraft mods in Python using pluggable loader backends.

Usage:
    import fabricpy as mc

    mod = mc.Mod(mod_id="mymod", name="My Mod", version="1.0.0")

    class CoolBlock(mc.Block):
        block_id = "cool_block"
        display_name = "Cool Block"
        hardness = 2.0

        @mc.on_use
        def on_use(self, ctx):
            ctx.player.send_message("Hello!")

    mod.register(CoolBlock)

    if __name__ == "__main__":
        mod.compile()
"""

from fabricpy.mod import Mod
from fabricpy.block import Block
from fabricpy.item import Item
from fabricpy.entity import Entity
from fabricpy.addons import list_addons
from fabricpy.mixin import Mixin
from fabricpy.decorators import on_use, on_right_click, on_place, on_break, on_tick, inject

__all__ = [
    "Mod",
    "Block",
    "Item",
    "Entity",
    "list_addons",
    "Mixin",
    "on_use",
    "on_right_click",
    "on_place",
    "on_break",
    "on_tick",
    "inject",
]

__version__ = "0.1.0"

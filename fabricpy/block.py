"""
Block base class. Subclass this to create a custom block.

Class attributes (all optional except block_id):
    block_id        str     Registry ID, e.g. "cool_block"         (required)
    display_name    str     In-game display name                    (default: title-cased block_id)
    hardness        float   Mining hardness (-1 = unbreakable)      (default: 1.5)
    resistance      float   Blast resistance                        (default: 6.0)
    luminance       int     Light level emitted (0-15)              (default: 0)
    slipperiness    float   Ice-like slipperiness (0.6-0.98)        (default: 0.6)
    sound_group     str     Sound type: "stone","wood","sand","wool","metal","glass","grass" (default: "stone")
    material        str     Block material hint for properties      (default: "stone")
    requires_tool   bool    Only drops if mined with correct tool   (default: False)
    drops_self      bool    Drops itself when broken               (default: True)
    has_block_entity bool   Whether this block has a block entity   (default: False; required for on_tick)
    uses_block_data bool    Whether this block needs persistent generated block data (default: False)
    opaque          bool    Whether the block is fully opaque       (default: True)
    collidable      bool    Whether players can walk through it     (default: True)
    variable_rotation bool  Whether compiler generates north-based facing rotation (default: False)
    rotation_mode   str     "wall" or "floor" rotation handling for a north-authored model (default: "wall")
    model_collision bool    Whether collisions use model cuboids    (default: False)
    render_layer    str     "solid","cutout","cutout_mipped","translucent" (default: "solid")
    render_scale_x  float   Renderer X scale for geo blocks         (default: 1.0)
    render_scale_y  float   Renderer Y scale for geo blocks         (default: 1.0)
    render_scale_z  float   Renderer Z scale for geo blocks         (default: 1.0)
    render_offset_x float   Renderer X offset for geo blocks        (default: 0.0)
    render_offset_y float   Renderer Y offset for geo blocks        (default: 0.0)
    render_offset_z float   Renderer Z offset for geo blocks        (default: 0.0)
    render_tint_r   float   Renderer tint red channel 0-1           (default: 1.0)
    render_tint_g   float   Renderer tint green channel 0-1         (default: 1.0)
    render_tint_b   float   Renderer tint blue channel 0-1          (default: 1.0)
    render_tint_a   float   Renderer tint alpha channel 0-1         (default: 1.0)
    geo_model       str     Optional GeckoLib geo model path        (default: "")
    geo_texture     str     Optional GeckoLib texture path          (default: "")
    geo_animations  str     Optional GeckoLib animation path        (default: "")
    default_animation str   Optional default GeckoLib animation     (default: "")

Hook decorators (import from fabricpy):
    @mc.on_use       — player right-clicks the block
    @mc.on_place     — block is placed
    @mc.on_break     — block is broken
    @mc.on_tick      — game tick (requires has_block_entity=True)
"""

import inspect
from fabricpy.decorators import on_use, on_place, on_break, on_tick


class BlockMeta(type):
    """Metaclass that collects hook methods."""
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        hooks = {}
        for base in reversed(cls.__mro__[1:]):
            hooks.update(getattr(base, "_hooks", {}))
        hooks = {kind: hook for kind, hook in hooks.items() if hook.__name__ not in namespace}
        for attr_name, val in namespace.items():
            if callable(val) and hasattr(val, "_fabricpy_hook"):
                hooks[val._fabricpy_hook] = val
        cls._hooks = hooks
        return cls


class Block(metaclass=BlockMeta):
    # ---- Registry ----
    block_id: str = ""                  # REQUIRED: e.g. "cool_block"
    display_name: str = ""              # Defaults to title-cased block_id
    namespace: str = ""                 # Set automatically from mod_id

    # ---- Physics / Material ----
    hardness: float = 1.5
    resistance: float = 6.0
    luminance: int = 0
    slipperiness: float = 0.6
    material: str = "stone"
    sound_group: str = "stone"

    # ---- Behavior ----
    requires_tool: bool = False
    drops_self: bool = True
    has_block_entity: bool = False
    uses_block_data: bool = False
    opaque: bool = True
    collidable: bool = True
    variable_rotation: bool = False
    rotation_mode: str = "wall"
    model_collision: bool = False
    render_layer: str = "solid"
    render_scale_x: float = 1.0
    render_scale_y: float = 1.0
    render_scale_z: float = 1.0
    render_offset_x: float = 0.0
    render_offset_y: float = 0.0
    render_offset_z: float = 0.0
    render_tint_r: float = 1.0
    render_tint_g: float = 1.0
    render_tint_b: float = 1.0
    render_tint_a: float = 1.0
    geo_model: str = ""
    geo_texture: str = ""
    geo_animations: str = ""
    default_animation: str = ""

    # ---- Assets ----
    texture: str = ""                   # Shortcut for cube_all texture
    emissive_texture: str = ""          # Optional overlay texture for emissive parts
    emissive_level: int = 0             # 1-255 authoring value, mapped to block light/render hints
    textures: dict = {}                 # Full block model texture map override
    emissive_textures: dict = {}        # Full emissive overlay texture map override
    model: dict | str | None = None           # Full block model JSON override
    emissive_model: dict | str | None = None  # Full emissive overlay block model JSON override
    wall_model: str = ""                # Optional model id/path override for wall rotation variants
    floor_model: str = ""               # Optional model id/path override for floor rotation variants
    blockstate: dict | None = None      # Full blockstate JSON override
    item_model: dict | str | None = None      # Full block item model JSON override

    # ---- Internal ----
    _hooks: dict = {}  # populated by BlockMeta

    @classmethod
    def get_hooks(cls) -> dict:
        """Return dict of {hook_type: method} for this block."""
        return cls._hooks

    @classmethod
    def get_class_name(cls) -> str:
        return cls.__name__

    @classmethod
    def get_display_name(cls) -> str:
        if cls.display_name:
            return cls.display_name
        return cls.block_id.replace("_", " ").title()

    @classmethod
    def get_full_id(cls) -> str:
        ns = cls.namespace or "modid"
        return f"{ns}:{cls.block_id}"

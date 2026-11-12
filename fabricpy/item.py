"""
Item base class. Subclass this to create a custom item.

Class attributes:
    item_id             str     Registry ID, e.g. "sonic_screwdriver"  (required)
    display_name        str     In-game display name                    (default: title-cased item_id)
    max_stack_size      int     Max stack size (1–64)                   (default: 64)
    max_damage          int     Durability (0 = unbreakable)            (default: 0)
    rarity              str     "common","uncommon","rare","epic"        (default: "common")
    fireproof           bool    Survives lava/fire                      (default: False)
    food_hunger         int     Hunger restored if food (0 = not food)  (default: 0)
    food_saturation     float   Saturation if food                      (default: 0.0)
    food_always_edible  bool    Edible even when not hungry             (default: False)
    is_tool             bool    Treat as a tool item                    (default: False)
    tool_type           str     "sword","pickaxe","axe","shovel","hoe"  (default: "")
    tool_material       str     "wood","stone","iron","gold","diamond","netherite" (default: "iron")

Hook decorators:
    @mc.on_right_click  — player right-clicks with the item
    @mc.on_tick         — item tick (advanced, requires block entity or entity)
"""


class ItemMeta(type):
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


class Item(metaclass=ItemMeta):
    # ---- Registry ----
    item_id: str = ""
    display_name: str = ""
    namespace: str = ""

    # ---- Stack / Durability ----
    max_stack_size: int = 64
    max_damage: int = 0
    rarity: str = "common"

    # ---- Survival ----
    fireproof: bool = False

    # ---- Food ----
    food_hunger: int = 0
    food_saturation: float = 0.0
    food_always_edible: bool = False

    # ---- Tool ----
    is_tool: bool = False
    tool_type: str = ""
    tool_material: str = "iron"

    # ---- Persistent item storage ----
    inventory_size: int = 0             # Fixed slots; GUI uses multiples of 9 up to 54
    inventory_title: str = ""           # Defaults to the translated item name
    open_inventory_on_use: bool = False
    open_screen_on_use: str = ""        # Client panel ID from mod.screen(...)
    attachment_slots: tuple[str, ...] = ()
    attachment_models: dict = {}        # Slot -> position/rotation/scale lists

    # ---- Assets ----
    texture: str = ""                   # Shortcut for generated item layer0
    emissive_texture: str = ""          # Optional overlay texture for emissive parts
    emissive_level: int = 0             # 1-255 authoring value, currently advisory for item overlays
    textures: dict = {}                 # Full item model texture map override
    model: dict | str | None = None           # Full item model JSON override

    # ---- Internal ----
    _hooks: dict = {}

    @classmethod
    def get_hooks(cls) -> dict:
        return cls._hooks

    @classmethod
    def get_class_name(cls) -> str:
        return cls.__name__

    @classmethod
    def get_display_name(cls) -> str:
        if cls.display_name:
            return cls.display_name
        return cls.item_id.replace("_", " ").title()

    @classmethod
    def get_full_id(cls) -> str:
        ns = cls.namespace or "modid"
        return f"{ns}:{cls.item_id}"

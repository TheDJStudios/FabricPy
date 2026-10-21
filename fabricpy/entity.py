"""
Entity base class. Subclass this to create a custom non-block entity.

This API now covers registration, ticking, basic size/category metadata,
and an optional GeckoLib-backed renderer/animation path.
"""

from fabricpy.decorators import on_tick


class EntityMeta(type):
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        hooks = {}
        for base in reversed(cls.__mro__[1:]):
            hooks.update(getattr(base, "_hooks", {}))
        hooks = {kind: hook for kind, hook in hooks.items() if hook.__name__ not in namespace}
        for _, val in namespace.items():
            if callable(val) and hasattr(val, "_fabricpy_hook"):
                hooks[val._fabricpy_hook] = val
        cls._hooks = hooks
        return cls


class Entity(metaclass=EntityMeta):
    entity_id: str = ""
    display_name: str = ""
    namespace: str = ""

    width: float = 0.6
    height: float = 1.8
    tracking_range: int = 8
    update_rate: int = 3
    spawn_group: str = "misc"
    fireproof: bool = False
    summonable: bool = True
    max_health: float = 20.0
    movement_speed: float = 0.25
    attack_damage: float = 2.0
    follow_range: float = 16.0
    knockback_resistance: float = 0.0
    render_layer: str = "solid"
    shadow_radius: float = 0.5
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
        return cls.entity_id.replace("_", " ").title()

    @classmethod
    def get_full_id(cls) -> str:
        ns = cls.namespace or "modid"
        return f"{ns}:{cls.entity_id}"

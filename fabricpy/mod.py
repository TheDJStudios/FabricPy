"""
Mod — the central object you configure and call .compile() on.

Usage:
    mod = mc.Mod(
        mod_id="tardismod",
        name="TARDIS Mod",
        version="1.0.0",
        description="Bigger on the inside.",
        authors=["DJ"],
        minecraft_version="1.20.1",
        loader="both",          # "fabric", "forge", "both", or "all"
    )

    mod.register(MyBlock)
    mod.register(MyItem)

    @mod.event("player_join")
    def on_join(ctx):
        ctx.player.send_message("Welcome!")

    @mod.command("mycommand")
    def my_cmd(ctx):
        ctx.source.send_message("Hello from command!")

    if __name__ == "__main__":
        mod.compile(output_dir="./dist")
"""

import inspect
from pathlib import Path
import re
from typing import List, Optional, Type


class _CreativeTabItems:
    def __init__(self, tab):
        self._tab = tab

    def add(self, item_id: str):
        if not item_id:
            raise ValueError("item_id is required")
        self._tab.items.append(item_id)
        return item_id


class CreativeTab:
    def __init__(self, mod, tab_id: str, title: str, icon_item: str):
        if not tab_id:
            raise ValueError("tab_id is required")
        if not title:
            raise ValueError("title is required")
        if not icon_item:
            raise ValueError("icon_item is required")
        self.mod = mod
        self.tab_id = tab_id.replace("\\", "/").strip("/")
        self.title = title
        self.icon_item = icon_item
        self.items: list[str] = []
        self.item = _CreativeTabItems(self)

    def set_title(self, title: str):
        if not title:
            raise ValueError("title is required")
        self.title = title
        return title

    def set_icon(self, item_id: str):
        if not item_id:
            raise ValueError("item_id is required")
        self.icon_item = item_id
        return item_id


class Keybind:
    def __init__(self, mod, keybind_id: str, title: str, key, category: str = "", category_title: str = ""):
        if not keybind_id:
            raise ValueError("keybind_id is required")
        if not title:
            raise ValueError("title is required")
        if key is None or key == "":
            raise ValueError("key is required")
        self.mod = mod
        self.keybind_id = keybind_id.replace("\\", "/").strip("/")
        self.title = title
        self.key = key
        self.category = category or mod.mod_id
        self.category_title = category_title or mod.name
        self.func = None
        self.source = ""
        self.key_type = "keyboard"

    def set_title(self, title: str):
        if not title:
            raise ValueError("title is required")
        self.title = title
        return title

    def set_key(self, key):
        if key is None or key == "":
            raise ValueError("key is required")
        self.key = key
        return key

    def set_category(self, category: str, title: str = ""):
        if not category:
            raise ValueError("category is required")
        self.category = category
        if title:
            self.category_title = title
        return category

    def on_press(self, func):
        self.func = func
        self.source = inspect.getsource(func)
        return func


class Packet:
    def __init__(self, mod, packet_id: str):
        if not packet_id:
            raise ValueError("packet_id is required")
        self.mod = mod
        self.packet_id = packet_id.replace("\\", "/").strip("/")
        self.server_func = None
        self.server_source = ""
        self.client_func = None
        self.client_source = ""

    def on_server(self, func):
        self.server_func = func
        self.server_source = inspect.getsource(func)
        return func

    def on_client(self, func):
        self.client_func = func
        self.client_source = inspect.getsource(func)
        return func


class ScreenButton:
    def __init__(self, screen, button_id: str, text: str, x: int, y: int, width: int = 100, height: int = 20):
        if not button_id:
            raise ValueError("button_id is required")
        self.screen = screen
        self.button_id = button_id.replace("\\", "/").strip("/")
        self.text = text
        self.x = int(x)
        self.y = int(y)
        self.width = int(width)
        self.height = int(height)
        self.func = None
        self.source = ""

    def on_click(self, func):
        self.func = func
        self.source = inspect.getsource(func)
        return func


class _ScreenButtons:
    def __init__(self, screen):
        self._screen = screen

    def add(self, button_id: str, text: str, x: int, y: int, width: int = 100, height: int = 20):
        button = ScreenButton(self._screen, button_id=button_id, text=text, x=x, y=y, width=width, height=height)
        self._screen.buttons.append(button)
        return button


class ScreenDefinition:
    def __init__(self, mod, screen_id: str, title: str, width: int = 248, height: int = 166):
        if not screen_id:
            raise ValueError("screen_id is required")
        if not title:
            raise ValueError("title is required")
        self.mod = mod
        self.screen_id = screen_id.replace("\\", "/").strip("/")
        self.title = title
        self.width = int(width)
        self.height = int(height)
        self.buttons: list[ScreenButton] = []
        self.labels: list[dict] = []
        self.open_func = None
        self.open_source = ""
        self.button = _ScreenButtons(self)

    def label(self, text: str, x: int, y: int, color: int = 0xFFFFFF):
        self.labels.append({
            "text": text,
            "x": int(x),
            "y": int(y),
            "color": int(color),
        })
        return self.labels[-1]

    def on_open(self, func):
        self.open_func = func
        self.open_source = inspect.getsource(func)
        return func


class Dependency:
    def __init__(
        self,
        coordinate: str = "",
        loader: str = "both",
        scope: str = "",
        repo: str = "",
        deobf: bool = True,
        mod_id: str = "",
        required: bool = False,
        version_range: str = "*",
        ordering: str = "NONE",
        side: str = "BOTH",
        path: str | Path | None = None,
    ):
        if bool(coordinate) == bool(path):
            raise ValueError("Specify exactly one dependency coordinate or path to a .jar")
        if coordinate and not re.fullmatch(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.+\[\],()-]+(?::[A-Za-z0-9_.-]+)?(?:@[A-Za-z0-9_.-]+)?", coordinate):
            raise ValueError("Dependency coordinate must be group:artifact:version[:classifier][@extension]")
        self.path = Path(path).expanduser().resolve() if path else None
        if self.path and (self.path.suffix.lower() != ".jar" or not self.path.is_file()):
            raise ValueError(f"Dependency JAR does not exist: {self.path}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", scope or "implementation"):
            raise ValueError(f"Invalid dependency scope: {scope!r}")
        self.coordinate = coordinate
        self.loader = loader.lower().strip()
        self.scope = scope.strip()
        self.repo = repo.strip()
        self.deobf = deobf
        self.mod_id = mod_id.strip()
        self.required = required
        self.version_range = version_range.strip() or "*"
        self.ordering = ordering.strip() or "NONE"
        self.side = side.strip() or "BOTH"


class Mod:
    def __init__(
        self,
        mod_id: str,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        authors: Optional[List[str]] = None,
        minecraft_version: str = "1.20.1",
        loader: str = "fabric",
        package: Optional[str] = None,
        website: str = "",
        license: str = "MIT",
    ):
        """
        Args:
            mod_id:             Short lowercase ID, e.g. "tardismod"
            name:               Human-readable mod name
            version:            Semantic version string
            description:        Short description shown in mod list
            authors:            List of author names
            minecraft_version:  Target MC version (default: "1.20.1")
            loader:             "fabric", "forge", "both", or "all"
            package:            Java package root (default: com.generated.<mod_id>)
            website:            Optional homepage URL
            license:            License identifier (default: "MIT")
        """
        if not mod_id or not re.fullmatch(r"[a-z][a-z0-9_]*", mod_id):
            raise ValueError(
                "mod_id must start with a lowercase letter and contain only lowercase letters, digits, and underscores"
            )

        self.mod_id = mod_id
        self.name = name
        self.version = version
        self.description = description
        self.authors = authors or []
        self.minecraft_version = minecraft_version.strip()
        self.loader = loader.lower().strip()
        self.package = package or f"com.generated.{mod_id}"
        self.website = website
        self.license = license

        self._blocks: list = []
        self._items: list = []
        self._entities: list = []
        self._mixins: list = []
        self._events: list = []
        self._commands: list = []
        self._recipes: list = []
        self._advancements: list = []
        self._sounds: list = []
        self._creative_tabs: list = []
        self._keybinds: list = []
        self._packets: list = []
        self._screens: list = []
        self._dependencies: list = []
        self._dimension_types: list = []
        self._dimensions: list = []
        self._structures: list = []

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register(self, cls):
        """
        Register a Block, Item, Entity, or Mixin class with this mod.
        Can be used as a decorator or called directly.

        Example:
            mod.register(MyBlock)

            @mod.register
            class MyOtherBlock(mc.Block):
                ...
        """
        from fabricpy.block import Block
        from fabricpy.item import Item
        from fabricpy.entity import Entity
        from fabricpy.mixin import Mixin

        if not isinstance(cls, type):
            raise TypeError("mod.register expects a Block, Item, Entity, or Mixin class")
        if isinstance(cls, type):
            if issubclass(cls, Block) and cls is not Block:
                cls.namespace = self.mod_id
                self._blocks.append(cls)
            elif issubclass(cls, Item) and cls is not Item:
                cls.namespace = self.mod_id
                self._items.append(cls)
            elif issubclass(cls, Entity) and cls is not Entity:
                cls.namespace = self.mod_id
                self._entities.append(cls)
            elif issubclass(cls, Mixin) and cls is not Mixin:
                self._mixins.append(cls)
            else:
                raise TypeError(f"Cannot register {cls}: must be a Block, Item, Entity, or Mixin subclass.")
        return cls

    # ------------------------------------------------------------------ #
    # Recipe system
    # ------------------------------------------------------------------ #

    def add_recipe(self, recipe_id: str, data: dict):
        """
        Register a raw recipe JSON object to be emitted under
        data/<modid>/recipes/<recipe_id>.json.
        """
        if not recipe_id:
            raise ValueError("recipe_id is required")
        if not isinstance(data, dict):
            raise TypeError("recipe data must be a dict")

        recipe_path = recipe_id.replace("\\", "/").strip("/")
        self._recipes.append({
            "id": recipe_path,
            "data": data,
        })
        return data

    def shaped_recipe(self, recipe_id: str, result: str, pattern: list[str], key: dict, count: int = 1):
        """Register a standard shaped crafting recipe."""
        data = {
            "type": "minecraft:crafting_shaped",
            "pattern": pattern,
            "key": key,
            "result": {
                "item": result,
                "count": count,
            },
        }
        self.add_recipe(recipe_id, data)
        return data

    # ------------------------------------------------------------------ #
    # Advancement system
    # ------------------------------------------------------------------ #

    def add_advancement(self, advancement_id: str, title: str, description: str, icon_item: str, parent: Optional[str] = None,
                        criteria: Optional[dict] = None, rewards: Optional[dict] = None, background: str = "",
                        frame: str = "task", show_toast: bool = True, announce_to_chat: bool = True, hidden: bool = False):
        if not advancement_id:
            raise ValueError("advancement_id is required")
        if not title:
            raise ValueError("title is required")
        if not description:
            raise ValueError("description is required")
        if not icon_item:
            raise ValueError("icon_item is required")

        data = {
            "display": {
                "icon": {"item": icon_item},
                "title": title,
                "description": description,
                "frame": frame,
                "show_toast": show_toast,
                "announce_to_chat": announce_to_chat,
                "hidden": hidden,
            },
            "criteria": criteria or {
                "fabricpy_manual": {
                    "trigger": "minecraft:impossible"
                }
            },
        }
        if parent:
            data["parent"] = parent
        if rewards:
            data["rewards"] = rewards
        if background:
            data["display"]["background"] = background

        self._advancements.append({
            "id": advancement_id.replace("\\", "/").strip("/"),
            "data": data,
        })
        return data

    def add_advancement_json(self, advancement_id: str, data: dict):
        if not advancement_id:
            raise ValueError("advancement_id is required")
        if not isinstance(data, dict):
            raise TypeError("advancement data must be a dict")
        self._advancements.append({
            "id": advancement_id.replace("\\", "/").strip("/"),
            "data": data,
        })
        return data

    def item_advancement(self, advancement_id: str, title: str, description: str, icon_item: str, trigger_item: Optional[str] = None,
                         parent: Optional[str] = None, rewards: Optional[dict] = None, background: str = "",
                         frame: str = "task", show_toast: bool = True, announce_to_chat: bool = True, hidden: bool = False):
        item_id = trigger_item or icon_item
        criteria = {
            "has_item": {
                "trigger": "minecraft:inventory_changed",
                "conditions": {
                    "items": [
                        {"items": [item_id]}
                    ]
                }
            }
        }
        return self.add_advancement(
            advancement_id=advancement_id,
            title=title,
            description=description,
            icon_item=icon_item,
            parent=parent,
            criteria=criteria,
            rewards=rewards,
            background=background,
            frame=frame,
            show_toast=show_toast,
            announce_to_chat=announce_to_chat,
            hidden=hidden,
        )

    # ------------------------------------------------------------------ #
    # Sound system
    # ------------------------------------------------------------------ #

    def add_sound(self, sound_id: str, sounds, subtitle: str = "", replace: bool = False):
        """
        Register a sound event to be emitted into assets/<modid>/sounds.json.

        Args:
            sound_id: registry-style sound id path, e.g. "machine/hum"
            sounds: a string path, a list of string paths, a single sound dict,
                    or a full sounds.json entry dict with a "sounds" key
            subtitle: optional subtitle text; stored in lang and wired to sounds.json
            replace: optional sounds.json "replace" flag
        """
        if not sound_id:
            raise ValueError("sound_id is required")

        if isinstance(sounds, dict) and "sounds" in sounds:
            data = dict(sounds)
        else:
            raw_entries = sounds if isinstance(sounds, list) else [sounds]
            data = {
                "sounds": [self._normalize_sound_entry(entry) for entry in raw_entries]
            }

        if replace:
            data["replace"] = True

        if subtitle:
            data["subtitle"] = f"subtitles.{self.mod_id}.{sound_id.replace('/', '.')}"

        self._sounds.append({
            "id": sound_id.replace("\\", "/").strip("/"),
            "data": data,
            "subtitle_text": subtitle,
        })
        return data

    def _normalize_sound_entry(self, entry):
        if isinstance(entry, str):
            name = entry.replace("\\", "/").strip("/")
            if ":" not in name:
                name = f"{self.mod_id}:{name}"
            return {"name": name}

        if isinstance(entry, dict):
            normalized = dict(entry)
            name = normalized.get("name")
            if isinstance(name, str) and ":" not in name:
                clean_name = name.replace("\\", "/").strip("/")
                normalized["name"] = f"{self.mod_id}:{clean_name}"
            return normalized

        raise TypeError("sound entries must be strings or dicts")

    # ------------------------------------------------------------------ #
    # Creative tabs
    # ------------------------------------------------------------------ #

    def creative_tab(self, tab_id: str, title: str, icon_item: str):
        tab = CreativeTab(self, tab_id=tab_id, title=title, icon_item=icon_item)
        self._creative_tabs.append(tab)
        return tab

    # ------------------------------------------------------------------ #
    # Keybind system
    # ------------------------------------------------------------------ #

    def keybind(self, keybind_id: str, title: str, key, category: str = "", category_title: str = ""):
        bind = Keybind(
            self,
            keybind_id=keybind_id,
            title=title,
            key=key,
            category=category,
            category_title=category_title,
        )
        self._keybinds.append(bind)
        return bind

    # ------------------------------------------------------------------ #
    # Packet system
    # ------------------------------------------------------------------ #

    def packet(self, packet_id: str):
        packet = Packet(self, packet_id=packet_id)
        self._packets.append(packet)
        return packet

    # ------------------------------------------------------------------ #
    # Screen system
    # ------------------------------------------------------------------ #

    def screen(self, screen_id: str, title: str, width: int = 248, height: int = 166):
        screen = ScreenDefinition(self, screen_id=screen_id, title=title, width=width, height=height)
        self._screens.append(screen)
        return screen

    # ------------------------------------------------------------------ #
    # Dependency system
    # ------------------------------------------------------------------ #

    def dependency(
        self,
        coordinate: str = "",
        loader: str = "both",
        scope: str = "",
        repo: str = "",
        deobf: bool = True,
        mod_id: str = "",
        required: bool = False,
        version_range: str = "*",
        ordering: str = "NONE",
        side: str = "BOTH",
        path: str | Path | None = None,
    ):
        dep = Dependency(
            coordinate=coordinate,
            path=path,
            loader=loader,
            scope=scope,
            repo=repo,
            deobf=deobf,
            mod_id=mod_id,
            required=required,
            version_range=version_range,
            ordering=ordering,
            side=side,
        )
        self._dependencies.append(dep)
        return dep

    # ------------------------------------------------------------------ #
    # Dimension system
    # ------------------------------------------------------------------ #

    def add_dimension_type(self, type_id: str, data: dict):
        """
        Register a dimension type JSON object under
        data/<modid>/dimension_type/<type_id>.json.
        """
        if not type_id:
            raise ValueError("type_id is required")
        if not isinstance(data, dict):
            raise TypeError("dimension type data must be a dict")

        type_path = type_id.replace("\\", "/").strip("/")
        self._dimension_types.append({
            "id": type_path,
            "data": data,
        })
        return data

    def add_dimension(self, dimension_id: str, dimension_type: str, generator: Optional[dict] = None, data: Optional[dict] = None):
        """
        Register a dimension JSON object under
        data/<modid>/dimension/<dimension_id>.json.

        You can either pass a full `data` dict or provide `dimension_type`
        plus `generator`.
        """
        if not dimension_id:
            raise ValueError("dimension_id is required")

        if data is not None:
            if not isinstance(data, dict):
                raise TypeError("dimension data must be a dict")
            payload = dict(data)
        else:
            if not dimension_type:
                raise ValueError("dimension_type is required when data is not provided")
            if generator is None:
                raise ValueError("generator is required when data is not provided")
            payload = {
                "type": dimension_type,
                "generator": generator,
            }

        dim_path = dimension_id.replace("\\", "/").strip("/")
        self._dimensions.append({
            "id": dim_path,
            "data": payload,
        })
        return payload

    def add_structure(self, structure_id: str, nbt_path: str):
        """
        Copy an NBT structure file into
        data/<modid>/structures/<structure_id>.nbt.
        """
        if not structure_id:
            raise ValueError("structure_id is required")
        if not nbt_path:
            raise ValueError("nbt_path is required")

        self._structures.append({
            "id": structure_id.replace("\\", "/").strip("/"),
            "path": nbt_path,
        })
        return nbt_path

    def shapeless_recipe(self, recipe_id: str, result: str, ingredients: list[dict], count: int = 1):
        """Register a standard shapeless crafting recipe."""
        data = {
            "type": "minecraft:crafting_shapeless",
            "ingredients": ingredients,
            "result": {
                "item": result,
                "count": count,
            },
        }
        self.add_recipe(recipe_id, data)
        return data

    # ------------------------------------------------------------------ #
    # Event system
    # ------------------------------------------------------------------ #

    def event(self, event_name: str, *, side: str | None = None):
        """
        Decorator to register an event handler function.

        Supported event names:
            "player_join"       — ServerPlayConnectionEvents.JOIN
            "player_leave"      — ServerPlayConnectionEvents.DISCONNECT
            "player_death"      — ServerEntityCombatEvents.AFTER_KILLED_OTHER_ENTITY  (ctx: player, attacker)
            "player_respawn"    — ServerPlayerEvents.AFTER_RESPAWN
            "block_break"       — PlayerBlockBreakEvents.AFTER  (ctx: player, world, pos, state)
            "server_start"      — ServerLifecycleEvents.SERVER_STARTED
            "server_stop"       — ServerLifecycleEvents.SERVER_STOPPED

        Example:
            @mod.event("player_join")
            def on_join(ctx):
                ctx.player.send_message("Welcome!")
        """
        from fabricpy.compiler.hook_sides import INTERACTION_EVENTS, validate_hook_side
        if side is not None:
            validate_hook_side(side)
            if event_name not in INTERACTION_EVENTS:
                raise ValueError("side is configurable for player interaction events only")
        def decorator(func):
            self._events.append({
                "event": event_name,
                "side": side or "server",
                "func": func,
                "source": inspect.getsource(func),
            })
            return func
        return decorator

    # ------------------------------------------------------------------ #
    # Command system
    # ------------------------------------------------------------------ #

    def command(self, name: str, permission_level: int = 0, aliases: Optional[List[str]] = None):
        """
        Decorator to register a slash command via Brigadier.

        Args:
            name:               Command name (no slash), e.g. "tardis"
            permission_level:   0=everyone, 1=trusted, 2=ops, 3=game master, 4=owner
            aliases:            Optional list of alias strings

        Example:
            @mod.command("tardis", permission_level=0)
            def tardis_cmd(ctx):
                ctx.source.send_message("TARDIS systems nominal.")
        """
        def decorator(func):
            self._commands.append({
                "name": name,
                "permission_level": permission_level,
                "aliases": aliases or [],
                "func": func,
                "source": inspect.getsource(func),
            })
            return func
        return decorator

    # ------------------------------------------------------------------ #
    # Compile
    # ------------------------------------------------------------------ #

    def generate(self):
        """Generate loader projects without running Gradle; return paths by loader."""
        from fabricpy.compiler import compile_mod
        return compile_mod(self, generate_only=True)

    def compile(self, output_dir: str = "./dist", clean: bool = False):
        """
        Compile this mod into a .jar file.

        Generates a complete Gradle project, transpiles Python to Java,
        then runs `gradlew build`. Output .jar is placed in output_dir.

        Args:
            output_dir: Where to put the finished .jar (default: ./dist)
            clean:      If True, runs `gradlew clean build` instead of just `gradlew build`
        """
        from fabricpy.compiler import compile_mod
        return compile_mod(self, output_dir=output_dir, clean=clean)

    # ------------------------------------------------------------------ #
    # Repr
    # ------------------------------------------------------------------ #

    def __repr__(self):
        return (
            f"<Mod id={self.mod_id!r} name={self.name!r} "
            f"loader={self.loader!r} mc={self.minecraft_version!r} "
            f"blocks={len(self._blocks)} items={len(self._items)} entities={len(self._entities)} "
            f"events={len(self._events)} commands={len(self._commands)} "
            f"recipes={len(self._recipes)} advancements={len(self._advancements)} sounds={len(self._sounds)} creative_tabs={len(self._creative_tabs)} keybinds={len(self._keybinds)} "
            f"packets={len(self._packets)} screens={len(self._screens)} "
            f"dependencies={len(self._dependencies)} "
            f"dimension_types={len(self._dimension_types)} dimensions={len(self._dimensions)} "
            f"structures={len(self._structures)}>"
        )

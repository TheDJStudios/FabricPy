"""Native music-disc item classes and resources for supported loader APIs."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

from fabricpy.music_disc import MusicDisc
from fabricpy.compiler.versions import version_tuple


def music_discs(mod) -> list[type[MusicDisc]]:
    return [item for item in mod._items if issubclass(item, MusicDisc)]


def sound_id(mod, item) -> str:
    value = item.sound
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{item.__name__}: music-disc sound is required")
    value = value.strip().replace("\\", "/")
    if value.endswith(".ogg"):
        value = value[:-4]
    if ":" not in value:
        value = f"{mod.mod_id}:{value}"
    if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", value):
        raise ValueError(f"{item.__name__}: invalid sound resource ID {value!r}")
    if any(part in {"", ".", ".."} for part in value.split(":", 1)[1].split("/")):
        raise ValueError(f"{item.__name__}: invalid sound resource path {value!r}")
    return value


def validate_music_disc(mod, item) -> None:
    if not issubclass(item, MusicDisc):
        return
    sound_id(mod, item)
    if mod.minecraft_version not in {"1.20.1", "1.21", "1.21.1"}:
        raise ValueError(f"MusicDisc currently supports Minecraft 1.20.1, 1.21 and 1.21.1; got {mod.minecraft_version!r}")
    duration = item.length_seconds
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"{item.__name__}: length_seconds must be a finite positive number")
    if duration > 2_147_483_647 / 20 or (mod.minecraft_version == "1.20.1" and math.ceil(duration) > 2_147_483_647 // 20):
        raise ValueError(f"{item.__name__}: length_seconds exceeds the native tick range")
    comparator = item.comparator_output
    if isinstance(comparator, bool) or not isinstance(comparator, int) or not 0 <= comparator <= 15:
        raise ValueError(f"{item.__name__}: comparator_output must be an integer from 0 to 15")
    if item.max_stack_size != 1 or item.max_damage != 0:
        raise ValueError(f"{item.__name__}: MusicDisc requires max_stack_size=1 and max_damage=0")
    if not isinstance(item.artist, str) or not isinstance(item.title, str):
        raise ValueError(f"{item.__name__}: artist and title must be strings")
    if not isinstance(item.rarity, str) or item.rarity.lower() not in {"common", "uncommon", "rare", "epic"}:
        raise ValueError(f"{item.__name__}: unknown rarity {item.rarity!r}")
    if item.get_hooks():
        raise ValueError(f"{item.__name__}: MusicDisc uses native jukebox behavior and does not support item hook overrides")
    if item.is_tool or item.food_hunger:
        raise ValueError(f"{item.__name__}: MusicDisc cannot also be a tool or food item")


def _modern(mod) -> bool:
    return version_tuple(mod.minecraft_version) >= (1, 21)


def _local_sounds(mod) -> list[str]:
    return sorted({sound_id(mod, item) for item in music_discs(mod)})


def _sound_field(mod, item) -> str:
    return f"SOUND_{_local_sounds(mod).index(sound_id(mod, item))}"


def music_disc_init_statement(mod, loader_name: str) -> str:
    if not music_discs(mod):
        return ""
    return "ModMusicDiscSounds.register();" if loader_name in {"fabric", "quilt"} else "ModMusicDiscSounds.register(bus);"


def _write_sound_registry(mod, java_root: Path, pkg: str, loader_name: str) -> None:
    sounds = _local_sounds(mod)
    fields = []
    fabric = loader_name in {"fabric", "quilt"}
    modern = _modern(mod)
    for index, identifier in enumerate(sounds):
        namespace, path = identifier.split(":", 1)
        own = namespace == mod.mod_id
        if fabric:
            identifier_expr = f'Identifier.of({json.dumps(namespace)}, {json.dumps(path)})' if modern else f'new Identifier({json.dumps(namespace)}, {json.dumps(path)})'
            expression = f"Registry.register(Registries.SOUND_EVENT, {identifier_expr}, SoundEvent.of({identifier_expr}))" if own else f"Registries.SOUND_EVENT.get({identifier_expr})"
            # The singleton is resolved before wrapping, so repeated get() calls never register again.
            fields.append(f"    private static final SoundEvent EVENT_{index} = {expression};\n    public static final Supplier<SoundEvent> SOUND_{index} = () -> EVENT_{index};")
        else:
            identifier_expr = f'ResourceLocation.fromNamespaceAndPath({json.dumps(namespace)}, {json.dumps(path)})' if modern else f'new ResourceLocation({json.dumps(namespace)}, {json.dumps(path)})'
            expression = f"SOUNDS.register({json.dumps(path)}, () -> SoundEvent.createVariableRangeEvent({identifier_expr}))" if own else f"() -> BuiltInRegistries.SOUND_EVENT.get({identifier_expr})"
            fields.append(f"    public static final Supplier<SoundEvent> SOUND_{index} = {expression};")
    if fabric:
        imports = """import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.sound.SoundEvent;
import net.minecraft.util.Identifier;"""
        registry = ""
        register = "    public static void register() { }"
    else:
        loader_package = "net.neoforged.neoforge" if loader_name == "neoforge" else "net.minecraftforge"
        bus_package = "net.neoforged.bus.api" if loader_name == "neoforge" else "net.minecraftforge.eventbus.api"
        imports = f"""import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.sounds.SoundEvent;
import {loader_package}.registries.DeferredRegister;
import {bus_package}.IEventBus;"""
        registry = f'    private static final DeferredRegister<SoundEvent> SOUNDS = DeferredRegister.create(Registries.SOUND_EVENT, {json.dumps(mod.mod_id)});\n'
        register = "    public static void register(IEventBus bus) { SOUNDS.register(bus); }"
    source = f"""package {pkg};

import java.util.function.Supplier;
{imports}

public final class ModMusicDiscSounds {{
{registry}{chr(10).join(fields)}
{register}
}}
"""
    java_root.mkdir(parents=True, exist_ok=True)
    (java_root / "ModMusicDiscSounds.java").write_text(source, encoding="utf-8")


def write_music_disc_class(mod, item, item_dir: Path, pkg: str, loader_name: str) -> bool:
    """Write a native disc and its shared sound registry; return False for ordinary items."""
    if not issubclass(item, MusicDisc):
        return False
    validate_music_disc(mod, item)
    if loader_name not in {"fabric", "quilt", "forge", "neoforge"}:
        raise ValueError(f"MusicDisc has no native backend for loader {loader_name!r}")
    item_dir.mkdir(parents=True, exist_ok=True)
    _write_sound_registry(mod, item_dir.parent, pkg, loader_name)
    fabric = loader_name in {"fabric", "quilt"}
    modern = _modern(mod)
    if fabric:
        base = "Item" if modern else "MusicDiscItem"
        imports = f"import net.minecraft.item.{base};\nimport net.minecraft.item.Item;\nimport net.minecraft.util.Rarity;"
        settings = f"new Item.Settings().maxCount(1).rarity(Rarity.{item.rarity.upper()})"
        if item.fireproof:
            settings += ".fireproof()"
        if modern:
            settings += f'.jukeboxPlayable(net.minecraft.registry.RegistryKey.of(net.minecraft.registry.RegistryKeys.JUKEBOX_SONG, net.minecraft.util.Identifier.of({json.dumps(mod.mod_id)}, {json.dumps(item.item_id)})))'
            constructor = f"super({settings});"
        else:
            constructor = f"super({item.comparator_output}, {pkg}.ModMusicDiscSounds.{_sound_field(mod, item)}.get(), {settings}, {math.ceil(item.length_seconds)});"
    else:
        base = "Item" if modern else "RecordItem"
        imports = f"import net.minecraft.world.item.{base};\nimport net.minecraft.world.item.Item;\nimport net.minecraft.world.item.Rarity;"
        settings = f"new Item.Properties().stacksTo(1).rarity(Rarity.{item.rarity.upper()})"
        if item.fireproof:
            settings += ".fireResistant()"
        if modern:
            settings += f'.jukeboxPlayable(net.minecraft.resources.ResourceKey.create(net.minecraft.core.registries.Registries.JUKEBOX_SONG, net.minecraft.resources.ResourceLocation.fromNamespaceAndPath({json.dumps(mod.mod_id)}, {json.dumps(item.item_id)})))'
            constructor = f"super({settings});"
        else:
            constructor = f"super({item.comparator_output}, {pkg}.ModMusicDiscSounds.{_sound_field(mod, item)}, {settings}, {math.ceil(item.length_seconds)});"
    source = f"""package {pkg}.item;

{imports}

public class {item.get_class_name()} extends {base} {{
    public {item.get_class_name()}() {{
        {constructor}
    }}
}}
"""
    (item_dir / f"{item.get_class_name()}.java").write_text(source, encoding="utf-8")
    return True


def _json_file(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot merge music-disc resource {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"Cannot merge music-disc resource {path}: expected a JSON object")
    return result


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_music_disc_resources(mod, res_root: Path) -> None:
    """Merge disc resources after ordinary/manual assets have been copied."""
    discs = music_discs(mod)
    if not discs:
        return
    assets = res_root / "assets" / mod.mod_id
    sounds_path = assets / "sounds.json"
    sounds = _json_file(sounds_path, {})
    lang_path = assets / "lang/en_us.json"
    lang = _json_file(lang_path, {})
    for item in discs:
        validate_music_disc(mod, item)
        namespace, path = sound_id(mod, item).split(":", 1)
        if namespace == mod.mod_id:
            # An explicit user event keeps its alternate files/subtitles, but playback
            # must stream long audio instead of decoding the whole track into memory.
            event = sounds.setdefault(path, {"sounds": [{"name": f"{namespace}:{path}", "stream": True}]})
            if not isinstance(event, dict) or not isinstance(event.get("sounds"), list):
                raise ValueError(f"{sounds_path}: disc sound {path!r} must have a sounds list")
            event["sounds"] = [({"name": entry, "stream": True} if isinstance(entry, str) else {**entry, "stream": True}) for entry in event["sounds"]]
        title = item.title or item.get_display_name()
        description = f"{item.artist} - {title}" if item.artist else title
        lang.setdefault(f"item.{mod.mod_id}.{item.item_id}.desc", description)
        if _modern(mod):
            translation = f"jukebox_song.{mod.mod_id}.{item.item_id}"
            lang.setdefault(translation, description)
            song = {"sound_event": sound_id(mod, item), "description": {"translate": translation},
                    "length_in_seconds": float(item.length_seconds), "comparator_output": item.comparator_output}
            song_file = res_root / "data" / mod.mod_id / "jukebox_song" / f"{item.item_id}.json"
            if not song_file.exists():
                _write_json(song_file, song)
    _write_json(sounds_path, sounds)
    _write_json(lang_path, lang)
    if not _modern(mod):
        tag_file = res_root / "data/minecraft/tags/items/music_discs.json"
        tag = _json_file(tag_file, {"replace": False, "values": []})
        values = tag.setdefault("values", [])
        if not isinstance(values, list):
            raise ValueError(f"{tag_file}: tag values must be a list")
        for item in discs:
            identifier = f"{mod.mod_id}:{item.item_id}"
            if identifier not in values:
                values.append(identifier)
        _write_json(tag_file, tag)

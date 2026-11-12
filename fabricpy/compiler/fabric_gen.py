"""
Fabric mod project generator.

Produces a complete Fabric 1.20.1 mod project:
  src/main/java/.../
    {ModId}.java            — Main mod class (ModInitializer)
    ModBlocks.java          — Block registry
    ModItems.java           — Item registry
    block/{BlockName}.java  — One file per Block subclass
    item/{ItemName}.java    — One file per Item subclass
    event/ModEvents.java    — All registered event handlers
    command/ModCommands.java— All registered commands
    mixin/{Name}Mixin.java  — All Mixin subclasses
  src/main/resources/
    fabric.mod.json
    {modid}.mixins.json
    assets/{modid}/lang/en_us.json
  build.gradle
  settings.gradle
  gradle.properties
"""

import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fabricpy.mod import Mod

from fabricpy.compiler.transpiler import JavaTranspiler
from fabricpy.compiler.item_features import effective_stack_size, item_storage_api_map
from fabricpy.compiler.item_storage import write_item_storage_helpers
from fabricpy.compiler.item_transfers import write_item_transfer_helpers
from fabricpy.compiler.item_menus import write_item_menu_helpers
from fabricpy.compiler.item_attachment_rendering import (attachment_items, attachment_proxy_registrations, attachment_item_client_extension, attachment_client_init_statement, write_attachment_renderer, write_attachment_resources)
from fabricpy.compiler.music_discs import write_music_disc_class, write_music_disc_resources, music_disc_init_statement
from fabricpy.compiler.hook_sides import guard_hook_body, INTERACTION_EVENTS
from fabricpy.compiler.dependencies import dependencies_for_loader, gradle_notation
from fabricpy.compiler.symbol_index import write_interop_metadata
from fabricpy.compiler.jar_scanner import build_symbol_index_for_project
from fabricpy.compiler.bbmodel_converter import compile_bbmodels_in_assets, resolve_model_input
from fabricpy.compiler.api_maps import (
    FABRIC_API_MAP, FABRIC_EXTRA_IMPORTS,
    FABRIC_EVENT_MAP,
)
from fabricpy.compiler.versions import FABRIC_VERSIONS, is_at_least


def to_pascal(snake: str) -> str:
    return "".join(w.capitalize() for w in snake.split("_"))


def _write_text(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def _resource_ref(mod_id: str, ref: str, folder: str, default_id: str) -> str:
    if ref:
        if ":" in ref:
            return ref
        return f"{mod_id}:{folder}/{ref}"
    return f"{mod_id}:{folder}/{default_id}"


def _clamp_emissive_level(level: int) -> int:
    try:
        return max(0, min(255, int(level)))
    except (TypeError, ValueError):
        return 0


def _block_light_level(block) -> int:
    emissive = _clamp_emissive_level(getattr(block, "emissive_level", 0))
    mapped = 0 if emissive <= 0 else max(1, min(15, (emissive + 16) // 17))
    return max(int(block.luminance), mapped)


def _overlay_texture_map(base_textures: dict | None, override_textures: dict | None, emissive_ref: str) -> dict:
    if override_textures:
        return dict(override_textures)
    if base_textures:
        overlay = dict(base_textures)
        for key in list(overlay.keys()):
            overlay[key] = emissive_ref
        return overlay
    return {"all": emissive_ref, "particle": emissive_ref}


def _append_emissive_overlay_blockstate(blockstate: dict, overlay_model_id: str) -> dict:
    data = json.loads(json.dumps(blockstate))
    if "variants" in data:
        multipart = []
        for key, value in data["variants"].items():
            when = {}
            if key:
                for condition in key.split(","):
                    if "=" in condition:
                        prop, prop_value = condition.split("=", 1)
                        when[prop] = prop_value
            base_part = {"apply": value}
            overlay_apply = json.loads(json.dumps(value))
            if isinstance(overlay_apply, dict):
                overlay_apply["model"] = overlay_model_id
            elif isinstance(overlay_apply, list):
                for entry in overlay_apply:
                    if isinstance(entry, dict):
                        entry["model"] = overlay_model_id
            overlay_part = {"apply": overlay_apply}
            if when:
                base_part["when"] = when
                overlay_part["when"] = dict(when)
            multipart.append(base_part)
            multipart.append(overlay_part)
        return {"multipart": multipart}
    if "multipart" in data:
        parts = list(data["multipart"])
        overlays = []
        for part in parts:
            overlay_part = json.loads(json.dumps(part))
            apply = overlay_part.get("apply")
            if isinstance(apply, dict):
                apply["model"] = overlay_model_id
            elif isinstance(apply, list):
                for entry in apply:
                    if isinstance(entry, dict):
                        entry["model"] = overlay_model_id
            overlays.append(overlay_part)
        data["multipart"] = parts + overlays
    return data


def _normalize_block_model_id(mod_id: str, model_ref: str, default_name: str) -> str:
    ref = (model_ref or "").strip()
    if not ref:
        return f"{mod_id}:block/{default_name}"
    if ":" in ref:
        return ref
    if ref.startswith("block/"):
        return f"{mod_id}:{ref}"
    return f"{mod_id}:block/{ref}"


def _generated_rotation_blockstate(mod_id: str, block) -> dict:
    wall_model_id = _normalize_block_model_id(mod_id, getattr(block, "wall_model", ""), block.block_id)
    floor_model_id = _normalize_block_model_id(mod_id, getattr(block, "floor_model", ""), block.block_id)
    variants = {}
    rotations = {
        "north": 0,
        "east": 90,
        "south": 180,
        "west": 270,
    }
    if getattr(block, "rotation_mode", "wall") == "floor":
        for facing, y in rotations.items():
            variants[f"facing={facing}"] = {"model": floor_model_id, "x": 90, "y": y}
    else:
        for facing, y in rotations.items():
            variants[f"facing={facing}"] = {"model": wall_model_id, "y": y}
    return {"variants": variants}


def _model_file_from_id(project_root: Path, default_mod_id: str, model_id: str) -> Path | None:
    if ":" in model_id:
        namespace, path = model_id.split(":", 1)
    else:
        namespace, path = default_mod_id, model_id
    if not path.startswith("block/"):
        return None
    rel = path[len("block/"):]
    return project_root / "assets" / namespace / "models" / "block" / f"{rel}.json"


def _load_block_model_data(project_root: Path, mod, block, model_id: str) -> dict | None:
    default_model_id = _normalize_block_model_id(mod.mod_id, "", block.block_id)
    if model_id == default_model_id and block.model is not None:
        return resolve_model_input(block.model, mod.mod_id, "block", block.block_id)
    model_file = _model_file_from_id(project_root, mod.mod_id, model_id)
    if model_file and model_file.exists():
        try:
            return json.loads(model_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    if model_file and model_file.with_suffix(".bbmodel").exists():
        return resolve_model_input(model_file.with_suffix(".bbmodel"), mod.mod_id, "block", block.block_id)
    return None


def _rotate_point_y(x: float, z: float, quarter_turns: int) -> tuple[float, float]:
    turns = quarter_turns % 4
    cx = x - 8.0
    cz = z - 8.0
    if turns == 0:
        rx, rz = cx, cz
    elif turns == 1:
        rx, rz = -cz, cx
    elif turns == 2:
        rx, rz = -cx, -cz
    else:
        rx, rz = cz, -cx
    return rx + 8.0, rz + 8.0


def _rotate_point_x_90(y: float, z: float) -> tuple[float, float]:
    cy = y - 8.0
    cz = z - 8.0
    ry = -cz
    rz = cy
    return ry + 8.0, rz + 8.0


def _transform_box(box: tuple[float, float, float, float, float, float], mode: str, facing: str) -> tuple[float, float, float, float, float, float]:
    x1, y1, z1, x2, y2, z2 = box
    corners = [
        (x, y, z)
        for x in (x1, x2)
        for y in (y1, y2)
        for z in (z1, z2)
    ]
    transformed = []
    quarter_turns = {"north": 0, "east": 1, "south": 2, "west": 3}.get(facing, 0)
    for x, y, z in corners:
        tx, ty, tz = x, y, z
        if mode == "floor":
            ty, tz = _rotate_point_x_90(ty, tz)
        tx, tz = _rotate_point_y(tx, tz, quarter_turns)
        transformed.append((tx, ty, tz))
    xs = [p[0] for p in transformed]
    ys = [p[1] for p in transformed]
    zs = [p[2] for p in transformed]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _model_boxes_for_block(project_root: Path, mod, block) -> dict[str, list[tuple[float, float, float, float, float, float]]]:
    mode = getattr(block, "rotation_mode", "wall")
    wall_model_id = _normalize_block_model_id(mod.mod_id, getattr(block, "wall_model", ""), block.block_id)
    floor_model_id = _normalize_block_model_id(mod.mod_id, getattr(block, "floor_model", ""), block.block_id)
    base_model_id = floor_model_id if mode == "floor" else wall_model_id
    model_data = _load_block_model_data(project_root, mod, block, base_model_id)
    if not isinstance(model_data, dict):
        return {}
    elements = model_data.get("elements")
    if not isinstance(elements, list):
        return {}
    base_boxes = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        from_pos = element.get("from")
        to_pos = element.get("to")
        if not (isinstance(from_pos, list) and isinstance(to_pos, list) and len(from_pos) == 3 and len(to_pos) == 3):
            continue
        base_boxes.append((
            float(from_pos[0]), float(from_pos[1]), float(from_pos[2]),
            float(to_pos[0]), float(to_pos[1]), float(to_pos[2]),
        ))
    if not base_boxes:
        return {}
    if getattr(block, "variable_rotation", False):
        return {
            facing: [_transform_box(box, mode, facing) for box in base_boxes]
            for facing in ("north", "east", "south", "west")
        }
    return {"default": base_boxes}


def _fabric_shape_code(shape_name: str, boxes: list[tuple[float, float, float, float, float, float]]) -> str:
    parts = [f"Block.createCuboidShape({x1}, {y1}, {z1}, {x2}, {y2}, {z2})" for x1, y1, z1, x2, y2, z2 in boxes]
    expr = "VoxelShapes.union(" + ", ".join(parts) + ")" if len(parts) > 1 else parts[0]
    return f"    private static final VoxelShape {shape_name} = {expr};"


def _copy_tree_if_exists(src: Path, dest: Path):
    if src.exists():
        shutil.copytree(src, dest, dirs_exist_ok=True)


def _fabric_api_map_for_version(minecraft_version: str) -> dict[str, str]:
    if is_at_least(minecraft_version, "1.21"):
        return {
            key: value.replace("new Identifier(", "Identifier.of(")
            for key, value in FABRIC_API_MAP.items()
        }
    return FABRIC_API_MAP


def _fabric_api_map_for_project(minecraft_version: str, pkg: str) -> dict[str, str]:
    api_map = dict(_fabric_api_map_for_version(minecraft_version))
    runtime = f"{pkg}.util.FabricPyRuntime"
    network = f"{pkg}.network.FabricPyNetwork"
    screens = f"{pkg}.client.ModScreens"

    api_map.update({
        "ctx.math.vec3": f"new net.minecraft.util.math.Vec3d({{0}}, {{1}}, {{2}})",
        "ctx.math.block_pos": "new BlockPos((int)({0}), (int)({1}), (int)({2}))",
        "ctx.math.clamp": f"{runtime}.clamp({{0}}, {{1}}, {{2}})",
        "ctx.math.lerp": f"{runtime}.lerp({{0}}, {{1}}, {{2}})",
        "ctx.math.distance3": f"{runtime}.distance3({{0}}, {{1}}, {{2}}, {{3}}, {{4}}, {{5}})",
        "ctx.math.length3": f"{runtime}.length3({{0}}, {{1}}, {{2}})",
        "ctx.math.normalize3": f"{runtime}.normalize3({{0}}, {{1}}, {{2}})",
        "ctx.math.add3": f"{runtime}.add3({{0}}, {{1}}, {{2}}, {{3}}, {{4}}, {{5}})",
        "ctx.world.spawn_particle": f"{runtime}.spawnParticle(world, {{0}}, {{1}}, {{2}}, {{3}}, {{4}}, {{5}}, {{6}}, {{7}}, {{8}})",
        "ctx.world.spawn_particle_self": f"{runtime}.spawnParticle(world, {{0}}, pos.getX() + 0.5, pos.getY() + 0.5, pos.getZ() + 0.5, {{1}}, {{2}}, {{3}}, {{4}}, {{5}})",
        "ctx.world.raycast_block": f"{runtime}.raycastBlock(world, {{0}}, {{1}})",
        "ctx.world.raycast_block_id": f"{runtime}.raycastBlockId(world, {{0}}, {{1}})",
        "ctx.world.raycast_block_pos_x": f"{runtime}.raycastBlockPosX(world, {{0}}, {{1}})",
        "ctx.world.raycast_block_pos_y": f"{runtime}.raycastBlockPosY(world, {{0}}, {{1}})",
        "ctx.world.raycast_block_pos_z": f"{runtime}.raycastBlockPosZ(world, {{0}}, {{1}})",
        "ctx.client.open_screen": f"{screens}.openClient({{0}})",
        "ctx.client.close_screen": f"{screens}.closeClient()",
        "ctx.net.send_to_server": f"{network}.sendToServer({{0}}, {{1}})",
        "ctx.net.send_to_player": f"{network}.sendToPlayer((ServerPlayerEntity)({{0}}), {{1}}, {{2}})",
        "ctx.net.broadcast": f"{network}.broadcast(server, {{0}}, {{1}})",
    })
    api_map.update(item_storage_api_map(pkg))
    return api_map


def _id_ctor(mod: "Mod", namespace_expr: str, path_expr: str) -> str:
    if is_at_least(mod.minecraft_version, "1.21"):
        return f"Identifier.of({namespace_expr}, {path_expr})"
    return f"new Identifier({namespace_expr}, {path_expr})"


def _blocks_with_block_entities(mod: "Mod") -> list:
    return [
        block for block in mod._blocks
        if block.has_block_entity or getattr(block, "uses_block_data", False) or bool(getattr(block, "geo_model", "")) or "on_tick" in block.get_hooks()
    ]


def _blocks_requiring_cutout(mod: "Mod") -> list:
    return [
        block for block in mod._blocks
        if _render_layer_value(getattr(block, "render_layer", "")) != "solid"
        or (not block.opaque)
        or bool(getattr(block, "emissive_texture", ""))
    ]


def _blocks_with_geo_animation(mod: "Mod") -> list:
    return [block for block in mod._blocks if bool(getattr(block, "geo_model", ""))]


def _entities_with_geo_animation(mod: "Mod") -> list:
    return [entity for entity in mod._entities if bool(getattr(entity, "geo_model", ""))]


def _uses_geckolib(mod: "Mod") -> bool:
    return bool(_blocks_with_geo_animation(mod) or _entities_with_geo_animation(mod))


def _render_layer_value(value: str) -> str:
    clean = (value or "solid").strip().lower()
    return clean if clean in {"solid", "cutout", "cutout_mipped", "translucent"} else "solid"


def _fabric_render_layer_expr(value: str) -> str:
    layer = _render_layer_value(value)
    if layer == "translucent":
        return "RenderLayer.getTranslucent()"
    if layer == "cutout_mipped":
        return "RenderLayer.getCutoutMipped()"
    if layer == "cutout":
        return "RenderLayer.getCutout()"
    return "RenderLayer.getSolid()"


def _resource_location_parts(mod_id: str, ref: str, prefix: str, default_id: str, suffix: str) -> tuple[str, str]:
    clean = (ref or "").strip()
    if ":" in clean:
        namespace, path = clean.split(":", 1)
    else:
        namespace, path = mod_id, clean
    if not path:
        path = default_id
    if prefix and not path.startswith(f"{prefix}/"):
        path = f"{prefix}/{path}"
    if suffix and not path.endswith(suffix):
        path = f"{path}{suffix}"
    return namespace, path


def _geo_model_resource_parts(mod_id: str, ref: str, default_id: str) -> tuple[str, str]:
    clean = (ref or "").strip()
    if clean.endswith(".bbmodel"):
        clean = clean[:-8]
    elif clean.endswith(".geo.json"):
        clean = clean[:-9]
    return _resource_location_parts(mod_id, clean, "geo", default_id, ".geo.json")


def _geo_model_parts(mod_id: str, block) -> tuple[str, str]:
    return _geo_model_resource_parts(mod_id, getattr(block, "geo_model", ""), block.block_id)


def _geo_texture_parts(mod_id: str, block) -> tuple[str, str]:
    return _resource_location_parts(mod_id, getattr(block, "geo_texture", "") or getattr(block, "texture", ""), "textures/block", block.block_id, ".png")


def _geo_animation_parts(mod_id: str, block) -> tuple[str, str]:
    return _resource_location_parts(mod_id, getattr(block, "geo_animations", ""), "animations", block.block_id, ".animation.json")


def _geo_entity_model_parts(mod_id: str, entity) -> tuple[str, str]:
    return _geo_model_resource_parts(mod_id, getattr(entity, "geo_model", ""), entity.entity_id)


def _geo_entity_texture_parts(mod_id: str, entity) -> tuple[str, str]:
    return _resource_location_parts(mod_id, getattr(entity, "geo_texture", ""), "textures/entity", entity.entity_id, ".png")


def _geo_entity_animation_parts(mod_id: str, entity) -> tuple[str, str]:
    return _resource_location_parts(mod_id, getattr(entity, "geo_animations", ""), "animations", entity.entity_id, ".animation.json")


def _keybind_code_expr(keybind) -> str:
    key = keybind.key
    if isinstance(key, int):
        return str(key)
    raw = str(key).strip().upper()
    if raw.startswith("GLFW.GLFW_KEY_"):
        return raw
    if raw.startswith("GLFW_KEY_"):
        return f"GLFW.{raw}"
    if len(raw) == 1 and raw.isalnum():
        return f"GLFW.GLFW_KEY_{raw}"
    return f"GLFW.GLFW_KEY_{raw}"


def _deps_for_loader(mod: "Mod", loader_name: str) -> list:
    return dependencies_for_loader(mod, loader_name)


def _fabric_dependency_scope(dep) -> str:
    return dep.scope or "modImplementation"


def _fabric_repository_lines(mod: "Mod", loader_name: str = "fabric") -> list[str]:
    repos = []
    seen = set()
    for dep in _deps_for_loader(mod, loader_name):
        if dep.repo and dep.repo not in seen:
            repos.append(f'    maven {{ url = "{dep.repo}" }}')
            seen.add(dep.repo)
    return repos


def _fabric_dependency_lines(mod: "Mod", loader_name: str = "fabric") -> list[str]:
    lines = []
    for dep in _deps_for_loader(mod, loader_name):
        lines.append(f'    {_fabric_dependency_scope(dep)} {gradle_notation(dep)}')
    return lines


def _fabric_manifest_dependencies(mod: "Mod", loader_name: str = "fabric") -> list[dict]:
    deps = []
    for dep in _deps_for_loader(mod, loader_name):
        if dep.mod_id and dep.required:
            deps.append({
                "mod_id": dep.mod_id,
                "required": True,
                "version_range": dep.version_range or "*",
            })
    return deps


def _fabric_spawn_group(group: str) -> str:
    mapping = {
        "monster": "SpawnGroup.MONSTER",
        "creature": "SpawnGroup.CREATURE",
        "ambient": "SpawnGroup.AMBIENT",
        "water_creature": "SpawnGroup.WATER_CREATURE",
        "water_ambient": "SpawnGroup.WATER_AMBIENT",
        "misc": "SpawnGroup.MISC",
        "underground_water_creature": "SpawnGroup.UNDERGROUND_WATER_CREATURE",
        "axolotls": "SpawnGroup.AXOLOTLS",
    }
    return mapping.get(group, "SpawnGroup.MISC")


def generate_fabric_project(mod: "Mod", project_dir: Path, *, loader_name: str = "fabric"):
    """Generate a complete Fabric mod project tree under project_dir."""
    pkg = mod.package
    pkg_path = pkg.replace(".", "/")
    src = project_dir / "src" / "main"
    java_root = src / "java" / pkg_path
    res_root = src / "resources"

    if java_root.exists():
        shutil.rmtree(java_root)
    if res_root.exists():
        shutil.rmtree(res_root)

    java_root.mkdir(parents=True, exist_ok=True)
    res_root.mkdir(parents=True, exist_ok=True)

    interop_repositories = ["https://maven.fabricmc.net/", *_fabric_repository_lines(mod, loader_name), "https://repo1.maven.org/maven2/"]
    interop_dependency_lines = _fabric_dependency_lines(mod, loader_name)
    if _uses_geckolib(mod):
        version_meta = FABRIC_VERSIONS.get(mod.minecraft_version)
        if version_meta is None:
            raise ValueError(f"Fabric does not support minecraft_version={mod.minecraft_version!r} in this generator.")
        interop_repositories.insert(1, "https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/")
        interop_dependency_lines = [
            f'modImplementation "software.bernie.geckolib:geckolib-fabric-{mod.minecraft_version}:{version_meta.geckolib}"',
            *interop_dependency_lines,
        ]
    write_interop_metadata(
        mod,
        project_dir,
        loader_name,
        repositories=interop_repositories,
        dependency_lines=interop_dependency_lines,
        manifest_dependencies=_fabric_manifest_dependencies(mod, loader_name),
    )
    try:
        build_symbol_index_for_project(project_dir)
    except Exception as exc:
        raise ValueError(f"Dependency scanning failed for {loader_name}: {exc}") from exc

    transpiler = JavaTranspiler(
        _fabric_api_map_for_project(mod.minecraft_version, pkg),
        interop_index_path=project_dir / ".fabricpy_meta" / "symbol_index.json",
    )

    _write_main_class(mod, java_root, pkg, loader_name)
    _write_client_class(mod, java_root, pkg, loader_name)
    _write_runtime_helpers(mod, java_root, pkg)
    _write_network(mod, java_root, pkg, transpiler)
    _write_screens(mod, java_root, pkg, transpiler)
    _write_mod_blocks(mod, java_root, pkg)
    _write_mod_block_entities(mod, java_root, pkg)
    _write_mod_items(mod, java_root, pkg, loader_name)
    _write_mod_creative_tabs(mod, java_root, pkg)
    _write_mod_keybinds(mod, java_root, pkg, transpiler)
    _write_mod_entities(mod, java_root, pkg)
    _write_geo_block_renderers(mod, java_root, pkg)
    _write_block_classes(mod, java_root, pkg, transpiler)
    _write_item_classes(mod, java_root, pkg, transpiler, loader_name)
    write_item_storage_helpers(mod, java_root, pkg, loader_name)
    write_item_transfer_helpers(mod, java_root, pkg, loader_name)
    write_item_menu_helpers(mod, java_root, pkg, loader_name)
    write_attachment_renderer(mod, java_root, pkg, loader_name)
    _write_entity_classes(mod, java_root, pkg, transpiler)
    _write_events(mod, java_root, pkg, transpiler)
    _write_commands(mod, java_root, pkg, transpiler)
    _write_mixins(mod, java_root, pkg, transpiler)
    _write_resources(mod, res_root, pkg, loader_name)
    _write_gradle_files(mod, project_dir, loader_name)
    print(f"[fabricpy] Fabric project generated at {project_dir}")


# ─────────────────────────────────────────────────────────────────────────── #
# Main mod class
# ─────────────────────────────────────────────────────────────────────────── #

def _write_main_class(mod: "Mod", java_root: Path, pkg: str, loader_name: str = "fabric"):
    class_name = to_pascal(mod.mod_id)

    has_blocks = bool(mod._blocks)
    has_block_entities = bool(_blocks_with_block_entities(mod))
    has_items = bool(mod._items)
    has_creative_tabs = bool(mod._creative_tabs)
    has_geo_blocks = _uses_geckolib(mod)
    has_entities = bool(mod._entities)
    has_events = bool(mod._events)
    has_commands = bool(mod._commands)
    has_packets = bool(mod._packets)

    reg_lines = []
    disc_init = music_disc_init_statement(mod, loader_name)
    if disc_init:
        reg_lines.append("        " + disc_init)
    if has_blocks:
        reg_lines.append(f"        ModBlocks.register();")
    if has_block_entities:
        reg_lines.append(f"        ModBlockEntities.register();")
    if has_items:
        reg_lines.append(f"        ModItems.register();")
    if has_creative_tabs:
        reg_lines.append(f"        ModCreativeTabs.register();")
    if has_entities:
        reg_lines.append(f"        ModEntities.register();")
    if has_events:
        reg_lines.append(f"        ModEvents.register();")
    if has_commands:
        reg_lines.append(f"        ModCommands.register();")
    if has_packets:
        reg_lines.append(f"        {pkg}.network.FabricPyNetwork.registerCommon();")
    if has_geo_blocks:
        reg_lines.append(f"        software.bernie.geckolib.GeckoLib.initialize();")
    if not reg_lines:
        reg_lines.append("        // No registrations yet")

    imports = []
    if has_block_entities:
        imports.append(f"import {pkg}.blockentity.ModBlockEntities;")
    if has_events:
        imports.append(f"import {pkg}.event.ModEvents;")
    if has_entities:
        imports.append(f"import {pkg}.entity.ModEntities;")
    if has_commands:
        imports.append(f"import {pkg}.command.ModCommands;")

    src = f"""\
package {pkg};

{chr(10).join(imports)}
import net.fabricmc.api.ModInitializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Generated by fabricpy — https://github.com/fabricpy
 * Main entrypoint for {mod.name} v{mod.version}
 */
public class {class_name} implements ModInitializer {{
    public static final String MOD_ID = "{mod.mod_id}";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    @Override
    public void onInitialize() {{
{chr(10).join(reg_lines)}
    }}
}}
"""
    _write_text(java_root / f"{class_name}.java", src)


def _write_client_class(mod: "Mod", java_root: Path, pkg: str, loader_name: str = "fabric"):
    cutout_blocks = _blocks_requiring_cutout(mod)
    has_keybinds = bool(mod._keybinds)
    has_geo = _uses_geckolib(mod)
    has_packets = bool(mod._packets)
    has_attachments = bool(attachment_items(mod))
    if not cutout_blocks and not has_keybinds and not has_geo and not has_packets and not has_attachments:
        return
    class_name = f"{to_pascal(mod.mod_id)}Client"
    imports = []
    if has_attachments:
        imports.append(f"import {pkg}.client.ModAttachmentRenderers;")
    if has_keybinds:
        imports.append(f"import {pkg}.client.ModKeybinds;")
    if has_geo:
        imports.append(f"import {pkg}.client.ModGeoRenderers;")
    if has_packets:
        imports.append(f"import {pkg}.network.FabricPyNetwork;")
    src = f"""\
package {pkg};

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.blockrenderlayer.v1.BlockRenderLayerMap;
import net.minecraft.client.render.RenderLayer;
{chr(10).join(imports)}

public class {class_name} implements ClientModInitializer {{

    @Override
    public void onInitializeClient() {{
{chr(10).join([f"        BlockRenderLayerMap.INSTANCE.putBlock(ModBlocks.{block.block_id.upper()}, {_fabric_render_layer_expr(getattr(block, 'render_layer', 'cutout' if (not block.opaque or getattr(block, 'emissive_texture', '')) else 'solid'))});" for block in cutout_blocks])}
{"        ModKeybinds.registerClient();" if has_keybinds else ""}
{"        ModGeoRenderers.registerClient();" if has_geo else ""}
{"        FabricPyNetwork.registerClient();" if has_packets else ""}
{"        " + attachment_client_init_statement(mod, loader_name) if has_attachments else ""}
    }}
}}
"""
    _write_text(java_root / f"{class_name}.java", src)


def _write_runtime_helpers(mod: "Mod", java_root: Path, pkg: str):
    util_dir = java_root / "util"
    util_dir.mkdir(exist_ok=True)
    src = f"""\
package {pkg}.util;

import net.minecraft.block.BlockState;
import net.minecraft.entity.Entity;
import net.minecraft.particle.{"SimpleParticleType" if is_at_least(mod.minecraft_version, "1.21") else "DefaultParticleType"};
import net.minecraft.registry.Registries;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.Identifier;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.RaycastContext;
import net.minecraft.world.World;

public class FabricPyRuntime {{
    public static double clamp(double value, double min, double max) {{
        return Math.max(min, Math.min(max, value));
    }}

    public static double lerp(double start, double end, double delta) {{
        return start + ((end - start) * delta);
    }}

    public static double distance3(double x1, double y1, double z1, double x2, double y2, double z2) {{
        return Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2) + Math.pow(z2 - z1, 2));
    }}

    public static double length3(double x, double y, double z) {{
        return Math.sqrt((x * x) + (y * y) + (z * z));
    }}

    public static Vec3d normalize3(double x, double y, double z) {{
        double len = length3(x, y, z);
        if (len <= 0.000001d) {{
            return new Vec3d(0, 0, 0);
        }}
        return new Vec3d(x / len, y / len, z / len);
    }}

    public static Vec3d add3(double x1, double y1, double z1, double x2, double y2, double z2) {{
        return new Vec3d(x1 + x2, y1 + y2, z1 + z2);
    }}

    public static BlockHitResult raycastBlock(World world, Vec3d start, Vec3d end) {{
        return world.raycast(new RaycastContext(start, end, RaycastContext.ShapeType.OUTLINE, RaycastContext.FluidHandling.NONE, (Entity)null));
    }}

    public static String raycastBlockId(World world, Vec3d start, Vec3d end) {{
        BlockHitResult hit = raycastBlock(world, start, end);
        if (hit.getType() != HitResult.Type.BLOCK) {{
            return "";
        }}
        BlockState state = world.getBlockState(hit.getBlockPos());
        return Registries.BLOCK.getId(state.getBlock()).toString();
    }}

    public static int raycastBlockPosX(World world, Vec3d start, Vec3d end) {{
        BlockHitResult hit = raycastBlock(world, start, end);
        return hit.getType() == HitResult.Type.BLOCK ? hit.getBlockPos().getX() : 0;
    }}

    public static int raycastBlockPosY(World world, Vec3d start, Vec3d end) {{
        BlockHitResult hit = raycastBlock(world, start, end);
        return hit.getType() == HitResult.Type.BLOCK ? hit.getBlockPos().getY() : 0;
    }}

    public static int raycastBlockPosZ(World world, Vec3d start, Vec3d end) {{
        BlockHitResult hit = raycastBlock(world, start, end);
        return hit.getType() == HitResult.Type.BLOCK ? hit.getBlockPos().getZ() : 0;
    }}

    public static void spawnParticle(World world, String particleId, double x, double y, double z, double dx, double dy, double dz, double speed, int count) {{
        var particleType = Registries.PARTICLE_TYPE.get({"Identifier.of(particleId)" if is_at_least(mod.minecraft_version, "1.21") else "new Identifier(particleId)"});
        if (!(particleType instanceof {"SimpleParticleType" if is_at_least(mod.minecraft_version, "1.21") else "DefaultParticleType"} defaultParticle)) {{
            return;
        }}
        if (world instanceof ServerWorld serverWorld) {{
            serverWorld.spawnParticles(defaultParticle, x, y, z, count, dx, dy, dz, speed);
            return;
        }}
        for (int i = 0; i < Math.max(1, count); i++) {{
            world.addParticle(defaultParticle, x, y, z, dx, dy, dz);
        }}
    }}
}}
"""
    _write_text(util_dir / "FabricPyRuntime.java", src)


def _write_network(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._packets:
        return
    network_dir = java_root / "network"
    network_dir.mkdir(exist_ok=True)

    server_cases = []
    client_cases = []
    for packet in mod._packets:
        if packet.server_source:
            body = transpiler.transpile_method(packet.server_source)
            server_cases.append(f"""\
                case "{packet.packet_id}" -> {{
                    ServerWorld world = player.getServerWorld();
                    BlockPos soundPos = player.getBlockPos();
{body}
                }}""")
        if packet.client_source:
            body = transpiler.transpile_method(packet.client_source)
            client_cases.append(f"""\
                case "{packet.packet_id}" -> {{
                    var player = client.player;
                    var world = client.world;
                    var server = client.getServer();
                    BlockPos soundPos = player != null ? player.getBlockPos() : BlockPos.ORIGIN;
{body}
                }}""")

    src = f"""\
package {pkg}.network;

import io.netty.buffer.Unpooled;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PacketByteBufs;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.network.PacketByteBuf;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.text.Text;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.BlockPos;

public class FabricPyNetwork {{
    public static final Identifier C2S = {_id_ctor(mod, f'"{mod.mod_id}"', '"fabricpy_c2s"')};
    public static final Identifier S2C = {_id_ctor(mod, f'"{mod.mod_id}"', '"fabricpy_s2c"')};

    public static void registerCommon() {{
        ServerPlayNetworking.registerGlobalReceiver(C2S, (server, player, handler, buf, responseSender) -> {{
            String packetId = buf.readString(32767);
            String message = buf.readString(32767);
            server.execute(() -> {{
                switch (packetId) {{
{chr(10).join(server_cases) if server_cases else '                    default -> { }'}
                    default -> {{
                    }}
                }}
            }});
        }});
    }}

    public static void registerClient() {{
        ClientPlayNetworking.registerGlobalReceiver(S2C, (client, handler, buf, responseSender) -> {{
            String packetId = buf.readString(32767);
            String message = buf.readString(32767);
            client.execute(() -> {{
                switch (packetId) {{
{chr(10).join(client_cases) if client_cases else '                    default -> { }'}
                    default -> {{
                    }}
                }}
            }});
        }});
    }}

    public static void sendToServer(String packetId, String message) {{
        PacketByteBuf buf = PacketByteBufs.create();
        buf.writeString(packetId == null ? "" : packetId);
        buf.writeString(message == null ? "" : message);
        ClientPlayNetworking.send(C2S, buf);
    }}

    public static void sendToPlayer(ServerPlayerEntity player, String packetId, String message) {{
        if (player == null) {{
            return;
        }}
        PacketByteBuf buf = new PacketByteBuf(Unpooled.buffer());
        buf.writeString(packetId == null ? "" : packetId);
        buf.writeString(message == null ? "" : message);
        ServerPlayNetworking.send(player, S2C, buf);
    }}

    public static void broadcast(net.minecraft.server.MinecraftServer server, String packetId, String message) {{
        if (server == null) {{
            return;
        }}
        for (ServerPlayerEntity player : server.getPlayerManager().getPlayerList()) {{
            sendToPlayer(player, packetId, message);
        }}
    }}
}}
"""
    _write_text(network_dir / "FabricPyNetwork.java", src)


def _write_screens(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._screens:
        return
    client_dir = java_root / "client"
    client_dir.mkdir(exist_ok=True)
    screen_dir = client_dir / "screen"
    screen_dir.mkdir(exist_ok=True)

    open_lines = []
    for screen in mod._screens:
        cn = f"{to_pascal(screen.screen_id.replace('/', '_'))}Screen"
        open_body = ""
        if screen.open_source:
            open_body = transpiler.transpile_method(screen.open_source)
        button_lines = []
        for button in screen.buttons:
            body = transpiler.transpile_method(button.source) if button.source else "            // No handler"
            button_lines.append(f"""\
        this.addDrawableChild(net.minecraft.client.gui.widget.ButtonWidget.builder(net.minecraft.text.Text.literal({json.dumps(button.text)}), widget -> {{
            var client = this.client;
            var screen = this;
            var player = client != null ? client.player : null;
            var world = client != null ? client.world : null;
            var server = client != null ? client.getServer() : null;
            var buttonObj = widget;
            BlockPos soundPos = player != null ? player.getBlockPos() : BlockPos.ORIGIN;
{body}
        }}).dimensions({button.x}, {button.y}, {button.width}, {button.height}).build());""")
        label_lines = [
            f'        context.drawText(this.textRenderer, net.minecraft.text.Text.literal({json.dumps(label["text"])}), {label["x"]}, {label["y"]}, {label["color"]}, false);'
            for label in screen.labels
        ]
        src = f"""\
package {pkg}.client.screen;

import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;
import net.minecraft.util.math.BlockPos;

public class {cn} extends Screen {{
    public {cn}() {{
        super(Text.literal({json.dumps(screen.title)}));
    }}

    @Override
    protected void init() {{
        super.init();
{f'''        {{
            var client = this.client;
            var screen = this;
            var player = client != null ? client.player : null;
            var world = client != null ? client.world : null;
            var server = client != null ? client.getServer() : null;
            BlockPos soundPos = player != null ? player.getBlockPos() : BlockPos.ORIGIN;
{open_body}
        }}''' if screen.open_source else '        // No on_open handler'}
{chr(10).join(button_lines)}
    }}

    @Override
    public void render(DrawContext context, int mouseX, int mouseY, float delta) {{
        {"this.renderBackground(context, mouseX, mouseY, delta);" if is_at_least(mod.minecraft_version, "1.21") else "this.renderBackground(context);"}
        super.render(context, mouseX, mouseY, delta);
        context.drawCenteredTextWithShadow(this.textRenderer, this.title, this.width / 2, 12, 0xFFFFFF);
{chr(10).join(label_lines) if label_lines else '        // No labels'}
    }}

    @Override
    public boolean shouldPause() {{
        return false;
    }}
}}
"""
        _write_text(screen_dir / f"{cn}.java", src)
        open_lines.append(f'            case "{screen.screen_id}" -> client.setScreen(new {pkg}.client.screen.{cn}());')

    src = f"""\
package {pkg}.client;

import net.minecraft.client.MinecraftClient;

public class ModScreens {{
    public static void openClient(String screenId) {{
        open(MinecraftClient.getInstance(), screenId);
    }}
    public static void closeClient() {{
        MinecraftClient client = MinecraftClient.getInstance();
        if (client != null) client.setScreen(null);
    }}
    public static void open(MinecraftClient client, String screenId) {{
        if (client == null || screenId == null) {{
            return;
        }}
        switch (screenId) {{
{chr(10).join(open_lines)}
            default -> {{
            }}
        }}
    }}
}}
"""
    _write_text(client_dir / "ModScreens.java", src)


def _write_geo_block_renderers(mod: "Mod", java_root: Path, pkg: str):
    geo_blocks = _blocks_with_geo_animation(mod)
    geo_entities = _entities_with_geo_animation(mod)
    if not geo_blocks and not geo_entities:
        return
    client_dir = java_root / "client"
    client_dir.mkdir(exist_ok=True)
    model_dir = client_dir / "model"
    model_dir.mkdir(exist_ok=True)
    renderer_dir = client_dir / "renderer"
    renderer_dir.mkdir(exist_ok=True)

    registration_lines = []
    for block in geo_blocks:
        cn = block.get_class_name()
        model_cn = f"{cn}GeoModel"
        renderer_cn = f"{cn}GeoRenderer"
        model_ns, model_path = _geo_model_parts(mod.mod_id, block)
        tex_ns, tex_path = _geo_texture_parts(mod.mod_id, block)
        anim_ns, anim_path = _geo_animation_parts(mod.mod_id, block)
        model_src = f"""\
package {pkg}.client.model;

import {pkg}.blockentity.{cn}BlockEntity;
import net.minecraft.util.Identifier;
import software.bernie.geckolib.model.GeoModel;

public class {model_cn} extends GeoModel<{cn}BlockEntity> {{
    private Identifier parseRef(String raw, String fallbackNamespace, String fallbackPath) {{
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {{
            return {_id_ctor(mod, "fallbackNamespace", "fallbackPath")};
        }}
        int split = value.indexOf(':');
        if (split >= 0) {{
            return {_id_ctor(mod, "value.substring(0, split)", "value.substring(split + 1)")};
        }}
        return {_id_ctor(mod, f'"{mod.mod_id}"', "value")};
    }}

    @Override
    public Identifier getModelResource({cn}BlockEntity animatable) {{
        return parseRef(animatable.getModelOverride(), "{model_ns}", "{model_path}");
    }}

    @Override
    public Identifier getTextureResource({cn}BlockEntity animatable) {{
        return parseRef(animatable.getTextureOverride(), "{tex_ns}", "{tex_path}");
    }}

    @Override
    public Identifier getAnimationResource({cn}BlockEntity animatable) {{
        return {_id_ctor(mod, f'"{anim_ns}"', f'"{anim_path}"')};
    }}
}}
"""
        _write_text(model_dir / f"{model_cn}.java", model_src)

        renderer_src = f"""\
package {pkg}.client.renderer;

import {pkg}.blockentity.{cn}BlockEntity;
import {pkg}.client.model.{model_cn};
import net.minecraft.client.render.VertexConsumer;
import net.minecraft.client.render.RenderLayer;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.util.Identifier;
import software.bernie.geckolib.cache.object.BakedGeoModel;
import software.bernie.geckolib.core.object.Color;
import software.bernie.geckolib.renderer.GeoBlockRenderer;

public class {renderer_cn} extends GeoBlockRenderer<{cn}BlockEntity> {{
    public {renderer_cn}() {{
        super(new {model_cn}());
    }}

    @Override
    public RenderLayer getRenderType({cn}BlockEntity animatable, Identifier texture, VertexConsumerProvider bufferSource, float partialTick) {{
        return {_fabric_render_layer_expr(getattr(block, "render_layer", "translucent" if not block.opaque else "solid"))};
    }}

    @Override
    public void preRender(MatrixStack poseStack, {cn}BlockEntity animatable, BakedGeoModel model, VertexConsumerProvider bufferSource, VertexConsumer buffer, boolean isReRender, float partialTick, int packedLight, int packedOverlay, float red, float green, float blue, float alpha) {{
        poseStack.translate({getattr(block, "render_offset_x", 0.0)}d, {getattr(block, "render_offset_y", 0.0)}d, {getattr(block, "render_offset_z", 0.0)}d);
        poseStack.scale({float(getattr(block, "render_scale_x", 1.0))}f, {float(getattr(block, "render_scale_y", 1.0))}f, {float(getattr(block, "render_scale_z", 1.0))}f);
        super.preRender(poseStack, animatable, model, bufferSource, buffer, isReRender, partialTick, packedLight, packedOverlay, red, green, blue, alpha);
    }}

    @Override
    public Color getRenderColor({cn}BlockEntity animatable, float partialTick, int packedLight) {{
        return Color.ofRGBA({float(getattr(block, "render_tint_r", 1.0))}f, {float(getattr(block, "render_tint_g", 1.0))}f, {float(getattr(block, "render_tint_b", 1.0))}f, {float(getattr(block, "render_tint_a", 1.0))}f);
    }}
}}
"""
        _write_text(renderer_dir / f"{renderer_cn}.java", renderer_src)
        registration_lines.append(
            f"        net.minecraft.client.render.block.entity.BlockEntityRendererFactories.register({pkg}.blockentity.ModBlockEntities.{block.block_id.upper()}, ctx -> new {pkg}.client.renderer.{renderer_cn}());"
        )

    for entity in geo_entities:
        cn = entity.get_class_name()
        model_cn = f"{cn}GeoModel"
        renderer_cn = f"{cn}GeoRenderer"
        model_ns, model_path = _geo_entity_model_parts(mod.mod_id, entity)
        tex_ns, tex_path = _geo_entity_texture_parts(mod.mod_id, entity)
        anim_ns, anim_path = _geo_entity_animation_parts(mod.mod_id, entity)
        model_src = f"""\
package {pkg}.client.model;

import {pkg}.entity.{cn};
import net.minecraft.util.Identifier;
import software.bernie.geckolib.model.GeoModel;

public class {model_cn} extends GeoModel<{cn}> {{
    private Identifier parseRef(String raw, String fallbackNamespace, String fallbackPath) {{
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {{
            return {_id_ctor(mod, "fallbackNamespace", "fallbackPath")};
        }}
        int split = value.indexOf(':');
        if (split >= 0) {{
            return {_id_ctor(mod, "value.substring(0, split)", "value.substring(split + 1)")};
        }}
        return {_id_ctor(mod, f'"{mod.mod_id}"', "value")};
    }}

    @Override
    public Identifier getModelResource({cn} animatable) {{
        return parseRef(animatable.getModelOverride(), "{model_ns}", "{model_path}");
    }}

    @Override
    public Identifier getTextureResource({cn} animatable) {{
        return parseRef(animatable.getTextureOverride(), "{tex_ns}", "{tex_path}");
    }}

    @Override
    public Identifier getAnimationResource({cn} animatable) {{
        return {_id_ctor(mod, f'"{anim_ns}"', f'"{anim_path}"')};
    }}
}}
"""
        _write_text(model_dir / f"{model_cn}.java", model_src)

        renderer_src = f"""\
package {pkg}.client.renderer;

import {pkg}.client.model.{model_cn};
import {pkg}.entity.{cn};
import net.minecraft.client.render.VertexConsumer;
import net.minecraft.client.render.RenderLayer;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.render.entity.EntityRendererFactory;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.util.Identifier;
import software.bernie.geckolib.cache.object.BakedGeoModel;
import software.bernie.geckolib.core.object.Color;
import software.bernie.geckolib.renderer.GeoEntityRenderer;

public class {renderer_cn} extends GeoEntityRenderer<{cn}> {{
    public {renderer_cn}(EntityRendererFactory.Context ctx) {{
        super(ctx, new {model_cn}());
        this.shadowRadius = {getattr(entity, "shadow_radius", 0.5)}f;
    }}

    @Override
    public RenderLayer getRenderType({cn} animatable, Identifier texture, VertexConsumerProvider bufferSource, float partialTick) {{
        return {_fabric_render_layer_expr(getattr(entity, "render_layer", "solid"))};
    }}

    @Override
    public void preRender(MatrixStack poseStack, {cn} animatable, BakedGeoModel model, VertexConsumerProvider bufferSource, VertexConsumer buffer, boolean isReRender, float partialTick, int packedLight, int packedOverlay, float red, float green, float blue, float alpha) {{
        poseStack.translate({getattr(entity, "render_offset_x", 0.0)}d, {getattr(entity, "render_offset_y", 0.0)}d, {getattr(entity, "render_offset_z", 0.0)}d);
        poseStack.scale({float(getattr(entity, "render_scale_x", 1.0))}f, {float(getattr(entity, "render_scale_y", 1.0))}f, {float(getattr(entity, "render_scale_z", 1.0))}f);
        super.preRender(poseStack, animatable, model, bufferSource, buffer, isReRender, partialTick, packedLight, packedOverlay, red, green, blue, alpha);
    }}

    @Override
    public Color getRenderColor({cn} animatable, float partialTick, int packedLight) {{
        return Color.ofRGBA({float(getattr(entity, "render_tint_r", 1.0))}f, {float(getattr(entity, "render_tint_g", 1.0))}f, {float(getattr(entity, "render_tint_b", 1.0))}f, {float(getattr(entity, "render_tint_a", 1.0))}f);
    }}
}}
"""
        _write_text(renderer_dir / f"{renderer_cn}.java", renderer_src)
        registration_lines.append(
            f"        net.fabricmc.fabric.api.client.rendering.v1.EntityRendererRegistry.register({pkg}.entity.ModEntities.{entity.entity_id.upper()}, ctx -> new {pkg}.client.renderer.{renderer_cn}(ctx));"
        )

    register_src = f"""\
package {pkg}.client;

public class ModGeoRenderers {{
    public static void registerClient() {{
{chr(10).join(registration_lines)}
    }}
}}
"""
    _write_text(client_dir / "ModGeoRenderers.java", register_src)


def _write_mod_keybinds(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._keybinds:
        return
    client_dir = java_root / "client"
    client_dir.mkdir(exist_ok=True)
    declarations = []
    handlers = []
    for bind in mod._keybinds:
        const_name = bind.keybind_id.replace("/", "_").upper()
        title_key = f"key.{mod.mod_id}.{bind.keybind_id.replace('/', '.')}"
        category_key = f"key.categories.{bind.category.replace('/', '.')}"
        declarations.append(
            f'    public static final KeyBinding {const_name} = KeyBindingHelper.registerKeyBinding('
            f'new KeyBinding("{title_key}", InputUtil.Type.KEYSYM, {_keybind_code_expr(bind)}, "{category_key}"));'
        )
        if bind.source:
            body = transpiler.transpile_method(bind.source)
            handlers.append(f"""\
            while ({const_name}.wasPressed()) {{
                if (client.player == null || client.world == null) {{
                    continue;
                }}
                var player = client.player;
                var world = client.world;
                var server = client.getServer();
                var keybind = {const_name};
                BlockPos soundPos = player.getBlockPos();
{body}
            }}""")
    src = f"""\
package {pkg}.client;

import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import net.minecraft.util.math.BlockPos;
import org.lwjgl.glfw.GLFW;
{chr(10).join(FABRIC_EXTRA_IMPORTS)}

public class ModKeybinds {{
{chr(10).join(declarations)}

    public static void registerClient() {{
        ClientTickEvents.END_CLIENT_TICK.register(client -> {{
{chr(10).join(handlers) if handlers else "            // No keybind handlers"}
        }});
    }}
}}
"""
    _write_text(client_dir / "ModKeybinds.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Block registry
# ─────────────────────────────────────────────────────────────────────────── #

def _write_mod_blocks(mod: "Mod", java_root: Path, pkg: str):
    if not mod._blocks:
        return

    pkg_block = f"{pkg}.block"
    imports = [f"import {pkg_block}.{b.get_class_name()};" for b in mod._blocks]
    registrations = []
    for b in mod._blocks:
        cn = b.get_class_name()
        bid = b.block_id
        registrations.append(
            f'    public static final {cn} {bid.upper()} = register("{bid}", new {cn}());'
        )

    block_item_regs = []
    for b in mod._blocks:
        if b.drops_self:
            bid = b.block_id
            item_id_expr = _id_ctor(mod, f"{to_pascal(mod.mod_id)}.MOD_ID", f'"{bid}"')
            block_item_regs.append(
                f'        Registry.register(Registries.ITEM, {item_id_expr}, '
                f'new BlockItem({bid.upper()}, new Item.Settings()));'
            )

    src = f"""\
package {pkg};

import net.minecraft.block.Block;
import net.minecraft.item.BlockItem;
import net.minecraft.item.Item;
import net.minecraft.item.ItemGroups;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;
import net.fabricmc.fabric.api.itemgroup.v1.ItemGroupEvents;
{chr(10).join(imports)}

/**
 * Registers all blocks for {mod.name}.
 */
public class ModBlocks {{
{chr(10).join(registrations)}

    private static <T extends Block> T register(String id, T block) {{
        Registry.register(Registries.BLOCK, {_id_ctor(mod, f"{to_pascal(mod.mod_id)}.MOD_ID", "id")}, block);
        return block;
    }}

    public static void register() {{
        // Blocks are registered via static initializer above.
        // Register block items:
{chr(10).join(block_item_regs) if block_item_regs else "        // No block items"}
{chr(10).join([f"        ItemGroupEvents.modifyEntriesEvent(ItemGroups.BUILDING_BLOCKS).register(entries -> entries.add({b.block_id.upper()}));" for b in mod._blocks])}
    }}
}}
"""
    _write_text(java_root / "ModBlocks.java", src)


def _write_mod_block_entities(mod: "Mod", java_root: Path, pkg: str):
    block_entities = _blocks_with_block_entities(mod)
    if not block_entities:
        return

    be_dir = java_root / "blockentity"
    be_dir.mkdir(exist_ok=True)
    imports = [f"import {pkg}.blockentity.{block.get_class_name()}BlockEntity;" for block in block_entities]
    registrations = []
    for block in block_entities:
        id_expr = _id_ctor(mod, f"{to_pascal(mod.mod_id)}.MOD_ID", f'"{block.block_id}"')
        registrations.append(
            f"    public static final BlockEntityType<{block.get_class_name()}BlockEntity> {block.block_id.upper()} = "
            f"Registry.register(Registries.BLOCK_ENTITY_TYPE, {id_expr}, "
            f"FabricBlockEntityTypeBuilder.create({block.get_class_name()}BlockEntity::new, ModBlocks.{block.block_id.upper()}).build());"
        )

    src = f"""\
package {pkg}.blockentity;

import {pkg}.{to_pascal(mod.mod_id)};
import {pkg}.ModBlocks;
import net.fabricmc.fabric.api.object.builder.v1.block.entity.FabricBlockEntityTypeBuilder;
import net.minecraft.block.entity.BlockEntityType;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;
{chr(10).join(imports)}

public class ModBlockEntities {{
{chr(10).join(registrations)}

    public static void register() {{
        // Block entities are registered via static fields above.
    }}
}}
"""
    _write_text(be_dir / "ModBlockEntities.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Item registry
# ─────────────────────────────────────────────────────────────────────────── #

def _write_mod_items(mod: "Mod", java_root: Path, pkg: str, loader_name: str = "fabric"):
    if not mod._items:
        return

    pkg_item = f"{pkg}.item"
    imports = [f"import {pkg_item}.{i.get_class_name()};" for i in mod._items]
    registrations = []
    for it in mod._items:
        cn = it.get_class_name()
        iid = it.item_id
        registrations.append(
            f'    public static final {cn} {iid.upper()} = register("{iid}", new {cn}());'
        )

    registrations.extend(attachment_proxy_registrations(mod, loader_name))

    src = f"""\
package {pkg};

import net.minecraft.item.Item;
import net.minecraft.item.ItemGroups;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;
import net.fabricmc.fabric.api.itemgroup.v1.ItemGroupEvents;
{chr(10).join(imports)}

/**
 * Registers all items for {mod.name}.
 */
public class ModItems {{
{chr(10).join(registrations)}

    private static <T extends Item> T register(String id, T item) {{
        return Registry.register(Registries.ITEM, {_id_ctor(mod, f"{to_pascal(mod.mod_id)}.MOD_ID", "id")}, item);
    }}

    public static void register() {{
        // Items registered via static fields above.
{chr(10).join([f"        ItemGroupEvents.modifyEntriesEvent(ItemGroups.INGREDIENTS).register(entries -> entries.add({it.item_id.upper()}));" for it in mod._items])}
    }}
}}
"""
    _write_text(java_root / "ModItems.java", src)


def _item_lookup_expr(mod: "Mod", item_ref: str) -> str:
    ref = (item_ref or "").strip()
    if not ref:
        return "net.minecraft.item.Items.AIR"
    if ":" in ref:
        namespace, path = ref.split(":", 1)
    else:
        namespace, path = mod.mod_id, ref
    for item in mod._items:
        if namespace == mod.mod_id and item.item_id == path:
            return f"ModItems.{item.item_id.upper()}"
    namespace_expr = f"\"{namespace}\""
    path_expr = f"\"{path}\""
    return f"Registries.ITEM.get({_id_ctor(mod, namespace_expr, path_expr)})"


def _write_mod_creative_tabs(mod: "Mod", java_root: Path, pkg: str):
    if not mod._creative_tabs:
        return

    class_name = to_pascal(mod.mod_id)
    registrations = []
    for tab in mod._creative_tabs:
        const_name = tab.tab_id.replace("/", "_").upper()
        title_key = f"itemGroup.{mod.mod_id}.{tab.tab_id.replace('/', '.')}"
        entry_lines = [
            f"                entries.add({_item_lookup_expr(mod, item_ref)});"
            for item_ref in tab.items
        ] or ["                // No explicit items"]
        registrations.append(
            f"""    public static final ItemGroup {const_name} = Registry.register(
        Registries.ITEM_GROUP,
        {_id_ctor(mod, f"{class_name}.MOD_ID", f'"{tab.tab_id}"')},
        FabricItemGroup.builder()
            .displayName(Text.translatable("{title_key}"))
            .icon(() -> new ItemStack({_item_lookup_expr(mod, tab.icon_item)}))
            .entries((displayContext, entries) -> {{
{chr(10).join(entry_lines)}
            }})
            .build()
    );"""
        )

    src = f"""\
package {pkg};

import net.fabricmc.fabric.api.itemgroup.v1.FabricItemGroup;
import net.minecraft.util.Identifier;
import net.minecraft.item.ItemGroup;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.text.Text;

public class ModCreativeTabs {{
{chr(10).join(registrations)}

    public static void register() {{
        // Creative tabs are registered via static fields above.
    }}
}}
"""
    _write_text(java_root / "ModCreativeTabs.java", src)


def _write_mod_entities(mod: "Mod", java_root: Path, pkg: str):
    if not mod._entities:
        return

    entity_dir = java_root / "entity"
    entity_dir.mkdir(exist_ok=True)
    imports = [f"import {pkg}.entity.{entity.get_class_name()};" for entity in mod._entities]
    registrations = []
    attribute_regs = []
    for entity in mod._entities:
        flags = []
        if entity.fireproof:
            flags.append(".fireImmune()")
        id_expr = _id_ctor(mod, f"{to_pascal(mod.mod_id)}.MOD_ID", f'"{entity.entity_id}"')
        registrations.append(
            f"    public static final EntityType<{entity.get_class_name()}> {entity.entity_id.upper()} = "
            f"Registry.register(Registries.ENTITY_TYPE, {id_expr}, "
            f"FabricEntityTypeBuilder.create({_fabric_spawn_group(entity.spawn_group)}, {entity.get_class_name()}::new)"
            f".dimensions(EntityDimensions.fixed({entity.width}f, {entity.height}f))"
            f".trackRangeBlocks({entity.tracking_range})"
            f".trackedUpdateRate({entity.update_rate})"
            f"{''.join(flags)}"
            f".build());"
        )
        attribute_regs.append(
            f"        FabricDefaultAttributeRegistry.register({entity.entity_id.upper()}, {entity.get_class_name()}.createAttributes());"
        )

    src = f"""\
package {pkg}.entity;

import {pkg}.{to_pascal(mod.mod_id)};
import net.fabricmc.fabric.api.object.builder.v1.entity.FabricDefaultAttributeRegistry;
import net.fabricmc.fabric.api.object.builder.v1.entity.FabricEntityTypeBuilder;
import net.minecraft.entity.EntityDimensions;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.SpawnGroup;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;
{chr(10).join(imports)}

public class ModEntities {{
{chr(10).join(registrations)}

    public static void register() {{
{chr(10).join(attribute_regs)}
    }}
}}
"""
    _write_text(entity_dir / "ModEntities.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Individual Block classes
# ─────────────────────────────────────────────────────────────────────────── #

_SOUND_MAP = {
    "stone": "BlockSoundGroup.STONE",
    "wood": "BlockSoundGroup.WOOD",
    "sand": "BlockSoundGroup.SAND",
    "wool": "BlockSoundGroup.WOOL",
    "metal": "BlockSoundGroup.METAL",
    "glass": "BlockSoundGroup.GLASS",
    "grass": "BlockSoundGroup.GRASS",
    "gravel": "BlockSoundGroup.GRAVEL",
    "snow": "BlockSoundGroup.SNOW",
}


def _write_block_classes(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._blocks:
        return
    block_dir = java_root / "block"
    block_dir.mkdir(exist_ok=True)
    block_entity_dir = java_root / "blockentity"
    block_entity_dir.mkdir(exist_ok=True)

    for block in mod._blocks:
        _write_single_block(mod, block, block_dir, pkg, transpiler)
        if block.has_block_entity or getattr(block, "uses_block_data", False) or "on_tick" in block.get_hooks():
            _write_single_block_entity(mod, block, block_entity_dir, pkg, transpiler)


def _write_single_block(mod, block, block_dir: Path, pkg: str, transpiler: JavaTranspiler):
    cn = block.get_class_name()
    pkg_block = f"{pkg}.block"
    hooks = block.get_hooks()
    has_block_entity = block.has_block_entity or getattr(block, "uses_block_data", False) or bool(getattr(block, "geo_model", "")) or "on_tick" in hooks
    uses_rotation = getattr(block, "variable_rotation", False)
    uses_model_shapes = uses_rotation or getattr(block, "model_collision", False)
    shape_boxes = _model_boxes_for_block(Path.cwd(), mod, block) if uses_model_shapes else {}
    has_shape_boxes = bool(shape_boxes)

    # Build FabricBlockSettings chain
    settings_chain = (
        f"FabricBlockSettings.create()"
        f".strength({block.hardness}f, {block.resistance}f)"
        f".luminance(state -> {_block_light_level(block)})"
        f".slipperiness({block.slipperiness}f)"
        f".sounds({_SOUND_MAP.get(block.sound_group, 'BlockSoundGroup.STONE')})"
    )
    if not block.collidable:
        settings_chain += ".noCollision()"
    if block.requires_tool:
        settings_chain += ".requiresTool()"
    if not block.opaque:
        settings_chain += ".nonOpaque()"

    shape_fields = []
    if has_shape_boxes:
        if uses_rotation:
            for facing in ("north", "east", "south", "west"):
                if facing in shape_boxes:
                    shape_fields.append(_fabric_shape_code(f"SHAPE_{facing.upper()}", shape_boxes[facing]))
        elif "default" in shape_boxes:
            shape_fields.append(_fabric_shape_code("SHAPE_DEFAULT", shape_boxes["default"]))
    shape_fields_str = "\n".join(shape_fields)

    # Generate hook methods
    method_blocks = []

    if "on_use" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_use"])
        )
        body = guard_hook_body(body, hooks["on_use"], "world.isClient")
        method_blocks.append(f"""\
    @Override
    public ActionResult onUse(BlockState state, World world, BlockPos pos,
                               PlayerEntity player, Hand hand, BlockHitResult hit) {{
        ItemStack stack = player.getStackInHand(hand);
        {f"{cn}BlockEntity blockEntity = world.getBlockEntity(pos) instanceof {cn}BlockEntity be ? be : null;" if has_block_entity else ""}
        BlockPos soundPos = pos;
{body}
        return ActionResult.SUCCESS;
    }}""")

    if "on_place" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_place"])
        )
        body = guard_hook_body(body, hooks["on_place"], "world.isClient")
        method_blocks.append(f"""\
    @Override
    public void onPlaced(World world, BlockPos pos, BlockState state,
                         @Nullable LivingEntity placer, ItemStack itemStack) {{
        PlayerEntity player = placer instanceof PlayerEntity ? (PlayerEntity) placer : null;
        {f"{cn}BlockEntity blockEntity = world.getBlockEntity(pos) instanceof {cn}BlockEntity be ? be : null;" if has_block_entity else ""}
        BlockPos soundPos = pos;
{body}
    }}""")

    if "on_break" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_break"])
        )
        body = guard_hook_body(body, hooks["on_break"], "world.isClient")
        method_blocks.append(f"""\
    @Override
    public void onBreak(World world, BlockPos pos, BlockState state, PlayerEntity player) {{
        {f"{cn}BlockEntity blockEntity = world.getBlockEntity(pos) instanceof {cn}BlockEntity be ? be : null;" if has_block_entity else ""}
        BlockPos soundPos = pos;
{body}
        super.onBreak(world, pos, state, player);
    }}""")

    methods_str = "\n\n".join(method_blocks)
    extra_imports = ""
    base_class = "Block"
    extra_methods = ""
    state_members = ""
    state_methods = ""
    if uses_rotation:
        state_members = """
    public static final DirectionProperty FACING = Properties.HORIZONTAL_FACING;
"""
        constructor_default_state = f"""
        setDefaultState(getStateManager().getDefaultState().with(FACING, Direction.NORTH));"""
        placement_return = "        return getDefaultState().with(FACING, ctx.getHorizontalPlayerFacing().getOpposite());"
        shape_selector = "state.get(FACING).asString().toUpperCase()"
        outline_shape_expr = (
            "switch (state.get(FACING)) {\n"
            "            case NORTH -> SHAPE_NORTH;\n"
            "            case EAST -> SHAPE_EAST;\n"
            "            case SOUTH -> SHAPE_SOUTH;\n"
            "            case WEST -> SHAPE_WEST;\n"
            "            default -> VoxelShapes.fullCube();\n"
            "        }"
            if has_shape_boxes
            else "super.getOutlineShape(state, world, pos, context)"
        )
        collision_shape_expr = (
            "switch (state.get(FACING)) {\n"
            "            case NORTH -> SHAPE_NORTH;\n"
            "            case EAST -> SHAPE_EAST;\n"
            "            case SOUTH -> SHAPE_SOUTH;\n"
            "            case WEST -> SHAPE_WEST;\n"
            "            default -> VoxelShapes.fullCube();\n"
            "        }"
            if has_shape_boxes
            else "super.getCollisionShape(state, world, pos, context)"
        )
        state_methods = f"""
    @Override
    protected void appendProperties(StateManager.Builder<Block, BlockState> builder) {{
        builder.add(FACING);
    }}

    @Override
    public BlockState getPlacementState(ItemPlacementContext ctx) {{
{placement_return}
    }}

    @Override
    public VoxelShape getOutlineShape(BlockState state, BlockView world, BlockPos pos, ShapeContext context) {{
        return {outline_shape_expr};
    }}"""
        if getattr(block, "model_collision", False) and has_shape_boxes and block.collidable:
            state_methods += f"""

    @Override
    public VoxelShape getCollisionShape(BlockState state, BlockView world, BlockPos pos, ShapeContext context) {{
        return {collision_shape_expr};
    }}"""
    else:
        constructor_default_state = ""
        if has_shape_boxes:
            state_methods += """
    @Override
    public VoxelShape getOutlineShape(BlockState state, BlockView world, BlockPos pos, ShapeContext context) {
        return SHAPE_DEFAULT;
    }"""
        if getattr(block, "model_collision", False) and has_shape_boxes and block.collidable:
            state_methods += """

    @Override
    public VoxelShape getCollisionShape(BlockState state, BlockView world, BlockPos pos, ShapeContext context) {
        return SHAPE_DEFAULT;
    }"""
    if has_block_entity:
        base_class = "BlockWithEntity"
        extra_imports = f"""
import {pkg}.blockentity.{cn}BlockEntity;
import {pkg}.blockentity.ModBlockEntities;
import net.minecraft.block.BlockRenderType;
import net.minecraft.block.BlockWithEntity;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.block.entity.BlockEntityTicker;
import net.minecraft.block.entity.BlockEntityType;"""
        codec_members = ""
        if is_at_least(mod.minecraft_version, "1.21"):
            extra_imports += """
import com.mojang.serialization.MapCodec;"""
            codec_members = f"""
    public static final MapCodec<{cn}> CODEC = MapCodec.unit(new {cn}());

    @Override
    protected MapCodec<? extends BlockWithEntity> getCodec() {{
        return CODEC;
    }}
"""
        ticker_body = "        return null;"
        if "on_tick" in hooks:
            ticker_body = (
                f"        return type == ModBlockEntities.{block.block_id.upper()} "
                f'? (world1, pos1, state1, be) -> {cn}BlockEntity.tick(world1, pos1, state1, ({cn}BlockEntity) be) : null;'
            )
        render_type_return = "BlockRenderType.ENTITYBLOCK_ANIMATED" if getattr(block, "geo_model", "") else "BlockRenderType.MODEL"
        extra_methods = f"""{codec_members}
    @Override
    public BlockEntity createBlockEntity(BlockPos pos, BlockState state) {{
        return new {cn}BlockEntity(pos, state);
    }}

    @Override
    public BlockRenderType getRenderType(BlockState state) {{
        return {render_type_return};
    }}

    @Override
    @Nullable
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(World world, BlockState state, BlockEntityType<T> type) {{
{ticker_body}
    }}"""

    src = f"""\
package {pkg_block};

import net.fabricmc.fabric.api.object.builder.v1.block.FabricBlockSettings;
import net.minecraft.block.Block;
import net.minecraft.block.BlockState;
import net.minecraft.block.ShapeContext;
import net.minecraft.sound.BlockSoundGroup;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.item.ItemPlacementContext;
import net.minecraft.text.Text;
import net.minecraft.util.ActionResult;
import net.minecraft.util.Hand;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.world.World;
import net.minecraft.world.BlockView;
import net.minecraft.sound.SoundCategory;
import net.minecraft.sound.SoundEvents;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.registry.Registries;
import net.minecraft.state.StateManager;
import net.minecraft.state.property.DirectionProperty;
import net.minecraft.state.property.Properties;
import net.minecraft.util.Identifier;
import net.minecraft.util.shape.VoxelShape;
import net.minecraft.util.shape.VoxelShapes;
import org.jetbrains.annotations.Nullable;
import java.util.Set;
{extra_imports}

/**
 * {block.get_display_name()} — generated by fabricpy
 */
public class {cn} extends {base_class} {{
{state_members}
{shape_fields_str}

    public {cn}() {{
        super({settings_chain});
{constructor_default_state}
    }}

{methods_str}
{state_methods}
{extra_methods}
}}
"""
    _write_text(block_dir / f"{cn}.java", src)


def _write_single_block_entity(mod, block, block_entity_dir: Path, pkg: str, transpiler: JavaTranspiler):
    cn = block.get_class_name()
    hooks = block.get_hooks()
    data_methods = ""
    data_imports = """
import net.minecraft.nbt.NbtCompound;
import net.minecraft.block.Block;"""
    if is_at_least(mod.minecraft_version, "1.21"):
        data_imports += """
import net.minecraft.registry.RegistryWrapper;"""
        data_methods = """
    private NbtCompound fabricpyData = new NbtCompound();

    public String getStringData(String key) {
        return fabricpyData.getString(key);
    }

    public String getTextureOverride() {
        return getStringData("__fabricpy_texture");
    }

    public void setTextureOverride(String value) {
        setStringData("__fabricpy_texture", value);
    }

    public String getModelOverride() {
        return getStringData("__fabricpy_model");
    }

    public void setModelOverride(String value) {
        setStringData("__fabricpy_model", value);
    }

    public void setStringData(String key, String value) {
        fabricpyData.putString(key, value);
        markDirty();
    }

    public int getIntData(String key) {
        return fabricpyData.getInt(key);
    }

    public void setIntData(String key, int value) {
        fabricpyData.putInt(key, value);
        markDirty();
    }

    public boolean getBoolData(String key) {
        return fabricpyData.getBoolean(key);
    }

    public void setBoolData(String key, boolean value) {
        fabricpyData.putBoolean(key, value);
        markDirty();
    }

    public double getDoubleData(String key) {
        return fabricpyData.getDouble(key);
    }

    public void setDoubleData(String key, double value) {
        fabricpyData.putDouble(key, value);
        markDirty();
    }

    public boolean hasData(String key) {
        return fabricpyData.contains(key);
    }

    public void removeData(String key) {
        fabricpyData.remove(key);
        markDirty();
    }

    public void syncData() {
        markDirty();
        if (world != null) {
            world.updateListeners(pos, getCachedState(), getCachedState(), Block.NOTIFY_LISTENERS);
        }
    }

    @Override
    protected void writeNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registries) {
        super.writeNbt(nbt, registries);
        nbt.put("fabricpy_data", fabricpyData.copy());
    }

    @Override
    public void readNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registries) {
        super.readNbt(nbt, registries);
        this.fabricpyData = nbt.contains("fabricpy_data") ? nbt.getCompound("fabricpy_data").copy() : new NbtCompound();
    }"""
    else:
        data_methods = """
    private NbtCompound fabricpyData = new NbtCompound();

    public String getStringData(String key) {
        return fabricpyData.getString(key);
    }

    public String getTextureOverride() {
        return getStringData("__fabricpy_texture");
    }

    public void setTextureOverride(String value) {
        setStringData("__fabricpy_texture", value);
    }

    public String getModelOverride() {
        return getStringData("__fabricpy_model");
    }

    public void setModelOverride(String value) {
        setStringData("__fabricpy_model", value);
    }

    public void setStringData(String key, String value) {
        fabricpyData.putString(key, value);
        markDirty();
    }

    public int getIntData(String key) {
        return fabricpyData.getInt(key);
    }

    public void setIntData(String key, int value) {
        fabricpyData.putInt(key, value);
        markDirty();
    }

    public boolean getBoolData(String key) {
        return fabricpyData.getBoolean(key);
    }

    public void setBoolData(String key, boolean value) {
        fabricpyData.putBoolean(key, value);
        markDirty();
    }

    public double getDoubleData(String key) {
        return fabricpyData.getDouble(key);
    }

    public void setDoubleData(String key, double value) {
        fabricpyData.putDouble(key, value);
        markDirty();
    }

    public boolean hasData(String key) {
        return fabricpyData.contains(key);
    }

    public void removeData(String key) {
        fabricpyData.remove(key);
        markDirty();
    }

    public void syncData() {
        markDirty();
        if (world != null) {
            world.updateListeners(pos, getCachedState(), getCachedState(), Block.NOTIFY_LISTENERS);
        }
    }

    @Override
    public void writeNbt(NbtCompound nbt) {
        super.writeNbt(nbt);
        nbt.put("fabricpy_data", fabricpyData.copy());
    }

    @Override
    public void readNbt(NbtCompound nbt) {
        super.readNbt(nbt);
        this.fabricpyData = nbt.contains("fabricpy_data") ? nbt.getCompound("fabricpy_data").copy() : new NbtCompound();
    }"""
    if getattr(block, "geo_model", ""):
        data_imports += """
import software.bernie.geckolib.animatable.GeoBlockEntity;
import software.bernie.geckolib.core.animatable.instance.AnimatableInstanceCache;
import software.bernie.geckolib.core.animation.AnimatableManager;
import software.bernie.geckolib.core.animation.AnimationController;
import software.bernie.geckolib.core.animation.RawAnimation;
import software.bernie.geckolib.core.object.PlayState;"""
        default_animation = getattr(block, "default_animation", "")
        data_methods = data_methods.replace(
            "private NbtCompound fabricpyData = new NbtCompound();",
            "private NbtCompound fabricpyData = new NbtCompound();\n    private final AnimatableInstanceCache geoCache = software.bernie.geckolib.util.GeckoLibUtil.createInstanceCache(this);",
            1,
        )
        data_methods += f"""

    public String getAnimationName() {{
        return getStringData("__fabricpy_animation");
    }}

    public void setAnimationState(String animationName, boolean loop) {{
        setStringData("__fabricpy_animation", animationName == null ? "" : animationName);
        setBoolData("__fabricpy_animation_loop", loop);
        syncData();
    }}

    public void clearAnimationName() {{
        removeData("__fabricpy_animation");
        removeData("__fabricpy_animation_loop");
        syncData();
    }}

    @Override
    public void registerControllers(AnimatableManager.ControllerRegistrar controllers) {{
        controllers.add(new AnimationController<>(this, "controller", 0, state -> {{
            String animationName = getAnimationName();
            if ((animationName == null || animationName.isEmpty()) && !"{default_animation}".isEmpty()) {{
                animationName = "{default_animation}";
            }}
            if (animationName == null || animationName.isEmpty()) {{
                return PlayState.STOP;
            }}
            boolean loop = !hasData("__fabricpy_animation_loop") || getBoolData("__fabricpy_animation_loop");
            RawAnimation animation = loop
                ? RawAnimation.begin().thenLoop(animationName)
                : RawAnimation.begin().thenPlay(animationName);
            return state.setAndContinue(animation);
        }}));
    }}

    @Override
    public AnimatableInstanceCache getAnimatableInstanceCache() {{
        return geoCache;
    }}"""
    tick_method = ""
    if "on_tick" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_tick"])
        )
        tick_method = f"""
    public static void tick(World world, BlockPos pos, BlockState state, {cn}BlockEntity blockEntity) {{
        BlockPos soundPos = pos;
{body}
    }}"""

    src = f"""\
package {pkg}.blockentity;

import net.minecraft.block.BlockState;
{data_imports}
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.World;

/**
 * Block entity backing {block.get_display_name()}.
 */
public class {cn}BlockEntity extends BlockEntity{" implements GeoBlockEntity" if getattr(block, "geo_model", "") else ""} {{

    public {cn}BlockEntity(BlockPos pos, BlockState state) {{
        super(ModBlockEntities.{block.block_id.upper()}, pos, state);
    }}
{data_methods}
{tick_method}
}}
"""
    _write_text(block_entity_dir / f"{cn}BlockEntity.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Individual Item classes
# ─────────────────────────────────────────────────────────────────────────── #

_RARITY_MAP = {
    "common": "Rarity.COMMON",
    "uncommon": "Rarity.UNCOMMON",
    "rare": "Rarity.RARE",
    "epic": "Rarity.EPIC",
}


def _write_item_classes(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler, loader_name: str = "fabric"):
    if not mod._items:
        return
    item_dir = java_root / "item"
    item_dir.mkdir(exist_ok=True)

    for item in mod._items:
        _write_single_item(mod, item, item_dir, pkg, transpiler, loader_name)


def _write_single_item(mod, item, item_dir: Path, pkg: str, transpiler: JavaTranspiler, loader_name: str = "fabric"):
    if write_music_disc_class(mod, item, item_dir, pkg, loader_name):
        return
    cn = item.get_class_name()
    pkg_item = f"{pkg}.item"
    hooks = item.get_hooks()

    settings_chain = f"new Item.Settings().maxCount({effective_stack_size(item)})"
    if item.max_damage > 0:
        settings_chain += f".maxDamage({item.max_damage})"
    rarity_java = _RARITY_MAP.get(item.rarity, "Rarity.COMMON")
    settings_chain += f".rarity({rarity_java})"
    if item.fireproof:
        settings_chain += ".fireproof()"
    if item.food_hunger > 0:
        settings_chain += (
            f".food(new FoodComponent.Builder()"
            f".hunger({item.food_hunger})"
            f".saturationModifier({item.food_saturation}f)"
            + (".alwaysEdible()" if item.food_always_edible else "")
            + ".build())"
        )
    food_import = ""
    if item.food_hunger > 0:
        food_import = (
            "import net.minecraft.component.type.FoodComponent;"
            if is_at_least(mod.minecraft_version, "1.21")
            else "import net.minecraft.item.FoodComponent;"
        )

    method_blocks = []

    if "on_right_click" in hooks or item.open_inventory_on_use or item.open_screen_on_use:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_right_click"])
        ) if "on_right_click" in hooks else ""
        body = guard_hook_body(body, hooks.get("on_right_click"), "world.isClient")
        if item.open_inventory_on_use:
            body += f"\n        if (!world.isClient) {{ {pkg}.item.FabricPyItemMenus.open(player, hand, stack); }}"
        if item.open_screen_on_use:
            body += f'\n        if (world.isClient) {{ {pkg}.client.ModScreens.openClient({json.dumps(item.open_screen_on_use)}); }}'
        method_blocks.append(f"""\
    @Override
    public TypedActionResult<ItemStack> use(World world, PlayerEntity user, Hand hand) {{
        PlayerEntity player = user;
        ItemStack stack = user.getStackInHand(hand);
        BlockPos soundPos = user.getBlockPos();
{body}
        return TypedActionResult.success(stack);
    }}""")

    extension = attachment_item_client_extension(mod, item, pkg, loader_name)
    if extension:
        method_blocks.append(extension)
    methods_str = "\n\n".join(method_blocks)

    src = f"""\
package {pkg_item};

import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.text.Text;
import net.minecraft.util.Hand;
import net.minecraft.util.Rarity;
import net.minecraft.util.TypedActionResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.World;
import net.minecraft.sound.SoundCategory;
import net.minecraft.sound.SoundEvents;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import java.util.Set;
{food_import}

/**
 * {item.get_display_name()} — generated by fabricpy
 */
public class {cn} extends Item {{

    public {cn}() {{
        super({settings_chain});
    }}

{methods_str}
}}
"""
    _write_text(item_dir / f"{cn}.java", src)


def _write_entity_classes(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._entities:
        return
    entity_dir = java_root / "entity"
    entity_dir.mkdir(exist_ok=True)
    for entity in mod._entities:
        _write_single_entity(mod, entity, entity_dir, pkg, transpiler)


def _write_single_entity(mod, entity, entity_dir: Path, pkg: str, transpiler: JavaTranspiler):
    cn = entity.get_class_name()
    hooks = entity.get_hooks()
    method_blocks = []
    is_geo = bool(getattr(entity, "geo_model", ""))

    if "on_tick" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_tick"])
        )
        method_blocks.append(f"""\
    @Override
    public void tick() {{
        super.tick();
        var entity = this;
        World world = this.getWorld();
        BlockPos pos = this.getBlockPos();
        BlockPos soundPos = pos;
{body}
    }}""")

    geo_imports = ""
    geo_fields = ""
    geo_methods = ""
    if is_geo:
        default_animation = getattr(entity, "default_animation", "")
        geo_imports = """import net.minecraft.entity.data.DataTracker;
import net.minecraft.entity.data.TrackedData;
import net.minecraft.entity.data.TrackedDataHandlerRegistry;
import software.bernie.geckolib.animatable.GeoEntity;
import software.bernie.geckolib.core.animatable.instance.AnimatableInstanceCache;
import software.bernie.geckolib.core.animation.AnimatableManager;
import software.bernie.geckolib.core.animation.AnimationController;
import software.bernie.geckolib.core.animation.RawAnimation;
import software.bernie.geckolib.util.GeckoLibUtil;"""
        geo_fields = f"""
    private static final TrackedData<String> FABRICPY_ANIMATION = DataTracker.registerData({cn}.class, TrackedDataHandlerRegistry.STRING);
    private static final TrackedData<Boolean> FABRICPY_ANIMATION_LOOP = DataTracker.registerData({cn}.class, TrackedDataHandlerRegistry.BOOLEAN);
    private static final TrackedData<String> FABRICPY_TEXTURE = DataTracker.registerData({cn}.class, TrackedDataHandlerRegistry.STRING);
    private static final TrackedData<String> FABRICPY_MODEL = DataTracker.registerData({cn}.class, TrackedDataHandlerRegistry.STRING);
    private final AnimatableInstanceCache cache = GeckoLibUtil.createInstanceCache(this);
"""
        geo_methods = f"""
    @Override
    protected void initDataTracker() {{
        super.initDataTracker();
        this.dataTracker.startTracking(FABRICPY_ANIMATION, "");
        this.dataTracker.startTracking(FABRICPY_ANIMATION_LOOP, true);
        this.dataTracker.startTracking(FABRICPY_TEXTURE, "");
        this.dataTracker.startTracking(FABRICPY_MODEL, "");
    }}

    public String getAnimationName() {{
        return this.dataTracker.get(FABRICPY_ANIMATION);
    }}

    public void setAnimationState(String animationName, boolean loop) {{
        this.dataTracker.set(FABRICPY_ANIMATION, animationName == null ? "" : animationName);
        this.dataTracker.set(FABRICPY_ANIMATION_LOOP, loop);
    }}

    public void clearAnimationName() {{
        this.dataTracker.set(FABRICPY_ANIMATION, "");
        this.dataTracker.set(FABRICPY_ANIMATION_LOOP, true);
    }}

    public String getTextureOverride() {{
        return this.dataTracker.get(FABRICPY_TEXTURE);
    }}

    public void setTextureOverride(String value) {{
        this.dataTracker.set(FABRICPY_TEXTURE, value == null ? "" : value);
    }}

    public String getModelOverride() {{
        return this.dataTracker.get(FABRICPY_MODEL);
    }}

    public void setModelOverride(String value) {{
        this.dataTracker.set(FABRICPY_MODEL, value == null ? "" : value);
    }}

    @Override
    public void registerControllers(AnimatableManager.ControllerRegistrar controllers) {{
        controllers.add(new AnimationController<>(this, "controller", 0, state -> {{
            String animationName = getAnimationName();
            if ((animationName == null || animationName.isEmpty()) && !"{default_animation}".isEmpty()) {{
                animationName = "{default_animation}";
            }}
            if (animationName == null || animationName.isEmpty()) {{
                return state.setAndContinue(RawAnimation.begin());
            }}
            boolean loop = this.dataTracker.get(FABRICPY_ANIMATION_LOOP);
            RawAnimation animation = loop
                ? RawAnimation.begin().thenLoop(animationName)
                : RawAnimation.begin().thenPlay(animationName);
            return state.setAndContinue(animation);
        }}));
    }}

    @Override
    public AnimatableInstanceCache getAnimatableInstanceCache() {{
        return this.cache;
    }}
"""

    src = f"""\
package {pkg}.entity;

import net.minecraft.entity.EntityType;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.ai.pathing.PathNodeType;
import net.minecraft.entity.attribute.DefaultAttributeContainer;
import net.minecraft.entity.attribute.EntityAttributes;
import net.minecraft.entity.mob.PathAwareEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.World;
{geo_imports}

/**
 * {entity.get_display_name()} - generated by fabricpy
 */
public class {cn} extends PathAwareEntity{" implements GeoEntity" if is_geo else ""} {{
{geo_fields}

    public {cn}(EntityType<? extends PathAwareEntity> entityType, World world) {{
        super(entityType, world);
    }}

    public static DefaultAttributeContainer.Builder createAttributes() {{
        return LivingEntity.createLivingAttributes()
            .add(EntityAttributes.GENERIC_MAX_HEALTH, {entity.max_health}d)
            .add(EntityAttributes.GENERIC_MOVEMENT_SPEED, {entity.movement_speed}d)
            .add(EntityAttributes.GENERIC_ATTACK_DAMAGE, {entity.attack_damage}d)
            .add(EntityAttributes.GENERIC_FOLLOW_RANGE, {entity.follow_range}d)
            .add(EntityAttributes.GENERIC_KNOCKBACK_RESISTANCE, {entity.knockback_resistance}d);
    }}

    @Override
    protected void initGoals() {{
        // No default AI goals generated by fabricpy yet.
    }}

{geo_methods}
{chr(10).join(method_blocks)}
}}
"""
    _write_text(entity_dir / f"{cn}.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Events
# ─────────────────────────────────────────────────────────────────────────── #

def _write_events(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._events:
        return
    event_dir = java_root / "event"
    event_dir.mkdir(exist_ok=True)

    main_class = to_pascal(mod.mod_id)
    imports = set()
    register_blocks = []

    imports.add("import net.minecraft.server.network.ServerPlayerEntity;")
    imports.add("import net.minecraft.text.Text;")
    imports.add("import net.minecraft.registry.Registries;")
    imports.add("import net.minecraft.util.Identifier;")
    imports.add("import net.minecraft.item.ItemStack;")
    imports.add("import net.minecraft.util.ActionResult;")
    imports.add("import net.minecraft.entity.effect.StatusEffectInstance;")
    imports.add("import net.minecraft.sound.SoundCategory;")
    imports.add("import net.minecraft.sound.SoundEvents;")
    imports.add("import net.minecraft.server.world.ServerWorld;")
    imports.add("import net.minecraft.world.World;")
    imports.add("import net.minecraft.util.math.BlockPos;")
    imports.add("import java.util.Set;")
    imports.add("import java.util.HashMap;")
    imports.add("import java.util.Map;")
    imports.add("import java.util.UUID;")

    for ev in mod._events:
        ev_name = ev["event"]
        if ev_name == "player_offhand_change":
            imports.add("import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;")
            imports.add("import net.minecraft.util.Hand;")
            body = transpiler.transpile_method(ev["source"])
            register_blocks.append(f"""\
        ServerTickEvents.END_SERVER_TICK.register((server) -> {{
            for (ServerPlayerEntity player : server.getPlayerManager().getPlayerList()) {{
                UUID playerId = player.getUuid();
                ItemStack stack = player.getOffHandStack();
                String previousOffhandItemId = LAST_OFFHAND_ITEM.getOrDefault(playerId, "");
                int previousOffhandCount = LAST_OFFHAND_COUNT.getOrDefault(playerId, 0);
                String currentOffhandItemId = Registries.ITEM.getId(stack.getItem()).toString();
                int currentOffhandCount = stack.getCount();
                if (!currentOffhandItemId.equals(previousOffhandItemId) || currentOffhandCount != previousOffhandCount) {{
                    ServerWorld world = player.getServerWorld();
                    Hand hand = Hand.OFF_HAND;
                    BlockPos soundPos = player.getBlockPos();
{body}
                }}
                LAST_OFFHAND_ITEM.put(playerId, currentOffhandItemId);
                LAST_OFFHAND_COUNT.put(playerId, currentOffhandCount);
            }}
        }});""")
            continue
        ev_info = FABRIC_EVENT_MAP.get(ev_name)
        if not ev_info:
            register_blocks.append(f"        // Unknown event: {ev_name}")
            continue

        imports.add(ev_info["import"])
        body = transpiler.transpile_method(ev["source"])
        if ev_name in INTERACTION_EVENTS:
            body = guard_hook_body(body, ev["func"], "world.isClient", side=ev.get("side", "server"))
        filled = ev_info["register"].format(body=body.strip())
        register_blocks.append(f"        {filled}")

    src = f"""\
package {pkg}.event;

{chr(10).join(sorted(imports))}

/**
 * Event registrations for {mod.name}.
 */
public class ModEvents {{
    private static final Map<UUID, String> LAST_OFFHAND_ITEM = new HashMap<>();
    private static final Map<UUID, Integer> LAST_OFFHAND_COUNT = new HashMap<>();

    public static void register() {{
{chr(10).join(register_blocks)}
    }}
}}
"""
    _write_text(event_dir / "ModEvents.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Commands
# ─────────────────────────────────────────────────────────────────────────── #

def _write_commands(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._commands:
        return
    cmd_dir = java_root / "command"
    cmd_dir.mkdir(exist_ok=True)

    main_class = to_pascal(mod.mod_id)
    command_blocks = []

    for cmd in mod._commands:
        body = transpiler.transpile_method(cmd["source"])
        perm = cmd["permission_level"]
        perm_clause = ""
        if perm > 0:
            perm_clause = f".requires(source -> source.hasPermissionLevel({perm}))"

        command_blocks.append(f"""\
        dispatcher.register(CommandManager.literal("{cmd['name']}")
            {perm_clause}
            .executes(context -> {{
{body}
                return 1;
            }}));""")

        for alias in cmd.get("aliases", []):
            command_blocks.append(
                f'        dispatcher.register(CommandManager.literal("{alias}")'
                f'.redirect(dispatcher.getRoot().getChild("{cmd["name"]}")));'
            )

    src = f"""\
package {pkg}.command;

import com.mojang.brigadier.CommandDispatcher;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.text.Text;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import java.util.Set;

/**
 * Command registrations for {mod.name}.
 */
public class ModCommands {{

    public static void register() {{
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {{
{chr(10).join(command_blocks)}
        }});
    }}
}}
"""
    _write_text(cmd_dir / "ModCommands.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Mixins
# ─────────────────────────────────────────────────────────────────────────── #

def _write_mixins(mod: "Mod", java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._mixins:
        return
    mixin_dir = java_root / "mixin"
    mixin_dir.mkdir(exist_ok=True)

    for mx in mod._mixins:
        _write_single_mixin(mod, mx, mixin_dir, pkg, transpiler)


def _write_single_mixin(mod, mx, mixin_dir: Path, pkg: str, transpiler: JavaTranspiler):
    cn = mx.get_class_name()
    target = mx.target_class
    injections = mx.get_injections()
    method_blocks = []

    for method_name, func in injections.items():
        hook_args = func._fabricpy_hook_args
        target_method = hook_args.get("method", method_name)
        at = hook_args.get("at", "HEAD")
        cancellable = hook_args.get("cancellable", False)

        body = transpiler.transpile_method(
            __import__("inspect").getsource(func)
        )
        ci_param = ", CallbackInfo ci" if not cancellable else ", CallbackInfo ci /* cancellable */"
        method_blocks.append(f"""\
    @Inject(method = "{target_method}", at = @At("{at}"){', cancellable = true' if cancellable else ''})
    private void {method_name}({ci_param}) {{
{body}
    }}""")

    methods_str = "\n\n".join(method_blocks)

    src = f"""\
package {pkg}.mixin;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import net.minecraft.text.Text;
import net.minecraft.server.network.ServerPlayerEntity;
import java.util.Set;

/**
 * Mixin into {target} — generated by fabricpy
 */
@Mixin({target}.class)
public class {cn} {{

{methods_str}
}}
"""
    _write_text(mixin_dir / f"{cn}.java", src)


# ─────────────────────────────────────────────────────────────────────────── #
# Resources
# ─────────────────────────────────────────────────────────────────────────── #

def _write_resources(mod: "Mod", res_root: Path, pkg: str, loader_name: str = "fabric"):
    main_class = f"{pkg}.{to_pascal(mod.mod_id)}"

    # fabric.mod.json
    fabric_mod = {
        "schemaVersion": 1,
        "id": mod.mod_id,
        "version": mod.version,
        "name": mod.name,
        "description": mod.description,
        "authors": mod.authors,
        "contact": {"homepage": mod.website} if mod.website else {},
        "license": mod.license,
        "environment": "*",
        "entrypoints": {"main": [main_class]},
        "depends": {
            "fabricloader": f">={FABRIC_VERSIONS[mod.minecraft_version].fabric_loader}",
            "fabric-api": "*",
            "minecraft": f"~{mod.minecraft_version}",
            "java": f">={FABRIC_VERSIONS[mod.minecraft_version].java}",
        },
    }
    for dep in _deps_for_loader(mod, loader_name):
        if dep.mod_id and dep.required:
            fabric_mod["depends"][dep.mod_id] = dep.version_range or "*"
    if _blocks_requiring_cutout(mod) or mod._keybinds or mod._packets or _uses_geckolib(mod) or attachment_items(mod):
        fabric_mod["entrypoints"]["client"] = [f"{pkg}.{to_pascal(mod.mod_id)}Client"]
    if mod._mixins:
        fabric_mod["mixins"] = [f"{mod.mod_id}.mixins.json"]
    _write_text(res_root / "fabric.mod.json", json.dumps(fabric_mod, indent=2))

    # mixins json
    if mod._mixins:
        mixin_pkg = f"{pkg}.mixin"
        mixin_classes = [mx.get_class_name() for mx in mod._mixins]
        mixins_json = {
            "required": True,
            "minVersion": "0.8",
            "package": mixin_pkg,
            "compatibilityLevel": f"JAVA_{FABRIC_VERSIONS[mod.minecraft_version].java}",
            "mixins": mixin_classes,
            "client": [],
            "injectors": {"defaultRequire": 1},
        }
        _write_text(res_root / f"{mod.mod_id}.mixins.json", json.dumps(mixins_json, indent=2))

    # en_us.json lang file
    lang = {}
    for b in mod._blocks:
        lang[f"block.{mod.mod_id}.{b.block_id}"] = b.get_display_name()
    for it in mod._items:
        lang[f"item.{mod.mod_id}.{it.item_id}"] = it.get_display_name()
    for entity in mod._entities:
        lang[f"entity.{mod.mod_id}.{entity.entity_id}"] = entity.get_display_name()
    for tab in mod._creative_tabs:
        lang[f"itemGroup.{mod.mod_id}.{tab.tab_id.replace('/', '.')}"] = tab.title
    for bind in mod._keybinds:
        lang[f"key.{mod.mod_id}.{bind.keybind_id.replace('/', '.')}"] = bind.title
        lang[f"key.categories.{bind.category.replace('/', '.')}"] = bind.category_title
    for advancement in mod._advancements:
        advancement_key = advancement["id"].replace("/", ".")
        display = advancement["data"].get("display", {})
        if isinstance(display.get("title"), str):
            lang[f"advancement.{mod.mod_id}.{advancement_key}.title"] = display["title"]
        if isinstance(display.get("description"), str):
            lang[f"advancement.{mod.mod_id}.{advancement_key}.description"] = display["description"]
    for sound in mod._sounds:
        if sound.get("subtitle_text"):
            key = f"subtitles.{mod.mod_id}.{sound['id'].replace('/', '.')}"
            lang[key] = sound["subtitle_text"]

    lang_dir = res_root / "assets" / mod.mod_id / "lang"
    lang_dir.mkdir(parents=True, exist_ok=True)
    _write_text(lang_dir / "en_us.json", json.dumps(lang, indent=2))

    blockstates_dir = res_root / "assets" / mod.mod_id / "blockstates"
    block_models_dir = res_root / "assets" / mod.mod_id / "models" / "block"
    item_models_dir = res_root / "assets" / mod.mod_id / "models" / "item"
    blockstates_dir.mkdir(parents=True, exist_ok=True)
    block_models_dir.mkdir(parents=True, exist_ok=True)
    item_models_dir.mkdir(parents=True, exist_ok=True)

    for block in mod._blocks:
        default_model_id = _normalize_block_model_id(mod.mod_id, "", block.block_id)
        blockstate = (
            _generated_rotation_blockstate(mod.mod_id, block)
            if getattr(block, "variable_rotation", False)
            else (block.blockstate or {
                "variants": {
                    "": {"model": f"{mod.mod_id}:block/{block.block_id}"}
                }
            })
        )
        block_model = resolve_model_input(block.model, mod.mod_id, "block", block.block_id, res_root / "assets" / mod.mod_id) or {
            "parent": "minecraft:block/cube_all",
            "textures": block.textures or {
                "all": _resource_ref(mod.mod_id, block.texture, "block", block.block_id)
            }
        }
        block_item_model = resolve_model_input(block.item_model, mod.mod_id, "item", block.block_id, res_root / "assets" / mod.mod_id) or {
            "parent": f"{mod.mod_id}:block/{block.block_id}"
        }
        emissive_ref = _resource_ref(mod.mod_id, block.emissive_texture, "block", f"{block.block_id}_emissive")
        if getattr(block, "emissive_texture", ""):
            overlay_model_id = f"{mod.mod_id}:block/{block.block_id}__emissive"
            base_overlay_model = _load_block_model_data(Path.cwd(), mod, block, default_model_id)
            if not isinstance(base_overlay_model, dict):
                base_overlay_model = block_model
            overlay_model = resolve_model_input(block.emissive_model, mod.mod_id, "block", block.block_id + "__emissive", res_root / "assets" / mod.mod_id) or json.loads(json.dumps(base_overlay_model))
            if isinstance(overlay_model, dict):
                base_textures = base_overlay_model.get("textures", {}) if isinstance(base_overlay_model, dict) else {}
                overlay_model["ambientocclusion"] = False
                overlay_model["textures"] = _overlay_texture_map(
                    base_textures,
                    getattr(block, "emissive_textures", {}),
                    emissive_ref,
                )
            blockstate = _append_emissive_overlay_blockstate(blockstate, overlay_model_id)
            _write_text(
                block_models_dir / f"{block.block_id}__emissive.json",
                json.dumps(overlay_model, indent=2),
            )
        _write_text(
            blockstates_dir / f"{block.block_id}.json",
            json.dumps(blockstate, indent=2),
        )
        _write_text(
            block_models_dir / f"{block.block_id}.json",
            json.dumps(block_model, indent=2),
        )
        _write_text(
            item_models_dir / f"{block.block_id}.json",
            json.dumps(block_item_model, indent=2),
        )

    for item in mod._items:
        item_model = resolve_model_input(item.model, mod.mod_id, "item", item.item_id, res_root / "assets" / mod.mod_id) or {
            "parent": "minecraft:item/generated",
            "textures": item.textures or {
                "layer0": _resource_ref(mod.mod_id, item.texture, "item", item.item_id)
            }
        }
        if getattr(item, "emissive_texture", "") and isinstance(item_model, dict):
            item_model = json.loads(json.dumps(item_model))
            textures = dict(item_model.get("textures", {}))
            textures.setdefault(
                "layer1",
                _resource_ref(mod.mod_id, item.emissive_texture, "item", f"{item.item_id}_emissive"),
            )
            item_model["textures"] = textures
        _write_text(
            item_models_dir / f"{item.item_id}.json",
            json.dumps(item_model, indent=2),
        )

    recipes_dir = res_root / "data" / mod.mod_id / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    for recipe in mod._recipes:
        recipe_path = recipes_dir / f"{recipe['id']}.json"
        recipe_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(recipe_path, json.dumps(recipe["data"], indent=2))

    advancements_dir = res_root / "data" / mod.mod_id / "advancements"
    advancements_dir.mkdir(parents=True, exist_ok=True)
    for advancement in mod._advancements:
        advancement_path = advancements_dir / f"{advancement['id']}.json"
        advancement_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(advancement_path, json.dumps(advancement["data"], indent=2))

    dimension_types_dir = res_root / "data" / mod.mod_id / "dimension_type"
    dimension_types_dir.mkdir(parents=True, exist_ok=True)
    for dimension_type in mod._dimension_types:
        type_path = dimension_types_dir / f"{dimension_type['id']}.json"
        type_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(type_path, json.dumps(dimension_type["data"], indent=2))

    dimensions_dir = res_root / "data" / mod.mod_id / "dimension"
    dimensions_dir.mkdir(parents=True, exist_ok=True)
    for dimension in mod._dimensions:
        dimension_path = dimensions_dir / f"{dimension['id']}.json"
        dimension_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(dimension_path, json.dumps(dimension["data"], indent=2))

    structures_dir = res_root / "data" / mod.mod_id / "structures"
    structures_dir.mkdir(parents=True, exist_ok=True)
    for structure in mod._structures:
        structure_path = structures_dir / f"{structure['id']}.nbt"
        structure_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(structure["path"]), structure_path)

    if mod._sounds:
        sounds_json = {
            sound["id"]: sound["data"]
            for sound in mod._sounds
        }
        _write_text(
            res_root / "assets" / mod.mod_id / "sounds.json",
            json.dumps(sounds_json, indent=2),
        )

    project_root = Path.cwd()
    _copy_tree_if_exists(project_root / "assets" / mod.mod_id, res_root / "assets" / mod.mod_id)
    _copy_tree_if_exists(project_root / "data" / mod.mod_id, res_root / "data" / mod.mod_id)
    compile_bbmodels_in_assets(res_root / "assets" / mod.mod_id, mod.mod_id, project_root / "assets" / mod.mod_id)
    write_music_disc_resources(mod, res_root)
    write_attachment_resources(mod, res_root)

    # pack.mcmeta
    _write_text(res_root / "pack.mcmeta", json.dumps({
        "pack": {
            "pack_format": FABRIC_VERSIONS[mod.minecraft_version].pack_format,
            "description": f"{mod.name} resources",
        }
    }, indent=2))


# ─────────────────────────────────────────────────────────────────────────── #
# Gradle build files
# ─────────────────────────────────────────────────────────────────────────── #

def _write_gradle_files(mod: "Mod", project_dir: Path, loader_name: str = "fabric"):
    mc = mod.minecraft_version
    use_geckolib = _uses_geckolib(mod)
    v = FABRIC_VERSIONS.get(mc)
    if v is None:
        raise ValueError(f"Fabric does not support minecraft_version={mc!r} in this generator.")
    main_class = to_pascal(mod.mod_id)
    extra_repos = _fabric_repository_lines(mod, loader_name)
    extra_deps = _fabric_dependency_lines(mod, loader_name)

    # build.gradle
    build_gradle = f"""\
plugins {{
    id 'fabric-loom' version '{v.loom}'
    id 'maven-publish'
}}

version = "{mod.version}"
group = "{mod.package}"

base {{
    archivesName = "{mod.mod_id}"
}}

repositories {{
    maven {{ url = "https://maven.fabricmc.net/" }}
    {"maven { url = \"https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/\" }" if use_geckolib else ""}
{chr(10).join(extra_repos)}
    mavenCentral()
}}

dependencies {{
    minecraft "com.mojang:minecraft:{mc}"
    mappings "net.fabricmc:yarn:{v.yarn}:v2"
    modImplementation "net.fabricmc:fabric-loader:{v.fabric_loader}"
    modImplementation "net.fabricmc.fabric-api:fabric-api:{v.fabric_api}"
    {"modImplementation \"software.bernie.geckolib:geckolib-fabric-" + mc + ":" + v.geckolib + "\"" if use_geckolib else ""}
{chr(10).join(extra_deps)}
}}

processResources {{
    inputs.property "version", version

    filesMatching("fabric.mod.json") {{
        expand "version": version
    }}
}}

tasks.withType(JavaCompile).configureEach {{
    it.options.release = {v.java}
}}

java {{
    withSourcesJar()
    toolchain.languageVersion = JavaLanguageVersion.of({v.java})
}}

jar {{
    from("LICENSE") {{
        rename {{ "${{it}}_${{base.archivesName.get()}}" }}
    }}
}}
"""
    _write_text(project_dir / "build.gradle", build_gradle)

    # settings.gradle
    _write_text(project_dir / "settings.gradle", f"""\
pluginManagement {{
    repositories {{
        maven {{ url = "https://maven.fabricmc.net/" }}
        mavenCentral()
        gradlePluginPortal()
    }}
}}
plugins {{
    id 'org.gradle.toolchains.foojay-resolver-convention' version '0.8.0'
}}
rootProject.name = "{mod.mod_id}"
""")

    # gradle.properties
    _write_text(project_dir / "gradle.properties", f"""\
org.gradle.jvmargs=-Xmx1G
""")

    # .gitignore
    _write_text(project_dir / ".gitignore", ".gradle/\nbuild/\n*.jar\n!gradle/wrapper/gradle-wrapper.jar\n")

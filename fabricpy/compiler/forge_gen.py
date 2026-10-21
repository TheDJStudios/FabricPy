"""
Forge mod project generator.

Produces a complete Forge 1.20.1 mod project:
  src/main/java/.../
    {ModId}.java                — @Mod main class
    ModBlocks.java              — DeferredRegister for blocks
    ModItems.java               — DeferredRegister for items
    block/{BlockName}.java      — One per Block subclass
    item/{ItemName}.java        — One per Item subclass
    event/ModEvents.java        — @SubscribeEvent handlers
    command/ModCommands.java    — RegisterCommandsEvent + Brigadier
  src/main/resources/
    META-INF/mods.toml
    pack.mcmeta
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
from fabricpy.compiler.dependencies import dependencies_for_loader, gradle_notation
from fabricpy.compiler.symbol_index import write_interop_metadata
from fabricpy.compiler.jar_scanner import build_symbol_index_for_project
from fabricpy.compiler.bbmodel_converter import compile_bbmodels_in_assets, resolve_model_input
from fabricpy.compiler.api_maps import (
    FORGE_API_MAP, FORGE_EXTRA_IMPORTS,
    FORGE_EVENT_MAP,
)
from fabricpy.compiler.versions import FORGE_VERSIONS, is_at_least


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


def _forge_shape_code(shape_name: str, boxes: list[tuple[float, float, float, float, float, float]]) -> str:
    parts = [f"Block.box({x1}, {y1}, {z1}, {x2}, {y2}, {z2})" for x1, y1, z1, x2, y2, z2 in boxes]
    expr = "Shapes.or(" + ", ".join(parts) + ")" if len(parts) > 1 else parts[0]
    return f"    private static final VoxelShape {shape_name} = {expr};"


def _copy_tree_if_exists(src: Path, dest: Path):
    if src.exists():
        shutil.copytree(src, dest, dirs_exist_ok=True)


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


def _forge_render_type_expr(value: str) -> str:
    layer = _render_layer_value(value)
    if layer == "translucent":
        return "RenderType.translucent()"
    if layer == "cutout_mipped":
        return "RenderType.cutoutMipped()"
    if layer == "cutout":
        return "RenderType.cutout()"
    return "RenderType.solid()"


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


def _forge_api_map_for_project(pkg: str) -> dict[str, str]:
    api_map = dict(FORGE_API_MAP)
    runtime = f"{pkg}.util.FabricPyRuntime"
    network = f"{pkg}.network.FabricPyNetwork"
    screens = f"{pkg}.client.ModScreens"
    api_map.update({
        "ctx.math.vec3": "new net.minecraft.world.phys.Vec3({0}, {1}, {2})",
        "ctx.math.block_pos": "new BlockPos((int)({0}), (int)({1}), (int)({2}))",
        "ctx.math.clamp": f"{runtime}.clamp({{0}}, {{1}}, {{2}})",
        "ctx.math.lerp": f"{runtime}.lerp({{0}}, {{1}}, {{2}})",
        "ctx.math.distance3": f"{runtime}.distance3({{0}}, {{1}}, {{2}}, {{3}}, {{4}}, {{5}})",
        "ctx.math.length3": f"{runtime}.length3({{0}}, {{1}}, {{2}})",
        "ctx.math.normalize3": f"{runtime}.normalize3({{0}}, {{1}}, {{2}})",
        "ctx.math.add3": f"{runtime}.add3({{0}}, {{1}}, {{2}}, {{3}}, {{4}}, {{5}})",
        "ctx.world.spawn_particle": f"{runtime}.spawnParticle(level, {{0}}, {{1}}, {{2}}, {{3}}, {{4}}, {{5}}, {{6}}, {{7}}, {{8}})",
        "ctx.world.spawn_particle_self": f"{runtime}.spawnParticle(level, {{0}}, pos.getX() + 0.5, pos.getY() + 0.5, pos.getZ() + 0.5, {{1}}, {{2}}, {{3}}, {{4}}, {{5}})",
        "ctx.world.raycast_block": f"{runtime}.raycastBlock(level, {{0}}, {{1}})",
        "ctx.world.raycast_block_id": f"{runtime}.raycastBlockId(level, {{0}}, {{1}})",
        "ctx.world.raycast_block_pos_x": f"{runtime}.raycastBlockPosX(level, {{0}}, {{1}})",
        "ctx.world.raycast_block_pos_y": f"{runtime}.raycastBlockPosY(level, {{0}}, {{1}})",
        "ctx.world.raycast_block_pos_z": f"{runtime}.raycastBlockPosZ(level, {{0}}, {{1}})",
        "ctx.client.open_screen": f"{screens}.open(client, {{0}})",
        "ctx.client.close_screen": "client.setScreen(null)",
        "ctx.net.send_to_server": f"{network}.sendToServer({{0}}, {{1}})",
        "ctx.net.send_to_player": f"{network}.sendToPlayer((ServerPlayer)({{0}}), {{1}}, {{2}})",
        "ctx.net.broadcast": f"{network}.broadcast(server, {{0}}, {{1}})",
    })
    return api_map


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


def _forge_repository_lines(mod: "Mod", loader_name: str = "forge") -> list[str]:
    repos = []
    seen = set()
    for dep in _deps_for_loader(mod, loader_name):
        if dep.repo and dep.repo not in seen:
            repos.append(f"    maven {{ url = '{dep.repo}' }}")
            seen.add(dep.repo)
    return repos


def _forge_dependency_line(dep, mc: str, loader_name: str = "forge") -> str:
    scope = dep.scope or "implementation"
    if dep.deobf and not dep.path and loader_name != "neoforge":
        return f"    {scope} fg.deobf({gradle_notation(dep)})"
    return f"    {scope} {gradle_notation(dep)}"


def _forge_manifest_dependencies(mod: "Mod", loader_name: str = "forge") -> list[dict]:
    deps = []
    for dep in _deps_for_loader(mod, loader_name):
        if dep.mod_id and dep.required:
            deps.append({
                "mod_id": dep.mod_id,
                "required": True,
                "version_range": dep.version_range or "*",
                "ordering": dep.ordering or "NONE",
                "side": dep.side or "BOTH",
            })
    return deps


def _mob_category(group: str) -> str:
    mapping = {
        "monster": "MobCategory.MONSTER",
        "creature": "MobCategory.CREATURE",
        "ambient": "MobCategory.AMBIENT",
        "water_creature": "MobCategory.WATER_CREATURE",
        "water_ambient": "MobCategory.WATER_AMBIENT",
        "misc": "MobCategory.MISC",
        "underground_water_creature": "MobCategory.UNDERGROUND_WATER_CREATURE",
        "axolotls": "MobCategory.AXOLOTLS",
    }
    return mapping.get(group, "MobCategory.MISC")


def generate_forge_project(mod: "Mod", project_dir: Path, *, loader_name: str = "forge"):
    """Generate a complete Forge mod project tree under project_dir."""
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

    interop_repositories = [*_forge_repository_lines(mod, loader_name), "https://repo1.maven.org/maven2/"]
    interop_dependency_lines = [_forge_dependency_line(dep, mod.minecraft_version, loader_name) for dep in _deps_for_loader(mod, loader_name)]
    if _uses_geckolib(mod):
        version_meta = FORGE_VERSIONS.get(mod.minecraft_version)
        if version_meta is None:
            raise ValueError(f"Forge does not support minecraft_version={mod.minecraft_version!r} in this generator.")
        interop_repositories.insert(0, "https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/")
        interop_dependency_lines = [
            (f"implementation 'software.bernie.geckolib:geckolib-neoforge-{mod.minecraft_version}:{version_meta.geckolib}'" if loader_name == "neoforge" else f"implementation fg.deobf('software.bernie.geckolib:geckolib-forge-{mod.minecraft_version}:{version_meta.geckolib}')"),
            *interop_dependency_lines,
        ]
    write_interop_metadata(
        mod,
        project_dir,
        loader_name,
        repositories=interop_repositories,
        dependency_lines=interop_dependency_lines,
        manifest_dependencies=_forge_manifest_dependencies(mod, loader_name),
    )
    try:
        build_symbol_index_for_project(project_dir)
    except Exception as exc:
        raise ValueError(f"Dependency scanning failed for {loader_name}: {exc}") from exc

    transpiler = JavaTranspiler(
        _forge_api_map_for_project(pkg),
        interop_index_path=project_dir / ".fabricpy_meta" / "symbol_index.json",
    )

    _write_main_class(mod, java_root, pkg)
    _write_runtime_helpers(mod, java_root, pkg)
    _write_network(mod, java_root, pkg, transpiler)
    _write_screens(mod, java_root, pkg, transpiler)
    _write_mod_blocks(mod, java_root, pkg)
    _write_mod_block_entities(mod, java_root, pkg)
    _write_mod_items(mod, java_root, pkg)
    _write_mod_creative_tabs(mod, java_root, pkg)
    _write_mod_keybinds(mod, java_root, pkg, transpiler)
    _write_mod_entities(mod, java_root, pkg)
    _write_geo_block_renderers(mod, java_root, pkg)
    _write_block_classes(mod, java_root, pkg, transpiler)
    _write_item_classes(mod, java_root, pkg, transpiler)
    _write_entity_classes(mod, java_root, pkg, transpiler)
    _write_events(mod, java_root, pkg, transpiler)
    _write_commands(mod, java_root, pkg, transpiler)
    _write_resources(mod, res_root, loader_name)
    _write_gradle_files(mod, project_dir, loader_name)
    print(f"[fabricpy] Forge project generated at {project_dir}")


def _write_main_class(mod, java_root: Path, pkg: str):
    class_name = to_pascal(mod.mod_id)
    has_block_entities = bool(_blocks_with_block_entities(mod))
    has_creative_tabs = bool(mod._creative_tabs)
    has_keybinds = bool(mod._keybinds)
    has_geo = _uses_geckolib(mod)
    has_packets = bool(mod._packets)
    cutout_blocks = _blocks_requiring_cutout(mod)

    imports = []
    if mod._entities:
        imports.append(f"import {pkg}.entity.ModEntities;")
    if mod._commands:
        imports.append(f"import {pkg}.command.ModCommands;")
    if mod._events:
        imports.append(f"import {pkg}.event.ModEvents;")
    if has_block_entities:
        imports.append(f"import {pkg}.blockentity.ModBlockEntities;")
    if has_keybinds:
        imports.append(f"import {pkg}.client.ModKeybinds;")
    if has_geo:
        imports.append(f"import {pkg}.client.ModGeoRenderers;")
    if has_packets:
        imports.append(f"import {pkg}.network.FabricPyNetwork;")

    client_setup_lines = [
        *(f"            ItemBlockRenderTypes.setRenderLayer(ModBlocks.{block.block_id.upper()}.get(), {_forge_render_type_expr(getattr(block, 'render_layer', 'cutout' if (not block.opaque or getattr(block, 'emissive_texture', '')) else 'solid'))});" for block in cutout_blocks),
        *(["            ModGeoRenderers.registerClient();"] if has_geo else []),
        *(["            // Keybinds register through ModKeybinds on the client bus."] if has_keybinds else []),
    ]
    client_setup_code = ""
    if cutout_blocks or has_keybinds or has_geo:
        client_setup_code = (
            "public void onClientSetup(FMLClientSetupEvent event) {\n"
            "        event.enqueueWork(() -> {\n"
            + "\n".join(client_setup_lines) +
            "\n        });\n"
            "    }"
        )

    src = f"""\
package {pkg};

{chr(10).join(imports)}
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.event.lifecycle.FMLClientSetupEvent;
import net.minecraftforge.fml.event.lifecycle.FMLCommonSetupEvent;
import net.minecraftforge.fml.javafmlmod.FMLJavaModLoadingContext;
import net.minecraftforge.eventbus.api.IEventBus;
import net.minecraft.client.renderer.ItemBlockRenderTypes;
import net.minecraft.client.renderer.RenderType;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

/**
 * Generated by fabricpy — {mod.name} v{mod.version}
 */
@Mod("{mod.mod_id}")
public class {class_name} {{
    public static final String MOD_ID = "{mod.mod_id}";
    public static final Logger LOGGER = LogManager.getLogger(MOD_ID);

    public {class_name}() {{
        IEventBus bus = FMLJavaModLoadingContext.get().getModEventBus();

        {"ModBlocks.BLOCKS.register(bus);" if mod._blocks else "// No blocks"}
        {"ModBlocks.ITEMS.register(bus);" if mod._blocks else ""}
        {"ModItems.ITEMS.register(bus);" if mod._items else "// No items"}
        {"ModBlockEntities.BLOCK_ENTITIES.register(bus);" if has_block_entities else ""}
        {"ModCreativeTabs.TABS.register(bus);" if has_creative_tabs else ""}
        {"ModKeybinds.register(bus);" if has_keybinds else ""}
        {"FabricPyNetwork.register();" if has_packets else ""}
        {"ModEntities.ENTITIES.register(bus);" if mod._entities else ""}
        {"bus.addListener(ModEvents::onCommonSetup);" if mod._events else "// No events"}
        {"bus.addListener(ModBlocks::addCreative);" if mod._blocks else ""}
        {"bus.addListener(ModItems::addCreative);" if mod._items else ""}
        {"bus.addListener(ModEntities::registerAttributes);" if mod._entities else ""}
        {"bus.addListener(this::onClientSetup);" if (cutout_blocks or has_keybinds or has_geo) else ""}

        // Register command events on Forge's main bus
        {"net.minecraftforge.common.MinecraftForge.EVENT_BUS.register(ModCommands.class);" if mod._commands else "// No commands"}
        {"net.minecraftforge.common.MinecraftForge.EVENT_BUS.register(ModEvents.class);" if mod._events else ""}
    }}

    {client_setup_code}
}}
"""
    _write_text(java_root / f"{class_name}.java", src)


def _write_runtime_helpers(mod, java_root: Path, pkg: str):
    util_dir = java_root / "util"
    util_dir.mkdir(exist_ok=True)
    src = f"""\
package {pkg}.util;

import net.minecraft.core.BlockPos;
import net.minecraft.core.particles.SimpleParticleType;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraftforge.registries.ForgeRegistries;

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

    public static Vec3 normalize3(double x, double y, double z) {{
        double len = length3(x, y, z);
        if (len <= 0.000001d) {{
            return new Vec3(0, 0, 0);
        }}
        return new Vec3(x / len, y / len, z / len);
    }}

    public static Vec3 add3(double x1, double y1, double z1, double x2, double y2, double z2) {{
        return new Vec3(x1 + x2, y1 + y2, z1 + z2);
    }}

    public static BlockHitResult raycastBlock(Level level, Vec3 start, Vec3 end) {{
        return level.clip(new ClipContext(start, end, ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, null));
    }}

    public static String raycastBlockId(Level level, Vec3 start, Vec3 end) {{
        BlockHitResult hit = raycastBlock(level, start, end);
        if (hit.getType() != HitResult.Type.BLOCK) {{
            return "";
        }}
        BlockState state = level.getBlockState(hit.getBlockPos());
        return ForgeRegistries.BLOCKS.getKey(state.getBlock()).toString();
    }}

    public static int raycastBlockPosX(Level level, Vec3 start, Vec3 end) {{
        BlockHitResult hit = raycastBlock(level, start, end);
        return hit.getType() == HitResult.Type.BLOCK ? hit.getBlockPos().getX() : 0;
    }}

    public static int raycastBlockPosY(Level level, Vec3 start, Vec3 end) {{
        BlockHitResult hit = raycastBlock(level, start, end);
        return hit.getType() == HitResult.Type.BLOCK ? hit.getBlockPos().getY() : 0;
    }}

    public static int raycastBlockPosZ(Level level, Vec3 start, Vec3 end) {{
        BlockHitResult hit = raycastBlock(level, start, end);
        return hit.getType() == HitResult.Type.BLOCK ? hit.getBlockPos().getZ() : 0;
    }}

    public static void spawnParticle(Level level, String particleId, double x, double y, double z, double dx, double dy, double dz, double speed, int count) {{
        var particleType = ForgeRegistries.PARTICLE_TYPES.getValue(new net.minecraft.resources.ResourceLocation(particleId));
        if (!(particleType instanceof SimpleParticleType simple)) {{
            return;
        }}
        if (level instanceof net.minecraft.server.level.ServerLevel serverLevel) {{
            serverLevel.sendParticles(simple, x, y, z, count, dx, dy, dz, speed);
            return;
        }}
        for (int i = 0; i < Math.max(1, count); i++) {{
            level.addParticle(simple, x, y, z, dx, dy, dz);
        }}
    }}
}}
"""
    _write_text(util_dir / "FabricPyRuntime.java", src)


def _write_network(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
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
                var player = context.getSender();
                if (player == null) {{
                    return;
                }}
                var server = player.getServer();
                var level = player.level();
                BlockPos soundPos = player.blockPosition();
{body}
            }}""")
        if packet.client_source:
            body = transpiler.transpile_method(packet.client_source)
            client_cases.append(f"""\
            case "{packet.packet_id}" -> {{
                var client = net.minecraft.client.Minecraft.getInstance();
                var player = client.player;
                var level = client.level;
                var server = client.getSingleplayerServer();
                BlockPos soundPos = player != null ? player.blockPosition() : BlockPos.ZERO;
{body}
            }}""")

    src = f"""\
package {pkg}.network;

import net.minecraft.core.BlockPos;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraftforge.network.NetworkDirection;
import net.minecraftforge.network.NetworkRegistry;
import net.minecraftforge.network.PacketDistributor;
import net.minecraftforge.network.simple.SimpleChannel;

import java.util.function.Supplier;

public class FabricPyNetwork {{
    private static final String PROTOCOL = "1";
    public static final SimpleChannel CHANNEL = NetworkRegistry.newSimpleChannel(
        new ResourceLocation("{mod.mod_id}", "fabricpy_network"),
        () -> PROTOCOL,
        PROTOCOL::equals,
        PROTOCOL::equals
    );

    public static void register() {{
        CHANNEL.registerMessage(0, FabricPyC2SPacket.class, FabricPyC2SPacket::encode, FabricPyC2SPacket::decode, FabricPyNetwork::handleC2S, java.util.Optional.of(NetworkDirection.PLAY_TO_SERVER));
        CHANNEL.registerMessage(1, FabricPyS2CPacket.class, FabricPyS2CPacket::encode, FabricPyS2CPacket::decode, FabricPyNetwork::handleS2C, java.util.Optional.of(NetworkDirection.PLAY_TO_CLIENT));
    }}

    public static void sendToServer(String packetId, String message) {{
        CHANNEL.sendToServer(new FabricPyC2SPacket(packetId, message));
    }}

    public static void sendToPlayer(ServerPlayer player, String packetId, String message) {{
        if (player == null) {{
            return;
        }}
        CHANNEL.send(PacketDistributor.PLAYER.with(() -> player), new FabricPyS2CPacket(packetId, message));
    }}

    public static void broadcast(net.minecraft.server.MinecraftServer server, String packetId, String message) {{
        if (server == null) {{
            return;
        }}
        for (ServerPlayer player : server.getPlayerList().getPlayers()) {{
            sendToPlayer(player, packetId, message);
        }}
    }}

    private static void handleC2S(FabricPyC2SPacket packet, Supplier<net.minecraftforge.network.NetworkEvent.Context> supplier) {{
        var context = supplier.get();
        context.enqueueWork(() -> {{
            String message = packet.message();
            switch (packet.packetId()) {{
{chr(10).join(server_cases) if server_cases else '            default -> { }'}
                default -> {{
                }}
            }}
        }});
        context.setPacketHandled(true);
    }}

    private static void handleS2C(FabricPyS2CPacket packet, Supplier<net.minecraftforge.network.NetworkEvent.Context> supplier) {{
        var context = supplier.get();
        context.enqueueWork(() -> {{
            String message = packet.message();
            switch (packet.packetId()) {{
{chr(10).join(client_cases) if client_cases else '            default -> { }'}
                default -> {{
                }}
            }}
        }});
        context.setPacketHandled(true);
    }}

    public record FabricPyC2SPacket(String packetId, String message) {{
        public static void encode(FabricPyC2SPacket packet, FriendlyByteBuf buf) {{
            buf.writeUtf(packet.packetId == null ? "" : packet.packetId);
            buf.writeUtf(packet.message == null ? "" : packet.message);
        }}

        public static FabricPyC2SPacket decode(FriendlyByteBuf buf) {{
            return new FabricPyC2SPacket(buf.readUtf(), buf.readUtf());
        }}
    }}

    public record FabricPyS2CPacket(String packetId, String message) {{
        public static void encode(FabricPyS2CPacket packet, FriendlyByteBuf buf) {{
            buf.writeUtf(packet.packetId == null ? "" : packet.packetId);
            buf.writeUtf(packet.message == null ? "" : packet.message);
        }}

        public static FabricPyS2CPacket decode(FriendlyByteBuf buf) {{
            return new FabricPyS2CPacket(buf.readUtf(), buf.readUtf());
        }}
    }}
}}
"""
    _write_text(network_dir / "FabricPyNetwork.java", src)


def _write_screens(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._screens:
        return
    client_dir = java_root / "client"
    client_dir.mkdir(exist_ok=True)
    screen_dir = client_dir / "screen"
    screen_dir.mkdir(exist_ok=True)

    open_lines = []
    for screen in mod._screens:
        cn = f"{to_pascal(screen.screen_id.replace('/', '_'))}Screen"
        open_body = transpiler.transpile_method(screen.open_source) if screen.open_source else "        // No on_open handler"
        button_lines = []
        for button in screen.buttons:
            body = transpiler.transpile_method(button.source) if button.source else "            // No handler"
            button_lines.append(f"""\
        this.addRenderableWidget(net.minecraft.client.gui.components.Button.builder(net.minecraft.network.chat.Component.literal("{button.text}"), widget -> {{
            var client = this.minecraft;
            var screen = this;
            var player = client != null ? client.player : null;
            var level = client != null ? client.level : null;
            var server = client != null ? client.getSingleplayerServer() : null;
            var buttonObj = widget;
            BlockPos soundPos = player != null ? player.blockPosition() : BlockPos.ZERO;
{body}
        }}).bounds({button.x}, {button.y}, {button.width}, {button.height}).build());""")
        label_lines = [
            f'        guiGraphics.drawString(this.font, net.minecraft.network.chat.Component.literal("{label["text"]}"), {label["x"]}, {label["y"]}, {label["color"]});'
            for label in screen.labels
        ]
        src = f"""\
package {pkg}.client.screen;

import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;

public class {cn} extends Screen {{
    public {cn}() {{
        super(Component.literal("{screen.title}"));
    }}

    @Override
    protected void init() {{
        super.init();
{f'''        {{
            var client = this.minecraft;
            var screen = this;
            var player = client != null ? client.player : null;
            var level = client != null ? client.level : null;
            var server = client != null ? client.getSingleplayerServer() : null;
            BlockPos soundPos = player != null ? player.blockPosition() : BlockPos.ZERO;
{open_body}
        }}''' if screen.open_source else '        // No on_open handler'}
{chr(10).join(button_lines)}
    }}

    @Override
    public void render(GuiGraphics guiGraphics, int mouseX, int mouseY, float partialTick) {{
        this.renderBackground(guiGraphics);
        super.render(guiGraphics, mouseX, mouseY, partialTick);
        guiGraphics.drawCenteredString(this.font, this.title, this.width / 2, 12, 0xFFFFFF);
{chr(10).join(label_lines) if label_lines else '        // No labels'}
    }}

    @Override
    public boolean isPauseScreen() {{
        return false;
    }}
}}
"""
        _write_text(screen_dir / f"{cn}.java", src)
        open_lines.append(f'            case "{screen.screen_id}" -> client.setScreen(new {pkg}.client.screen.{cn}());')

    src = f"""\
package {pkg}.client;

import net.minecraft.client.Minecraft;

public class ModScreens {{
    public static void open(Minecraft client, String screenId) {{
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


def _write_mod_blocks(mod, java_root: Path, pkg: str):
    if not mod._blocks:
        return

    pkg_block = f"{pkg}.block"
    imports = [f"import {pkg_block}.{b.get_class_name()};" for b in mod._blocks]
    reg_lines = []
    for b in mod._blocks:
        cn = b.get_class_name()
        bid = b.block_id
        reg_lines.append(
            f'    public static final RegistryObject<Block> {bid.upper()} = '
            f'BLOCKS.register("{bid}", {cn}::new);'
        )
    block_item_lines = []
    for b in mod._blocks:
        if b.drops_self:
            bid = b.block_id
            block_item_lines.append(
                f'    public static final RegistryObject<Item> {bid.upper()}_ITEM = '
                f'ITEMS.register("{bid}", () -> new BlockItem({bid.upper()}.get(), new Item.Properties()));'
            )

    src = f"""\
package {pkg};

import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.CreativeModeTabs;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.block.Block;
import net.minecraftforge.event.BuildCreativeModeTabContentsEvent;
import net.minecraftforge.registries.DeferredRegister;
import net.minecraftforge.registries.ForgeRegistries;
import net.minecraftforge.registries.RegistryObject;
{chr(10).join(imports)}

public class ModBlocks {{
    public static final DeferredRegister<Block> BLOCKS =
        DeferredRegister.create(ForgeRegistries.BLOCKS, {to_pascal(mod.mod_id)}.MOD_ID);
    public static final DeferredRegister<Item> ITEMS =
        DeferredRegister.create(ForgeRegistries.ITEMS, {to_pascal(mod.mod_id)}.MOD_ID);

{chr(10).join(reg_lines)}
{chr(10).join(block_item_lines)}

    public static void addCreative(BuildCreativeModeTabContentsEvent event) {{
        if (event.getTabKey() == CreativeModeTabs.BUILDING_BLOCKS) {{
{chr(10).join([f"            event.accept({b.block_id.upper()}_ITEM);" for b in mod._blocks if b.drops_self]) if any(b.drops_self for b in mod._blocks) else "            // No block items"}
        }}
    }}
}}
"""
    _write_text(java_root / "ModBlocks.java", src)


def _write_mod_block_entities(mod, java_root: Path, pkg: str):
    block_entities = _blocks_with_block_entities(mod)
    if not block_entities:
        return

    be_dir = java_root / "blockentity"
    be_dir.mkdir(exist_ok=True)
    registrations = []
    for block in block_entities:
        cn = block.get_class_name()
        registrations.append(
            f'    public static final RegistryObject<BlockEntityType<{cn}BlockEntity>> {block.block_id.upper()} = '
            f'BLOCK_ENTITIES.register("{block.block_id}", () -> BlockEntityType.Builder.of({cn}BlockEntity::new, ModBlocks.{block.block_id.upper()}.get()).build(null));'
        )

    imports = [f"import {pkg}.blockentity.{block.get_class_name()}BlockEntity;" for block in block_entities]
    src = f"""\
package {pkg}.blockentity;

import {pkg}.{to_pascal(mod.mod_id)};
import {pkg}.ModBlocks;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraftforge.registries.DeferredRegister;
import net.minecraftforge.registries.ForgeRegistries;
import net.minecraftforge.registries.RegistryObject;
{chr(10).join(imports)}

public class ModBlockEntities {{
    public static final DeferredRegister<BlockEntityType<?>> BLOCK_ENTITIES =
        DeferredRegister.create(ForgeRegistries.BLOCK_ENTITY_TYPES, {to_pascal(mod.mod_id)}.MOD_ID);

{chr(10).join(registrations)}
}}
"""
    _write_text(be_dir / "ModBlockEntities.java", src)


def _write_mod_items(mod, java_root: Path, pkg: str):
    if not mod._items:
        return

    pkg_item = f"{pkg}.item"
    imports = [f"import {pkg_item}.{i.get_class_name()};" for i in mod._items]
    reg_lines = []
    for it in mod._items:
        cn = it.get_class_name()
        iid = it.item_id
        reg_lines.append(
            f'    public static final RegistryObject<Item> {iid.upper()} = '
            f'ITEMS.register("{iid}", {cn}::new);'
        )

    src = f"""\
package {pkg};

import net.minecraft.world.item.CreativeModeTabs;
import net.minecraft.world.item.Item;
import net.minecraftforge.event.BuildCreativeModeTabContentsEvent;
import net.minecraftforge.registries.DeferredRegister;
import net.minecraftforge.registries.ForgeRegistries;
import net.minecraftforge.registries.RegistryObject;
{chr(10).join(imports)}

public class ModItems {{
    public static final DeferredRegister<Item> ITEMS =
        DeferredRegister.create(ForgeRegistries.ITEMS, {to_pascal(mod.mod_id)}.MOD_ID);

{chr(10).join(reg_lines)}

    public static void addCreative(BuildCreativeModeTabContentsEvent event) {{
        if (event.getTabKey() == CreativeModeTabs.INGREDIENTS) {{
{chr(10).join([f"            event.accept({it.item_id.upper()});" for it in mod._items])}
        }}
    }}
}}
"""
    _write_text(java_root / "ModItems.java", src)


def _item_lookup_expr(mod: "Mod", item_ref: str) -> str:
    ref = (item_ref or "").strip()
    if not ref:
        return "net.minecraft.world.item.Items.AIR"
    if ":" in ref:
        namespace, path = ref.split(":", 1)
    else:
        namespace, path = mod.mod_id, ref
    for item in mod._items:
        if namespace == mod.mod_id and item.item_id == path:
            return f"ModItems.{item.item_id.upper()}.get()"
    return f'ForgeRegistries.ITEMS.getValue(new net.minecraft.resources.ResourceLocation("{namespace}", "{path}"))'


def _write_mod_creative_tabs(mod, java_root: Path, pkg: str):
    if not mod._creative_tabs:
        return

    class_name = to_pascal(mod.mod_id)
    registrations = []
    for tab in mod._creative_tabs:
        const_name = tab.tab_id.replace("/", "_").upper()
        title_key = f"itemGroup.{mod.mod_id}.{tab.tab_id.replace('/', '.')}"
        entry_lines = [
            f"                output.accept({_item_lookup_expr(mod, item_ref)});"
            for item_ref in tab.items
        ] or ["                // No explicit items"]
        registrations.append(
            f"""    public static final RegistryObject<CreativeModeTab> {const_name} = TABS.register("{tab.tab_id}", () ->
        CreativeModeTab.builder()
            .title(Component.translatable("{title_key}"))
            .icon(() -> new ItemStack({_item_lookup_expr(mod, tab.icon_item)}))
            .displayItems((parameters, output) -> {{
{chr(10).join(entry_lines)}
            }})
            .build()
    );"""
        )

    src = f"""\
package {pkg};

import net.minecraft.network.chat.Component;
import net.minecraft.core.registries.Registries;
import net.minecraft.world.item.CreativeModeTab;
import net.minecraft.world.item.ItemStack;
import net.minecraftforge.registries.DeferredRegister;
import net.minecraftforge.registries.ForgeRegistries;
import net.minecraftforge.registries.RegistryObject;

public class ModCreativeTabs {{
    public static final DeferredRegister<CreativeModeTab> TABS =
        DeferredRegister.create(Registries.CREATIVE_MODE_TAB, {class_name}.MOD_ID);

{chr(10).join(registrations)}
}}
"""
    _write_text(java_root / "ModCreativeTabs.java", src)


def _write_mod_keybinds(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
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
            f'    public static final KeyMapping {const_name} = new KeyMapping("{title_key}", InputConstants.Type.KEYSYM, {_keybind_code_expr(bind)}, "{category_key}");'
        )
        if bind.source:
            body = transpiler.transpile_method(bind.source)
            handlers.append(f"""\
        while ({const_name}.consumeClick()) {{
            if (client.player == null || client.level == null) {{
                continue;
            }}
            var player = client.player;
            var level = client.level;
            var server = client.getSingleplayerServer();
            var keybind = {const_name};
            BlockPos soundPos = player.blockPosition();
{body}
        }}""")
    src = f"""\
package {pkg}.client;

import com.mojang.blaze3d.platform.InputConstants;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraftforge.client.event.RegisterKeyMappingsEvent;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.eventbus.api.IEventBus;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import org.lwjgl.glfw.GLFW;
{chr(10).join(FORGE_EXTRA_IMPORTS)}

public class ModKeybinds {{
{chr(10).join(declarations)}

    public static void register(IEventBus bus) {{
        bus.addListener(ModKeybinds::onRegisterKeyMappings);
        net.minecraftforge.common.MinecraftForge.EVENT_BUS.register(ModKeybinds.class);
    }}

    public static void onRegisterKeyMappings(RegisterKeyMappingsEvent event) {{
{chr(10).join([f"        event.register({bind.keybind_id.replace('/', '_').upper()});" for bind in mod._keybinds])}
    }}

    @SubscribeEvent
    public static void onClientTick(TickEvent.ClientTickEvent event) {{
        if (event.phase != TickEvent.Phase.END) {{
            return;
        }}
        Minecraft client = Minecraft.getInstance();
{chr(10).join(handlers) if handlers else "        // No keybind handlers"}
    }}
}}
"""
    _write_text(client_dir / "ModKeybinds.java", src)


def _write_geo_block_renderers(mod, java_root: Path, pkg: str):
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
import net.minecraft.resources.ResourceLocation;
import software.bernie.geckolib.model.GeoModel;

public class {model_cn} extends GeoModel<{cn}BlockEntity> {{
    private ResourceLocation parseRef(String raw, String fallbackNamespace, String fallbackPath) {{
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {{
            return new ResourceLocation(fallbackNamespace, fallbackPath);
        }}
        int split = value.indexOf(':');
        if (split >= 0) {{
            return new ResourceLocation(value.substring(0, split), value.substring(split + 1));
        }}
        return new ResourceLocation("{mod.mod_id}", value);
    }}

    @Override
    public ResourceLocation getModelResource({cn}BlockEntity animatable) {{
        return parseRef(animatable.getModelOverride(), "{model_ns}", "{model_path}");
    }}

    @Override
    public ResourceLocation getTextureResource({cn}BlockEntity animatable) {{
        return parseRef(animatable.getTextureOverride(), "{tex_ns}", "{tex_path}");
    }}

    @Override
    public ResourceLocation getAnimationResource({cn}BlockEntity animatable) {{
        return new ResourceLocation("{anim_ns}", "{anim_path}");
    }}
}}
"""
        _write_text(model_dir / f"{model_cn}.java", model_src)

        renderer_src = f"""\
package {pkg}.client.renderer;

import {pkg}.blockentity.{cn}BlockEntity;
import {pkg}.client.model.{model_cn};
import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.blaze3d.vertex.VertexConsumer;
import net.minecraft.client.renderer.MultiBufferSource;
import net.minecraft.client.renderer.RenderType;
import net.minecraft.resources.ResourceLocation;
import software.bernie.geckolib.cache.object.BakedGeoModel;
import software.bernie.geckolib.core.object.Color;
import software.bernie.geckolib.renderer.GeoBlockRenderer;

public class {renderer_cn} extends GeoBlockRenderer<{cn}BlockEntity> {{
    public {renderer_cn}() {{
        super(new {model_cn}());
    }}

    @Override
    public RenderType getRenderType({cn}BlockEntity animatable, ResourceLocation texture, MultiBufferSource bufferSource, float partialTick) {{
        return {_forge_render_type_expr(getattr(block, "render_layer", "translucent" if not block.opaque else "solid"))};
    }}

    @Override
    public void preRender(PoseStack poseStack, {cn}BlockEntity animatable, BakedGeoModel model, MultiBufferSource bufferSource, VertexConsumer buffer, boolean isReRender, float partialTick, int packedLight, int packedOverlay, float red, float green, float blue, float alpha) {{
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
            f"        net.minecraft.client.renderer.blockentity.BlockEntityRenderers.register({pkg}.blockentity.ModBlockEntities.{block.block_id.upper()}.get(), context -> new {pkg}.client.renderer.{renderer_cn}());"
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
import net.minecraft.resources.ResourceLocation;
import software.bernie.geckolib.model.GeoModel;

public class {model_cn} extends GeoModel<{cn}> {{
    private ResourceLocation parseRef(String raw, String fallbackNamespace, String fallbackPath) {{
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {{
            return new ResourceLocation(fallbackNamespace, fallbackPath);
        }}
        int split = value.indexOf(':');
        if (split >= 0) {{
            return new ResourceLocation(value.substring(0, split), value.substring(split + 1));
        }}
        return new ResourceLocation("{mod.mod_id}", value);
    }}

    @Override
    public ResourceLocation getModelResource({cn} animatable) {{
        return parseRef(animatable.getModelOverride(), "{model_ns}", "{model_path}");
    }}

    @Override
    public ResourceLocation getTextureResource({cn} animatable) {{
        return parseRef(animatable.getTextureOverride(), "{tex_ns}", "{tex_path}");
    }}

    @Override
    public ResourceLocation getAnimationResource({cn} animatable) {{
        return new ResourceLocation("{anim_ns}", "{anim_path}");
    }}
}}
"""
        _write_text(model_dir / f"{model_cn}.java", model_src)

        renderer_src = f"""\
package {pkg}.client.renderer;

import {pkg}.client.model.{model_cn};
import {pkg}.entity.{cn};
import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.blaze3d.vertex.VertexConsumer;
import net.minecraft.client.renderer.MultiBufferSource;
import net.minecraft.client.renderer.RenderType;
import net.minecraft.client.renderer.entity.EntityRendererProvider;
import net.minecraft.resources.ResourceLocation;
import software.bernie.geckolib.cache.object.BakedGeoModel;
import software.bernie.geckolib.core.object.Color;
import software.bernie.geckolib.renderer.GeoEntityRenderer;

public class {renderer_cn} extends GeoEntityRenderer<{cn}> {{
    public {renderer_cn}(EntityRendererProvider.Context ctx) {{
        super(ctx, new {model_cn}());
        this.shadowRadius = {getattr(entity, "shadow_radius", 0.5)}f;
    }}

    @Override
    public RenderType getRenderType({cn} animatable, ResourceLocation texture, MultiBufferSource bufferSource, float partialTick) {{
        return {_forge_render_type_expr(getattr(entity, "render_layer", "solid"))};
    }}

    @Override
    public void preRender(PoseStack poseStack, {cn} animatable, BakedGeoModel model, MultiBufferSource bufferSource, VertexConsumer buffer, boolean isReRender, float partialTick, int packedLight, int packedOverlay, float red, float green, float blue, float alpha) {{
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
            f"        net.minecraft.client.renderer.entity.EntityRenderers.register({pkg}.entity.ModEntities.{entity.entity_id.upper()}.get(), context -> new {pkg}.client.renderer.{renderer_cn}(context));"
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


def _write_mod_entities(mod, java_root: Path, pkg: str):
    if not mod._entities:
        return

    entity_dir = java_root / "entity"
    entity_dir.mkdir(exist_ok=True)
    imports = [f"import {pkg}.entity.{entity.get_class_name()};" for entity in mod._entities]
    reg_lines = []
    attribute_lines = []
    for entity in mod._entities:
        flags = ".fireImmune()" if entity.fireproof else ""
        reg_lines.append(
            f'    public static final RegistryObject<EntityType<{entity.get_class_name()}>> {entity.entity_id.upper()} = '
            f'ENTITIES.register("{entity.entity_id}", () -> EntityType.Builder.<{entity.get_class_name()}>of({entity.get_class_name()}::new, {_mob_category(entity.spawn_group)})'
            f'.sized({entity.width}f, {entity.height}f)'
            f'.clientTrackingRange({entity.tracking_range})'
            f'.updateInterval({entity.update_rate})'
            f'{flags}.build("{mod.mod_id}:{entity.entity_id}"));'
        )
        attribute_lines.append(
            f"        event.put({entity.entity_id.upper()}.get(), {entity.get_class_name()}.createAttributes().build());"
        )

    src = f"""\
package {pkg}.entity;

import {pkg}.{to_pascal(mod.mod_id)};
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.MobCategory;
import net.minecraftforge.event.entity.EntityAttributeCreationEvent;
import net.minecraftforge.registries.DeferredRegister;
import net.minecraftforge.registries.ForgeRegistries;
import net.minecraftforge.registries.RegistryObject;
{chr(10).join(imports)}

public class ModEntities {{
    public static final DeferredRegister<EntityType<?>> ENTITIES =
        DeferredRegister.create(ForgeRegistries.ENTITY_TYPES, {to_pascal(mod.mod_id)}.MOD_ID);

{chr(10).join(reg_lines)}

    public static void registerAttributes(EntityAttributeCreationEvent event) {{
{chr(10).join(attribute_lines)}
    }}
}}
"""
    _write_text(entity_dir / "ModEntities.java", src)


def _write_block_classes(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
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
    hooks = block.get_hooks()
    has_block_entity = block.has_block_entity or getattr(block, "uses_block_data", False) or bool(getattr(block, "geo_model", "")) or "on_tick" in hooks
    uses_rotation = getattr(block, "variable_rotation", False)
    uses_model_shapes = uses_rotation or getattr(block, "model_collision", False)
    shape_boxes = _model_boxes_for_block(Path.cwd(), mod, block) if uses_model_shapes else {}
    has_shape_boxes = bool(shape_boxes)

    settings = (
        f"BlockBehaviour.Properties.of()"
        f".strength({block.hardness}f, {block.resistance}f)"
        f".lightLevel(state -> {_block_light_level(block)})"
        f".friction({block.slipperiness}f)"
    )
    if not block.collidable:
        settings += ".noCollission()"
    if block.requires_tool:
        settings += ".requiresCorrectToolForDrops()"
    if not block.opaque:
        settings += ".noOcclusion()"
    if getattr(block, "emissive_level", 0) > 0:
        settings += ".emissiveRendering((state, getter, pos) -> true)"

    shape_fields = []
    if has_shape_boxes:
        if uses_rotation:
            for facing in ("north", "east", "south", "west"):
                if facing in shape_boxes:
                    shape_fields.append(_forge_shape_code(f"SHAPE_{facing.upper()}", shape_boxes[facing]))
        elif "default" in shape_boxes:
            shape_fields.append(_forge_shape_code("SHAPE_DEFAULT", shape_boxes["default"]))
    shape_fields_str = "\n".join(shape_fields)

    method_blocks = []

    if "on_use" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_use"])
        )
        method_blocks.append(f"""\
    @Override
    public InteractionResult use(BlockState state, Level level, BlockPos pos,
                                  Player player, InteractionHand hand, BlockHitResult hit) {{
        ItemStack stack = player.getItemInHand(hand);
        {f"{cn}BlockEntity blockEntity = level.getBlockEntity(pos) instanceof {cn}BlockEntity be ? be : null;" if has_block_entity else ""}
        BlockPos soundPos = pos;
{body}
        return InteractionResult.SUCCESS;
    }}""")

    if "on_place" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_place"])
        )
        method_blocks.append(f"""\
    @Override
    public void setPlacedBy(Level level, BlockPos pos, BlockState state,
                             @Nullable LivingEntity placer, ItemStack stack) {{
        Player player = placer instanceof Player ? (Player) placer : null;
        {f"{cn}BlockEntity blockEntity = level.getBlockEntity(pos) instanceof {cn}BlockEntity be ? be : null;" if has_block_entity else ""}
        BlockPos soundPos = pos;
{body}
    }}""")

    if "on_break" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_break"])
        )
        method_blocks.append(f"""\
    @Override
    public void playerDestroy(Level level, Player player, BlockPos pos, BlockState state,
                               @Nullable BlockEntity te, ItemStack stack) {{
        {f"{cn}BlockEntity blockEntity = level.getBlockEntity(pos) instanceof {cn}BlockEntity be ? be : null;" if has_block_entity else ""}
        BlockPos soundPos = pos;
{body}
        super.playerDestroy(level, player, pos, state, te, stack);
    }}""")

    methods_str = "\n\n".join(method_blocks)
    base_class = "Block"
    extra_imports = ""
    extra_methods = ""
    state_members = ""
    state_methods = ""
    if uses_rotation:
        state_members = """
    public static final DirectionProperty FACING = BlockStateProperties.HORIZONTAL_FACING;
"""
        constructor_default_state = """
        this.registerDefaultState(this.stateDefinition.any().setValue(FACING, Direction.NORTH));"""
        outline_shape_expr = (
            "switch (state.getValue(FACING)) {\n"
            "            case NORTH -> SHAPE_NORTH;\n"
            "            case EAST -> SHAPE_EAST;\n"
            "            case SOUTH -> SHAPE_SOUTH;\n"
            "            case WEST -> SHAPE_WEST;\n"
            "            default -> Shapes.block();\n"
            "        }"
            if has_shape_boxes
            else "super.getShape(state, level, pos, context)"
        )
        collision_shape_expr = (
            "switch (state.getValue(FACING)) {\n"
            "            case NORTH -> SHAPE_NORTH;\n"
            "            case EAST -> SHAPE_EAST;\n"
            "            case SOUTH -> SHAPE_SOUTH;\n"
            "            case WEST -> SHAPE_WEST;\n"
            "            default -> Shapes.block();\n"
            "        }"
            if has_shape_boxes
            else "super.getCollisionShape(state, level, pos, context)"
        )
        state_methods = f"""
    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {{
        builder.add(FACING);
    }}

    @Override
    @Nullable
    public BlockState getStateForPlacement(BlockPlaceContext ctx) {{
        return this.defaultBlockState().setValue(FACING, ctx.getHorizontalDirection().getOpposite());
    }}

    @Override
    public VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {{
        return {outline_shape_expr};
    }}"""
        if getattr(block, "model_collision", False) and has_shape_boxes and block.collidable:
            state_methods += f"""

    @Override
    public VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {{
        return {collision_shape_expr};
    }}"""
    else:
        constructor_default_state = ""
        if has_shape_boxes:
            state_methods += """
    @Override
    public VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
        return SHAPE_DEFAULT;
    }"""
        if getattr(block, "model_collision", False) and has_shape_boxes and block.collidable:
            state_methods += """

    @Override
    public VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
        return SHAPE_DEFAULT;
    }"""
    if has_block_entity:
        base_class = "BaseEntityBlock"
        extra_imports = f"""
import {pkg}.blockentity.{cn}BlockEntity;
import {pkg}.blockentity.ModBlockEntities;
import net.minecraft.world.level.block.BaseEntityBlock;
import net.minecraft.world.level.block.RenderShape;
import net.minecraft.world.level.block.entity.BlockEntityTicker;
import net.minecraft.world.level.block.entity.BlockEntityType;"""
        codec_members = ""
        if is_at_least(mod.minecraft_version, "1.21"):
            extra_imports += """
import com.mojang.serialization.MapCodec;"""
            codec_members = f"""
    public static final MapCodec<{cn}> CODEC = MapCodec.unit(new {cn}());

    @Override
    protected MapCodec<? extends BaseEntityBlock> codec() {{
        return CODEC;
    }}
"""
        ticker_body = "        return null;"
        if "on_tick" in hooks:
            ticker_body = (
                f"        return createTickerHelper(type, ModBlockEntities.{block.block_id.upper()}.get(), "
                f"{cn}BlockEntity::tick);"
            )
        render_shape_return = "RenderShape.ENTITYBLOCK_ANIMATED" if getattr(block, "geo_model", "") else "RenderShape.MODEL"
        extra_methods = f"""{codec_members}
    @Override
    public BlockEntity newBlockEntity(BlockPos pos, BlockState state) {{
        return new {cn}BlockEntity(pos, state);
    }}

    @Override
    public RenderShape getRenderShape(BlockState state) {{
        return {render_shape_return};
    }}

    @Override
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(Level level, BlockState state, BlockEntityType<T> type) {{
{ticker_body}
    }}"""

    src = f"""\
package {pkg}.block;

import net.minecraft.core.BlockPos;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.level.block.state.properties.DirectionProperty;
import net.minecraft.core.Direction;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;
import net.minecraft.network.chat.Component;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.resources.ResourceLocation;
import net.minecraftforge.registries.ForgeRegistries;
import org.jetbrains.annotations.Nullable;
{extra_imports}

/**
 * {block.get_display_name()} — generated by fabricpy
 */
public class {cn} extends {base_class} {{
{state_members}
{shape_fields_str}

    public {cn}() {{
        super({settings});
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
    data_imports = """
import net.minecraft.nbt.CompoundTag;
import net.minecraft.world.level.block.Block;"""
    if is_at_least(mod.minecraft_version, "1.21"):
        data_imports += """
import net.minecraft.core.HolderLookup;"""
        data_methods = """
    private CompoundTag fabricpyData = new CompoundTag();

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
        setChanged();
    }

    public int getIntData(String key) {
        return fabricpyData.getInt(key);
    }

    public void setIntData(String key, int value) {
        fabricpyData.putInt(key, value);
        setChanged();
    }

    public boolean getBoolData(String key) {
        return fabricpyData.getBoolean(key);
    }

    public void setBoolData(String key, boolean value) {
        fabricpyData.putBoolean(key, value);
        setChanged();
    }

    public double getDoubleData(String key) {
        return fabricpyData.getDouble(key);
    }

    public void setDoubleData(String key, double value) {
        fabricpyData.putDouble(key, value);
        setChanged();
    }

    public boolean hasData(String key) {
        return fabricpyData.contains(key);
    }

    public void removeData(String key) {
        fabricpyData.remove(key);
        setChanged();
    }

    public void syncData() {
        setChanged();
        if (level != null) {
            level.sendBlockUpdated(worldPosition, getBlockState(), getBlockState(), Block.UPDATE_ALL);
        }
    }

    public String getAnimationName() {
        return getStringData("__fabricpy_animation");
    }

    public void setAnimationState(String animationName, boolean loop) {
        setStringData("__fabricpy_animation", animationName == null ? "" : animationName);
        setBoolData("__fabricpy_animation_loop", loop);
        syncData();
    }

    public void clearAnimationName() {
        removeData("__fabricpy_animation");
        removeData("__fabricpy_animation_loop");
        syncData();
    }

    @Override
    protected void saveAdditional(CompoundTag tag, HolderLookup.Provider registries) {
        super.saveAdditional(tag, registries);
        tag.put("fabricpy_data", fabricpyData.copy());
    }

    @Override
    protected void loadAdditional(CompoundTag tag, HolderLookup.Provider registries) {
        super.loadAdditional(tag, registries);
        this.fabricpyData = tag.contains("fabricpy_data") ? tag.getCompound("fabricpy_data").copy() : new CompoundTag();
    }"""
    else:
        data_methods = """
    private CompoundTag fabricpyData = new CompoundTag();

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
        setChanged();
    }

    public int getIntData(String key) {
        return fabricpyData.getInt(key);
    }

    public void setIntData(String key, int value) {
        fabricpyData.putInt(key, value);
        setChanged();
    }

    public boolean getBoolData(String key) {
        return fabricpyData.getBoolean(key);
    }

    public void setBoolData(String key, boolean value) {
        fabricpyData.putBoolean(key, value);
        setChanged();
    }

    public double getDoubleData(String key) {
        return fabricpyData.getDouble(key);
    }

    public void setDoubleData(String key, double value) {
        fabricpyData.putDouble(key, value);
        setChanged();
    }

    public boolean hasData(String key) {
        return fabricpyData.contains(key);
    }

    public void removeData(String key) {
        fabricpyData.remove(key);
        setChanged();
    }

    public void syncData() {
        setChanged();
        if (level != null) {
            level.sendBlockUpdated(worldPosition, getBlockState(), getBlockState(), Block.UPDATE_ALL);
        }
    }

    public String getAnimationName() {
        return getStringData("__fabricpy_animation");
    }

    public void setAnimationState(String animationName, boolean loop) {
        setStringData("__fabricpy_animation", animationName == null ? "" : animationName);
        setBoolData("__fabricpy_animation_loop", loop);
        syncData();
    }

    public void clearAnimationName() {
        removeData("__fabricpy_animation");
        removeData("__fabricpy_animation_loop");
        syncData();
    }

    @Override
    protected void saveAdditional(CompoundTag tag) {
        super.saveAdditional(tag);
        tag.put("fabricpy_data", fabricpyData.copy());
    }

    @Override
    public void load(CompoundTag tag) {
        super.load(tag);
        this.fabricpyData = tag.contains("fabricpy_data") ? tag.getCompound("fabricpy_data").copy() : new CompoundTag();
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
            "private CompoundTag fabricpyData = new CompoundTag();",
            "private CompoundTag fabricpyData = new CompoundTag();\n    private final AnimatableInstanceCache geoCache = software.bernie.geckolib.util.GeckoLibUtil.createInstanceCache(this);",
            1,
        )
        data_methods += f"""

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
    public static void tick(Level level, BlockPos pos, BlockState state, {cn}BlockEntity blockEntity) {{
        BlockPos soundPos = pos;
{body}
    }}"""

    src = f"""\
package {pkg}.blockentity;

import net.minecraft.core.BlockPos;
{data_imports}
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;

/**
 * Block entity backing {block.get_display_name()}.
 */
public class {cn}BlockEntity extends BlockEntity{" implements GeoBlockEntity" if getattr(block, "geo_model", "") else ""} {{

    public {cn}BlockEntity(BlockPos pos, BlockState state) {{
        super(ModBlockEntities.{block.block_id.upper()}.get(), pos, state);
    }}
{data_methods}
{tick_method}
}}
"""
    _write_text(block_entity_dir / f"{cn}BlockEntity.java", src)


def _write_item_classes(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._items:
        return
    item_dir = java_root / "item"
    item_dir.mkdir(exist_ok=True)
    for item in mod._items:
        _write_single_item(mod, item, item_dir, pkg, transpiler)


def _write_single_item(mod, item, item_dir: Path, pkg: str, transpiler: JavaTranspiler):
    cn = item.get_class_name()
    hooks = item.get_hooks()

    settings = f"new Item.Properties().stacksTo({item.max_stack_size})"
    if item.max_damage > 0:
        settings += f".durability({item.max_damage})"
    if item.fireproof:
        settings += ".fireResistant()"

    method_blocks = []
    if "on_right_click" in hooks:
        body = transpiler.transpile_method(
            __import__("inspect").getsource(hooks["on_right_click"])
        )
        method_blocks.append(f"""\
    @Override
    public InteractionResultHolder<ItemStack> use(Level level, Player user, InteractionHand hand) {{
        Player player = user;
        ItemStack stack = user.getItemInHand(hand);
        BlockPos soundPos = user.blockPosition();
{body}
        return InteractionResultHolder.success(stack);
    }}""")

    methods_str = "\n\n".join(method_blocks)

    src = f"""\
package {pkg}.item;

import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResultHolder;
import net.minecraft.world.level.Level;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.resources.ResourceLocation;
import net.minecraftforge.registries.ForgeRegistries;

/**
 * {item.get_display_name()} — generated by fabricpy
 */
public class {cn} extends Item {{

    public {cn}() {{
        super({settings});
    }}

{methods_str}
}}
"""
    _write_text(item_dir / f"{cn}.java", src)


def _write_entity_classes(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._entities:
        return
    entity_dir = java_root / "entity"
    entity_dir.mkdir(exist_ok=True)
    for entity in mod._entities:
        _write_single_entity(entity, entity_dir, pkg, transpiler)


def _write_single_entity(entity, entity_dir: Path, pkg: str, transpiler: JavaTranspiler):
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
        Level level = this.level();
        BlockPos pos = this.blockPosition();
        BlockPos soundPos = pos;
{body}
    }}""")

    geo_imports = ""
    geo_fields = ""
    geo_methods = ""
    if is_geo:
        default_animation = getattr(entity, "default_animation", "")
        geo_imports = """import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.network.syncher.EntityDataSerializers;
import net.minecraft.network.syncher.SynchedEntityData;
import software.bernie.geckolib.animatable.GeoEntity;
import software.bernie.geckolib.core.animatable.instance.AnimatableInstanceCache;
import software.bernie.geckolib.core.animation.AnimatableManager;
import software.bernie.geckolib.core.animation.AnimationController;
import software.bernie.geckolib.core.animation.RawAnimation;
import software.bernie.geckolib.util.GeckoLibUtil;"""
        geo_fields = f"""
    private static final EntityDataAccessor<String> FABRICPY_ANIMATION = SynchedEntityData.defineId({cn}.class, EntityDataSerializers.STRING);
    private static final EntityDataAccessor<Boolean> FABRICPY_ANIMATION_LOOP = SynchedEntityData.defineId({cn}.class, EntityDataSerializers.BOOLEAN);
    private static final EntityDataAccessor<String> FABRICPY_TEXTURE = SynchedEntityData.defineId({cn}.class, EntityDataSerializers.STRING);
    private static final EntityDataAccessor<String> FABRICPY_MODEL = SynchedEntityData.defineId({cn}.class, EntityDataSerializers.STRING);
    private final AnimatableInstanceCache geoCache = GeckoLibUtil.createInstanceCache(this);
"""
        geo_methods = f"""
    @Override
    protected void defineSynchedData() {{
        super.defineSynchedData();
        this.entityData.define(FABRICPY_ANIMATION, "");
        this.entityData.define(FABRICPY_ANIMATION_LOOP, true);
        this.entityData.define(FABRICPY_TEXTURE, "");
        this.entityData.define(FABRICPY_MODEL, "");
    }}

    public String getAnimationName() {{
        return this.entityData.get(FABRICPY_ANIMATION);
    }}

    public void setAnimationState(String animationName, boolean loop) {{
        this.entityData.set(FABRICPY_ANIMATION, animationName == null ? "" : animationName);
        this.entityData.set(FABRICPY_ANIMATION_LOOP, loop);
    }}

    public void clearAnimationName() {{
        this.entityData.set(FABRICPY_ANIMATION, "");
        this.entityData.set(FABRICPY_ANIMATION_LOOP, true);
    }}

    public String getTextureOverride() {{
        return this.entityData.get(FABRICPY_TEXTURE);
    }}

    public void setTextureOverride(String value) {{
        this.entityData.set(FABRICPY_TEXTURE, value == null ? "" : value);
    }}

    public String getModelOverride() {{
        return this.entityData.get(FABRICPY_MODEL);
    }}

    public void setModelOverride(String value) {{
        this.entityData.set(FABRICPY_MODEL, value == null ? "" : value);
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
            boolean loop = this.entityData.get(FABRICPY_ANIMATION_LOOP);
            RawAnimation animation = loop
                ? RawAnimation.begin().thenLoop(animationName)
                : RawAnimation.begin().thenPlay(animationName);
            return state.setAndContinue(animation);
        }}));
    }}

    @Override
    public AnimatableInstanceCache getAnimatableInstanceCache() {{
        return geoCache;
    }}
"""

    src = f"""\
package {pkg}.entity;

import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.PathfinderMob;
import net.minecraft.world.entity.ai.attributes.AttributeSupplier;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.level.Level;
{geo_imports}

/**
 * {entity.get_display_name()} - generated by fabricpy
 */
public class {cn} extends PathfinderMob{" implements GeoEntity" if is_geo else ""} {{
{geo_fields}

    public {cn}(EntityType<? extends PathfinderMob> entityType, Level level) {{
        super(entityType, level);
    }}

    public static AttributeSupplier.Builder createAttributes() {{
        return LivingEntity.createLivingAttributes()
            .add(Attributes.MAX_HEALTH, {entity.max_health}d)
            .add(Attributes.MOVEMENT_SPEED, {entity.movement_speed}d)
            .add(Attributes.ATTACK_DAMAGE, {entity.attack_damage}d)
            .add(Attributes.FOLLOW_RANGE, {entity.follow_range}d)
            .add(Attributes.KNOCKBACK_RESISTANCE, {entity.knockback_resistance}d);
    }}

    @Override
    protected void registerGoals() {{
        // No default AI goals generated by fabricpy yet.
    }}

{geo_methods}
{chr(10).join(method_blocks)}
}}
"""
    _write_text(entity_dir / f"{cn}.java", src)


def _write_events(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._events:
        return
    event_dir = java_root / "event"
    event_dir.mkdir(exist_ok=True)

    imports = set()
    imports.add("import net.minecraftforge.eventbus.api.SubscribeEvent;")
    imports.add("import net.minecraftforge.fml.common.Mod;")
    imports.add("import net.minecraft.world.entity.player.Player;")
    imports.add("import net.minecraft.network.chat.Component;")
    imports.add("import net.minecraft.server.level.ServerPlayer;")
    imports.add("import net.minecraft.world.effect.MobEffectInstance;")
    imports.add("import net.minecraft.resources.ResourceLocation;")
    imports.add("import net.minecraft.sounds.SoundSource;")
    imports.add("import net.minecraft.server.level.ServerLevel;")
    imports.add("import net.minecraft.world.level.Level;")
    imports.add("import net.minecraft.core.BlockPos;")
    imports.add("import net.minecraftforge.registries.ForgeRegistries;")
    imports.add("import java.util.HashMap;")
    imports.add("import java.util.Map;")
    imports.add("import java.util.UUID;")

    method_blocks = []

    for ev in mod._events:
        ev_name = ev["event"]
        if ev_name == "player_offhand_change":
            imports.add("import net.minecraftforge.event.TickEvent;")
            imports.add("import net.minecraft.world.InteractionHand;")
            body = transpiler.transpile_method(ev["source"])
            method_blocks.append(f"""\
    @SubscribeEvent
    public static void onPlayerOffhandChange(TickEvent.PlayerTickEvent event) {{
        if (event.phase != TickEvent.Phase.END) {{
            return;
        }}
        Player player = event.player;
        UUID playerId = player.getUUID();
        var server = player.getServer();
        var level = player.level();
        var stack = player.getOffhandItem();
        var hand = InteractionHand.OFF_HAND;
        var soundPos = player.blockPosition();
        String previousOffhandItemId = LAST_OFFHAND_ITEM.getOrDefault(playerId, "");
        int previousOffhandCount = LAST_OFFHAND_COUNT.getOrDefault(playerId, 0);
        String currentOffhandItemId = ForgeRegistries.ITEMS.getKey(stack.getItem()).toString();
        int currentOffhandCount = stack.getCount();
        if (!currentOffhandItemId.equals(previousOffhandItemId) || currentOffhandCount != previousOffhandCount) {{
{body}
        }}
        LAST_OFFHAND_ITEM.put(playerId, currentOffhandItemId);
        LAST_OFFHAND_COUNT.put(playerId, currentOffhandCount);
    }}""")
            continue
        ev_info = FORGE_EVENT_MAP.get(ev_name)
        if not ev_info:
            method_blocks.append(f"    // Unknown event: {ev_name}")
            continue

        imports.add(ev_info["import"])
        body = transpiler.transpile_method(ev["source"])

        setup_line = ev_info.get("setup", "")
        local_lines = "\n".join(ev_info.get("locals", []))
        if not local_lines and ev_info.get("player_expr"):
            local_lines = f"        Player player = {ev_info['player_expr']};"

        method_blocks.append(f"""\
    @SubscribeEvent
    public static void on{to_pascal(ev_name)}({ev_info['class']} event) {{
{setup_line}
{local_lines}
{body}
    }}""")

    src = f"""\
package {pkg}.event;

import {pkg}.{to_pascal(mod.mod_id)};
import net.minecraftforge.fml.event.lifecycle.FMLCommonSetupEvent;
{chr(10).join(sorted(imports))}

@Mod.EventBusSubscriber(modid = {to_pascal(mod.mod_id)}.MOD_ID, bus = Mod.EventBusSubscriber.Bus.FORGE)
public class ModEvents {{
    private static final Map<UUID, String> LAST_OFFHAND_ITEM = new HashMap<>();
    private static final Map<UUID, Integer> LAST_OFFHAND_COUNT = new HashMap<>();

    public static void onCommonSetup(FMLCommonSetupEvent event) {{
        // Common setup
    }}

{chr(10).join(method_blocks)}
}}
"""
    _write_text(event_dir / "ModEvents.java", src)


def _write_commands(mod, java_root: Path, pkg: str, transpiler: JavaTranspiler):
    if not mod._commands:
        return
    cmd_dir = java_root / "command"
    cmd_dir.mkdir(exist_ok=True)

    command_blocks = []
    for cmd in mod._commands:
        body = transpiler.transpile_method(cmd["source"])
        perm = cmd["permission_level"]
        perm_clause = f".requires(s -> s.hasPermission({perm}))" if perm > 0 else ""
        command_blocks.append(f"""\
        event.getDispatcher().register(Commands.literal("{cmd['name']}")
            {perm_clause}
            .executes(context -> {{
{body}
                return 1;
            }}));""")

    src = f"""\
package {pkg}.command;

import {pkg}.{to_pascal(mod.mod_id)};
import com.mojang.brigadier.context.CommandContext;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraftforge.event.RegisterCommandsEvent;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.fml.common.Mod;

@Mod.EventBusSubscriber(modid = {to_pascal(mod.mod_id)}.MOD_ID, bus = Mod.EventBusSubscriber.Bus.FORGE)
public class ModCommands {{

    @SubscribeEvent
    public static void onRegisterCommands(RegisterCommandsEvent event) {{
{chr(10).join(command_blocks)}
    }}
}}
"""
    _write_text(cmd_dir / "ModCommands.java", src)


def _write_resources(mod, res_root: Path, loader_name: str = "forge"):
    # META-INF/mods.toml
    meta_dir = res_root / "META-INF"
    meta_dir.mkdir(parents=True, exist_ok=True)

    meta = FORGE_VERSIONS.get(mod.minecraft_version)
    if meta is None:
        raise ValueError(f"Forge does not support minecraft_version={mod.minecraft_version!r} in this generator.")

    extra_meta_deps = []
    for dep in _deps_for_loader(mod, loader_name):
        if dep.mod_id and dep.required:
            extra_meta_deps.append(f"""
[[dependencies.{mod.mod_id}]]
    modId="{dep.mod_id}"
    mandatory=true
    versionRange="{dep.version_range}"
    ordering="{dep.ordering}"
    side="{dep.side}"
""")

    deps = f"""
[[dependencies.{mod.mod_id}]]
    modId="forge"
    mandatory=true
    versionRange="{meta.forge_dep}"
    ordering="NONE"
    side="BOTH"

[[dependencies.{mod.mod_id}]]
    modId="minecraft"
    mandatory=true
    versionRange="[{mod.minecraft_version},)"
    ordering="NONE"
    side="BOTH"
"""
    deps += "".join(extra_meta_deps)

    mods_toml = f"""\
modLoader="javafml"
loaderVersion="{meta.loader_version}"
license="{mod.license}"

[[mods]]
modId="{mod.mod_id}"
version="{mod.version}"
displayName="{mod.name}"
description="{mod.description}"
{deps}
"""
    _write_text(meta_dir / "mods.toml", mods_toml)

    # pack.mcmeta
    _write_text(res_root / "pack.mcmeta", json.dumps({
        "pack": {"pack_format": meta.pack_format, "description": f"{mod.name} resources"}
    }, indent=2))

    # lang
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


def _write_gradle_files(mod, project_dir: Path, loader_name: str = "forge"):
    mc = mod.minecraft_version
    use_geckolib = _uses_geckolib(mod)
    v = FORGE_VERSIONS.get(mc)
    if v is None:
        raise ValueError(f"Forge does not support minecraft_version={mc!r} in this generator.")
    extra_repos = _forge_repository_lines(mod, loader_name)
    extra_deps = [_forge_dependency_line(dep, mc, loader_name) for dep in _deps_for_loader(mod, loader_name)]

    if is_at_least(mc, "1.21"):
        build_gradle = f"""\
plugins {{
    id 'java'
    id 'idea'
    id 'eclipse'
    id 'net.minecraftforge.gradle' version '{v.plugin}'
}}

version = "{mod.version}"
group = "{mod.package}"

java.toolchain.languageVersion = JavaLanguageVersion.of({v.java})

sourceSets.main.resources {{ srcDir 'src/generated/resources' }}

minecraft {{
    mappings channel: 'official', version: '{mc}'

    runs {{
        configureEach {{
            workingDir = layout.projectDirectory.dir('run')
            systemProperty 'forge.enabledGameTestNamespaces', '{mod.mod_id}'
        }}

        register('client')

        register('server') {{
            args '--nogui'
        }}

        register('gameTestServer')

        register('data') {{
            workingDir = layout.projectDirectory.dir('run-data')
            args '--mod', '{mod.mod_id}', '--all', '--output', layout.projectDirectory.dir('src/generated/resources'), '--existing', layout.projectDirectory.dir('src/main/resources')
        }}
    }}
}}

repositories {{
    minecraft.mavenizer(it)
    maven fg.forgeMaven
    maven fg.minecraftLibsMaven
    {"maven { url = 'https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/' }" if use_geckolib else ""}
{chr(10).join(extra_repos)}
    mavenCentral()
}}

dependencies {{
    implementation minecraft.dependency('net.minecraftforge:forge:{mc}-{v.forge}')
    {"implementation fg.deobf('software.bernie.geckolib:geckolib-forge-" + mc + ":" + v.geckolib + "')" if use_geckolib else ""}
{chr(10).join(extra_deps)}
}}

tasks.withType(JavaCompile).configureEach {{
    options.encoding = 'UTF-8'
}}
"""
        settings_gradle = f"""\
plugins {{
    id 'org.gradle.toolchains.foojay-resolver-convention' version '{v.settings_plugin}'
}}

rootProject.name = "{mod.mod_id}-forge"
"""
        gradle_properties = (
            "org.gradle.caching=true\n"
            "org.gradle.parallel=true\n"
            "org.gradle.configureondemand=true\n\n"
            "org.gradle.configuration-cache=true\n"
            "org.gradle.configuration-cache.parallel=true\n"
            "org.gradle.configuration-cache.problems=warn\n\n"
            "net.minecraftforge.gradle.merge-source-sets=true\n"
        )
    else:
        build_gradle = f"""\
buildscript {{
    repositories {{
        maven {{ url = 'https://maven.minecraftforge.net' }}
        mavenCentral()
    }}
    dependencies {{
            classpath 'net.minecraftforge.gradle:ForgeGradle:{v.plugin}'
    }}
}}

apply plugin: 'net.minecraftforge.gradle'
apply plugin: 'java'

version = "{mod.version}"
group = "{mod.package}"

java {{
    toolchain.languageVersion = JavaLanguageVersion.of({v.java})
}}

minecraft {{
    mappings channel: 'official', version: '{mc}'

    runs {{
        client {{
            workingDirectory project.file('run')
            property 'forge.logging.console.level', 'debug'
            mods {{
                {mod.mod_id} {{
                    source sourceSets.main
                }}
            }}
        }}
        server {{
            workingDirectory project.file('run')
            property 'forge.logging.console.level', 'debug'
            mods {{
                {mod.mod_id} {{
                    source sourceSets.main
                }}
            }}
        }}
    }}
}}

repositories {{
    {"maven { url = 'https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/' }" if use_geckolib else ""}
{chr(10).join(extra_repos)}
    mavenCentral()
}}

dependencies {{
    minecraft 'net.minecraftforge:forge:{mc}-{v.forge}'
    {"implementation fg.deobf('software.bernie.geckolib:geckolib-forge-" + mc + ":" + v.geckolib + "')" if use_geckolib else ""}
{chr(10).join(extra_deps)}
}}

jar {{
    manifest {{
        attributes([
            "Specification-Title"  : "{mod.mod_id}",
            "Specification-Vendor" : "{', '.join(mod.authors) if mod.authors else 'Unknown'}",
            "Specification-Version": "1",
            "Implementation-Title" : project.name,
            "Implementation-Version": project.version,
            "Implementation-Vendor": "{', '.join(mod.authors) if mod.authors else 'Unknown'}",
        ])
    }}
}}
"""
        settings_gradle = f'rootProject.name = "{mod.mod_id}-forge"\n'
        gradle_properties = "org.gradle.jvmargs=-Xmx2G\n"

    _write_text(project_dir / "build.gradle", build_gradle)
    _write_text(project_dir / "settings.gradle", settings_gradle)
    _write_text(project_dir / "gradle.properties", gradle_properties)
    _write_text(project_dir / ".gitignore", ".gradle/\nbuild/\nrun/\n*.jar\n")

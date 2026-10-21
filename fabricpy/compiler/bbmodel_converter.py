import json
import math
from pathlib import Path


_FACE_NAMES = ("north", "south", "east", "west", "up", "down")


def _float_list(value, length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != length:
        return None
    try:
        numbers = [float(v) for v in value]
        return numbers if all(math.isfinite(v) for v in numbers) else None
    except (TypeError, ValueError):
        return None


def _cube_uv_from_box_uv(element: dict) -> list[float] | None:
    uv_offset = _float_list(element.get("uv_offset"), 2)
    if uv_offset:
        return uv_offset
    faces = element.get("faces")
    if isinstance(faces, dict):
        for face_name in _FACE_NAMES:
            face = faces.get(face_name)
            if isinstance(face, dict):
                uv = _float_list(face.get("uv"), 4)
                if uv:
                    return [uv[0], uv[1]]
    return None


def _cube_uv_from_faces(element: dict) -> dict | None:
    faces = element.get("faces")
    if not isinstance(faces, dict):
        return None
    uv_map = {}
    for face_name in _FACE_NAMES:
        face = faces.get(face_name)
        if not isinstance(face, dict):
            continue
        uv = _float_list(face.get("uv"), 4)
        if not uv:
            continue
        entry = {
            "uv": [uv[0], uv[1]],
            "uv_size": [uv[2] - uv[0], uv[3] - uv[1]],
        }
        rotation = face.get("rotation")
        if isinstance(rotation, (int, float)) and rotation:
            entry["uv_rotation"] = float(rotation)
        uv_map[face_name] = entry
    return uv_map or None


def _convert_cube(element: dict, box_uv_default: bool) -> dict | None:
    from_pos = _float_list(element.get("from"), 3)
    to_pos = _float_list(element.get("to"), 3)
    if not from_pos or not to_pos:
        return None
    cube = {
        "origin": from_pos,
        "size": [to_pos[i] - from_pos[i] for i in range(3)],
    }
    pivot = _float_list(element.get("origin"), 3)
    if pivot:
        cube["pivot"] = pivot
    rotation = _float_list(element.get("rotation"), 3)
    if rotation and any(abs(v) > 1e-6 for v in rotation):
        cube["rotation"] = rotation
    inflate = element.get("inflate")
    if isinstance(inflate, (int, float)) and inflate:
        cube["inflate"] = float(inflate)
    if bool(element.get("mirror_uv")) or bool(element.get("mirror")):
        cube["mirror"] = True

    if bool(element.get("box_uv", box_uv_default)):
        uv = _cube_uv_from_box_uv(element)
        if uv:
            cube["uv"] = uv
    else:
        uv = _cube_uv_from_faces(element)
        if uv:
            cube["uv"] = uv

    return cube


def _cube_bounds(cube: dict) -> tuple[float, float, float, float, float, float]:
    origin = cube["origin"]
    size = cube["size"]
    return (
        float(origin[0]),
        float(origin[1]),
        float(origin[2]),
        float(origin[0] + size[0]),
        float(origin[1] + size[1]),
        float(origin[2] + size[2]),
    )


def _merge_bounds(bounds: list[tuple[float, float, float, float, float, float]]) -> tuple[float, float, float, float, float, float]:
    xs1 = [b[0] for b in bounds]
    ys1 = [b[1] for b in bounds]
    zs1 = [b[2] for b in bounds]
    xs2 = [b[3] for b in bounds]
    ys2 = [b[4] for b in bounds]
    zs2 = [b[5] for b in bounds]
    return (min(xs1), min(ys1), min(zs1), max(xs2), max(ys2), max(zs2))


def convert_bbmodel_to_geckolib_geo(model: dict, mod_id: str, default_id: str) -> dict:
    if not isinstance(model, dict):
        raise ValueError("Blockbench model must be an object")
    resolution = model.get("resolution") if isinstance(model, dict) else None
    texture_width = int(resolution.get("width", 16)) if isinstance(resolution, dict) else 16
    texture_height = int(resolution.get("height", 16)) if isinstance(resolution, dict) else 16
    if texture_width <= 0 or texture_height <= 0:
        raise ValueError("Blockbench texture resolution must be positive")
    box_uv_default = bool(model.get("meta", {}).get("box_uv")) if isinstance(model.get("meta"), dict) else False

    group_map = {group["uuid"]: group for group in model.get("groups", []) if isinstance(group, dict) and "uuid" in group}
    elements = model.get("elements") if isinstance(model, dict) else None
    outliner = model.get("outliner") if isinstance(model, dict) else None
    if not isinstance(elements, list):
        elements = []
    if not isinstance(outliner, list):
        outliner = []

    element_map = {}
    converted_cubes = {}
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise ValueError("Blockbench elements must be objects")
        if element.get("export") is False:
            continue
        if element.get("type", "cube") != "cube":
            raise ValueError(f"Unsupported GeckoLib element {element.get('type')!r}; use cuboids")
        uuid = str(element.get("uuid") or f"element_{index}")
        element_map[uuid] = element
        cube = _convert_cube(element, box_uv_default)
        if cube is None:
            raise ValueError(f"Blockbench cube {uuid} needs numeric from/to coordinates")
        converted_cubes[uuid] = cube

    bones: list[dict] = []
    bone_by_name: dict[str, dict] = {}
    used_elements: set[str] = set()
    root_bone: dict | None = None
    synthetic_index = 0

    def ensure_root() -> dict:
        nonlocal root_bone
        if root_bone is None and "root" in bone_by_name:
            root_bone = bone_by_name["root"]
        if root_bone is None:
            root_bone = {"name": "root", "pivot": [0.0, 0.0, 0.0], "cubes": []}
            bones.append(root_bone)
            bone_by_name["root"] = root_bone
        return root_bone

    def new_group_name(raw_name: str | None) -> str:
        nonlocal synthetic_index
        name = (raw_name or "").strip()
        if not name:
            synthetic_index += 1
            name = f"bone_{synthetic_index}"
        existing = {bone["name"] for bone in bones}
        if name not in existing:
            return name
        suffix = 2
        while f"{name}_{suffix}" in existing:
            suffix += 1
        return f"{name}_{suffix}"

    def walk(nodes: list, parent_name: str | None = None):
        nonlocal root_bone
        for node in nodes:
            if isinstance(node, str):
                cube = converted_cubes.get(node)
                if not cube:
                    continue
                used_elements.add(node)
                target = ensure_root() if parent_name is None else bone_by_name.get(parent_name) or ensure_root()
                target.setdefault("cubes", []).append(cube)
                continue

            if not isinstance(node, dict):
                continue

            node = {**group_map.get(node.get("uuid"), {}), **node}
            bone_name = new_group_name(node.get("name"))
            bone = {"name": bone_name}
            if parent_name:
                bone["parent"] = parent_name

            pivot = _float_list(node.get("origin"), 3) or _float_list(node.get("pivot"), 3)
            bone["pivot"] = pivot or [0.0, 0.0, 0.0]

            rotation = _float_list(node.get("rotation"), 3)
            if rotation and any(abs(v) > 1e-6 for v in rotation):
                bone["rotation"] = rotation

            if node.get("visibility") is False:
                bone["neverRender"] = True

            bone["cubes"] = []
            bones.append(bone)
            bone_by_name[bone_name] = bone
            if bone_name == "root" and root_bone is None:
                root_bone = bone
            walk(node.get("children") if isinstance(node.get("children"), list) else [], bone_name)
            if not bone["cubes"]:
                bone.pop("cubes")

    walk(outliner)

    for uuid, cube in converted_cubes.items():
        if uuid not in used_elements:
            ensure_root().setdefault("cubes", []).append(cube)

    if not bones:
        ensure_root()

    bounds = []
    for bone in bones:
        for cube in bone.get("cubes", []):
            bounds.append(_cube_bounds(cube))
    if bounds:
        min_x, min_y, min_z, max_x, max_y, max_z = _merge_bounds(bounds)
        visible_bounds_width = max(1.0, max(max_x - min_x, max_z - min_z) / 16.0)
        visible_bounds_height = max(1.0, (max_y - min_y) / 16.0)
        visible_bounds_offset = [
            (min_x + max_x) / 32.0,
            (min_y + max_y) / 32.0,
            (min_z + max_z) / 32.0,
        ]
    else:
        visible_bounds_width = 1.0
        visible_bounds_height = 1.0
        visible_bounds_offset = [0.0, 0.5, 0.0]

    identifier = model.get("model_identifier") or model.get("geometry_name") or f"geometry.{mod_id}.{default_id.replace('/', '.')}"

    return {
        "format_version": "1.12.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier": identifier,
                    "texture_width": texture_width,
                    "texture_height": texture_height,
                    "visible_bounds_width": visible_bounds_width,
                    "visible_bounds_height": visible_bounds_height,
                    "visible_bounds_offset": visible_bounds_offset,
                },
                "bones": bones,
            }
        ],
    }


def compile_bbmodel_file(src: Path, dest: Path, mod_id: str, default_id: str) -> None:
    model = load_bbmodel(src)
    geo = convert_bbmodel_to_geckolib_geo(model, mod_id, default_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(geo, indent=2), encoding="utf-8")


def compile_bbmodels_in_assets(assets_mod_dir: Path, mod_id: str, source_assets_mod_dir: Path | None = None) -> list[Path]:
    compiled = []
    source_assets_mod_dir = source_assets_mod_dir or assets_mod_dir
    geo_root = assets_mod_dir / "geo"
    for src in sorted(geo_root.rglob("*.bbmodel")):
        rel = src.relative_to(geo_root).with_suffix("")
        dest = src.with_suffix(".geo.json")
        original = source_assets_mod_dir / src.relative_to(assets_mod_dir)
        compile_bbmodel_file(original if original.is_file() else src, dest, mod_id, rel.as_posix())
        compiled.append(dest)
    for kind in ("block", "item"):
        root = assets_mod_dir / "models" / kind
        for src in sorted(root.rglob("*.bbmodel")):
            dest = src.with_suffix(".json")
            # Hand-authored JSON always wins over an editor project.
            source_json = source_assets_mod_dir / "models" / kind / src.relative_to(root).with_suffix(".json")
            if source_json.is_file():
                continue
            rel = src.relative_to(root).with_suffix("").as_posix()
            original = source_assets_mod_dir / src.relative_to(assets_mod_dir)
            value = resolve_model_input(original if original.is_file() else src, mod_id, kind, rel, assets_mod_dir)
            dest.write_text(json.dumps(value, indent=2), encoding="utf-8")
            compiled.append(dest)
    return compiled


def load_bbmodel(src: Path) -> dict:
    """Read a Blockbench project, with a useful filename in every error."""
    try:
        model = json.loads(src.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read Blockbench model {src}: {exc}") from exc
    if not isinstance(model, dict) or not isinstance(model.get("elements"), list):
        raise ValueError(f"{src}: expected a Blockbench project with an elements list")
    return model


def _resource_path(value: str) -> str:
    import re
    clean = value.replace("\\", "/")
    if not re.fullmatch(r"[a-z0-9_./-]+", clean) or any(p in {"", ".", ".."} for p in clean.split("/")):
        raise ValueError(f"Invalid Minecraft resource path: {value!r}")
    return clean


def _texture_data(model: dict, src: Path, mod_id: str, texture_prefix: str, assets_dir: Path | None) -> dict:
    """Keep texture IDs stable; embedded and relative PNGs work without exports."""
    import base64
    import re
    import shutil

    textures = {}
    for index, texture in enumerate(model.get("textures", [])):
        if not isinstance(texture, dict):
            raise ValueError(f"{src}: texture {index} must be an object")
        key = str(texture.get("id", index))
        name = re.sub(r"[^a-z0-9_/-]+", "_", Path(texture.get("name") or f"texture_{index}").stem.lower())
        folder = str(texture.get("folder") or "").strip("/")
        path = _resource_path(f"{folder}/{name}" if folder else f"{texture_prefix}/{name}")
        namespace = texture.get("namespace") or mod_id
        if not re.fullmatch(r"[a-z0-9_.-]+", namespace):
            raise ValueError(f"{src}: invalid texture namespace {namespace!r}")
        textures[key] = f"{namespace}:{path}"
        if assets_dir is None:
            continue
        dest = assets_dir.parent / namespace / "textures" / f"{path}.png"
        source = texture.get("source", "")
        relative = texture.get("relative_path") or texture.get("path")
        if source.startswith("data:image/png;base64,"):
            try:
                data = base64.b64decode(source.split(",", 1)[1], validate=True)
            except ValueError as exc:
                raise ValueError(f"{src}: invalid embedded PNG for texture {key}") from exc
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"{src}: texture {key} is not a PNG")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        elif source.startswith("data:"):
            raise ValueError(f"{src}: texture {key} must be embedded as PNG")
        elif relative:
            texture_file = Path(str(relative).replace("\\", "/"))
            if not texture_file.is_absolute():
                texture_file = src.parent / texture_file
            if not texture_file.is_file():
                # Existing project textures are a valid alternative to editor paths.
                if not dest.is_file():
                    raise ValueError(f"{src}: missing texture {texture_file}; embed it in Blockbench or supply {dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if texture_file.resolve() != dest.resolve():
                    shutil.copy2(texture_file, dest)
        elif namespace == mod_id and not dest.is_file():
            project_texture = Path("assets") / namespace / "textures" / f"{path}.png"
            if project_texture.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                if project_texture.resolve() != dest.resolve():
                    shutil.copy2(project_texture, dest)
            else:
                raise ValueError(f"{src}: texture {key} has no PNG source; embed it in Blockbench or supply {project_texture}")
    if textures:
        textures["particle"] = next(iter(textures.values()))
    return textures


def convert_bbmodel_to_java_model(model: dict, textures: dict | None = None) -> dict:
    """Convert cuboids to the vanilla Java block/item model format.

    Unsupported geometry is an error instead of a silently damaged model.
    """
    import copy

    if model.get("animations"):
        raise ValueError("Animated .bbmodel files require geo_model/GeckoLib; static model= cannot play animations")
    groups = list(model.get("groups", []))
    def check_groups(nodes):
        for node in nodes:
            if isinstance(node, dict):
                groups.append(node)
                check_groups(node.get("children", []))
    check_groups(model.get("outliner", []))
    if any(any(float(v) != 0 for v in group.get("rotation", [])) for group in groups):
        raise ValueError("Rotated groups require geo_model/GeckoLib; apply group rotations in Blockbench for static models")
    resolution = model.get("resolution") or {}
    width, height = float(resolution.get("width", 16)), float(resolution.get("height", 16))
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError("Blockbench texture resolution must be positive")
    result = {"textures": dict(textures or {}), "elements": []}
    for element in model.get("elements", []):
        if element.get("export") is False:
            continue
        if element.get("type", "cube") != "cube":
            raise ValueError(f"Unsupported Blockbench element {element.get('type')!r}; use cuboids for Minecraft models")
        start, end = _float_list(element.get("from"), 3), _float_list(element.get("to"), 3)
        if start is None or end is None:
            raise ValueError("Blockbench cubes need numeric from/to coordinates")
        inflate = float(element.get("inflate", 0))
        if not math.isfinite(inflate):
            raise ValueError("Blockbench cube inflate must be finite")
        start = [value - inflate for value in start]
        end = [value + inflate for value in end]
        if any(a > b for a, b in zip(start, end)):
            raise ValueError("Blockbench cube from coordinates cannot exceed to coordinates")
        if any(v < -16 or v > 32 for v in start + end):
            raise ValueError("Static Minecraft cube coordinates must be between -16 and 32; use geo_model for larger geometry")
        cube = {"from": start, "to": end, "faces": {}}
        if "shade" in element:
            cube["shade"] = bool(element["shade"])
        rotation = _float_list(element.get("rotation", [0, 0, 0]), 3)
        if rotation is None:
            raise ValueError("Invalid Blockbench cube rotation")
        axes = [i for i, angle in enumerate(rotation) if angle != 0]
        if axes:
            if len(axes) > 1 or rotation[axes[0]] not in {-45, -22.5, 22.5, 45}:
                raise ValueError("Static Minecraft cubes support one rotation axis at ±22.5 or ±45 degrees; use geo_model otherwise")
            cube["rotation"] = {
                "origin": _float_list(element.get("origin", [8, 8, 8]), 3),
                "axis": "xyz"[axes[0]], "angle": rotation[axes[0]],
                "rescale": bool(element.get("rescale", False)),
            }
        for face_name, face in element.get("faces", {}).items():
            if face_name not in _FACE_NAMES or face.get("texture") is None:
                continue
            tex = str(face["texture"]).lstrip("#")
            if tex not in result["textures"]:
                raise ValueError(f"Face references missing Blockbench texture {tex!r}")
            uv = _float_list(face.get("uv"), 4)
            if uv is None:
                raise ValueError(f"Face {face_name} needs four UV coordinates")
            texture = next((t for i, t in enumerate(model.get("textures", [])) if str(t.get("id", i)) == tex), {})
            tw, th = float(texture.get("uv_width", width)), float(texture.get("uv_height", height))
            if not math.isfinite(tw) or not math.isfinite(th) or tw <= 0 or th <= 0:
                raise ValueError("Blockbench texture resolution must be positive")
            entry = {"uv": [uv[0]*16/tw, uv[1]*16/th, uv[2]*16/tw, uv[3]*16/th], "texture": f"#{tex}"}
            for key in ("rotation", "cullface", "tintindex"):
                if key in face:
                    entry[key] = face[key]
            cube["faces"][face_name] = entry
        result["elements"].append(cube)
    for key in ("parent", "display", "ambientocclusion", "gui_light", "overrides"):
        if key in model:
            result[key] = copy.deepcopy(model[key])
    return result


def resolve_model_input(value, mod_id: str, kind: str, default_id: str, assets_dir: Path | None = None):
    """Resolve a dict, JSON file, .bbmodel file or namespaced model parent."""
    import copy
    if value is None:
        return None
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if not isinstance(value, (str, Path)):
        raise TypeError("model must be a dict, .json/.bbmodel path, or model resource ID")
    ref = str(value).replace("\\", "/")
    if not ref.lower().endswith((".json", ".bbmodel")):
        namespace, path = ref.split(":", 1) if ":" in ref else (mod_id, ref)
        return {"parent": f"{namespace}:{_resource_path(path)}"}
    src = Path(ref)
    if not src.is_file():
        namespace, path = ref.split(":", 1) if ":" in ref else (mod_id, ref)
        if not path.startswith(("block/", "item/")):
            path = f"{kind}/{path}"
        src = Path("assets") / namespace / "models" / _resource_path(path)
    if ref.lower().endswith(".bbmodel"):
        model = load_bbmodel(src)
        texture_prefix = f"{kind}/{_resource_path(default_id)}"
        textures = _texture_data(model, src, mod_id, texture_prefix, assets_dir)
        try:
            return convert_bbmodel_to_java_model(model, textures)
        except ValueError as exc:
            raise ValueError(f"{src}: {exc}") from exc
    try:
        result = json.loads(src.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read model {src}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{src}: model JSON must be an object")
    return result

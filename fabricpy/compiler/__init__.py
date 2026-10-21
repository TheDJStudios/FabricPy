"""
Main compiler entry point.

Called by Mod.compile() and Mod.generate(). Resolves loader addons, generates
projects, and invokes each backend builder to produce mod artifacts.
"""

from pathlib import Path
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fabricpy.mod import Mod


def compile_mod(mod: "Mod", output_dir: str = "./dist", clean: bool = False, *, generate_only: bool = False):
    """
    Compile a Mod into .jar files.

    Steps:
      1. Validate the mod definition
      2. Generate loader project(s)
      4. Run Gradle build(s)
      5. Copy output .jar(s) to output_dir
    """
    from fabricpy.compiler.jar_scanner import build_symbol_index_for_project
    from fabricpy.addons import resolve_addon

    _validate(mod)

    out = Path(output_dir).resolve()
    if not generate_only:
        out.mkdir(parents=True, exist_ok=True)

    gen_root = Path(".fabricpy_build").resolve()
    gen_root.mkdir(exist_ok=True)

    loaders = _resolve_loaders(mod.loader, mod.minecraft_version)

    print(f"[fabricpy] Compiling {mod.name!r} v{mod.version} -> {loaders}")
    print(f"  Blocks:   {len(mod._blocks)}")
    print(f"  Items:    {len(mod._items)}")
    print(f"  Entities: {len(mod._entities)}")
    print(f"  Events:   {len(mod._events)}")
    print(f"  Commands: {len(mod._commands)}")
    print(f"  Mixins:   {len(mod._mixins)}")
    print(f"  Recipes:  {len(mod._recipes)}")
    print(f"  Advancements: {len(mod._advancements)}")
    print(f"  Sounds:   {len(mod._sounds)}")
    print(f"  Creative Tabs: {len(mod._creative_tabs)}")
    print(f"  Keybinds: {len(mod._keybinds)}")
    print(f"  Packets:  {len(mod._packets)}")
    print(f"  Screens:  {len(mod._screens)}")
    print(f"  Dependencies: {len(mod._dependencies)}")
    print(f"  Dimension Types: {len(mod._dimension_types)}")
    print(f"  Dimensions:      {len(mod._dimensions)}")
    print(f"  Structures:      {len(mod._structures)}")
    print()

    results = {}

    for loader in loaders:
        addon = resolve_addon("loader", loader, mod.minecraft_version)
        if addon is None:
            raise ValueError(
                f"No loader addon found for loader={loader!r} minecraft_version={mod.minecraft_version!r}."
            )

        project_dir = gen_root / f"{mod.mod_id}-{loader}"
        addon.generate_project(mod, project_dir)
        if generate_only:
            results[loader] = project_dir
            continue
        meta = project_dir / ".fabricpy_meta" / "interop_project.json"
        if meta.exists():
            import json
            payload = json.loads(meta.read_text(encoding="utf-8"))
            if payload.get("dependencies") or any("geckolib" in line for line in payload.get("dependency_lines", [])):
                if not addon.prepare_dependencies(project_dir, mod.minecraft_version):
                    results[loader] = False
                    continue
                # Freshly resolved dependencies must be indexed before translating constructors.
                addon.generate_project(mod, project_dir)
        success = addon.build_project(project_dir, mod.minecraft_version, clean=clean, output_dir=out)
        results[loader] = success
        if success:
            try:
                if build_symbol_index_for_project(project_dir) is not None:
                    print(f"[fabricpy] Interop index written: {project_dir / '.fabricpy_meta' / 'symbol_index.json'}")
            except Exception as exc:
                print(f"[fabricpy] Warning: interop index generation failed for {loader}: {exc}")

    print()
    print("=" * 50)
    print(f"[fabricpy] Compilation complete for {mod.name}")
    for loader, ok in results.items():
        status = "GENERATED" if generate_only else ("SUCCESS" if ok else "FAILED (source generated, check errors above)")
        print(f"  {loader.upper():8} {status}")
    if any(results.values()):
        print(f"  Output: {gen_root if generate_only else out}")
    print("=" * 50)
    return results


def _resolve_loaders(loader: str, minecraft_version: str) -> list[str]:
    from fabricpy.addons import supported_targets

    loader = loader.lower().strip()

    supported = supported_targets("loader", minecraft_version)
    if not supported:
        raise ValueError(
            f"No loader addons found for minecraft_version={minecraft_version!r}."
        )

    alias_map = {
        "both": [name for name in ("fabric", "forge") if name in supported],
        "all": list(supported),
    }

    if loader in alias_map:
        if not alias_map[loader]:
            raise ValueError(f"No targets available for loader alias {loader!r}; supported: {supported}")
        return alias_map[loader]

    requested = [part.strip() for part in loader.replace("+", ",").split(",") if part.strip()]
    if not requested:
        raise ValueError("loader is required")

    invalid = [name for name in requested if name not in supported]
    if invalid:
        raise ValueError(
            f"Invalid loader(s) for Minecraft {minecraft_version}: {invalid!r}. "
            f"Supported loaders: {supported!r}."
        )

    seen = []
    for name in requested:
        if name not in seen:
            seen.append(name)
    return seen


def _validate(mod: "Mod"):
    """Basic sanity checks before compiling."""
    from fabricpy.addons import supported_targets

    errors = []

    if not mod.mod_id:
        errors.append("mod_id is required")
    elif not re.fullmatch(r"[a-z][a-z0-9_]*", mod.mod_id):
        errors.append("mod_id must start with a lowercase letter and contain only lowercase letters, digits, and underscores")
    if not mod.name:
        errors.append("name is required")

    try:
        loaders = _resolve_loaders(mod.loader, mod.minecraft_version)
    except ValueError as exc:
        errors.append(str(exc))
        loaders = []

    supported = supported_targets("loader", mod.minecraft_version)
    if loaders and not supported:
        errors.append(f"No loader addons found for minecraft_version={mod.minecraft_version!r}")

    block_ids = set()
    for block in mod._blocks:
        if not block.block_id:
            errors.append(f"{block.__name__} is missing block_id")
        elif block.block_id in block_ids:
            errors.append(f"duplicate block_id: {block.block_id}")
        else:
            block_ids.add(block.block_id)
        if "on_tick" in block.get_hooks() and not (block.has_block_entity or getattr(block, "uses_block_data", False) or getattr(block, "geo_model", "")):
            errors.append(f"{block.__name__} uses @on_tick but has_block_entity is not enabled")

    item_ids = set()
    for item in mod._items:
        if not item.item_id:
            errors.append(f"{item.__name__} is missing item_id")
        elif item.item_id in item_ids:
            errors.append(f"duplicate item_id: {item.item_id}")
        else:
            item_ids.add(item.item_id)

    entity_ids = set()
    for entity in mod._entities:
        if not entity.entity_id:
            errors.append(f"{entity.__name__} is missing entity_id")
        elif entity.entity_id in entity_ids:
            errors.append(f"duplicate entity_id: {entity.entity_id}")
        else:
            entity_ids.add(entity.entity_id)
    for mx in mod._mixins:
        if not mx.target_class:
            errors.append(f"{mx.__name__} is missing target_class")
    for structure in mod._structures:
        if not Path(structure["path"]).exists():
            errors.append(f"structure source file does not exist: {structure['path']}")

    for kind, entries in (("block", mod._blocks), ("item", mod._items), ("entity", mod._entities)):
        for entry in entries:
            identifier = getattr(entry, f"{kind}_id")
            if identifier and not re.fullmatch(r"[a-z_][a-z0-9_]*", identifier):
                errors.append(f"{entry.__name__}: {kind}_id must contain lowercase letters, digits and underscores, and cannot start with a digit")
    for identifier in block_ids & item_ids:
        errors.append(f"item_id {identifier!r} conflicts with a block's automatically registered item")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", mod.package):
        errors.append("package must be a valid dotted Java package")
    if errors:
        raise ValueError(
            "Mod definition has errors:\n" + "\n".join(f"  - {e}" for e in errors)
        )

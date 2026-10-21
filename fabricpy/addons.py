from __future__ import annotations

import hashlib
import os
import sys
import warnings
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Callable


@dataclass(frozen=True)
class Addon:
    kind: str
    target: str
    minecraft_version: str
    name: str
    module: ModuleType
    path: Path
    priority: int = 0

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.target, self.minecraft_version)

    @property
    def build_label(self) -> str:
        return self.target

    def generate_project(self, mod, project_dir: Path):
        generator: Callable | None = getattr(self.module, "generate_project", None)
        if generator is None:
            raise ValueError(f"Addon {self.name!r} does not define generate_project(mod, project_dir)")
        return generator(mod, project_dir)

    def prepare_dependencies(self, project_dir: Path, minecraft_version: str):
        """Backends own dependency resolution; custom builders need not use Gradle."""
        prepare = getattr(self.module, "prepare_dependencies", None)
        if prepare is not None:
            return prepare(project_dir, minecraft_version)
        if getattr(self.module, "build_project", None) is not None:
            return True
        from fabricpy.compiler.gradle_runner import resolve_project_dependencies
        return resolve_project_dependencies(project_dir, minecraft_version, self.target)

    def build_project(self, project_dir: Path, minecraft_version: str, clean: bool = False, output_dir: Path | None = None):
        builder: Callable | None = getattr(self.module, "build_project", None)
        if builder is not None:
            return builder(project_dir, minecraft_version, clean=clean, output_dir=output_dir)
        from fabricpy.compiler.gradle_runner import run_build

        return run_build(project_dir, minecraft_version, self.build_label, clean=clean, output_dir=output_dir)


def _addons_root() -> Path:
    return Path(__file__).resolve().parent / "addons"


def _load_module(module_path: Path) -> ModuleType:
    module_name = "fabricpy_dynamic_" + hashlib.sha256(str(module_path.resolve()).encode()).hexdigest()[:16]
    spec = spec_from_file_location(module_name, module_path, submodule_search_locations=[str(module_path.parent)])
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load addon module from {module_path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _addons_from_module(module: ModuleType, module_path: Path) -> list[Addon]:
    kind = str(getattr(module, "ADDON_KIND", "")).strip().lower()
    target = str(getattr(module, "ADDON_TARGET", getattr(module, "LOADER", ""))).strip().lower()
    name = str(getattr(module, "ADDON_NAME", module_path.parent.name)).strip() or module_path.parent.name
    priority = int(getattr(module, "ADDON_PRIORITY", 0))

    raw_versions = getattr(module, "MINECRAFT_VERSIONS", None)
    if raw_versions is None:
        single_version = str(getattr(module, "MINECRAFT_VERSION", "")).strip()
        raw_versions = [single_version] if single_version else []

    versions = [str(version).strip() for version in raw_versions if str(version).strip()]
    if not kind or not target or not versions:
        return []

    return [
        Addon(
            kind=kind,
            target=target,
            minecraft_version=minecraft_version,
            name=name,
            module=module,
            path=module_path.parent,
            priority=priority,
        )
        for minecraft_version in versions
    ]


def discover_addons() -> list[Addon]:
    roots = [_addons_root(), Path.cwd() / "fabricpy_addons"]
    roots.extend(Path(value).expanduser() for value in os.environ.get("FABRICPY_ADDON_PATH", "").split(os.pathsep) if value)
    paths = sorted({p.resolve() for root in roots if root.exists() for p in root.rglob("addon.py")})
    found: list[Addon] = []
    for module_path in paths:
        try:
            module = _load_module(module_path)
            found.extend(_addons_from_module(module, module_path))
        except Exception as exc:
            warnings.warn(f"Cannot load FabricPy addon {module_path}: {exc}", RuntimeWarning, stacklevel=2)
            continue

    found.sort(key=lambda addon: (addon.kind, addon.target, addon.minecraft_version, addon.priority, addon.name))
    return found


def list_addons(kind: str = "", minecraft_version: str = "") -> list[dict]:
    kind = (kind or "").strip().lower()
    minecraft_version = (minecraft_version or "").strip()

    addons = []
    for addon in discover_addons():
        if kind and addon.kind != kind:
            continue
        if minecraft_version and addon.minecraft_version != minecraft_version:
            continue
        addons.append({
            "kind": addon.kind,
            "target": addon.target,
            "minecraft_version": addon.minecraft_version,
            "name": addon.name,
            "priority": addon.priority,
            "path": str(addon.path),
        })
    return addons


def resolve_addon(kind: str, target: str, minecraft_version: str) -> Addon | None:
    kind = kind.strip().lower()
    target = target.strip().lower()
    minecraft_version = minecraft_version.strip()

    matches = [
        addon
        for addon in discover_addons()
        if addon.kind == kind and addon.target == target and addon.minecraft_version == minecraft_version
    ]
    if not matches:
        return None

    matches.sort(key=lambda addon: (addon.priority, addon.name))
    return matches[-1]


def supported_targets(kind: str, minecraft_version: str) -> list[str]:
    kind = kind.strip().lower()
    minecraft_version = minecraft_version.strip()
    targets = {
        addon.target
        for addon in discover_addons()
        if addon.kind == kind and addon.minecraft_version == minecraft_version
    }
    return sorted(targets)

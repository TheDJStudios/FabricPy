"""
Interop metadata and symbol-index scaffolding.

This module does not resolve jars yet. It writes a stable metadata shape
that future jar introspection and typed symbol resolution can consume.
"""

from __future__ import annotations

import json
from pathlib import Path
from fabricpy.compiler.dependencies import dependencies_for_loader
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fabricpy.mod import Mod


def _normalize_dep_loader(loader: str) -> str:
    return (loader or "both").strip().lower()


def _interop_roots(mod: "Mod", loader: str) -> list[dict]:
    roots = [
        {"root": "mc", "kind": "minecraft", "loader": loader},
        {"root": "loader", "kind": "loader_api", "loader": loader},
        {"root": f"mod.{mod.mod_id}", "kind": "generated_mod", "loader": loader},
    ]
    for dep in dependencies_for_loader(mod, loader):
        dep_loader = _normalize_dep_loader(dep.loader)
        if dep.mod_id:
            roots.append({
                "root": f"dep.{dep.mod_id}",
                "kind": "dependency_mod",
                "loader": loader,
                "mod_id": dep.mod_id,
                "coordinate": dep.coordinate,
            })
    return roots


def _dependency_entries(mod: "Mod", loader: str) -> list[dict]:
    entries = []
    for dep in dependencies_for_loader(mod, loader):
        dep_loader = _normalize_dep_loader(dep.loader)
        entries.append({
            "coordinate": dep.coordinate,
            "path": str(dep.path) if dep.path else "",
            "loader": dep_loader or "both",
            "scope": dep.scope or "",
            "repo": dep.repo or "",
            "deobf": bool(dep.deobf),
            "mod_id": dep.mod_id or "",
            "required": bool(dep.required),
            "version_range": dep.version_range or "*",
            "ordering": dep.ordering or "NONE",
            "side": dep.side or "BOTH",
        })
    return entries


def write_interop_metadata(
    mod: "Mod",
    project_dir: Path,
    loader: str,
    repositories: list[str],
    dependency_lines: list[str],
    manifest_dependencies: list[dict] | None = None,
):
    meta_dir = project_dir / ".fabricpy_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    cleaned_repositories = []
    for repo in repositories:
        value = (repo or "").strip()
        if not value:
            continue
        if 'url = "' in value:
            value = value.split('url = "', 1)[1].split('"', 1)[0]
        elif "url = '" in value:
            value = value.split("url = '", 1)[1].split("'", 1)[0]
        cleaned_repositories.append(value)

    project_meta = {
        "format": 1,
        "kind": "fabricpy_interop_project",
        "mod_id": mod.mod_id,
        "mod_name": mod.name,
        "minecraft_version": mod.minecraft_version,
        "loader": loader,
        "package": mod.package,
        "project_dir": str(project_dir.resolve()),
        "repositories": cleaned_repositories,
        "dependencies": _dependency_entries(mod, loader),
        "dependency_lines": dependency_lines,
        "manifest_dependencies": manifest_dependencies or [],
        "generated_files": {
            "build_gradle": str((project_dir / "build.gradle").resolve()),
            "settings_gradle": str((project_dir / "settings.gradle").resolve()),
            "resources_dir": str((project_dir / "src" / "main" / "resources").resolve()),
            "java_dir": str((project_dir / "src" / "main" / "java").resolve()),
        },
    }

    symbol_index_stub = {
        "format": 1,
        "kind": "fabricpy_symbol_index_stub",
        "status": "pending_jar_introspection",
        "mod_id": mod.mod_id,
        "loader": loader,
        "minecraft_version": mod.minecraft_version,
        "package": mod.package,
        "roots": _interop_roots(mod, loader),
        "class_sources": [
            {"kind": "minecraft", "loader": loader},
            {"kind": "loader_api", "loader": loader},
            *[
                {
                    "kind": "dependency",
                    "loader": loader,
                    "coordinate": dep["coordinate"],
                    "mod_id": dep["mod_id"],
                    "repo": dep["repo"],
                }
                for dep in project_meta["dependencies"]
            ],
        ],
        "notes": [
            "This file is a scaffold for future jar introspection.",
            "It is not a resolved type index yet.",
            "Future compiler phases should replace this stub with discovered classes, methods, fields, and signatures.",
        ],
    }

    project_meta_path = meta_dir / "interop_project.json"
    try:
        previous_meta = json.loads(project_meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous_meta = {}
    resolution_keys = ("loader", "minecraft_version", "dependencies", "dependency_lines", "repositories")
    if any(previous_meta.get(key) != project_meta.get(key) for key in resolution_keys):
        (meta_dir / "resolved_dependencies.json").unlink(missing_ok=True)
    project_meta_path.write_text(json.dumps(project_meta, indent=2), encoding="utf-8")
    (meta_dir / "symbol_index.stub.json").write_text(json.dumps(symbol_index_stub, indent=2), encoding="utf-8")

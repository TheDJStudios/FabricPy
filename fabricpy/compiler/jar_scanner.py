"""
Dependency jar scanning and lightweight Python stub generation.

This is a first-pass interop scanner:
- resolves dependency jars from the local Gradle cache
- indexes package/class names from class files
- emits a symbol index JSON
- emits lightweight Python stub packages for autocomplete and discovery
"""

from __future__ import annotations

import json
import keyword
import os
import shutil
import re
import subprocess
import zipfile
from pathlib import Path


CORE_GROUP_PREFIXES = (
    "com.mojang",
    "net.fabricmc",
    "net.minecraftforge",
    "org.spongepowered",
)


def _parse_coordinate(value: str) -> tuple[str, str, str] | None:
    parts = (value or "").strip().split(":")
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def _load_project_meta(project_dir: Path) -> dict | None:
    meta_path = project_dir / ".fabricpy_meta" / "interop_project.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _extract_gradle_coordinates(project_meta: dict) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()

    for dep in project_meta.get("dependencies", []):
        if dep.get("path"):
            path = str(Path(dep["path"]).resolve())
            if path not in seen:
                entries.append({**dep, "coordinate": dep.get("coordinate") or path, "explicit": True})
                seen.add(path)
            continue
        coord = dep.get("coordinate", "")
        if coord and coord not in seen:
            entries.append({
                "coordinate": coord,
                "repo": dep.get("repo", ""),
                "mod_id": dep.get("mod_id", ""),
                "explicit": True,
            })
            seen.add(coord)

    for line in project_meta.get("dependency_lines", []):
        for match in re.findall(r"['\"]([A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+:[^'\"]+)['\"]", line or ""):
            if match not in seen:
                entries.append({
                    "coordinate": match,
                    "repo": "",
                    "mod_id": "",
                    "explicit": False,
                })
                seen.add(match)

    return entries


def _should_scan_dependency(entry: dict) -> bool:
    if entry.get("path"):
        return True
    parsed = _parse_coordinate(entry.get("coordinate", ""))
    if not parsed:
        return False
    group, artifact, _version = parsed
    if entry.get("explicit") or entry.get("mod_id"):
        return True
    if "geckolib" in artifact.lower():
        return True
    if group.startswith(CORE_GROUP_PREFIXES):
        return False
    return True


def _dependency_alias(entry: dict) -> str:
    if entry.get("mod_id"):
        return _sanitize_python_name(entry["mod_id"])
    parsed = _parse_coordinate(entry.get("coordinate", ""))
    if entry.get("path"):
        return _sanitize_python_name(Path(entry["path"]).stem)
    if not parsed:
        return "unknown"
    _group, artifact, _version = parsed
    if "geckolib" in artifact.lower():
        return "geckolib"
    return _sanitize_python_name(artifact)


def _sanitize_python_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", value or "").strip("_")
    if not clean:
        return "unknown"
    if clean[0].isdigit():
        clean = f"pkg_{clean}"
    if keyword.iskeyword(clean):
        clean += "_"
    return clean


def _resolve_gradle_cached_jars(coordinate: str) -> list[Path]:
    parsed = _parse_coordinate(coordinate)
    if not parsed:
        return []
    group, artifact, version = parsed
    version = version.split("@", 1)[0]
    parts = coordinate.split("@", 1)[0].split(":")
    classifier = parts[3] if len(parts) > 3 else ""
    cache_root = Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle")) / "caches" / "modules-2" / "files-2.1"
    base = cache_root / group / artifact / version
    if not base.exists():
        return []
    jars = []
    for jar in base.rglob("*.jar"):
        name = jar.name.lower()
        if name.endswith("-sources.jar") or name.endswith("-javadoc.jar"):
            continue
        expected = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "") + ".jar"
        if jar.name == expected:
            jars.append(jar)
    return sorted(jars)


def _artifact_identity(coordinate: str) -> tuple[str, str, str, str] | None:
    """Identity excluding the selected version: Gradle may resolve a range or conflict."""
    notation, _, extension = coordinate.partition("@")
    parts = notation.split(":")
    if len(parts) not in {3, 4}:
        return None
    return parts[0], parts[1], parts[3] if len(parts) == 4 else "", extension or "jar"


def _resolved_artifact_coordinate(artifact: dict) -> str:
    coordinate = artifact.get("coordinate", "")
    parsed = _parse_coordinate(coordinate)
    if not parsed:
        return coordinate
    group, name, version = parsed
    version = version.split("@", 1)[0]
    parts = coordinate.split("@", 1)[0].split(":")
    classifier = artifact.get("classifier")
    if classifier is None:
        classifier = parts[3] if len(parts) > 3 else ""
        # Older resolver records omitted classifiers. Do not mislabel an API JAR
        # as the unclassified artifact when its conventional filename identifies it.
        if not classifier:
            filename = Path(artifact.get("path", "")).name
            prefix = f"{name}-{version}-"
            if filename.startswith(prefix) and filename.endswith(".jar"):
                classifier = filename[len(prefix):-4]
    extension = artifact.get("extension") or (coordinate.split("@", 1)[1] if "@" in coordinate else "jar")
    return f"{group}:{name}:{version}" + (f":{classifier}" if classifier else "") + (f"@{extension}" if extension != "jar" else "")


def _resolved_jars_for_coordinate(coordinate: str, artifacts: list[dict]) -> list[Path]:
    identity = _artifact_identity(coordinate)
    if identity is None or identity[-1] != "jar":
        return []
    return [Path(artifact["path"]) for artifact in artifacts
            if artifact.get("path") and _artifact_identity(_resolved_artifact_coordinate(artifact)) == identity]


def _scan_jar_classes(jar_path: Path) -> tuple[dict[str, set[str]], list[str]]:
    packages: dict[str, set[str]] = {}
    full_class_names: list[str] = []
    with zipfile.ZipFile(jar_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".class"):
                continue
            if name.startswith("META-INF/") or name.rsplit("/", 1)[-1] in {"module-info.class", "package-info.class"}:
                continue
            clean = name[:-6]
            parts = clean.split("/")
            if not parts:
                continue
            class_name = parts[-1]
            if "$" in class_name:
                nested_name = class_name.split("$", 1)[1]
                # Skip anonymous/synthetic nested classes but keep named inners.
                if any(part[:1].isdigit() for part in nested_name.split("$")):
                    continue
            package_name = ".".join(parts[:-1])
            packages.setdefault(package_name, set()).add(class_name.replace("$", "_"))
            binary_class_name = f"{package_name}.{class_name}" if package_name else class_name
            full_class_names.append(binary_class_name)
    return packages, sorted(full_class_names)


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _run_javap(jar_path: Path, class_names: list[str]) -> str:
    if not class_names:
        return ""
    java_home = os.environ.get("JAVA_HOME")
    javap = str(Path(java_home) / "bin" / ("javap.exe" if os.name == "nt" else "javap")) if java_home else shutil.which("javap")
    if not javap:
        return ""
    result = subprocess.run(
        [javap, "-classpath", str(jar_path), "-public", *class_names],
        capture_output=True,
        text=True,
        timeout=120,
    )
    # javap can return useful output even if one class in a batch is unavailable.
    return result.stdout


def _split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in value:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_method_signature(line: str, current_class: str) -> dict | None:
    text = line.strip().rstrip(";")
    if "(" not in text or ")" not in text:
        return None

    before_args, after_open = text.split("(", 1)
    args_text = after_open.rsplit(")", 1)[0].strip()
    tokens = before_args.split()
    if not tokens:
        return None
    name_token = tokens[-1]
    normalized_name = name_token.replace("$", ".")
    is_constructor = normalized_name == current_class
    is_static = " static " in f" {text} "
    type_text = before_args.rsplit(name_token, 1)[0].strip()
    type_text = re.sub(r"^(?:(?:public|protected|private|static|final|abstract|synchronized|native|strictfp|default)\s+)+", "", type_text)
    if type_text.startswith("<"):
        depth = 0
        for index, char in enumerate(type_text):
            depth += (char == "<") - (char == ">")
            if depth == 0:
                type_text = type_text[index + 1:].strip()
                break
    return_type = current_class if is_constructor else (type_text or "void")
    arg_types = _split_top_level_commas(args_text) if args_text else []
    arg_count = 0 if not args_text else len(_split_top_level_commas(args_text))

    return {
        "name": "__init__" if is_constructor else name_token.split(".")[-1],
        "arg_count": arg_count,
        "arg_types": arg_types,
        "return_type": return_type,
        "static": is_static,
        "constructor": is_constructor,
        "raw": text,
    }


def _parse_field_signature(line: str) -> dict | None:
    text = line.strip().rstrip(";")
    if "(" in text or ")" in text:
        return None
    tokens = text.split()
    if len(tokens) < 2:
        return None
    return {
        "name": tokens[-1],
        "type": " ".join(tokens[1:-1]).removeprefix("static ").removeprefix("final ").removeprefix("volatile ").removeprefix("transient "),
        "static": " static " in f" {text} ",
        "raw": text,
    }


def _parse_javap_output(output: str) -> dict[str, dict]:
    class_map: dict[str, dict] = {}
    current_class: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Compiled from "):
            continue
        if line == "}":
            current_class = None
            continue

        class_match = re.match(r"^(?:(?:public|protected|private|abstract|final|static|sealed)\s+)*(class|interface|enum)\s+([A-Za-z0-9_.$]+)", line)
        if class_match:
            current_class = class_match.group(2).replace("$", ".")
            class_map.setdefault(current_class, {
                "kind": class_match.group(1),
                "methods": [],
                "fields": [],
            })
            continue

        if not current_class:
            continue

        method_info = _parse_method_signature(line, current_class)
        if method_info:
            class_map[current_class]["methods"].append(method_info)
            continue

        field_info = _parse_field_signature(line)
        if field_info:
            class_map[current_class]["fields"].append(field_info)

    return class_map


def _ensure_stub_pkg(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.pyi"
    if not init_file.exists():
        init_file.write_text("# generated by fabricpy jar scanner\n", encoding="utf-8")


def _java_type_to_stub(value: str) -> str:
    clean = (value or "").strip()
    clean = clean.replace("...", "[]")
    if not clean:
        return "object"

    if clean.endswith("[]"):
        return "list[object]"

    mapping = {
        "byte": "int",
        "short": "int",
        "int": "int",
        "long": "int",
        "float": "float",
        "double": "float",
        "boolean": "bool",
        "char": "str",
        "java.lang.String": "str",
        "String": "str",
        "void": "None",
    }
    if clean in mapping:
        return mapping[clean]
    return "object"


def _render_stub_class(class_name: str, detail: dict | None) -> str:
    lines = [f"class {_sanitize_python_name(class_name)}:"]
    body: list[str] = []

    if detail:
        for field in detail.get("fields", []):
            body.append(f"    {_sanitize_python_name(field['name'])}: {_java_type_to_stub(field.get('type', 'object'))}")

        methods = detail.get("methods", [])
        counts = {}
        for method in methods:
            counts[method["name"]] = counts.get(method["name"], 0) + 1
        for method in methods:
            args = []
            if not method.get("static") and not method.get("constructor"):
                args.append("self")
            elif method.get("constructor"):
                args.append("self")
            for index, arg_type in enumerate(method.get("arg_types", [])):
                if arg_type.endswith("..."):
                    args.append(f"*arg{index}: {_java_type_to_stub(arg_type[:-3])}")
                else:
                    args.append(f"arg{index}: {_java_type_to_stub(arg_type)}")
            signature = ", ".join(args)
            return_type = "None" if method.get("constructor") else _java_type_to_stub(method.get("return_type", "object"))
            if counts[method["name"]] > 1:
                body.append("    @overload")
            if method.get("static") and not method.get("constructor"):
                body.append("    @staticmethod")
                body.append(f"    def {_sanitize_python_name(method['name']) if method['name'] != '__init__' else '__init__'}({signature}) -> {return_type}: ...")
            else:
                body.append(f"    def {_sanitize_python_name(method['name']) if method['name'] != '__init__' else '__init__'}({signature}) -> {return_type}: ...")

    if not body:
        body.append("    ...")

    lines.extend(body)
    return "\n".join(lines)


def _write_stub_tree(stub_root: Path, alias: str, packages: dict[str, set[str]], class_details: dict[str, dict]):
    base = stub_root / "dep" / alias
    _ensure_stub_pkg(stub_root / "dep")
    _ensure_stub_pkg(base)

    for package_name, classes in sorted(packages.items()):
        current = base
        if package_name:
            for part in package_name.split("."):
                current = current / part
                _ensure_stub_pkg(current)
        init_path = current / "__init__.pyi"
        header = "# generated by fabricpy jar scanner\nfrom typing import overload\n\n"
        rendered_classes = []
        detail_names = {key[len(package_name) + 1:].replace(".", "_"): value for key, value in class_details.items() if key.startswith(package_name + ".")}
        for cls in sorted(classes):
            full_name = f"{package_name}.{cls}" if package_name else cls
            rendered_classes.append(_render_stub_class(cls, class_details.get(full_name) or detail_names.get(cls)))
        body = "\n\n".join(rendered_classes)
        init_path.write_text(header + body + ("\n" if body else ""), encoding="utf-8")


def build_symbol_index_for_project(project_dir: Path):
    project_meta = _load_project_meta(project_dir)
    if not project_meta:
        return

    resolved_path = project_dir / ".fabricpy_meta" / "resolved_dependencies.json"
    resolved_artifacts = json.loads(resolved_path.read_text(encoding="utf-8")) if resolved_path.exists() else []
    scan_entries = [entry for entry in _extract_gradle_coordinates(project_meta) if _should_scan_dependency(entry)]
    meta_dir = project_dir / ".fabricpy_meta"
    stubs_dir = meta_dir / "python_stubs"
    if stubs_dir.exists():
        shutil.rmtree(stubs_dir)
    stubs_dir.mkdir(parents=True, exist_ok=True)

    resolved = []
    unresolved = []
    package_index = []
    diagnostics = []
    aliases = {}

    for entry in scan_entries:
        coordinate = entry["coordinate"]
        alias = _dependency_alias(entry)
        jar_paths = [Path(entry["path"])] if entry.get("path") else _resolve_gradle_cached_jars(coordinate)
        if not entry.get("path"):
            matches = _resolved_jars_for_coordinate(coordinate, resolved_artifacts)
            if matches:
                jar_paths = matches
        if alias in aliases and aliases[alias] != coordinate:
            raise ValueError(f"Dependency alias {alias!r} is shared by {aliases[alias]} and {coordinate}; set distinct mod_id values")
        aliases[alias] = coordinate
        if not jar_paths:
            unresolved.append({
                "coordinate": coordinate,
                "alias": alias,
                "repo": entry.get("repo", ""),
            })
            continue

        merged_packages: dict[str, set[str]] = {}
        merged_class_details: dict[str, dict] = {}
        for jar_path in jar_paths:
            try:
                jar_packages, full_class_names = _scan_jar_classes(jar_path)
            except (OSError, zipfile.BadZipFile) as exc:
                diagnostics.append({"jar": str(jar_path), "error": str(exc)})
                continue
            for binary_name in full_class_names:
                merged_class_details.setdefault(binary_name.replace("$", "."), {"kind": "class", "methods": [], "fields": []})
            for package_name, classes in jar_packages.items():
                merged_packages.setdefault(package_name, set()).update(classes)
            for chunk in _chunked(full_class_names, 40):
                try:
                    javap_output = _run_javap(jar_path, chunk)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    diagnostics.append({"jar": str(jar_path), "error": str(exc)})
                    break
                if not javap_output:
                    diagnostics.append({"jar": str(jar_path), "error": "javap produced no API details; use a JDK that supports this dependency"})
                    break
                merged_class_details.update(_parse_javap_output(javap_output))
            resolved_coordinate = next((_resolved_artifact_coordinate(a) for a in resolved_artifacts
                                        if a.get("path") and Path(a["path"]) == jar_path), coordinate)
            resolved.append({
                "coordinate": coordinate,
                "resolved_coordinate": resolved_coordinate,
                "alias": alias,
                "jar": str(jar_path.resolve()),
            })

        _write_stub_tree(stubs_dir, alias, merged_packages, merged_class_details)
        package_index.append({
            "coordinate": coordinate,
            "alias": alias,
            "package_count": len(merged_packages),
            "class_count": sum(len(classes) for classes in merged_packages.values()),
            "packages": {pkg: sorted(classes) for pkg, classes in sorted(merged_packages.items())},
            "class_details": merged_class_details,
        })

    symbol_index = {
        "format": 1,
        "kind": "fabricpy_symbol_index",
        "status": "partial" if unresolved or diagnostics else "complete",
        "diagnostics": diagnostics,
        "loader": project_meta.get("loader", ""),
        "minecraft_version": project_meta.get("minecraft_version", ""),
        "resolved_jars": resolved,
        "unresolved_dependencies": unresolved,
        "dependencies": package_index,
        "stub_root": str(stubs_dir.resolve()),
    }

    for diagnostic in diagnostics:
        print(f"[fabricpy] Dependency scan warning: {diagnostic['jar']}: {diagnostic['error']}")
    (meta_dir / "symbol_index.json").write_text(json.dumps(symbol_index, indent=2), encoding="utf-8")

    return symbol_index

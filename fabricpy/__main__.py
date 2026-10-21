"""Command-line build and source generation: python -m fabricpy build mod.py."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import sys

from fabricpy.mod import Mod


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write Minecraft mods in Python using pluggable loader backends.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "generate"):
        command = sub.add_parser(name, help="Build mod JARs" if name == "build" else "Generate projects and scan available dependencies without Gradle")
        command.add_argument("source", type=Path, help="Python file defining a Mod named 'mod'")
        command.add_argument("--loader", help="Target addon name, comma-separated loaders, or all")
        command.add_argument("--minecraft-version")
        if name == "build":
            command.add_argument("--output", default="dist")
            command.add_argument("--clean", action="store_true")
    init = sub.add_parser("init", help="Create a ready-to-build starter mod")
    init.add_argument("directory", type=Path)
    init.add_argument("--mod-id", default="examplemod")
    init.add_argument("--name", default="My Python Mod")
    init.add_argument("--loader", default="all")
    init.add_argument("--minecraft-version", default="1.20.1")
    sub.add_parser("loaders", help="List available loader addons")
    args = parser.parse_args(argv)
    if args.command == "loaders":
        from fabricpy.addons import list_addons
        for addon in list_addons(kind="loader"):
            print(f"{addon['target']:12} {addon['minecraft_version']:12} {addon['name']}")
        return 0
    if args.command == "init":
        try:
            _init_project(args)
            return 0
        except (OSError, ValueError) as exc:
            print(f"[fabricpy] {exc}", file=sys.stderr)
            return 1
    source = args.source.expanduser().resolve()
    previous_cwd = Path.cwd()
    previous_path = list(sys.path)
    try:
        os.chdir(source.parent)
        sys.path.insert(0, str(source.parent))
        namespace = runpy.run_path(str(source), run_name="fabricpy_project")
        mod = namespace.get("mod")
        if not isinstance(mod, Mod):
            raise ValueError(f"{source}: define your Mod as 'mod = mc.Mod(...)'")
        if args.loader:
            mod.loader = args.loader.strip().lower()
        if args.minecraft_version:
            mod.minecraft_version = args.minecraft_version.strip()
        if args.command == "generate":
            mod.generate()
            return 0
        results = mod.compile(output_dir=args.output, clean=args.clean)
        return 0 if results and all(results.values()) else 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"[fabricpy] {exc}", file=sys.stderr)
        return 1
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = previous_path


def _init_project(args):
    import base64
    import json
    # Validate before creating any files.
    Mod(args.mod_id, args.name, minecraft_version=args.minecraft_version, loader=args.loader)
    root = args.directory.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    texture_dir = root / "assets" / args.mod_id / "textures" / "block"
    texture_dir.mkdir(parents=True)
    texture_dir.joinpath("starter.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
    ))
    source = "import fabricpy as mc\n\nmod = mc.Mod(\n"
    source += f"    mod_id={json.dumps(args.mod_id)}, name={json.dumps(args.name)},\n"
    source += f"    minecraft_version={json.dumps(args.minecraft_version)}, loader={json.dumps(args.loader)},\n)\n\n"
    source += """@mod.register
class StarterBlock(mc.Block):
    block_id = "starter_block"
    texture = "starter"

    @mc.on_use
    def interact(self, ctx):
        ctx.player.send_message("Hello from Python!")

if __name__ == "__main__":
    mod.compile()
"""
    (root / "mod.py").write_text(source, encoding="utf-8")
    (root / ".gitignore").write_text(".fabricpy_build/\ndist/\n__pycache__/\n", encoding="utf-8")
    print(f"[fabricpy] Starter mod created at {root}")
    print(f"[fabricpy] Build it with: python -m fabricpy build {root / 'mod.py'}")


if __name__ == "__main__":
    raise SystemExit(main())

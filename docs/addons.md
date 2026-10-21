# Addons

`fabricpy` addons let you extend the compiler without editing the core compile entrypoint.

Right now the addon system is used for loader and version support. That means the built-in Fabric, Forge, Quilt, and NeoForge targets are no longer special-cased in the compiler. They are discovered the same way external addons are discovered.

This page is the authoring guide for addon developers.

## What An Addon Is

An addon is a Python module named `addon.py`, discovered from a project-level
`fabricpy_addons/` tree, an external `FABRICPY_ADDON_PATH` root, or the bundled
`fabricpy/addons/` tree.

An addon declares:

- what kind of addon it is
- what target it handles
- what Minecraft version or versions it supports
- how to generate a project for that target
- optionally how to build that generated project

For loader addons:

- `kind` is `loader`
- `target` is the loader name, such as `fabric`, `forge`, `neoforge`, or `quilt`
- `minecraft_version` is something like `1.20.1`, or `MINECRAFT_VERSIONS` is a list of supported versions

## Folder Layout

Place project addons under `fabricpy_addons/`, for example:

```text
fabricpy_addons/
  my_quilt_support/
    addon.py
    quilt_gen.py
    api_maps.py
    templates/
```

Discovery is recursive; folder names do not determine targets. The constants in
`addon.py` select the loader and Minecraft version. For reusable addons, place the
same layout in a root listed in `FABRICPY_ADDON_PATH`.

Builtins use `fabricpy/addons/<kind>/<target>/<minecraft_version>/<name>/addon.py`
or a version-independent `<target>/builtin/addon.py` with `MINECRAFT_VERSIONS`.
Those paths are references for backend authors; project addons do not need to be
copied into the installed package.

Only `addon.py` is discovered automatically. Any sibling files are yours to import from `addon.py`.

## Discovery Rules

`fabricpy` recursively scans for files named:

- `addon.py`

and then reads these module attributes:

- `ADDON_KIND`
- `ADDON_TARGET`
- `MINECRAFT_VERSION`
- `ADDON_NAME`
- optional `ADDON_PRIORITY`

The current discovery logic is implemented in [addons.py](../fabricpy/addons.py).

If multiple addons target the same:

- `kind`
- `target`
- `minecraft_version`

the highest `ADDON_PRIORITY` wins.

That is how an external addon can override a built-in one.

## Minimal Addon Contract

Every addon must define these fields:

```python
ADDON_KIND = "loader"
ADDON_TARGET = "quilt"
MINECRAFT_VERSION = "1.20.1"
ADDON_NAME = "my_quilt_support"
```

Optional:

```python
ADDON_PRIORITY = 10
```

Every loader addon must define:

```python
def generate_project(mod, project_dir):
    ...
```

Optional:

```python
def build_project(project_dir, minecraft_version, clean=False, output_dir=None):
    ...
```

If `build_project(...)` is omitted, `fabricpy` falls back to the default Gradle runner in `fabricpy/compiler/gradle_runner.py`.

## Smallest Possible Loader Addon

This is the smallest useful addon:

```python
ADDON_KIND = "loader"
ADDON_TARGET = "quilt"
MINECRAFT_VERSION = "1.20.1"
ADDON_NAME = "my_quilt_support"

def generate_project(mod, project_dir):
    from .quilt_gen import generate_quilt_project
    return generate_quilt_project(mod, project_dir)
```

This works if:

- your generator writes a valid Gradle project
- the default Gradle runner can build it by calling `gradlew`
- the build output lands in the usual Gradle `build/libs` area

## Full Loader Addon Example

If your loader needs custom build handling, define `build_project(...)` too:

```python
ADDON_KIND = "loader"
ADDON_TARGET = "quilt"
MINECRAFT_VERSION = "1.20.1"
ADDON_NAME = "my_quilt_support"
ADDON_PRIORITY = 10

def generate_project(mod, project_dir):
    from .quilt_gen import generate_quilt_project
    return generate_quilt_project(mod, project_dir)

def build_project(project_dir, minecraft_version, clean=False, output_dir=None):
    from fabricpy.compiler.gradle_runner import run_build
    return run_build(project_dir, minecraft_version, "quilt", clean=clean, output_dir=output_dir)
```

## What A Loader Addon Actually Has To Do

For a loader addon to be real, not just discoverable, it has to bridge Python `fabricpy` concepts into that loader’s Java and metadata model.

In practice that means your generator needs to handle these areas:

### 1. Project generation

Your addon must write a real buildable project, including:

- `build.gradle`
- `settings.gradle`
- Gradle wrapper if needed
- source roots
- resource roots
- loader metadata

For reference, see:

- [fabric_gen.py](../fabricpy/compiler/fabric_gen.py)
- [forge_gen.py](../fabricpy/compiler/forge_gen.py)

### 2. Metadata generation

Your addon must write whatever the loader needs for mod metadata.

For example:

- Fabric writes `fabric.mod.json`
- Forge writes `META-INF/mods.toml`

If your loader needs mixin metadata, dependency metadata, or entrypoint metadata, that belongs here too.

### 3. Python-to-Java call mapping

The `ctx.*` system is not magic runtime reflection. It is a compiler surface.

That means your loader addon needs mappings for things like:

- `ctx.player.send_message(...)`
- `ctx.world.set_block(...)`
- `ctx.block_entity.get_string(...)`
- `ctx.entity.play_animation(...)`

The existing maps live in:

- [api_maps.py](../fabricpy/compiler/api_maps.py)

Important pieces there:

- `FABRIC_API_MAP`
- `FORGE_API_MAP`
- `FABRIC_EXTRA_IMPORTS`
- `FORGE_EXTRA_IMPORTS`
- `FABRIC_EVENT_MAP`
- `FORGE_EVENT_MAP`

If you add a new loader, you will usually need your own equivalents.

## How Mapping Works

The transpiler takes Python callback code and substitutes known calls using a map.

Example idea:

```python
ctx.player.send_message("Hello")
```

becomes a loader-specific Java call because the transpiler finds a string template for:

- `ctx.player.send_message`

The transpiler entrypoint is in:

- [transpiler.py](../fabricpy/compiler/transpiler.py)

That means if your loader uses different Java types or helper methods, your addon has to expose a compatible API map or generator strategy.

### 4. Event wiring

`mod.event("...")` handlers are also loader-specific.

Your addon has to decide:

- what event names are supported
- what Java imports are needed
- what registration code is generated
- what local variables are available inside the handler

Examples of those decisions are in the built-in event maps:

- [api_maps.py](../fabricpy/compiler/api_maps.py)

If your loader does not have a direct equivalent for some built-in event, you have to:

- emulate it
- omit it
- or document that it is unsupported for that loader addon

### 5. Registration code

Your addon has to generate registration code for:

- blocks
- items
- entities
- block entities
- sounds
- packets
- screens
- commands
- keybinds
- creative tabs
- advancements
- dimensions
- structures

The built-in generators are useful because they already show all the moving parts that need to be registered.

### 6. Resource and data copying

The generated project still needs:

- `assets/<modid>/...`
- `data/<modid>/...`

copied into the loader project correctly.

If your loader uses a different convention, your addon has to map that too.

### 7. Dependency handling

If your loader uses Maven dependencies differently, your generator must adapt:

- repositories
- dependency scopes
- deobf/remap rules
- loader metadata dependencies

This matters for both ordinary dependencies and optional systems like GeckoLib.

## Recommended Strategy For New Loader Addons

Do not start from zero unless the loader is completely different.

The practical path is:

1. Copy the closest built-in generator.
2. Rename it into your addon folder.
3. Replace metadata generation first.
4. Replace dependency/build config second.
5. Replace API maps and event maps third.
6. Keep the asset/data flow and transpiler flow as close as possible.

For example:

- a Quilt-like addon should probably start from the Fabric generator
- a Forge-adjacent addon should probably start from the Forge generator

## Minimal Checklist For A Real Loader Addon

Before calling a loader addon usable, make sure it can handle:

- `mc.Mod(..., loader="<your loader>")`
- one item
- one block
- one event
- one command
- one resource pack texture
- one data pack recipe
- one build that produces a jar

If it cannot pass that baseline, discovery is working but the addon is not actually usable.

## Example: Adding A New Version For An Existing Loader

If the loader is already supported conceptually and only the Minecraft version is new, you often do not need a totally new architecture.

You can:

1. copy the built-in addon folder for the closest existing version
2. update `MINECRAFT_VERSION`
3. adjust:
   - dependency versions
   - loader versions
   - mappings
   - metadata version ranges
   - any changed Java APIs

That kind of addon is often much smaller than a whole new loader addon.

## Example: Overriding A Built-in Addon

If you want to replace the built-in Fabric `1.20.1` support:

```python
ADDON_KIND = "loader"
ADDON_TARGET = "fabric"
MINECRAFT_VERSION = "1.20.1"
ADDON_NAME = "my_better_fabric_1201"
ADDON_PRIORITY = 50
```

That addon will win over the built-in one because the built-in priority is lower.

## Debugging Addon Discovery

You can inspect discovered addons from Python:

```python
import fabricpy as mc

for addon in mc.list_addons():
    print(addon)
```

You can also filter:

```python
mc.list_addons(kind="loader", minecraft_version="1.20.1")
```

If your addon does not show up:

- check the path
- check that the file is named `addon.py`
- check that `ADDON_KIND`, `ADDON_TARGET`, and `MINECRAFT_VERSION` exist
- check that the module imports cleanly

## Current Limits

The addon system currently solves discovery and selection.

It does not yet provide a special high-level SDK for generator authors.

That means addon developers still need to understand the existing compiler architecture:

- project generation
- API maps
- event maps
- transpilation
- Gradle build flow
- metadata generation

So the real rule is:

- addon discovery is easy
- loader implementation is still advanced work

## Practical Advice

If you want people to build serious addons, give them:

- a generator file
- an API map file
- an event map file
- one working demo mod
- one test compile target

That is enough for a community addon to be maintainable.

## Built-in Addons

The current built-in loader addons are:

- Fabric `1.20.1`, `1.21`, and `1.21.1` through `1.21.8`
- Forge `1.20.1`
- Forge `1.21.1`
- Quilt `1.20.1`
- NeoForge `1.21.1`

They live in the same folder structure external addons use, so they are the reference implementation for addon authors.

## Project and external addon roots

Backends no longer need to be installed inside the FabricPy package. Discovery
also searches `fabricpy_addons/` in the current mod project and roots from the
`FABRICPY_ADDON_PATH` environment variable (using the platform path separator).
A typical layout is:

```text
fabricpy_addons/
  custom_loader/
    addon.py
    generator.py
```

`addon.py` can use `from .generator import generate_project`. Addon load failures
emit warnings naming the broken file. Selection still uses declared priority;
project addons with the default priority override the lower-priority builtins.

Any loader can define `ADDON_TARGET`; the compiler resolves it from installed
addons, not a fixed allowlist. Implement `build_project` when your loader does
not use Gradle. The custom builder receives the generated project directory,
Minecraft version, clean flag and output directory and must return a success
boolean. `mod.generate()` lets you inspect a backend without running its builder.

An addon with a custom `build_project` owns its dependency resolution too. If it
needs an earlier resolution phase before final Python translation, it can provide
`prepare_dependencies(project_dir, minecraft_version) -> bool`. The compiler
regenerates the project after this hook succeeds. Backends using the default
builder use the shared Gradle classpath resolver. A non-Gradle backend is never
forced through Gradle merely because it writes dependency metadata.

The compiler invokes dependency preparation when a generated
`.fabricpy_meta/interop_project.json` declares dependencies (or GeckoLib dependency
lines). A custom backend that needs this phase should write that metadata during
`generate_project`, using
`fabricpy.compiler.symbol_index.write_interop_metadata(mod, project_dir, loader,
repositories, dependency_lines)`. It can then implement `prepare_dependencies`
to resolve its own artifacts before regeneration. Without such metadata, dependency
preparation is left to its custom builder. This hook is not run by `generate`.

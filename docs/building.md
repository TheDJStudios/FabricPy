# Building

`fabricpy` generates a real loader project under `.fabricpy_build/`, then runs Gradle to produce jars in `dist/`.

That means there are always two layers to keep in mind:

- your Python mod source
- the generated loader projects and their normal Java/Gradle build rules

Loader support now comes from addons under `fabricpy/addons/...`.

## Requirements

- Python `3.10+`
- Java `17` for Minecraft `1.20.1`
- Java `21` for Minecraft `1.21+`
- Gradle available for the first wrapper bootstrap, or an existing wrapper jar that can be reused

## JDK Selection

`fabricpy` now tries to pick a matching JDK automatically.

Version rules:

- Minecraft `1.20.1` prefers Java `17`
- Minecraft `1.21+` prefers Java `21`

Discovery order:

- `JAVA_HOME`
- `JDK*_HOME` environment variables
- common Windows JDK install locations
- `PATH`

Important note:

- you can install Java 17 and Java 21 side by side
- `fabricpy` will try to choose the correct one for the selected Minecraft version
- this is better than manually swapping JDKs on and off `PATH`

## Gradle Selection

Gradle wrapper selection is automatic per loader/version combination:

- Fabric `1.20.1`: Gradle `8.8`
- Fabric `1.21+`: Gradle `8.8`
- Forge `1.20.1`: Gradle `8.8`
- Forge and NeoForge `1.21+`: Gradle `9.3.0`

## Basic Compile Flow

Minimal pattern:

```python
import fabricpy as mc

mod = mc.Mod(
    mod_id="examplemod",
    name="Example Mod",
    minecraft_version="1.20.1",
    loader="both",
)

if __name__ == "__main__":
    mod.compile()
```

Run it from PowerShell:

```powershell
python .\my_mod.py
```

## What `mod.compile()` Actually Does

1. validates the Python mod definition
2. resolves target loaders from `loader` and `minecraft_version`
3. resolves the best loader addon for each requested loader
4. generates loader projects in `.fabricpy_build/<modid>-<loader>`
5. copies repo `assets/` and `data/` into generated resources
6. runs the addon build step in each generated project
7. copies built jars into `dist/`
8. emits interop metadata and dependency stub output under `.fabricpy_meta/`

## Generated Output

Per-loader generated projects:

- `.fabricpy_build/<modid>-fabric/`
- `.fabricpy_build/<modid>-forge/`

Built jars:

- `dist/<modid>-<version>.jar`
- `dist/<modid>-forge-<version>.jar`

Interop/compiler metadata:

- `.fabricpy_build/<modid>-<loader>/.fabricpy_meta/interop_project.json`
- `.fabricpy_build/<modid>-<loader>/.fabricpy_meta/symbol_index.stub.json`
- `.fabricpy_build/<modid>-<loader>/.fabricpy_meta/symbol_index.json`
- `.fabricpy_build/<modid>-<loader>/.fabricpy_meta/python_stubs/dep/...`

## Addon-backed Loader Support

Built-in loader support is now provided through addon folders inside `fabricpy/addons/...`.

See [addons.md](./addons.md) for:

- the addon file layout
- the required `addon.py` fields
- loader override priority
- how to add custom loader/version support

## Repo Asset and Data Layout

Textures, models, blockstates, lang, and sounds should live under:

- `assets/<modid>/textures/...`
- `assets/<modid>/models/...`
- `assets/<modid>/blockstates/...`
- `assets/<modid>/lang/...`
- `assets/<modid>/sounds.json`
- `assets/<modid>/sounds/...`

Recipes, advancements, dimensions, and structures should live under:

- `data/<modid>/recipes/...`
- `data/<modid>/advancements/...`
- `data/<modid>/dimension_type/...`
- `data/<modid>/dimension/...`
- `data/<modid>/structures/...`

## Troubleshooting

### Wrong Java version

- Java 17 installed for `1.20.1`
- Java 21 installed for `1.21+`
- `JAVA_HOME` is not forcing the wrong JDK globally

### Wrong model or texture in-game

Most common cause:

- a manual file under `assets/<modid>/models/...` or `assets/<modid>/blockstates/...` is overriding the generated JSON

### Missing block particles

Cause:

- manual block model JSON is missing a `particle` texture entry

### Item texture missing

Cause:

- manual model uses `<modid>:food/foo` instead of `<modid>:item/foo`

### Dependency interop output missing

- the build may have had no scan-worthy dependency jars
- non-geo builds with no explicit dependencies will often have an empty dependency symbol index, which is expected

## Command line and generation without a build

Install from the checkout with `python -m pip install -e .`, then use:

```sh
fabricpy generate my_mod.py
fabricpy build my_mod.py --loader all
fabricpy build my_mod.py --loader forge --output dist --clean
fabricpy loaders
```

The module form `python -m fabricpy` accepts the same arguments. The source must
expose a `Mod` named `mod`. Its `if __name__ == "__main__"` block is not executed
by the CLI. Resource paths are relative to the source file's directory. Build
failures produce exit status 1.

From Python, `mod.generate()` returns `{loader: project_path}` without invoking
Gradle. `mod.compile()` returns `{loader: bool}`. Inspect those results when
integrating FabricPy with another tool. A Gradle success with no distributable
JAR is reported as a failure. Wrapper setup checks the script, properties, and
wrapper JAR together, so an incomplete first setup is retried.

Dependency builds resolve the Gradle compile classpath before their final Java
generation. This avoids needing a successful first compilation to discover
constructors in a dependency mod.

Unsupported Python syntax now raises a line-specific `TranspileError`; it is no
longer replaced by a comment that discards behavior. Supported fixes include
reassignment, descending literal-step ranges, string literal inequality,
null-safe string comparisons, string escapes, and Python integer floor division.
The transpiler still uses Java local types and scopes: keep a variable's type
stable, initialize shared variables before branches, and do not rely on a loop
variable after the loop. Python's dynamic typing and full collection semantics
are not implemented.

A starter can be created with `fabricpy init my_mod --mod-id example --loader all`.
It includes an editable Python block definition and a placeholder PNG. The target
directory must not already exist, so initialization cannot overwrite a project.
NeoForge can run Gradle on Java 17 and provision a Java 21 compiler via its Gradle
toolchain; other backends continue requiring the target Java version to run their
build plugins.

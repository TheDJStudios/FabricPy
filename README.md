# FabricPy — PyPI distribution: mcmod

Write Minecraft mods in Python and compile them to Java mod JARs.
FabricPy uses loader addons: the name does not restrict it to Fabric. Bundled
backends target Fabric, Forge, Quilt and NeoForge; additional loaders can provide
their own generators and build steps without changing the compiler core.

Python callbacks are translated at build time. This is a practical Python subset,
not a bundled Python interpreter or automatic compatibility with every Java API.

## Start here

The PyPI distribution name is `mcmod`; Python code continues to use
`import fabricpy as mc`, and the CLI is `fabricpy`.

Use Python 3.10+, a JDK (17 for Minecraft 1.20.1; 21 for 1.21+) and Gradle for
the first wrapper setup. Once published, install it with `python -m pip install mcmod`.
For development from this checkout:

```sh
python -m pip install -e .
```

For a complete starter with a block and texture:

```sh
fabricpy init my_mod --mod-id example --loader all
fabricpy build my_mod/mod.py
```

Or create `my_mod.py` yourself:

```python
import fabricpy as mc

mod = mc.Mod("example", "Example", minecraft_version="1.20.1", loader="all")

@mod.register
class Table(mc.Block):
    block_id = "table"
    model = "models/table.bbmodel"
    model_collision = True

    @mc.on_use
    def interact(self, ctx):
        ctx.player.send_message("Made with Python!")

if __name__ == "__main__":
    mod.compile()
```

Save a cuboid Java block/item project from Blockbench at `models/table.bbmodel`.
Embedded PNG textures are extracted automatically. To start without a model,
replace `model` with `texture = "table"` and put a PNG at
`assets/example/textures/block/table.png`.

```sh
fabricpy generate my_mod.py                  # inspect source; no Gradle needed
fabricpy build my_mod.py                     # build all selected loaders
fabricpy build my_mod.py --loader forge      # override the target
fabricpy loaders                            # discover installed backends
```

`python -m fabricpy` works with the same commands. The CLI resolves resources and
outputs relative to the source file's directory. Generated projects go to
`.fabricpy_build/<modid>-<loader>/`; distributable JARs go to `dist/`. Build failures
return a nonzero CLI exit code. From Python, `mod.generate()` returns project paths
and `mod.compile()` returns a dictionary of loader build results.

## Blockbench models

Blocks and items accept `model = "path/to/model.bbmodel"`, a `.json` path, a model
dictionary, or a model resource parent such as `"minecraft:block/cube_all"`.
Block item models also accept these inputs through `item_model`.

Models saved under `assets/<modid>/models/block/` or `models/item/` are converted
automatically. Matching hand-authored JSON files override generated models.
Static models support cuboids, faces, UV scaling, display transforms, and vanilla
single-axis rotations. Meshes, animated static models, and unsupported rotations
produce errors explaining when to use `geo_model` instead.

For GeckoLib geometry, put `.bbmodel` files under `assets/<modid>/geo/` and use
`geo_model = "machines/relay.bbmodel"`. Both older inline groups and Blockbench 5
separate group records are understood. Supply the texture and animation resources
through `geo_texture` and `geo_animations`; embedded animation tracks are not yet
converted. See [models](https://github.com/TheDJStudios/FabricPy/blob/main/docs/models.md) and [animations](https://github.com/TheDJStudios/FabricPy/blob/main/docs/animations.md).

## Dependency mods

Declare either a Maven coordinate or a local JAR:

```python
mod.dependency(
    coordinate="your.group:your-mod:1.0.0",
    repo="https://your.maven.example/releases",
    loader="forge",
    mod_id="your_mod",
    required=True,
)
mod.dependency(path="libs/helper.jar", loader="all", mod_id="helper")
```

Use loader-specific declarations when the dependency publishes separate builds.
`loader="all"` and the legacy default `"both"` apply a dependency to every target.
Dependencies are not automatically bundled into your mod: install required mods
alongside it. A local production mod JAR may need remapping or a development JAR
for calls involving Minecraft types.

Generation scans available local/cached JARs. Builds resolve the actual Gradle
compile classpath and scan it before translating dependency calls. Results include
public methods, constructors, fields, nested classes and Python editor stubs under
`.fabricpy_build/<modid>-<loader>/.fabricpy_meta/`.

Experimental direct access inside callbacks:

```python
widget = dep.helper.com.example.Widget("hello")
```

`dep` is a compiler namespace; callback bodies are not run by Python during builds.
Scanning discovers APIs; it does not guarantee arbitrary cross-loader interop.
See [dependencies](https://github.com/TheDJStudios/FabricPy/blob/main/docs/dependencies.md) and [interop](https://github.com/TheDJStudios/FabricPy/blob/main/docs/interop.md).

## Any loader through addons

Put an `addon.py` backend under `fabricpy_addons/<your-loader>/` in your mod project,
or point `FABRICPY_ADDON_PATH` at external addon roots (separate paths using your
platform's path separator). Relative helper imports work. A backend declares its
loader/version targets and implements `generate_project`; it can also implement a
custom `build_project` for loaders that do not use Gradle.

`loader="all"` selects every installed addon supporting the requested Minecraft
version. A new loader still needs an implementation for its APIs, entrypoints and
metadata. See [addons](https://github.com/TheDJStudios/FabricPy/blob/main/docs/addons.md).

Bundled version targets:

| Loader | Minecraft targets |
| --- | --- |
| Fabric | 1.20.1, 1.21, 1.21.1–1.21.8 |
| Forge | 1.20.1, 1.21.1 |
| Quilt | 1.20.1 |
| NeoForge | 1.21.1 |

These are generator targets, not a claim that every feature has been tested in-game
on every version. NeoForge currently rejects packet definitions. Later Minecraft
API changes and GeckoLib render paths need further integration coverage.

## Development and documentation

```sh
python -m unittest discover -v
```

The suite covers both generator families, four-loader dependency handling,
Blockbench resources, real JAR scanning, executable Java translation, external
loader addons and build failure reporting. Java integration tests require a JDK.

- [Documentation index](https://github.com/TheDJStudios/FabricPy/blob/main/docs/index.md)
- [Building](https://github.com/TheDJStudios/FabricPy/blob/main/docs/building.md)
- [Python API](https://github.com/TheDJStudios/FabricPy/blob/main/docs/mod.md)
- [Work plan and verification](https://github.com/TheDJStudios/FabricPy/blob/main/WORK_PLAN.md)

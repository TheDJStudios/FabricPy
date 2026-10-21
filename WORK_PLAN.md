# FabricPy improvement goal

Make Python mod authoring reliable and approachable across loader backends, with
Blockbench model input and dependency mod discovery. The name does not constrain
the architecture to Fabric. New loaders plug into the addon contract.

## Steps

- [x] Establish regression tests for generation, models, dependencies and translation.
- [x] Accept static block/item `.bbmodel` files; preserve textures and validate unsupported geometry.
- [x] Repair GeckoLib conversion for current Blockbench group layouts.
- [x] Accept local dependency JARs and scan them before translating hooks; improve Maven cache scanning and diagnostics.
- [x] Fix dependency filtering/metadata for Quilt and NeoForge as well as Fabric/Forge.
- [x] Allow external loader addons without editing the installed package.
- [x] Fix Python translation and build reliability bugs exposed by tests.
- [x] Provide a source-generation workflow, clear build results and a documented quick start.
- [x] Finish final integration rebuilds, NeoForge fixes and packaging checks; record limits honestly.

## Verification / resume notes

Initial checkout has no test suite or packaging metadata. Existing generators attempt
pre-translation Maven cache scans, but ignore all scanner exceptions. Only geo/
.bbmodel files are converted; static model strings are serialized as JSON strings.
Quilt inherits Fabric dependency filtering; NeoForge drops declared dependencies
from build.gradle and inherits Forge interop metadata. These are priority regressions.

Local runtime: Python 3.13, JDK 17 and 26, system Gradle. Java 21 is not installed.

## Verified result (2026-10-21)

- 31 regression tests pass: `python -m unittest discover -v`.
- Actual JAR builds pass for Fabric, Forge and Quilt on Minecraft 1.20.1, and
  NeoForge on Minecraft 1.21.1. Each fixture combines a .bbmodel block/item,
  a local dependency JAR constructor call, and a Python block interaction hook.
- Archive checks verify model JSON, the extracted PNG and compiled block classes.
- Reproduce the builds and archive checks with:
  - `python examples/integration_check.py --loader all`
  - `python examples/integration_check.py --loader neoforge --minecraft-version 1.21.1`
- Final integration JARs are under `.fabricpy_build/integration-check/dist/`.
  They are verification fixtures; the helper library is intentionally a separate
  dependency, not bundled into the mod.
- Final wheel built and installed in a temporary isolated virtual environment.
  All four backend targets and all eight builtin addon files are included;
  `init` plus `generate` works from the installed package outside this checkout.
- `git diff --check` passes.
- Final logs: `/tmp/fabricpy-tests-final.log`,
  `/tmp/fabricpy-final-integration.log`, `/tmp/fabricpy-final-neoforge.log`,
  `/tmp/fabricpy-wheel-final.log`.

## Important fixes

- Static .bbmodel and .json file inputs now produce JSON objects rather than
  serialized file-path strings. Embedded and linked PNGs are handled; linked
  paths resolve relative to the original source even during automatic conversion.
- Blockbench 5 group records preserve bone names and pivots in geo conversion.
- Shared dependency filtering works for every backend, including Quilt/NeoForge.
- Dependency scanning happens before final hook translation, supports local JARs,
  actual Gradle-selected dynamic versions/classifiers, and reports diagnostics.
- Changed declarations invalidate stale resolved artifacts and generated stubs.
- External addons support relative imports, custom non-Gradle builders and an
  optional `prepare_dependencies` hook without mandatory Gradle resolution.
- Forge automatic block items now register on the mod bus. NeoForge's 1.21.1
  event-bus injection, registries, factories and block interaction APIs compile.
- Python reassignment, descending ranges, string inequality, floor assignment,
  bitwise inversion and escaped strings are fixed. Unsupported syntax and wrong
  API arity raise useful errors instead of discarding behavior.
- Hooks inherit correctly, and advancement generation does not mutate source
  definitions between loader builds.
- CLI init/generate/build/loaders, build results and packaging make the workflow
  usable without copying the package folder by hand.

## Remaining boundaries

These are build and archive checks, not in-game launch tests. They cover the
specified baseline, not every feature/version combination. New loaders still
need a backend implementation. NeoForge packets remain explicitly unsupported.
GeckoLib .bbmodel input converts cuboid geometry; animation JSON and texture
resources remain separate. Meshes and rotations that vanilla static models cannot
represent raise errors. Python uses a translated subset with Java local types and
scopes, not a complete Python runtime. Dependency discovery does not guarantee
safe automatic interoperability with arbitrary obfuscated mod APIs.

## PyPI release preparation

The user selected PyPI distribution name `mcmod` (Python import and console
command remain `fabricpy`). A direct PyPI JSON query returned404 on2026-10-21;
that is not a reservation or guarantee of name acceptance.

Release artifacts: `dist/pypi/mcmod-0.1.0.tar.gz` and
`dist/pypi/mcmod-0.1.0-py3-none-any.whl`. Both pass `twine check --strict`.
An independent subagent audited source freshness, metadata, license, addon data,
RECORD hashes and clean contents. The source archive includes docs, tests and the
integration example, and excludes caches/JARs/old distribution metadata.
Project links and an Alpha classifier are included. Nothing has been published.

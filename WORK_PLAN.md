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

## Callback duplication and IDE typing (2026-10-22)

- User-reported duplicate place/use effects reproduced in generated code: callbacks
  were executed on both logical client and logical server. Four lifecycle/use
  decorators now default to server execution, with explicit client/both options.
- The four global player interaction observers use the same default and side
  option, while retaining separate hand attempts and vanilla PASS/results.
- Added main-hand/offhand helper predicates, preserved vanilla superclass calls,
  fixed missing Fabric ActionResult event import, and repaired NeoForge method
  rewriting for nested callback braces. Removed redundant Forge auto-subscriber
  annotations while retaining explicit event registration. Bus registration itself
  was deduplicated by Forge and was not the duplicate-effects cause.
- Exposed annotation-only hook context Protocols and portable nested helper APIs;
  shipped py.typed and per-decorator annotation examples in docs/context.md and
  docs/decorators.md. Placement context correctly has an optional player.
- 43 tests pass. The executable Java harness exercises all four loaders and all
  three side settings against a simulated client/server action pair. Expanded real
  loader builds pass on Fabric/Forge/Quilt1.20.1 and NeoForge1.21.1 with typed
  use/place/break/item hooks and global interaction observers.
- Refreshed dist/pypi artifacts pass strict Twine checks and installed-package
  annotation/marker checks. No release uploaded; version remains0.1.0.

## Release 0.1.1

Bumped distribution and Python __version__ to 0.1.1. Built wheel and source archive
under dist/pypi; both pass strict Twine validation and embedded version checks.
No upload performed.

## Portable item features (2026-10-22)

Goal: native music discs, named attachment slots with visible models, persistent
item inventories and functions, and useful GUIs across the bundled loader targets,
with Minecraft 1.20.1 as the primary target.

1. [x] Define portable Python fields, validation and typed context APIs.
2. [x] Generate native music discs, sound registration and jukebox resources.
3. [x] Persist real inventory/attachment stacks and scalar item data.
4. [x] Add server-authoritative transfer functions and vanilla storage menus.
5. [x] Connect visible attachment models to each loader's native item renderer.
6. [x] Add item-opened client panels, documentation and a standalone example.
7. [x] Run focused behavior tests and complete real loader builds; record limits.

Subagents implemented storage/typing, menus/transfers, and discs/rendering in
parallel. Root integrated shared generators and the full example. These changes
are unreleased; the pre-existing 0.1.1 distributions have not been replaced.

Verification: 71 unit/behavior tests pass, including executable Java storage,
conservation/authority, menu ownership, callback side and branch-scope checks.
The complete examples/item_features.py builds on Fabric/Forge/Quilt 1.20.1 and
Fabric/Forge/NeoForge 1.21.1. Inspected all six JARs for compiled helpers, native
disc resources and original/attachment proxy models. Fixed existing modern
particle/raycast API incompatibilities and Python branch-variable scope exposed
by those builds. Temporary wheel/sdist validation passes strict Twine checks;
new modules/type hints/docs/example are included and generated projects excluded.

Limitations: in-game visual/audio/manual interaction QA remains unperformed;
storage GUI uses vanilla chest layouts (1–6 rows), while custom panels support
labels/buttons. Named slots currently accept any non-container attachment item;
slot-specific item filters and attachment-slot GUIs are future extensions.
Newer Minecraft versions need native API adapters for these features. No release
version bump or upload was performed; dist/pypi/0.1.1 artifacts remain unchanged.

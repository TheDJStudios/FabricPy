# Dependencies

`fabricpy` supports declared dependencies, generated build metadata, dependency jar scanning, and an early direct dependency interop path.

This is the beginning of the “stop adding one-off wrappers forever” direction.

## Main API

```python
mod.dependency(
    coordinate="com.simibubi.create:create-fabric-1.20.1:0.5.1",
    loader="fabric",
    scope="modImplementation",
    repo="https://maven.tterrag.com/",
    deobf=True,
    mod_id="create",
    required=True,
    version_range="*",
    ordering="NONE",
    side="BOTH",
)
```

## What Dependency Declarations Affect

Declared dependencies influence:

- generated repositories in `build.gradle`
- generated dependency lines in `build.gradle`
- generated loader metadata
- interop metadata written into `.fabricpy_meta/`

## Generated Interop Files

Each successful build now emits:

- `.fabricpy_meta/interop_project.json`
- `.fabricpy_meta/symbol_index.stub.json`
- `.fabricpy_meta/symbol_index.json`
- `.fabricpy_meta/python_stubs/dep/<alias>/...`

## Automatic Dependency Discovery

Some dependencies are not only user-declared.

Example:

- if a block uses `geo_model`, `geo_texture`, and `geo_animations`, GeckoLib is added automatically

Important rule:

- GeckoLib is only added if a GeckoLib-backed feature is actually used
- non-geo mods do not get GeckoLib injected just because the compiler supports it

## Current Jar Scanner

After a successful build, the jar scanner now:

- resolves dependency jars from Gradle cache
- indexes package and top-level class names
- indexes named nested classes
- extracts public methods and fields with `javap`
- records basic return types and argument types
- writes richer class detail into `symbol_index.json`
- emits `.pyi` stub packages with class, method, and field surfaces

## Experimental Direct Dependency Path

There is now an early direct dependency path:

```python
dep.geckolib.software.bernie.geckolib.core.animation.RawAnimation.begin()
```

What happens today:

1. the transpiler sees the `dep.<alias>...` namespace
2. it runs that path through the interop resolver
3. if a matching class/member is present in the scanned symbol index, that path is treated as resolved
4. if the dependency path names a class and is called like a function, the compiler emits a constructor call
5. otherwise the compiler emits the resolved Java path directly

Generated Java example:

```java
software.bernie.geckolib.core.animation.RawAnimation.begin();
```

Constructor example:

```python
dep.somealias.com.example.Widget("hello")
```

becomes:

```java
new com.example.Widget("hello");
```

## Limits of the Current Interop Path

- `.pyi` stubs now include primitive/string-shaped hints where the scanner can infer them, but they are still only hints
- overloads are still matched primarily by argument count, not exact Java parameter types
- constructor calls are now recognized, but deeper type checking is still partial
- instance-vs-static misuse is reported with generated interop notes, not hard compiler errors yet
- core Minecraft and loader jars are still intentionally excluded from this first pass

So the correct way to think about the current state is:

- real discovery layer: yes
- real dependency path resolution: yes
- constructor/static-call assistance: yes
- typed safe general Java frontend: not yet

## Local JARs and first-build scanning

```python
mod.dependency(path="libs/helper.jar", mod_id="helper", loader="all")
```

Specify exactly one of `coordinate` and `path`. Paths are resolved when declaring
the dependency, must name an existing JAR, and are emitted as Gradle `files(...)`
dependencies. Local JARs are not passed to Forge's Maven `fg.deobf` helper.
The loader backend handles classpath configuration; production JARs using
obfuscated Minecraft names may need a remapped development artifact.

Generation scans available local/cached JARs without Gradle. A build resolves
`compileClasspath`, records the resolved artifacts, then regenerates Java using
the refreshed index **before Java compilation**. This allows scanned constructors
to work on the first build. A custom loader addon can provide its own build step
and metadata instead of using this Gradle path.

The scanner honors `GRADLE_USER_HOME`, selects Maven classifiers explicitly,
reports corrupt/unreadable JARs and missing `javap` output, and clears stale stub
packages. `symbol_index.json` contains `diagnostics` and `unresolved_dependencies`;
`status="complete"` means the requested scan finished without these diagnostics,
not that type-safe Java interop is guaranteed. Name collisions between dependency
aliases produce an error; set different `mod_id` values for colliding artifacts.

`loader="all"` and the legacy `"both"` selector include every loader. A concrete
loader name applies only to that backend, including Quilt and NeoForge.

Add `.fabricpy_build/<modid>-<loader>/.fabricpy_meta/python_stubs` to your editor's
Python analysis search paths to browse `dep.<alias>` stubs. This is a compile-time
namespace, not a Python runtime import package. Nested classes appear flattened
in the discovery stubs (`Outer_Inner`); Java interop uses `Outer.Inner`.

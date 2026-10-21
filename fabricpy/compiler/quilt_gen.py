from __future__ import annotations

import json
from pathlib import Path

from fabricpy.compiler.fabric_gen import _fabric_dependency_lines, _fabric_repository_lines, _uses_geckolib, generate_fabric_project
from fabricpy.compiler.versions import QUILT_VERSIONS


def generate_quilt_project(mod, project_dir: Path):
    version_meta = QUILT_VERSIONS.get(mod.minecraft_version)
    if version_meta is None:
        raise ValueError(f"Quilt does not support minecraft_version={mod.minecraft_version!r} in this generator.")

    generate_fabric_project(mod, project_dir, loader_name="quilt")
    _rewrite_fabric_mod_json(mod, project_dir, version_meta)
    _write_quilt_gradle_files(mod, project_dir, version_meta)
    print(f"[fabricpy] Quilt project generated at {project_dir}")


def _rewrite_fabric_mod_json(mod, project_dir: Path, version_meta):
    path = project_dir / "src" / "main" / "resources" / "fabric.mod.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    depends = data.setdefault("depends", {})
    depends.pop("fabricloader", None)
    depends["quilt_loader"] = f">={version_meta.quilt_loader}"
    depends["quilted_fabric_api"] = "*"
    depends["java"] = f">={version_meta.java}"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_quilt_gradle_files(mod, project_dir: Path, version_meta):
    mc = mod.minecraft_version
    use_geckolib = _uses_geckolib(mod)
    extra_repos = _fabric_repository_lines(mod, "quilt")
    extra_deps = _fabric_dependency_lines(mod, "quilt")
    geckolib_line = (
        f'modImplementation "software.bernie.geckolib:geckolib-fabric-{mc}:{version_meta.geckolib}"'
        if use_geckolib
        else ""
    )
    geckolib_repo = (
        '    maven { url = "https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/" }'
        if use_geckolib
        else ""
    )

    build_gradle = f"""\
plugins {{
    id 'org.quiltmc.loom' version '{version_meta.loom}'
    id 'maven-publish'
}}

version = "{mod.version}"
group = "{mod.package}"

base {{
    archivesName = "{mod.mod_id}-quilt"
}}

repositories {{
    maven {{ url = "https://maven.quiltmc.org/repository/release/" }}
    maven {{ url = "https://maven.fabricmc.net/" }}
{geckolib_repo}
{chr(10).join(extra_repos)}
    mavenCentral()
}}

dependencies {{
    minecraft "com.mojang:minecraft:{mc}"
    mappings "net.fabricmc:yarn:{version_meta.yarn}:v2"
    modImplementation "org.quiltmc:quilt-loader:{version_meta.quilt_loader}"
    modImplementation "org.quiltmc.quilted-fabric-api:quilted-fabric-api:{version_meta.quilted_fabric_api}"
    {geckolib_line}
{chr(10).join(extra_deps)}
}}

tasks.withType(JavaCompile).configureEach {{
    it.options.release = {version_meta.java}
}}

java {{
    withSourcesJar()
    toolchain.languageVersion = JavaLanguageVersion.of({version_meta.java})
}}
"""
    (project_dir / "build.gradle").write_text(build_gradle, encoding="utf-8")

    (project_dir / "settings.gradle").write_text(f"""\
pluginManagement {{
    repositories {{
        maven {{ url = "https://maven.quiltmc.org/repository/release/" }}
        maven {{ url = "https://maven.fabricmc.net/" }}
        mavenCentral()
        gradlePluginPortal()
    }}
}}
plugins {{
    id 'org.gradle.toolchains.foojay-resolver-convention' version '0.8.0'
}}
rootProject.name = "{mod.mod_id}-quilt"
""", encoding="utf-8")

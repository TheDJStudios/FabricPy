"""
Gradle runner - sets up the Gradle wrapper and runs the build.

Requirements:
  - Java 17+ for Minecraft 1.20.1
  - Java 21+ for Minecraft 1.21.1
  - Gradle must be installed for first-time wrapper setup,
    OR the wrapper jar can be copied from another project.

After setup, ./gradlew handles everything automatically.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fabricpy.compiler.versions import (
    required_gradle_version as _version_required_gradle_version,
    required_java_major as _version_required_java_major,
)

DEFAULT_GRADLE_VERSION = "8.8"


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in re.findall(r"\d+", version):
        parts.append(int(piece))
    return tuple(parts)


def _gradle_version(gradle_bin: str, env: dict[str, str]) -> tuple[int, ...] | None:
    try:
        result = subprocess.run(
            [gradle_bin, "-v"],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    output = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"Gradle\s+([0-9.]+)", output)
    if not match:
        return None
    return _parse_version_tuple(match.group(1))

def _required_java_major(minecraft_version: str) -> int:
    return _version_required_java_major(minecraft_version)


def _required_gradle_version(loader: str, minecraft_version: str) -> str:
    return _version_required_gradle_version(loader, minecraft_version)


def _gradle_runtime_minimum(loader: str, minecraft_version: str) -> int:
    # ModDevGradle runs on Java 17 and uses Gradle toolchains for Minecraft.
    # Loom and other bundled plugins can require the target JVM during setup.
    return 17 if loader.lower().strip() == "neoforge" else _required_java_major(minecraft_version)


def _java_major_version(java_exe: Path) -> int | None:
    try:
        result = subprocess.run(
            [str(java_exe), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    output = (result.stderr or result.stdout).strip()
    match = re.search(r'version "(\d+)', output)
    if not match:
        return None
    return int(match.group(1))


def _iter_java_candidates() -> list[Path]:
    candidates: list[Path] = []

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home) / "bin" / ("java.exe" if sys.platform == "win32" else "java"))

    if sys.platform == "darwin":
        java_home_tool = Path("/usr/libexec/java_home")
        if java_home_tool.exists():
            try:
                result = subprocess.run(
                    [str(java_home_tool)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    candidates.append(Path(result.stdout.strip()) / "bin" / "java")
            except subprocess.TimeoutExpired:
                pass

    for env_name, env_value in os.environ.items():
        if env_name.upper().startswith("JDK") and env_name.upper().endswith("_HOME") and env_value:
            candidates.append(Path(env_value) / "bin" / ("java.exe" if sys.platform == "win32" else "java"))

    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        common_roots = [
            program_files / "Java",
            program_files / "Microsoft",
            program_files / "Eclipse Adoptium",
            program_files / "Zulu",
            program_files / "Amazon Corretto",
        ]
        for root in common_roots:
            if not root.exists():
                continue
            for candidate in sorted(root.rglob("java.exe"), reverse=True):
                candidates.append(candidate)

    which_java = shutil.which("java")
    if which_java:
        candidates.append(Path(which_java))

    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    for part in path_parts:
        if not part:
            continue
        java_candidate = Path(part) / ("java.exe" if sys.platform == "win32" else "java")
        candidates.append(java_candidate)

    return candidates


def _find_java_executable(required_major: int) -> str | None:
    """Find a Java executable matching the required major version."""
    candidates = _iter_java_candidates()

    if sys.platform == "darwin":
        java_home_tool = Path("/usr/libexec/java_home")
        if java_home_tool.exists():
            for version_arg in (str(required_major), f"{required_major}+"):
                try:
                    result = subprocess.run(
                        [str(java_home_tool), "-v", version_arg],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                except subprocess.TimeoutExpired:
                    continue
                if result.returncode == 0 and result.stdout.strip():
                    candidates.insert(0, Path(result.stdout.strip()) / "bin" / "java")

    seen: set[str] = set()
    exact_matches: list[tuple[int, str]] = []
    fallback_matches: list[tuple[int, str]] = []

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except FileNotFoundError:
            continue
        if str(resolved) in seen or not resolved.exists():
            continue
        seen.add(str(resolved))

        major = _java_major_version(resolved)
        if major is None:
            continue
        if major == required_major:
            exact_matches.append((major, str(resolved)))
        elif major > required_major:
            fallback_matches.append((major, str(resolved)))

    if exact_matches:
        return exact_matches[0][1]
    if fallback_matches:
        fallback_matches.sort(key=lambda item: item[0])
        return fallback_matches[0][1]

    return None


def _max_java_major_for_gradle(gradle_version: str) -> int:
    version = _parse_version_tuple(gradle_version)
    if version < (9, 0):
        return 22
    if version < (9, 6):
        return 25
    return 26


def _find_java_executable_in_range(min_major: int, max_major: int) -> str | None:
    candidates = []
    seen: set[str] = set()
    if sys.platform == "darwin":
        java_home_tool = Path("/usr/libexec/java_home")
        if java_home_tool.exists():
            for version_arg in (str(min_major), f"{min_major}+"):
                try:
                    result = subprocess.run(
                        [str(java_home_tool), "-v", version_arg],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                except subprocess.TimeoutExpired:
                    continue
                if result.returncode == 0 and result.stdout.strip():
                    candidate = Path(result.stdout.strip()) / "bin" / "java"
                    major = _java_major_version(candidate)
                    if major is not None and min_major <= major <= max_major:
                        candidates.append((major, str(candidate)))

    for candidate in _iter_java_candidates():
        try:
            resolved = candidate.resolve()
        except FileNotFoundError:
            continue
        if str(resolved) in seen or not resolved.exists():
            continue
        seen.add(str(resolved))
        major = _java_major_version(resolved)
        if major is not None and min_major <= major <= max_major:
            candidates.append((major, str(resolved)))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    return None


def _find_gradle_java_executable(gradle_version: str, min_major: int = 17) -> str | None:
    """Find a JVM suitable for running Gradle itself."""
    max_major = _max_java_major_for_gradle(gradle_version)
    return _find_java_executable_in_range(min_major, max_major)


def _build_env(java_exe: str | None = None) -> dict[str, str]:
    """Build an environment that prefers the selected Java executable."""
    env = os.environ.copy()
    if not java_exe:
        return env

    java_bin = str(Path(java_exe).parent)
    java_home = str(Path(java_exe).parent.parent)
    if sys.platform == "darwin":
        try:
            resolved = Path(java_exe).resolve()
            if resolved == Path("/usr/bin/java"):
                result = subprocess.run(
                    ["/usr/libexec/java_home"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    java_home = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    path_parts = [java_bin] + [
        part for part in env.get("PATH", "").split(os.pathsep)
        if part and part != java_bin
    ]
    env["JAVA_HOME"] = java_home
    env["PATH"] = os.pathsep.join(path_parts)
    return env


def _check_java(minecraft_version: str) -> str | None:
    """Verify the required Java version is available and return its executable path."""
    required_major = _required_java_major(minecraft_version)
    java_exe = _find_java_executable(required_major)
    if java_exe:
        return java_exe

    which_java = shutil.which("java")
    if which_java:
        try:
            result = subprocess.run(
                [which_java, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (result.stderr or result.stdout).strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            output = ""
        if output:
            print(f"[fabricpy] Warning: Java {required_major}+ required for Minecraft {minecraft_version}. Found: {output[:120]}")
        else:
            print(f"[fabricpy] Warning: Java {required_major}+ required for Minecraft {minecraft_version}, but the detected 'java' could not be used.")
        return None

    print(
        f"[fabricpy] Error: Java {required_major}+ not found for Minecraft {minecraft_version}. "
        "Install a matching JDK or set JAVA_HOME/JDK*_HOME."
    )
    return None


def _setup_gradle_wrapper(project_dir: Path, env: dict[str, str], gradle_version: str) -> bool:
    """
    Set up the Gradle wrapper in project_dir.

    Strategy:
    1. If `gradle` is on PATH, run `gradle wrapper --gradle-version <required>`
    2. Otherwise, generate scripts and report the missing wrapper jar.
    """
    wrapper_script = project_dir / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
    wrapper_props = project_dir / "gradle" / "wrapper" / "gradle-wrapper.properties"

    wrapper_jar = project_dir / "gradle" / "wrapper" / "gradle-wrapper.jar"
    if wrapper_script.exists() and wrapper_props.exists() and wrapper_jar.is_file():
        props_text = wrapper_props.read_text(encoding="utf-8", errors="ignore")
        if f"gradle-{gradle_version}-bin.zip" in props_text:
            print("[fabricpy] Gradle wrapper already present.")
            return True
        print(f"[fabricpy] Updating Gradle wrapper to {gradle_version}...")

    gradle_bin = shutil.which("gradle", path=env.get("PATH"))
    if gradle_bin:
        print("[fabricpy] Setting up Gradle wrapper via system Gradle...")
        wrapper_tmp = Path(tempfile.mkdtemp(prefix="fabricpy-gradle-wrapper-"))
        (wrapper_tmp / "settings.gradle").write_text('rootProject.name = "fabricpy-wrapper"\n', encoding="utf-8")
        try:
            result = subprocess.run(
                [gradle_bin, "--no-daemon", "wrapper", "--gradle-version", gradle_version],
                cwd=wrapper_tmp,
                env=env,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            print("[fabricpy] gradle wrapper timed out after 3 minutes.")
            result = None
        if result is not None and result.returncode == 0:
            for name in ("gradlew", "gradlew.bat"):
                src = wrapper_tmp / name
                if src.exists():
                    shutil.copy2(src, project_dir / name)
            wrapper_src = wrapper_tmp / "gradle" / "wrapper"
            wrapper_dest = project_dir / "gradle" / "wrapper"
            if wrapper_dest.exists():
                shutil.rmtree(wrapper_dest)
            shutil.copytree(wrapper_src, wrapper_dest)
            gradlew = project_dir / "gradlew"
            if gradlew.exists():
                gradlew.chmod(0o755)
            print("[fabricpy] Gradle wrapper ready.")
            shutil.rmtree(wrapper_tmp, ignore_errors=True)
            return True
        if result is not None:
            print(f"[fabricpy] gradle wrapper failed with exit code {result.returncode}.")
        shutil.rmtree(wrapper_tmp, ignore_errors=True)

    print("[fabricpy] Generating minimal Gradle wrapper scripts...")
    _write_wrapper_scripts(project_dir, gradle_version)

    print("[fabricpy] Could not find gradle-wrapper.jar.")
    print("[fabricpy] Please install Gradle (https://gradle.org/install/) and run:")
    print(f"    cd {project_dir} && gradle wrapper --gradle-version {gradle_version}")
    return False


def _write_wrapper_scripts(project_dir: Path, gradle_version: str):
    """Write gradlew and gradlew.bat scripts."""
    wrapper_dir = project_dir / "gradle" / "wrapper"
    wrapper_dir.mkdir(parents=True, exist_ok=True)

    (wrapper_dir / "gradle-wrapper.properties").write_text(
        "distributionBase=GRADLE_USER_HOME\n"
        "distributionPath=wrapper/dists\n"
        f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{gradle_version}-bin.zip\n"
        "networkTimeout=10000\n"
        "validateDistributionUrl=true\n"
        "zipStoreBase=GRADLE_USER_HOME\n"
        "zipStorePath=wrapper/dists\n"
    , encoding="utf-8")

    gradlew = r"""#!/bin/sh
##############################################################################
# Gradle start up script for UN*X
# Generated by fabricpy
##############################################################################
APP_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "$JAVA_HOME" ]; then
  exec "$JAVA_HOME/bin/java" -jar "$APP_HOME/gradle/wrapper/gradle-wrapper.jar" "$@"
fi
exec java -jar "$APP_HOME/gradle/wrapper/gradle-wrapper.jar" "$@"
"""
    gradlew_path = project_dir / "gradlew"
    gradlew_path.write_text(gradlew, encoding="utf-8")
    gradlew_path.chmod(0o755)

    (project_dir / "gradlew.bat").write_text(
        "@rem Generated by fabricpy\r\n"
        "@echo off\r\n"
        "if defined JAVA_HOME (\r\n"
        "  \"%JAVA_HOME%\\bin\\java.exe\" -jar \"%~dp0gradle\\wrapper\\gradle-wrapper.jar\" %*\r\n"
        ") else (\r\n"
        "  java -jar \"%~dp0gradle\\wrapper\\gradle-wrapper.jar\" %*\r\n"
        ")\r\n",
        encoding="utf-8",
    )


def run_build(project_dir: Path, minecraft_version: str, loader: str, clean: bool = False, output_dir: Path = None) -> bool:
    """
    Run the Gradle build in project_dir and copy output .jar to output_dir.

    Returns True if build succeeded.
    """
    gradle_version = _required_gradle_version(loader, minecraft_version)
    required_major = _required_java_major(minecraft_version)
    runtime_minimum = _gradle_runtime_minimum(loader, minecraft_version)
    java_exe = _find_gradle_java_executable(gradle_version, min_major=runtime_minimum)
    if not java_exe:
        max_major = _max_java_major_for_gradle(gradle_version)
        print(
            f"[fabricpy] Error: No Java runtime compatible with Gradle {gradle_version} was found. "
            f"Install a Gradle runtime JDK from {runtime_minimum} to {max_major}. Minecraft {minecraft_version} compiles with the Java {required_major} toolchain."
        )
        return False

    env = _build_env(java_exe)

    if not _setup_gradle_wrapper(project_dir, env, gradle_version):
        print("[fabricpy] Build skipped - Gradle wrapper not set up.")
        print(f"[fabricpy] Source was generated at: {project_dir}")
        print("[fabricpy] Once you have Gradle installed, run:")
        print(f"    cd {project_dir} && gradle wrapper && ./gradlew build")
        return False

    gradlew = str(project_dir / ("gradlew.bat" if sys.platform == "win32" else "gradlew"))
    task = "clean build" if clean else "build"
    cmd = [gradlew, "--no-daemon"] + task.split()

    print(f"[fabricpy] Running: {' '.join(cmd)}")
    print("[fabricpy] (This will download Minecraft and Fabric/Forge on first run - may take a few minutes)")

    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print("[fabricpy] Build timed out after 10 minutes.")
        return False
    except KeyboardInterrupt:
        print("\n[fabricpy] Build cancelled.")
        return False

    if result.returncode != 0:
        print(f"[fabricpy] Build FAILED (exit code {result.returncode})")
        print("[fabricpy] Check the output above for Java compiler errors.")
        print(f"[fabricpy] Generated source is at: {project_dir / 'src'}")
        return False

    libs_dir = project_dir / "build" / "libs"
    jars = [f for f in libs_dir.glob("*.jar") if not f.name.endswith(("-sources.jar", "-javadoc.jar", "-dev.jar"))]
    if not jars:
        print(f"[fabricpy] Build produced no distributable JARs in {libs_dir}")
        return False
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for jar in jars:
            dest = output_dir / jar.name
            shutil.copy2(jar, dest)
            print(f"[fabricpy] Built: {dest}")

    return True


def resolve_project_dependencies(project_dir: Path, minecraft_version: str, loader: str) -> bool:
    """Resolve the actual Java compile classpath before translating dependency calls."""
    gradle_version = _required_gradle_version(loader, minecraft_version)
    runtime_minimum = _gradle_runtime_minimum(loader, minecraft_version)
    java_exe = _find_gradle_java_executable(gradle_version, min_major=runtime_minimum)
    if not java_exe:
        print(f"[fabricpy] Cannot resolve dependencies: install a Gradle {gradle_version} compatible runtime JDK (Java {runtime_minimum} to {_max_java_major_for_gradle(gradle_version)}).")
        return False
    env = _build_env(java_exe)
    if not _setup_gradle_wrapper(project_dir, env, gradle_version):
        return False
    meta_dir = project_dir / ".fabricpy_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    init_script = meta_dir / "resolve.init.gradle"
    init_script.write_text('''\
gradle.projectsEvaluated {
    rootProject.tasks.register('fabricpyResolveDependencies') {
        doLast {
            def config = rootProject.configurations.findByName('compileClasspath')
            def artifacts = config == null ? [] : config.resolvedConfiguration.resolvedArtifacts.collect {
                def classifier = it.classifier ?: ''
                def extension = it.extension ?: 'jar'
                def coordinate = "${it.moduleVersion.id.group}:${it.name}:${it.moduleVersion.id.version}" +
                    (classifier ? ":${classifier}" : '') + (extension == 'jar' ? '' : "@${extension}")
                [coordinate: coordinate, classifier: classifier, extension: extension, path: it.file.absolutePath]
            }
            def output = new File(rootProject.projectDir, '.fabricpy_meta/resolved_dependencies.json')
            output.text = groovy.json.JsonOutput.toJson(artifacts)
        }
    }
}
''', encoding="utf-8")
    gradlew = project_dir / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
    try:
        result = subprocess.run([str(gradlew), "--no-daemon", "--init-script", str(init_script), "fabricpyResolveDependencies"],
                                cwd=project_dir, env=env, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[fabricpy] Dependency resolution failed: {exc}")
        return False
    return result.returncode == 0

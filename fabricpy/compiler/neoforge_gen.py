from __future__ import annotations

import re
from pathlib import Path

from fabricpy.compiler.forge_gen import _uses_geckolib, _forge_repository_lines, generate_forge_project
from fabricpy.compiler.dependencies import dependencies_for_loader, gradle_notation
from fabricpy.compiler.versions import NEOFORGE_VERSIONS


def generate_neoforge_project(mod, project_dir: Path):
    version_meta = NEOFORGE_VERSIONS.get(mod.minecraft_version)
    if version_meta is None:
        raise ValueError(f"NeoForge does not support minecraft_version={mod.minecraft_version!r} in this generator.")
    if mod._packets:
        raise ValueError("NeoForge packet generation is not implemented yet; remove mod.packet(...) or target fabric/forge.")

    generate_forge_project(mod, project_dir, loader_name="neoforge")
    _rewrite_java_sources(project_dir)
    _rewrite_mods_toml(mod, project_dir, version_meta)
    _write_neoforge_gradle_files(mod, project_dir, version_meta)
    print(f"[fabricpy] NeoForge project generated at {project_dir}")


def _rewrite_java_sources(project_dir: Path):
    replacements = (
        ("net.minecraftforge.fml", "net.neoforged.fml"),
        ("net.minecraftforge.eventbus.api", "net.neoforged.bus.api"),
        ("net.minecraftforge.common.MinecraftForge.EVENT_BUS", "net.neoforged.neoforge.common.NeoForge.EVENT_BUS"),
        ("net.minecraftforge.common.MinecraftForge", "net.neoforged.neoforge.common.NeoForge"),
        ("net.minecraftforge.client.event", "net.neoforged.neoforge.client.event"),
        ("net.minecraftforge.event.", "net.neoforged.neoforge.event."),
        ("net.minecraftforge.registries", "net.neoforged.neoforge.registries"),
        ("net.minecraftforge.network", "net.neoforged.neoforge.network"),
    )
    for path in (project_dir / "src" / "main" / "java").rglob("*.java"):
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        text = text.replace("modId=\"forge\"", "modId=\"neoforge\"")
        text = _adapt_neoforge_121_java(text)
        path.write_text(text, encoding="utf-8")


def _adapt_neoforge_121_java(text: str) -> str:
    """Adapt shared Forge source to the explicit 1.21.1 NeoForge API surface."""
    text = text.replace("import net.neoforged.fml.javafmlmod.FMLJavaModLoadingContext;\n", "")
    text = re.sub(
        r"public ([A-Za-z_$][\w$]*)\(\) \{\s*IEventBus bus = FMLJavaModLoadingContext\.get\(\)\.getModEventBus\(\);",
        r"public \1(IEventBus bus) {", text,
    )
    text = text.replace("import net.neoforged.neoforge.registries.ForgeRegistries;",
                        "import net.minecraft.core.registries.BuiltInRegistries;")
    text = text.replace("import net.neoforged.neoforge.registries.RegistryObject;", "import java.util.function.Supplier;")
    text = text.replace("RegistryObject<", "Supplier<")
    text = re.sub(r"event\.accept\(([A-Z_][A-Z0-9_]*)\)", r"event.accept(\1.get())", text)
    registries = {
        "BLOCK_ENTITY_TYPES": "BLOCK_ENTITY_TYPE", "PARTICLE_TYPES": "PARTICLE_TYPE",
        "ENTITY_TYPES": "ENTITY_TYPE", "SOUND_EVENTS": "SOUND_EVENT",
        "MOB_EFFECTS": "MOB_EFFECT", "BLOCKS": "BLOCK", "ITEMS": "ITEM",
    }
    for forge_name, builtin_name in registries.items():
        text = text.replace(f"ForgeRegistries.{forge_name}", f"BuiltInRegistries.{builtin_name}")
    text = re.sub(r"(BuiltInRegistries\.[A-Z_]+)\.getValue\(", r"\1.get(", text)
    text = _rewrite_resource_locations(text)
    text = text.replace("ClipContext.Fluid.NONE, null", "ClipContext.Fluid.NONE, (net.minecraft.world.entity.Entity) null")
    # 1.21 separates item-bearing interactions from empty-hand block interaction.
    use_pattern = re.compile(
        r"public InteractionResult use\(BlockState state, Level level, BlockPos pos,\s*"
        r"Player player, InteractionHand hand, BlockHitResult hit\) \{",
    )
    pieces = []
    cursor = 0
    for match in use_pattern.finditer(text):
        closing = _java_block_end(text, match.end() - 1)
        body = text[match.end():closing].replace("        ItemStack stack = player.getItemInHand(hand);\n", "")
        body = body.replace("return InteractionResult.", "return net.minecraft.world.ItemInteractionResult.")
        pieces.append(text[cursor:match.start()])
        pieces.append(
            "public net.minecraft.world.ItemInteractionResult useItemOn(ItemStack stack, BlockState state, Level level, BlockPos pos,\n"
            "                                  Player player, InteractionHand hand, BlockHitResult hit) {" + body + "}\n\n"
            "    @Override\n"
            "    public InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {\n"
            "        return useItemOn(player.getMainHandItem(), state, level, pos, player, InteractionHand.MAIN_HAND, hit).result();\n"
            "    }"
        )
        cursor = closing + 1
    pieces.append(text[cursor:])
    return "".join(pieces)


def _java_block_end(text: str, opening: int) -> int:
    """Find a generated method's end without mistaking callback branches for it."""
    depth, quote, escaped = 1, None, False
    line_comment, block_comment = False, False
    index = opening + 1
    while index < len(text):
        char = text[index]
        following = text[index:index + 2]
        if line_comment:
            line_comment = char != "\n"
        elif block_comment:
            if following == "*/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif following == "//":
            line_comment = True
            index += 1
        elif following == "/*":
            block_comment = True
            index += 1
        elif char in {'"', "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("Generated NeoForge interaction method has an unclosed Java block")


def _rewrite_resource_locations(text: str) -> str:
    """Choose the 1.21 factory while retaining nested expressions and string commas."""
    pattern = re.compile(r"new ((?:net\.minecraft\.resources\.)?ResourceLocation)\(")
    result = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() < cursor:
            continue
        depth, commas, quote, escaped = 1, 0, None, False
        end = match.end()
        while end < len(text) and depth:
            char = text[end]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 1:
                commas += 1
            end += 1
        if depth:
            continue
        factory = "fromNamespaceAndPath" if commas else "parse"
        result.append(text[cursor:match.start()])
        result.append(f"{match.group(1)}.{factory}(" + text[match.end():end])
        cursor = end
    result.append(text[cursor:])
    return "".join(result)


def _rewrite_mods_toml(mod, project_dir: Path, version_meta):
    path = project_dir / "src" / "main" / "resources" / "META-INF" / "mods.toml"
    text = path.read_text(encoding="utf-8")
    text = text.replace('modId="forge"', 'modId="neoforge"')
    text = re.sub(r'versionRange="[^"]+"', f'versionRange="{version_meta.neoforge_dep}"', text, count=1)
    text = re.sub(r'loaderVersion="[^"]+"', f'loaderVersion="{version_meta.loader_version}"', text, count=1)
    text = text.replace("mandatory=true", 'type="required"')
    dest = path.with_name("neoforge.mods.toml")
    dest.write_text(text, encoding="utf-8")
    path.unlink()


def _write_neoforge_gradle_files(mod, project_dir: Path, version_meta):
    mc = mod.minecraft_version
    extra_repos = _forge_repository_lines(mod, "neoforge")
    extra_deps = [f"    {dep.scope or 'implementation'} {gradle_notation(dep)}" for dep in dependencies_for_loader(mod, "neoforge")]
    use_geckolib = _uses_geckolib(mod)
    geckolib_repo = (
        "    maven { url = 'https://dl.cloudsmith.io/public/geckolib3/geckolib/maven/' }"
        if use_geckolib
        else ""
    )
    geckolib_dep = (
        f"    implementation 'software.bernie.geckolib:geckolib-neoforge-{mc}:{version_meta.geckolib}'"
        if use_geckolib
        else ""
    )

    build_gradle = f"""\
plugins {{
    id 'java-library'
    id 'maven-publish'
    id 'net.neoforged.moddev' version '{version_meta.plugin}'
}}

version = "{mod.version}"
group = "{mod.package}"

base {{
    archivesName = "{mod.mod_id}-neoforge"
}}

java.toolchain.languageVersion = JavaLanguageVersion.of({version_meta.java})

neoForge {{
    version = "{version_meta.neoforge}"

    runs {{
        client {{
            client()
        }}
        server {{
            server()
            programArgument '--nogui'
        }}
    }}

    mods {{
        "{mod.mod_id}" {{
            sourceSet sourceSets.main
        }}
    }}
}}

repositories {{
{chr(10).join(extra_repos)}
{geckolib_repo}
    mavenCentral()
}}

dependencies {{
{chr(10).join(extra_deps)}
{geckolib_dep}
}}

tasks.withType(JavaCompile).configureEach {{
    options.encoding = 'UTF-8'
    options.release = {version_meta.java}
}}
"""
    (project_dir / "build.gradle").write_text(build_gradle, encoding="utf-8")
    (project_dir / "settings.gradle").write_text(f"""\
pluginManagement {{
    repositories {{
        maven {{ url = 'https://maven.neoforged.net/releases' }}
        gradlePluginPortal()
        mavenCentral()
    }}
}}
plugins {{
    id 'org.gradle.toolchains.foojay-resolver-convention' version '1.0.0'
}}
rootProject.name = "{mod.mod_id}-neoforge"
""", encoding="utf-8")
    (project_dir / "gradle.properties").write_text(
        "org.gradle.jvmargs=-Xmx2G\n"
        "org.gradle.parallel=true\n",
        encoding="utf-8",
    )

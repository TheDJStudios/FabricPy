import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import fabricpy as mc
from fabricpy.addons import resolve_addon, discover_addons
from fabricpy.compiler import _validate, compile_mod
from fabricpy.compiler.gradle_runner import _setup_gradle_wrapper
from tests.support import project_dir


class WorkflowTests(unittest.TestCase):
    def test_external_loader_addon_relative_import_and_custom_builder(self):
        with project_dir() as root:
            addon = root / 'fabricpy_addons/custom'
            addon.mkdir(parents=True)
            (addon / 'helper.py').write_text('VALUE = "generated"\n')
            (addon / 'addon.py').write_text('''from .helper import VALUE
ADDON_KIND = "loader"
ADDON_TARGET = "custom"
MINECRAFT_VERSION = "1.20.1"
def generate_project(mod, project_dir):
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "result.txt").write_text(VALUE)
def build_project(project_dir, minecraft_version, clean=False, output_dir=None):
    return True
''')
            mod = mc.Mod('example', 'Example', loader='custom')
            paths = mod.generate()
            self.assertEqual((paths['custom'] / 'result.txt').read_text(), 'generated')
            self.assertEqual(mod.compile(), {'custom': True})
            self.assertIsNotNone(resolve_addon('loader', 'custom', '1.20.1'))

    def test_compile_reports_failed_build(self):
        with project_dir(), patch('fabricpy.addons.Addon.build_project', return_value=False):
            self.assertEqual(mc.Mod('example', 'Example').compile(), {'fabric': False})

    def test_invalid_registry_id_and_block_item_conflict(self):
        mod = mc.Mod('example', 'Example')
        @mod.register
        class Invalid(mc.Block):
            block_id = '../invalid'
        with self.assertRaisesRegex(ValueError, 'block_id'):
            _validate(mod)
        mod = mc.Mod('example', 'Example')
        @mod.register
        class Block(mc.Block):
            block_id = 'same'
        @mod.register
        class Item(mc.Item):
            item_id = 'same'
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            _validate(mod)

    def test_missing_wrapper_jar_is_not_success(self):
        with project_dir() as root, patch('fabricpy.compiler.gradle_runner.shutil.which', return_value=None):
            (root / 'gradlew').touch()
            wrapper = root / 'gradle/wrapper'
            wrapper.mkdir(parents=True)
            (wrapper / 'gradle-wrapper.properties').write_text('distributionUrl=gradle-8.8-bin.zip')
            self.assertFalse(_setup_gradle_wrapper(root, {}, '8.8'))

    def test_advancement_generation_does_not_mutate_source(self):
        with project_dir():
            mod = mc.Mod('example', 'Example', loader='both')
            mod.item_advancement('story/test', 'Test', 'Get token', 'minecraft:stone')
            original = json.dumps(mod._advancements)
            paths = mod.generate()
            self.assertEqual(json.dumps(mod._advancements), original)
            for project in paths.values():
                lang = json.loads((project / 'src/main/resources/assets/example/lang/en_us.json').read_text())
                self.assertEqual(lang['advancement.example.story.test.title'], 'Test')

    def test_inherited_hooks_and_overrides(self):
        class Base(mc.Block):
            @mc.on_use
            def interact(self, ctx):
                pass
        class Child(Base):
            block_id = 'child'
        class Disabled(Base):
            def interact(self, ctx):
                pass
        self.assertIn('on_use', Child.get_hooks())
        self.assertNotIn('on_use', Disabled.get_hooks())

    def test_cli_generates_relative_to_source_and_returns_failure(self):
        from fabricpy.__main__ import main
        with project_dir() as root:
            folder = root / 'project'
            folder.mkdir()
            source = folder / 'mod.py'
            source.write_text('import fabricpy as mc\nmod = mc.Mod("example", "Example")\nif __name__ == "__main__":\n    raise RuntimeError("main guard should not execute")\n')
            self.assertEqual(main(['generate', str(source)]), 0)
            self.assertTrue((folder / '.fabricpy_build/example-fabric/build.gradle').is_file())
            self.assertEqual(Path.cwd().resolve(), root.resolve())
            with patch('fabricpy.mod.Mod.compile', return_value={'fabric': False}):
                self.assertEqual(main(['build', str(source)]), 1)

    def test_custom_builder_with_dependency_metadata_does_not_require_gradle(self):
        from types import ModuleType
        from fabricpy.addons import Addon
        from fabricpy.compiler.symbol_index import write_interop_metadata
        with project_dir() as root:
            module = ModuleType("custom_test")
            def generate(mod, project_dir):
                write_interop_metadata(mod, project_dir, "custom", [], [])
            module.generate_project = generate
            module.build_project = lambda *a, **kw: True
            addon = Addon("loader", "custom", "1.20.1", "test", module, root)
            # Metadata may contain dependencies resolved by a backend's own builder.
            mod = mc.Mod("example", "Example", loader="custom")
            mod.dependency(coordinate="example:helper:1.0")
            with patch("fabricpy.compiler._resolve_loaders", return_value=["custom"]), patch("fabricpy.addons.resolve_addon", return_value=addon), patch("fabricpy.compiler.gradle_runner.resolve_project_dependencies") as gradle:
                self.assertEqual(mod.compile(), {"custom": True})
                gradle.assert_not_called()

    def test_init_creates_buildable_source_and_preserves_existing_directory(self):
        from fabricpy.__main__ import main
        with project_dir() as root:
            target = root / "starter"
            self.assertEqual(main(["init", str(target), "--mod-id", "starter"]), 0)
            self.assertTrue((target / "assets/starter/textures/block/starter.png").read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(main(["generate", str(target / "mod.py")]), 0)
            source = (target / "mod.py").read_bytes()
            self.assertEqual(main(["init", str(target)]), 1)
            self.assertEqual((target / "mod.py").read_bytes(), source)

    def test_forge_registers_automatic_block_items(self):
        from fabricpy.compiler.forge_gen import generate_forge_project
        with project_dir() as root:
            mod = mc.Mod("example", "Example", loader="forge")
            @mod.register
            class Starter(mc.Block):
                block_id = "starter"
            generate_forge_project(mod, root / "generated")
            source = (root / "generated/src/main/java/com/generated/example/Example.java").read_text()
            self.assertIn("ModBlocks.BLOCKS.register(bus);", source)
            self.assertIn("ModBlocks.ITEMS.register(bus);", source)

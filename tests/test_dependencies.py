import ast
import json
import os
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import fabricpy as mc
from fabricpy.compiler.jar_scanner import build_symbol_index_for_project, _resolve_gradle_cached_jars, _resolved_jars_for_coordinate
from fabricpy.compiler.symbol_index import write_interop_metadata
from fabricpy.compiler.transpiler import JavaTranspiler
from fabricpy.compiler.fabric_gen import generate_fabric_project
from fabricpy.compiler.forge_gen import generate_forge_project
from fabricpy.compiler.quilt_gen import generate_quilt_project
from fabricpy.compiler.neoforge_gen import generate_neoforge_project
from tests.support import project_dir


class DependencyTests(unittest.TestCase):
    def test_loader_dependencies_are_preserved_and_filtered(self):
        with project_dir() as root:
            jar = root / 'dependency.jar'
            with zipfile.ZipFile(jar, 'w'):
                pass
            for loader, version, generator in [
                ('fabric', '1.20.1', generate_fabric_project), ('forge', '1.20.1', generate_forge_project),
                ('quilt', '1.20.1', generate_quilt_project), ('neoforge', '1.21.1', generate_neoforge_project),
            ]:
                mod = mc.Mod('example', 'Example', minecraft_version=version, loader=loader)
                mod.dependency(path=jar, loader=loader, mod_id='helper', required=True)
                mod.dependency(coordinate='example:wrong:1.0', loader='other', mod_id='wrong', required=True)
                generated = root / loader
                generator(mod, generated)
                gradle = (generated / 'build.gradle').read_text()
                self.assertIn('files(', gradle)
                self.assertIn(str(jar), gradle)
                self.assertNotIn('example:wrong', gradle)
                metadata = json.loads((generated / '.fabricpy_meta/interop_project.json').read_text())
                self.assertEqual(metadata['loader'], loader)
                self.assertEqual(len(metadata['dependencies']), 1)
                if loader in {'fabric', 'quilt'}:
                    manifest = json.loads((generated / 'src/main/resources/fabric.mod.json').read_text())
                    self.assertIn('helper', manifest['depends'])
                    self.assertNotIn('wrong', manifest['depends'])
                else:
                    name = 'neoforge.mods.toml' if loader == 'neoforge' else 'mods.toml'
                    self.assertIn('modId="helper"', (generated / 'src/main/resources/META-INF' / name).read_text())

    @unittest.skipUnless(shutil.which('javac') and shutil.which('javap'), 'JDK required')
    def test_local_jar_scan_constructor_static_nested_and_valid_stubs(self):
        with project_dir() as root:
            source = root / 'Widget.java'
            source.write_text('''package sample;
public final class Widget {
 public static final String NAME = "widget";
 public Widget(String name) {}
 public static int count(int a) { return a; }
 public static class Nested { public Nested() {} }
}''')
            subprocess.run(['javac', '-d', str(root / 'classes'), str(source)], check=True, capture_output=True)
            jar = root / 'helper.jar'
            with zipfile.ZipFile(jar, 'w') as archive:
                for file in (root / 'classes').rglob('*.class'):
                    archive.write(file, file.relative_to(root / 'classes').as_posix())
            mod = mc.Mod('example', 'Example')
            mod.dependency(path=jar, mod_id='helper')
            write_interop_metadata(mod, root / 'generated', 'fabric', [], [])
            index = build_symbol_index_for_project(root / 'generated')
            self.assertEqual(index['status'], 'complete')
            details = index['dependencies'][0]['class_details']
            self.assertTrue(any(m['constructor'] for m in details['sample.Widget.Nested']['methods']))
            transpiler = JavaTranspiler({}, interop_index_path=root / 'generated/.fabricpy_meta/symbol_index.json')
            output = transpiler.transpile_method('def hook(ctx):\n    widget = dep.helper.sample.Widget("name")\n    count = dep.helper.sample.Widget.count(1)')
            self.assertIn('new sample.Widget("name")', output)
            self.assertNotIn('// interop:', output)
            for stub in (root / 'generated/.fabricpy_meta/python_stubs').rglob('*.pyi'):
                ast.parse(stub.read_text())
            nested = (root / 'generated/.fabricpy_meta/python_stubs/dep/helper/sample/__init__.pyi').read_text()
            self.assertIn('class Widget_Nested:', nested)
            self.assertIn('def __init__(self) -> None', nested)

    def test_gradle_user_home_and_classifiers(self):
        with project_dir() as root, patch.dict(os.environ, {'GRADLE_USER_HOME': str(root)}):
            folder = root / 'caches/modules-2/files-2.1/group/artifact/1.0/hash'
            folder.mkdir(parents=True)
            for name in ('artifact-1.0.jar', 'artifact-1.0-api.jar', 'artifact-1.0-sources.jar'):
                (folder / name).touch()
            self.assertEqual([p.name for p in _resolve_gradle_cached_jars('group:artifact:1.0')], ['artifact-1.0.jar'])
            self.assertEqual([p.name for p in _resolve_gradle_cached_jars('group:artifact:1.0:api')], ['artifact-1.0-api.jar'])

    def test_dependency_input_validation(self):
        mod = mc.Mod('example', 'Example')
        for kwargs in ({}, {'path': 'missing.jar'}, {'coordinate': 'bad'}, {'coordinate': 'a:b:1', 'path': 'bad.jar'}):
            with self.assertRaises(ValueError):
                mod.dependency(**kwargs)


    def test_dynamic_versions_use_selected_gradle_artifacts(self):
        with project_dir() as root:
            jar = root / 'artifact-1.2.jar'
            with zipfile.ZipFile(jar, 'w'):
                pass
            mod = mc.Mod('example', 'Example')
            mod.dependency(coordinate='group:artifact:1.+', mod_id='api')
            generated = root / 'generated'
            write_interop_metadata(mod, generated, 'fabric', [], [])
            (generated / '.fabricpy_meta/resolved_dependencies.json').write_text(json.dumps([
                {'coordinate': 'group:artifact:1.2', 'classifier': '', 'extension': 'jar', 'path': str(jar)},
            ]))
            index = build_symbol_index_for_project(generated)
            self.assertEqual(index['unresolved_dependencies'], [])
            self.assertEqual(index['resolved_jars'][0]['resolved_coordinate'], 'group:artifact:1.2')
            self.assertEqual(index['resolved_jars'][0]['coordinate'], 'group:artifact:1.+')

    def test_resolved_classifiers_are_not_confused_with_main_artifact(self):
        artifacts = [
            {'coordinate': 'group:artifact:1.2:api', 'classifier': 'api', 'extension': 'jar', 'path': '/tmp/artifact-1.2-api.jar'},
            {'coordinate': 'group:artifact:1.2', 'classifier': '', 'extension': 'jar', 'path': '/tmp/artifact-1.2.jar'},
        ]
        self.assertEqual(_resolved_jars_for_coordinate('group:artifact:[1,2):api', artifacts), [Path('/tmp/artifact-1.2-api.jar')])
        self.assertEqual(_resolved_jars_for_coordinate('group:artifact:1.+', artifacts), [Path('/tmp/artifact-1.2.jar')])
        self.assertEqual(_resolved_jars_for_coordinate('group:artifact:1.+@zip', artifacts), [])
        # Old resolver JSON omitted classifier attributes and suffixes from coordinates.
        legacy = [{'coordinate': 'group:artifact:1.2', 'path': '/tmp/artifact-1.2-api.jar'}]
        self.assertEqual(_resolved_jars_for_coordinate('group:artifact:1.+', legacy), [])
        self.assertEqual(_resolved_jars_for_coordinate('group:artifact:1.+:api', legacy), [Path('/tmp/artifact-1.2-api.jar')])

    def test_neoforge_gradle_jvm_can_use_toolchain_for_target_java(self):
        from fabricpy.compiler.gradle_runner import _gradle_runtime_minimum, run_build, resolve_project_dependencies
        self.assertEqual(_gradle_runtime_minimum('neoforge', '1.21.1'), 17)
        self.assertEqual(_gradle_runtime_minimum('fabric', '1.21.1'), 21)
        self.assertEqual(_gradle_runtime_minimum('forge', '1.21.1'), 21)
        with project_dir() as root:
            libs = root / 'build/libs'
            libs.mkdir(parents=True)
            (libs / 'example.jar').touch()
            with patch('fabricpy.compiler.gradle_runner._find_gradle_java_executable', return_value='/jdk17/bin/java') as find_java, \
                 patch('fabricpy.compiler.gradle_runner._setup_gradle_wrapper', return_value=True), \
                 patch('fabricpy.compiler.gradle_runner.subprocess.run') as run:
                run.return_value.returncode = 0
                self.assertTrue(run_build(root, '1.21.1', 'neoforge'))
                find_java.assert_called_with('9.3.0', min_major=17)
                self.assertTrue(resolve_project_dependencies(root, '1.21.1', 'neoforge'))
                find_java.assert_called_with('9.3.0', min_major=17)
                script = (root / '.fabricpy_meta/resolve.init.gradle').read_text()
                self.assertIn('classifier: classifier', script)
                self.assertIn('extension: extension', script)

    def test_changed_dependencies_invalidate_resolved_classpath(self):
        with project_dir() as root:
            mod = mc.Mod("example", "Example")
            dependency = mod.dependency(coordinate="group:artifact:1.0")
            project = root / "generated"
            write_interop_metadata(mod, project, "fabric", [], [])
            resolved = project / ".fabricpy_meta/resolved_dependencies.json"
            resolved.write_text("[]")
            write_interop_metadata(mod, project, "fabric", [], [])
            self.assertTrue(resolved.is_file())
            dependency.coordinate = "group:artifact:2.0"
            write_interop_metadata(mod, project, "fabric", [], [])
            self.assertFalse(resolved.exists())

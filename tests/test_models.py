import base64
import json
import unittest
from pathlib import Path

import fabricpy as mc
from fabricpy.compiler.bbmodel_converter import (
    convert_bbmodel_to_java_model, convert_bbmodel_to_geckolib_geo, resolve_model_input,
)
from fabricpy.compiler.fabric_gen import generate_fabric_project
from fabricpy.compiler.forge_gen import generate_forge_project
from tests.support import project_dir

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')


def model():
    return {
        'meta': {'format_version': '5.0', 'model_format': 'java_block'},
        'resolution': {'width': 32, 'height': 32},
        'textures': [{'id': '0', 'name': 'test.png', 'source': 'data:image/png;base64,' + base64.b64encode(PNG).decode()}],
        'elements': [{'uuid': 'cube', 'from': [0, 0, 0], 'to': [16, 8, 16], 'faces': {
            'north': {'uv': [0, 0, 32, 16], 'texture': 0},
            'south': {'uv': [0, 0, 32, 16], 'texture': None},
        }}],
        'groups': [{'uuid': 'group', 'name': 'body', 'origin': [8, 8, 8]}],
        'outliner': [{'uuid': 'group', 'children': ['cube']}],
        'display': {'gui': {'rotation': [30, 45, 0]}},
    }


class ModelTests(unittest.TestCase):
    def test_static_bbmodel_in_both_generator_families(self):
        with project_dir() as root:
            Path('models').mkdir()
            Path('models/table.bbmodel').write_text(json.dumps(model()))
            for name, generator in [('fabric', generate_fabric_project), ('forge', generate_forge_project)]:
                mod = mc.Mod('example', 'Example')
                @mod.register
                class Table(mc.Block):
                    block_id = 'table'
                    model = 'models/table.bbmodel'
                    model_collision = True
                @mod.register
                class Tool(mc.Item):
                    item_id = 'tool'
                    model = Path('models/table.bbmodel')
                generator(mod, root / name)
                assets = root / name / 'src/main/resources/assets/example'
                block = json.loads((assets / 'models/block/table.json').read_text())
                self.assertEqual(block['elements'][0]['faces']['north']['uv'], [0, 0, 16, 8])
                self.assertNotIn('south', block['elements'][0]['faces'])
                self.assertEqual((assets / 'textures/block/table/test.png').read_bytes(), PNG)
                self.assertIsInstance(json.loads((assets / 'models/item/tool.json').read_text()), dict)
                self.assertEqual(Table.model, 'models/table.bbmodel')

    def test_asset_bbmodel_overrides_default_and_manual_json_wins(self):
        with project_dir() as root:
            source = Path('assets/example/models/block')
            source.mkdir(parents=True)
            (source / 'table.bbmodel').write_text(json.dumps(model()))
            mod = mc.Mod('example', 'Example')
            @mod.register
            class Table(mc.Block):
                block_id = 'table'
            for i in range(2):
                if i:
                    (source / 'table.json').write_text('{"parent":"example:block/manual"}')
                generate_fabric_project(mod, root / 'generated')
                output = json.loads((root / 'generated/src/main/resources/assets/example/models/block/table.json').read_text())
                self.assertEqual(output.get('parent'), 'example:block/manual' if i else None)
                if not i:
                    self.assertEqual(len(output['elements']), 1)

    def test_group_layout_5_preserves_bones(self):
        result = convert_bbmodel_to_geckolib_geo(model(), 'example', 'table')
        bone = result['minecraft:geometry'][0]['bones'][0]
        self.assertEqual(bone['name'], 'body')
        self.assertEqual(bone['pivot'], [8, 8, 8])
        self.assertEqual(len(bone['cubes']), 1)

    def test_unsupported_geometry_fails_explicitly(self):
        for change in ({'type': 'mesh'}, {'rotation': [30, 30, 0]}):
            value = model()
            value['elements'][0].update(change)
            with self.assertRaises(ValueError):
                convert_bbmodel_to_java_model(value, {'0': 'example:block/test'})

    def test_models_do_not_mutate_source_and_allow_resource_parent(self):
        value = {'textures': {'all': 'example:block/table'}}
        copy = resolve_model_input(value, 'example', 'block', 'table')
        copy['textures']['all'] = 'changed'
        self.assertEqual(value['textures']['all'], 'example:block/table')
        self.assertEqual(resolve_model_input('minecraft:block/cube_all', 'example', 'block', 'table'), {'parent': 'minecraft:block/cube_all'})

    def test_automatic_conversion_resolves_linked_texture_from_original_model(self):
        with project_dir() as root:
            source = root / 'assets/example/models/block'
            source.mkdir(parents=True)
            (root / 'source.png').write_bytes(PNG)
            data = model()
            data['textures'][0].pop('source')
            data['textures'][0]['relative_path'] = '../../../../source.png'
            (source / 'table.bbmodel').write_text(json.dumps(data))
            mod = mc.Mod('example', 'Example')
            @mod.register
            class Table(mc.Block):
                block_id = 'table'
            generate_fabric_project(mod, root / 'generated')
            self.assertEqual((root / 'generated/src/main/resources/assets/example/textures/block/table/test.png').read_bytes(), PNG)

    def test_missing_texture_fails_with_source_filename(self):
        with project_dir() as root:
            value = model()
            value['textures'][0].pop('source')
            source = root / 'table.bbmodel'
            source.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'table.bbmodel.*no PNG source'):
                resolve_model_input(source, 'example', 'block', 'table', root / 'generated/assets/example')

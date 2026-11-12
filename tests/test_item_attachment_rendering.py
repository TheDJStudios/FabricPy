import json
import math
import unittest

import fabricpy as mc
from fabricpy.compiler.item_attachment_rendering import (
    attachment_client_init_statement, attachment_item_client_extension,
    attachment_proxy_registrations, validate_attachment_rendering,
    write_attachment_renderer, write_attachment_resources,
)
from tests.support import project_dir


class ItemAttachmentRenderingTests(unittest.TestCase):
    def make_mod(self, loader='fabric', version='1.20.1'):
        mod = mc.Mod('example', 'Example', loader=loader, minecraft_version=version)
        @mod.register
        class Tool(mc.Item):
            item_id = 'tool'
            max_stack_size = 1
            attachment_slots = ('scope', 'charm')
            attachment_models = {'scope': {'position': [0, 0.5, 0], 'rotation': [0, 90, 0], 'scale': [0.4, 0.4, 0.4]}}
        return mod, Tool

    def test_native_renderers_draw_actual_owner_and_stored_stacks(self):
        for loader, version in (('fabric', '1.20.1'), ('quilt', '1.20.1'), ('forge', '1.20.1'), ('neoforge', '1.21.1')):
            with self.subTest(loader=loader), project_dir() as root:
                mod, item = self.make_mod(loader, version)
                self.assertTrue(write_attachment_renderer(mod, root, 'com.example', loader))
                source = (root / 'client/render/FabricPyAttachmentRenderer.java').read_text()
                self.assertIn('FabricPyItemStorage.getAttachment(owner, "scope")', source)
                self.assertIn('FabricPyItemStorage.getAttachment(owner, "charm")', source)
                self.assertIn('if (!attachment0.isEmpty())', source)
                self.assertIn('matrices.translate(0.0, 0.5, 0.0)', source)
                self.assertIn('matrices.scale(0.4f, 0.4f, 0.4f)', source)
                self.assertIn('depth >= 8', source)
                self.assertIn('DEPTH.set(depth)', source)
                if loader in {'fabric', 'quilt'}:
                    self.assertIn('renderer.renderItem(owner, ModelTransformationMode.NONE', source)
                    self.assertIn('renderer.renderItem(attachment0, ModelTransformationMode.NONE', source)
                    self.assertIn('model.getTransformation().getTransformation(mode).apply', source)
                    registration = (root / 'client/ModAttachmentRenderers.java').read_text()
                    self.assertIn('BuiltinItemRendererRegistry.INSTANCE.register(ModItems.TOOL', registration)
                    self.assertEqual(attachment_client_init_statement(mod, loader), 'ModAttachmentRenderers.register();')
                else:
                    self.assertIn('renderer.render(owner, ItemDisplayContext.NONE', source)
                    self.assertIn('renderer.renderStatic(attachment0, ItemDisplayContext.NONE', source)
                    self.assertIn('model.getTransforms().getTransform(mode).apply', source)
                    extension = attachment_item_client_extension(mod, item, 'com.example', loader)
                    if loader == 'forge':
                        self.assertIn('initializeClient(', extension)
                        self.assertIn('IClientItemExtensions', extension)
                    else:
                        self.assertEqual(extension, '')
                        registration = (root / 'client/ModAttachmentRenderers.java').read_text()
                        self.assertIn('RegisterClientExtensionsEvent', registration)
                        self.assertIn('value = Dist.CLIENT', registration)
                        self.assertIn('event.registerItem(', registration)

    def test_final_model_is_preserved_in_hidden_proxy(self):
        with project_dir() as root:
            mod, item = self.make_mod()
            models = root / 'assets/example/models/item'
            models.mkdir(parents=True)
            original = {'parent': 'minecraft:item/handheld', 'textures': {'layer0': 'example:item/tool'},
                        'display': {'gui': {'rotation': [10, 20, 30]}}, 'overrides': [{'predicate': {'custom_model_data': 1}, 'model': 'example:item/alternate'}]}
            (models / 'tool.json').write_text(json.dumps(original))
            write_attachment_resources(mod, root)
            self.assertEqual(json.loads((models / 'tool__base.json').read_text()), original)
            self.assertEqual(json.loads((models / 'tool.json').read_text()), {'parent': 'builtin/entity', 'gui_light': 'front'})
            self.assertEqual(len(mod._items), 1)
            self.assertIn('TOOL__BASE', attachment_proxy_registrations(mod, 'fabric')[0])
            self.assertIn('register("tool__base"', attachment_proxy_registrations(mod, 'fabric')[0])
            self.assertIn('ITEMS.register("tool__base"', attachment_proxy_registrations(mod, 'forge')[0])

    def test_transform_validation_and_unsupported_versions(self):
        for transform in ({'scale': [0, 1, 1]}, {'position': [1, 2]}, {'rotation': [0, math.nan, 0]}, {'unrecognized': 1}):
            mod, item = self.make_mod()
            item.attachment_models = {'scope': transform}
            with self.subTest(transform=transform), self.assertRaises(ValueError):
                validate_attachment_rendering(mod, item)
        mod, item = self.make_mod()
        item.attachment_models = {'unknown': {}}
        with self.assertRaisesRegex(ValueError, 'undeclared slots'):
            validate_attachment_rendering(mod, item)
        mod, item = self.make_mod(version='1.21.8')
        with self.assertRaisesRegex(ValueError, 'currently support'):
            validate_attachment_rendering(mod, item)

    def test_existing_builtin_renderer_is_rejected_instead_of_recursing(self):
        with project_dir() as root:
            mod, item = self.make_mod()
            models = root / 'assets/example/models/item'
            models.mkdir(parents=True)
            (models / 'tool.json').write_text('{"parent":"minecraft:builtin/entity"}')
            with self.assertRaisesRegex(ValueError, 'not another builtin/entity'):
                write_attachment_resources(mod, root)

    def test_ordinary_items_do_not_gain_hidden_items_or_renderers(self):
        with project_dir() as root:
            mod = mc.Mod('example', 'Example')
            self.assertFalse(write_attachment_renderer(mod, root, 'com.example', 'fabric'))
            self.assertEqual(attachment_proxy_registrations(mod, 'fabric'), [])
            self.assertEqual(attachment_client_init_statement(mod, 'fabric'), '')
            self.assertFalse((root / 'client').exists())

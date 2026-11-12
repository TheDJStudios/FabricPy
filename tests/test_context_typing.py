import inspect
from importlib.resources import files
import string
import unittest
from typing import get_type_hints

import fabricpy as mc
from fabricpy import context as ctx_types
from fabricpy.compiler.fabric_gen import _fabric_api_map_for_project
from fabricpy.compiler.forge_gen import _forge_api_map_for_project
from fabricpy.compiler.transpiler import JavaTranspiler


class ContextTypingTests(unittest.TestCase):
    def test_typed_annotation_keeps_callback_translation_unchanged(self):
        code = '''def interact(self, ctx: mc.BlockUseContext) -> None:
    if ctx.hand.is_main_hand():
        ctx.player.send_message("Hello")
'''
        untyped = code.replace(': mc.BlockUseContext', '').replace(' -> None', '')
        for api in (_fabric_api_map_for_project('1.20.1', 'example'), _forge_api_map_for_project('example')):
            self.assertEqual(JavaTranspiler(api).transpile_method(code), JavaTranspiler(api).transpile_method(untyped))

    def test_hook_contexts_expose_only_available_fields(self):
        use = get_type_hints(mc.BlockUseContext)
        place = get_type_hints(mc.BlockPlaceContext)
        item = get_type_hints(mc.ItemUseContext)
        block_tick = get_type_hints(mc.BlockTickContext)
        entity_tick = get_type_hints(mc.EntityTickContext)
        self.assertEqual(use['player'], ctx_types.Player)
        self.assertEqual(use['hand'], ctx_types.Hand)
        self.assertEqual(place['player'], ctx_types.Player | None)
        self.assertNotIn('hand', place)
        self.assertNotIn('stack', place)
        self.assertNotIn('block_entity', use)
        self.assertNotIn('pos', item)
        self.assertEqual(block_tick['block_entity'], ctx_types.BlockEntity)
        self.assertEqual(entity_tick['entity'], ctx_types.Entity)
        self.assertNotIn('player', entity_tick)
        self.assertEqual(get_type_hints(mc.BlockEntityUseContext)['block_entity'], ctx_types.BlockEntity)

    def test_portable_autocomplete_methods_match_both_compiler_backends(self):
        # A suggested method must compile on each bundled generator family with
        # the same positional argument count promised to the editor.
        apis = (_fabric_api_map_for_project('1.20.1', 'example'), _forge_api_map_for_project('example'))
        helpers = {
            'player': ctx_types.Player, 'world': ctx_types.PositionedWorld,
            'stack': ctx_types.ItemStack, 'block_entity': ctx_types.BlockEntity,
            'entity': ctx_types.Entity, 'math': ctx_types.Math, 'hand': ctx_types.Hand,
            'client': ctx_types.Client,
            'stack.data': ctx_types.ItemData, 'stack.inventory': ctx_types.ItemInventory,
            'stack.attachments': ctx_types.ItemAttachments,
        }
        for area, helper in helpers.items():
            for method_name, method in inspect.getmembers(helper, inspect.isfunction):
                if method_name.startswith('_'):
                    continue
                key = f'ctx.{area}.{method_name}'
                expected = len(inspect.signature(method).parameters) - 1
                for api in apis:
                    with self.subTest(method=key, api=api[key] if key in api else 'missing'):
                        self.assertIn(key, api)
                        fields = {int(field) for _, field, _, _ in string.Formatter().parse(api[key]) if field is not None and field.isdigit()}
                        self.assertEqual(fields, set(range(expected)))

    def test_type_information_is_marked_for_installed_editors(self):
        self.assertTrue(files('fabricpy').joinpath('py.typed').is_file())
        self.assertTrue(files('fabricpy').joinpath('context.py').is_file())

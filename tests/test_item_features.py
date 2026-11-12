"""Validate authoring errors before generating invalid or lossy native items."""
import unittest

import fabricpy as mc
from fabricpy.compiler import _validate
from fabricpy.compiler.item_features import effective_stack_size


class ItemFeatureValidationTests(unittest.TestCase):
    def make_item(self):
        mod = mc.Mod('features', 'Features')
        @mod.register
        class Bag(mc.Item):
            item_id = 'bag'
            inventory_size = 9
        return mod, Bag

    def test_storage_defaults_to_one_item_and_rejects_explicit_stack_size(self):
        mod, item = self.make_item()
        self.assertEqual(effective_stack_size(item), 1)
        _validate(mod)
        item.max_stack_size = 16
        with self.assertRaisesRegex(ValueError, 'unstackable'):
            _validate(mod)

    def test_rejects_invalid_slot_sizes_and_gui_shapes(self):
        for size in (-1, 55, True, 9.5):
            mod, item = self.make_item()
            item.inventory_size = size
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'inventory_size'):
                _validate(mod)
        mod, item = self.make_item()
        item.inventory_size = 5
        item.open_inventory_on_use = True
        with self.assertRaisesRegex(ValueError, 'open_inventory_on_use'):
            _validate(mod)

    def test_rejects_ambiguous_or_missing_automatic_screen(self):
        mod, item = self.make_item()
        item.open_screen_on_use = 'missing'
        with self.assertRaisesRegex(ValueError, 'unknown screen'):
            _validate(mod)
        mod.screen('panel', 'Panel')
        item.open_screen_on_use = 'panel'
        _validate(mod)
        item.open_inventory_on_use = True
        with self.assertRaisesRegex(ValueError, 'choose one automatic screen'):
            _validate(mod)

    def test_rejects_attachment_proxy_registry_collision(self):
        mod, item = self.make_item()
        item.attachment_slots = ('scope',)
        @mod.register
        class Collision(mc.Item):
            item_id = 'bag__base'
        with self.assertRaisesRegex(ValueError, 'reserved attachment proxy ID'):
            _validate(mod)

    def test_rejects_unsupported_targets_and_music_storage_combination(self):
        mod, item = self.make_item()
        mod.minecraft_version = '1.21.5'
        with self.assertRaisesRegex(ValueError, 'item storage currently supports'):
            _validate(mod)
        mod = mc.Mod('features', 'Features')
        @mod.register
        class Disc(mc.MusicDisc):
            item_id = 'disc'
            sound = 'minecraft:music_disc.cat'
            inventory_size = 9
        with self.assertRaisesRegex(ValueError, 'MusicDisc cannot also own'):
            _validate(mod)

    def test_rejects_disc_automatic_screen_that_would_hide_native_use(self):
        mod = mc.Mod('features', 'Features')
        mod.screen('panel', 'Panel')
        @mod.register
        class Disc(mc.MusicDisc):
            item_id = 'disc'
            sound = 'minecraft:music_disc.cat'
            open_screen_on_use = 'panel'
        with self.assertRaisesRegex(ValueError, 'cannot override native use'):
            _validate(mod)

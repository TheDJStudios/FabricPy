import json
import math
from pathlib import Path
import unittest

import fabricpy as mc
from fabricpy.music_disc import MusicDisc
from fabricpy.compiler.music_discs import (
    music_disc_init_statement, sound_id, validate_music_disc,
    write_music_disc_class, write_music_disc_resources,
)
from tests.support import project_dir


class MusicDiscTests(unittest.TestCase):
    def disc_mod(self, version='1.20.1', loader='fabric'):
        mod = mc.Mod('example', 'Example', minecraft_version=version, loader=loader)
        @mod.register
        class Song(MusicDisc):
            item_id = 'song'
            sound = 'music/song'
            length_seconds = 180
            comparator_output = 7
            artist = 'Python Artist'
            title = 'A Song'
        return mod, Song

    def test_native_120_disc_types_and_sound_registration(self):
        for loader in ('fabric', 'quilt', 'forge'):
            with self.subTest(loader=loader), project_dir() as root:
                mod, item = self.disc_mod(loader=loader)
                item_dir = root / 'java/item'
                self.assertTrue(write_music_disc_class(mod, item, item_dir, 'com.example', loader))
                source = (item_dir / 'Song.java').read_text()
                self.assertIn('extends MusicDiscItem' if loader in {'fabric', 'quilt'} else 'extends RecordItem', source)
                self.assertIn('super(7, com.example.ModMusicDiscSounds.SOUND_0', source)
                self.assertIn('180);', source)
                self.assertNotIn('public InteractionResult', source)
                registry = (root / 'java/ModMusicDiscSounds.java').read_text()
                if loader in {'fabric', 'quilt'}:
                    self.assertIn('Registry.register(Registries.SOUND_EVENT', registry)
                    self.assertEqual(music_disc_init_statement(mod, loader), 'ModMusicDiscSounds.register();')
                else:
                    self.assertIn('DeferredRegister.create(Registries.SOUND_EVENT', registry)
                    self.assertIn('SOUNDS.register(bus)', registry)
                    self.assertEqual(music_disc_init_statement(mod, loader), 'ModMusicDiscSounds.register(bus);')

    def test_modern_native_component_and_song_data(self):
        for loader in ('fabric', 'forge', 'neoforge'):
            with self.subTest(loader=loader), project_dir() as root:
                mod, item = self.disc_mod('1.21.1', loader)
                write_music_disc_class(mod, item, root / 'java/item', 'com.example', loader)
                source = (root / 'java/item/Song.java').read_text()
                self.assertIn('extends Item', source)
                self.assertIn('.jukeboxPlayable(', source)
                self.assertIn('RegistryKeys.JUKEBOX_SONG' if loader == 'fabric' else 'Registries.JUKEBOX_SONG', source)
                self.assertNotIn('extends RecordItem', source)
                write_music_disc_resources(mod, root / 'resources')
                data = json.loads((root / 'resources/data/example/jukebox_song/song.json').read_text())
                self.assertEqual(data['sound_event'], 'example:music/song')
                self.assertEqual(data['length_in_seconds'], 180.0)
                self.assertEqual(data['comparator_output'], 7)
                self.assertFalse((root / 'resources/data/minecraft/tags/items/music_discs.json').exists())

    def test_streaming_description_tag_and_resource_merge(self):
        with project_dir() as root:
            mod, item = self.disc_mod()
            assets = root / 'assets/example'
            assets.mkdir(parents=True)
            (assets / 'sounds.json').write_text(json.dumps({'other': {'sounds': ['example:other']}, 'music/song': {'subtitle': 'custom.subtitle', 'sounds': ['example:music/alternate']}}))
            (assets / 'lang').mkdir()
            (assets / 'lang/en_us.json').write_text('{"existing":"Keep"}')
            tag = root / 'data/minecraft/tags/items/music_discs.json'
            tag.parent.mkdir(parents=True)
            tag.write_text('{"replace":false,"values":["other:disc"]}')
            write_music_disc_resources(mod, root)
            write_music_disc_resources(mod, root)
            sounds = json.loads((assets / 'sounds.json').read_text())
            self.assertEqual(sounds['other']['sounds'], ['example:other'])
            self.assertEqual(sounds['music/song']['sounds'], [{'name': 'example:music/alternate', 'stream': True}])
            self.assertEqual(sounds['music/song']['subtitle'], 'custom.subtitle')
            lang = json.loads((assets / 'lang/en_us.json').read_text())
            self.assertEqual(lang['existing'], 'Keep')
            self.assertEqual(lang['item.example.song.desc'], 'Python Artist - A Song')
            self.assertEqual(json.loads(tag.read_text())['values'], ['other:disc', 'example:song'])

    def test_shared_sound_event_is_registered_once(self):
        with project_dir() as root:
            mod, item = self.disc_mod()
            @mod.register
            class SongTwo(MusicDisc):
                item_id = 'song_two'
                sound = 'music/song'
            write_music_disc_class(mod, item, root / 'java/item', 'com.example', 'fabric')
            registry = (root / 'java/ModMusicDiscSounds.java').read_text()
            self.assertEqual(registry.count('Registry.register('), 1)
            self.assertNotIn('SOUND_1', registry)

    def test_existing_namespaced_sound_is_not_reregistered(self):
        with project_dir() as root:
            mod, item = self.disc_mod()
            item.sound = 'minecraft:music_disc.cat'
            write_music_disc_class(mod, item, root / 'java/item', 'com.example', 'fabric')
            registry = (root / 'java/ModMusicDiscSounds.java').read_text()
            self.assertNotIn('Registry.register(', registry)
            write_music_disc_resources(mod, root / 'resources')
            self.assertEqual(json.loads((root / 'resources/assets/example/sounds.json').read_text()), {})

    def test_validation_rejects_invalid_values_and_native_hook_overrides(self):
        for field, value in (
            ('sound', ''), ('sound', '../song'), ('sound', 'UPPER/song'),
            ('length_seconds', 0), ('length_seconds', math.nan), ('length_seconds', True),
            ('comparator_output', 16), ('comparator_output', -1), ('comparator_output', True),
            ('max_stack_size', 64), ('max_damage', 5),
        ):
            with self.subTest(field=field, value=value):
                mod, item = self.disc_mod()
                setattr(item, field, value)
                with self.assertRaises(ValueError):
                    validate_music_disc(mod, item)
        mod, item = self.disc_mod('1.21.8')
        with self.assertRaisesRegex(ValueError, 'currently supports'):
            validate_music_disc(mod, item)
        mod, item = self.disc_mod()
        @mc.on_right_click
        def override(self, ctx):
            pass
        item._hooks = {'on_right_click': override}
        with self.assertRaisesRegex(ValueError, 'native jukebox'):
            validate_music_disc(mod, item)

    def test_ordinary_items_are_left_to_existing_generator(self):
        with project_dir() as root:
            mod = mc.Mod('example', 'Example')
            class Plain(mc.Item):
                item_id = 'plain'
            self.assertFalse(write_music_disc_class(mod, Plain, root / 'java/item', 'com.example', 'fabric'))
            self.assertFalse((root / 'java').exists())
            self.assertEqual(music_disc_init_statement(mod, 'fabric'), '')

    def test_ogg_suffix_is_a_convenience_not_part_of_sound_id(self):
        mod, item = self.disc_mod()
        item.sound = 'music/song.ogg'
        self.assertEqual(sound_id(mod, item), 'example:music/song')

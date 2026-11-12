import re
import unittest

import fabricpy as mc
from fabricpy.compiler.forge_gen import generate_forge_project
from fabricpy.compiler.neoforge_gen import generate_neoforge_project
from tests.support import project_dir


def matching_brace(text, opening):
    depth = 1
    for index in range(opening + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if not depth:
            return index
    raise AssertionError('Unclosed Java brace')


class ForgeHookSidesTests(unittest.TestCase):
    def test_callback_sides_preserve_vanilla_methods_for_forge_and_neoforge(self):
        for loader, version, generator in (
            ('forge', '1.20.1', generate_forge_project),
            ('neoforge', '1.21.1', generate_neoforge_project),
        ):
            for side in ('server', 'client', 'both'):
                with self.subTest(loader=loader, side=side), project_dir() as root:
                    mod = mc.Mod('example', 'Example', loader=loader, minecraft_version=version)
                    @mod.register
                    class TestBlock(mc.Block):
                        block_id = 'test_block'
                        @mc.on_use(side=side)
                        def interact(self, ctx):
                            ctx.player.send_message('used')
                        @mc.on_place(side=side)
                        def placed(self, ctx):
                            ctx.player.send_message('placed')
                        @mc.on_break(side=side)
                        def broken(self, ctx):
                            ctx.player.send_message('broken')
                    @mod.register
                    class TestItem(mc.Item):
                        item_id = 'test_item'
                        @mc.on_right_click(side=side)
                        def clicked(self, ctx):
                            ctx.player.send_message('clicked')
                    generator(mod, root / 'generated')
                    java = root / 'generated/src/main/java/com/generated/example'
                    block = (java / 'block/TestBlock.java').read_text()
                    item = (java / 'item/TestItem.java').read_text()
                    for source, marker in ((block, 'used'), (block, 'placed'), (block, 'broken'), (item, 'clicked')):
                        marker_at = source.index('"' + marker + '"')
                        if side == 'both':
                            self.assertNotIn('if (!level.isClientSide)', source)
                            self.assertNotIn('if (level.isClientSide)', source)
                            continue
                        guards = list(re.finditer(r'if\s*\([^\n]*level\.isClientSide[^\n]*\)\s*\{', source[:marker_at]))
                        self.assertTrue(guards, marker)
                        guard = guards[-1]
                        self.assertEqual('!' in guard.group(), side == 'server')
                        closing = matching_brace(source, source.index('{', guard.start()))
                        self.assertLess(marker_at, closing)
                        if marker == 'broken':
                            self.assertGreater(source.index('super.playerDestroy('), closing)
                        elif marker in {'used', 'clicked'}:
                            self.assertIn('return ', source[closing:])
                    self.assertIn('super.playerDestroy(level, player, pos, state, te, stack);', block)
                    self.assertIn('return InteractionResultHolder.success(stack);', item)
                    if loader == 'neoforge':
                        self.assertIn('useWithoutItem(', block)
                        self.assertIn('return net.minecraft.world.ItemInteractionResult.SUCCESS;', block)
                    else:
                        self.assertIn('return InteractionResult.SUCCESS;', block)

    def test_default_bare_decorators_are_server_guarded(self):
        with project_dir() as root:
            mod = mc.Mod('example', 'Example')
            @mod.register
            class TestBlock(mc.Block):
                block_id = 'test_block'
                @mc.on_place
                def placed(self, ctx):
                    ctx.player.send_message('placed')
            generate_forge_project(mod, root / 'generated')
            source = (root / 'generated/src/main/java/com/generated/example/block/TestBlock.java').read_text()
            self.assertRegex(source, r'if\s*\([^\n]*!.*level\.isClientSide[^\n]*\)')

    def test_global_event_classes_use_one_explicit_registration_path(self):
        with project_dir() as root:
            mod = mc.Mod('example', 'Example')
            @mod.event('player_join')
            def joined(ctx):
                ctx.player.send_message('joined')
            @mod.command('hello')
            def hello(ctx):
                ctx.source.send_message('hello')
            generate_forge_project(mod, root / 'generated')
            java = root / 'generated/src/main/java/com/generated/example'
            main = (java / 'Example.java').read_text()
            self.assertEqual(main.count('MinecraftForge.EVENT_BUS.register(ModEvents.class)'), 1)
            self.assertEqual(main.count('MinecraftForge.EVENT_BUS.register(ModCommands.class)'), 1)
            for file in (java / 'event/ModEvents.java', java / 'command/ModCommands.java'):
                self.assertNotIn('@Mod.EventBusSubscriber', file.read_text())
                self.assertIn('@SubscribeEvent', file.read_text())

    def test_global_interaction_bodies_respect_side_without_discarding_hands(self):
        for side in ('server', 'client', 'both'):
            with self.subTest(side=side), project_dir() as root:
                mod = mc.Mod('example', 'Example')
                @mod.event('player_use_item', side=side)
                def use_item(ctx):
                    ctx.player.send_message('use_item')
                @mod.event('player_use_block', side=side)
                def use_block(ctx):
                    ctx.player.send_message('use_block')
                @mod.event('player_attack_entity', side=side)
                def attack_entity(ctx):
                    ctx.player.send_message('attack_entity')
                @mod.event('player_interact_entity', side=side)
                def interact_entity(ctx):
                    ctx.player.send_message('interact_entity')
                generate_forge_project(mod, root / 'generated')
                source = (root / 'generated/src/main/java/com/generated/example/event/ModEvents.java').read_text()
                expected = 0 if side == 'both' else 4
                self.assertEqual(source.count('if (!level.isClientSide)'), expected if side == 'server' else 0)
                self.assertEqual(source.count('if (level.isClientSide)'), expected if side == 'client' else 0)
                self.assertNotIn('event.getHand() != InteractionHand.MAIN_HAND', source)

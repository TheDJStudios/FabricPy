"""Execute generated overrides against both logical sides of one action."""
import shutil
import subprocess
import unittest
from pathlib import Path

import fabricpy as mc
from fabricpy.compiler.fabric_gen import generate_fabric_project
from fabricpy.compiler.forge_gen import generate_forge_project
from fabricpy.compiler.neoforge_gen import generate_neoforge_project
from fabricpy.compiler.quilt_gen import generate_quilt_project
from tests.support import project_dir


def java_method(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    cursor = opening + 1
    while depth:
        depth += (source[cursor] == '{') - (source[cursor] == '}')
        cursor += 1
    return source[start:cursor]


class HookSideTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_one_action_on_client_and_server_executes_callback_on_selected_side(self):
        targets = [
            ('fabric', '1.20.1', generate_fabric_project),
            ('quilt', '1.20.1', generate_quilt_project),
            ('forge', '1.20.1', generate_forge_project),
            ('neoforge', '1.21.1', generate_neoforge_project),
        ]
        with project_dir() as root:
            for loader, version, generator in targets:
                for side in ('server', 'client', 'both'):
                    with self.subTest(loader=loader, side=side):
                        mod = mc.Mod('example', 'Example', minecraft_version=version, loader=loader)
                        @mod.register
                        class TestBlock(mc.Block):
                            block_id = 'test_block'
                            @mc.on_use(side=side)
                            def interact(self, ctx):
                                dep.fixture.test.Counter.record(ctx.world.is_client())
                            @mc.on_place(side=side)
                            def placed(self, ctx):
                                dep.fixture.test.Counter.record(ctx.world.is_client())
                            @mc.on_break(side=side)
                            def broken(self, ctx):
                                dep.fixture.test.Counter.record(ctx.world.is_client())
                        @mod.register
                        class TestItem(mc.Item):
                            item_id = 'test_item'
                            @mc.on_right_click(side=side)
                            def use(self, ctx):
                                dep.fixture.test.Counter.record(ctx.world.is_client())
                        project = root / f'{loader}-{side}'
                        generator(mod, project)
                        java = project / 'src/main/java/com/generated/example'
                        block = (java / 'block/TestBlock.java').read_text()
                        item = (java / 'item/TestItem.java').read_text()
                        fabric = loader in {'fabric', 'quilt'}
                        methods = [java_method(block, 'public void onPlaced' if fabric else 'public void setPlacedBy'),
                                   java_method(block, 'public void onBreak' if fabric else 'public void playerDestroy')]
                        if loader == 'neoforge':
                            methods.extend([java_method(block, 'public net.minecraft.world.ItemInteractionResult useItemOn'),
                                            java_method(block, 'public InteractionResult useWithoutItem')])
                        else:
                            methods.append(java_method(block, 'public ActionResult onUse' if fabric else 'public InteractionResult use('))
                        item_method = java_method(item, 'public TypedActionResult<ItemStack> use' if fabric else 'public InteractionResultHolder<ItemStack> use')
                        # Keep all method bodies exactly as generated, adapting only the fully-qualified
                        # NeoForge enum type to the equivalent isolated harness type.
                        methods = [value.replace('net.minecraft.world.ItemInteractionResult', 'ItemInteractionResult') for value in methods]
                        world, hand = ('World', 'Hand.MAIN_HAND') if fabric else ('Level', 'InteractionHand.MAIN_HAND')
                        calls = [
                            'block.onPlaced(world, pos, state, player, stack)' if fabric else 'block.setPlacedBy(world, pos, state, player, stack)',
                            'block.onBreak(world, pos, state, player)' if fabric else 'block.playerDestroy(world, player, pos, state, null, stack)',
                            f'block.onUse(state, world, pos, player, {hand}, hit)' if fabric else (
                                f'block.useItemOn(stack, state, world, pos, player, {hand}, hit)' if loader == 'neoforge' else f'block.use(state, world, pos, player, {hand}, hit)'),
                            f'item.use(world, player, {hand})',
                        ]
                        if loader == 'neoforge':
                            calls.append('block.useWithoutItem(state, world, pos, player, hit)')
                        checks = []
                        expected_client, expected_server = int(side != 'server'), int(side != 'client')
                        for call in calls:
                            checks.append(f'Counter.client = Counter.server = 0; world.isClient = world.isClientSide = true; {call}; world.isClient = world.isClientSide = false; {call}; if (Counter.client != {expected_client} || Counter.server != {expected_server}) throw new AssertionError("{loader}/{side}: " + Counter.client + "/" + Counter.server);')
                        checks.append('if (Counter.base != 2) throw new AssertionError("super break must run on both sides");')
                        harness = '''package test;
class Counter { static int client, server, base; static void record(boolean isClient) { if (isClient) client++; else server++; } }
@interface Nullable {}
class BlockState {} class BlockPos {} class ItemStack {} class BlockEntity {} class BlockHitResult {}
enum Hand { MAIN_HAND } enum InteractionHand { MAIN_HAND }
class World { boolean isClient, isClientSide; boolean isClient() { return isClient; } boolean isClientSide() { return isClientSide; } }
class Level extends World {}
class LivingEntity {}
class Player extends LivingEntity { ItemStack getItemInHand(InteractionHand hand) { return new ItemStack(); } ItemStack getMainHandItem() { return new ItemStack(); } BlockPos blockPosition() { return new BlockPos(); } }
class PlayerEntity extends Player { ItemStack getStackInHand(Hand hand) { return new ItemStack(); } BlockPos getBlockPos() { return new BlockPos(); } }
enum ActionResult { SUCCESS }
enum InteractionResult { SUCCESS }
enum ItemInteractionResult { SUCCESS; InteractionResult result() { return InteractionResult.SUCCESS; } }
class TypedActionResult<T> { static <T> TypedActionResult<T> success(T stack) { return new TypedActionResult<>(); } }
class InteractionResultHolder<T> { static <T> InteractionResultHolder<T> success(T stack) { return new InteractionResultHolder<>(); } }
class Base { public void onBreak(World world, BlockPos pos, BlockState state, PlayerEntity player) { Counter.base++; } public void playerDestroy(Level level, Player player, BlockPos pos, BlockState state, BlockEntity te, ItemStack stack) { Counter.base++; } }
'''
                        harness += 'class GeneratedBlock extends Base {\n' + '\n'.join(methods) + '\n}\n'
                        harness += 'class GeneratedItem {\n' + item_method + '\n}\n'
                        harness += f'''public class Harness {{ public static void main(String[] args) {{
                            {world} world = new {world}(); PlayerEntity player = new PlayerEntity();
                            BlockPos pos = new BlockPos(); BlockState state = new BlockState(); ItemStack stack = new ItemStack(); BlockHitResult hit = new BlockHitResult();
                            GeneratedBlock block = new GeneratedBlock(); GeneratedItem item = new GeneratedItem();
                            {''.join(checks)}
                        }} }}'''
                        source = project / 'Harness.java'
                        source.write_text(harness)
                        result = subprocess.run(['javac', '-d', str(project), str(source)], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        subprocess.run(['java', '-cp', str(project), 'test.Harness'], check=True, capture_output=True, text=True)

    def test_plain_decorators_default_to_server_and_reject_invalid_sides(self):
        for decorator in (mc.on_use, mc.on_place, mc.on_break, mc.on_right_click):
            func = decorator(lambda ctx: None)
            self.assertEqual(func._fabricpy_hook_args['side'], 'server')
            with self.assertRaises(ValueError):
                decorator(side='wrong')

    def test_fabric_global_interactions_guard_effects_and_preserve_pass_result(self):
        for side, condition in ((None, "!world.isClient"), ("client", "world.isClient"), ("both", None)):
            with project_dir() as root:
                mod = mc.Mod("example", "Example")
                @mod.event("player_use_block", side=side)
                def interact(ctx):
                    if ctx.hand.is_main_hand():
                        ctx.player.send_message("Global interaction")
                generate_fabric_project(mod, root / "generated")
                source = (root / "generated/src/main/java/com/generated/example/event/ModEvents.java").read_text()
                self.assertIn("import net.minecraft.util.ActionResult;", source)
                self.assertIn("return ActionResult.PASS;", source)
                if condition:
                    self.assertIn(f"if ({condition})", source)
                else:
                    self.assertNotIn("world.isClient", source)
                self.assertIn("hand == net.minecraft.util.Hand.MAIN_HAND", source)

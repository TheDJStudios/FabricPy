import unittest

import fabricpy as mc
from fabricpy.compiler.neoforge_gen import generate_neoforge_project, _rewrite_resource_locations
from tests.support import project_dir


class NeoForgeTests(unittest.TestCase):
    def test_121_registration_runtime_and_block_interactions_use_neoforge_apis(self):
        with project_dir() as root:
            mod = mc.Mod('example', 'Example', minecraft_version='1.21.1', loader='neoforge')
            @mod.register
            class Table(mc.Block):
                block_id = 'table'
                @mc.on_use
                def interact(self, ctx):
                    ctx.player.send_message('Hello')
            @mod.register
            class Token(mc.Item):
                item_id = 'token'
            project = root / 'generated'
            generate_neoforge_project(mod, project)
            java = project / 'src/main/java/com/generated/example'
            main = (java / 'Example.java').read_text()
            self.assertIn('public Example(IEventBus bus)', main)
            self.assertNotIn('FMLJavaModLoadingContext', main)
            registrations = (java / 'ModBlocks.java').read_text()
            self.assertIn('DeferredRegister.create(BuiltInRegistries.BLOCK', registrations)
            self.assertIn('Supplier<Block>', registrations)
            self.assertIn('event.accept(TABLE_ITEM.get())', registrations)
            self.assertNotIn('RegistryObject', registrations)
            block = (java / 'block/Table.java').read_text()
            self.assertIn('ItemInteractionResult useItemOn(ItemStack stack', block)
            self.assertIn('InteractionResult useWithoutItem(', block)
            self.assertIn('InteractionHand.MAIN_HAND, hit).result()', block)
            self.assertNotIn('public InteractionResult use(', block)
            runtime = (java / 'util/FabricPyRuntime.java').read_text()
            self.assertIn('BuiltInRegistries.PARTICLE_TYPE.get(', runtime)
            self.assertIn('ResourceLocation.parse(particleId)', runtime)
            self.assertIn('ClipContext.Fluid.NONE, (net.minecraft.world.entity.Entity) null', runtime)
            for source in java.rglob('*.java'):
                text = source.read_text()
                self.assertNotIn('ForgeRegistries', text)
                self.assertNotIn('new ResourceLocation(', text)
                self.assertNotIn('new net.minecraft.resources.ResourceLocation(', text)

    def test_resource_location_factories_preserve_nested_arguments(self):
        self.assertEqual(
            _rewrite_resource_locations('new ResourceLocation("example", getPath("a,b"))'),
            'ResourceLocation.fromNamespaceAndPath("example", getPath("a,b"))',
        )
        self.assertEqual(
            _rewrite_resource_locations('new net.minecraft.resources.ResourceLocation(choose("a,b"))'),
            'net.minecraft.resources.ResourceLocation.parse(choose("a,b"))',
        )

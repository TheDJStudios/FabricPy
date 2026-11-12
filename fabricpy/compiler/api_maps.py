"""
API mapping tables: Python ctx.* calls → Java method calls.

The transpiler looks up "ctx.player.send_message" etc. and substitutes
the Java equivalent. {0}, {1} are positional args; named kwargs are also supported.

Fabric targets MC 1.20.1 / Fabric API 0.91+
Forge targets MC 1.20.1 / Forge 47+
"""

# ── Fabric API map ────────────────────────────────────────────────────────── #

FABRIC_API_MAP: dict[str, str] = {
    # Player
    "ctx.player":
        'player',
    "ctx.player.send_message":
        'player.sendMessage(Text.literal({0}), false)',
    "ctx.player.send_action_bar":
        'player.sendMessage(Text.literal({0}), true)',
    "ctx.player.teleport":
        '((ServerPlayerEntity)player).teleport((ServerWorld)world, {0}, {1}, {2}, Set.of(), player.getYaw(), player.getPitch())',
    "ctx.player.teleport_dimension":
        'player.getServer().getCommandManager().executeWithPrefix(player.getCommandSource().withSilent(), "execute in " + {0} + " run tp " + player.getName().getString() + " " + {1} + " " + {2} + " " + {3})',
    "ctx.player.give_item":
        'player.giveItemStack(new ItemStack(Registries.ITEM.get(new Identifier({0})), {1}))',
    "ctx.player.remove_item":
        'player.getServer().getCommandManager().executeWithPrefix(player.getCommandSource().withSilent(), "clear " + player.getName().getString() + " " + {0} + " " + ((int)({1})))',
    "ctx.player.get_health":
        'player.getHealth()',
    "ctx.player.set_health":
        'player.setHealth({0})',
    "ctx.player.is_creative":
        'player.isCreative()',
    "ctx.player.is_sneaking":
        'player.isSneaking()',
    "ctx.player.is_sprinting":
        'player.isSprinting()',
    "ctx.player.get_name":
        'player.getName().getString()',
    "ctx.player.set_on_fire":
        'player.setFireTicks((int)({0} * 20))',
    "ctx.player.heal":
        'player.heal({0})',
    "ctx.player.damage":
        'player.damage(world.getDamageSources().generic(), {0})',
    "ctx.player.add_effect":
        'player.addStatusEffect(new StatusEffectInstance(Registries.STATUS_EFFECT.get(new Identifier(({0}).contains(":") ? {0} : "minecraft:" + ({0}).toLowerCase())), {1} * 20, {2}))',
    "ctx.player.remove_effect":
        'player.removeStatusEffect(Registries.STATUS_EFFECT.get(new Identifier(({0}).contains(":") ? {0} : "minecraft:" + ({0}).toLowerCase())))',
    "ctx.player.clear_effects":
        'player.clearStatusEffects()',
    "ctx.player.get_hunger":
        'player.getHungerManager().getFoodLevel()',
    "ctx.player.set_hunger":
        'player.getHungerManager().setFoodLevel((int)({0}))',
    "ctx.player.get_saturation":
        'player.getHungerManager().getSaturationLevel()',
    "ctx.player.set_saturation":
        'player.getHungerManager().setSaturationLevel((float)({0}))',
    "ctx.player.add_experience":
        'player.addExperience((int)({0}))',
    "ctx.player.kill":
        'player.kill()',
    "ctx.player.get_pos_x":
        'player.getX()',
    "ctx.player.get_pos_y":
        'player.getY()',
    "ctx.player.get_pos_z":
        'player.getZ()',
    "ctx.player.get_main_hand_item_id":
        'Registries.ITEM.getId(player.getMainHandStack().getItem()).toString()',
    "ctx.player.get_main_hand_count":
        'player.getMainHandStack().getCount()',
    "ctx.player.get_offhand_item_id":
        'Registries.ITEM.getId(player.getOffHandStack().getItem()).toString()',
    "ctx.player.get_offhand_count":
        'player.getOffHandStack().getCount()',
    "ctx.player.consume_main_hand_item":
        'player.getMainHandStack().decrement((int)({0}))',
    "ctx.player.set_main_hand_item":
        'player.setStackInHand(Hand.MAIN_HAND, new ItemStack(Registries.ITEM.get(new Identifier({0})), (int)({1})))',
    "ctx.player.has_item":
        '(player.getInventory().main.stream().anyMatch(s -> s.isOf(Registries.ITEM.get(new Identifier({0})))) || player.getOffHandStack().isOf(Registries.ITEM.get(new Identifier({0}))))',
    "ctx.player.count_item":
        '(player.getInventory().main.stream().filter(s -> s.isOf(Registries.ITEM.get(new Identifier({0})))).mapToInt(ItemStack::getCount).sum() + (player.getOffHandStack().isOf(Registries.ITEM.get(new Identifier({0}))) ? player.getOffHandStack().getCount() : 0))',
    "ctx.player.has_advancement":
        '(((ServerPlayerEntity)player).getServer().getAdvancementLoader().get(new Identifier({0})) != null && ((ServerPlayerEntity)player).getAdvancementTracker().getProgress(((ServerPlayerEntity)player).getServer().getAdvancementLoader().get(new Identifier({0}))).isDone())',
    "ctx.player.has_advancment":
        '(((ServerPlayerEntity)player).getServer().getAdvancementLoader().get(new Identifier({0})) != null && ((ServerPlayerEntity)player).getAdvancementTracker().getProgress(((ServerPlayerEntity)player).getServer().getAdvancementLoader().get(new Identifier({0}))).isDone())',
    "ctx.player.add_cooldown":
        'player.getItemCooldownManager().set(Registries.ITEM.get(new Identifier({0})), (int)({1}))',

    # World
    "ctx.world":
        'world',
    "ctx.world.is_client":
        'world.isClient()',
    "ctx.world.play_sound":
        'Registries.SOUND_EVENT.getOrEmpty(new Identifier({0})).ifPresent(s -> world.playSound(null, soundPos, s, SoundCategory.BLOCKS, {1}, {2}))',
    "ctx.world.explode":
        'world.createExplosion(null, {0}, {1}, {2}, {3}, false, World.ExplosionSourceType.NONE)',
    "ctx.world.set_block":
        'world.setBlockState(new BlockPos((int){0}, (int){1}, (int){2}), Registries.BLOCK.get(new Identifier({3})).getDefaultState())',
    "ctx.world.set_block_self":
        'world.setBlockState(pos, Registries.BLOCK.get(new Identifier({0})).getDefaultState())',
    "ctx.world.break_block":
        'world.breakBlock(new BlockPos((int){0}, (int){1}, (int){2}), {3})',
    "ctx.world.break_self":
        'world.breakBlock(pos, {0})',
    "ctx.world.get_block_id":
        'Registries.BLOCK.getId(world.getBlockState(new BlockPos((int){0}, (int){1}, (int){2})).getBlock()).toString()',
    "ctx.world.get_self_block_id":
        'Registries.BLOCK.getId(world.getBlockState(pos).getBlock()).toString()',
    "ctx.world.is_air":
        'world.isAir(new BlockPos((int){0}, (int){1}, (int){2}))',
    "ctx.world.is_self_air":
        'world.isAir(pos)',
    "ctx.world.set_block_in_dimension":
        'world.getServer().getCommandManager().executeWithPrefix(world.getServer().getCommandSource().withSilent(), "execute in " + {0} + " run setblock " + ((int)({1})) + " " + ((int)({2})) + " " + ((int)({3})) + " " + {4})',
    "ctx.world.fill_in_dimension":
        'world.getServer().getCommandManager().executeWithPrefix(world.getServer().getCommandSource().withSilent(), "execute in " + {0} + " run fill " + ((int)({1})) + " " + ((int)({2})) + " " + ((int)({3})) + " " + ((int)({4})) + " " + ((int)({5})) + " " + ((int)({6})) + " " + {7} + ({8} != null ? " " + {8} : ""))',
    "ctx.world.place_structure":
        'world.getServer().getCommandManager().executeWithPrefix(world.getServer().getCommandSource().withSilent(), "execute in " + {0} + " run place template " + {1} + " " + ((int)({2})) + " " + ((int)({3})) + " " + ((int)({4})))',
    "ctx.world.place_nbt":
        'world.getServer().getCommandManager().executeWithPrefix(world.getServer().getCommandSource().withSilent(), "execute in " + {0} + " run place template " + {1} + " " + ((int)({2})) + " " + ((int)({3})) + " " + ((int)({4})))',
    "ctx.world.spawn_entity":
        'world.getServer().getCommandManager().executeWithPrefix(world.getServer().getCommandSource().withSilent(), "summon " + {0} + " " + {1} + " " + {2} + " " + {3})',
    "ctx.world.get_time":
        'world.getTime()',
    "ctx.world.is_day":
        '(world.getTimeOfDay() % 24000L < 13000L)',
    "ctx.world.is_raining":
        'world.isRaining()',
    "ctx.world.get_dimension":
        'world.getRegistryKey().getValue().toString()',
    "ctx.world.spawn_lightning":
        'world.spawnEntity(new LightningEntity(EntityType.LIGHTNING_BOLT, world))',
    "ctx.client":
        'client',
    "ctx.keybind":
        'keybind',

    # Context values
    "ctx.pos":
        'pos',
    "ctx.state":
        'state',
    "ctx.hand":
        'hand',
    "ctx.hand.is_main_hand":
        '(hand == net.minecraft.util.Hand.MAIN_HAND)',
    "ctx.hand.is_off_hand":
        '(hand == net.minecraft.util.Hand.OFF_HAND)',
    "ctx.stack":
        'stack',
    "ctx.stack.get_item_id":
        'Registries.ITEM.getId(stack.getItem()).toString()',
    "ctx.stack.get_count":
        'stack.getCount()',
    "ctx.stack.get_texture":
        '(stack.hasNbt() && stack.getNbt().contains("fabricpy_texture") ? stack.getNbt().getString("fabricpy_texture") : "")',
    "ctx.stack.texture_change":
        'stack.getOrCreateNbt().putString("fabricpy_texture", {0})',
    "ctx.stack.get_model":
        '(stack.hasNbt() && stack.getNbt().contains("fabricpy_model") ? stack.getNbt().getString("fabricpy_model") : "")',
    "ctx.stack.model_change":
        'stack.getOrCreateNbt().putString("fabricpy_model", {0})',
    "ctx.stack.decrement":
        'stack.decrement((int)({0}))',
    "ctx.stack.increment":
        'stack.increment((int)({0}))',
    "ctx.stack.is_of":
        'stack.isOf(Registries.ITEM.get(new Identifier({0})))',
    "ctx.message":
        'message',
    "ctx.entity":
        'entity',
    "ctx.entity.get_pos_x":
        'entity.getX()',
    "ctx.entity.get_pos_y":
        'entity.getY()',
    "ctx.entity.get_pos_z":
        'entity.getZ()',
    "ctx.entity.teleport":
        'entity.refreshPositionAndAngles({0}, {1}, {2}, entity.getYaw(), entity.getPitch())',
    "ctx.entity.discard":
        'entity.discard()',
    "ctx.entity.set_on_fire":
        'entity.setFireTicks((int)({0} * 20))',
    "ctx.entity.damage":
        'entity.damage(world.getDamageSources().generic(), {0})',
    "ctx.entity.get_animation":
        'entity.getAnimationName()',
    "ctx.entity.play_animation":
        'entity.setAnimationState({0}, true)',
    "ctx.entity.play_animation_once":
        'entity.setAnimationState({0}, false)',
    "ctx.entity.stop_animation":
        'entity.clearAnimationName()',
    "ctx.entity.get_texture":
        'entity.getTextureOverride()',
    "ctx.entity.texture_change":
        'entity.setTextureOverride({0})',
    "ctx.entity.get_model":
        'entity.getModelOverride()',
    "ctx.entity.model_change":
        'entity.setModelOverride({0})',
    "ctx.block_entity":
        'blockEntity',
    "ctx.block_entity.mark_dirty":
        'blockEntity.markDirty()',
    "ctx.block_entity.get_string":
        'blockEntity.getStringData({0})',
    "ctx.block_entity.get_animation":
        'blockEntity.getAnimationName()',
    "ctx.block_entity.play_animation":
        'blockEntity.setAnimationState({0}, true)',
    "ctx.block_entity.play_animation_once":
        'blockEntity.setAnimationState({0}, false)',
    "ctx.block_entity.stop_animation":
        'blockEntity.clearAnimationName()',
    "ctx.block_entity.get_texture":
        'blockEntity.getStringData("__fabricpy_texture")',
    "ctx.block_entity.texture_change":
        'blockEntity.setStringData("__fabricpy_texture", {0})',
    "ctx.block_entity.get_model":
        'blockEntity.getStringData("__fabricpy_model")',
    "ctx.block_entity.model_change":
        'blockEntity.setStringData("__fabricpy_model", {0})',
    "ctx.block_entity.set_string":
        'blockEntity.setStringData({0}, {1})',
    "ctx.block_entity.get_int":
        'blockEntity.getIntData({0})',
    "ctx.block_entity.set_int":
        'blockEntity.setIntData({0}, (int)({1}))',
    "ctx.block_entity.get_bool":
        'blockEntity.getBoolData({0})',
    "ctx.block_entity.set_bool":
        'blockEntity.setBoolData({0}, {1})',
    "ctx.block_entity.get_double":
        'blockEntity.getDoubleData({0})',
    "ctx.block_entity.set_double":
        'blockEntity.setDoubleData({0}, {1})',
    "ctx.block_entity.has":
        'blockEntity.hasData({0})',
    "ctx.block_entity.remove":
        'blockEntity.removeData({0})',
    "ctx.block_entity.sync":
        'blockEntity.syncData()',
    "ctx.server":
        'server',
    "ctx.server.run_command":
        'server.getCommandManager().executeWithPrefix(server.getCommandSource().withSilent(), {0})',
    "ctx.server.reload_data":
        'server.getCommandManager().executeWithPrefix(server.getCommandSource().withSilent(), "reload")',

    # Source (commands)
    "ctx.source":
        'context.getSource()',
    "ctx.source.send_message":
        'context.getSource().sendFeedback(() -> Text.literal({0}), false)',
    "ctx.source.get_player":
        'context.getSource().getPlayer()',
    "ctx.source.get_pos":
        'context.getSource().getPosition()',
    "ctx.source.run_command":
        'context.getSource().getServer().getCommandManager().executeWithPrefix(context.getSource().withSilent(), {0})',
}

# ── Required Java imports for Fabric ─────────────────────────────────────── #

FABRIC_EXTRA_IMPORTS: list[str] = [
    "import net.minecraft.text.Text;",
    "import net.minecraft.registry.Registries;",
    "import net.minecraft.util.Identifier;",
    "import net.minecraft.util.Hand;",
    "import net.minecraft.item.ItemStack;",
    "import net.minecraft.entity.effect.StatusEffectInstance;",
    "import net.minecraft.entity.effect.StatusEffects;",
    "import net.minecraft.sound.SoundCategory;",
    "import net.minecraft.sound.SoundEvents;",
    "import net.minecraft.server.network.ServerPlayerEntity;",
    "import net.minecraft.server.world.ServerWorld;",
    "import net.minecraft.world.World;",
    "import net.minecraft.util.math.BlockPos;",
    "import java.util.Set;",
]

# ── Forge API map ─────────────────────────────────────────────────────────── #

FORGE_API_MAP: dict[str, str] = {
    # Player
    "ctx.player":
        'player',
    "ctx.player.send_message":
        'player.sendSystemMessage(Component.literal({0}))',
    "ctx.player.send_action_bar":
        'player.displayClientMessage(Component.literal({0}), true)',
    "ctx.player.teleport":
        '((ServerPlayer)player).teleportTo((ServerLevel)level, {0}, {1}, {2}, player.getYRot(), player.getXRot())',
    "ctx.player.teleport_dimension":
        'player.getServer().getCommands().performPrefixedCommand(player.createCommandSourceStack().withSuppressedOutput(), "execute in " + {0} + " run tp " + player.getGameProfile().getName() + " " + {1} + " " + {2} + " " + {3})',
    "ctx.player.give_item":
        'player.addItem(new ItemStack(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0})), {1}))',
    "ctx.player.remove_item":
        'player.getServer().getCommands().performPrefixedCommand(player.createCommandSourceStack().withSuppressedOutput(), "clear " + player.getGameProfile().getName() + " " + {0} + " " + ((int)({1})))',
    "ctx.player.get_health":
        'player.getHealth()',
    "ctx.player.set_health":
        'player.setHealth({0})',
    "ctx.player.is_creative":
        'player.isCreative()',
    "ctx.player.is_sneaking":
        'player.isCrouching()',
    "ctx.player.is_sprinting":
        'player.isSprinting()',
    "ctx.player.get_name":
        'player.getName().getString()',
    "ctx.player.set_on_fire":
        'player.setRemainingFireTicks((int)({0} * 20))',
    "ctx.player.heal":
        'player.heal({0})',
    "ctx.player.damage":
        'player.hurt(level.damageSources().generic(), {0})',
    "ctx.player.add_effect":
        'player.addEffect(new MobEffectInstance(ForgeRegistries.MOB_EFFECTS.getValue(new ResourceLocation(({0}).contains(":") ? {0} : "minecraft:" + ({0}).toLowerCase())), {1} * 20, {2}))',
    "ctx.player.remove_effect":
        'player.removeEffect(ForgeRegistries.MOB_EFFECTS.getValue(new ResourceLocation(({0}).contains(":") ? {0} : "minecraft:" + ({0}).toLowerCase())))',
    "ctx.player.clear_effects":
        'player.removeAllEffects()',
    "ctx.player.get_hunger":
        'player.getFoodData().getFoodLevel()',
    "ctx.player.set_hunger":
        'player.getFoodData().setFoodLevel((int)({0}))',
    "ctx.player.get_saturation":
        'player.getFoodData().getSaturationLevel()',
    "ctx.player.set_saturation":
        'player.getFoodData().setSaturation((float)({0}))',
    "ctx.player.add_experience":
        'player.giveExperiencePoints((int)({0}))',
    "ctx.player.kill":
        'player.kill()',
    "ctx.player.get_pos_x":
        'player.getX()',
    "ctx.player.get_pos_y":
        'player.getY()',
    "ctx.player.get_pos_z":
        'player.getZ()',
    "ctx.player.get_main_hand_item_id":
        'ForgeRegistries.ITEMS.getKey(player.getMainHandItem().getItem()).toString()',
    "ctx.player.get_main_hand_count":
        'player.getMainHandItem().getCount()',
    "ctx.player.get_offhand_item_id":
        'ForgeRegistries.ITEMS.getKey(player.getOffhandItem().getItem()).toString()',
    "ctx.player.get_offhand_count":
        'player.getOffhandItem().getCount()',
    "ctx.player.consume_main_hand_item":
        'player.getMainHandItem().shrink((int)({0}))',
    "ctx.player.set_main_hand_item":
        'player.setItemInHand(InteractionHand.MAIN_HAND, new ItemStack(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0})), (int)({1})))',
    "ctx.player.has_item":
        '(player.getInventory().items.stream().anyMatch(s -> s.is(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0})))) || player.getOffhandItem().is(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0}))))',
    "ctx.player.count_item":
        '(player.getInventory().items.stream().filter(s -> s.is(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0})))).mapToInt(ItemStack::getCount).sum() + (player.getOffhandItem().is(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0}))) ? player.getOffhandItem().getCount() : 0))',
    "ctx.player.has_advancement":
        '(((ServerPlayer)player).getServer().getAdvancements().getAdvancement(new ResourceLocation({0})) != null && ((ServerPlayer)player).getAdvancements().getOrStartProgress(((ServerPlayer)player).getServer().getAdvancements().getAdvancement(new ResourceLocation({0}))).isDone())',
    "ctx.player.has_advancment":
        '(((ServerPlayer)player).getServer().getAdvancements().getAdvancement(new ResourceLocation({0})) != null && ((ServerPlayer)player).getAdvancements().getOrStartProgress(((ServerPlayer)player).getServer().getAdvancements().getAdvancement(new ResourceLocation({0}))).isDone())',
    "ctx.player.add_cooldown":
        'player.getCooldowns().addCooldown(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0})), (int)({1}))',

    # World (Forge calls it "level" not "world")
    "ctx.world":
        'level',
    "ctx.world.is_client":
        'level.isClientSide()',
    "ctx.world.play_sound":
        'level.playSound(null, soundPos, ForgeRegistries.SOUND_EVENTS.getValue(new ResourceLocation({0})), SoundSource.BLOCKS, {1}, {2})',
    "ctx.world.explode":
        'level.explode(null, {0}, {1}, {2}, {3}, false, Level.ExplosionInteraction.NONE)',
    "ctx.world.set_block":
        'level.setBlock(new BlockPos((int){0}, (int){1}, (int){2}), ForgeRegistries.BLOCKS.getValue(new ResourceLocation({3})).defaultBlockState(), 3)',
    "ctx.world.set_block_self":
        'level.setBlock(pos, ForgeRegistries.BLOCKS.getValue(new ResourceLocation({0})).defaultBlockState(), 3)',
    "ctx.world.break_block":
        'level.destroyBlock(new BlockPos((int){0}, (int){1}, (int){2}), {3})',
    "ctx.world.break_self":
        'level.destroyBlock(pos, {0})',
    "ctx.world.get_block_id":
        'ForgeRegistries.BLOCKS.getKey(level.getBlockState(new BlockPos((int){0}, (int){1}, (int){2})).getBlock()).toString()',
    "ctx.world.get_self_block_id":
        'ForgeRegistries.BLOCKS.getKey(level.getBlockState(pos).getBlock()).toString()',
    "ctx.world.is_air":
        'level.isEmptyBlock(new BlockPos((int){0}, (int){1}, (int){2}))',
    "ctx.world.is_self_air":
        'level.isEmptyBlock(pos)',
    "ctx.world.set_block_in_dimension":
        'level.getServer().getCommands().performPrefixedCommand(level.getServer().createCommandSourceStack().withSuppressedOutput(), "execute in " + {0} + " run setblock " + ((int)({1})) + " " + ((int)({2})) + " " + ((int)({3})) + " " + {4})',
    "ctx.world.fill_in_dimension":
        'level.getServer().getCommands().performPrefixedCommand(level.getServer().createCommandSourceStack().withSuppressedOutput(), "execute in " + {0} + " run fill " + ((int)({1})) + " " + ((int)({2})) + " " + ((int)({3})) + " " + ((int)({4})) + " " + ((int)({5})) + " " + ((int)({6})) + " " + {7} + ({8} != null ? " " + {8} : ""))',
    "ctx.world.place_structure":
        'level.getServer().getCommands().performPrefixedCommand(level.getServer().createCommandSourceStack().withSuppressedOutput(), "execute in " + {0} + " run place template " + {1} + " " + ((int)({2})) + " " + ((int)({3})) + " " + ((int)({4})))',
    "ctx.world.place_nbt":
        'level.getServer().getCommands().performPrefixedCommand(level.getServer().createCommandSourceStack().withSuppressedOutput(), "execute in " + {0} + " run place template " + {1} + " " + ((int)({2})) + " " + ((int)({3})) + " " + ((int)({4})))',
    "ctx.world.spawn_entity":
        'level.getServer().getCommands().performPrefixedCommand(level.getServer().createCommandSourceStack().withSuppressedOutput(), "summon " + {0} + " " + {1} + " " + {2} + " " + {3})',
    "ctx.world.get_time":
        'level.getGameTime()',
    "ctx.world.is_day":
        '(level.getDayTime() % 24000L < 13000L)',
    "ctx.world.is_raining":
        'level.isRaining()',
    "ctx.world.get_dimension":
        'level.dimension().location().toString()',
    "ctx.client":
        'client',
    "ctx.keybind":
        'keybind',

    # Context values
    "ctx.pos":
        'pos',
    "ctx.state":
        'state',
    "ctx.hand":
        'hand',
    "ctx.hand.is_main_hand":
        '(hand == net.minecraft.world.InteractionHand.MAIN_HAND)',
    "ctx.hand.is_off_hand":
        '(hand == net.minecraft.world.InteractionHand.OFF_HAND)',
    "ctx.stack":
        'stack',
    "ctx.stack.get_item_id":
        'ForgeRegistries.ITEMS.getKey(stack.getItem()).toString()',
    "ctx.stack.get_count":
        'stack.getCount()',
    "ctx.stack.get_texture":
        '(stack.hasTag() && stack.getTag().contains("fabricpy_texture") ? stack.getTag().getString("fabricpy_texture") : "")',
    "ctx.stack.texture_change":
        'stack.getOrCreateTag().putString("fabricpy_texture", {0})',
    "ctx.stack.get_model":
        '(stack.hasTag() && stack.getTag().contains("fabricpy_model") ? stack.getTag().getString("fabricpy_model") : "")',
    "ctx.stack.model_change":
        'stack.getOrCreateTag().putString("fabricpy_model", {0})',
    "ctx.stack.decrement":
        'stack.shrink((int)({0}))',
    "ctx.stack.increment":
        'stack.grow((int)({0}))',
    "ctx.stack.is_of":
        'stack.is(ForgeRegistries.ITEMS.getValue(new ResourceLocation({0})))',
    "ctx.message":
        'message',
    "ctx.entity":
        'entity',
    "ctx.entity.get_pos_x":
        'entity.getX()',
    "ctx.entity.get_pos_y":
        'entity.getY()',
    "ctx.entity.get_pos_z":
        'entity.getZ()',
    "ctx.entity.teleport":
        'entity.teleportTo({0}, {1}, {2})',
    "ctx.entity.discard":
        'entity.discard()',
    "ctx.entity.set_on_fire":
        'entity.setRemainingFireTicks((int)({0} * 20))',
    "ctx.entity.damage":
        'entity.hurt(level.damageSources().generic(), {0})',
    "ctx.entity.get_animation":
        'entity.getAnimationName()',
    "ctx.entity.play_animation":
        'entity.setAnimationState({0}, true)',
    "ctx.entity.play_animation_once":
        'entity.setAnimationState({0}, false)',
    "ctx.entity.stop_animation":
        'entity.clearAnimationName()',
    "ctx.entity.get_texture":
        'entity.getTextureOverride()',
    "ctx.entity.texture_change":
        'entity.setTextureOverride({0})',
    "ctx.entity.get_model":
        'entity.getModelOverride()',
    "ctx.entity.model_change":
        'entity.setModelOverride({0})',
    "ctx.block_entity":
        'blockEntity',
    "ctx.block_entity.mark_dirty":
        'blockEntity.setChanged()',
    "ctx.block_entity.get_string":
        'blockEntity.getStringData({0})',
    "ctx.block_entity.get_animation":
        'blockEntity.getAnimationName()',
    "ctx.block_entity.play_animation":
        'blockEntity.setAnimationState({0}, true)',
    "ctx.block_entity.play_animation_once":
        'blockEntity.setAnimationState({0}, false)',
    "ctx.block_entity.stop_animation":
        'blockEntity.clearAnimationName()',
    "ctx.block_entity.get_texture":
        'blockEntity.getStringData("__fabricpy_texture")',
    "ctx.block_entity.texture_change":
        'blockEntity.setStringData("__fabricpy_texture", {0})',
    "ctx.block_entity.get_model":
        'blockEntity.getStringData("__fabricpy_model")',
    "ctx.block_entity.model_change":
        'blockEntity.setStringData("__fabricpy_model", {0})',
    "ctx.block_entity.set_string":
        'blockEntity.setStringData({0}, {1})',
    "ctx.block_entity.get_int":
        'blockEntity.getIntData({0})',
    "ctx.block_entity.set_int":
        'blockEntity.setIntData({0}, (int)({1}))',
    "ctx.block_entity.get_bool":
        'blockEntity.getBoolData({0})',
    "ctx.block_entity.set_bool":
        'blockEntity.setBoolData({0}, {1})',
    "ctx.block_entity.get_double":
        'blockEntity.getDoubleData({0})',
    "ctx.block_entity.set_double":
        'blockEntity.setDoubleData({0}, {1})',
    "ctx.block_entity.has":
        'blockEntity.hasData({0})',
    "ctx.block_entity.remove":
        'blockEntity.removeData({0})',
    "ctx.block_entity.sync":
        'blockEntity.syncData()',
    "ctx.server":
        'server',
    "ctx.server.run_command":
        'server.getCommands().performPrefixedCommand(server.createCommandSourceStack().withSuppressedOutput(), {0})',
    "ctx.server.reload_data":
        'server.getCommands().performPrefixedCommand(server.createCommandSourceStack().withSuppressedOutput(), "reload")',

    # Source (commands)
    "ctx.source":
        'context.getSource()',
    "ctx.source.send_message":
        'context.getSource().sendSuccess(() -> Component.literal({0}), false)',
    "ctx.source.get_player":
        'context.getSource().getPlayerOrException()',
    "ctx.source.get_pos":
        'context.getSource().getPosition()',
    "ctx.source.run_command":
        'context.getSource().getServer().getCommands().performPrefixedCommand(context.getSource().withSuppressedOutput(), {0})',
}

# ── Required Java imports for Forge ──────────────────────────────────────── #

FORGE_EXTRA_IMPORTS: list[str] = [
    "import net.minecraft.network.chat.Component;",
    "import net.minecraft.resources.ResourceLocation;",
    "import net.minecraft.world.InteractionHand;",
    "import net.minecraft.world.item.ItemStack;",
    "import net.minecraft.world.effect.MobEffectInstance;",
    "import net.minecraft.world.effect.MobEffects;",
    "import net.minecraft.sounds.SoundSource;",
    "import net.minecraft.sounds.SoundEvents;",
    "import net.minecraft.server.level.ServerPlayer;",
    "import net.minecraft.server.level.ServerLevel;",
    "import net.minecraft.world.level.Level;",
    "import net.minecraft.core.BlockPos;",
    "import net.minecraftforge.registries.ForgeRegistries;",
]

# ── Event name mappings ───────────────────────────────────────────────────── #

FABRIC_EVENT_MAP: dict[str, dict] = {
    "player_join": {
        "import": "import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;",
        "register": "ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {{\n            ServerPlayerEntity player = handler.getPlayer();\n            ServerWorld world = player.getServerWorld();\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n        }});",
    },
    "player_leave": {
        "import": "import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;",
        "register": "ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> {{\n            ServerPlayerEntity player = handler.getPlayer();\n            ServerWorld world = player.getServerWorld();\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n        }});",
    },
    "server_start": {
        "import": "import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;",
        "register": "ServerLifecycleEvents.SERVER_STARTED.register((server) -> {{\n            {body}\n        }});",
    },
    "server_stop": {
        "import": "import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;",
        "register": "ServerLifecycleEvents.SERVER_STOPPING.register((server) -> {{\n            {body}\n        }});",
    },
    "server_tick": {
        "import": "import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;",
        "register": "ServerTickEvents.END_SERVER_TICK.register((server) -> {{\n            {body}\n        }});",
    },
    "block_break": {
        "import": "import net.fabricmc.fabric.api.event.player.PlayerBlockBreakEvents;",
        "register": "PlayerBlockBreakEvents.AFTER.register((world, player, pos, state, be) -> {{\n            var server = world.getServer();\n            BlockPos soundPos = pos;\n            {body}\n        }});",
    },
    "player_respawn": {
        "import": "import net.fabricmc.fabric.api.entity.event.v1.ServerPlayerEvents;",
        "register": "ServerPlayerEvents.AFTER_RESPAWN.register((oldPlayer, newPlayer, alive) -> {{\n            ServerPlayerEntity player = newPlayer;\n            var server = player.getServer();\n            ServerWorld world = player.getServerWorld();\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n        }});",
    },
    "player_death": {
        "import": "import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;",
        "register": "ServerLivingEntityEvents.AFTER_DEATH.register((entity, damageSource) -> {{\n            if (entity instanceof ServerPlayerEntity player) {{\n                var server = player.getServer();\n                ServerWorld world = player.getServerWorld();\n                BlockPos soundPos = player.getBlockPos();\n                {body}\n            }\n        }});",
    },
    "player_change_dimension": {
        "import": "import net.fabricmc.fabric.api.entity.event.v1.ServerEntityWorldChangeEvents;",
        "register": "ServerEntityWorldChangeEvents.AFTER_PLAYER_CHANGE_WORLD.register((player, origin, destination) -> {{\n            var server = player.getServer();\n            ServerWorld world = destination;\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n        }});",
    },
    "player_chat": {
        "import": "import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;",
        "register": "ServerMessageEvents.CHAT_MESSAGE.register((signedMessage, player, params) -> {{\n            var server = player.getServer();\n            ServerWorld world = player.getServerWorld();\n            BlockPos soundPos = player.getBlockPos();\n            String message = signedMessage.getSignedContent();\n            {body}\n        }});",
    },
    "player_tick": {
        "import": "import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;",
        "register": "ServerTickEvents.END_SERVER_TICK.register((server) -> {{\n            for (ServerPlayerEntity player : server.getPlayerManager().getPlayerList()) {{\n                ServerWorld world = player.getServerWorld();\n                BlockPos soundPos = player.getBlockPos();\n                {body}\n            }}\n        }});",
    },
    "player_use_item": {
        "import": "import net.fabricmc.fabric.api.event.player.UseItemCallback;\nimport net.minecraft.util.TypedActionResult;",
        "register": "UseItemCallback.EVENT.register((player, world, hand) -> {{\n            ItemStack stack = player.getStackInHand(hand);\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n            return TypedActionResult.pass(stack);\n        }});",
    },
    "player_use_block": {
        "import": "import net.fabricmc.fabric.api.event.player.UseBlockCallback;\nimport net.minecraft.block.BlockState;",
        "register": "UseBlockCallback.EVENT.register((player, world, hand, hitResult) -> {{\n            BlockPos pos = hitResult.getBlockPos();\n            BlockState state = world.getBlockState(pos);\n            ItemStack stack = player.getStackInHand(hand);\n            BlockPos soundPos = pos;\n            {body}\n            return ActionResult.PASS;\n        }});",
    },
    "player_attack_entity": {
        "import": "import net.fabricmc.fabric.api.event.player.AttackEntityCallback;",
        "register": "AttackEntityCallback.EVENT.register((player, world, hand, entity, hitResult) -> {{\n            ItemStack stack = player.getStackInHand(hand);\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n            return ActionResult.PASS;\n        }});",
    },
    "player_interact_entity": {
        "import": "import net.fabricmc.fabric.api.event.player.UseEntityCallback;",
        "register": "UseEntityCallback.EVENT.register((player, world, hand, entity, hitResult) -> {{\n            ItemStack stack = player.getStackInHand(hand);\n            BlockPos soundPos = player.getBlockPos();\n            {body}\n            return ActionResult.PASS;\n        }});",
    },
    "entity_death": {
        "import": "import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;",
        "register": "ServerLivingEntityEvents.AFTER_DEATH.register((entity, damageSource) -> {{\n            if (entity instanceof ServerPlayerEntity) {{ return; }}\n            var server = entity.getServer();\n            ServerWorld world = (ServerWorld) entity.getWorld();\n            BlockPos soundPos = entity.getBlockPos();\n            {body}\n        }});",
    },
}

FORGE_EVENT_MAP: dict[str, dict] = {
    "player_join": {
        "class": "PlayerEvent.PlayerLoggedInEvent",
        "import": "import net.minecraftforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_leave": {
        "class": "PlayerEvent.PlayerLoggedOutEvent",
        "import": "import net.minecraftforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "server_start": {
        "class": "ServerStartedEvent",
        "import": "import net.minecraftforge.event.server.ServerStartedEvent;",
        "locals": [
            "        var server = event.getServer();",
        ],
    },
    "server_stop": {
        "class": "ServerStoppingEvent",
        "import": "import net.minecraftforge.event.server.ServerStoppingEvent;",
        "locals": [
            "        var server = event.getServer();",
        ],
    },
    "server_tick": {
        "class": "TickEvent.ServerTickEvent",
        "import": "import net.minecraftforge.event.TickEvent;",
        "setup": "        if (event.phase != TickEvent.Phase.END) {\n            return;\n        }",
        "locals": [
            "        var server = net.minecraftforge.server.ServerLifecycleHooks.getCurrentServer();",
        ],
    },
    "block_break": {
        "class": "BlockEvent.BreakEvent",
        "import": "import net.minecraftforge.event.level.BlockEvent;",
        "locals": [
            "        Player player = event.getPlayer();",
            "        var level = event.getLevel();",
            "        var server = level.getServer();",
            "        var pos = event.getPos();",
            "        var state = event.getState();",
            "        var soundPos = pos;",
        ],
    },
    "player_respawn": {
        "class": "PlayerEvent.PlayerRespawnEvent",
        "import": "import net.minecraftforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_death": {
        "class": "LivingDeathEvent",
        "import": "import net.minecraftforge.event.entity.living.LivingDeathEvent;",
        "setup": "        if (!(event.getEntity() instanceof Player player)) {\n            return;\n        }",
        "locals": [
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_change_dimension": {
        "class": "PlayerEvent.PlayerChangedDimensionEvent",
        "import": "import net.minecraftforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_chat": {
        "class": "ServerChatEvent",
        "import": "import net.minecraftforge.event.ServerChatEvent;",
        "locals": [
            "        ServerPlayer player = event.getPlayer();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
            "        String message = event.getMessage().getString();",
        ],
    },
    "player_tick": {
        "class": "TickEvent.PlayerTickEvent",
        "import": "import net.minecraftforge.event.TickEvent;",
        "setup": "        if (event.phase != TickEvent.Phase.END || !(event.player instanceof Player player)) {\n            return;\n        }",
        "locals": [
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_use_item": {
        "class": "PlayerInteractEvent.RightClickItem",
        "import": "import net.minecraftforge.event.entity.player.PlayerInteractEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var hand = event.getHand();",
            "        var stack = event.getItemStack();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_use_block": {
        "class": "PlayerInteractEvent.RightClickBlock",
        "import": "import net.minecraftforge.event.entity.player.PlayerInteractEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var hand = event.getHand();",
            "        var stack = event.getItemStack();",
            "        var pos = event.getPos();",
            "        var state = level.getBlockState(pos);",
            "        var soundPos = pos;",
        ],
    },
    "player_attack_entity": {
        "class": "AttackEntityEvent",
        "import": "import net.minecraftforge.event.entity.player.AttackEntityEvent;\nimport net.minecraft.world.InteractionHand;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var hand = InteractionHand.MAIN_HAND;",
            "        var stack = player.getMainHandItem();",
            "        var entity = event.getTarget();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_interact_entity": {
        "class": "PlayerInteractEvent.EntityInteract",
        "import": "import net.minecraftforge.event.entity.player.PlayerInteractEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var hand = event.getHand();",
            "        var stack = event.getItemStack();",
            "        var entity = event.getTarget();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "entity_death": {
        "class": "LivingDeathEvent",
        "import": "import net.minecraftforge.event.entity.living.LivingDeathEvent;",
        "setup": "        if (event.getEntity() instanceof Player) {\n            return;\n        }",
        "locals": [
            "        var entity = event.getEntity();",
            "        var level = entity.level();",
            "        var server = level.getServer();",
            "        var soundPos = entity.blockPosition();",
        ],
    },
}


NEOFORGE_API_MAP: dict[str, str] = {
    **FORGE_API_MAP,
    "ctx.player.give_item":
        'player.addItem(new ItemStack(BuiltInRegistries.ITEM.getValue(ResourceLocation.parse({0})), {1}))',
    "ctx.player.add_effect":
        'player.addEffect(new MobEffectInstance(BuiltInRegistries.MOB_EFFECT.getValue(ResourceLocation.parse((({0}).contains(":") ? {0} : "minecraft:" + ({0}).toLowerCase()))), {1} * 20, {2}))',
    "ctx.player.remove_effect":
        'player.removeEffect(BuiltInRegistries.MOB_EFFECT.getValue(ResourceLocation.parse((({0}).contains(":") ? {0} : "minecraft:" + ({0}).toLowerCase()))))',
    "ctx.world.play_sound":
        'level.playSound(null, soundPos, BuiltInRegistries.SOUND_EVENT.getValue(ResourceLocation.parse({0})), SoundSource.BLOCKS, {1}, {2})',
    "ctx.world.set_block":
        'level.setBlock(new BlockPos((int){0}, (int){1}, (int){2}), BuiltInRegistries.BLOCK.getValue(ResourceLocation.parse({3})).defaultBlockState(), 3)',
}

NEOFORGE_EXTRA_IMPORTS: list[str] = [
    "import net.minecraft.network.chat.Component;",
    "import net.minecraft.resources.ResourceLocation;",
    "import net.minecraft.world.item.ItemStack;",
    "import net.minecraft.world.effect.MobEffectInstance;",
    "import net.minecraft.sounds.SoundSource;",
    "import net.minecraft.sounds.SoundEvents;",
    "import net.minecraft.server.level.ServerPlayer;",
    "import net.minecraft.server.level.ServerLevel;",
    "import net.minecraft.world.level.Level;",
    "import net.minecraft.core.BlockPos;",
    "import net.minecraft.core.registries.BuiltInRegistries;",
]

NEOFORGE_EVENT_MAP: dict[str, dict] = {
    "player_join": {
        "class": "PlayerEvent.PlayerLoggedInEvent",
        "import": "import net.neoforged.neoforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_leave": {
        "class": "PlayerEvent.PlayerLoggedOutEvent",
        "import": "import net.neoforged.neoforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "server_start": {
        "class": "ServerStartedEvent",
        "import": "import net.neoforged.neoforge.event.server.ServerStartedEvent;",
        "locals": [
            "        var server = event.getServer();",
        ],
    },
    "server_stop": {
        "class": "ServerStoppingEvent",
        "import": "import net.neoforged.neoforge.event.server.ServerStoppingEvent;",
        "locals": [
            "        var server = event.getServer();",
        ],
    },
    "server_tick": {
        "class": "ServerTickEvent.Post",
        "import": "import net.neoforged.neoforge.event.tick.ServerTickEvent;",
        "locals": [
            "        var server = event.getServer();",
        ],
    },
    "block_break": {
        "class": "BlockEvent.BreakEvent",
        "import": "import net.neoforged.neoforge.event.level.BlockEvent;",
        "locals": [
            "        Player player = event.getPlayer();",
            "        var level = event.getLevel();",
            "        var server = level.getServer();",
            "        var pos = event.getPos();",
            "        var state = event.getState();",
            "        var soundPos = pos;",
        ],
    },
    "player_respawn": {
        "class": "PlayerEvent.PlayerRespawnEvent",
        "import": "import net.neoforged.neoforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_death": {
        "class": "LivingDeathEvent",
        "import": "import net.neoforged.neoforge.event.entity.living.LivingDeathEvent;",
        "setup": "        if (!(event.getEntity() instanceof Player player)) {\n            return;\n        }",
        "locals": [
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_change_dimension": {
        "class": "PlayerEvent.PlayerChangedDimensionEvent",
        "import": "import net.neoforged.neoforge.event.entity.player.PlayerEvent;",
        "locals": [
            "        Player player = event.getEntity();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
        ],
    },
    "player_chat": {
        "class": "ServerChatEvent",
        "import": "import net.neoforged.neoforge.event.ServerChatEvent;",
        "locals": [
            "        ServerPlayer player = event.getPlayer();",
            "        var server = player.getServer();",
            "        var level = player.level();",
            "        var soundPos = player.blockPosition();",
            "        String message = event.getRawText();",
        ],
    },
}

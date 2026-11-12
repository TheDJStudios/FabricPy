"""Server-authoritative held-item transfer wrappers preserving stack metadata."""
from pathlib import Path


def write_item_transfer_helpers(mod, java_root: Path, pkg: str, loader_name: str):
    if not any(getattr(item, 'inventory_size', 0) or getattr(item, 'attachment_slots', ()) for item in mod._items):
        return
    fabric = loader_name in {'fabric', 'quilt'}
    player_type = 'net.minecraft.entity.player.PlayerEntity' if fabric else 'net.minecraft.world.entity.player.Player'
    hand_type = 'net.minecraft.util.Hand' if fabric else 'net.minecraft.world.InteractionHand'
    stack_type = 'net.minecraft.item.ItemStack' if fabric else 'net.minecraft.world.item.ItemStack'
    player = 'PlayerEntity' if fabric else 'Player'
    hand = 'Hand' if fabric else 'InteractionHand'
    get_stack = 'player.getStackInHand' if fabric else 'player.getItemInHand'
    client = 'player.getWorld().isClient' if fabric else 'player.level().isClientSide'
    shrink = 'decrement' if fabric else 'shrink'
    give = 'player.getInventory().offerOrDrop(extracted);' if fabric else 'player.addItem(extracted); if (!extracted.isEmpty()) player.drop(extracted, false);'
    changed = 'markDirty' if fabric else 'setChanged'
    source = f'''package {pkg}.item;
import {player_type};
import {hand_type};
import {stack_type};
public final class FabricPyItemTransfers {{
    private static boolean held({player} player, ItemStack owner) {{
        return player != null && owner != null && player.isAlive() && !player.isRemoved()
            && !{client} && owner.getCount() == 1
            && ({get_stack}({hand}.MAIN_HAND) == owner || {get_stack}({hand}.OFF_HAND) == owner);
    }}
    private static ItemStack offered({player} player, String handName) {{
        if ("main_hand".equals(handName)) return {get_stack}({hand}.MAIN_HAND);
        if ("off_hand".equals(handName)) return {get_stack}({hand}.OFF_HAND);
        return ItemStack.EMPTY;
    }}
    public static int insertFromHand({player} player, ItemStack owner, String sourceHand, int amount) {{
        if (!held(player, owner) || amount <= 0) return 0;
        ItemStack source = offered(player, sourceHand);
        if (source == owner || source.isEmpty()) return 0;
        ItemStack portion = source.copy();
        portion.setCount(Math.min(amount, source.getCount()));
        int moved = FabricPyItemStorage.insert(owner, portion);
        if (moved > 0) {{ source.{shrink}(moved); player.getInventory().{changed}(); }}
        return moved;
    }}
    public static int extractToPlayer({player} player, ItemStack owner, int slot, int amount) {{
        if (!held(player, owner) || amount <= 0) return 0;
        ItemStack extracted = FabricPyItemStorage.extract(owner, slot, amount);
        int moved = extracted.getCount();
        if (!extracted.isEmpty()) {{ {give} player.getInventory().{changed}(); }}
        return moved;
    }}
    public static boolean installFromHand({player} player, ItemStack owner, String name, String sourceHand) {{
        if (!held(player, owner)) return false;
        ItemStack source = offered(player, sourceHand);
        boolean installed = source != owner && FabricPyItemStorage.installAttachment(owner, name, source);
        if (installed) player.getInventory().{changed}();
        return installed;
    }}
    public static boolean removeToPlayer({player} player, ItemStack owner, String name) {{
        if (!held(player, owner)) return false;
        ItemStack extracted = FabricPyItemStorage.removeAttachment(owner, name);
        if (extracted.isEmpty()) return false;
        {give}
        player.getInventory().{changed}();
        return true;
    }}
}}
'''
    dest = java_root / 'item' / 'FabricPyItemTransfers.java'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding='utf-8')

"""Generate server-owned item inventories using vanilla chest menu networking."""
from __future__ import annotations

import json
from pathlib import Path


def write_item_menu_helpers(mod, java_root: Path, pkg: str, loader_name: str) -> None:
    """Write the shared menu helper for a loader's mapped Minecraft API."""
    if not any(int(getattr(item, "inventory_size", 0)) > 0 for item in mod._items):
        return
    fabric = loader_name in {"fabric", "quilt"}
    names = {
        "player": "PlayerEntity" if fabric else "Player",
        "player_inv": "PlayerInventory" if fabric else "Inventory",
        "hand": "Hand" if fabric else "InteractionHand",
        "server_player": "ServerPlayerEntity" if fabric else "ServerPlayer",
        "container": "SimpleInventory" if fabric else "SimpleContainer",
        "menu": "GenericContainerScreenHandler" if fabric else "ChestMenu",
        "menu_type": "ScreenHandlerType" if fabric else "MenuType",
        "click": "SlotActionType" if fabric else "ClickType",
        "text": "Text" if fabric else "Component",
        "inv_get": "getStack" if fabric else "getItem",
        "inv_set": "setStack" if fabric else "setItem",
        "inv_size": "size" if fabric else "getContainerSize",
        "dirty": "markDirty" if fabric else "setChanged",
        "inv_valid": "canPlayerUse" if fabric else "stillValid",
        "valid": "canUse" if fabric else "stillValid",
        "selected": "selectedSlot" if fabric else "selected",
        "get_hand": "getStackInHand" if fabric else "getItemInHand",
        "slot_inv": "inventory" if fabric else "container",
        "slot_index": "getIndex" if fabric else "getContainerSlot",
        "slot_id": "id" if fabric else "index",
        "may_place": "canInsert" if fabric else "mayPlace",
        "may_pickup": "canTakeItems" if fabric else "mayPickup",
        "quick": "quickMove" if fabric else "quickMoveStack",
        "clicked": "onSlotClick" if fabric else "clicked",
        "pick_all": "canInsertIntoSlot" if fabric else "canTakeItemForPickAll",
        "drag": "canInsertIntoSlot" if fabric else "canDragTo",
        "closed": "onClosed" if fabric else "removed",
        "broadcast": "sendContentUpdates" if fabric else "broadcastChanges",
        "get_name": "getName" if fabric else "getHoverName",
    }
    if fabric:
        imports = """import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.player.PlayerInventory;
import net.minecraft.inventory.SimpleInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.screen.GenericContainerScreenHandler;
import net.minecraft.screen.ScreenHandlerType;
import net.minecraft.screen.SimpleNamedScreenHandlerFactory;
import net.minecraft.screen.slot.Slot;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.Hand;"""
        open_line = "return serverPlayer.openHandledScreen(new SimpleNamedScreenHandlerFactory((syncId, inventory, ignored) -> new HeldMenu(syncId, inventory, data, rows), title(owner))).isPresent();"
        slot_constructor = "super(original.inventory, original.getIndex(), original.x, original.y);\n            this.id = original.id;"
    else:
        imports = """import net.minecraft.world.entity.player.Player;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.inventory.ChestMenu;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.InteractionHand;"""
        open_line = "return serverPlayer.openMenu(new SimpleMenuProvider((syncId, inventory, ignored) -> new HeldMenu(syncId, inventory, data, rows), title(owner))).isPresent();"
        slot_constructor = "super(original.container, original.getContainerSlot(), original.x, original.y);\n            this.index = original.index;"
    title_cases = []
    for item in mod._items:
        title = getattr(item, "inventory_title", "")
        if int(getattr(item, "inventory_size", 0)) > 0 and title:
            title_cases.append(f"        if (owner.getItem() instanceof {item.get_class_name()}) return {names['text']}.literal({json.dumps(str(title))});")
    type_cases = "\n".join(f"            case {rows} -> {names['menu_type']}.GENERIC_9{'X' if fabric else 'x'}{rows};" for rows in range(1, 7))
    source = _TEMPLATE.replace("@PKG@", pkg).replace("@IMPORTS@", imports)
    source = source.replace("@TITLE_CASES@", "\n".join(title_cases)).replace("@TYPE_CASES@", type_cases)
    source = source.replace("@OPEN@", open_line).replace("@SLOT_CONSTRUCTOR@", slot_constructor)
    for key, value in names.items():
        source = source.replace("@" + key + "@", value)
    directory = java_root / "item"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "FabricPyItemMenus.java").write_text(source, encoding="utf-8")


_TEMPLATE = '''package @PKG@.item;

@IMPORTS@
import java.util.ArrayList;

/** Vanilla-networked, server-authoritative inventories stored in the held item. */
public final class FabricPyItemMenus {
    private FabricPyItemMenus() {}

    public static boolean open(@player@ player, @hand@ hand, ItemStack owner) {
        if (!(player instanceof @server_player@ serverPlayer)) return false;
        int size = FabricPyItemStorage.inventorySize(owner);
        if (size < 9 || size > 54 || size % 9 != 0 || owner.getCount() != 1
                || player.@get_hand@(hand) != owner) return false;
        int rows = size / 9;
        HeldInventory data = new HeldInventory(player, hand, owner, size);
        @OPEN@
    }

    private static @text@ title(ItemStack owner) {
@TITLE_CASES@
        return owner.@get_name@();
    }

    private static @menu_type@<?> menuType(int rows) {
        return switch (rows) {
@TYPE_CASES@
            default -> throw new IllegalArgumentException("Item inventory needs one to six rows");
        };
    }

    private static final class HeldInventory extends @container@ {
        private final @player@ ownerPlayer;
        private final @hand@ ownerHand;
        private final ItemStack ownerStack;
        private final int selectedSlot;
        private boolean loading = true;

        HeldInventory(@player@ player, @hand@ hand, ItemStack owner, int size) {
            super(size);
            ownerPlayer = player;
            ownerHand = hand;
            ownerStack = owner;
            selectedSlot = player.getInventory().@selected@;
            loading = false;
            refresh();
        }

        void refresh() {
            if (!validOwner(ownerPlayer)) return;
            loading = true;
            try {
                var contents = FabricPyItemStorage.loadInventory(ownerStack, @inv_size@());
                for (int index = 0; index < @inv_size@(); index++) super.@inv_set@(index, contents.get(index));
            } finally {
                loading = false;
            }
        }

        boolean validOwner(@player@ player) {
            return player == ownerPlayer && player.isAlive() && !player.isRemoved()
                && ownerStack.getCount() == 1 && player.@get_hand@(ownerHand) == ownerStack
                && (ownerHand != @hand@.MAIN_HAND || player.getInventory().@selected@ == selectedSlot);
        }

        int ownerInventorySlot() {
            return ownerHand == @hand@.MAIN_HAND ? selectedSlot : 40;
        }

        boolean allowed(ItemStack candidate) {
            return FabricPyItemStorage.canStore(ownerStack, candidate);
        }

        @Override
        public boolean @inv_valid@(@player@ player) {
            return validOwner(player);
        }

        @Override
        public void @dirty@() {
            super.@dirty@();
            flush();
        }

        void flush() {
            if (loading || !validOwner(ownerPlayer)) return;
            var contents = new ArrayList<ItemStack>();
            for (int index = 0; index < @inv_size@(); index++) contents.add(@inv_get@(index).copy());
            FabricPyItemStorage.saveInventory(ownerStack, contents);
            ownerPlayer.getInventory().@dirty@();
        }
    }

    private static final class SafeSlot extends Slot {
        private final HeldInventory data;
        private final boolean locked;
        private final boolean storage;

        SafeSlot(Slot original, HeldInventory data, boolean storage, boolean locked) {
            @SLOT_CONSTRUCTOR@
            this.data = data;
            this.storage = storage;
            this.locked = locked;
        }

        @Override
        public boolean @may_place@(ItemStack candidate) {
            return !locked && (!storage || data.allowed(candidate)) && super.@may_place@(candidate);
        }

        @Override
        public boolean @may_pickup@(@player@ player) {
            return !locked && data.validOwner(player) && super.@may_pickup@(player);
        }
    }

    private static final class HeldMenu extends @menu@ {
        private final HeldInventory data;
        private int lockedMenuSlot = -1;

        HeldMenu(int syncId, @player_inv@ inventory, HeldInventory data, int rows) {
            super(menuType(rows), syncId, inventory, data, rows);
            this.data = data;
            for (int index = 0; index < slots.size(); index++) {
                Slot original = slots.get(index);
                boolean storage = original.@slot_inv@ == data;
                boolean locked = original.@slot_inv@ == inventory
                    && original.@slot_index@() == data.ownerInventorySlot();
                if (locked) lockedMenuSlot = index;
                slots.set(index, new SafeSlot(original, data, storage, locked));
            }
        }

        @Override
        public boolean @valid@(@player@ player) {
            return data.validOwner(player) && super.@valid@(player);
        }

        @Override
        public void @clicked@(int slot, int button, @click@ action, @player@ player) {
            if (!data.validOwner(player) || slot == lockedMenuSlot
                    || (action == @click@.SWAP && button == data.ownerInventorySlot())) return;
            data.refresh();
            super.@clicked@(slot, button, action, player);
            data.flush();
        }

        @Override
        public ItemStack @quick@(@player@ player, int slot) {
            if (!data.validOwner(player) || slot == lockedMenuSlot) return ItemStack.EMPTY;
            data.refresh();
            ItemStack moved = super.@quick@(player, slot);
            data.flush();
            return moved;
        }

        @Override
        public boolean @pick_all@(ItemStack cursor, Slot slot) {
            return slot.@slot_id@ != lockedMenuSlot && super.@pick_all@(cursor, slot);
        }

        @Override
        public boolean @drag@(Slot slot) {
            return slot.@slot_id@ != lockedMenuSlot && super.@drag@(slot);
        }

        @Override
        public void @broadcast@() {
            if (data != null) data.refresh();
            super.@broadcast@();
        }

        @Override
        public void @closed@(@player@ player) {
            data.refresh();
            data.flush();
            super.@closed@(player);
        }
    }
}
'''

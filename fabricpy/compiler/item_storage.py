"""Persistent per-stack item data, inventories, and named attachments.

Legacy targets serialize complete stacks to NBT. Component targets use the
vanilla CONTAINER component, preserving every stack's components without a
registry lookup in each callback. Inventory slots occupy 0..53; attachment
positions are named in CUSTOM_DATA and occupy 54..255.
"""
from __future__ import annotations

import json
from pathlib import Path

from fabricpy.compiler.versions import is_at_least


def write_item_storage_helpers(mod, java_root: Path, pkg: str, loader_name: str) -> None:
    fabric = loader_name in {"fabric", "quilt"}
    modern = is_at_least(mod.minecraft_version, "1.20.5")
    names = {
        "PACKAGE": pkg,
        "STACK_IMPORT": "net.minecraft.item.ItemStack" if fabric else "net.minecraft.world.item.ItemStack",
        "ITEM_IMPORT": "net.minecraft.item.Item" if fabric else "net.minecraft.world.item.Item",
        "BUNDLE_IMPORT": "net.minecraft.item.BundleItem" if fabric else "net.minecraft.world.item.BundleItem",
        "TAG_IMPORT": "net.minecraft.nbt.NbtCompound" if fabric else "net.minecraft.nbt.CompoundTag",
        "TAG": "NbtCompound" if fabric else "CompoundTag",
        "LIST_TAG_IMPORT": "net.minecraft.nbt.NbtList" if fabric else "net.minecraft.nbt.ListTag",
        "LIST_TAG": "NbtList" if fabric else "ListTag",
        "LIST_IMPORT": "net.minecraft.util.collection.DefaultedList" if fabric else "net.minecraft.core.NonNullList",
        "LIST": "DefaultedList" if fabric else "NonNullList",
        "LIST_NEW": "DefaultedList.ofSize" if fabric else "NonNullList.withSize",
        "MAX_COUNT": "getMaxCount" if fabric else "getMaxStackSize",
        "SHRINK": "decrement" if fabric else "shrink",
        "GROW": "increment" if fabric else "grow",
        "CAN_NEST": "canBeNested" if fabric else "canFitInsideContainerItems",
        "KEYS": "getKeys" if fabric else "getAllKeys",
        "REGISTRY_IMPORT": "net.minecraft.registry.Registries" if fabric else "net.minecraft.core.registries.BuiltInRegistries",
        "ID_IMPORT": "net.minecraft.util.Identifier" if fabric else "net.minecraft.resources.ResourceLocation",
        "REGISTRY": "Registries.ITEM" if fabric else "BuiltInRegistries.ITEM",
        "REGISTRY_ID": "getId" if fabric else "getKey",
        "REGISTRY_CONTAINS": "containsId" if fabric else "containsKey",
        "ID": "Identifier" if fabric else "ResourceLocation",
        "ID_PARSE": "Identifier.tryParse" if fabric else "ResourceLocation.tryParse",
        "COMBINE": "ItemStack.areItemsAndComponentsEqual" if fabric and modern else "ItemStack.canCombine" if fabric else "ItemStack.isSameItemSameComponents" if modern else "ItemStack.isSameItemSameTags",
    }
    inventory_cases = []
    attachment_cases = []
    for item in mod._items:
        inventory_size = int(getattr(item, "inventory_size", 0))
        slots = tuple(getattr(item, "attachment_slots", ()))
        if inventory_size or slots:
            item_id = json.dumps(f"{mod.mod_id}:{item.item_id}")
            inventory_cases.append(f"            case {item_id} -> {inventory_size};")
            attachment_cases.append(f"            case {item_id} -> new String[] {{{', '.join(json.dumps(slot) for slot in slots)}}};")
    names["INVENTORY_CASES"] = "\n".join(inventory_cases)
    names["ATTACHMENT_CASES"] = "\n".join(attachment_cases)
    if modern:
        names.update({
            "COMPONENT_IMPORTS": "import net.minecraft.component.DataComponentTypes;\nimport net.minecraft.component.type.NbtComponent;\nimport net.minecraft.component.type.ContainerComponent;" if fabric else "import net.minecraft.core.component.DataComponents;\nimport net.minecraft.world.item.component.CustomData;\nimport net.minecraft.world.item.component.ItemContainerContents;",
            "ROOT_READ": "return owner.getOrDefault(DataComponentTypes.CUSTOM_DATA, NbtComponent.DEFAULT).copyNbt();" if fabric else "return owner.getOrDefault(DataComponents.CUSTOM_DATA, CustomData.EMPTY).copyTag();",
            "ROOT_WRITE": "if (root.isEmpty()) owner.remove(DataComponentTypes.CUSTOM_DATA); else owner.set(DataComponentTypes.CUSTOM_DATA, NbtComponent.of(root));" if fabric else "if (root.isEmpty()) owner.remove(DataComponents.CUSTOM_DATA); else owner.set(DataComponents.CUSTOM_DATA, CustomData.of(root));",
            "ITEMS_READ": "owner.getOrDefault(DataComponentTypes.CONTAINER, ContainerComponent.DEFAULT).copyTo(result);" if fabric else "owner.getOrDefault(DataComponents.CONTAINER, ItemContainerContents.EMPTY).copyInto(result);",
            "ITEMS_WRITE": "owner.set(DataComponentTypes.CONTAINER, ContainerComponent.fromStacks(items));" if fabric else "owner.set(DataComponents.CONTAINER, ItemContainerContents.fromItems(items));",
            "NESTED_COMPONENT_CHECK": "if (candidate.contains(DataComponentTypes.CONTAINER) || candidate.contains(DataComponentTypes.BUNDLE_CONTENTS) || candidate.contains(DataComponentTypes.CONTAINER_LOOT)) return false;" if fabric else "if (candidate.has(DataComponents.CONTAINER) || candidate.has(DataComponents.BUNDLE_CONTENTS) || candidate.has(DataComponents.CONTAINER_LOOT)) return false;",
        })
    else:
        names["COMPONENT_IMPORTS"] = ""
        names["ROOT_READ"] = "return owner.hasNbt() ? owner.getNbt().copy() : new NbtCompound();" if fabric else "return owner.hasTag() ? owner.getTag().copy() : new CompoundTag();"
        names["ROOT_WRITE"] = "owner.setNbt(root.isEmpty() ? null : root);" if fabric else "owner.setTag(root.isEmpty() ? null : root);"
        names["ITEMS_READ"] = '''@LIST_TAG@ entries = readRoot(owner).getList(ITEMS_KEY, 10);
        for (int i = 0; i < entries.size(); i++) {
            @TAG@ entry = entries.getCompound(i);
            int slot = entry.getInt("Slot");
            if (slot < 0 || slot >= MAX_SLOTS) throw new IllegalStateException("Invalid persisted item slot");
            if (!result.get(slot).isEmpty()) throw new IllegalStateException("Duplicate persisted item slot");
            result.set(slot, @STACK_LOAD@);
        }'''.replace("@STACK_LOAD@", 'ItemStack.fromNbt(entry.getCompound("Stack"))' if fabric else 'ItemStack.of(entry.getCompound("Stack"))')
        names["ITEMS_WRITE"] = '''@TAG@ root = readRoot(owner);
        @LIST_TAG@ entries = new @LIST_TAG@();
        for (int i = 0; i < items.size(); i++) {
            if (items.get(i).isEmpty()) continue;
            @TAG@ entry = new @TAG@();
            entry.putInt("Slot", i);
            entry.put("Stack", @STACK_SAVE@);
            entries.add(entry);
        }
        root.put(ITEMS_KEY, entries);
        writeRoot(owner, root);'''.replace("@STACK_SAVE@", "items.get(i).writeNbt(new NbtCompound())" if fabric else "items.get(i).save(new CompoundTag())")
        names["NESTED_COMPONENT_CHECK"] = '''@TAG@ tag = readRoot(candidate);
        if (tag.contains(ITEMS_KEY) || tag.contains("Items") || tag.getCompound("BlockEntityTag").contains("Items")) return false;'''
    source = _SOURCE
    # Some snippets contain the shared mapping tokens themselves.
    for _ in range(2):
        for key, value in names.items():
            source = source.replace(f"@{key}@", value)
    if fabric and is_at_least(mod.minecraft_version, "1.21.5"):
        # NBT scalar getters became Optional-valued in 1.21.5; explicit fallbacks
        # keep the authored defaults and use the matching newer Yarn surface.
        import re
        source = source.replace(".getCompound(", ".getCompoundOrEmpty(")
        for method, fallback in (("getString", '\"\"'), ("getInt", "0"), ("getBoolean", "false"), ("getDouble", "0.0")):
            source = re.sub(r"\." + method + r"\(([^()]*)\)", lambda m: f".{method}({m.group(1)}, {fallback})", source)
    item_dir = java_root / "item"
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "FabricPyItemStorage.java").write_text(source, encoding="utf-8")


_SOURCE = '''package @PACKAGE@.item;

import java.util.List;
import java.util.HashSet;
import java.util.Set;
import @STACK_IMPORT@;
import @ITEM_IMPORT@;
import @BUNDLE_IMPORT@;
import @TAG_IMPORT@;
import @LIST_TAG_IMPORT@;
import @LIST_IMPORT@;
import @REGISTRY_IMPORT@;
import @ID_IMPORT@;
@COMPONENT_IMPORTS@

/** Server-authoritative, copy-on-write item storage. Generated by FabricPy. */
public final class FabricPyItemStorage {
    private FabricPyItemStorage() {}
    private static final int INVENTORY_LIMIT = 54;
    private static final int MAX_SLOTS = 256;
    private static final String DATA_KEY = "fabricpy_data";
    private static final String ITEMS_KEY = "fabricpy_storage_items";
    private static final String ATTACHMENTS_KEY = "fabricpy_attachment_layout";

    public static int inventorySize(ItemStack owner) {
        return switch (itemId(owner)) {
@INVENTORY_CASES@
            default -> 0;
        };
    }

    public static String[] attachmentSlots(ItemStack owner) {
        return switch (itemId(owner)) {
@ATTACHMENT_CASES@
            default -> new String[0];
        };
    }

    private static String itemId(ItemStack stack) {
        return stack == null || stack.isEmpty() ? "" : @REGISTRY@.@REGISTRY_ID@(stack.getItem()).toString();
    }

    private static Item requireItem(String id) {
        @ID@ identifier = @ID_PARSE@(id);
        if (identifier == null || !@REGISTRY@.@REGISTRY_CONTAINS@(identifier)) throw new IllegalArgumentException("Unknown item ID: " + id);
        Item item = @REGISTRY@.get(identifier);
        if (new ItemStack(item).isEmpty()) throw new IllegalArgumentException("Air is not a stored item");
        return item;
    }

    private static void requireOwner(ItemStack owner) {
        if (owner == null || owner.isEmpty() || owner.getCount() != 1 || (inventorySize(owner) == 0 && attachmentSlots(owner).length == 0)) {
            throw new IllegalArgumentException("Storage requires a single configured storage item");
        }
    }

    private static void requireSlot(ItemStack owner, int slot) {
        requireOwner(owner);
        if (slot < 0 || slot >= inventorySize(owner)) throw new IndexOutOfBoundsException("Inventory slot: " + slot);
    }

    private static void requireAttachment(ItemStack owner, String name) {
        requireOwner(owner);
        for (String allowed : attachmentSlots(owner)) if (allowed.equals(name)) return;
        throw new IllegalArgumentException("Unknown attachment slot: " + name);
    }

    private static void requireKey(String key) {
        if (key == null || key.isBlank() || key.length() > 256) throw new IllegalArgumentException("Data key must contain 1..256 characters");
    }

    private static @TAG@ readRoot(ItemStack owner) {
        if (owner == null || owner.isEmpty()) throw new IllegalArgumentException("Item stack is empty");
        @ROOT_READ@
    }

    private static void writeRoot(ItemStack owner, @TAG@ root) {
        @ROOT_WRITE@
    }

    private static @TAG@ data(ItemStack owner, String key) {
        requireKey(key);
        return readRoot(owner).getCompound(DATA_KEY);
    }

    private static void writeData(ItemStack owner, String key, java.util.function.Consumer<@TAG@> change) {
        requireKey(key);
        @TAG@ root = readRoot(owner);
        @TAG@ data = root.getCompound(DATA_KEY).copy();
        change.accept(data);
        if (data.isEmpty()) root.remove(DATA_KEY); else root.put(DATA_KEY, data);
        writeRoot(owner, root);
    }

    public static String getString(ItemStack owner, String key) { return data(owner, key).getString(key); }
    public static void setString(ItemStack owner, String key, String value) { if (value == null) throw new IllegalArgumentException("String value is null"); writeData(owner, key, tag -> tag.putString(key, value)); }
    public static int getInt(ItemStack owner, String key) { return data(owner, key).getInt(key); }
    public static void setInt(ItemStack owner, String key, int value) { writeData(owner, key, tag -> tag.putInt(key, value)); }
    public static boolean getBool(ItemStack owner, String key) { return data(owner, key).getBoolean(key); }
    public static void setBool(ItemStack owner, String key, boolean value) { writeData(owner, key, tag -> tag.putBoolean(key, value)); }
    public static double getFloat(ItemStack owner, String key) { return data(owner, key).getDouble(key); }
    public static void setFloat(ItemStack owner, String key, double value) { if (!Double.isFinite(value)) throw new IllegalArgumentException("Float value must be finite"); writeData(owner, key, tag -> tag.putDouble(key, value)); }
    public static boolean containsData(ItemStack owner, String key) { return data(owner, key).contains(key); }
    public static void removeData(ItemStack owner, String key) { writeData(owner, key, tag -> tag.remove(key)); }

    private static @LIST@<ItemStack> readItems(ItemStack owner) {
        @LIST@<ItemStack> result = @LIST_NEW@(MAX_SLOTS, ItemStack.EMPTY);
        @ITEMS_READ@
        return result;
    }

    private static void writeItems(ItemStack owner, List<ItemStack> items) {
        @ITEMS_WRITE@
    }

    private static @TAG@ attachmentLayout(ItemStack owner) {
        @TAG@ layout = readRoot(owner).getCompound(ATTACHMENTS_KEY).copy();
        Set<Integer> used = new HashSet<>();
        for (String name : layout.@KEYS@()) {
            int index = layout.getInt(name);
            if (index < INVENTORY_LIMIT || index >= MAX_SLOTS || !used.add(index)) throw new IllegalStateException("Corrupt attachment layout");
        }
        return layout;
    }

    public static boolean canStore(ItemStack owner, ItemStack candidate) {
        if (candidate == null || candidate == owner || candidate.isEmpty()) return false;
        if (inventorySize(candidate) > 0 || attachmentSlots(candidate).length > 0) return false;
        if (!candidate.getItem().@CAN_NEST@() || candidate.getItem() instanceof BundleItem) return false;
        @NESTED_COMPONENT_CHECK@
        return candidate.getCount() > 0 && candidate.getCount() <= candidate.@MAX_COUNT@();
    }

    public static @LIST@<ItemStack> loadInventory(ItemStack owner) {
        return loadInventory(owner, inventorySize(owner));
    }

    public static @LIST@<ItemStack> loadInventory(ItemStack owner, int size) {
        requireOwner(owner);
        if (size != inventorySize(owner)) throw new IllegalArgumentException("Inventory size does not match item configuration");
        @LIST@<ItemStack> stored = readItems(owner);
        @LIST@<ItemStack> result = @LIST_NEW@(size, ItemStack.EMPTY);
        for (int i = 0; i < size; i++) result.set(i, stored.get(i).copy());
        return result;
    }

    public static void saveInventory(ItemStack owner, List<ItemStack> items) {
        requireOwner(owner);
        if (items == null || items.size() != inventorySize(owner)) throw new IllegalArgumentException("Inventory size does not match item configuration");
        for (ItemStack stack : items) {
            if (stack == null || (!stack.isEmpty() && !canStore(owner, stack))) throw new IllegalArgumentException("Item cannot be stored");
        }
        @LIST@<ItemStack> stored = readItems(owner);
        for (int i = 0; i < items.size(); i++) stored.set(i, items.get(i).copy());
        writeItems(owner, stored);
    }

    public static String getSlotId(ItemStack owner, int slot) { requireSlot(owner, slot); return itemId(readItems(owner).get(slot)); }
    public static int getSlotCount(ItemStack owner, int slot) { requireSlot(owner, slot); return readItems(owner).get(slot).getCount(); }

    /** Administrative overwrite API: refuses to delete an occupied slot. */
    public static void setSlot(ItemStack owner, int slot, String id, int amount) {
        requireSlot(owner, slot);
        ItemStack stack = new ItemStack(requireItem(id), amount);
        if (amount <= 0 || !canStore(owner, stack)) throw new IllegalArgumentException("Invalid stored stack");
        @LIST@<ItemStack> items = readItems(owner);
        if (!items.get(slot).isEmpty()) throw new IllegalStateException("Remove the occupied stack before setting a slot");
        items.set(slot, stack);
        writeItems(owner, items);
    }

    public static ItemStack removeSlot(ItemStack owner, int slot) {
        requireSlot(owner, slot);
        return extract(owner, slot, Integer.MAX_VALUE);
    }

    public static int count(ItemStack owner, String id) {
        requireOwner(owner);
        Item item = requireItem(id);
        int count = 0;
        for (ItemStack stack : loadInventory(owner)) if (!stack.isEmpty() && stack.getItem() == item) count += stack.getCount();
        return count;
    }

    public static boolean contains(ItemStack owner, String id, int required) {
        if (required < 0) throw new IllegalArgumentException("Required count must be nonnegative");
        return count(owner, id) >= required;
    }

    public static int space(ItemStack owner, String id) {
        requireOwner(owner);
        ItemStack candidate = new ItemStack(requireItem(id));
        if (!canStore(owner, candidate)) return 0;
        int result = 0;
        for (ItemStack stack : loadInventory(owner)) {
            if (stack.isEmpty()) result += candidate.@MAX_COUNT@();
            else if (@COMBINE@(stack, candidate)) result += Math.max(0, candidate.@MAX_COUNT@() - stack.getCount());
        }
        return result;
    }

    /** Move items into storage; shrink offered by exactly the returned count. */
    public static int insert(ItemStack owner, ItemStack offered) {
        requireOwner(owner);
        if (!canStore(owner, offered)) return 0;
        @LIST@<ItemStack> items = loadInventory(owner);
        int remaining = offered.getCount();
        for (int pass = 0; pass < 2 && remaining > 0; pass++) {
            for (int i = 0; i < items.size() && remaining > 0; i++) {
                ItemStack stored = items.get(i);
                if ((pass == 0 && !stored.isEmpty() && @COMBINE@(stored, offered)) || (pass == 1 && stored.isEmpty())) {
                    int capacity = Math.max(0, offered.@MAX_COUNT@() - stored.getCount());
                    int moved = Math.min(remaining, capacity);
                    if (moved > 0) {
                        if (stored.isEmpty()) items.set(i, offered.copyWithCount(moved));
                        else stored.@GROW@(moved);
                        remaining -= moved;
                    }
                }
            }
        }
        int moved = offered.getCount() - remaining;
        if (moved > 0) { saveInventory(owner, items); offered.@SHRINK@(moved); }
        return moved;
    }

    public static ItemStack extract(ItemStack owner, int slot, int amount) {
        requireSlot(owner, slot);
        if (amount <= 0) throw new IllegalArgumentException("Extract count must be positive");
        @LIST@<ItemStack> items = loadInventory(owner);
        ItemStack result = items.get(slot).split(Math.min(amount, items.get(slot).getCount()));
        if (!result.isEmpty()) saveInventory(owner, items);
        return result;
    }

    public static String getAttachmentId(ItemStack owner, String name) {
        requireAttachment(owner, name);
        @TAG@ layout = attachmentLayout(owner);
        return layout.contains(name) ? itemId(readItems(owner).get(layout.getInt(name))) : "";
    }

    public static ItemStack getAttachment(ItemStack owner, String name) {
        requireAttachment(owner, name);
        @TAG@ layout = attachmentLayout(owner);
        return layout.contains(name) ? readItems(owner).get(layout.getInt(name)).copy() : ItemStack.EMPTY;
    }

    public static boolean hasAttachment(ItemStack owner, String name) { return !getAttachmentId(owner, name).isEmpty(); }

    /** Install one real stack item into an empty named slot, preserving metadata. */
    public static boolean installAttachment(ItemStack owner, String name, ItemStack offered) {
        requireAttachment(owner, name);
        if (!canStore(owner, offered)) return false;
        @TAG@ layout = attachmentLayout(owner);
        @LIST@<ItemStack> items = readItems(owner);
        int index = -1;
        if (layout.contains(name)) index = layout.getInt(name);
        else {
            Set<Integer> used = new HashSet<>();
            for (String key : layout.@KEYS@()) used.add(layout.getInt(key));
            for (int i = INVENTORY_LIMIT; i < MAX_SLOTS; i++) if (!used.contains(i) && items.get(i).isEmpty()) { index = i; break; }
        }
        if (index < 0) throw new IllegalStateException("Attachment storage is full");
        if (!items.get(index).isEmpty()) return false;
        items.set(index, offered.copyWithCount(1));
        layout.putInt(name, index);
        writeItems(owner, items);
        @TAG@ root = readRoot(owner);
        root.put(ATTACHMENTS_KEY, layout);
        writeRoot(owner, root);
        offered.@SHRINK@(1);
        return true;
    }

    public static ItemStack removeAttachment(ItemStack owner, String name) {
        requireAttachment(owner, name);
        @TAG@ layout = attachmentLayout(owner);
        if (!layout.contains(name)) return ItemStack.EMPTY;
        @LIST@<ItemStack> items = readItems(owner);
        int index = layout.getInt(name);
        ItemStack result = items.get(index).copy();
        if (!result.isEmpty()) { items.set(index, ItemStack.EMPTY); writeItems(owner, items); }
        return result;
    }
}
'''

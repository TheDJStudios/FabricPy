"""Portable item feature validation and callback mappings."""
from __future__ import annotations

import math
import re


def has_item_storage(item) -> bool:
    return bool(getattr(item, "inventory_size", 0) or getattr(item, "attachment_slots", ()))


def effective_stack_size(item) -> int:
    return 1 if has_item_storage(item) else item.max_stack_size


def validate_item_features(mod, item):
    size = getattr(item, "inventory_size", 0)
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 54:
        raise ValueError(f"{item.__name__}: inventory_size must be an integer from 0 to 54")
    slots = getattr(item, "attachment_slots", ())
    if not isinstance(slots, (tuple, list)) or any(not isinstance(slot, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", slot) for slot in slots):
        raise ValueError(f"{item.__name__}: attachment_slots must be a list/tuple of lowercase slot names")
    if len(slots) != len(set(slots)) or len(slots) > 16:
        raise ValueError(f"{item.__name__}: attachment slots must be unique (maximum 16)")
    if has_item_storage(item) and 'max_stack_size' in item.__dict__ and item.max_stack_size != 1:
        raise ValueError(f"{item.__name__}: inventory/attachment items are unstackable; omit max_stack_size or set it to 1")
    if has_item_storage(item) and mod.minecraft_version not in {"1.20.1", "1.21", "1.21.1"}:
        raise ValueError(f"{item.__name__}: item storage currently supports Minecraft 1.20.1, 1.21 and 1.21.1")
    if item.open_inventory_on_use and (not size or size % 9):
        raise ValueError(f"{item.__name__}: open_inventory_on_use needs inventory_size 9,18,27,36,45 or 54")
    if not isinstance(item.open_screen_on_use, str):
        raise ValueError(f"{item.__name__}: open_screen_on_use must be a screen ID")
    if item.open_screen_on_use and item.open_screen_on_use not in {screen.screen_id for screen in mod._screens}:
        raise ValueError(f"{item.__name__}: unknown screen {item.open_screen_on_use!r}; declare it with mod.screen(...)")
    if item.open_screen_on_use and item.open_inventory_on_use:
        raise ValueError(f"{item.__name__}: choose one automatic screen: client panel or inventory")
    if not isinstance(item.inventory_title, str):
        raise ValueError(f"{item.__name__}: inventory_title must be text")
    models = item.attachment_models
    if not isinstance(models, dict) or any(key not in slots for key in models):
        raise ValueError(f"{item.__name__}: attachment_models keys must name declared attachment_slots")
    for slot, transform in models.items():
        if not isinstance(transform, dict) or any(key not in {"position", "rotation", "scale"} for key in transform):
            raise ValueError(f"{item.__name__}: slot {slot} model settings accept position,rotation,scale")
        for key, values in transform.items():
            if not isinstance(values, (list, tuple)) or len(values) != 3 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
                raise ValueError(f"{item.__name__}: {slot}.{key} must have three finite numbers")
            if key == 'scale' and any(value <= 0 for value in values):
                raise ValueError(f"{item.__name__}: attachment scale must be positive")


def item_storage_api_map(pkg: str) -> dict[str, str]:
    storage = f"{pkg}.item.FabricPyItemStorage"
    transfers = f"{pkg}.item.FabricPyItemTransfers"
    menus = f"{pkg}.item.FabricPyItemMenus"
    return {
        **{f"ctx.stack.data.{snake}": f"{storage}.{java}(stack, {{0}})" for snake, java in (
            ('get_string','getString'),('get_int','getInt'),('get_bool','getBool'),('get_float','getFloat'),
            ('contains','containsData'),('remove','removeData'),
        )},
        **{f"ctx.stack.data.set_{kind}": f"{storage}.set{kind.title()}(stack, {{0}}, {{1}})" for kind in ('string','int','bool','float')},
        'ctx.stack.inventory.size': f'{storage}.inventorySize(stack)',
        'ctx.stack.inventory.get_item_id': f'{storage}.getSlotId(stack, {{0}})',
        'ctx.stack.inventory.get_count': f'{storage}.getSlotCount(stack, {{0}})',
        'ctx.stack.inventory.count': f'{storage}.count(stack, {{0}})',
        'ctx.stack.inventory.contains': f'{storage}.contains(stack, {{0}}, {{1}})',
        'ctx.stack.inventory.space': f'{storage}.space(stack, {{0}})',
        'ctx.stack.inventory.insert_from_hand': f'{transfers}.insertFromHand(player, stack, {{0}}, {{1}})',
        'ctx.stack.inventory.extract_to_player': f'{transfers}.extractToPlayer(player, stack, {{0}}, {{1}})',
        'ctx.stack.inventory.open': f'{menus}.open(player, hand, stack)',
        'ctx.stack.attachments.get_item_id': f'{storage}.getAttachmentId(stack, {{0}})',
        'ctx.stack.attachments.has': f'{storage}.hasAttachment(stack, {{0}})',
        'ctx.stack.attachments.install_from_hand': f'{transfers}.installFromHand(player, stack, {{0}}, {{1}})',
        'ctx.stack.attachments.remove_to_player': f'{transfers}.removeToPlayer(player, stack, {{0}})',
    }

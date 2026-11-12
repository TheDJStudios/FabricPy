"""Exercise generated menu transaction guards independently of Minecraft bootstrap."""
from pathlib import Path
import shutil
import subprocess
import unittest

import fabricpy as mc
from fabricpy.compiler.item_menus import write_item_menu_helpers
from tests.support import project_dir


def _method(source, signature):
    start = source.index(signature)
    cursor = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[cursor] == '{') - (source[cursor] == '}')
        cursor += 1
    return source[start:cursor]


def _generate(root, loader):
    mod = mc.Mod('example', 'Example')
    @mod.register
    class Bag(mc.Item):
        item_id = 'bag'
        inventory_size = 9
        inventory_title = 'My Bag'
    write_item_menu_helpers(mod, root, 'test', loader)
    return (root / 'item/FabricPyItemMenus.java').read_text()


class ItemMenuTests(unittest.TestCase):
    def test_vanilla_types_persistence_and_metadata_preserving_storage_are_wired(self):
        with project_dir() as root:
            for loader in ('fabric', 'quilt', 'forge', 'neoforge'):
                source = _generate(root / loader, loader)
                self.assertIn('FabricPyItemStorage.loadInventory(ownerStack,', source)
                self.assertIn('FabricPyItemStorage.saveInventory(ownerStack, contents)', source)
                self.assertIn('FabricPyItemStorage.canStore(ownerStack, candidate)', source)
                self.assertIn('.copy()', source)
                self.assertIn('"My Bag"', source)
                self.assertIn('GENERIC_9X6' if loader in {'fabric', 'quilt'} else 'GENERIC_9x6', source)
                self.assertIn('owner.getCount() != 1', source)
                self.assertNotIn('send_to_server', source)
                self.assertNotRegex(source, r'@[A-Za-z_]+@')
                if loader in {'fabric', 'quilt'}:
                    self.assertIn('SimpleNamedScreenHandlerFactory', source)
                else:
                    self.assertIn('SimpleMenuProvider', source)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_slot_clicks_swaps_and_shift_clicks_cannot_move_owner(self):
        with project_dir() as root:
            for loader in ('fabric', 'forge'):
                with self.subTest(loader=loader):
                    source = _generate(root / loader, loader)
                    fabric = loader == 'fabric'
                    player = 'PlayerEntity' if fabric else 'Player'
                    action = 'SlotActionType' if fabric else 'ClickType'
                    clicked = 'onSlotClick' if fabric else 'clicked'
                    quick = 'quickMove' if fabric else 'quickMoveStack'
                    body = _method(source, f'public void {clicked}(') + '\n' + _method(source, f'public ItemStack {quick}(')
                    java = f'''class ItemStack {{ static final ItemStack EMPTY = new ItemStack(); }}
class {player} {{}}
enum {action} {{ PICKUP, SWAP, THROW, CLONE, QUICK_MOVE }}
class HeldInventory {{ boolean valid = true; int ownerSlot; int flushes; boolean validOwner({player} p) {{ return valid; }} int ownerInventorySlot() {{ return ownerSlot; }} void flush() {{ flushes++; }} void refresh() {{}} }}
class Base {{ int clicks, moves; public void {clicked}(int slot,int button,{action} a,{player} p) {{ clicks++; }} public ItemStack {quick}({player} p,int slot) {{ moves++; return new ItemStack(); }} }}
class Menu extends Base {{ HeldInventory data = new HeldInventory(); int lockedMenuSlot = 10;
{body}
}}
public class Harness {{ public static void main(String[] args) {{
    Menu menu = new Menu(); {player} p = new {player}();
    for ({action} action : {action}.values()) menu.{clicked}(10,0,action,p);
    if (menu.clicks != 0 || menu.data.flushes != 0) throw new AssertionError("Owner slot was mutable");
    menu.data.ownerSlot = 0;
    menu.{clicked}(1,0,{action}.SWAP,p);
    menu.data.ownerSlot = 40;
    menu.{clicked}(1,40,{action}.SWAP,p);
    if (menu.clicks != 0) throw new AssertionError("Hotbar/offhand owner swap allowed");
    if (menu.{quick}(p,10) != ItemStack.EMPTY || menu.moves != 0) throw new AssertionError("Owner shift-click allowed");
    menu.data.valid = false;
    menu.{clicked}(1,1,{action}.PICKUP,p);
    menu.{quick}(p,1);
    if (menu.clicks != 0 || menu.moves != 0 || menu.data.flushes != 0) throw new AssertionError("Stale owner was mutable");
    menu.data.valid = true;
    menu.{clicked}(1,1,{action}.PICKUP,p);
    menu.{quick}(p,1);
    if (menu.clicks != 1 || menu.moves != 1 || menu.data.flushes != 2) throw new AssertionError("Normal transactions failed");
}} }}'''
                    # javac's public type filename requirement uses one isolated directory per backend.
                    folder = root / f'{loader}-exec'
                    folder.mkdir()
                    (folder / 'Harness.java').write_text(java)
                    result = subprocess.run(['javac', '-d', str(folder), str(folder / 'Harness.java')], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    subprocess.run(['java', '-cp', str(folder), 'Harness'], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_physical_owner_identity_and_original_hand_are_required(self):
        with project_dir() as root:
            source = _generate(root, 'fabric')
            body = _method(source, 'boolean validOwner(')
            java = '''class ItemStack { int count = 1; int getCount() { return count; } }
enum Hand { MAIN_HAND, OFF_HAND }
class PlayerInventory { int selectedSlot; }
class PlayerEntity { boolean alive = true, removed; ItemStack main, off; PlayerInventory inventory = new PlayerInventory(); boolean isAlive() { return alive; } boolean isRemoved() { return removed; } PlayerInventory getInventory() { return inventory; } ItemStack getStackInHand(Hand hand) { return hand == Hand.MAIN_HAND ? main : off; } }
class Owner { PlayerEntity ownerPlayer; Hand ownerHand = Hand.MAIN_HAND; ItemStack ownerStack; int selectedSlot;
''' + body + '''
}
public class Harness { public static void main(String[] args) {
    PlayerEntity p = new PlayerEntity(); Owner owner = new Owner(); owner.ownerPlayer = p; owner.ownerStack = p.main = new ItemStack();
    if (!owner.validOwner(p)) throw new AssertionError("Original owner rejected");
    p.main = new ItemStack(); if (owner.validOwner(p)) throw new AssertionError("Copy accepted"); p.main = owner.ownerStack;
    p.inventory.selectedSlot = 1; if (owner.validOwner(p)) throw new AssertionError("Changed hotbar slot accepted"); p.inventory.selectedSlot = 0;
    owner.ownerStack.count = 2; if (owner.validOwner(p)) throw new AssertionError("Stacked owner accepted"); owner.ownerStack.count = 1;
    p.alive = false; if (owner.validOwner(p)) throw new AssertionError("Dead player accepted"); p.alive = true;
    p.removed = true; if (owner.validOwner(p)) throw new AssertionError("Removed player accepted"); p.removed = false;
    if (owner.validOwner(new PlayerEntity())) throw new AssertionError("Other player accepted");
    owner.ownerHand = Hand.OFF_HAND; p.off = owner.ownerStack; p.inventory.selectedSlot = 3;
    if (!owner.validOwner(p)) throw new AssertionError("Legitimate offhand rejected");
    p.off = null; if (owner.validOwner(p)) throw new AssertionError("Dropped owner accepted");
} }'''
            (root / 'Harness.java').write_text(java)
            result = subprocess.run(['javac', '-d', str(root), str(root / 'Harness.java')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run(['java', '-cp', str(root), 'Harness'], check=True, capture_output=True, text=True)

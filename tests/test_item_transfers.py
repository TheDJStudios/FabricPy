"""Execute generated hand-transfer wrappers with the real storage implementation."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fabricpy.compiler.item_storage import write_item_storage_helpers
from fabricpy.compiler.item_transfers import write_item_transfer_helpers
from tests import test_item_storage as storage_tests


_PLAYER_STUBS = {
    'net/minecraft/world/InteractionHand.java': '''package net.minecraft.world;
public enum InteractionHand { MAIN_HAND, OFF_HAND }''',
    'net/minecraft/world/level/Level.java': '''package net.minecraft.world.level;
public class Level {public boolean isClientSide;}''',
    'net/minecraft/world/entity/player/Inventory.java': '''package net.minecraft.world.entity.player;
import java.util.*;import net.minecraft.world.item.ItemStack;
public class Inventory {public int dirty,capacity;public final List<ItemStack> received=new ArrayList<>();public void setChanged(){dirty++;}}''',
    'net/minecraft/world/entity/player/Player.java': '''package net.minecraft.world.entity.player;
import java.util.*;import net.minecraft.world.item.ItemStack;import net.minecraft.world.InteractionHand;import net.minecraft.world.level.Level;
public class Player {
 public ItemStack main=ItemStack.EMPTY,off=ItemStack.EMPTY;public boolean alive=true,removed;
 public final Inventory inventory=new Inventory();public final Level world=new Level();public final List<ItemStack> dropped=new ArrayList<>();
 public boolean isAlive(){return alive;}public boolean isRemoved(){return removed;}public Level level(){return world;}public Inventory getInventory(){return inventory;}
 public ItemStack getItemInHand(InteractionHand hand){return hand==InteractionHand.MAIN_HAND?main:off;}
 public boolean addItem(ItemStack stack){int n=Math.min(inventory.capacity,stack.getCount());if(n>0){inventory.received.add(stack.copyWithCount(n));inventory.capacity-=n;stack.shrink(n);}return stack.isEmpty();}
 public Object drop(ItemStack stack,boolean random){dropped.add(stack.copy());return null;}
}''',
}

_MAIN = '''import example.item.FabricPyItemStorage;import example.item.FabricPyItemTransfers;
import net.minecraft.world.item.*;import net.minecraft.world.entity.player.Player;import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.component.DataComponents;import net.minecraft.world.item.component.CustomData;import net.minecraft.nbt.CompoundTag;
public class TransferCheck {
 static void check(boolean ok){if(!ok)throw new AssertionError();}
 static void name(ItemStack stack,String name){CompoundTag tag=new CompoundTag();tag.putString("name",name);if(MODERN)stack.set(DataComponents.CUSTOM_DATA,CustomData.of(tag));else stack.setTag(tag);}
 static String name(ItemStack stack){return MODERN?stack.getOrDefault(DataComponents.CUSTOM_DATA,CustomData.EMPTY).copyTag().getString("name"):stack.getTag().getString("name");}
 static int total(java.util.List<ItemStack> list){return list.stream().mapToInt(ItemStack::getCount).sum();}
 public static void main(String[] args){
  Item bagItem=new Item(1),stone=new Item(64);BuiltInRegistries.ITEM.register("test:bag",bagItem);BuiltInRegistries.ITEM.register("minecraft:stone",stone);
  Player p=new Player();ItemStack bag=new ItemStack(bagItem);p.main=bag;p.off=new ItemStack(stone,20);name(p.off,"special");
  check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",7)==7);check(p.off.getCount()==13);check(FabricPyItemStorage.getSlotCount(bag,0)==7);check(p.inventory.dirty==1);
  check(name(FabricPyItemStorage.loadInventory(bag).get(0)).equals("special"));
  check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",0)==0);check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",-1)==0);
  check(FabricPyItemTransfers.insertFromHand(p,bag,"missing",1)==0);check(FabricPyItemTransfers.insertFromHand(p,bag,"main_hand",1)==0);check(p.inventory.dirty==1);
  p.world.isClientSide=true;check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",1)==0);check(!FabricPyItemTransfers.installFromHand(p,bag,"lens","off_hand"));check(FabricPyItemTransfers.extractToPlayer(p,bag,0,1)==0);p.world.isClientSide=false;
  p.alive=false;check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",1)==0);p.alive=true;
  p.removed=true;check(FabricPyItemTransfers.extractToPlayer(p,bag,0,1)==0);p.removed=false;
  check(FabricPyItemTransfers.insertFromHand(null,bag,"off_hand",1)==0);check(FabricPyItemTransfers.insertFromHand(p,null,"off_hand",1)==0);
  check(FabricPyItemTransfers.insertFromHand(p,bag.copy(),"off_hand",1)==0);bag.setCount(2);check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",1)==0);bag.setCount(1);
  check(p.off.getCount()==13&&FabricPyItemStorage.getSlotCount(bag,0)==7&&p.inventory.dirty==1);
  p.inventory.capacity=2;check(FabricPyItemTransfers.extractToPlayer(p,bag,0,5)==5);check(total(p.inventory.received)==2&&total(p.dropped)==3);check(FabricPyItemStorage.getSlotCount(bag,0)==2);
  check(name(p.inventory.received.get(0)).equals("special")&&name(p.dropped.get(0)).equals("special"));check(p.off.getCount()+total(p.inventory.received)+total(p.dropped)+FabricPyItemStorage.getSlotCount(bag,0)==20);
  check(FabricPyItemTransfers.extractToPlayer(p,bag,0,99)==2);check(FabricPyItemTransfers.extractToPlayer(p,bag,0,1)==0);check(total(p.dropped)==5);
  check(FabricPyItemTransfers.installFromHand(p,bag,"lens","off_hand"));check(p.off.getCount()==12);check(!FabricPyItemTransfers.installFromHand(p,bag,"lens","off_hand"));check(p.off.getCount()==12);
  check(!FabricPyItemTransfers.installFromHand(p,bag,"core","main_hand"));check(!FabricPyItemTransfers.installFromHand(p,bag,"core","missing"));
  p.world.isClientSide=true;check(!FabricPyItemTransfers.removeToPlayer(p,bag,"lens"));check(FabricPyItemStorage.hasAttachment(bag,"lens"));p.world.isClientSide=false;
  check(FabricPyItemTransfers.removeToPlayer(p,bag,"lens"));check(!FabricPyItemTransfers.removeToPlayer(p,bag,"lens"));check(total(p.dropped)==6&&name(p.dropped.get(p.dropped.size()-1)).equals("special"));
  check(p.off.getCount()+total(p.inventory.received)+total(p.dropped)==20);
  p.off=new ItemStack(stone,64);check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",64)==64);p.off=new ItemStack(stone,64);check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",64)==64);
  p.off=new ItemStack(stone,9);int dirty=p.inventory.dirty;check(FabricPyItemTransfers.insertFromHand(p,bag,"off_hand",9)==0);check(p.off.getCount()==9&&p.inventory.dirty==dirty);
  System.out.print("transfer invariants passed");
 }
}'''


class ItemTransferTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_server_authority_conservation_metadata_and_full_inventory(self):
        for modern in (False, True):
            loader = 'neoforge' if modern else 'forge'
            version = '1.21.1' if modern else '1.20.1'
            with self.subTest(loader=loader), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name, source in {**storage_tests._STUBS, **_PLAYER_STUBS}.items():
                    if name.endswith('/ItemStack.java'):
                        source = source.replace('public void grow(int n)', 'public void setCount(int n){count=n;}public void grow(int n)')
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source)
                mod = storage_tests.ItemStorageTests()._mod(version, loader)
                write_item_storage_helpers(mod, root / 'example', 'example', loader)
                write_item_transfer_helpers(mod, root / 'example', 'example', loader)
                (root / 'TransferCheck.java').write_text(_MAIN.replace('MODERN', 'true' if modern else 'false'))
                result = subprocess.run(['javac', '-d', str(root / 'classes'), *map(str, root.rglob('*.java'))], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run(['java', '-cp', str(root / 'classes'), 'TransferCheck'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'transfer invariants passed')

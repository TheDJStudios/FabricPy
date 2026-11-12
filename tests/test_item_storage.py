import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fabricpy as mc
from fabricpy.compiler.item_storage import write_item_storage_helpers


# A small deterministic model of Minecraft's value/copy APIs lets the generated
# Java's transfer algorithm execute without launching a game or downloading jars.
# Separate compile smoke checks against actual mapped classes are also documented.
_STUBS = {
'net/minecraft/resources/ResourceLocation.java': '''package net.minecraft.resources;
public record ResourceLocation(String id) {
 public static ResourceLocation tryParse(String id) { return id != null && id.matches("[a-z0-9_]+:[a-z0-9_]+") ? new ResourceLocation(id) : null; }
 public String toString() { return id; }
}''',
'net/minecraft/core/registries/BuiltInRegistries.java': '''package net.minecraft.core.registries;
import java.util.*; import net.minecraft.world.item.Item; import net.minecraft.resources.ResourceLocation;
public class BuiltInRegistries { public static final Registry ITEM=new Registry();
 public static class Registry { private final Map<ResourceLocation,Item> items=new HashMap<>();
 public void register(String id,Item item){items.put(ResourceLocation.tryParse(id),item);}
 public boolean containsKey(ResourceLocation id){return items.containsKey(id);}
 public Item get(ResourceLocation id){return items.get(id);}
 public ResourceLocation getKey(Item item){return items.entrySet().stream().filter(e->e.getValue()==item).findFirst().get().getKey();}
 }}''',
'net/minecraft/core/NonNullList.java': '''package net.minecraft.core;
public class NonNullList<T> extends java.util.ArrayList<T> {
 public static <T> NonNullList<T> withSize(int size,T value){NonNullList<T> list=new NonNullList<>();for(int i=0;i<size;i++)list.add(value);return list;}
}''',
'net/minecraft/nbt/CompoundTag.java': '''package net.minecraft.nbt;
import java.util.*;
public class CompoundTag {
 private final Map<String,Object> entries=new HashMap<>();
 public void put(String k,Object v){entries.put(k,v);} public boolean contains(String k){return entries.containsKey(k);}
 public void putString(String k,String v){put(k,v);} public String getString(String k){return entries.get(k) instanceof String s?s:"";}
 public void putInt(String k,int v){put(k,v);} public int getInt(String k){return entries.get(k) instanceof Number n?n.intValue():0;}
 public void putBoolean(String k,boolean v){put(k,v);} public boolean getBoolean(String k){return Boolean.TRUE.equals(entries.get(k));}
 public void putDouble(String k,double v){put(k,v);} public double getDouble(String k){return entries.get(k) instanceof Number n?n.doubleValue():0;}
 public CompoundTag getCompound(String k){return entries.get(k) instanceof CompoundTag t?t:new CompoundTag();}
 public ListTag getList(String k,int type){return entries.get(k) instanceof ListTag t?t:new ListTag();}
 public boolean isEmpty(){return entries.isEmpty();} public Set<String> getAllKeys(){return entries.keySet();} public void remove(String k){entries.remove(k);}
 public CompoundTag copy(){CompoundTag copy=new CompoundTag();entries.forEach((k,v)->copy.put(k,v instanceof CompoundTag t?t.copy():v instanceof ListTag l?l.copy():v));return copy;}
 public boolean equals(Object v){return v instanceof CompoundTag t&&entries.equals(t.entries);} public int hashCode(){return entries.hashCode();}
}''',
'net/minecraft/nbt/ListTag.java': '''package net.minecraft.nbt;
public class ListTag extends java.util.ArrayList<CompoundTag> {public CompoundTag getCompound(int i){return get(i);} public ListTag copy(){ListTag c=new ListTag();for(CompoundTag t:this)c.add(t.copy());return c;}}''',
'net/minecraft/core/component/DataComponentType.java': '''package net.minecraft.core.component;
public class DataComponentType<T> {}''',
'net/minecraft/core/component/DataComponents.java': '''package net.minecraft.core.component;
import net.minecraft.world.item.component.*;
public class DataComponents {public static final DataComponentType<CustomData> CUSTOM_DATA=new DataComponentType<>();public static final DataComponentType<ItemContainerContents> CONTAINER=new DataComponentType<>();public static final DataComponentType<Object> BUNDLE_CONTENTS=new DataComponentType<>(),CONTAINER_LOOT=new DataComponentType<>();}''',
'net/minecraft/world/item/component/CustomData.java': '''package net.minecraft.world.item.component;
import net.minecraft.nbt.CompoundTag;
public final class CustomData {public static final CustomData EMPTY=new CustomData(new CompoundTag());private final CompoundTag tag;private CustomData(CompoundTag tag){this.tag=tag.copy();}public static CustomData of(CompoundTag tag){return new CustomData(tag);}public CompoundTag copyTag(){return tag.copy();}public boolean equals(Object other){return other instanceof CustomData d&&tag.equals(d.tag);} public int hashCode(){return tag.hashCode();}}''',
'net/minecraft/world/item/component/ItemContainerContents.java': '''package net.minecraft.world.item.component;
import net.minecraft.world.item.ItemStack;import net.minecraft.core.NonNullList;import java.util.*;
public final class ItemContainerContents {public static final ItemContainerContents EMPTY=new ItemContainerContents(List.of());private final List<ItemStack> items;private ItemContainerContents(List<ItemStack> items){this.items=new ArrayList<>();for(ItemStack s:items)this.items.add(s.copy());}public static ItemContainerContents fromItems(List<ItemStack> items){return new ItemContainerContents(items);}public void copyInto(NonNullList<ItemStack> out){for(int i=0;i<out.size();i++)out.set(i,i<items.size()?items.get(i).copy():ItemStack.EMPTY);}}''',
'net/minecraft/world/item/Item.java': '''package net.minecraft.world.item;
public class Item {public final int max;public Item(int max){this.max=max;}public boolean canFitInsideContainerItems(){return true;}}''',
'net/minecraft/world/item/BundleItem.java': '''package net.minecraft.world.item;
public class BundleItem extends Item {public BundleItem(){super(1);}}''',
'net/minecraft/world/item/ItemStack.java': '''package net.minecraft.world.item;
import java.util.*;import net.minecraft.core.component.*;import net.minecraft.nbt.*;import net.minecraft.core.registries.BuiltInRegistries;import net.minecraft.resources.ResourceLocation;
public class ItemStack {
 public static final ItemStack EMPTY=new ItemStack(null,0);private final Item item;private int count;private CompoundTag tag;private Map<DataComponentType<?>,Object> components=new HashMap<>();
 public ItemStack(Item item){this(item,1);}public ItemStack(Item item,int count){this.item=item;this.count=count;}
 public boolean isEmpty(){return item==null||count<=0;}public int getCount(){return isEmpty()?0:count;}public Item getItem(){return item;}public int getMaxStackSize(){return item.max;}
 public void grow(int n){count+=n;}public void shrink(int n){count=Math.max(0,count-n);}public ItemStack split(int n){if(n<=0||isEmpty())return EMPTY;int amount=Math.min(n,count);ItemStack result=copyWithCount(amount);shrink(amount);return result;}
 public ItemStack copy(){return copyWithCount(getCount());}public ItemStack copyWithCount(int n){if(isEmpty()||n<=0)return EMPTY;ItemStack result=new ItemStack(item,n);result.tag=tag==null?null:tag.copy();result.components=new HashMap<>(components);return result;}
 public boolean hasTag(){return tag!=null;}public CompoundTag getTag(){return tag;}public void setTag(CompoundTag tag){this.tag=tag;}
 public <T>T getOrDefault(DataComponentType<T> type,T fallback){return (T)components.getOrDefault(type,fallback);}public <T>void set(DataComponentType<T> type,T value){components.put(type,value);}public boolean has(DataComponentType<?> type){return components.containsKey(type);}public void remove(DataComponentType<?> type){components.remove(type);}
 public static boolean isSameItemSameTags(ItemStack a,ItemStack b){return a.item==b.item&&Objects.equals(a.tag,b.tag);}public static boolean isSameItemSameComponents(ItemStack a,ItemStack b){return a.item==b.item&&Objects.equals(a.components,b.components);}
 public CompoundTag save(CompoundTag out){out.putString("id",BuiltInRegistries.ITEM.getKey(item).toString());out.putInt("count",getCount());if(tag!=null)out.put("tag",tag.copy());return out;}
 public static ItemStack of(CompoundTag in){Item item=BuiltInRegistries.ITEM.get(ResourceLocation.tryParse(in.getString("id")));ItemStack result=new ItemStack(item,in.getInt("count"));if(in.contains("tag"))result.tag=in.getCompound("tag").copy();return result;}
}''',
}

_MAIN = '''import example.item.FabricPyItemStorage;
import net.minecraft.world.item.*;import net.minecraft.core.registries.BuiltInRegistries;import net.minecraft.core.component.DataComponents;import net.minecraft.world.item.component.CustomData;import net.minecraft.nbt.CompoundTag;import java.util.*;
public class StorageCheck {
 static void check(boolean ok){if(!ok)throw new AssertionError();}
 static void fails(Runnable r){try{r.run();throw new AssertionError("expected validation failure");}catch(IllegalArgumentException|IndexOutOfBoundsException|IllegalStateException expected){}}
 static void name(ItemStack stack,String name){CompoundTag tag=new CompoundTag();tag.putString("name",name);if(MODERN)stack.set(DataComponents.CUSTOM_DATA,CustomData.of(tag));else stack.setTag(tag);}
 static String name(ItemStack stack){return MODERN?stack.getOrDefault(DataComponents.CUSTOM_DATA,CustomData.EMPTY).copyTag().getString("name"):stack.getTag().getString("name");}
 public static void main(String[] args){
  Item bagItem=new Item(1),stone=new Item(64),diamond=new Item(64);BuiltInRegistries.ITEM.register("test:bag",bagItem);BuiltInRegistries.ITEM.register("minecraft:stone",stone);BuiltInRegistries.ITEM.register("minecraft:diamond",diamond);
  ItemStack splitBag=new ItemStack(bagItem),first=new ItemStack(stone,20),second=new ItemStack(stone,64);
  check(FabricPyItemStorage.space(splitBag,"minecraft:stone")==128);
  check(FabricPyItemStorage.insert(splitBag,first)==20);check(FabricPyItemStorage.insert(splitBag,second)==64&&second.isEmpty());
  check(FabricPyItemStorage.getSlotCount(splitBag,0)==64&&FabricPyItemStorage.getSlotCount(splitBag,1)==20);check(FabricPyItemStorage.space(splitBag,"minecraft:stone")==44);
  ItemStack bag=new ItemStack(bagItem),offered=new ItemStack(stone,64);name(offered,"named");
  FabricPyItemStorage.setInt(bag,"count",12);FabricPyItemStorage.setString(bag,"label","saved");FabricPyItemStorage.setBool(bag,"enabled",true);FabricPyItemStorage.setFloat(bag,"charge",1.5);
  check(FabricPyItemStorage.getInt(bag.copy(),"count")==12);check(FabricPyItemStorage.getString(bag,"label").equals("saved"));check(FabricPyItemStorage.getBool(bag,"enabled"));check(FabricPyItemStorage.getFloat(bag,"charge")==1.5);FabricPyItemStorage.removeData(bag,"count");check(!FabricPyItemStorage.containsData(bag,"count"));fails(()->FabricPyItemStorage.setFloat(bag,"bad",Double.NaN));
  check(FabricPyItemStorage.insert(bag,offered)==64&&offered.isEmpty());check(FabricPyItemStorage.count(bag,"minecraft:stone")==64);
  ItemStack other=new ItemStack(stone,64);name(other,"different");check(FabricPyItemStorage.insert(bag,other)==64);check(FabricPyItemStorage.count(bag,"minecraft:stone")==128);
  ItemStack blocked=new ItemStack(stone);check(FabricPyItemStorage.insert(bag,blocked)==0&&blocked.getCount()==1);
  var copy=FabricPyItemStorage.loadInventory(bag,2);copy.get(0).shrink(10);check(FabricPyItemStorage.getSlotCount(bag,0)==64);
  ItemStack removed=FabricPyItemStorage.extract(bag,0,2);check(removed.getCount()==2&&name(removed).equals("named"));check(FabricPyItemStorage.getSlotCount(bag,0)==62);
  ItemStack refill=new ItemStack(stone,3);name(refill,"named");check(FabricPyItemStorage.insert(bag,refill)==2&&refill.getCount()==1);check(FabricPyItemStorage.contains(bag,"minecraft:stone",128));
  fails(()->FabricPyItemStorage.extract(bag,-1,1));fails(()->FabricPyItemStorage.extract(bag,0,-2));fails(()->FabricPyItemStorage.count(bag,"missing:item"));fails(()->FabricPyItemStorage.setSlot(bag,0,"minecraft:stone",1));check(!FabricPyItemStorage.canStore(bag,bag));check(FabricPyItemStorage.insert(bag,new ItemStack(bagItem))==0);
  var bad=FabricPyItemStorage.loadInventory(bag);bad.set(0,bag);fails(()->FabricPyItemStorage.saveInventory(bag,bad));check(FabricPyItemStorage.count(bag,"minecraft:stone")==128);
  ItemStack attachment=new ItemStack(diamond,5);name(attachment,"enchanted lens");check(FabricPyItemStorage.installAttachment(bag,"lens",attachment));check(attachment.getCount()==4);check(!FabricPyItemStorage.installAttachment(bag,"lens",attachment));check(attachment.getCount()==4);
  FabricPyItemStorage.getAttachment(bag,"lens").shrink(1);check(FabricPyItemStorage.hasAttachment(bag,"lens"));FabricPyItemStorage.saveInventory(bag,FabricPyItemStorage.loadInventory(bag));check(FabricPyItemStorage.hasAttachment(bag,"lens"));
  ItemStack loaded=bag.copy();ItemStack lens=FabricPyItemStorage.removeAttachment(loaded,"lens");check(lens.getCount()==1&&name(lens).equals("enchanted lens"));check(FabricPyItemStorage.removeAttachment(loaded,"lens").isEmpty());check(!FabricPyItemStorage.hasAttachment(loaded,"lens"));check(FabricPyItemStorage.hasAttachment(bag,"lens"));
  fails(()->FabricPyItemStorage.installAttachment(bag,"unknown",attachment));check(attachment.getCount()==4);check(FabricPyItemStorage.count(loaded,"minecraft:stone")==128);
  ItemStack plain=new ItemStack(stone,64);FabricPyItemStorage.setInt(plain,"quality",7);check(FabricPyItemStorage.getInt(plain.copy(),"quality")==7);
  FabricPyItemStorage.removeData(plain,"quality");ItemStack unmodified=new ItemStack(stone,64);check(MODERN?ItemStack.isSameItemSameComponents(plain,unmodified):ItemStack.isSameItemSameTags(plain,unmodified));
  ItemStack empty=FabricPyItemStorage.removeSlot(loaded,0);check(empty.getCount()==64);check(FabricPyItemStorage.space(loaded,"minecraft:stone")==64);
  System.out.print("storage invariants passed");
 }
}'''


class ItemStorageTests(unittest.TestCase):
    def _mod(self, version, loader):
        mod = mc.Mod('test', 'Test', minecraft_version=version, loader=loader)
        @mod.register
        class Bag(mc.Item):
            item_id = 'bag'
            max_stack_size = 1
            inventory_size = 2
            attachment_slots = ('lens', 'core')
        return mod

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_generated_storage_transfers_preserve_metadata_and_counts(self):
        for modern in (False, True):
            with self.subTest(modern=modern), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name, source in _STUBS.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source)
                write_item_storage_helpers(self._mod('1.21.1' if modern else '1.20.1', 'neoforge' if modern else 'forge'), root / 'example', 'example', 'neoforge' if modern else 'forge')
                (root / 'StorageCheck.java').write_text(_MAIN.replace('MODERN', 'true' if modern else 'false'))
                sources = [str(p) for p in root.rglob('*.java')]
                result = subprocess.run(['javac', '-d', str(root / 'classes'), *sources], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run(['java', '-cp', str(root / 'classes'), 'StorageCheck'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'storage invariants passed')

    def test_backend_serialization_and_modern_nbt_accessors(self):
        for loader, version in [('fabric', '1.20.1'), ('quilt', '1.20.1'), ('fabric', '1.21.1'), ('fabric', '1.21.5'), ('forge', '1.20.1'), ('neoforge', '1.21.1')]:
            with self.subTest(loader=loader, version=version), tempfile.TemporaryDirectory() as temp:
                write_item_storage_helpers(self._mod(version, loader), Path(temp), 'example', loader)
                source = (Path(temp) / 'item/FabricPyItemStorage.java').read_text()
                self.assertNotIn('@', source)
                if version == '1.20.1':
                    self.assertIn('entry.put("Stack",', source)
                    self.assertNotIn('CUSTOM_DATA', source)
                else:
                    self.assertIn('CUSTOM_DATA', source)
                    self.assertIn('.CONTAINER,', source)
                if version == '1.21.5':
                    self.assertIn('getCompoundOrEmpty(DATA_KEY)', source)
                    self.assertIn('getString(key, "")', source)

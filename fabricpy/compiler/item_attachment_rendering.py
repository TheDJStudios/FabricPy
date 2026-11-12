"""Native item attachment rendering backed by stored ItemStacks and static base proxies."""
from __future__ import annotations

import json
import math
from pathlib import Path


def attachment_items(mod) -> list:
    return [item for item in mod._items if getattr(item, "attachment_slots", ())]


def _slots(item) -> list[str]:
    return list(getattr(item, "attachment_slots", ()))


def attachment_proxy_id(item) -> str:
    return f"{item.item_id}__base"


def attachment_proxy_constant(item) -> str:
    return f"{item.item_id.upper()}__BASE"


def validate_attachment_rendering(mod, item) -> None:
    if not getattr(item, "attachment_slots", ()):
        if getattr(item, "attachment_models", {}):
            raise ValueError(f"{item.__name__}: attachment_models requires attachment_slots")
        return
    if mod.minecraft_version not in {"1.20.1", "1.21", "1.21.1"}:
        raise ValueError("Visible item attachments currently support Minecraft 1.20.1, 1.21 and 1.21.1")
    models = getattr(item, "attachment_models", {})
    if not isinstance(models, dict):
        raise ValueError(f"{item.__name__}: attachment_models must be a dictionary")
    unknown = set(models) - set(_slots(item))
    if unknown:
        raise ValueError(f"{item.__name__}: attachment_models has undeclared slots {sorted(unknown)!r}")
    for name in _slots(item):
        transform = models.get(name, {})
        if not isinstance(transform, dict) or set(transform) - {"position", "rotation", "scale"}:
            raise ValueError(f"{item.__name__}: slot {name!r} accepts position, rotation and scale transforms")
        for key, default in (("position", [0, 0, 0]), ("rotation", [0, 0, 0]), ("scale", [1, 1, 1])):
            values = transform.get(key, default)
            if not isinstance(values, (list, tuple)) or len(values) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError(f"{item.__name__}: {name}.{key} must contain three finite numbers")
            if key == "scale" and any(v <= 0 for v in values):
                raise ValueError(f"{item.__name__}: {name}.scale must be positive")


def attachment_proxy_registrations(mod, loader_name: str) -> list[str]:
    fabric = loader_name in {"fabric", "quilt"}
    result = []
    for item in attachment_items(mod):
        identifier = json.dumps(attachment_proxy_id(item))
        constant = attachment_proxy_constant(item)
        if fabric:
            result.append(f"    public static final Item {constant} = register({identifier}, new Item(new Item.Settings().maxCount(1)));")
        else:
            result.append(f"    public static final java.util.function.Supplier<Item> {constant} = ITEMS.register({identifier}, () -> new Item(new Item.Properties().stacksTo(1)));")
    return result


def attachment_item_client_extension(mod, item, pkg: str, loader_name: str) -> str:
    if not getattr(item, "attachment_slots", ()) or loader_name != "forge":
        return ""
    return f"""    @Override
    public void initializeClient(java.util.function.Consumer<net.minecraftforge.client.extensions.common.IClientItemExtensions> consumer) {{
        consumer.accept(new net.minecraftforge.client.extensions.common.IClientItemExtensions() {{
            @Override
            public net.minecraft.client.renderer.BlockEntityWithoutLevelRenderer getCustomRenderer() {{
                return {pkg}.client.render.FabricPyAttachmentRenderer.instance();
            }}
        }});
    }}"""


def attachment_client_init_statement(mod, loader_name: str) -> str:
    if not attachment_items(mod) or loader_name not in {"fabric", "quilt"}:
        return ""
    return "ModAttachmentRenderers.register();"


def _item_ref(item, fabric: bool) -> str:
    return f"ModItems.{item.item_id.upper()}" + ("" if fabric else ".get()")


def _proxy_ref(item, fabric: bool) -> str:
    return f"ModItems.{attachment_proxy_constant(item)}" + ("" if fabric else ".get()")


def _slot_render_code(item, pkg: str, fabric: bool) -> str:
    lines = []
    models = getattr(item, "attachment_models", {})
    for index, name in enumerate(_slots(item)):
        transform = models.get(name, {})
        position = transform.get("position", [0, 0, 0])
        rotation = transform.get("rotation", [0, 0, 0])
        scale = transform.get("scale", [1, 1, 1])
        stack_name = f"attachment{index}"
        lines.append(f"            ItemStack {stack_name} = {pkg}.item.FabricPyItemStorage.getAttachment(owner, {json.dumps(name)});")
        lines.append(f"            if (!{stack_name}.isEmpty()) {{")
        lines.append("                matrices.push();" if fabric else "                matrices.pushPose();")
        lines.append(f"                matrices.translate({float(position[0])}, {float(position[1])}, {float(position[2])});")
        for axis, value in zip("XYZ", rotation):
            if value:
                if fabric:
                    lines.append(f"                matrices.multiply(net.minecraft.util.math.RotationAxis.POSITIVE_{axis}.rotationDegrees({float(value)}f));")
                else:
                    lines.append(f"                matrices.mulPose(com.mojang.math.Axis.{axis}P.rotationDegrees({float(value)}f));")
        lines.append(f"                matrices.scale({float(scale[0])}f, {float(scale[1])}f, {float(scale[2])}f);")
        if fabric:
            lines.append(f"                renderer.renderItem({stack_name}, ModelTransformationMode.NONE, light, overlay, matrices, consumers, client.world, 0);")
            lines.append("                matrices.pop();")
        else:
            lines.append(f"                renderer.renderStatic({stack_name}, ItemDisplayContext.NONE, light, overlay, matrices, consumers, client.level, 0);")
            lines.append("                matrices.popPose();")
        lines.append("            }")
    return "\n".join(lines)


def write_attachment_renderer(mod, java_root: Path, pkg: str, loader_name: str) -> bool:
    items = attachment_items(mod)
    if not items:
        return False
    for item in items:
        validate_attachment_rendering(mod, item)
    if loader_name not in {"fabric", "quilt", "forge", "neoforge"}:
        raise ValueError(f"Visible item attachments have no native renderer for loader {loader_name!r}")
    fabric = loader_name in {"fabric", "quilt"}
    render_dir = java_root / "client/render"
    render_dir.mkdir(parents=True, exist_ok=True)
    condition = "owner.isOf" if fabric else "owner.is"
    proxy_cases = "\n".join(f"        if ({condition}({_item_ref(item, fabric)})) return {_proxy_ref(item, fabric)};" for item in items)
    attachment_cases = "\n".join(f"        if ({condition}({_item_ref(item, fabric)})) {{\n{_slot_render_code(item, pkg, fabric)}\n        }}" for item in items)
    if fabric:
        source = f"""package {pkg}.client.render;

import {pkg}.ModItems;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.render.item.ItemRenderer;
import net.minecraft.client.render.model.BakedModel;
import net.minecraft.client.render.model.json.ModelTransformationMode;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.item.Item;
import net.minecraft.item.Items;
import net.minecraft.item.ItemStack;

public final class FabricPyAttachmentRenderer {{
    private static final ThreadLocal<Integer> DEPTH = ThreadLocal.withInitial(() -> 0);
    private static Item baseItem(ItemStack owner) {{
{proxy_cases}
        return Items.AIR;
    }}
    public static void render(ItemStack owner, ModelTransformationMode mode, MatrixStack matrices, VertexConsumerProvider consumers, int light, int overlay) {{
        int depth = DEPTH.get();
        if (depth >= 8) return;
        DEPTH.set(depth + 1);
        matrices.push();
        try {{
            MinecraftClient client = MinecraftClient.getInstance();
            ItemRenderer renderer = client.getItemRenderer();
            Item base = baseItem(owner);
            if (base == Items.AIR) return;
            BakedModel model = renderer.getModels().getModel(base);
            BakedModel override = model.getOverrides().apply(model, owner, client.world, null, 0);
            if (override != null) model = override;
            if (model.isBuiltin()) return;
            matrices.translate(0.5, 0.5, 0.5);
            boolean left = mode == ModelTransformationMode.FIRST_PERSON_LEFT_HAND || mode == ModelTransformationMode.THIRD_PERSON_LEFT_HAND;
            model.getTransformation().getTransformation(mode).apply(left, matrices);
            renderer.renderItem(owner, ModelTransformationMode.NONE, false, matrices, consumers, light, overlay, model);
{attachment_cases}
        }} finally {{
            matrices.pop();
            DEPTH.set(depth);
        }}
    }}
}}
"""
    else:
        source = f"""package {pkg}.client.render;

import {pkg}.ModItems;
import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.BlockEntityWithoutLevelRenderer;
import net.minecraft.client.renderer.MultiBufferSource;
import net.minecraft.client.renderer.entity.ItemRenderer;
import net.minecraft.client.resources.model.BakedModel;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.ItemDisplayContext;

public final class FabricPyAttachmentRenderer extends BlockEntityWithoutLevelRenderer {{
    private static FabricPyAttachmentRenderer INSTANCE;
    private static final ThreadLocal<Integer> DEPTH = ThreadLocal.withInitial(() -> 0);
    private FabricPyAttachmentRenderer() {{
        super(Minecraft.getInstance().getBlockEntityRenderDispatcher(), Minecraft.getInstance().getEntityModels());
    }}
    public static FabricPyAttachmentRenderer instance() {{
        if (INSTANCE == null) INSTANCE = new FabricPyAttachmentRenderer();
        return INSTANCE;
    }}
    private static Item baseItem(ItemStack owner) {{
{proxy_cases}
        return Items.AIR;
    }}
    @Override
    public void renderByItem(ItemStack owner, ItemDisplayContext mode, PoseStack matrices, MultiBufferSource consumers, int light, int overlay) {{
        int depth = DEPTH.get();
        if (depth >= 8) return;
        DEPTH.set(depth + 1);
        matrices.pushPose();
        try {{
            Minecraft client = Minecraft.getInstance();
            ItemRenderer renderer = client.getItemRenderer();
            Item base = baseItem(owner);
            if (base == Items.AIR) return;
            BakedModel model = renderer.getItemModelShaper().getItemModel(new ItemStack(base));
            BakedModel override = model.getOverrides().resolve(model, owner, client.level, null, 0);
            if (override != null) model = override;
            if (model.isCustomRenderer()) return;
            matrices.translate(0.5, 0.5, 0.5);
            boolean left = mode == ItemDisplayContext.FIRST_PERSON_LEFT_HAND || mode == ItemDisplayContext.THIRD_PERSON_LEFT_HAND;
            model.getTransforms().getTransform(mode).apply(left, matrices);
            renderer.render(owner, ItemDisplayContext.NONE, false, matrices, consumers, light, overlay, model);
{attachment_cases}
        }} finally {{
            matrices.popPose();
            DEPTH.set(depth);
        }}
    }}
}}
"""
    (render_dir / "FabricPyAttachmentRenderer.java").write_text(source, encoding="utf-8")
    if fabric:
        registrations = "\n".join(f"        BuiltinItemRendererRegistry.INSTANCE.register({_item_ref(item, True)}, (BuiltinItemRendererRegistry.DynamicItemRenderer) {pkg}.client.render.FabricPyAttachmentRenderer::render);" for item in items)
        registration_source = f"""package {pkg}.client;
import {pkg}.ModItems;
import net.fabricmc.fabric.api.client.rendering.v1.BuiltinItemRendererRegistry;
public final class ModAttachmentRenderers {{
    public static void register() {{
{registrations}
    }}
}}
"""
    elif loader_name == "neoforge":
        registrations = ", ".join(_item_ref(item, False) for item in items)
        registration_source = f"""package {pkg}.client;
import {pkg}.ModItems;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.neoforge.client.extensions.common.IClientItemExtensions;
import net.neoforged.neoforge.client.extensions.common.RegisterClientExtensionsEvent;
@EventBusSubscriber(modid = {json.dumps(mod.mod_id)}, bus = EventBusSubscriber.Bus.MOD, value = Dist.CLIENT)
public final class ModAttachmentRenderers {{
    @SubscribeEvent
    public static void register(RegisterClientExtensionsEvent event) {{
        event.registerItem(new IClientItemExtensions() {{
            @Override
            public net.minecraft.client.renderer.BlockEntityWithoutLevelRenderer getCustomRenderer() {{
                return {pkg}.client.render.FabricPyAttachmentRenderer.instance();
            }}
        }}, {registrations});
    }}
}}
"""
    else:
        registration_source = None
    if registration_source:
        (java_root / "client/ModAttachmentRenderers.java").write_text(registration_source, encoding="utf-8")
    return True


def write_attachment_resources(mod, res_root: Path) -> None:
    """Capture final source models after normal/manual resources, then wrap owners."""
    for item in attachment_items(mod):
        validate_attachment_rendering(mod, item)
        model_dir = res_root / "assets" / mod.mod_id / "models/item"
        source = model_dir / f"{item.item_id}.json"
        try:
            model = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot prepare attachment base model {source}: {exc}") from exc
        if not isinstance(model, dict):
            raise ValueError(f"{source}: item model must be a JSON object")
        if model.get("parent", "").removeprefix("minecraft:") == "builtin/entity":
            raise ValueError(f"{item.__name__}: attachment base must be a baked JSON/.bbmodel, not another builtin/entity renderer")
        proxy = model_dir / f"{attachment_proxy_id(item)}.json"
        proxy.write_text(json.dumps(model, indent=2), encoding="utf-8")
        wrapper = {"parent": "builtin/entity"}
        if "gui_light" in model:
            wrapper["gui_light"] = model["gui_light"]
        elif model.get("parent") in {"minecraft:item/generated", "minecraft:item/handheld", "item/generated", "item/handheld"}:
            wrapper["gui_light"] = "front"
        source.write_text(json.dumps(wrapper, indent=2), encoding="utf-8")

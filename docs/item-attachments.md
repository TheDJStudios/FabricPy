# Visible item attachments

Declare named attachment slots on an item to render the installed physical item
stacks alongside its base model:

```python
@mod.register
class CustomTool(mc.Item):
    item_id = "custom_tool"
    max_stack_size = 1
    texture = "custom_tool"
    attachment_slots = ("scope", "charm")
    attachment_models = {
        "scope": {
            "position": [0, 0.5, 0],
            "rotation": [0, 0, 0],
            "scale": [0.4, 0.4, 0.4],
        },
        "charm": {
            "position": [0.2, -0.3, 0],
            "rotation": [0, 0, 25],
            "scale": [0.25, 0.25, 0.25],
        },
    }
```

Each slot renders the actual installed `ItemStack`, including its item model and
stack metadata. Empty slots draw nothing. Installation, removal and item transfer
use the persistent item-storage APIs; declaring a transform does not create or
duplicate an attachment item.

Positions use blocks relative to the parent model's center. Rotations use degrees
around X, Y and Z, applied in that order. Scale is a three-number positive scale.
A slot without an explicit transform defaults to position `[0,0,0]`, rotation
`[0,0,0]`, and scale `[1,1,1]`. Transforms apply in local model space after the
parent's display transform, so they follow the item in the player's hand, GUI,
ground and item frames. Attachment models render in their neutral model space;
their own GUI or hand display transforms do not move them off the parent.

## Rendering behavior

Fabric/Quilt use the native dynamic item-renderer registry. Forge uses native
client item extensions and a `BlockEntityWithoutLevelRenderer`. NeoForge 1.21.1
registers those extensions through its client registration event. No mixins or
resource-pack tricks are used to pretend that installed attachment models exist.

A hidden ordinary item named `<item_id>__base` carries the parent's original baked
model. The compiler captures the final model after copied resource overrides and
`.bbmodel` conversion, then routes the visible parent through a native renderer.
The proxy is not added to creative tabs. Reserve this generated item ID in your
project. It is an implementation detail and should not be used in recipes or
player inventories.

The renderer uses the original baked model's effective display transforms and the
real parent stack when drawing the base, preserving ordinary glint and stack
metadata. Normal model predicates and static custom models can still participate;
renderers supplied by another mod and pre-existing `builtin/entity` parent models
cannot be combined with this renderer. Such a direct parent produces an error.
An indirect model override that resolves to another custom renderer is skipped
to prevent recursion. A depth guard also limits nested attachment-renderer calls.

Visible attachment rendering currently targets Minecraft 1.20.1 (Fabric, Forge,
Quilt) and 1.21/1.21.1 (bundled Fabric, Forge and NeoForge targets as available).
Later Minecraft item-renderer changes require separate compatibility work and
produce an explicit unsupported-version error.

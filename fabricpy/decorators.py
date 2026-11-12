"""
Decorators that mark Python methods as Minecraft event hooks.
These get picked up by the compiler and translated to Java override methods.
Placement, break and use hooks default to the logical server. Pass side="client"
or side="both" explicitly for effects intended to run on those sides.
"""

def _mark(hook_type, **kwargs):
    """Internal: mark a function with a hook type."""
    def decorator(func):
        func._fabricpy_hook = hook_type
        func._fabricpy_hook_args = kwargs
        return func
    return decorator


def _sided_hook(hook_type, func, side):
    from fabricpy.compiler.hook_sides import validate_hook_side
    validate_hook_side(side)
    decorator = _mark(hook_type, side=side)
    return decorator(func) if func is not None else decorator


def on_use(func=None, *, side: str = "server"):
    """
    Block: Called when a player right-clicks the block.
    Maps to: onUse() / use() override.

    Java params available via ctx:
        ctx.player, ctx.world, ctx.pos, ctx.state, ctx.hand
    """
    return _sided_hook("on_use", func, side)


def on_right_click(func=None, *, side: str = "server"):
    """
    Item: Called when a player right-clicks with the item.
    Maps to: use() override.

    Java params available via ctx:
        ctx.player, ctx.world, ctx.stack, ctx.hand
    """
    return _sided_hook("on_right_click", func, side)


def on_place(func=None, *, side: str = "server"):
    """
    Block: Called when the block is placed.
    Maps to: onPlaced() override.

    Java params available via ctx:
        ctx.player, ctx.world, ctx.pos, ctx.state
    """
    return _sided_hook("on_place", func, side)


def on_break(func=None, *, side: str = "server"):
    """
    Block: Called when the block is broken.
    Maps to: onBreak() override.

    Java params available via ctx:
        ctx.player, ctx.world, ctx.pos, ctx.state
    """
    return _sided_hook("on_break", func, side)


def on_tick(func):
    """
    Block: Called every game tick while the block exists (requires BlockEntity).
    Maps to: tick() on the block entity.

    Java params available via ctx:
        ctx.world, ctx.pos, ctx.state
    """
    func._fabricpy_hook = "on_tick"
    func._fabricpy_hook_args = {}
    return func


def inject(method: str, at: str = "HEAD", cancellable: bool = False):
    """
    Mixin injection decorator.

    Args:
        method: Target method signature, e.g. "teleport(DDD)V"
        at: Injection point — "HEAD", "TAIL", or "INVOKE:..."
        cancellable: Whether to allow cancelling the original method via ci.cancel()

    Example:
        @mc.inject(method="teleport", at="HEAD", cancellable=True)
        def on_teleport(self, ctx):
            ctx.player.send_message("Teleporting!")
    """
    return _mark("inject", method=method, at=at, cancellable=cancellable)

"""Logical-side selection shared by loader hook generators."""
from __future__ import annotations

import textwrap


INTERACTION_EVENTS = frozenset({
    "player_use_item", "player_use_block", "player_attack_entity", "player_interact_entity",
})


def validate_hook_side(side: str) -> str:
    if side not in {"server", "client", "both"}:
        raise ValueError("hook side must be 'server', 'client', or 'both'")
    return side


def guard_hook_body(body: str, func, client_expression: str, *, side: str | None = None) -> str:
    """Guard Python effects, preserving the engine's superclass and result flow."""
    if side is None:
        side = getattr(func, "_fabricpy_hook_args", {}).get("side", "server")
    validate_hook_side(side)
    if side == "both":
        return body
    condition = client_expression if side == "client" else f"!{client_expression}"
    return f"        if ({condition}) {{\n" + textwrap.indent(body, "        ") + "\n        }"

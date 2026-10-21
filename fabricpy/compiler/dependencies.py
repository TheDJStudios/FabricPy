"""Shared dependency selection and build notation for loader backends."""
from __future__ import annotations

import json


def dependencies_for_loader(mod, loader: str) -> list:
    return [dep for dep in mod._dependencies if dep.loader in {loader, "both", "all", ""}]


def gradle_notation(dep) -> str:
    # JSON quoting also safely quotes paths in Groovy; escape interpolation.
    value = str(dep.path) if dep.path else dep.coordinate
    quoted = json.dumps(value.replace("\\", "/")).replace("$", "\\$")
    return f"files({quoted})" if dep.path else quoted

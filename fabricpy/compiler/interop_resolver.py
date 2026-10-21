"""
Interop symbol resolver for dependency namespaces.

This layer sits between the generated symbol index and the transpiler.
It is intentionally lightweight: it resolves dependency aliases, class names,
static methods, and static fields from the partial symbol index output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InteropCallResolution:
    kind: str
    java_path: str
    validated: bool
    reason: str = ""


class InteropResolver:
    def __init__(self):
        self.class_index: dict[str, dict] = {}
        self.class_by_alias: dict[str, set[str]] = {}
        self.details_by_alias: dict[str, dict[str, dict]] = {}

    @classmethod
    def from_index(cls, index_path: Path | None) -> "InteropResolver":
        resolver = cls()
        if not index_path:
            return resolver
        try:
            payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
        except Exception:
            return resolver

        for dependency in payload.get("dependencies", []):
            alias = dependency.get("alias", "")
            class_details = dependency.get("class_details", {})
            if not alias or not isinstance(class_details, dict):
                continue

            alias_set = resolver.class_by_alias.setdefault(alias, set())
            resolver.details_by_alias.setdefault(alias, {}).update(class_details)
            for class_name, detail in class_details.items():
                resolver.class_index[class_name] = detail
                alias_set.add(class_name)

        return resolver

    def resolve_dependency_path(self, dotted: str) -> str | None:
        """
        Resolve `dep.<alias>....` into a concrete Java path when possible.

        Returns:
        - fully resolved Java class/member path when found
        - best-effort package/class path when only alias stripping is possible
        - None for non-dependency paths
        """
        if not dotted.startswith("dep."):
            return None

        parts = dotted.split(".")
        if len(parts) < 4:
            return None

        alias = parts[1]
        java_parts = parts[2:]
        known_classes = self.class_by_alias.get(alias, set())

        for size in range(len(java_parts), 0, -1):
            class_candidate = ".".join(java_parts[:size])
            if class_candidate not in known_classes:
                continue

            detail = self.details_by_alias.get(alias, {}).get(class_candidate, {})
            remainder = java_parts[size:]
            if not remainder:
                return class_candidate

            member_name = remainder[0]
            if self._has_member(detail, member_name):
                tail = ".".join(remainder)
                return f"{class_candidate}.{tail}"

            # Unknown member after a known class: still emit the candidate path,
            # but keep the remainder attached for best-effort passthrough.
            return f"{class_candidate}.{'.'.join(remainder)}"

        return ".".join(java_parts)

    def resolve_dependency_call(self, dotted: str, arg_count: int) -> InteropCallResolution | None:
        if not dotted.startswith("dep."):
            return None

        parts = dotted.split(".")
        if len(parts) < 3:
            return None

        alias = parts[1]
        java_parts = parts[2:]
        known_classes = self.class_by_alias.get(alias, set())

        for size in range(len(java_parts), 0, -1):
            class_candidate = ".".join(java_parts[:size])
            if class_candidate not in known_classes:
                continue

            detail = self.details_by_alias.get(alias, {}).get(class_candidate, {})
            remainder = java_parts[size:]
            if not remainder:
                matched_ctor = self._match_method(detail, "__init__", arg_count, constructor=True)
                return InteropCallResolution(
                    kind="constructor",
                    java_path=class_candidate,
                    validated=matched_ctor is not None,
                    reason="" if matched_ctor else "constructor arity not confirmed by scanned symbol index",
                )

            if len(remainder) != 1:
                return InteropCallResolution(
                    kind="call",
                    java_path=f"{class_candidate}.{'.'.join(remainder)}",
                    validated=False,
                    reason="call chain extends past a scanned class/member boundary",
                )

            member_name = remainder[0]
            matched_static = self._match_method(detail, member_name, arg_count, static=True)
            if matched_static:
                return InteropCallResolution(
                    kind="static_method",
                    java_path=f"{class_candidate}.{member_name}",
                    validated=True,
                )

            matched_any = self._match_method(detail, member_name, arg_count, static=None)
            if matched_any:
                return InteropCallResolution(
                    kind="instance_method",
                    java_path=f"{class_candidate}.{member_name}",
                    validated=False,
                    reason="resolved member is an instance method; class-qualified call may be invalid",
                )

            return InteropCallResolution(
                kind="call",
                java_path=f"{class_candidate}.{member_name}",
                validated=False,
                reason="member arity not confirmed by scanned symbol index",
            )

        return InteropCallResolution(
            kind="call",
            java_path=".".join(java_parts),
            validated=False,
            reason="dependency path not found in scanned symbol index",
        )

    @staticmethod
    def _has_member(detail: dict, member_name: str) -> bool:
        for method in detail.get("methods", []):
            if method.get("name") == member_name:
                return True
        for field in detail.get("fields", []):
            if field.get("name") == member_name:
                return True
        return False

    @staticmethod
    def _match_method(detail: dict, member_name: str, arg_count: int, static: bool | None = None, constructor: bool = False) -> dict | None:
        for method in detail.get("methods", []):
            if method.get("name") != member_name:
                continue
            params = method.get("arg_types", [])
            varargs = bool(params and params[-1].endswith("..."))
            if (varargs and arg_count < len(params) - 1) or (not varargs and method.get("arg_count") != arg_count):
                continue
            if constructor and not method.get("constructor"):
                continue
            if static is not None and method.get("static") != static:
                continue
            return method
        return None

"""
Python → Java transpiler.

Supports a practical subset of Python that covers most modding use cases:
  - Variable assignment (var x = ...)
  - If / elif / else
  - For (range only) and while loops
  - Method calls, including ctx.player.* and ctx.world.* API calls
  - f-strings → Java string concatenation
  - Comparisons, boolean ops, arithmetic
  - Return statements
  - Pass (skipped)

Unsupported Python raises TranspileError with the source line so a build
cannot silently discard behavior.
"""

import ast
import json
import string
import textwrap
from pathlib import Path
from typing import Optional

from fabricpy.compiler.interop_resolver import InteropResolver


class TranspileError(ValueError):
    """Python that cannot be translated without changing its meaning."""


class JavaTranspiler:
    """Transpiles a Python function body to Java statements."""

    def __init__(self, api_map: dict, indent_spaces: int = 4, interop_index_path: Optional[Path] = None):
        self.api_map = api_map
        self.indent_spaces = indent_spaces
        self._lines: list[str] = []
        self._depth: int = 0
        self._interop_index_path = Path(interop_index_path) if interop_index_path else None
        self._interop_resolver = InteropResolver.from_index(self._interop_index_path)
        self._interop_notes: list[str] = []

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def transpile_method(self, source: str) -> str:
        """
        Given the source of a Python function (as a string), transpile its
        body to a Java code block (just the statements, no braces).
        """
        src = textwrap.dedent(source).strip()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            raise TranspileError(f"Invalid Python callback: {e}") from e

        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_node = node
                break

        if func_node is None:
            raise TranspileError("Expected a Python function definition")

        self._lines = []
        self._variables = {}
        self._string_variables = set()
        self._interop_notes = []
        self._depth = 1  # inside a Java method body = 1 indent level

        for stmt in func_node.body:
            self._stmt(stmt)

        if self._interop_notes:
            notes = [(" " * self.indent_spaces) + f"// interop: {note}" for note in self._interop_notes]
            return "\n".join(notes + self._lines)

        return "\n".join(self._lines)

    # ------------------------------------------------------------------ #
    # Statement dispatch
    # ------------------------------------------------------------------ #

    def _stmt(self, node: ast.AST):
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return  # docstring
            expr = self._expr(node.value)
            if expr:
                self._emit(f"{expr};")

        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                raise TranspileError(f"Line {node.lineno}: chained assignment is unsupported; split it into separate assignments")
            self._assign(node.targets[0], node.value)

        elif isinstance(node, ast.AugAssign):
            target = self._expr(node.target)
            value = self._expr(node.value)
            if isinstance(node.op, ast.FloorDiv):
                self._emit(f"{target} = Math.floorDiv({target}, {value});")
            elif isinstance(node.op, ast.Div):
                raise TranspileError(f"Line {node.lineno}: /= may change the inferred Java type; assign a division result to a new variable")
            else:
                op = self._binop(node.op)
                self._emit(f"{target} {op}= {value};")

        elif isinstance(node, ast.AnnAssign):
            if node.value:
                self._assign(node.target, node.value)

        elif isinstance(node, ast.Return):
            if node.value:
                self._emit(f"return {self._expr(node.value)};")
            else:
                self._emit("return;")

        elif isinstance(node, ast.If):
            self._if(node)

        elif isinstance(node, ast.For):
            self._for(node)

        elif isinstance(node, ast.While):
            if node.orelse:
                raise TranspileError(f"Line {node.lineno}: while/else is unsupported")
            cond = self._expr(node.test)
            self._emit(f"while ({cond}) {{")
            self._depth += 1
            for s in node.body:
                self._stmt(s)
            self._depth -= 1
            self._emit("}")

        elif isinstance(node, ast.Pass):
            pass  # intentionally skip

        elif isinstance(node, ast.Break):
            self._emit("break;")

        elif isinstance(node, ast.Continue):
            self._emit("continue;")

        elif isinstance(node, ast.Delete):
            raise TranspileError(f"Line {node.lineno}: del is unsupported")

        else:
            raise TranspileError(f"Line {getattr(node, 'lineno', '?')}: unsupported Python statement {type(node).__name__}")

    def _assign(self, target, value):
        if isinstance(target, (ast.Tuple, ast.List)):
            raise TranspileError(f"Line {target.lineno}: unpacking assignment is unsupported")
        name = self._expr(target)
        prefix = ""
        if isinstance(target, ast.Name) and name not in self._variables:
            if isinstance(value, ast.Constant) and value.value is None:
                raise TranspileError(f"Line {target.lineno}: cannot infer a Java type from None")
            prefix = "var "
            self._variables[name] = self._depth
        is_string = self._is_string(value)
        self._emit(f"{prefix}{name} = {self._expr(value)};")
        if isinstance(target, ast.Name):
            if is_string:
                self._string_variables.add(name)
            else:
                self._string_variables.discard(name)

    def _is_string(self, node):
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str)
        if isinstance(node, ast.Name):
            return node.id in self._string_variables
        if isinstance(node, ast.JoinedStr):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._is_string(node.left) or self._is_string(node.right)
        return False

    def _if(self, node: ast.If):
        cond = self._expr(node.test)
        self._emit(f"if ({cond}) {{")
        self._depth += 1
        for s in node.body:
            self._stmt(s)
        self._depth -= 1

        if node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                # elif
                inner = node.orelse[0]
                inner_cond = self._expr(inner.test)
                self._emit(f"}} else if ({inner_cond}) {{")
                self._depth += 1
                for s in inner.body:
                    self._stmt(s)
                self._depth -= 1
                # Handle further elif/else recursively but inline
                if inner.orelse:
                    self._if_orelse(inner.orelse)
                else:
                    self._emit("}")
            else:
                self._emit("} else {")
                self._depth += 1
                for s in node.orelse:
                    self._stmt(s)
                self._depth -= 1
                self._emit("}")
        else:
            self._emit("}")

    def _if_orelse(self, orelse: list):
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            inner = orelse[0]
            cond = self._expr(inner.test)
            self._emit(f"}} else if ({cond}) {{")
            self._depth += 1
            for s in inner.body:
                self._stmt(s)
            self._depth -= 1
            if inner.orelse:
                self._if_orelse(inner.orelse)
            else:
                self._emit("}")
        else:
            self._emit("} else {")
            self._depth += 1
            for s in orelse:
                self._stmt(s)
            self._depth -= 1
            self._emit("}")

    def _for(self, node: ast.For):
        if node.orelse:
            raise TranspileError(f"Line {node.lineno}: for/else is unsupported")
        if not isinstance(node.target, ast.Name):
            raise TranspileError(f"Line {node.lineno}: loop target must be a name")
        # range loops and Java iterables are supported.
        if (isinstance(node.iter, ast.Call) and
                isinstance(node.iter.func, ast.Name) and
                node.iter.func.id == "range"):

            var = self._expr(node.target)
            self._variables[var] = self._depth + 1
            args = [self._expr(a) for a in node.iter.args]

            if len(args) == 1:
                self._emit(f"for (int {var} = 0; {var} < {args[0]}; {var}++) {{")
            elif len(args) == 2:
                self._emit(f"for (int {var} = {args[0]}; {var} < {args[1]}; {var}++) {{")
            elif len(args) == 3:
                step_node = node.iter.args[2]
                try:
                    step = ast.literal_eval(step_node)
                except (ValueError, TypeError):
                    raise TranspileError(f"Line {node.lineno}: range step must be a nonzero integer literal")
                if not isinstance(step, int) or isinstance(step, bool) or step == 0:
                    raise TranspileError(f"Line {node.lineno}: range step must be a nonzero integer")
                compare = "<" if step > 0 else ">"
                self._emit(f"for (int {var} = {args[0]}; {var} {compare} {args[1]}; {var} += {args[2]}) {{")
            else:
                raise TranspileError(f"Line {node.lineno}: range expects 1 to 3 arguments")

            self._depth += 1
            for s in node.body:
                self._stmt(s)
            self._depth -= 1
            self._emit("}")
        else:
            # Best-effort: emit iterable as array-style
            var = self._expr(node.target)
            self._variables[var] = self._depth + 1
            it = self._expr(node.iter)
            self._emit(f"for (var {var} : {it}) {{")
            self._depth += 1
            for s in node.body:
                self._stmt(s)
            self._depth -= 1
            self._emit("}")

    # ------------------------------------------------------------------ #
    # Expression dispatch
    # ------------------------------------------------------------------ #

    def _expr(self, node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return self._const(node)

        elif isinstance(node, ast.Name):
            # Map Python True/False/None
            name_map = {"True": "true", "False": "false", "None": "null"}
            return name_map.get(node.id, node.id)

        elif isinstance(node, ast.Attribute):
            dotted = self._dotted(node)
            if dotted in self.api_map:
                return self.api_map[dotted]
            interop = self._resolve_interop_dotted(dotted)
            if interop:
                return interop
            return f"{self._expr(node.value)}.{node.attr}"

        elif isinstance(node, ast.Call):
            return self._call(node)

        elif isinstance(node, ast.BinOp):
            return self._binop_expr(node)

        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return f"!({self._expr(node.operand)})"
            elif isinstance(node.op, ast.USub):
                return f"-{self._expr(node.operand)}"
            elif isinstance(node.op, ast.UAdd):
                return self._expr(node.operand)
            elif isinstance(node.op, ast.Invert):
                return f"~({self._expr(node.operand)})"
            else:
                raise TranspileError(f"Line {node.lineno}: unsupported unary operator {type(node.op).__name__}")

        elif isinstance(node, ast.Compare):
            return self._compare(node)

        elif isinstance(node, ast.BoolOp):
            op = "&&" if isinstance(node.op, ast.And) else "||"
            return f" {op} ".join(f"({self._expr(v)})" for v in node.values)

        elif isinstance(node, ast.JoinedStr):
            return self._fstring(node)

        elif isinstance(node, ast.IfExp):
            # Ternary: a if cond else b
            t = self._expr(node.test)
            b = self._expr(node.body)
            o = self._expr(node.orelse)
            return f"({t} ? {b} : {o})"

        elif isinstance(node, ast.Subscript):
            val = self._expr(node.value)
            sl = self._expr(node.slice)
            return f"{val}[{sl}]"

        elif isinstance(node, ast.Tuple) or isinstance(node, ast.List):
            elts = ", ".join(self._expr(e) for e in node.elts)
            return f"new Object[] {{{elts}}}"

        elif isinstance(node, ast.NamedExpr):
            # Walrus operator :=
            target = self._expr(node.target)
            value = self._expr(node.value)
            return f"({target} = {value})"

        else:
            raise TranspileError(f"Line {getattr(node, 'lineno', '?')}: unsupported Python expression {type(node).__name__}")

    def _const(self, node: ast.Constant) -> str:
        if isinstance(node.value, str):
            return json.dumps(node.value, ensure_ascii=True)
        elif isinstance(node.value, bool):
            return "true" if node.value else "false"
        elif node.value is None:
            return "null"
        elif isinstance(node.value, float):
            return f"{node.value}f"
        else:
            return str(node.value)

    def _call(self, node: ast.Call) -> str:
        # Build dotted signature for API map lookup
        sig = self._dotted(node.func)
        args = [self._expr(a) for a in node.args]
        if any(kw.arg is None for kw in node.keywords):
            raise TranspileError(f"Line {node.lineno}: **keyword expansion is unsupported")
        kwargs = {kw.arg: self._expr(kw.value) for kw in node.keywords if kw.arg}

        if isinstance(node.func, ast.Name):
            builtin = node.func.id
            if builtin == "str" and len(args) == 1:
                return f"String.valueOf({args[0]})"
            if builtin == "int" and len(args) == 1:
                return f"((int) ({args[0]}))"
            if builtin == "float" and len(args) == 1:
                return f"((float) ({args[0]}))"
            if builtin == "bool" and len(args) == 1:
                raise TranspileError(f"Line {node.lineno}: bool() requires type information; use an explicit comparison")

        if sig in self.api_map:
            template = self.api_map[sig]
            fields = {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}
            unused_positions = [index for index in range(len(args)) if str(index) not in fields]
            unused_keywords = set(kwargs) - fields
            if unused_positions or unused_keywords:
                raise TranspileError(f"Line {node.lineno}: wrong arguments for {sig}; unexpected argument(s)")
            try:
                return template.format(*args, **kwargs)
            except (IndexError, KeyError) as exc:
                raise TranspileError(f"Line {node.lineno}: wrong arguments for {sig}") from exc

        interop_call = self._interop_resolver.resolve_dependency_call(sig, len(node.args))
        if interop_call:
            if kwargs:
                raise TranspileError(f"Line {node.lineno}: Java dependency calls require positional arguments")
            if interop_call.reason:
                note = f"{sig} -> {interop_call.java_path}: {interop_call.reason}"
                if note not in self._interop_notes:
                    self._interop_notes.append(note)
            if interop_call.kind == "constructor":
                return f"new {interop_call.java_path}({', '.join(args)})"
            return f"{interop_call.java_path}({', '.join(args)})"

        # Generic call — not in API map
        func = self._expr(node.func)
        for kw in node.keywords:
            if kw.arg:
                args.append(f"/* {kw.arg}= */ {self._expr(kw.value)}")
        return f"{func}({', '.join(args)})"

    def _dotted(self, node: ast.AST) -> str:
        """Produce dotted string representation of a call target."""
        if isinstance(node, ast.Attribute):
            return f"{self._dotted(node.value)}.{node.attr}"
        elif isinstance(node, ast.Name):
            return node.id
        return ""

    def _resolve_interop_dotted(self, dotted: str) -> Optional[str]:
        return self._interop_resolver.resolve_dependency_path(dotted)

    def _binop_expr(self, node: ast.BinOp) -> str:
        left = self._expr(node.left)
        right = self._expr(node.right)
        if isinstance(node.op, ast.Pow):
            return f"Math.pow({left}, {right})"
        if isinstance(node.op, ast.FloorDiv):
            return f"Math.floorDiv({left}, {right})"
        if isinstance(node.op, ast.Div):
            return f"(((double) ({left})) / ({right}))"
        op = self._binop(node.op)

        # Python string concat with + → Java string concat
        if isinstance(node.op, ast.Add):
            return f"({left} + {right})"
        return f"({left} {op} {right})"

    def _binop(self, op: ast.operator) -> str:
        operators = {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*",
            ast.Div: "/", ast.Mod: "%", ast.FloorDiv: "/",
            ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
            ast.LShift: "<<", ast.RShift: ">>",
        }
        if type(op) not in operators:
            raise TranspileError(f"Unsupported Python operator {type(op).__name__}")
        return operators[type(op)]

    def _compare(self, node: ast.Compare) -> str:
        cmp_ops = {
            ast.Is: "==", ast.IsNot: "!=",
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=",
        }
        left_node = node.left
        left = self._expr(left_node)
        parts = []
        for op, comp in zip(node.ops, node.comparators):
            java_op = cmp_ops.get(type(op))
            if java_op is None:
                raise TranspileError(f"Line {node.lineno}: unsupported comparison {type(op).__name__}")
            right = self._expr(comp)
            # String equality: use .equals() for String literals
            if isinstance(op, (ast.Eq, ast.NotEq)) and (self._is_string(left_node) or self._is_string(comp)):
                equality = f"java.util.Objects.equals({left}, {right})"
                parts.append(f"!{equality}" if isinstance(op, ast.NotEq) else equality)
            else:
                parts.append(f"{left} {java_op} {right}")
            left_node = comp
            left = self._expr(comp)
        return " && ".join(parts)

    def _fstring(self, node: ast.JoinedStr) -> str:
        """Convert Python f-string to Java String.format or concatenation."""
        parts = []
        for val in node.values:
            if isinstance(val, ast.Constant):
                parts.append(json.dumps(val.value, ensure_ascii=True))
            elif isinstance(val, ast.FormattedValue):
                if val.format_spec or val.conversion not in {-1, 115}:
                    raise TranspileError("Formatted f-strings support plain values and !s only")
                parts.append(f"String.valueOf({self._expr(val.value)})")
        if not parts:
            return '""'
        return "(" + " + ".join(parts) + ")"

    # ------------------------------------------------------------------ #
    # Emit helper
    # ------------------------------------------------------------------ #

    def _emit(self, line: str):
        if line.startswith("}"):
            self._variables = {name: depth for name, depth in self._variables.items() if depth <= self._depth}
            self._string_variables.intersection_update(self._variables)
        indent = " " * (self.indent_spaces * self._depth)
        self._lines.append(indent + line)

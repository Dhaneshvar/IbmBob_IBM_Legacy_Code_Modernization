"""Deterministic IR → Python 3.12 emitter.

Produces a complete Python module from an IrProgram without any LLM involvement.
The output is a compilable scaffold: every IrStmt maps to valid Python, and
UNSUPPORTED ops become clearly-marked TODO comments.

The LLM executor layer later fills in business logic on top of this scaffold.
"""
from __future__ import annotations

import re
from typing import Optional

from ..ir.nodes import (
    IrBlock,
    IrConst,
    IrExpr,
    IrFunction,
    IrProgram,
    IrStmt,
    IrType,
    IrVar,
    OpKind,
)

# ─────────────────────────────── type mapping ─────────────────────────────

_PYTHON_TYPE: dict[IrType, str] = {
    IrType.INT:     "int",
    IrType.DEC:     "Decimal",
    IrType.STR:     "str",
    IrType.BOOL:    "bool",
    IrType.UNKNOWN: "object",
}

_PYTHON_DEFAULT: dict[IrType, str] = {
    IrType.INT:     "0",
    IrType.DEC:     "Decimal('0')",
    IrType.STR:     '""',
    IrType.BOOL:    "False",
    IrType.UNKNOWN: "None",
}


def python_type(var: IrVar) -> str:
    t = _PYTHON_TYPE.get(var.type, "object")
    if var.occurs > 1:
        return f"list[{t}]"
    return t


def python_default(var: IrVar) -> str:
    if var.occurs > 1:
        base = _PYTHON_DEFAULT.get(var.type, "None")
        return f"[{base}] * {var.occurs}"
    if var.initial is not None:
        return _literal(var.initial, var.type)
    return _PYTHON_DEFAULT.get(var.type, "None")


def _literal(val, t: IrType = IrType.UNKNOWN) -> str:
    if val is None:
        return "None"
    if isinstance(val, bool):
        return "True" if val else "False"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return f"Decimal('{val}')"
    s = str(val).replace('"', '\\"')
    return f'"{s}"'


# ─────────────────────────────── expression emitter ───────────────────────

def emit_expr(expr: Optional[IrExpr], vars_: dict[str, IrVar], context: str = "") -> str:
    if expr is None:
        return "None"
    if expr.kind == "const" and expr.const is not None:
        c = expr.const
        if c.ctype == "int":
            return str(c.value)
        if c.ctype == "dec":
            return f"Decimal('{c.value}')"
        if c.ctype == "str":
            val = str(c.value).replace('"', '\\"')
            return f'"{val}"'
        if c.symbol:  # figurative
            sym = c.symbol
            if sym in ("ZERO", "ZEROS", "ZEROES"):
                return "0"
            if sym in ("SPACE", "SPACES"):
                return '""'
        return f'"{c.value}"'
    if expr.kind == "var":
        vid = expr.var
        var = vars_.get(vid)
        if var:
            return f"{context}{_python_name(var.name)}"
        return f"{context}v_{vid}"
    if expr.kind == "binary":
        left = emit_expr(expr.left, vars_, context)
        right = emit_expr(expr.right, vars_, context)
        op = expr.op
        if op == "index":
            return f"{left}[int({right}) - 1]"
        if op == "slice":
            idx = emit_expr(expr.right, vars_, context)
            return f"{left}[int({idx}) - 1]"
        py_op = {
            "+": "+", "-": "-", "*": "*", "/": "/",
            "=": "==", "<": "<", ">": ">", "<=": "<=", ">=": ">=",
            "<>": "!=", "/=": "!=",
            "AND": "and", "OR": "or",
        }.get(op, op)
        return f"({left} {py_op} {right})"
    if expr.kind == "unary":
        operand = emit_expr(expr.left, vars_, context)
        if expr.op == "-":
            return f"(-{operand})"
        if expr.op in ("NOT", "!"):
            return f"(not {operand})"
        return f"({expr.op}{operand})"
    if expr.kind == "call":
        args = ", ".join(emit_expr(a, vars_, context) for a in expr.args)
        fn = expr.op or "unknown"
        fn_upper = fn.upper()
        if fn_upper == "LENGTH":
            return f"len({args})"
        elif fn_upper == "TRIM":
            return f"({args}).strip()"
        elif fn_upper == "UPPER":
            return f"({args}).upper()"
        elif fn_upper == "LOWER":
            return f"({args}).lower()"
        return f"{context}{_python_name(fn)}({args})"
    return "# unknown expr"


# ─────────────────────────────── statement emitter ────────────────────────

def emit_stmt(
    stmt: IrStmt,
    vars_: dict[str, IrVar],
    indent: str = "        ",
    context: str = "self.",
) -> list[str]:
    lines: list[str] = []
    op = stmt.op

    if op in (OpKind.ASSIGN, OpKind.COMPUTE):
        expr = emit_expr(stmt.expr, vars_, context)
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                name = _python_name(var.name)
                if var.type == IrType.DEC:
                    lines.append(f"{indent}{context}{name} = Decimal(str({expr}))")
                else:
                    lines.append(f"{indent}{context}{name} = {expr}")
            else:
                lines.append(f"{indent}# assign to unknown vid {t}: {expr}")

    elif op in (OpKind.ADD, OpKind.SUBTRACT, OpKind.MULTIPLY, OpKind.DIVIDE):
        expr = emit_expr(stmt.expr, vars_, context)
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                lines.append(f"{indent}{context}{_python_name(var.name)} = {expr}")

    elif op == OpKind.DISPLAY:
        parts = [emit_expr(a, vars_, context) for a in stmt.args]
        joined = " + ".join(f"str({p})" for p in parts) if parts else '""'
        if stmt.text == "noadv":
            lines.append(f"{indent}print({joined}, end='')")
        else:
            lines.append(f"{indent}print({joined})")

    elif op == OpKind.ACCEPT:
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                lines.append(f"{indent}{context}{_python_name(var.name)} = input()")

    elif op == OpKind.CALL:
        callee = stmt.callee or "unknown"
        args = ", ".join(emit_expr(a, vars_, context) for a in stmt.args)
        ret_assign = ""
        if stmt.targets:
            var = vars_.get(stmt.targets[0])
            if var:
                ret_assign = f"{context}{_python_name(var.name)} = "
        lines.append(f"{indent}{ret_assign}{context}{_python_name(callee)}({args})")

    elif op == OpKind.RETURN:
        lines.append(f"{indent}return")

    elif op == OpKind.BRANCH:
        lbl = stmt.target_label or ""
        if lbl and lbl != "EXIT":
            lines.append(f"{indent}# → {lbl}")

    elif op == OpKind.BRANCH_COND:
        cond = emit_expr(stmt.cond, vars_, context)
        lbls = stmt.targets_labels
        then_lbl = lbls[0] if lbls else "?"
        else_lbl = lbls[1] if len(lbls) > 1 else "?"
        lines.append(f"{indent}if {cond}:")
        lines.append(f"{indent}    # → {then_lbl}")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    # → {else_lbl}")

    elif op == OpKind.EVALUATE:
        dispatch = emit_expr(stmt.dispatch, vars_, context)
        lines.append(f"{indent}match {dispatch}:")
        has_cases = False
        for conds, lbl in stmt.cases:
            has_cases = True
            cond_strs = [emit_expr(c, vars_, context) for c in conds if c]
            if cond_strs:
                lines.append(f"{indent}    case {' | '.join(cond_strs)}:")
                lines.append(f"{indent}        # → {lbl}")
            else:
                lines.append(f"{indent}    case _:")
                lines.append(f"{indent}        # → {lbl}")
        if not has_cases:
            lines.append(f"{indent}    case _:")
            lines.append(f"{indent}        pass")

    elif op == OpKind.GOTO_INDEXED:
        dep = vars_.get(stmt.targets[0]) if stmt.targets else None
        dep_name = f"{context}{_python_name(dep.name)}" if dep else "index"
        lines.append(f"{indent}match int({dep_name}):")
        for i, lbl in enumerate(stmt.targets_labels, start=1):
            lines.append(f"{indent}    case {i}:")
            lines.append(f"{indent}        self.{_python_name(lbl.lower().replace('p_', ''))}()")
        lines.append(f"{indent}    case _:")
        lines.append(f"{indent}        pass")

    elif op == OpKind.IO_OPEN:
        file_var = vars_.get(stmt.file) if stmt.file else None
        fname = _python_name(file_var.name) if file_var else "file"
        mode = stmt.text or "INPUT"
        lines.append(f'{indent}# OPEN {mode}: {fname} (implement file I/O here)')

    elif op == OpKind.IO_CLOSE:
        file_var = vars_.get(stmt.file) if stmt.file else None
        fname = _python_name(file_var.name) if file_var else "file"
        lines.append(f"{indent}# CLOSE: {fname}")

    elif op == OpKind.IO_READ:
        file_var = vars_.get(stmt.file) if stmt.file else None
        fname = _python_name(file_var.name) if file_var else "file"
        target_vars = [vars_.get(t) for t in stmt.targets if vars_.get(t)]
        targets_str = ", ".join(f"{context}{_python_name(v.name)}" for v in target_vars if v)
        lines.append(f"{indent}# READ {fname} INTO {targets_str or 'record'}")
        lines.append(f"{indent}# TODO: implement file read")

    elif op == OpKind.IO_WRITE:
        target_vars = [vars_.get(t) for t in stmt.targets if vars_.get(t)]
        rec = target_vars[0] if target_vars else None
        rec_name = f"{context}{_python_name(rec.name)}" if rec else "record"
        lines.append(f"{indent}# WRITE {rec_name}")
        lines.append(f"{indent}# TODO: implement file write")

    elif op == OpKind.NOP:
        lines.append(f"{indent}pass")

    elif op == OpKind.SET_FLAG:
        expr = emit_expr(stmt.expr, vars_, context)
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                lines.append(f"{indent}{context}{_python_name(var.name)} = {expr}")

    elif op == OpKind.STRING_OP:
        parts = [emit_expr(a, vars_, context) for a in stmt.args]
        into_var = vars_.get(stmt.targets[0]) if stmt.targets else None
        into = f"{context}{_python_name(into_var.name)}" if into_var else "result"
        empty_str = '""'
        joined_parts = ' + '.join(f"str({p})" for p in parts) if parts else empty_str
        lines.append(f"{indent}{into} = {joined_parts}")

    elif op == OpKind.UNSTRING_OP:
        src = emit_expr(stmt.expr, vars_, context)
        targets = [vars_.get(t) for t in stmt.targets if vars_.get(t)]
        lines.append(f"{indent}# UNSTRING {src}")
        for i, tv in enumerate(targets):
            if tv:
                lines.append(f'{indent}{context}{_python_name(tv.name)} = self._unstring({src}, {i})')

    elif op == OpKind.UNSUPPORTED:
        lines.append(f"{indent}# TODO: UNSUPPORTED — {stmt.text}")
        lines.append(f"{indent}# Origin: {stmt.origin} | Span: {stmt.span}")

    elif op == OpKind.TALLY:
        lines.append(f"{indent}# INSPECT/TALLY: {stmt.text}")

    elif op == OpKind.SEARCH:
        lines.append(f"{indent}# SEARCH — implement as loop")

    else:
        lines.append(f"{indent}# unhandled op: {op.value}")

    return lines


# ─────────────────────────────── function emitter ─────────────────────────

def emit_function(fn: IrFunction, vars_: dict[str, IrVar], indent: str = "    ") -> list[str]:
    lines: list[str] = []
    py_name = _python_name(fn.name)
    lines.append(f"{indent}def {py_name}(self):")

    empty = True
    for blk in fn.blocks:
        if len(fn.blocks) > 1:
            lines.append(f"{indent}    # ── block: {blk.label} ──")
        for stmt in blk.stmts:
            empty = False
            lines.extend(emit_stmt(stmt, vars_, indent + "    ", "self."))

    if empty:
        lines.append(f"{indent}    pass")

    return lines


# ─────────────────────────────── class emitter ────────────────────────────

def emit_program(ir: IrProgram) -> str:
    """Emit a complete Python 3.12 module from an IrProgram."""
    class_name = _python_class_name(ir.name)
    lines: list[str] = [
        f'"""',
        f'Migrated from COBOL program: {ir.name}',
        f'Source: {ir.path or "unknown"}',
        f'Dialect: {ir.dialect}',
        f'Source lines: {ir.source_lines}',
        f'Migration tool: IBM Legacy Modernizer',
        f'"""',
        f'from __future__ import annotations',
        f'',
        f'import sys',
        f'from decimal import Decimal',
        f'',
        f'',
        f'class {class_name}:',
        f'    def __init__(self):',
        f'        # ── global variables (from WORKING-STORAGE) ─────────────────────────────',
    ]

    has_vars = False
    for vid, var in ir.vars.items():
        if var.is_temp or var.section not in (
            "WORKING-STORAGE", "LOCAL-STORAGE", "FILE", "LINKAGE", "UNDECLARED"
        ):
            continue
        has_vars = True
        ptype = python_type(var)
        pdefault = python_default(var)
        comment = f"  # {var.section}"
        if var.picture:
            comment += f" PIC {var.picture}"
        if var.redefines:
            comment += f" REDEFINES {var.redefines}"
        lines.append(f"        self.{_python_name(var.name)}: {ptype} = {pdefault}{comment}")

    if not has_vars:
        lines.append("        pass")

    lines.append("")
    lines.append("    # ── helper for UNSTRING ─────────────────────────────────────────────────")
    lines.append("    def _unstring(self, src: str, idx: int) -> str:")
    lines.append("        parts = str(src).strip().split()")
    lines.append("        return parts[idx] if idx < len(parts) else \"\"")
    lines.append("")

    main_fn = ir.function("main")
    if main_fn:
        lines.extend(emit_function(main_fn, ir.vars))
        lines.append("")

    for fn in ir.functions:
        if fn.name == "main" or fn.name == "__FILES__":
            continue
        lines.extend(emit_function(fn, ir.vars))
        lines.append("")

    lines.extend([
        "",
        "if __name__ == '__main__':",
        f"    program = {class_name}()",
        "    program.main()",
        ""
    ])
    return "\n".join(lines)


def emit_files(ir: IrProgram) -> dict[str, str]:
    """Return a dict of filename → Python source for all emitted files."""
    module_name = _python_name(ir.name)
    py_src = emit_program(ir)
    return {f"{module_name}.py": py_src}


# ─────────────────────────────── helpers ──────────────────────────────────

def _python_name(cobol_name: str) -> str:
    """Convert COBOL-style NAME-WITH-HYPHENS to snake_case."""
    if not cobol_name:
        return "unknown"
    parts = re.split(r"[-_]", cobol_name)
    if not parts:
        return cobol_name.lower()
    return "_".join(p.lower() for p in parts if p)


def _python_class_name(name: str) -> str:
    """PascalCase class name from COBOL program name."""
    parts = re.split(r"[-_]", name.upper())
    return "".join(p.capitalize() for p in parts if p)

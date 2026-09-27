"""Deterministic IR → Java 17 emitter.

Produces a complete Java class from an IrProgram without any LLM involvement.
The output is a compilable scaffold: every IrStmt maps to valid Java, and
UNSUPPORTED ops become clearly-marked TODO comments.

The LLM executor layer later fills in business logic on top of this scaffold.
"""
from __future__ import annotations

import re
import textwrap
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

_JAVA_TYPE: dict[IrType, str] = {
    IrType.INT:     "long",
    IrType.DEC:     "java.math.BigDecimal",
    IrType.STR:     "String",
    IrType.BOOL:    "boolean",
    IrType.UNKNOWN: "Object",
}

_JAVA_DEFAULT: dict[IrType, str] = {
    IrType.INT:     "0L",
    IrType.DEC:     "java.math.BigDecimal.ZERO",
    IrType.STR:     '""',
    IrType.BOOL:    "false",
    IrType.UNKNOWN: "null",
}


def java_type(var: IrVar) -> str:
    t = _JAVA_TYPE.get(var.type, "Object")
    if var.occurs > 1:
        t += "[]"
    return t


def java_default(var: IrVar) -> str:
    if var.occurs > 1:
        base = _JAVA_DEFAULT.get(var.type, "null")
        return f"new {_JAVA_TYPE.get(var.type, 'Object')}[{var.occurs}]"
    if var.initial is not None:
        return _literal(var.initial, var.type)
    return _JAVA_DEFAULT.get(var.type, "null")


def _literal(val, t: IrType = IrType.UNKNOWN) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return f"{val}L"
    if isinstance(val, float):
        return f"new java.math.BigDecimal(\"{val}\")"
    s = str(val).replace('"', '\\"')
    return f'"{s}"'


# ─────────────────────────────── expression emitter ───────────────────────

def emit_expr(expr: Optional[IrExpr], vars_: dict[str, IrVar]) -> str:
    if expr is None:
        return "null"
    if expr.kind == "const" and expr.const is not None:
        c = expr.const
        if c.ctype == "int":
            return f"{c.value}L"
        if c.ctype == "dec":
            return f"new java.math.BigDecimal(\"{c.value}\")"
        if c.ctype == "str":
            val = str(c.value).replace('"', '\\"')
            return f'"{val}"'
        if c.symbol:  # figurative
            sym = c.symbol
            if sym in ("ZERO", "ZEROS", "ZEROES"):
                return "0L"
            if sym in ("SPACE", "SPACES"):
                return '""'
        return f'"{c.value}"'
    if expr.kind == "var":
        vid = expr.var
        var = vars_.get(vid)
        if var:
            return _java_name(var.name)
        return f"v_{vid}"
    if expr.kind == "binary":
        left = emit_expr(expr.left, vars_)
        right = emit_expr(expr.right, vars_)
        op = expr.op
        if op == "index":
            return f"{left}[(int)({right}) - 1]"
        if op == "slice":
            idx = emit_expr(expr.right, vars_)
            return f"{left}[(int)({idx}) - 1]"
        java_op = {
            "+": "+", "-": "-", "*": "*", "/": "/",
            "=": "==", "<": "<", ">": ">", "<=": "<=", ">=": ">=",
            "<>": "!=", "/=": "!=",
            "AND": "&&", "OR": "||",
        }.get(op, op)
        return f"({left} {java_op} {right})"
    if expr.kind == "unary":
        operand = emit_expr(expr.left, vars_)
        if expr.op == "-":
            return f"(-{operand})"
        if expr.op in ("NOT", "!"):
            return f"(!{operand})"
        return f"({expr.op}{operand})"
    if expr.kind == "call":
        args = ", ".join(emit_expr(a, vars_) for a in expr.args)
        fn = expr.op or "unknown"
        java_fn = {
            "LENGTH": f"({args}).length()",
            "TRIM":   f"({args}).trim()",
            "UPPER":  f"({args}).toUpperCase()",
            "LOWER":  f"({args}).toLowerCase()",
        }.get(fn.upper(), f"{_java_name(fn.lower())}({args})")
        return java_fn
    return "/* unknown expr */"


# ─────────────────────────────── statement emitter ────────────────────────

def emit_stmt(
    stmt: IrStmt,
    vars_: dict[str, IrVar],
    indent: str = "        ",
) -> list[str]:
    lines: list[str] = []
    op = stmt.op

    if op in (OpKind.ASSIGN, OpKind.COMPUTE):
        expr = emit_expr(stmt.expr, vars_)
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                name = _java_name(var.name)
                # BigDecimal assignment needs special handling
                if var.type == IrType.DEC:
                    lines.append(f"{indent}{name} = new java.math.BigDecimal(String.valueOf({expr}));")
                else:
                    lines.append(f"{indent}{name} = {expr};")
            else:
                lines.append(f"{indent}// assign to unknown vid {t}: {expr}")

    elif op in (OpKind.ADD, OpKind.SUBTRACT, OpKind.MULTIPLY, OpKind.DIVIDE):
        expr = emit_expr(stmt.expr, vars_)
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                lines.append(f"{indent}{_java_name(var.name)} = {expr};")

    elif op == OpKind.DISPLAY:
        parts = [emit_expr(a, vars_) for a in stmt.args]
        joined = " + ".join(parts) if parts else '""'
        if stmt.text == "noadv":
            lines.append(f"{indent}System.out.print({joined});")
        else:
            lines.append(f"{indent}System.out.println({joined});")

    elif op == OpKind.ACCEPT:
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                lines.append(f"{indent}{_java_name(var.name)} = _scanner.nextLine();")

    elif op == OpKind.CALL:
        callee = stmt.callee or "unknown"
        args = ", ".join(emit_expr(a, vars_) for a in stmt.args)
        ret_assign = ""
        if stmt.targets:
            var = vars_.get(stmt.targets[0])
            if var:
                ret_assign = f"{_java_name(var.name)} = "
        lines.append(f"{indent}{ret_assign}{_java_name(callee.lower())}({args});")

    elif op == OpKind.RETURN:
        lines.append(f"{indent}return;")

    elif op == OpKind.BRANCH:
        lbl = stmt.target_label or ""
        if lbl and lbl != "EXIT":
            lines.append(f"{indent}// → {lbl}")

    elif op == OpKind.BRANCH_COND:
        cond = emit_expr(stmt.cond, vars_)
        lbls = stmt.targets_labels
        then_lbl = lbls[0] if lbls else "?"
        else_lbl = lbls[1] if len(lbls) > 1 else "?"
        lines.append(f"{indent}if ({cond}) {{")
        lines.append(f"{indent}    // → {then_lbl}")
        lines.append(f"{indent}}} else {{")
        lines.append(f"{indent}    // → {else_lbl}")
        lines.append(f"{indent}}}")

    elif op == OpKind.EVALUATE:
        dispatch = emit_expr(stmt.dispatch, vars_)
        lines.append(f"{indent}// EVALUATE {dispatch}")
        for conds, lbl in stmt.cases:
            cond_strs = [emit_expr(c, vars_) for c in conds if c]
            if cond_strs:
                lines.append(f"{indent}// WHEN {', '.join(cond_strs)} → {lbl}")
            else:
                lines.append(f"{indent}// WHEN OTHER → {lbl}")

    elif op == OpKind.GOTO_INDEXED:
        dep = vars_.get(stmt.targets[0]) if stmt.targets else None
        dep_name = _java_name(dep.name) if dep else "index"
        lines.append(f"{indent}switch ((int){dep_name}) {{")
        for i, lbl in enumerate(stmt.targets_labels, start=1):
            lines.append(f"{indent}    case {i}: {_java_name(lbl.lower().replace('p_', ''))}(); break;")
        lines.append(f"{indent}}}")

    elif op == OpKind.IO_OPEN:
        file_var = vars_.get(stmt.file) if stmt.file else None
        fname = _java_name(file_var.name.lower()) if file_var else "file"
        mode = stmt.text or "INPUT"
        lines.append(f'{indent}// OPEN {mode}: {fname} (implement file I/O here)')

    elif op == OpKind.IO_CLOSE:
        file_var = vars_.get(stmt.file) if stmt.file else None
        fname = _java_name(file_var.name.lower()) if file_var else "file"
        lines.append(f"{indent}// CLOSE: {fname}")

    elif op == OpKind.IO_READ:
        file_var = vars_.get(stmt.file) if stmt.file else None
        fname = _java_name(file_var.name.lower()) if file_var else "file"
        target_vars = [vars_.get(t) for t in stmt.targets if vars_.get(t)]
        targets_str = ", ".join(_java_name(v.name) for v in target_vars if v)
        lines.append(f"{indent}// READ {fname} INTO {targets_str or 'record'}")
        lines.append(f"{indent}// TODO: implement file read")

    elif op == OpKind.IO_WRITE:
        target_vars = [vars_.get(t) for t in stmt.targets if vars_.get(t)]
        rec = target_vars[0] if target_vars else None
        rec_name = _java_name(rec.name) if rec else "record"
        lines.append(f"{indent}// WRITE {rec_name}")
        lines.append(f"{indent}// TODO: implement file write")

    elif op == OpKind.NOP:
        lines.append(f"{indent}// CONTINUE (no-op)")

    elif op == OpKind.SET_FLAG:
        expr = emit_expr(stmt.expr, vars_)
        for t in stmt.targets:
            var = vars_.get(t)
            if var:
                lines.append(f"{indent}{_java_name(var.name)} = {expr};")

    elif op == OpKind.STRING_OP:
        parts = [emit_expr(a, vars_) for a in stmt.args]
        into_var = vars_.get(stmt.targets[0]) if stmt.targets else None
        into = _java_name(into_var.name) if into_var else "result"
        empty_str = '""'
        joined_parts = ' + '.join(parts) if parts else empty_str
        lines.append(f"{indent}{into} = {joined_parts};")

    elif op == OpKind.UNSTRING:
        src = emit_expr(stmt.expr, vars_)
        targets = [vars_.get(t) for t in stmt.targets if vars_.get(t)]
        lines.append(f"{indent}// UNSTRING {src}")
        for i, tv in enumerate(targets):
            if tv:
                lines.append(f'{indent}{_java_name(tv.name)} = _unstring({src}, {i});')

    elif op == OpKind.UNSUPPORTED:
        lines.append(f"{indent}// TODO: UNSUPPORTED — {stmt.text}")
        lines.append(f"{indent}// Origin: {stmt.origin} | Span: {stmt.span}")

    elif op == OpKind.TALLY:
        lines.append(f"{indent}// INSPECT/TALLY: {stmt.text}")

    elif op == OpKind.SEARCH:
        lines.append(f"{indent}// SEARCH — implement as loop")

    else:
        lines.append(f"{indent}// unhandled op: {op.value}")

    return lines


# ─────────────────────────────── function emitter ─────────────────────────

def emit_function(fn: IrFunction, vars_: dict[str, IrVar], indent: str = "    ") -> list[str]:
    lines: list[str] = []
    is_main = fn.kind == "main"
    access = "public static" if is_main else "private static"
    signature = (
        f"{indent}{access} void main(String[] args)"
        if is_main
        else f"{indent}{access} void {_java_name(fn.name.lower())}()"
    )
    lines.append(signature + " {")

    # collect all statements from all blocks in order
    for blk in fn.blocks:
        if len(fn.blocks) > 1:
            lbl_clean = blk.label.replace("-", "_").lower()
            lines.append(f"{indent}    // ── block: {blk.label} ──")
        for stmt in blk.stmts:
            lines.extend(emit_stmt(stmt, vars_, indent + "        " if is_main else indent + "    "))

    lines.append(f"{indent}}}")
    return lines


# ─────────────────────────────── class emitter ────────────────────────────

def emit_program(ir: IrProgram) -> str:
    """Emit a complete Java 17 class from an IrProgram."""
    class_name = _java_class_name(ir.name)
    lines: list[str] = [
        f"/**",
        f" * Migrated from COBOL program: {ir.name}",
        f" * Source: {ir.path or 'unknown'}",
        f" * Dialect: {ir.dialect}",
        f" * Source lines: {ir.source_lines}",
        f" * Migration tool: IBM Legacy Modernizer",
        f" */",
        f"public class {class_name} {{",
        "",
        "    // ── global variables (from WORKING-STORAGE) ─────────────────────────────",
    ]

    # Declare global variables
    for vid, var in ir.vars.items():
        if var.is_temp or var.section not in (
            "WORKING-STORAGE", "LOCAL-STORAGE", "FILE", "LINKAGE", "UNDECLARED"
        ):
            continue
        jtype = java_type(var)
        jdefault = java_default(var)
        comment = f"  // {var.section}"
        if var.picture:
            comment += f" PIC {var.picture}"
        if var.redefines:
            comment += f" REDEFINES {var.redefines}"
        lines.append(f"    private static {jtype} {_java_name(var.name)} = {jdefault};{comment}")

    lines.append("")
    lines.append("    // ── scanner for ACCEPT statements ──────────────────────────────────────")
    lines.append("    private static final java.util.Scanner _scanner = new java.util.Scanner(System.in);")
    lines.append("")
    lines.append("    // ── helper for UNSTRING ─────────────────────────────────────────────────")
    lines.append("    private static String _unstring(String src, int idx) {")
    lines.append("        String[] parts = src.trim().split(\"\\\\s+\");")
    lines.append("        return idx < parts.length ? parts[idx] : \"\";")
    lines.append("    }")
    lines.append("")

    # Emit functions (main first, then paragraphs)
    main_fn = ir.function("main")
    if main_fn:
        lines.extend(emit_function(main_fn, ir.vars))
        lines.append("")

    for fn in ir.functions:
        if fn.name == "main" or fn.name == "__FILES__":
            continue
        lines.extend(emit_function(fn, ir.vars))
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def emit_files(ir: IrProgram) -> dict[str, str]:
    """Return a dict of filename → Java source for all emitted files."""
    class_name = _java_class_name(ir.name)
    java_src = emit_program(ir)
    return {f"{class_name}.java": java_src}


# ─────────────────────────────── helpers ──────────────────────────────────

def _java_name(cobol_name: str) -> str:
    """Convert COBOL-style NAME-WITH-HYPHENS to javaStyleCamelCase."""
    if not cobol_name:
        return "unknown"
    parts = re.split(r"[-_]", cobol_name)
    if not parts:
        return cobol_name.lower()
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _java_class_name(name: str) -> str:
    """PascalCase class name from COBOL program name."""
    parts = re.split(r"[-_]", name.upper())
    return "".join(p.capitalize() for p in parts if p)

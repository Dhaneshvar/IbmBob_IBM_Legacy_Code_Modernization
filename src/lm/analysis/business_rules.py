from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..ir.nodes import (
    IrProgram,
    IrFunction,
    IrStmt,
    OpKind,
    IrExpr,
)

@dataclass
class BusinessRule:
    rule_id: str
    category: str  # validation | calculation | decision | accumulation | io | workflow
    description: str  # Natural language description
    source_function: str
    source_spans: list[str]  # COBOL source references
    variables_involved: list[str]  # Variable names
    conditions: list[str]  # Condition expressions
    complexity: str  # LOW | MEDIUM | HIGH
    modernization_notes: str  # How to implement in modern code

def _extract_vars_from_expr(expr: Optional[IrExpr], var_map: dict) -> list[str]:
    if not expr:
        return []
    res = []
    if expr.kind == "var" and expr.var:
        var = var_map.get(expr.var)
        if var:
            res.append(var.name)
    if expr.left:
        res.extend(_extract_vars_from_expr(expr.left, var_map))
    if expr.right:
        res.extend(_extract_vars_from_expr(expr.right, var_map))
    for a in expr.args:
        res.extend(_extract_vars_from_expr(a, var_map))
    return list(set(res))

def _extract_vars_from_stmt(stmt: IrStmt, var_map: dict) -> list[str]:
    vars_list = []
    for t in stmt.targets:
        var = var_map.get(t)
        if var:
            vars_list.append(var.name)
    if stmt.expr:
        vars_list.extend(_extract_vars_from_expr(stmt.expr, var_map))
    if stmt.cond:
        vars_list.extend(_extract_vars_from_expr(stmt.cond, var_map))
    for a in stmt.args:
        vars_list.extend(_extract_vars_from_expr(a, var_map))
    return list(set(vars_list))

def extract_business_rules(ir: IrProgram) -> list[BusinessRule]:
    rules = []
    rule_idx = 1
    
    for fn in ir.functions:
        for blk in fn.blocks:
            for stmt in blk.stmts:
                cat = None
                desc = ""
                complexity = "LOW"
                notes = ""
                conds = []
                
                vars_inv = _extract_vars_from_stmt(stmt, ir.vars)
                target_vars = [ir.vars.get(t).name for t in stmt.targets if ir.vars.get(t)]
                
                # Calculation
                if stmt.op in (OpKind.COMPUTE, OpKind.ADD, OpKind.SUBTRACT, OpKind.MULTIPLY, OpKind.DIVIDE):
                    cat = "calculation"
                    if stmt.op == OpKind.ADD and len(target_vars) > 0 and stmt.expr and stmt.expr.kind == "var" and stmt.expr.var in stmt.targets:
                        cat = "accumulation"
                        desc = f"Running total: {target_vars[0]} accumulates values"
                        notes = f"Use += operator or equivalent for accumulating in {target_vars[0]}"
                    else:
                        t = target_vars[0] if target_vars else "unknown_target"
                        desc = f"Financial calculation: {t} computed using {stmt.op.value}"
                        notes = "Use BigDecimal or appropriate numeric types for accuracy"
                        
                # Decision & Validation
                elif stmt.op in (OpKind.BRANCH_COND, OpKind.EVALUATE):
                    # Check if it looks like validation
                    if "error" in (stmt.text or "").lower():
                        cat = "validation"
                        v = vars_inv[0] if vars_inv else "input"
                        desc = f"Input validation: {v} must meet conditions"
                        notes = "Extract to an explicit validation method or use a validation framework"
                    else:
                        cat = "decision"
                        v = vars_inv[0] if vars_inv else "variables"
                        desc = f"Business decision: Based on {v}, routes to different outcomes"
                        notes = "Use standard if/else or switch constructs"
                        if stmt.op == OpKind.EVALUATE or len(stmt.cases) > 2:
                            complexity = "MEDIUM"
                
                # I/O
                elif stmt.op in (OpKind.IO_READ, OpKind.IO_WRITE):
                    cat = "io"
                    f = stmt.file or "unknown_file"
                    f_name = ir.vars.get(f).name if ir.vars.get(f) else f
                    op_str = "reads" if stmt.op == OpKind.IO_READ else "writes"
                    desc = f"Data I/O: {op_str} {f_name} records"
                    notes = "Replace with ORM or direct database access layer"
                    
                # Workflow
                elif stmt.op == OpKind.CALL:
                    cat = "workflow"
                    c = stmt.callee or "unknown"
                    desc = f"Subprocess: invokes {c} for specialized processing"
                    notes = "Inject as a dependency or make it a service call"

                if cat:
                    rules.append(BusinessRule(
                        rule_id=f"BR_{rule_idx:03d}",
                        category=cat,
                        description=desc,
                        source_function=fn.name,
                        source_spans=[stmt.span or stmt.origin or f"Block: {blk.label}"],
                        variables_involved=vars_inv,
                        conditions=conds,
                        complexity=complexity,
                        modernization_notes=notes
                    ))
                    rule_idx += 1
                    
    return rules

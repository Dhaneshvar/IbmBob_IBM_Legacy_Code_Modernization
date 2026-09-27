from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..ir.nodes import (
    IrProgram,
    IrFunction,
    IrStmt,
    OpKind,
    IrVar,
    IrType,
)

@dataclass
class TraceEntry:
    source_element: str  # e.g. 'COBOL:PAYROLL:MAIN:s1'
    source_type: str  # 'statement' | 'variable' | 'function'
    source_description: str  # 'MOVE 0 TO WS-COUNT'
    target_element: str  # e.g. 'Java:Payroll.java:line 15'
    target_description: str  # 'wsCount = 0L;'
    mapping_type: str  # 'direct' | 'transformed' | 'unsupported'
    confidence: float  # 0.0 to 1.0
    notes: str


def build_traceability_matrix(ir: IrProgram, target_lang: str = 'java') -> list[TraceEntry]:
    entries = []
    
    prog_name = ir.name
    
    # Trace variables
    for vid, var in ir.vars.items():
        if var.is_temp:
            continue
        
        target_type = "long/BigDecimal" if var.type in (IrType.INT, IrType.DEC) else "String"
        entries.append(TraceEntry(
            source_element=f"{prog_name}:{var.name}",
            source_type="variable",
            source_description=f"Level {var.level} {var.usage}",
            target_element=f"{target_lang.capitalize()}:{prog_name.capitalize()}",
            target_description=f"Mapped to {target_type}",
            mapping_type="direct",
            confidence=0.9,
            notes="Data declaration mapped based on picture clause"
        ))
        
    # Trace functions and statements
    for fn in ir.functions:
        entries.append(TraceEntry(
            source_element=f"{prog_name}:{fn.name}",
            source_type="function",
            source_description="Paragraph or Program entry",
            target_element=f"{target_lang.capitalize()}:{prog_name.capitalize()}:{fn.name.lower()}",
            target_description="Method declaration",
            mapping_type="direct",
            confidence=1.0,
            notes="Control flow function"
        ))
        
        for blk in fn.blocks:
            for i, stmt in enumerate(blk.stmts):
                mapping = "direct"
                conf = 0.9
                if stmt.op == OpKind.UNSUPPORTED:
                    mapping = "unsupported"
                    conf = 0.0
                elif stmt.op in (OpKind.EVALUATE, OpKind.SEARCH, OpKind.STRING_OP, OpKind.UNSTRING_OP):
                    mapping = "transformed"
                    conf = 0.7
                    
                entries.append(TraceEntry(
                    source_element=f"{prog_name}:{fn.name}:{blk.label}:s{i}",
                    source_type="statement",
                    source_description=stmt.origin or stmt.op.value,
                    target_element=f"{target_lang.capitalize()}:{prog_name.capitalize()}",
                    target_description=f"Implementation of {stmt.op.value}",
                    mapping_type=mapping,
                    confidence=conf,
                    notes=f"Generated from span: {stmt.span}" if stmt.span else ""
                ))
                
    return entries


def generate_test_scaffold(ir: IrProgram, target_lang: str = 'java') -> str:
    """Generate JUnit 5 or pytest scaffold for the program."""
    
    class_name = ir.name.capitalize()
    lines = []
    
    if target_lang.lower() == 'java':
        lines.append(f"import org.junit.jupiter.api.Test;")
        lines.append(f"import static org.junit.jupiter.api.Assertions.*;")
        lines.append("")
        lines.append(f"public class {class_name}Test {{")
        
        # Test functions
        for fn in ir.functions:
            if fn.name == "__FILES__":
                continue
            lines.append(f"    @Test")
            lines.append(f"    public void test{fn.name.capitalize()}() {{")
            lines.append(f"        // TODO: setup inputs")
            if fn.name == "main":
                lines.append(f"        // {class_name}.main(new String[]{{}});")
            else:
                lines.append(f"        // {class_name}.{fn.name.lower()}();")
            lines.append(f"        // TODO: assert outcomes")
            lines.append(f"    }}")
            lines.append("")
            
        lines.append("}")
    else:
        lines.append("import pytest")
        lines.append(f"import {class_name.lower()}")
        lines.append("")
        
        # Test functions
        for fn in ir.functions:
            if fn.name == "__FILES__":
                continue
            lines.append(f"def test_{fn.name.lower()}():")
            lines.append(f"    # TODO: setup inputs")
            if fn.name == "main":
                lines.append(f"    # {class_name.lower()}.main([])")
            else:
                lines.append(f"    # {class_name.lower()}.{fn.name.lower()}()")
            lines.append(f"    # TODO: assert outcomes")
            lines.append(f"    pass")
            lines.append("")
            
    return "\n".join(lines)


def matrix_to_markdown(entries: list[TraceEntry]) -> str:
    lines = [
        "| Source Element | Type | Description | Target Element | Mapping | Confidence | Notes |",
        "|---|---|---|---|---|---|---|"
    ]
    for e in entries:
        lines.append(f"| {e.source_element} | {e.source_type} | {e.source_description} | {e.target_element} | {e.mapping_type} | {e.confidence:.2f} | {e.notes} |")
    return "\n".join(lines)


def matrix_to_json(entries: list[TraceEntry]) -> list[dict]:
    import dataclasses
    return [dataclasses.asdict(e) for e in entries]

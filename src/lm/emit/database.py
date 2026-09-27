"""COBOL Data Division to Modern SQL/ORM Emitter.

Translates COBOL variables (from WORKING-STORAGE, etc.) into SQL schemas
and SQLAlchemy models.
"""

from __future__ import annotations

import re
from typing import Any

from ..ir.nodes import IrProgram, IrVar, pic_info


def emit_sql_schema(ir: IrProgram) -> str:
    """Returns CREATE TABLE SQL for the 01/77 level items."""
    lines = []
    
    # We will treat the program as the database namespace/schema
    # and 01/77 items as tables or columns depending on mapping.
    # The prompt says: "Use only 01 and 77 level items as table columns".
    # We'll create a table named after the program.
    
    table_name = ir.name.lower()
    if not table_name:
        table_name = "cobol_data"
        
    lines.append(f"CREATE TABLE {table_name} (")
    
    columns = []
    for vid, var in ir.vars.items():
        if var.level in ("01", "77", "1"):
            if var.redefines:
                lines.append(f"    -- REDEFINES: {var.name} redefines {var.redefines}")
                continue
                
            sql_type = _cobol_to_sql_type(var)
            
            # Check for OCCURS
            if var.occurs > 1:
                sql_type = f"{sql_type} ARRAY"
                
            col_name = var.name.replace("-", "_").lower()
            columns.append(f"    {col_name} {sql_type}")
            
    lines.append(",\n".join(columns))
    lines.append(");")
    lines.append("")
    
    # Add check constraints for 88 levels
    for vid, var in ir.vars.items():
        if var.is_condition and var.host:
            host_var = ir.vars.get(var.host)
            if host_var and host_var.level in ("01", "77", "1"):
                val = str(var.initial).replace("'", "''")
                host_col = host_var.name.replace("-", "_").lower()
                lines.append(f"-- 88-level constraint: {var.name}")
                lines.append(f"ALTER TABLE {table_name} ADD CONSTRAINT chk_{var.name.replace('-', '_').lower()} CHECK ({host_col} = '{val}');")
                
    return "\n".join(lines)


def emit_sqlalchemy_models(ir: IrProgram) -> str:
    """Returns SQLAlchemy model classes."""
    table_name = ir.name.lower()
    if not table_name:
        table_name = "cobol_data"
        
    class_name = "".join(p.capitalize() for p in table_name.split("_"))
    
    lines = [
        "from sqlalchemy import Column, Integer, String, Numeric, CheckConstraint, ARRAY, BigInteger, Char",
        "from sqlalchemy.orm import declarative_base",
        "",
        "Base = declarative_base()",
        "",
        f"class {class_name}(Base):",
        f"    __tablename__ = '{table_name}'",
        "",
        "    id = Column(Integer, primary_key=True)  # Auto-generated primary key",
    ]
    
    for vid, var in ir.vars.items():
        if var.level in ("01", "77", "1"):
            if var.redefines:
                lines.append(f"    # REDEFINES: {var.name} redefines {var.redefines}")
                continue
                
            sa_type = _cobol_to_sqlalchemy_type(var)
            col_name = var.name.replace("-", "_").lower()
            
            if var.occurs > 1:
                sa_type = f"ARRAY({sa_type})"
                
            lines.append(f"    {col_name} = Column({sa_type})")
            
    # Add 88 levels as CheckConstraints in __table_args__
    constraints = []
    for vid, var in ir.vars.items():
        if var.is_condition and var.host:
            host_var = ir.vars.get(var.host)
            if host_var and host_var.level in ("01", "77", "1"):
                host_col = host_var.name.replace("-", "_").lower()
                val = str(var.initial).replace("'", "''")
                constraints.append(f"CheckConstraint(\"{host_col} = '{val}'\", name='chk_{var.name.replace('-', '_').lower()}')")
                
    if constraints:
        lines.append("")
        lines.append("    __table_args__ = (")
        for c in constraints:
            lines.append(f"        {c},")
        lines.append("    )")
        
    return "\n".join(lines)


def emit_database_files(ir: IrProgram) -> dict[str, str]:
    """Returns a dictionary of filename to generated code."""
    name = ir.name.lower() or "schema"
    return {
        f"{name}.sql": emit_sql_schema(ir),
        f"{name}_models.py": emit_sqlalchemy_models(ir)
    }


def _cobol_to_sql_type(var: IrVar) -> str:
    """Map COBOL PIC to SQL type."""
    pic = var.picture
    usage = var.usage
    
    if not pic:
        return "VARCHAR(255)"
        
    info = pic_info(pic, usage)
    p = info.get("expanded", "")
    
    if "V" in p or "." in p:
        digits = info["digits"]
        scale = info["scale"]
        # PIC S9(n)V9(m) -> DECIMAL(n+m, m) - Note digits already includes scale
        return f"DECIMAL({digits}, {scale})"
    elif "9" in p:
        if info["digits"] > 9:
            return "BIGINT"
        return "INTEGER"
    else:
        width = info["width"]
        if width == 1:
            return "CHAR(1)"
        return f"VARCHAR({width})"


def _cobol_to_sqlalchemy_type(var: IrVar) -> str:
    """Map COBOL PIC to SQLAlchemy type."""
    pic = var.picture
    usage = var.usage
    
    if not pic:
        return "String(255)"
        
    info = pic_info(pic, usage)
    p = info.get("expanded", "")
    
    if "V" in p or "." in p:
        digits = info["digits"]
        scale = info["scale"]
        return f"Numeric({digits}, {scale})"
    elif "9" in p:
        if info["digits"] > 9:
            return "BigInteger"
        return "Integer"
    else:
        width = info["width"]
        if width == 1:
            return "Char(1)"
        return f"String({width})"

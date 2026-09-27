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

def detect_cics_patterns(ir: IrProgram) -> list[dict]:
    """Detect CICS-like patterns and map them to API endpoints."""
    patterns = []
    
    # We will map functions with I/O or DISPLAY/ACCEPT to endpoints.
    for fn in ir.functions:
        if fn.name == "__FILES__":
            continue
            
        endpoint_info = {
            "function": fn.name,
            "method": "GET", # default
            "path": f"/{fn.name.lower().replace('_', '-')}",
            "request_fields": [],
            "response_fields": [],
            "io_operations": [],
            "external_calls": [],
            "business_logic": [],
        }
        
        has_pattern = False
        
        for blk in fn.blocks:
            for stmt in blk.stmts:
                if stmt.op == OpKind.IO_READ:
                    endpoint_info["method"] = "GET"
                    endpoint_info["io_operations"].append({"op": "READ", "file": stmt.file})
                    has_pattern = True
                elif stmt.op == OpKind.IO_WRITE:
                    endpoint_info["method"] = "POST"
                    endpoint_info["io_operations"].append({"op": "WRITE", "file": stmt.file})
                    has_pattern = True
                elif stmt.op == OpKind.ACCEPT:
                    for t in stmt.targets:
                        var = ir.vars.get(t)
                        if var:
                            endpoint_info["request_fields"].append(var.name)
                    endpoint_info["method"] = "POST" # Accept usually implies input, so POST or PUT
                    has_pattern = True
                elif stmt.op == OpKind.DISPLAY:
                    for t in stmt.targets:
                        var = ir.vars.get(t)
                        if var:
                            endpoint_info["response_fields"].append(var.name)
                    has_pattern = True
                elif stmt.op == OpKind.CALL:
                    endpoint_info["external_calls"].append(stmt.callee)
                    has_pattern = True
                elif stmt.op in (OpKind.EVALUATE, OpKind.BRANCH_COND):
                    endpoint_info["business_logic"].append(stmt.op.value)
                    
        # If we found relevant CICS-like interactions, add as pattern
        if has_pattern:
            patterns.append(endpoint_info)
            
    return patterns

def _map_type_to_openapi(ir_type: IrType) -> str:
    if ir_type == IrType.INT:
        return "integer"
    if ir_type == IrType.DEC:
        return "number"
    if ir_type == IrType.BOOL:
        return "boolean"
    return "string"

def _map_type_to_python(ir_type: IrType) -> str:
    if ir_type == IrType.INT:
        return "int"
    if ir_type == IrType.DEC:
        return "float"
    if ir_type == IrType.BOOL:
        return "bool"
    return "str"

def emit_openapi_spec(ir: IrProgram, patterns: list[dict]) -> str:
    """Generate OpenAPI 3.0 YAML spec."""
    lines = [
        "openapi: 3.0.0",
        "info:",
        f"  title: {ir.name} API",
        "  version: 1.0.0",
        f"  description: Modernized REST API for {ir.name}",
        "paths:"
    ]
    
    for pat in patterns:
        lines.append(f"  {pat['path']}:")
        lines.append(f"    {pat['method'].lower()}:")
        lines.append(f"      summary: Endpoint for {pat['function']}")
        lines.append(f"      operationId: {pat['function']}")
        
        # Request body if there are accept fields or write operations
        if pat['request_fields'] or pat['method'] in ('POST', 'PUT'):
            lines.append("      requestBody:")
            lines.append("        required: true")
            lines.append("        content:")
            lines.append("          application/json:")
            lines.append("            schema:")
            lines.append("              type: object")
            lines.append("              properties:")
            for field in pat['request_fields']:
                lines.append(f"                {field.lower()}:")
                var = ir.var_by_name(field)
                vtype = _map_type_to_openapi(var.type) if var else "string"
                lines.append(f"                  type: {vtype}")
                
        # Response body
        lines.append("      responses:")
        lines.append("        '200':")
        lines.append("          description: Successful response")
        lines.append("          content:")
        lines.append("            application/json:")
        lines.append("              schema:")
        lines.append("                type: object")
        if pat['response_fields']:
            lines.append("                properties:")
            for field in pat['response_fields']:
                lines.append(f"                  {field.lower()}:")
                var = ir.var_by_name(field)
                vtype = _map_type_to_openapi(var.type) if var else "string"
                lines.append(f"                    type: {vtype}")
    
    return "\n".join(lines)

def emit_fastapi_app(ir: IrProgram, patterns: list[dict]) -> str:
    """Generate FastAPI Python app."""
    lines = [
        "from fastapi import FastAPI, HTTPException",
        "from pydantic import BaseModel",
        "from typing import Optional",
        "",
        "app = FastAPI(title=\"Modernized CICS API\")",
        ""
    ]
    
    # Models
    for pat in patterns:
        if pat['request_fields']:
            model_name = f"{pat['function'].capitalize()}Request"
            lines.append(f"class {model_name}(BaseModel):")
            for field in pat['request_fields']:
                var = ir.var_by_name(field)
                vtype = _map_type_to_python(var.type) if var else "str"
                lines.append(f"    {field.lower().replace('-', '_')}: Optional[{vtype}] = None")
            lines.append("")
            
        if pat['response_fields']:
            model_name = f"{pat['function'].capitalize()}Response"
            lines.append(f"class {model_name}(BaseModel):")
            for field in pat['response_fields']:
                var = ir.var_by_name(field)
                vtype = _map_type_to_python(var.type) if var else "str"
                lines.append(f"    {field.lower().replace('-', '_')}: Optional[{vtype}] = None")
            lines.append("")

    # Endpoints
    for pat in patterns:
        req_type = f"{pat['function'].capitalize()}Request" if pat['request_fields'] else ""
        res_type = f"{pat['function'].capitalize()}Response" if pat['response_fields'] else "dict"
        
        args = f"request: {req_type}" if req_type else ""
        
        lines.append(f"@app.{pat['method'].lower()}(\"{pat['path']}\", response_model={res_type})")
        lines.append(f"async def {pat['function'].lower()}({args}):")
        lines.append(f"    # TODO: Implement business logic for {pat['function']}")
        for logic in pat['business_logic']:
            lines.append(f"    # Contains logic: {logic}")
        for call in pat['external_calls']:
            lines.append(f"    # Calls external service: {call}")
        for io in pat['io_operations']:
            lines.append(f"    # Performs {io['op']} on {io['file'] or 'unknown'}")
            
        if pat['response_fields']:
            lines.append(f"    return {res_type}()")
        else:
            lines.append("    return {\"status\": \"success\"}")
        lines.append("")
        
    return "\n".join(lines)

def emit_rest_api_files(ir: IrProgram) -> dict[str, str]:
    """Generate all REST API related files."""
    patterns = detect_cics_patterns(ir)
    return {
        "openapi.yaml": emit_openapi_spec(ir, patterns),
        "app.py": emit_fastapi_app(ir, patterns)
    }

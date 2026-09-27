"""BMS Screen to React Component and API Endpoint Emitter.

Translates BMS IR into a modern web UI (React) and backend API (FastAPI).
"""

from __future__ import annotations

from typing import Any


def emit_react_component(bms_ir: dict[str, Any]) -> str:
    """Returns JSX/TSX React component representing the BMS screen."""
    name = bms_ir.get("name", "Screen")
    fields = bms_ir.get("fields", [])
    
    # Parse dimensions, e.g., "24x80"
    dim_str = bms_ir.get("dimensions", "24x80")
    try:
        rows, cols = map(int, dim_str.split("x"))
    except ValueError:
        rows, cols = 24, 80
        
    lines = [
        "import React, { useState } from 'react';",
        "import './Screen.css'; // Add grid styling here",
        "",
        f"export default function {name}Screen() {{",
        "  const [formData, setFormData] = useState({",
    ]
    
    # Initialize form data state for input fields
    for field in fields:
        if field.get("is_input"):
            fname = field.get("name", "")
            finit = field.get("initial", "")
            lines.append(f"    {fname}: '{finit}',")
            
    lines.append("  });")
    lines.append("")
    lines.append("  const [response, setResponse] = useState(null);")
    lines.append("")
    lines.append("  const handleChange = (e) => {")
    lines.append("    const { name, value } = e.target;")
    lines.append("    setFormData((prev) => ({ ...prev, [name]: value }));")
    lines.append("  };")
    lines.append("")
    lines.append("  const handleSubmit = async (e) => {")
    lines.append("    e.preventDefault();")
    lines.append(f"    try {{")
    lines.append(f"      const res = await fetch('/api/{name.lower()}', {{")
    lines.append("        method: 'POST',")
    lines.append("        headers: { 'Content-Type': 'application/json' },")
    lines.append("        body: JSON.stringify(formData),")
    lines.append("      });")
    lines.append("      const data = await res.json();")
    lines.append("      setResponse(data);")
    lines.append("    } catch (err) {")
    lines.append("      console.error(err);")
    lines.append("    }")
    lines.append("  };")
    lines.append("")
    lines.append("  return (")
    lines.append("    <div className=\"bms-screen-container\">")
    lines.append(f"      <form onSubmit={{handleSubmit}} className=\"bms-grid\" style={{{{")
    lines.append(f"        display: 'grid',")
    lines.append(f"        gridTemplateColumns: `repeat({cols}, 1ch)`,")
    lines.append(f"        gridTemplateRows: `repeat({rows}, 1.2em)`")
    lines.append("      }}>")
    
    for field in fields:
        fname = field.get("name", "Field")
        r = field.get("line", 1)
        c = field.get("col", 1)
        length = field.get("length", 10)
        is_input = field.get("is_input", False)
        initial = field.get("initial", "")
        
        style = f"{{ gridRow: {r}, gridColumn: '{c} / span {length}' }}"
        
        if is_input:
            lines.append(f"        <input")
            lines.append(f"          type=\"text\"")
            lines.append(f"          name=\"{fname}\"")
            lines.append(f"          value={{formData.{fname}}}")
            lines.append(f"          onChange={{handleChange}}")
            lines.append(f"          maxLength={{{length}}}")
            lines.append(f"          style={style}")
            lines.append(f"          className=\"bms-input\"")
            lines.append(f"        />")
        else:
            lines.append(f"        <span style={style} className=\"bms-label\">")
            lines.append(f"          {initial}")
            lines.append(f"        </span>")
            
    lines.append("        {/* Submit button placed automatically at bottom */}")
    lines.append(f"        <button type=\"submit\" style={{{{ gridRow: {rows + 1}, gridColumn: 1 }}}}>Submit</button>")
    lines.append("      </form>")
    lines.append("      {response && <pre>{JSON.stringify(response, null, 2)}</pre>}</pre>}")
    lines.append("    </div>")
    lines.append("  );")
    lines.append("}")
    
    return "\n".join(lines)


def emit_api_endpoint(bms_ir: dict[str, Any]) -> str:
    """Returns FastAPI endpoint code for the BMS screen."""
    name = bms_ir.get("name", "Screen")
    fields = bms_ir.get("fields", [])
    
    lines = [
        "from fastapi import APIRouter, HTTPException",
        "from pydantic import BaseModel, Field",
        "",
        f"router = APIRouter()",
        "",
        f"class {name}Request(BaseModel):",
    ]
    
    has_inputs = False
    for field in fields:
        if field.get("is_input"):
            fname = field.get("name", "")
            length = field.get("length", 10)
            lines.append(f"    {fname}: str = Field(..., max_length={length}, description=\"{fname} field\")")
            has_inputs = True
            
    if not has_inputs:
        lines.append("    pass  # No input fields defined")
        
    lines.append("")
    lines.append(f"class {name}Response(BaseModel):")
    lines.append("    status: str")
    lines.append("    message: str")
    lines.append("")
    lines.append(f"@router.post('/api/{name.lower()}', response_model={name}Response)")
    lines.append(f"async def process_{name.lower()}(request: {name}Request):")
    lines.append('    """Process data submitted from the BMS screen."""')
    lines.append("    # TODO: Implement business logic here")
    lines.append("    ")
    
    for field in fields:
        if field.get("is_input"):
            fname = field.get("name", "")
            lines.append(f"    # print(request.{fname})")
            
    lines.append("    return {")
    lines.append('        "status": "success",')
    lines.append('        "message": "Data processed successfully"')
    lines.append("    }")
    
    return "\n".join(lines)


def emit_webui_files(bms_ir: dict[str, Any]) -> dict[str, str]:
    """Returns a dictionary of filename to generated code."""
    name = bms_ir.get("name", "Screen")
    return {
        f"{name}.tsx": emit_react_component(bms_ir),
        f"{name}_api.py": emit_api_endpoint(bms_ir)
    }

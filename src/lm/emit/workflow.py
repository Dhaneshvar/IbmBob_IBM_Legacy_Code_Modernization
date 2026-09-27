"""JCL Job to Modern Workflow Emitter.

Translates JCL jobs represented as IrJob nodes into Python scripts,
Bash scripts, or Airflow DAGs.
"""

from __future__ import annotations

import re
from typing import Any

from ..ir.nodes import IrJob, IrDataset


def emit_workflow(job: IrJob, target: str = 'python') -> dict[str, str]:
    """Emit the workflow for the specified target ('python', 'shell', or 'airflow')."""
    if target == 'python':
        return {"code": _emit_python(job)}
    elif target == 'shell':
        return {"code": _emit_shell(job)}
    elif target == 'airflow':
        return {"code": _emit_airflow(job)}
    else:
        raise ValueError(f"Unknown workflow target: {target}")


def emit_workflow_files(job: IrJob, target: str) -> dict[str, str]:
    """Return a dictionary of filename to generated code for the workflow."""
    code_dict = emit_workflow(job, target)
    code = code_dict["code"]
    
    if target == 'python':
        ext = "py"
    elif target == 'shell':
        ext = "sh"
    elif target == 'airflow':
        ext = "py"
    else:
        ext = "txt"
        
    filename = f"{job.name.lower() or 'job'}_{target}.{ext}"
    return {filename: code}


def _emit_python(job: IrJob) -> str:
    lines = [
        '"""',
        f'Migrated workflow for JCL Job: {job.name}',
        '"""',
        "import os",
        "import subprocess",
        "import sys",
        "",
    ]
    
    # Emit functions for each step
    for step in job.steps:
        step_name = step.get('name', 'step')
        pgm = step.get('pgm', 'unknown_program')
        
        lines.append(f"def step_{step_name.lower()}():")
        lines.append(f'    print("Running step: {step_name} (Program: {pgm})")')
        
        # Handle DDs
        for dd in step.get('dd', []):
            dd_name = dd.get('name', '')
            dsn = dd.get('dsn', '')
            disp = dd.get('disp', 'SHR')
            
            mode = "'r'"
            if 'NEW' in disp.upper() or 'MOD' in disp.upper():
                mode = "'a'" if 'MOD' in disp.upper() else "'w'"
            
            if dsn:
                lines.append(f'    os.environ["DD_{dd_name}"] = "{dsn}"')
                
        # Call the program
        lines.append(f'    # TODO: implement call to {pgm}')
        lines.append(f'    return 0  # return code')
        lines.append("")

    # Main block
    lines.append("def main():")
    lines.append("    rc = 0")
    for step in job.steps:
        step_name = step.get('name', 'step')
        cond = step.get('cond', '')
        
        if cond:
            # simplified condition handling
            lines.append(f"    # COND: {cond}")
            lines.append(f"    if rc == 0:  # Simplified check")
            lines.append(f"        rc = step_{step_name.lower()}()")
        else:
            lines.append(f"    rc = step_{step_name.lower()}()")
            
    lines.append("    return rc")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    sys.exit(main())")
    
    return "\n".join(lines)


def _emit_shell(job: IrJob) -> str:
    lines = [
        "#!/usr/bin/env bash",
        f"# Migrated workflow for JCL Job: {job.name}",
        "set -e",
        "",
    ]
    
    for step in job.steps:
        step_name = step.get('name', 'step')
        pgm = step.get('pgm', 'unknown_program')
        
        lines.append(f"echo 'Running step: {step_name} (Program: {pgm})'")
        
        for dd in step.get('dd', []):
            dd_name = dd.get('name', '')
            dsn = dd.get('dsn', '')
            if dsn:
                lines.append(f"export DD_{dd_name}=\"{dsn}\"")
                
        lines.append(f"# TODO: call {pgm}")
        lines.append(f"./{pgm.lower()}")
        lines.append("")
        
    return "\n".join(lines)


def _emit_airflow(job: IrJob) -> str:
    lines = [
        "from datetime import timedelta",
        "from airflow import DAG",
        "from airflow.operators.bash import BashOperator",
        "from airflow.utils.dates import days_ago",
        "",
        "default_args = {",
        "    'owner': 'legacy_modernizer',",
        "    'depends_on_past': False,",
        "    'email_on_failure': False,",
        "    'email_on_retry': False,",
        "    'retries': 1,",
        "    'retry_delay': timedelta(minutes=5),",
        "}",
        "",
        f"with DAG(",
        f"    '{job.name.lower() or 'migrated_job'}',",
        "    default_args=default_args,",
        "    description='Migrated from JCL',",
        "    schedule_interval=timedelta(days=1),",
        "    start_date=days_ago(1),",
        "    catchup=False,",
        ") as dag:",
        "",
    ]
    
    prev_task = None
    for step in job.steps:
        step_name = step.get('name', 'step').lower()
        pgm = step.get('pgm', 'unknown_program')
        
        env_vars = []
        for dd in step.get('dd', []):
            dd_name = dd.get('name', '')
            dsn = dd.get('dsn', '')
            if dsn:
                env_vars.append(f"export DD_{dd_name}=\"{dsn}\"")
        
        env_setup = " && ".join(env_vars)
        if env_setup:
            cmd = f"{env_setup} && ./{pgm.lower()}"
        else:
            cmd = f"./{pgm.lower()}"
            
        lines.append(f"    task_{step_name} = BashOperator(")
        lines.append(f"        task_id='{step_name}',")
        lines.append(f"        bash_command='{cmd}',")
        lines.append(f"    )")
        lines.append("")
        
        if prev_task:
            lines.append(f"    {prev_task} >> task_{step_name}")
            lines.append("")
            
        prev_task = f"task_{step_name}"
        
    return "\n".join(lines)

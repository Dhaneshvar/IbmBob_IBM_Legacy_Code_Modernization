"""lm CLI — entry point for the legacy modernization pipeline.

Commands:
    lm serve              Start the FastAPI server
    lm parse <file>       Parse COBOL/JCL and show IR summary
    lm migrate <file>     Full pipeline: parse → IR → agents → Java
    lm report             Show AI-Ops report from DB
    lm graph              Show dependency graph stats
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def cmd_serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("uvicorn not installed. Run: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    os.environ.setdefault("LM_DB_PATH", args.db)
    if args.neo4j:
        os.environ.setdefault("NEO4J_URI", args.neo4j)

    print(f"🚀 Starting Legacy Modernizer API on http://{args.host}:{args.port}")
    print(f"   DB: {args.db}")
    print(f"   Docs: http://{args.host}:{args.port}/docs")
    uvicorn.run(
        "lm.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


def cmd_parse(args: argparse.Namespace) -> None:
    from lm.cobol.parser import parse_cobol
    from lm.ir.builder import build_ir, build_ir_from_jcl
    from lm.jcl.parser import parse_jcl

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    source = path.read_text(encoding="utf-8", errors="replace")
    ext = path.suffix.lower()
    is_jcl = ext in (".jcl", ".jcljob") or args.jcl

    if is_jcl:
        jcl = parse_jcl(source, path=str(path))
        job = build_ir_from_jcl(jcl)
        print(f"\n✅ JCL parsed: {job.name}")
        print(f"   Steps    : {len(job.steps)}")
        print(f"   Datasets : {len(job.datasets)}")
    else:
        ast = parse_cobol(source, path=str(path))
        ir = build_ir(ast, path=str(path), source_text=source)
        print(f"\n✅ COBOL parsed: {ir.name}")
        print(f"   Dialect     : {ir.dialect}")
        print(f"   Source lines: {ir.source_lines}")
        print(f"   Functions   : {len(ir.functions)}")
        print(f"   Variables   : {len(ir.vars)}")
        print(f"   Unsupported : {len(ir.unsupported)}")
        if ir.unsupported:
            print("\n   Unsupported operations:")
            for u in ir.unsupported[:10]:
                print(f"     [{u['function']}] line {u['line']}: {u['verb']} {u['text'][:60]}")

        if args.ir:
            print("\n--- IR JSON ---")
            print(json.dumps(ir.to_json(), indent=2)[:4000])

        if args.store:
            from lm.store.sqlite import open_db, save_program
            conn = open_db(args.db)
            pid = save_program(conn, ir)
            conn.close()
            print(f"\n💾 Stored as program ID {pid} in {args.db}")


def cmd_migrate(args: argparse.Namespace) -> None:
    from lm.cobol.parser import parse_cobol
    from lm.ir.builder import build_ir
    from lm.agents.pipeline import MigrationOrchestrator
    from lm.obs.metrics import reset_metrics
    from lm.obs.tracer import configure_tracer

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    source = path.read_text(encoding="utf-8", errors="replace")
    print(f"\n🔍 Parsing {path.name}...")
    ast = parse_cobol(source, path=str(path))
    ir = build_ir(ast, path=str(path), source_text=source)
    print(f"✅ Parsed: {ir.name} ({ir.source_lines} lines, {len(ir.functions)} functions)")

    if args.llm_key:
        os.environ["LM_LLM_API_KEY"] = args.llm_key
    if args.llm_backend:
        os.environ["LM_LLM_BACKEND"] = args.llm_backend
    if args.llm_model:
        os.environ["LM_LLM_MODEL"] = args.llm_model

    tracer = configure_tracer(log_path=".lm/traces.ndjson")
    metrics = reset_metrics("cli")
    metrics.start()

    def on_progress(ev: dict):
        event = ev.get("event", "")
        fn = ev.get("function", "")
        rnd = ev.get("round", "")
        if event == "plan_done":
            print(f"📋 Plan: {ev.get('strategy')} | effort={ev.get('effort')} | risks={ev.get('risks')}")
        elif event == "execute_start":
            print(f"⚙️  Executing {fn} (round {rnd})...", end="", flush=True)
        elif event == "critic_pass":
            print(f" ✅ (completeness {ev.get('completeness', '?')}%)")
        elif event == "critic_fail":
            issues = ev.get("issues", [])
            print(f" ❌ [{', '.join(issues[:2])}]")
        elif event == "done":
            print(f"🎉 Done! Files: {ev.get('files')} | Rounds: {ev.get('rounds')}")
        elif event == "error":
            print(f"❌ Error: {ev.get('error')}")

    print(f"\n🤖 Starting agentic migration to {args.target}...")
    orch = MigrationOrchestrator(tracer=tracer, metrics=metrics)
    result = orch.migrate(ir, args.target, on_progress=on_progress)
    metrics.finish()

    # Write output files
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, code in result.files.items():
        out_file = out_dir / fname
        out_file.write_text(code, encoding="utf-8")
        print(f"📄 Written: {out_file} ({code.count(chr(10))} lines)")

    # Write explanations
    if result.explanations:
        exp_file = out_dir / "MIGRATION_NOTES.md"
        lines = ["# Migration Notes\n"]
        for fn_name, exp in result.explanations.items():
            lines.append(f"## `{fn_name}`\n\n{exp}\n")
        exp_file.write_text("\n".join(lines), encoding="utf-8")
        print(f"📝 Migration notes: {exp_file}")

    print(f"\n✅ Migration complete: {len(result.files)} files in {out_dir}/")
    print(f"   Agent rounds  : {result.agent_rounds}")
    print(f"   Lines emitted : {metrics.lines_emitted}")
    print(f"   LLM tokens    : in={metrics.llm_tokens_in} out={metrics.llm_tokens_out}")


def cmd_report(args: argparse.Namespace) -> None:
    from lm.store.sqlite import open_db, all_programs, load_program
    from lm.obs.metrics import get_metrics
    from lm.obs.report import generate_report

    conn = open_db(args.db)
    rows = all_programs(conn)
    programs = []
    for row in rows:
        ir = load_program(conn, row["name"])
        if ir:
            programs.append(ir)
    conn.close()

    m = get_metrics("cli")
    report = generate_report(m, programs)
    print(report["markdown"])

    if args.output:
        Path(args.output).write_text(report["markdown"], encoding="utf-8")
        print(f"\n💾 Report saved to {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lm",
        description="IBM Legacy Modernizer — COBOL/JCL → IR → Java",
    )
    parser.add_argument("--db", default="lm.db", help="SQLite database path")
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start the API server")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument("--neo4j", default=None, help="Neo4j URI e.g. bolt://localhost:7687")

    # parse
    p_parse = sub.add_parser("parse", help="Parse a COBOL or JCL file")
    p_parse.add_argument("file", help="Path to .cbl or .jcl file")
    p_parse.add_argument("--jcl", action="store_true", help="Force JCL mode")
    p_parse.add_argument("--ir", action="store_true", help="Print IR JSON")
    p_parse.add_argument("--store", action="store_true", help="Save IR to DB")

    # migrate
    p_mig = sub.add_parser("migrate", help="Run full agentic migration")
    p_mig.add_argument("file", help="Path to .cbl file")
    p_mig.add_argument("--target", default="java", help="Target language (java|python)")
    p_mig.add_argument("--output", default="output", help="Output directory")
    p_mig.add_argument("--llm-key", help="LLM API key")
    p_mig.add_argument("--llm-backend", default="mock", choices=["mock", "anthropic", "openai"])
    p_mig.add_argument("--llm-model", help="Model name")

    # report
    p_rep = sub.add_parser("report", help="Print AI-Ops report")
    p_rep.add_argument("--output", default="", help="Save report to file")

    args = parser.parse_args()
    dispatch = {
        "serve":   cmd_serve,
        "parse":   cmd_parse,
        "migrate": cmd_migrate,
        "report":  cmd_report,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(0)
    handler(args)


if __name__ == "__main__":
    main()

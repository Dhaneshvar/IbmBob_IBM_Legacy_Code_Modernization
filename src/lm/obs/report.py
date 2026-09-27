"""AI-Ops report generator.

Produces a structured Markdown + JSON report covering:
- Program inventory (functions, complexity, unsupported ops)
- Risk heatmap  
- Migration completeness
- Agent performance statistics
- Dependency summary
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from ..ir.nodes import IrProgram
from .metrics import PipelineMetrics


def generate_report(
    metrics: PipelineMetrics,
    programs: list[IrProgram],
    migration_results: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Return a dict with keys ``markdown`` and ``json``."""
    now = datetime.now(timezone.utc).isoformat()

    # ── program summary ────────────────────────────────────────────────────
    prog_rows = []
    total_complexity = 0
    total_unsupported = 0
    for p in programs:
        fns = len(p.functions)
        cx = sum(f.complexity for f in p.functions)
        unsup = len(p.unsupported)
        total_complexity += cx
        total_unsupported += unsup
        prog_rows.append({
            "name": p.name,
            "path": p.path,
            "functions": fns,
            "variables": len(p.vars),
            "complexity": cx,
            "unsupported": unsup,
            "source_lines": p.source_lines,
            "risk": _risk_level(cx, unsup),
        })

    # ── function risk heatmap ──────────────────────────────────────────────
    fn_rows = []
    for p in programs:
        for fn in p.functions:
            fn_rows.append({
                "program": p.name,
                "function": fn.name,
                "complexity": fn.complexity,
                "fan_in": fn.fan_in,
                "fan_out": fn.fan_out,
                "unsupported": fn.unsupported_count,
                "is_io": fn.is_io,
                "risk": _risk_level(fn.complexity, fn.unsupported_count),
            })
    fn_rows.sort(key=lambda r: (-r["complexity"], -r["unsupported"]))

    # ── migration completeness ─────────────────────────────────────────────
    completeness_pct = 0.0
    if metrics.lines_emitted and sum(p.source_lines for p in programs) > 0:
        src = sum(p.source_lines for p in programs)
        completeness_pct = min(100.0, metrics.lines_emitted / max(src, 1) * 100)

    # ── unsupported ops breakdown ──────────────────────────────────────────
    verb_counts: dict[str, int] = {}
    for p in programs:
        for u in p.unsupported:
            v = u.get("verb", "UNKNOWN")
            verb_counts[v] = verb_counts.get(v, 0) + 1

    # ── markdown ──────────────────────────────────────────────────────────
    md = _render_markdown(
        now=now,
        metrics=metrics,
        prog_rows=prog_rows,
        fn_rows=fn_rows[:20],  # top 20 by risk
        verb_counts=verb_counts,
        completeness_pct=completeness_pct,
        migration_results=migration_results or [],
    )

    report_json = {
        "generated_at": now,
        "metrics": metrics.to_dict(),
        "programs": prog_rows,
        "top_risk_functions": fn_rows[:20],
        "unsupported_verbs": verb_counts,
        "completeness_pct": round(completeness_pct, 1),
        "migration_results": migration_results or [],
    }

    return {"markdown": md, "json": report_json}


def _risk_level(complexity: int, unsupported: int) -> str:
    score = complexity + unsupported * 3
    if score >= 20:
        return "HIGH"
    if score >= 8:
        return "MEDIUM"
    return "LOW"


def _render_markdown(
    now: str,
    metrics: PipelineMetrics,
    prog_rows: list[dict],
    fn_rows: list[dict],
    verb_counts: dict[str, int],
    completeness_pct: float,
    migration_results: list[dict],
) -> str:
    lines = [
        "# Legacy Modernization AI-Ops Report",
        f"\n> Generated: {now}",
        "\n---\n",

        "## 📊 Pipeline Summary\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Programs parsed | **{metrics.programs_parsed}** |",
        f"| IR functions | **{metrics.ir_functions_total}** |",
        f"| IR variables | **{metrics.ir_vars_total}** |",
        f"| Unsupported ops | **{metrics.unsupported_ops}** |",
        f"| Agent rounds | **{metrics.agent_rounds_total}** |",
        f"| Critic passes | ✅ {metrics.critic_passes} |",
        f"| Critic failures | ❌ {metrics.critic_failures} |",
        f"| Lines emitted | **{metrics.lines_emitted}** |",
        f"| Migration completeness | **{completeness_pct:.1f}%** |",
        f"| Total duration | **{metrics.total_duration_ms:.0f} ms** |",
        f"| LLM tokens in | {metrics.llm_tokens_in} |",
        f"| LLM tokens out | {metrics.llm_tokens_out} |",

        "\n---\n",
        "## 📁 Program Inventory\n",
        "| Program | Functions | Variables | Complexity | Unsupported | Lines | Risk |",
        "|---------|-----------|-----------|------------|-------------|-------|------|",
    ]
    for r in prog_rows:
        risk_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(r["risk"], "⚪")
        lines.append(
            f"| `{r['name']}` | {r['functions']} | {r['variables']} | "
            f"{r['complexity']} | {r['unsupported']} | {r['source_lines']} | "
            f"{risk_emoji} {r['risk']} |"
        )

    lines += [
        "\n---\n",
        "## 🔥 Function Risk Heatmap (Top 20)\n",
        "| Program | Function | Complexity | Unsupported | I/O | Risk |",
        "|---------|----------|------------|-------------|-----|------|",
    ]
    for r in fn_rows:
        risk_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(r["risk"], "⚪")
        io_icon = "📁" if r["is_io"] else ""
        lines.append(
            f"| `{r['program']}` | `{r['function']}` | {r['complexity']} | "
            f"{r['unsupported']} | {io_icon} | {risk_emoji} {r['risk']} |"
        )

    if verb_counts:
        lines += [
            "\n---\n",
            "## ⚠️ Unsupported Operations\n",
            "| COBOL Verb | Occurrences | Migration Action |",
            "|------------|-------------|-----------------|",
        ]
        actions = {
            "SORT":   "Use Java `Collections.sort()` or stream API",
            "MERGE":  "Use Java `Stream.concat()` with sorted inputs",
            "EXEC":   "Manual review required — inline SQL/CICS",
            "SEARCH": "Convert to Java `for` loop with condition",
        }
        for verb, count in sorted(verb_counts.items(), key=lambda x: -x[1]):
            action = actions.get(verb, "Review and convert manually")
            lines.append(f"| `{verb}` | {count} | {action} |")

    if migration_results:
        lines += [
            "\n---\n",
            "## ✅ Migration Results\n",
            "| Program | Target | Status | Rounds | Files |",
            "|---------|--------|--------|--------|-------|",
        ]
        for r in migration_results:
            status_icon = "✅" if r.get("status") == "done" else "⏳"
            output = r.get("output_json")
            file_count = len(json.loads(output)) if output else 0
            lines.append(
                f"| `{r.get('prog_name', '?')}` | {r.get('target_lang', '?')} | "
                f"{status_icon} {r.get('status', '?')} | "
                f"{r.get('agent_rounds', 0)} | {file_count} |"
            )

    lines += [
        "\n---\n",
        "## 💡 Recommendations\n",
    ]
    # Generate recommendations based on metrics
    if metrics.unsupported_ops > 0:
        lines.append(
            f"- **{metrics.unsupported_ops} unsupported operations** require manual review. "
            "Focus on `EXEC SQL`, `SORT`, and computed `GO TO` statements first."
        )
    high_risk = [r for r in fn_rows if r["risk"] == "HIGH"]
    if high_risk:
        names = ", ".join(f"`{r['function']}`" for r in high_risk[:3])
        lines.append(
            f"- **{len(high_risk)} high-risk functions** detected ({names}...). "
            "Consider decomposing these into smaller units before migration."
        )
    if metrics.critic_failures > metrics.critic_passes:
        lines.append(
            "- **Critic failure rate is high**. Consider providing more context in the "
            "executor prompt or increasing the maximum agent rounds."
        )
    if completeness_pct < 80:
        lines.append(
            f"- **Migration completeness is {completeness_pct:.0f}%**. "
            "Review UNSUPPORTED stubs in emitted code and complete them manually."
        )
    if not lines[-1].startswith("-"):
        lines.append("- All metrics within acceptable range. Proceed with code review.")

    lines += [
        "\n---\n",
        "_Report generated by IBM Legacy Modernizer — powered by IBM Bob_\n",
    ]
    return "\n".join(lines)

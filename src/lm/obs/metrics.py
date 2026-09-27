"""Pipeline metrics — Prometheus-compatible counters and gauges."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PipelineMetrics:
    # parse
    programs_parsed: int = 0
    parse_errors: int = 0
    parse_duration_ms: float = 0.0

    # IR
    ir_vars_total: int = 0
    ir_functions_total: int = 0
    ir_stmts_total: int = 0
    unsupported_ops: int = 0

    # store
    db_writes: int = 0

    # graph
    graph_nodes_pushed: int = 0

    # agents
    agent_plan_calls: int = 0
    agent_execute_calls: int = 0
    agent_critic_calls: int = 0
    agent_rounds_total: int = 0
    critic_passes: int = 0
    critic_failures: int = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0

    # emit
    lines_emitted: int = 0
    files_emitted: int = 0

    # overall
    pipeline_runs: int = 0
    pipeline_errors: int = 0
    total_duration_ms: float = 0.0
    started_at: Optional[float] = None

    def start(self) -> None:
        self.started_at = time.monotonic()
        self.pipeline_runs += 1

    def finish(self) -> None:
        if self.started_at:
            self.total_duration_ms = (time.monotonic() - self.started_at) * 1000

    def to_prometheus(self) -> str:
        """Render as Prometheus text format for /metrics endpoint."""
        lines = [
            "# HELP lm_programs_parsed Total COBOL programs parsed",
            "# TYPE lm_programs_parsed counter",
            f"lm_programs_parsed {self.programs_parsed}",
            "# HELP lm_parse_errors Parse errors encountered",
            "# TYPE lm_parse_errors counter",
            f"lm_parse_errors {self.parse_errors}",
            "# HELP lm_ir_functions IR functions extracted",
            "# TYPE lm_ir_functions gauge",
            f"lm_ir_functions {self.ir_functions_total}",
            "# HELP lm_ir_vars IR variables declared",
            "# TYPE lm_ir_vars gauge",
            f"lm_ir_vars {self.ir_vars_total}",
            "# HELP lm_unsupported_ops Unsupported COBOL operations",
            "# TYPE lm_unsupported_ops gauge",
            f"lm_unsupported_ops {self.unsupported_ops}",
            "# HELP lm_agent_rounds LLM agent iteration rounds",
            "# TYPE lm_agent_rounds counter",
            f"lm_agent_rounds {self.agent_rounds_total}",
            "# HELP lm_critic_passes Critic agent passes",
            "# TYPE lm_critic_passes counter",
            f"lm_critic_passes {self.critic_passes}",
            "# HELP lm_critic_failures Critic agent failures",
            "# TYPE lm_critic_failures counter",
            f"lm_critic_failures {self.critic_failures}",
            "# HELP lm_lines_emitted Lines of code emitted",
            "# TYPE lm_lines_emitted counter",
            f"lm_lines_emitted {self.lines_emitted}",
            "# HELP lm_pipeline_duration_ms Total pipeline duration ms",
            "# TYPE lm_pipeline_duration_ms gauge",
            f"lm_pipeline_duration_ms {self.total_duration_ms:.2f}",
            "# HELP lm_llm_tokens_in LLM input tokens used",
            "# TYPE lm_llm_tokens_in counter",
            f"lm_llm_tokens_in {self.llm_tokens_in}",
            "# HELP lm_llm_tokens_out LLM output tokens used",
            "# TYPE lm_llm_tokens_out counter",
            f"lm_llm_tokens_out {self.llm_tokens_out}",
        ]
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ── thread-safe global registry ────────────────────────────────────────────

_lock = threading.Lock()
_registry: dict[str, PipelineMetrics] = {}


def get_metrics(run_id: str = "default") -> PipelineMetrics:
    with _lock:
        if run_id not in _registry:
            _registry[run_id] = PipelineMetrics()
        return _registry[run_id]


def reset_metrics(run_id: str = "default") -> PipelineMetrics:
    with _lock:
        m = PipelineMetrics()
        _registry[run_id] = m
        return m


def all_metrics() -> dict[str, dict]:
    with _lock:
        return {k: v.to_dict() for k, v in _registry.items()}

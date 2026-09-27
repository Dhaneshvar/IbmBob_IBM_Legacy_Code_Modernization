"""Agentic migration: Planner → Executor → Critic loop.

The LLM never sees raw COBOL source. It only receives the normalised IR
(as JSON) and the Java scaffold produced by the deterministic emitter.
This is the correctness guarantee: the IR is the contract.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..ir.nodes import IrFunction, IrProgram
from ..obs.metrics import PipelineMetrics
from ..obs.tracer import Tracer, get_tracer


# ─────────────────────────────── LLM client ───────────────────────────────

def _llm_call(prompt: str, system: str = "", max_tokens: int = 4096) -> tuple[str, int, int]:
    """Call the configured LLM. Returns (text, tokens_in, tokens_out).

    Respects LM_LLM_BACKEND env var:
      'mock'      — deterministic mock (default, no API key needed)
      'anthropic' — Anthropic Claude
      'openai'    — OpenAI GPT
      'granite'   — IBM Granite via watsonx.ai REST API
      'watsonx'   — alias for 'granite'
            'ollama'    — local Ollama server (for Granite local inference)
            'groq'      — Groq Cloud inference (including openai/gpt-oss-120b and openai/gpt-oss-20b)
      'gemini'    — Google Gemini via generativelanguage API
      'grok'      — xAI Grok (OpenAI-compatible endpoint)
    """
    backend = os.environ.get("LM_LLM_BACKEND", "mock").lower()
    api_key = os.environ.get("LM_LLM_API_KEY")

    if backend == "mock":
        return _mock_llm(prompt), len(prompt) // 4, 200

    if backend in ("granite", "watsonx"):
        if not api_key:
            raise RuntimeError("IBM Granite migration requires an IBM Cloud API key.")
        if not os.environ.get("WATSONX_PROJECT_ID"):
            raise RuntimeError("IBM Granite migration requires a watsonx.ai project ID.")
        return _watsonx_granite_call(prompt, system, max_tokens)

    if backend == "ollama":
        return _ollama_call(prompt, system, max_tokens)

    if backend in ("anthropic", "openai", "groq", "gemini", "grok") and not api_key:
        raise RuntimeError(f"{backend} migration requires an API key.")

    if backend == "anthropic":
        return _anthropic_call(prompt, system, max_tokens)

    if backend == "openai":
        return _openai_call(prompt, system, max_tokens)

    if backend == "groq":
        return _groq_call(prompt, system, max_tokens)

    if backend == "gemini":
        return _gemini_call(prompt, system, max_tokens)

    if backend == "grok":
        return _grok_call(prompt, system, max_tokens)

    raise RuntimeError(f"Unsupported LLM backend '{backend}'.")


def _mock_llm(prompt: str) -> str:
    """Generate a plausible-looking mock LLM response for dev/testing."""
    p_lower = prompt.lower()
    if "migration plan" in p_lower or "migrationplan" in p_lower:
        return json.dumps({
            "strategy": "direct",
            "target_language": "java",
            "estimated_effort": "MEDIUM",
            "functions_order": [],
            "risks": [
                {"type": "UNSUPPORTED_OPS", "severity": "LOW", "description": "No unsupported ops detected"},
            ],
            "notes": "Direct translation is feasible. All constructs map cleanly to Java equivalents.",
        })
    if "critique" in p_lower or "criticverdict" in p_lower or "review this java method" in p_lower or "return only this json:" in p_lower:
        return json.dumps({
            "passed": True,
            "issues": [],
            "completeness_pct": 100,
            "notes": "All IR operations are represented in the emitted Java code.",
        })
    if "explain the migration" in p_lower:
        return (
            "This function implements the core procedural logic migrated from COBOL. "
            "Control flow, data items, and arithmetic operations have been mapped directly "
            "to idiomatic Java 17 constructs while preserving precision and program semantics."
        )
    # Default: return the scaffold unchanged with minor enhancement
    scaffold = _extract_code_block(prompt)
    if scaffold:
        lines = []
        for line in scaffold.split("\n"):
            if "TODO: UNSUPPORTED" in line:
                verb = line.split("—")[-1].strip() if "—" in line else "UNKNOWN"
                lines.append(line)
                lines.append(f"        // Migrated from COBOL {verb} — review required")
            else:
                lines.append(line)
        return "```java\n" + "\n".join(lines) + "\n```"

    lines = []
    for line in prompt.split("\n"):
        if "TODO: UNSUPPORTED" in line:
            verb = line.split("—")[-1].strip() if "—" in line else "UNKNOWN"
            lines.append(line)
            lines.append(f"        // Migrated from COBOL {verb} — review required")
        else:
            lines.append(line)
    return "\n".join(lines)


def _anthropic_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    import anthropic  # type: ignore
    client = anthropic.Anthropic(api_key=os.environ["LM_LLM_API_KEY"])
    msg = client.messages.create(
        model=os.environ.get("LM_LLM_MODEL", "claude-3-5-sonnet-20241022"),
        max_tokens=max_tokens,
        system=system or "You are an expert COBOL to Java migration assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text if msg.content else ""
    return text, msg.usage.input_tokens, msg.usage.output_tokens


def _openai_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    import openai  # type: ignore
    client = openai.OpenAI(api_key=os.environ["LM_LLM_API_KEY"])
    resp = client.chat.completions.create(
        model=os.environ.get("LM_LLM_MODEL", "gpt-4o"),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system or "You are an expert COBOL to Java migration assistant."},
            {"role": "user", "content": prompt},
        ],
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0


def _watsonx_granite_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    """Call IBM Granite via watsonx.ai REST API.

    Environment variables:
      LM_LLM_API_KEY     — IBM Cloud API key (or watsonx bearer token)
      WATSONX_PROJECT_ID  — watsonx.ai project ID
      WATSONX_URL         — watsonx.ai endpoint (default: us-south)
      LM_LLM_MODEL        — model id (default: ibm/granite-3-8b-instruct)
    """
    import urllib.request
    import urllib.error

    api_key = os.environ["LM_LLM_API_KEY"]
    project_id = os.environ.get("WATSONX_PROJECT_ID", "")
    base_url = os.environ.get(
        "WATSONX_URL",
        "https://us-south.ml.cloud.ibm.com"
    )
    model_id = os.environ.get("LM_LLM_MODEL", "ibm/granite-3-8b-instruct")

    # Step 1: Exchange API key for IAM bearer token
    token_url = "https://iam.cloud.ibm.com/identity/token"
    token_data = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={api_key}"
    token_req = urllib.request.Request(
        token_url,
        data=token_data.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        token_resp = urllib.request.urlopen(token_req, timeout=15)
        token_json = json.loads(token_resp.read().decode())
        bearer = token_json["access_token"]
    except Exception:
        # If IAM exchange fails, assume the key IS a bearer token
        bearer = api_key

    # Step 2: Call watsonx.ai text generation endpoint
    gen_url = f"{base_url}/ml/v1/text/generation?version=2024-03-14"
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    payload = {
        "model_id": model_id,
        "input": full_prompt,
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": max_tokens,
            "min_new_tokens": 1,
            "temperature": 0.1,
            "top_p": 1.0,
            "repetition_penalty": 1.05,
        },
        "project_id": project_id,
    }

    gen_req = urllib.request.Request(
        gen_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
        },
    )
    try:
        gen_resp = urllib.request.urlopen(gen_req, timeout=120)
        result = json.loads(gen_resp.read().decode())
        text = result.get("results", [{}])[0].get("generated_text", "")
        tok_in = result.get("results", [{}])[0].get("input_token_count", len(prompt) // 4)
        tok_out = result.get("results", [{}])[0].get("generated_token_count", len(text) // 4)
        return text, tok_in, tok_out
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if hasattr(e, "read") else str(e)
        raise RuntimeError(f"watsonx.ai Granite call failed ({e.code}): {err_body}") from e


def _ollama_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    """Call a local Ollama server running IBM Granite or any supported model.

    Environment variables:
      OLLAMA_URL    — Ollama API URL (default: http://localhost:11434)
      LM_LLM_MODEL — model name (default: granite3.1-dense:8b)
    """
    import urllib.request

    base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("LM_LLM_MODEL", "granite3.1-dense:8b")

    payload = {
        "model": model,
        "prompt": prompt,
        "system": system or "You are an expert COBOL to Java migration assistant.",
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.1,
        },
    }

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=300)
    result = json.loads(resp.read().decode())
    text = result.get("response", "")
    tok_in = result.get("prompt_eval_count", len(prompt) // 4)
    tok_out = result.get("eval_count", len(text) // 4)
    return text, tok_in, tok_out


def _groq_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    """Call Groq Cloud inference API.

    Environment variables:
      LM_LLM_API_KEY  — Groq API key (gsk_...)
      LM_LLM_MODEL    — model ID (default: openai/gpt-oss-20b)
      LM_LLM_REASONING_EFFORT — optional reasoning budget (low|medium|high)

    Supported models:
      openai/gpt-oss-120b            — OpenAI OSS reasoning model
      openai/gpt-oss-20b             — OpenAI OSS reasoning model
      llama-3.3-70b-versatile         — Llama 3.3 70B (recommended)
      llama-3.1-8b-instant            — Llama 3.1 8B (fast)
      llama-3.1-70b-versatile         — Llama 3.1 70B
      mixtral-8x7b-32768              — Mixtral 8x7B MoE
      gemma2-9b-it                    — Google Gemma 2 9B
      llama3-groq-70b-8192-tool-use-preview — Llama 3 70B tool use
    """
    try:
        from groq import Groq  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "Groq support requires the 'groq' package. Install the llm extras or pip install groq."
        ) from exc

    api_key = os.environ["LM_LLM_API_KEY"]
    model = os.environ.get("LM_LLM_MODEL", "openai/gpt-oss-20b")
    reasoning_effort = os.environ.get("LM_LLM_REASONING_EFFORT")
    if reasoning_effort is None and model.startswith("openai/gpt-oss"):
        reasoning_effort = "medium"
    client = Groq(api_key=api_key)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "You are an expert COBOL to Java migration assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "top_p": 1,
        "max_completion_tokens": max_tokens,
    }

    # Reasoning models accept reasoning_effort; other models may ignore it or reject it.
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    try:
        resp = client.chat.completions.create(**payload)
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        tok_in = getattr(usage, "prompt_tokens", len(prompt) // 4) if usage else len(prompt) // 4
        tok_out = getattr(usage, "completion_tokens", len(text) // 4) if usage else len(text) // 4
        return text, tok_in, tok_out
    except Exception as e:
        raise RuntimeError(f"Groq API call failed: {e}") from e


def _gemini_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    """Call Google Gemini via the generativelanguage REST API.

    Environment variables:
      LM_LLM_API_KEY  — Google AI Studio API key
      LM_LLM_MODEL    — model ID (default: gemini-3.8-flash)

    Supported models:
      gemini-3.8-flash             — Fastest multimodal model
      gemini-3.1-pro-preview       — High-end reasoning preview
      gemini-3.7-flash             — Balanced speed and quality
      gemini-3.6-flash             — High-throughput generation
      gemini-3.5-flash             — Efficient general-purpose model
      gemini-3.5-flash-lite        — Lightweight low-cost model
    """
    import urllib.request
    import urllib.error

    api_key = os.environ["LM_LLM_API_KEY"]
    model = os.environ.get("LM_LLM_MODEL", "gemini-3.8-flash")

    # Combine system + user prompts (Gemini uses single-turn for simplicity)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": full_prompt}]}
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.1,
            "topP": 0.95,
        },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode())
        candidates = result.get("candidates", [])
        text = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
        usage = result.get("usageMetadata", {})
        tok_in = usage.get("promptTokenCount", len(prompt) // 4)
        tok_out = usage.get("candidatesTokenCount", len(text) // 4)
        return text, tok_in, tok_out
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if hasattr(e, "read") else str(e)
        raise RuntimeError(f"Gemini API call failed ({e.code}): {err_body}") from e


def _grok_call(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    """Call xAI Grok via its OpenAI-compatible API endpoint.

    Environment variables:
      LM_LLM_API_KEY  — xAI API key (xai-...)
      LM_LLM_MODEL    — model ID (default: grok-beta)

    Supported models:
      grok-beta          — Grok Beta (general purpose)
      grok-2-1212        — Grok 2 (December 2024)
      grok-2-vision-1212 — Grok 2 Vision (multimodal)
      grok-vision-beta   — Grok Vision Beta
    """
    import urllib.request
    import urllib.error

    api_key = os.environ["LM_LLM_API_KEY"]
    model = os.environ.get("LM_LLM_MODEL", "grok-beta")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "You are an expert COBOL to Java migration assistant."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }

    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode())
        text = result["choices"][0]["message"]["content"] or ""
        usage = result.get("usage", {})
        return text, usage.get("prompt_tokens", len(prompt) // 4), usage.get("completion_tokens", len(text) // 4)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if hasattr(e, "read") else str(e)
        raise RuntimeError(f"xAI Grok API call failed ({e.code}): {err_body}") from e


@dataclass
class MigrationPlan:
    program_name: str
    target_language: str = "java"
    strategy: str = "direct"        # direct | decompose | rewrite
    functions_order: list[str] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    estimated_effort: str = "MEDIUM"
    notes: str = ""
    raw_response: str = ""


@dataclass
class FunctionDraft:
    function_name: str
    target_language: str
    code: str
    explanation: str = ""
    critic_rounds: int = 0
    passed: bool = False
    issues: list[str] = field(default_factory=list)


@dataclass
class MigrationResult:
    program_name: str
    target_language: str
    plan: Optional[MigrationPlan] = None
    files: dict[str, str] = field(default_factory=dict)      # filename → code
    explanations: dict[str, str] = field(default_factory=dict)  # function → explanation
    agent_rounds: int = 0
    status: str = "pending"
    error: Optional[str] = None
    metrics: Optional[dict] = None


# ─────────────────────────────── planner ──────────────────────────────────

class PlannerAgent:
    """Analyzes IR and produces a structured MigrationPlan."""

    SYSTEM = (
        "You are a senior software architect specialising in legacy COBOL modernization. "
        "You analyse normalised Intermediate Representation (IR) summaries and produce "
        "structured JSON migration plans. Never ask for more information — work with what "
        "you are given."
    )

    def plan(
        self,
        ir: IrProgram,
        target_lang: str = "java",
        tracer: Optional[Tracer] = None,
        metrics: Optional[PipelineMetrics] = None,
    ) -> MigrationPlan:
        tracer = tracer or get_tracer()
        with tracer.span("agent.plan", program=ir.name, target=target_lang):
            summary = _ir_summary(ir)
            prompt = self._build_prompt(ir.name, summary, target_lang)
            raw, tok_in, tok_out = _llm_call(prompt, self.SYSTEM)
            if metrics:
                metrics.agent_plan_calls += 1
                metrics.llm_tokens_in += tok_in
                metrics.llm_tokens_out += tok_out
            return self._parse_response(ir, raw, target_lang)

    def _build_prompt(self, name: str, summary: dict, target: str) -> str:
        return f"""Analyze this COBOL program IR summary and produce a MigrationPlan JSON object.

Program: {name}
Target language: {target}

IR Summary:
{json.dumps(summary, indent=2)}

Return ONLY valid JSON with this exact schema:
{{
  "strategy": "direct" | "decompose" | "rewrite",
  "target_language": "{target}",
  "estimated_effort": "LOW" | "MEDIUM" | "HIGH",
  "functions_order": ["list", "of", "function", "names", "in", "migration", "order"],
  "risks": [
    {{"type": "RISK_TYPE", "severity": "LOW|MEDIUM|HIGH", "description": "..."}}
  ],
  "notes": "Brief rationale explaining the migration strategy"
}}"""

    def _parse_response(self, ir: IrProgram, raw: str, target_lang: str) -> MigrationPlan:
        try:
            data = _extract_json(raw)
            order = data.get("functions_order") or [
                fn.name for fn in ir.functions if fn.kind not in ("files",)
            ]
            return MigrationPlan(
                program_name=ir.name,
                target_language=target_lang,
                strategy=data.get("strategy", "direct"),
                functions_order=order,
                risks=data.get("risks", []),
                estimated_effort=data.get("estimated_effort", "MEDIUM"),
                notes=data.get("notes", ""),
                raw_response=raw,
            )
        except Exception:
            # Fallback plan
            return MigrationPlan(
                program_name=ir.name,
                target_language=target_lang,
                functions_order=[fn.name for fn in ir.functions],
                raw_response=raw,
            )


# ─────────────────────────────── executor ─────────────────────────────────

class ExecutorAgent:
    """Translates one IrFunction at a time to target language code."""

    SYSTEM = (
        "You are an expert COBOL to Java migration engineer. "
        "You receive a Java scaffold generated deterministically from COBOL IR and "
        "improve it: fill in TODO stubs, add proper exception handling, and ensure "
        "idiomatic Java 17. Return ONLY the improved Java method code, no explanations."
    )

    EXPLANATION_SYSTEM = (
        "You are a technical documentation writer. Given COBOL IR and Java code, "
        "write a concise paragraph (3-5 sentences) explaining WHY and HOW each "
        "migration decision was made. Be specific about COBOL constructs and their Java equivalents."
    )

    def execute(
        self,
        fn: IrFunction,
        scaffold: str,
        plan: MigrationPlan,
        issues: Optional[list[str]] = None,
        tracer: Optional[Tracer] = None,
        metrics: Optional[PipelineMetrics] = None,
    ) -> FunctionDraft:
        tracer = tracer or get_tracer()
        with tracer.span("agent.execute", function=fn.name, program=plan.program_name):
            prompt = self._build_prompt(fn, scaffold, plan, issues)
            raw, tok_in, tok_out = _llm_call(prompt, self.SYSTEM)
            if metrics:
                metrics.agent_execute_calls += 1
                metrics.llm_tokens_in += tok_in
                metrics.llm_tokens_out += tok_out
            code = _extract_code_block(raw) or raw

            # Generate explanation
            exp_prompt = self._explanation_prompt(fn, code, plan.target_language)
            explanation, et_in, et_out = _llm_call(exp_prompt, self.EXPLANATION_SYSTEM, max_tokens=512)
            if metrics:
                metrics.llm_tokens_in += et_in
                metrics.llm_tokens_out += et_out

            return FunctionDraft(
                function_name=fn.name,
                target_language=plan.target_language,
                code=code,
                explanation=explanation.strip(),
            )

    def _build_prompt(
        self,
        fn: IrFunction,
        scaffold: str,
        plan: MigrationPlan,
        issues: Optional[list[str]],
    ) -> str:
        fn_ir = _fn_ir_summary(fn)
        retry_note = ""
        if issues:
            retry_note = f"\n\nCRITIC FEEDBACK — fix these issues:\n" + "\n".join(f"- {i}" for i in issues)

        return f"""Improve this Java method that was auto-generated from COBOL IR.

Function: {fn.name} (from program: {plan.program_name})
Strategy: {plan.strategy}

IR summary for this function:
{json.dumps(fn_ir, indent=2)}

Current Java scaffold (auto-generated):
```java
{scaffold}
```
{retry_note}

Rules:
1. Keep the method signature exactly as-is
2. Fill in all TODO comments with real Java code
3. Preserve UNSUPPORTED comments but add your best-effort implementation
4. Use BigDecimal for decimal arithmetic (never float/double for financial values)
5. Add JavaDoc comment explaining what the function does
6. Return ONLY the improved Java method, no class wrapper"""

    def _explanation_prompt(self, fn: IrFunction, code: str, target: str) -> str:
        ops = list({s.op.value for b in fn.blocks for s in b.stmts})
        return f"""Explain the migration of COBOL function '{fn.name}' to {target}.

COBOL operations present: {', '.join(ops)}
Migrated code:
```java
{code[:1000]}
```

Write 3-5 sentences explaining:
1. What this function does in the legacy system
2. Key COBOL constructs and how they were migrated
3. Any important differences in behaviour or edge cases to watch for"""


# ─────────────────────────────── critic ───────────────────────────────────

class CriticAgent:
    """Validates that executor output covers all IR operations."""

    SYSTEM = (
        "You are a code review AI specialising in COBOL-to-Java migration quality. "
        "Check that every IR operation is properly handled in the Java code. "
        "Return ONLY valid JSON — no markdown, no explanation outside the JSON."
    )

    def critique(
        self,
        fn: IrFunction,
        draft: FunctionDraft,
        tracer: Optional[Tracer] = None,
        metrics: Optional[PipelineMetrics] = None,
    ) -> dict:
        tracer = tracer or get_tracer()
        with tracer.span("agent.critic", function=fn.name) as sp:
            prompt = self._build_prompt(fn, draft)
            raw, tok_in, tok_out = _llm_call(prompt, self.SYSTEM)
            if metrics:
                metrics.agent_critic_calls += 1
                metrics.llm_tokens_in += tok_in
                metrics.llm_tokens_out += tok_out

            result = self._parse_verdict(raw)

            # Always check UNSUPPORTED ops are present
            unsup_stmts = [
                s for b in fn.blocks for s in b.stmts
                if s.op.value == "unsupported"
            ]
            if unsup_stmts and "TODO" not in draft.code and "UNSUPPORTED" not in draft.code:
                result["issues"].append(
                    f"{len(unsup_stmts)} UNSUPPORTED ops must be marked as TODO in the output"
                )
                result["passed"] = False

            sp.attrs["passed"] = result["passed"]
            sp.attrs["issues"] = len(result.get("issues", []))
            if metrics:
                if result["passed"]:
                    metrics.critic_passes += 1
                else:
                    metrics.critic_failures += 1
            return result

    def _build_prompt(self, fn: IrFunction, draft: FunctionDraft) -> str:
        fn_ir = _fn_ir_summary(fn)
        return f"""Review this Java method migrated from COBOL.

IR operations that MUST be covered: {json.dumps(fn_ir.get('ops', []))}
UNSUPPORTED ops: {fn_ir.get('unsupported_count', 0)}

Java code:
```java
{draft.code[:2000]}
```

Return ONLY this JSON:
{{
  "passed": true | false,
  "issues": ["list of specific issues if any"],
  "completeness_pct": 0-100,
  "notes": "brief review summary"
}}"""

    def _parse_verdict(self, raw: str) -> dict:
        try:
            data = _extract_json(raw)
            return {
                "passed": bool(data.get("passed", False)),
                "issues": list(data.get("issues", [])),
                "completeness_pct": int(data.get("completeness_pct", 0)),
                "notes": str(data.get("notes", "")),
            }
        except Exception:
            return {"passed": False, "issues": ["Could not parse critic response"], "completeness_pct": 0, "notes": ""}


# ─────────────────────────────── orchestrator ─────────────────────────────

class MigrationOrchestrator:
    """Runs the full Planner → Executor → Critic loop for a program."""

    MAX_ROUNDS = 3

    def __init__(
        self,
        tracer: Optional[Tracer] = None,
        metrics: Optional[PipelineMetrics] = None,
    ):
        self.tracer = tracer or get_tracer()
        self.metrics = metrics
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.critic = CriticAgent()

    def migrate(
        self,
        ir: IrProgram,
        target_lang: str = "java",
        on_progress: Optional[Any] = None,
        check_pause: Optional[Any] = None,
        check_cancel: Optional[Any] = None,
    ) -> MigrationResult:
        """Full migration pipeline. Calls on_progress(event_dict) for live updates.
        Supports check_pause() and check_cancel() callbacks for interactive control.
        """
        if target_lang == "python":
            from ..emit.python import emit_function, emit_files
        else:
            from ..emit.java import emit_function, emit_files

        result = MigrationResult(
            program_name=ir.name,
            target_language=target_lang,
            status="running",
        )

        def _notify(event: str, **kw):
            if on_progress:
                on_progress({"event": event, "program": ir.name, **kw})

        with self.tracer.span("migration", program=ir.name, target=target_lang):
            try:
                # ── 1. Plan ──────────────────────────────────────────────
                _notify("plan_start", progress_pct=5, status_text="Synthesizing migration strategy")
                plan = self.planner.plan(ir, target_lang, self.tracer, self.metrics)
                result.plan = plan
                _notify("plan_done", strategy=plan.strategy, risks=len(plan.risks),
                        effort=plan.estimated_effort, notes=plan.notes, progress_pct=15,
                        status_text=f"Plan synthesized: {plan.strategy} strategy")

                # ── Check for cancel/pause ──
                if check_cancel and check_cancel():
                    result.status = "stopped"
                    _notify("stopped", progress_pct=15, notes="Migration stopped by operator")
                    return result

                # ── 2. Generate deterministic scaffold ───────────────────
                _notify("scaffold_start", progress_pct=20, status_text="Building AST scaffold")
                scaffold_files = emit_files(ir)

                # ── 3. Execute + Critique per function ───────────────────
                improved_functions: dict[str, str] = {}
                total_rounds = 0

                raw_fns = [fn for fn in (ir.function(fn_name) for fn_name in (plan.functions_order or [fn.name for fn in ir.functions]))
                           if fn is not None and fn.kind not in ("files",)]
                total_fns = max(len(raw_fns), 1)

                for fn_idx, fn in enumerate(raw_fns):
                    fn_name = fn.name

                    # Check cancel
                    if check_cancel and check_cancel():
                        result.status = "stopped"
                        _notify("stopped", progress_pct=int(20 + (fn_idx / total_fns) * 70), notes=f"Stopped before {fn_name}")
                        break

                    # Check pause
                    while check_pause and check_pause():
                        _notify("paused", progress_pct=int(20 + (fn_idx / total_fns) * 70), notes=f"Paused at function {fn_name}")
                        time.sleep(0.5)

                    pct = int(20 + (fn_idx / total_fns) * 70)

                    # Build function scaffold
                    fn_scaffold_lines = emit_function(fn, ir.vars)
                    fn_scaffold = "\n".join(fn_scaffold_lines)

                    draft = None
                    issues: list[str] = []
                    passed = False

                    for rnd in range(1, self.MAX_ROUNDS + 1):
                        # Check cancel/pause inside rounds
                        if check_cancel and check_cancel():
                            break
                        while check_pause and check_pause():
                            time.sleep(0.5)

                        total_rounds += 1
                        if self.metrics:
                            self.metrics.agent_rounds_total += 1

                        _notify("execute_start", function=fn_name, round=rnd, progress_pct=pct,
                                current_step=f"Refining {fn_name} (Round {rnd}/{self.MAX_ROUNDS})",
                                completed_functions=fn_idx, total_functions=total_fns)
                        draft = self.executor.execute(
                            fn, fn_scaffold if rnd == 1 else (draft.code if draft else fn_scaffold),
                            plan, issues if issues else None,
                            self.tracer, self.metrics,
                        )
                        draft.critic_rounds = rnd

                        _notify("critic_start", function=fn_name, round=rnd, progress_pct=pct + 2)
                        verdict = self.critic.critique(fn, draft, self.tracer, self.metrics)

                        if verdict["passed"]:
                            passed = True
                            draft.passed = True
                            _notify("critic_pass", function=fn_name, round=rnd, progress_pct=pct + 4,
                                    completeness=verdict.get("completeness_pct", 100))
                            break
                        else:
                            issues = verdict.get("issues", [])
                            _notify("critic_fail", function=fn_name, round=rnd, issues=issues, progress_pct=pct + 2)

                    if draft:
                        improved_functions[fn_name] = draft.code
                        result.explanations[fn_name] = draft.explanation

                if result.status == "stopped":
                    return result

                if self.metrics:
                    self.metrics.agent_rounds_total += total_rounds

                # ── 4. Assemble final output ─────────────────────────────
                _notify("assembly_start", progress_pct=92, status_text="Assembling target artifact bundle")
                final_files = {}
                for fname, scaffold_code in scaffold_files.items():
                    # Patch the improved function bodies into the scaffold
                    final_code = _patch_functions(scaffold_code, improved_functions)
                    final_files[fname] = final_code
                    if self.metrics:
                        self.metrics.lines_emitted += final_code.count("\n")
                        self.metrics.files_emitted += 1

                result.files = final_files
                result.agent_rounds = total_rounds
                result.status = "done"
                _notify("done", files=list(final_files.keys()), rounds=total_rounds, progress_pct=100, status_text="Migration completed successfully")

            except Exception as exc:
                result.status = "error"
                result.error = str(exc)
                _notify("error", error=str(exc))
                raise

        return result


# ─────────────────────────────── helpers ──────────────────────────────────

def _ir_summary(ir: IrProgram) -> dict:
    return {
        "name": ir.name,
        "dialect": ir.dialect,
        "source_lines": ir.source_lines,
        "variables": len(ir.vars),
        "functions": len(ir.functions),
        "unsupported_ops": len(ir.unsupported),
        "uses_files": ir.uses_files,
        "high_complexity_functions": [
            {"name": fn.name, "complexity": fn.complexity, "is_io": fn.is_io}
            for fn in ir.functions if fn.complexity >= 5
        ],
        "external_calls": list({
            s.callee for fn in ir.functions for b in fn.blocks
            for s in b.stmts if s.callee and s.op.value == "call"
        }),
        "unsupported_verbs": list({u.get("verb", "") for u in ir.unsupported}),
    }


def _fn_ir_summary(fn: IrFunction) -> dict:
    ops = [s.op.value for b in fn.blocks for s in b.stmts]
    op_counts: dict[str, int] = {}
    for op in ops:
        op_counts[op] = op_counts.get(op, 0) + 1
    return {
        "name": fn.name,
        "kind": fn.kind,
        "complexity": fn.complexity,
        "blocks": len(fn.blocks),
        "stmts": len(ops),
        "ops": list(op_counts.keys()),
        "op_counts": op_counts,
        "callers": fn.callers,
        "callees": fn.callees,
        "unsupported_count": fn.unsupported_count,
        "is_io": fn.is_io,
    }


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    import re
    # Try to find a JSON block (possibly in markdown fences)
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    # Find the outermost { ... }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    return json.loads(text)


def _extract_code_block(text: str) -> Optional[str]:
    """Extract Java code from a markdown fenced block."""
    import re
    m = re.search(r"```(?:java)?\s*([\s\S]+?)```", text)
    return m.group(1).strip() if m else None


#: A Java method signature: an identifier immediately followed by ``(``.
_SIG_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")


def _method_body(code: str) -> Optional[list[str]]:
    """Return the body lines of a Java method, or None if ``code`` isn't one.

    The executor is asked for a whole method ("keep the signature exactly
    as-is"), so we peel the signature and the enclosing braces off and keep
    only what goes between them.
    """
    lines = code.strip().split("\n")
    open_idx = next((i for i, l in enumerate(lines) if "{" in l), None)
    if open_idx is None or not lines[open_idx].rstrip().endswith("{"):
        return None
    depth = 0
    for i in range(open_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            if i == open_idx:
                return []          # `{ }` — an empty but valid body
            return lines[open_idx + 1 : i]
    return None


def _splice_method(scaffold: str, fn_name: str, code: str) -> str:
    """Replace the body of the scaffold's method named ``fn_name`` with ``code``."""
    body = _method_body(code)
    if body is None:
        if "{" not in code and "}" not in code:
            body = [l for l in code.strip().split("\n") if l.strip()]

    if body is None:
        return _append_reference(scaffold, fn_name, code)

    lines = scaffold.split("\n")

    clean_target = fn_name.lower().replace("-", "").replace("_", "")
    sig_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(("//", "*", "/*")):
            continue
        m = _SIG_RE.search(s)
        if m:
            clean_m = m.group(1).lower().replace("-", "").replace("_", "")
            if clean_m == clean_target or m.group(1).lower() == fn_name.lower():
                sig_idx = i
                break
    if sig_idx is None:
        return _append_reference(scaffold, fn_name, code)

    # The emitter writes `{` on the signature line and a lone `}` to close, so
    # only that shape is spliced; anything fancier is kept as a reference block.
    open_idx = next((i for i in range(sig_idx, len(lines)) if "{" in lines[i]), None)
    if open_idx is None or not lines[open_idx].rstrip().endswith("{"):
        return _append_reference(scaffold, fn_name, code)
    depth = 0
    close_idx = None
    for i in range(open_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            close_idx = i
            break
    if close_idx is None or lines[close_idx].strip() != "}":
        return _append_reference(scaffold, fn_name, code)

    pad = " " * (len(lines[sig_idx]) - len(lines[sig_idx].lstrip()) + 4)
    new_body = [pad + b if b.strip() else "" for b in body]
    return "\n".join(lines[: open_idx + 1] + new_body + lines[close_idx:])


def _append_reference(scaffold: str, fn_name: str, code: str) -> str:
    """Keep the agent's work visible when it can't be spliced in automatically."""
    return scaffold + f"\n    // === AGENT OUTPUT (unmatched): {fn_name} ===\n{code}\n"


def _patch_functions(scaffold: str, improved: dict[str, str]) -> str:
    """Replace function bodies in the scaffold with the executor's versions."""
    result = scaffold
    for fn_name, code in improved.items():
        if not code:
            continue
        result = _splice_method(result, fn_name, code)
    return result

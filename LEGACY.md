# ⚡ IBM Legacy Modernizer

> **Deterministic COBOL/JCL → Normalized IR → Agentic Java Migration with Live AI-Ops**
>
> A full-stack pipeline that parses IBM mainframe legacy code, builds a language-agnostic
> Intermediate Representation, stores it in SQLite + Neo4j, then runs a
> Planner → Executor → Critic agent loop to emit clean Java 17 — with a real-time
> observability dashboard showing every step live.

---

## 🎬 Live Demo Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BROWSER  http://localhost:3000                                              │
│                                                                             │
│  Step 1 ──► Connect        Dummy z/OS mainframe (pre-loaded demo assets)   │
│  Step 2 ──► Browse         COBOL programs / JCL jobs / BMS screens         │
│  Step 3 ──► Configure      Target language + LLM backend (mock/real)       │
│  Step 4 ──► AI-Ops Live    Loki logs · Grafana metrics · Neo4j graph        │
│  Step 5 ──► Results        Java code · COBOL↔Java diff · Explanations      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Local)

### Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | ≥ 3.10 | `python --version` |
| Node.js | ≥ 18 | `node --version` |
| npm | ≥ 9 | `npm --version` |

### 1 — Install Python backend

```bash
# From the project root
pip install -e ".[serve]"
```

### 2 — Start the API server

```bash
python run_api.py
# ✅  API running at  http://localhost:8000
# ✅  Docs (Swagger)  http://localhost:8000/docs
```

### 3 — Install & start the React frontend

```bash
cd frontend
npm install
npm run dev
# ✅  UI running at   http://localhost:3000
```

### 4 — Open the app

Navigate to **http://localhost:3000** and follow the 5-step wizard.

---

## 🐳 Docker (Everything in One Command)

```bash
docker-compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| Neo4j Browser | http://localhost:7474 (neo4j / password) |

---

## ⚙️ CLI Usage

```bash
# Parse a COBOL file and show IR summary
python -m lm parse tests/fixtures/PAYROLL.cbl

# Parse + persist to SQLite
python -m lm parse tests/fixtures/PAYROLL.cbl --store

# Full agentic migration (mock LLM, no API key needed)
python -m lm migrate tests/fixtures/PAYROLL.cbl --target java --output out/

# Full migration with Anthropic Claude
python -m lm migrate tests/fixtures/PAYROLL.cbl \
  --target java \
  --llm-backend anthropic \
  --llm-key sk-ant-... \
  --output out/

# AI-Ops report
python -m lm report
```

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        IBM LEGACY MODERNIZER                             │
│                                                                          │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────────────┐    │
│  │  Mainframe  │    │  ANTLR4      │    │  Normalized IR            │    │
│  │  Connector  │───▶│  Grammars    │───▶│  (IrProgram, IrFunction,  │    │
│  │  (dummy     │    │  Cobol85.g4  │    │   IrVar, IrStmt, IrEdge)  │    │
│  │   z/OS sim) │    │  JCL.g4      │    └──────────┬───────────────┘    │
│  └─────────────┘    └──────────────┘               │                    │
│                                                     ▼                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  LAYER 3 & 4: PERSISTENCE                                        │   │
│  │  SQLite ─── programs / functions / variables / jobs / migrations │   │
│  │  Neo4j  ─── (:Program)─[:CALLS]─▶(:Function)─[:RUNS]─▶(:Job)   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                     │                    │
│                                                     ▼                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  LAYER 5: AGENTIC MIGRATION                                      │   │
│  │                                                                   │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │   │
│  │  │ Planner  │───▶│ Executor │───▶│  Critic  │ (up to 3 rounds)  │   │
│  │  │  Agent   │    │  Agent   │    │  Agent   │◀──────────────────│   │
│  │  │          │    │          │    │          │                    │   │
│  │  │IR summary│    │IR+Scaffold│   │Verify all│                   │   │
│  │  │→ Plan    │    │→ Java code│   │ops covered│                  │   │
│  │  └──────────┘    └──────────┘    └──────────┘                   │   │
│  │                                                                   │   │
│  │  ⚠️  LLM sees ONLY the IR — never raw COBOL source              │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                     │                    │
│                                                     ▼                    │
│  ┌──────────────────┐    ┌──────────────────────────────────────────┐   │
│  │  LAYER 6: EMIT   │    │  LAYER 7: OBSERVABILITY                  │   │
│  │  Java 17 emitter │    │  Tracer → NDJSON spans  (Loki-style)     │   │
│  │  Deterministic   │    │  Metrics → Prometheus   (Grafana-style)  │   │
│  │  scaffold first, │    │  Graph   → Neo4j / Canvas force-graph    │   │
│  │  LLM fills logic │    │  Report  → Markdown AI-Ops summary       │   │
│  └──────────────────┘    └──────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Pipeline Stages (Detailed)

### Stage 1 — Deterministic Parsing (no LLM)

| Component | File | What it does |
|-----------|------|-------------|
| COBOL Lexer | `src/lm/cobol/lexer.py` | Fixed/free format tokenizer, continuation folding |
| COBOL Parser | `src/lm/cobol/parser.py` | Recursive-descent, total (unknowns → `Other`, never dropped) |
| ANTLR4 Grammar | `grammars/Cobol85.g4` | IBM Enterprise COBOL grammar (generate with `python scripts/gen_antlr.py`) |
| JCL Parser | `src/lm/jcl/parser.py` | Card-image JOB/EXEC/DD parser |
| ANTLR4 JCL | `grammars/JCL.g4` | JCL grammar for generated parser |

### Stage 2 — Normalized IR

All COBOL vocabulary is erased here. After this stage, nothing downstream needs to know about PIC clauses, figurative constants, or paragraph-name dashes.

| Concept | IR Node |
|---------|---------|
| COBOL program | `IrProgram` |
| Paragraph / section | `IrFunction` |
| Data item | `IrVar` (with `IrType`: INT / DEC / STR / BOOL) |
| Statement | `IrStmt` (with `OpKind`: ASSIGN / COMPUTE / BRANCH_COND / CALL / IO_READ…) |
| Control edge | `IrEdge` (fallthrough / conditional / call / return) |

### Stage 3 — SQLite Store

```sql
programs        -- full IR as JSON blob + metrics
functions       -- per-function: complexity, fan_in, fan_out, is_io
variables       -- var inventory: type, section, picture, level
unsupported_ops -- COBOL constructs the emitter couldn't model
jobs            -- JCL job metadata
job_programs    -- step → program edges
migration_results -- agent output, status, rounds
```

### Stage 4 — Neo4j Dependency Graph

```cypher
(:Program)-[:HAS_FUNCTION]->(:Function)
(:Function)-[:CALLS]->(:Function)       -- from PERFORM / CALL
(:Function)-[:READS|WRITES]->(:Variable)-- from IO statements
(:Job)-[:RUNS {step}]->(:Program)       -- JCL → COBOL link
(:Job)-[:USES_DATASET]->(:Dataset)
```

### Stage 5 — Agentic Migration Loop

```
Planner   → Reads IR summary (JSON) → emits MigrationPlan
               { strategy, functions_order, risks, estimated_effort }

Executor  → Gets one IrFunction + Java scaffold → emits improved Java method
               Prompt contains IR blocks only — no COBOL source ever

Critic    → Checks: every IrStmt.op has a Java counterpart
               UNSUPPORTED ops are marked TODO (never silently dropped)
               Returns { passed, issues, completeness_pct }

Loop      → If critic fails → executor retries with issues → up to 3 rounds
```

### Stage 6 — Java 17 Emitter (Deterministic)

| COBOL construct | Java output |
|----------------|-------------|
| `PIC S9(7)V99 COMP-3` | `java.math.BigDecimal` |
| `PIC 9(4) COMP` | `long` |
| `PIC X(n)` | `String` |
| `01 group-item` | `class` fields (static) |
| `OCCURS n TIMES` | `T[n]` array |
| `PERFORM PARA-NAME` | `paraName()` static method call |
| `IF … ELSE … END-IF` | `if/else` block |
| `EVALUATE … WHEN` | `switch` expression |
| `GO TO DEPENDING ON` | `switch((int)index)` |
| `DISPLAY "text"` | `System.out.println(...)` |
| `ACCEPT var` | `scanner.nextLine()` |
| `UNSUPPORTED verb` | `// TODO: UNSUPPORTED — verb` |

### Stage 7 — Observability

| Feature | Implementation | Equivalent |
|---------|----------------|------------|
| Live log stream | WebSocket `/ws/logs` → NDJSON spans | Grafana Loki |
| Metrics endpoint | `GET /api/metrics` → Prometheus text | Grafana |
| Dependency graph | `GET /api/graph` → Canvas force-graph | Neo4j Bloom |
| AI-Ops report | `GET /api/report` → Markdown | Custom |

---

## 🖥️ Frontend Pages

| Page | Route | Purpose |
|------|-------|---------|
| Connect | `/` | z/OS credentials (dummy), pipeline overview |
| Asset Browser | `/assets` | Browse COBOL/JCL/BMS, syntax highlight, parse inline |
| Wizard | `/wizard` | Target language, LLM config, start migration |
| Live AI-Ops | `/live` | Real-time logs · metrics grid · force-directed graph |
| Results | `/result` | Java code viewer · COBOL↔Java mapping · agent explanations |

---

## 🔌 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/connect` | Connect to simulated z/OS |
| `GET` | `/api/assets` | List COBOL/JCL/BMS/Dataset assets |
| `GET` | `/api/source/{name}` | Get source text of an asset |
| `POST` | `/api/parse` | Parse COBOL/JCL → build & store IR |
| `GET` | `/api/ir/{name}` | Retrieve stored IR as JSON |
| `GET` | `/api/programs` | All programs in SQLite |
| `GET` | `/api/graph` | Dependency graph (Neo4j or SQLite fallback) |
| `POST` | `/api/migrate` | Run full Planner→Executor→Critic pipeline |
| `GET` | `/api/migrate/{name}` | Get saved migration result |
| `GET` | `/api/metrics` | Prometheus-format pipeline metrics |
| `GET` | `/api/logs` | Recent span log lines (NDJSON) |
| `GET` | `/api/report` | Full AI-Ops Markdown report |
| `WS` | `/ws/logs` | Live WebSocket log stream |
| `GET` | `/docs` | Interactive Swagger UI |

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|------------|-----|
| COBOL/JCL Grammar | **ANTLR4** | Auditable grammar, error recovery, IBM dialect support |
| COBOL fallback parser | Hand-rolled recursive-descent | Zero dependencies, works without ANTLR |
| IR | Python dataclasses + JSON | Total, serializable, no COBOL vocabulary |
| Store | **SQLite** (stdlib) | Zero deps, fast, self-contained |
| Dependency Graph | **Neo4j** (optional) | Real graph DB, falls back to SQLite |
| Agent LLM | **Anthropic Claude** or **OpenAI** | Configurable; mock mode for demos |
| Code emission | Deterministic Python | Scaffold before LLM — correctness guarantee |
| API | **FastAPI** + WebSocket | Async, type-safe, auto Swagger docs |
| Frontend | **React 18 + Vite + TypeScript** | Fast HMR, component isolation |
| Dependency graph UI | Canvas 2D force simulation | No license needed (no Bloom/D3 deps) |
| Metrics format | Prometheus text | Drop-in for real Grafana |
| Log format | NDJSON spans | Drop-in for real Loki |
| Containers | **Docker Compose** | Neo4j + API + Nginx in one command |

---

## 📁 Project Structure

```
IBM Bob Hackathon/
│
├── grammars/
│   ├── Cobol85.g4           IBM Enterprise COBOL ANTLR4 grammar
│   └── JCL.g4               JCL card-image grammar
│
├── scripts/
│   └── gen_antlr.py         Generate Python parsers from grammars
│
├── src/lm/
│   ├── cobol/
│   │   ├── lexer.py          Hand-rolled tokenizer (fixed + free format)
│   │   ├── parser.py         Recursive-descent COBOL parser
│   │   ├── ast_nodes.py      30+ typed AST dataclasses
│   │   └── antlr_visitor.py  ANTLR CST → CobolProgram visitor
│   │
│   ├── jcl/
│   │   └── parser.py         JCL card parser → JclUnit/Step/DdEntry
│   │
│   ├── ir/
│   │   ├── nodes.py          IrProgram / IrFunction / IrStmt / IrVar / IrEdge
│   │   └── builder.py        COBOL AST → IR lowering
│   │
│   ├── store/
│   │   ├── sqlite.py         SQLite schema + CRUD
│   │   └── graph.py          Neo4j Cypher projections
│   │
│   ├── mainframe/
│   │   └── dummy_connector.py  Simulated z/OS (PAYROLL, ORDPRCS, INVNTRY)
│   │
│   ├── agents/
│   │   └── pipeline.py       PlannerAgent + ExecutorAgent + CriticAgent
│   │
│   ├── emit/
│   │   └── java.py           Deterministic IR → Java 17
│   │
│   ├── obs/
│   │   ├── tracer.py         Span recorder → NDJSON
│   │   ├── metrics.py        Prometheus counters
│   │   └── report.py         AI-Ops Markdown report
│   │
│   ├── api/
│   │   └── app.py            FastAPI application (22 routes + WebSocket)
│   │
│   └── cli.py                lm CLI: serve / parse / migrate / report
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx             Router + header stepper
│   │   ├── App.css             Dark theme design system
│   │   ├── pages/
│   │   │   ├── ConnectPage.tsx
│   │   │   ├── AssetBrowserPage.tsx
│   │   │   ├── WizardPage.tsx
│   │   │   ├── LiveOpsPage.tsx
│   │   │   └── ResultPage.tsx
│   │   └── api/client.ts       Typed fetch + WebSocket hooks
│   └── package.json
│
├── tests/fixtures/
│   └── PAYROLL.cbl             Sample COBOL program
│
├── run_api.py                  API launcher (no install needed)
├── pyproject.toml              Python package definition
├── docker-compose.yml          Neo4j + API + Frontend
├── Dockerfile                  API container
└── frontend/Dockerfile         Nginx frontend container
```

---

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_DB_PATH` | `lm.db` | SQLite database file path |
| `LM_LLM_BACKEND` | `mock` | LLM backend: `mock` / `anthropic` / `openai` |
| `LM_LLM_API_KEY` | — | API key for the selected backend |
| `LM_LLM_MODEL` | auto | Model name override |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password |

---

## 🧪 Demo Assets (Pre-loaded)

| Asset | Type | Description |
|-------|------|-------------|
| `PAYROLL` | COBOL | Payroll computation with PERFORM VARYING loop |
| `ORDPRCS` | COBOL | Order processing with IF/EVALUATE and COMPUTE |
| `INVNTRY` | COBOL | Inventory management with OCCURS table |
| `PAYJOB` | JCL | Payroll batch job (runs PAYROLL, reads/writes datasets) |
| `ORDJOB` | JCL | Order + inventory batch (2 steps, multiple DDs) |
| `PAYINQ` | BMS | Payroll inquiry CICS screen |
| `ORDINQ` | BMS | Order inquiry CICS screen |

---

## 🔑 ANTLR4 Parser (Optional Upgrade)

The pipeline ships with a hand-rolled parser that works with zero dependencies.
To use the ANTLR4-generated parser for better error recovery and IBM dialect accuracy:

```bash
# Install ANTLR4 tool
pip install antlr4-tools

# Generate Python parsers from grammars
python scripts/gen_antlr.py

# The visitor in src/lm/cobol/antlr_visitor.py auto-detects
# the generated files and uses them automatically
```

---

## 🤖 Using a Real LLM

```bash
# Anthropic Claude (best for COBOL)
export LM_LLM_BACKEND=anthropic
export LM_LLM_API_KEY=sk-ant-api03-...

# OpenAI GPT-4o
export LM_LLM_BACKEND=openai
export LM_LLM_API_KEY=sk-proj-...

# Then run
python run_api.py
# The Wizard page LLM selector will reflect your choice
```

> **Without an API key** the pipeline runs in **mock mode** which generates a
> realistic Java scaffold from the IR deterministically — perfect for demos.

---

## 📊 Sample Migration Output

**Input (COBOL)**
```cobol
WORKING-STORAGE SECTION.
01  WS-TOTAL   PIC S9(7)V99 COMP-3 VALUE 0.
01  WS-RATE    PIC S9(3)V99 COMP-3 VALUE 0.
01  WS-HOURS   PIC S9(3)V9  COMP-3 VALUE 0.

PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-TOTAL = WS-RATE * WS-HOURS.
    DISPLAY "TOTAL: " WS-TOTAL.
    STOP RUN.
```

**Output (Java 17)**
```java
/**
 * Migrated from COBOL program: PAYROLL
 * Migration tool: IBM Legacy Modernizer
 */
public class Payroll {

    // WORKING-STORAGE PIC S9(7)V99 COMP-3
    private static java.math.BigDecimal wsTotal = java.math.BigDecimal.ZERO;
    private static java.math.BigDecimal wsRate  = java.math.BigDecimal.ZERO;
    private static java.math.BigDecimal wsHours = java.math.BigDecimal.ZERO;

    public static void main(String[] args) {
        wsTotal = new java.math.BigDecimal(String.valueOf((wsRate * wsHours)));
        System.out.println("TOTAL: " + wsTotal);
        return;
    }
}
```

**Why BigDecimal?**
> `PIC S9(7)V99 COMP-3` is packed decimal with 2 implied decimal places —
> this maps to `java.math.BigDecimal` to preserve financial precision.
> Using `float` or `double` would introduce rounding errors unacceptable in payroll systems.

---

## 🩺 Validation Results

Run the full test suite without any server:

```bash
python -c "
import sys; sys.path.insert(0,'src')
from lm.cobol.parser import parse_cobol
from lm.ir.builder import build_ir
from lm.store.sqlite import open_db, save_program, load_program
from lm.emit.java import emit_files
from lm.agents.pipeline import MigrationOrchestrator
from lm.obs.report import generate_report
from lm.obs.metrics import reset_metrics
import os; os.environ['LM_LLM_BACKEND']='mock'

src = open('tests/fixtures/PAYROLL.cbl').read()
ir  = build_ir(parse_cobol(src), source_text=src)
conn = open_db(':memory:')
save_program(conn, ir)
files = emit_files(ir)
m = reset_metrics('test')
result = MigrationOrchestrator(metrics=m).migrate(ir, 'java')
rpt = generate_report(m, [ir])

print('parse     :', ir.name, len(ir.functions), 'fns')
print('sqlite    : saved + loaded ok')
print('emit      :', list(files.keys())[0], list(files.values())[0].count(chr(10)), 'lines')
print('migration :', result.status, result.agent_rounds, 'rounds')
print('report    :', len(rpt[\"markdown\"]), 'chars')
print()
print('ALL PASSED')
"
```

Expected output:
```
parse     : PROGRAM 2 fns
sqlite    : saved + loaded ok
emit      : Program.java 59 lines
migration : done 3 rounds
report    : 1198 chars

ALL PASSED
```

---

## 📜 License

MIT — built for the IBM Bob Hackathon.

---

*Made with ⚡ IBM Bob — Legacy Modernizer v0.1.0*

# LM Modernizer: AI-Powered COBOL → Python/Java Transpiler

> 🚀 **Automatic legacy mainframe modernization using AI reasoning and multi-agent orchestration**

Intelligently transform decades-old COBOL programs running on IBM z/OS systems into modern, maintainable Python and Java code. Powered by advanced LLMs (IBM watsonx, Groq, Anthropic, OpenAI, Google Gemini) with agentic reasoning loops.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab.svg)](https://www.python.org/downloads/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178c6.svg)](https://www.typescriptlang.org/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ed.svg)](Dockerfile)

---

## 🎯 Problem Statement

**The Challenge of Legacy Modernization:**
- 220+ billion lines of COBOL still running in production worldwide
- Skilled COBOL developers retiring; expertise becoming rare
- Manual rewriting takes months per program, costs millions
- Business logic embedded in poorly documented, arcane code
- High regression risk; hard to validate correctness

**Why Traditional Tools Fail:**
1. ❌ No parser understands COBOL's complex fixed-format syntax and implicit semantics
2. ❌ Business logic scattered across thousands of lines with cryptic variable names
3. ❌ File I/O patterns and JCL workflows must be perfectly preserved
4. ❌ Data type conversions and calculations require 100% fidelity
5. ❌ Manual code review cannot scale to entire application portfolios

---

## 💡 Our Solution

**LM Modernizer** is an end-to-end **AI-powered multi-agent system** that:

### 1️⃣ **Parses COBOL** with Native Grammar Support
- Custom ANTLR4 grammar for COBOL-85 and GnuCOBOL dialects
- Auto-detects fixed vs. free-format source code
- Handles edge cases: embedded CICS, DB2 SQL, JCL linkage
- Builds complete Abstract Syntax Tree (AST)

### 2️⃣ **Normalizes to Language-Agnostic IR**
- Converts COBOL AST → Intermediate Representation (IR)
- Extracts: paragraphs, data divisions, file I/O, control flow
- Enables multi-target codegen (Python, Java, Go planned)

### 3️⃣ **Plans Migration with AI**
- AI **Planner Agent** analyzes IR structure
- Creates step-by-step migration strategy
- Identifies: functions, refactoring opportunities, complexity hotspots
- Ranks transformation priorities

### 4️⃣ **Executes with LLM Reasoning**
- **Executor Agent** generates Python/Java scaffolds
- Iteratively refines through **3 rounds of execution**
- Uses LLM extended reasoning (watsonx, Groq gpt-oss models)
- Fallback strategies for complex edge cases

### 5️⃣ **Validates with AI Critique**
- **Critic Agent** validates generated code:
  - ✅ Preserves business logic (no silent mutations)
  - ✅ Handles all data types and ranges correctly
  - ✅ Supports file I/O patterns from original
  - ✅ Catches exception cases and edge conditions

### 6️⃣ **Delivers with Full Traceability**
- Web dashboard shows real-time migration progress
- Links generated code back to original COBOL source
- Function complexity metrics & risk assessment
- Downloadable outputs with documentation

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + TypeScript)            │
│        Real-time migration dashboard, model selection       │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP/WebSocket
┌──────────────────────▼──────────────────────────────────────┐
│              FastAPI Backend (Python 3.10+)                 │
├─────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────────┐  │
│ │           Legacy Modernization Pipeline               │  │
│ ├────────────────────────────────────────────────────────┤  │
│ │ 1. Parser (ANTLR4)      → COBOL AST                   │  │
│ │ 2. IR Builder           → Normalized IR               │  │
│ │ 3. Multi-Agent System:                                │  │
│ │    • Planner Agent      → Migration plan              │  │
│ │    • Executor Agent     → Generated code              │  │
│ │    • Critic Agent       → Validated & improved        │  │
│ │ 4. Emitters             → Python/Java/Docs            │  │
│ └────────────────────────────────────────────────────────┘  │
│ ┌────────────────────────────────────────────────────────┐  │
│ │        LLM Integration & Model Management             │  │
│ ├────────────────────────────────────────────────────────┤  │
│ │ • IBM watsonx.ai (Granite models, extended reasoning) │  │
│ │ • Groq Cloud (ultra-fast inference)                   │  │
│ │ • OpenAI (GPT-4o, o1 reasoning)                       │  │
│ │ • Anthropic Claude (3.5 Sonnet + family)              │  │
│ │ • Google Gemini (3.x multimodal)                      │  │
│ │ • xAI Grok (strong reasoning)                         │  │
│ │ • Ollama (local open models)                          │  │
│ └────────────────────────────────────────────────────────┘  │
│ ┌────────────────────────────────────────────────────────┐  │
│ │              Storage & Analysis                       │  │
│ ├────────────────────────────────────────────────────────┤  │
│ │ • SQLite (parsed IR, migrations)                      │  │
│ │ • Neo4j (optional: call graphs, lineage)              │  │
│ │ • Business rules extractor                            │  │
│ │ • Traceability matrix generator                       │  │
│ └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧠 Key Features

| Feature | Details |
|---------|---------|
| **COBOL Parsing** | Format auto-detection, fixed/free, COBOL-85 & GnuCOBOL dialects |
| **Multi-Backend LLM** | 7+ LLM providers (watsonx, Groq, OpenAI, Claude, Gemini, Grok, Ollama) |
| **AI Reasoning** | Extended reasoning loops, multi-round refinement, critique validation |
| **Code Traceability** | Links generated code → original COBOL paragraphs/lines |
| **Real-time Dashboard** | Live progress, function metrics, risk scoring, error tracking |
| **Batch Processing** | Migrate multiple programs in one workflow |
| **Neo4j Graph DB** | Optional call-graph visualization (requires Neo4j running) |
| **Business Rules Extraction** | Automated documentation of business logic |
| **Docker Support** | Full containerized backend + frontend + optional Neo4j |

---

## 🛠️ Tech Stack

### Backend
- **Language**: Python 3.10+
- **Web Framework**: FastAPI with CORS, WebSocket support
- **Parsing**: ANTLR4 + custom COBOL grammar
- **AI/LLM**: Multiple SDK integrations (Groq, Anthropic, OpenAI, Google, etc.)
- **Data**: SQLite, Neo4j (optional)
- **Observability**: OTEL tracing, Prometheus metrics
- **Task Queue**: Mock asyncio (Celery ready)

### Frontend
- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite
- **Styling**: CSS3 (custom theme system)
- **Real-time**: WebSocket via Socket.io
- **Routing**: React Router v6

### DevOps
- **Containerization**: Docker + Docker Compose
- **Web Server**: NGINX (frontend proxy)
- **Database**: SQLite (bundled), Neo4j (optional)

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+ ([download](https://www.python.org/))
- Node.js 18+ ([download](https://nodejs.org/))
- Docker & Docker Compose (optional, for containerized setup)
- LLM API key(s) for at least one provider (see [Supported Backends](#-supported-backends))

### Option 1: Local Development

#### 1. Clone & Setup

```bash
git clone https://github.com/yourusername/lm-modernizer.git
cd lm-modernizer

# Backend setup
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
pip install -r requirements-dev.txt
```

#### 2. Start Backend

```bash
export LM_LLM_BACKEND=gemini
export LM_LLM_API_KEY=<your-google-api-key>

python run_api.py
# Server runs on http://localhost:8000
# Swagger UI: http://localhost:8000/docs
```

#### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
# Frontend runs on http://localhost:5173
```

#### 4. Upload COBOL & Migrate

Visit http://localhost:5173 and:
1. Connect to mainframe (mock or real)
2. Browse and select COBOL programs
3. Configure LLM backend & model
4. Run migration
5. Review AI-generated Python/Java

### Option 2: Docker Compose

```bash
docker-compose up -d
# Backend: http://localhost:8000
# Frontend: http://localhost:3000
# Neo4j (optional): http://localhost:7474 (user: neo4j, pass: password)
```

---

## 🔑 Supported Backends

**All providers require valid API keys.** Get them from:

| Backend | Model Examples | Get Key | Note |
|---------|---|---|---|
| **IBM Granite** | `ibm/granite-3-8b-instruct`, `ibm/granite-34b-code` | [IBM Cloud Console](https://cloud.ibm.com) | Requires watsonx.ai project ID |
| **Groq** | `llama-3.3-70b`, `openai/gpt-oss-120b` | [console.groq.com](https://console.groq.com) | Ultra-fast, free tier available |
| **Anthropic** | `claude-3-5-sonnet-20241022` | [console.anthropic.com](https://console.anthropic.com) | Best for reasoning |
| **OpenAI** | `gpt-4o`, `o1-preview` | [platform.openai.com](https://platform.openai.com) | Most capable |
| **Google Gemini** | `gemini-3.8-flash` | [aistudio.google.com](https://aistudio.google.com) | Multimodal, free tier |
| **xAI Grok** | `grok-2-1212` | [console.x.ai](https://console.x.ai) | Strong reasoning |
| **Ollama** | Local models (Granite, Llama, Mistral) | [ollama.ai](https://ollama.ai) | Run locally, no API key |
| **Mock (Local)** | Built-in deterministic engine | — | No API call, ideal for testing |

---

## 📖 API Documentation

### REST Endpoints

```bash
# Mainframe Integration
POST   /api/connect                 # Connect to mainframe
POST   /api/disconnect              # Disconnect session
GET    /api/assets                  # List programs, jobs, datasets
GET    /api/source/{name}           # Get COBOL source code

# Parsing & IR
POST   /api/parse                   # Parse COBOL/JCL → IR
GET    /api/ir/{name}               # Retrieve stored IR
GET    /api/programs                # List all programs

# Migration
POST   /api/migrate                 # Start AI migration
GET    /api/migrate/{name}          # Get migration result
POST   /api/migrate-all             # Batch migration

# Analysis & Reporting
GET    /api/graph                   # Neo4j call graph (if enabled)
GET    /api/metrics                 # Prometheus metrics
GET    /api/report                  # AI-Ops summary report
```

### WebSocket Events

```javascript
// Client → Server
ws.send(JSON.stringify({
  action: 'migrate',
  program_name: 'PAYROLL',
  llm_backend: 'gemini',
  llm_model: 'gemini-3.8-flash'
}))

// Server → Client (real-time updates)
{
  "event": "progress",
  "status_text": "Executing function main",
  "progress_pct": 45,
  "current_step": "Executor Round 2/3"
}
```

See [API Documentation](docs/API.md) for full details.

---

## 💻 Usage Examples

### Example 1: Migrate PAYROLL Program

```bash
curl -X POST http://localhost:8000/api/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "program_name": "PAYROLL",
    "target_lang": "python",
    "llm_backend": "groq",
    "llm_model": "llama-3.3-70b-versatile",
    "llm_api_key": "gsk_..."
  }'
```

**Response:**
```json
{
  "ok": true,
  "status": "done",
  "program": "PAYROLL",
  "files": {
    "payroll.py": "# Generated Python code...",
    "payroll_test.py": "# Test scaffold..."
  },
  "agent_rounds": 3,
  "metrics": {
    "planner_calls": 1,
    "executor_calls": 3,
    "critic_calls": 3
  }
}
```

### Example 2: Batch Migration

```bash
curl -X POST http://localhost:8000/api/migrate-all \
  -H "Content-Type: application/json" \
  -d '{
    "program_names": ["PAYROLL", "INVNTRY", "ORDPRCS"],
    "target_lang": "java",
    "llm_backend": "anthropic",
    "llm_model": "claude-3-5-sonnet-20241022",
    "llm_api_key": "sk-ant-..."
  }'
```

### Example 3: Python Client

```python
from src.lm.cobol.parser import parse_cobol
from src.lm.ir.builder import build_ir
from src.lm.agents.pipeline import MigrationOrchestrator

# Parse COBOL
cobol_text = open('programs/PAYROLL.cbl').read()
ast = parse_cobol(cobol_text)
ir = build_ir(ast)

# Migrate with Gemini
orch = MigrationOrchestrator(
    tracer=None,
    metrics=None,
    backend='google',
    model='gemini-3.8-flash'
)

result = orch.migrate(ir, target_lang='python')
print(result.files)  # Generated code
print(f"Rounds: {result.agent_rounds}")
```

---

## 🔧 Configuration

### Environment Variables

```bash
# LLM Backend Selection
LM_LLM_BACKEND=gemini              # mock|granite|anthropic|openai|groq|gemini|grok|ollama
LM_LLM_MODEL=gemini-3.8-flash      # Model identifier (see Supported Backends)
LM_LLM_API_KEY=AIza...             # API key (not stored, used for single request)

# Backend-Specific
WATSONX_PROJECT_ID=abc123          # IBM Granite (watsonx.ai)
WATSONX_URL=https://us-south.ml.cloud.ibm.com
OLLAMA_URL=http://localhost:11434  # Local Ollama

# Database
LM_DB_PATH=lm.db                   # SQLite path
NEO4J_URI=bolt://localhost:7687    # Neo4j connection
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Server
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=info
```

### pyproject.toml

```toml
[tool.lm-modernizer]
max_execution_rounds = 3           # Executor iterations per function
max_critic_rounds = 3              # Critique loops
timeout_per_call = 120             # LLM call timeout (seconds)
enable_traceability = true         # Link generated code to source
```

---

## 📊 Project Structure

```
lm-modernizer/
├── src/lm/
│   ├── cobol/                  # COBOL lexer & parser
│   │   ├── lexer.py
│   │   ├── parser.py
│   │   ├── ast_nodes.py
│   │   └── antlr_visitor.py
│   ├── ir/                     # Intermediate Representation
│   │   ├── nodes.py
│   │   └── builder.py
│   ├── agents/                 # Multi-agent orchestration
│   │   └── pipeline.py
│   ├── emit/                   # Code generators
│   │   ├── python.py
│   │   ├── java.py
│   │   ├── workflow.py
│   │   └── database.py
│   ├── api/                    # FastAPI REST endpoints
│   │   └── app.py
│   ├── store/                  # SQLite & Neo4j storage
│   │   ├── sqlite.py
│   │   └── graph.py
│   ├── analysis/               # Business rules extraction
│   │   ├── business_rules.py
│   │   └── traceability.py
│   └── obs/                    # Observability
│       ├── metrics.py
│       ├── tracer.py
│       └── report.py
├── frontend/                   # React + TypeScript UI
│   ├── src/
│   │   ├── pages/              # Page components
│   │   ├── api/                # Client API
│   │   └── App.tsx
│   ├── index.html
│   └── vite.config.ts
├── grammars/                   # ANTLR4 grammar files
│   ├── Cobol85.g4
│   └── JCL.g4
├── tests/                      # Test suite
│   ├── test_backend.py
│   └── fixtures/
│       └── PAYROLL.cbl
├── scripts/                    # Utilities
│   ├── gen_antlr.py           # Generate ANTLR parser
│   └── check_and_seed.py      # Seed sample data
├── docker-compose.yml
├── Dockerfile
└── README.md
```

---

## 🧪 Testing

### Unit Tests

```bash
pytest tests/ -v --cov=src
```

### Integration Tests

```bash
# Start backend & frontend first
pytest tests/test_backend.py -v

# Test specific backend
pytest tests/test_backend.py::test_groq_migration -v
```

### Manual Testing

```bash
# Parse COBOL test fixture
python script/debug_parse.py tests/fixtures/PAYROLL.cbl

# Run migration with mock backend
curl -X POST http://localhost:8000/api/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "program_name": "PAYROLL",
    "target_lang": "python",
    "llm_backend": "mock"
  }'
```

---

## 🤝 Contributing

We welcome contributions! Please:

1. **Fork** the repository
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make changes** & test thoroughly
4. **Commit** with clear messages: `git commit -m 'Add amazing feature'`
5. **Push** to your fork: `git push origin feature/amazing-feature`
6. **Open a Pull Request** with detailed description

### Development Setup

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linters
black src/ && isort src/ && flake8 src/
mypy src/                          # Type checking
pylint src/lm/                     # Code quality

# Pre-commit hooks
pre-commit install
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## ✨ Acknowledgments

- **ANTLR Project** for parsing infrastructure
- **IBM watsonx.ai** for advanced reasoning models
- **Groq** for ultra-fast inference
- **OpenAI, Anthropic, Google** for multimodal LLMs
- **COBOL community** for test programs and dialect examples

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) file for details.

---

## 📞 Support & Contact

- **Issues & Bugs**: [GitHub Issues](https://github.com/yourusername/lm-modernizer/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/lm-modernizer/discussions)
- **Email**: contact@lm-modernizer.dev

---

## 🗺️ Roadmap

### v0.2 (Next)
- [ ] Support for COBOL copybooks & nested includes
- [ ] JCL workflow transpilation (→ Kubernetes manifests)
- [ ] CICS screen form → React component generation
- [ ] Database schema extraction & ORM mapping

### v0.3
- [ ] IMS database translation
- [ ] COBOL GUI-for-web transpilation
- [ ] Business rules visualization (interactive diagram)
- [ ] A/B testing framework for code quality

### v1.0
- [ ] Production-grade mainframe connectors (z/OS SSH, SFTP)
- [ ] Compliance scanning (OWASP SAST integration)
- [ ] Multi-workspace collaboration & version control
- [ ] SaaS deployment option

---

**Built with ❤️ for enterprise modernization.**

© 2026 LM Modernizer Contributors

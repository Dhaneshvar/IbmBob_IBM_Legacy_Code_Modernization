# Contributing to LM Modernizer

Thank you for your interest in contributing to LM Modernizer! 🎉

We welcome bug reports, feature requests, documentation improvements, and code contributions. This document outlines our process and guidelines.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Style & Quality](#code-style--quality)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Reporting Issues](#reporting-issues)
- [License](#license)

---

## 📜 Code of Conduct

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project, you agree to abide by its terms.

**We are committed to:**
- Being welcoming and inclusive
- Respecting all contributors
- Focusing on constructive feedback
- Having a harassment-free community

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- Git
- Docker + Docker Compose (optional)

### Setup Your Development Environment

1. **Fork the repository**
   ```bash
   git clone https://github.com/yourusername/lm-modernizer.git
   cd lm-modernizer
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Install dependencies**
   ```bash
   # Backend
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -e ".[dev]"

   # Frontend
   cd frontend
   npm install
   ```

4. **Set up Git hooks** (optional but recommended)
   ```bash
   pre-commit install
   ```

---

## 💻 Development Workflow

### 1. Create an Issue First
For non-trivial contributions, open an issue to discuss:
- What problem you're solving
- Your proposed solution
- Any design decisions or tradeoffs

### 2. Work on Your Feature

**Backend changes:**
```bash
cd src/lm/
# Edit relevant modules
# Example: src/lm/cobol/lexer.py, src/lm/agents/pipeline.py

# Test your changes
pytest tests/ -v --cov=src
```

**Frontend changes:**
```bash
cd frontend/
# Edit relevant components
# Example: src/pages/WizardPage.tsx, src/api/client.ts

npm run dev    # Live reload development server
npm run build  # Production build
```

### 3. Maintain Code Quality

**Format code:**
```bash
# Python
black src/
isort src/
autopep8 --in-place --aggressive --aggressive src/**/*.py

# TypeScript
cd frontend && npm run format
```

**Lint code:**
```bash
# Python
flake8 src/
pylint src/lm
mypy src/

# TypeScript
cd frontend && npm run lint
```

**Type checking:**
```bash
# Python - type annotations
mypy src/ --strict-optional

# TypeScript - built into IDE
cd frontend && npm run build
```

### 4. Write Tests

**For Python (backends, parsers, agents):**
```python
# tests/test_feature.py
import pytest
from src.lm.module import function_to_test

def test_functionality():
    result = function_to_test(input_data)
    assert result == expected_output

def test_error_handling():
    with pytest.raises(ValueError):
        function_to_test(invalid_input)
```

**For TypeScript (UI components):**
```typescript
// frontend/src/__tests__/Component.test.tsx
import { render, screen } from '@testing-library/react'
import Component from '../Component'

test('renders correctly', () => {
  render(<Component />)
  expect(screen.getByText('Expected Text')).toBeInTheDocument()
})
```

Run tests:
```bash
# Python
pytest tests/ -v

# TypeScript
cd frontend && npm test
```

---

## 📐 Code Style & Quality

### Python Standards
- **Format**: Black (line length: 100)
- **Import order**: isort
- **Linting**: flake8, pylint
- **Type hints**: mypy (preferably strict)
- **Docstrings**: Google style

Example:
```python
def parse_cobol(source: str) -> CobolAST:
    """Parse COBOL source code into an Abstract Syntax Tree.
    
    Args:
        source: Raw COBOL program text (fixed or free format)
        
    Returns:
        CobolAST with parsed programs, sections, paragraphs
        
    Raises:
        SyntaxError: If source contains invalid COBOL syntax
        
    Example:
        >>> ast = parse_cobol("IDENTIFICATION DIVISION...")
        >>> ast.programs[0].name
        'MYPROG'
    """
    # Implementation
```

### TypeScript Standards
- **Format**: Prettier (2 spaces)
- **Linting**: ESLint
- **Type**: Strict TypeScript (`strict: true`)
- **Framework**: React best practices

Example:
```typescript
interface MigrationOptions {
  programName: string
  targetLang: 'python' | 'java'
  llmBackend: string
}

export async function migrate(opts: MigrationOptions): Promise<MigrationResult> {
  // Implementation
}
```

### Documentation
- Use clear variable/function names
- Add docstrings/comments for complex logic
- Update README for feature changes
- Link related issues in commit messages

---

## 🧪 Testing Requirements

### Minimum Coverage
- Aim for **70%+ code coverage**
- All public APIs must have tests
- Edge cases and error paths tested

### Test Organization
```
tests/
├── test_parser.py          # COBOL lexer/parser tests
├── test_ir.py              # IR builder tests
├── test_agents.py          # Multi-agent orchestration
├── test_backend.py         # FastAPI endpoints
├── test_frontend.tsx       # React components
└── fixtures/
    ├── PAYROLL.cbl         # Test COBOL programs
    └── sample_ir.json      # Example IR
```

### Before Submitting PR
```bash
# Run full test suite
pytest tests/ -v --cov=src --cov-report=html

# Check coverage
coverage report  # Should be ≥70%

# Lint and format
black src/ && isort src/ && flake8 src/ && mypy src/
cd frontend && npm run lint && npm run format && npm test
```

---

## 🔄 Pull Request Process

### 1. Update Your Branch
```bash
git fetch origin
git rebase origin/main
```

### 2. Push Your Changes
```bash
git push origin feature/your-feature-name
```

### 3. Open a Pull Request

**PR Title**: Use clear, descriptive titles
- ❌ `Fix bug`
- ✅ `Fix case-insensitive function lookup in IR builder`

**PR Description** (use template):
```markdown
## Description
Brief explanation of changes and why they're needed.

## Related Issue
Closes #123

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Changes Made
- Change 1
- Change 2

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments/documentation updated
- [ ] No new warnings generated
- [ ] Tests pass locally
```

### 4. Code Review

**Reviewers will check:**
- ✅ Code quality & style consistency
- ✅ Test coverage & quality
- ✅ No regressions
- ✅ Documentation clarity
- ✅ Breaking changes noted

**Respond to feedback:**
- Address all comments
- Push follow-up commits (don't force-push unless requested)
- Re-request review after updates

### 5. Merge

Once approved:
- PR will be merged to `main`
- Your branch will be deleted
- Your contribution will be celebrated! 🎉

---

## 🐛 Reporting Issues

### Bug Reports

Use the bug report template:
```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Go to...
2. Click on...
3. See error

**Expected behavior**
Clear explanation of what should happen.

**Screenshots**
If applicable, add screenshots.

**Environment**
- OS: [e.g., Windows, macOS, Linux]
- Python: 3.10.x
- Node: 18.x
- LLM Backend: groq | gemini | etc.

**Additional context**
Any additional information that might be helpful.
```

### Feature Requests

Use the feature request template:
```markdown
**Is your feature related to a problem?**
Description of the problem.

**Describe the solution you'd like**
Clear description of desired behavior.

**Describe alternatives you've considered**
Other approaches considered.

**Additional context**
Use cases, mockups, reference implementations.
```

---

## 🎓 Development Tips

### Architecture & Key Modules

- **Parser** (`src/lm/cobol/`): ANTLR4-based COBOL parsing
- **IR** (`src/lm/ir/`): Language-neutral intermediate representation
- **Agents** (`src/lm/agents/`): Multi-agent orchestration pipeline
- **Emitters** (`src/lm/emit/`): Code generators (Python, Java, etc.)
- **API** (`src/lm/api/`): FastAPI REST endpoints
- **Frontend** (`frontend/src/`): React + TypeScript UI

### Common Tasks

**Add a new LLM backend:**
1. Update `src/lm/agents/pipeline.py` (add backend case)
2. Update `frontend/src/pages/WizardPage.tsx` (add to MODEL_CATALOGUE)
3. Add tests in `tests/test_backend.py`

**Add a new code emitter (e.g., Go):**
1. Create `src/lm/emit/go.py`
2. Implement `emit_program()` and `emit_files()`
3. Register in `src/lm/agents/pipeline.py`
4. Update frontend language options

**Improve COBOL parsing:**
1. Update `grammars/Cobol85.g4`
2. Run `python scripts/gen_antlr.py`
3. Add test case to `tests/test_parser.py`

### Debugging Tips

```bash
# Enable verbose logging
LM_LOG_LEVEL=DEBUG python run_api.py

# Debug migrations
python -c "
from src.lm.cobol.parser import parse_cobol
from src.lm.ir.builder import build_ir

cbl = open('tests/fixtures/PAYROLL.cbl').read()
ast = parse_cobol(cbl)
ir = build_ir(ast)
print(ir.to_json())
"

# Test specific LLM integration
pytest tests/test_backend.py::test_groq_migration -v -s

# Profile performance
python -m cProfile -s cumulative run_api.py
```

---

## 📚 Resources

- [COBOL-85 Standard](https://en.wikipedia.org/wiki/COBOL)
- [ANTLR4 Documentation](https://www.antlr.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [Black Code Formatter](https://black.readthedocs.io/)
- [mypy Type Checker](https://www.mypy-lang.org/)

---

## ❓ Questions?

- **Issues & Discussions**: [GitHub Discussions](https://github.com/yourusername/lm-modernizer/discussions)
- **Email**: contributors@lm-modernizer.dev

Thank you for contributing! ❤️

---

**Last Updated**: September 2026

"""Automated unit and integration test suite for the modernization backend."""
import json
import pytest
from fastapi.testclient import TestClient

from lm.cobol.parser import parse_cobol
from lm.ir.builder import build_ir, build_ir_from_jcl
from lm.jcl.parser import parse_jcl
from lm.emit.java import emit_program
from lm.agents.pipeline import MigrationOrchestrator
from lm.mainframe.dummy_connector import _MOCK_COBOL, _MOCK_JCL, _MOCK_BMS, _MOCK_DATASETS
from lm.store import sqlite as db
from lm.api.app import app


def test_cobol_parser_all_mock_programs():
    """Ensure all sample programs parse cleanly and lower to IR without errors."""
    for name, src in _MOCK_COBOL.items():
        ast = parse_cobol(src, path=name)
        assert ast is not None
        ir = build_ir(ast, path=name, source_text=src)
        assert ir.name in (name, "PROGRAM")
        assert len(ir.functions) >= 1
        assert len(ir.vars) >= 1


def test_jcl_parser_all_mock_jobs():
    """Ensure all sample JCL jobs parse with accurate steps, programs, and datasets."""
    for name, src in _MOCK_JCL.items():
        jcl = parse_jcl(src, path=name)
        assert jcl is not None
        job = build_ir_from_jcl(jcl, path=name)
        assert job.name == name
        assert len(job.steps) >= 1
        assert len(job.datasets) >= 1
        # Check programs
        for s in job.steps:
            assert s["pgm"] in ("PAYROLL", "ORDPRCS", "INVNTRY")


def test_emit_java():
    """Verify deterministic Java generation produces valid class structure."""
    ast = parse_cobol(_MOCK_COBOL["PAYROLL"], path="PAYROLL")
    ir = build_ir(ast, path="PAYROLL", source_text=_MOCK_COBOL["PAYROLL"])
    java_code = emit_program(ir)
    assert "public class Payroll" in java_code
    assert "public static void main" in java_code
    assert "java.math.BigDecimal" in java_code


def test_agent_orchestrator_mock():
    """Verify full agentic migration loop (Planner -> Executor -> Critic) passes."""
    ast = parse_cobol(_MOCK_COBOL["PAYROLL"], path="PAYROLL")
    ir = build_ir(ast, path="PAYROLL", source_text=_MOCK_COBOL["PAYROLL"])
    orch = MigrationOrchestrator()
    res = orch.migrate(ir, target_lang="java")
    assert res.status == "done"
    assert res.agent_rounds >= 1
    assert "Payroll.java" in res.files
    code = res.files["Payroll.java"]
    assert "public class Payroll" in code


def test_api_full_flow(tmp_path):
    """Test all FastAPI endpoints in sequence."""
    test_db = tmp_path / "test.db"
    conn = db.open_db(test_db)
    
    with TestClient(app) as client:
        # 1. Health
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # 2. Connect
        r = client.post("/api/connect", json={"host": "zos.example.com", "port": 23, "user": "IBMUSER", "password": "PW"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # 3. Assets
        r = client.get("/api/assets")
        assert r.status_code == 200
        assets = r.json()["assets"]
        assert len(assets) > 0

        # 4. Source
        r = client.get("/api/source/PAYROLL")
        assert r.status_code == 200
        payroll_src = r.json()["source"]
        assert "IDENTIFICATION DIVISION" in payroll_src

        # 5. Parse COBOL (PAYROLL)
        r = client.post("/api/parse", json={"name": "PAYROLL", "source": payroll_src, "source_type": "COBOL", "store": True, "push_graph": True})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["ir_summary"]["functions"] == 2

        # 6. Parse JCL (PAYJOB)
        jcl_src = _MOCK_JCL["PAYJOB"]
        r = client.post("/api/parse", json={"name": "PAYJOB", "source": jcl_src, "source_type": "JCL", "store": True, "push_graph": True})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["ir_summary"]["steps"] == 1
        assert r.json()["ir_summary"]["datasets"] == 2

        # 6b. Parse BMS (PAYINQ)
        bms_src = _MOCK_BMS["PAYINQ"]
        r = client.post("/api/parse", json={"name": "PAYINQ", "source": bms_src, "source_type": "BMS", "store": True, "push_graph": True})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["ir_summary"]["fields"] >= 4
        assert r.json()["ir_summary"]["dimensions"] == "24x80"

        # Check /api/ir/PAYINQ
        r = client.get("/api/ir/PAYINQ")
        assert r.status_code == 200
        assert r.json()["name"] == "PAYINQ"
        assert len(r.json()["fields"]) >= 4

        # 6c. Parse DATASET (HLQ.PAYROLL.INPUT)
        ds_src = _MOCK_DATASETS["HLQ.PAYROLL.INPUT"]
        r = client.post("/api/parse", json={"name": "HLQ.PAYROLL.INPUT", "source": ds_src, "source_type": "DATASET", "store": True, "push_graph": True})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["ir_summary"]["records"] == 10
        assert r.json()["ir_summary"]["recfm"] == "FB"

        # Check /api/ir/HLQ.PAYROLL.INPUT
        r = client.get("/api/ir/HLQ.PAYROLL.INPUT")
        assert r.status_code == 200
        assert r.json()["name"] == "HLQ.PAYROLL.INPUT"

        # 7. Programs & Jobs
        r = client.get("/api/programs")
        assert r.status_code == 200
        assert any(p["name"] == "PAYROLL" for p in r.json()["programs"])

        r = client.get("/api/jobs")
        assert r.status_code == 200
        assert any(j["name"] == "PAYJOB" for j in r.json()["jobs"])

        # 8. Graph (SQLite fallback) - Full multi-asset graph
        r = client.get("/api/graph")
        assert r.status_code == 200
        graph_data = r.json()
        assert len(graph_data["nodes"]) >= 4
        assert len(graph_data["links"]) >= 2
        labels = {n["label"] for n in graph_data["nodes"]}
        assert "Program" in labels
        assert "Job" in labels
        assert "Screen" in labels
        assert "Dataset" in labels

        # Subgraph for BMS
        r = client.get("/api/graph?program=PAYINQ")
        assert r.status_code == 200
        sub_bms = r.json()
        assert any(n["label"] == "Screen" for n in sub_bms["nodes"])
        assert any(n["label"] == "Field" for n in sub_bms["nodes"])

        # Subgraph for Dataset
        r = client.get("/api/graph?program=HLQ.PAYROLL.INPUT")
        assert r.status_code == 200
        sub_ds = r.json()
        assert any(n["label"] == "Dataset" for n in sub_ds["nodes"])

        # Subgraph for Program PAYROLL
        r = client.get("/api/graph?program=PAYROLL")
        assert r.status_code == 200
        sub_pgm = r.json()
        assert any(n["name"] == "PAYROLL" for n in sub_pgm["nodes"])

        # 9. Migrate
        r = client.post("/api/migrate", json={"program_name": "PAYROLL", "target_lang": "java"})
        assert r.status_code == 200
        res = r.json()
        assert res["ok"] is True
        assert res["status"] == "done"
        assert "Payroll.java" in res["files"]

        # 10. Get migration
        r = client.get("/api/migrate/PAYROLL")
        assert r.status_code == 200
        assert r.json()["status"] == "done"
        assert "Payroll.java" in r.json()["file_contents"]

        # 11. Metrics & Logs & Report
        r = client.get("/api/metrics")
        assert r.status_code == 200
        assert "programs_parsed" in r.json()

        r = client.get("/api/metrics/prometheus")
        assert r.status_code == 200
        assert "lm_programs_parsed" in r.text

        r = client.get("/api/logs")
        assert r.status_code == 200
        assert isinstance(r.json()["logs"], list)

        r = client.get("/api/report")
        assert r.status_code == 200
        assert "markdown" in r.json()
        assert "# Legacy Modernization AI-Ops Report" in r.json()["markdown"]

        # 12. Stats
        r = client.get("/api/stats")
        assert r.status_code == 200
        assert r.json()["programs"] >= 1

"""SQLite persistence layer for the modernization pipeline.

Schema
------
programs        -- one row per parsed COBOL program (full IR as JSON blob)
functions       -- extracted per-function metrics
variables       -- variable inventory
unsupported_ops -- constructs the emitter could not model
jobs            -- JCL job metadata
job_programs    -- step → program edges
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from ..ir.nodes import IrJob, IrProgram


# ─────────────────────────────── DDL ──────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS programs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    path        TEXT,
    dialect     TEXT,
    source_format TEXT,
    source_lines  INTEGER DEFAULT 0,
    source_bytes  INTEGER DEFAULT 0,
    ir_json     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_programs_name ON programs(name);

CREATE TABLE IF NOT EXISTS functions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prog_id       INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    kind          TEXT,
    complexity    INTEGER DEFAULT 1,
    fan_in        INTEGER DEFAULT 0,
    fan_out       INTEGER DEFAULT 0,
    is_io         BOOLEAN DEFAULT 0,
    unsupported_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_functions_prog ON functions(prog_id);

CREATE TABLE IF NOT EXISTS variables (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    prog_id  INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    vid      TEXT    NOT NULL,
    name     TEXT    NOT NULL,
    type     TEXT,
    section  TEXT,
    picture  TEXT,
    level    TEXT,
    occurs   INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_variables_prog ON variables(prog_id);

CREATE TABLE IF NOT EXISTS unsupported_ops (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    prog_id   INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    function  TEXT,
    verb      TEXT,
    text      TEXT,
    line      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    path       TEXT,
    ir_json    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_name ON jobs(name);

CREATE TABLE IF NOT EXISTS job_programs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step_name TEXT,
    pgm       TEXT
);

CREATE TABLE IF NOT EXISTS migration_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prog_id     INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    target_lang TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    plan_json   TEXT,
    output_json TEXT,
    report_md   TEXT,
    agent_rounds INTEGER DEFAULT 0,
    created_at  TEXT    NOT NULL,
    finished_at TEXT
);
"""


# ─────────────────────────────── connection ────────────────────────────────

def open_db(path: str | Path = "lm.db") -> sqlite3.Connection:
    """Open (or create) the SQLite database and apply migrations."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    conn.commit()
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ─────────────────────────────── programs ──────────────────────────────────

def save_program(conn: sqlite3.Connection, ir: IrProgram) -> int:
    """Insert or replace a program. Returns the row id."""
    now = datetime.now(timezone.utc).isoformat()
    ir_json = json.dumps(ir.to_json())
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO programs (name, path, dialect, source_format,
                                  source_lines, source_bytes, ir_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                path=excluded.path, dialect=excluded.dialect,
                source_format=excluded.source_format,
                source_lines=excluded.source_lines,
                source_bytes=excluded.source_bytes,
                ir_json=excluded.ir_json,
                created_at=excluded.created_at
            """,
            (
                ir.name, ir.path, ir.dialect, ir.source_format,
                ir.source_lines, ir.source_bytes, ir_json, now,
            ),
        )
        prog_id = cur.lastrowid or _get_prog_id(conn, ir.name)

        # Refresh child tables
        conn.execute("DELETE FROM functions WHERE prog_id=?", (prog_id,))
        conn.execute("DELETE FROM variables WHERE prog_id=?", (prog_id,))
        conn.execute("DELETE FROM unsupported_ops WHERE prog_id=?", (prog_id,))

        for fn in ir.functions:
            conn.execute(
                """INSERT INTO functions
                   (prog_id, name, kind, complexity, fan_in, fan_out, is_io, unsupported_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (prog_id, fn.name, fn.kind, fn.complexity,
                 fn.fan_in, fn.fan_out, fn.is_io, fn.unsupported_count),
            )

        for vid, var in ir.vars.items():
            conn.execute(
                """INSERT INTO variables (prog_id, vid, name, type, section, picture, level, occurs)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (prog_id, vid, var.name, var.type.value if hasattr(var.type, "value") else str(var.type),
                 var.section, var.picture, var.level, var.occurs),
            )

        for u in ir.unsupported:
            conn.execute(
                """INSERT INTO unsupported_ops (prog_id, function, verb, text, line)
                   VALUES (?,?,?,?,?)""",
                (prog_id, u.get("function", ""), u.get("verb", ""),
                 u.get("text", ""), u.get("line", 0)),
            )

    return prog_id


def _get_prog_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM programs WHERE name=?", (name,)).fetchone()
    return row["id"] if row else 0


def load_program(conn: sqlite3.Connection, name: str) -> Optional[IrProgram]:
    row = conn.execute("SELECT ir_json FROM programs WHERE name=?", (name,)).fetchone()
    if not row:
        return None
    return IrProgram.from_json(json.loads(row["ir_json"]))


def all_programs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT p.id, p.name, p.path, p.dialect, p.source_format,
                  p.source_lines, p.source_bytes, p.created_at,
                  COUNT(DISTINCT f.id) as fn_count,
                  COUNT(DISTINCT v.id) as var_count,
                  COUNT(DISTINCT u.id) as unsupported_count
           FROM programs p
           LEFT JOIN functions f ON f.prog_id=p.id
           LEFT JOIN variables v ON v.prog_id=p.id
           LEFT JOIN unsupported_ops u ON u.prog_id=p.id
           GROUP BY p.id
           ORDER BY p.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def program_functions(conn: sqlite3.Connection, prog_name: str) -> list[dict]:
    prog_id = _get_prog_id(conn, prog_name)
    rows = conn.execute(
        "SELECT * FROM functions WHERE prog_id=? ORDER BY complexity DESC",
        (prog_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────── jobs ──────────────────────────────────────

def save_job(conn: sqlite3.Connection, job: IrJob) -> int:
    from dataclasses import asdict
    now = datetime.now(timezone.utc).isoformat()
    ir_json = json.dumps(asdict(job))
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO jobs (name, path, ir_json, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   path=excluded.path, ir_json=excluded.ir_json,
                   created_at=excluded.created_at""",
            (job.name, job.path, ir_json, now),
        )
        job_id = cur.lastrowid or _get_job_id(conn, job.name)
        conn.execute("DELETE FROM job_programs WHERE job_id=?", (job_id,))
        for step in job.steps:
            if step.get("pgm"):
                conn.execute(
                    "INSERT INTO job_programs (job_id, step_name, pgm) VALUES (?,?,?)",
                    (job_id, step.get("name", ""), step.get("pgm", "")),
                )
    return job_id


def _get_job_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM jobs WHERE name=?", (name,)).fetchone()
    return row["id"] if row else 0


def all_jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT j.id, j.name, j.path, j.created_at,
                  COUNT(DISTINCT jp.id) as step_count
           FROM jobs j
           LEFT JOIN job_programs jp ON jp.job_id=j.id
           GROUP BY j.id ORDER BY j.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────── migration results ─────────────────────────

def save_migration(
    conn: sqlite3.Connection,
    prog_name: str,
    target_lang: str,
    status: str,
    plan_json: Optional[str] = None,
    output_json: Optional[str] = None,
    report_md: Optional[str] = None,
    agent_rounds: int = 0,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    prog_id = _get_prog_id(conn, prog_name)
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO migration_results
               (prog_id, target_lang, status, plan_json, output_json, report_md,
                agent_rounds, created_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (prog_id, target_lang, status, plan_json, output_json, report_md,
             agent_rounds, now, now if status == "done" else None),
        )
    return cur.lastrowid or 0


def get_migration(conn: sqlite3.Connection, prog_name: str, target_lang: str) -> Optional[dict]:
    prog_id = _get_prog_id(conn, prog_name)
    row = conn.execute(
        """SELECT * FROM migration_results WHERE prog_id=? AND target_lang=?
           ORDER BY created_at DESC LIMIT 1""",
        (prog_id, target_lang),
    ).fetchone()
    return dict(row) if row else None


# ─────────────────────────────── stats ─────────────────────────────────────

def pipeline_stats(conn: sqlite3.Connection) -> dict:
    progs = conn.execute("SELECT COUNT(*) as c FROM programs").fetchone()["c"]
    fns = conn.execute("SELECT COUNT(*) as c FROM functions").fetchone()["c"]
    vars_ = conn.execute("SELECT COUNT(*) as c FROM variables").fetchone()["c"]
    unsup = conn.execute("SELECT COUNT(*) as c FROM unsupported_ops").fetchone()["c"]
    jobs = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
    migs = conn.execute("SELECT COUNT(*) as c FROM migration_results WHERE status='done'").fetchone()["c"]
    return {
        "programs": progs,
        "functions": fns,
        "variables": vars_,
        "unsupported_ops": unsup,
        "jobs": jobs,
        "migrations_done": migs,
    }

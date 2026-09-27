"""Neo4j dependency graph projection.

Pushes IR programs and JCL jobs into a Neo4j graph database.
Falls back silently when the driver is not installed or the server is down.

Node types:
    (:Program)   — a parsed COBOL program
    (:Function)  — one per paragraph / main function inside a program
    (:Variable)  — data items declared in the program
    (:Dataset)   — JCL datasets (DSN= values)
    (:Job)       — a JCL JOB

Relationship types:
    (:Program)-[:HAS_FUNCTION]->(:Function)
    (:Function)-[:CALLS]->(:Function)
    (:Function)-[:READS|WRITES]->(:Variable)
    (:Job)-[:RUNS {step}]->(:Program)
    (:Job)-[:USES_DATASET]->(:Dataset)
    (:Program)-[:USES_DATASET]->(:Dataset)   (via file section names)
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from ..ir.nodes import IrJob, IrProgram, OpKind

log = logging.getLogger(__name__)


# ─────────────────────────────── driver ───────────────────────────────────

def get_driver(uri: str, user: str = "neo4j", password: str = "password"):
    """Return a *connected* neo4j Driver, or None if Neo4j is unavailable.

    ``GraphDatabase.driver()`` is lazy: it succeeds even when nothing is
    listening on the bolt port, and the failure only surfaces later as an
    opaque ``ServiceUnavailable`` from inside a request handler. We verify
    connectivity here so callers degrade to their fallback path instead.
    """
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError:
        log.warning("neo4j package not installed — graph projection disabled. "
                    "Install with: pip install neo4j")
        return None

    # Fast socket probe so offline Neo4j doesn't stall startup for 30s
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    try:
        sock = socket.create_connection((host, port), timeout=0.5)
        sock.close()
    except Exception as exc:
        log.warning("Neo4j unavailable at %s:%s (%s) — graph projection disabled.", host, port, exc)
        return None

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=1.0)
        driver.verify_connectivity()
        return driver
    except Exception as exc:
        log.warning("Neo4j unavailable at %s (%s) — graph projection disabled.", uri, exc)
        return None


# ─────────────────────────────── schema constraints ───────────────────────

_CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Program)  REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Function) REQUIRE f.id   IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (j:Job)      REQUIRE j.name IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dataset)  REQUIRE d.dsn  IS UNIQUE",
]


def ensure_schema(driver) -> None:
    with driver.session() as s:
        for q in _CONSTRAINTS:
            try:
                s.run(q)
            except Exception:
                pass  # Neo4j Community doesn't support all constraint types


# ─────────────────────────────── programs ─────────────────────────────────

def push_program(driver, ir: IrProgram) -> None:
    """Upsert an IrProgram into Neo4j."""
    if driver is None:
        return
    with driver.session() as s:
        # Program node
        s.run(
            """
            MERGE (p:Program {name: $name})
            SET p.path=$path, p.dialect=$dialect,
                p.source_format=$sf, p.source_lines=$lines,
                p.uses_files=$uses_files
            """,
            name=ir.name, path=ir.path, dialect=ir.dialect,
            sf=ir.source_format, lines=ir.source_lines,
            uses_files=ir.uses_files,
        )

        # Function nodes and Program→Function edges
        for fn in ir.functions:
            fn_id = f"{ir.name}.{fn.name}"
            s.run(
                """
                MERGE (f:Function {id: $id})
                SET f.name=$name, f.kind=$kind, f.complexity=$cx,
                    f.fan_in=$fi, f.fan_out=$fo, f.is_io=$io,
                    f.unsupported=$unsup, f.prog=$prog
                WITH f
                MATCH (p:Program {name: $prog})
                MERGE (p)-[:HAS_FUNCTION]->(f)
                """,
                id=fn_id, name=fn.name, kind=fn.kind,
                cx=fn.complexity, fi=fn.fan_in, fo=fn.fan_out,
                io=fn.is_io, unsup=fn.unsupported_count, prog=ir.name,
            )

        # Call edges (PERFORM / CALL)
        for fn in ir.functions:
            caller_id = f"{ir.name}.{fn.name}"
            for callee_name in set(fn.callees):
                callee_id = f"{ir.name}.{callee_name}"
                s.run(
                    """
                    MERGE (a:Function {id: $cid})
                    MERGE (b:Function {id: $eid})
                    MERGE (a)-[:CALLS]->(b)
                    """,
                    cid=caller_id, eid=callee_id,
                )

        # Variable nodes (top-level only to keep graph manageable)
        for vid, var in ir.vars.items():
            if var.section in ("WORKING-STORAGE", "FILE", "LINKAGE") and var.level in ("01", "77"):
                s.run(
                    """
                    MERGE (v:Variable {id: $id})
                    SET v.name=$name, v.type=$type, v.section=$sec,
                        v.picture=$pic, v.prog=$prog
                    WITH v
                    MATCH (p:Program {name: $prog})
                    MERGE (p)-[:DECLARES]->(v)
                    """,
                    id=f"{ir.name}.{vid}", name=var.name,
                    type=var.type.value if hasattr(var.type, "value") else str(var.type),
                    sec=var.section, pic=var.picture or "", prog=ir.name,
                )

        # IO edges: function → variable
        for fn in ir.functions:
            fn_id = f"{ir.name}.{fn.name}"
            for blk in fn.blocks:
                for stmt in blk.stmts:
                    if stmt.op in (OpKind.IO_READ,) and stmt.file:
                        _add_io_edge(s, fn_id, f"{ir.name}.{stmt.file}", "READS")
                    elif stmt.op in (OpKind.IO_WRITE,) and stmt.file:
                        _add_io_edge(s, fn_id, f"{ir.name}.{stmt.file}", "WRITES")

    log.info("Pushed program %s to Neo4j (%d functions)", ir.name, len(ir.functions))


def _add_io_edge(session, fn_id: str, var_id: str, rel: str) -> None:
    session.run(
        f"""
        MERGE (f:Function {{id: $fid}})
        MERGE (v:Variable {{id: $vid}})
        MERGE (f)-[:{rel}]->(v)
        """,
        fid=fn_id, vid=var_id,
    )


# ─────────────────────────────── jobs ─────────────────────────────────────

def push_job(driver, job: IrJob) -> None:
    """Upsert a JCL job into Neo4j."""
    if driver is None:
        return
    with driver.session() as s:
        s.run(
            "MERGE (j:Job {name: $name}) SET j.path=$path",
            name=job.name, path=job.path,
        )
        for step in job.steps:
            pgm = step.get("pgm")
            if pgm:
                s.run(
                    """
                    MERGE (p:Program {name: $pgm})
                    WITH p
                    MATCH (j:Job {name: $job})
                    MERGE (j)-[:RUNS {step: $step}]->(p)
                    """,
                    pgm=pgm, job=job.name, step=step.get("name", ""),
                )
        for ds in job.datasets:
            s.run(
                """
                MERGE (d:Dataset {dsn: $dsn})
                SET d.recfm=$recfm, d.lrecl=$lrecl, d.is_temp=$temp
                WITH d
                MATCH (j:Job {name: $job})
                MERGE (j)-[:USES_DATASET]->(d)
                """,
                dsn=ds.name, recfm=ds.recfm, lrecl=ds.lrecl,
                temp=ds.is_temp, job=job.name,
            )
    log.info("Pushed job %s to Neo4j (%d datasets)", job.name, len(job.datasets))


# ─────────────────────────────── query helpers ────────────────────────────

#: Node ids are ``{Program}.{Function}`` for functions and variables, and the
#: bare program name for :Program nodes — so prefer ``id`` and fall back to
#: ``name``. Written as two single-hop queries because ``startNode()`` may not
#: be projected out of a variable-length path.
_SUBGRAPH_NODES = """
MATCH path = (:Program {name: $name})-[*0..2]-()
UNWIND nodes(path) AS nd
WITH DISTINCT nd
RETURN collect({
    id: coalesce(nd.id, nd.name),
    label: labels(nd)[0],
    name: coalesce(nd.name, nd.id),
    complexity: nd.complexity
}) AS nodes
"""

_SUBGRAPH_LINKS = """
MATCH path = (:Program {name: $name})-[*0..2]-()
UNWIND relationships(path) AS r
WITH DISTINCT r
RETURN collect({
    source: coalesce(startNode(r).id, startNode(r).name),
    target: coalesce(endNode(r).id, endNode(r).name),
    type: type(r)
}) AS links
"""


def dependency_subgraph(driver, program_name: str) -> dict:
    """Return a JSON-serializable subgraph centred on a program."""
    if driver is None:
        return {"nodes": [], "links": []}
    with driver.session() as s:
        node_row = s.run(_SUBGRAPH_NODES, name=program_name).single()
        link_row = s.run(_SUBGRAPH_LINKS, name=program_name).single()
    nodes = (node_row["nodes"] if node_row else []) or []
    links = (link_row["links"] if link_row else []) or []
    return {
        "nodes": [n for n in nodes if n.get("id")],
        "links": [lk for lk in links if lk.get("source") and lk.get("target")],
    }


def full_graph(driver) -> dict:
    """Return the complete graph for the dashboard visualisation."""
    if driver is None:
        return {"nodes": [], "links": []}
    with driver.session() as s:
        nodes_result = s.run(
            """
            MATCH (n) WHERE n:Program OR n:Function OR n:Job OR n:Dataset
            RETURN id(n) as uid,
                   labels(n)[0] as label,
                   CASE WHEN n.name IS NOT NULL THEN n.name ELSE n.id END as name,
                   n.complexity as complexity,
                   n.prog as prog
            LIMIT 500
            """
        )
        links_result = s.run(
            """
            MATCH (a)-[r]->(b)
            WHERE (a:Program OR a:Function OR a:Job OR a:Dataset)
              AND (b:Program OR b:Function OR b:Job OR b:Dataset)
            RETURN id(a) as source, id(b) as target, type(r) as type
            LIMIT 1000
            """
        )
        nodes = [dict(r) for r in nodes_result]
        links = [dict(r) for r in links_result]
        return {"nodes": nodes, "links": links}

"""Verify parsing + DB state and seed missing assets."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from lm.mainframe.dummy_connector import _MOCK_COBOL, _MOCK_JCL
from lm.cobol.parser import parse_cobol
from lm.ir.builder import build_ir, build_ir_from_jcl
from lm.jcl.parser import parse_jcl
from lm.store.sqlite import open_db, save_program, save_job, load_program, all_programs, all_jobs

conn = open_db('lm.db')

print("=== COBOL Programs ===")
for name, src in _MOCK_COBOL.items():
    try:
        ast = parse_cobol(src, path=name)
        ir = build_ir(ast, path=name, source_text=src)
        save_program(conn, ir)
        fns = [f.name for f in ir.functions if f.name != '__FILES__']
        unsup = len(ir.unsupported)
        print(f"  OK {name}: {len(fns)} fns={fns}, {len(ir.vars)} vars, {len(ir.unsupported)} unsupported")
        if unsup:
            for u in ir.unsupported:
                print(f"     UNSUP: {u}")
    except Exception as e:
        print(f"  FAIL {name}: {e}")

print("\n=== JCL Jobs ===")
for name, src in _MOCK_JCL.items():
    try:
        jcl = parse_jcl(src, path=name)
        job = build_ir_from_jcl(jcl, path=name)
        save_job(conn, job)
        print(f"  OK {name}: {len(job.steps)} steps, {len(job.datasets)} datasets")
        for s in job.steps:
            print(f"     step={s.get('name')} pgm={s.get('pgm')}")
    except Exception as e:
        print(f"  FAIL {name}: {e}")

print("\n=== DB State ===")
progs = all_programs(conn)
print(f"  Programs in DB: {[p['name'] for p in progs]}")
jobs = all_jobs(conn)
print(f"  Jobs in DB: {[j['name'] for j in jobs]}")

conn.close()
print("\nAll checks complete.")

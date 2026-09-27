"""Debug PAYROLL parse in detail."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from lm.cobol.parser import parse_cobol
from lm.ir.builder import build_ir

src = open(os.path.join(os.path.dirname(__file__), '..', 'tests', 'fixtures', 'PAYROLL.cbl')).read()
print(f"Source lines: {len(src.splitlines())}")

ast = parse_cobol(src, path='PAYROLL')
print(f"Program ID: {ast.program_id}")
print(f"WS items: {len(ast.data.working_storage)}")
for item in ast.data.working_storage[:5]:
    print(f"  {item.level} {item.name} PIC={item.picture}")
print(f"File sections: {len(ast.data.file_sections)}")
for fe in ast.data.file_sections:
    print(f"  FILE: {fe.name}, records={len(fe.fd_records)}")
paras = ast.paragraphs()
print(f"Paragraphs: {len(paras)} -> {[p.name for p in paras]}")

ir = build_ir(ast, path='PAYROLL', source_text=src)
print(f"\nIR: {len(ir.functions)} functions, {len(ir.vars)} vars, {len(ir.unsupported)} unsup")
for fn in ir.functions:
    stmts = sum(len(b.stmts) for b in fn.blocks)
    print(f"  fn={fn.name} kind={fn.kind} blocks={len(fn.blocks)} stmts={stmts} callees={fn.callees}")

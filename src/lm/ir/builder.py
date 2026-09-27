"""COBOL AST -> Normalised IR.

This is the single place where COBOL vocabulary is resolved. After this module,
nothing downstream should know that a PICTURE clause, a figurative constant,
a level-66 RENAMES, or an implicit DECIMAL-POINT COBOL decimal ever existed.

The lowering follows a fixed plan so it is reviewable:

* one IrFunction per paragraph, plus one for the implicit MAIN
* one IrBlock per straight-line region, split at branch targets
* PERFORM A THRU B becomes a call to the range, and control returns to the
  instruction after the PERFORM (via a synthetic return block)
* every variable referenced but not declared becomes a typed UNKNOWN var
* anything unmodelled becomes OpKind.UNSUPPORTED *and* an entry in
  ``program.unsupported`` so it can never be silently lost
"""

from __future__ import annotations

from typing import Optional

from ..cobol import ast_nodes as A
from ..cobol.lexer import detect_format
from .nodes import (
    IrBlock,
    IrConst,
    IrEdge,
    IrExpr,
    IrFile,
    IrFunction,
    IrParam,
    IrProgram,
    IrStmt,
    IrType,
    IrVar,
    OpKind,
    pic_size,
    pic_type,
)

#: PIC-letter -> equivalent single character, for compact type reporting
_PIC_DIGITS = set("9")


def _resolve_figurative(name: str) -> Any:
    n = (name or "").upper()
    if n in ("ZERO", "ZEROS", "ZEROES"):
        return 0
    if n in ("SPACE", "SPACES"):
        return " "
    if n in ("HIGH-VALUE", "HIGH-VALUES"):
        return "\xff"
    if n in ("LOW-VALUE", "LOW-VALUES"):
        return "\x00"
    if n in ("QUOTE", "QUOTES"):
        return '"'
    if n in ("NULL", "NULLS"):
        return None
    return "*"


class _Lowering:
    def __init__(self, program: A.CobolProgram, path: str = ""):
        self.src = program
        self.path = path or program.path
        self.prog = IrProgram(
            name=program.program_id or "PROGRAM",
            path=self.path,
            source_format=program.source_format,
            dialect=program.dialect,
        )
        self.vid_seq = 0
        self.sid_seq = 0
        self.bid_seq = 0
        self.name_to_vid: dict[str, str] = {}
        #: para name -> (function name, entry block id, exit label)
        self.para_index: dict[str, tuple[str, str, str]] = {}
        self.cur_fn: Optional[IrFunction] = None
        self.cur_block: Optional[IrBlock] = None
        self.temp_seq = 0
        self.loop_stack: list[str] = []
        self._pending: list[IrStmt] = []
        self._eof_flags: dict[str, str] = {}

    # -- ids -------------------------------------------------------------
    def _sid(self) -> str:
        self.sid_seq += 1
        return f"s{self.sid_seq}"

    def _bid(self) -> str:
        self.bid_seq += 1
        return f"b{self.bid_seq}"

    def _temp(self) -> str:
        self.temp_seq += 1
        vid = f"t{self.temp_seq}"
        self.prog.vars[vid] = IrVar(
            vid=vid,
            name=f"__tmp{self.temp_seq}",
            type=IrType.UNKNOWN,
            is_temp=True,
        )
        return vid

    # -- variables -------------------------------------------------------
    def declare(self, item: A.DataItem, section: str, is_param: bool = False) -> str:
        vid = f"v{self.vid_seq + 1}"
        self.vid_seq += 1
        vtype = pic_type(item.picture, item.usage)
        occurs = 1
        if item.occurs is not None:
            occurs = self._const_int(item.occurs) or 1
        init = self._literal_value(item.value) if item.value else None
        if init is None and item.values:
            init = self._literal_value(item.values[0])
        var = IrVar(
            vid=vid,
            name=item.name,
            type=vtype,
            size=pic_size(item.picture, item.usage),
            occurs=occurs,
            level=item.level,
            usage=item.usage or "DISPLAY",
            picture=item.picture,
            section=section,
            redefines=item.redefines,
            initial=init,
            is_param=is_param,
            origin=f"{self.path}:{item.span.line}" if item.span else None,
        )
        self.prog.vars[vid] = var
        # qualified names map to the same vid
        self.name_to_vid.setdefault(item.name, vid)
        for cn in item.condition_names:
            cv = f"v{self.vid_seq + 1}"
            self.vid_seq += 1
            cvar = IrVar(
                vid=cv,
                name=cn.name,
                type=IrType.BOOL,
                section=section,
                is_condition=True,
                host=vid,
                initial=[self._literal_value(v) for v in cn.values],
                origin=f"{self.path}:{cn.span.line}" if cn.span else None,
            )
            self.prog.vars[cv] = cvar
            self.name_to_vid.setdefault(cn.name, cv)
        return vid

    def declare_tree(self, items: list[A.DataItem], section: str, occurs: int = 1) -> None:
        for item in items:
            vid = self.declare(item, section)
            # OCCURS on a group item applies to every subordinate item, so
            # ``WS-ROW(n).WS-ROW-ID`` is a plain subscript on the child's own
            # vid rather than a slice of the group.
            n = max(occurs, self.prog.vars[vid].occurs)
            if n > 1:
                self.prog.vars[vid].occurs = n
            self.declare_tree(item.children, section, n)

    def resolve(self, name: str) -> str:
        """Look up a COBOL name, creating an UNKNOWN var if absent.

        Absent declarations are the normal case for copy-book-hosted fields,
        so this must never fail — but it records the miss so the critic can
        flag undeclared field use.
        """
        vid = self.name_to_vid.get(name)
        if vid is not None:
            return vid
        upper = name.upper()
        vid = f"v{self.vid_seq + 1}"
        self.vid_seq += 1
        self.prog.vars[vid] = IrVar(
            vid=vid,
            name=upper,
            type=IrType.UNKNOWN,
            section="UNDECLARED",
            origin="?",
        )
        self.name_to_vid[upper] = vid
        return vid

    def _const_int(self, expr: A.Expression) -> Optional[int]:
        if isinstance(expr, A.NumericLiteral):
            try:
                return int(expr.value)
            except ValueError:
                return None
        return None

    def _literal_value(self, expr: Optional[A.Expression]) -> Any:
        if expr is None:
            return None
        if isinstance(expr, A.NumericLiteral):
            try:
                return int(expr.value)
            except ValueError:
                try:
                    return float(expr.value)
                except ValueError:
                    return expr.value
        if isinstance(expr, A.StringLiteral):
            return expr.value
        if isinstance(expr, A.FigurativeConstant):
            return _resolve_figurative(expr.name)
        if isinstance(expr, A.Identifier):
            return expr.name
        return None

    # -- expressions -----------------------------------------------------
    def lower_expr(self, expr: Optional[A.Expression]) -> Optional[IrExpr]:
        if expr is None:
            return None
        if isinstance(expr, A.NumericLiteral):
            ctype = "dec" if "." in expr.value else "int"
            try:
                val: Any = float(expr.value) if ctype == "dec" else int(expr.value)
            except ValueError:
                val = expr.value
                ctype = "literal"
            return IrExpr(
                kind="const",
                const=IrConst(
                    ctype=ctype,
                    value=val,
                    type=IrType.DEC if ctype == "dec" else IrType.INT,
                ),
                span=self._span_str(expr.span),
            )
        if isinstance(expr, A.StringLiteral):
            return IrExpr(
                kind="const",
                const=IrConst(ctype="str", value=expr.value, type=IrType.STR),
                span=self._span_str(expr.span),
            )
        if isinstance(expr, A.FigurativeConstant):
            resolved = _resolve_figurative(expr.name)
            ctype = "int" if isinstance(resolved, int) else "str"
            return IrExpr(
                kind="const",
                const=IrConst(
                    ctype=ctype,
                    value=resolved,
                    type=IrType.INT if ctype == "int" else IrType.STR,
                    symbol=expr.name,
                ),
                span=self._span_str(expr.span),
            )
        if isinstance(expr, A.Identifier):
            if expr.name == "*" and expr.subscripts:
                return self.lower_expr(expr.subscripts[0])
            vid = self.resolve(expr.name)
            if expr.subscripts:
                base = IrExpr(kind="var", var=vid, span=self._span_str(expr.span))
                idx = self.lower_expr(expr.subscripts[0])
                if len(expr.subscripts) > 1:
                    idx2 = self.lower_expr(expr.subscripts[1])
                    return IrExpr(
                        kind="binary",
                        op="slice",
                        left=base,
                        right=idx,
                        args=[idx2] if idx2 else [],
                        span=self._span_str(expr.span),
                    )
                return IrExpr(kind="binary", op="index", left=base, right=idx, span=self._span_str(expr.span))
            return IrExpr(kind="var", var=vid, span=self._span_str(expr.span))
        if isinstance(expr, A.UnaryOp):
            return IrExpr(
                kind="unary",
                op=expr.op,
                left=self.lower_expr(expr.operand),
                span=self._span_str(expr.span),
            )
        if isinstance(expr, A.BinaryOp):
            return IrExpr(
                kind="binary",
                op=expr.op,
                left=self.lower_expr(expr.left),
                right=self.lower_expr(expr.right),
                span=self._span_str(expr.span),
            )
        if isinstance(expr, A.FunctionCall):
            return IrExpr(
                kind="call",
                op=expr.name.upper(),
                args=[self.lower_expr(a) for a in expr.args if a is not None],
                span=self._span_str(expr.span),
            )
        return IrExpr(kind="const", const=IrConst(ctype="literal", value=str(expr)))

    def _ref(self, ident: Optional[A.Identifier]) -> Optional[str]:
        if ident is None:
            return None
        return self.resolve(ident.name)

    def _refs(self, idents: list[A.Identifier]) -> list[str]:
        return [self.resolve(i.name) for i in idents]

    # -- emission --------------------------------------------------------
    def emit(self, stmt: IrStmt) -> IrStmt:
        if self.cur_block is not None:
            self.cur_block.stmts.append(stmt)
        else:
            self._pending.append(stmt)
        return stmt

    def new_block(self, label: str) -> IrBlock:
        if self.cur_fn is None:
            return IrBlock(bid=self._bid(), label=label)
        blk = IrBlock(bid=self._bid(), label=label, exit_label=f"X{label}")
        self.cur_fn.blocks.append(blk)
        self.cur_block = blk
        return blk

    def start_fn(self, name: str, kind: str = "paragraph") -> IrFunction:
        fn = IrFunction(name=name, kind=kind)
        self.prog.functions.append(fn)
        self.cur_fn = fn
        self.cur_block = None
        return fn

    # -- program ---------------------------------------------------------
    def run(self) -> IrProgram:
        self._declarations()
        self._functions()
        self._linkage()
        self._finalise()
        return self.prog

    def _declarations(self) -> None:
        self._file_owner: dict[str, IrFile] = {}
        self.prog.functions.append(IrFunction(name="__FILES__", kind="files"))
        for fe in self.src.data.file_sections:
            self.prog.uses_files = True
            fv = f"f{abs(hash(fe.name)) % 100000}"
            self.prog.vars[fv] = IrVar(
                vid=fv,
                name=fe.name,
                section="FILE",
                type=IrType.STR,
                is_file=True,
                origin=f"{self.path}:{fe.span.line}" if fe.span else None,
            )
            self.name_to_vid[fe.name] = fv
            rec_len = 80
            for rec in fe.fd_records:
                rid = self.declare(rec, "FILE")
                if rec.picture:
                    rec_len = pic_size(rec.picture, rec.usage)
            if fe.name not in self._file_owner:
                self._file_owner[fe.name] = IrFile(
                    name=fe.name,
                    organization=(fe.organization or "SEQUENTIAL").upper(),
                    record_len=rec_len,
                )
        for item in self.src.data.working_storage:
            self.declare(item, "WORKING-STORAGE")
            self.declare_tree(item.children, "WORKING-STORAGE")
        for item in self.src.data.local_storage:
            self.declare(item, "LOCAL-STORAGE")
            self.declare_tree(item.children, "LOCAL-STORAGE")
        for item in self.src.data.linkage:
            vid = self.declare(item, "LINKAGE", is_param=True)
            self.prog.globals.append(vid)

    def _functions(self) -> None:
        paras = self.src.paragraphs()
        if not paras:
            paras = [A.Paragraph(name="MAIN", statements=[])]
        # index first so PERFORM can forward-reference
        for p in paras:
            self.para_index[p.name.upper()] = (p.name.upper(), "", f"P_{p.name.upper()}")

        main = self.start_fn("main", "main")
        main.entry_block = ""
        for p in paras:
            if p.name.upper() == "MAIN":
                self._emit_para_into(main, p)
        for p in paras:
            if p.name.upper() != "MAIN":
                fn = self.start_fn(p.name.upper(), "paragraph")
                self._emit_para_into(fn, p)
        if not main.blocks:
            self.new_block("P_MAIN")

    def _emit_para_into(self, fn: IrFunction, para: A.Paragraph) -> None:
        label = f"P_{para.name.upper()}"
        self.new_block(label)
        fn.entry_block = self.cur_block.bid
        for st in para.statements:
            self._lower_stmt(st)
        # implicit fallthrough exit
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.RETURN,
                target_label=label + "_RET",
                origin="implicit",
            )
        )
        for b in fn.blocks:
            if b.label == label:
                b.exit_label = label + "_RET"
        self.prog.edges.append(
            IrEdge(src=self.cur_block.bid, dst=label + "_RET", kind="return")
        )
        if fn.name == "main":
            for st in self._pending:
                self.cur_block.stmts.insert(0, st)
            self._pending = []

    def _linkage(self) -> None:
        for fn in self.prog.functions:
            if fn.kind == "main":
                fn.params = [
                    IrParam(name=self.prog.vars[v].name, vid=v, direction="inout")
                    for v in self.prog.globals
                ]
        # attach files to main
        main = self.prog.function("main")
        if main is not None:
            for fv in self.prog.vars.values():
                if fv.is_file:
                    main.files.append(
                        IrFile(name=fv.name, record_vids=[], record_len=80)
                    )

    def _finalise(self) -> None:
        # caller/callee from CALL/PERFORM edges
        call_edges: list[tuple[str, str]] = []
        for fn in self.prog.functions:
            for b in fn.blocks:
                for s in b.stmts:
                    if s.op is OpKind.CALL and s.callee:
                        fn.callees.append(s.callee)
                        call_edges.append((fn.name, s.callee))
                    elif s.op is OpKind.UNSUPPORTED:
                        fn.unsupported_count += 1
            fn.complexity = self._complexity(fn)
            fn.fan_out = len(set(fn.callees))
        for caller, callee in call_edges:
            tgt = self.prog.function(callee)
            if tgt is not None and caller not in tgt.callers:
                tgt.callers.append(caller)
        for fn in self.prog.functions:
            fn.fan_in = len(set(fn.callers))
            fn.is_io = any(
                s.op in (OpKind.IO_READ, OpKind.IO_WRITE, OpKind.DISPLAY, OpKind.ACCEPT)
                for b in fn.blocks
                for s in b.stmts
            )
        self.prog.entry = "main"

    def _complexity(self, fn: IrFunction) -> int:
        score = 1
        for b in fn.blocks:
            for s in b.stmts:
                if s.op in (
                    OpKind.BRANCH_COND,
                    OpKind.GOTO_INDEXED,
                ):
                    score += 1
                elif s.op is OpKind.EVALUATE:
                    score += len(s.cases)
                elif s.op is OpKind.SEARCH:
                    score += 2
        return score

    # -- statements ------------------------------------------------------
    def _unsupported(self, verb: str, text: str, span: Optional[A.Span]) -> None:
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.UNSUPPORTED,
                text=f"{verb} {text}".strip(),
                span=f"{self.path}:{span.line}" if span else None,
                origin=verb,
            )
        )
        self.prog.unsupported.append(
            {
                "verb": verb,
                "text": f"{verb} {text}".strip(),
                "line": span.line if span else 0,
                "function": self.cur_fn.name if self.cur_fn else "",
            }
        )

    def _lower_stmt(self, st: A.Statement) -> None:
        if isinstance(st, A.Move):
            src = self.lower_expr(st.source)
            for t in st.targets:
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.ASSIGN,
                        targets=[self._ref(t)],
                        expr=src,
                        origin="MOVE",
                        span=self._loc(st.span),
                    )
                )
        elif isinstance(st, A.Compute):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.COMPUTE,
                    targets=self._refs(st.targets),
                    expr=self.lower_expr(st.expression),
                    text="rounded" if st.rounded else None,
                    origin="COMPUTE",
                    span=self._loc(st.span),
                )
            )
            if st.on_size_error:
                self._lower_stmt(st.on_size_error)
        elif isinstance(st, A.Arith):
            self._lower_arith(st)
        elif isinstance(st, A.If):
            self._lower_if(st)
        elif isinstance(st, A.Evaluate):
            self._lower_evaluate(st)
        elif isinstance(st, A.Perform):
            self._lower_perform(st)
        elif isinstance(st, A.Call):
            self._lower_call(st)
        elif isinstance(st, A.Display):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.DISPLAY,
                    args=[self.lower_expr(o) for o in st.operands if o],
                    text="noadv" if st.no_advancing else None,
                    origin="DISPLAY",
                    span=self._loc(st.span),
                )
            )
        elif isinstance(st, A.Accept):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.ACCEPT,
                    targets=[self._ref(st.target)] if st.target else [],
                    expr=self.lower_expr(st.from_source),
                    origin="ACCEPT",
                    span=self._loc(st.span),
                )
            )
        elif isinstance(st, A.GoTo):
            self._lower_goto(st)
        elif isinstance(st, A.StopRun):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.RETURN,
                    target_label="EXIT",
                    origin="STOP RUN",
                    span=self._loc(st.span),
                )
            )
        elif isinstance(st, A.ExitStmt):
            if st.target and st.target.startswith("PROGRAM"):
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.RETURN,
                        target_label="EXIT",
                        origin="EXIT PROGRAM",
                    )
                )
            elif st.target:
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.BRANCH,
                        target_label=f"P_{st.target}",
                        origin="EXIT",
                    )
                )
        elif isinstance(st, A.ContinueStmt):
            self.emit(IrStmt(sid=self._sid(), op=OpKind.NOP, origin="CONTINUE"))
        elif isinstance(st, A.SetStmt):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.SET_FLAG,
                    targets=self._refs(st.targets),
                    expr=self.lower_expr(st.to),
                    origin="SET",
                )
            )
        elif isinstance(st, A.Inspect):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.TALLY,
                    targets=[self._ref(st.target)] if st.target else [],
                    text=st.operation or "TALLYING",
                    origin="INSPECT",
                )
            )
        elif isinstance(st, A.OpenStmt):
            for mode, names in st.entries:
                for nm in names:
                    self.emit(
                        IrStmt(
                            sid=self._sid(),
                            op=OpKind.IO_OPEN,
                            file=self.resolve(nm),
                            text=mode,
                            origin="OPEN",
                        )
                    )
        elif isinstance(st, A.CloseStmt):
            for nm in st.files:
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.IO_CLOSE,
                        file=self.resolve(nm),
                        origin="CLOSE",
                    )
                )
        elif isinstance(st, A.ReadStmt):
            vid = self.resolve(st.file) if st.file else None
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.IO_READ,
                    file=vid,
                    targets=[self._ref(st.into)] if st.into else [],
                    origin="READ",
                    span=self._loc(st.span),
                )
            )
            if st.at_end or st.not_at_end:
                n = self.bid_seq + 1
                ok_lbl, end_lbl, join_lbl = f"L{n}_R", f"L{n}_E", f"L{n}_J"
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.BRANCH_COND,
                        cond=IrExpr(kind="var", var=self._eof_flag(vid)),
                        targets_labels=[ok_lbl, end_lbl],
                        text=join_lbl,
                        origin="READ-AT-END",
                    )
                )
                self.new_block(ok_lbl)
                for s in st.not_at_end:
                    self._lower_stmt(s)
                self.emit(
                    IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=join_lbl, origin="READ-JOIN")
                )
                self.new_block(end_lbl)
                for s in st.at_end:
                    self._lower_stmt(s)
                self.emit(
                    IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=join_lbl, origin="READ-JOIN")
                )
                self.new_block(join_lbl)
        elif isinstance(st, A.WriteStmt):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.IO_WRITE,
                    file=None,
                    targets=[self._ref(st.record)] if st.record else [],
                    expr=self.lower_expr(st.from_source),
                    origin="WRITE",
                    span=self._loc(st.span),
                )
            )
        elif isinstance(st, A.DeleteStmt):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.IO_WRITE,
                    file=self.resolve(st.file) if st.file else None,
                    text="delete",
                    origin="DELETE",
                )
            )
        elif isinstance(st, A.RewriteStmt):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.IO_WRITE,
                    file=None,
                    targets=[self._ref(st.record)] if st.record else [],
                    text="rewrite",
                    origin="REWRITE",
                )
            )
        elif isinstance(st, A.SearchStmt):
            self._lower_search(st)
        elif isinstance(st, A.StringStmt):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.STRING_OP,
                    targets=[self._ref(st.into)] if st.into else [],
                    args=[self.lower_expr(x) for x in st.sending if x],
                    origin="STRING",
                )
            )
        elif isinstance(st, A.UnstringStmt):
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.UNSTRING,
                    targets=[self._ref(t) for _, t in st.targets],
                    expr=self.lower_expr(st.source),
                    origin="UNSTRING",
                )
            )
        elif isinstance(st, A.Other):
            self._unsupported(st.verb, st.text, st.span)
        else:  # pragma: no cover - defensive
            self._unsupported("UNKNOWN", type(st).__name__, st.span)

    def _loc(self, span: Optional[A.Span]) -> Optional[str]:
        if span is None:
            return None
        return f"{self.path}:{span.line}"

    def _span_str(self, span) -> Optional[str]:
        """Convert any span object (Span dataclass or str) to a string."""
        if span is None:
            return None
        if isinstance(span, str):
            return span
        if isinstance(span, A.Span):
            return f"{self.path}:{span.line}"
        return str(span)

    def _lower_arith(self, st: A.Arith) -> None:
        operands = [self.lower_expr(o) for o in st.operands if o is not None]
        if st.giving:
            for t in st.giving:
                vid = self._ref(t)
                if st.kind == "ADD":
                    acc = self._emit_sum(operands, vid)
                elif st.kind == "SUBTRACT":
                    acc = self._emit_diff(operands, vid)
                elif st.kind == "MULTIPLY":
                    acc = self._emit_mul(operands, vid)
                else:
                    acc = self._emit_div(operands, vid)
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.ASSIGN,
                        targets=[vid],
                        expr=acc,
                        text="rounded" if st.rounded else None,
                        origin=st.kind,
                        span=self._loc(st.span),
                    )
                )
        elif st.receiving is not None:
            vid = self._ref(st.receiving)
            srcs = operands
            if st.kind == "MULTIPLY" and len(operands) >= 2:
                expr = IrExpr(kind="binary", op="*", left=srcs[0], right=srcs[1])
            elif st.kind == "DIVIDE" and len(operands) >= 2:
                expr = IrExpr(kind="binary", op="/", left=srcs[1], right=srcs[0])
            elif st.kind == "ADD":
                expr = self._fold_sum(srcs)
            elif st.kind == "SUBTRACT":
                expr = self._fold_diff(srcs)
            else:
                expr = srcs[0] if srcs else None
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.ASSIGN,
                    targets=[vid],
                    expr=expr,
                    text="rounded" if st.rounded else None,
                    origin=st.kind,
                    span=self._loc(st.span),
                )
            )
        if st.on_size_error:
            self._lower_stmt(st.on_size_error)

    def _fold_sum(self, exprs: list[IrExpr]) -> Optional[IrExpr]:
        acc: Optional[IrExpr] = None
        for e in exprs:
            acc = e if acc is None else IrExpr(kind="binary", op="+", left=acc, right=e)
        return acc

    def _fold_diff(self, exprs: list[IrExpr]) -> Optional[IrExpr]:
        if not exprs:
            return None
        if len(exprs) == 1:
            return IrExpr(
                kind="unary",
                op="-",
                left=exprs[0],
            )
        acc = exprs[0]
        for e in exprs[1:]:
            acc = IrExpr(kind="binary", op="-", left=acc, right=e)
        return acc

    def _emit_sum(self, operands: list[IrExpr], into: str) -> IrExpr:
        return self._fold_sum(operands) or IrExpr(
            kind="const", const=IrConst(ctype="int", value=0)
        )

    def _emit_diff(self, operands: list[IrExpr], into: str) -> IrExpr:
        return self._fold_diff(operands) or IrExpr(
            kind="const", const=IrConst(ctype="int", value=0)
        )

    def _emit_mul(self, operands: list[IrExpr], into: str) -> IrExpr:
        acc: Optional[IrExpr] = None
        for e in operands:
            acc = e if acc is None else IrExpr(kind="binary", op="*", left=acc, right=e)
        return acc or IrExpr(kind="const", const=IrConst(ctype="int", value=1))

    def _emit_div(self, operands: list[IrExpr], into: str) -> IrExpr:
        # COBOL DIVIDE A INTO B  =>  B = B / A ;  DIVIDE A BY B => B = A / B
        if len(operands) >= 2:
            return IrExpr(kind="binary", op="/", left=operands[1], right=operands[0])
        if operands:
            return IrExpr(kind="binary", op="/", left=operands[0], right=operands[0])
        return IrExpr(kind="const", const=IrConst(ctype="int", value=0))

    def _lower_if(self, st: A.If) -> None:
        entry = self.cur_block
        then_label = f"L{self.bid_seq + 1}_T"
        else_label = f"L{self.bid_seq + 1}_E"
        join_label = f"L{self.bid_seq + 1}_J"
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.BRANCH_COND,
                cond=self.lower_expr(st.condition),
                targets_labels=[then_label, else_label],
                text=join_label,
                origin="IF",
                span=self._loc(st.span),
            )
        )
        then_blk = self.new_block(then_label)
        for s in st.then_branch:
            self._lower_stmt(s)
        self.emit(
            IrStmt(
                sid=self._sid(), op=OpKind.BRANCH, target_label=join_label, origin="IF-JOIN"
            )
        )
        then_blk.exit_label = join_label
        else_blk = self.new_block(else_label)
        if st.next_sibling is not None:
            # ELSE IF chain: the sibling is a full If, so recurse into it rather
            # than re-lowering its then_branch here.
            self._lower_stmt(st.next_sibling)
        else:
            for s in st.else_branch:
                self._lower_stmt(s)
        self.emit(
            IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=join_label, origin="IF-JOIN")
        )
        else_blk.exit_label = join_label
        self.new_block(join_label)
        if entry is not None and self.cur_block is not None:
            self.prog.edges.append(
                IrEdge(src=entry.bid, dst=then_blk.bid, kind="conditional")
            )
            self.prog.edges.append(
                IrEdge(src=entry.bid, dst=else_blk.bid, kind="conditional")
            )

    def _lower_evaluate(self, st: A.Evaluate) -> None:
        dispatch = self.lower_expr(st.subject) if st.subject else None
        case_labels: list[tuple[list[Optional[IrExpr]], str]] = []
        bodies: list[list[IrStmt]] = []
        for wh in st.whens:
            lbl = f"L{self.bid_seq + 1}_W{len(case_labels)}"
            conds = [self.lower_expr(w) for w in wh.whens]
            case_labels.append((conds, lbl))
            bodies.append(wh.statements)
        join = f"L{self.bid_seq + 1}_J"
        all_labels = [lbl for _, lbl in case_labels] + [join]
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.EVALUATE,
                dispatch=dispatch,
                cases=case_labels,
                targets_labels=all_labels,
                text=join,
                origin="EVALUATE",
                span=self._loc(st.span),
            )
        )
        for lbl, stmts in zip(all_labels, bodies):
            blk = self.new_block(lbl)
            for s in stmts:
                self._lower_stmt(s)
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.BRANCH,
                    target_label=join,
                    origin="EVALUATE-JOIN",
                )
            )
            blk.exit_label = join
        self.new_block(join)

    def _lower_search(self, st: A.SearchStmt) -> None:
        dispatch = IrExpr(
            kind="var", var=self._ref(st.varying) if st.varying else None
        )
        join = f"L{self.bid_seq + 1}_J"
        labels = []
        for i, (cond, _body) in enumerate(st.when):
            lbl = f"L{self.bid_seq + 1}_W{i}"
            labels.append(([self.lower_expr(cond) if cond else None], lbl))
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.SEARCH,
                dispatch=dispatch,
                cases=labels,
                targets_labels=[l for _, l in labels] + [join],
                text=join,
                origin="SEARCH",
            )
        )
        for (_, lbl), (_cond, body) in zip(labels, st.when):
            blk = self.new_block(lbl)
            for s in body:
                self._lower_stmt(s)
            self.emit(
                IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=join, origin="SEARCH-JOIN")
            )
            blk.exit_label = join
        self.new_block(join)

    def _lower_goto(self, st: A.GoTo) -> None:
        if st.depending is not None:
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.GOTO_INDEXED,
                    targets=[self._ref(st.depending)],
                    targets_labels=[f"P_{t}" for t in st.targets],
                    origin="GO TO DEPENDING ON",
                )
            )
        elif st.targets:
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.BRANCH,
                    target_label=f"P_{st.targets[0]}",
                    origin="GO TO",
                    span=self._loc(st.span),
                )
            )

    def _lower_perform(self, st: A.Perform) -> None:
        if st.target:
            entry_lbl = f"P_{st.target}"
            if st.thru:
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.CALL,
                        callee=st.target,
                        text=f"thru:{st.thru}",
                        origin="PERFORM THRU",
                        span=self._loc(st.span),
                    )
                )
            else:
                self.emit(
                    IrStmt(
                        sid=self._sid(),
                        op=OpKind.CALL,
                        callee=st.target,
                        origin="PERFORM",
                        span=self._loc(st.span),
                    )
                )
            return

        # Inline PERFORM.
        #   until  -> do-while lowered as a *pre-test* loop so PERFORM UNTIL
        #             never executes the body one time too many.
        #   times  -> a compiler temp is counted down; head tests ``tmp <= 0``.
        #   neither-> straight-line, body runs exactly once (a bare PERFORM).
        # All three end up as:  [enter: BRANCH head]
        #                        head : BRANCH_COND [done, body]
        #                        body : <stmts> [++counter] BRANCH head
        #                        done :
        # which is the shape the interpreter and the Python emitter both expect.
        varying = st.varying
        until = st.until if st.until is not None else (varying.until if varying else None)
        if varying is not None and varying.counter:
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.ASSIGN,
                    targets=[self._ref(varying.counter)],
                    expr=self.lower_expr(varying.start),
                    origin="PERFORM-VARYING-FROM",
                )
            )
        counter_tmp: Optional[str] = None
        if st.times is not None and until is None:
            counter_tmp = self._temp()
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.ASSIGN,
                    targets=[counter_tmp],
                    expr=self.lower_expr(st.times),
                    origin="PERFORM-TIMES",
                )
            )

        n = self.bid_seq + 1
        head_lbl = f"L{n}_P"
        body_lbl = f"L{n}_B"
        done_lbl = f"L{n}_D"

        if until is None and counter_tmp is None:
            self.emit(
                IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=body_lbl, origin="PERFORM-ENTER")
            )
            self.new_block(body_lbl)
            for s in st.body:
                self._lower_stmt(s)
            self.emit(
                IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=done_lbl, origin="PERFORM-END")
            )
            self.new_block(done_lbl)
            return

        self.emit(
            IrStmt(sid=self._sid(), op=OpKind.BRANCH, target_label=head_lbl, origin="PERFORM-ENTER")
        )
        self.new_block(head_lbl)
        if until is not None:
            cond: IrExpr = self.lower_expr(until)
        else:
            cond = IrExpr(
                kind="binary",
                op="<=",
                left=IrExpr(kind="var", var=counter_tmp),
                right=IrExpr(kind="const", const=IrConst(ctype="int", value=0)),
            )
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.BRANCH_COND,
                cond=cond,
                targets_labels=[done_lbl, body_lbl],
                origin="PERFORM-UNTIL" if until is not None else "PERFORM-TIMES-TEST",
            )
        )
        self.new_block(body_lbl)
        for s in st.body:
            self._lower_stmt(s)
        if varying is not None and varying.counter:
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.COMPUTE,
                    targets=[self._ref(varying.counter)],
                    expr=IrExpr(
                        kind="binary",
                        op="+",
                        left=IrExpr(kind="var", var=self._ref(varying.counter)),
                        right=self.lower_expr(varying.by)
                        or IrExpr(kind="const", const=IrConst(ctype="int", value=1)),
                    ),
                    origin="PERFORM-VARYING-BY",
                )
            )
        if counter_tmp is not None:
            self.emit(
                IrStmt(
                    sid=self._sid(),
                    op=OpKind.COMPUTE,
                    targets=[counter_tmp],
                    expr=IrExpr(
                        kind="binary",
                        op="-",
                        left=IrExpr(kind="var", var=counter_tmp),
                        right=IrExpr(kind="const", const=IrConst(ctype="int", value=1)),
                    ),
                    origin="PERFORM-TIMES-DEC",
                )
            )
        self.emit(
            IrStmt(
                sid=self._sid(), op=OpKind.BRANCH, target_label=head_lbl, origin="PERFORM-BACK"
            )
        )
        self.new_block(done_lbl)

    def _lower_call(self, st: A.Call) -> None:
        callee = None
        if isinstance(st.program, A.StringLiteral):
            callee = st.program.value.upper()
        elif isinstance(st.program, A.Identifier):
            callee = st.program.name.upper()
        if callee and callee.startswith("*"):
            callee = callee[1:]
        args = []
        for u in st.using:
            e = self.lower_expr(u)
            if e is not None:
                args.append(e)
        self.emit(
            IrStmt(
                sid=self._sid(),
                op=OpKind.CALL,
                callee=callee,
                args=args,
                targets=[self._ref(st.returning)] if st.returning else [],
                origin="CALL",
                span=self._loc(st.span),
            )
        )


def build_ir(
    program: A.CobolProgram, path: str = "", source_text: str = ""
) -> IrProgram:
    """Lower a parsed COBOL program into normalised IR."""
    if not program.source_format or program.source_format == "auto":
        program.source_format = detect_format(source_text) if source_text else "free"
    lowerer = _Lowering(program, path=path)
    ir = lowerer.run()
    if source_text:
        ir.source_lines = source_text.count("\n") + 1
        ir.source_bytes = len(source_text.encode("utf-8"))
    return ir


def build_ir_from_jcl(unit, path: str = ""):
    """Project a JCL unit into the same IR node types, for the graph layer."""
    from .nodes import IrDataset, IrJob

    job = IrJob(name=unit.job.name if unit.job else "JOB", path=path or unit.path)
    seen: dict[str, IrDataset] = {}
    for step in unit.steps:
        job.steps.append(
            {
                "name": step.name,
                "pgm": step.pgm,
                "proc": step.proc,
                "cond": step.cond,
                "region": step.region,
                "line": step.lines[0],
            }
        )
        for dd in step.dds:
            for dsn in dd.dsn_list or ([dd.dsn] if dd.dsn else []):
                if not dsn:
                    continue
                recfm = dd.dcb.get("RECFM", "")
                is_temp = bool(dd.disp and ("SCRATCH" in dd.disp.upper() or "DELETE" in dd.disp.upper()))
                if dsn not in seen:
                    seen[dsn] = IrDataset(
                        name=dsn,
                        dcb=dd.dcb,
                        disp=dd.disp,
                        recfm=recfm,
                        lrecl=int(dd.dcb.get("LRECL", "80") or 80)
                        if (dd.dcb.get("LRECL", "80") or "80").isdigit()
                        else 80,
                        is_temp=is_temp,
                    )
    job.datasets = list(seen.values())
    return job

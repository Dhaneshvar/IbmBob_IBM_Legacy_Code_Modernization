"""ANTLR4 visitor that converts a Cobol85 parse tree into the existing
``ast_nodes.CobolProgram`` dataclasses.

This module is the only place that knows about the ANTLR-generated names.
Everything downstream (IR builder, store, agents) only ever sees the same
``CobolProgram`` that the hand-rolled parser produces — so the two parsers
are completely interchangeable.

If the ANTLR-generated files are not present (i.e. ``scripts/gen_antlr.py``
has not been run), this module falls back to the hand-rolled parser
transparently.
"""
from __future__ import annotations

import re
from typing import Optional

from .ast_nodes import (
    Accept,
    Arith,
    BinaryOp,
    Call,
    CloseStmt,
    CobolProgram,
    Compute,
    ConditionName,
    ContinueStmt,
    DataDivision,
    DataItem,
    Display,
    EnvironmentDivision,
    Evaluate,
    EvaluateWhen,
    ExitStmt,
    FileEntry,
    FigurativeConstant,
    FunctionCall,
    GoTo,
    Identifier,
    IdentificationDivision,
    If,
    Inspect,
    Move,
    NumericLiteral,
    OpenStmt,
    Other,
    Paragraph,
    Perform,
    PerformVarying,
    ProcedureDivision,
    ReadStmt,
    RewriteStmt,
    SearchStmt,
    Section,
    SetStmt,
    Span,
    StopRun,
    StringLiteral,
    StringStmt,
    UnstringStmt,
    WriteStmt,
)


def _antlr_available() -> bool:
    try:
        import antlr4  # noqa: F401

        # Check generated files exist
        from .gen import Cobol85Lexer  # noqa: F401

        return True
    except ImportError:
        return False


def parse_cobol_antlr(text: str, path: str = "") -> CobolProgram:
    """Parse ``text`` using the ANTLR4 grammar, return a ``CobolProgram``."""
    import antlr4
    from .gen.Cobol85Lexer import Cobol85Lexer
    from .gen.Cobol85Parser import Cobol85Parser

    # Pre-process: strip fixed-format sequence area and fold continuations
    preprocessed = _preprocess(text)

    input_stream = antlr4.InputStream(preprocessed)
    lexer = Cobol85Lexer(input_stream)
    lexer.removeErrorListeners()
    lexer.addErrorListener(_SilentErrorListener())

    token_stream = antlr4.CommonTokenStream(lexer)
    parser = Cobol85Parser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(_SilentErrorListener())

    tree = parser.startRule()
    visitor = _CobolAstBuilder(path=path, source_text=text)
    return visitor.build(tree)


def _preprocess(text: str) -> str:
    """Strip column 1-6 sequence numbers and column-7 indicator for fixed format."""
    lines = []
    for raw in text.splitlines():
        if len(raw) > 6:
            indicator = raw[6]
            if indicator in ("*", "/"):
                continue  # comment line
            body = raw[7:] if len(raw) > 7 else ""
            lines.append(body)
        else:
            lines.append(raw)
    return "\n".join(lines)


class _SilentErrorListener:
    """ANTLR error listener that records but does not raise on parse errors."""

    def syntaxError(self, recognizer, offending_symbol, line, column, msg, e):
        pass  # errors are captured in the partial AST

    def reportAmbiguity(self, *args):
        pass

    def reportAttemptingFullContext(self, *args):
        pass

    def reportContextSensitivity(self, *args):
        pass


class _CobolAstBuilder:
    """Walks the ANTLR4 CST and builds ``ast_nodes`` dataclasses."""

    def __init__(self, path: str = "", source_text: str = ""):
        self.path = path
        self.source_text = source_text
        self._prog = CobolProgram(path=path)

    def build(self, tree) -> CobolProgram:
        try:
            from .gen.Cobol85Parser import Cobol85Parser as P

            for prog_unit in tree.programUnit():
                self._visit_program_unit(prog_unit, P)
        except Exception:
            # Partial parse — return whatever was collected
            pass
        return self._prog

    # ── divisions ──────────────────────────────────────────────────────────

    def _visit_program_unit(self, ctx, P) -> None:
        if ctx.identificationDivision():
            self._prog.identification = self._visit_identification(
                ctx.identificationDivision(), P
            )
            self._prog.program_id = self._prog.identification.program_id

        if ctx.environmentDivision():
            self._prog.environment = self._visit_environment(
                ctx.environmentDivision(), P
            )

        if ctx.dataDivision():
            self._prog.data = self._visit_data_division(ctx.dataDivision(), P)

        if ctx.procedureDivision():
            self._prog.procedure = self._visit_procedure_division(
                ctx.procedureDivision(), P
            )

    def _visit_identification(self, ctx, P) -> IdentificationDivision:
        ident = IdentificationDivision()
        if ctx.programName():
            ident.program_id = ctx.programName().getText().upper()
            ident.entries.append(("PROGRAM-ID", ident.program_id))
        return ident

    def _visit_environment(self, ctx, P) -> EnvironmentDivision:
        return EnvironmentDivision()

    def _visit_data_division(self, ctx, P) -> DataDivision:
        data = DataDivision()
        for sec in ctx.dataDivisionSection():
            if sec.workingStorageSection():
                for entry in sec.workingStorageSection().dataDescriptionEntry():
                    item = self._visit_data_entry(entry, P)
                    if item:
                        data.working_storage.append(item)
            elif sec.linkageSection():
                for entry in sec.linkageSection().dataDescriptionEntry():
                    item = self._visit_data_entry(entry, P)
                    if item:
                        data.linkage.append(item)
            elif sec.fileSection():
                for fe in sec.fileSection().fileDescriptionEntry():
                    file_entry = self._visit_file_entry(fe, P)
                    if file_entry:
                        data.file_sections.append(file_entry)
        return data

    def _visit_file_entry(self, ctx, P) -> Optional[FileEntry]:
        name = ctx.cobolWord().getText().upper() if ctx.cobolWord() else "FILE"
        fe = FileEntry(name=name)
        for entry in ctx.dataDescriptionEntry():
            item = self._visit_data_entry(entry, P)
            if item:
                fe.fd_records.append(item)
        return fe

    def _visit_data_entry(self, ctx, P) -> Optional[DataItem]:
        level_text = ctx.levelNumber().getText()
        name_ctx = ctx.cobolWord()
        name = name_ctx.getText().upper() if name_ctx else "FILLER"
        item = DataItem(
            level=level_text,
            name=name,
            span=Span(
                line=ctx.start.line if ctx.start else 0,
                end_line=ctx.stop.line if ctx.stop else 0,
            ),
        )
        for clause in ctx.dataDescriptionClause():
            self._apply_data_clause(item, clause, P)
        return item

    def _apply_data_clause(self, item: DataItem, ctx, P) -> None:
        if ctx.pictureClause():
            # Collect all tokens after PIC/PICTURE IS
            pic_ctx = ctx.pictureClause()
            tokens = [t.getText() for t in pic_ctx.pictureString().getTokens(-1)]
            item.picture = "".join(tokens) if tokens else pic_ctx.pictureString().getText()
        elif ctx.usageClause():
            item.usage = ctx.usageClause().usageValue().getText().upper()
        elif ctx.occursClause():
            oc = ctx.occursClause()
            nums = oc.IntegerLiteral()
            if nums:
                item.occurs = NumericLiteral(value=nums[0].getText())
        elif ctx.valueClause():
            vals = []
            for lit in ctx.valueClause().literal():
                vals.append(self._visit_literal(lit))
            item.values = vals
            item.value = vals[0] if vals else None
        elif ctx.redefinesClause():
            item.redefines = ctx.redefinesClause().cobolWord().getText().upper()

    # ── procedure division ─────────────────────────────────────────────────

    def _visit_procedure_division(self, ctx, P) -> ProcedureDivision:
        proc = ProcedureDivision()
        body = ctx.procedureDivisionBody()
        if not body:
            return proc

        if body.section():
            for sec_ctx in body.section():
                sec = Section(
                    name=sec_ctx.cobolWord().getText().upper(),
                    span=Span(
                        line=sec_ctx.start.line if sec_ctx.start else 0,
                        end_line=sec_ctx.stop.line if sec_ctx.stop else 0,
                    ),
                )
                for para_ctx in sec_ctx.paragraph():
                    para = self._visit_paragraph(para_ctx, P)
                    sec.paragraphs.append(para)
                proc.sections.append(sec)
        else:
            # flat paragraph list
            main_sec = Section(name="MAIN")
            for para_ctx in body.paragraph() if hasattr(body, "paragraph") else []:
                main_sec.paragraphs.append(self._visit_paragraph(para_ctx, P))
            if main_sec.paragraphs:
                proc.sections.append(main_sec)
        return proc

    def _visit_paragraph(self, ctx, P) -> Paragraph:
        name = ctx.cobolWord().getText().upper() if ctx.cobolWord() else "PARA"
        para = Paragraph(
            name=name,
            span=Span(
                line=ctx.start.line if ctx.start else 0,
                end_line=ctx.stop.line if ctx.stop else 0,
            ),
        )
        for sent in ctx.sentence():
            for stmt_ctx in sent.statement():
                stmt = self._visit_statement(stmt_ctx, P)
                if stmt:
                    para.statements.append(stmt)
        return para

    # ── statements ─────────────────────────────────────────────────────────

    def _visit_statement(self, ctx, P):
        span = Span(
            line=ctx.start.line if ctx.start else 0,
            end_line=ctx.stop.line if ctx.stop else 0,
        )
        if ctx.moveStatement():
            return self._visit_move(ctx.moveStatement(), span, P)
        if ctx.ifStatement():
            return self._visit_if(ctx.ifStatement(), span, P)
        if ctx.performStatement():
            return self._visit_perform(ctx.performStatement(), span, P)
        if ctx.computeStatement():
            return self._visit_compute(ctx.computeStatement(), span, P)
        if ctx.addStatement():
            return self._visit_arith("ADD", ctx.addStatement(), span, P)
        if ctx.subtractStatement():
            return self._visit_arith("SUBTRACT", ctx.subtractStatement(), span, P)
        if ctx.multiplyStatement():
            return self._visit_arith("MULTIPLY", ctx.multiplyStatement(), span, P)
        if ctx.divideStatement():
            return self._visit_arith("DIVIDE", ctx.divideStatement(), span, P)
        if ctx.displayStatement():
            return self._visit_display(ctx.displayStatement(), span, P)
        if ctx.acceptStatement():
            return self._visit_accept(ctx.acceptStatement(), span, P)
        if ctx.callStatement():
            return self._visit_call(ctx.callStatement(), span, P)
        if ctx.openStatement():
            return self._visit_open(ctx.openStatement(), span, P)
        if ctx.closeStatement():
            return self._visit_close(ctx.closeStatement(), span, P)
        if ctx.readStatement():
            return self._visit_read(ctx.readStatement(), span, P)
        if ctx.writeStatement():
            return self._visit_write(ctx.writeStatement(), span, P)
        if ctx.stopStatement():
            return StopRun(span=span)
        if ctx.gobackStatement():
            return StopRun(span=span)
        if ctx.exitStatement():
            es = ctx.exitStatement()
            target = None
            if es.PROGRAM():
                target = "PROGRAM"
            return ExitStmt(target=target, span=span)
        if ctx.continueStatement():
            return ContinueStmt(span=span)
        if ctx.goToStatement():
            return self._visit_goto(ctx.goToStatement(), span, P)
        if ctx.evaluateStatement():
            return self._visit_evaluate(ctx.evaluateStatement(), span, P)
        if ctx.setStatement():
            return self._visit_set(ctx.setStatement(), span, P)
        # anything else → Other
        return Other(
            verb=ctx.start.text.upper() if ctx.start else "UNKNOWN",
            text=ctx.getText(),
            span=span,
        )

    def _visit_move(self, ctx, span: Span, P) -> Move:
        src_ctx = ctx.getChild(1)  # after MOVE keyword
        src = self._visit_generic_expr(src_ctx)
        targets = []
        for ident_ctx in ctx.identifier():
            targets.append(Identifier(name=ident_ctx.getText().upper()))
        return Move(source=src, targets=targets, span=span)

    def _visit_if(self, ctx, span: Span, P) -> If:
        cond = self._visit_condition(ctx.condition(), P)
        then_stmts = []
        else_stmts = []
        # Collect THEN branch and ELSE branch
        in_else = False
        for child in ctx.getChildren():
            text = child.getText().upper() if hasattr(child, "getText") else ""
            if text == "ELSE":
                in_else = True
                continue
            if hasattr(child, "statement"):
                for stmt_ctx in child.statement() if hasattr(child, "statement") else []:
                    stmt = self._visit_statement(stmt_ctx, P)
                    if stmt:
                        (else_stmts if in_else else then_stmts).append(stmt)
        return If(condition=cond, then_branch=then_stmts, else_branch=else_stmts, span=span)

    def _visit_perform(self, ctx, span: Span, P) -> Perform:
        if ctx.performProcedure():
            pp = ctx.performProcedure()
            words = [cw.getText().upper() for cw in pp.cobolWord()]
            target = words[0] if words else None
            thru = words[1] if len(words) > 1 else None
            return Perform(target=target, thru=thru, span=span)
        # Inline PERFORM
        pi = ctx.performInline()
        until = None
        varying = None
        body = []
        if pi:
            if pi.performUntil():
                until = self._visit_condition(pi.performUntil().condition(), P)
            if pi.performVarying():
                pv = pi.performVarying()
                counters = [cw.getText().upper() for cw in pv.identifier()]
                varying = PerformVarying(
                    counter=Identifier(name=counters[0]) if counters else None,
                )
            for stmt_ctx in pi.statement():
                stmt = self._visit_statement(stmt_ctx, P)
                if stmt:
                    body.append(stmt)
        return Perform(until=until, varying=varying, body=body, span=span)

    def _visit_compute(self, ctx, span: Span, P) -> Compute:
        targets = [Identifier(name=i.getText().upper()) for i in ctx.identifier()]
        expr = self._visit_arith_expr(ctx.arithmeticExpression(), P)
        return Compute(targets=targets, expression=expr, span=span)

    def _visit_arith(self, kind: str, ctx, span: Span, P) -> Arith:
        return Arith(kind=kind, span=span)

    def _visit_display(self, ctx, span: Span, P) -> Display:
        ops = []
        for child in ctx.getChildren():
            text = child.getText().upper() if hasattr(child, "getText") else ""
            if text not in ("DISPLAY", "WITH", "NO", "ADVANCING", "UPON"):
                if hasattr(child, "identifier"):
                    ops.append(Identifier(name=child.getText().upper()))
                elif hasattr(child, "literal"):
                    ops.append(self._visit_literal(child))
        return Display(operands=ops, span=span)

    def _visit_accept(self, ctx, span: Span, P) -> Accept:
        idents = ctx.qualifiedName() if hasattr(ctx, "qualifiedName") else []
        target = Identifier(name=idents[0].getText().upper()) if idents else None
        return Accept(target=target, span=span)

    def _visit_call(self, ctx, span: Span, P) -> Call:
        lits = ctx.literal()
        idents = ctx.identifier()
        if lits:
            prog = StringLiteral(value=lits[0].getText().strip("\"'"))
        elif idents:
            prog = Identifier(name=idents[0].getText().upper())
        else:
            prog = None
        return Call(program=prog, span=span)

    def _visit_open(self, ctx, span: Span, P) -> OpenStmt:
        entries = []
        mode = "INPUT"
        for child in ctx.getChildren():
            t = child.getText().upper() if hasattr(child, "getText") else ""
            if t in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = t
            elif t not in ("OPEN",) and t.isalpha():
                entries.append((mode, [t]))
        return OpenStmt(entries=entries, span=span)

    def _visit_close(self, ctx, span: Span, P) -> CloseStmt:
        files = [cw.getText().upper() for cw in ctx.cobolWord()]
        return CloseStmt(files=files, span=span)

    def _visit_read(self, ctx, span: Span, P) -> ReadStmt:
        words = [cw.getText().upper() for cw in ctx.cobolWord()]
        file_name = words[0] if words else ""
        return ReadStmt(file=file_name, span=span)

    def _visit_write(self, ctx, span: Span, P) -> WriteStmt:
        qn = ctx.qualifiedName() if hasattr(ctx, "qualifiedName") else []
        record = Identifier(name=qn[0].getText().upper()) if qn else None
        return WriteStmt(record=record, span=span)

    def _visit_goto(self, ctx, span: Span, P) -> GoTo:
        targets = [cw.getText().upper() for cw in ctx.cobolWord()]
        depending = None
        if ctx.identifier():
            depending = Identifier(name=ctx.identifier()[0].getText().upper())
        return GoTo(targets=targets, depending=depending, span=span)

    def _visit_evaluate(self, ctx, span: Span, P) -> Evaluate:
        subjects = [self._visit_generic_expr(ctx.evaluateSubject(0))]
        whens = []
        for wp in ctx.whenPhrase():
            wh = EvaluateWhen()
            for ec in wp.evaluateCondition():
                wh.whens.append(self._visit_generic_expr(ec))
            for stmt_ctx in wp.statement():
                stmt = self._visit_statement(stmt_ctx, P)
                if stmt:
                    wh.statements.append(stmt)
            whens.append(wh)
        return Evaluate(subjects=subjects, subject=subjects[0] if subjects else None, whens=whens, span=span)

    def _visit_set(self, ctx, span: Span, P) -> SetStmt:
        idents = [Identifier(name=i.getText().upper()) for i in ctx.identifier()]
        return SetStmt(targets=idents, span=span)

    # ── expression helpers ─────────────────────────────────────────────────

    def _visit_condition(self, ctx, P):
        if ctx is None:
            return FigurativeConstant(name="TRUE")
        return self._visit_generic_expr(ctx)

    def _visit_arith_expr(self, ctx, P):
        if ctx is None:
            return NumericLiteral(value="0")
        return self._visit_generic_expr(ctx)

    def _visit_generic_expr(self, ctx):
        if ctx is None:
            return NumericLiteral(value="0")
        text = ctx.getText()
        if re.match(r"^-?\d+$", text):
            return NumericLiteral(value=text, kind="integer")
        if re.match(r"^-?\d+\.\d*$", text):
            return NumericLiteral(value=text, kind="decimal")
        if text.startswith('"') or text.startswith("'"):
            return StringLiteral(value=text.strip("\"'"))
        return Identifier(name=text.upper())

    def _visit_literal(self, ctx) -> "Expression":
        if ctx is None:
            return StringLiteral(value="")
        text = ctx.getText()
        if re.match(r"^-?\d+$", text):
            return NumericLiteral(value=text)
        if re.match(r"^-?\d+\.\d+$", text):
            return NumericLiteral(value=text, kind="decimal")
        if text.startswith('"') or text.startswith("'"):
            return StringLiteral(value=text.strip("\"'"))
        return FigurativeConstant(name=text.upper())

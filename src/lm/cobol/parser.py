"""Recursive-descent COBOL parser.

Deliberately total: every statement verb either maps to a modelled node or
falls through to ``Other`` with its source text intact. A parser that silently
drops what it does not understand is worse than no parser, because the IR and
the critic downstream both assume completeness.
"""

from __future__ import annotations

from typing import Optional

from .ast_nodes import (
    Accept,
    Arith,
    BinaryOp,
    Call,
    CobolProgram,
    CloseStmt,
    Compute,
    ConditionName,
    ContinueStmt,
    DataDivision,
    DataItem,
    DeleteStmt,
    Display,
    Division,
    EnvironmentDivision,
    Evaluate,
    EvaluateWhen,
    ExitStmt,
    Expression,
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
    Paragraph,
    Perform,
    PerformAfter,
    PerformVarying,
    ProcedureDivision,
    ReadStmt,
    RewriteStmt,
    SearchStmt,
    Section,
    SetStmt,
    Span,
    Statement,
    StopRun,
    StringLiteral,
    StringStmt,
    UnaryOp,
    UnstringStmt,
    WriteStmt,
    Other,
)
from .lexer import CobolSyntaxError, TokKind, Token, tokenize

# Statements that carry an imperative phrase (IF, PERFORM, ...) and are
# terminated by END-IF / the next period, not by the sentence period.
_BLOCK_STARTERS = {"IF", "EVALUATE"}

_VERBS = {    "ACCEPT", "ADD", "CALL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE",
    "DISPLAY", "DIVIDE", "EVALUATE", "EXIT", "GO", "GOBACK", "IF", "INSPECT",
    "MERGE", "MOVE", "MULTIPLY", "OPEN", "PERFORM", "READ", "RELEASE",
    "RETURN", "REWRITE", "SEARCH", "SET", "SORT", "STOP", "STRING", "SUBTRACT",
    "UNSTRING", "WRITE",
}

# Word sequences that begin a paragraph name in the procedure division. We
# match these only at the start of a sentence position.
_SECTION_WORDS = {"SECTION"}
_SECTION_SKIP = {
    "USAGE", "IS", "THRU", "THROUGH", "UNTIL", "VARYING", "AFTER", "DEPENDING",
    "ON", "FROM", "IN", "WITH", "GIVING", "TIMES", "IF", "ELSE", "END-IF",
    "END-PERFORM", "END-EVALUATE", "END-READ", "END-CALL", "END-ADD",
    "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE", "END-RETURN",
    "END-REWRITE", "END-STRING", "END-UNSTRING", "END-DISPLAY", "END-ACCEPT",
}

_DATA_SECTIONS = {
    "FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE", "SCREEN", "COMMUNICATION",
    "REPORT",
}

_USAGE_WORDS = {"BINARY", "COMP", "COMP-3", "PACKED-DECIMAL", "DISPLAY", "INDEX"}

#: Characters legal inside a PICTURE character-string (ANSI 14.7.1).  A WORD
#: token continues a picture only if *every* one of its characters is legal here,
#: which is what separates ``V99``/``S9``/``CR`` from ``COMP-3``/``VALUE``.
_PICTURE_CHARS = set("0123456789XAZRSVPCB*/+-.,$")


def _is_picture_word(text: str) -> bool:
    t = text.upper()
    return bool(t) and all(ch in _PICTURE_CHARS for ch in t)


def _starts_statement(word: str) -> bool:
    """True when ``word`` begins a new statement rather than continuing the
    current one. Used by verbs whose operands are space-separated."""
    return word.upper() in _VERBS or word.upper() in _SECTION_SKIP


class _Parser:
    def __init__(self, tokens: list[Token], path: str = ""):
        self.toks = tokens
        self.i = 0
        self.path = path

    # -- token helpers ---------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def at_word(self, *words: str) -> bool:
        t = self.cur
        return t.kind is TokKind.WORD and t.text.upper() in words

    def at_op(self, *ops: str) -> bool:
        t = self.cur
        if t.kind is TokKind.OP:
            return t.text in ops
        # The lexer gives brackets their own kinds; normalise so callers only
        # ever have to think about the spelling.
        if t.kind is TokKind.LPAREN:
            return "(" in ops
        if t.kind is TokKind.RPAREN:
            return ")" in ops
        return False

    def next(self) -> Token:
        t = self.toks[self.i]
        if t.kind is not TokKind.EOF:
            self.i += 1
        return t

    def accept_word(self, *words: str) -> bool:
        if self.at_word(*words):
            self.next()
            return True
        return False

    def expect_word(self, word: str) -> Token:
        if not self.at_word(word):
            raise CobolSyntaxError(
                f"expected {word!r}, found {self.cur.text!r}", self.cur.span, self.path
            )
        return self.next()

    def accept_op(self, *ops: str) -> bool:
        if self.at_op(*ops):
            self.next()
            return True
        return False

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            raise CobolSyntaxError(
                f"expected {op!r}, found {self.cur.text!r}", self.cur.span, self.path
            )
        return self.next()

    def skip_separators(self) -> None:
        while self.cur.kind in (TokKind.PERIOD, TokKind.COMMA, TokKind.SEMI):
            self.next()

    def at_end_of_sentence(self) -> bool:
        return self.cur.kind in (TokKind.PERIOD, TokKind.EOF, TokKind.SEMI)

    # -- program ---------------------------------------------------------
    def parse_program(self) -> CobolProgram:
        prog = CobolProgram(path=self.path)
        # Skip anything before the first division.
        while not self.at_word(
            "IDENTIFICATION", "ID", "PROGRAM-ID", "ENVIRONMENT", "DATA",
            "PROCEDURE",
        ) and self.cur.kind is not TokKind.EOF:
            self.next()

        if self.at_word("IDENTIFICATION", "ID"):
            self.next()
            prog.identification = self._parse_identification()
            # PROGRAM-ID lives on the division; CobolProgram.program_id is what
            # the IR builder reads, so mirror it here.
            prog.program_id = prog.identification.program_id
        if self.at_word("PROGRAM-ID"):
            # Tolerate sources that omit the IDENTIFICATION DIVISION header.
            self.next()
            self.skip_separators()
            self.accept_word("IS")
            self.accept_word("RECURSIVE")
            prog.program_id = self.next().text
            prog.identification.program_id = prog.program_id
            prog.identification.entries.append(("PROGRAM-ID", prog.program_id))
        if self.at_word("ENVIRONMENT"):
            self.next()
            prog.environment = self._parse_environment()
        if self.at_word("DATA"):
            self.next()
            prog.data = self._parse_data_division()
        if self.at_word("PROCEDURE"):
            self.next()
            prog.procedure = self._parse_procedure_division()
        if not prog.identification.entries and not prog.procedure.sections:
            raise CobolSyntaxError("no divisions found", self.cur.span, self.path)
        return prog

    def _parse_identification(self) -> IdentificationDivision:
        ident = IdentificationDivision()
        self.expect_word("DIVISION")
        self.skip_separators()
        self.expect_word("PROGRAM-ID")
        self.skip_separators()
        self.accept_word("IS")
        self.accept_word("RECURSIVE")
        ident.program_id = self.next().text
        ident.entries.append(("PROGRAM-ID", ident.program_id))
        self.skip_separators()

        # Consume optional paragraph entries (AUTHOR, DATE-WRITTEN, etc.)
        # Stop at the next DIVISION keyword or EOF
        _IDENT_KNOWN = {
            "AUTHOR", "DATE-WRITTEN", "DATE-COMPILED", "SECURITY",
            "REMARKS", "INSTALLATION",
        }
        while self.cur.kind is not TokKind.EOF and not self.at_word(
            "ENVIRONMENT", "DATA", "PROCEDURE"
        ):
            if self.cur.kind in (TokKind.PERIOD, TokKind.COMMA, TokKind.SEMI):
                self.next()
                continue
            if self.cur.kind is not TokKind.WORD:
                self.next()
                continue
            # Stop if this looks like the start of the next division
            if self.at_word("ENVIRONMENT", "DATA", "PROCEDURE"):
                break
            key = self.next().text.upper()
            if key not in _IDENT_KNOWN:
                # Unknown identifier entry — skip until next period
                while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
                    if self.at_word("ENVIRONMENT", "DATA", "PROCEDURE"):
                        break
                    self.next()
                self.skip_separators()
                continue
            if self.accept_word("IS"):
                parts = []
                while self.cur.kind is TokKind.STRING:
                    parts.append(self.next().value or "")
                if parts:
                    ident.entries.append((key, " ".join(parts)))
            # Skip to end of this clause
            while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
                if self.at_word("ENVIRONMENT", "DATA", "PROCEDURE"):
                    break
                self.next()
            self.skip_separators()
        return ident

    def _parse_environment(self) -> EnvironmentDivision:
        env = EnvironmentDivision()
        self.expect_word("DIVISION")
        if self.at_word("CONFIGURATION"):
            self.next()
            self.expect_word("SECTION")
            self.skip_separators()
            while self.cur.kind is TokKind.WORD and not self.at_word("DATA", "PROCEDURE"):
                key = self.next().text.upper()
                if self.accept_word("IS"):
                    env.entries.append((key, self.next().text))
                self.skip_separators()
        if self.at_word("INPUT-OUTPUT"):
            self.next()
            self.expect_word("SECTION")
            self.skip_separators()
            # Skip FILE-CONTROL / I-O-CONTROL blocks entirely
            # by consuming tokens until we reach DATA or PROCEDURE DIVISION
            while self.cur.kind is not TokKind.EOF and not self.at_word("DATA", "PROCEDURE"):
                self.next()
                # After each period, peek ahead to see if the next meaningful
                # word is DATA or PROCEDURE so we don't consume into them
                if self.cur.kind is TokKind.PERIOD:
                    self.next()
                    if self.at_word("DATA", "PROCEDURE"):
                        break
        self.skip_separators()
        return env

    # -- data division ---------------------------------------------------
    def _parse_data_division(self) -> DataDivision:
        data = DataDivision()
        self.expect_word("DIVISION")
        self.skip_separators()

        while self.at_word("FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE", "SCREEN"):
            section = self.next().text.upper()
            if self.accept_word("SECTION"):
                pass
            self.skip_separators()
            if section == "FILE":
                data.file_sections.extend(self._parse_file_section())
            else:
                bucket = {
                    "WORKING-STORAGE": data.working_storage,
                    "LOCAL-STORAGE": data.local_storage,
                    "LINKAGE": data.linkage,
                }.get(section)
                if bucket is None:
                    break
                bucket.extend(self._parse_data_entries(section))
            if self.at_word("PROCEDURE"):
                break
        return data

    def _parse_file_section(self) -> list[FileEntry]:
        entries: list[FileEntry] = []
        self.expect_word("SECTION")
        self.skip_separators()
        while self.at_word("FD", "SD"):
            self.next()
            entry = FileEntry(name=self.next().text.upper(), span=self.cur.span)
            depth = 1
            while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
                w = self.cur
                if w.kind is TokKind.WORD:
                    u = w.text.upper()
                    if u in ("RECORD", "LABEL", "BLOCK", "DATA", "VALUE", "LINAGE"):
                        depth += 1
                    if depth == 0:
                        break
                entry.record_clause.append(self.next().text)
            self.skip_separators()
            entry.fd_records = self._parse_data_entries("FILE", entry=entry)
            entries.append(entry)
        return entries

    def _is_level(self) -> bool:
        return self.cur.kind is TokKind.NUMBER and not self.cur.text.startswith(".")

    def _parse_data_entries(
        self, section: str, entry: Optional[FileEntry] = None
    ) -> list[DataItem]:
        roots: list[DataItem] = []
        stack: list[tuple[int, DataItem]] = []
        while self.at_word("PROCEDURE") or self.cur.kind is TokKind.EOF:
            break
        if not self._is_level():
            return roots
        while self._is_level():
            start = self.cur.span
            level = self.next().text
            if self.cur.kind is TokKind.WORD:
                name = self.next().text.upper()
            else:
                name = f"FILLER-{level}"
            item = DataItem(
                level=level,
                name=name,
                section=section,
                file_entry=entry,
                span=start,
            )
            self._parse_data_attributes(item)
            self.skip_separators()

            if level == "88":
                # An 88-level is a *condition name*, not a data item: it is
                # evaluated against its parent and writes through to it.
                while stack and int(stack[-1][0]) >= int(level):
                    stack.pop()
                if stack:
                    vals = list(item.values)
                    if item.value is not None and item.value not in vals:
                        vals.insert(0, item.value)
                    stack[-1][1].condition_names.append(
                        ConditionName(name=item.name, values=vals, span=start)
                    )
                continue

            while stack and int(stack[-1][0]) >= int(level):
                stack.pop()
            if stack:
                stack[-1][1].children.append(item)
            else:
                roots.append(item)
            stack.append((int(level), item))
        return roots

    def _parse_data_attributes(self, item: DataItem) -> None:
        while True:
            t = self.cur
            if t.kind is TokKind.EOF or t.kind in (
                TokKind.PERIOD,
                TokKind.COMMA,
            ):
                if item.picture and self._is_level():
                    return
                if item.picture:
                    return
                return
            if self.at_word("REDEFINES"):
                self.next()
                item.redefines = self.next().text.upper()
                self.accept_word("DEPENDING")
                continue
            if self.at_word("OCCURS"):
                self.next()
                item.occurs = self._parse_expression()
                if self.accept_word("TO"):
                    self._parse_expression()
                if self.accept_word("TIMES"):
                    pass
                continue
            if self.at_word("VALUE", "VALUES"):
                self.next()
                vals: list[Expression] = [self._parse_value_item()]
                while self.cur.kind is TokKind.COMMA:
                    self.next()
                    vals.append(self._parse_value_item())
                item.values = vals
                item.value = vals[0] if vals else None
                continue
            if self.at_word("PICTURE", "PIC"):
                self.next()
                if self.at_word("IS"):
                    self.next()
                item.picture = self._collect_picture()
                continue
            if self.at_word("USAGE"):
                self.next()
                if self.accept_word("IS"):
                    pass
                u = self.cur.text.upper()
                if u in _USAGE_WORDS:
                    self.next()
                    item.usage = u
                continue
            if self.at_word("SIGN"):
                self.next()
                self.accept_word("IS")
                if self.at_word("LEADING", "TRAILING"):
                    item.sign = self.next().text.upper()
                if self.accept_word("SEPARATE"):
                    item.sign = (item.sign or "LEADING") + " SEPARATE"
                continue
            if self.at_word("JUSTIFIED", "JUST"):
                self.next()
                self.accept_word("RIGHT")
                item.justified = "RIGHT"
                continue
            if self.at_word("SYNCHRONIZED", "SYNC"):
                self.next()
                self.accept_word("LEFT")
                self.accept_word("RIGHT")
                continue
            if t.kind is TokKind.NUMBER and self._is_level():
                return
            if t.kind is TokKind.STRING:
                item.values.append(StringLiteral(value=self.next().value or ""))
                item.value = item.values[-1]
                continue
            if t.kind is TokKind.WORD:
                u = t.text.upper()
                if u == "FILLER":
                    self.next()
                    continue
                if self._is_level():
                    return
                self.next()
                continue
            self.next()

    def _collect_picture(self) -> str:
        """Scan a PICTURE character-string.

        A PICTURE is not a token — ``99V99``, ``S9(7)V99``, ``X(30)``, ``CR`` are
        all legal, and the lexer emits each of those as a plain WORD or NUMBER.
        So the terminator is not "the next token"; it is *the first token that
        cannot be a picture character*. ``COMP-3`` and ``VALUE`` fail that test
        (``O`` and ``L`` are not picture characters), and so does the next data
        item's name — which is exactly the boundary we need.
        """
        parts: list[str] = []
        depth = 0
        while True:
            t = self.cur
            if t.kind is TokKind.EOF or t.kind in (TokKind.PERIOD, TokKind.COMMA):
                break
            if t.kind is TokKind.NUMBER:
                if parts and depth == 0 and self._is_level():
                    # ``PIC X 05 WS-NEXT`` — a bare level number ends the
                    # clause even though a digit is a legal picture character.
                    # ``S9(7)`` is not a level: the digit is inside parens.
                    break
                self.next()
                txt = t.text
                # The lexer glues a sentence-ending period onto a number
                # (``PIC 9.`` lexes as NUMBER "9.").  That period separates
                # statements; only an *internal* dot (``99.10``) belongs to the
                # picture, so drop a trailing one.
                if txt.endswith("."):
                    txt = txt[:-1]
                if txt:
                    parts.append(txt)
                continue
            if t.kind in (TokKind.LPAREN, TokKind.RPAREN):
                parts.append(self.next().text)
                depth += 1 if t.kind is TokKind.LPAREN else -1
                continue
            if t.kind is TokKind.OP and t.text in "()":
                parts.append(self.next().text)
                depth += 1 if t.text == "(" else -1
                continue
            if t.kind is TokKind.WORD and _is_picture_word(t.text):
                parts.append(self.next().text.upper())
                continue
            break
        return "".join(parts)

    def _parse_value_item(self) -> Expression:
        t = self.cur
        if t.kind is TokKind.STRING:
            return StringLiteral(value=self.next().value or "", span=t.span)
        if t.kind is TokKind.NUMBER:
            n = self.next()
            return NumericLiteral(value=n.text, span=n.span)
        if t.kind is TokKind.FIGURATIVE:
            return FigurativeConstant(name=self.next().text.upper(), span=t.span)
        if t.kind is TokKind.WORD:
            return self._parse_qualified_identifier()
        return StringLiteral(value="", span=t.span)

    def _parse_qualified_identifier(self) -> Identifier:
        t = self.next()
        ident = Identifier(name=t.text.upper(), span=t.span)
        while self.at_op("("):
            self.next()
            while not self.at_op(")"):
                if self.cur.kind is TokKind.EOF:
                    break
                if self.cur.kind in (TokKind.PERIOD, TokKind.COMMA):
                    self.next()
                    continue
                if self.cur.kind is TokKind.WORD and self.cur.text.upper() == "OF":
                    self.next()
                    continue
                if self.cur.kind is TokKind.WORD and self.cur.text.upper() == "ALL":
                    self.next()
                    self._parse_value_item()
                    continue
                if self.cur.kind is TokKind.WORD and self.cur.text.upper() == "IN":
                    self.next()
                    continue
                ident.subscripts.append(self._parse_expression())
            self.accept_op(")")
        return ident

    # -- procedure division ----------------------------------------------
    def _parse_procedure_division(self) -> ProcedureDivision:
        proc = ProcedureDivision()
        self.expect_word("DIVISION")
        current: Optional[Section] = None
        current_para: Optional[Paragraph] = None

        while self.cur.kind is not TokKind.EOF:
            self.skip_separators()
            if self.cur.kind is TokKind.EOF:
                break

            # A section header is NAME SECTION.
            if (
                self.cur.kind is TokKind.WORD
                and self.peek().kind is TokKind.WORD
                and self.peek().text.upper() == "SECTION"
                and self.cur.text.upper() not in _VERBS
            ):
                name = self.next().text.upper()
                self.next()
                current = Section(name=name, span=self.cur.span)
                proc.sections.append(current)
                current_para = None
                self.skip_separators()
                continue

            # A paragraph header is NAME followed by period, or a known
            # imperative phrase, or anything at all that is not a verb.
            header = self._try_paragraph_header()
            if header is not None:
                if current is None:
                    current = Section(name="MAIN", span=self.cur.span)
                    proc.sections.insert(0, current)
                current_para = Paragraph(name=header, span=self.cur.span)
                current.paragraphs.append(current_para)
                self.skip_separators()
                continue

            stmts = self._parse_sentence()
            if not stmts:
                self.next()
                continue
            if current_para is None:
                current = Section(name="MAIN", span=self.cur.span)
                if not proc.sections or proc.sections[0] is not current:
                    proc.sections.insert(0, current)
                current_para = Paragraph(name="MAIN", span=self.cur.span)
                current.paragraphs.append(current_para)
            current_para.statements.extend(stmts)

        return proc

    def _try_paragraph_header(self) -> Optional[str]:
        t = self.cur
        if t.kind is not TokKind.WORD:
            return None
        upper = t.text.upper()
        if upper in _VERBS:
            return None
        # NAME. or NAME followed by an imperative phrase
        if self.peek().kind is TokKind.PERIOD:
            self.next()
            self.next()
            return upper
        if self.peek().kind is TokKind.WORD and self.peek().text.upper() in _SECTION_SKIP:
            if upper not in ("MAIN",):
                return upper
        return None

    def _parse_sentence(self) -> list[Statement]:
        out: list[Statement] = []
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            st = self._parse_statement()
            if st is not None:
                out.append(st)
            else:
                break
        self.skip_separators()
        return out

    # -- statements ------------------------------------------------------
    def _parse_statement(self) -> Optional[Statement]:
        t = self.cur
        if t.kind is not TokKind.WORD:
            return None
        verb = t.text.upper()
        handler = getattr(self, f"_stmt_{verb.replace('-', '_').replace(' ', '_')}", None)
        if handler is not None:
            return handler()
        if verb in _VERBS:
            return self._stmt_generic(verb)
        return None

    def _stmt_generic(self, verb: str) -> Statement:
        start = self.cur.span
        words: list[str] = []
        words.append(self.next().text)
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            words.append(self.next().text)
        return Other(verb=verb, text=" ".join(words), span=start)

    # MOVE ---------------------------------------------------------------
    def _stmt_MOVE(self) -> Statement:
        start = self.cur.span
        self.next()
        self.accept_word("CORRESPONDING", "CORR")
        src = self._parse_expression()
        to = False
        if self.accept_word("TO"):
            to = True
        targets: list[Identifier] = []
        if to:
            targets.append(self._parse_qualified_identifier())
            while self.cur.kind is TokKind.COMMA:
                self.next()
                targets.append(self._parse_qualified_identifier())
        return Move(source=src, targets=targets, span=start)

    # COMPUTE ------------------------------------------------------------
    def _stmt_COMPUTE(self) -> Statement:
        start = self.cur.span
        self.next()
        targets = [self._parse_qualified_identifier()]
        while self.cur.kind is TokKind.COMMA:
            self.next()
            targets.append(self._parse_qualified_identifier())
        if self.at_op("="):
            self.next()
        elif self.at_word("EQUAL", "EQUALS"):
            self.next()
        else:
            raise CobolSyntaxError(
                f"expected '=' or 'EQUAL', found {self.cur.text!r}", self.cur.span, self.path
            )
        expr = self._parse_expression()
        rounded = self._accept_rounded()
        on_err, not_err = self._accept_size_error()
        return Compute(
            targets=targets,
            expression=expr,
            rounded=rounded,
            on_size_error=on_err,
            not_on_size_error=not_err,
            span=start,
        )

    def _accept_rounded(self) -> bool:
        if self.at_word("ON", "ROUNDED", "IS"):
            save = self.i
            if self.accept_word("ON"):
                if self.at_word("SIZE"):
                    return False
                self.accept_word("IS")
                if self.accept_word("ROUNDED"):
                    return True
            self.i = save
        return False

    def _accept_size_error(self) -> tuple[Optional[Statement], Optional[Statement]]:
        on_err = None
        not_err = None
        while self.at_word("ON"):
            save = self.i
            self.next()
            if self.accept_word("SIZE"):
                self.expect_word("ERROR")
                on_err = self._parse_statement()
            elif self.at_word("OVERFLOW"):
                self.next()
                on_err = self._parse_statement()
            elif self.at_word("END-EVALUATE", "END-COMPUTE", "END-ARITH"):
                self.next()
            else:
                self.i = save
                break
        return on_err, not_err

    # ADD / SUBTRACT / MULTIPLY / DIVIDE ---------------------------------
    def _arith(self, kind: str) -> Statement:
        start = self.cur.span
        self.next()
        operands = [self._parse_arith_operand()]
        while self.cur.kind is TokKind.COMMA:
            self.next()
            operands.append(self._parse_arith_operand())
        giving: list[Identifier] = []
        receiving: Optional[Identifier] = None
        if self.accept_word("GIVING"):
            giving.append(self._parse_qualified_identifier())
            while self.cur.kind is TokKind.COMMA:
                self.next()
                giving.append(self._parse_qualified_identifier())
        elif self.cur.kind is TokKind.WORD and self._looks_like_receiving_target():
            receiving = self._parse_qualified_identifier()
        elif kind in ("ADD", "SUBTRACT"):
            receiving = self._parse_qualified_identifier()
        elif kind in ("MULTIPLY", "DIVIDE"):
            self.accept_word("BY")
            operands.append(self._parse_arith_operand())
            if self.at_word("GIVING"):
                self.next()
                giving.append(self._parse_qualified_identifier())
            else:
                receiving = self._parse_qualified_identifier()
        rounded = self._accept_rounded()
        on_err, not_err = self._accept_size_error()
        return Arith(
            kind=kind,
            operands=operands,
            giving=giving,
            receiving=receiving,
            rounded=rounded,
            on_size_error=on_err,
            not_on_size_error=not_err,
            span=start,
        )

    def _parse_arith_operand(self) -> Expression:
        return self._parse_expression()

    def _looks_like_receiving_target(self) -> bool:
        t = self.cur
        if t.kind is not TokKind.WORD:
            return False
        u = t.text.upper()
        if u in _VERBS or u in _SECTION_SKIP or u in _DATA_SECTIONS:
            return False
        # A receiving target is followed by a period, or by an
        # (subscript). An operand is followed by an operator.
        nxt = self.peek()
        if nxt.kind in (TokKind.PERIOD, TokKind.EOF, TokKind.SEMI):
            return True
        if nxt.kind is TokKind.OP and nxt.text == "(":
            return True
        return False

    def _stmt_ADD(self) -> Statement:
        return self._arith("ADD")

    def _stmt_SUBTRACT(self) -> Statement:
        return self._arith("SUBTRACT")

    def _stmt_MULTIPLY(self) -> Statement:
        return self._arith("MULTIPLY")

    def _stmt_DIVIDE(self) -> Statement:
        return self._arith("DIVIDE")

    # IF -----------------------------------------------------------------
    def _stmt_IF(self) -> Statement:
        start = self.cur.span
        self.next()
        cond = self._parse_expression()
        if self.at_word("THEN"):
            self.next()
        elif self.at_word("NEXT"):
            self.next()
            self.accept_word("SENTENCE")
        then_branch = self._parse_until_else_or_end()
        else_branch: list[Statement] = []
        if self.at_word("ELSE"):
            self.next()
            if self.at_word("IF"):
                nested = self._stmt_IF()
                if isinstance(nested, If):
                    nested.next_sibling = None
                    else_branch = [nested]
                else:  # pragma: no cover - defensive
                    else_branch = [nested]
            else:
                else_branch = self._parse_until_else_or_end()
        if self.at_word("END-IF"):
            self.next()
            self.accept_word("END-IF")
        return If(condition=cond, then_branch=then_branch, else_branch=else_branch, span=start)

    def _parse_until_else_or_end(self) -> list[Statement]:
        out: list[Statement] = []
        while not self.at_word("ELSE", "END-IF") and self.cur.kind is not TokKind.EOF:
            if self.at_end_of_sentence():
                self.next()
                continue
            st = self._parse_statement()
            if st is None:
                break
            out.append(st)
        return out

    # EVALUATE -----------------------------------------------------------
    def _stmt_EVALUATE(self) -> Statement:
        start = self.cur.span
        self.next()
        subjects: list[Expression] = []
        primary = True
        subjects.append(self._parse_expression())
        while self.accept_word("ALSO"):
            subjects.append(self._parse_expression())
        subject = subjects[0]
        whens: list[EvaluateWhen] = []
        while self.at_word("WHEN"):
            self.next()
            wh = EvaluateWhen()
            if self.at_word("OTHER"):
                self.next()
            else:
                wh.whens.append(self._parse_expression())
                while self.at_word("THROUGH", "THRU"):
                    self.next()
                    wh.whens.append(self._parse_expression())
                while self.accept_word("ALSO"):
                    wh.whens.append(self._parse_expression())
            # Also-subjects on the WHEN line
            while self.accept_word("ALSO"):
                wh.whens.append(self._parse_expression())
            self._parse_when_body(wh.statements)
            whens.append(wh)
        if self.at_word("END-EVALUATE"):
            self.next()
        return Evaluate(subject=subject, subjects=subjects, whens=whens, span=start)

    def _parse_when_body(self, out: list[Statement]) -> None:
        while not self.at_word("WHEN", "END-EVALUATE") and self.cur.kind is not TokKind.EOF:
            if self.at_end_of_sentence():
                self.next()
                continue
            st = self._parse_statement()
            if st is None:
                break
            out.append(st)

    # PERFORM ------------------------------------------------------------
    def _stmt_PERFORM(self) -> Statement:
        start = self.cur.span
        self.next()
        # PERFORM proc-name
        if self.cur.kind is TokKind.WORD and not self.at_word(
            "UNTIL", "VARYING", "FOREVER", "WITH", "TEST", "INFINITY", "TIMES",
        ):
            if self.cur.text.upper() not in _VERBS:
                name = self.next().text.upper()
                thru = None
                if self.at_word("THRU", "THROUGH"):
                    self.next()
                    thru = self.next().text.upper()
                return Perform(target=name, thru=thru, span=start)

        times = None
        until = None
        varying = None
        if self.at_word("WITH", "TEST"):
            self.next()
            self.accept_word("TEST")
            self.accept_word("AFTER")
        if self.at_word("UNTIL"):
            self.next()
            until = self._parse_expression()
        if self.at_word("VARYING"):
            varying = self._parse_varying()
        if self.at_word("FOREVER"):
            self.next()
            varying = PerformVarying(until=FigurativeConstant(name="TRUE"))
        if self.at_word("WITH", "TEST"):
            self.next()
            self.accept_word("TEST")
            self.accept_word("AFTER")
        if self.at_word("UNTIL"):
            self.next()
            until = self._parse_expression()
        if self.at_word("TIMES"):
            self.next()
            times = self._parse_expression()
        body: list[Statement] = []
        if not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            body = self._parse_until_end_perform()
        if self.at_word("END-PERFORM"):
            self.next()
        return Perform(
            times=times, until=until, varying=varying, body=body, span=start
        )

    def _parse_varying(self) -> PerformVarying:
        self.expect_word("VARYING")
        v = PerformVarying(counter=self._parse_qualified_identifier())
        self.expect_word("FROM")
        v.start = self._parse_expression()
        self.expect_word("BY")
        v.by = self._parse_expression()
        self.expect_word("UNTIL")
        v.until = self._parse_expression()
        while self.at_word("AFTER"):
            self.next()
            a = PerformAfter(counter=self._parse_qualified_identifier())
            self.expect_word("FROM")
            a.start = self._parse_expression()
            self.expect_word("BY")
            a.by = self._parse_expression()
            self.expect_word("UNTIL")
            a.until = self._parse_expression()
            v.after.append(a)
        return v

    def _parse_until_end_perform(self) -> list[Statement]:
        out: list[Statement] = []
        while not self.at_word("END-PERFORM") and self.cur.kind is not TokKind.EOF:
            if self.at_end_of_sentence():
                self.next()
                continue
            st = self._parse_statement()
            if st is None:
                break
            out.append(st)
        return out

    # CALL ---------------------------------------------------------------
    def _stmt_CALL(self) -> Statement:
        start = self.cur.span
        self.next()
        program: Optional[Expression] = None
        if self.cur.kind is TokKind.STRING:
            program = StringLiteral(value=self.next().value or "", span=start)
        else:
            program = self._parse_qualified_identifier()
        using: list[Expression] = []
        if self.accept_word("USING"):
            using.append(self._parse_expression())
            while self.cur.kind is TokKind.COMMA:
                self.next()
                using.append(self._parse_expression())
        returning = None
        if self.at_word("RETURNING"):
            self.next()
            returning = self._parse_qualified_identifier()
        on_overflow: list[Statement] = []
        if self.at_word("OVERFLOW", "EXCEPTION", "ON"):
            save = self.i
            self.next()
            if self.at_word("OVERFLOW", "EXCEPTION"):
                self.next()
                on_overflow = self._parse_until_end_call()
            else:
                self.i = save
        if self.at_word("END-CALL"):
            self.next()
        return Call(
            program=program, using=using, returning=returning, on_overflow=on_overflow, span=start
        )

    def _parse_until_end_call(self) -> list[Statement]:
        out: list[Statement] = []
        while not self.at_word("END-CALL") and self.cur.kind is not TokKind.EOF:
            if self.at_end_of_sentence():
                self.next()
                continue
            st = self._parse_statement()
            if st is None:
                break
            out.append(st)
        return out

    # DISPLAY / ACCEPT ---------------------------------------------------
    def _stmt_DISPLAY(self) -> Statement:
        start = self.cur.span
        self.next()
        ops: list[Expression] = []
        no_adv = False
        upon = None
        if not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            ops.append(self._parse_expression())
            # DISPLAY concatenates its operands, and the separator between
            # them is a space rather than a comma.
            while self.cur.kind in (
                TokKind.STRING,
                TokKind.NUMBER,
                TokKind.FIGURATIVE,
                TokKind.LPAREN,
            ) or (self.cur.kind is TokKind.WORD and not _starts_statement(self.cur.text)):
                ops.append(self._parse_expression())
                if self.cur.kind is TokKind.COMMA:
                    self.next()
        if self.at_word("WITH", "UPON"):
            self.next()
            if self.at_word("NO"):
                self.next()
                self.accept_word("ADVANCING")
                no_adv = True
            else:
                upon = self.next().text.upper()
        return Display(operands=ops, upon=upon, no_advancing=no_adv, span=start)

    def _stmt_ACCEPT(self) -> Statement:
        start = self.cur.span
        self.next()
        target = self._parse_qualified_identifier()
        src = None
        if self.at_word("FROM"):
            self.next()
            src = self._parse_expression()
        return Accept(target=target, from_source=src, span=start)

    # GO TO --------------------------------------------------------------
    def _stmt_GO(self) -> Statement:
        start = self.cur.span
        self.next()
        if self.at_word("TO"):
            self.next()
        elif self.at_word("TO)"):
            self.next()
            return GoTo(span=start)
        targets: list[str] = []
        while self.cur.kind is TokKind.WORD and self.cur.text.upper() not in (
            "DEPENDING", "ON",
        ):
            targets.append(self.next().text.upper())
            if self.cur.kind is TokKind.COMMA:
                self.next()
                continue
            break
        depending = None
        if self.at_word("DEPENDING"):
            self.next()
            self.accept_word("ON")
            depending = self._parse_qualified_identifier()
        return GoTo(targets=targets, depending=depending, span=start)

    def _stmt_GOBACK(self) -> Statement:
        start = self.cur.span
        self.next()
        return StopRun(span=start)

    # STOP / EXIT / CONTINUE ---------------------------------------------
    def _stmt_STOP(self) -> Statement:
        start = self.cur.span
        self.next()
        self.accept_word("RUN")
        return StopRun(span=start)

    def _stmt_EXIT(self) -> Statement:
        start = self.cur.span
        self.next()
        target = None
        if self.at_word("PARAGRAPH", "SECTION", "PROGRAM", "PERFORM", "FUNCTION"):
            target = self.next().text.upper()
            if target == "FUNCTION":
                target = f"PROGRAM:{self.next().text.upper()}"
        return ExitStmt(target=target, span=start)

    def _stmt_CONTINUE(self) -> Statement:
        start = self.cur.span
        self.next()
        return ContinueStmt(span=start)

    # SET ----------------------------------------------------------------
    def _stmt_SET(self) -> Statement:
        start = self.cur.span
        self.next()
        targets = [self._parse_qualified_identifier()]
        while self.cur.kind is TokKind.COMMA:
            self.next()
            targets.append(self._parse_qualified_identifier())
        to = None
        if self.accept_word("TO"):
            if self.at_word("TRUE"):
                to = self.next()
            elif self.at_word("FALSE"):
                to = self.next()
            else:
                to = self._parse_expression()
        return SetStmt(targets=targets, to=to, span=start)

    # INSPECT ------------------------------------------------------------
    def _stmt_INSPECT(self) -> Statement:
        start = self.cur.span
        self.next()
        target = self._parse_qualified_identifier()
        operation = None
        if self.at_word("TALLYING"):
            self.next()
            operation = "TALLYING"
            while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
                if self.cur.kind is TokKind.WORD and self.cur.text.upper() in (
                    "REPLACING", "CONVERTING", "CONVERT",
                ):
                    operation = self.next().text.upper()
                    continue
                if self.cur.kind is TokKind.WORD:
                    key = self.next().text.upper()
                    if self.accept_word("FOR"):
                        # skip the pattern
                        if self.at_word("CHARACTERS", "ALL", "LEADING", "TRAILING"):
                            self.next()
                        else:
                            self._parse_value_item()
                        self.next()  # CHARACTERS
                    if self.accept_word("WITH"):
                        if self.at_word("CHARACTERS"):
                            self.next()
                    continue
                self.next()
        else:
            self._collect_word_sequence()
        return Inspect(target=target, operation=operation, span=start)

    def _collect_word_sequence(self) -> list[str]:
        out: list[str] = []
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            out.append(self.next().text)
        return out

    # file statements ----------------------------------------------------
    def _stmt_OPEN(self) -> Statement:
        start = self.cur.span
        self.next()
        entries: list[tuple[str, list[str]]] = []
        mode: str = "INPUT"
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            if self.at_word("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = self.next().text.upper()
                continue
            if self.cur.kind is TokKind.WORD:
                entries.append((mode, [self.next().text.upper()]))
                while self.at_word("REVERSED", "WITH"):
                    self.next()
                continue
            self.next()
        return OpenStmt(entries=entries, span=start)

    def _stmt_CLOSE(self) -> Statement:
        start = self.cur.span
        self.next()
        files: list[str] = []
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            if self.cur.kind is TokKind.WORD:
                files.append(self.next().text.upper())
                continue
            self.next()
        return CloseStmt(files=files, span=start)

    def _stmt_READ(self) -> Statement:
        start = self.cur.span
        self.next()
        nxt = None
        if self.at_word("NEXT", "PREVIOUS"):
            nxt = self.next().text.upper()
        if self.at_word("RECORD"):
            self.next()
        self.accept_word("INTO")
        file_name = self.next().text.upper() if self.cur.kind is TokKind.WORD else ""
        into = None
        if self.accept_word("INTO"):
            into = self._parse_qualified_identifier()
        key = None
        if self.at_word("KEY"):
            self.next()
            self.accept_word("IS")
            key = self._parse_qualified_identifier()
        at_end: list[Statement] = []
        not_at_end: list[Statement] = []
        invalid: list[Statement] = []
        while self.at_word("AT", "NOT", "INVALID"):
            if self.at_word("AT"):
                self.next()
                if self.at_word("END"):
                    self.next()
                    at_end = self._parse_read_handler()
                else:
                    self.next()
            elif self.at_word("NOT"):
                self.next()
                if self.at_word("AT"):
                    self.next()
                    self.accept_word("END")
                    not_at_end = self._parse_read_handler()
            else:
                self.next()
                if self.at_word("KEY"):
                    self.next()
                invalid = self._parse_read_handler()
        if self.at_word("END-READ"):
            self.next()
        return ReadStmt(
            file=file_name,
            into=into,
            next_record=nxt,
            key=key,
            at_end=at_end,
            not_at_end=not_at_end,
            invalid_key=invalid,
            span=start,
        )

    def _parse_read_handler(self) -> list[Statement]:
        out: list[Statement] = []
        while not self.at_word("AT", "NOT", "INVALID", "END-READ") and self.cur.kind is not TokKind.EOF:
            if self.at_end_of_sentence():
                self.next()
                continue
            st = self._parse_statement()
            if st is None:
                break
            out.append(st)
        return out

    def _stmt_WRITE(self) -> Statement:
        start = self.cur.span
        self.next()
        self.accept_word("RECORD")
        record = None
        if self.cur.kind is TokKind.WORD and not self.at_word("AFTER", "BEFORE", "FROM"):
            record = self._parse_qualified_identifier()
        from_source = None
        if self.at_word("FROM"):
            self.next()
            from_source = self._parse_expression()
        invalid: list[Statement] = []
        while self.at_word("INVALID", "END-WRITE"):
            if self.at_word("END-WRITE"):
                self.next()
                break
            self.next()
            if self.at_word("KEY"):
                self.next()
            invalid = self._parse_until_end_write()
        return WriteStmt(record=record, from_source=from_source, invalid_key=invalid, span=start)

    def _parse_until_end_write(self) -> list[Statement]:
        out: list[Statement] = []
        while not self.at_word("INVALID", "END-WRITE") and self.cur.kind is not TokKind.EOF:
            if self.at_end_of_sentence():
                self.next()
                continue
            st = self._parse_statement()
            if st is None:
                break
            out.append(st)
        return out

    def _stmt_DELETE(self) -> Statement:
        start = self.cur.span
        self.next()
        self.accept_word("RECORD")
        self.accept_word("FROM")
        f = self.next().text.upper() if self.cur.kind is TokKind.WORD else ""
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            self.next()
        return DeleteStmt(file=f, span=start)

    def _stmt_REWRITE(self) -> Statement:
        start = self.cur.span
        self.next()
        self.accept_word("RECORD")
        rec = self._parse_qualified_identifier() if self.cur.kind is TokKind.WORD else None
        from_source = None
        if self.at_word("FROM"):
            self.next()
            from_source = self._parse_expression()
        while not self.at_end_of_sentence() and self.cur.kind is not TokKind.EOF:
            self.next()
        return RewriteStmt(record=rec, from_source=from_source, span=start)

    def _stmt_SEARCH(self) -> Statement:
        start = self.cur.span
        self.next()
        self.accept_word("ALL")
        target = self._parse_qualified_identifier() if self.cur.kind is TokKind.WORD else None
        varying = None
        if self.at_word("VARYING"):
            self.next()
            varying = self._parse_qualified_identifier()
        whens: list[tuple[Optional[Expression], list[Statement]]] = []
        while self.at_word("WHEN"):
            self.next()
            cond = None
            if not self.at_word("OTHER"):
                cond = self._parse_expression()
            body: list[Statement] = []
            while not self.at_word("WHEN", "END-SEARCH") and self.cur.kind is not TokKind.EOF:
                if self.at_end_of_sentence():
                    self.next()
                    continue
                st = self._parse_statement()
                if st is None:
                    break
                body.append(st)
            whens.append((cond, body))
        if self.at_word("END-SEARCH"):
            self.next()
        return SearchStmt(target=target, varying=varying, when=whens, span=start)

    def _stmt_STRING(self) -> Statement:
        start = self.cur.span
        self.next()
        sending: list[Expression] = []
        if not self.at_end_of_sentence():
            sending.append(self._parse_expression())
            while self.cur.kind is TokKind.COMMA:
                self.next()
                sending.append(self._parse_expression())
        into = None
        ptr = None
        if self.accept_word("INTO"):
            into = self._parse_qualified_identifier()
        if self.at_word("WITH"):
            self.next()
            self.accept_word("POINTER")
            ptr = self._parse_qualified_identifier()
        if self.at_word("END-STRING"):
            self.next()
        return StringStmt(sending=sending, into=into, with_pointer=ptr, span=start)

    def _stmt_UNSTRING(self) -> Statement:
        start = self.cur.span
        self.next()
        src = None
        if not self.at_end_of_sentence():
            src = self._parse_expression()
        targets: list[tuple[Optional[Expression], Identifier]] = []
        if self.at_word("INTO"):
            self.next()
            targets.append((None, self._parse_qualified_identifier()))
            while self.cur.kind is TokKind.COMMA:
                self.next()
                targets.append((None, self._parse_qualified_identifier()))
        if self.at_word("END-UNSTRING"):
            self.next()
        return UnstringStmt(source=src, targets=targets, span=start)

    # -- expressions -----------------------------------------------------
    def _parse_expression(self) -> Expression:
        return self._parse_or()

    def _parse_or(self) -> Expression:
        left = self._parse_and()
        while self.at_op("OR"):
            op = self.next()
            right = self._parse_and()
            left = BinaryOp(op="OR", left=left, right=right, span=op.span)
        return left

    def _parse_and(self) -> Expression:
        left = self._parse_not()
        while self.at_op("AND"):
            op = self.next()
            right = self._parse_not()
            left = BinaryOp(op="AND", left=left, right=right, span=op.span)
        return left

    def _parse_not(self) -> Expression:
        if self.at_op("-", "+"):
            op = self.next()
            operand = self._parse_not()
            return UnaryOp(op=op.text, operand=operand, span=op.span)
        if self.at_word("NOT"):
            op = self.next()
            operand = self._parse_not()
            return UnaryOp(op="NOT", operand=operand, span=op.span)
        return self._parse_relational()

    def _parse_relational(self) -> Expression:
        left = self._parse_additive()
        if self.at_op("=", "<", ">", "<=", ">=", "<>"):
            op = self.next()
            right = self._parse_additive()
            return BinaryOp(op=op.text, left=left, right=right, span=op.span)
        return left

    def _parse_additive(self) -> Expression:
        left = self._parse_multiplicative()
        while self.at_op("+", "-"):
            op = self.next()
            right = self._parse_multiplicative()
            left = BinaryOp(op=op.text, left=left, right=right, span=op.span)
        return left

    def _parse_multiplicative(self) -> Expression:
        left = self._parse_power()
        while self.at_op("*", "/"):
            op = self.next()
            right = self._parse_power()
            left = BinaryOp(op=op.text, left=left, right=right, span=op.span)
        return left

    def _parse_power(self) -> Expression:
        left = self._parse_primary()
        if self.at_op("**"):
            op = self.next()
            right = self._parse_primary()
            return BinaryOp(op="**", left=left, right=right, span=op.span)
        return left

    def _parse_primary(self) -> Expression:
        t = self.cur
        if t.kind is TokKind.NUMBER:
            self.next()
            return NumericLiteral(
                value=t.text,
                kind="decimal" if "." in t.text else "integer",
                span=t.span,
            )
        if t.kind is TokKind.STRING:
            self.next()
            return StringLiteral(value=t.value or "", span=t.span)
        if t.kind is TokKind.FIGURATIVE:
            self.next()
            return FigurativeConstant(name=t.text.upper(), span=t.span)
        if t.kind is TokKind.LPAREN:
            self.next()
            inner = self._parse_expression()
            self.accept_op(")")
            return inner
        if t.kind is TokKind.OP and t.text == "*":
            # reference modification: FIELD(1:4)
            self.next()
            return Identifier(name="*", span=t.span)
        if t.kind is TokKind.WORD:
            u = t.text.upper()
            nxt = self.peek()
            if u in ("FUNCTION",) or (
                nxt.kind is TokKind.LPAREN and u in _INTRINSICS
            ):
                name = self.next().text.upper()
                if name == "FUNCTION":
                    name = self.next().text.upper()
                args: list[Expression] = []
                if self.at_op("("):
                    self.next()
                    while not self.at_op(")") and self.cur.kind is not TokKind.EOF:
                        if self.cur.kind in (TokKind.PERIOD, TokKind.COMMA):
                            self.next()
                            continue
                        if self.at_word("OF", "IN", "LENGTH", "ALL"):
                            self.next()
                            continue
                        args.append(self._parse_expression())
                    self.accept_op(")")
                return FunctionCall(name=name, args=args, span=t.span)
            return self._parse_qualified_identifier()
        if t.kind is TokKind.OP and t.text in ("=", "<", ">"):
            return self._parse_qualified_identifier()
        raise CobolSyntaxError(f"unexpected token {t.text!r}", t.span, self.path)


_INTRINSICS = {
    "LENGTH", "FUNCTION-LENGTH", "NUMVAL", "FUNCTION-NUMVAL", "MAX",
    "FUNCTION-MAX", "MIN", "FUNCTION-MIN", "ORD", "FUNCTION-ORD",
    "CHAR", "FUNCTION-CHAR", "SUM", "FUNCTION-SUM", "MOD", "FUNCTION-MOD",
    "FUNCTION-ABS", "ABS", "FUNCTION-INTEGER", "INTEGER", "FUNCTION-REM",
    "REM",
}


def parse_cobol(text: str, path: str = "", source_format: str = "auto") -> CobolProgram:
    """Parse COBOL source into a :class:`CobolProgram`.

    Raises :class:`CobolSyntaxError` with a line number on malformed input.
    """
    tokens = tokenize(text, path=path, source_format=source_format)
    parser = _Parser(tokens, path=path)
    return parser.parse_program()

"""Typed AST for the COBOL subset the pipeline understands.

Everything is a plain dataclass. The parser is the only thing that builds
these, and the IR builder is the only thing that reads them, so the AST can
stay boring and total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Span:
    """1-based source position. ``end_line`` is inclusive."""

    line: int
    end_line: int
    column: int = 0

    def merge(self, other: "Span") -> "Span":
        return Span(self.line, max(self.end_line, other.end_line), self.column)


# --------------------------------------------------------------------------
# literals and expressions
# --------------------------------------------------------------------------


@dataclass
class NumericLiteral:
    value: str
    kind: str = "integer"  # integer | decimal
    span: Optional[Span] = None


@dataclass
class StringLiteral:
    value: str
    span: Optional[Span] = None


@dataclass
class FigurativeConstant:
    name: str  # ZERO SPACE HIGH-VALUES LOW-VALUES QUOTE ALL
    span: Optional[Span] = None


@dataclass
class Identifier:
    name: str
    subscripts: list["Expression"] = field(default_factory=list)
    span: Optional[Span] = None

    @property
    def qualified(self) -> str:
        return self.name


@dataclass
class UnaryOp:
    op: str  # + -
    operand: "Expression"
    span: Optional[Span] = None


@dataclass
class BinaryOp:
    op: str  # + - * / ** = < > <= >= AND OR NOT
    left: "Expression"
    right: "Expression"
    span: Optional[Span] = None


@dataclass
class FunctionCall:
    name: str  # LENGTH FUNCTION-NUM etc, uppercased
    args: list["Expression"] = field(default_factory=list)
    span: Optional[Span] = None


Expression = (
    NumericLiteral
    | StringLiteral
    | FigurativeConstant
    | Identifier
    | UnaryOp
    | BinaryOp
    | FunctionCall
)


# --------------------------------------------------------------------------
# data division
# --------------------------------------------------------------------------


@dataclass
class ConditionName:
    """An 88-level, e.g. ``88 EOF-AT-END VALUE 10 20 30``."""

    name: str
    values: list["Expression"] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class DataItem:
    level: str
    name: str
    picture: Optional[str] = None
    usage: Optional[str] = None  # DISPLAY BINARY COMP PACKED-DECIMAL
    occurs: Optional[Expression] = None
    redefines: Optional[str] = None
    value: Optional["Expression"] = None
    values: list["Expression"] = field(default_factory=list)
    condition_names: list[ConditionName] = field(default_factory=list)
    sign: Optional[str] = None  # LEADING SEPARATE/TRAILING
    blank: bool = False
    justified: Optional[str] = None
    children: list["DataItem"] = field(default_factory=list)
    section: str = "WORKING-STORAGE"  # FILE | WORKING-STORAGE | LOCAL-STORAGE | LINKAGE
    file_entry: Optional["FileEntry"] = None
    span: Optional[Span] = None

    @property
    def qualified_name(self) -> str:
        return self.name


@dataclass
class FileEntry:
    name: str
    organization: Optional[str] = None  # SEQUENTIAL INDEXED RELATIVE
    access: Optional[str] = None
    record_clause: list[str] = field(default_factory=list)
    label_records: list[str] = field(default_factory=list)
    fd_records: list[DataItem] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class DataDivision:
    file_sections: list[FileEntry] = field(default_factory=list)
    working_storage: list[DataItem] = field(default_factory=list)
    local_storage: list[DataItem] = field(default_factory=list)
    linkage: list[DataItem] = field(default_factory=list)

    def all_items(self) -> list[DataItem]:
        out: list[DataItem] = []
        for f in self.file_sections:
            out.extend(f.fd_records)
        for group in (self.working_storage, self.local_storage, self.linkage):
            out.extend(group)
        return out


# --------------------------------------------------------------------------
# procedure division statements
# --------------------------------------------------------------------------


@dataclass
class Statement:
    """Base. ``kind`` discriminates for the IR builder."""

    kind: str = "stmt"
    span: Optional[Span] = None


@dataclass
class Move(Statement):
    kind: str = "MOVE"
    source: Optional[Expression] = None
    targets: list[Identifier] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class Compute(Statement):
    kind: str = "COMPUTE"
    targets: list[Identifier] = field(default_factory=list)
    expression: Optional[Expression] = None
    rounded: bool = False
    on_size_error: Optional["Statement"] = None
    not_on_size_error: Optional["Statement"] = None
    span: Optional[Span] = None


@dataclass
class Arith(Statement):
    """ADD/SUBTRACT/MULTIPLY/DIVIDE. The 3-op form ``ADD A B GIVING C`` is
    distinguished by ``giving``."""

    kind: str = "ADD"
    operands: list[Expression] = field(default_factory=list)
    giving: list[Identifier] = field(default_factory=list)
    receiving: Optional[Identifier] = None
    rounded: bool = False
    on_size_error: Optional["Statement"] = None
    not_on_size_error: Optional["Statement"] = None
    span: Optional[Span] = None


@dataclass
class If(Statement):
    kind: str = "IF"
    condition: Optional[Expression] = None
    then_branch: list[Statement] = field(default_factory=list)
    else_branch: list[Statement] = field(default_factory=list)
    next_sibling: Optional["If"] = None  # ELSE IF chain
    span: Optional[Span] = None


@dataclass
class EvaluateWhen:
    whens: list[Expression] = field(default_factory=list)  # empty == WHEN OTHER
    statements: list[Statement] = field(default_factory=list)


@dataclass
class Evaluate(Statement):
    kind: str = "EVALUATE"
    subject: Optional[Expression] = None
    subjects: list[Expression] = field(default_factory=list)  # multi-subject form
    whens: list[EvaluateWhen] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class Perform(Statement):
    kind: str = "PERFORM"
    target: Optional[str] = None
    thru: Optional[str] = None
    times: Optional[Expression] = None
    until: Optional[Expression] = None
    varying: Optional["PerformVarying"] = None
    body: list[Statement] = field(default_factory=list)  # inline PERFORM
    span: Optional[Span] = None


@dataclass
class PerformVarying:
    counter: Optional[Identifier] = None
    start: Optional[Expression] = None
    by: Optional[Expression] = None
    until: Optional[Expression] = None
    after: list["PerformAfter"] = field(default_factory=list)


@dataclass
class PerformAfter:
    counter: Optional[Identifier] = None
    start: Optional[Expression] = None
    by: Optional[Expression] = None
    until: Optional[Expression] = None


@dataclass
class Call(Statement):
    kind: str = "CALL"
    program: Optional[Expression] = None  # Identifier or StringLiteral
    using: list[Expression] = field(default_factory=list)
    returning: Optional[Identifier] = None
    on_overflow: list[Statement] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class Display(Statement):
    kind: str = "DISPLAY"
    operands: list[Expression] = field(default_factory=list)
    upon: Optional[str] = None
    no_advancing: bool = False
    span: Optional[Span] = None


@dataclass
class Accept(Statement):
    kind: str = "ACCEPT"
    target: Optional[Identifier] = None
    from_source: Optional[Expression] = None
    span: Optional[Span] = None


@dataclass
class GoTo(Statement):
    kind: str = "GO TO"
    targets: list[str] = field(default_factory=list)
    depending: Optional[Identifier] = None
    span: Optional[Span] = None


@dataclass
class StopRun(Statement):
    kind: str = "STOP RUN"
    span: Optional[Span] = None


@dataclass
class ExitStmt(Statement):
    kind: str = "EXIT"
    target: Optional[str] = None  # EXIT PARAGRAPH-name / EXIT SECTION
    span: Optional[Span] = None


@dataclass
class ContinueStmt(Statement):
    kind: str = "CONTINUE"
    span: Optional[Span] = None


@dataclass
class SetStmt(Statement):
    kind: str = "SET"
    targets: list[Identifier] = field(default_factory=list)
    to: Optional[Expression] = None  # TRUE / FALSE / TO
    span: Optional[Span] = None


@dataclass
class Inspect(Statement):
    kind: str = "INSPECT"
    target: Optional[Identifier] = None
    operation: Optional[str] = None
    tallying: list[tuple[Optional[str], Optional[Identifier]]] = field(
        default_factory=list
    )
    span: Optional[Span] = None


@dataclass
class OpenStmt(Statement):
    kind: str = "OPEN"
    entries: list[tuple[str, list[str]]] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class CloseStmt(Statement):
    kind: str = "CLOSE"
    files: list[str] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class ReadStmt(Statement):
    kind: str = "READ"
    file: Optional[str] = None
    into: Optional[Identifier] = None
    next_record: Optional[str] = None
    key: Optional[Identifier] = None
    at_end: list[Statement] = field(default_factory=list)
    not_at_end: list[Statement] = field(default_factory=list)
    invalid_key: list[Statement] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class WriteStmt(Statement):
    kind: str = "WRITE"
    record: Optional[Identifier] = None
    from_source: Optional[Expression] = None
    invalid_key: list[Statement] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class SearchStmt(Statement):
    kind: str = "SEARCH"
    target: Optional[Identifier] = None
    varying: Optional[Identifier] = None
    when: list[tuple[Optional[Expression], list[Statement]]] = field(
        default_factory=list
    )
    span: Optional[Span] = None


@dataclass
class StringStmt(Statement):
    kind: str = "STRING"
    sending: list[Expression] = field(default_factory=list)
    into: Optional[Identifier] = None
    with_pointer: Optional[Identifier] = None
    span: Optional[Span] = None


@dataclass
class UnstringStmt(Statement):
    kind: str = "UNSTRING"
    source: Optional[Expression] = None
    targets: list[tuple[Optional[Expression], Identifier]] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class DeleteStmt(Statement):
    kind: str = "DELETE"
    file: Optional[str] = None
    span: Optional[Span] = None


@dataclass
class RewriteStmt(Statement):
    kind: str = "REWRITE"
    record: Optional[Identifier] = None
    from_source: Optional[Expression] = None
    span: Optional[Span] = None


@dataclass
class Other(Statement):
    """Anything we parse but do not model. Never silently dropped: the IR
    builder emits an UNSUPPORTED edge so the critic can require a decision."""

    kind: str = "OTHER"
    verb: str = ""
    text: str = ""
    span: Optional[Span] = None


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------


@dataclass
class Paragraph:
    name: str
    statements: list[Statement] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class Section:
    name: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class ProcedureDivision:
    sections: list[Section] = field(default_factory=list)
    span: Optional[Span] = None

    def paragraphs(self) -> list[Paragraph]:
        return [p for s in self.sections for p in s.paragraphs]


@dataclass
class Division:
    name: str
    statements: list[Statement] = field(default_factory=list)
    span: Optional[Span] = None


@dataclass
class IdentificationDivision:
    program_id: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class EnvironmentDivision:
    source_computer: str = ""
    object_computer: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)
    special_names: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CobolProgram:
    path: str
    source_format: str = "fixed"  # fixed | free
    dialect: str = "COBOL-85"
    program_id: str = ""
    identification: IdentificationDivision = field(default_factory=IdentificationDivision)
    environment: EnvironmentDivision = field(default_factory=EnvironmentDivision)
    data: DataDivision = field(default_factory=DataDivision)
    procedure: ProcedureDivision = field(default_factory=ProcedureDivision)
    spans: list[Span] = field(default_factory=list)

    def paragraphs(self) -> list[Paragraph]:
        return self.procedure.paragraphs()

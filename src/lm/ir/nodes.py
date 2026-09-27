"""Normalised Intermediate Representation.

Design rules, in priority order:

1. **Total.** Every COBOL statement has an IR form, including the ones we do
   not support. ``OpKind.UNSUPPORTED`` exists so the critic can force a human
   decision rather than letting a construct vanish.
2. **No COBOL vocabulary.** No PIC clauses, no figurative constants, no
   paragraph names with dashes, no verb strings. Anything COBOL-specific is
   *resolved* here, once, into explicit type and op decisions.
3. **Addressable.** Every variable has a stable id (``v7``) separate from its
   name, so renaming, and therefore the ``ORIGIN`` provenance edge, is cheap.
4. **Serializable.** Every node is a plain dataclass that round-trips to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class OpKind(str, Enum):
    ASSIGN = "assign"
    COMPUTE = "compute"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    COMPARE = "compare"
    BRANCH = "branch"
    BRANCH_COND = "branch_cond"
    RETURN = "return"
    CALL = "call"
    IO_READ = "io_read"
    IO_WRITE = "io_write"
    IO_OPEN = "io_open"
    IO_CLOSE = "io_close"
    DISPLAY = "display"
    ACCEPT = "accept"
    SET_FLAG = "set_flag"
    TALLY = "tally"
    SEARCH = "search"
    STRING_OP = "string_op"
    UNSTRING_OP = "unstring"
    GOTO_INDEXED = "goto_indexed"
    EVALUATE = "evaluate"
    NOP = "nop"
    UNSUPPORTED = "unsupported"


class IrType(str, Enum):
    INT = "int"
    DEC = "dec"
    STR = "str"
    BOOL = "bool"
    UNKNOWN = "unknown"


#: Characters legal inside a PICTURE character-string, plus the ``X(n)`` /
#: ``9(n)`` repeat operator.
_PIC_TAIL = "0123456789XAZRSVPCB*/+-.,$"

#: USAGEs that carry their own sign bit, so ``S`` need not appear in the PICTURE.
_SIGNED_USAGES = {"COMP", "COMP-1", "COMP-2", "COMP-4", "COMP-5", "BINARY", "COMPUTATIONAL"}


def expand_picture(picture: Optional[str]) -> str:
    """Expand a PICTURE character-string to one character per storage position.

    ``S9(3)V99`` -> ``S999V99``; ``X(30)`` -> thirty ``X``s.  Everything
    downstream — storage size, digit count, the decimal scale the interpreter
    truncates to — is derived from this, so the arithmetic lives in one place.
    """
    if not picture:
        return ""
    p = picture.upper()
    if p.startswith("PIC"):
        p = p[3:].strip()
    out: list[str] = []
    i = 0
    while i < len(p):
        ch = p[i]
        if ch == "(":
            j = p.find(")", i + 1)
            if j > 0:
                try:
                    n = int(p[i + 1 : j])
                except ValueError:
                    n = 1
                out.append("?" * n)
                i = j + 1
                continue
            i += 1
            continue
        if ch == ")":
            i += 1
            continue
        if i + 1 < len(p) and p[i + 1] == "(":
            j = p.find(")", i + 2)
            if j > 0:
                try:
                    n = int(p[i + 2 : j])
                except ValueError:
                    n = 1
                out.append(ch * n)
                i = j + 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def pic_info(picture: Optional[str], usage: Optional[str] = None) -> dict:
    """Storage model of a PICTURE: digit count, implied-decimal scale, sign,
    and the fixed display width.  The differential oracle uses this to make the
    IR interpreter and the emitted code truncate to identical storage."""
    p = expand_picture(picture)
    digits = sum(1 for ch in p if ch == "9")
    if "." in p:
        scale = len(p.split(".", 1)[1])
        digits += scale
    elif "V" in p:
        scale = len(p.split("V", 1)[1])
    else:
        scale = 0
    # S and P are sign/padding positions; V is an implied decimal point that
    # occupies no storage.  What is left is the field's display width.
    width = sum(1 for ch in p if ch not in "SPV.")
    return {
        "picture": picture,
        "expanded": p,
        "digits": digits,
        "scale": scale,
        "signed": "S" in p or (usage or "").upper() in _SIGNED_USAGES,
        "width": max(1, width) if width else 1,
        "alpha": sum(1 for ch in p if ch in "XA"),
    }


#: COBOL USAGE/PIC -> IR type
def pic_type(picture: Optional[str], usage: Optional[str]) -> IrType:
    u = (usage or "DISPLAY").upper()
    if u in {"COMP-3", "PACKED-DECIMAL", "COMP", "BINARY", "COMPUTATIONAL"}:
        return IrType.DEC if "COMP-3" in u or "PACKED" in u else IrType.INT
    if not picture:
        return IrType.UNKNOWN
    p = picture.upper()
    if p.startswith("PIC"):
        p = p[3:].strip()
    has_9 = "9" in p
    has_v = "V" in p or "." in p
    has_x = "X" in p or "A" in p
    if has_x and not has_9:
        return IrType.STR
    if has_v:
        return IrType.DEC
    if has_9:
        return IrType.INT
    return IrType.STR


def pic_size(picture: Optional[str], usage: Optional[str]) -> int:
    """Approximate on-disk size in bytes. Used for OCCURS expansion and for
    telling the executor how a field behaves, not for accounting."""
    if not picture:
        return 1
    u = (usage or "DISPLAY").upper()
    expanded = expand_picture(picture)
    digits = 0
    alpha = 0
    for ch in expanded:
        if ch in "9":
            digits += 1
        elif ch in "XA":
            alpha += 1
    scale = pic_info(picture, usage)["scale"]
    digits += scale
    if u in {"COMP-3", "PACKED-DECIMAL"}:
        return (digits // 2) + 1 if digits else 1
    if u in {"COMP", "BINARY", "COMPUTATIONAL"}:
        if digits <= 4:
            return 2
        if digits <= 9:
            return 4
        return 8
    total = digits + alpha
    return total if total else 1


@dataclass
class IrVar:
    """A variable slot. ``name`` is the COBOL name; ``vid`` is IR-internal."""

    vid: str
    name: str
    type: IrType = IrType.UNKNOWN
    size: int = 1
    occurs: int = 1
    level: str = ""
    usage: str = "DISPLAY"
    picture: Optional[str] = None
    section: str = "WORKING-STORAGE"
    redefines: Optional[str] = None
    initial: Any = None
    is_condition: bool = False  # 88-level
    #: for 88-levels: the vid of the data item whose value the condition tests.
    #: Reading a condition var evaluates ``host in initial``; assigning one
    #: writes through to the host.
    host: Optional[str] = None
    is_param: bool = False
    is_file: bool = False
    is_temp: bool = False
    origin: Optional[str] = None  # source span string, for provenance

    def qualified(self) -> str:
        return self.name


@dataclass
class IrConst:
    ctype: str = "literal"  # literal | int | dec | str | figurative
    value: Any = None
    type: IrType = IrType.STR
    symbol: Optional[str] = None  # for figurative: ZERO/SPACES/...


@dataclass
class IrExpr:
    """Expression node. ``kind`` is one of: const, var, binary, unary, call."""

    kind: str
    const: Optional[IrConst] = None
    var: Optional[str] = None  # vid
    op: Optional[str] = None
    left: Optional["IrExpr"] = None
    right: Optional["IrExpr"] = None
    args: list["IrExpr"] = field(default_factory=list)
    span: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "const": asdict(self.const) if self.const else None,
            "var": self.var,
            "op": self.op,
            "left": self.left.to_json() if self.left else None,
            "right": self.right.to_json() if self.right else None,
            "args": [a.to_json() for a in self.args],
            "span": self.span,
        }

    @staticmethod
    def from_json(d: dict) -> "IrExpr":
        const = IrConst(**d["const"]) if d.get("const") else None
        return IrExpr(
            kind=d["kind"],
            const=const,
            var=d.get("var"),
            op=d.get("op"),
            left=IrExpr.from_json(d["left"]) if d.get("left") else None,
            right=IrExpr.from_json(d["right"]) if d.get("right") else None,
            args=[IrExpr.from_json(a) for a in d.get("args", [])],
            span=d.get("span"),
        )


@dataclass
class IrStmt:
    """A single IR instruction, always in a block."""

    sid: str
    op: OpKind
    targets: list[str] = field(default_factory=list)  # vids
    expr: Optional[IrExpr] = None
    args: list[IrExpr] = field(default_factory=list)
    label: Optional[str] = None
    target_label: Optional[str] = None
    targets_labels: list[str] = field(default_factory=list)
    cond: Optional[IrExpr] = None
    cases: list[tuple[list[Optional[IrExpr]], str]] = field(default_factory=list)
    #: for io_*: file vid
    file: Optional[str] = None
    #: for call: normalised callee
    callee: Optional[str] = None
    #: for display/accept
    text: Optional[str] = None
    #: block-level for dispatch (evaluate/search): a switch expression
    dispatch: Optional[IrExpr] = None
    span: Optional[str] = None
    #: provenance: source verb this came from
    origin: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d["op"] = self.op.value
        if self.expr is not None:
            d["expr"] = self.expr.to_json()
        d["args"] = [a.to_json() for a in self.args]
        if self.cond is not None:
            d["cond"] = self.cond.to_json()
        if self.dispatch is not None:
            d["dispatch"] = self.dispatch.to_json()
        d["cases"] = [
            ([c.to_json() if c else None for c in conds], lbl) for conds, lbl in self.cases
        ]
        return d

    @staticmethod
    def from_json(d: dict) -> "IrStmt":
        return IrStmt(
            sid=d["sid"],
            op=OpKind(d["op"]),
            targets=d.get("targets", []),
            expr=IrExpr.from_json(d["expr"]) if d.get("expr") else None,
            args=[IrExpr.from_json(a) for a in d.get("args", [])],
            label=d.get("label"),
            target_label=d.get("target_label"),
            targets_labels=d.get("targets_labels", []),
            cond=IrExpr.from_json(d["cond"]) if d.get("cond") else None,
            cases=[
                ([IrExpr.from_json(c) if c else None for c in conds], lbl)
                for conds, lbl in d.get("cases", [])
            ],
            file=d.get("file"),
            callee=d.get("callee"),
            text=d.get("text"),
            dispatch=IrExpr.from_json(d["dispatch"]) if d.get("dispatch") else None,
            span=d.get("span"),
            origin=d.get("origin", ""),
        )


@dataclass
class IrBlock:
    """A flat instruction list. Control flow is via labels, never via nesting,
    which keeps the CFG trivially constructible and the emitter dumb."""

    bid: str
    label: str
    stmts: list[IrStmt] = field(default_factory=list)
    exit_label: str = ""

    def to_json(self) -> dict:
        return {
            "bid": self.bid,
            "label": self.label,
            "exit_label": self.exit_label,
            "stmts": [s.to_json() for s in self.stmts],
        }

    @staticmethod
    def from_json(d: dict) -> "IrBlock":
        return IrBlock(
            bid=d["bid"],
            label=d["label"],
            exit_label=d.get("exit_label", ""),
            stmts=[IrStmt.from_json(s) for s in d.get("stmts", [])],
        )


@dataclass
class IrEdge:
    src: str  # block id
    dst: str  # block id or "" for exit
    kind: str  # fallthrough | conditional | call | return | goto
    label: str = ""


@dataclass
class IrFile:
    name: str
    organization: str = "SEQUENTIAL"
    record_vids: list[str] = field(default_factory=list)
    record_len: int = 80


@dataclass
class IrParam:
    """A CALL parameter: direction is 'in'/'out'/'inout'."""

    name: str
    vid: str
    direction: str = "inout"
    by_ref: bool = True


@dataclass
class IrSubprogram:
    """A paragraph promoted to a callable block, or an external program."""

    name: str
    kind: str  # paragraph | program | external
    blocks: list[IrBlock] = field(default_factory=list)
    params: list[IrParam] = field(default_factory=list)
    returns: Optional[str] = None
    entry_block: str = ""


@dataclass
class IrFunction:
    name: str
    kind: str = "main"  # main | paragraph
    blocks: list[IrBlock] = field(default_factory=list)
    params: list[IrParam] = field(default_factory=list)
    files: list[IrFile] = field(default_factory=list)
    returns: Optional[str] = None
    entry_block: str = ""
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    complexity: int = 0
    fan_in: int = 0
    fan_out: int = 0
    is_io: bool = False
    unsupported_count: int = 0


@dataclass
class IrProgram:
    name: str
    path: str = ""
    source_format: str = "free"
    dialect: str = "COBOL-85"
    vars: dict[str, IrVar] = field(default_factory=dict)
    functions: list[IrFunction] = field(default_factory=list)
    edges: list[IrEdge] = field(default_factory=list)
    globals: list[str] = field(default_factory=list)
    entry: str = "main"
    uses_files: bool = False
    unsupported: list[dict] = field(default_factory=list)
    source_lines: int = 0
    source_bytes: int = 0
    copy_books: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def var_by_name(self, name: str) -> Optional[IrVar]:
        for v in self.vars.values():
            if v.name == name:
                return v
        return None

    def function(self, name: str) -> Optional[IrFunction]:
        needle = name.strip().lower()
        for f in self.functions:
            if f.name.lower() == needle:
                return f
        return None

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "source_format": self.source_format,
            "dialect": self.dialect,
            "vars": {k: asdict(v) for k, v in self.vars.items()},
            "functions": [
                {
                    "name": f.name,
                    "kind": f.kind,
                    "blocks": [b.to_json() for b in f.blocks],
                    "params": [asdict(p) for p in f.params],
                    "files": [asdict(x) for x in f.files],
                    "returns": f.returns,
                    "entry_block": f.entry_block,
                    "callers": f.callers,
                    "callees": f.callees,
                    "complexity": f.complexity,
                    "fan_in": f.fan_in,
                    "fan_out": f.fan_out,
                    "is_io": f.is_io,
                    "unsupported_count": f.unsupported_count,
                }
                for f in self.functions
            ],
            "edges": [asdict(e) for e in self.edges],
            "globals": self.globals,
            "entry": self.entry,
            "uses_files": self.uses_files,
            "unsupported": self.unsupported,
            "source_lines": self.source_lines,
            "source_bytes": self.source_bytes,
            "copy_books": self.copy_books,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_json(d: dict) -> "IrProgram":
        prog = IrProgram(
            name=d["name"],
            path=d.get("path", ""),
            source_format=d.get("source_format", "free"),
            dialect=d.get("dialect", "COBOL-85"),
            vars={k: IrVar(**v) for k, v in d.get("vars", {}).items()},
            globals=d.get("globals", []),
            entry=d.get("entry", "main"),
            uses_files=d.get("uses_files", False),
            unsupported=d.get("unsupported", []),
            source_lines=d.get("source_lines", 0),
            source_bytes=d.get("source_bytes", 0),
            copy_books=d.get("copy_books", []),
            metadata=d.get("metadata", {}),
        )
        for f in d.get("functions", []):
            prog.functions.append(
                IrFunction(
                    name=f["name"],
                    kind=f.get("kind", "main"),
                    blocks=[IrBlock.from_json(b) for b in f.get("blocks", [])],
                    params=[IrParam(**p) for p in f.get("params", [])],
                    files=[IrFile(**x) for x in f.get("files", [])],
                    returns=f.get("returns"),
                    entry_block=f.get("entry_block", ""),
                    callers=f.get("callers", []),
                    callees=f.get("callees", []),
                    complexity=f.get("complexity", 0),
                    fan_in=f.get("fan_in", 0),
                    fan_out=f.get("fan_out", 0),
                    is_io=f.get("is_io", False),
                    unsupported_count=f.get("unsupported_count", 0),
                )
            )
        prog.edges = [IrEdge(**e) for e in d.get("edges", [])]
        return prog


@dataclass
class IrDataset:
    """A JCL dataset node, used to link JCL to programs."""

    name: str
    dcb: dict[str, str] = field(default_factory=dict)
    disp: Optional[str] = None
    recfm: str = ""
    lrecl: int = 80
    is_temp: bool = False


@dataclass
class IrJob:
    name: str
    path: str = ""
    steps: list[dict] = field(default_factory=list)
    datasets: list[IrDataset] = field(default_factory=list)

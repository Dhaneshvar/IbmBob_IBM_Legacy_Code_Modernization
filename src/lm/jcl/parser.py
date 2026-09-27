"""JCL parser.

JCL is card-oriented, which the model below reflects rather than fights: cards
keep their source line, columns, and raw text, and continuations (``-`` in
column 72/73) are joined into logical cards.

The one thing that matters for modernization is the JCL→dataset→program edge,
because that edge is what tells the dependency graph which COBOL programs a
dataset flows through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..cobol.ast_nodes import Span


class JclSyntaxError(Exception):
    def __init__(self, message: str, span: Span, path: str = ""):
        self.span = span
        self.path = path
        loc = f"{path}:{span.line}" if path else f"line {span.line}"
        super().__init__(f"{loc}: {message}")


@dataclass
class Card:
    """A logical JCL card (continuations already joined)."""

    name: str  # JOB, EXEC, DD, PROC, PGM, IF, INCLUDE
    operands: str  # text after the card name
    line: int
    raw: str = ""
    span: Optional[Span] = None
    label: str = ""

    def key(self, keyword: str) -> Optional[str]:
        """Return the value of ``KEYWORD=value`` from this card's operands."""
        m = re.search(
            rf"(?:^|[\s,]){re.escape(keyword)}\s*=\s*('[^']*'|\"[^\"]*\"|\([^)]*\)|[^,\s]+)",
            self.operands,
            re.IGNORECASE,
        )
        if not m:
            return None
        return _unquote(m.group(1))


@dataclass
class DdEntry:
    ddname: str
    dsn: Optional[str] = None
    dsn_list: list[str] = field(default_factory=list)  # for GDGs, 'base(+0)'
    disp: Optional[str] = None
    unit: Optional[str] = None
    space: Optional[str] = None
    dcb: dict[str, str] = field(default_factory=dict)
    inline_data: Optional[str] = None  # in-stream data after DD *
    sysin: bool = False
    card: Optional[Card] = None


@dataclass
class Step:
    name: str
    pgm: Optional[str] = None  # normalised program name
    pgm_raw: Optional[str] = None  # as written, e.g. IEBGENER
    proc: Optional[str] = None  # invoked PROC name
    parms: dict[str, str] = field(default_factory=dict)
    parm_text: str = ""
    dds: list[DdEntry] = field(default_factory=list)
    cond: Optional[str] = None
    region: Optional[str] = None
    class_: Optional[str] = None
    lines: tuple[int, int] = (0, 0)
    cards: list[Card] = field(default_factory=list)


@dataclass
class JobCard:
    name: str
    accounting: Optional[str] = None
    jobclass: Optional[str] = None
    programmer: Optional[str] = None
    region: Optional[str] = None
    notify: Optional[str] = None
    lines: tuple[int, int] = (0, 0)


@dataclass
class ProcStepTemplate:
    name: str
    pgm: Optional[str] = None
    dds: list[DdEntry] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)


@dataclass
class Proc:
    name: str
    steps: list[ProcStepTemplate] = field(default_factory=list)
    lines: tuple[int, int] = (0, 0)


@dataclass
class JclUnit:
    """A whole member: either a JOB (with steps) or a PROC definition."""

    path: str
    kind: str = "JOB"  # JOB | PROC
    job: Optional[JobCard] = None
    steps: list[Step] = field(default_factory=list)
    procs: list[Proc] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)

    def all_dds(self) -> list[DdEntry]:
        return [dd for s in self.steps for dd in s.dds]


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


_CARD_NAMES = {
    "JOB", "EXEC", "DD", "PROC", "PEND", "SET", "IF", "THEN", "ELSE",
    "ENDIF", "INCLUDE", "OUTPUT", "JCLLIB", "CNTL", "ENDCNTL",
}


def _strip_comment(raw: str) -> str:
    """Return the card with any trailing comment removed, and its comment."""
    # Card comments start with /* or in col 3, or the card is //*
    s = raw.rstrip()
    idx = s.find("/*")
    if idx >= 0:
        return s[:idx].rstrip()
    return s


def _classify(name: str) -> str:
    n = name.upper().strip()
    if n.startswith("//*"):
        return "COMMENT"
    if n in {"//", ""}:
        return "INLINE"
    if n == "ENDCNTL":
        return "ENDCNTL"
    return n.split(None, 1)[0] if n.split() else ""


def parse_jcl(text: str, path: str = "") -> JclUnit:
    """Parse JCL source into a :class:`JclUnit`."""
    unit = JclUnit(path=path, kind="JOB")
    lines = text.splitlines()
    logical: list[Card] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        start = i + 1
        if not raw.strip():
            i += 1
            continue
        if not raw.lstrip().startswith("//"):
            # Non-JCL noise (prologues, banners). Skip.
            i += 1
            continue
        body = raw.lstrip()[2:]
        comment = _strip_comment(body)
        if comment.strip().upper().startswith("*"):
            i += 1
            continue
        # Continuation: a - in the last two meaningful columns.
        while (
            len(raw) >= 73
            and raw[71:73] == "- "
            and i + 1 < len(lines)
            and lines[i + 1].lstrip().startswith("//")
        ):
            nxt = lines[i + 1].lstrip()[2:]
            comment = _strip_comment(nxt)
            body = comment[:71]
            raw = raw[:71] + " " + nxt.lstrip()[2:]
            i += 1
        body = _strip_comment(body)
        if not body.strip():
            i += 1
            continue
        stripped = body.strip()
        tokens = stripped.split(None, 2)
        if tokens[0].upper() in _CARD_NAMES:
            label = ""
            name = tokens[0].upper()
            operands = body.split(tokens[0], 1)[1].strip() if len(tokens) > 1 else ""
        elif len(tokens) >= 2 and tokens[1].upper() in _CARD_NAMES:
            label = tokens[0]
            name = tokens[1].upper()
            operands = tokens[2].strip() if len(tokens) > 2 else ""
        else:
            label = tokens[0]
            name = tokens[1].upper() if len(tokens) > 1 else tokens[0].upper()
            operands = tokens[2].strip() if len(tokens) > 2 else ""
        logical.append(
            Card(
                name=name,
                operands=operands,
                line=start,
                raw=raw.rstrip(),
                span=Span(start, i + 1, 3),
                label=label,
            )
        )
        i += 1

    unit.cards = logical
    _build_unit(unit, logical)
    return unit


def _build_unit(unit: JclUnit, cards: list[Card]) -> None:
    current_proc: Optional[Proc] = None
    current_procstep: Optional[ProcStepTemplate] = None
    current_step: Optional[Step] = None
    current_dd: Optional[DdEntry] = None
    mode: str = "JOB"  # JOB | PROCDEF
    collecting_inline: Optional[DdEntry] = None
    inline_lines: list[str] = []
    inline_start = 0

    idx = 0
    while idx < len(cards):
        card = cards[idx]
        name = card.name.upper()

        if collecting_inline is not None:
            if name == "INLINE" or name == "":
                inline_lines.append(card.operands)
                idx += 1
                continue
            if name == "*" or card.operands.strip() == "*":
                # A literal asterisk terminates in-stream data.
                collecting_inline.inline_data = "\n".join(inline_lines)
                collecting_inline = None
                _attach_dd(unit, current_step, current_procstep, collecting_inline, inline_start, card.line)
                continue
            if name == "ENDCNTL":
                collecting_inline.inline_data = "\n".join(inline_lines)
                _attach_dd(unit, current_step, current_procstep, collecting_inline, inline_start, card.line)
                collecting_inline = None
                idx += 1
                continue
            # Any other real card ends the data block.
            collecting_inline.inline_data = "\n".join(inline_lines)
            dd = collecting_inline
            collecting_inline = None
            _attach_dd(unit, current_step, current_procstep, dd, inline_start, card.line)
            # fall through to normal handling of this card

        if name == "JOB":
            if unit.job is None:
                unit.job = JobCard(
                    name=card.label or _first_word(card.operands, "(", "JOB"), lines=(card.line, card.line)
                )
            unit.job.accounting = card.key("ACCOUNTING") or unit.job.accounting
            unit.job.jobclass = card.key("CLASS") or unit.job.jobclass
            unit.job.programmer = card.key("PROGRAMMER") or unit.job.programmer
            unit.job.region = card.key("REGION") or unit.job.region
            unit.job.notify = card.key("NOTIFY") or unit.job.notify
            mode = "JOB"
            idx += 1
            continue

        if name == "PROC":
            # "//PROC" defines a procedure; "//        PROC NAME" inside a job
            # invokes one. A definition is followed by a bare "PROC name" card.
            if idx + 1 < len(cards) and cards[idx + 1].name.upper() == "PROC":
                procname = card.label or _first_word(cards[idx + 1].operands, "", "")
                current_proc = Proc(name=procname.upper(), lines=(card.line, card.line))
                unit.procs.append(current_proc)
                current_procstep = None
                mode = "PROCDEF"
                idx += 2
                continue
            idx += 1
            continue

        if name == "EXEC":
            operands = card.operands
            pgm_raw = card.key("PGM")
            proc_name = card.key("PROC")
            # "//EXEC  PGM=ORDPRCS,PARM=(A,B)" or "//EXEC  PROC=STEP1"
            if mode == "PROCDEF":
                if current_procstep is None and not pgm_raw and not proc_name:
                    pass
                step = ProcStepTemplate(name=card.label or proc_name or pgm_raw or "STEP")
                current_procstep = step
                if current_proc is not None:
                    current_proc.steps.append(step)
                    current_proc.lines = (current_proc.lines[0], card.line)
                else:
                    current_proc = Proc(name="ANON", lines=(card.line, card.line))
                    current_proc.steps.append(step)
                    unit.procs.append(current_proc)
                    mode = "PROCDEF"
                step.pgm = _normalise_pgm(pgm_raw)
                step.cards.append(card)
                _fill_step_common(step, card, proc_name, operands)
                current_dd = None
                idx += 1
                continue
            if current_step is not None:
                current_step.lines = (current_step.lines[0], card.line)
            step = Step(
                name=card.label or proc_name or pgm_raw or f"STEP{len(unit.steps) + 1}",
                pgm=_normalise_pgm(pgm_raw),
                pgm_raw=pgm_raw,
                proc=proc_name,
                lines=(card.line, card.line),
            )
            step.cards.append(card)
            _fill_step_common(step, card, proc_name, operands)
            unit.steps.append(step)
            current_step = step
            current_dd = None
            idx += 1
            continue

        if name == "DD":
            ddname = card.label or _first_word(card.operands, " ", "DDNAME")
            dd = DdEntry(ddname=ddname.upper(), card=card)
            dd.disp = card.key("DISP")
            dd.unit = card.key("UNIT")
            dd.space = card.key("SPACE")
            for kw in (
                "DSORG", "LRECL", "RECFM", "BLKSIZE", "KEYLEN", "KEYLOC",
                "DCB", "VOLUME", "LABEL", "RETAIN", "CREATE", "CATLG",
            ):
                v = card.key(kw)
                if v is not None:
                    dd.dcb[kw] = v
            dsn = card.key("DSN")
            if dsn:
                if "," in dsn:
                    dd.dsn_list = [_normalise_dsn(_unquote(p)) for p in dsn.split(",")]
                    dd.dsn = dd.dsn_list[0]
                else:
                    dd.dsn = _normalise_dsn(_unquote(dsn))
                    dd.dsn_list = [dd.dsn]
            if re.search(r"(?:^|\s)SYSIN\s*(?:=\s*\S+)?$|DD\s+SYSIN\s*$", card.raw, re.I):
                dd.sysin = True
            if card.operands.rstrip().upper().endswith("*") or card.operands.rstrip().endswith("=*"):
                collecting_inline = dd
                inline_lines = []
                inline_start = card.line
            _attach_dd(unit, current_step, current_procstep, dd, card.line, card.line)
            current_dd = dd
            idx += 1
            continue

        if name == "COND":
            if current_step is not None:
                current_step.cond = card.operands
            idx += 1
            continue

        if name in {"SET", "IF", "THEN", "ELSE", "ENDIF", "INCLUDE", "OUTPUT", "PEND", "ENDCNTL"}:
            idx += 1
            continue

        idx += 1


def _attach_dd(
    unit: JclUnit,
    step: Optional[Step],
    procstep: Optional[ProcStepTemplate],
    dd: Optional[DdEntry],
    start: int,
    end: int,
) -> None:
    if dd is None:
        return
    if procstep is not None:
        procstep.dds.append(dd)
        if procstep.pgm is None and dd.ddname == "SYSIN":
            procstep.pgm = None
    elif step is not None:
        step.dds.append(dd)


def _fill_step_common(
    step: object, card: Card, proc_name: Optional[str], operands: str
) -> None:
    region = card.key("REGION")
    if region:
        step.region = region
    cls = card.key("CLASS")
    if cls:
        step.class_ = cls
    if hasattr(step, "parms"):
        step.parm_text = operands
        for kw in ("PARM", "SYSIN", "REGION", "COND", "CLASS", "ACCOUNT", "TIME"):
            v = card.key(kw)
            if v is not None:
                step.parms[kw] = v


def _first_word(operands: str, stop_chars: str, fallback: str) -> str:
    """First whitespace-delimited token of ``operands``."""
    cleaned = operands.strip()
    if not cleaned:
        return fallback
    cleaned = cleaned.split("(")[0]
    cleaned = cleaned.split(",")[0]
    m = re.match(r"\S+", cleaned)
    return m.group(0) if m else fallback


_JCL_PROGRAM_PREFIXES = {"IEBGENER": "*IE", "SORT": "SORT", "PEND": "PEND"}


def _normalise_pgm(pgm: Optional[str]) -> Optional[str]:
    """``IEBGENER`` -> ``*IEBGENER`` so a JCL step lines up with a COBOL
    program that declares ``PROGRAM-ID. IEBGENER``."""
    if not pgm:
        return None
    p = _unquote(pgm).upper().strip()
    if p.startswith("*"):
        return p
    if p in {"IEBGENER"}:
        return "*IEBGENER"
    if p.startswith("EXEC") or p.startswith("PROC"):
        return None
    return p


def _normalise_dsn(dsn: str) -> str:
    d = dsn.strip().upper()
    if d.endswith(")"):
        base = d.split("(")[0]
        return base
    return d

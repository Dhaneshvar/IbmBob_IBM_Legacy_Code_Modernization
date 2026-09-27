"""COBOL tokenizer.

Handles both fixed-format (cols 1-6 sequence, col 7 indicator) and free-format
sources, and normalises them into a single token stream. Continuation lines are
folded here rather than in the parser, because the fixed-format continuation
rules interact with comment detection.

Word characters are alphanumeric plus hyphen. Hyphen is *always* an intra-word
character, which is why we never emit it as an operator; arithmetic minus is
recognised by the parser only when a token boundary is unambiguous. This is the
one genuinely surprising thing about COBOL and it is why hand-rolled tokenizers
break.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from .ast_nodes import Span


class TokKind(Enum):
    WORD = auto()
    NUMBER = auto()
    STRING = auto()
    FIGURATIVE = auto()
    OP = auto()
    PERIOD = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()
    COLON = auto()
    SEMI = auto()
    EOF = auto()

    @property
    def display(self) -> str:
        return self.name.lower()


@dataclass
class Token:
    kind: TokKind
    text: str
    span: Span
    #: for STRING tokens the decoded value, else None
    value: Optional[str] = None

    def is_word(self, *words: str) -> bool:
        return self.kind is TokKind.WORD and self.text in words

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Token({self.kind.display}, {self.text!r}, L{self.span.line})"


FIGURATIVES = {
    "ZERO",
    "ZEROS",
    "ZEROES",
    "SPACE",
    "SPACES",
    "HIGH-VALUE",
    "HIGH-VALUES",
    "LOW-VALUE",
    "LOW-VALUES",
    "QUOTE",
    "QUOTES",
    "ALL",
}

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_NUM_RE = re.compile(r"\d+(?:\.\d*)?|\.\d+")
_STR_RE = re.compile(r'"((?:[^"]|"")*)"')


class CobolSyntaxError(Exception):
    def __init__(self, message: str, span: Span, path: str = ""):
        self.span = span
        self.path = path
        loc = f"{path}:{span.line}" if path else f"line {span.line}"
        super().__init__(f"{loc}: {message}")


def _fold_fixed(lines: list[str], path: str) -> list[tuple[str, Span]]:
    """Strip sequence numbers and resolve continuations for fixed format."""
    out: list[tuple[str, Span]] = []
    pending: Optional[tuple[str, Span]] = None
    for idx, raw in enumerate(lines, start=1):
        if not raw:
            continue
        indicator = raw[6] if len(raw) > 6 else " "
        body = raw[7:] if len(raw) > 7 else ""
        span = Span(line=idx, end_line=idx, column=8 if body else 1)
        if indicator in ("*", "/"):
            continue
        if indicator == "-":
            # continuation: append to the previous logical line
            if pending is None:
                out.append((" ".join(body.split()), span))
            else:
                text, sp = pending
                merged = Span(sp.line, idx, sp.column)
                out[-1] = (text + " " + " ".join(body.split()), merged)
                pending = None
            continue
        text = " ".join(body.split())
        out.append((text, span))
        pending = None
    return out


def _fold_free(lines: list[str]) -> list[tuple[str, Span]]:
    out: list[tuple[str, Span]] = []
    for idx, raw in enumerate(lines, start=1):
        text = re.sub(r"\*>.*$", "", raw)
        if not text.strip():
            continue
        out.append((text, Span(line=idx, end_line=idx, column=1)))
    return out


def detect_format(text: str) -> str:
    """Fixed format if any line looks like it has a sequence number or a
    column-7 indicator. Free format is the default for short lines."""
    for raw in text.splitlines():
        # Do not treat leading indentation alone as fixed-format evidence.
        # Many free-format COBOL samples are indented, and misclassifying them
        # as fixed strips the first 7 columns from every line.
        if len(raw) > 6 and raw[6] in "*/-":
            return "fixed"
        if raw[:6].strip().isdigit():
            return "fixed"
    for raw in text.splitlines():
        if raw.lstrip().startswith("*>") or "*> " in raw:
            return "free"
    return "free"


def tokenize(text: str, path: str = "", source_format: str = "auto") -> list[Token]:
    """Return the token stream for ``text``, ending with a single EOF token."""
    if source_format == "auto":
        source_format = detect_format(text)
    lines = text.splitlines()
    logical = (
        _fold_fixed(lines, path)
        if source_format == "fixed"
        else _fold_free(lines)
    )

    tokens: list[Token] = []
    for line_text, span in logical:
        i = 0
        n = len(line_text)
        while i < n:
            ch = line_text[i]
            if ch in " \t":
                i += 1
                continue
            if ch == ".":
                # A period is a separator only if followed by whitespace or
                # end-of-line; otherwise it is part of a decimal literal,
                # which _NUM_RE already consumed greedily.
                tokens.append(Token(TokKind.PERIOD, ".", span))
                i += 1
                continue
            if ch == ",":
                tokens.append(Token(TokKind.COMMA, ",", span))
                i += 1
                continue
            if ch == "(":
                tokens.append(Token(TokKind.LPAREN, "(", span))
                i += 1
                continue
            if ch == ")":
                tokens.append(Token(TokKind.RPAREN, ")", span))
                i += 1
                continue
            if ch == ":":
                tokens.append(Token(TokKind.COLON, ":", span))
                i += 1
                continue
            if ch == ";":
                tokens.append(Token(TokKind.SEMI, ";", span))
                i += 1
                continue
            if ch == '"':
                m = _STR_RE.match(line_text, i)
                if not m:
                    raise CobolSyntaxError("unterminated string literal", span, path)
                raw = m.group(1)
                tokens.append(
                    Token(
                        TokKind.STRING,
                        raw,
                        span,
                        value=raw.replace('""', '"'),
                    )
                )
                i = m.end()
                continue
            if ch.isdigit() or (
                ch == "." and i + 1 < n and line_text[i + 1].isdigit()
            ):
                m = _NUM_RE.match(line_text, i)
                if m:
                    tokens.append(Token(TokKind.NUMBER, m.group(0), span))
                    i = m.end()
                    continue
            if ch.isalpha() or ch == "_":
                m = _WORD_RE.match(line_text, i)
                if m:
                    word = m.group(0)
                    upper = word.upper()
                    kind = (
                        TokKind.FIGURATIVE
                        if upper in FIGURATIVES
                        else TokKind.WORD
                    )
                    tokens.append(Token(kind, word, span))
                    i = m.end()
                    continue
            m = re.match(r"\*\*|<=|>=|<>|/=|[=<>+\-*/&]", line_text[i:])
            if m:
                tokens.append(Token(TokKind.OP, m.group(0), span))
                i += m.end()
                continue
            raise CobolSyntaxError(f"unexpected character {ch!r}", span, path)
    tokens.append(Token(TokKind.EOF, "<EOF>", Span(len(lines), len(lines))))
    return tokens

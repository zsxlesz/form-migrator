"""Small, fail-closed PL/SQL parser. A whole trigger must parse successfully.

No SQL execution, dynamic evaluation, regex-based partial translation, or LLM code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .common import decode_line_escapes


class Unsupported(Exception):
    pass


@dataclass
class Token:
    kind: str
    value: str
    pos: int


TOKEN = re.compile(r"(?P<space>\s+)|(?P<comment>--[^\r\n]*|/\*[\s\S]*?\*/)|(?P<string>'(?:''|[^'])*')|(?P<bind>:[A-Za-z][A-Za-z0-9_$#]*\.[A-Za-z][A-Za-z0-9_$#]*)|(?P<number>\d+(?:\.\d+)?)|(?P<id>[A-Za-z][A-Za-z0-9_$#]*)|(?P<op>:=|<=|>=|<>|!=|\|\||[;(),+*/=<>.-])")


def qualified(tokens: list[Token]) -> list[Token]:
    """PKG.PROC / OWNER.PKG.FUNC as one identifier (binds already carry their dot)."""
    folded, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        if token.kind == "id":
            parts = [token.value]
            while i + 2 < len(tokens) and tokens[i + 1].value == "." and tokens[i + 2].kind == "id":
                parts.append(tokens[i + 2].value); i += 2
            token = Token("id", ".".join(parts), token.pos)
        folded.append(token); i += 1
    return folded


def tokenize(source: str) -> list[Token]:
    # Forms2XML leaves line breaks as literal "&#10;"; without decoding every
    # multi-line trigger, WHERE and ORDER BY would fail on the first "&".
    source = decode_line_escapes(source)
    if len(source) > 100_000:
        raise Unsupported("A trigger túl nagy a beépített parserhez.")
    result = []
    pos = 0
    while pos < len(source):
        match = TOKEN.match(source, pos)
        if not match:
            raise Unsupported(f"Nem támogatott token a(z) {pos}. karakternél: {source[pos:pos+25]!r}")
        kind = match.lastgroup
        value = match.group()
        if kind not in {"space", "comment"}:
            result.append(Token(kind, value.upper() if kind in {"id", "bind"} else value, pos))
        pos = match.end()
    result.append(Token("eof", "<EOF>", pos))
    return result


class Parser:
    def __init__(self, source: str):
        self.tokens = qualified(tokenize(source))
        self.i = 0
        self.depth = 0

    def peek(self, value: str) -> bool:
        return self.tokens[self.i].value == value

    def take(self) -> Token:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def accept(self, value: str) -> bool:
        if self.peek(value):
            self.i += 1
            return True
        return False

    def need(self, value: str) -> None:
        if not self.accept(value):
            token = self.tokens[self.i]
            raise Unsupported(f"Várt token: {value}; kapott: {token.value}, pozíció: {token.pos}.")

    def parse(self) -> list[dict]:
        body = self.statements({"<EOF>"})
        self.need("<EOF>")
        return body

    def statements(self, stop: set[str]) -> list[dict]:
        self.depth += 1
        if self.depth > 32:
            raise Unsupported("Túl mély PL/SQL beágyazás.")
        body = []
        while self.tokens[self.i].value not in stop:
            body.append(self.statement())
            if len(body) > 1000:
                raise Unsupported("Túl sok utasítás.")
        self.depth -= 1
        return body

    def statement(self) -> dict:
        if self.accept("BEGIN"):
            body = self.statements({"END", "EXCEPTION", "<EOF>"})
            handlers = []
            if self.accept("EXCEPTION"):
                # Kept as data: only catalogued framework handlers may be dropped
                # later (rules.strip_framework); flatten() rejects every other one.
                while self.accept("WHEN"):
                    names = [self.take().value]
                    while self.accept("OR"):
                        names.append(self.take().value)
                    self.need("THEN")
                    handlers.append({"names": names, "body": self.statements({"WHEN", "END", "<EOF>"})})
                if not handlers:
                    raise Unsupported("Üres EXCEPTION szakasz.")
            self.need("END")
            self.need(";")
            return {"op": "block", "body": body, "handlers": handlers}
        if self.accept("NULL"):
            self.need(";")
            return {"op": "noop"}
        if self.accept("IF"):
            branches = []
            while True:
                condition = self.expression()
                self.need("THEN")
                branches.append({"condition": condition, "body": self.statements({"ELSIF", "ELSE", "END", "<EOF>"})})
                if not self.accept("ELSIF"):
                    break
            otherwise = self.statements({"END", "<EOF>"}) if self.accept("ELSE") else []
            self.need("END")
            self.need("IF")
            self.need(";")
            return {"op": "if", "branches": branches, "else": otherwise}
        token = self.take()
        if token.kind == "bind":
            self.need(":=")
            value = self.expression()
            self.need(";")
            return {"op": "assign", "target": token.value[1:], "value": value}
        if token.value == "RAISE":
            self.need("FORM_TRIGGER_FAILURE")
            self.need(";")
            return {"op": "abort"}
        if token.kind != "id":
            raise Unsupported(f"Nem támogatott utasítás: {token.value}")
        args = []
        if self.accept("("):
            if not self.peek(")"):
                args.append(self.expression())
                while self.accept(","):
                    args.append(self.expression())
            self.need(")")
        self.need(";")
        return {"op": "call", "name": token.value, "args": args}

    def expression(self, minimum: int = 0) -> dict:
        token = self.take()
        if token.value in {"NOT", "+", "-"}:
            left = {"op": "unary", "operator": token.value, "value": self.expression(25 if token.value == "NOT" else 60)}
        elif token.value == "(":
            left = self.expression()
            self.need(")")
        elif token.kind == "bind":
            left = {"op": "ref", "name": token.value[1:]}
        elif token.kind == "string":
            left = {"op": "literal", "type": "text", "value": token.value[1:-1].replace("''", "'") or None}
        elif token.kind == "number":
            left = {"op": "literal", "type": "number", "value": token.value}
        elif token.value in {"NULL", "TRUE", "FALSE"}:
            left = {"op": "literal", "type": "null" if token.value == "NULL" else "boolean", "value": {"NULL": None, "TRUE": True, "FALSE": False}[token.value]}
        elif token.kind == "id":
            if self.accept("("):
                args = []
                if not self.peek(")"):
                    args.append(self.expression())
                    while self.accept(","):
                        args.append(self.expression())
                self.need(")")
                left = {"op": "function", "name": token.value, "args": args}
            else:
                left = {"op": "symbol", "name": token.value}
        else:
            raise Unsupported(f"Nem támogatott kifejezés: {token.value}")
        precedence = {"OR": 10, "AND": 20, "=": 30, "<>": 30, "!=": 30, "<": 30, ">": 30, "<=": 30, ">=": 30, "IS": 30, "||": 40, "+": 40, "-": 40, "*": 50, "/": 50}
        while precedence.get(self.tokens[self.i].value, -1) >= minimum:
            operator = self.take().value
            if operator == "IS":
                negated = self.accept("NOT")
                self.need("NULL")
                left = {"op": "is_null", "value": left, "negated": negated}
                continue
            right = self.expression(precedence[operator] + 1)
            left = {"op": "binary", "operator": operator, "left": left, "right": right}
        return left


def parse(source: str) -> list[dict]:
    try:
        return Parser(source).parse()
    except (RecursionError, IndexError) as exc:
        raise Unsupported("Hibás vagy túl mély PL/SQL.") from exc


def flatten(body: list[dict]):
    for node in body:
        if node["op"] == "block":
            if node.get("handlers"):
                names = ", ".join(n for h in node["handlers"] for n in h["names"])
                raise Unsupported(f"Saját kivételkezelő (EXCEPTION WHEN {names}): a hibaágat külön kell átültetni.")
            yield from flatten(node["body"])
        else:
            yield node

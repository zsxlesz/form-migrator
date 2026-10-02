"""COMMIT_FORM in the middle of a button's code: a commit point the request stops at and resumes after.

Forms commits the screen where the code says COMMIT_FORM and then runs the rest of the code. The
web screen commits with its own endpoint, so the anonymous block stops there: it returns the item
values of that moment and a NIVA_COMMIT command. The screen saves (the commit endpoint runs the code
up to the point again, in the commit's transaction, and checks that it arrived at the same state),
then calls the button once more with NIVA.RESUME = the point. In that run every statement before
the point is skipped and the branches leading to it are taken without evaluating their conditions
again, so the code continues exactly after COMMIT_FORM, with the saved values of the screen.

    IF ank_jog.irhat THEN                  IF (niva_resume IN (1) OR (niva_resume NOT IN (1) AND (ank_jog.irhat))) THEN
        COMMIT_FORM;               ->          niva_commit_form(1);
        ank_naplo.mentes(:B.ID);               ank_naplo.mentes(nv_...);
    END IF;                                END IF;

Statements in front of a point get IF niva_resume NOT IN (...) THEN ... END IF. Refused (manual
work, with the reason): a point in a loop, a CASE statement or an exception handler; a local
variable set before the point and read after it (the second request starts the block again); a
local package with state; GOTO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .plsql import Unsupported

PLACEHOLDER = 'niva_commit_form(NIVA_POINT)'
STOP_LIST = {'END', 'ELSE', 'ELSIF', 'EXCEPTION', 'WHEN'}


@dataclass
class Node:
    kind: str  # simple | opaque | if | block
    start: int  # token index
    end: int  # token index of the closing ';'
    branches: list = field(default_factory=list)  # if: [(cond_start, cond_end, [nodes])]; else -> cond None
    body: list = field(default_factory=list)  # block statements
    handlers: list = field(default_factory=list)  # block: [[nodes] per WHEN]
    declare: tuple | None = None  # block: (first, last) token index of the declarations
    exception_at: int | None = None  # block: token index of EXCEPTION


class Parser:
    def __init__(self, sig):
        self.sig = sig

    def word(self, i):
        return self.sig[i][1].upper() if i < len(self.sig) and self.sig[i][0] == 'ident' else (
            self.sig[i][1] if i < len(self.sig) else '')

    def fail(self, i, what):
        near = ' '.join(t[1] for t in self.sig[max(0, i - 2):i + 3])
        raise Unsupported('COMMIT_FORM a kód közepén: a kód szerkezete nem bontható (' + what + ': ' + near + ').')

    def statements(self, i, stop):
        nodes = []
        while i < len(self.sig) and self.word(i) not in stop:
            node, i = self.statement(i)
            nodes.append(node)
        if i >= len(self.sig):
            self.fail(i - 1, 'lezáratlan utasításlista')
        return nodes, i

    def statement(self, i):
        word = self.word(i)
        if word == '<' and self.word(i + 1) == '<':
            close = i + 2
            while close < len(self.sig) and not (self.word(close) == '>' and self.word(close + 1) == '>'):
                close += 1
            node, end = self.statement(close + 2)
            node.start = i
            return node, end
        if word == 'IF':
            return self.if_statement(i)
        if word in {'BEGIN', 'DECLARE'}:
            return self.block(i)
        if word == 'GOTO':
            raise Unsupported('COMMIT_FORM a kód közepén: GOTO mellett a folytatási pont nem követhető.')
        return self.opaque(i)

    def opaque(self, i):
        """A statement up to its ';', loops and CASE statements included (no point may be inside)."""
        stack, depth, k = [], 0, i
        kind = 'simple'
        while k < len(self.sig):
            word = self.word(k)
            if word in {'BEGIN', 'IF', 'LOOP', 'CASE'}:
                stack.append(word)
                if word == 'LOOP' or (word == 'CASE' and k == i):
                    kind = 'opaque'
            elif word == 'END':
                if not stack:
                    self.fail(k, 'felesleges END')
                stack.pop()
                if self.word(k + 1) in {'IF', 'LOOP', 'CASE'}:
                    k += 1
            elif word == '(':
                depth += 1
            elif word == ')':
                depth -= 1
            elif word == ';' and depth == 0 and not stack:
                return Node(kind, i, k), k + 1
            k += 1
        self.fail(i, 'lezáratlan utasítás')

    def condition(self, i, until):
        """The expression from sig[i] to its THEN (a CASE expression inside it has THENs too)."""
        cases, k = 0, i
        while k < len(self.sig):
            word = self.word(k)
            if word == 'CASE':
                cases += 1
            elif word == 'END' and cases:
                cases -= 1
            elif word == until and not cases:
                return k
            k += 1
        self.fail(i, 'THEN nélküli feltétel')

    def if_statement(self, i):
        node = Node('if', i, i)
        keyword = i  # IF or ELSIF
        while True:
            then = self.condition(keyword + 1, 'THEN')
            nodes, k = self.statements(then + 1, {'ELSIF', 'ELSE', 'END'})
            node.branches.append((keyword + 1, then - 1, nodes))
            word = self.word(k)
            if word == 'ELSIF':
                keyword = k
                continue
            if word == 'ELSE':
                nodes, k = self.statements(k + 1, {'END'})
                node.branches.append((None, None, nodes))
            if self.word(k) != 'END' or self.word(k + 1) != 'IF' or self.word(k + 2) != ';':
                self.fail(k, 'END IF hiányzik')
            node.end = k + 2
            return node, k + 3

    def block(self, i):
        from .libraries import declarations
        node = Node('block', i, i)
        k = i
        if self.word(i) == 'DECLARE':
            try:
                k = declarations(self.sig, i + 1)
            except Unsupported as exc:
                self.fail(i, str(exc))
            node.declare = (i + 1, k - 1)
            if self.word(k) != 'BEGIN':
                self.fail(k, 'DECLARE után BEGIN hiányzik')
        node.body, k = self.statements(k + 1, {'END', 'EXCEPTION'})
        if self.word(k) == 'EXCEPTION':
            node.exception_at = k
            k += 1
            while self.word(k) == 'WHEN':
                then = self.condition(k + 1, 'THEN')
                nodes, k = self.statements(then + 1, {'WHEN', 'END'})
                node.handlers.append(nodes)
        if self.word(k) != 'END':
            self.fail(k, 'END hiányzik')
        k += 1
        if self.word(k) != ';':
            k += 1  # END label
        if self.word(k) != ';':
            self.fail(k, 'END utáni ; hiányzik')
        node.end = k
        return node, k + 1


def walk(nodes, path, found, sig, text):
    """Points in program order with their path: [(list, index, node), ...]."""
    for index, node in enumerate(nodes):
        here = path + [(id(nodes), index, node)]
        segment = text[sig[node.start][2]:sig[node.end][3]]
        if PLACEHOLDER not in segment:
            continue
        if node.kind == 'simple':
            if segment.strip().rstrip(';').strip() != PLACEHOLDER:
                raise Unsupported('COMMIT_FORM a kód közepén: kifejezésben vagy összetett utasításban.')
            found.append(here)
        elif node.kind == 'opaque':
            raise Unsupported('COMMIT_FORM a kód közepén: ciklusban vagy CASE utasításban a folytatási pont nem követhető.')
        elif node.kind == 'if':
            for _, _, branch in node.branches:
                walk(branch, here, found, sig, text)
        else:
            for handler in node.handlers:
                if any(PLACEHOLDER in text[sig[n.start][2]:sig[n.end][3]] for n in handler):
                    raise Unsupported('COMMIT_FORM a kód közepén: kivételkezelőben a folytatási pont nem követhető.')
            walk(node.body, here, found, sig, text)


def declared_names(sig, first, last):
    """Variables and cursors of a declaration section (constants, exceptions, types, subprograms excluded)."""
    from .libraries import statement_end, subprogram_end
    names, i = [], first
    while i <= last:
        word = sig[i][1].upper() if sig[i][0] == 'ident' else sig[i][1]
        if word in {'PROCEDURE', 'FUNCTION'}:
            i = subprogram_end(sig, i) + 1
            continue
        end = statement_end(sig, i)
        words = [t[1].upper() for t in sig[i:end] if t[0] == 'ident']
        if word == 'CURSOR' and len(words) > 1:
            names.append(words[1])
        elif word not in {'TYPE', 'SUBTYPE', 'PRAGMA'} and len(words) > 1 and words[1] not in {'CONSTANT', 'EXCEPTION'}:
            names.append(words[0])
        i = end + 1
    return names


def transform(body: str) -> tuple[str, int]:
    """The body with numbered commit points and resume guards; (text, number of points)."""
    from .plsql_passthrough import scan, significant
    sig = significant(scan(body))
    parser = Parser(sig)
    if parser.word(0) not in {'BEGIN', 'DECLARE'}:
        raise Unsupported('COMMIT_FORM a kód közepén: a kód nem blokk.')
    root, after = parser.block(0)
    if after != len(sig):
        parser.fail(after, 'a blokk után további kód áll')
    points, top = [], [root]
    walk(top, [], points, sig, body)
    if not points:
        return body, 0
    number = {id(path[-1][2]): k + 1 for k, path in enumerate(points)}
    edits = []  # (start offset, end offset, text, order)

    # Statements in front of a point (in each list on its path): skipped when resuming at that point.
    preceding = {}
    for path in points:
        point = number[id(path[-1][2])]
        for list_id, index, node in path:
            preceding.setdefault(list_id, {}).setdefault(index, set()).add(point)
    lists = {}

    def collect(nodes):
        lists[id(nodes)] = nodes
        for node in nodes:
            for _, _, branch in node.branches:
                collect(branch)
            if node.kind == 'block':
                collect(node.body)
                for handler in node.handlers:
                    collect(handler)
    collect(top)
    for list_id, positions in preceding.items():
        nodes = lists[list_id]
        for index, node in enumerate(nodes):
            skip = sorted({p for later, ps in positions.items() if later > index for p in ps})
            if skip:
                start, end = sig[node.start][2], sig[node.end][3]
                line = body[body.rfind('\n', 0, start) + 1:start]
                margin = line if not line.strip() else ''
                edits.append((start, start, 'IF niva_resume NOT IN (' + ', '.join(map(str, skip)) + ') THEN\n' + margin, 1))
                edits.append((end, end, '\n' + margin + 'END IF;', 0))

    for path in points:
        for _, _, node in path:
            if node.kind == 'if' and not getattr(node, 'done', False):
                node.done = True
                inside = lambda nodes: sorted(number[id(p[-1][2])] for p in points if any(n is x for _, _, x in p for n in nodes))
                every = inside([node])
                for cond_start, cond_end, branch in node.branches:
                    if cond_start is None:
                        continue
                    own = inside(branch)
                    start, end = sig[cond_start][2], sig[cond_end][3]
                    condition = body[start:end]
                    others = 'niva_resume NOT IN (' + ', '.join(map(str, every)) + ') AND (' + condition + ')'
                    new = ('(niva_resume IN (' + ', '.join(map(str, own)) + ') OR (' + others + '))') if own else '(' + others + ')'
                    edits.append((start, end, new, 2))
            elif node.kind == 'block' and not getattr(node, 'done', False):
                node.done = True
                if node.exception_at is not None:
                    at = sig[node.exception_at][3]
                    edits.append((at, at, '\n  WHEN niva_commit_pending THEN\n    RAISE;', 2))
                if node.declare:
                    names = declared_names(sig, *node.declare)
                    for path_point in points:
                        if not any(x is node for _, _, x in path_point):
                            continue
                        stop = path_point[-1][2]
                        before = {t[1].upper() for t in sig[node.declare[1] + 1:stop.start] if t[0] == 'ident'}
                        later = {t[1].upper() for t in sig[stop.end + 1:node.end] if t[0] == 'ident'}
                        for name in names:
                            if name in before and name in later:
                                raise Unsupported('COMMIT_FORM a kód közepén: a(z) ' + name + ' helyi változó a mentés előtt '
                                                  'kaphat értéket és utána is használt; a folytatás új kérésben indul.')
    for path in points:
        node = path[-1][2]
        start, end = sig[node.start][2], sig[node.end][2]
        edits.append((start, end, 'niva_commit_form(' + str(number[id(node)]) + ')', 2))
    out = body
    for start, end, text, order in sorted(edits, key=lambda e: (e[0], e[1], e[3]), reverse=True):
        out = out[:start] + text + out[end:]
    return out, len(points)


def state_expression(binds, var) -> str:
    """The item values at the point, as one text: the commit endpoint checks it arrived at the same state."""
    parts = []
    for b in binds:
        if b['parameter'] and b['block'] != 'GLOBAL':
            continue
        v = var(b['source'])
        if b['type'] == 'number':
            parts.append(f"TO_CHAR({v}, 'TM9', 'NLS_NUMERIC_CHARACTERS=''.,''')")
        elif b['type'] == 'datetime':
            parts.append(f"TO_CHAR({v}, 'YYYYMMDDHH24MISS')")
        else:
            parts.append(v)
    return ' || CHR(29) || '.join(parts) if parts else 'NULL'


def declarations(resume_var: str, mode_var: str, state: str) -> tuple[list[str], list[str]]:
    """(variables, subprograms) of a block with commit points."""
    items = [f'  niva_resume PLS_INTEGER := NVL(TO_NUMBER({resume_var}), 0);',
             f'  niva_commit_mode VARCHAR2(10) := {mode_var};',
             '  niva_commit_at PLS_INTEGER;',
             '  niva_commit_state VARCHAR2(32767);',
             '  niva_commit_pending EXCEPTION;']
    subprograms = ['  PROCEDURE niva_commit_form(p_point PLS_INTEGER) IS',
                   '  BEGIN',
                   '    IF p_point <> niva_resume THEN',
                   '      niva_commit_at := p_point;',
                   f'      niva_commit_state := SUBSTR({state}, 1, 32000);',
                   '      RAISE niva_commit_pending;',
                   '    END IF;',
                   '  END;']
    return items, subprograms


HANDLER = ("  WHEN niva_commit_pending THEN\n"
           "    IF niva_commit_mode IS NULL THEN\n"
           "      ROLLBACK TO SAVEPOINT niva_start;\n"
           "    END IF;\n"
           "    niva_cmd('NIVA_COMMIT', TO_CHAR(niva_commit_at), niva_commit_state);")


def placeholder_count(text: str) -> int:
    return len(re.findall(re.escape(PLACEHOLDER), text))

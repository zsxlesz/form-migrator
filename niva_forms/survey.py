"""Felmérés: why the generated endpoints stay disabled, over many forms, in a shareable form.

The outputs of a batch already hold every reason (analysis/form.ir.json, backend-plan.json).
The survey joins them per cause (issue code + message template) and counts

- the endpoints a cause disables, and how many it disables alone ("egyedüli ok"): fix that
  one rule and exactly these endpoints open, so the causes are ranked by what a fix frees;
- the triggers waiting for translation, with the Forms constructs they contain;
- the queries (WHERE, LOV record groups) behind disabled reads.

Each cause carries a few code shapes: the trigger, WHERE clause or LOV query with names,
literals, numbers and comments replaced by placeholders (N1, :B1.I2, '…'). The keywords,
Forms built-ins and the structure stay, so the missing translator rule is visible while
FELMERES_HU.md and felmeres.json can be shared outside the company. names=True keeps the
real names for local work.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import html
from pathlib import Path
import re

from . import __version__
from .common import write_json
from .discovery import FORMS_BUILTINS
from .portfolio import TRIGGER_ID, load, normalize
from .rules import BLOCKING_SCOPES, WRITE_APPROVAL

SURVEY_VERSION = 1
MAX_EXAMPLES = 3
MAX_LINES = 40
MAX_CHARS = 2400

PLSQL_WORDS = frozenset('''
ALL AND ANY AS ASC BEGIN BETWEEN BINARY_INTEGER BODY BOOLEAN BULK BY CASE CHAR CLOSE COLLECT COMMIT CONNECT
CONSTANT CONTINUE CROSS CURSOR DATE DECLARE DEFAULT DELETE DESC DISTINCT ELSE ELSIF END EXCEPTION EXECUTE EXISTS
EXIT FALSE FETCH FIRST FOR FORALL FOUND FROM FULL FUNCTION GOTO GROUP HAVING IF IMMEDIATE IN INDEX INNER INSERT
INTEGER INTERSECT INTO IS ISOPEN JOIN LAST LEFT LIKE LOOP MERGE MINUS NATURAL NEXT NOCOPY NOT NOTFOUND NOWAIT
NULL NULLS NUMBER OF OFFSET ON ONLY OPEN OR ORDER OTHERS OUT OUTER PACKAGE PLS_INTEGER PRAGMA PRIOR PROCEDURE
RAISE RECORD RETURN RETURNING REVERSE RIGHT ROLLBACK ROW ROWCOUNT ROWID ROWS ROWTYPE SAVEPOINT SELECT SET START
SUBTYPE TABLE THEN TO TRUE TYPE UNION UNIQUE UPDATE USING VALUES VARCHAR VARCHAR2 WHEN WHERE WHILE WITH
'''.split())
ORACLE_WORDS = frozenset('''
ABS ADD_MONTHS ASCII AVG CAST CEIL CHR COALESCE CONCAT COUNT DECODE DUAL EXTRACT FLOOR GREATEST INITCAP INSTR
LAST_DAY LEAST LENGTH LEVEL LOWER LPAD LTRIM MAX MIN MOD MONTHS_BETWEEN NEXT_DAY NULLIF NVL NVL2 POWER
REGEXP_INSTR REGEXP_LIKE REGEXP_REPLACE REGEXP_SUBSTR REPLACE ROUND ROWNUM RPAD RTRIM SIGN SQLCODE SQLERRM SUBSTR
SUM SYSDATE SYSTIMESTAMP TO_CHAR TO_DATE TO_NUMBER TO_TIMESTAMP TRANSLATE TRIM TRUNC UID UPPER USER
DUP_VAL_ON_INDEX FORM_TRIGGER_FAILURE INVALID_NUMBER NO_DATA_FOUND TOO_MANY_ROWS VALUE_ERROR ZERO_DIVIDE
FORM_SUCCESS FORM_FAILURE FORM_FATAL ERROR_CODE ERROR_TEXT ERROR_TYPE DBMS_ERROR_CODE DBMS_ERROR_TEXT
MESSAGE_CODE MESSAGE_TEXT MESSAGE_TYPE ID_NULL CHECKBOX_CHECKED
'''.split())
# Forms property names and values passed to the built-ins (SET_BLOCK_PROPERTY(…, DEFAULT_WHERE, …)).
FORMS_CONSTANTS = frozenset('''
PROPERTY_TRUE PROPERTY_FALSE PROPERTY_ON PROPERTY_OFF DEFAULT_WHERE ONETIME_WHERE ORDER_BY QUERY_DATA_SOURCE_NAME
QUERY_DATA_SOURCE_TYPE QUERY_DATA_SOURCE_COLUMNS QUERY_DATA_SOURCE_ARGUMENTS DML_DATA_TARGET_NAME
DML_DATA_TARGET_TYPE DML_ARGUMENTS QUERY_ALLOWED INSERT_ALLOWED UPDATE_ALLOWED DELETE_ALLOWED ENABLED VISIBLE
DISPLAYED ENTERABLE NAVIGABLE REQUIRED UPDATEABLE INSERTABLE QUERYABLE UPDATE_NULL LOV_NAME VALIDATE_FROM_LIST
LABEL PROMPT_TEXT HINT_TEXT TOOLTIP_TEXT BACKGROUND_COLOR FOREGROUND_COLOR VISUAL_ATTRIBUTE
CURRENT_RECORD_ATTRIBUTE ITEM_IS_VALID WIDTH HEIGHT X_POS Y_POS POSITION TITLE WINDOW_STATE MAXIMIZE MINIMIZE
CURSOR_STYLE TOPMOST_TAB_PAGE NO_VALIDATE DO_VALIDATE ASK_COMMIT NO_COMMIT FULL_ROLLBACK NO_ROLLBACK HIDE NO_HIDE
REPLACE NO_REPLACE ACTIVATE NO_ACTIVATE SESSION NO_SESSION QUERY_ONLY TEXT_PARAMETER DATA_PARAMETER
ALERT_BUTTON1 ALERT_BUTTON2 ALERT_BUTTON3 RECORD_STATUS BLOCK_STATUS FORM_STATUS QUERY_HITS
'''.split())
# Oracle and Forms packages, and the words of the generator's own messages that name a construct.
KEEP_PREFIXES = ('DBMS_', 'UTL_', 'SYS.', 'STANDARD.', 'WEB.', 'TOOL_ENV.', 'OLE2.', 'TEXT_IO.', 'CLIENT_',
                 'FORMS_', 'FTREE.', 'HOST', 'QMS$', 'CG$')
MESSAGE_WORDS = frozenset('''
API CRUD DML DTO HTTP JSON LOV MMB OLB PK SQL UI XML WHERE ORDER BY MODULE_REVIEWED DEFAULT_WHERE ONETIME_WHERE
ORDER_BY QUERY_DATA_SOURCE_NAME QUERY_DATA_SOURCE_TYPE QUERY_DATA_SOURCE_COLUMNS QUERY_DATA_SOURCE_ARGUMENTS
DML_DATA_TARGET_NAME DML_DATA_TARGET_TYPE DML_ARGUMENTS QUERY_ALLOWED INSERT_ALLOWED UPDATE_ALLOWED
DELETE_ALLOWED ENTERABLE VISIBLE ENABLED REQUIRED NAVIGABLE UPDATEABLE INSERT_ALLOWED SYSTEM GLOBAL PARAMETER
NEXTVAL CURRVAL RECORDGROUPQUERY TODO
'''.split())

TOKEN = re.compile(r"""
    (?P<comment>--[^\n]*|/\*.*?(?:\*/|$))
  | (?P<string>[nN]?'(?:[^']|'')*'?)
  | (?P<number>\b\d+(?:\.\d+)?\b)
  | (?P<bind>:[A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)?)
  | (?P<name>"[^"\n]+"|[A-Za-z_][\w$#]*(?:\.(?:"[^"\n]+"|[A-Za-z_][\w$#]*))*)
  | (?P<other>.)
""", re.S | re.X)
SQL_LIKE = re.compile(r"\b(?:select|where|and|or|order\s+by|like|in|is\s+null|from)\b|[=<>]|:\w", re.I)


def kept(word: str) -> bool:
    upper = word.upper()
    return (upper in PLSQL_WORDS or upper in ORACLE_WORDS or upper in FORMS_BUILTINS or upper in FORMS_CONSTANTS
            or upper.startswith(KEEP_PREFIXES))


class Shaper:
    """Code shape: placeholders instead of names, literals and comments, numbered per snippet."""

    def __init__(self, names: bool = False):
        self.names = names
        self.aliases = {}
        self.counts = Counter()

    def alias(self, name: str, kind: str) -> str:
        key = (kind, name.upper())
        if key not in self.aliases:
            self.counts[kind] += 1
            self.aliases[key] = kind + str(self.counts[kind])
        return self.aliases[key]

    def word(self, word: str) -> str:
        if kept(word):
            return word.upper()
        return '.'.join(self.alias(part.strip('"'), 'N') for part in word.split('.'))

    def bind(self, bind: str) -> str:
        parts = bind[1:].upper().split('.')
        if parts[0] == 'SYSTEM':
            return ':' + '.'.join(parts)
        if parts[0] in ('GLOBAL', 'PARAMETER') and len(parts) == 2:
            return ':' + parts[0] + '.' + self.alias(parts[1], parts[0][0])
        if len(parts) == 2:
            return ':' + self.alias(parts[0], 'B') + '.' + self.alias(parts[1], 'I')
        return ':' + self.alias(parts[0], 'V')

    def string(self, literal: str) -> str:
        body = literal[literal.index("'") + 1:-1 if len(literal) > 1 and literal.endswith("'") else None]
        if not SQL_LIKE.search(body):
            return "'…'"  # a message or a constant: its text is not needed for the shape
        return "'" + self.tokens(body.replace("''", "'")).replace("'", "''") + "'"  # SQL text built in a string

    def tokens(self, text: str) -> str:
        out = []
        for match in TOKEN.finditer(text):
            kind, value = match.lastgroup, match.group()
            if kind == 'comment':
                out.append('\n' if '\n' in value else '')
            elif kind == 'string':
                out.append(self.string(value))
            elif kind == 'number':
                out.append(value if len(value) <= 3 else 'N')
            elif kind == 'bind':
                out.append(self.bind(value))
            elif kind == 'name':
                out.append(self.word(value))
            else:
                out.append(value)
        return ''.join(out)

    def shape(self, text: str) -> str:
        text = html.unescape(text or '').replace('\r\n', '\n').replace('\r', '\n')
        if not self.names:
            text = self.tokens(text)
        lines = [line.rstrip().replace('\t', '    ') for line in text.split('\n')]
        lines = [line for index, line in enumerate(lines) if line or (index and lines[index - 1])]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        indent = min((len(line) - len(line.lstrip()) for line in lines if line), default=0)
        lines = [line[indent:] for line in lines]
        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES] + [f'-- … (+{len(lines) - MAX_LINES} sor)']
        result = '\n'.join(lines)
        return result if len(result) <= MAX_CHARS else result[:MAX_CHARS] + '\n-- … (rövidítve)'


def constructs(text: str) -> set[str]:
    """Forms built-ins, system variables, SQL statements and calls in one piece of PL/SQL."""
    found = set()
    tokens = [(m.lastgroup, m.group()) for m in TOKEN.finditer(html.unescape(text or ''))
              if m.lastgroup not in ('comment',) and not (m.lastgroup == 'other' and m.group().isspace())]
    words = [value.upper() for kind, value in tokens if kind == 'name']
    for index, (kind, value) in enumerate(tokens):
        upper = value.upper()
        following = tokens[index + 1][1] if index + 1 < len(tokens) else ''
        if kind == 'bind':
            parts = upper[1:].split('.')
            found.add(':SYSTEM.' + parts[1] if parts[0] == 'SYSTEM' and len(parts) > 1
                      else ':' + parts[0] + '.*' if parts[0] in ('GLOBAL', 'PARAMETER') else ':blokk.mező')
        elif kind == 'name':
            if upper in FORMS_BUILTINS:
                found.add(upper)
            elif upper in ('INSERT', 'DELETE', 'MERGE', 'COMMIT', 'ROLLBACK', 'CURSOR', 'RAISE', 'EXCEPTION'):
                found.add(upper)
            elif upper == 'UPDATE' and (index == 0 or tokens[index - 1][1].upper() != 'FOR'):
                found.add('UPDATE')
            elif upper == 'EXECUTE' and following.upper() == 'IMMEDIATE':
                found.add('EXECUTE IMMEDIATE')
            elif following == '(' or following == ';':
                if '.' in upper and not kept(upper):
                    found.add('csomag.rutin hívása')
                elif not kept(upper) and upper not in MESSAGE_WORDS:
                    found.add('saját/ismeretlen rutin hívása')
    if 'SELECT' in words:
        found.add('SELECT … INTO' if 'INTO' in words else 'SELECT')
    return found


def scrub(text: str, names: bool) -> str:
    """A message template without the remaining single names (tables, LOVs, units)."""
    if names:
        return text
    def replace(match):
        word = match.group()
        return word if kept(word) or word in MESSAGE_WORDS else '<név>'
    return re.sub(r'(?<![\w$#-])[A-Z][A-Z0-9_$#]{2,}(?![\w$#-])', replace, text)


def digest(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]


def add_example(bucket: dict, example: dict) -> None:
    if example.get('code') is None:
        return
    seen = {e['id'] for e in bucket['examples']}
    example['id'] = digest(example['code'])
    if example['id'] not in seen and len(bucket['examples']) < MAX_EXAMPLES:
        bucket['examples'].append(example)


def bucket() -> dict:
    return {'endpoints': 0, 'sole': 0, 'forms': set(), 'operations': Counter(), 'examples': []}


def collect(out: Path, entries: list[dict], names: bool = False) -> dict:
    """The survey of the migrate outputs under out (one folder per entry, as in portfolio)."""
    causes = defaultdict(bucket)
    triggers = defaultdict(lambda: {'triggers': 0, 'forms': set(), 'scopes': Counter(), 'constructs': Counter(),
                                    'examples': []})
    construct_triggers, construct_forms = Counter(), defaultdict(set)
    queries = defaultdict(lambda: {'blocks': 0, 'forms': set(), 'examples': []})
    lovs = defaultdict(lambda: {'lovs': 0, 'forms': set(), 'examples': []})
    issue_codes, sources, failures = Counter(), Counter(), Counter()
    operations = defaultdict(Counter)
    totals = Counter()
    for number, entry in enumerate(entries, 1):
        root = out / entry['folder']
        summary = load(root / 'analysis/summary.json')
        totals['forms'] += 1
        if entry.get('status') != 'ok' or summary is None:
            totals['failed'] += 1
            failures[scrub(normalize(entry.get('error') or 'ismeretlen hiba'), names)] += 1
            continue
        model = load(root / 'analysis/form.ir.json', {}) or {}
        plan = load(root / 'analysis/backend-plan.json', {}) or {}
        form = summary.get('form', entry['folder']) if names else f'F{number}'
        issues = {}
        for issue in model.get('issues', []):
            issues.setdefault(issue.get('detail'), issue)
            issue_codes[(issue.get('code'), issue.get('scope'))] += 1
        by_trigger = {t.get('id'): t for t in model.get('triggers', [])}
        blocks = {b.get('name'): b for b in model.get('blocks', [])}
        for block in blocks.values():
            if block.get('database'):
                p = block.get('properties', {})
                sources[(p.get('querydatasourcetype') or 'Table', p.get('dmldatatargettype') or 'Table')] += 1
        totals['triggers'] += summary.get('triggers', 0)
        totals['review_triggers'] += summary.get('review_triggers', 0)
        totals['skipped_operations'] += len(plan.get('skipped_operations', []))
        if plan.get('module_gate', {}).get('required'):
            totals['module_gate_forms'] += 1

        for endpoint in plan.get('endpoints', []):
            op = endpoint.get('operation')
            if not op:
                continue
            state = 'enabled' if endpoint.get('implemented') else 'ready' if endpoint.get('ready_after_module_review') else 'blocked'
            if op == 'lov':
                totals['lov_' + state] += 1
                continue
            operations[op]['total'] += 1
            operations[op][state] += 1
            if state != 'blocked':
                continue
            block = blocks.get(endpoint.get('block'), {})
            keys = {}
            for detail in dict.fromkeys(endpoint.get('blockers') or ['(nincs megadott ok)']):
                issue = issues.get(detail, {})
                code = 'WRITE_APPROVAL' if detail == WRITE_APPROVAL else issue.get('code', 'EGYÉB')
                key = (code, scrub(normalize(detail), names))
                trigger = by_trigger.get(detail.split(': ', 1)[0]) if TRIGGER_ID.match(detail) else None
                keys[key] = trigger
            for key, trigger in keys.items():
                row = causes[key]
                row['endpoints'] += 1
                row['sole'] += len(keys) == 1
                row['forms'].add(form)
                row['operations'][op] += 1
                if trigger:
                    add_example(row, {'form': form, 'event': trigger.get('event'),
                                      'code': Shaper(names).shape(trigger.get('source', ''))})
                elif op in ('read', 'search', 'list') and block.get('properties', {}).get('whereclause'):
                    add_example(row, {'form': form, 'event': 'WHERE',
                                      'code': Shaper(names).shape(block['properties']['whereclause'])})
            if op in ('read', 'search', 'list'):
                where = block.get('properties', {}).get('whereclause')
                if where:
                    shape = Shaper(names).shape(where)
                    row = queries[next(iter(keys))[1] if keys else '']
                    row['blocks'] += 1
                    row['forms'].add(form)
                    add_example(row, {'form': form, 'event': 'WHERE', 'code': shape})

        for trigger in model.get('triggers', []):
            if trigger.get('status') != 'review':
                continue
            reason = trigger.get('reason') or ''
            issue = issues.get((trigger.get('id') or '') + ': ' + reason, {})
            scope = issue.get('scope', 'review')
            row = triggers[(trigger.get('event') or '', scrub(normalize(reason), names))]
            row['triggers'] += 1
            row['forms'].add(form)
            row['scopes'][scope] += 1
            found = constructs(trigger.get('source', ''))
            row['constructs'].update(found)
            add_example(row, {'form': form, 'event': trigger.get('event'), 'scope': scope,
                              'code': Shaper(names).shape(trigger.get('source', ''))})
            if scope in BLOCKING_SCOPES:
                construct_triggers.update(found)
                for name in found:
                    construct_forms[name].add(form)

        for plan_lov in model.get('lov_plans', []):
            if not plan_lov.get('blockers'):
                continue
            row = lovs[scrub(normalize(plan_lov['blockers'][0]), names)]
            row['lovs'] += 1
            row['forms'].add(form)
            add_example(row, {'form': form, 'event': 'RecordGroupQuery',
                              'code': Shaper(names).shape(plan_lov.get('query') or '')})

    for op, counts in operations.items():
        for state in ('total', 'enabled', 'ready', 'blocked'):
            totals['endpoints' if state == 'total' else state] += counts[state]

    def rows(table, weight, label):
        result = []
        for key, data in table.items():
            row = {label: key} if not isinstance(key, tuple) else dict(zip(label, key))
            for field, value in data.items():
                row[field] = (len(value) if field == 'forms' else dict(value.most_common()) if isinstance(value, Counter)
                              else value)
            result.append(row)
        return sorted(result, key=lambda r: (-r[weight], -r['forms'], str(r)))

    return {
        'survey_version': SURVEY_VERSION,
        'generator': __version__,
        'names': names,
        'totals': dict(totals),
        'operations': {op: dict(counts) for op, counts in sorted(operations.items())},
        'causes': rows(causes, 'endpoints', ('code', 'reason')),
        'triggers': rows(triggers, 'triggers', ('event', 'reason')),
        'constructs': sorted(({'construct': name, 'triggers': count, 'forms': len(construct_forms[name])}
                              for name, count in construct_triggers.items()),
                             key=lambda r: (-r['triggers'], -r['forms'], r['construct'])),
        'queries': rows(queries, 'blocks', 'reason'),
        'lovs': rows(lovs, 'lovs', 'reason'),
        'data_sources': [{'query_source': q, 'dml_target': d, 'blocks': n} for (q, d), n in sources.most_common()],
        'issue_codes': [{'code': c, 'scope': s, 'count': n} for (c, s), n in issue_codes.most_common()],
        'failures': [{'error': e, 'forms': n} for e, n in failures.most_common()],
    }


# --- output ----------------------------------------------------------------------

OPERATION_LABELS = {'list': 'lista', 'read': 'olvasás', 'search': 'keresés', 'create': 'új rekord',
                    'update': 'módosítás', 'delete': 'törlés', 'action': 'gomb / indítás', 'commit': 'mentési lánc'}


def cell(value) -> str:
    return str(value).replace('|', '\\|').replace('\n', ' ')


def fence(example: dict) -> list[str]:
    where = ', '.join(str(v) for v in (example.get('form'), example.get('event'), example.get('scope')) if v)
    return [f'Példa ({where}):', '', '```sql', example['code'], '```', '']


def markdown(report: dict, limit: int = 30, detailed: int = 12) -> str:
    t = report['totals']
    endpoints = t.get('endpoints', 0)
    share = lambda part: f'{100 * part / endpoints:.0f}%' if endpoints else '–'
    lines = ['# Felmérés: miért tiltottak a generált végpontok', '',
             f"Generátor: {report['generator']}. Formok: {t.get('forms', 0)}, ebből sikertelen: {t.get('failed', 0)}. "
             f"Átültetendő trigger: {t.get('review_triggers', 0)} / {t.get('triggers', 0)}.", '']
    if report['names']:
        lines += ['**Ez a változat a valódi neveket tartalmazza: ne oszd meg a cégen kívül.**', '']
    else:
        lines += ['A nevek, szövegek, számok és kommentek helyén helyettesítők állnak (N1, :B1.I2, \'…\'); a kulcsszavak, '
                  'a Forms beépített hívásai és a kód szerkezete megmaradt. A fájl megosztható a hibák feltárásához; '
                  'a teljes adat a felmeres.json-ban van.', '']
    lines += ['## Végpontok', '', '| Művelet | Összes | Engedélyezett | Kapcsolóra vár | Tiltott |', '|---|---:|---:|---:|---:|']
    for op, counts in report['operations'].items():
        lines.append(f"| {OPERATION_LABELS.get(op, op)} | {counts.get('total', 0)} | {counts.get('enabled', 0)} | "
                     f"{counts.get('ready', 0)} | {counts.get('blocked', 0)} |")
    lines.append(f"| **összesen** | **{endpoints}** | **{t.get('enabled', 0)}** ({share(t.get('enabled', 0))}) | "
                 f"**{t.get('ready', 0)}** | **{t.get('blocked', 0)}** ({share(t.get('blocked', 0))}) |")
    lines += ['', f"Nem generált művelet (a Forms-blokk nem engedi): {t.get('skipped_operations', 0)}. "
              f"LOV-végpont: {t.get('lov_enabled', 0)} engedélyezett, {t.get('lov_blocked', 0)} tiltott.", '',
              '## Okok a tiltott végpontok szerint', '',
              'Egy sor egy ok (hibakód és üzenetsablon). „Egyedüli ok”: ennyi végpontot csak ez tilt, vagyis az ok '
              'megszüntetésével ennyi végpont nyílik meg.', '',
              '| # | Kód | Ok | Végpont | Egyedüli ok | Form | Műveletek |', '|---:|---|---|---:|---:|---:|---|']
    for index, row in enumerate(report['causes'][:limit], 1):
        ops = ', '.join(f'{OPERATION_LABELS.get(o, o)} {n}' for o, n in row['operations'].items())
        lines.append(f"| {index} | {cell(row['code'])} | {cell(row['reason'][:220])} | {row['endpoints']} | "
                     f"{row['sole']} | {row['forms']} | {cell(ops)} |")
    if not report['causes']:
        lines.append('| – | Nincs tiltott végpont. | | 0 | 0 | 0 | |')
    for index, row in enumerate(report['causes'][:detailed], 1):
        if not row['examples']:
            continue
        lines += ['', f"### {index}. {row['code']}: {row['reason'][:160]}", '']
        for example in row['examples']:
            lines += fence(example)
    lines += ['## Átültetendő triggerek', '',
              'Hatókör: all/read/write/create/update/delete = végpontot tilt; frontend = képernyőfeladat; button = gomb.', '',
              '| # | Esemény | Ok | Trigger | Form | Hatókör | Szerkezetek |', '|---:|---|---|---:|---:|---|---|']
    for index, row in enumerate(report['triggers'][:limit], 1):
        scopes = ', '.join(f'{s} {n}' for s, n in row['scopes'].items())
        found = ', '.join(f'{c} {n}' for c, n in list(row['constructs'].items())[:6])
        lines.append(f"| {index} | {cell(row['event'])} | {cell(row['reason'][:200])} | {row['triggers']} | "
                     f"{row['forms']} | {cell(scopes)} | {cell(found)} |")
    for index, row in enumerate(report['triggers'][:detailed], 1):
        if row['examples']:
            lines += ['', f"### T{index}. {row['event']}: {row['reason'][:160]}", '']
            lines += fence(row['examples'][0])
    lines += ['## Szerkezetek a végpontot tiltó triggerekben', '',
              'Hány végpontot tiltó trigger tartalmazza az adott Forms-hívást vagy SQL-szerkezetet.', '',
              '| Szerkezet | Trigger | Form |', '|---|---:|---:|']
    lines += [f"| {cell(r['construct'])} | {r['triggers']} | {r['forms']} |" for r in report['constructs'][:40]]
    if report['queries']:
        lines += ['', '## Lekérdezések a tiltott olvasásoknál', '', '| Ok | Blokk | Form |', '|---|---:|---:|']
        lines += [f"| {cell(r['reason'][:200])} | {r['blocks']} | {r['forms']} |" for r in report['queries'][:limit]]
        for row in report['queries'][:5]:
            for example in row['examples'][:1]:
                lines += [''] + fence(example)
    if report['lovs']:
        lines += ['', '## Tiltott LOV-ok', '', '| Ok | LOV | Form |', '|---|---:|---:|']
        lines += [f"| {cell(r['reason'][:200])} | {r['lovs']} | {r['forms']} |" for r in report['lovs'][:limit]]
        for row in report['lovs'][:5]:
            for example in row['examples'][:1]:
                lines += [''] + fence(example)
    lines += ['', '## Adatforrások (adatbázis-blokkok)', '', '| Lekérdezés forrása | DML cél | Blokk |', '|---|---|---:|']
    lines += [f"| {cell(r['query_source'])} | {cell(r['dml_target'])} | {r['blocks']} |" for r in report['data_sources']]
    lines += ['', '## Hibakódok (minden figyelmeztetés)', '', '| Kód | Hatókör | Db |', '|---|---|---:|']
    lines += [f"| {cell(r['code'])} | {cell(r['scope'])} | {r['count']} |" for r in report['issue_codes'][:limit]]
    if report['failures']:
        lines += ['', '## Sikertelen generálás', '', '| Hiba | Form |', '|---|---:|']
        lines += [f"| {cell(r['error'][:300])} | {r['forms']} |" for r in report['failures']]
    return '\n'.join(lines).rstrip() + '\n'


def write(out: Path, report: dict) -> None:
    write_json(out / 'felmeres.json', report)
    (out / 'FELMERES_HU.md').write_text(markdown(report), encoding='utf-8')

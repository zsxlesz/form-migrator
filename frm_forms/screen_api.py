"""Backend calls of the generated screen, in the company pattern.

Every endpoint gets its own one-line method; frm-forms-screen.ts (send) logs the successful response first with
WFF.debug(<module>.<method>, res) and reports errors with WFF.err:

    searchAit(body: unknown) { return this.send('searchAit', this.http.post(this.url('searchait'), body)); }

The argument of this.url(...) is the endpoint as the CL names it (its Constants path without the leading '/'; in
the company format exactly the <METHOD>_NAME value), so a text search finds the call in CL, DPS, WBS and the
component alike. ServiceBase.url adds the server and module path. The screen gives the rest as data (queries,
lovs, rowKeys, actionEndpoints ...): frm-forms-screen.ts runs them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .angular_single import Code, ts
from .common import name

QUERY_LIMIT = 200  # backend list/search limit: 1..200
DEFAULT_HTTP = {'list': 'get', 'search': 'post', 'create': 'post', 'update': 'put', 'delete': 'delete'}
# Members of the screen and of frm-forms-screen.ts the endpoint methods must not shadow.
RESERVED = {'constructor', 'url', 'http', 'toast', 'toastLife', 'labels', 'router', 'modName', 'send', 'button', 'lov', 'fields',
            'blockOf', 'cursor', 'oracleName', 'keyOf', 'onFormGroupGenerated', 'watch', 'fieldValidators', 'updateField', 'locate',
            'validBefore', 'onAction', 'navigate', 'onLovSearch', 'setLovSuggestions', 'lovChoice', 'applyLovReturns',
            'setItemState', 'applyItemState', 'setItemValue', 'stateValue', 'isNull', 'cmp', 'setWindowVisible', 'showCanvas',
            'hideCanvas', 'payload', 'wireText', 'value', 'rowFields', 'fromDto', 'showRecord', 'applyOracleValues', 'screenBlocks',
            'recordOf', 'executeQuery', 'criterion', 'showRows', 'selectedRecords', 'clearTable', 'runSteps', 'runAction',
            'formsGlobals', 'rememberGlobals', 'requestContext', 'formsStatus', 'runCommands', 'screenBlockNames', 'formsQuery',
            'formsItemProperty', 'clearBlock', 'formsCall', 'formsKey', 'recordGroup', 'askAlert', 'answerAlert', 'markPristine',
            'formsDelete', 'onToolbar', 'applyChanged', 'formsCommit', 'structures', 'tables', 'validators', 'queries', 'lovs',
            'actionEndpoints', 'actionSteps', 'queryActionBlocks', 'checkboxValues', 'oracleNames', 'rowKeys', 'commitBlocks',
            'commitEndpoint', 'alertDefinitions', 'formRoutes', 'navigations', 'manualNavigations', 'changeHandlers',
            'recordHandlers', 'buttonHandlers', 'initAction', 'windowVisible', 'canvasVisible', 'activeContentCanvas',
            'canvasTargets', 'formGroups', 'formValues', 'itemStates', 'originals', 'pendingDeletes', 'activeQueryActions',
            'paramLists', 'recordGroups', 'formsAlert', 'cursorBlock', 'cursorItem', 'changeDetector', 'destroyRef'}


def load_api(output: Path) -> dict | None:
    path = output / 'analysis' / 'backend-plan.json'
    if not path.is_file():
        return None  # --frontend-only: no generated backend
    api = json.loads(path.read_text(encoding='utf-8')).get('api')
    return api if api and api.get('paths') else None


def method_name(constant: str, taken: set) -> str:
    base = name(re.sub(r'_PATH$', '', constant).lower(), 'camel') or 'call'
    base = base if base not in RESERVED else base + 'Call'
    result, n = base, 2
    while result in taken:
        result, n = base + str(n), n + 1
    return result


def wiring(plan: dict, ui: dict, api: dict | None, key: str, forms: list, tables: list, checkboxes: list, buttons: bool = False) -> dict | None:
    if not api:
        return None
    prefix = name(key, 'pascal')
    on_screen = {s['block'] for s in forms + tables}
    spacers = {s['owner'] for s in plan.get('spacers', [])}  # layout gaps never carry data
    # Oracle item -> screen control key, for every rendered block.
    screen_keys = {}
    for block in ui['blocks']:
        if block['name'] in on_screen:
            screen_keys[block['name']] = {i['name']: i['key'] for i in block['items'] if i['owner'] not in spacers}
    owner_keys = {b + '.' + n: (b, k) for b, names in screen_keys.items() for n, k in names.items()}
    endpoints, taken = [], set(RESERVED)

    def endpoint(constant, http, kind, target):
        method = method_name(constant, taken)
        taken.add(method)
        entry = {'method': method, 'url': api['paths'][constant].lstrip('/'), 'http': http.lower(), 'constant': constant,
                 'kind': kind, 'target': target}
        endpoints.append(entry)
        return entry

    queries, row_keys = {}, {}
    for block, entry in api['blocks'].items():
        if block not in on_screen:
            continue
        keys = screen_keys.get(block, {})
        row_keys[block] = {field: keys[item] for item, field in entry['fields'].items() if item in keys}
        calls = {op: endpoint(o['constant'], o.get('http') or DEFAULT_HTTP.get(op, 'post'), op, block)
                 for op, o in entry['operations'].items()}
        kind = 'search' if 'search' in calls else 'list' if 'list' in calls else None
        if kind is None:
            continue
        query = {'call': calls[kind]['method'], 'kind': kind, 'limit': QUERY_LIMIT}
        if kind == 'search':
            criteria = []
            emulation = bool(api['actions'] or api.get('commit'))
            for c in entry['operations']['search'].get('criteria', []):
                if emulation and c['source'].split('.')[0] in {'GLOBAL', 'PARAMETER'}:
                    # :GLOBAL / :PARAMETER: the screen's Forms context (screen_emulation.requestContext).
                    criteria.append({'field': c['field'], 'block': '', 'key': '', 'context': c['source']})
                    continue
                if c['source'] not in owner_keys:
                    query = None  # a criterion from outside the screen: the developer runs this search
                    break
                b, k = owner_keys[c['source']]
                criteria.append({'field': c['field'], 'block': b, 'key': k})
            if query is None:
                continue
            query['criteria'] = criteria
        queries[block] = query
    lov_endpoints = {}
    lookups = {l['name']: l for l in plan['lookups']}
    for lov, entry in api['lovs'].items():
        if lov not in lookups:
            continue
        binds = []
        for bind in entry['binds']:
            if bind['source'] not in owner_keys:
                binds = None
                break
            b, k = owner_keys[bind['source']]
            binds.append({'source': bind['source'], 'block': b, 'key': k})
        if binds is None:
            continue
        columns = [{'column': c['column'], 'returnItem': c['return_item'] or ''} for c in lookups[lov]['columns'] if c['column']]
        lov_endpoints[lov] = {'call': endpoint(entry['constant'], 'post', 'lov', lov)['method'], 'binds': binds, 'columns': columns}
    actions = {owner: endpoint(a['constant'], 'post', 'action', owner)['method'] for owner, a in api['actions'].items()}
    # Forms COMMIT_FORM: the save chain of the screen's form blocks (commit_chain).
    commit = None
    spec = api.get('commit')
    if spec:
        call = endpoint(spec['constant'], 'post', 'commit', '@FORM')['method']  # every CL endpoint has its method
        saved = {b: s for b, s in spec['blocks'].items() if b in {f['block'] for f in forms}}
        if saved:
            commit = {'call': call, 'blocks': saved}
    query_actions = {owner: a['query_block'] for owner, a in api['actions'].items() if a.get('query_block')}
    checkbox_values = {}
    for item in checkboxes:
        checkbox_values.setdefault(item['block'], {})[item['key']] = [item['checked'], item['unchecked']]
    table_records = [(s['block'], s['property']) for s in tables]
    oracle_names = {b: {k: n for n, k in names.items()} for b, names in screen_keys.items()}
    return {'prefix': prefix, 'api': api, 'constants_class': api['constants_class'], 'envelope': api.get('response_envelope'),
            'endpoints': endpoints, 'queries': queries, 'row_keys': row_keys, 'lovs': lov_endpoints, 'actions': actions,
            'query_actions': query_actions,
            'checkbox_values': checkbox_values, 'tables': table_records, 'oracle_names': oracle_names,
            'screen_keys': screen_keys, 'forms': bool(forms), 'buttons': buttons, 'commit': commit,
            'ui_disabled': {b: e.get('ui_disabled', {}) for b, e in api['blocks'].items()},
            'alerts_used': any(a.get('alerts') for a in api['actions'].values()),
            # COMMIT_FORM in the middle of a button's code: the screen saves, then the button resumes (commit_points).
            'commit_points': bool(commit) and bool(forms) and any(a.get('commit_point') for a in api['actions'].values())}


def oracle_exceptions(oracle_names: dict) -> dict:
    """The items whose Oracle name frm-forms-screen.ts cannot derive from the control key (VEVO_NEV <-> vevoNev)."""
    result = {}
    for block, names in oracle_names.items():
        for control, oracle in names.items():
            derived_key = re.sub(r'_+([a-z0-9])', lambda m: m.group(1).upper(), oracle.lower())
            derived_name = re.sub(r'([A-Z])', r'_\1', control).upper()
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', oracle) or derived_key != control or derived_name != oracle:
                result.setdefault(block, {})[control] = oracle
    return result


def fields(w: dict) -> list[str]:
    """The screen's backend data for frm-forms-screen.ts."""
    from .angular_single import Code
    from .ts_code import record
    result = []
    if w['queries']:
        queries = {}
        for block, q in w['queries'].items():
            call = 'request => this.' + q['call'] + ('(request.offset, request.limit)' if q['kind'] == 'list' else '(request)')
            spec = {'call': Code(call)}
            if q.get('criteria'):
                spec['criteria'] = {c['field']: ':' + c['context'] if c.get('context') else c['block'] + '.' + c['key'] for c in q['criteria']}
            queries[block] = spec
        result.append('  protected override readonly queries: Record<string, FrmQuery> = ' + record(queries) + ';')
    if w['lovs']:
        lovs = {lov: {'call': Code('request => this.' + e['call'] + '(request)'), 'columns': {c['column']: c['returnItem'] for c in e['columns']},
                      **({'binds': {b['source']: b['block'] + '.' + b['key'] for b in e['binds']}} if e['binds'] else {})}
                for lov, e in w['lovs'].items()}
        result.append('  protected override readonly lovs: Record<string, FrmLov> = ' + record(lovs) + ';')
    if w['row_keys'] and (w['queries'] or w['actions'] or w.get('commit')):
        rows = {block: [field if field == control else [field, control] for field, control in keys.items()] for block, keys in w['row_keys'].items()}
        result.append('  protected override readonly rowKeys = ' + record(rows) + ';')
    exceptions = oracle_exceptions(w['oracle_names'])
    if exceptions:
        result.append('  protected override readonly oracleNames = ' + record(exceptions) + ';')
    if w['actions']:
        calls = {owner: Code('request => this.' + method + '(request)') for owner, method in w['actions'].items()}
        result.append('  protected override readonly actionEndpoints: Record<string, FrmActionCall> = ' + record(calls) + ';')
    if w.get('query_actions'):
        result.append('  protected override readonly queryActionBlocks = ' + record(w['query_actions']) + ';')
    return result


def endpoint_method(e: dict) -> str:
    """One backend call: this.url('<CL endpoint>'), logged and reported by send (frm-forms-screen.ts)."""
    from .ts_code import sq
    url = 'this.url(' + sq(e['url']) + ')'
    if e['http'] == 'get':
        signature, call = f'offset = 0, limit = {QUERY_LIMIT}', f'this.http.get({url}, {{ params: {{ offset, limit }} }})'
    elif e['http'] == 'delete':
        signature, call = 'body: unknown', f'this.http.delete({url}, {{ body }})'
    else:
        signature, call = 'body: unknown', f"this.http.{e['http']}({url}, body)"
    return f"  {e['method']}({signature}) {{ return this.send({sq(e['method'])}, {call}); }}"


def summary(w: dict | None) -> dict | None:
    """What the component calls, for screen-plan.json and the notes."""
    if not w:
        return None
    return {'constants_class': w['constants_class'], 'response_envelope': w.get('envelope'),
            'endpoints': [{k: e[k] for k in ('method', 'url', 'http', 'constant', 'kind', 'target')} for e in w['endpoints']],
            'queries': {block: q['call'] for block, q in w['queries'].items()},
            'lovs': {lov: e['call'] for lov, e in w['lovs'].items()},
            'actions': dict(w['actions']), 'query_actions': dict(w.get('query_actions', {})),
            'commit': {'call': w['commit']['call'], 'blocks': sorted(w['commit']['blocks'])} if w.get('commit') else None,
            'uncalled': uncalled(w)}


def uncalled(w: dict) -> list[dict]:
    """Generated endpoints the screen never calls, with the reason: a review list, nothing is broken by it."""
    called = {q['call'] for q in w['queries'].values()} | {e['call'] for e in w['lovs'].values()} | set(w['actions'].values())
    if w.get('commit'):
        called.add(w['commit']['call'])
    saved = set(w['commit']['blocks']) if w.get('commit') else set()
    result = []
    for e in w['endpoints']:
        if e['method'] in called:
            continue
        kind, target = e['kind'], e['target']
        if kind in {'create', 'update', 'delete'}:
            reason = ('a mentési lánc (commit) hívja a backendben; önálló rekordművelethez (pl. táblázatos szerkesztő) köthető'
                      if target in saved else 'a blokk nem űrlapként jelenik meg: a mentést a fejlesztő köti be')
        elif kind in {'list', 'search'}:
            reason = ('a keresés feltétele a képernyőn kívüli mezőből jön (GLOBAL/PARAMETER vagy rejtett blokk)'
                      if target in w['screen_keys'] else 'a blokk nincs a generált képernyőn')
        elif kind == 'lov':
            reason = 'a LOV kötött mezője nincs a képernyőn, vagy képernyőn kívüli értéket köt'
        elif kind == 'commit':
            reason = 'a képernyőn nincs menthető űrlapblokk'
        else:
            reason = 'a hívó gomb nincs a generált képernyőn'
        result.append({'method': e['method'], 'kind': kind, 'target': target, 'reason': reason})
    return result


def notes(w: dict | None) -> list[str]:
    if not w:
        return ['', '## Backend-hívások', '', 'Nincs generált backend (frontend-only): a komponens nem hív backendet.']
    lines = ['', '## Backend-hívások', '',
             'A komponens a közös `FrmFormsScreen`-t (frm-forms-screen.ts) örökli. Minden végpontnak egysoros metódusa van: '
             "`this.send('<metódus>', this.http.<ige>(this.url('<végpont>')))`. A `send` a sikeres választ legelőször "
             "`WFF.debug(this.modName + '.<metódus>', res)` hívással naplózza, hibánál `WFF.err('Hiba', error)` jelez. "
             'A `this.url(...)` argumentuma a végpont neve úgy, ahogy a CL használja: rákeresve a CL-ben, a DPS-ben, '
             'a WBS-ben és a komponensben is megtalálható.', '',
             '| Metódus | Hívás | CL-konstans | Használja |', '|---|---|---|---|']
    use = {'search': 'lekérdezés (go_block + execute_query, `executeQuery`)', 'list': 'lekérdezés (`executeQuery`)',
           'lov': 'LOV-keresés', 'action': 'gomb', 'commit': 'mentés (Forms COMMIT_FORM)'}
    for e in w['endpoints']:
        lines.append(f"| `{e['method']}` | `{e['http'].upper()} this.url('{e['url']}')` | `{w['constants_class']}.{e['constant']}` | "
                     f"{use.get(e['kind'], 'mentés: a fejlesztő hívja')} |")
    if w.get('uncalled'):
        lines += ['', '### Végpontok, amelyeket a képernyő nem hív', '',
                  'Nem hiba: a backend kész, de a generált képernyő nem hívja őket. Ha egyik sem kell, a végpont törölhető.', '',
                  '| Metódus | Művelet | Blokk / gomb | Miért nem hívja |', '|---|---|---|---|']
        lines += [f"| `{u['method']}` | {u['kind']} | `{u['target']}` | {u['reason']} |" for u in w['uncalled']]
    if w.get('commit'):
        lines += ['', '## Mentés (Forms COMMIT_FORM)', '',
                  'Az eszköztár **Mentés** gombja (és a kódban hívott `COMMIT_FORM` / `DO_KEY(\'COMMIT_FORM\')`) a `'
                  + w['commit']['call'] + '` végpontot hívja: a képernyő összes változása egy kérésben megy, a backend '
                  'egy tranzakcióban, Forms-sorrendben menti (blokksorrend; blokkonként törlés, majd beszúrás és módosítás; '
                  'minden rekord a saját triggereivel). Hiba esetén semmi sem mentődik.',
                  '',
                  '- Lekérdezett rekord módosítása: módosítás (az eredeti rekorddal: ütközésfigyelés). Lekérdezés nélkül kitöltött '
                  'blokk: új rekord. **Törlés**: a rekord törlésre jelölve, a Mentés véglegesíti. **Új rekord**: a blokk ürül.',
                  '- Új részletrekord kulcsa a most mentett masterből (szekvenciából is), különben a master képernyőértékéből jön.',
                  '- Közelítés: blokkonként egy aktuális rekord (a táblázatos blokkok soraihoz saját szerkesztő szükséges).',
                  '- Saját logikájú KEY-COMMIT trigger nem fut a Mentés gombon: a logikáját át kell nézni (BACKEND_TASKS.md).']
    else:
        lines += ['', 'Mentés (create/update/delete): a metódusok elkészülnek, de a Forms COMMIT-szemantikája (több rekord, sorrend, '
                  'hibakezelés) miatt a mentést a fejlesztő köti be; a komponens nem ment automatikusan.']
    if w.get('envelope'):
        lines += ['', f"A válasz a `{w['envelope']}` borítékban érkezik: a `payload()` metódus veszi ki belőle az adatot "
                  '(a keresett mezőnevek listája egy helyen igazítható).']
    return lines

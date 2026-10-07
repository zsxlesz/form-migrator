"""Backend calls of the generated screen, in the company pattern.

Every endpoint gets its own method in the component (screen_code.endpoint_method): the successful response is logged
first with WFF.debug(<module>.<method>, res), an error with WFF.err:

    aitSearch(body: unknown) {
      return this.http.post<Page>(this.url('ait/query/search'), body).pipe(tap(res => WFF.debug(...)), catchError(...));
    }

The argument of this.url(...) is the endpoint as the CL names it (its Constants path without the leading '/'; in
the company format exactly the <METHOD>_NAME value), so a text search finds the call in CL, DPS, WBS and the
component alike. ServiceBase.url adds the server and module path. wiring() says which endpoint the screen calls for
what (queries, LOVs, buttons, save); screen_code writes the calls.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .angular_single import Code, ts
from .common import name

QUERY_LIMIT = 200  # backend list/search limit: 1..200
DEFAULT_HTTP = {'list': 'get', 'search': 'post', 'create': 'post', 'update': 'put', 'delete': 'delete'}
from .screen_code import RESERVED  # members of the component the endpoint methods must not shadow


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
            for c in entry['operations']['search'].get('criteria', []):
                if c['source'].split('.')[0] in {'GLOBAL', 'PARAMETER'}:
                    # :PARAMETER from the URL, :GLOBAL a TODO of the query method (screen_code.query).
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
             'Minden végpontnak saját metódusa van a komponensben: `this.http.<ige>(this.url(\'<végpont>\'))`. A sikeres választ '
             "legelőször `WFF.debug(this.modName + '.<metódus>', res)` naplózza, hibánál `WFF.err('Hiba', error)` jelez. "
             'A `this.url(...)` argumentuma a végpont neve úgy, ahogy a CL használja: rákeresve a CL-ben, a DPS-ben, '
             'a WBS-ben és a komponensben is megtalálható.', '',
             '| Metódus | Hívás | CL-konstans | Használja |', '|---|---|---|---|']
    use = {'search': 'lekérdezés (`query<Blokk>()`)', 'list': 'lekérdezés (`query<Blokk>()`)',
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
                  'Az eszköztár **Mentés** gombja (`save()`; a felismert `COMMIT_FORM` gomblépés is ezt hívja) a `'
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
        lines += ['', f"A válasz a `{w['envelope']}` borítékban érkezik: a komponens `data()` metódusa veszi ki belőle az adatot "
                  '(a boríték mezőneve ott igazítható).']
    return lines

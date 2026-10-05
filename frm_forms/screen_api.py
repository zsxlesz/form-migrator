"""Backend calls of the generated screen, in the company pattern.

The component extends ServiceBase; every endpoint gets its own method:

    searchAit(body: unknown) {
      return this.http.post(this.url('searchait'), body)
        .pipe(
          catchError((error) => {
            WFF.err('Hiba', error);
            throw error;
          })
        );
    }

The argument of this.url(...) is the endpoint as the CL names it (its Constants path without the
leading '/'; in the company format exactly the <METHOD>_NAME value), so a text search finds the
call in CL, DPS, WBS and the component alike. ServiceBase.url adds the server and module path.
Errors are reported by WFF.err; results, empty queries and messages by the ToastService.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .angular_single import Code, ts
from .common import name

QUERY_LIMIT = 200  # backend list/search limit: 1..200
DEFAULT_HTTP = {'list': 'get', 'search': 'post', 'create': 'post', 'update': 'put', 'delete': 'delete'}
# Component members the endpoint methods must not shadow.
RESERVED = {'constructor', 'url', 'http', 'toast', 'executeQuery', 'searchLov', 'runAction', 'runSteps', 'showRows', 'showRecord',
            'value', 'payload', 'wireText', 'lovChoice', 'applyOracleValues', 'onAction', 'onLovSearch', 'setLovSuggestions',
            'queryActionBlocks', 'activeQueryActions'}


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


def declarations(w: dict) -> list[str]:
    if w.get('runtime'):
        return []  # FrmPage, FrmActionResult, FrmCommitResult and localIso: frm-forms-screen.ts
    result = []
    if w['queries'] or w.get('query_actions'):
        nullable = ' | null' if w.get('query_actions') else ''
        result.append('interface ' + w['prefix'] + 'Page {\n  rows?: Record<string, unknown>[]' + nullable + ';\n  messages?: string[];\n}')
    if w['actions']:
        result.append('interface ' + w['prefix'] + 'ActionResult {\n  blocks?: Record<string, Record<string, string | null>>;\n  messages?: string[];\n'
                      '  /** A Forms-hívások felületi utasításként, sorrendben: [művelet, argumentumok...]. */\n'
                      '  commands?: (string | null)[][];\n  /** A kód által írt :GLOBAL értékek. */\n'
                      '  globals?: Record<string, string | null>;\n}')
    if w.get('commit'):
        result.append('interface ' + w['prefix'] + 'CommitResult {\n  blocks?: Record<string, Record<string, string | null>>;\n'
                      '  messages?: string[];\n  commands?: (string | null)[][];\n  globals?: Record<string, string | null>;\n'
                      '  /** A mentett rekordok blokkonként: <blokk>Rows. */\n  [rows: string]: unknown;\n}')
    result.append('''function localIso(value: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())}T${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`;
}''')
    return result


def fields(w: dict) -> list[str]:
    result = ['  private readonly http = inject(HttpClient);']
    # With the shared runtime (frm-forms-screen.ts) the screen only gives its data: override of the base fields.
    shared = 'protected override readonly' if w.get('runtime') else 'private readonly'
    if w['queries'] or w.get('query_actions'):
        result.append('  // Forms EXECUTE_QUERY: blokk -> a keresés/lista kritériumai a képernyő mezőiből.\n'
                      '  private readonly queries: Record<string, { limit: number; criteria?: readonly { field: string; block: string; key: string; context?: string }[] }> = '
                      + ts({b: {k: v for k, v in q.items() if k in {'limit', 'criteria'}} for b, q in w['queries'].items()}, 1) + ';')
    if w['queries'] or w['actions'] or w.get('commit'):
        result.append('  // Backend DTO-mező -> képernyő-vezérlő, blokkonként.\n  ' + shared + ' rowKeys: Record<string, Record<string, string>> = '
                      + ts(w['row_keys'], 1) + ';')
    if w['lovs']:
        result.append('  private readonly lovEndpoints: Record<string, { binds: readonly { source: string; block: string; key: string }[]; '
                      'columns: readonly { column: string; returnItem: string }[] }> = '
                      + ts({l: {'binds': e['binds'], 'columns': e['columns']} for l, e in w['lovs'].items()}, 1) + ';')
    if w['actions']:
        calls = {owner: Code('request => this.' + method + '(request)') for owner, method in w['actions'].items()}
        result.append('  // Gomb (Oracle BLOKK.ITEM) -> a generált akció-végpont hívása.\n'
                      '  ' + shared + ' actionEndpoints: Record<string, (request: { blocks: Record<string, Record<string, string | null>>; '
                      'parameters: Record<string, string>; offset?: number; limit?: number }) => Observable<unknown>> = ' + ts(calls, 1) + ';')
    if w['actions'] or w.get('commit'):
        result.append('  // Képernyő-vezérlő -> Oracle mezőnév (az ActionRequest szerződése), blokkonként.\n'
                      '  ' + shared + ' oracleNames: Record<string, Record<string, string>> = ' + ts(w['oracle_names'], 1) + ';')
        from .screen_emulation import emulation_fields
        result += emulation_fields(w)
    if w.get('query_actions'):
        result.append('  ' + shared + ' queryActionBlocks: Record<string, string> = ' + ts(w['query_actions'], 1) + ';')
        if not w.get('runtime'):
            result.append('  private readonly activeQueryActions: Record<string, string> = {};')
    if w['checkbox_values']:
        result.append('  ' + shared + ' checkboxValues: Record<string, Record<string, readonly [string, string]>> = '
                      + ts(w['checkbox_values'], 1) + ';')
    return result


def endpoint_method(w: dict, e: dict) -> str:
    """One backend call as the company writes it: this.url('<CL endpoint>') + catchError(WFF.err)."""
    url = "this.url('" + e['url'].replace('\\', '\\\\').replace("'", "\\'") + "')"
    if e['http'] == 'get':
        signature, call = f'offset = 0, limit = {QUERY_LIMIT}', f'this.http.get({url}, {{ params: {{ offset, limit }} }})'
    elif e['http'] == 'delete':
        signature, call = 'body: unknown', f'this.http.delete({url}, {{ body }})'
    else:
        signature, call = 'body: unknown', f"this.http.{e['http']}({url}, body)"
    return (f"  /** {w['constants_class']}.{e['constant']} ({e['http'].upper()}) */\n"
            f"  {e['method']}({signature}) {{\n"
            f"    return {call}\n"
            "      .pipe(\n"
            "        catchError((error) => {\n"
            "          WFF.err('Hiba', error);\n"
            "          throw error;\n"
            "        })\n"
            "      );\n"
            "  }")


def methods(w: dict, form_values: bool) -> list[str]:
    p = w['prefix']
    result = [endpoint_method(w, e) for e in w['endpoints']]
    runtime = bool(w.get('runtime'))  # payload, wireText, value, showRecord, runAction ... are in frm-forms-screen.ts
    if (w['queries'] or w['lovs'] or w['actions']) and not runtime:
        envelope = w.get('envelope')
        where = (': a ' + envelope + ' boríték adatmezője (a mezőnév-lista itt igazítható), boríték nélkül maga a válasz'
                 if envelope else '; ha boríték érkezik, annak adatmezője')
        result.append('''  /** A válasz hasznos tartalma__WHERE__. */
  private payload<T>(response: unknown): T {
    if (response && typeof response === 'object') {
      for (const field of ['data', 'result', 'payload', 'body', 'content']) {
        const value = (response as Record<string, unknown>)[field];
        if (value && typeof value === 'object') return value as T;
      }
    }
    return response as T;
  }'''.replace('__WHERE__', where))
    checkbox = ('''    const pair = this.checkboxValues[block]?.[key];
    if (pair && typeof value === 'boolean') return value ? pair[0] : pair[1];
''' if w['checkbox_values'] else '')
    if not runtime:
        result.append('''  private wireText(block: string, key: string, value: unknown): string | null {
__CHECKBOX__    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return localIso(value);
    return String(value);
  }'''.replace('__CHECKBOX__', checkbox))
    if w['queries'] or w.get('query_actions'):
        cases = ''
        for block, q in w['queries'].items():
            call = (f"this.{q['call']}(0, query.limit)" if q['kind'] == 'list'
                    else f"this.{q['call']}({{ criteria, offset: 0, limit: query.limit }})")
            cases += f"      case {json.dumps(block)}: request = {call}; break;\n"
        table_cases = ''.join(f"      case {json.dumps(block)}: this.{prop}Rows = mapped as unknown as {p}{name(prop, 'pascal')}Row[]; this.{prop}Selection = null; return;\n"
                              for block, prop in w['tables'] if block in w['queries'] or block in w.get('query_actions', {}).values())
        form_case = "      default: this.showRecord(block, mapped[0] ?? {});\n" if form_values else '      default: return;\n'
        if form_values and (w['actions'] or w.get('commit')):
            # The queried record as the backend sent it (ROWID and hidden keys too): the original of the save chain.
            form_case = ('      default:\n        this.originals[block] = rows[0] ? { ...rows[0] } : null;\n'
                         '        this.showRecord(block, mapped[0] ?? {});\n        this.markPristine(block);\n')
        result.append('''  /** Forms EXECUTE_QUERY a blokk generált keresés/lista végpontján. false: nincs hozzá végpont.
   *  done: a sorok megjelenítése után (képernyőpont: utána folytatódik a gomb kódja). */
  public __OVERRIDE__executeQuery(block: string, done?: () => void): boolean {
__ACTIVE_QUERY__
    const query = this.queries[block];
    if (!query) return false;
    const criteria = Object.fromEntries((query.criteria ?? []).map(c => [c.field, __CONTEXT__this.wireText(c.block, c.key, this.value(c.block, c.key))]));
    let request: Observable<unknown>;
    switch (block) {
__CASES__      default: return false;
    }
    request.subscribe({
      next: response => {
        const page = this.payload<__PAGE__>(response);
        this.showRows(block, page.rows ?? []);
        if (!page.rows?.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, TOAST_LIFE.warning);
        if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, TOAST_LIFE.warning);
        done?.();
      },
      error: () => undefined, // WFF.err már jelezte
    });
    return true;
  }'''.replace('__CASES__', cases).replace('__PAGE__', 'FrmPage' if runtime else p + 'Page').replace('__OVERRIDE__', 'override ' if runtime else '')
        .replace('__CONTEXT__', 'c.context ? this.requestContext([])[c.context] ?? null : ' if w['actions'] or w.get('commit') else '')
        .replace('__ACTIVE_QUERY__',
            '    const action = this.activeQueryActions[block];\n    if (action) return this.runAction(action'
            + (', [], 0, done' if runtime else '') + ');'
            if w.get('query_actions') else ''))
        result.append('''  __SHOW_ROWS__showRows(block: string, rows: readonly Record<string, unknown>[]): void {
    this.changeDetector.markForCheck();
    const keys = this.rowKeys[block] ?? {};
    const mapped = rows.map(row => Object.fromEntries(Object.entries(row).filter(([field]) => field in keys).map(([field, value]) => [keys[field], value])));
    switch (block) {
__TABLES____FORM__    }
  }'''.replace('__TABLES__', table_cases).replace('__FORM__', form_case)
            .replace('__SHOW_ROWS__', 'protected override ' if runtime else 'private '))
    if w['actions'] and w['buttons'] and not runtime:
        from .screen_emulation import steps_method
        result.append(steps_method())
    elif w['queries'] and w['buttons'] and not runtime:
        result.append('''  /** Felismert gomblépések: go_block + execute_query. true: a komponens lefuttatta. */
  private runSteps(steps: readonly { op: string; block?: string }[] | null): boolean {
    if (!steps?.length) return false;
    let block = '';
    const blocks: string[] = [];
    for (const step of steps) {
      if (step.op === 'goBlock' && step.block) block = step.block.toUpperCase();
      else if (step.op === 'executeQuery' && block && this.queries[block]) blocks.push(block);
      else return false;
    }
    for (const target of blocks) this.executeQuery(target);
    return blocks.length > 0;
  }''')
    if runtime:
        pass  # value and showRecord: frm-forms-screen.ts (stateRecord is the screen's hook)
    elif form_values:
        result.append('''  private value(block: string, key: string): unknown {
    return this.formValues[block]?.[key];
  }''')
        result.append('''  private showRecord(block: string, record: Record<string, unknown>): void {
    this.changeDetector.markForCheck();
    Object.assign(this.formValues[block] ??= {}, record);
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.regionBlocks[region] === block) group.patchValue(record, { emitEvent: false });
    }
__RECORD_STATES__  }'''.replace('__RECORD_STATES__', '    this.stateRecord(block); // Forms WHEN-NEW-RECORD-INSTANCE / POST-QUERY állapotai\n' if w.get('record_states') else ''))
    else:
        result.append('''  private value(_block: string, _key: string): unknown {
    return null;
  }''')
    if w['lovs']:
        cases = ''.join(f"      case {json.dumps(lov)}: request = this.{e['call']}(body); break;\n" for lov, e in w['lovs'].items())
        result.append('''  private searchLov(ownId: string, lov: string, query: string, requestId: number): boolean {
    const endpoint = this.lovEndpoints[lov];
    if (!endpoint) return false;
    const parameters: Record<string, string> = {};
    for (const bind of endpoint.binds) {
      const value = this.wireText(bind.block, bind.key, this.value(bind.block, bind.key));
      if (value !== null) parameters[bind.source] = value;
    }
    const body = { term: query || null, parameters, limit: 50 };
    let request: Observable<unknown>;
    switch (lov) {
__CASES__      default: return false;
    }
    request.subscribe({
      next: response => {
        const rows = this.payload<{ rows?: Record<string, unknown>[] }>(response).rows ?? [];
        this.setLovSuggestions(ownId, rows.map(row => this.lovChoice(ownId, endpoint.columns, row)), requestId);
      },
      error: () => this.setLovSuggestions(ownId, [], requestId), // WFF.err már jelezte
    });
    return true;
  }'''.replace('__CASES__', cases))
        result.append('''  private lovChoice(ownId: string, columns: readonly { column: string; returnItem: string }[], row: Record<string, unknown>): __P__LovChoice {
    const own = columns.find(c => c.returnItem === ownId)?.column ?? columns[0]?.column ?? Object.keys(row)[0] ?? '';
    const raw = row[own];
    const value = typeof raw === 'number' ? raw : raw === null || raw === undefined ? null : String(raw);
    const shown = (columns.length ? columns.map(c => row[c.column]) : [raw]).filter(v => v !== null && v !== undefined && v !== '');
    const returnValues: Record<string, unknown> = {};
    for (const c of columns) if (c.returnItem) returnValues[c.returnItem] = row[c.column];
    return { label: shown.map(v => String(v)).join(' – '), value, returnValues };
  }'''.replace('__P__', p))
    if runtime:
        from .screen_emulation import runtime_hooks
        return result + runtime_hooks(w)
    if w['actions']:
        selections = ''.join(f"    if (this.{prop}Selection) records[{json.dumps(block)}] = {{ ...this.{prop}Selection }};\n" for block, prop in w['tables'])
        form_copy = ('    for (const [block, values] of Object.entries(this.formValues)) records[block] = { ...values };\n' if form_values else '')
        result.append('''  /** Gomb a generált akció-végponton: aktuális rekordok Oracle nevekkel, a válasz visszaírva.
   *  answers: az eddigi alert-válaszok (a kód újrafut, és ezeket kapja a SHOW_ALERT).__RESUME_DOC__ */
  private runAction(ownId: string, answers: readonly number[] = []__RESUME_ARG__): boolean {
    const call = this.actionEndpoints[ownId];
    if (!call) return false;
    const records: Record<string, Record<string, unknown>> = {};
__FORMS____SELECTIONS__    const blocks: Record<string, Record<string, string | null>> = {};
    for (const [block, values] of Object.entries(records)) {
      const names = this.oracleNames[block] ?? {};
      blocks[block] = Object.fromEntries(Object.entries(values).filter(([key]) => key in names).map(([key, value]) => [names[key], this.wireText(block, key, value)]));
    }
__PARAMETERS__    call({ blocks, parameters__PARAMETERS_VALUE____QUERY_REQUEST__ }).subscribe({
      next: response => {
__QUERY_RESPONSE__
        const result = this.payload<__P__ActionResult>(response);
        const alert = result.commands?.find(command => command[0] === 'SHOW_ALERT');
        if (alert) {
          // Forms SHOW_ALERT: a kérés munkája visszagörgetve; a válasszal a kód elölről fut.
          this.askAlert(alert, choice => this.runAction(ownId, [...answers, choice]__RESUME_PASS__));
          return;
        }
__COMMIT_POINT__        if (result.globals) this.rememberGlobals(result.globals);
        for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyOracleValues(block, values);
        this.runCommands(result.commands ?? []);
        if (result.messages?.length) this.toast.success('Üzenet', result.messages.join(' '), true, TOAST_LIFE.success);
        else if (ownId !== __INIT__) this.toast.success('Kész', 'A művelet sikeresen lefutott.', true, TOAST_LIFE.success);
      },
      error: () => undefined, // WFF.err már jelezte
    });
    return true;
  }'''.replace('__FORMS__', form_copy).replace('__SELECTIONS__', selections).replace('__P__', p)
            .replace('__RESUME_DOC__', '\n   *  resume: mentési pont után a folytatás (FRM.RESUME; COMMIT_FORM a kód közepén).' if w.get('commit_points') else '')
            .replace('__RESUME_ARG__', ', resume = 0' if w.get('commit_points') else '')
            .replace('__RESUME_PASS__', ', resume' if w.get('commit_points') else '')
            .replace('__PARAMETERS__', ('    const parameters: Record<string, string> = { ...this.requestContext(answers), ...(resume ? { \'FRM.RESUME\': String(resume) } : {}) };\n'
                                        if w.get('commit_points') else ''))
            .replace('__PARAMETERS_VALUE__', '' if w.get('commit_points') else ': this.requestContext(answers)')
            .replace('__COMMIT_POINT__', '''        const point = result.commands?.find(command => command[0] === 'FRM_COMMIT');
        if (point) {
          // COMMIT_FORM a kód közepén: a mentés előtti értékek a képernyőre, mentés (a backend a mentési pontig
          // újrafuttatja a gomb kódját ugyanebben a tranzakcióban), majd a kód folytatása a pont után.
          if (result.globals) this.rememberGlobals(result.globals);
          for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyChanged(block, values);
          this.formsCommit({ action: ownId, actionBlocks: blocks, actionParameters: { ...parameters, 'FRM.COMMIT_POINT': point[1] ?? '', 'FRM.COMMIT_STATE': point[2] ?? '' } },
                           () => this.runAction(ownId, [], Number(point[1])));
          return;
        }
''' if w.get('commit_points') else '')
            .replace('__INIT__', json.dumps(w.get('init') or '@INIT'))
            .replace('__QUERY_REQUEST__', ', ...(this.queryActionBlocks[ownId] ? { offset: 0, limit: ' + str(QUERY_LIMIT) + ' } : {})'
                     if w.get('query_actions') else '')
            .replace('__QUERY_RESPONSE__', '''        const target = this.queryActionBlocks[ownId];
        if (target) {
          const page = this.payload<__P__Page>(response);
          if (page.rows != null) {
            this.activeQueryActions[target] = ownId;
            this.showRows(target, page.rows);
            if (!page.rows.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, TOAST_LIFE.warning);
          }
          if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, TOAST_LIFE.warning);
          return;
        }'''.replace('__P__', p) if w.get('query_actions') else ''))
        apply_body = ('''    const names = this.oracleNames[block] ?? {};
    const keys = Object.fromEntries(Object.entries(names).map(([key, oracle]) => [oracle, key]));
    const record = Object.fromEntries(Object.entries(values).filter(([oracle]) => oracle in keys).map(([oracle, value]) => [keys[oracle], value]));
    this.showRecord(block, record);''' if form_values else '    void block; void values;')
    if w['actions'] or w.get('commit'):
        apply_body = ('''    const names = this.oracleNames[block] ?? {};
    const keys = Object.fromEntries(Object.entries(names).map(([key, oracle]) => [oracle, key]));
    const record = Object.fromEntries(Object.entries(values).filter(([oracle]) => oracle in keys).map(([oracle, value]) => [keys[oracle], value]));
    this.showRecord(block, record);''' if form_values else '    void block; void values;')
        result.append('''  private applyOracleValues(block: string, values: Record<string, string | null>): void {
__BODY__
  }'''.replace('__BODY__', apply_body))
        from .screen_emulation import emulation_methods
        result += emulation_methods(w, form_values)
    return result


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
             'A komponens a `ServiceBase`-ből öröklődik. Minden végpontnak saját metódusa van, a céges mintára: '
             "`this.http.<ige>(this.url('<végpont>'))` és `pipe(catchError(...))`, amelyben `WFF.err('Hiba', error)` jelez. "
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

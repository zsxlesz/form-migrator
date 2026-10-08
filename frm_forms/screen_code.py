"""The generated screen's code (4.27): only the frame, no Forms emulation.

The component extends the company ServiceBase and has:

- the FormBlock structures of its regions, and the fields of its wf-tables (columns, rows, selected row);
- one method per backend endpoint (this.http + WFF.debug / WFF.err), in the company pattern;
- onFormGroupGenerated: the FormGroup of every FormBlock region;
- on<Item>Click() for every button: the HTTP request of the button, built simply from the form values (its backend
  action, the query of the block it queries), or its navigation, or a TODO with the original Forms code;
- save() when the screen has a save (COMMIT_FORM) endpoint: the request with a TODO for the changes.

What the Forms runtime did beyond that (item states, LOV return values, alerts, :GLOBAL values, the record buffer,
the Forms commands of the backend) is the developer's: the button has a TODO, MIGRATION_NOTES.md lists the rest.
"""
from __future__ import annotations

import re

from .common import name
from .ts_code import IDENTIFIER, key as ts_key, member, record, sq, tsv

QUERY_LIMIT = 200
CONTROL = {'text', 'textarea', 'password', 'display', 'number', 'date', 'datetime', 'checkbox', 'select', 'radio',
           'autocomplete'}
# Focus moves of a button: no web equivalent, nothing to do.
NAVIGATION_STEPS = {'goItem', 'nextRecord', 'previousRecord', 'firstRecord', 'lastRecord', 'nextBlock', 'previousBlock',
                    'nextItem', 'previousItem', 'listValues', 'enterQuery'}
# Members of the component (and of ServiceBase) the endpoint methods must not shadow.
RESERVED = {'constructor', 'url', 'http', 'toast', 'toastLife', 'labels', 'router', 'route', 'modName', 'forms', 'structures', 'onFormGroupGenerated',
            'onRowAction', 'save', 'windowVisible', 'canvasVisible', 'activeContentCanvas'}
# Local names of a method: a region's values never take them.
LOCALS = {'res', 'row', 'error', 'body'}
LINE = 120  # a longer request is written one block per line


def pascal(text: str) -> str:
    result = name(re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').lower(), 'pascal') or 'X'
    return result if re.match(r'[A-Za-z]', result) else 'X' + result


def camel(text: str) -> str:
    result = pascal(text)
    return result[:1].lower() + result[1:]


class Body:
    """The statements of one method, and the regions whose form values they read."""

    def __init__(self):
        self.regions, self.lines = {}, []

    def local(self, region: str) -> str:
        if region not in self.regions:
            local = region if IDENTIFIER.fullmatch(region) and '$' not in region else camel(region)
            while local in LOCALS or local in self.regions.values():
                local += '2'
            self.regions[region] = local
        return self.regions[region]

    def text(self) -> str:
        head = [f'const {local} = this.forms[{sq(region)}]?.getRawValue() ?? {{}};' for region, local in self.regions.items()]
        return '\n'.join('    ' + line if line else '' for line in head + self.lines)


class ScreenCode:
    """Collects the fields, methods and imports of one generated component."""

    def __init__(self, plan, forms, tables, wiring, config, navigations, manual_navs, sources):
        self.plan, self.forms, self.tables, self.w, self.config = plan, forms, tables, wiring or {}, config
        self.navigations, self.manual_navs, self.sources = navigations, manual_navs, sources
        self.core, self.rxjs, self.angular_forms = {'Component'}, set(), set()
        self.methods, self.called = [], set()
        self.taken = set(RESERVED) | {e['method'] for e in self.w.get('endpoints', [])}
        api = self.w.get('api') or {}
        self.api_fields = {b: e['fields'] for b, e in api.get('blocks', {}).items()}
        self.api_actions = api.get('actions', {})
        self.envelope = bool(self.w.get('envelope'))
        # Rendered form controls: Oracle owner -> (region, control key, item)
        self.controls = {}
        for section in forms:
            for item in section['items']:
                if item['widget'] in CONTROL and not item.get('spacer'):
                    self.controls[item['owner']] = (section['property'], item['key'], item)
        self.by_key = {(o.split('.', 1)[0], c[1]): o for o, c in self.controls.items()}
        self.table_blocks = {s['block']: s for s in tables}
        self.form_blocks = {}
        for section in forms:
            self.form_blocks.setdefault(section['block'], []).append(section['property'])
        self.queries = dict(self.w.get('queries', {}))
        self.click = {}
        buttons = [i['owner'] for s in forms + tables for i in s['items'] if i['widget'] == 'button']
        short = [o.split('.', 1)[1] for o in buttons]
        for owner in buttons:
            item = owner.split('.', 1)[1]
            self.click[owner] = self.unique('on' + pascal(item if short.count(item) == 1 else owner) + 'Click')

    def unique(self, base: str) -> str:
        result, n = base, 2
        while result in self.taken:
            result, n = base + str(n), n + 1
        self.taken.add(result)
        return result

    def table_name(self, block: str) -> str:
        return camel(block)

    # ---------------------------------------------------------------- values of the screen

    def owner_value(self, owner: str, body: Body) -> str | None:
        """A screen value by its Oracle name: a form control, or a column of a table's selected row."""
        if owner in self.controls:
            region, key, _ = self.controls[owner]
            return body.local(region) + member(key)
        block, item = owner.split('.', 1)
        field = self.api_fields.get(block, {}).get(item)
        if block in self.table_blocks and field:
            return f'this.{self.table_name(block)}Selection?.[{sq(field)}]'
        return None

    def key_value(self, block: str, key: str, body: Body) -> str | None:
        """A screen value by its control key (the criteria of a search, the parameters of a navigation)."""
        if (block, key) in self.by_key:
            return self.owner_value(self.by_key[(block, key)], body)
        items = {k: n for n, k in self.w.get('screen_keys', {}).get(block, {}).items()}
        return self.owner_value(block + '.' + items[key], body) if key in items else None

    # ---------------------------------------------------------------- endpoints

    def endpoint_method(self, e: dict) -> str:
        self.rxjs.update({'EMPTY', 'catchError', 'tap'})
        url = 'this.url(' + sq(e['url']) + ')'
        if e['http'] == 'get':
            signature, call = f'offset = 0, limit = {QUERY_LIMIT}', f'this.http.get<any>({url}, {{ params: {{ offset, limit }} }})'
        elif e['http'] == 'delete':
            signature, call = 'body: unknown', f'this.http.delete<any>({url}, {{ body }})'
        else:
            signature, call = 'body: unknown', f"this.http.{e['http']}<any>({url}, body)"
        return (f"  {e['method']}({signature}) {{\n    return {call}.pipe(\n"
                f"      tap(res => WFF.debug(this.modName + {sq('.' + e['method'])}, res)),\n"
                "      catchError(error => {\n        WFF.err('Hiba', error);\n        return EMPTY;\n      }),\n    );\n  }")

    @staticmethod
    def request(call: str, entries: list[tuple[str, str]]) -> list[str]:
        """this.<call>({ ... }): on one line, or one entry per line when long."""
        line = f'this.{call}({{ ' + ', '.join(k + ': ' + v for k, v in entries) + ' })'
        if len(line) <= LINE:
            return [line]
        return [f'this.{call}({{'] + ['  ' + k + ': ' + v + ',' for k, v in entries] + ['})']

    def subscribe(self, request: list[str], block: str) -> list[str]:
        """The request of a query: its rows into the block's table, or the first row into the block's form."""
        show = []
        if self.envelope:
            show.append('// TODO: a válasz RestResponseDto-borítékban jön: a rows a boríték adatmezőjében van.')
        if block in self.table_blocks:
            show.append(f'this.{self.table_name(block)}Rows = res.rows ?? [];')
        elif block in self.form_blocks:
            for region in self.form_blocks[block]:
                pairs = [(key, self.api_fields.get(block, {}).get(owner.split('.', 1)[1], key))
                         for owner, (r, key, _) in self.controls.items() if r == region]
                if all(key == field for key, field in pairs):
                    show.append(f'this.forms[{sq(region)}]?.patchValue(res.rows?.[0] ?? {{}});')
                else:
                    if 'const row = res.rows?.[0] ?? {};' not in show:
                        show.append('const row = res.rows?.[0] ?? {};')
                    show.append(f'this.forms[{sq(region)}]?.patchValue({{ ' + ', '.join(
                        f'{ts_key(key)}: row{member(field)}' for key, field in pairs) + ' });')
        if not [line for line in show if not line.startswith('//')]:
            return [f'// TODO: a(z) {block} blokk nincs a képernyőn: az eredményt kézzel kell megjeleníteni.'] + request[:-1] + [request[-1] + '.subscribe();']
        return request[:-1] + [request[-1] + '.subscribe(res => {'] + ['  ' + line for line in show] + ['});']

    def query(self, block: str, body: Body) -> list[str]:
        """The search of a block (Forms EXECUTE_QUERY), its criteria from the screen."""
        q = self.queries[block]
        self.called.add(q['call'])
        if q['kind'] == 'list':
            return self.subscribe([f"this.{q['call']}()"], block)
        criteria, todo = [], []
        for c in q.get('criteria', []):
            value = None if c.get('context') else self.key_value(c['block'], c['key'], body)
            criteria.append(f"{ts_key(c['field'])}: {value or 'null'}")
            if not value:
                todo.append(':' + c['context'] if c.get('context') else c['block'] + '.' + c['key'])
        head = ['// TODO: a feltétel értéke: ' + ', '.join(todo) + '.'] if todo else []
        entries = [('criteria', '{ ' + ', '.join(criteria) + ' }' if criteria else '{}'), ('offset', '0'), ('limit', str(QUERY_LIMIT))]
        return head + self.subscribe(self.request(q['call'], entries), block)

    def action(self, owner: str, body: Body, init: bool = False) -> list[str]:
        """The backend action of a button: the values its code reads, by their Oracle names."""
        call = self.w['actions'][owner]
        self.called.add(call)
        spec = self.api_actions.get(owner, {})
        reads = None if init else spec.get('reads')
        blocks, missing = {}, []
        for source in reads or []:
            value = self.owner_value(source, body)
            if not value:
                missing.append(source)
            block, item = source.split('.', 1)
            blocks.setdefault(block, []).append(ts_key(item) + ': ' + (value or 'null'))
        parameters = spec.get('parameters') or []
        head = []
        if reads is None and not init:
            head.append('// TODO: a kérés mezőértékei: blocks: { BLOKK: { MEZO: érték } }.')
        if missing:
            head.append('// TODO: nincs a képernyőn: ' + ', '.join(missing) + '.')
        if parameters:
            head.append('// TODO: a :PARAMETER / :GLOBAL értékek: ' + ', '.join(parameters) + '.')
        entries = [('blocks', '{ ' + ', '.join(ts_key(b) + ': { ' + ', '.join(v) + ' }' for b, v in blocks.items()) + ' }' if blocks else '{}'),
                   ('parameters', '{ ' + ', '.join(sq(p) + ': null' for p in parameters) + ' }' if parameters else '{}')]
        target = (self.w.get('query_actions') or {}).get(owner)
        if target:
            entries += [('offset', '0'), ('limit', str(QUERY_LIMIT))]
            return head + self.subscribe(self.request(call, entries), target)
        request = self.request(call, entries)
        head.append('// TODO: a válasz feldolgozása (res.blocks: a visszaírt mezők, res.messages: az üzenetek).')
        return head + request[:-1] + [request[-1] + '.subscribe();']

    # ---------------------------------------------------------------- buttons

    def steps(self, owner: str, steps: list, body: Body) -> list[str] | None:
        """A button's recognised Forms steps: its queries, its save, its windows; None when one has no plain equivalent."""
        block, lines = owner.split('.', 1)[0], []
        controls = self.plan.get('window_controls') or {}
        for step in steps:
            op = step['op']
            if op == 'goBlock':
                block = step['block'].upper()
            elif op in NAVIGATION_STEPS:
                continue
            elif op == 'executeQuery' and block in self.queries:
                lines += self.query(block, body)
            elif op == 'commit' and self.w.get('commit'):
                lines.append('this.save();')
            elif op in {'showWindow', 'hideWindow'} and step['window'].upper() in controls.get('windows', {}):
                lines.append(f"this.windowVisible[{sq(step['window'].upper())}] = {'true' if op == 'showWindow' else 'false'};")
            elif op in {'showCanvas', 'hideCanvas'} and step['canvas'].upper() in controls.get('canvases', {}):
                canvas = step['canvas'].upper()
                lines.append(f"this.canvasVisible[{sq(canvas)}] = {'true' if op == 'showCanvas' else 'false'};")
                surface = next((s for s in self.plan['surfaces'] if s['name'] == canvas), None)
                if op == 'showCanvas' and surface and surface['window'] in controls.get('content', {}) and surface['type'].lower() == 'content':
                    lines.append(f"this.activeContentCanvas[{sq(surface['window'])}] = {sq(canvas)};")
                if op == 'showCanvas' and surface and surface['window'] in controls.get('windows', {}):
                    lines.append(f"this.windowVisible[{sq(surface['window'])}] = true;")
            else:
                return None
        return lines

    def original(self, owner: str, todo: str, code: str | None = None) -> list[str]:
        source = (self.sources.get(owner, '') if code is None else code).strip()
        lines = ['// TODO: ' + todo]
        if source:
            lines += ['//#region Eredeti Forms-kód'] + ['//' + (' ' + l if l else '') for l in source.split('\n')] + ['//#endregion']
        return lines

    def button(self, owner: str) -> None:
        body, note = Body(), ''
        action = next((a for a in self.plan['actions'] if a['owner'] == owner), {})
        called = set(self.called)
        recognised = self.steps(owner, action['steps'], body) if action.get('steps') else None
        if not recognised:
            body, self.called = Body(), called  # a partly recognised button: nothing of it
        if owner in self.navigations:
            n = self.navigations[owner]
            params = [ts_key(p['name']) + ': ' + ((self.key_value(p['block'], p['key'], body) or 'null') if 'block' in p else sq(p['value']))
                      for p in n['params']]
            body.lines = [f"void this.router.navigate([{sq(n['route'])}]" + (', { queryParams: { ' + ', '.join(params) + ' } }' if params else '') + ');']
            note = f"Forms {n['call']}('{n['form']}'): navigáció."
        elif owner in self.manual_navs:
            body.lines = self.original(owner, 'összetett formhívás: a célt és a paramétereket kézzel kell megírni, például '
                                              "void this.router.navigate(['/<útvonal>'], { queryParams: { ... } });",
                                       self.manual_navs[owner]['code'])
        elif recognised:
            body.lines = recognised
        elif owner in self.w.get('actions', {}):
            body.lines = self.action(owner, body)
            note = 'a gomb kódja a backendben fut.'
        else:
            body.lines = self.original(owner, 'a gomb kódját kézzel kell átültetni.')
        self.methods.append(f'  // {owner}' + (': ' + note if note else '') + '\n'
                            + f'  protected {self.click[owner]}(): void {{\n' + body.text() + '\n  }')

    # ---------------------------------------------------------------- save (Forms COMMIT_FORM)

    def save(self) -> None:
        commit = self.w.get('commit')
        if not commit:
            return
        self.called.add(commit['call'])
        regions = [r for b in commit['blocks'] for r in self.form_blocks.get(b, [])]
        entries = [(ts_key(spec['request']), '{ inserted: [], updated: [], deleted: [] }') for spec in commit['blocks'].values()]
        request = self.request(commit['call'], entries)
        lines = ['// TODO: a blokkok változásai a DTO mezőivel: inserted: [új rekord], updated: [{ original, value }], deleted: [rekord].',
                 '// Az űrlap értékei: ' + ', '.join(f'this.forms[{sq(r)}]?.getRawValue()' for r in regions) + '.',
                 *request[:-1], request[-1] + '.subscribe();']
        self.methods.append('  // Mentés (Forms COMMIT_FORM): a változások egy kérésben; a backend egy tranzakcióban, Forms-sorrendben ment.\n'
                            '  protected save(): void {\n' + '\n'.join('    ' + l for l in lines) + '\n  }')

    # ---------------------------------------------------------------- assembly

    def build(self) -> None:
        for owner in self.click:
            self.button(owner)
        self.save()
        row_actions = [o for s in self.tables for o in (i['owner'] for i in s['items'] if i['widget'] == 'button')]
        if row_actions:
            cases = [f'      case {sq(o)}: this.{self.click[o]}(); break;' for o in row_actions]
            self.methods.append('  // Egy táblázatsor gombja (a sor már ki van választva).\n  protected onRowAction(ownId: string): void {\n'
                                '    switch (ownId) {\n' + '\n'.join(cases) + '\n    }\n  }')

    def class_fields(self, tab_fields: list, labels: dict, toast_symbol: str, form_type: str, structures: dict) -> list[str]:
        """The component's fields in their order (toast, http, labels, structures, tables, windows)."""
        life = self.config['toast_life_ms']
        self.core.add('inject')
        # The company toast of every component (the developer's messages); the frame itself does not call it.
        fields = ['  protected readonly toast = inject(' + toast_symbol + ');\n'
                  f"  protected readonly toastLife = {{ success: {life['success']}, warning: {life['warning']}, danger: {life['danger']} }};"]
        if self.w.get('endpoints'):
            fields[-1] += '\n  private readonly http = inject(HttpClient);'
        if labels:
            fields.append('  protected readonly labels = ' + record(labels) + ';')
        fields.extend(tab_fields)
        if self.forms:
            self.angular_forms.add('FormGroup')
            from .ts_code import nested
            fields.append('  // A FormBlock-régiók FormGroupjai (onFormGroupGenerated).\n  protected readonly forms: Record<string, FormGroup> = {};')
            fields.append('  protected readonly structures: Record<string, ' + form_type + '[]> = ' + nested(structures) + ';')
        for section in self.tables:
            t = self.table_name(section['block'])
            columns = [i for i in section['items'] if i['widget'] not in {'button', 'image', 'unsupported', 'tree'} and not i.get('spacer')]
            weights = [max(1, i['width']) for i in columns]
            total = sum(weights) or 1
            cols = [{'field': self.api_fields.get(section['block'], {}).get(i['owner'].split('.', 1)[1], i['key']), 'header': i['label'],
                     'width': str(round(w / total * 100, 2)) + '%'} for i, w in zip(columns, weights)]
            fields.append(f"  // {section['block']}: a táblázat oszlopai, sorai (a backend DTO-mezőivel) és a kiválasztott sor.\n"
                          f'  protected readonly {t}Columns = [\n' + ''.join('    ' + tsv(c) + ',\n' for c in cols) + '  ];\n'
                          f'  protected {t}Rows: Record<string, unknown>[] = [];\n'
                          f'  protected {t}Selection: Record<string, unknown> | null = null;')
            actions = [{'ownId': i['owner'], 'label': i['label'], **({} if i['enabled'] else {'disabled': True})}
                       for i in section['items'] if i['widget'] == 'button']
            if actions:
                fields.append(f'  protected readonly {t}Actions = ' + tsv(actions) + ';')
        controls = self.plan.get('window_controls') or {}
        if controls.get('windows'):
            fields.append('  // Az ablakok, canvasok láthatósága (Forms SHOW_WINDOW / SHOW_VIEW).\n'
                          '  protected readonly windowVisible: Record<string, boolean> = ' + record(controls['windows']) + ';')
        if controls.get('content'):
            fields.append('  protected readonly activeContentCanvas: Record<string, string> = ' + record(controls['content']) + ';')
        if controls.get('canvases'):
            fields.append('  protected readonly canvasVisible: Record<string, boolean> = ' + record(controls['canvases']) + ';')
        return fields

    def form_group_method(self) -> str | None:
        if not self.forms:
            return None
        return ('  // A FormBlock elkészítette a régió FormGroupját.\n'
                '  protected onFormGroupGenerated(region: string, group: FormGroup): void {\n    this.forms[region] = group;\n  }')

    def constructor(self) -> str:
        lines = ['    super();']
        init = (self.w.get('api') or {}).get('init')
        if init and init in self.w.get('actions', {}):
            lines.append('    // Indításkor (Forms WHEN-NEW-FORM-INSTANCE): ' + init + '.')
            lines += ['    ' + l for l in self.action(init, Body(), init=True)]
        return '  constructor() {\n' + '\n'.join(lines) + '\n  }'

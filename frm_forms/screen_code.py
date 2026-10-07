"""The generated screen's own code (4.26): plain methods for what this screen uses, no shared runtime.

The component extends the company ServiceBase and carries everything it needs itself, so a developer changes one
screen without touching a shared file:

- one method per backend endpoint (this.http + WFF.debug / WFF.err), in the company pattern;
- onFormGroupGenerated keeps the FormGroup of every FormBlock region;
- query<Block>() for a block the screen queries (Forms EXECUTE_QUERY), show<Block>() / fill<Block>() for the result;
- search<Lov>() for a LOV field, choose<Lov>() for its return values;
- on<Item>Click() for every button: its recognised steps, its backend action, its navigation, or a TODO with the
  original Forms code;
- save() / newRecord() / deleteRecord() for the Forms save (COMMIT_FORM);
- a few small helpers (value, text, blocks, parameters ...) only where a method above needs them.

What the Forms runtime did beyond that (alert dialogs, :GLOBAL storage, screen and save points, the Forms commands the
backend returns) is not emulated: the method has a TODO and the commands are logged.
"""
from __future__ import annotations

import re

from .angular_single import Code
from .common import name
from .ts_code import key as ts_key, member, record, sq, tsv

QUERY_LIMIT = 200
CONTROL = {'text', 'textarea', 'password', 'display', 'number', 'date', 'datetime', 'checkbox', 'select', 'radio',
           'autocomplete'}
NAVIGATION_STEPS = {'goBlock', 'goItem', 'nextRecord', 'previousRecord', 'firstRecord', 'lastRecord', 'nextBlock',
                    'previousBlock', 'nextItem', 'previousItem', 'listValues', 'enterQuery'}
# Members of the component (and of ServiceBase) the endpoint methods must not shadow.
RESERVED = {'constructor', 'url', 'http', 'toast', 'toastLife', 'labels', 'router', 'modName', 'forms', 'structures', 'items',
            'value', 'text', 'blocks', 'parameters', 'showBlocks', 'showResult', 'data', 'suggest', 'onFormGroupGenerated',
            'onRowAction', 'save', 'newRecord', 'deleteRecord', 'originals', 'deleted', 'windowVisible', 'canvasVisible',
            'activeContentCanvas', 'destroyRef', 'setItemState', 'setItemValue', 'stateValue', 'isNull', 'cmp', 'route'}

TYPES = {
    'Page': 'interface Page {\n  rows?: Record<string, unknown>[] | null;\n  messages?: string[];\n}',
    'ActionResult': 'interface ActionResult {\n  blocks?: Record<string, Record<string, string | null>>;\n  messages?: string[];\n'
                    '  commands?: (string | null)[][];\n}',
    'CommitResult': 'interface CommitResult extends ActionResult {\n  [rows: string]: unknown;\n}',
}

HELPERS = {
    'value': '''  // A mező értéke a képernyőn (a régió FormGroupjából).
  private value(region: string, key: string): unknown {
    return this.forms[region]?.get(key)?.value;
  }''',
    'text': '''  // Érték a backendnek (Oracle-szöveg): üres -> null, dátum -> helyi idő ISO-formában.
  private text(value: unknown): string | null {
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) {
      const p = (n: number) => String(n).padStart(2, '0');
      return `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())}T${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`;
    }
    return String(value);
  }''',
    'parameters': '''  // A Forms :PARAMETER értékei az URL-ből (?NEV=érték). TODO: ha a backend :GLOBAL vagy :SYSTEM értéket olvas,
  // azt is itt kell átadni, például parameters['GLOBAL.FELHASZNALO'] = ... (lásd MIGRATION_NOTES.md).
  private parameters(): Record<string, string> {
    const parameters: Record<string, string> = {};
    const hash = window.location.hash;
    const query = window.location.search || (hash.includes('?') ? hash.slice(hash.indexOf('?')) : '');
    new URLSearchParams(query).forEach((value, name) => { parameters['PARAMETER.' + name.toUpperCase()] = value; });
    return parameters;
  }''',
    'showBlocks': '''  // A backend által visszaírt mezőértékek (Oracle-nevekkel) a képernyőre.
  private showBlocks(blocks: Record<string, Record<string, string | null>> | undefined): void {
    for (const [block, values] of Object.entries(blocks ?? {})) {
      for (const [item, value] of Object.entries(values)) {
        const target = this.items[block + '.' + item];
        if (target) this.forms[target[0]]?.get(target[1])?.setValue(target[2] === undefined ? value : value === target[2], { emitEvent: false });
      }
    }
  }''',
    'showResult': '''  // Egy gomb (vagy az indítás) válasza: a visszaírt mezők és az üzenetek.
  private showResult(result: ActionResult, done: string): void {
    this.showBlocks(result.blocks);
    if (result.messages?.length) this.toast.success('Üzenet', result.messages.join(' '), true, this.toastLife.success);
    else if (done) this.toast.success('Kész', done, true, this.toastLife.success);
    // A backend Forms-utasításokat is visszaadhat (GO_BLOCK, EXECUTE_QUERY, SHOW_ALERT ...). A képernyő ezeket nem
    // futtatja: ahol kell, a gomb metódusában kell bekötni (MIGRATION_NOTES.md).
    if (result.commands?.length) console.warn('Forms-utasítások (kézi bekötés):', result.commands);
  }''',
    'suggest': '''  // A LOV találatai a mező legördülőjébe (FormBlock suggestions).
  private suggest(ownId: string, suggestions: { label: string; value: unknown }[]): void {
    for (const fields of Object.values(this.structures)) {
      const field = fields.find(f => f['ownId'] === ownId);
      if (field) field['suggestions'] = suggestions;
    }
  }''',
    'data': '''  // A céges válaszboríték (RestResponseDto) adata. TODO: igazítsd a boríték tényleges mezőnevéhez.
  private data<T>(response: unknown): T {
    if (response && typeof response === 'object') {
      for (const field of ['data', 'result', 'payload', 'body', 'content']) {
        const value = (response as Record<string, unknown>)[field];
        if (value && typeof value === 'object') return value as T;
      }
    }
    return response as T;
  }''',
    'setItemState': '''  // Forms SET_ITEM_PROPERTY: a mező állapota a FormBlock-definícióban és a FormGroupban.
  private setItemState(ownId: string, state: { enabled?: boolean; visible?: boolean; required?: boolean; editable?: boolean }): void {
    for (const fields of Object.values(this.structures)) {
      const field = fields.find(f => f['ownId'] === ownId);
      if (!field) continue;
      if (state.enabled !== undefined) field['disabled'] = !state.enabled;
      if (state.visible !== undefined) field['invisible'] = !state.visible;
      if (state.required !== undefined) field['validator'] = state.required;
      if (state.editable !== undefined) field['readonly'] = !state.editable;
    }
    const target = this.items[ownId];
    const control = target ? this.forms[target[0]]?.get(target[1]) : null;
    if (!control) return;
    if (state.enabled === true) control.enable({ emitEvent: false });
    if (state.enabled === false) control.disable({ emitEvent: false });
    if (state.required !== undefined) {
      if (state.required) control.addValidators(Validators.required); else control.removeValidators(Validators.required);
      control.updateValueAndValidity({ emitEvent: false });
    }
  }''',
    'stateValue': '''  // Egy mező értéke a Forms-feltételekhez (a checkbox a Forms-értékével).
  private stateValue(ownId: string): unknown {
    const target = this.items[ownId];
    const value = target ? this.value(target[0], target[1]) : null;
    if (target?.[2] !== undefined && typeof value === 'boolean') return value ? target[2] : target[3] ?? null;
    return value === undefined || value === '' ? null : value;
  }''',
    'setItemValue': '''  // Értékadás egy mezőnek (Forms :BLOKK.MEZO := ...).
  private setItemValue(ownId: string, value: unknown): void {
    const target = this.items[ownId];
    if (target) this.forms[target[0]]?.get(target[1])?.setValue(target[2] === undefined ? value : value === target[2], { emitEvent: false });
  }''',
    'isNull': '''  private isNull(value: unknown): boolean {
    return value === null || value === undefined || value === '';
  }''',
    'cmp': '''  // Forms-összehasonlítás: NULL-lal mindig hamis; számnál számként, különben szövegként.
  private cmp(left: unknown, op: string, right: unknown): boolean {
    if (this.isNull(left) || this.isNull(right)) return false;
    const numeric = typeof left === 'number' || typeof right === 'number';
    const order = numeric ? Math.sign(Number(left) - Number(right)) : String(left) < String(right) ? -1 : String(left) > String(right) ? 1 : 0;
    switch (op) {
      case '=': return order === 0;
      case '!=': return order !== 0;
      case '<': return order < 0;
      case '>': return order > 0;
      case '<=': return order <= 0;
      default: return order >= 0;
    }
  }''',
}
# A helper's own dependencies.
NEEDS = {'showBlocks': {'items'}, 'showResult': {'showBlocks'}, 'stateValue': {'items', 'value'}, 'setItemValue': {'items'},
         'setItemState': {'items'}, 'cmp': {'isNull'}}


def pascal(text: str) -> str:
    result = name(re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').lower(), 'pascal') or 'X'
    return result if re.match(r'[A-Za-z]', result) else 'X' + result


def camel(text: str) -> str:
    result = pascal(text)
    return result[:1].lower() + result[1:]


def comment(text: str, indent: str) -> str:
    return '\n'.join(indent + '//' + (' ' + line if line else '') for line in text.split('\n'))


class ScreenCode:
    """Collects the fields, methods, helpers and imports of one generated component."""

    def __init__(self, plan, forms, tables, wiring, config, navigations, manual_navs, states, sources):
        self.plan, self.forms, self.tables, self.w, self.config = plan, forms, tables, wiring, config
        self.navigations, self.manual_navs, self.states, self.sources = navigations, manual_navs, states, sources
        self.core, self.rxjs, self.angular_forms = {'Component', 'inject'}, set(), set()
        self.types, self.needs, self.subscriptions = set(), set(), {}  # region -> [statement]
        self.fields, self.methods, self.todo = [], [], []
        self.taken = set(RESERVED) | {e['method'] for e in (wiring or {}).get('endpoints', [])}
        self.api_fields = {b: e['fields'] for b, e in ((wiring or {}).get('api') or {}).get('blocks', {}).items()}
        self.envelope = bool((wiring or {}).get('envelope'))
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
        self.click = {}
        buttons = [i['owner'] for s in forms + tables for i in s['items'] if i['widget'] == 'button']
        short = [o.split('.', 1)[1] for o in buttons]
        for owner in buttons:
            item = owner.split('.', 1)[1]
            self.click[owner] = self.unique('on' + pascal(item if short.count(item) == 1 else owner) + 'Click')
        self.queries = dict((wiring or {}).get('queries', {}))
        self.query_method = {block: self.unique('query' + pascal(block)) for block in self.queries}
        self.show_method = {}
        self.fill_method = {}
        self.lov_search = {}
        self.later = []  # show/fill methods: after the methods that call them

    def unique(self, base: str) -> str:
        result, n = base, 2
        while result in self.taken:
            result, n = base + str(n), n + 1
        self.taken.add(result)
        return result

    def need(self, *helpers: str) -> None:
        for helper in helpers:
            if helper not in self.needs:
                self.needs.add(helper)
                self.need(*NEEDS.get(helper, ()))

    # ---------------------------------------------------------------- values of the screen

    def dto_field(self, owner: str, fallback: str) -> str:
        block, item = owner.split('.', 1)
        return self.api_fields.get(block, {}).get(item, fallback)

    def screen_value(self, block: str, key: str) -> str | None:
        """The text of a screen value for the backend: a form control, or the selected row of a table."""
        owner = self.by_key.get((block, key))
        if owner:
            region, control, item = self.controls[owner]
            self.need('value')
            if item['widget'] == 'checkbox':
                return f"(this.value({sq(region)}, {sq(control)}) ? {sq(item['checked'])} : {sq(item['unchecked'])})"
            self.need('text')
            return f'this.text(this.value({sq(region)}, {sq(control)}))'
        if block in self.table_blocks:
            names = {v: k for k, v in (self.w or {}).get('screen_keys', {}).get(block, {}).items()}
            field = self.api_fields.get(block, {}).get(names.get(key, ''), key)
            self.need('text')
            return f'this.text(this.{self.table_name(block)}Selection?.[{sq(field)}])'
        return None

    def table_name(self, block: str) -> str:
        return camel(block)

    # ---------------------------------------------------------------- endpoints

    def called(self) -> set:
        w = self.w or {}
        result = {q['call'] for q in w.get('queries', {}).values()} | {e['call'] for e in w.get('lovs', {}).values()}
        result |= set(w.get('actions', {}).values())
        if w.get('commit'):
            result.add(w['commit']['call'])
        return result

    def endpoint_method(self, e: dict) -> str:
        kind = e['kind']
        if e['method'] not in self.called():
            kind = 'other'  # the screen does not call it: the developer may
        if kind in {'search', 'list', 'lov'} or (kind == 'action' and e['target'] in (self.w.get('query_actions') or {})):
            result = 'Page'
        elif kind == 'action':
            result = 'ActionResult'
        elif kind == 'commit':
            result = 'CommitResult'
            self.types.add('ActionResult')
        else:
            result = 'unknown'
        if result != 'unknown':
            self.types.add(result)
        self.rxjs.update({'EMPTY', 'catchError', 'tap'})
        typed = 'unknown' if self.envelope else result
        url = 'this.url(' + sq(e['url']) + ')'
        if e['http'] == 'get':
            signature, call = f'offset = 0, limit = {QUERY_LIMIT}', f'this.http.get<{typed}>({url}, {{ params: {{ offset, limit }} }})'
        elif e['http'] == 'delete':
            signature, call = 'body: unknown', f'this.http.delete<{typed}>({url}, {{ body }})'
        else:
            signature, call = 'body: unknown', f"this.http.{e['http']}<{typed}>({url}, body)"
        unwrap = ''
        if self.envelope and result != 'unknown':
            self.rxjs.add('map')
            self.need('data')
            unwrap = f'\n      map(res => this.data<{result}>(res)),'
        return (f"  {e['method']}({signature}) {{\n    return {call}.pipe(\n"
                f"      tap(res => WFF.debug(this.modName + {sq('.' + e['method'])}, res)),{unwrap}\n"
                "      catchError(error => {\n        WFF.err('Hiba', error);\n        return EMPTY;\n      }),\n    );\n  }")

    # ---------------------------------------------------------------- queries

    def query(self, block: str, q: dict) -> str:
        call = q['call']
        if q['kind'] == 'list':
            request = f'this.{call}(0, {QUERY_LIMIT})'
        else:
            criteria = []  # (entry, TODO comment)
            for c in q.get('criteria', []):
                if c.get('context', '').startswith('PARAMETER.'):
                    self.need('parameters')
                    criteria.append((f"{ts_key(c['field'])}: this.parameters()[{sq(c['context'])}] ?? null", ''))
                elif c.get('context'):
                    criteria.append((f"{ts_key(c['field'])}: null", f"TODO: :{c['context']} értéke"))
                else:
                    value = self.screen_value(c['block'], c['key'])
                    criteria.append((f"{ts_key(c['field'])}: {value or 'null'}", '' if value else 'TODO: a feltétel értéke nincs a képernyőn'))
            if any(note for _, note in criteria):
                body = '{\n' + ''.join(f'        {entry},' + (f' // {note}' if note else '') + '\n' for entry, note in criteria) + '      }'
            else:
                body = '{ ' + ', '.join(entry for entry, _ in criteria) + ' }' if criteria else '{}'
            request = f'this.{call}({{ criteria: {body}, offset: 0, limit: {QUERY_LIMIT} }})'
        return (f'  // {block} lekérdezése (Forms EXECUTE_QUERY); a feltételek a képernyőről.\n'
                f'  protected {self.query_method[block]}(): void {{\n    {request}.subscribe(page => this.{self.show(block)}(page));\n  }}')

    def show(self, block: str) -> str:
        """The method that shows a query result (Page) of the block: the table rows, or the form's first record."""
        if block not in self.show_method:
            self.show_method[block] = self.unique('show' + pascal(block))
            self.types.add('Page')
            if block in self.table_blocks:
                t = self.table_name(block)
                lines = [f'    this.{t}Rows = page.rows ?? [];', f'    this.{t}Selection = null;',
                         f'    if (!this.{t}Rows.length) this.toast.warning(\'Nincs találat\', \'A lekérdezés nem adott vissza rekordot.\', true, this.toastLife.warning);']
            elif block in self.form_blocks:
                lines = [f'    this.{self.fill(block)}(page.rows?.[0] ?? null);',
                         "    if (!page.rows?.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, this.toastLife.warning);"]
            else:
                lines = [f'    // TODO: a(z) {block} blokk nincs a képernyőn: az eredményt kézzel kell megjeleníteni.', '    void page;']
            lines.append("    if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, this.toastLife.warning);")
            self.later.append(f'  private {self.show_method[block]}(page: Page): void {{\n' + '\n'.join(lines) + '\n  }')
        return self.show_method[block]

    def fill(self, block: str) -> str:
        """The method that puts one record (DTO) into the block's form controls; it is the original of the save."""
        if block not in self.fill_method:
            self.fill_method[block] = self.unique('fill' + pascal(block))
            self.originals()
            lines = [f'    this.originals[{sq(block)}] = row;']
            for region in self.form_blocks[block]:
                values = []
                for owner, (r, key, item) in self.controls.items():
                    if r != region:
                        continue
                    field = self.dto_field(owner, key)
                    if item['widget'] == 'checkbox':
                        values.append(f"{ts_key(key)}: row?.[{sq(field)}] === {sq(item['checked'])}")
                    else:
                        values.append(f"{ts_key(key)}: row?.[{sq(field)}] ?? null")
                if values:
                    lines.append(f'    this.forms[{sq(region)}]?.reset({{ ' + ', '.join(values) + ' });')
            lines += ['    ' + call for call in self.handler_calls('record', block)]
            self.later.append(f'  private {self.fill_method[block]}(row: Record<string, unknown> | null): void {{\n'
                                + '\n'.join(lines) + '\n  }')
        return self.fill_method[block]

    def originals(self) -> None:
        if not any('private readonly originals' in f for f in self.fields):
            self.fields.append('  // A lekérdezett rekordok (a mentés ezekhez képest módosít).\n'
                               '  private readonly originals: Record<string, Record<string, unknown> | null> = {};')

    # ---------------------------------------------------------------- LOVs

    def lovs(self) -> None:
        lookups = {l['name']: l for l in self.plan['lookups']}
        owners = {}
        for owner, (region, key, item) in self.controls.items():
            if item.get('lov') and item['lov'] in (self.w or {}).get('lovs', {}):
                owners.setdefault(item['lov'], []).append(owner)
        self.lov_search = {}
        for lov, spec in (self.w or {}).get('lovs', {}).items():
            if lov not in owners:
                continue
            base = pascal(lov)
            rows, search, choose = camel(lov) + 'Rows', self.unique('search' + base), self.unique('choose' + base)
            self.taken.add(rows)
            columns = [c for c in spec['columns'] if c['column']]
            first = owners[lov][0]
            own = next((c['column'] for c in columns if c['returnItem'] == first), columns[0]['column'] if columns else '')
            parameters = []
            for bind in spec['binds']:
                value = self.screen_value(bind['block'], bind['key'])
                parameters.append(f"{sq(bind['source'])}: {value or 'null'}")
            label = ('[' + ', '.join(f"row[{sq(c['column'])}]" for c in columns) + "].filter(v => v !== null && v !== undefined && v !== '').map(String).join(' – ')"
                     if columns else "''")
            self.fields.append(f'  private {rows}: Record<string, unknown>[] = [];')
            self.need('suggest')
            self.types.add('Page')
            self.methods.append(
                f'  // {lov} LOV: a mező keresője (FormBlock autocomplete).\n'
                f'  protected {search}(ownId: string, term: string): void {{\n'
                f"    this.{spec['call']}({{ term: term || null, parameters: " + ('{ ' + ', '.join(parameters) + ' }' if parameters else '{}') + ", limit: 50 }).subscribe(page => {\n"
                f'      this.{rows} = page.rows ?? [];\n'
                f'      this.suggest(ownId, this.{rows}.map(row => ({{ label: {label}, value: row[{sq(own)}] }})));\n'
                '    });\n  }')
            for owner in owners[lov]:
                self.lov_search[owner] = search
            # Return values: the other columns into their fields when a value is chosen.
            returns = {}
            for c in columns:
                target = self.controls.get(c['returnItem'] or '')
                if target and c['returnItem'] not in owners[lov]:
                    returns.setdefault(target[0], []).append(f"{ts_key(target[1])}: row[{sq(c['column'])}]")
            if not returns:
                continue
            body = [f'    const row = this.{rows}.find(r => r[{sq(own)}] === value);', '    if (!row) return;']
            body += [f'    this.forms[{sq(region)}]?.patchValue({{ ' + ', '.join(values) + ' }, { emitEvent: false });'
                     for region, values in returns.items()]
            self.methods.append(f'  // {lov}: a kiválasztott sor többi oszlopa a hozzá tartozó mezőkbe.\n'
                                f'  private {choose}(value: unknown): void {{\n' + '\n'.join(body) + '\n  }')
            for owner in owners[lov]:
                region, key, _ = self.controls[owner]
                self.subscribe(region, f'group.get({sq(key)})?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(value => this.{choose}(value));')

    def subscribe(self, region: str, statement: str) -> None:
        self.subscriptions.setdefault(region, []).append(statement)
        self.core.add('DestroyRef')

    # ---------------------------------------------------------------- buttons

    @staticmethod
    def inline(h: dict) -> str | None:
        """A one-statement handler is written in place; a longer one is a method of its own."""
        line = h['lines'][0].strip() if len(h['lines']) == 1 else ''
        return line if line.startswith('this.') and line.endswith(');') else None

    def handler_calls(self, moment: str, target: str) -> list[str]:
        result = []
        for h in self.states.get('handlers', []):
            key = h['block'] if moment == 'record' else h['owner']
            if h['moment'] == moment and (moment == 'init' or key == target):
                result.append(self.inline(h) or 'this.' + h['method'] + '();')
        return result

    def steps(self, owner: str, steps: list) -> list[str] | None:
        """The statements of a button's recognised Forms steps, or None when one of them has no plain equivalent."""
        block, lines = owner.split('.', 1)[0], []
        controls = self.plan.get('window_controls') or {}
        for step in steps:
            op = step['op']
            if op == 'goBlock':
                block = step['block'].upper()
                continue
            if op in NAVIGATION_STEPS:
                continue  # focus: no web equivalent
            if op == 'executeQuery':
                if block not in self.query_method:
                    return None
                lines.append(f'this.{self.query_method[block]}();')
            elif op == 'commit':
                if not (self.w or {}).get('commit'):
                    return None
                lines.append('this.save();')
            elif op in {'clearBlock', 'createRecord', 'clearRecord'}:
                lines += self.clear(block)
            elif op == 'clearForm':
                for b in list(self.form_blocks) + list(self.table_blocks):
                    lines += self.clear(b)
            elif op == 'deleteRecord' and self.can_delete():
                lines.append('this.deleteRecord();')
            elif op == 'exitForm':
                lines.append('window.history.back();')
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
            elif op == 'message':
                lines.append(f"this.toast.warning('Üzenet', {sq(step.get('text', ''))}, true, this.toastLife.warning);")
            else:
                return None
        return lines

    def clear(self, block: str) -> list[str]:
        if block in self.table_blocks:
            t = self.table_name(block)
            return [f'this.{t}Rows = [];', f'this.{t}Selection = null;']
        lines = [f'this.forms[{sq(region)}]?.reset();' for region in self.form_blocks.get(block, [])]
        if lines and self.fill_method.get(block):
            lines.insert(0, f'this.originals[{sq(block)}] = null;')
        return lines

    def can_delete(self) -> bool:
        commit = (self.w or {}).get('commit') or {}
        return any('delete' in spec['operations'] for spec in commit.get('blocks', {}).values())

    def button(self, owner: str) -> None:
        method, lines, note = self.click[owner], [], ''
        action = next((a for a in self.plan['actions'] if a['owner'] == owner), {})
        api_action = ((self.w or {}).get('api') or {}).get('actions', {}).get(owner, {})
        handlers = self.handler_calls('button', owner)
        recognised = self.steps(owner, action['steps']) if action.get('steps') else None
        if handlers:
            lines = handlers
        elif owner in self.navigations:
            n = self.navigations[owner]
            params = []
            for p in n['params']:
                value = self.screen_value(p['block'], p['key']) if 'block' in p else sq(p['value'])
                params.append(f"{ts_key(p['name'])}: {value or 'null'}")
            lines = [f"void this.router.navigate([{sq(n['route'])}], {{ queryParams: {{ " + ', '.join(params) + ' } });']
            note = f"Forms {n['call']}('{n['form']}'): navigáció."
        elif owner in self.manual_navs:
            lines = [f"this.{self.manual_navs[owner]['method']}();"]
        elif recognised is not None and recognised:
            lines = recognised
        elif owner in (self.w or {}).get('actions', {}):
            endpoint = self.w['actions'][owner]
            self.need('blocks', 'parameters')
            target = (self.w.get('query_actions') or {}).get(owner)
            if target:
                lines = [f'this.{endpoint}({{ blocks: this.blocks(), parameters: this.parameters(), offset: 0, limit: {QUERY_LIMIT} }})'
                         f'.subscribe(page => this.{self.show(target)}(page));']
                note = f'Lekérdezés a(z) {target} blokkra: a feltételt a backend állítja össze.'
            else:
                self.need('showResult')
                self.types.add('ActionResult')
                lines = [f"this.{endpoint}({{ blocks: this.blocks(), parameters: this.parameters() }}).subscribe(result => this.showResult(result, 'A művelet sikeresen lefutott.'));"]
                note = 'Az eredeti PL/SQL a backendben fut.'
            todo = []
            if api_action.get('alerts'):
                todo.append('a kód Forms-alertet mutat (SHOW_ALERT): a válaszgomb sorszámát a parameters[\'FRM.ALERTS\'] '
                            'értékben kell visszaküldeni, és a kérést megismételni')
            if api_action.get('commit_point'):
                todo.append('a kód közepén mentés (COMMIT_FORM) van: a backend FRM_COMMIT utasítással jelzi; a mentést '
                            'és a folytatást (FRM.RESUME) kézzel kell bekötni')
            if api_action.get('screen_points'):
                todo.append('a kód közepén képernyőlépés van (FRM_RESUME): a lépés után a kérést FRM.RESUME paraméterrel '
                            'kell folytatni')
            if api_action.get('commands'):
                queries = ', '.join(f'this.{m}()' for m in self.query_method.values())
                todo.append('a backend ezeket a Forms-utasításokat adhatja vissza (a válasz commands mezőjében): '
                            + ', '.join(api_action['commands']) + '; a képernyő nem futtatja őket, ahol kell, itt kösd be'
                            + (f' (lekérdezés: {queries})' if queries and 'EXECUTE_QUERY' in api_action['commands'] else ''))
            if todo:
                lines = ['// TODO: ' + t + '.' for t in todo] + lines
        else:
            source = self.sources.get(owner, '')
            lines = ['// TODO: a gomb kódját kézzel kell átültetni (az eredeti Forms-kód lent).']
            if action.get('steps'):
                lines.append('// Felismert Forms-lépések: ' + '; '.join(
                    step['op'] + ''.join("('" + str(v) + "')" for k, v in step.items() if k != 'op') for step in action['steps'])
                    + ' (a képernyőn nincs hozzájuk generált lekérdezés vagy mentés).')
            if source.strip():
                lines += ['//#region Eredeti Forms-kód'] + ['//' + (' ' + l if l else '') for l in source.strip().split('\n')] + ['//#endregion']
            lines.append(f"this.toast.warning('Nincs bekötve', {sq('A gomb kódja kézi átültetést igényel: ' + owner)}, true, this.toastLife.warning);")
        head = f'  // {owner}' + (': ' + note if note else '') + '\n'
        self.methods.append(head + f'  protected {method}(): void {{\n' + '\n'.join('    ' + l for l in lines) + '\n  }')

    # ---------------------------------------------------------------- save (Forms COMMIT_FORM)

    def save(self) -> None:
        commit = (self.w or {}).get('commit')
        if not commit:
            return
        self.need('blocks', 'parameters', 'text', 'value', 'showResult')
        self.types.update({'CommitResult', 'ActionResult'})
        self.originals()
        deletes = self.can_delete()
        if deletes:
            self.fields.append('  // A törlésre jelölt rekordok (a Mentés véglegesíti).\n'
                               '  private readonly deleted: Record<string, Record<string, unknown>[]> = {};')
        lines = ['    const request: Record<string, unknown> = { blocks: this.blocks(), parameters: this.parameters() };',
                 '    let changed = false;']
        after = []
        for block, spec in commit['blocks'].items():
            regions = self.form_blocks.get(block, [])
            groups = '[' + ', '.join(f'this.forms[{sq(r)}]' for r in regions) + ']'
            fill = self.fill(block)
            values = []
            for owner, (region, key, item) in self.controls.items():
                if region not in regions:
                    continue
                field = self.dto_field(owner, key)
                if item['widget'] == 'checkbox':
                    values.append(f"{ts_key(field)}: this.value({sq(region)}, {sq(key)}) ? {sq(item['checked'])} : {sq(item['unchecked'])}")
                else:
                    values.append(f"{ts_key(field)}: this.text(this.value({sq(region)}, {sq(key)}))")
            ops = spec['operations']
            v = camel(block)
            lines += [f'    // {block}: ' + ', '.join(ops),
                      f'    const {v}Groups = {groups};',
                      f'    const {v}Dirty = {v}Groups.some(group => group?.dirty);',
                      f'    if ({v}Dirty && {v}Groups.some(group => group?.invalid)) {{',
                      f'      {v}Groups.forEach(group => group?.markAllAsTouched());',
                      f"      this.toast.warning('Hiányzó vagy hibás adat', {sq('Ellenőrizd a(z) ' + block + ' mezőit.')}, true, this.toastLife.warning);",
                      '      return;', '    }',
                      f'    const {v}Original = this.originals[{sq(block)}] ?? null;',
                      f"    const {v}Deleted = {('this.deleted[' + sq(block) + '] ?? []') if 'delete' in ops else '[]'};",
                      f'    if ({v}Dirty || {v}Deleted.length) {{',
                      f'      const value = {{ ...{v}Original, ' + ', '.join(values) + ' };',
                      f"      request[{sq(spec['request'])}] = {{",
                      f"        inserted: {(v + 'Dirty && !' + v + 'Original ? [value] : []') if 'create' in ops else '[]'},",
                      f"        updated: {(v + 'Dirty && ' + v + 'Original ? [{ original: ' + v + 'Original, value }] : []') if 'update' in ops else '[]'},",
                      f'        deleted: {v}Deleted,',
                      '      };', '      changed = true;', '    }']
            after += [f"      const {camel(block)}Rows = result[{sq(spec['result'])}];",
                      f'      if (Array.isArray({camel(block)}Rows) && {camel(block)}Rows.length) this.{fill}({camel(block)}Rows[{camel(block)}Rows.length - 1] as Record<string, unknown>);']
            if 'delete' in ops:
                after.append(f'      delete this.deleted[{sq(block)}];')
            after += [f'      {camel(block)}Groups.forEach(group => group?.markAsPristine());']
        lines += ["    if (!changed) {", "      this.toast.warning('Mentés', 'Nincs mentendő változás.', true, this.toastLife.warning);",
                  '      return;', '    }',
                  f"    this.{commit['call']}(request).subscribe(result => {{", *after,
                  "      this.showResult(result, 'A változások mentése sikerült.');", '    });']
        self.methods.append('  // Forms COMMIT_FORM: a képernyő változásai egy kérésben; a backend egy tranzakcióban, Forms-sorrendben ment.\n'
                            '  protected save(): void {\n' + '\n'.join(lines) + '\n  }')
        first = next(iter(commit['blocks']))
        self.methods.append(f'  // Új rekord a(z) {first} blokkban (Forms CREATE_RECORD / CLEAR_BLOCK).\n  protected newRecord(): void {{\n'
                            + '\n'.join('    ' + l for l in self.clear(first)) + '\n  }')
        if deletes:
            block = next(b for b, s in commit['blocks'].items() if 'delete' in s['operations'])
            self.methods.append(f'  // A(z) {block} rekordja törlésre jelölve; a Mentés véglegesíti.\n  protected deleteRecord(): void {{\n'
                                f"    const original = this.originals[{sq(block)}];\n"
                                f"    if (original) (this.deleted[{sq(block)}] ??= []).push(original);\n"
                                + '\n'.join('    ' + l for l in self.clear(block)) + '\n'
                                "    this.toast.warning('Törlés', 'A rekord törlésre jelölve; a Mentés véglegesíti.', true, this.toastLife.warning);\n  }")

    # ---------------------------------------------------------------- assembly

    def build(self) -> None:
        self.lovs()  # first: the LOV fields' search methods are known before the buttons and the structures
        lov_methods, self.methods = self.methods, []
        for owner in self.click:
            self.button(owner)
        for block, q in self.queries.items():
            self.methods.append(self.query(block, q))
        self.methods += lov_methods
        self.save()
        table_actions = {s['block']: [i['owner'] for i in s['items'] if i['widget'] == 'button'] for s in self.tables}
        if any(table_actions.values()):
            cases = [f'      case {sq(o)}: this.{self.click[o]}(); break;' for owners in table_actions.values() for o in owners]
            self.methods.append('  // Egy táblázatsor gombja (a sor már ki van választva).\n  protected onRowAction(ownId: string): void {\n'
                                '    switch (ownId) {\n' + '\n'.join(cases) + '\n    }\n  }')
        for h in self.states.get('handlers', []):
            call = self.inline(h)
            if h['moment'] == 'change':
                target = self.controls.get(h['owner'])
                if target:
                    self.subscribe(target[0], f"group.get({sq(target[1])})?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))"
                                              f".subscribe(() => {call[:-1] if call else 'this.' + h['method'] + '()'});")
            text = '\n'.join(h['lines'])
            for helper in ('setItemState', 'setItemValue', 'stateValue', 'isNull', 'cmp'):
                if 'this.' + helper + '(' in text:
                    self.need(helper)
            if not call:
                self.methods.append(f"  // {h['owner']} / {h['event']}: a mezők állapota (Forms SET_ITEM_PROPERTY).\n"
                                    f"  private {h['method']}(): void {{\n" + text + '\n  }')
        for owner, m in self.manual_navs.items():
            rows = ', '.join(ts_key(b) + ': this.' + self.table_name(b) + 'Selection' for b, _ in m['tables'] if b in self.table_blocks)
            code = '\n'.join('    // ' + line if line else '    //' for line in m['code'].split('\n'))
            self.methods.append('  private ' + m['method'] + '(): void {\n'
                                + ('    const selected = { ' + rows + ' };\n    void selected;\n' if rows else '')
                                + "    // Mintának: void this.router.navigate(['/<cél modul útvonala>'], { queryParams: { /* Forms-paraméterek */ } });\n"
                                + '    //#region Eredeti Forms-kód (kiindulásnak)\n' + code + '\n    //#endregion\n'
                                + "    this.toast.warning('Nincs bekötve', " + sq('A navigációt kézzel kell befejezni: ' + owner) + ', true, this.toastLife.warning);\n  }')
        self.methods += self.later
        if 'setItemState' in self.needs:
            self.angular_forms.add('Validators')

    def class_fields(self, tab_fields: list, labels: dict, toast_symbol: str, form_type: str, structures: dict) -> list[str]:
        """The component's fields in their order (structures, tables, windows ... and what the methods declared)."""
        life = self.config['toast_life_ms']
        fields = ['  protected readonly toast = inject(' + toast_symbol + ');\n'
                  f"  protected readonly toastLife = {{ success: {life['success']}, warning: {life['warning']}, danger: {life['danger']} }};"]
        if (self.w or {}).get('endpoints'):
            fields[-1] += '\n  private readonly http = inject(HttpClient);'
        if 'DestroyRef' in self.core:
            fields[-1] += '\n  private readonly destroyRef = inject(DestroyRef);'
        if labels:
            fields.append('  protected readonly labels = ' + record(labels) + ';')
        fields.extend(tab_fields)
        if self.forms:
            self.angular_forms.add('FormGroup')
            fields.append('  // A FormBlock-régiók FormGroupjai (onFormGroupGenerated).\n  protected readonly forms: Record<string, FormGroup> = {};')
            from .ts_code import nested
            fields.append('  protected readonly structures: Record<string, ' + form_type + '[]> = ' + nested(structures) + ';')
        if {'items'} & self.needs:
            entries = {}
            for owner, (region, key, item) in self.controls.items():
                entries[owner] = [region, key] + ([item['checked'], item['unchecked']] if item['widget'] == 'checkbox' else [])
            fields.append('  // Oracle-név -> [régió, mező, checkbox bejelölt / üres értéke]: a backend kérései és válaszai ezekkel a nevekkel.\n'
                          '  private readonly items: Record<string, [string, string, string?, string?]> = ' + record(entries) + ';')
        for section in self.tables:
            t = self.table_name(section['block'])
            columns = [i for i in section['items'] if i['widget'] not in {'button', 'image', 'unsupported', 'tree'} and not i.get('spacer')]
            weights = [max(1, i['width']) for i in columns]
            total = sum(weights) or 1
            cols = [{'field': self.dto_field(i['owner'], i['key']), 'header': i['label'], 'width': str(round(w / total * 100, 2)) + '%'}
                    for i, w in zip(columns, weights)]
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
        return fields + self.fields

    def form_group_method(self) -> str | None:
        if not self.forms:
            return None
        lines = ['    this.forms[region] = group;']
        for region, statements in self.subscriptions.items():
            lines.append(f'    if (region === {sq(region)}) {{')
            lines += ['      ' + s for s in statements]
            lines.append('    }')
        return ('  // A FormBlock elkészítette a régió FormGroupját.\n'
                '  protected onFormGroupGenerated(region: string, group: FormGroup): void {\n' + '\n'.join(lines) + '\n  }')

    def constructor(self) -> str:
        lines = ['    super();'] + ['    ' + c for c in self.handler_calls('init', '')]
        # WHEN-NEW-RECORD-INSTANCE / POST-QUERY of a form block: at the start too (and when a record is loaded: fill<Block>)
        lines += ['    ' + c for block in self.form_blocks for c in self.handler_calls('record', block)]
        init = (self.w or {}).get('api', {}).get('init')
        if init and init in (self.w or {}).get('actions', {}):
            self.need('blocks', 'parameters', 'showResult')
            self.types.add('ActionResult')
            lines.append(f"    this.{self.w['actions'][init]}({{ blocks: this.blocks(), parameters: this.parameters() }}).subscribe(result => this.showResult(result, ''));")
        return '  constructor() {\n' + '\n'.join(lines) + '\n  }'

    def blocks_helper(self) -> str:
        lines = ['    const blocks: Record<string, Record<string, string | null>> = {};',
                 '    for (const [owner, [region, key, checked, unchecked]] of Object.entries(this.items)) {',
                 "      const [block, item] = owner.split('.');",
                 '      const value = this.value(region, key);',
                 '      (blocks[block] ??= {})[item] = checked === undefined ? this.text(value) : value ? checked : unchecked ?? null;',
                 '    }']
        for block in self.table_blocks:
            fields = self.api_fields.get(block)
            if not fields:
                continue
            t = self.table_name(block)
            lines.append(f'    const {t} = this.{t}Selection;')
            lines.append(f'    if ({t}) blocks[{sq(block)}] = {{ ' + ', '.join(f"{ts_key(o)}: this.text({t}[{sq(f)}])" for o, f in fields.items()) + ' };')
        lines.append('    return blocks;')
        return ('  // A képernyő értékei Oracle-nevekkel: a gombok, az indítás és a mentés kérésének blocks része\n'
                '  // (a táblázatból a kiválasztott sor).\n'
                '  private blocks(): Record<string, Record<string, string | null>> {\n' + '\n'.join(lines) + '\n  }')

    def helper_methods(self) -> list[str]:
        if 'blocks' in self.needs:
            self.need('items', 'value', 'text')
        result = []
        if 'blocks' in self.needs:
            result.append(self.blocks_helper())
        order = ['parameters', 'showResult', 'showBlocks', 'suggest', 'setItemState', 'setItemValue', 'stateValue', 'isNull', 'cmp',
                 'value', 'text', 'data']
        result += [HELPERS[h] for h in order if h in self.needs]
        return result

    def type_declarations(self) -> str:
        return ''.join(TYPES[t] + '\n\n' for t in ('Page', 'ActionResult', 'CommitResult') if t in self.types)

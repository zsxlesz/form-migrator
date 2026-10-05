"""The screen side of the Forms runtime emulation (forms_emulation): what the generated component does
with the commands of an action or init endpoint.

The backend runs the original PL/SQL and returns the Forms built-ins it called as commands
(GO_BLOCK, SET_ITEM_PROPERTY, EXECUTE_QUERY, CALL_FORM, SHOW_ALERT ...). The component keeps the
:GLOBAL values in the browser tab, sends its context (:SYSTEM, :PARAMETER) with every request,
and executes the commands in order after writing back the item values.
"""
from __future__ import annotations

import json

from .angular_single import ts


# Forms SET_ITEM_PROPERTY property -> screen item state.
ITEM_PROPERTIES = {'ENABLED': 'enabled', 'VISIBLE': 'visible', 'DISPLAYED': 'visible', 'REQUIRED': 'required',
                   'UPDATE_ALLOWED': 'editable', 'INSERT_ALLOWED': 'editable', 'UPDATEABLE': 'editable', 'INSERTABLE': 'editable'}


def emulation_fields(w: dict) -> list[str]:
    """State of the Forms runtime emulation: cursor, parameter lists, record groups, the open alert."""
    if w.get('runtime'):
        return runtime_fields(w)
    result = ['  // Forms-futtatókörnyezet emuláció: a backend a Forms-hívásokat felületi utasításként adja vissza (runCommands).\n'
              '  private cursorBlock = ' + json.dumps(w.get('first_block') or '') + ';\n'
              '  private cursorItem = \'\';\n'
              '  private readonly paramLists: Record<string, Record<string, string | null>> = {};\n'
              '  private readonly recordGroups: Record<string, { columns: string[]; rows: Record<string, string | null>[] }> = {};\n'
              '  protected formsAlert: { title: string; text: string; buttons: string[]; resolve: (choice: number) => void } | null = null;',
              '  // Forms-alertek (cím, szöveg, gombfeliratok) az XML-ből; a SET_ALERT_PROPERTY felülírhatja őket.\n'
              '  private readonly alertDefinitions: Record<string, { title: string; text: string; buttons: string[] }> = '
              + ts(w.get('alerts', {}), 1) + ';',
              '  // CALL_FORM/OPEN_FORM/NEW_FORM cél -> Angular útvonal (config: form_routes, alapból /<formnév>).\n'
              '  private readonly formRoutes: Record<string, string> = ' + ts(w.get('form_routes', {}), 1) + ';',
              '  // Forms-rekordállapot: a lekérdezett rekord (a backend DTO-ja, rejtett kulcsokkal) és a törlésre jelöltek.\n'
              '  private readonly originals: Record<string, Record<string, unknown> | null> = {};\n'
              '  private readonly pendingDeletes: Record<string, Record<string, unknown>[]> = {};']
    if w.get('commit'):
        blocks = {block: {'request': spec['request'], 'result': spec['result'], 'operations': spec['operations']}
                  for block, spec in w['commit']['blocks'].items()}
        result.append('  // Forms COMMIT_FORM: a mentett blokkok a commit-kérés mezőivel és a megengedett műveletekkel.\n'
                      '  private readonly commitBlocks: Record<string, { request: string; result: string; operations: readonly string[] }> = '
                      + ts(blocks, 1) + ';')
    return result


def emulation_methods(w: dict, form_values: bool) -> list[str]:
    """The screen side of the emulation: request context, globals, alerts and the command executor."""
    query = ("    if (!this.executeQuery(block)) this.toast.warning('Lekérdezés', 'Ehhez a blokkhoz nincs generált lekérdezés: ' + block, true, TOAST_LIFE.warning);"
             if w['queries'] or w.get('query_actions') else
             "    this.toast.warning('Lekérdezés', 'Ehhez a blokkhoz nincs generált lekérdezés: ' + block, true, TOAST_LIFE.warning);")
    states = w.get('states')
    prop_cases = ''.join(f"      case {json.dumps(k)}: this.setItemState(owner, {{ {v}: on }}); break;\n" for k, v in ITEM_PROPERTIES.items())
    item_property = (f"""    const owner = item.includes('.') ? item : this.cursorBlock + '.' + item;
    const on = ['PROPERTY_TRUE', 'PROPERTY_ON', 'TRUE'].includes(value);
    switch (property) {{
{prop_cases}      default: console.warn('SET_ITEM_PROPERTY nincs leképezve:', owner, property, value);
    }}""" if states else "    console.warn('SET_ITEM_PROPERTY: a képernyőn nincs állapotkezelés', item, property, value);")
    window = (f"    if (Object.hasOwn(this.windowVisible(), name)) this.setWindowVisible(name as {w['window_type']}, visible);"
              if w.get('window_type') else "    void name; void visible;")
    canvas = (f"""    if (!Object.hasOwn(this.canvasVisible(), name)) return;
    if (visible) this.showCanvas(name as {w['canvas_type']}); else this.hideCanvas(name as {w['canvas_type']});"""
              if w.get('canvas_type') else "    void name; void visible;")
    clear_tables = ''.join(f"      case {json.dumps(block)}: this.{prop}Rows = []; this.{prop}Selection = null; break;\n" for block, prop in w['tables'])
    clear_form = ('''    this.formValues[block] = {};
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.regionBlocks[region] === block) group.reset({}, { emitEvent: false });
    }
''' if form_values else '')
    status = ('''  /** :SYSTEM.FORM_STATUS / BLOCK_STATUS közelítése: módosított űrlap = CHANGED. */
  private formsStatus(block?: string): string {
    const groups = Object.entries(this.formGroups).filter(([region]) => !block || this.regionBlocks[region] === block);
    return groups.some(([, group]) => group.dirty) ? 'CHANGED' : 'QUERY';
  }''' if form_values else '''  private formsStatus(_block?: string): string {
    return 'QUERY';
  }''')
    navigate = ('    void this.router.navigate([route], { queryParams });' if w.get('router') else
                "    this.toast.warning('Navigáció', 'Kösd be az Angular Routert: ' + route, true, TOAST_LIFE.warning);\n    void queryParams;")
    return ['''  /** :GLOBAL értékek: a böngészőfülön belül közösek a formok között (Forms: munkamenet-szintű globálisok). */
  private formsGlobals(): Record<string, string | null> {
    try {
      const stored: unknown = JSON.parse(sessionStorage.getItem('frm.forms.globals') ?? '{}');
      return stored && typeof stored === 'object' ? stored as Record<string, string | null> : {};
    } catch {
      return {};
    }
  }''', '''  private rememberGlobals(values: Record<string, string | null>): void {
    try {
      sessionStorage.setItem('frm.forms.globals', JSON.stringify({ ...this.formsGlobals(), ...values }));
    } catch {
      // privát mód / tiltott tárhely: a globálisok csak ebben a kérésben élnek
    }
  }''', '''  /** A kérés képernyő-kontextusa: :GLOBAL, :PARAMETER (az URL query paraméterei), :SYSTEM és az alert-válaszok. */
  private requestContext(answers: readonly number[]): Record<string, string> {
    const context: Record<string, string> = {};
    for (const [name, value] of Object.entries(this.formsGlobals())) if (value !== null) context[name] = value;
    const query = window.location.search || (window.location.hash.includes('?') ? window.location.hash.slice(window.location.hash.indexOf('?')) : '');
    new URLSearchParams(query).forEach((value, name) => { context['PARAMETER.' + name.toUpperCase()] = value; });
    const item = this.cursorItem || this.cursorBlock;
    Object.assign(context, {
      'SYSTEM.CURSOR_BLOCK': this.cursorBlock, 'SYSTEM.CURRENT_BLOCK': this.cursorBlock,
      'SYSTEM.CURSOR_ITEM': item, 'SYSTEM.CURRENT_ITEM': item.split('.').pop() ?? '',
      'SYSTEM.CURSOR_RECORD': '1', 'SYSTEM.TRIGGER_RECORD': '1', 'SYSTEM.LAST_RECORD': 'TRUE', 'SYSTEM.MESSAGE_LEVEL': '0',
      'SYSTEM.FORM_STATUS': this.formsStatus(), 'SYSTEM.BLOCK_STATUS': this.formsStatus(this.cursorBlock),
      'SYSTEM.RECORD_STATUS': this.formsStatus(this.cursorBlock), 'SYSTEM.CURRENT_DATETIME': localIso(new Date()),
    });
    if (answers.length) context['FRM.ALERTS'] = answers.join(',');
    return context;
  }''', status, '''  /** A backend által visszaadott Forms-hívások végrehajtása, sorrendben. */
  private runCommands(commands: readonly (readonly (string | null)[])[]): void {
    for (const [op, ...args] of commands) {
      const arg = (index: number) => (args[index] ?? '').toUpperCase();
      switch (op) {
        case 'GO_BLOCK': this.cursorBlock = arg(0); this.cursorItem = ''; break;
        case 'GO_ITEM': {
          const target = arg(0).includes('.') ? arg(0) : this.cursorBlock + '.' + arg(0);
          this.cursorBlock = target.split('.')[0]; this.cursorItem = target;
          break;
        }
        case 'EXECUTE_QUERY': this.formsQuery(this.cursorBlock); break;
        case 'SET_ITEM_PROPERTY': case 'SET_ITEM_INSTANCE_PROPERTY':
          if (op === 'SET_ITEM_PROPERTY') this.formsItemProperty(arg(0), arg(1), arg(2));
          else this.formsItemProperty(arg(0), arg(2), arg(3));
          break;
        case 'SHOW_WINDOW': case 'HIDE_WINDOW': this.formsWindow(arg(0), op === 'SHOW_WINDOW'); break;
        case 'SHOW_VIEW': case 'HIDE_VIEW': this.formsCanvas(arg(0), op === 'SHOW_VIEW'); break;
        case 'CLEAR_BLOCK': case 'CREATE_RECORD': case 'CLEAR_RECORD': this.clearBlock(this.cursorBlock); break;
        case 'DELETE_RECORD': this.formsDelete(this.cursorBlock); break;
        case 'CLEAR_FORM': for (const block of __BLOCKS__) this.clearBlock(block); break;
        case 'ADD_PARAMETER': (this.paramLists[arg(0)] ??= {})[args[1] ?? ''] = args[3] ?? null; break;
        case 'DESTROY_PARAMETER_LIST': delete this.paramLists[arg(0)]; break;
        case 'CALL_FORM': case 'OPEN_FORM': case 'NEW_FORM': this.formsCall(arg(0), args.slice(1).map(a => (a ?? '').toUpperCase())); break;
        case 'COMMIT_FORM': case 'POST': this.formsCommit(); break;
        case 'DO_KEY': this.formsKey(arg(0)); break;
        case 'EXIT_FORM': window.history.back(); break;
        case 'WEB.SHOW_DOCUMENT': window.open(args[0] ?? '', args[1] || '_blank'); break;
        case 'CREATE_GROUP': case 'ADD_GROUP_COLUMN': case 'ADD_GROUP_ROW': case 'SET_GROUP_CHAR_CELL':
        case 'SET_GROUP_NUMBER_CELL': case 'SET_GROUP_DATE_CELL': case 'DELETE_GROUP': case 'DELETE_GROUP_ROW':
          this.recordGroup(op, args);
          break;
        case 'ENTER_QUERY': case 'LIST_VALUES': case 'SET_RECORD_PROPERTY': case 'SET_BLOCK_PROPERTY': break;
        default: console.warn('Forms-utasítás nincs bekötve:', op, args);
      }
    }
    this.changeDetector.markForCheck();
  }'''.replace('__BLOCKS__', json.dumps(sorted(w['screen_keys']))), '''  private formsQuery(block: string): void {
__QUERY__
  }'''.replace('__QUERY__', query), '''  private formsItemProperty(item: string, property: string, value: string): void {
__ITEM__
  }'''.replace('__ITEM__', item_property), '''  private formsWindow(name: string, visible: boolean): void {
__WINDOW__
  }'''.replace('__WINDOW__', window), '''  private formsCanvas(name: string, visible: boolean): void {
__CANVAS__
  }'''.replace('__CANVAS__', canvas), '''  private clearBlock(block: string): void {
    this.originals[block] = null;  // Forms: a new record, nothing queried
__FORM__    switch (block) {
__TABLES__      default: break;
    }
  }'''.replace('__FORM__', clear_form).replace('__TABLES__', clear_tables), '''  /** CALL_FORM/OPEN_FORM/NEW_FORM: navigáció a cél form útvonalára, a paraméterlista query paraméterként. */
  private formsCall(form: string, args: readonly string[]): void {
    const list = args.find(name => Object.hasOwn(this.paramLists, name));
    const queryParams: Record<string, string> = {};
    for (const [name, value] of Object.entries(list ? this.paramLists[list] : {})) if (value !== null) queryParams[name] = value;
    const route = this.formRoutes[form] ?? '/' + form.toLowerCase();
__NAVIGATE__
  }'''.replace('__NAVIGATE__', navigate), '''  private formsKey(key: string): void {
    switch (key) {
      case 'EXECUTE_QUERY': this.formsQuery(this.cursorBlock); break;
      case 'COMMIT_FORM': this.formsCommit(); break;
      case 'CLEAR_BLOCK': case 'CREATE_RECORD': this.clearBlock(this.cursorBlock); break;
      case 'EXIT_FORM': window.history.back(); break;
      case 'LIST_VALUES': case 'ENTER_QUERY': break;
      default: console.warn('DO_KEY nincs bekötve:', key);
    }
  }''', '''  /** Futásidőben épített Forms-rekordcsoportok (CREATE_GROUP ...), például statikus LOV-listákhoz. */
  private recordGroup(op: string, args: readonly (string | null)[]): void {
    const name = (args[0] ?? '').toUpperCase();
    const [groupName, column] = name.split('.');
    const group = this.recordGroups[groupName];
    const row = Number(args[1] ?? 0) - 1;
    switch (op) {
      case 'CREATE_GROUP': this.recordGroups[name] = { columns: [], rows: [] }; break;
      case 'ADD_GROUP_COLUMN': this.recordGroups[name]?.columns.push((args[1] ?? '').toUpperCase()); break;
      case 'ADD_GROUP_ROW': group?.rows.splice(row >= 0 ? row : group.rows.length, 0, {}); break;
      case 'DELETE_GROUP_ROW': group?.rows.splice(row, 1); break;
      case 'DELETE_GROUP': delete this.recordGroups[name]; break;
      default: if (group?.rows[row]) group.rows[row][column] = args[2] ?? null;
    }
  }''', '''  /** Forms SHOW_ALERT: párbeszédablak; a választott gomb (1..3) száma a kód újrafuttatásába kerül. */
  private askAlert(command: readonly (string | null)[], then: (choice: number) => void): void {
    const name = (command[1] ?? '').toUpperCase();
    const definition = this.alertDefinitions[name] ?? { title: name, text: '', buttons: ['OK'] };
    const buttons = [0, 1, 2].map(index => command[3 + index] || definition.buttons[index] || '').filter(label => label !== '');
    this.formsAlert = { title: definition.title || name, text: command[2] || definition.text, buttons: buttons.length ? buttons : ['OK'], resolve: then };
    this.changeDetector.markForCheck();
  }''', *commit_methods(w, form_values), '''  protected answerAlert(choice: number): void {
    const alert = this.formsAlert;
    this.formsAlert = null;
    alert?.resolve(choice);
  }''']


# Recognised button steps (framework.action_steps) -> the commands of the emulation.
STEP_COMMANDS = {'goBlock': 'GO_BLOCK', 'goItem': 'GO_ITEM', 'executeQuery': 'EXECUTE_QUERY', 'commit': 'COMMIT_FORM',
                 'createRecord': 'CREATE_RECORD', 'clearBlock': 'CLEAR_BLOCK', 'clearForm': 'CLEAR_FORM',
                 'clearRecord': 'CLEAR_RECORD', 'showWindow': 'SHOW_WINDOW', 'hideWindow': 'HIDE_WINDOW',
                 'showCanvas': 'SHOW_VIEW', 'hideCanvas': 'HIDE_VIEW', 'exitForm': 'EXIT_FORM', 'enterQuery': 'ENTER_QUERY',
                 'listValues': 'LIST_VALUES'}


def steps_method() -> str:
    """runSteps: a button made only of recognised Forms built-ins runs on the screen, without a backend call."""
    return '''  /** Felismert gomblépések (GO_BLOCK, EXECUTE_QUERY, CREATE_RECORD, COMMIT_FORM ...): a képernyő hajtja végre. */
  private runSteps(steps: readonly { op: string; block?: string; item?: string; window?: string; canvas?: string; text?: string }[] | null): boolean {
    if (!steps?.length) return false;
    const known: Record<string, string> = __STEPS__;
    const commands: (string | null)[][] = [];
    for (const step of steps) {
      if (step.op === 'message') {
        this.toast.warning('Üzenet', step.text ?? '', true, TOAST_LIFE.warning);
        continue;
      }
      const command = known[step.op];
      if (!command) return false;
      commands.push([command, step.block ?? step.item ?? step.window ?? step.canvas ?? null]);
    }
    this.runCommands(commands);
    return true;
  }'''.replace('__STEPS__', ts(STEP_COMMANDS, 2))


def commit_methods(w: dict, form_values: bool) -> list[str]:
    """Forms COMMIT_FORM / DELETE_RECORD on the screen: record states and the save chain (commit_chain)."""
    pristine = ('''  /** A blokk mezői mentett állapotúak: a következő mentés csak az ezutáni változást küldi. */
  private markPristine(block: string): void {
    for (const [region, group] of Object.entries(this.formGroups)) if (this.regionBlocks[region] === block) group.markAsPristine();
  }''' if form_values else '''  private markPristine(_block: string): void {
    // nincs űrlapblokk
  }''')
    delete = '''  /** Forms DELETE_RECORD: a lekérdezett rekord törlésre jelölve (a Mentés véglegesíti), az új csak ürül. */
  private formsDelete(block: string): void {
    const original = this.originals[block];
    if (original) (this.pendingDeletes[block] ??= []).push(original);
    this.clearBlock(block);
    this.markPristine(block);
  }'''
    if not (w.get('commit') and form_values):
        return [pristine, delete, '''  /** Forms COMMIT_FORM: ehhez a képernyőhöz nincs generált mentési végpont. */
  private formsCommit(): void {
    this.toast.warning('Mentés', 'Ehhez a képernyőhöz nincs generált mentési végpont.', true, TOAST_LIFE.warning);
  }''']
    p = w['prefix']
    selections = ''.join(f"    if (this.{prop}Selection) records[{json.dumps(block)}] = {{ ...this.{prop}Selection }};\n" for block, prop in w['tables'])
    return [pristine, delete, '''  /** A képernyő eszköztára (Forms: CREATE_RECORD, DELETE_RECORD, COMMIT_FORM az aktuális blokkon). */
  protected onToolbar(action: 'new' | 'delete' | 'save'): void {
    if (action === 'save') {
      this.formsCommit();
      return;
    }
    const block = Object.hasOwn(this.commitBlocks, this.cursorBlock) ? this.cursorBlock : Object.keys(this.commitBlocks)[0];
    if (action === 'new') this.clearBlock(block);
    else {
      this.formsDelete(block);
      this.toast.warning('Törlés', 'A rekord törlésre jelölve; a Mentés véglegesíti.', true, TOAST_LIFE.warning);
    }
    this.cursorBlock = block;
    this.changeDetector.markForCheck();
  }''', '''  /** A képernyő aktuális rekordjai Oracle-nevekkel (a Forms-triggerek :BLOKK.MEZŐ értékei). */
  private screenBlocks(): Record<string, Record<string, string | null>> {
    const records: Record<string, Record<string, unknown>> = {};
    for (const [block, values] of Object.entries(this.formValues)) records[block] = { ...values };
__SELECTIONS__    const blocks: Record<string, Record<string, string | null>> = {};
    for (const [block, values] of Object.entries(records)) {
      const names = this.oracleNames[block] ?? {};
      blocks[block] = Object.fromEntries(Object.entries(values).filter(([key]) => key in names).map(([key, value]) => [names[key], this.wireText(block, key, value)]));
    }
    return blocks;
  }'''.replace('__SELECTIONS__', selections), '''  /** A blokk rekordja a backend DTO-jaként: a lekérdezett rekord (rejtett mezők, ROWID) a képernyő értékeivel. */
  private recordOf(block: string, original: Record<string, unknown> | null): Record<string, unknown> {
    const record: Record<string, unknown> = { ...(original ?? {}) };
    const values = this.formValues[block] ?? {};
    for (const [field, key] of Object.entries(this.rowKeys[block] ?? {})) record[field] = this.wireText(block, key, values[key]);
    return record;
  }''', '''__APPLY_CHANGED__  /** Forms COMMIT_FORM: a képernyő összes változása egy kérésben; a backend Forms-sorrendben, a triggerekkel menti.__PRELUDE_DOC__ */
  private formsCommit(__PRELUDE_ARGS__): void {
    const request: Record<string, unknown> = { blocks: this.screenBlocks(), parameters: this.requestContext([])__PRELUDE_SPREAD__ };
    let changed = false;
    for (const [block, spec] of Object.entries(this.commitBlocks)) {
      const changes: { inserted: unknown[]; updated: { original: unknown; value: unknown }[]; deleted: unknown[] } =
        { inserted: [], updated: [], deleted: [...(this.pendingDeletes[block] ?? [])] };
      const groups = Object.entries(this.formGroups).filter(([region]) => this.regionBlocks[region] === block).map(([, group]) => group);
      if (groups.some(group => group.dirty)) {
        if (groups.some(group => group.invalid)) {
          for (const group of groups) group.markAllAsTouched();
          this.toast.warning('Hiányzó vagy hibás adat', 'Ellenőrizd a(z) ' + block + ' mezőit.', true, TOAST_LIFE.warning);
          return;
        }
        const original = this.originals[block] ?? null;
        const value = this.recordOf(block, original);
        if (original && spec.operations.includes('update')) changes.updated.push({ original, value });
        else if (!original && spec.operations.includes('create')) changes.inserted.push(value);
      }
      if (changes.inserted.length || changes.updated.length || changes.deleted.length) {
        request[spec.request] = changes;
        changed = true;
      }
    }
    if (!changed__NO_PRELUDE__) {
      this.toast.warning('Mentés', 'Nincs mentendő változás.', true, TOAST_LIFE.warning);
      return;
    }
    this.__CALL__(request).subscribe({
      next: response => {
        const result = this.payload<__P__CommitResult>(response);
        for (const [block, spec] of Object.entries(this.commitBlocks)) {
          const rows = result[spec.result];
          if (Array.isArray(rows) && rows.length) {
            const saved = rows[rows.length - 1] as Record<string, unknown>;
            this.originals[block] = { ...saved };
            const keys = this.rowKeys[block] ?? {};
            this.showRecord(block, Object.fromEntries(Object.entries(saved).filter(([field]) => field in keys).map(([field, value]) => [keys[field], value])));
          }
          delete this.pendingDeletes[block];
          this.markPristine(block);
        }
        if (result.globals) this.rememberGlobals(result.globals);
        for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyOracleValues(block, values);
        this.runCommands(result.commands ?? []);
        this.toast.success('Mentve', result.messages?.join(' ') || 'A változások mentése sikerült.', true, TOAST_LIFE.success);__THEN__
      },
      error: () => undefined, // WFF.err már jelezte; a tranzakció visszagörgetve, a képernyő változatlan
    });
  }'''.replace('__CALL__', w['commit']['call']).replace('__P__', p)
        .replace('__APPLY_CHANGED__', '''  /** Egy gomb mentés előtti mezőértékei: a megváltozott blokk mentendő lesz (Forms: a rekord CHANGED állapotú). */
  private applyChanged(block: string, values: Record<string, string | null>): void {
    const before = JSON.stringify(this.screenBlocks()[block] ?? {});
    this.applyOracleValues(block, values);
    if (JSON.stringify(this.screenBlocks()[block] ?? {}) === before) return;
    for (const [region, group] of Object.entries(this.formGroups)) if (this.regionBlocks[region] === block) group.markAsDirty();
  }

''' if w.get('commit_points') else '')
        .replace('__PRELUDE_DOC__', '\n   *  prelude: mentési pontos gomb (a backend előbb a kódját futtatja a pontig); then: sikeres mentés után.'
                 if w.get('commit_points') else '')
        .replace('__PRELUDE_ARGS__', 'prelude: Record<string, unknown> | null = null, then: (() => void) | null = null'
                 if w.get('commit_points') else '')
        .replace('__PRELUDE_SPREAD__', ', ...(prelude ?? {})' if w.get('commit_points') else '')
        .replace('__NO_PRELUDE__', ' && !prelude' if w.get('commit_points') else '')
        .replace('__THEN__', '\n        then?.();' if w.get('commit_points') else '')]



RUNTIME_FILE = 'frm-forms-screen.ts'
RUNTIME_IMPORT = '../frm-forms-screen'


def runtime_source() -> str:
    """frontend/frm-forms-screen.ts: the Forms runtime every generated screen extends (one copy per project)."""
    from pathlib import Path
    return (Path(__file__).with_name('templates') / 'frm-forms-screen.ts.tpl').read_text(encoding='utf-8')


def runtime_fields(w: dict) -> list[str]:
    """The screen's data for FrmFormsScreen: overrides of the base fields, nothing of its own state."""
    result = ['  // Forms-futtatókörnyezet emuláció: frm-forms-screen.ts; itt a képernyő adatai.\n'
              '  protected override cursorBlock = ' + json.dumps(w.get('first_block') or '') + ';']
    if w.get('alerts'):
        result.append('  protected override readonly alertDefinitions: Record<string, { title: string; text: string; buttons: string[] }> = '
                      + ts(w['alerts'], 1) + ';')
    if w.get('form_routes'):
        result.append('  protected override readonly formRoutes: Record<string, string> = ' + ts(w['form_routes'], 1) + ';')
    result.append('  protected override readonly screenBlockNames: readonly string[] = ' + json.dumps(sorted(w['screen_keys'])) + ';')
    if w.get('init') and w['init'] != '@INIT':
        result.append('  protected override readonly initAction = ' + json.dumps(w['init']) + ';')
    if w.get('commit'):
        blocks = {block: {'request': spec['request'], 'result': spec['result'], 'operations': spec['operations']}
                  for block, spec in w['commit']['blocks'].items()}
        result.append('  // Forms COMMIT_FORM: a mentett blokkok a commit-kérés mezőivel és a megengedett műveletekkel.\n'
                      '  protected override readonly commitBlocks: Record<string, { request: string; result: string; operations: readonly string[] }> = '
                      + ts(blocks, 1) + ';\n'
                      '  protected override readonly commitEndpoint = (request: Record<string, unknown>) => this.' + w['commit']['call'] + '(request);')
    return result


def runtime_hooks(w: dict) -> list[str]:
    """The screen-specific parts FrmFormsScreen asks for: the tables' selected rows, CLEAR_BLOCK of a table,
    windows and canvases (SHOW_WINDOW, SHOW_VIEW)."""
    result = []
    if w['tables']:
        selections = ''.join(f"    if (this.{prop}Selection) records[{json.dumps(block)}] = {{ ...this.{prop}Selection }};\n" for block, prop in w['tables'])
        result.append('''  /** A táblázatok kijelölt sorai (Forms: a blokk aktuális rekordja). */
  protected override selectedRecords(): Record<string, Record<string, unknown>> {
    const records: Record<string, Record<string, unknown>> = {};
__SELECTIONS__    return records;
  }'''.replace('__SELECTIONS__', selections))
        cases = ''.join(f"      case {json.dumps(block)}: this.{prop}Rows = []; this.{prop}Selection = null; break;\n" for block, prop in w['tables'])
        result.append('''  protected override clearTable(block: string): void {
    switch (block) {
__CASES__      default: break;
    }
  }'''.replace('__CASES__', cases))
    if w.get('window_type'):
        result.append(f'''  protected override formsWindow(name: string, visible: boolean): void {{
    if (Object.hasOwn(this.windowVisible(), name)) this.setWindowVisible(name as {w['window_type']}, visible);
  }}''')
    if w.get('canvas_type'):
        result.append(f'''  protected override formsCanvas(name: string, visible: boolean): void {{
    if (!Object.hasOwn(this.canvasVisible(), name)) return;
    if (visible) this.showCanvas(name as {w['canvas_type']}); else this.hideCanvas(name as {w['canvas_type']});
  }}''')
    return result

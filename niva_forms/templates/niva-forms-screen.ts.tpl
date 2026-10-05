// NIVA Forms képernyő-futtató. Egyszer kell a projektbe tenni, a generált képernyők mappája mellé;
// minden generált képernyő ezt örökli, így egy javítás itt minden képernyőre érvényes, újragenerálás nélkül.
// A generált képernyők a NIVA_FORMS_SCREEN_VERSION változatot várják: ha a migrátor újat ad, ezt az egy fájlt kell cserélni.
import { ChangeDetectorRef, Directive, inject } from '@angular/core';
import { FormGroup } from '@angular/forms';
import { Router } from '@angular/router';
import { Observable } from 'rxjs';
// TODO: importáld a saját csomagodból: ServiceBase (java-imports.json).

export const NIVA_FORMS_SCREEN_VERSION = '1';

/** Helyi idő ISO-alakban, időzóna nélkül (Oracle DATE). */
export function localIso(value: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())}T${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`;
}

/** A képernyő ToastService-e: cím, részletek, mentés az előzményekbe, élettartam. */
export interface NivaToast {
  success(title: string, detail: string, history?: boolean, life?: number): void;
  warning(title: string, detail: string, history?: boolean, life?: number): void;
}

export interface NivaToastLife {
  readonly success: number;
  readonly warning: number;
  readonly danger: number;
}

/** Felismert gomblépés (GO_BLOCK, EXECUTE_QUERY ...): a képernyő backendhívás nélkül hajtja végre. */
export interface NivaFormsStep {
  op: string;
  block?: string;
  item?: string;
  window?: string;
  canvas?: string;
  text?: string;
}

export interface NivaActionResult {
  blocks?: Record<string, Record<string, string | null>>;
  messages?: string[];
  /** A Forms-hívások felületi utasításként, sorrendben: [művelet, argumentumok...]. */
  commands?: (string | null)[][];
  /** A kód által írt :GLOBAL értékek. */
  globals?: Record<string, string | null>;
}

export interface NivaCommitResult extends NivaActionResult {
  /** A mentett rekordok blokkonként: <blokk>Rows. */
  [rows: string]: unknown;
}

export interface NivaPage {
  rows?: Record<string, unknown>[] | null;
  messages?: string[];
}

export type NivaActionCall = (request: { blocks: Record<string, Record<string, string | null>>; parameters: Record<string, string>;
  offset?: number; limit?: number }) => Observable<unknown>;

export interface NivaItemState {
  enabled?: boolean;
  visible?: boolean;
  required?: boolean;
  editable?: boolean;
}

/** Forms COMMIT_FORM: a blokk a commit-kérés melyik mezőjében megy, és mit enged. */
export interface NivaCommitBlock {
  request: string;
  result: string;
  operations: readonly string[];
}

/** A backend lista/keresés felső korlátja (1..200). */
export const NIVA_QUERY_LIMIT = 200;

const STEP_COMMANDS: Record<string, string> = {
  goBlock: 'GO_BLOCK', goItem: 'GO_ITEM', executeQuery: 'EXECUTE_QUERY', commit: 'COMMIT_FORM', createRecord: 'CREATE_RECORD',
  clearBlock: 'CLEAR_BLOCK', clearForm: 'CLEAR_FORM', clearRecord: 'CLEAR_RECORD', showWindow: 'SHOW_WINDOW',
  hideWindow: 'HIDE_WINDOW', showCanvas: 'SHOW_VIEW', hideCanvas: 'HIDE_VIEW', exitForm: 'EXIT_FORM', enterQuery: 'ENTER_QUERY',
  listValues: 'LIST_VALUES',
};

// Forms SET_ITEM_PROPERTY tulajdonság -> a képernyő mezőállapota.
const ITEM_PROPERTIES: Record<string, keyof NivaItemState> = {
  ENABLED: 'enabled', VISIBLE: 'visible', DISPLAYED: 'visible', REQUIRED: 'required',
  UPDATE_ALLOWED: 'editable', INSERT_ALLOWED: 'editable', UPDATEABLE: 'editable', INSERTABLE: 'editable',
};

/**
 * A generált képernyők közös Forms-futtatója: gombok és indítási kód (a backend PL/SQL-je, a Forms-hívások
 * felületi utasításként), :GLOBAL és :SYSTEM kontextus, alertek, rekordállapotok és a mentési lánc (COMMIT_FORM).
 *
 * A képernyő adja az adatait (protected override readonly ...) és a hook-okat (executeQuery, showRows,
 * selectedRecords, clearTable, setItemState, stateRecord, formsWindow, formsCanvas, commitEndpoint).
 */
@Directive()
export abstract class NivaFormsScreen extends ServiceBase {
  /** A képernyő ToastService-e (protected readonly toast = inject(ToastService)). */
  protected abstract readonly toast: NivaToast;
  protected abstract readonly toastLife: NivaToastLife;
  protected readonly changeDetector = inject(ChangeDetectorRef);
  protected readonly router = inject(Router);

  // A képernyő adatai: a generált képernyő felülírja őket.
  protected readonly formGroups: Record<string, FormGroup> = Object.create(null);
  protected readonly formValues: Record<string, Record<string, unknown>> = Object.create(null);
  /** Régió (FormBlock) -> Forms-blokk. */
  protected readonly regionBlocks: Record<string, string> = {};
  /** Képernyő-vezérlő -> Oracle mezőnév (az ActionRequest szerződése), blokkonként. */
  protected readonly oracleNames: Record<string, Record<string, string>> = {};
  /** Backend DTO-mező -> képernyő-vezérlő, blokkonként. */
  protected readonly rowKeys: Record<string, Record<string, string>> = {};
  /** Checkbox: [Checked, Unchecked] Forms-érték. */
  protected readonly checkboxValues: Record<string, Record<string, readonly [string, string]>> = {};
  /** Gomb (Oracle BLOKK.ITEM) -> a generált akció-végpont hívása. */
  protected readonly actionEndpoints: Record<string, NivaActionCall> = {};
  protected readonly actionSteps: Record<string, readonly NivaFormsStep[]> = {};
  /** Lekérdező gomb -> a blokk, amelynek a sorait adja. */
  protected readonly queryActionBlocks: Record<string, string> = {};
  protected readonly activeQueryActions: Record<string, string> = {};
  protected readonly commitBlocks: Record<string, NivaCommitBlock> = {};
  /** Forms-alertek (cím, szöveg, gombfeliratok) az XML-ből; a SET_ALERT_PROPERTY felülírhatja őket. */
  protected readonly alertDefinitions: Record<string, { title: string; text: string; buttons: string[] }> = {};
  /** CALL_FORM/OPEN_FORM/NEW_FORM cél -> Angular útvonal (config: form_routes, alapból /<formnév>). */
  protected readonly formRoutes: Record<string, string> = {};
  /** A képernyő blokkjai (CLEAR_FORM). */
  protected readonly screenBlockNames: readonly string[] = [];
  /** Az indítási kód végpontja (PRE-FORM, WHEN-NEW-FORM-INSTANCE): nincs „Kész” üzenet. */
  protected readonly initAction: string = '@INIT';
  /** Forms COMMIT_FORM: a generált mentési végpont; null: nincs. */
  protected readonly commitEndpoint: ((request: Record<string, unknown>) => Observable<unknown>) | null = null;

  // Forms-futtatókörnyezet emuláció: kurzor, paraméterlisták, rekordcsoportok, a nyitott alert, rekordállapotok.
  protected cursorBlock = '';
  protected cursorItem = '';
  protected readonly paramLists: Record<string, Record<string, string | null>> = {};
  protected readonly recordGroups: Record<string, { columns: string[]; rows: Record<string, string | null>[] }> = {};
  protected formsAlert: { title: string; text: string; buttons: string[]; resolve: (choice: number) => void } | null = null;
  /** A lekérdezett rekord (a backend DTO-ja, rejtett kulcsokkal) blokkonként, és a törlésre jelöltek. */
  protected readonly originals: Record<string, Record<string, unknown> | null> = {};
  protected readonly pendingDeletes: Record<string, Record<string, unknown>[]> = {};

  // ---------------------------------------------------------------- hook-ok: a képernyő felülírja

  /** Forms EXECUTE_QUERY a blokk generált keresés/lista végpontján. false: nincs hozzá végpont. */
  public executeQuery(_block: string): boolean {
    return false;
  }

  /** A lekérdezett sorok a képernyőn (táblázat vagy űrlap). */
  protected showRows(_block: string, _rows: readonly Record<string, unknown>[]): void {
    // nincs lekérdezhető blokk
  }

  /** A táblázatok kijelölt sorai blokkonként (Forms: a blokk aktuális rekordja). */
  protected selectedRecords(): Record<string, Record<string, unknown>> {
    return {};
  }

  /** CLEAR_BLOCK egy táblázatos blokkon. */
  protected clearTable(_block: string): void {
    // nincs táblázat
  }

  protected setItemState(owner: string, state: NivaItemState): void {
    console.warn('SET_ITEM_PROPERTY: a képernyőn nincs állapotkezelés', owner, state);
  }

  /** Forms WHEN-NEW-RECORD-INSTANCE / POST-QUERY állapotai. */
  protected stateRecord(_block: string): void {
    // nincs rekordszintű állapot
  }

  protected formsWindow(name: string, visible: boolean): void {
    void name; void visible;
  }

  protected formsCanvas(name: string, visible: boolean): void {
    void name; void visible;
  }

  // ---------------------------------------------------------------- értékek

  /** A válasz hasznos tartalma; ha boríték érkezik, annak adatmezője (a mezőnév-lista itt igazítható). */
  protected payload<T>(response: unknown): T {
    if (response && typeof response === 'object') {
      for (const field of ['data', 'result', 'payload', 'body', 'content']) {
        const value = (response as Record<string, unknown>)[field];
        if (value && typeof value === 'object') return value as T;
      }
    }
    return response as T;
  }

  protected wireText(block: string, key: string, value: unknown): string | null {
    const pair = this.checkboxValues[block]?.[key];
    if (pair && typeof value === 'boolean') return value ? pair[0] : pair[1];
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return localIso(value);
    return String(value);
  }

  protected value(block: string, key: string): unknown {
    return this.formValues[block]?.[key];
  }

  protected showRecord(block: string, record: Record<string, unknown>): void {
    this.changeDetector.markForCheck();
    Object.assign(this.formValues[block] ??= {}, record);
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.regionBlocks[region] === block) group.patchValue(record, { emitEvent: false });
    }
    this.stateRecord(block);
  }

  protected applyOracleValues(block: string, values: Record<string, string | null>): void {
    const names = this.oracleNames[block] ?? {};
    const keys = Object.fromEntries(Object.entries(names).map(([key, oracle]) => [oracle, key]));
    const record = Object.fromEntries(Object.entries(values).filter(([oracle]) => oracle in keys).map(([oracle, value]) => [keys[oracle], value]));
    this.showRecord(block, record);
  }

  /** A képernyő aktuális rekordjai Oracle-nevekkel (a Forms-triggerek :BLOKK.MEZŐ értékei). */
  protected screenBlocks(): Record<string, Record<string, string | null>> {
    const records: Record<string, Record<string, unknown>> = {};
    for (const [block, values] of Object.entries(this.formValues)) records[block] = { ...values };
    Object.assign(records, this.selectedRecords());
    const blocks: Record<string, Record<string, string | null>> = {};
    for (const [block, values] of Object.entries(records)) {
      const names = this.oracleNames[block] ?? {};
      blocks[block] = Object.fromEntries(Object.entries(values).filter(([key]) => key in names).map(([key, value]) => [names[key], this.wireText(block, key, value)]));
    }
    return blocks;
  }

  /** A blokk rekordja a backend DTO-jaként: a lekérdezett rekord (rejtett mezők, ROWID) a képernyő értékeivel. */
  protected recordOf(block: string, original: Record<string, unknown> | null): Record<string, unknown> {
    const record: Record<string, unknown> = { ...(original ?? {}) };
    const values = this.formValues[block] ?? {};
    for (const [field, key] of Object.entries(this.rowKeys[block] ?? {})) record[field] = this.wireText(block, key, values[key]);
    return record;
  }

  // ---------------------------------------------------------------- gombok és indítási kód

  /** Felismert gomblépések (GO_BLOCK, EXECUTE_QUERY, CREATE_RECORD, COMMIT_FORM ...): a képernyő hajtja végre. */
  protected runSteps(steps: readonly NivaFormsStep[] | null): boolean {
    if (!steps?.length) return false;
    const commands: (string | null)[][] = [];
    for (const step of steps) {
      if (step.op === 'message') {
        this.toast.warning('Üzenet', step.text ?? '', true, this.toastLife.warning);
        continue;
      }
      const command = STEP_COMMANDS[step.op];
      if (!command) return false;
      commands.push([command, step.block ?? step.item ?? step.window ?? step.canvas ?? null]);
    }
    this.runCommands(commands);
    return true;
  }

  /** Gomb a generált akció-végponton: aktuális rekordok Oracle nevekkel, a válasz visszaírva.
   *  answers: az eddigi alert-válaszok (a kód újrafut, és ezeket kapja a SHOW_ALERT).
   *  resume: mentési pont után a folytatás (NIVA.RESUME; COMMIT_FORM a kód közepén). */
  protected runAction(ownId: string, answers: readonly number[] = [], resume = 0): boolean {
    const call = this.actionEndpoints[ownId];
    if (!call) return false;
    const blocks = this.screenBlocks();
    const parameters: Record<string, string> = { ...this.requestContext(answers), ...(resume ? { 'NIVA.RESUME': String(resume) } : {}) };
    const target = this.queryActionBlocks[ownId];
    call({ blocks, parameters, ...(target ? { offset: 0, limit: NIVA_QUERY_LIMIT } : {}) }).subscribe({
      next: response => {
        if (target) {
          const page = this.payload<NivaPage>(response);
          if (page.rows != null) {
            this.activeQueryActions[target] = ownId;
            this.showRows(target, page.rows);
            if (!page.rows.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, this.toastLife.warning);
          }
          if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, this.toastLife.warning);
          return;
        }
        const result = this.payload<NivaActionResult>(response);
        const alert = result.commands?.find(command => command[0] === 'SHOW_ALERT');
        if (alert) {
          // Forms SHOW_ALERT: a kérés munkája visszagörgetve; a válasszal a kód elölről fut.
          this.askAlert(alert, choice => this.runAction(ownId, [...answers, choice], resume));
          return;
        }
        const point = result.commands?.find(command => command[0] === 'NIVA_COMMIT');
        if (point) {
          // COMMIT_FORM a kód közepén: a mentés előtti értékek a képernyőre, mentés (a backend a mentési pontig
          // újrafuttatja a gomb kódját ugyanebben a tranzakcióban), majd a kód folytatása a pont után.
          if (result.globals) this.rememberGlobals(result.globals);
          for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyChanged(block, values);
          this.formsCommit({ action: ownId, actionBlocks: blocks, actionParameters: { ...parameters, 'NIVA.COMMIT_POINT': point[1] ?? '', 'NIVA.COMMIT_STATE': point[2] ?? '' } },
                           () => this.runAction(ownId, [], Number(point[1])));
          return;
        }
        if (result.globals) this.rememberGlobals(result.globals);
        for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyOracleValues(block, values);
        this.runCommands(result.commands ?? []);
        if (result.messages?.length) this.toast.success('Üzenet', result.messages.join(' '), true, this.toastLife.success);
        else if (ownId !== this.initAction) this.toast.success('Kész', 'A művelet sikeresen lefutott.', true, this.toastLife.success);
      },
      error: () => undefined, // WFF.err már jelezte
    });
    return true;
  }

  /** :GLOBAL értékek: a böngészőfülön belül közösek a formok között (Forms: munkamenet-szintű globálisok). */
  protected formsGlobals(): Record<string, string | null> {
    try {
      const stored: unknown = JSON.parse(sessionStorage.getItem('niva.forms.globals') ?? '{}');
      return stored && typeof stored === 'object' ? stored as Record<string, string | null> : {};
    } catch {
      return {};
    }
  }

  protected rememberGlobals(values: Record<string, string | null>): void {
    try {
      sessionStorage.setItem('niva.forms.globals', JSON.stringify({ ...this.formsGlobals(), ...values }));
    } catch {
      // privát mód / tiltott tárhely: a globálisok csak ebben a kérésben élnek
    }
  }

  /** A kérés képernyő-kontextusa: :GLOBAL, :PARAMETER (az URL query paraméterei), :SYSTEM és az alert-válaszok. */
  protected requestContext(answers: readonly number[]): Record<string, string> {
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
    if (answers.length) context['NIVA.ALERTS'] = answers.join(',');
    return context;
  }

  /** :SYSTEM.FORM_STATUS / BLOCK_STATUS közelítése: módosított űrlap = CHANGED. */
  protected formsStatus(block?: string): string {
    const groups = Object.entries(this.formGroups).filter(([region]) => !block || this.regionBlocks[region] === block);
    return groups.some(([, group]) => group.dirty) ? 'CHANGED' : 'QUERY';
  }

  /** A backend által visszaadott Forms-hívások végrehajtása, sorrendben. */
  protected runCommands(commands: readonly (readonly (string | null)[])[]): void {
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
        case 'CLEAR_FORM': for (const block of this.screenBlockNames) this.clearBlock(block); break;
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
  }

  protected formsQuery(block: string): void {
    if (!this.executeQuery(block)) this.toast.warning('Lekérdezés', 'Ehhez a blokkhoz nincs generált lekérdezés: ' + block, true, this.toastLife.warning);
  }

  protected formsItemProperty(item: string, property: string, value: string): void {
    const owner = item.includes('.') ? item : this.cursorBlock + '.' + item;
    const on = ['PROPERTY_TRUE', 'PROPERTY_ON', 'TRUE'].includes(value);
    const state = ITEM_PROPERTIES[property];
    if (state) this.setItemState(owner, { [state]: on });
    else console.warn('SET_ITEM_PROPERTY nincs leképezve:', owner, property, value);
  }

  protected clearBlock(block: string): void {
    this.originals[block] = null;  // Forms: a new record, nothing queried
    this.formValues[block] = {};
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.regionBlocks[region] === block) group.reset({}, { emitEvent: false });
    }
    this.clearTable(block);
  }

  /** CALL_FORM/OPEN_FORM/NEW_FORM: navigáció a cél form útvonalára, a paraméterlista query paraméterként. */
  protected formsCall(form: string, args: readonly string[]): void {
    const list = args.find(name => Object.hasOwn(this.paramLists, name));
    const queryParams: Record<string, string> = {};
    for (const [name, value] of Object.entries(list ? this.paramLists[list] : {})) if (value !== null) queryParams[name] = value;
    const route = this.formRoutes[form] ?? '/' + form.toLowerCase();
    void this.router.navigate([route], { queryParams });
  }

  protected formsKey(key: string): void {
    switch (key) {
      case 'EXECUTE_QUERY': this.formsQuery(this.cursorBlock); break;
      case 'COMMIT_FORM': this.formsCommit(); break;
      case 'CLEAR_BLOCK': case 'CREATE_RECORD': this.clearBlock(this.cursorBlock); break;
      case 'EXIT_FORM': window.history.back(); break;
      case 'LIST_VALUES': case 'ENTER_QUERY': break;
      default: console.warn('DO_KEY nincs bekötve:', key);
    }
  }

  /** Futásidőben épített Forms-rekordcsoportok (CREATE_GROUP ...), például statikus LOV-listákhoz. */
  protected recordGroup(op: string, args: readonly (string | null)[]): void {
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
  }

  /** Forms SHOW_ALERT: párbeszédablak; a választott gomb (1..3) száma a kód újrafuttatásába kerül. */
  protected askAlert(command: readonly (string | null)[], then: (choice: number) => void): void {
    const name = (command[1] ?? '').toUpperCase();
    const definition = this.alertDefinitions[name] ?? { title: name, text: '', buttons: ['OK'] };
    const buttons = [0, 1, 2].map(index => command[3 + index] || definition.buttons[index] || '').filter(label => label !== '');
    this.formsAlert = { title: definition.title || name, text: command[2] || definition.text, buttons: buttons.length ? buttons : ['OK'], resolve: then };
    this.changeDetector.markForCheck();
  }

  protected answerAlert(choice: number): void {
    const alert = this.formsAlert;
    this.formsAlert = null;
    alert?.resolve(choice);
  }

  // ---------------------------------------------------------------- rekordállapotok és mentés (COMMIT_FORM)

  /** A blokk mezői mentett állapotúak: a következő mentés csak az ezutáni változást küldi. */
  protected markPristine(block: string): void {
    for (const [region, group] of Object.entries(this.formGroups)) if (this.regionBlocks[region] === block) group.markAsPristine();
  }

  /** Forms DELETE_RECORD: a lekérdezett rekord törlésre jelölve (a Mentés véglegesíti), az új csak ürül. */
  protected formsDelete(block: string): void {
    const original = this.originals[block];
    if (original) (this.pendingDeletes[block] ??= []).push(original);
    this.clearBlock(block);
    this.markPristine(block);
  }

  /** A képernyő eszköztára (Forms: CREATE_RECORD, DELETE_RECORD, COMMIT_FORM az aktuális blokkon). */
  protected onToolbar(action: 'new' | 'delete' | 'save'): void {
    if (action === 'save') {
      this.formsCommit();
      return;
    }
    const block = Object.hasOwn(this.commitBlocks, this.cursorBlock) ? this.cursorBlock : Object.keys(this.commitBlocks)[0];
    if (action === 'new') this.clearBlock(block);
    else {
      this.formsDelete(block);
      this.toast.warning('Törlés', 'A rekord törlésre jelölve; a Mentés véglegesíti.', true, this.toastLife.warning);
    }
    this.cursorBlock = block;
    this.changeDetector.markForCheck();
  }

  /** Egy gomb mentés előtti mezőértékei: a megváltozott blokk mentendő lesz (Forms: a rekord CHANGED állapotú). */
  protected applyChanged(block: string, values: Record<string, string | null>): void {
    const before = JSON.stringify(this.screenBlocks()[block] ?? {});
    this.applyOracleValues(block, values);
    if (JSON.stringify(this.screenBlocks()[block] ?? {}) === before) return;
    for (const [region, group] of Object.entries(this.formGroups)) if (this.regionBlocks[region] === block) group.markAsDirty();
  }

  /** Forms COMMIT_FORM: a képernyő összes változása egy kérésben; a backend Forms-sorrendben, a triggerekkel menti.
   *  prelude: mentési pontos gomb (a backend előbb a kódját futtatja a pontig); then: sikeres mentés után. */
  protected formsCommit(prelude: Record<string, unknown> | null = null, then: (() => void) | null = null): void {
    const endpoint = this.commitEndpoint;
    if (!endpoint) {
      this.toast.warning('Mentés', 'Ehhez a képernyőhöz nincs generált mentési végpont.', true, this.toastLife.warning);
      return;
    }
    const request: Record<string, unknown> = { blocks: this.screenBlocks(), parameters: this.requestContext([]), ...(prelude ?? {}) };
    let changed = false;
    for (const [block, spec] of Object.entries(this.commitBlocks)) {
      const changes: { inserted: unknown[]; updated: { original: unknown; value: unknown }[]; deleted: unknown[] } =
        { inserted: [], updated: [], deleted: [...(this.pendingDeletes[block] ?? [])] };
      const groups = Object.entries(this.formGroups).filter(([region]) => this.regionBlocks[region] === block).map(([, group]) => group);
      if (groups.some(group => group.dirty)) {
        if (groups.some(group => group.invalid)) {
          for (const group of groups) group.markAllAsTouched();
          this.toast.warning('Hiányzó vagy hibás adat', 'Ellenőrizd a(z) ' + block + ' mezőit.', true, this.toastLife.warning);
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
    if (!changed && !prelude) {
      this.toast.warning('Mentés', 'Nincs mentendő változás.', true, this.toastLife.warning);
      return;
    }
    endpoint(request).subscribe({
      next: response => {
        const result = this.payload<NivaCommitResult>(response);
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
        this.toast.success('Mentve', result.messages?.join(' ') || 'A változások mentése sikerült.', true, this.toastLife.success);
        then?.();
      },
      error: () => undefined, // WFF.err már jelezte; a tranzakció visszagörgetve, a képernyő változatlan
    });
  }
}

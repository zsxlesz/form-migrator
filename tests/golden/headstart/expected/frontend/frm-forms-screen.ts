// FRM Forms képernyő-futtató: egyszer kell a projektbe tenni, minden generált képernyő ezt örökli.
// A generált képernyők a FRM_FORMS_SCREEN_VERSION változatot várják: új változatnál ezt az egy fájlt kell cserélni.
import { ChangeDetectorRef, Component, DestroyRef, Directive, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl, FormGroup, ValidationErrors, ValidatorFn, Validators } from '@angular/forms';
import { Observable, Subscription, catchError, tap } from 'rxjs';
import { TableModule } from '@openng/optimus-ui/table';
import { ButtonModule } from '@openng/optimus-ui/button';
import { DialogModule } from '@openng/optimus-ui/dialog';
// TODO: importáld a saját csomagodból: ServiceBase, WFF (java-imports.json).

export const FRM_FORMS_SCREEN_VERSION = '5';
export const FRM_QUERY_LIMIT = 200;

export type FrmOracleValues = Record<string, Record<string, string | null>>;
export type FrmActionCall = (request: { blocks: FrmOracleValues; parameters: Record<string, string>; offset?: number; limit?: number }) => Observable<unknown>;

export interface FrmToast {
  success(title: string, detail: string, history?: boolean, life?: number): void;
  warning(title: string, detail: string, history?: boolean, life?: number): void;
}

export interface FrmToastLife {
  readonly success: number;
  readonly warning: number;
  readonly danger: number;
}

export interface FrmFormsStep {
  op: string;
  block?: string;
  item?: string;
  window?: string;
  canvas?: string;
  text?: string;
}

export interface FrmActionResult {
  blocks?: FrmOracleValues;
  messages?: string[];
  commands?: (string | null)[][];
  globals?: Record<string, string | null>;
}

export interface FrmCommitResult extends FrmActionResult {
  [rows: string]: unknown;
}

export interface FrmPage {
  rows?: Record<string, unknown>[] | null;
  messages?: string[];
}

export interface FrmItemState {
  enabled?: boolean;
  visible?: boolean;
  required?: boolean;
  editable?: boolean;
}

export interface FrmCommitBlock {
  request: string;
  result: string;
  operations: readonly string[];
}

export interface FrmField {
  ownId?: string;
  formControlName?: string;
  labelText?: string;
  disabled?: boolean;
  invisible?: boolean;
  validator?: boolean;
  readonly?: boolean;
  minLenght?: number;
  maxLenght?: number;
  regexRule?: { regex: RegExp };
  suggestions?: unknown[];
}

export interface FrmColumn {
  field: string;
  header: string;
  width: string;
}

export interface FrmRowAction {
  ownId: string;
  label: string;
  disabled?: boolean;
}

export interface FrmTable {
  columns: FrmColumn[];
  pageSize: number;
  actions?: FrmRowAction[];
  rows: Record<string, unknown>[];
  selection: Record<string, unknown> | null;
}

export interface FrmQuery {
  call: (request: { criteria: Record<string, string | null>; offset: number; limit: number }) => Observable<unknown>;
  criteria?: Record<string, string>;
}

export interface FrmLov {
  call: (request: { term: string | null; parameters: Record<string, string>; limit: number }) => Observable<unknown>;
  columns: Record<string, string>;
  binds?: Record<string, string>;
}

export interface FrmLovChoice {
  label: string;
  value: string | number | null;
  returnValues?: Record<string, unknown>;
}

export interface FrmNavigation {
  route: string;
  params: Record<string, string>;
}

export interface FrmAlert {
  title: string;
  text: string;
  buttons: string[];
}

export type FrmToolbarAction = 'new' | 'delete' | 'save';

export function localIso(value: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())}T${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`;
}

export function frmTable(pageSize: number, columns: readonly (readonly [string, string, string])[], actions?: FrmRowAction[]): FrmTable {
  return { columns: columns.map(([field, header, width]) => ({ field, header, width })), pageSize, actions, rows: [], selection: null };
}

export const FrmValidators = {
  number(rule: { min?: string; max?: string; precision?: number; scale?: number; integer?: boolean } = {}): ValidatorFn {
    const decimal = (text: string) => {
      if (text.length > 260) return null;
      const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
      return match ? { digits: BigInt(match[2] + (match[3] ?? '')) * (match[1] === '-' ? -1n : 1n),
        scale: (match[3] ?? '').length, integral: match[2].replace(/^0+/, '').length } : null;
    };
    const minimum = rule.min === undefined ? null : decimal(rule.min);
    const maximum = rule.max === undefined ? null : decimal(rule.max);
    return control => {
      const value: unknown = control.value;
      if (value == null || value === '') return null;
      if (rule.integer ? !Number.isSafeInteger(value) : typeof value !== 'string') return { number: true };
      const parsed = decimal(String(value));
      if (!parsed) return { number: true };
      const compare = (bound: NonNullable<ReturnType<typeof decimal>>) => {
        const scale = Math.max(parsed.scale, bound.scale);
        const a = parsed.digits * 10n ** BigInt(scale - parsed.scale), b = bound.digits * 10n ** BigInt(scale - bound.scale);
        return a < b ? -1 : a > b ? 1 : 0;
      };
      if (rule.scale !== undefined && parsed.scale > rule.scale) return { scale: true };
      if (rule.precision !== undefined && parsed.integral + (rule.scale ?? parsed.scale) > rule.precision) return { precision: true };
      if (minimum && compare(minimum) < 0) return { min: { min: rule.min, actual: value } };
      if (maximum && compare(maximum) > 0) return { max: { max: rule.max, actual: value } };
      return null;
    };
  },
  date: (control: AbstractControl): ValidationErrors | null =>
    control.value == null || control.value === '' || control.value instanceof Date && Number.isFinite(control.value.getTime()) ? null : { date: true },
  checkbox: (control: AbstractControl): ValidationErrors | null =>
    control.value == null || control.value === '' || typeof control.value === 'boolean' ? null : { checkbox: true },
  checked: (control: AbstractControl): ValidationErrors | null =>
    control.value === null || control.value === undefined || control.value === '' ? { required: true } : null,
};

@Component({
  selector: 'frm-table',
  standalone: true,
  imports: [TableModule, ButtonModule],
  template: `
    <p-table [value]="table().rows" [columns]="table().columns" [paginator]="true" [rows]="table().pageSize" size="small"
      [showGridlines]="true" [scrollable]="true" selectionMode="single" [selection]="table().selection" (selectionChange)="select($event)">
      <ng-template #header><tr>
        @for (col of table().columns; track col.field) { <th [style.width]="col.width" class="whitespace-nowrap">{{ col.header }}</th> }
        @if (table().actions?.length) { <th>Műveletek</th> }
      </tr></ng-template>
      <ng-template #body let-row><tr [pSelectableRow]="row">
        @for (col of table().columns; track col.field) { <td>{{ row[col.field] }}</td> }
        @if (table().actions?.length) {
          <td class="whitespace-nowrap">
            @for (button of table().actions; track button.ownId) {
              <button pButton type="button" [disabled]="!!button.disabled" (click)="$event.stopPropagation(); select(row); action.emit(button.ownId)">{{ button.label }}</button>
            }
          </td>
        }
      </tr></ng-template>
      <ng-template #emptymessage><tr><td [attr.colspan]="table().columns.length + (table().actions?.length ? 1 : 0)" class="py-4 text-center">Nincs megjeleníthető adat.</td></tr></ng-template>
    </p-table>
  `,
})
export class FrmTableComponent {
  readonly table = input.required<FrmTable>();
  readonly action = output<string>();

  select(row: Record<string, unknown> | null): void {
    this.table().selection = row;
  }
}

@Component({
  selector: 'frm-toolbar',
  standalone: true,
  imports: [ButtonModule],
  template: `
    <div class="flex justify-end gap-2">
      @if (actions().includes('new')) { <button pButton type="button" severity="secondary" (click)="action.emit('new')">Új rekord</button> }
      @if (actions().includes('delete')) { <button pButton type="button" severity="secondary" (click)="action.emit('delete')">Törlés</button> }
      @if (actions().includes('save')) { <button pButton type="button" (click)="action.emit('save')">Mentés</button> }
    </div>
  `,
})
export class FrmToolbarComponent {
  readonly actions = input<readonly FrmToolbarAction[]>(['new', 'delete', 'save']);
  readonly action = output<FrmToolbarAction>();
}

@Component({
  selector: 'frm-alert',
  standalone: true,
  imports: [DialogModule, ButtonModule],
  template: `
    @if (alert(); as current) {
      <p-dialog [header]="current.title" [visible]="true" [modal]="true" [closable]="false" [closeOnEscape]="false"
        [dismissableMask]="false" styleClass="w-[95vw] max-w-lg">
        <p class="whitespace-pre-line">{{ current.text }}</p>
        <div class="mt-4 flex justify-end gap-2">
          @for (label of current.buttons; track $index) {
            <button pButton type="button" (click)="answer.emit($index + 1)">{{ label }}</button>
          }
        </div>
      </p-dialog>
    }
  `,
})
export class FrmAlertComponent {
  readonly alert = input<FrmAlert | null>(null);
  readonly answer = output<number>();
}

const STEP_COMMANDS: Record<string, string> = {
  goBlock: 'GO_BLOCK', goItem: 'GO_ITEM', executeQuery: 'EXECUTE_QUERY', commit: 'COMMIT_FORM', createRecord: 'CREATE_RECORD',
  clearBlock: 'CLEAR_BLOCK', clearForm: 'CLEAR_FORM', clearRecord: 'CLEAR_RECORD', showWindow: 'SHOW_WINDOW',
  hideWindow: 'HIDE_WINDOW', showCanvas: 'SHOW_VIEW', hideCanvas: 'HIDE_VIEW', exitForm: 'EXIT_FORM', enterQuery: 'ENTER_QUERY',
  listValues: 'LIST_VALUES',
};

const ITEM_PROPERTIES: Record<string, keyof FrmItemState> = {
  ENABLED: 'enabled', VISIBLE: 'visible', DISPLAYED: 'visible', REQUIRED: 'required',
  UPDATE_ALLOWED: 'editable', INSERT_ALLOWED: 'editable', UPDATEABLE: 'editable', INSERTABLE: 'editable',
};

@Directive()
export abstract class FrmFormsScreen extends ServiceBase {
  protected abstract readonly toast: FrmToast;
  protected abstract readonly toastLife: FrmToastLife;
  protected readonly changeDetector = inject(ChangeDetectorRef);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly structures: Record<string, readonly object[]> = {};
  protected readonly tables: Record<string, FrmTable> = {};
  protected readonly validators: Record<string, ValidatorFn[]> = {};
  protected readonly queries: Record<string, FrmQuery> = {};
  protected readonly lovs: Record<string, FrmLov> = {};
  protected readonly actionEndpoints: Record<string, FrmActionCall> = {};
  protected readonly actionSteps: Record<string, readonly FrmFormsStep[]> = {};
  protected readonly queryActionBlocks: Record<string, string> = {};
  protected readonly checkboxValues: Record<string, Record<string, readonly string[]>> = {};
  protected readonly oracleNames: Record<string, Record<string, string>> = {};
  protected readonly rowKeys: Record<string, readonly (string | readonly string[])[]> = {};
  protected readonly commitBlocks: Record<string, FrmCommitBlock> = {};
  protected readonly commitEndpoint: ((request: Record<string, unknown>) => Observable<unknown>) | null = null;
  protected readonly alertDefinitions: Record<string, FrmAlert> = {};
  protected readonly formRoutes: Record<string, string> = {};
  protected readonly navigations: Record<string, FrmNavigation> = {};
  protected readonly manualNavigations: Record<string, () => void> = {};
  protected readonly changeHandlers: Record<string, () => void> = {};
  protected readonly recordHandlers: Record<string, () => void> = {};
  protected readonly buttonHandlers: Record<string, () => void> = {};
  protected readonly initAction: string = '@INIT';
  protected readonly windowVisible = signal<Record<string, boolean>>({});
  protected readonly canvasVisible = signal<Record<string, boolean>>({});
  protected readonly activeContentCanvas = signal<Record<string, string>>({});
  protected readonly canvasTargets: Record<string, { window: string | null; contentWindow: string | null }> = {};

  protected readonly formGroups: Record<string, FormGroup> = Object.create(null);
  protected readonly formValues: Record<string, Record<string, unknown>> = Object.create(null);
  protected readonly itemStates: Record<string, FrmItemState> = {};
  protected readonly originals: Record<string, Record<string, unknown> | null> = {};
  protected readonly pendingDeletes: Record<string, Record<string, unknown>[]> = {};
  protected readonly activeQueryActions: Record<string, string> = {};
  protected readonly paramLists: Record<string, Record<string, string | null>> = {};
  protected readonly recordGroups: Record<string, { columns: string[]; rows: Record<string, string | null>[] }> = {};
  protected formsAlert: (FrmAlert & { resolve: (choice: number) => void }) | null = null;
  protected cursorBlock = '';
  protected cursorItem = '';
  private readonly subscriptions: Record<string, Subscription> = {};
  private readonly lovTickets: Record<string, number> = {};
  private readonly lovChoices: Record<string, FrmLovChoice[]> = {};

  protected send<T>(name: string, request: Observable<T>): Observable<T> {
    return request.pipe(
      tap(res => WFF.debug(this.modName + '.' + name, res)),
      catchError(error => {
        WFF.err('Hiba', error);
        throw error;
      }),
    );
  }

  protected button(ownId: string) {
    return { btnSeverity: 'primary' as const, onClick: () => this.onAction(ownId) };
  }

  protected lov(ownId: string, lov: string) {
    return { dropdown: true, optionLabel: 'label', optionValue: 'value', suggestions: [] as FrmLovChoice[],
      completeMethod: (event: { query: string }) => this.onLovSearch(ownId, lov, event) };
  }

  // ---------------------------------------------------------------- mezők és űrlapok

  protected fields(region: string): readonly FrmField[] {
    return (this.structures[region] ?? []) as readonly FrmField[];
  }

  protected blockOf(region: string): string {
    return this.fields(region)[0]?.ownId?.split('.')[0] ?? region;
  }

  protected get cursor(): string {
    return this.cursorBlock || this.blockOf(Object.keys(this.structures)[0] ?? '') || Object.keys(this.tables)[0] || '';
  }

  protected oracleName(block: string, key: string): string {
    return this.oracleNames[block]?.[key] ?? key.replace(/[A-Z]/g, c => '_' + c).toUpperCase();
  }

  protected keyOf(block: string, oracle: string): string {
    const named = Object.entries(this.oracleNames[block] ?? {}).find(([, name]) => name === oracle);
    return named ? named[0] : oracle.toLowerCase().replace(/_+([a-z0-9])/g, (_, c: string) => c.toUpperCase());
  }

  protected onFormGroupGenerated(region: string, group: FormGroup): void {
    if (this.formGroups[region] === group) return;
    const block = this.blockOf(region), previous = this.formGroups[region];
    const values = this.formValues[block] ??= {};
    if (previous) Object.assign(values, previous.getRawValue());
    group.patchValue(values, { emitEvent: false });
    if (previous?.dirty) group.markAsDirty();
    if (previous?.touched) group.markAsTouched();
    this.formGroups[region] = group;
    for (const field of this.fields(region)) {
      const control = field.formControlName ? group.get(field.formControlName) : null;
      if (!control) continue;
      control.addValidators(this.fieldValidators(block, field));
      control.updateValueAndValidity({ emitEvent: false });
      const handler = this.changeHandlers[field.ownId ?? ''];
      if (handler) this.watch(region + '.' + field.ownId, control.valueChanges, handler);
    }
    for (const owner of Object.keys(this.itemStates)) this.applyItemState(owner);
    const update = () => {
      Object.assign(values, group.getRawValue());
      this.applyLovReturns(block, group);
    };
    update();
    this.watch(region, group.valueChanges, () => {
      this.cursorBlock = block;
      update();
    });
  }

  private watch(id: string, changes: Observable<unknown>, handler: () => void): void {
    this.subscriptions[id]?.unsubscribe();
    this.subscriptions[id] = changes.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => handler());
  }

  private fieldValidators(block: string, field: FrmField): ValidatorFn[] {
    const result = [...(this.validators[field.ownId ?? ''] ?? [])];
    if (field.validator) result.push(Validators.required);
    if (field.minLenght) result.push(Validators.minLength(field.minLenght));
    if (field.maxLenght) result.push(Validators.maxLength(field.maxLenght));
    if (field.regexRule?.regex) result.push(Validators.pattern(field.regexRule.regex));
    if (this.checkboxValues[block]?.[field.formControlName ?? '']) result.push(FrmValidators.checkbox);
    return result;
  }

  private updateField(ownId: string, change: (field: FrmField) => FrmField): void {
    for (const region of Object.keys(this.structures)) {
      const fields = this.fields(region);
      const index = fields.findIndex(field => field.ownId === ownId);
      if (index < 0) continue;
      const next = change(fields[index]);
      const keys = new Set([...Object.keys(next), ...Object.keys(fields[index])]);
      if ([...keys].every(key => next[key as keyof FrmField] === fields[index][key as keyof FrmField])) continue;
      this.structures[region] = fields.map((field, i) => i === index ? next : field);
    }
  }

  private locate(owner: string): { region: string; block: string; key: string } | null {
    for (const region of Object.keys(this.structures)) {
      const field = this.fields(region).find(f => f.ownId === owner);
      if (field?.formControlName) return { region, block: this.blockOf(region), key: field.formControlName };
    }
    return null;
  }

  protected validBefore(ownId: string): boolean {
    const steps = this.actionSteps[ownId] ?? null;
    const data = steps ? steps.some(step => ['executeQuery', 'commit', 'createRecord', 'deleteRecord'].includes(step.op)) : !!this.actionEndpoints[ownId];
    if (!data) return true;
    const missing: string[] = [];
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (!group.invalid) continue;
      group.markAllAsTouched();
      for (const [key, control] of Object.entries(group.controls)) {
        if (control.invalid) missing.push(this.fields(region).find(field => field.formControlName === key)?.labelText || key);
      }
    }
    if (!missing.length) return true;
    this.toast.warning('Hiányzó vagy hibás adat', 'Ellenőrizd: ' + missing.join(', '), true, this.toastLife.warning);
    return false;
  }

  protected onAction(ownId: string): void {
    const handler = this.buttonHandlers[ownId];
    if (handler) return handler();
    if (!this.validBefore(ownId)) return;
    if (this.navigate(ownId)) return;
    const manual = this.manualNavigations[ownId];
    if (manual) return manual();
    if (this.runSteps(this.actionSteps[ownId] ?? null)) return;
    if (this.runAction(ownId)) return;
    this.toast.warning('Nincs bekötve', 'A gomb kódja kézi átültetést igényel: ' + ownId, true, this.toastLife.warning);
  }

  protected navigate(ownId: string): boolean {
    const target = this.navigations[ownId];
    if (!target) return false;
    const queryParams: Record<string, string> = {};
    for (const [name, source] of Object.entries(target.params)) {
      const dot = source.indexOf('.');
      const raw = source.startsWith('=') ? source.slice(1) : this.value(source.slice(0, dot), source.slice(dot + 1));
      if (raw === null || raw === undefined || raw === '') continue;
      queryParams[name] = raw instanceof Date ? raw.toISOString().slice(0, 10) : String(raw);
    }
    void this.router.navigate([target.route], { queryParams });
    return true;
  }

  // ---------------------------------------------------------------- LOV

  protected onLovSearch(ownId: string, lov: string, event: { query: string }): void {
    const ticket = this.lovTickets[ownId] = (this.lovTickets[ownId] ?? 0) + 1;
    const spec = this.lovs[lov];
    if (!spec) return this.setLovSuggestions(ownId, [], ticket);
    const parameters: Record<string, string> = {};
    for (const [source, target] of Object.entries(spec.binds ?? {})) {
      const [block, key] = target.split('.');
      const value = this.wireText(block, key, this.value(block, key));
      if (value !== null) parameters[source] = value;
    }
    spec.call({ term: event.query || null, parameters, limit: 50 }).subscribe({
      next: response => this.setLovSuggestions(ownId, (this.payload<FrmPage>(response).rows ?? []).map(row => this.lovChoice(ownId, spec.columns, row)), ticket),
      error: () => this.setLovSuggestions(ownId, [], ticket),
    });
  }

  protected setLovSuggestions(ownId: string, choices: FrmLovChoice[], ticket: number): void {
    if (ticket !== this.lovTickets[ownId]) return;
    this.lovChoices[ownId] = choices;
    this.updateField(ownId, field => ({ ...field, suggestions: choices }));
    this.changeDetector.markForCheck();
  }

  private lovChoice(ownId: string, columns: Record<string, string>, row: Record<string, unknown>): FrmLovChoice {
    const names = Object.keys(columns);
    const own = names.find(column => columns[column] === ownId) ?? names[0] ?? Object.keys(row)[0] ?? '';
    const raw = row[own];
    const value = typeof raw === 'number' ? raw : raw === null || raw === undefined ? null : String(raw);
    const shown = (names.length ? names.map(column => row[column]) : [raw]).filter(v => v !== null && v !== undefined && v !== '');
    const returnValues: Record<string, unknown> = {};
    for (const column of names) if (columns[column]) returnValues[columns[column]] = row[column];
    return { label: shown.map(v => String(v)).join(' – '), value, returnValues };
  }

  private applyLovReturns(block: string, group: FormGroup): void {
    for (const [owner, choices] of Object.entries(this.lovChoices)) {
      const target = this.locate(owner);
      if (target?.block !== block || !group.contains(target.key)) continue;
      const value: unknown = group.get(target.key)?.value;
      const selected = choices.find(choice => choice.value === value);
      for (const [returned, returnedValue] of Object.entries(selected?.returnValues ?? {})) {
        const [returnBlock, item] = returned.split('.');
        const key = this.keyOf(returnBlock, item);
        (this.formValues[returnBlock] ??= {})[key] = returnedValue;
        for (const [region, targetGroup] of Object.entries(this.formGroups)) {
          if (this.blockOf(region) === returnBlock) targetGroup.get(key)?.setValue(returnedValue, { emitEvent: false });
        }
      }
    }
  }

  // ---------------------------------------------------------------- mezőállapotok

  protected setItemState(owner: string, state: FrmItemState): void {
    this.itemStates[owner] = { ...this.itemStates[owner], ...state };
    this.applyItemState(owner);
  }

  private applyItemState(owner: string): void {
    const state = this.itemStates[owner];
    if (!state) return;
    this.updateField(owner, field => ({
      ...field,
      ...(state.enabled === undefined ? {} : { disabled: !state.enabled }),
      ...(state.visible === undefined ? {} : { invisible: !state.visible }),
      ...(state.required === undefined ? {} : { validator: state.required }),
      ...(state.editable === undefined ? {} : { readonly: !state.editable }),
    }));
    const target = this.locate(owner);
    const control = target ? this.formGroups[target.region]?.get(target.key) : null;
    if (control) {
      if (state.enabled === false) control.disable({ emitEvent: false });
      else if (state.enabled === true) control.enable({ emitEvent: false });
      if (state.required !== undefined) {
        if (state.required) control.addValidators(Validators.required); else control.removeValidators(Validators.required);
        control.updateValueAndValidity({ emitEvent: false });
      }
    }
    this.changeDetector.markForCheck();
  }

  protected setItemValue(owner: string, value: unknown): void {
    const target = this.locate(owner);
    if (!target) return;
    const pair = this.checkboxValues[target.block]?.[target.key];
    const stored = pair && typeof value === 'string' ? value === pair[0] : value;
    (this.formValues[target.block] ??= {})[target.key] = stored;
    this.formGroups[target.region]?.get(target.key)?.setValue(stored, { emitEvent: false });
  }

  protected stateValue(owner: string): unknown {
    const target = this.locate(owner);
    if (!target) return null;
    const control = this.formGroups[target.region]?.get(target.key);
    const value = control ? control.value : this.formValues[target.block]?.[target.key];
    const pair = this.checkboxValues[target.block]?.[target.key];
    if (pair && typeof value === 'boolean') return value ? pair[0] : pair[1];
    return value === undefined || value === '' ? null : value;
  }

  protected isNull(value: unknown): boolean {
    return value === null || value === undefined || value === '';
  }

  protected cmp(left: unknown, op: string, right: unknown): boolean {
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
  }

  // ---------------------------------------------------------------- ablakok és canvasok

  public setWindowVisible(window: string, visible: boolean): void {
    if (!Object.hasOwn(this.windowVisible(), window) || this.windowVisible()[window] === visible) return;
    this.windowVisible.update(state => ({ ...state, [window]: visible }));
  }

  public showCanvas(canvas: string): void {
    if (!Object.hasOwn(this.canvasVisible(), canvas)) return;
    this.canvasVisible.update(state => ({ ...state, [canvas]: true }));
    const target = this.canvasTargets[canvas];
    const window = target?.contentWindow;
    if (window) this.activeContentCanvas.update(state => ({ ...state, [window]: canvas }));
    if (target?.window) this.setWindowVisible(target.window, true);
  }

  public hideCanvas(canvas: string): void {
    if (Object.hasOwn(this.canvasVisible(), canvas)) this.canvasVisible.update(state => ({ ...state, [canvas]: false }));
  }

  // ---------------------------------------------------------------- értékek, lekérdezés, táblázatok

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

  private rowFields(block: string): [string, string][] {
    return (this.rowKeys[block] ?? []).map(entry => typeof entry === 'string' ? [entry, entry] : [entry[0], entry[1]]);
  }

  protected fromDto(block: string, row: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(this.rowFields(block).filter(([field]) => field in row).map(([field, key]) => [key, row[field]]));
  }

  protected showRecord(block: string, record: Record<string, unknown>): void {
    this.changeDetector.markForCheck();
    Object.assign(this.formValues[block] ??= {}, record);
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.blockOf(region) === block) group.patchValue(record, { emitEvent: false });
    }
    this.recordHandlers[block]?.();
  }

  protected applyOracleValues(block: string, values: Record<string, string | null>): void {
    this.showRecord(block, Object.fromEntries(Object.entries(values).map(([oracle, value]) => [this.keyOf(block, oracle), value])));
  }

  protected screenBlocks(): FrmOracleValues {
    const records: Record<string, Record<string, unknown>> = {};
    for (const [block, values] of Object.entries(this.formValues)) records[block] = { ...values };
    Object.assign(records, this.selectedRecords());
    const blocks: FrmOracleValues = {};
    for (const [block, values] of Object.entries(records)) {
      blocks[block] = Object.fromEntries(Object.entries(values).map(([key, value]) => [this.oracleName(block, key), this.wireText(block, key, value)]));
    }
    return blocks;
  }

  protected recordOf(block: string, original: Record<string, unknown> | null): Record<string, unknown> {
    const record: Record<string, unknown> = { ...(original ?? {}) };
    const values = this.formValues[block] ?? {};
    for (const [field, key] of this.rowFields(block)) record[field] = this.wireText(block, key, values[key]);
    return record;
  }

  public executeQuery(block: string, done?: () => void): boolean {
    const action = this.activeQueryActions[block];
    if (action) return this.runAction(action, [], 0, done);
    const query = this.queries[block];
    if (!query) return false;
    const criteria = Object.fromEntries(Object.entries(query.criteria ?? {}).map(([field, source]) => [field, this.criterion(source)]));
    query.call({ criteria, offset: 0, limit: FRM_QUERY_LIMIT }).subscribe({
      next: response => {
        const page = this.payload<FrmPage>(response);
        this.showRows(block, page.rows ?? []);
        if (!page.rows?.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, this.toastLife.warning);
        if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, this.toastLife.warning);
        done?.();
      },
      error: () => undefined,
    });
    return true;
  }

  private criterion(source: string): string | null {
    if (source.startsWith(':')) return this.requestContext([])[source.slice(1)] ?? null;
    const [block, key] = source.split('.');
    return this.wireText(block, key, this.value(block, key));
  }

  protected showRows(block: string, rows: readonly Record<string, unknown>[]): void {
    this.changeDetector.markForCheck();
    const mapped = rows.map(row => this.fromDto(block, row));
    const table = this.tables[block];
    if (table) {
      table.rows = mapped;
      table.selection = null;
      return;
    }
    this.originals[block] = rows[0] ? { ...rows[0] } : null;
    this.showRecord(block, mapped[0] ?? {});
    this.markPristine(block);
  }

  protected selectedRecords(): Record<string, Record<string, unknown>> {
    const records: Record<string, Record<string, unknown>> = {};
    for (const [block, table] of Object.entries(this.tables)) if (table.selection) records[block] = { ...table.selection };
    return records;
  }

  protected clearTable(block: string): void {
    const table = this.tables[block];
    if (!table) return;
    table.rows = [];
    table.selection = null;
  }

  // ---------------------------------------------------------------- gombok, indítási kód, Forms-utasítások

  protected runSteps(steps: readonly FrmFormsStep[] | null): boolean {
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

  protected runAction(ownId: string, answers: readonly number[] = [], resume = 0, after?: () => void): boolean {
    const call = this.actionEndpoints[ownId];
    if (!call) return false;
    const blocks = this.screenBlocks();
    const parameters: Record<string, string> = { ...this.requestContext(answers), ...(resume ? { 'FRM.RESUME': String(resume) } : {}) };
    const target = this.queryActionBlocks[ownId];
    call({ blocks, parameters, ...(target ? { offset: 0, limit: FRM_QUERY_LIMIT } : {}) }).subscribe({
      next: response => {
        if (target) {
          const page = this.payload<FrmPage>(response);
          if (page.rows != null) {
            this.activeQueryActions[target] = ownId;
            this.showRows(target, page.rows);
            if (!page.rows.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, this.toastLife.warning);
          }
          if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, this.toastLife.warning);
          after?.();
          return;
        }
        const result = this.payload<FrmActionResult>(response);
        const alert = result.commands?.find(command => command[0] === 'SHOW_ALERT');
        if (alert) {
          this.askAlert(alert, choice => this.runAction(ownId, [...answers, choice], resume));
          return;
        }
        const point = result.commands?.find(command => command[0] === 'FRM_COMMIT');
        if (point) {
          if (result.globals) this.rememberGlobals(result.globals);
          for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyChanged(block, values);
          this.formsCommit({ action: ownId, actionBlocks: blocks, actionParameters: { ...parameters, 'FRM.COMMIT_POINT': point[1] ?? '', 'FRM.COMMIT_STATE': point[2] ?? '' } },
                           () => this.runAction(ownId, [], Number(point[1])));
          return;
        }
        if (result.globals) this.rememberGlobals(result.globals);
        for (const [block, values] of Object.entries(result.blocks ?? {})) this.applyOracleValues(block, values);
        const commands = result.commands ?? [];
        const step = commands.find(command => command[0] === 'FRM_RESUME');
        if (step) {
          if (result.messages?.length) this.toast.success('Üzenet', result.messages.join(' '), true, this.toastLife.success);
          this.runCommands(commands.slice(0, commands.indexOf(step)), () => this.runAction(ownId, [], Number(step[1])));
          return;
        }
        this.runCommands(commands);
        if (result.messages?.length) this.toast.success('Üzenet', result.messages.join(' '), true, this.toastLife.success);
        else if (ownId !== this.initAction) this.toast.success('Kész', 'A művelet sikeresen lefutott.', true, this.toastLife.success);
      },
      error: () => undefined,
    });
    return true;
  }

  protected formsGlobals(): Record<string, string | null> {
    try {
      const stored: unknown = JSON.parse(sessionStorage.getItem('frm.forms.globals') ?? '{}');
      return stored && typeof stored === 'object' ? stored as Record<string, string | null> : {};
    } catch {
      return {};
    }
  }

  protected rememberGlobals(values: Record<string, string | null>): void {
    try {
      sessionStorage.setItem('frm.forms.globals', JSON.stringify({ ...this.formsGlobals(), ...values }));
    } catch {
      // privát mód / tiltott tárhely: a globálisok csak ebben a kérésben élnek
    }
  }

  protected requestContext(answers: readonly number[]): Record<string, string> {
    const context: Record<string, string> = {};
    for (const [name, value] of Object.entries(this.formsGlobals())) if (value !== null) context[name] = value;
    const query = window.location.search || (window.location.hash.includes('?') ? window.location.hash.slice(window.location.hash.indexOf('?')) : '');
    new URLSearchParams(query).forEach((value, name) => { context['PARAMETER.' + name.toUpperCase()] = value; });
    const block = this.cursor, item = this.cursorItem || block;
    Object.assign(context, {
      'SYSTEM.CURSOR_BLOCK': block, 'SYSTEM.CURRENT_BLOCK': block,
      'SYSTEM.CURSOR_ITEM': item, 'SYSTEM.CURRENT_ITEM': item.split('.').pop() ?? '',
      'SYSTEM.CURSOR_RECORD': '1', 'SYSTEM.TRIGGER_RECORD': '1', 'SYSTEM.LAST_RECORD': 'TRUE', 'SYSTEM.MESSAGE_LEVEL': '0',
      'SYSTEM.FORM_STATUS': this.formsStatus(), 'SYSTEM.BLOCK_STATUS': this.formsStatus(block),
      'SYSTEM.RECORD_STATUS': this.formsStatus(block), 'SYSTEM.CURRENT_DATETIME': localIso(new Date()),
    });
    if (answers.length) context['FRM.ALERTS'] = answers.join(',');
    return context;
  }

  protected formsStatus(block?: string): string {
    const groups = Object.entries(this.formGroups).filter(([region]) => !block || this.blockOf(region) === block);
    return groups.some(([, group]) => group.dirty) ? 'CHANGED' : 'QUERY';
  }

  protected runCommands(commands: readonly (readonly (string | null)[])[], then?: () => void): void {
    let pending = 1;
    const finished = () => {
      pending -= 1;
      if (pending === 0) then?.();
    };
    for (const [op, ...args] of commands) {
      const arg = (index: number) => (args[index] ?? '').toUpperCase();
      switch (op) {
        case 'GO_BLOCK': this.cursorBlock = arg(0); this.cursorItem = ''; break;
        case 'GO_ITEM': {
          const target = arg(0).includes('.') ? arg(0) : this.cursor + '.' + arg(0);
          this.cursorBlock = target.split('.')[0]; this.cursorItem = target;
          break;
        }
        case 'EXECUTE_QUERY': pending += 1; this.formsQuery(this.cursor, finished); break;
        case 'SET_ITEM_PROPERTY': case 'SET_ITEM_INSTANCE_PROPERTY':
          if (op === 'SET_ITEM_PROPERTY') this.formsItemProperty(arg(0), arg(1), arg(2));
          else this.formsItemProperty(arg(0), arg(2), arg(3));
          break;
        case 'SHOW_WINDOW': case 'HIDE_WINDOW': this.setWindowVisible(arg(0), op === 'SHOW_WINDOW'); break;
        case 'SHOW_VIEW': this.showCanvas(arg(0)); break;
        case 'HIDE_VIEW': this.hideCanvas(arg(0)); break;
        case 'CLEAR_BLOCK': case 'CREATE_RECORD': case 'CLEAR_RECORD': this.clearBlock(this.cursor); break;
        case 'DELETE_RECORD': this.formsDelete(this.cursor); break;
        case 'CLEAR_FORM': for (const block of this.screenBlockNames()) this.clearBlock(block); break;
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
    finished();
  }

  protected screenBlockNames(): string[] {
    return [...new Set([...Object.keys(this.structures).map(region => this.blockOf(region)), ...Object.keys(this.tables)])];
  }

  protected formsQuery(block: string, done?: () => void): void {
    if (this.executeQuery(block, done)) return;
    this.toast.warning('Lekérdezés', 'Ehhez a blokkhoz nincs generált lekérdezés: ' + block, true, this.toastLife.warning);
    done?.();
  }

  protected formsItemProperty(item: string, property: string, value: string): void {
    const owner = item.includes('.') ? item : this.cursor + '.' + item;
    const state = ITEM_PROPERTIES[property];
    if (state) this.setItemState(owner, { [state]: ['PROPERTY_TRUE', 'PROPERTY_ON', 'TRUE'].includes(value) });
    else console.warn('SET_ITEM_PROPERTY nincs leképezve:', owner, property, value);
  }

  protected clearBlock(block: string): void {
    this.originals[block] = null;
    this.formValues[block] = {};
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.blockOf(region) === block) group.reset({}, { emitEvent: false });
    }
    this.clearTable(block);
  }

  protected formsCall(form: string, args: readonly string[]): void {
    const list = args.find(name => Object.hasOwn(this.paramLists, name));
    const queryParams: Record<string, string> = {};
    for (const [name, value] of Object.entries(list ? this.paramLists[list] : {})) if (value !== null) queryParams[name] = value;
    void this.router.navigate([this.formRoutes[form] ?? '/' + form.toLowerCase()], { queryParams });
  }

  protected formsKey(key: string): void {
    switch (key) {
      case 'EXECUTE_QUERY': this.formsQuery(this.cursor); break;
      case 'COMMIT_FORM': this.formsCommit(); break;
      case 'CLEAR_BLOCK': case 'CREATE_RECORD': this.clearBlock(this.cursor); break;
      case 'EXIT_FORM': window.history.back(); break;
      case 'LIST_VALUES': case 'ENTER_QUERY': break;
      default: console.warn('DO_KEY nincs bekötve:', key);
    }
  }

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

  // ---------------------------------------------------------------- mentés (COMMIT_FORM)

  protected markPristine(block: string): void {
    for (const [region, group] of Object.entries(this.formGroups)) if (this.blockOf(region) === block) group.markAsPristine();
  }

  protected formsDelete(block: string): void {
    const original = this.originals[block];
    if (original) (this.pendingDeletes[block] ??= []).push(original);
    this.clearBlock(block);
    this.markPristine(block);
  }

  protected onToolbar(action: FrmToolbarAction): void {
    if (action === 'save') return this.formsCommit();
    const block = Object.hasOwn(this.commitBlocks, this.cursor) ? this.cursor : Object.keys(this.commitBlocks)[0];
    if (action === 'new') this.clearBlock(block);
    else {
      this.formsDelete(block);
      this.toast.warning('Törlés', 'A rekord törlésre jelölve; a Mentés véglegesíti.', true, this.toastLife.warning);
    }
    this.cursorBlock = block;
    this.changeDetector.markForCheck();
  }

  protected applyChanged(block: string, values: Record<string, string | null>): void {
    const before = JSON.stringify(this.screenBlocks()[block] ?? {});
    this.applyOracleValues(block, values);
    if (JSON.stringify(this.screenBlocks()[block] ?? {}) === before) return;
    for (const [region, group] of Object.entries(this.formGroups)) if (this.blockOf(region) === block) group.markAsDirty();
  }

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
      const groups = Object.entries(this.formGroups).filter(([region]) => this.blockOf(region) === block).map(([, group]) => group);
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
        const result = this.payload<FrmCommitResult>(response);
        for (const [block, spec] of Object.entries(this.commitBlocks)) {
          const rows = result[spec.result];
          if (Array.isArray(rows) && rows.length) {
            const saved = rows[rows.length - 1] as Record<string, unknown>;
            this.originals[block] = { ...saved };
            this.showRecord(block, this.fromDto(block, saved));
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
      error: () => undefined,
    });
  }
}

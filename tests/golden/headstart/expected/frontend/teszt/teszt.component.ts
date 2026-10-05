// CREATE_ONCE: szerkeszthető képernyőváz. Migrációs részletek: MIGRATION_NOTES.md.
import { Component, OnDestroy, ChangeDetectorRef, inject } from '@angular/core';
// TODO: importáld a saját csomagodból: ToastService (config: toast_service_import_path).
// TODO: importáld a saját csomagodból: ServiceBase, WFF (java-imports.json).
import { HttpClient } from '@angular/common/http';
import { Observable, catchError } from 'rxjs';
import { FormGroup, ValidatorFn, Validators } from '@angular/forms';
// TODO: importáld a saját csomagodból: AnkFormBlockComponent és FormBlock.Structure.
import { TableModule } from '@openng/optimus-ui/table';

/** Toast élettartamok (ms); a figyelmeztetés tovább marad. */
const TOAST_LIFE = { success: 3000, warning: 8000, danger: 6000 } as const;

interface TesztPage {
  rows?: Record<string, unknown>[];
  messages?: string[];
}

function localIso(value: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())}T${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`;
}

export interface TesztFormsStep {
  op: string;
  block?: string;
  item?: string;
  window?: string;
  canvas?: string;
  text?: string;
}

export interface TesztAitRow {
  aitKulcs?: string | null;
  aitTipus?: string | null;
  aitStatus?: string | null;
  aitMegj?: string | null;
}

export interface TesztLovChoice {
  label: string;
  value: string | number | null;
  returnValues?: Record<string, unknown>;
}

@Component({
  selector: "app-teszt",
  standalone: true,
  imports: [AnkFormBlockComponent, TableModule],
  template: `
    <section class="flex flex-col gap-2">
    <ank-form-block [formStructure]="vElekAdlapStructure" (formGroupGenerated)="onFormGroupGenerated('V_ELEK_ADLAP', 'vElekAdlapRegion1', $event)" />
    </section>
    <section class="flex flex-col gap-2">
    <p-table [value]="aitRows" [columns]="aitColumns" [paginator]="true" [rows]="aitPageSize"
      size="small" [showGridlines]="true" [scrollable]="true" selectionMode="single" [selection]="aitSelection" (selectionChange)="aitSelection = $event">
      <ng-template #header><tr>
        @for (col of aitColumns; track col.field) { <th [style.width]="col.width" class="whitespace-nowrap">{{ col.header }}</th> }
      </tr></ng-template>
      <ng-template #body let-row><tr [pSelectableRow]="row">
        @for (col of aitColumns; track col.field) { <td>{{ row[col.field] }}</td> }
      </tr></ng-template>
      <ng-template #emptymessage><tr><td [attr.colspan]="aitColumns.length" class="py-4 text-center">Nincs megjeleníthető adat.</td></tr></ng-template>
    </p-table>
    </section>
    <section class="flex flex-col gap-2">
    <ank-form-block [formStructure]="cgnvW011Structure" (formGroupGenerated)="onFormGroupGenerated('CGNV$W01_1', 'cgnvW011Region3', $event)" />
    </section>
  `,
})
export class TesztComponent extends ServiceBase implements OnDestroy {
  /** Hibák, figyelmeztetések és sikeres műveletek jelzése: toast.success / warning / danger(cím, részletek, mentés az előzményekbe = true, élettartam). */
  protected readonly toast = inject(ToastService);
  protected readonly toastLife = TOAST_LIFE;

  private readonly actionSteps: Record<string, readonly TesztFormsStep[]> = {
    "CGNV$W01_1.PB_RESZLETEK": [{ op: "goBlock", block: "AIT" }, { op: "executeQuery" }],
  };

  protected vElekAdlapStructure: FormBlock.Structure[] = [
    { type: "autocomplete", ownId: "V_ELEK_ADLAP.UBI_INPTIP_KOD", formControlName: "ubiInptipKod", labelText: "Adatlap típus", col: "3", maxLenght: 10, dropdown: true, optionLabel: "label", optionValue: "value", suggestions: [], completeMethod: (event: { query: string }) => this.onLovSearch("V_ELEK_ADLAP.UBI_INPTIP_KOD", "INPTIP", event) },
    { type: "text", ownId: "V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV", formControlName: "ubiInptipKodNev", labelText: "Megnevezés", col: "9", readonly: true, maxLenght: 80 },
    { type: "label", ownId: "V_ELEK_ADLAP.L_URES_1", labelText: "", col: "12" },
    { type: "calendar", ownId: "V_ELEK_ADLAP.DATUM_TOL", formControlName: "datumTol", labelText: "Dátum", col: "5", dateFormat: "yy.mm.dd", showIcon: true, showTime: true },
    { type: "label", ownId: "V_ELEK_ADLAP.L_URES_2", labelText: "", col: "2" },
    { type: "label", ownId: "V_ELEK_ADLAP.DATUM_IG#separator", labelText: "-", col: "1" },
    { type: "calendar", ownId: "V_ELEK_ADLAP.DATUM_IG", formControlName: "datumIg", labelText: "", col: "4", dateFormat: "yy.mm.dd", showIcon: true, showTime: true },
    { type: "checkBox", ownId: "V_ELEK_ADLAP.UBI_E04", formControlName: "ubiE04", labelText: "Elektronikus", col: "12", binary: true },
  ];

  protected readonly cgnvW011Structure: FormBlock.Structure[] = [
    { type: "button", ownId: "CGNV$W01_1.PB_RESZLETEK", labelText: "Részletek", btnSeverity: "primary", onClick: () => this.onAction("CGNV$W01_1.PB_RESZLETEK"), col: "2", colBefore: "10" },
  ];

  protected readonly aitColumns: { field: keyof TesztAitRow; header: string; width: string }[] = [
    { field: "aitKulcs", header: "Kulcs", width: "20.0%" },
    { field: "aitTipus", header: "Típus", width: "20.0%" },
    { field: "aitStatus", header: "Státusz", width: "10.0%" },
    { field: "aitMegj", header: "Megjegyzés", width: "50.0%" }
  ];

  protected aitRows: TesztAitRow[] = [];
  protected aitSelection: TesztAitRow | null = null;
  protected readonly aitPageSize = 15;

  protected readonly formGroups: Record<string, FormGroup> = Object.create(null);
  private readonly formValues: Record<string, Record<string, unknown>> = Object.create(null);
  private readonly bindings = new Map<string, { unsubscribe(): void }>();

  private readonly checkboxRules = [
    { owner: "V_ELEK_ADLAP.UBI_E04", block: "V_ELEK_ADLAP", field: "ubiE04", checked: "1", unchecked: "0" }
  ];

  private readonly validationRules: Record<string, Record<string, ValidatorFn[]>> = {
    "vElekAdlapRegion1": {
      "ubiInptipKod": [Validators.maxLength(10)],
      "ubiInptipKodNev": [Validators.maxLength(80)],
      "datumTol": [c => c.value == null || c.value === '' || c.value instanceof Date && Number.isFinite(c.value.getTime()) ? null : { date: true }],
      "datumIg": [c => c.value == null || c.value === '' || c.value instanceof Date && Number.isFinite(c.value.getTime()) ? null : { date: true }],
      "ubiE04": [c => c.value == null || c.value === '' || typeof c.value === 'boolean' ? null : { checkbox: true }]
    }
  };

  // Mezőfeliratok a toast-üzenetekhez, régiónként.
  private readonly fieldLabels: Record<string, Record<string, string>> = {
    vElekAdlapRegion1: {
      ubiInptipKod: "Adatlap típus",
      ubiInptipKodNev: "Megnevezés",
      datumTol: "Dátum",
      datumIg: "Dátum – ig",
      ubiE04: "Elektronikus"
    },
    cgnvW011Region3: {

    }
  };

  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly lovTickets: Record<string, number> = Object.create(null);
  private readonly lovChoices: Record<string, TesztLovChoice[]> = Object.create(null);

  private readonly lovRules = [
    { owner: "V_ELEK_ADLAP.UBI_INPTIP_KOD", block: "V_ELEK_ADLAP", field: "ubiInptipKod", returns: ["V_ELEK_ADLAP.UBI_INPTIP_KOD", "V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV"] }
  ];

  private readonly lovTargets: Record<string, { block: string; field: string }> = {
    "V_ELEK_ADLAP.UBI_INPTIP_KOD": {
      block: "V_ELEK_ADLAP",
      field: "ubiInptipKod"
    },
    "V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV": {
      block: "V_ELEK_ADLAP",
      field: "ubiInptipKodNev"
    }
  };

  private readonly regionBlocks: Record<string, string> = {
    vElekAdlapRegion1: "V_ELEK_ADLAP",
    cgnvW011Region3: "CGNV$W01_1"
  };

  private readonly http = inject(HttpClient);

  // Forms EXECUTE_QUERY: blokk -> a keresés/lista kritériumai a képernyő mezőiből.
  private readonly queries: Record<string, { limit: number; criteria?: readonly { field: string; block: string; key: string; context?: string }[] }> = {
    AIT: {
      limit: 200,
      criteria: [
        {
          field: "vElekAdlapUbiInptipKod",
          block: "V_ELEK_ADLAP",
          key: "ubiInptipKod"
        }
      ]
    }
  };

  // Backend DTO-mező -> képernyő-vezérlő, blokkonként.
  private readonly rowKeys: Record<string, Record<string, string>> = {
    AIT: {
      aitKulcs: "aitKulcs",
      aitTipus: "aitTipus",
      aitStatus: "aitStatus",
      aitMegj: "aitMegj"
    }
  };

  private readonly lovEndpoints: Record<string, { binds: readonly { source: string; block: string; key: string }[]; columns: readonly { column: string; returnItem: string }[] }> = {
    INPTIP: {
      binds: [],
      columns: [
        {
          column: "KOD",
          returnItem: "V_ELEK_ADLAP.UBI_INPTIP_KOD"
        },
        {
          column: "NEV",
          returnItem: "V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV"
        }
      ]
    }
  };

  private readonly checkboxValues: Record<string, Record<string, readonly [string, string]>> = {
    V_ELEK_ADLAP: {
      ubiE04: [
        "1",
        "0"
      ]
    }
  };

  constructor() {
    super();
  }

  protected onFormGroupGenerated(block: string, region: string, group: FormGroup): void {
    if (this.formGroups[region] === group) return;
    this.bindings.get(region)?.unsubscribe();
    const previous = this.formGroups[region];
    const values = this.formValues[block] ??= {};
    if (previous) Object.assign(values, previous.getRawValue());
    group.patchValue(values, { emitEvent: false });
    if (previous?.dirty) group.markAsDirty();
    if (previous?.touched) group.markAsTouched();
    this.formGroups[region] = group;
    for (const [field, rules] of Object.entries(this.validationRules[region] ?? {})) {
      const control = group.get(field);
      control?.addValidators(rules);
      control?.updateValueAndValidity({ emitEvent: false });
    }
    const update = () => {
      Object.assign(values, group.getRawValue());
      this.applyLovReturns(block, group);
    };
    update();
    this.bindings.set(region, group.valueChanges.subscribe(update));
  }

  ngOnDestroy(): void {
    for (const binding of this.bindings.values()) binding.unsubscribe();
  }

  /** Adatművelet előtt a Forms is validál (FRM-40202): hiányzó/hibás mezőnél toast, és nincs kérés. */
  private validBefore(ownId: string): boolean {
    const steps = this.actionSteps[ownId] ?? null;
    const data = steps ? steps.some(step => ['executeQuery', 'commit', 'createRecord', 'deleteRecord'].includes(step.op)) : false;
    if (!data) return true;
    const missing: string[] = [];
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (!group.invalid) continue;
      group.markAllAsTouched();
      for (const [key, control] of Object.entries(group.controls)) if (control.invalid) missing.push(this.fieldLabels[region]?.[key] ?? key);
    }
    if (!missing.length) return true;
    this.toast.warning('Hiányzó vagy hibás adat', 'Ellenőrizd: ' + missing.join(', '), true, TOAST_LIFE.warning);
    return false;
  }

  protected onAction(ownId: string): void {
    // Az üzleti működést ide kösd.
    if (!this.validBefore(ownId)) return;
    const values: Record<string, Record<string, unknown>> = Object.fromEntries(Object.entries(this.formValues).map(([block, values]) => [block, { ...values }]));
    for (const rule of this.checkboxRules) {
      const value = values[rule.block]?.[rule.field];
      if (value === true || value === false) values[rule.block][rule.field] = value ? rule.checked : rule.unchecked;
    }
    if (this.runSteps(this.actionSteps[ownId] ?? null)) return;
    this.toast.warning('Nincs bekötve', 'A gomb kódja kézi átültetést igényel: ' + ownId, true, TOAST_LIFE.warning);
  }

  protected onLovSearch(ownId: string, lov: string, event: { query: string }): void {
    const requestId = this.lovTickets[ownId] = (this.lovTickets[ownId] ?? 0) + 1;
    if (this.searchLov(ownId, lov, event.query, requestId)) return;
    this.setLovSuggestions(ownId, [], requestId); // nincs hozzá generált LOV-végpont
  }

  public setLovSuggestions(ownId: string, choices: TesztLovChoice[], requestId: number): void {
    if (requestId !== this.lovTickets[ownId]) return;
    this.lovChoices[ownId] = choices;
    this.vElekAdlapStructure = this.vElekAdlapStructure.map(field => field.ownId === ownId ? { ...field, suggestions: choices } : field);
    this.changeDetector.markForCheck();
  }

  private applyLovReturns(block: string, group: FormGroup): void {
    for (const rule of this.lovRules.filter(r => r.block === block && group.contains(r.field))) {
      const value: unknown = group.get(rule.field)?.value;
      const selected = this.lovChoices[rule.owner]?.find(c => c.value === value);
      if (!selected?.returnValues) continue;
      for (const owner of rule.returns) {
        if (!Object.hasOwn(selected.returnValues, owner)) continue;
        const target = this.lovTargets[owner];
        if (!target) continue;
        (this.formValues[target.block] ??= {})[target.field] = selected.returnValues[owner];
        for (const [region, targetGroup] of Object.entries(this.formGroups)) {
          if (this.regionBlocks[region] === target.block) targetGroup.get(target.field)?.setValue(selected.returnValues[owner], { emitEvent: false });
        }
      }
    }
  }

  /** TesztConstants.AIT_UPDATE_PATH (PUT) */
  aitUpdate(body: unknown) {
    return this.http.put(this.url('ait/update'), body)
      .pipe(
        catchError((error) => {
          WFF.err('Hiba', error);
          throw error;
        })
      );
  }

  /** TesztConstants.AIT_SEARCH_PATH (POST) */
  aitSearch(body: unknown) {
    return this.http.post(this.url('ait/query/search'), body)
      .pipe(
        catchError((error) => {
          WFF.err('Hiba', error);
          throw error;
        })
      );
  }

  /** TesztConstants.LOV_INPTIP_PATH (POST) */
  lovInptip(body: unknown) {
    return this.http.post(this.url('lov/inptip'), body)
      .pipe(
        catchError((error) => {
          WFF.err('Hiba', error);
          throw error;
        })
      );
  }

  /** TesztConstants.COMMIT_FORM_PATH (POST) */
  commitForm(body: unknown) {
    return this.http.post(this.url('commit'), body)
      .pipe(
        catchError((error) => {
          WFF.err('Hiba', error);
          throw error;
        })
      );
  }

  /** A válasz hasznos tartalma; ha boríték érkezik, annak adatmezője. */
  private payload<T>(response: unknown): T {
    if (response && typeof response === 'object') {
      for (const field of ['data', 'result', 'payload', 'body', 'content']) {
        const value = (response as Record<string, unknown>)[field];
        if (value && typeof value === 'object') return value as T;
      }
    }
    return response as T;
  }

  private wireText(block: string, key: string, value: unknown): string | null {
    const pair = this.checkboxValues[block]?.[key];
    if (pair && typeof value === 'boolean') return value ? pair[0] : pair[1];
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return localIso(value);
    return String(value);
  }

  /** Forms EXECUTE_QUERY a blokk generált keresés/lista végpontján. false: nincs hozzá végpont.
   *  done: a sorok megjelenítése után (képernyőpont: utána folytatódik a gomb kódja). */
  public executeQuery(block: string, done?: () => void): boolean {

    const query = this.queries[block];
    if (!query) return false;
    const criteria = Object.fromEntries((query.criteria ?? []).map(c => [c.field, this.wireText(c.block, c.key, this.value(c.block, c.key))]));
    let request: Observable<unknown>;
    switch (block) {
      case "AIT": request = this.aitSearch({ criteria, offset: 0, limit: query.limit }); break;
      default: return false;
    }
    request.subscribe({
      next: response => {
        const page = this.payload<TesztPage>(response);
        this.showRows(block, page.rows ?? []);
        if (!page.rows?.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, TOAST_LIFE.warning);
        if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, TOAST_LIFE.warning);
        done?.();
      },
      error: () => undefined, // WFF.err már jelezte
    });
    return true;
  }

  private showRows(block: string, rows: readonly Record<string, unknown>[]): void {
    this.changeDetector.markForCheck();
    const keys = this.rowKeys[block] ?? {};
    const mapped = rows.map(row => Object.fromEntries(Object.entries(row).filter(([field]) => field in keys).map(([field, value]) => [keys[field], value])));
    switch (block) {
      case "AIT": this.aitRows = mapped as unknown as TesztAitRow[]; this.aitSelection = null; return;
      default: this.showRecord(block, mapped[0] ?? {});
    }
  }

  /** Felismert gomblépések: go_block + execute_query. true: a komponens lefuttatta. */
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
  }

  private value(block: string, key: string): unknown {
    return this.formValues[block]?.[key];
  }

  private showRecord(block: string, record: Record<string, unknown>): void {
    this.changeDetector.markForCheck();
    Object.assign(this.formValues[block] ??= {}, record);
    for (const [region, group] of Object.entries(this.formGroups)) {
      if (this.regionBlocks[region] === block) group.patchValue(record, { emitEvent: false });
    }
  }

  private searchLov(ownId: string, lov: string, query: string, requestId: number): boolean {
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
      case "INPTIP": request = this.lovInptip(body); break;
      default: return false;
    }
    request.subscribe({
      next: response => {
        const rows = this.payload<{ rows?: Record<string, unknown>[] }>(response).rows ?? [];
        this.setLovSuggestions(ownId, rows.map(row => this.lovChoice(ownId, endpoint.columns, row)), requestId);
      },
      error: () => this.setLovSuggestions(ownId, [], requestId), // WFF.err már jelezte
    });
    return true;
  }

  private lovChoice(ownId: string, columns: readonly { column: string; returnItem: string }[], row: Record<string, unknown>): TesztLovChoice {
    const own = columns.find(c => c.returnItem === ownId)?.column ?? columns[0]?.column ?? Object.keys(row)[0] ?? '';
    const raw = row[own];
    const value = typeof raw === 'number' ? raw : raw === null || raw === undefined ? null : String(raw);
    const shown = (columns.length ? columns.map(c => row[c.column]) : [raw]).filter(v => v !== null && v !== undefined && v !== '');
    const returnValues: Record<string, unknown> = {};
    for (const c of columns) if (c.returnItem) returnValues[c.returnItem] = row[c.column];
    return { label: shown.map(v => String(v)).join(' – '), value, returnValues };
  }
}

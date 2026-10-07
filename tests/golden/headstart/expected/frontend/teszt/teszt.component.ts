// CREATE_ONCE: szerkeszthető képernyő. Migrációs részletek: MIGRATION_NOTES.md.
import { Component, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient } from '@angular/common/http';
import { FormGroup } from '@angular/forms';
import { EMPTY, catchError, tap } from 'rxjs';
// TODO: importáld a saját csomagodból: ToastService (config: toast_service_import_path).
// TODO: importáld a saját csomagodból: ServiceBase, WFF (java-imports.json).
import { WfTable } from '../wf-table';
// TODO: importáld a saját csomagodból: FormBlocksComponent és FormBlock.Structure.

interface Page {
  rows?: Record<string, unknown>[] | null;
  messages?: string[];
}

@Component({
  selector: 'app-teszt',
  standalone: true,
  imports: [FormBlocksComponent, WfTable],
  template: `
    <ank-form-block [formStructure]="structures['vElekAdlap']" (formGroupGenerated)="onFormGroupGenerated('vElekAdlap', $event)" />
    <wf-table [value]="aitRows" [columns]="aitColumns" [rows]="15" [(selection)]="aitSelection" />
    <ank-form-block [formStructure]="structures['cgnvW011']" (formGroupGenerated)="onFormGroupGenerated('cgnvW011', $event)" />
  `,
})
export class TesztComponent extends ServiceBase {
  protected readonly toast = inject(ToastService);
  protected readonly toastLife = { success: 3000, warning: 8000, danger: 6000 };
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  // A FormBlock-régiók FormGroupjai (onFormGroupGenerated).
  protected readonly forms: Record<string, FormGroup> = {};

  protected readonly structures: Record<string, FormBlock.Structure[]> = {
    vElekAdlap: [
      { type: 'autocomplete', ownId: 'V_ELEK_ADLAP.UBI_INPTIP_KOD', formControlName: 'ubiInptipKod', labelText: 'Adatlap típus', col: '3', maxLenght: 10, dropdown: true, optionLabel: 'label', optionValue: 'value', suggestions: [], completeMethod: (event: { query: string }) => this.searchInptip('V_ELEK_ADLAP.UBI_INPTIP_KOD', event.query) },
      { type: 'text', ownId: 'V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV', formControlName: 'ubiInptipKodNev', labelText: 'Megnevezés', col: '9', readonly: true, maxLenght: 80 },
      { type: 'label', ownId: 'V_ELEK_ADLAP.L_URES_1', labelText: '', col: '12' },
      { type: 'calendar', ownId: 'V_ELEK_ADLAP.DATUM_TOL', formControlName: 'datumTol', labelText: 'Dátum', col: '5', dateFormat: 'yy.mm.dd', showIcon: true, showTime: true },
      { type: 'label', ownId: 'V_ELEK_ADLAP.L_URES_2', labelText: '', col: '2' },
      { type: 'label', ownId: 'V_ELEK_ADLAP.DATUM_IG#separator', labelText: '-', col: '1' },
      { type: 'calendar', ownId: 'V_ELEK_ADLAP.DATUM_IG', formControlName: 'datumIg', labelText: '', col: '4', dateFormat: 'yy.mm.dd', showIcon: true, showTime: true },
      { type: 'checkBox', ownId: 'V_ELEK_ADLAP.UBI_E04', formControlName: 'ubiE04', labelText: 'Elektronikus', col: '12', binary: true },
    ],
    cgnvW011: [
      { type: 'button', ownId: 'CGNV$W01_1.PB_RESZLETEK', labelText: 'Részletek', col: '2', colBefore: '10', btnSeverity: 'primary', onClick: () => this.onPbReszletekClick() },
    ],
  };

  // AIT: a táblázat oszlopai, sorai (a backend DTO-mezőivel) és a kiválasztott sor.
  protected readonly aitColumns = [
    { field: 'aitKulcs', header: 'Kulcs', width: '20.0%' },
    { field: 'aitTipus', header: 'Típus', width: '20.0%' },
    { field: 'aitStatus', header: 'Státusz', width: '10.0%' },
    { field: 'aitMegj', header: 'Megjegyzés', width: '50.0%' },
  ];
  protected aitRows: Record<string, unknown>[] = [];
  protected aitSelection: Record<string, unknown> | null = null;

  private inptipRows: Record<string, unknown>[] = [];

  constructor() {
    super();
  }

  aitUpdate(body: unknown) {
    return this.http.put<unknown>(this.url('ait/update'), body).pipe(
      tap(res => WFF.debug(this.modName + '.aitUpdate', res)),
      catchError(error => {
        WFF.err('Hiba', error);
        return EMPTY;
      }),
    );
  }

  aitSearch(body: unknown) {
    return this.http.post<Page>(this.url('ait/query/search'), body).pipe(
      tap(res => WFF.debug(this.modName + '.aitSearch', res)),
      catchError(error => {
        WFF.err('Hiba', error);
        return EMPTY;
      }),
    );
  }

  lovInptip(body: unknown) {
    return this.http.post<Page>(this.url('lov/inptip'), body).pipe(
      tap(res => WFF.debug(this.modName + '.lovInptip', res)),
      catchError(error => {
        WFF.err('Hiba', error);
        return EMPTY;
      }),
    );
  }

  commitForm(body: unknown) {
    return this.http.post<unknown>(this.url('commit'), body).pipe(
      tap(res => WFF.debug(this.modName + '.commitForm', res)),
      catchError(error => {
        WFF.err('Hiba', error);
        return EMPTY;
      }),
    );
  }

  // A FormBlock elkészítette a régió FormGroupját.
  protected onFormGroupGenerated(region: string, group: FormGroup): void {
    this.forms[region] = group;
    if (region === 'vElekAdlap') {
      group.get('ubiInptipKod')?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(value => this.chooseInptip(value));
    }
  }

  // CGNV$W01_1.PB_RESZLETEK
  protected onPbReszletekClick(): void {
    this.queryAit();
  }

  // AIT lekérdezése (Forms EXECUTE_QUERY); a feltételek a képernyőről.
  protected queryAit(): void {
    this.aitSearch({ criteria: { vElekAdlapUbiInptipKod: this.text(this.value('vElekAdlap', 'ubiInptipKod')) }, offset: 0, limit: 200 }).subscribe(page => this.showAit(page));
  }

  // INPTIP LOV: a mező keresője (FormBlock autocomplete).
  protected searchInptip(ownId: string, term: string): void {
    this.lovInptip({ term: term || null, parameters: {}, limit: 50 }).subscribe(page => {
      this.inptipRows = page.rows ?? [];
      this.suggest(ownId, this.inptipRows.map(row => ({ label: [row['KOD'], row['NEV']].filter(v => v !== null && v !== undefined && v !== '').map(String).join(' – '), value: row['KOD'] })));
    });
  }

  // INPTIP: a kiválasztott sor többi oszlopa a hozzá tartozó mezőkbe.
  private chooseInptip(value: unknown): void {
    const row = this.inptipRows.find(r => r['KOD'] === value);
    if (!row) return;
    this.forms['vElekAdlap']?.patchValue({ ubiInptipKodNev: row['NEV'] }, { emitEvent: false });
  }

  private showAit(page: Page): void {
    this.aitRows = page.rows ?? [];
    this.aitSelection = null;
    if (!this.aitRows.length) this.toast.warning('Nincs találat', 'A lekérdezés nem adott vissza rekordot.', true, this.toastLife.warning);
    if (page.messages?.length) this.toast.warning('Üzenet', page.messages.join(' '), true, this.toastLife.warning);
  }

  // A LOV találatai a mező legördülőjébe (FormBlock suggestions).
  private suggest(ownId: string, suggestions: { label: string; value: unknown }[]): void {
    for (const fields of Object.values(this.structures)) {
      const field = fields.find(f => f['ownId'] === ownId);
      if (field) field['suggestions'] = suggestions;
    }
  }

  // A mező értéke a képernyőn (a régió FormGroupjából).
  private value(region: string, key: string): unknown {
    return this.forms[region]?.get(key)?.value;
  }

  // Érték a backendnek (Oracle-szöveg): üres -> null, dátum -> helyi idő ISO-formában.
  private text(value: unknown): string | null {
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) {
      const p = (n: number) => String(n).padStart(2, '0');
      return `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())}T${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`;
    }
    return String(value);
  }
}

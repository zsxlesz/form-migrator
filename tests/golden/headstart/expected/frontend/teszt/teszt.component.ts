// CREATE_ONCE: szerkeszthető képernyőváz. Migrációs részletek: MIGRATION_NOTES.md.
import { Component, inject } from '@angular/core';
// TODO: importáld a saját csomagodból: ToastService (config: toast_service_import_path).
import { HttpClient } from '@angular/common/http';
import { FrmFormsScreen, FrmTableComponent, FrmLov, FrmQuery, FrmValidators, frmTable } from '../frm-forms-screen';
// TODO: importáld a saját csomagodból: FormBlocksComponent és FormBlock.Structure.

@Component({
  selector: 'app-teszt',
  standalone: true,
  imports: [FormBlocksComponent, FrmTableComponent],
  template: `
    <ank-form-block [formStructure]="structures['vElekAdlap']" (formGroupGenerated)="onFormGroupGenerated('vElekAdlap', $event)" />
    <frm-table [table]="tables.AIT" />
    <ank-form-block [formStructure]="structures['cgnvW011']" (formGroupGenerated)="onFormGroupGenerated('cgnvW011', $event)" />
  `,
})
export class TesztComponent extends FrmFormsScreen {
  protected readonly toast = inject(ToastService);
  protected readonly toastLife = { success: 3000, warning: 8000, danger: 6000 };

  private readonly http = inject(HttpClient);

  protected override readonly structures: Record<string, FormBlock.Structure[]> = {
    vElekAdlap: [
      { type: 'autocomplete', ownId: 'V_ELEK_ADLAP.UBI_INPTIP_KOD', formControlName: 'ubiInptipKod', labelText: 'Adatlap típus', col: '3', maxLenght: 10, ...this.lov('V_ELEK_ADLAP.UBI_INPTIP_KOD', 'INPTIP') },
      { type: 'text', ownId: 'V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV', formControlName: 'ubiInptipKodNev', labelText: 'Megnevezés', col: '9', readonly: true, maxLenght: 80 },
      { type: 'label', ownId: 'V_ELEK_ADLAP.L_URES_1', labelText: '', col: '12' },
      { type: 'calendar', ownId: 'V_ELEK_ADLAP.DATUM_TOL', formControlName: 'datumTol', labelText: 'Dátum', col: '5', dateFormat: 'yy.mm.dd', showIcon: true, showTime: true },
      { type: 'label', ownId: 'V_ELEK_ADLAP.L_URES_2', labelText: '', col: '2' },
      { type: 'label', ownId: 'V_ELEK_ADLAP.DATUM_IG#separator', labelText: '-', col: '1' },
      { type: 'calendar', ownId: 'V_ELEK_ADLAP.DATUM_IG', formControlName: 'datumIg', labelText: '', col: '4', dateFormat: 'yy.mm.dd', showIcon: true, showTime: true },
      { type: 'checkBox', ownId: 'V_ELEK_ADLAP.UBI_E04', formControlName: 'ubiE04', labelText: 'Elektronikus', col: '12', binary: true },
    ],
    cgnvW011: [
      { type: 'button', ownId: 'CGNV$W01_1.PB_RESZLETEK', labelText: 'Részletek', col: '2', colBefore: '10', ...this.button('CGNV$W01_1.PB_RESZLETEK') },
    ],
  };

  protected override readonly tables = {
    AIT: frmTable(15, [['aitKulcs', 'Kulcs', '20.0%'], ['aitTipus', 'Típus', '20.0%'], ['aitStatus', 'Státusz', '10.0%'], ['aitMegj', 'Megjegyzés', '50.0%']]),
  };

  protected override readonly validators = {
    'V_ELEK_ADLAP.DATUM_TOL': [FrmValidators.date],
    'V_ELEK_ADLAP.DATUM_IG': [FrmValidators.date],
  };

  protected override readonly checkboxValues = {
    V_ELEK_ADLAP: { ubiE04: ['1', '0'] },
  };

  protected override readonly queries: Record<string, FrmQuery> = {
    AIT: { call: request => this.aitSearch(request), criteria: { vElekAdlapUbiInptipKod: 'V_ELEK_ADLAP.ubiInptipKod' } },
  };

  protected override readonly lovs: Record<string, FrmLov> = {
    INPTIP: { call: request => this.lovInptip(request), columns: { KOD: 'V_ELEK_ADLAP.UBI_INPTIP_KOD', NEV: 'V_ELEK_ADLAP.UBI_INPTIP_KOD_NEV' } },
  };

  protected override readonly rowKeys = {
    AIT: ['aitKulcs', 'aitTipus', 'aitStatus', 'aitMegj'],
  };

  protected override readonly actionSteps = {
    'CGNV$W01_1.PB_RESZLETEK': [{ op: 'goBlock', block: 'AIT' }, { op: 'executeQuery' }],
  };

  constructor() {
    super();
  }

  aitUpdate(body: unknown) { return this.send('aitUpdate', this.http.put(this.url('ait/update'), body)); }
  aitSearch(body: unknown) { return this.send('aitSearch', this.http.post(this.url('ait/query/search'), body)); }
  lovInptip(body: unknown) { return this.send('lovInptip', this.http.post(this.url('lov/inptip'), body)); }
  commitForm(body: unknown) { return this.send('commitForm', this.http.post(this.url('commit'), body)); }
}

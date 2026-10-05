"""Screen conventions: L_URES_* spacers, full-width rows, field length JSON, primary buttons, ToastService."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from frm_forms.cli import main
from frm_forms import framework

HEADSTART = Path(__file__).with_name('golden') / 'headstart' / 'input.xml'


class ScreenConventionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_screen(self, *extra, config=None, lengths=None, label='out'):
        args = ['migrate', str(HEADSTART), '--screen', '--module', 'teszt', '--out', str(self.root / label), *extra]
        if config is not None:
            (self.root / (label + '-config.json')).write_text(json.dumps(config), encoding='utf-8')
            args += ['--config', str(self.root / (label + '-config.json'))]
        if lengths is not None:
            (self.root / (label + '-lengths.json')).write_text(json.dumps(lengths), encoding='utf-8')
            args += ['--field-lengths', str(self.root / (label + '-lengths.json'))]
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(args)
        out = self.root / label
        source = (out / 'frontend/teszt/teszt.component.ts').read_text(encoding='utf-8') if code == 0 else ''
        return code, err.getvalue(), out, source

    def test_rows_are_filled_and_gaps_only_come_from_spacers(self):
        code, err, out, source = self.run_screen()
        self.assertEqual(code, 0, err)
        plan = json.loads((out / 'analysis/screen-plan.json').read_text(encoding='utf-8'))
        self.assertFalse(plan['layout_settings']['preserve_gaps'])
        for section in plan['sections']:
            if section['mode'] != 'form' or all(i['widget'] == 'button' for i in section['items']):
                continue  # button rows keep their right alignment
            for item in section['items']:
                self.assertEqual((item['col_before'], item['col_after']), (0, 0), item['owner'])
        self.assertIn("{ type: 'label', ownId: 'V_ELEK_ADLAP.L_URES_2', labelText: '', col: '2' }", source)
        self.assertNotIn("labelText: 'L_URES", source)

    def test_custom_catalog_without_spacer_items_keeps_the_convention(self):
        catalog = self.root / 'catalog.json'
        catalog.write_text(json.dumps({'version': 1, 'call_prefixes': ['qms$']}), encoding='utf-8')
        self.assertEqual(framework.load({'framework_catalog': str(catalog)})['spacer_items'], framework.DEFAULT_SPACERS)
        catalog.write_text(json.dumps({'version': 1, 'spacer_items': []}), encoding='utf-8')
        self.assertEqual(framework.load({'framework_catalog': str(catalog)})['spacer_items'], ())

    def test_field_lengths_json_sets_min_and_max(self):
        lengths = {'version': 1, 'fields': {'ubiInptipKod': {'min': 2, 'max': 6}, 'V_ELEK_ADLAP.ubiInptipKodNev': {'max': 40},
                                            'nincsIlyen': {'max': 3}}}
        code, err, out, source = self.run_screen(lengths=lengths)
        self.assertEqual(code, 0, err)
        definition = next(line for line in source.splitlines() if "formControlName: 'ubiInptipKod'" in line)
        self.assertIn('maxLenght: 6, minLenght: 2', definition)  # the runtime turns these into minLength/maxLength validators
        self.assertNotRegex(source, r'\bValidators\.')
        runtime = (out / 'frontend/frm-forms-screen.ts').read_text(encoding='utf-8')
        self.assertIn('if (field.minLenght) result.push(Validators.minLength(field.minLenght));', runtime)
        plan = json.loads((out / 'analysis/screen-plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['field_lengths']['unknown'], ['nincsIlyen'])
        codes = {n['code'] for n in plan['notices']}
        self.assertTrue({'FIELD_LENGTH_UNKNOWN', 'FIELD_LENGTH_IGNORED'} <= codes)  # a display field has no input length
        notes = (out / 'frontend/teszt/MIGRATION_NOTES.md').read_text(encoding='utf-8')
        self.assertIn('## Mezőhosszak (segítő JSON)', notes)
        template = json.loads((out / 'analysis/field-lengths.template.json').read_text(encoding='utf-8'))
        self.assertEqual(template['fields'], {'ubiInptipKod': {'min': 2, 'max': 6}})
        code, err, _, _ = self.run_screen(lengths={'fields': {'x': {'min': 5, 'max': 2}}}, label='bad')
        self.assertEqual(code, 1)
        self.assertIn('FIELD_LENGTHS', err)

    def test_buttons_are_primary(self):
        code, err, out, source = self.run_screen()
        self.assertEqual(code, 0, err)
        self.assertIn("...this.button('CGNV$W01_1.PB_RESZLETEK') }", source)
        self.assertNotIn('secondary', source)
        runtime = (out / 'frontend/frm-forms-screen.ts').read_text(encoding='utf-8')
        self.assertIn("return { btnSeverity: 'primary' as const, onClick: () => this.onAction(ownId) };", runtime)
        self.assertNotIn("'secondary'", runtime)

    def test_toast_service_in_every_component_with_configured_import(self):
        code, err, out, source = self.run_screen()
        self.assertEqual(code, 0, err)
        self.assertIn('// TODO: importáld a saját csomagodból: ToastService', source)
        self.assertIn('protected readonly toast = inject(ToastService);', source)
        self.assertIn('protected readonly toastLife = { success: 3000, warning: 8000, danger: 6000 };', source)
        # Missing data, backend errors and empty results are signalled by the shared runtime, with the screen's toast.
        runtime = (out / 'frontend/frm-forms-screen.ts').read_text(encoding='utf-8')
        self.assertIn('if (!this.validBefore(ownId)) return;', runtime)
        for call in ["this.toast.warning('Hiányzó vagy hibás adat'", "WFF.err('Hiba', error);", "this.toast.warning('Nincs találat'"]:
            self.assertIn(call, runtime)
        self.assertIn('protected abstract readonly toast: FrmToast;', runtime)
        config = {'emit_imports': True, 'optimus_import_path': '@company/optimus', 'optimus_form_block_symbol': 'AnkFormBlockComponent',
                  'form_block_type_import_path': '@company/optimus/form-block', 'toast_service_import_path': '@company/ui/toast',
                  'toast_life_ms': {'success': 2500, 'warning': 10000, 'danger': 7000}}
        code, err, _, source = self.run_screen(config=config, label='emit')
        self.assertEqual(code, 0, err)
        self.assertIn("import { ToastService } from '@company/ui/toast';", source)
        self.assertIn('protected readonly toastLife = { success: 2500, warning: 10000, danger: 7000 };', source)
        code, err, _, _ = self.run_screen(config={'toast_life_ms': {'success': 10}}, label='bad-life')
        self.assertEqual(code, 1)
        self.assertIn('toast_life_ms', err)

    def test_frontend_only_component_still_gets_the_toast(self):
        code, err, out, source = self.run_screen('--frontend-only', label='front')
        self.assertEqual(code, 0, err)
        self.assertIn('protected readonly toast = inject(ToastService);', source)
        self.assertNotIn('HttpClient', source)
        self.assertNotIn('validBefore', source)  # the shared runtime checks the form before a data step


if __name__ == '__main__':
    unittest.main()

"""4.14: the Forms runtime of the generated screens is shared (frontend/frm-forms-screen.ts).

Every screen extends FrmFormsScreen: runAction, formsCommit, runCommands, the alerts and the :GLOBAL / :SYSTEM
context exist once per project; the component keeps its layout, its data (protected override readonly ...) and its
hooks. With tsc available (FRM_TSC or on PATH), the generated screen and the runtime are type-checked with the
tsconfig of a new Angular CLI project against stubs (tests/ts_stubs); with the Angular compiler (FRM_NGC=<path to
ngc>) the templates too (strictTemplates).
"""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from java_support import COMPANY_IMPORTS
from frm_forms import screen_emulation
from frm_forms.cli import main
from frm_forms.screen_api import QUERY_LIMIT
from screen_support import ANGULAR_CLI_OPTIONS, RUNTIME, component, ngc_check, runtime, with_company_imports

ROOT = Path(__file__).resolve().parents[1]
REPLICA = ROOT / 'tests' / 'fixtures' / 'felmeres_replika_fmb.xml'
SIMPLE = '''<Module><FormModule Name="EGYSZERU" Title="Egyszerű"><Coordinate CoordinateSystem="Real" RealUnit="Pixel"/>
 <Block Name="B" DatabaseDataBlock="false"><Item Name="NEV" ItemType="Text Item" DataType="Char" Prompt="Név" CanvasName="C"
  XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="AKTIV" ItemType="Check Box" Prompt="Aktív" CheckedValue="I" UncheckedValue="N" CanvasName="C"
   XPosition="120" YPosition="10" Width="80" Height="20">
   <Trigger Name="WHEN-CHECKBOX-CHANGED" TriggerText="IF :B.AKTIV = &apos;I&apos; THEN set_item_property(&apos;B.NEV&apos;, ENABLED, PROPERTY_TRUE);
ELSE set_item_property(&apos;B.NEV&apos;, ENABLED, PROPERTY_FALSE); END IF;"/></Item></Block>
 <Canvas Name="C" CanvasType="Content" WindowName="W"/><Window Name="W" Title="Egyszerű"/></FormModule></Module>'''

# A list screen without buttons: backend calls, but no runtime (the component has its own modName).
LISTAS = '''<Module><FormModule Name="LISTAS" Title="Listás"><Coordinate CoordinateSystem="Real" RealUnit="Pixel"/>
 <Block Name="PARTNER" DatabaseDataBlock="true" QueryDataSourceName="PARTNER" RecordsDisplayCount="5">
  <Item Name="KOD" ItemType="Text Item" DataType="Char" Prompt="Kód" CanvasName="C" ColumnName="KOD" PrimaryKey="true"
   XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="NEV" ItemType="Text Item" DataType="Char" Prompt="Név" CanvasName="C" ColumnName="NEV"
   XPosition="120" YPosition="10" Width="100" Height="20"/></Block>
 <Canvas Name="C" CanvasType="Content" WindowName="W"/><Window Name="W" Title="Listás"/></FormModule></Module>'''


def generate(root: Path, source: Path, module: str) -> Path:
    config = root / (module + '.json')
    config.write_text(json.dumps({'java_company_imports': COMPANY_IMPORTS, 'backend_live': True,
                                  'screen_window_selection': 'all', 'screen_primary_window_auto': True}))
    out = root / module
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(['migrate', str(source), '--out', str(out), '--screen', '--module', module, '--config', str(config)]) == 0
    return out


class ScreenRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('FRM_JAVA_IMPORT_MAP', '-')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.out = generate(cls.root, REPLICA, 'rendeles')
        simple = cls.root / 'egyszeru_fmb.xml'
        simple.write_text(SIMPLE, encoding='utf-8')
        cls.simple = generate(cls.root, simple, 'egyszeru')
        listas = cls.root / 'listas_fmb.xml'
        listas.write_text(LISTAS, encoding='utf-8')
        cls.listas = generate(cls.root, listas, 'listas')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_screen_extends_the_shared_runtime_and_keeps_only_its_own_parts(self):
        screen = component(self.out)
        self.assertIn("import { FrmFormsScreen, FrmTableComponent, FrmToolbarComponent, FrmAlertComponent, FrmActionCall, FrmLov, "
                      "FrmQuery, FrmValidators, frmTable } from '../frm-forms-screen';", screen)
        self.assertIn('export class RendelesComponent extends FrmFormsScreen {', screen)
        self.assertIn('protected readonly toast = inject(ToastService);', screen)  # the company convention stays
        self.assertIn('protected readonly toastLife = { success: 3000, warning: 8000, danger: 6000 };', screen)
        self.assertIn('protected override readonly commitEndpoint = (request: Record<string, unknown>) => this.commitForm(request);', screen)
        # the generic screen logic lives in frm-forms-screen.ts: the screen has its data, endpoints and template
        for moved in ('runAction(', 'formsCommit(', 'runCommands(', 'requestContext(', 'askAlert(', 'formsGlobals(', 'onFormGroupGenerated(',
                      'validBefore(', 'onAction(', 'onLovSearch(', 'setItemState(', 'executeQuery(', 'showRows(', 'selectedRecords(',
                      'clearTable(', 'numberValidator('):
            self.assertNotRegex(screen, r'\n  (?:private |protected |public )?(?:override )?' + re.escape(moved), moved)
        for gone in ('cursorBlock', 'stateTargets', 'fieldLabels', 'regionBlocks', 'bindings', 'ngOnDestroy', '/**', 'TOAST_LIFE',
                     'screenBlockNames', 'oracleNames'):
            self.assertNotIn(gone, screen)
        self.assertIn("<frm-table [table]=\"tables.TETEL\" />", screen)
        # structures is a Record: noPropertyAccessFromIndexSignature (Angular CLI default) wants the brackets
        self.assertIn('<ank-form-block [formStructure]="structures[\'ctrl\']" (formGroupGenerated)="onFormGroupGenerated(\'ctrl\', $event)" />', screen)
        self.assertNotIn('"structures.', screen)
        self.assertIn('<frm-toolbar (action)="onToolbar($event)" />', screen)
        self.assertIn('<frm-alert [alert]="formsAlert" (answer)="answerAlert($event)" />', screen)
        self.assertIn("{ type: 'button', ownId: 'CTRL.PB_KERES', labelText: 'Keresés', col: '2', ...this.button('CTRL.PB_KERES') },", screen)
        self.assertIn("...this.lov('RENDELES.STATUSZ', 'LOV_STATUSZ') },", screen)
        self.assertRegex(screen, r"TETEL: \{ call: request => this\.\w+\(request\), criteria: \{ rendelesId: 'RENDELES\.id' \} \},")
        self.assertLess(len(screen.splitlines()), 140)
        self.assertEqual(runtime(self.out), screen_emulation.runtime_source())

    def test_runtime_constants_follow_the_generator(self):
        source = screen_emulation.runtime_source()
        self.assertIn(f'export const FRM_QUERY_LIMIT = {QUERY_LIMIT};', source)
        from frm_forms.screen_emulation import ITEM_PROPERTIES, STEP_COMMANDS
        for step, command in STEP_COMMANDS.items():
            self.assertIn(f"{step}: '{command}'", source)
        for prop, state in ITEM_PROPERTIES.items():
            self.assertIn(f"{prop}: '{state}'", source)
        self.assertRegex(source, r"export const FRM_FORMS_SCREEN_VERSION = '\d+';")
        self.assertNotIn('/**', source)  # no doc comments in the shared runtime either

    def test_every_screen_extends_the_runtime(self):
        for out in (self.simple, self.listas):
            self.assertTrue((out / 'frontend' / RUNTIME).is_file())
            self.assertIn('extends FrmFormsScreen {', component(out))
        simple = component(self.simple)
        self.assertNotIn('HttpClient', simple)  # nothing to call
        self.assertIn("B: { aktiv: ['I', 'N'] },", simple)  # checked strictly by tsc below
        self.assertIn("'B.AKTIV': () => this.setItemState('B.NEV', { enabled: this.cmp(this.stateValue('B.AKTIV'), '=', 'I') }),", simple)

    def test_every_successful_request_is_logged_first_with_the_module_and_method_name(self):
        source = component(self.out)
        self.assertIn("rendelesList(offset = 0, limit = 200) { return this.send('rendelesList', this.http.get(this.url(", source)
        self.assertEqual(source.count('this.http.'), source.count('return this.send('))
        for method in re.findall(r"\n  (\w+)\([^)]*\) \{ return this\.send\('(\w+)'", source):
            self.assertEqual(method[0], method[1])  # the name logged is the method's own
        runtime = (self.out / 'frontend' / RUNTIME).read_text(encoding='utf-8')
        self.assertIn("tap(res => WFF.debug(this.modName + '.' + name, res)),\n      catchError(", runtime)
        self.assertIn("get modName(): string {\n    return WFF.trim(this.router.url, '/');\n  }", runtime)
        self.assertIn('ServiceBase, WFF (java-imports.json)', runtime)
        self.assertNotIn('inject(Router)', runtime)  # the router comes from ServiceBase
        self.assertNotIn("from '@angular/router'", runtime)
        listas = component(self.listas)
        self.assertIn("partnerList(offset = 0, limit = 200) { return this.send('partnerList',", listas)
        for text in (source, listas, component(self.simple)):
            self.assertNotIn('inject(Router)', text)
            self.assertNotIn('AnkFormBlockComponent', text)
            self.assertNotIn('get modName', text)
        self.assertIn('imports: [FormBlocksComponent', source)

    def test_the_constructor_is_always_between_the_fields_and_the_methods(self):
        for out in (self.out, self.simple, self.listas):
            screen = component(out)
            constructor = screen.index('  constructor() {\n    super();\n')
            fields = [m.start() for m in re.finditer(r'\n  (?:protected|private) (?:override )?readonly ', screen)]
            methods = [m.start() for m in re.finditer(r'\n  (?:private )?\w+\([^)]*\)(?:: void)? \{', screen) if m.start() != constructor - 1]
            self.assertLess(max(fields), constructor, out.name)
            self.assertTrue(all(constructor < m for m in methods), out.name)
        self.assertIn('  constructor() {\n    super();\n  }\n}\n', component(self.simple))  # nothing to start: still there

    def test_typescript_strict(self):
        tsc = os.environ.get('FRM_TSC') or shutil.which('tsc')
        if not tsc:
            self.skipTest('tsc required (FRM_TSC=<path to tsc>)')
        for out in (self.out, self.simple, self.listas):
            with self.subTest(out=out.name):
                work = self.root / ('ts-' + out.name)
                shutil.copytree(out / 'frontend', work / 'frontend')
                shutil.copy(ROOT / 'tests/ts_stubs/company.ts', work / 'company.ts')
                files = with_company_imports(work / 'frontend')
                (work / 'tsconfig.json').write_text(json.dumps({'compilerOptions': {
                    **ANGULAR_CLI_OPTIONS, 'noUnusedLocals': True, 'useDefineForClassFields': True, 'noEmit': True},
                    'files': [str(ROOT / 'tests/ts_stubs/host.d.ts')] + files}))
                run = subprocess.run([tsc, '-p', str(work / 'tsconfig.json')], capture_output=True, text=True, timeout=180)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_angular_compiler_strict_templates(self):
        ngc = os.environ.get('FRM_NGC')
        if not ngc:
            self.skipTest('Angular compiler required (FRM_NGC=<path to node_modules/.bin/ngc> of an install with '
                          '@angular/compiler-cli, core, common, forms, router and rxjs)')
        for out in (self.out, self.simple, self.listas):
            with self.subTest(out=out.name):
                code, output = ngc_check(out, ngc)
                self.assertEqual(code, 0, output)

if __name__ == '__main__':
    unittest.main()

"""4.26: the generated screen carries its own code; frm-forms-screen.ts is gone, the table is wf-table.ts.

The component extends the company ServiceBase. What the screen uses (its endpoints, queries, LOVs, buttons, save,
windows, item states) are plain methods of the component, generated only where needed; a change to one screen
touches one file. The shared wf-table.ts wraps the p-table: every p-table input, output and template (#header,
#body, #caption ...) can be given to it. With tsc (FRM_TSC or on PATH) the screens are type-checked with the tsconfig
of a new Angular CLI project against stubs (tests/ts_stubs); with the Angular compiler (FRM_NGC=<path to ngc>) the
templates too (strictTemplates), a developer's own wf-table templates included.
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
from frm_forms.angular_screen import wf_table_source
from frm_forms.cli import main
from screen_support import ANGULAR_CLI_OPTIONS, SCREEN_GLOBALS, component, ngc_check, screen_field, screen_method, with_company_imports

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

# A list screen without buttons: backend calls only.
LISTAS = '''<Module><FormModule Name="LISTAS" Title="Listás"><Coordinate CoordinateSystem="Real" RealUnit="Pixel"/>
 <Block Name="PARTNER" DatabaseDataBlock="true" QueryDataSourceName="PARTNER" RecordsDisplayCount="5">
  <Item Name="KOD" ItemType="Text Item" DataType="Char" Prompt="Kód" CanvasName="C" ColumnName="KOD" PrimaryKey="true"
   XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="NEV" ItemType="Text Item" DataType="Char" Prompt="Név" CanvasName="C" ColumnName="NEV"
   XPosition="120" YPosition="10" Width="100" Height="20"/></Block>
 <Canvas Name="C" CanvasType="Content" WindowName="W"/><Window Name="W" Title="Listás"/></FormModule></Module>'''


# A dialog window with tab pages, a hidden stacked canvas, a frame, and buttons whose steps open and close them.
DIALOGS = '''<Module><FormModule Name="ABLAKOS" Title="Ablakos" FirstNavigationBlock="B"><Coordinate CoordinateSystem="Real" RealUnit="Pixel"/>
 <Window Name="MAIN" Title="Ablakos"/><Window Name="EDIT" Title="Szerkesztés" WindowStyle="Dialog" Modal="true"/>
 <Canvas Name="PAGE" CanvasType="Content" WindowName="MAIN">
  <Graphics Name="KERET" GraphicsType="Frame" FrameTitle="Adatok" XPosition="0" YPosition="0" Width="400" Height="60"/></Canvas>
 <Canvas Name="EXTRA" CanvasType="Stacked" WindowName="MAIN" Visible="false"/>
 <Canvas Name="EDIT_C" CanvasType="Content" WindowName="EDIT"/>
 <Canvas Name="TABS" CanvasType="Tab" WindowName="EDIT"><TabPage Name="P1" Label="Első"/><TabPage Name="P2" Label="Második"/></Canvas>
 <Block Name="B" DatabaseDataBlock="false">
  <Item Name="NEV" ItemType="Text Item" Prompt="Név" CanvasName="PAGE" XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="PB_NYIT" ItemType="Push Button" Label="Nyit" CanvasName="PAGE" XPosition="120" YPosition="10" Width="80" Height="20">
   <Trigger Name="WHEN-BUTTON-PRESSED" TriggerText="show_window('EDIT'); show_view('EXTRA');"/></Item>
  <Item Name="E" ItemType="Text Item" Prompt="Extra" CanvasName="EXTRA" XPosition="10" YPosition="100" Width="100" Height="20"/>
  <Item Name="D" ItemType="Text Item" Prompt="Dialógus" CanvasName="EDIT_C" XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="T1" ItemType="Text Item" Prompt="Első mező" CanvasName="TABS" TabPageName="P1" XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="T2" ItemType="Text Item" Prompt="Második mező" CanvasName="TABS" TabPageName="P2" XPosition="10" YPosition="10" Width="100" Height="20"/>
  <Item Name="PB_BEZAR" ItemType="Push Button" Label="Bezár" CanvasName="EDIT_C" XPosition="120" YPosition="10" Width="80" Height="20">
   <Trigger Name="WHEN-BUTTON-PRESSED" TriggerText="hide_window('EDIT');"/></Item>
 </Block>
</FormModule></Module>'''

# A developer's own table: extra filters in the caption, an own row, the p-table inputs it wants.
OWN_TABLE = '''import { Component } from '@angular/core';
import { WfTable } from '../wf-table';

@Component({
  selector: 'app-sajat-tabla',
  standalone: true,
  imports: [WfTable],
  template: `
    <wf-table [value]="rows" [columns]="columns" [rows]="25" [globalFilterFields]="['nev']" [sortField]="'nev'" [lazy]="true"
      [rowsPerPageOptions]="[10, 25, 50]" (onLazyLoad)="load($event)" (onSort)="sorted = true" [(selection)]="selected">
      <ng-template #caption><input type="text" placeholder="Keresés" /></ng-template>
      <ng-template #header let-columns><tr>@for (col of columns; track col.field) { <th>{{ col.header }}</th> }</tr></ng-template>
      <ng-template #body let-row let-columns="columns" let-rowIndex="rowIndex">
        <tr><td>{{ rowIndex }}</td>@for (col of columns; track col.field) { <td>{{ row[col.field] }}</td> }</tr>
      </ng-template>
      <ng-template #emptymessage><tr><td>Üres</td></tr></ng-template>
    </wf-table>
  `,
})
export class SajatTablaComponent {
  protected readonly columns = [{ field: 'nev', header: 'Név' }];
  protected rows: Record<string, unknown>[] = [];
  protected selected: Record<string, unknown> | null = null;
  protected sorted = false;
  protected load(event: unknown): void { void event; }
}
'''


def generate(root: Path, source: Path, module: str, *extra: str) -> Path:
    config = root / (module + '.json')
    config.write_text(json.dumps({'java_company_imports': COMPANY_IMPORTS, 'backend_live': True,
                                  'screen_window_selection': 'all', 'screen_primary_window_auto': True}))
    out = root / module
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(['migrate', str(source), '--out', str(out), '--screen', '--module', module, '--config', str(config), *extra]) == 0
    return out


class ScreenComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('FRM_JAVA_IMPORT_MAP', '-')
        os.environ.setdefault('FRM_JAVA_VARIABLE_MAP', '-')  # nor a developer's own java-variables.json
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.out = generate(cls.root, REPLICA, 'rendeles')
        outputs = {}
        for module, xml in (('egyszeru', SIMPLE), ('listas', LISTAS), ('ablakos', DIALOGS)):
            source = cls.root / (module + '_fmb.xml')
            source.write_text(xml, encoding='utf-8')
            outputs[module] = generate(cls.root, source, module, *(['--frontend-only'] if module == 'ablakos' else []))
        cls.simple, cls.listas, cls.dialogs = outputs['egyszeru'], outputs['listas'], outputs['ablakos']
        cls.outputs = (cls.out, cls.simple, cls.listas, cls.dialogs)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_no_shared_runtime_and_the_table_is_wf_table(self):
        for out in self.outputs:
            self.assertFalse((out / 'frontend/frm-forms-screen.ts').exists())
            self.assertIn(' extends ServiceBase {', component(out))
            self.assertNotIn('override', component(out))
        screen = component(self.out)
        self.assertEqual((self.out / 'frontend/wf-table.ts').read_text(encoding='utf-8'), wf_table_source())
        self.assertIn("import { WfTable } from '../wf-table';", screen)
        self.assertIn('<wf-table [value]="tetelRows" [columns]="tetelColumns" [rows]="5" [(selection)]="tetelSelection" />', screen)
        self.assertIn("    { field: 'cikk', header: 'Cikk', width: '45.45%' },", screen)  # the backend DTO field names
        self.assertNotRegex(screen, r'<frm-|Frm[A-Z]')
        self.assertFalse((self.simple / 'frontend/wf-table.ts').exists())  # no table: no wf-table.ts
        self.assertIn('// TODO: importáld a saját csomagodból: ServiceBase, WFF (java-imports.json).', screen)

    def test_wf_table_passes_the_p_table_api_and_the_templates(self):
        source = wf_table_source()
        self.assertIn("selector: 'wf-table',", source)
        self.assertIn("export const WF_TABLE_VERSION = '1';", source)
        for binding in ('[value]="value()"', '[globalFilterFields]="globalFilterFields()"', '[lazy]="lazy()"', '[sortField]="sortField()"',
                        '[virtualScroll]="virtualScroll()"', '(onLazyLoad)="onLazyLoad.emit($event)"', '(selectionChange)="selection.set($event)"'):
            self.assertIn(binding, source)
        for name in ('caption', 'header', 'body', 'emptymessage', 'footer', 'summary', 'rowexpansion'):
            self.assertIn(f"readonly {name}Template = contentChild<TemplateRef<any>>('{name}');", source)
        # without a template of its own, the default: the columns, the row buttons, the empty text
        self.assertIn('@for (col of columns; track col.field) { <td>{{ row[col.field] }}</td> }', source)
        self.assertIn("readonly emptyMessage = input<string>('Nincs megjeleníthető adat.');", source)
        self.assertIn('readonly paginator = input<boolean>(true);', source)
        self.assertIn("readonly selectionMode = input<'single' | 'multiple' | null | undefined>('single');", source)

    def test_every_successful_request_is_logged_first_with_the_module_and_method_name(self):
        for out in (self.out, self.listas):
            source = component(out)
            methods = re.findall(r"\n  (\w+)\([^)]*\) \{\n    return this\.http\.(?:get|post|put|delete)<[^>]+>\(this\.url\('[^']*'\)", source)
            logged = re.findall(r"tap\(res => WFF\.debug\(this\.modName \+ '\.(\w+)', res\)\),", source)
            self.assertTrue(methods)
            self.assertEqual(methods, logged)  # the name logged is the method's own
            self.assertEqual(source.count('this.http.'), len(methods))
            self.assertEqual(source.count("WFF.err('Hiba', error);"), len(methods))
            self.assertNotIn('inject(Router)', source)  # the router comes from ServiceBase
            self.assertNotIn('get modName', source)

    def test_the_constructor_is_always_between_the_fields_and_the_methods(self):
        for out in self.outputs:
            screen = component(out)
            constructor = screen.index('  constructor() {\n    super();\n')
            fields = [m.start() for m in re.finditer(r'\n  (?:protected|private) (?:readonly )?\w+(?:: [^=\n]+)? = ', screen)]
            methods = [m.start() for m in re.finditer(r'\n  (?:private |protected )?\w+\([^)]*\)(?:: \w+)? \{', screen) if m.start() != constructor - 1]
            self.assertLess(max(fields), constructor, out.name)
            self.assertTrue(all(constructor < m for m in methods), out.name)
        self.assertIn('  constructor() {\n    super();\n  }\n', component(self.simple))  # nothing to start: still there

    def test_only_what_the_screen_uses(self):
        simple = component(self.simple)
        self.assertNotIn('HttpClient', simple)  # nothing to call
        for absent in ('blocks()', 'parameters()', 'save()', 'interface Page', 'WfTable'):
            self.assertNotIn(absent, simple)
        self.assertIn("    'B.AKTIV': ['b', 'aktiv', 'I', 'N'],", simple)  # the checkbox's Forms values for the item state
        self.assertIn("subscribe(() => this.setItemState('B.NEV', { enabled: this.cmp(this.stateValue('B.AKTIV'), '=', 'I') }));", simple)
        listas = component(self.listas)
        self.assertIn('  protected queryPartner(): void {', listas)
        self.assertNotIn('save()', listas)  # no form block to save
        replica = component(self.out)
        for method in ('protected save(): void {', 'protected newRecord(): void {', 'protected deleteRecord(): void {',
                       'private blocks(): Record<string, Record<string, string | null>> {', 'private showResult(result: ActionResult, done: string): void {'):
            self.assertIn(method, replica)
        self.assertLess(len(replica.splitlines()), 650)

    def test_no_wrapper_around_the_form_blocks(self):
        for out in self.outputs:
            template = component(out).split('template: `', 1)[1].split('`,', 1)[0]
            self.assertNotRegex(template, r'<(?:div|section) class="flex flex-col gap-\d">', out.name)
        dialogs = component(self.dialogs)
        self.assertIn('<p-fieldset [legend]="labels.text1">\n    <ank-form-block', dialogs)
        self.assertIn("<p-tabpanel [value]=\"'P1'\">\n    <ank-form-block", dialogs)

    def test_windows_canvases_and_their_steps_are_plain_fields(self):
        dialogs = component(self.dialogs)
        self.assertIn("<p-dialog [header]=\"labels.text4\" [(visible)]=\"windowVisible['EDIT']\"", dialogs)
        self.assertIn("@if (canvasVisible['EXTRA']) {", dialogs)
        self.assertIn('  protected readonly windowVisible: Record<string, boolean> = {', dialogs)
        self.assertIn("  protected onPbNyitClick(): void {\n    this.windowVisible['EDIT'] = true;\n    this.canvasVisible['EXTRA'] = true;", dialogs)
        self.assertIn("  protected onPbBezarClick(): void {\n    this.windowVisible['EDIT'] = false;\n  }", dialogs)
        self.assertNotIn('signal', dialogs)

    def test_save_sends_the_changed_record_in_node(self):
        if not shutil.which('node'):
            self.skipTest('Node with TypeScript stripping required')
        members = [screen_field(self.out, 'items'), screen_field(self.out, 'originals'), screen_field(self.out, 'deleted')]
        members += [screen_method(self.out, name) for name in ('save', 'deleteRecord', 'fillRendeles', 'blocks', 'parameters', 'showResult',
                                                              'showBlocks', 'value', 'text')]
        self.assertNotIn(None, members)
        script = self.root / 'save-flow.ts'
        script.write_text('''import assert from 'node:assert/strict';
__SCREEN_GLOBALS__
const window = {location: {search: '', hash: ''}};
class Group {
  values: Record<string, unknown> = {}; dirty = false; invalid = false;
  get(key: string) { const group = this; return {get value() { return group.values[key] ?? null; }, setValue(v: unknown) { group.values[key] = v; }}; }
  reset(values: Record<string, unknown> = {}) { this.values = {...values}; this.dirty = false; }
  markAsPristine() { this.dirty = false; } markAllAsTouched() {}
}
class Screen {
  forms = {ctrl: new Group(), rendeles: new Group()};
  tetelSelection = null; partnerSelection = null;
  toastLife = {warning: 1, success: 1};
  warnings = []; successes = [];
  toast = {warning: (...args) => this.warnings.push(args), success: (...args) => this.successes.push(args)};
  commits = [];
  commitForm(request) {
    this.commits.push(structuredClone(request));
    return {subscribe: next => next({messages: [], rowsRendeles: [{id: 7, vevo: 'V2', statusz: 'L'}]})};
  }
__MEMBERS__
}
const screen = new Screen();
screen.save();
assert.equal(screen.commits.length, 0);  // nothing changed
screen.fillRendeles({id: 7, vevo: 'V1', statusz: 'N'});
screen.forms.rendeles.values.vevo = 'V2';
screen.forms.rendeles.dirty = true;
screen.save();
const request = screen.commits[0];
assert.deepEqual(request.changesRendeles.updated, [{original: {id: 7, vevo: 'V1', statusz: 'N'},
  value: {id: '7', vevo: 'V2', vevoNev: null, datum: null, statusz: 'N', osszeg: null}}]);
assert.deepEqual(request.changesRendeles.inserted, []);
assert.equal(request.blocks.RENDELES.VEVO, 'V2');
assert.equal(screen.forms.rendeles.values.statusz, 'L');  // the saved record comes back
assert.equal(screen.successes.length, 1);
screen.deleteRecord();
screen.save();
assert.deepEqual(screen.commits[1].changesRendeles, {inserted: [], updated: [], deleted: [{id: 7, vevo: 'V2', statusz: 'L'}]});
console.log('typescript save OK');
'''.replace('__MEMBERS__', '\n'.join(members)).replace('__SCREEN_GLOBALS__', SCREEN_GLOBALS))
        run = subprocess.run(['node', '--experimental-strip-types', '--no-warnings', str(script)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('typescript save OK', run.stdout)

    def test_typescript_strict(self):
        tsc = os.environ.get('FRM_TSC') or shutil.which('tsc')
        if not tsc:
            self.skipTest('tsc required (FRM_TSC=<path to tsc>)')
        for out in self.outputs:
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
        own = self.root / 'own-table'
        shutil.copytree(self.out / 'frontend', own / 'frontend')
        (own / 'frontend/sajat').mkdir()
        (own / 'frontend/sajat/sajat.component.ts').write_text(OWN_TABLE, encoding='utf-8')
        for out in (*self.outputs, own):
            with self.subTest(out=out.name):
                code, output = ngc_check(out, ngc)
                self.assertEqual(code, 0, output)


if __name__ == '__main__':
    unittest.main()

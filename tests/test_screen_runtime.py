"""4.14: the Forms runtime of the generated screens is shared (frontend/frm-forms-screen.ts).

A screen with buttons or a save chain extends FrmFormsScreen: runAction, formsCommit, runCommands,
the alerts and the :GLOBAL / :SYSTEM context exist once per project; the component keeps its layout,
its data (protected override readonly ...) and its hooks. With tsc available (FRM_TSC or on PATH),
the generated screen and the runtime are type-checked strictly against stubs (tests/ts_stubs).
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
from frm_forms.ts_imports import code
from screen_support import RUNTIME, component, runtime

ROOT = Path(__file__).resolve().parents[1]
REPLICA = ROOT / 'tests' / 'fixtures' / 'felmeres_replika_fmb.xml'
SIMPLE = '''<Module><FormModule Name="EGYSZERU" Title="Egyszerű"><Coordinate CoordinateSystem="Real" RealUnit="Pixel"/>
 <Block Name="B" DatabaseDataBlock="false"><Item Name="NEV" ItemType="Text Item" DataType="Char" Prompt="Név" CanvasName="C"
  XPosition="10" YPosition="10" Width="100" Height="20"/></Block>
 <Canvas Name="C" CanvasType="Content" WindowName="W"/><Window Name="W" Title="Egyszerű"/></FormModule></Module>'''


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

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_screen_extends_the_shared_runtime_and_keeps_only_its_own_parts(self):
        screen = component(self.out)
        self.assertIn("import { FrmFormsScreen, FrmPage } from '../frm-forms-screen';", screen)
        self.assertIn('export class RendelesComponent extends FrmFormsScreen implements OnDestroy {', screen)
        self.assertIn('protected readonly toast = inject(ToastService);', screen)  # the company convention stays
        self.assertIn('protected readonly toastLife = TOAST_LIFE;', screen)
        self.assertIn('protected override readonly commitEndpoint = (request: Record<string, unknown>) => this.commitForm(request);', screen)
        self.assertIn('protected override selectedRecords()', screen)
        for moved in ('runAction(', 'formsCommit(', 'runCommands(', 'requestContext(', 'askAlert(', 'formsGlobals('):
            self.assertNotRegex(screen, r'\n  (?:private |protected )' + re.escape(moved), moved)
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

    def test_screen_without_buttons_needs_no_runtime(self):
        self.assertFalse((self.simple / 'frontend' / RUNTIME).exists())
        self.assertIn('extends ServiceBase', component(self.simple))

    def test_typescript_strict(self):
        tsc = os.environ.get('FRM_TSC') or shutil.which('tsc')
        if not tsc:
            self.skipTest('tsc required (FRM_TSC=<path to tsc>)')
        for out in (self.out, self.simple):
            with self.subTest(out=out.name):
                work = self.root / ('ts-' + out.name)
                shutil.copytree(out / 'frontend', work / 'frontend')
                shutil.copy(ROOT / 'tests/ts_stubs/company.ts', work / 'company.ts')
                files = []
                for path in (work / 'frontend').rglob('*.ts'):
                    depth = len(path.relative_to(work / 'frontend').parts)
                    text = path.read_text(encoding='utf-8')
                    names = [n for n in ('ServiceBase', 'WFF', 'ToastService', 'AnkFormBlockComponent', 'FormBlock')
                             if re.search(r'\b' + n + r'\b', code(text))]  # used in code, not only in a TODO comment
                    if names:
                        text = 'import { ' + ', '.join(names) + " } from '" + '../' * depth + "company';\n" + text
                    path.write_text(text, encoding='utf-8')
                    files.append(str(path))
                (work / 'tsconfig.json').write_text(json.dumps({'compilerOptions': {
                    'strict': True, 'noImplicitOverride': True, 'noUnusedLocals': True, 'target': 'ES2022', 'module': 'ES2022',
                    'moduleResolution': 'bundler', 'experimentalDecorators': True, 'useDefineForClassFields': True, 'noEmit': True,
                    'skipLibCheck': True, 'lib': ['ES2022', 'DOM']}, 'files': [str(ROOT / 'tests/ts_stubs/host.d.ts')] + files}))
                run = subprocess.run([tsc, '-p', str(work / 'tsconfig.json')], capture_output=True, text=True, timeout=180)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()

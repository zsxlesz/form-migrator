"""The generated screen as tests read it: the component and the shared runtime it extends (4.14).

A screen with Forms emulation extends FrmFormsScreen (frontend/frm-forms-screen.ts): runAction,
formsCommit, runCommands ... live there once per project, the component keeps its data and hooks.
"""
from pathlib import Path
import re

from frm_forms.service_inline import mask

RUNTIME = 'frm-forms-screen.ts'


def component(out: Path) -> str:
    return next((Path(out) / 'frontend').rglob('*.component.ts')).read_text(encoding='utf-8')


def runtime(out: Path) -> str:
    path = Path(out) / 'frontend' / RUNTIME
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def screen_source(out: Path) -> str:
    """The component and the runtime, in this order."""
    return component(out) + '\n' + runtime(out)


def ts_method(source: str, name: str) -> str | None:
    """The TypeScript method or getter `name` of the source (any visibility, override included), or None."""
    visible = mask(source)
    match = re.search(r'^  (?:private |public |protected )?(?:override )?(?:get )?' + re.escape(name) + r'(?:<[^>]+>)?\([^\n]*\)[^\n]*\{',
                      visible, re.M)
    if not match:
        return None
    start, end, depth = match.start(), match.end(), 1
    while depth:
        depth += {'{': 1, '}': -1}.get(visible[end], 0)
        end += 1
    return source[start:end]


def screen_method(out: Path, name: str) -> str | None:
    """The method the screen runs: the component's own (an override) first, else the runtime's.

    For a Node harness class, which extends nothing: without the override modifier."""
    method = ts_method(component(out), name) or ts_method(runtime(out), name)
    return re.sub(r'^(  (?:private |public |protected )?)override ', r'\1', method) if method else None


# What a Node harness needs from frm-forms-screen.ts besides the methods it extracts.
RUNTIME_GLOBALS = '''const FRM_QUERY_LIMIT = 200;
const STEP_COMMANDS: Record<string, string> = {goBlock: 'GO_BLOCK', executeQuery: 'EXECUTE_QUERY', commit: 'COMMIT_FORM'};
interface FrmPage { rows?: Record<string, unknown>[] | null; messages?: string[]; }
interface FrmActionResult { blocks?: Record<string, Record<string, string | null>>; messages?: string[]; commands?: (string | null)[][]; globals?: Record<string, string | null>; }
interface FrmCommitResult extends FrmActionResult { [rows: string]: unknown; }
'''


# The company names the generated files use from the host project (TODO imports in the generated code).
COMPANY_NAMES = ('ServiceBase', 'WFF', 'ToastService', 'FormBlocksComponent', 'FormBlock')
STUBS = Path(__file__).with_name('ts_stubs')
# The tsconfig of a new Angular CLI project (ng new): the flags a developer's project compiles the screens with.
ANGULAR_CLI_OPTIONS = {'strict': True, 'noImplicitOverride': True, 'noPropertyAccessFromIndexSignature': True,
                       'noImplicitReturns': True, 'noFallthroughCasesInSwitch': True, 'skipLibCheck': True,
                       'isolatedModules': True, 'experimentalDecorators': True, 'target': 'ES2022', 'module': 'ES2022',
                       'moduleResolution': 'bundler', 'lib': ['ES2022', 'DOM']}


def with_company_imports(frontend: Path, company: str = 'company') -> list[str]:
    """Import the company stand-ins (a sibling of frontend/) into every generated .ts file that uses them."""
    from frm_forms.ts_imports import code
    files = []
    for path in sorted(frontend.rglob('*.ts')):
        depth = len(path.relative_to(frontend).parts)
        text = path.read_text(encoding='utf-8')
        names = [n for n in COMPANY_NAMES if re.search(r'\b' + n + r'\b', code(text))]  # in code, not only in a TODO
        if names:
            text = 'import { ' + ', '.join(names) + " } from '" + '../' * depth + company + "';\n" + text
        path.write_text(text, encoding='utf-8')
        files.append(str(path))
    return files


def ngc_check(out: Path, ngc: str) -> tuple[int, str]:
    """Compile the generated frontend with the Angular compiler (strictTemplates, the Angular CLI tsconfig flags).

    The company classes and the Optimus modules are stand-ins (tests/ts_stubs/angular); elements and properties
    the stand-ins do not declare are allowed (NO_ERRORS_SCHEMA), every template expression is type-checked."""
    import json
    import shutil
    import subprocess
    import tempfile
    home = Path(ngc).resolve().parents[2]  # <install>/node_modules/.bin/ngc: @angular/* resolve from <install>
    work = Path(tempfile.mkdtemp(prefix='frm-ngc-', dir=home))
    try:
        shutil.copytree(Path(out) / 'frontend', work / 'frontend')
        shutil.copy(STUBS / 'angular' / 'company.ts', work / 'company.ts')
        shutil.copytree(STUBS / 'angular' / 'optimus', work / 'optimus')
        files = with_company_imports(work / 'frontend')
        for name in files:
            path = Path(name)
            text = path.read_text(encoding='utf-8')
            if '@Component({' in text:
                text = "import { NO_ERRORS_SCHEMA } from '@angular/core';\n" + text.replace(
                    '@Component({', '@Component({\n  schemas: [NO_ERRORS_SCHEMA],')
                path.write_text(text, encoding='utf-8')
        (work / 'tsconfig.json').write_text(json.dumps({
            'compilerOptions': {**ANGULAR_CLI_OPTIONS, 'outDir': str(work / 'dist'), 'baseUrl': str(work),
                                'paths': {'@openng/optimus-ui/*': ['optimus/*']}},
            'angularCompilerOptions': {'strictTemplates': True, 'strictInjectionParameters': True,
                                       'strictInputAccessModifiers': True},
            'files': files}))
        run = subprocess.run([ngc, '-p', str(work / 'tsconfig.json')], capture_output=True, text=True, timeout=300)
        return run.returncode, (run.stdout + run.stderr).replace(str(work) + '/', '')
    finally:
        shutil.rmtree(work, ignore_errors=True)

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

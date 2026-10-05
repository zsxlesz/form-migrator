"""The screen side of the Forms runtime emulation (forms_emulation): what the generated component does
with the commands of an action or init endpoint.

The backend runs the original PL/SQL and returns the Forms built-ins it called as commands
(GO_BLOCK, SET_ITEM_PROPERTY, EXECUTE_QUERY, CALL_FORM, SHOW_ALERT ...). The component keeps the
:GLOBAL values in the browser tab, sends its context (:SYSTEM, :PARAMETER) with every request,
and executes the commands in order after writing back the item values.
"""
from __future__ import annotations


# Forms SET_ITEM_PROPERTY property -> screen item state.
ITEM_PROPERTIES = {'ENABLED': 'enabled', 'VISIBLE': 'visible', 'DISPLAYED': 'visible', 'REQUIRED': 'required',
                   'UPDATE_ALLOWED': 'editable', 'INSERT_ALLOWED': 'editable', 'UPDATEABLE': 'editable', 'INSERTABLE': 'editable'}


# Recognised button steps -> the Forms built-in the runtime executes (runSteps in frm-forms-screen.ts).
STEP_COMMANDS = {'goBlock': 'GO_BLOCK', 'goItem': 'GO_ITEM', 'executeQuery': 'EXECUTE_QUERY', 'commit': 'COMMIT_FORM',
                 'createRecord': 'CREATE_RECORD', 'clearBlock': 'CLEAR_BLOCK', 'clearForm': 'CLEAR_FORM',
                 'clearRecord': 'CLEAR_RECORD', 'showWindow': 'SHOW_WINDOW', 'hideWindow': 'HIDE_WINDOW',
                 'showCanvas': 'SHOW_VIEW', 'hideCanvas': 'HIDE_VIEW', 'exitForm': 'EXIT_FORM', 'enterQuery': 'ENTER_QUERY',
                 'listValues': 'LIST_VALUES'}

RUNTIME_FILE = 'frm-forms-screen.ts'
RUNTIME_IMPORT = '../frm-forms-screen'


def runtime_source() -> str:
    """frontend/frm-forms-screen.ts: the Forms runtime every generated screen extends (one copy per project)."""
    from pathlib import Path
    return (Path(__file__).with_name('templates') / 'frm-forms-screen.ts.tpl').read_text(encoding='utf-8')


def runtime_fields(w: dict) -> list[str]:
    """The screen's data for the emulation in FrmFormsScreen: the save chain, the alerts, the form routes."""
    from .ts_code import record, sq
    result = []
    if w.get('commit'):
        blocks = {block: {'request': spec['request'], 'result': spec['result'], 'operations': spec['operations']}
                  for block, spec in w['commit']['blocks'].items()}
        result.append('  protected override readonly commitBlocks = ' + record(blocks) + ';\n'
                      '  protected override readonly commitEndpoint = (request: Record<string, unknown>) => this.' + w['commit']['call'] + '(request);')
    if w.get('alerts_used') and w.get('alerts'):
        result.append('  protected override readonly alertDefinitions = ' + record(w['alerts']) + ';')
    if w.get('form_routes'):
        result.append('  protected override readonly formRoutes = ' + record(w['form_routes']) + ';')
    if w.get('init') and w['init'] != '@INIT':
        result.append('  protected override readonly initAction = ' + sq(w['init']) + ';')
    return result

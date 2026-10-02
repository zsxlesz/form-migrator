"""4.14: DO_KEY runs the form's own KEY trigger; COMMIT_FORM followed by more code is a commit point.

The button stops at the commit point (its work rolled back), the screen saves - the commit endpoint
runs the code up to the point again in the commit's transaction and checks the state - and the
button resumes after the point (NIVA.RESUME).
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

from java_support import COMPANY_IMPORTS, write_stubs
from niva_forms.cli import main
from niva_forms.commit_points import transform
from niva_forms.plsql import Unsupported
from niva_forms.plsql_passthrough import prepare
from screen_support import RUNTIME_GLOBALS, screen_method, screen_source

ROOT = Path(__file__).resolve().parents[1]
REPLICA = ROOT / 'tests' / 'fixtures' / 'felmeres_replika_fmb.xml'
ITEMS = {'B': {'ID': {'type': 'number'}, 'NAME': {'type': 'text'}}, 'CTRL': {'X': {'type': 'text'}}}
KEY_COMMIT = {'id': 'F:KEY-COMMIT', 'event': 'KEY-COMMIT', 'block': None, 'item': None, 'hierarchy': 'OVERRIDE',
              'source': "BEGIN IF :B.ID IS NOT NULL THEN COMMIT_FORM; log_save(:B.ID); :CTRL.X := 'MENTVE'; END IF; END;"}


def button(source, keys=(KEY_COMMIT,), **options):
    triggers = {}
    for key in keys:
        triggers.setdefault(key['event'], []).append(key)
    overrides = {'KEY-COMMIT': 'COMMIT_FORM', 'KEY-EXEQRY': 'EXECUTE_QUERY', 'KEY-LISTVAL': 'LIST_VALUES'}
    options.setdefault('trigger_item', 'CTRL.PB')
    return prepare(source, block='CTRL', items=ITEMS, units=options.pop('units', {}), prefixes=('qms$',), other_blocks=True,
                   parameters=True, transaction=True, ui=True, form='F', commit_points=True, key_triggers=triggers,
                   key_overrides={overrides[k['event']] for k in keys}, **options)


class TransformTests(unittest.TestCase):
    def test_branches_to_the_point_are_taken_again_and_earlier_statements_skipped(self):
        body, count = transform("BEGIN\n  :a := 1;\n  IF x THEN\n    niva_commit_form(NIVA_POINT);\n    y := 2;\n  END IF;\nEND;")
        self.assertEqual(count, 1)
        self.assertIn('IF niva_resume NOT IN (1) THEN\n  :a := 1;\n  END IF;', body)
        self.assertIn('IF (niva_resume IN (1) OR (niva_resume NOT IN (1) AND (x))) THEN', body)
        self.assertIn('niva_commit_form(1);\n    y := 2;', body)

    def test_points_in_sequence_and_in_else_branches_get_their_own_numbers(self):
        body, count = transform('BEGIN IF a THEN niva_commit_form(NIVA_POINT); ELSIF b THEN NULL; ELSE niva_commit_form(NIVA_POINT);'
                                ' END IF; z := 1; niva_commit_form(NIVA_POINT); w := 2; END;')
        self.assertEqual(count, 3)
        self.assertIn('ELSIF (niva_resume NOT IN (1, 2) AND (b)) THEN', body)
        self.assertIn('ELSE niva_commit_form(2);', body)
        self.assertIn('IF niva_resume NOT IN (3) THEN\nz := 1;\nEND IF;', body)

    def test_enclosing_handlers_let_the_point_through(self):
        body, _ = transform('BEGIN BEGIN niva_commit_form(NIVA_POINT); EXCEPTION WHEN OTHERS THEN NULL; END; END;')
        self.assertIn('EXCEPTION\n  WHEN niva_commit_pending THEN\n    RAISE; WHEN OTHERS', body)

    def test_refused_where_the_continuation_cannot_be_followed(self):
        for source, reason in [
            ('BEGIN FOR r IN (SELECT 1 FROM dual) LOOP niva_commit_form(NIVA_POINT); END LOOP; END;', 'ciklusban'),
            ('BEGIN NULL; EXCEPTION WHEN OTHERS THEN niva_commit_form(NIVA_POINT); END;', 'kivételkezelőben'),
            ('DECLARE v NUMBER; BEGIN v := 1; niva_commit_form(NIVA_POINT); log(v); END;', 'V helyi változó'),
            ('BEGIN GOTO x; niva_commit_form(NIVA_POINT); END;', 'GOTO'),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(Unsupported, reason):
                transform(source)
        # A constant and a variable first set after the point are fine.
        transform('DECLARE c CONSTANT NUMBER := 1; v NUMBER; BEGIN niva_commit_form(NIVA_POINT); v := c; log(v); END;')


class PrepareTests(unittest.TestCase):
    def test_do_key_embeds_the_key_trigger_and_its_commit_form_is_a_commit_point(self):
        r = button("do_key('COMMIT_FORM');")
        self.assertEqual(r['commit_points'], 1)
        self.assertIn("IF (niva_resume IN (1) OR (niva_resume NOT IN (1) AND (nv_", r['sql'])
        self.assertIn('niva_commit_form(1);', r['sql'])
        self.assertIn("NIVA.RESUME", [b['source'] for b in r['binds']])
        self.assertIn("niva_cmd('NIVA_COMMIT', TO_CHAR(niva_commit_at), niva_commit_state);", r['sql'])
        self.assertIn('IF niva_commit_mode IS NULL THEN\n      ROLLBACK TO SAVEPOINT niva_start;', r['sql'])
        self.assertTrue(any('F:KEY-COMMIT saját kódja beágyazva' in n for n in r['notes']))
        # The state compares the item values (numbers in a fixed format), never the request context.
        state = re.search(r'niva_commit_state := SUBSTR\((.*), 1, 32000\);', r['sql'])[1]
        self.assertIn("TO_CHAR(", state)
        self.assertNotIn(re.search(r'(nv_\w+) VARCHAR2\(32767\) := \?; -- NIVA.RESUME', r['sql'])[1], state)

    def test_commit_form_last_stays_a_screen_command(self):
        r = button("do_key('COMMIT_FORM');", keys=[{**KEY_COMMIT, 'source': "message('Mentés'); commit_form;"}])
        self.assertEqual(r['commit_points'], 0)
        self.assertIn("niva_cmd('COMMIT_FORM')", r['sql'])
        # The same KEY trigger with code after DO_KEY: its COMMIT_FORM is no longer last.
        r = button("do_key('COMMIT_FORM'); :CTRL.X := 'kész';", keys=[{**KEY_COMMIT, 'source': "commit_form;"}])
        self.assertEqual(r['commit_points'], 1)

    def test_plain_commit_form_in_the_middle(self):
        r = button("commit_form; :CTRL.X := 'ok';", keys=())
        self.assertEqual(r['commit_points'], 1)
        r = button("commit_form;", keys=())
        self.assertEqual((r['commit_points'], r['commands']), (0, ['COMMIT_FORM']))

    def test_key_trigger_scope_hierarchy_and_recursion(self):
        block_key = {**KEY_COMMIT, 'id': 'B:KEY-COMMIT', 'block': 'B', 'source': 'NULL;'}
        with self.assertRaisesRegex(Unsupported, 'kurzor helyétől'):
            button("do_key('COMMIT_FORM');", keys=[block_key], trigger_item=None)
        own_block = {**KEY_COMMIT, 'id': 'CTRL:KEY-COMMIT', 'block': 'CTRL', 'source': "message('blokk');"}
        r = button("do_key('COMMIT_FORM');", keys=[KEY_COMMIT, own_block])
        self.assertTrue(any('CTRL:KEY-COMMIT' in n for n in r['notes']))  # the button's block wins over the form
        with self.assertRaisesRegex(Unsupported, 'Execution Hierarchy'):
            button("do_key('COMMIT_FORM');", keys=[{**KEY_COMMIT, 'hierarchy': 'BEFORE'}])
        with self.assertRaisesRegex(Unsupported, 'végtelen'):
            button("do_key('COMMIT_FORM');", keys=[{**KEY_COMMIT, 'source': "do_key('COMMIT_FORM');"}])

    def test_navigation_before_do_key_leaves_only_the_form_level_trigger_certain(self):
        block_key = {**KEY_COMMIT, 'id': 'B:KEY-COMMIT', 'block': 'B', 'source': "message('B');"}
        with self.assertRaisesRegex(Unsupported, 'kurzor helyétől'):
            button("go_block('B'); do_key('COMMIT_FORM');", keys=[KEY_COMMIT, block_key])
        r = button("go_block('B'); do_key('COMMIT_FORM');")
        self.assertTrue(any('F:KEY-COMMIT saját kódja beágyazva' in n for n in r['notes']))
        with self.assertRaisesRegex(Unsupported, 'LIST_VALUES lépést'):
            button("do_key('LIST_VALUES');", keys=[{**KEY_COMMIT, 'id': 'F:KEY-LISTVAL', 'event': 'KEY-LISTVAL', 'source': 'list_values;'}])

    def test_local_package_state_cannot_cross_the_point(self):
        units = {'PKG': {'kind': 'package', 'text': '', 'spec': 'PACKAGE pkg IS g NUMBER; PROCEDURE run; END pkg;',
                         'body': 'PACKAGE BODY pkg IS PROCEDURE run IS BEGIN g := 1; END run; END pkg;'}}
        with self.assertRaisesRegex(Unsupported, 'PKG helyi csomag'):
            button("pkg.run; commit_form; pkg.run;", keys=(), units=units)


def java_available():
    if not shutil.which('java'):
        return False
    probe = subprocess.run(['java', 'com.sun.tools.javac.Main', '-version'], capture_output=True, text=True)
    return 'Could not find or load main class' not in probe.stderr


class PreludeJavaTests(unittest.TestCase):
    def test_prelude_accepts_the_same_state_and_refuses_any_other(self):
        if not java_available():
            self.skipTest('JDK (javac) required')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools = root / 'src' / 'CommonMigrateTools.java'
            tools.parent.mkdir()
            template = (ROOT / 'niva_forms/templates/CommonMigrateTools.java.tpl').read_text(encoding='utf-8')
            tools.write_text(template.replace('@@PACKAGE@@', 'hu.test.cl'), encoding='utf-8')
            check = root / 'src' / 'PreludeCheck.java'
            check.write_text('''import hu.test.cl.CommonMigrateTools.PlsqlValues;
import java.util.List;
import java.util.Map;
public class PreludeCheck {
    public static void main(String[] args) {
        var commands = List.of(List.of("GO_BLOCK", "B"), List.of("NIVA_COMMIT", "1", "7\\u001dL"));
        var kept = PlsqlValues.prelude(commands, Map.of("NIVA.COMMIT_POINT", "1", "NIVA.COMMIT_STATE", "7\\u001dL"));
        if (!kept.equals(List.of(List.of("GO_BLOCK", "B")))) throw new AssertionError(kept.toString());
        for (var parameters : List.of(Map.of("NIVA.COMMIT_POINT", "1", "NIVA.COMMIT_STATE", "8\\u001dL"),
                                      Map.of("NIVA.COMMIT_POINT", "2", "NIVA.COMMIT_STATE", "7\\u001dL"))) {
            try {
                PlsqlValues.prelude(commands, parameters);
                throw new AssertionError("an other state must be refused: " + parameters);
            } catch (org.springframework.web.server.ResponseStatusException expected) {
                // HTTP 409: the commit's transaction rolls back
            }
        }
        try {
            PlsqlValues.prelude(List.of(List.of("GO_BLOCK", "B")), Map.of("NIVA.COMMIT_POINT", "1"));
            throw new AssertionError("a run that never reached the point must be refused");
        } catch (org.springframework.web.server.ResponseStatusException expected) {
            // the code did not arrive at the commit point this time
        }
        System.out.println("prelude OK");
    }
}
''', encoding='utf-8')
            sources = [tools, check] + write_stubs(root / 'stubs')
            build = subprocess.run(['java', 'com.sun.tools.javac.Main', '--release', '11', '-encoding', 'UTF-8', '-d',
                                    str(root / 'classes'), *map(str, sources)], capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run(['java', '-cp', str(root / 'classes'), 'PreludeCheck'], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('prelude OK', run.stdout)


class ReplicaFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('NIVA_JAVA_IMPORT_MAP', '-')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = cls.root / 'config.json'
        config.write_text(json.dumps({'java_company_imports': COMPANY_IMPORTS, 'backend_live': True,
                                      'screen_window_selection': 'all', 'screen_primary_window_auto': True}))
        cls.out = cls.root / 'out'
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(['migrate', str(REPLICA), '--out', str(cls.out), '--screen', '--module', 'rendeles', '--config', str(config)])
        assert code == 0, code
        cls.service = (cls.out / 'backend/DPS/RendelesServiceImpl.java').read_text(encoding='utf-8')
        cls.screen = screen_source(cls.out)  # the component and niva-forms-screen.ts

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_commit_endpoint_runs_the_button_first(self):
        commit = self.service[self.service.index('public CommitResult commitForm'):]
        prelude = commit.index('runOnCtrlPbMent(actionValues, actionParameters')
        self.assertLess(prelude, commit.index('changesRendeles()'))
        self.assertIn('actionParameters.put("NIVA.COMMIT", "POST");', commit)
        self.assertIn('commands.addAll(PlsqlValues.prelude(actionCommands, actionParameters));', commit)
        self.assertIn('public String action;', (self.out / 'backend/CL/RendelesDtos.java').read_text(encoding='utf-8'))

    def method(self, name):
        source = screen_method(self.out, name)  # the component's override, else niva-forms-screen.ts
        self.assertIsNotNone(source, name)
        return source

    def test_screen_saves_with_the_prelude_and_resumes_after_the_point(self):
        if not shutil.which('node'):
            self.skipTest('Node with TypeScript stripping required')
        methods = '\n'.join(self.method(name) for name in ('runAction', 'applyChanged', 'formsCommit', 'screenBlocks', 'recordOf',
                                                            'wireText', 'payload', 'showRecord', 'applyOracleValues'))
        self.assertIn('commitEndpoint = (request: Record<string, unknown>) => this.', self.screen)
        script = self.root / 'commit-flow.ts'
        script.write_text('''import assert from 'node:assert/strict';
const TOAST_LIFE = {warning: 1, success: 1};
const localIso = (value: Date) => value.toISOString();
__RUNTIME_GLOBALS__
class Group { dirty = false; invalid = false; value: Record<string, unknown> = {}; markAsDirty() { this.dirty = true; } markAsPristine() { this.dirty = false; } markAllAsTouched() {} patchValue(v) { Object.assign(this.value, v); } }
class Screen {
  toastLife = TOAST_LIFE;
  initAction = '@INIT';
  queryActionBlocks = {};
  activeQueryActions = {};
  checkboxValues = {};
  stateRecord() {}
  selectedRecords() { return {}; }
  formValues: Record<string, Record<string, unknown>> = {RENDELES: {id: 7, statusz: 'N', vevo: 'V1'}, CTRL: {utolso: null}};
  formGroups = {rendeles: new Group(), ctrl: new Group()};
  regionBlocks = {rendeles: 'RENDELES', ctrl: 'CTRL'};
  oracleNames = {RENDELES: {id: 'ID', statusz: 'STATUSZ', vevo: 'VEVO'}, CTRL: {utolso: 'UTOLSO'}};
  rowKeys = {RENDELES: {id: 'id', statusz: 'statusz', vevo: 'vevo'}};
  commitBlocks = {RENDELES: {request: 'changesRendeles', result: 'rowsRendeles', operations: ['create', 'update', 'delete']}};
  originals: Record<string, Record<string, unknown> | null> = {RENDELES: {id: 7, statusz: 'N', vevo: 'V1'}};
  pendingDeletes = {};
  changeDetector = {markForCheck() {}};
  successes = [];
  warnings = [];
  toast = {warning: (...args) => this.warnings.push(args), success: (...args) => this.successes.push(args)};
  actions = [];
  commits = [];
  actionReplies = [];
  actionEndpoints = {'CTRL.PB_MENT': request => {
    this.actions.push(structuredClone(request));
    const reply = this.actionReplies.shift();
    return {subscribe: handlers => handlers.next({data: reply})};
  }};
  commitEndpoint = request => {
    this.commits.push(structuredClone(request));
    return {subscribe: handlers => handlers.next({data: {blocks: {}, messages: [], commands: [], globals: {}, rowsRendeles: [{id: 7, statusz: 'L', vevo: 'V1'}]}})};
  };
  requestContext() { return {'SYSTEM.CURSOR_BLOCK': 'CTRL'}; }
  rememberGlobals() {}
  runCommands(commands) { this.ran = commands; }
  askAlert() { throw new Error('no alert'); }
  markPristine(block) { for (const [region, group] of Object.entries(this.formGroups)) if (this.regionBlocks[region] === block) group.markAsPristine(); }
__METHODS__
}
const screen = new Screen();
// 1. The button reaches COMMIT_FORM: its work was rolled back, the values of that moment come back.
screen.actionReplies.push({blocks: {RENDELES: {ID: '7', STATUSZ: 'L', VEVO: 'V1'}, CTRL: {UTOLSO: null}}, messages: [],
                           commands: [['NIVA_COMMIT', '1', '7\\u001dL\\u001dV1\\u001d']], globals: {}});
// 3. Resumed after the point: the code after COMMIT_FORM ran.
screen.actionReplies.push({blocks: {CTRL: {UTOLSO: 'L'}}, messages: [], commands: [], globals: {}});
assert.equal(screen.runAction('CTRL.PB_MENT'), true);
// 2. The commit carries the changed record and the button's original request (prelude).
assert.equal(screen.commits.length, 1);
const commit = screen.commits[0];
assert.equal(commit.action, 'CTRL.PB_MENT');
assert.deepEqual(commit.actionBlocks.RENDELES, {ID: '7', STATUSZ: 'N', VEVO: 'V1'});
assert.equal(commit.actionParameters['NIVA.COMMIT_POINT'], '1');
assert.equal(commit.actionParameters['NIVA.COMMIT_STATE'], '7\\u001dL\\u001dV1\\u001d');
assert.deepEqual(commit.changesRendeles.updated[0].value, {id: '7', statusz: 'L', vevo: 'V1'});
assert.equal(screen.actions.length, 2);
assert.equal(screen.actions[0].parameters['NIVA.RESUME'], undefined);
assert.equal(screen.actions[1].parameters['NIVA.RESUME'], '1');
assert.equal(screen.formValues.CTRL.utolso, 'L');
console.log('typescript commit-point OK');
'''.replace('__METHODS__', methods).replace('__RUNTIME_GLOBALS__', RUNTIME_GLOBALS))
        run = subprocess.run(['node', '--experimental-strip-types', '--no-warnings', str(script)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('typescript commit-point OK', run.stdout)


if __name__ == '__main__':
    unittest.main()

"""DEFAULT_WHERE actions preserve the Forms builder and execute typed queries."""
import contextlib
import io
import itertools
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from java_support import COMPANY_IMPORTS, write_stubs
from niva_forms.cli import main
from niva_forms.plsql_passthrough import scan
from niva_forms.service_inline import mask


BASE = '''COL6=;00; and ((:T1.COL1 = ;MB_34ADLAP; and COL7 in (;MB_34;,;MB_35;)) or
  (:T1.COL1 = ;T109; and COL7 = ;06109;) or
  (:T1.COL1 = ;MB_UCC; and COL7 = ;MB_UCC;) or
  (:T1.COL1 = ;T104; and COL7 = ;T104;) or
  (:T1.COL1 = ;25T104; and COL7 = ;25T104;) or
  (:T1.COL1 = ;26T104; and COL7 = ;26T104;)) and
  COL8 = :T1.COL5'''

BUILDER = "PROCEDURE lekerdezesi_feltetelek IS\n  lek_sql varchar2(1000);\nBEGIN\n"
BUILDER += "/* régi, már nem futó feltételek: SET_BLOCK_PROPERTY('OTHER', DEFAULT_WHERE, 'X'); */\n"
BUILDER += "lek_sql := '" + BASE + "';\n"
for flags, codes in [((1, 1, 1), ('E04', 'P01')), ((1, 1, 0), ('E04', 'E07')),
                     ((0, 1, 1), ('E07', 'P01')), ((1, 0, 1), ('E04', 'P01'))]:
    BUILDER += ('IF ' + ' AND '.join(':T1.COL' + str(i) + ' = ' + str(f) for i, f in zip((2, 3, 4), flags))
                + " THEN lek_sql := lek_sql || ' and (COL9=;" + codes[0] + '; or COL9=;' + codes[1] + ";)'; END IF;\n")
BUILDER += """SELECT REPLACE(lek_sql, ';', chr(39)) INTO lek_sql FROM dual;
  Set_Block_Property('BLK', DEFAULT_WHERE, lek_sql);
  go_block('BLK');
  execute_query();
END;"""

BUTTON = """/* CGAP$OLES_SEQUENCE_BEFORE */
begin qms$event_item('WHEN-BUTTON-PRESSED'); end;
Begin
 If :T1.COL1 is not null then
    lekerdezesi_feltetelek;
 else
    wuzenet('Adatlap kiválasztása nem történt meg!');
 end if;
End;"""


def fixture(builder=BUILDER, button=BUTTON, extra=''):
    root = ET.Element('Module')
    form = ET.SubElement(root, 'FormModule', Name='F')
    ET.SubElement(form, 'Coordinate', CoordinateSystem='Real', RealUnit='Pixel')
    ET.SubElement(form, 'Window', Name='W')
    ET.SubElement(form, 'Canvas', Name='C', CanvasType='Content', WindowName='W', Width='600', Height='400')
    controls = ET.SubElement(form, 'Block', Name='T1', DatabaseDataBlock='false')
    for i in range(1, 6):
        props = dict(Name='COL' + str(i), DataType='Number' if i in (2, 3, 4) else 'Char',
                     DatabaseItem='false', CanvasName='C', XPosition=str(i * 90), YPosition='20', Width='80', Height='20')
        if i in (2, 3, 4):
            props.update(ItemType='Check Box', CheckBoxCheckedValue='1', CheckBoxUncheckedValue='0', InitialValue='0')
        else:
            props.update(ItemType='Text Item', MaximumLength='40')
        ET.SubElement(controls, 'Item', **props)
    button_item = ET.SubElement(controls, 'Item', Name='PB_LEKERDEZES', ItemType='Push Button', DatabaseItem='false',
                               CanvasName='C', XPosition='10', YPosition='60', Width='100', Height='30', Label='Lekérdezés')
    ET.SubElement(button_item, 'Trigger', Name='WHEN-BUTTON-PRESSED', TriggerText=button)
    block = ET.SubElement(form, 'Block', Name='BLK', DatabaseDataBlock='true', QueryDataSourceName='T_BLK',
                          InsertAllowed='false', UpdateAllowed='false', DeleteAllowed='false', RecordsDisplayCount='5')
    for i in range(6, 10):
        ET.SubElement(block, 'Item', Name='COL' + str(i), ColumnName='COL' + str(i), ItemType='Text Item',
                      DataType='Char', MaximumLength='40', PrimaryKey='true' if i == 6 else 'false',
                      CanvasName='C', XPosition=str((i - 6) * 100), YPosition='120', Width='90', Height='20')
    ET.SubElement(block, 'Item', Name='INFO', ItemType='Text Item', DataType='Char', DatabaseItem='false')
    ET.SubElement(block, 'Trigger', Name='POST-QUERY', TriggerText=":BLK.INFO := 'Betöltve';")
    ET.SubElement(form, 'ProgramUnit', Name='LEKERDEZESI_FELTETELEK', ProgramUnitType='Procedure', ProgramUnitText=builder)
    if extra:
        ET.SubElement(form, 'ProgramUnit', Name='OTHER', ProgramUnitType='Procedure', ProgramUnitText=extra)
    return ET.tostring(root)


class QueryActionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def generate(self, builder=BUILDER, button=BUTTON, extra='', config=None, label='out', raw=None, module='query'):
        source = self.root / (label + '.xml')
        source.write_bytes(raw if raw is not None else fixture(builder, button, extra))
        settings = self.root / (label + '.json')
        settings.write_text(json.dumps({'backend_live': True, 'backend_trigger_mode': 'plsql',
                                       'java_company_imports': COMPANY_IMPORTS, 'java_import_map': '-', **(config or {})}))
        output = self.root / label
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            result = main(['migrate', str(source), '--module', module, '--screen', '--config', str(settings), '--out', str(output)])
        self.assertEqual(result, 0, errors.getvalue())
        return output

    def model(self, output):
        return json.loads((output / 'analysis/form.ir.json').read_text())

    def action(self, output):
        plan = json.loads((output / 'analysis/backend-plan.json').read_text())
        return next(e for e in plan['endpoints'] if e['operation'] == 'action')

    def test_button_is_a_query_and_original_plsql_is_preserved(self):
        out = self.generate()
        endpoint = self.action(out)
        self.assertTrue(endpoint['implemented'], endpoint)
        self.assertEqual(endpoint['runs'], 'plsql-query')
        self.assertEqual(endpoint['query_block'], 'BLK')
        self.assertEqual(endpoint['blockers'], [])
        service = (out / 'backend/DPS/QueryServiceImpl.java').read_text()
        self.assertIn('QueryActionRequest request', service)
        self.assertIn('PageResult<BlkRow> onT1PbLekerdezes', service)
        self.assertIn('SELECT REPLACE(lek_sql', service)
        self.assertIn('IF ', service)
        query_plan = next(t['query_action'] for t in self.model(out)['triggers'] if t.get('query_action'))
        self.assertEqual(len(query_plan['variants']), 4)
        executable = ''.join(t[1] for t in scan(query_plan['prepared']['sql']) if t[0] not in {'string', 'comment'}).upper()
        self.assertNotIn('SET_BLOCK_PROPERTY(', executable)
        self.assertNotIn('GO_BLOCK(', executable)
        self.assertNotIn('EXECUTE_QUERY();', executable)
        self.assertNotIn('Ez a gomb még nincs átültetve', service)
        self.assertIn('postQueryBlk(row, context)', service)
        evidence = (out / 'analysis/backend-evidence.md').read_text()
        self.assertIn('Set_Block_Property', evidence)
        self.assertIn('wuzenet', evidence)
        self.assertIn('Előre lefordított SQL-változatok: 4', evidence)
        coverage = json.loads((out / 'analysis/runtime-coverage.json').read_text())
        rows = coverage.get('triggers', [])
        action_row = next(r for r in rows if r['event'] == 'WHEN-BUTTON-PRESSED')
        self.assertEqual(action_row['engine'], 'plsql-query')
        self.assertEqual(action_row['query_block'], 'BLK')
        self.assertFalse(any('Képernyőn nem szereplő blokk' in g for g in action_row['gaps']))
        post_row = next(r for r in rows if r['event'] == 'POST-QUERY')
        self.assertTrue(any(e['method'] == endpoint['method'] for e in post_row['endpoints']))
        # The unrelated default list cannot silently bypass the dynamic WHERE.
        default = next(e for e in json.loads((out / 'analysis/backend-plan.json').read_text())['endpoints'] if e['operation'] == 'list')
        self.assertFalse(default['implemented'])

    def test_all_checkbox_combinations_and_codes_use_bound_predicates(self):
        out = self.generate()
        trigger = next(t for t in self.model(out)['triggers'] if t['event'] == 'WHEN-BUTTON-PRESSED')
        choices = {v['predicate']: v for v in trigger['query_action']['variants']}
        allowed = {(1, 1, 1): {'E04', 'P01'}, (1, 1, 0): {'E04', 'E07'},
                   (0, 1, 1): {'E07', 'P01'}, (1, 0, 1): {'E04', 'P01'}}
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE T_BLK (COL6 TEXT, COL7 TEXT, COL8 TEXT, COL9 TEXT)')
            for col6, col7, col8, col9 in itertools.product(('00', '99'), ('MB_34', 'MB_35', '06109', 'MB_UCC', 'T104', '25T104', '26T104'), ('X', 'Y'), ('E04', 'E07', 'P01', 'OTHER')):
                db.execute('INSERT INTO T_BLK VALUES (?, ?, ?, ?)', (col6, col7, col8, col9))
            for flags in itertools.product((0, 1), repeat=3):
                codes = allowed.get(flags)
                source = BASE
                if codes:
                    # The actual code's order is immaterial to the result, but
                    # matching the original Oracle output uses its exact text.
                    order = ('E07', 'P01') if flags == (0, 1, 1) else ('E04', 'E07') if flags == (1, 1, 0) else ('E04', 'P01')
                    source += ' and (COL9=;' + order[0] + '; or COL9=;' + order[1] + ';)'
                choice = choices[source.replace(';', "'")]
                for selected, values in [('MB_34ADLAP', {'MB_34', 'MB_35'}), ('T109', {'06109'}), ('MB_UCC', {'MB_UCC'}), ('T104', {'T104'}), ('25T104', {'25T104'}), ('26T104', {'26T104'}), ("' OR 1=1 --", set()), (None, set())]:
                    params = {b['parameter']: selected if b['source'] == 'T1.COL1' else 'X' for b in choice['binds']}
                    rows = db.execute(choice['sql'].split(' OFFSET :offset')[0], params).fetchall()
                    expected = set(itertools.product(('00',), values, ('X',), codes or {'E04', 'E07', 'P01', 'OTHER'}))
                    self.assertEqual(set(rows), expected, (flags, selected))

    def test_char_checkboxes_keep_native_numeric_comparisons_and_varchar_binds(self):
        out = self.generate(raw=fixture().replace(b'DataType="Number"', b'DataType="Char"'))
        action = self.action(out)
        self.assertTrue(action['implemented'], action['blockers'])
        self.assertEqual(action['runs'], 'plsql-query')
        plan = next(t['query_action'] for t in self.model(out)['triggers'] if t.get('query_action'))
        self.assertEqual(len(plan['variants']), 4)
        flag_binds = [b for b in plan['prepared']['binds'] if b['source'] in {'T1.COL2', 'T1.COL3', 'T1.COL4'}]
        self.assertEqual(len(flag_binds), 3)
        self.assertTrue(all(b['type'] == 'text' for b in flag_binds))
        service = (out / 'backend/DPS/QueryServiceImpl.java').read_text()
        for i in (2, 3, 4):
            self.assertIn(' = 1 AND' if i == 2 else ' = 1', plan['prepared']['sql'])
            self.assertIn('PlsqlValues.text(values, "T1", "COL' + str(i) + '")', service)
        self.assertNotIn('Ez a gomb még nincs átültetve', service)

    def test_native_guard_and_nvl_use_oracle_conversion_without_changing_sql_validation(self):
        button = BUTTON.replace(':T1.COL1 is not null', "NVL(:T1.COL2, '0') = 1")
        raw = fixture(button=button).replace(b'DataType="Number"', b'DataType="Char"')
        out = self.generate(raw=raw)
        self.assertTrue(self.action(out)['implemented'], self.action(out)['blockers'])
        plan = next(t['query_action'] for t in self.model(out)['triggers'] if t.get('query_action'))
        self.assertIn('NVL(', plan['prepared']['sql'])
        # JDBC SQL remains a closed typed compiler: conversion was relaxed only
        # for the PL/SQL that Oracle executes, never for the compiled WHERE.
        raw = raw.replace(b'Name="COL6" ColumnName="COL6" ItemType="Text Item" DataType="Char"',
                          b'Name="COL6" ColumnName="COL6" ItemType="Text Item" DataType="Number"')
        blocked = self.generate(raw=raw, label='sql-type-mismatch')
        self.assertFalse(self.action(blocked)['implemented'])

    def test_unknown_and_shadowed_functions_in_query_conditions_stay_manual(self):
        for i, condition in enumerate(('pkg.mutate(:T1.COL2) = 1', 'GET_ITEM_PROPERTY(\'T1.COL2\', ENABLED) = 1',
                                       'COL6 = 1', ':GLOBAL.SELECTED = 1')):
            out = self.generate(button=BUTTON.replace(':T1.COL1 is not null', condition), label='impure' + str(i))
            action = self.action(out)
            self.assertFalse(action['implemented'], condition)
            self.assertEqual(action['runs'], 'manual')
            self.assertIn('query', action['adapter_diagnostics'])
        root = ET.fromstring(fixture(button=BUTTON.replace(':T1.COL1 is not null', 'ABS(:T1.COL2) = 1')))
        ET.SubElement(root.find('FormModule'), 'ProgramUnit', Name='ABS', ProgramUnitType='Function',
                      ProgramUnitText='FUNCTION abs(p NUMBER) RETURN NUMBER IS BEGIN INSERT INTO audit_log VALUES(p); RETURN p; END;')
        out = self.generate(raw=ET.tostring(root), label='shadowed')
        self.assertFalse(self.action(out)['implemented'])
        self.assertIn('ABS', self.action(out)['adapter_diagnostics']['query'])

    def test_do_key_query_tail_uses_builtin_only_without_any_key_override(self):
        builder = BUILDER.replace('execute_query();', "do_key('EXECUTE_QUERY');")
        out = self.generate(builder=builder)
        self.assertTrue(self.action(out)['implemented'], self.action(out)['blockers'])
        plan = next(t['query_action'] for t in self.model(out)['triggers'] if t.get('query_action'))
        executable = ''.join(t[1] for t in scan(plan['prepared']['sql']) if t[0] not in {'string', 'comment'}).upper()
        self.assertNotIn('DO_KEY(', executable)
        for index, level in enumerate(('form', 'block', 'item')):
            root = ET.fromstring(fixture(builder=builder))
            form = root.find('FormModule')
            block = next(b for b in form.findall('Block') if b.get('Name') == 'BLK')
            owner = {'form': form, 'block': block, 'item': block.find('Item')}[level]
            ET.SubElement(owner, 'Trigger', Name='KEY-EXEQRY', TriggerText='NULL;')
            blocked = self.generate(raw=ET.tostring(root), label='key' + str(index))
            self.assertFalse(self.action(blocked)['implemented'])
            self.assertIn('KEY-EXEQRY', self.action(blocked)['adapter_diagnostics']['query'])

    def test_same_pattern_works_with_another_module_and_all_source_names_changed(self):
        replacements = {'F': 'REPORT_004', 'T1': 'CONTROLS', 'BLK': 'RESULT_ROWS', 'T_BLK': 'T_REPORT_ROWS',
                        'COL1': 'KIND_CODE', 'COL2': 'FLAG_A', 'COL3': 'FLAG_B', 'COL4': 'FLAG_C',
                        'COL5': 'SCOPE_CODE', 'COL6': 'STATUS_CODE', 'COL7': 'REPORT_CODE', 'COL8': 'AREA_CODE',
                        'COL9': 'RULE_CODE', 'PB_LEKERDEZES': 'LOAD_ROWS', 'LEK_SQL': 'where_text',
                        'LEKERDEZESI_FELTETELEK': 'build_report_filter'}
        raw = fixture().decode()
        raw = re.sub(r'\b(?:' + '|'.join(replacements) + r')\b',
                     lambda match: replacements[match.group().upper()], raw, flags=re.I)
        raw = raw.replace('DataType="Number"', 'DataType="Char"')
        out = self.generate(raw=raw.encode(), label='renamed', module='report004')
        action = self.action(out)
        self.assertTrue(action['implemented'], action['blockers'])
        self.assertEqual(action['query_block'], 'RESULT_ROWS')
        self.assertEqual(action['query_unit'], 'BUILD_REPORT_FILTER')
        self.assertTrue((out / 'backend/DPS/Report004ServiceImpl.java').is_file())
        plan = next(t['query_action'] for t in self.model(out)['triggers'] if t.get('query_action'))
        self.assertEqual(len(plan['variants']), 4)
        self.assertTrue(all('T_REPORT_ROWS' in p['sql'] for p in plan['variants']))
        self.assertTrue(all(b['source'].startswith('CONTROLS.') for p in plan['variants'] for b in p['binds']))

    def test_full_recognition_reason_is_visible_in_java_and_backend_reports(self):
        out = self.generate(builder=BUILDER.replace("go_block('BLK')", "go_block('OTHER')"))
        action = self.action(out)
        self.assertFalse(action['implemented'])
        reason = action['adapter_diagnostics']['query']
        self.assertIn('GO_BLOCK', reason)
        self.assertTrue(action['blockers'][0].startswith('Lekérdezés-adapter: '))
        java = (out / 'backend/DPS/QueryServiceImpl.java').read_text()
        # Wrapped comments must retain the full reason, rather than a 160-char prefix.
        comments = ' '.join(line.strip().removeprefix('// ') for line in java.splitlines() if line.strip().startswith('// '))
        self.assertIn(reason, comments)
        self.assertIn(reason, (out / 'analysis/backend-evidence.md').read_text())

    def test_regeneration_reports_preserved_501_even_when_the_fresh_candidate_is_ready(self):
        out = self.generate(builder=BUILDER.replace("go_block('BLK')", "go_block('OTHER')"))
        service_file = out / 'backend/DPS/QueryServiceImpl.java'
        previous = service_file.read_bytes()
        self.assertIn(b'NOT_IMPLEMENTED', previous)
        source = self.root / 'out.xml'
        source.write_bytes(fixture().replace(b'DataType="Number"', b'DataType="Char"'))
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            result = main(['migrate', str(source), '--module', 'query', '--screen', '--regenerate',
                           '--config', str(self.root / 'out.json'), '--out', str(out)])
        self.assertEqual(result, 0, errors.getvalue())
        self.assertEqual(service_file.read_bytes(), previous)
        candidate = out / 'analysis/backend-regeneration/backend/DPS/QueryServiceImpl.java.txt'
        self.assertIn('PageResult<BlkRow> onT1PbLekerdezes', candidate.read_text())
        self.assertNotIn('Ez a gomb még nincs átültetve', candidate.read_text())
        plan = json.loads((out / 'analysis/backend-plan.json').read_text())
        self.assertTrue(plan['regeneration_status']['manual_merge_required'])
        self.assertIn('backend/DPS/QueryServiceImpl.java', plan['regeneration_status']['preserved_files'])
        self.assertTrue(self.action(out)['implemented'])  # candidate state, explicitly documented in the report

    def test_other_runtime_properties_still_block_the_query(self):
        out = self.generate(extra="PROCEDURE other IS BEGIN set_block_property('BLK', ORDER_BY, 'COL9 DESC'); END;")
        endpoint = self.action(out)
        self.assertFalse(endpoint['implemented'])
        self.assertTrue(any('ORDER_BY' in s for s in endpoint['blockers']))

    def test_unrecognized_builder_cannot_be_partially_migrated(self):
        for index, broken in enumerate((BUILDER.replace("go_block('BLK')", "go_block('OTHER')"),
                       BUILDER.replace("lek_sql := 'COL6", "lek_sql := :T1.COL1 || 'COL6"),
                       BUILDER.replace('BEGIN\n', 'BEGIN\n DELETE FROM T_BLK;\n', 1),
                       BUILDER.replace('COL6=;00;', 'SECRET=;00;'))):
            with self.subTest(builder=broken[-150:]):
                out = self.generate(builder=broken, label='broken' + str(index))
                self.assertFalse(self.action(out)['implemented'])
                self.assertEqual(self.action(out)['runs'], 'manual')

    def test_frontend_sends_flags_and_displays_rows_without_clearing_on_validation(self):
        out = self.generate()
        component = next((out / 'frontend').rglob('*.component.ts')).read_text()
        self.assertIn('queryActionBlocks', component)
        self.assertIn('offset: 0, limit: 200', component)
        self.assertIn('if (page.rows != null)', component)
        self.assertIn('this.showRows(target, page.rows)', component)
        self.assertIn('this.activeQueryActions[target] = ownId', component)
        self.assertIn('if (action) return this.runAction(action)', component)
        self.assertIn('value ? pair[0] : pair[1]', component)

    def test_company_contract_uses_the_same_query_request_and_page_in_every_layer(self):
        from test_company_cl import CL_IMPORTS
        out = self.generate(config={'AWU_AZON': '00123', 'java_company_imports': CL_IMPORTS})
        endpoint = self.action(out)
        self.assertTrue(endpoint['implemented'])
        method = endpoint['method']
        for layer, suffix in [('CL', 'RestClient'), ('DPS', 'Controller'), ('DPS', 'Service'),
                              ('WBS', 'Controller'), ('WBS', 'Service')]:
            source = (out / 'backend' / layer / ('Query' + suffix + '.java')).read_text()
            self.assertIn(method, source)
            self.assertIn('QueryQueryActionRequestDto', source)
            self.assertIn('QueryPageResultDto<QueryBlkDto>', source)
        request = (out / 'backend/CL/QueryQueryActionRequestDto.java').read_text()
        self.assertIn('private int offset;', request)
        self.assertIn('private int limit;', request)
        service = (out / 'backend/DPS/QueryServiceImpl.java').read_text()
        self.assertIn('request.getBlocks()', service)
        self.assertIn('request.getLimit()', service)
        self.assertIn('row.setCol6(rs.getString(1))', service)
        self.assertIn('new QueryPageResultDto<>(rows, messages)', service)

    def test_review_gate_still_controls_the_query_button(self):
        out = self.generate(config={'backend_live': False})
        action = self.action(out)
        self.assertFalse(action['implemented'])
        self.assertTrue(action['ready_after_module_review'])
        self.assertEqual(action['blockers'], [])

    def test_generated_java_compiles_and_calls_builder_then_query_and_post_query(self):
        self.java_query_flow()

    def test_generated_java_executes_char_checkbox_request_with_varchar_jdbc_binds(self):
        self.java_query_flow(char_flags=True)

    def java_query_flow(self, char_flags=False):
        if not shutil.which('java'):
            self.skipTest('Java 11+ compiler required')
        raw = fixture().replace(b'DataType="Number"', b'DataType="Char"') if char_flags else None
        out = self.generate(raw=raw)
        action = self.action(out)
        plan = next(t['query_action'] for t in self.model(out)['triggers'] if t.get('query_action'))
        prepared = plan['prepared']
        predicate = BASE.replace(';', "'") + " and (COL9='E04' or COL9='P01')"
        binds = {b['source']: n + 1 for n, b in enumerate(prepared['binds'])}
        outs = {b['source']: len(prepared['binds']) + n + 1 for n, b in enumerate(prepared['outs'])}
        message_index = len(prepared['binds']) + len(prepared['outs']) + 1
        smoke = self.root / 'QuerySmoke.java'
        smoke.write_text('''import java.lang.reflect.Proxy;
import java.sql.CallableStatement;
import java.sql.ResultSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import hu.company.features.query.dps.QueryServiceImpl;
import hu.company.features.query.cl.QueryDtos.QueryActionRequest;
import hu.company.common.UserDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.CallableStatementCallback;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

public class QuerySmoke {
    static String predicate = __PREDICATE__;

    static class CaptureJdbc extends NamedParameterJdbcTemplate {
        int builders;
        int queries;
        int postQueries;
        boolean selected = true;
        boolean tampered;

        @Override
        public JdbcTemplate getJdbcTemplate() {
            return new JdbcTemplate() {
                @Override
                public <T> T execute(String sql, CallableStatementCallback<T> callback) {
                    var inputs = new HashMap<Integer, Object>();
                    var outputs = new HashMap<Integer, Object>();
                    boolean builder = sql.contains("PROCEDURE lekerdezesi_feltetelek");
                    if (builder) {
                        builders++;
                        outputs.put(__WHERE_OUT__, tampered ? "1=1" : predicate);
                        outputs.put(__EXECUTED_OUT__, selected ? "Y" : null);
                        outputs.put(__MESSAGE_OUT__, selected ? null : "Adatlap kiválasztása nem történt meg!");
                    } else {
                        postQueries++;
                        outputs.put(2, "Betöltve");
                        outputs.put(3, "Sorüzenet");
                    }
                    var statement = (CallableStatement) Proxy.newProxyInstance(
                        getClass().getClassLoader(), new Class<?>[] {CallableStatement.class}, (proxy, method, args) -> {
                            switch (method.getName()) {
                                case "setObject": inputs.put((Integer) args[0], args[1]); return null;
                                case "setNull": inputs.put((Integer) args[0], null); return null;
                                case "registerOutParameter": return null;
                                case "getString": return outputs.get(args[0]);
                                case "getBigDecimal": return outputs.get(args[0]);
                                case "execute":
                                    if (builder && (inputs.get(__WHERE_IN__) != null || inputs.get(__EXECUTED_IN__) != null)) {
                                        throw new AssertionError("Client cannot supply the computed predicate.");
                                    }
                                    if (builder && selected && !__FLAG_VALUE__.equals(inputs.get(__FLAG_IN__))) {
                                        throw new AssertionError("Checkboxes must retain the original Forms data type.");
                                    }
                                    return true;
                                default: throw new AssertionError(method.getName());
                            }
                        });
                    try {
                        return callback.doInCallableStatement(statement);
                    } catch (java.sql.SQLException e) {
                        throw new AssertionError(e);
                    }
                }
            };
        }

        @Override
        public <T> List<T> query(String sql, SqlParameterSource params, RowMapper<T> mapper) {
            queries++;
            if (builders != queries || !"MB_34ADLAP".equals(params.getValue("q0"))
                    || !"X".equals(params.getValue("q1")) || !Integer.valueOf(200).equals(params.getValue("limit"))
                    || !sql.contains("WHERE") || sql.contains(":T1.") || sql.contains("MB_34ADLAP' OR")) {
                throw new AssertionError("Builder, typed binds and bounded query must be used.");
            }
            var row = (ResultSet) Proxy.newProxyInstance(getClass().getClassLoader(), new Class<?>[] {ResultSet.class},
                (proxy, method, args) -> {
                    if (!method.getName().equals("getString")) throw new AssertionError(method.getName());
                    return new String[] {"00", "MB_34", "X", "E04"}[(Integer) args[0] - 1];
                });
            try {
                return List.of(mapper.mapRow(row, 0));
            } catch (java.sql.SQLException e) {
                throw new AssertionError(e);
            }
        }
    }

    public static void main(String[] args) throws Exception {
        var jdbc = new CaptureJdbc();
        var service = new QueryServiceImpl(jdbc);
        var values = Map.of("T1", Map.of("COL1", "MB_34ADLAP", "COL2", "1", "COL3", "1", "COL4", "1", "COL5", "X"),
                            "NIVA_QUERY_CONTEXT", Map.of("WHERE_TEXT", "1=1", "EXECUTED", "Y"));
        var request = new QueryActionRequest(values, Map.of(), 0, 200);
        var result = service.__METHOD__(new UserDto(), request);
        if (result.rows().size() != 1 || !"MB_34".equals(result.rows().get(0).col7)
                || !"Betöltve".equals(result.rows().get(0).info) || !result.messages().equals(List.of("Sorüzenet"))
                || jdbc.queries != 1 || jdbc.postQueries != 1) {
            throw new AssertionError("Query rows, POST-QUERY values and messages must be returned.");
        }
        jdbc.selected = false;
        result = service.__METHOD__(new UserDto(), request);
        if (result.rows() != null || jdbc.queries != 1 || result.messages().isEmpty()) {
            throw new AssertionError("No selection must warn without clearing existing rows or querying.");
        }
        jdbc.selected = true;
        jdbc.tampered = true;
        try {
            service.__METHOD__(new UserDto(), request);
            throw new AssertionError("An uncompiled runtime predicate must be refused.");
        } catch (org.springframework.web.server.ResponseStatusException expected) {
            if (jdbc.queries != 1) throw new AssertionError("Uncompiled SQL must not reach JDBC SELECT.");
        }
        System.out.println("query-action OK");
    }
}
'''.replace('__PREDICATE__', json.dumps(predicate, ensure_ascii=False))
            .replace('__WHERE_OUT__', str(outs[plan['context'] + '.WHERE_TEXT']))
            .replace('__EXECUTED_OUT__', str(outs[plan['context'] + '.EXECUTED']))
            .replace('__MESSAGE_OUT__', str(message_index))
            .replace('__WHERE_IN__', str(binds[plan['context'] + '.WHERE_TEXT']))
            .replace('__EXECUTED_IN__', str(binds[plan['context'] + '.EXECUTED']))
            .replace('__FLAG_IN__', str(binds['T1.COL2']))
            .replace('__FLAG_VALUE__', '"1"' if char_flags else 'new java.math.BigDecimal("1")')
            .replace('__METHOD__', action['method']))
        sources = list(out.glob('backend/**/*.java')) + write_stubs(self.root / 'stubs') + [smoke]
        classes = self.root / 'classes'
        compile_result = subprocess.run(['java', 'com.sun.tools.javac.Main', '--release', '11', '-d', str(classes),
                                         *map(str, sources)], text=True, capture_output=True)
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
        run = subprocess.run(['java', '-cp', str(classes), 'QuerySmoke'], text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('query-action OK', run.stdout)

    def test_generated_typescript_action_flow_in_node(self):
        if not shutil.which('node'):
            self.skipTest('Node with TypeScript stripping required')
        out = self.generate()
        component = next((out / 'frontend').rglob('*.component.ts')).read_text()
        visible = mask(component)
        methods = []
        for method in ('runAction', 'executeQuery', 'showRows', 'showRecord', 'wireText', 'payload'):
            match = re.search(r'^  (?:private |public )?' + method + r'(?:<[^>]+>)?\([^\n]*\)[^\n]*\{', visible, re.M)
            self.assertIsNotNone(match, method)
            start, end, depth = match.start(), match.end(), 1
            while depth:
                if visible[end] == '{':
                    depth += 1
                elif visible[end] == '}':
                    depth -= 1
                end += 1
            methods.append(component[start:end])
        p = re.search(r'interface (\w+)Page', component)[1]
        script = self.root / 'query-flow.ts'
        script.write_text('''import assert from 'node:assert/strict';
const TOAST_LIFE = {warning: 1, success: 1};
const localIso = (value: Date) => value.toISOString();
interface __P__Page { rows?: Record<string, unknown>[] | null; messages?: string[]; }
interface __P__ActionResult { blocks?: Record<string, Record<string, string | null>>; messages?: string[]; }
interface __P__BlkRow { col6?: string; col7?: string; }
class Screen {
  formValues = {T1: {col1: 'MB_34ADLAP', col2: true, col3: false, col4: true, col5: 'X'}};
  formGroups = {};
  regionBlocks = {};
  oracleNames = {T1: {col1: 'COL1', col2: 'COL2', col3: 'COL3', col4: 'COL4', col5: 'COL5'}};
  checkboxValues = {T1: {col2: ['1','0'], col3: ['1','0'], col4: ['1','0']}};
  queryActionBlocks = {'T1.PB_LEKERDEZES': 'BLK'};
  activeQueryActions = {};
  rowKeys = {BLK: {col6: 'col6', col7: 'col7'}};
  queries = {};
  blkRows = [{col7: 'old'}];
  blkSelection = null;
  changeDetector = {markForCheck() {}};
  warnings = [];
  successes = [];
  toast = {warning: (...args) => this.warnings.push(args), success: (...args) => this.successes.push(args)};
  requests = [];
  reply = {rows: [{col6: '00', col7: 'MB_34'}], messages: []};
  actionEndpoints = {'T1.PB_LEKERDEZES': request => {
    this.requests.push(request);
    return {subscribe: handlers => handlers.next({data: this.reply})};
  }};
  applyOracleValues() { throw new Error('A page is not an ActionResult'); }
  // Forms runtime emulation (screen_emulation): not part of the query-action flow under test.
  requestContext() { return {}; }
  rememberGlobals() { throw new Error('A page has no globals'); }
  runCommands(commands) { if (commands.length) throw new Error('Unexpected commands'); }
  askAlert() { throw new Error('A page has no alert'); }
__METHODS__
}
const screen = new Screen();
assert.equal(screen.runAction('T1.PB_LEKERDEZES'), true);
assert.deepEqual(screen.requests[0], {blocks:{T1:{COL1:'MB_34ADLAP',COL2:'1',COL3:'0',COL4:'1',COL5:'X'}},parameters:{},offset:0,limit:200});
assert.deepEqual(screen.blkRows, [{col6:'00',col7:'MB_34'}]);
assert.equal(screen.successes.length, 0);
screen.reply = {rows:null,messages:['Adatlap kiválasztása nem történt meg!']};
assert.equal(screen.runAction('T1.PB_LEKERDEZES'), true);
assert.deepEqual(screen.blkRows, [{col6:'00',col7:'MB_34'}]);
assert.equal(screen.warnings.length, 1);
screen.reply = {rows:[],messages:[]};
assert.equal(screen.executeQuery('BLK'), true);
assert.equal(screen.requests.length, 3);
assert.deepEqual(screen.blkRows, []);
assert.equal(screen.warnings.length, 2);
screen.actionEndpoints['T1.OTHER'] = request => {
  screen.requests.push(request);
  return {subscribe: handlers => handlers.next({data:{blocks:{},messages:[]}})};
};
assert.equal(screen.runAction('T1.OTHER'), true);
assert.equal('offset' in screen.requests[3], false);
assert.equal('limit' in screen.requests[3], false);
assert.equal(screen.successes.length, 1);
console.log('typescript query-action OK');
'''.replace('__METHODS__', '\n'.join(methods)).replace('__P__', p))
        run = subprocess.run(['node', '--experimental-strip-types', str(script)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('typescript query-action OK', run.stdout)


if __name__ == '__main__':
    unittest.main()

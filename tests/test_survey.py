"""Felmérés (survey): why endpoints stay disabled, counted over forms and shareable without names."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from niva_forms import survey
from niva_forms.cli import main
from test_screen_windows import simple_windows

ROOT = Path(__file__).resolve().parent
REPLICA = ROOT / 'fixtures' / 'felmeres_replika_fmb.xml'


def replica_variant() -> str:
    """The survey replica with the patterns the approximations count and the replica lacks."""
    xml = REPLICA.read_text(encoding='utf-8')
    cikk = xml[xml.index('<Item Name="CIKK" '):]
    cikk = cikk[:cikk.index('/>') + 2]
    xml = xml.replace(cikk, cikk + '\n   <Item Name="CIKK_NEV" ItemType="Display Item" DataType="Char" MaximumLength="80" '
                      'DatabaseItem="false" Prompt="Cikknév" CanvasName="C" XPosition="260" YPosition="120" Width="100" Height="20"/>', 1)
    pre = '   <Trigger Name="PRE-INSERT" TriggerText="SELECT tetel_seq.NEXTVAL'
    xml = xml.replace(pre, '\n'.join([
        '   <Trigger Name="POST-QUERY" TriggerText="SELECT nev INTO :TETEL.CIKK_NEV FROM cikk WHERE kod = :TETEL.CIKK;"/>',
        '   <Trigger Name="WHEN-VALIDATE-RECORD" TriggerText="IF :TETEL.MENNYISEG &lt; 0 THEN&amp;#10;  RAISE FORM_TRIGGER_FAILURE;'
        '&amp;#10;END IF;"/>',
        '   <Trigger Name="KEY-NEXT-ITEM" TriggerText="cikk_ellenor(:TETEL.CIKK);&amp;#10;NEXT_ITEM;"/>',
        '   <Trigger Name="KEY-NXTBLK" TriggerText="NEXT_BLOCK;"/>', pre]), 1)
    return xml.replace('TriggerText="blokk_frissit;"', 'TriggerText="GO_BLOCK(&apos;TETEL&apos;);&amp;#10;EXECUTE_QUERY;'
                       '&amp;#10;:CTRL.UTOLSO := :TETEL.CIKK;"', 1)


class ShapeTests(unittest.TestCase):
    def test_names_literals_and_comments_become_placeholders(self):
        source = ("BEGIN -- why&#10;  SELECT VEVO_NEV INTO :ORDERS.NAME FROM APP.VEVO WHERE ID = :GLOBAL.CUSTOMER;&#10;"
                  "  IF :SYSTEM.RECORD_STATUS = 'NEW' THEN MESSAGE('Hiányzik a vevő'); END IF;&#10;"
                  "  SET_BLOCK_PROPERTY('ORDERS', DEFAULT_WHERE, 'STATUS = ''A'' AND OWNER = :PARAMETER.P_USER');&#10;"
                  "  X := 123456; END;")
        shape = survey.Shaper().shape(source)
        self.assertEqual(shape, "BEGIN\n"
                                "  SELECT N1 INTO :B1.I1 FROM N2.N3 WHERE N4 = :GLOBAL.G1;\n"
                                "  IF :SYSTEM.RECORD_STATUS = '…' THEN MESSAGE('…'); END IF;\n"
                                "  SET_BLOCK_PROPERTY('…', DEFAULT_WHERE, 'N5 = ''…'' AND N6 = :PARAMETER.P1');\n"
                                "  N7 := N; END;")
        for secret in ('VEVO', 'ORDERS', 'CUSTOMER', 'Hiányzik', 'P_USER', '123456', 'why'):
            self.assertNotIn(secret, shape)
        self.assertIn('VEVO_NEV', survey.Shaper(names=True).shape(source))

    def test_constructs_name_the_forms_calls_and_statements(self):
        found = survey.constructs("BEGIN GO_BLOCK('X'); EXECUTE_QUERY; SELECT A INTO :B.C FROM T; "
                                  "PKG.RUN(1); LOCAL_UNIT; UPDATE T SET A = 1; IF :SYSTEM.MODE = 'X' THEN NULL; END IF; END;")
        self.assertTrue({'GO_BLOCK', 'EXECUTE_QUERY', 'SELECT … INTO', ':blokk.mező', 'csomag.rutin hívása',
                         'saját/ismeretlen rutin hívása', 'UPDATE', ':SYSTEM.MODE'} <= found, found)
        self.assertNotIn('UPDATE', survey.constructs('SELECT A FROM T FOR UPDATE NOWAIT'))

    def test_messages_keep_constructs_but_lose_names(self):
        text = 'Nem támogatott UI hívás: EXECUTE_QUERY; LOV=RG_VEVO a VEVO_TABLA táblán, DEFAULT_WHERE'
        self.assertEqual(survey.scrub(text, False),
                         'Nem támogatott UI hívás: EXECUTE_QUERY; LOV=<név> a <név> táblán, DEFAULT_WHERE')
        self.assertEqual(survey.scrub(text, True), text)


class ApproximationHelperTests(unittest.TestCase):
    def test_a_key_trigger_doing_only_its_default_is_no_difference(self):
        self.assertTrue(survey.default_key('KEY-NXTBLK', 'NEXT_BLOCK;'))
        self.assertTrue(survey.default_key('KEY-COMMIT', 'BEGIN&#10;  commit_form; -- mentés&#10;END;'))
        self.assertFalse(survey.default_key('KEY-COMMIT', "BEGIN IF ank_jog.irhat THEN COMMIT_FORM; END IF; END;"))
        self.assertFalse(survey.default_key('KEY-NEXT-ITEM', 'ellenor(:B.I); NEXT_ITEM;'))
        self.assertFalse(survey.default_key('KEY-EXIT', 'NULL;'))  # the key no longer exits: a difference

    def test_mid_code_steps_come_from_the_generator_reasons(self):
        reasons = ['Átfuttatás az adatbázisban sem lehetséges: EXECUTE_QUERY után további adat- vagy mezőművelet '
                   'következik (:B.I): a webes képernyő a EXECUTE_QUERY lépést a kód végén hajtja végre.',
                   'COMMIT_FORM a kód közepén: GOTO a kódban.', None,
                   'CLEAR_BLOCK a DO_KEY-val beágyazott KEY-trigger kódjában: a DO_KEY után további kód következik.']
        self.assertEqual(survey.mid_code_steps(reasons), {'EXECUTE_QUERY', 'COMMIT_FORM', 'CLEAR_BLOCK'})
        self.assertEqual(survey.mid_code_steps(['Nem támogatott UI hívás: EXECUTE_QUERY']), set())

    def test_records_displayed(self):
        self.assertEqual(survey.records_displayed({'properties': {'recordsdisplaycount': '5'}}), 5)
        self.assertEqual(survey.records_displayed({'properties': {'numberofrecordsdisplayed': '10'}}), 10)
        self.assertEqual(survey.records_displayed({'properties': {'recordsdisplaycount': ''}}), 1)


class ApproximationRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / 'forms').mkdir()
        (root / 'forms' / 'valtozat_fmb.xml').write_text(replica_variant(), encoding='utf-8')
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            assert main(['survey', str(root / 'forms'), '--out', str(root / 'out')]) == 0, errors.getvalue()
        cls.report = json.loads((root / 'out' / 'felmeres.json').read_text(encoding='utf-8'))
        cls.text = (root / 'out' / 'FELMERES_HU.md').read_text(encoding='utf-8')
        cls.rows = {r['kind']: r for r in cls.report['approximations']}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_kind_is_counted(self):
        self.assertEqual(self.report['survey_version'], 2)
        self.assertEqual(set(self.rows), set(survey.APPROXIMATIONS))
        counts = {kind: row['count'] for kind, row in self.rows.items()}
        self.assertEqual(counts, {'multi_record_write': 2, 'item_validation': 2, 'record_validation': 1, 'data_key': 3,
                                  'other_key': 1, 'mid_code_step': 1, 'on_error': 1, 'post_query_rows': 1})
        self.assertEqual(self.report['totals']['multi_record_blocks'], 2)

    def test_details_say_what_to_fix_first(self):
        self.assertEqual(self.rows['multi_record_write']['details'].get('részletblokk'), 1)
        self.assertEqual(self.rows['item_validation']['details'].get('többsoros blokkon'), 1)
        self.assertEqual(self.rows['data_key']['details'], {'KEY-COMMIT': 1, 'KEY-EXEQRY': 1, 'KEY-CREREC': 1})
        self.assertEqual(self.rows['other_key']['details'], {'KEY-NEXT-ITEM': 1})  # KEY-NXTBLK only does NEXT_BLOCK
        self.assertEqual(self.rows['mid_code_step']['details'], {'EXECUTE_QUERY': 1})
        self.assertEqual(self.rows['post_query_rows']['details'], {'SELECT … INTO (kikeresés)': 1})
        events = [e['event'] for row in self.rows.values() for e in row['examples']]
        self.assertNotIn('KEY-EXIT', events)  # qms$ framework call only
        self.assertNotIn('KEY-NXTBLK', events)

    def test_the_section_is_shareable(self):
        section = self.text[self.text.index('## Eltérések a Forms-működéstől'):self.text.index('## Okok a tiltott')]
        self.assertIn('| K1 |', section)
        self.assertIn('- **Javítás:**', section)
        self.assertIn('Többsoros adatbázis-blokk összesen: 2, ebből írható: 2.', section)
        self.assertIn('SELECT N1 INTO :B1.I1 FROM N2 WHERE N3 = :B1.I2;', section)  # the POST-QUERY lookup, anonymised
        for secret in ('CIKK', 'TETEL', 'RENDELES', 'cikk_ellenor', 'hiba_kezelo', 'ank_', 'UTOLSO', 'Túl nagy'):
            self.assertNotIn(secret, section)


class SurveyRunTests(unittest.TestCase):
    def test_survey_command_measures_every_form_without_questions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            forms = root / 'forms'
            forms.mkdir()
            (forms / 'headstart.xml').write_bytes((ROOT / 'golden/headstart/input.xml').read_bytes())
            (forms / 'windows.xml').write_text(simple_windows())  # two possible main windows: no question in a survey
            out = root / 'out'
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                code = main(['survey', str(forms), '--out', str(out)])
            self.assertEqual(code, 0, errors.getvalue())
            report = json.loads((out / 'felmeres.json').read_text(encoding='utf-8'))
            text = (out / 'FELMERES_HU.md').read_text(encoding='utf-8')
            self.assertEqual(report['totals']['forms'], 2)
            self.assertEqual(report['totals'].get('failed', 0), 0)
            totals = report['totals']
            self.assertEqual(totals['endpoints'], totals.get('enabled', 0) + totals.get('ready', 0) + totals.get('blocked', 0))
            self.assertTrue(report['causes'])
            for cause in report['causes']:
                self.assertLessEqual(cause['sole'], cause['endpoints'])
                self.assertNotEqual(cause['code'], 'WRITE_APPROVAL')  # backend_live, as on the web
            self.assertIn('Okok a tiltott végpontok szerint', text)
            for secret in ('FRM_ANK_TESZT', 'AIT_MEGJ', 'ANY_MODULE'):
                self.assertNotIn(secret, text)
            self.assertTrue((out / 'PORTFOLIO_HU.md').is_file())
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['survey', '--out', str(out), '--report-only', '--names']), 0)
            named = (out / 'FELMERES_HU.md').read_text(encoding='utf-8')
            self.assertIn('valódi neveket', named)
            self.assertIn('AIT', named)


if __name__ == '__main__':
    unittest.main()

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

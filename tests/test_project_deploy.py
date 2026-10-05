"""Generated files straight into the developer's project: CL, DPS, WBS and the frontend in their own folders.

A fake company project (rendszer-cl, rendszer-dps, rendszer-wbs, rendszer-ui with angular.json) stands in
for the developer's main folder. The generated replica module is deployed into it: every Java file under
its package in the right project, the screens next to each other in the Angular app, CREATE_ONCE files
never overwritten, files changed in the project reported instead of overwritten. The parts can also be
chosen one by one, anywhere, without a main folder (the web UI's "Tallózás…" buttons): the folder browser
and the operating system's folder dialog (a fake dialog process here) are tested with the web API.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest

from java_support import COMPANY_IMPORTS
from frm_forms.cli import main
from frm_forms.common import MigrationError
from frm_forms.project_deploy import MANIFEST, deploy, map_project, markdown, parse_layout

ROOT = Path(__file__).resolve().parents[1]
REPLICA = ROOT / 'tests' / 'fixtures' / 'felmeres_replika_fmb.xml'


def company_project(root: Path, name='rendszer') -> Path:
    for layer in ('cl', 'dps', 'wbs'):
        (root / f'{name}-{layer}/src/main/java/hu/company/features').mkdir(parents=True)
    ui = root / f'{name}-ui'
    (ui / 'src/app/meglevo').mkdir(parents=True)
    (ui / 'node_modules/some-lib/src/main/java').mkdir(parents=True)  # never a candidate
    (ui / 'angular.json').write_text(json.dumps({'projects': {name: {'projectType': 'application', 'sourceRoot': 'src'}}}))
    return root


def generate(out: Path, extra=None, awu='1234') -> Path:
    config = out.parent / (out.name + '.json')
    config.write_text(json.dumps({'java_company_imports': COMPANY_IMPORTS, 'backend_live': True,
                                  'screen_window_selection': 'all', 'screen_primary_window_auto': True, **(extra or {})}))
    args = ['migrate', str(REPLICA), '--out', str(out), '--screen', '--module', 'rendeles', '--config', str(config)]
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(args + (['--awu-azon', awu] if awu else [])) == 0
    return out


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = company_project(Path(self.temp.name) / 'projekt')

    def test_the_parts_are_found_by_their_folders(self):
        mapped = map_project(self.root)
        self.assertEqual(mapped['CL'], self.root / 'rendszer-cl/src/main/java')
        self.assertEqual(mapped['DPS'], self.root / 'rendszer-dps/src/main/java')
        self.assertEqual(mapped['WBS'], self.root / 'rendszer-wbs/src/main/java')
        self.assertEqual(mapped['frontend'], self.root / 'rendszer-ui/src/app')
        self.assertNotIn('rendszer-ui/node_modules/some-lib/src/main/java', mapped['candidates']['java'])

    def test_the_screens_of_earlier_deploys_set_the_frontend_folder(self):
        (self.root / 'rendszer-ui/src/app/kepernyok').mkdir()
        (self.root / 'rendszer-ui/src/app/kepernyok/frm-forms-screen.ts').write_text('// v2')
        self.assertEqual(map_project(self.root)['frontend'], self.root / 'rendszer-ui/src/app/kepernyok')

    def test_ambiguity_asks_for_the_folder_and_the_layout_settles_it(self):
        (self.root / 'masik-dps/src/main/java').mkdir(parents=True)
        with self.assertRaisesRegex(MigrationError, '--layout DPS='):
            map_project(self.root)
        mapped = map_project(self.root, parse_layout(['DPS=masik-dps/src/main/java']))
        self.assertEqual(mapped['DPS'], self.root / 'masik-dps/src/main/java')
        with self.assertRaisesRegex(MigrationError, 'nem létezik'):
            map_project(self.root, {'DPS': '../kivul'})
        with self.assertRaisesRegex(MigrationError, 'KULCS=MAPPA'):
            parse_layout(['BACKEND=x'])

    def test_parts_chosen_one_by_one_anywhere_without_a_main_folder(self):
        elsewhere = company_project(Path(self.temp.name) / 'mashol', 'masik')
        mapped = map_project(None, {'CL': str(self.root / 'rendszer-cl'),  # a Java project folder: its src/main/java
                                    'DPS': str(elsewhere / 'masik-dps/src/main/java'),
                                    'WBS': str(self.root / 'rendszer-wbs/src/main/java/hu/company'),  # a package in it
                                    'frontend': str(elsewhere / 'masik-ui')})  # the Angular project: its screens folder
        self.assertIsNone(mapped['root'])
        self.assertEqual(mapped['CL'], self.root / 'rendszer-cl/src/main/java')
        self.assertEqual(mapped['DPS'], elsewhere / 'masik-dps/src/main/java')
        self.assertEqual(mapped['WBS'], self.root / 'rendszer-wbs/src/main/java')
        self.assertEqual(mapped['frontend'], elsewhere / 'masik-ui/src/app')
        self.assertEqual(mapped['home'], {'CL': self.root / 'rendszer-cl', 'DPS': elsewhere / 'masik-dps',
                                          'WBS': self.root / 'rendszer-wbs', 'frontend': elsewhere / 'masik-ui'})
        only_dps = map_project(None, {'DPS': str(elsewhere / 'masik-dps')})
        self.assertIsNone(only_dps['CL'])
        # a chosen part beside the found ones
        mixed = map_project(self.root, {'DPS': str(elsewhere / 'masik-dps')})
        self.assertEqual(mixed['DPS'], elsewhere / 'masik-dps/src/main/java')
        self.assertEqual(mixed['CL'], self.root / 'rendszer-cl/src/main/java')

    def test_wrong_part_folders_are_refused(self):
        with self.assertRaisesRegex(MigrationError, 'fő projektmappát, vagy legalább egy rész'):
            map_project(None, {})
        with self.assertRaisesRegex(MigrationError, 'teljes útvonallal'):
            map_project(None, {'DPS': 'rendszer-dps'})
        with self.assertRaisesRegex(MigrationError, 'nem mappa'):
            map_project(None, {'frontend': str(self.root / 'rendszer-ui/angular.json')})
        with self.assertRaisesRegex(MigrationError, 'nem létezik'):
            map_project(None, {'DPS': str(self.root / 'rendszer-dps/uj')})  # a Java part is never created
        with self.assertRaisesRegex(MigrationError, 'nem létezik'):
            map_project(None, {'frontend': str(self.root / 'nincs/kepernyok')})
        # a new screens folder in the Angular project: the first deploy creates it
        new = map_project(None, {'frontend': str(self.root / 'rendszer-ui/src/app/kepernyok')})
        self.assertEqual(new['frontend'], self.root / 'rendszer-ui/src/app/kepernyok')
        self.assertEqual(new['home']['frontend'], self.root / 'rendszer-ui')

    def test_company_classes_tell_a_layer_without_a_telling_folder_name(self):
        other = Path(self.temp.name) / 'egyeb'
        (other / 'szolgaltatas/src/main/java/hu/x').mkdir(parents=True)
        (other / 'szolgaltatas/src/main/java/hu/x/A.java').write_text('class A extends Base<DpsLogHelper> {}')
        (other / 'kliens/src/main/java/hu/y').mkdir(parents=True)
        (other / 'kliens/src/main/java/hu/y/B.java').write_text('class B extends DataProviderServiceRestClientBase {}')
        (other / 'semmi/src/main/java/hu/z').mkdir(parents=True)
        self.assertEqual(map_project(other)['DPS'], other / 'szolgaltatas/src/main/java')
        self.assertEqual(map_project(other)['CL'], other / 'kliens/src/main/java')
        self.assertIsNone(map_project(other)['WBS'])


class DeployTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('FRM_JAVA_IMPORT_MAP', '-')
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        cls.output = generate(base / 'out')
        cls.empty_package = generate(base / 'out-web', {'java_empty_package': True})

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = company_project(Path(self.work.name) / 'projekt')

    def statuses(self, report):
        return {f['source']: f['status'] for f in report['files']}

    def test_every_file_lands_in_its_own_project_under_its_package(self):
        report = deploy([self.output], self.root)
        self.assertEqual(set(report['counts']), {'new'})
        dps = self.root / 'rendszer-dps/src/main/java/hu/company/features/rendeles/dps'
        self.assertIn('public class RendelesServiceImpl extends RendelesServiceBase {',
                      (dps / 'RendelesServiceImpl.java').read_text(encoding='utf-8'))
        self.assertTrue((dps / 'RendelesServiceBase.java').is_file())
        self.assertTrue((self.root / 'rendszer-wbs/src/main/java/hu/company/features/rendeles/wbs/RendelesServiceImpl.java').is_file())
        self.assertTrue((self.root / 'rendszer-cl/src/main/java/hu/company/features/rendeles/cl/RendelesConstants.java').is_file())
        self.assertTrue((self.root / 'rendszer-cl/src/main/java/hu/company/features/cl/CommonMigrateTools.java').is_file())
        app = self.root / 'rendszer-ui/src/app'
        self.assertTrue((app / 'frm-forms-screen.ts').is_file())
        self.assertTrue((app / 'rendeles/rendeles.component.ts').is_file())
        self.assertFalse(list(self.root.rglob('*.md')))  # reports and notes stay in the output
        # the last deploy's hashes: in each part's project folder
        self.assertFalse((self.root / MANIFEST).exists())
        ui = json.loads((self.root / 'rendszer-ui' / MANIFEST).read_text(encoding='utf-8'))
        self.assertIn('src/app/frm-forms-screen.ts', ui['files'])
        dps_manifest = json.loads((self.root / 'rendszer-dps' / MANIFEST).read_text(encoding='utf-8'))
        self.assertIn('src/main/java/hu/company/features/rendeles/dps/RendelesServiceImpl.java', dps_manifest['files'])
        files = {f['source']: f for f in report['files']}
        self.assertEqual(files['backend/DPS/RendelesServiceImpl.java']['display'],
                         'DPS: src/main/java/hu/company/features/rendeles/dps/RendelesServiceImpl.java')
        self.assertEqual(files['backend/DPS/RendelesServiceImpl.java']['target'], str(dps / 'RendelesServiceImpl.java'))
        self.assertEqual(report['layout']['DPS'], str(self.root / 'rendszer-dps/src/main/java'))
        self.assertIn('Telepítés a projektbe', markdown(report))

    def test_redeploy_updates_ours_keeps_create_once_and_reports_foreign_changes(self):
        deploy([self.output], self.root)
        self.assertEqual(set(deploy([self.output], self.root)['counts']), {'unchanged'})
        cl = self.root / 'rendszer-cl/src/main/java/hu/company/features/rendeles/cl/RendelesConstants.java'
        impl = self.root / 'rendszer-dps/src/main/java/hu/company/features/rendeles/dps/RendelesServiceImpl.java'
        impl.write_text(impl.read_text(encoding='utf-8') + '\n// kézi folytatás\n', encoding='utf-8')
        cl.write_text(cl.read_text(encoding='utf-8') + '\n// kézi módosítás\n', encoding='utf-8')
        report = deploy([self.output], self.root)
        statuses = self.statuses(report)
        self.assertEqual(statuses['backend/DPS/RendelesServiceImpl.java'], 'kept')
        self.assertEqual(statuses['backend/CL/RendelesConstants.java'], 'conflict')
        self.assertIn('// kézi folytatás', impl.read_text(encoding='utf-8'))
        self.assertIn('// kézi módosítás', cl.read_text(encoding='utf-8'))  # not overwritten
        forced = self.statuses(deploy([self.output], self.root, force=True))
        self.assertEqual(forced['backend/CL/RendelesConstants.java'], 'overwritten')
        self.assertEqual(forced['backend/DPS/RendelesServiceImpl.java'], 'kept')  # never, not even with force
        self.assertNotIn('// kézi módosítás', cl.read_text(encoding='utf-8'))

    def test_a_new_generation_updates_the_files_of_the_last_deploy(self):
        deploy([self.output], self.root)
        work = Path(self.work.name) / 'out'
        shutil.copytree(self.output, work)
        constants = work / 'backend/CL/RendelesConstants.java'
        constants.write_text(constants.read_text(encoding='utf-8').replace('listrendeles', 'listrendeles2'), encoding='utf-8')
        report = deploy([work], self.root)
        self.assertEqual(self.statuses(report)['backend/CL/RendelesConstants.java'], 'updated')
        self.assertIn('listrendeles2', (self.root / 'rendszer-cl/src/main/java/hu/company/features/rendeles/cl/'
                                                    'RendelesConstants.java').read_text(encoding='utf-8'))

    def test_dry_run_writes_nothing(self):
        report = deploy([self.output], self.root, dry_run=True)
        self.assertEqual(set(report['counts']), {'new'})
        self.assertFalse(list(self.root.rglob(MANIFEST)))
        self.assertFalse((self.root / 'rendszer-ui/src/app/frm-forms-screen.ts').exists())

    def test_parts_chosen_one_by_one_get_their_files_without_a_main_folder(self):
        elsewhere = company_project(Path(self.work.name) / 'mashol', 'masik')
        layout = {'CL': str(self.root / 'rendszer-cl'), 'DPS': str(elsewhere / 'masik-dps'),
                  'WBS': str(self.root / 'rendszer-wbs/src/main/java'), 'frontend': str(elsewhere / 'masik-ui/src/app/kepernyok')}
        report = deploy([self.output], None, layout)
        self.assertIsNone(report['project'])
        self.assertEqual(set(report['counts']), {'new'})
        self.assertTrue((elsewhere / 'masik-dps/src/main/java/hu/company/features/rendeles/dps/RendelesServiceImpl.java').is_file())
        self.assertTrue((self.root / 'rendszer-wbs/src/main/java/hu/company/features/rendeles/wbs/RendelesServiceImpl.java').is_file())
        self.assertTrue((elsewhere / 'masik-ui/src/app/kepernyok/rendeles/rendeles.component.ts').is_file())
        self.assertFalse((self.root / 'rendszer-dps/src/main/java/hu/company/features/rendeles').exists())
        ui = json.loads((elsewhere / 'masik-ui' / MANIFEST).read_text(encoding='utf-8'))
        self.assertIn('src/app/kepernyok/frm-forms-screen.ts', ui['files'])
        self.assertNotIn('Fő projektmappa', markdown(report))
        self.assertEqual(set(deploy([self.output], None, layout)['counts']), {'unchanged'})

    def test_the_hashes_of_a_4_16_deploy_still_tell_our_files_from_changed_ones(self):
        deploy([self.output], self.root)
        legacy = {}
        for part in ('rendszer-cl', 'rendszer-dps', 'rendszer-wbs', 'rendszer-ui'):
            own = self.root / part / MANIFEST
            for rel, entry in json.loads(own.read_text(encoding='utf-8'))['files'].items():
                legacy[part + '/' + rel] = entry
            own.unlink()
        (self.root / MANIFEST).write_text(json.dumps({'generator': 'frm-forms-migrator', 'files': legacy}), encoding='utf-8')
        work = Path(self.work.name) / 'out'
        shutil.copytree(self.output, work)
        constants = work / 'backend/CL/RendelesConstants.java'
        constants.write_text(constants.read_text(encoding='utf-8').replace('listrendeles', 'listrendeles2'), encoding='utf-8')
        report = deploy([work], self.root)
        self.assertEqual(self.statuses(report)['backend/CL/RendelesConstants.java'], 'updated')
        self.assertTrue((self.root / 'rendszer-cl' / MANIFEST).is_file())

    def test_a_file_generated_without_package_gets_the_package_of_its_imports(self):
        source = (self.empty_package / 'backend/DPS/RendelesServiceBase.java').read_text(encoding='utf-8')
        self.assertNotIn('package ', source.split('\n', 1)[0])
        deploy([self.empty_package], self.root)
        placed = (self.root / 'rendszer-dps/src/main/java/hu/company/features/rendeles/dps/RendelesServiceBase.java')
        self.assertTrue(placed.read_text(encoding='utf-8').startswith('package hu.company.features.rendeles.dps;\n\n'))
        constants = self.root / 'rendszer-cl/src/main/java/hu/company/features/rendeles/cl/RendelesConstants.java'
        self.assertTrue(constants.read_text(encoding='utf-8').startswith('package hu.company.features.rendeles.cl;'))

    def test_a_missing_part_skips_its_files_and_a_symlink_is_never_followed(self):
        shutil.rmtree(self.root / 'rendszer-wbs')
        outside = Path(self.work.name) / 'kivul'
        outside.mkdir()
        target = self.root / 'rendszer-dps/src/main/java/hu/company/features'
        shutil.rmtree(target)
        try:
            target.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlink nem hozható létre')
        report = deploy([self.output], self.root)
        files = {f['source']: f for f in report['files']}
        self.assertEqual(files['backend/WBS/RendelesServiceImpl.java']['status'], 'skipped')
        self.assertIn('nincs WBS mappa', files['backend/WBS/RendelesServiceImpl.java']['reason'])
        self.assertEqual(files['backend/DPS/RendelesServiceImpl.java']['status'], 'skipped')
        self.assertFalse(list(outside.rglob('*.java')))

    def test_cli_deploy_and_migrate_with_project(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(['deploy', str(self.output), '--project', str(self.root), '--dry-run']), 0)
        self.assertTrue(json.loads(stdout.getvalue())['dry_run'])
        self.assertTrue((self.output / 'PROJECT_DEPLOY_HU.md').is_file())
        config = Path(self.work.name) / 'c.json'
        config.write_text(json.dumps({'java_company_imports': COMPANY_IMPORTS, 'backend_live': True,
                                      'screen_window_selection': 'all', 'screen_primary_window_auto': True,
                                      'project_layout': {'frontend': 'rendszer-ui/src/app/kepernyok'}}))
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(['migrate', str(REPLICA), '--out', str(Path(self.work.name) / 'kozvetlen'), '--screen',
                         '--module', 'rendeles', '--config', str(config), '--awu-azon', '1234', '--project', str(self.root)])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / 'rendszer-ui/src/app/kepernyok/rendeles/rendeles.component.ts').is_file())
        self.assertTrue((self.root / 'rendszer-dps/src/main/java/hu/company/features/rendeles/dps/RendelesServiceBase.java').is_file())

    def test_cli_deploy_into_chosen_parts_without_project(self):
        elsewhere = company_project(Path(self.work.name) / 'mashol', 'masik')
        args = ['deploy', str(self.output), '--layout', 'DPS=' + str(elsewhere / 'masik-dps'),
                '--layout', 'frontend=' + str(elsewhere / 'masik-ui')]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(args)
        self.assertEqual(code, 3)  # CL and WBS were not chosen: their files are skipped
        self.assertIsNone(json.loads(stdout.getvalue())['project'])
        self.assertTrue((elsewhere / 'masik-dps/src/main/java/hu/company/features/rendeles/dps/RendelesServiceImpl.java').is_file())
        self.assertTrue((elsewhere / 'masik-ui/src/app/rendeles/rendeles.component.ts').is_file())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(main(['deploy', str(self.output)]), 1)
        self.assertIn('fő projektmappát, vagy legalább egy rész', stderr.getvalue())


try:
    from fastapi.testclient import TestClient
    from frm_forms.web.app import create_app
    from frm_forms.web.settings import Settings
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

HEADERS = {'Origin': 'http://localhost:4200', 'X-Frm-Client': 'local-ui'}


@unittest.skipUnless(WEB_AVAILABLE, 'Web API tesztekhez: pip install -r requirements-test.txt')
class WebDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.project = company_project(base / 'projekt')
        self.settings = Settings(data_dir=base / 'data')
        self.client = TestClient(create_app(self.settings), base_url='http://localhost:8000')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def completed_job(self):
        options = {'module': 'rendeles', 'screen_window_selection': 'all', 'screen_primary_window_auto': True}
        files = {'file': ('felmeres_replika_fmb.xml', REPLICA.read_bytes(), 'application/octet-stream')}
        response = self.client.post('/api/jobs', files=files, data={'options': json.dumps(options)}, headers=HEADERS)
        self.assertEqual(response.status_code, 202, response.text)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.client.get('/api/jobs/' + response.json()['id']).json()
            if job['status'] in {'completed', 'failed', 'cancelled', 'interrupted', 'needs_input'}:
                self.assertEqual(job['status'], 'completed', job)
                return job
            time.sleep(0.05)
        self.fail('A feladat nem fejeződött be.')

    def test_preview_then_deploy_into_the_project(self):
        job = self.completed_job()
        url = '/api/jobs/' + job['id'] + '/deploy'
        preview = self.client.post(url, json={'project': str(self.project)}, headers=HEADERS)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()['dry_run'])
        self.assertEqual(preview.json()['layout']['DPS'], str(self.project / 'rendszer-dps/src/main/java'))
        self.assertFalse(list(self.project.rglob(MANIFEST)))
        done = self.client.post(url, json={'project': str(self.project), 'dry_run': False}, headers=HEADERS)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertIn('new', done.json()['counts'])
        self.assertTrue((self.project / 'rendszer-ui/src/app/rendeles/rendeles.component.ts').is_file())
        # web jobs generate without package lines: the deploy writes the package of the imports
        placed = next((self.project / 'rendszer-dps/src/main/java').rglob('RendelesServiceImpl.java'))
        self.assertTrue(placed.read_text(encoding='utf-8').startswith('package '))
        self.assertIn('Telepítés a projektbe', done.json()['markdown'])

    def test_parts_chosen_one_by_one_without_a_main_folder(self):
        job = self.completed_job()
        url = '/api/jobs/' + job['id'] + '/deploy'
        layout = {'CL': str(self.project / 'rendszer-cl'), 'DPS': str(self.project / 'rendszer-dps'),
                  'WBS': str(self.project / 'rendszer-wbs'), 'frontend': str(self.project / 'rendszer-ui')}
        done = self.client.post(url, json={'project': '', 'layout': layout, 'dry_run': False}, headers=HEADERS)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertIsNone(done.json()['project'])
        self.assertEqual(done.json()['layout']['frontend'], str(self.project / 'rendszer-ui/src/app'))
        self.assertEqual(set(done.json()['counts']), {'new'})
        self.assertTrue(any(f['display'].startswith('DPS: src/main/java/') for f in done.json()['files']))
        self.assertTrue((self.project / 'rendszer-ui/src/app/rendeles/rendeles.component.ts').is_file())

    def test_relative_paths_and_folders_outside_the_allowed_roots_are_refused(self):
        job = self.completed_job()
        url = '/api/jobs/' + job['id'] + '/deploy'
        self.assertEqual(self.client.post(url, json={'project': 'projekt'}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.post(url, json={'project': str(self.project), 'layout': {'X': 'y'}},
                                          headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.post(url, json={'layout': {'DPS': 'rendszer-dps'}}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.post(url, json={'project': ' ', 'layout': {'DPS': ''}}, headers=HEADERS).status_code, 422)
        self.settings.project_roots = [str(Path(self.temp.name) / 'mas')]
        self.assertEqual(self.client.post(url, json={'project': str(self.project)}, headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.post(url, json={'layout': {'DPS': str(self.project / 'rendszer-dps')}},
                                          headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.post(url, json={'project': str(self.project)}).status_code, 403)  # no client header
        self.settings.project_roots = [str(self.project / 'rendszer-dps')]
        allowed = self.client.post(url, json={'layout': {'DPS': str(self.project / 'rendszer-dps')}}, headers=HEADERS)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        outside = self.client.post(url, json={'layout': {'DPS': str(self.project / 'rendszer-dps'),
                                                         'WBS': str(self.project / 'rendszer-wbs')}}, headers=HEADERS)
        self.assertEqual(outside.status_code, 403)
        # a package folder means its src/main/java (and the manifest above it): checked where it is really written
        self.settings.project_roots = [str(self.project / 'rendszer-dps/src/main/java/hu')]
        package = self.client.post(url, json={'layout': {'DPS': str(self.project / 'rendszer-dps/src/main/java/hu/company')}},
                                   headers=HEADERS)
        self.assertEqual(package.status_code, 403)


@unittest.skipUnless(WEB_AVAILABLE, 'Web API tesztekhez: pip install -r requirements-test.txt')
class FolderBrowsingTests(unittest.TestCase):
    """The "Tallózás…" buttons: the in-page folder browser and the operating system's folder dialog."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = company_project(self.base / 'projekt')
        (self.project / '.git').mkdir()

    def client(self, **settings):
        self.servers = getattr(self, 'servers', 0) + 1  # one work folder per server (its lock)
        self.settings = Settings(data_dir=self.base / ('data' + str(self.servers)), **settings)
        client = TestClient(create_app(self.settings), base_url='http://localhost:8000')
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def fake_dialog(self, code):
        return [sys.executable, '-c', code]

    def test_the_folder_browser_lists_subfolders_and_marks_the_projects(self):
        client = self.client()
        start = client.post('/api/fs/folders', json={}, headers=HEADERS)
        self.assertEqual(start.status_code, 200, start.text)
        self.assertIsNone(start.json()['path'])
        self.assertIn(str(Path.home()), [f['path'] for f in start.json()['folders']])
        listed = client.post('/api/fs/folders', json={'path': str(self.project)}, headers=HEADERS).json()
        self.assertEqual(listed['path'], str(self.project))
        self.assertEqual(listed['parent'], str(self.base))
        kinds = {f['name']: f['kind'] for f in listed['folders']}
        self.assertEqual(kinds, {'rendszer-cl': 'java', 'rendszer-dps': 'java', 'rendszer-ui': 'angular',
                                 'rendszer-wbs': 'java'})  # sorted, without .git
        self.assertEqual([f['name'] for f in listed['folders']], sorted(kinds))
        self.assertEqual(client.post('/api/fs/folders', json={'path': 'projekt'}, headers=HEADERS).status_code, 422)
        self.assertEqual(client.post('/api/fs/folders', json={'path': str(self.base / 'nincs')}, headers=HEADERS).status_code, 404)
        self.assertEqual(client.post('/api/fs/folders', json={'path': str(self.project)}).status_code, 403)  # no client header

    def test_the_allowed_roots_limit_the_browser(self):
        client = self.client(project_roots=[str(self.project)])
        start = client.post('/api/fs/folders', json={}, headers=HEADERS).json()
        self.assertEqual([f['path'] for f in start['folders']], [str(self.project)])
        self.assertIsNone(client.post('/api/fs/folders', json={'path': str(self.project)}, headers=HEADERS).json()['parent'])
        self.assertEqual(client.post('/api/fs/folders', json={'path': str(self.base)}, headers=HEADERS).status_code, 403)

    def test_the_folder_dialog_returns_the_chosen_folder(self):
        chosen = self.project / 'rendszer-dps'
        client = self.client(folder_dialog_command=self.fake_dialog(
            'import sys; assert sys.argv[1] == "DPS"; sys.stdout.buffer.write(%r.encode())' % chosen.as_posix()))
        picked = client.post('/api/fs/pick', json={'title': 'DPS', 'initial': str(self.project)}, headers=HEADERS)
        self.assertEqual(picked.status_code, 200, picked.text)
        self.assertEqual(picked.json(), {'path': str(chosen), 'cancelled': False, 'kind': 'java'})
        self.settings.project_roots = [str(self.project / 'rendszer-ui')]
        self.assertEqual(client.post('/api/fs/pick', json={'title': 'DPS'}, headers=HEADERS).status_code, 403)

    def test_a_closed_dialog_and_a_machine_without_dialog(self):
        cancelled = self.client(folder_dialog_command=self.fake_dialog('pass'))
        self.assertEqual(cancelled.post('/api/fs/pick', json={}, headers=HEADERS).json(), {'path': None, 'cancelled': True})
        missing = self.client(folder_dialog_command=self.fake_dialog('import sys; sys.exit(4)'))
        self.assertEqual(missing.post('/api/fs/pick', json={}, headers=HEADERS).status_code, 501)
        switched_off = self.client(folder_dialog=False)
        self.assertEqual(switched_off.post('/api/fs/pick', json={}, headers=HEADERS).status_code, 501)
        self.assertFalse(switched_off.get('/api/defaults').json()['folders']['dialog'])

    def test_one_dialog_at_a_time_and_the_ui_can_close_it(self):
        opened = self.base / 'opened'
        client = self.client(folder_dialog_command=self.fake_dialog(
            'import pathlib, time; pathlib.Path(%r).touch(); time.sleep(60)' % str(opened)))
        result = {}
        waiting = threading.Thread(target=lambda: result.update(response=client.post('/api/fs/pick', json={}, headers=HEADERS)))
        waiting.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not opened.exists():
            time.sleep(0.05)
        self.assertTrue(opened.exists())
        self.assertEqual(client.post('/api/fs/pick', json={}, headers=HEADERS).status_code, 409)
        self.assertEqual(client.post('/api/fs/pick/cancel', headers=HEADERS).json(), {'cancelled': True})
        waiting.join(15)
        self.assertEqual(result['response'].json(), {'path': None, 'cancelled': True})
        self.assertEqual(client.post('/api/fs/pick/cancel', headers=HEADERS).json(), {'cancelled': False})


if __name__ == '__main__':
    unittest.main()

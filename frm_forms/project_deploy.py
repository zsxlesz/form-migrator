"""Generated files straight into the developer's project: CL, DPS, WBS and the frontend in their own folders.

map_project() looks over a project root that holds the four parts (each in its own folder):
  - the Java source roots (.../src/main/java) of the CL, DPS and WBS projects: by the folder name
    (…-cl, …-dps, …-wbs), then by the packages and company classes found in them;
  - the Angular project (angular.json) and its folder of screens: where frm-forms-screen.ts already is,
    else <sourceRoot>/app.
project_layout (config) or --layout KEY=PATH names any of them explicitly (relative to the root).

deploy() places every generated file of migrate outputs:
  - Java: by its package under the layer's source root. A file generated without package line (web:
    java_empty_package) gets the package the generator used for its imports, so it compiles in place;
  - frontend: under the screens folder, with the output's relative path (frm-forms-screen.ts, <module>/...).
Generated files are overwritten; CREATE_ONCE files (ServiceImpl, ControllerImpl, the component) are written
only when they do not exist yet - the fresh version stays in the output. A generated file changed in the
project since the last deploy (.frm-deploy.json keeps the hashes), or a foreign file of the same name, is
not overwritten unless force: it is reported as a conflict. Nothing is written outside the root and no
symlink is followed. dry_run: the plan only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .common import MigrationError

LAYERS = ('CL', 'DPS', 'WBS')
LAYOUT_KEYS = set(LAYERS) | {'frontend'}
MANIFEST = '.frm-deploy.json'
SKIP_DIRS = {'node_modules', 'target', 'build', 'dist', 'out', 'bin', 'obj', 'coverage', 'tmp', 'temp', 'venv',
             '__pycache__', 'local-data'}
MAX_DEPTH = 8
FRONTEND_TOKENS = {'frontend', 'front', 'fe', 'ui', 'web', 'angular', 'client'}
CONTENT_MARKERS = {'DPS': ('DpsLogHelper',), 'WBS': ('WbsLogHelper', 'WbsServiceBase', 'WbsControllerBase'),
                   'CL': ('DataProviderServiceRestClientBase', 'CommonMigrateTools')}
DOCUMENTS = {'.md', '.txt'}
STATUS_TEXT = {'new': 'új', 'updated': 'frissítve', 'unchanged': 'változatlan', 'kept': 'megőrizve (CREATE_ONCE)',
               'conflict': 'ütközés (nem írtuk felül)', 'overwritten': 'felülírva (force)', 'skipped': 'kihagyva'}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tokens(path: Path) -> set[str]:
    return {t for t in re.split(r'[^a-z0-9]+', path.as_posix().lower()) if t}


def walk(root: Path):
    """(directory, subdirectory names, file names) under root: no hidden, build or dependency folders, no symlinks."""
    for current, directories, files in os.walk(root, followlinks=False):
        here = Path(current)
        depth = len(here.relative_to(root).parts)
        directories[:] = [] if depth >= MAX_DEPTH else sorted(
            d for d in directories if d not in SKIP_DIRS and not d.startswith('.') and not (here / d).is_symlink())
        yield here, directories, files


def layer_scores(root: Path, java_root: Path) -> dict[str, int]:
    """How much a Java source root looks like the CL, DPS or WBS project."""
    project = java_root.parents[2] if len(java_root.parts) >= 3 else java_root
    names = tokens(project.relative_to(root)) if project != root else set()
    scores = {layer: (10 if layer.lower() in names else 0) for layer in LAYERS}
    packages, seen = {layer: 0 for layer in LAYERS}, 0
    for current, directories, files in walk(java_root):
        name = current.name.lower()
        for layer in LAYERS:
            if name == layer.lower():
                packages[layer] += 1
        for file in files:
            if not file.endswith('.java') or seen >= 400:
                continue
            seen += 1
            try:
                text = (current / file).read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for layer, markers in CONTENT_MARKERS.items():
                if any(marker in text for marker in markers):
                    scores[layer] += 1
    for layer in LAYERS:
        scores[layer] += min(packages[layer], 5)
    return scores


def angular_screens(root: Path, angular: Path) -> Path:
    """The folder of the generated screens in one Angular project."""
    try:
        workspace = json.loads((angular / 'angular.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        workspace = {}
    projects = workspace.get('projects') if isinstance(workspace.get('projects'), dict) else {}
    chosen = next((p for p in projects.values() if isinstance(p, dict) and p.get('projectType') == 'application'),
                  next(iter(projects.values()), {}) if projects else {})
    source = angular / (chosen.get('sourceRoot') or str(Path(chosen.get('root') or '') / 'src'))
    for current, _, files in walk(source if source.is_dir() else angular):
        if 'frm-forms-screen.ts' in files:
            return current  # where the screens of earlier deploys are
    return source / 'app'


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise MigrationError('PROJECT_LAYOUT: a mappa a projekten kívül van: ' + value)
    return path


def map_project(root, layout: dict | None = None) -> dict:
    """{'root', 'CL', 'DPS', 'WBS', 'frontend' (paths or None), 'candidates', 'warnings'} of a project folder."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise MigrationError('PROJECT: a projektmappa nem létezik: ' + str(root))
    layout = dict(layout or {})
    unknown = set(layout) - LAYOUT_KEYS
    if unknown:
        raise MigrationError('PROJECT_LAYOUT: ismeretlen kulcs: ' + ', '.join(sorted(unknown)) + ' (CL, DPS, WBS, frontend)')
    java_roots, angular = [], []
    for current, directories, files in walk(root):
        if current.parts[-3:] == ('src', 'main', 'java'):
            java_roots.append(current)
            directories[:] = []
            continue
        if 'angular.json' in files:
            angular.append(current)
    result = {'root': root, 'warnings': [], 'candidates': {'java': [p.relative_to(root).as_posix() for p in java_roots],
                                                             'angular': [p.relative_to(root).as_posix() for p in angular]}}
    scores = {path: layer_scores(root, path) for path in java_roots}
    for layer in LAYERS:
        if layout.get(layer):
            result[layer] = resolve(root, layout[layer])
            continue
        ranked = sorted(((s[layer], path) for path, s in scores.items() if s[layer] > 0), key=lambda x: -x[0])
        if not ranked:
            result[layer] = None
            continue
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            raise MigrationError(f'PROJECT_LAYOUT: a {layer} projekt nem egyértelmű ('
                                 + ', '.join(p.relative_to(root).as_posix() for s, p in ranked if s == ranked[0][0])
                                 + f'); add meg: --layout {layer}=<mappa>/src/main/java')
        result[layer] = ranked[0][1]
    if layout.get('frontend'):
        result['frontend'] = resolve(root, layout['frontend'])
    elif angular:
        chosen = angular
        if len(angular) > 1:
            chosen = [a for a in angular if tokens(a.relative_to(root)) & FRONTEND_TOKENS] or angular
        if len(chosen) > 1:
            raise MigrationError('PROJECT_LAYOUT: több Angular-projekt van (' + ', '.join(a.relative_to(root).as_posix()
                                 for a in chosen) + '); add meg: --layout frontend=<a képernyők mappája>')
        result['frontend'] = angular_screens(root, chosen[0])
    else:
        result['frontend'] = None
    return result


def output_folders(outputs) -> list[Path]:
    """migrate output folders, or the module folders of a batch folder (each with generated-files.json)."""
    folders = []
    for output in outputs:
        output = Path(output)
        if (output / 'generated-files.json').is_file():
            folders.append(output)
        elif output.is_dir():
            folders += sorted(d for d in output.iterdir() if (d / 'generated-files.json').is_file())
    if not folders:
        raise MigrationError('DEPLOY: nincs generált modul (generated-files.json) a megadott mappákban.')
    return folders


def java_package(output: Path, layer: str, filename: str, text: str) -> str:
    """The package of a generated Java file: its own line, else the one the generator used for the imports."""
    found = re.search(r'^package\s+([\w.]+)\s*;', text, re.M)
    if found:
        return found.group(1)
    try:
        effective = json.loads((output / 'analysis/effective-config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise MigrationError('DEPLOY: hiányzik az analysis/effective-config.json: ' + str(output)) from exc
    config, package = effective['config'], effective['package']
    from .compact_backend import common_tools_package
    from .java_imports import cl_package
    if filename == 'CommonMigrateTools.java':
        return common_tools_package(config)
    return cl_package(config, package) if layer == 'CL' else package + '.' + layer.lower()


def plan_files(output: Path, layout: dict) -> list[dict]:
    """Target, content and policy of every deployable file of one output."""
    from .angular_ui import overwrite_policy
    manifest = json.loads((output / 'generated-files.json').read_text(encoding='utf-8'))
    planned = []
    for entry in manifest['files']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.suffix in DOCUMENTS:
            continue
        source = output / relative
        if not source.is_file() or source.is_symlink():
            continue
        policy = entry.get('overwrite_policy') or overwrite_policy(relative.as_posix())
        item = {'source': source, 'path': relative.as_posix(), 'policy': policy, 'target': None, 'data': None, 'reason': None}
        if relative.parts[0] == 'backend' and len(relative.parts) == 3 and relative.parts[1] in LAYERS and relative.suffix == '.java':
            layer = relative.parts[1]
            text = source.read_text(encoding='utf-8')
            package = java_package(output, layer, relative.name, text)
            if not re.search(r'^package\s+[\w.]+\s*;', text, re.M):
                text = 'package ' + package + ';\n\n' + text  # the generator left it to the IDE: it is known here
            item['data'] = text.encode('utf-8')
            if layout.get(layer) is None:
                item['reason'] = f'nincs {layer} projekt (add meg: --layout {layer}=<mappa>/src/main/java)'
            else:
                item['target'] = layout[layer].joinpath(*package.split('.'), relative.name)
        elif relative.parts[0] == 'frontend' and len(relative.parts) > 1:
            item['data'] = source.read_bytes()
            if layout.get('frontend') is None:
                item['reason'] = 'nincs Angular-projekt (add meg: --layout frontend=<a képernyők mappája>)'
            else:
                item['target'] = layout['frontend'].joinpath(*relative.parts[1:])
        else:
            continue  # analysis, reports: they stay in the output
        planned.append(item)
    return planned


def load_manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not path.is_file():
        return {'generator': 'frm-forms-migrator', 'files': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise MigrationError('DEPLOY: sérült ' + MANIFEST + ' a projektben.') from exc
    if not isinstance(data.get('files'), dict):
        raise MigrationError('DEPLOY: sérült ' + MANIFEST + ' a projektben.')
    return data


def deploy(outputs, root, layout: dict | None = None, dry_run: bool = False, force: bool = False) -> dict:
    """Place the generated files of migrate outputs into the project; returns the report."""
    from . import __version__
    mapped = map_project(root, layout)
    root = mapped['root']
    manifest = load_manifest(root)
    recorded = manifest['files']
    results, counts = [], {}
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for output in output_folders(outputs):
        for item in plan_files(output, mapped):
            status, target = 'skipped', item['target']
            rel = None
            if target is not None:
                inside = target.is_relative_to(root) and target.resolve().is_relative_to(root)
                links = [p for p in [target, *target.parents] if p != root and p.is_relative_to(root) and p.is_symlink()]
                rel = target.relative_to(root).as_posix() if inside else None
                if not inside or links:
                    status, item['reason'] = 'skipped', 'a cél a projekten kívülre vagy symlinkre mutat'
                elif not target.exists():
                    status = 'new'
                else:
                    current = target.read_bytes()
                    if current == item['data']:
                        status = 'unchanged'
                    elif item['policy'] == 'create_once':
                        status = 'kept'
                    elif recorded.get(rel, {}).get('sha256') == sha256(current):
                        status = 'updated'  # ours, untouched since the last deploy
                    else:
                        status = 'overwritten' if force else 'conflict'
                if status in {'new', 'updated', 'overwritten'} and not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + '.frm-tmp')
                    temporary.write_bytes(item['data'])
                    os.replace(temporary, target)
                if status in {'new', 'updated', 'overwritten', 'unchanged'} and not dry_run:
                    recorded[rel] = {'sha256': sha256(item['data']), 'source': item['path'], 'deployed': stamp}
            counts[status] = counts.get(status, 0) + 1
            results.append({'output': str(output), 'source': item['path'], 'target': rel, 'status': status,
                            'policy': item['policy'], **({'reason': item['reason']} if item['reason'] else {})})
    if not dry_run and any(r['status'] in {'new', 'updated', 'overwritten', 'unchanged'} for r in results):
        manifest.update(generator='frm-forms-migrator', version=__version__, files=dict(sorted(recorded.items())))
        temporary = root / (MANIFEST + '.frm-tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, root / MANIFEST)
    layout_report = {key: (mapped[key].relative_to(root).as_posix() if mapped.get(key) is not None and mapped[key].is_relative_to(root)
                           else None) for key in (*LAYERS, 'frontend')}
    report = {'project': str(root), 'dry_run': dry_run, 'force': force, 'layout': layout_report,
              'candidates': mapped['candidates'], 'counts': counts, 'files': results}
    return report


def markdown(report: dict) -> str:
    lines = ['# Telepítés a projektbe' + (' – előnézet' if report['dry_run'] else ''), '',
             f"Projekt: `{report['project']}`", '', '| Rész | Mappa |', '|---|---|']
    lines += [f"| {key} | {('`' + value + '`') if value else '— (nem található)'} |" for key, value in report['layout'].items()]
    lines += ['', 'Összesítés: ' + (', '.join(f"{STATUS_TEXT.get(k, k)}: {v}" for k, v in sorted(report['counts'].items())) or 'nincs fájl'),
              '', '| Fájl | Cél | Állapot |', '|---|---|---|']
    lines += [f"| {r['source']} | {r['target'] or '—'} | {STATUS_TEXT.get(r['status'], r['status'])}"
              + (f" ({r['reason']})" if r.get('reason') else '') + ' |' for r in report['files']]
    if any(r['status'] == 'conflict' for r in report['files']):
        lines += ['', 'Ütközés: a projektben lévő fájl nem a legutóbbi telepítés változata (kézzel módosították, vagy nem a '
                      'migrátor írta). Nem írtuk felül; a friss változat a generált kimenetben van. Felülírás: `--force`.']
    if any(r['status'] == 'kept' for r in report['files']):
        lines += ['', 'Megőrizve: a CREATE_ONCE fájlok (ServiceImpl, ControllerImpl, képernyőkomponens) a projektben már '
                      'léteztek. A friss változatuk a generált kimenetben van, a változásokat kézzel kell átvezetni.']
    return '\n'.join(lines) + '\n'


def parse_layout(values) -> dict:
    """--layout KEY=PATH options."""
    layout = {}
    for value in values or []:
        key, sep, path = value.partition('=')
        if not sep or key not in LAYOUT_KEYS or not path.strip():
            raise MigrationError('--layout: KULCS=MAPPA alak kell (CL, DPS, WBS vagy frontend): ' + value)
        layout[key] = path.strip()
    return layout


def validate_layout(value) -> dict:
    """The project_layout setting: {"CL"|"DPS"|"WBS"|"frontend": "<folder, relative to the project root>"}."""
    if not isinstance(value, dict) or not all(k in LAYOUT_KEYS and isinstance(v, str) and v.strip() for k, v in value.items()):
        raise MigrationError('project_layout: {"CL": "...", "DPS": "...", "WBS": "...", "frontend": "..."} objektum kell '
                             '(mappák a projekt gyökeréhez képest).')
    return {k: v.strip() for k, v in value.items()}


def run(outputs, project, layout: dict, dry_run: bool = False, force: bool = False, report_path=None) -> int:
    """CLI: deploy, write PROJECT_DEPLOY_HU.md (+ analysis/project-deploy.json in each output), print the summary.

    Exit code 3 when a file was not written because of a conflict, or skipped for a missing project part."""
    report = deploy(outputs, project, layout, dry_run=dry_run, force=force)
    folders = output_folders(outputs)
    text = markdown(report)
    target = Path(report_path) if report_path else folders[0] / 'PROJECT_DEPLOY_HU.md'
    target.write_text(text, encoding='utf-8')
    for folder in folders:
        own = dict(report, files=[f for f in report['files'] if f['output'] == str(folder)])
        (folder / 'analysis').mkdir(exist_ok=True)
        (folder / 'analysis' / 'project-deploy.json').write_text(json.dumps(own, ensure_ascii=False, indent=2) + '\n',
                                                                 encoding='utf-8')
    print(json.dumps({'project': report['project'], 'dry_run': dry_run, 'layout': report['layout'], 'counts': report['counts'],
                      'report': str(target)}, ensure_ascii=False, indent=2))
    return 3 if report['counts'].get('conflict') or report['counts'].get('skipped') else 0

"""Generated files straight into the developer's project: CL, DPS, WBS and the frontend in their own folders.

Every part has a folder of its own, chosen or found:
  - chosen: layout {"CL"|"DPS"|"WBS"|"frontend": folder} (the web UI's folder pickers, project_layout in the
    config, --layout KEY=PATH). Absolute, or relative to the project folder. For a Java part the project folder
    (…/rendszer-dps) and its src/main/java both do; for the frontend the Angular project (angular.json) or the
    screens folder itself;
  - found: map_project() looks over the main project folder, when one is given: the Java source roots
    (.../src/main/java) by folder name (…-cl, …-dps, …-wbs), then by the packages and company classes found
    in them; the Angular project (angular.json) and its screens folder (where frm-forms-screen.ts already is,
    else <sourceRoot>/app).

deploy() places every generated file of migrate outputs:
  - Java: by its package under the part's source root. A file generated without package line (web:
    java_empty_package) gets the package the generator used for its imports, so it compiles in place;
  - frontend: under the screens folder, with the output's relative path (frm-forms-screen.ts, <module>/...).
Generated files are overwritten; CREATE_ONCE files (ServiceImpl, ControllerImpl, the component) are written
only when they do not exist yet - the fresh version stays in the output. A generated file changed in the
project since the last deploy, or a foreign file of the same name, is not overwritten unless force: it is
reported as a conflict. The hashes of the last deploy are kept in .frm-deploy.json in each part's project
folder (rendszer-dps/, the Angular project). Nothing is written outside the part folders and no symlink is
followed. dry_run: the plan only.
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
PARTS = (*LAYERS, 'frontend')
LAYOUT_KEYS = set(PARTS)
MANIFEST = '.frm-deploy.json'
SKIP_DIRS = {'node_modules', 'target', 'build', 'dist', 'out', 'bin', 'obj', 'coverage', 'tmp', 'temp', 'venv',
             '__pycache__', 'local-data'}
MAX_DEPTH = 8
FRONTEND_TOKENS = {'frontend', 'front', 'fe', 'ui', 'web', 'angular', 'client'}
CONTENT_MARKERS = {'DPS': ('DpsLogHelper',), 'WBS': ('WbsLogHelper', 'WbsServiceBase', 'WbsControllerBase'),
                   'CL': ('DataProviderServiceRestClientBase', 'CommonMigrateTools')}
DOCUMENTS = {'.md', '.txt'}
WRITTEN = {'new', 'updated', 'overwritten'}
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


def is_java_root(path: Path) -> bool:
    return path.parts[-3:] == ('src', 'main', 'java')


def java_source_root(folder: Path) -> Path:
    """The source root of a chosen Java folder: the project folder, its src or src/main, src/main/java itself, or a
    package folder inside it (the files go by their package anyway)."""
    for candidate in (folder / 'src' / 'main' / 'java', folder / 'main' / 'java', folder / 'java'):
        if candidate.is_dir() and is_java_root(candidate):
            return candidate
    return next((p for p in [folder, *folder.parents] if is_java_root(p)), folder)


def java_home(source_root: Path) -> Path:
    """Where the part's .frm-deploy.json lives: the Java project folder (…/rendszer-dps)."""
    return source_root.parents[2] if is_java_root(source_root) else source_root


def angular_screens(angular: Path) -> Path:
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


def frontend_home(screens: Path) -> Path:
    """The Angular project of a screens folder (the nearest folder above with angular.json), else the folder."""
    for folder in [screens, *screens.parents][:12]:
        if (folder / 'angular.json').is_file():
            return folder
    return screens


def chosen_folder(key: str, value: str, root: Path | None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        if root is None:
            raise MigrationError(f'PROJECT_LAYOUT: a(z) {key} mappát teljes útvonallal add meg (nincs fő projektmappa): {value}')
        path = root / path
    path = path.resolve()
    if path.is_dir():
        return path
    if path.exists():
        raise MigrationError(f'PROJECT_LAYOUT: a(z) {key} útvonal nem mappa: {path}')
    if key == 'frontend' and path.parent.is_dir() and frontend_home(path) != path:
        return path  # a new screens folder in the Angular project: the first deploy creates it
    raise MigrationError(f'PROJECT_LAYOUT: a(z) {key} mappa nem létezik: {path}')


def part_folders(key: str, folder: Path) -> tuple[Path, Path]:
    """(target root, home) of a chosen folder: files go under the target root, the manifest into the home."""
    if key == 'frontend':
        target = angular_screens(folder) if (folder / 'angular.json').is_file() else folder
        return target, frontend_home(target)
    target = java_source_root(folder)
    return target, java_home(target)


def map_project(root=None, layout: dict | None = None) -> dict:
    """{'root', 'CL', 'DPS', 'WBS', 'frontend' (target roots or None), 'home', 'candidates'} of a project.

    root: the main project folder, the parts not chosen in layout are found in it (optional)."""
    layout = {k: v for k, v in (layout or {}).items() if isinstance(v, str) and v.strip()}
    unknown = set(layout) - LAYOUT_KEYS
    if unknown:
        raise MigrationError('PROJECT_LAYOUT: ismeretlen kulcs: ' + ', '.join(sorted(unknown)) + ' (CL, DPS, WBS, frontend)')
    if root is None or not str(root).strip():
        if not layout:
            raise MigrationError('PROJECT: add meg a fő projektmappát, vagy legalább egy rész (CL, DPS, WBS, frontend) mappáját.')
        root = None
    else:
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            raise MigrationError('PROJECT: a projektmappa nem létezik: ' + str(root))
    result = {'root': root, 'home': {}, 'candidates': {'java': [], 'angular': []}}
    for key in PARTS:
        result[key] = None
    for key, value in layout.items():
        result[key], result['home'][key] = part_folders(key, chosen_folder(key, value, root))
    missing = [key for key in PARTS if key not in layout]
    if root is None or not missing:
        return result
    java_roots, angular = [], []
    for current, directories, files in walk(root):
        if is_java_root(current):
            java_roots.append(current)
            directories[:] = []
            continue
        if 'angular.json' in files:
            angular.append(current)
    result['candidates'] = {'java': [p.relative_to(root).as_posix() for p in java_roots],
                            'angular': [p.relative_to(root).as_posix() for p in angular]}
    scores = {path: layer_scores(root, path) for path in java_roots}
    for layer in (layer for layer in LAYERS if layer in missing):
        ranked = sorted(((s[layer], path) for path, s in scores.items() if s[layer] > 0), key=lambda x: -x[0])
        if not ranked:
            continue
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            raise MigrationError(f'PROJECT_LAYOUT: a {layer} projekt nem egyértelmű ('
                                 + ', '.join(p.relative_to(root).as_posix() for s, p in ranked if s == ranked[0][0])
                                 + f'); válaszd ki a mappáját (--layout {layer}=<mappa>)')
        result[layer], result['home'][layer] = ranked[0][1], java_home(ranked[0][1])
    if 'frontend' in missing and angular:
        chosen = angular
        if len(angular) > 1:
            chosen = [a for a in angular if tokens(a.relative_to(root)) & FRONTEND_TOKENS] or angular
        if len(chosen) > 1:
            raise MigrationError('PROJECT_LAYOUT: több Angular-projekt van (' + ', '.join(a.relative_to(root).as_posix()
                                 for a in chosen) + '); válaszd ki a frontend mappáját (--layout frontend=<mappa>)')
        result['frontend'], result['home']['frontend'] = angular_screens(chosen[0]), chosen[0]
    return result


def mapped_folders(mapped: dict) -> list[Path]:
    """Every folder a deploy may write into: the part folders and their homes (.frm-deploy.json)."""
    return [path for path in [*(mapped[key] for key in PARTS), *mapped['home'].values()] if path is not None]


def layer_scores(root: Path, java_root: Path) -> dict[str, int]:
    """How much a Java source root looks like the CL, DPS or WBS project."""
    project = java_home(java_root)
    names = tokens(project.relative_to(root)) if project != root and project.is_relative_to(root) else set()
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
    """Part, target, content and policy of every deployable file of one output."""
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
        item = {'source': source, 'path': relative.as_posix(), 'policy': policy, 'part': None, 'target': None,
                'data': None, 'reason': None}
        if relative.parts[0] == 'backend' and len(relative.parts) == 3 and relative.parts[1] in LAYERS and relative.suffix == '.java':
            layer = item['part'] = relative.parts[1]
            text = source.read_text(encoding='utf-8')
            package = java_package(output, layer, relative.name, text)
            if not re.search(r'^package\s+[\w.]+\s*;', text, re.M):
                text = 'package ' + package + ';\n\n' + text  # the generator left it to the IDE: it is known here
            item['data'] = text.encode('utf-8')
            if layout.get(layer) is None:
                item['reason'] = f'nincs {layer} mappa (válaszd ki, vagy add meg: --layout {layer}=<mappa>)'
            else:
                item['target'] = layout[layer].joinpath(*package.split('.'), relative.name)
        elif relative.parts[0] == 'frontend' and len(relative.parts) > 1:
            item['part'] = 'frontend'
            item['data'] = source.read_bytes()
            if layout.get('frontend') is None:
                item['reason'] = 'nincs frontend mappa (válaszd ki, vagy add meg: --layout frontend=<mappa>)'
            else:
                item['target'] = layout['frontend'].joinpath(*relative.parts[1:])
        else:
            continue  # analysis, reports: they stay in the output
        planned.append(item)
    return planned


def load_manifest(folder: Path) -> dict:
    path = folder / MANIFEST
    if not path.is_file():
        return {'generator': 'frm-forms-migrator', 'files': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise MigrationError('DEPLOY: sérült ' + MANIFEST + ': ' + str(path)) from exc
    if not isinstance(data.get('files'), dict):
        raise MigrationError('DEPLOY: sérült ' + MANIFEST + ': ' + str(path))
    return data


def deploy(outputs, root=None, layout: dict | None = None, dry_run: bool = False, force: bool = False,
           mapped: dict | None = None) -> dict:
    """Place the generated files of migrate outputs into the project's part folders; returns the report.

    mapped: the map_project(root, layout) result when the caller already has it."""
    from . import __version__
    mapped = mapped or map_project(root, layout)
    manifests = {}  # home folder -> its .frm-deploy.json

    def manifest(home: Path) -> dict:
        if home not in manifests:
            manifests[home] = load_manifest(home)
        return manifests[home]

    # 4.16 kept one .frm-deploy.json in the main project folder: its hashes still tell our files from changed ones.
    legacy = {}
    if mapped['root'] is not None and (mapped['root'] / MANIFEST).is_file():
        legacy = {str(mapped['root'] / rel): entry for rel, entry in load_manifest(mapped['root'])['files'].items()}
    results, counts, touched = [], {}, set()
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for output in output_folders(outputs):
        for item in plan_files(output, mapped):
            status, target, display = 'skipped', item['target'], None
            if target is not None:
                base, home = mapped[item['part']], mapped['home'][item['part']]
                inside = target.is_relative_to(base) and target.resolve().is_relative_to(base.resolve())
                links = [p for p in [target, *target.parents] if p != base and p.is_relative_to(base) and p.is_symlink()]
                if not inside or links:
                    status, item['reason'] = 'skipped', 'a cél a rész mappáján kívülre vagy symlinkre mutat'
                else:
                    rel = target.relative_to(home).as_posix()
                    display = item['part'] + ': ' + rel
                    recorded = manifest(home)['files'].get(rel) or legacy.get(str(target)) or {}
                    if not target.exists():
                        status = 'new'
                    else:
                        current = target.read_bytes()
                        if current == item['data']:
                            status = 'unchanged'
                        elif item['policy'] == 'create_once':
                            status = 'kept'
                        elif recorded.get('sha256') == sha256(current):
                            status = 'updated'  # ours, untouched since the last deploy
                        else:
                            status = 'overwritten' if force else 'conflict'
                    if status in WRITTEN and not dry_run:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + '.frm-tmp')
                        temporary.write_bytes(item['data'])
                        os.replace(temporary, target)
                    if status in WRITTEN | {'unchanged'} and not dry_run:
                        manifest(home)['files'][rel] = {'sha256': sha256(item['data']), 'source': item['path'], 'deployed': stamp}
                        touched.add(home)
            counts[status] = counts.get(status, 0) + 1
            results.append({'output': str(output), 'part': item['part'], 'source': item['path'],
                            'target': str(target) if target is not None and display else None, 'display': display,
                            'status': status, 'policy': item['policy'], **({'reason': item['reason']} if item['reason'] else {})})
    for home in sorted(touched):
        data = manifests[home]
        data.update(generator='frm-forms-migrator', version=__version__, files=dict(sorted(data['files'].items())))
        temporary = home / (MANIFEST + '.frm-tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, home / MANIFEST)
    return {'project': str(mapped['root']) if mapped['root'] is not None else None, 'dry_run': dry_run, 'force': force,
            'layout': {key: (str(mapped[key]) if mapped[key] is not None else None) for key in PARTS},
            'candidates': mapped['candidates'], 'counts': counts, 'files': results}


def markdown(report: dict) -> str:
    lines = ['# Telepítés a projektbe' + (' – előnézet' if report['dry_run'] else ''), '']
    if report.get('project'):
        lines += [f"Fő projektmappa: `{report['project']}`", '']
    lines += ['| Rész | Mappa |', '|---|---|']
    lines += [f"| {key} | {('`' + value + '`') if value else '— (nincs kiválasztva / nem található)'} |"
              for key, value in report['layout'].items()]
    lines += ['', 'Összesítés: ' + (', '.join(f"{STATUS_TEXT.get(k, k)}: {v}" for k, v in sorted(report['counts'].items())) or 'nincs fájl'),
              '', '| Fájl | Cél | Állapot |', '|---|---|---|']
    lines += [f"| {r['source']} | {r.get('display') or '—'} | {STATUS_TEXT.get(r['status'], r['status'])}"
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
    """The project_layout setting: {"CL"|"DPS"|"WBS"|"frontend": "<folder: absolute, or relative to the project>"}."""
    if not isinstance(value, dict) or not all(k in LAYOUT_KEYS and isinstance(v, str) and v.strip() for k, v in value.items()):
        raise MigrationError('project_layout: {"CL": "...", "DPS": "...", "WBS": "...", "frontend": "..."} objektum kell '
                             '(teljes útvonalak, vagy a fő projektmappához képest).')
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

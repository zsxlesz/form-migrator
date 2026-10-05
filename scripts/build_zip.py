"""Package source, compiled local UI, examples and guides; exclude runtime data."""
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"frm_forms", "web-ui", "web-dist", "examples", "sample-output", "review-output", "screen-output", "tests", "docs", "scripts"}
FILES = {"README.md", "README_HU.md", "LOCAL_START_HU.md", "VALIDATION_HU.md", "FRONTEND_SCREEN_HU.md", "pyproject.toml", "requirements-web.txt", "requirements-test.txt", ".gitignore", "COMPANY_PROFILE_HU.md", "BACKEND_COMPACT_HU.md", "BACKEND_OPTIMIZATION_HU.md"}
EXCLUDED = {"node_modules", "__pycache__", ".angular", ".venv", "out-tsc", "local-data", ".git", ".pytest_cache", ".frm-ai-cache", "build"}


def excluded(relative):
    return relative.suffix == ".pyc" or any(
        part in EXCLUDED or part.startswith((".frm-stage-", ".frm-screen-check-")) or part.endswith(".egg-info")
        for part in relative.parts)


def main():
    assert (ROOT / "web-dist/browser/index.html").is_file(), "Build web-ui before packaging"
    output = ROOT.parent / (ROOT.name + ".zip")
    count = 0
    # Publish only a closed, verified archive, including in watched/synced folders.
    with tempfile.TemporaryDirectory(prefix="frm-package-", dir=ROOT.parent) as temporary:
        staged = Path(temporary) / output.name
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(ROOT.rglob("*")):
                relative = path.relative_to(ROOT)
                if not path.is_file() or excluded(relative):
                    continue
                if not ((len(relative.parts) == 1 and relative.name in FILES) or relative.parts[0] in DIRECTORIES):
                    continue
                entry = zipfile.ZipInfo(ROOT.name + "/" + relative.as_posix(), (2026, 9, 16, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, path.read_bytes())
                count += 1
        with zipfile.ZipFile(staged) as archive:
            assert archive.testzip() is None
            assert any(name.endswith("web-dist/browser/index.html") for name in archive.namelist())
            assert any(name.endswith("LOCAL_START_HU.md") for name in archive.namelist())
            assert any(name.endswith("FRONTEND_SCREEN_HU.md") for name in archive.namelist())
            assert any(name.endswith("BACKEND_COMPACT_HU.md") for name in archive.namelist())
            assert any(name.endswith("BACKEND_OPTIMIZATION_HU.md") for name in archive.namelist())
            assert not any(excluded(Path(name)) for name in archive.namelist())
        staged.replace(output)
    print(f"{output}: {count} files, {output.stat().st_size} bytes, CRC OK")


if __name__ == "__main__":
    main()

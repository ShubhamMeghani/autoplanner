"""Synthetic screenshots (AC-36), no real screenshots in the repo (AC-37), no keys (AC-3)."""

import importlib.util
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest
from PIL import Image

from autoplanner.config import TZ
from autoplanner.importers.ocr import tesseract_available
from autoplanner.importers.pipeline import import_screenshots, normalise

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SYNTHETIC = FIXTURES / "teams_synthetic"
MARKER = ("autoplanner-synthetic", "1")
KEY_PATTERNS = re.compile(r"sb_secret_[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}"
                          r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")


def generator():
    spec = importlib.util.spec_from_file_location("make_synthetic", FIXTURES / "make_synthetic_screenshots.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args: str) -> list[str] | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line for line in out.splitlines() if line]


def test_generator_is_deterministic_and_matches_the_committed_labels_ac36(tmp_path):
    gen = generator()
    first, second = tmp_path / "a", tmp_path / "b"
    paths = gen.generate(first)
    gen.generate(second)
    labels = (first / "labels.json").read_text(encoding="utf-8")
    assert labels == (second / "labels.json").read_text(encoding="utf-8")
    assert labels == (SYNTHETIC / "labels.json").read_text(encoding="utf-8")
    assert len(paths) >= 3
    for path in paths:
        with Image.open(path) as image:
            assert image.text.get(MARKER[0]) == MARKER[1]


def test_every_png_under_fixtures_is_synthetic_ac37():
    tracked = git("ls-files", "--", "tests/fixtures") or []
    on_disk = [str(p.relative_to(ROOT)).replace("\\", "/") for p in FIXTURES.rglob("*.png")]
    pngs = sorted({p for p in tracked + on_disk if p.lower().endswith(".png")})
    assert pngs
    for rel in pngs:
        with Image.open(ROOT / rel) as image:
            assert image.text.get(MARKER[0]) == MARKER[1], f"{rel} is not a generated synthetic screenshot"


def test_private_folder_is_ignored_and_never_tracked_ac37():
    assert "private/" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    tracked = git("ls-files", "--", "private")
    assert tracked in (None, [])


def test_eval_import_skips_without_private_fixtures_ac37(tmp_path, capsys):
    from bench.eval_import import SKIP_MESSAGE, main

    assert main(["--dir", str(tmp_path / "missing")]) == 0
    assert capsys.readouterr().out.strip() == SKIP_MESSAGE


def test_no_real_keys_in_tracked_files_ac3():
    files = git("ls-files")
    if files is None:
        pytest.skip("not a git checkout")
    for rel in files:
        path = ROOT / rel
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not KEY_PATTERNS.search(text), f"key-like string in {rel}"


@pytest.mark.skipif(not tesseract_available(), reason="Tesseract is not installed (CI installs it)")
def test_tesseract_reads_the_synthetic_screenshots_ac36():
    spec = json.loads((SYNTHETIC / "labels.json").read_text(encoding="utf-8"))
    import_date = date.fromisoformat(spec["import_date"])
    now = datetime.combine(import_date, datetime.min.time(), TZ)
    hits = total = 0
    for item in spec["images"]:
        result = import_screenshots([(SYNTHETIC / item["file"]).read_bytes()], import_date, now, [],
                                    api_key=None, model=None, gemini_allowed=False)
        found = {(normalise(r.title), r.deadline) for r in result.rows}
        for label in item["rows"]:
            total += 1
            hits += (normalise(label["title"]), datetime.fromisoformat(label["deadline"])) in found
    assert hits / total >= 0.80, f"Tesseract read {hits}/{total} rows correctly"

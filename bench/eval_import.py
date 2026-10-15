"""Screenshot-import accuracy on labelled screenshots (AC-17, R65).

    python -m bench.eval_import                      # the owner's real screenshots in private/teams/
    python -m bench.eval_import --dir tests/fixtures/teams_synthetic

A row is correct when some extracted row has the same normalised title and the same resolved
deadline as the label. Each engine is scored on its own (no fallback). Only aggregate numbers
are printed, never titles, unless --show-misses is given (keep that output local).
labels.json format: {"import_date": "YYYY-MM-DD", "images": [{"file": ..., "rows": [{"title", "deadline"}]}]}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path

from autoplanner.config import TZ
from autoplanner.importers import gemini_vision
from autoplanner.importers.ocr import ocr_text, tesseract_available
from autoplanner.importers.pipeline import build_rows, normalise
from autoplanner.importers.text_parser import parse_text

THRESHOLDS = {"gemini": 0.90, "tesseract": 0.60}
SKIP_MESSAGE = "skipped: private fixtures not present"


def gemini_settings() -> tuple[str | None, str | None]:
    secrets_file = Path(".streamlit/secrets.toml")
    values = tomllib.loads(secrets_file.read_text(encoding="utf-8")) if secrets_file.exists() else {}
    return (os.environ.get("GEMINI_API_KEY") or values.get("GEMINI_API_KEY"),
            os.environ.get("GEMINI_MODEL") or values.get("GEMINI_MODEL"))


def matches(rows, labels: list[dict]) -> list[bool]:
    found = {(normalise(r.title), r.deadline) for r in rows}
    return [(normalise(lab["title"]), datetime.fromisoformat(lab["deadline"]).astimezone(TZ)) in found
            for lab in labels]


def read_with(engine: str, image: bytes, import_date: date, now: datetime, key, model):
    if engine == "gemini":
        raw = gemini_vision.extract_rows(image, api_key=key, model=model)
    else:
        raw = parse_text(ocr_text(image))
    return build_rows(raw, import_date, now, [], engine)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default="private/teams", help="folder with the screenshots and labels.json")
    parser.add_argument("--engines", default="gemini,tesseract")
    parser.add_argument("--show-misses", action="store_true", help="print missed titles (local use only)")
    args = parser.parse_args(argv)

    folder = Path(args.dir)
    labels_file = folder / "labels.json"
    if not labels_file.exists():
        print(SKIP_MESSAGE)
        return 0
    spec = json.loads(labels_file.read_text(encoding="utf-8"))
    import_date = date.fromisoformat(spec["import_date"])
    now = datetime.combine(import_date, datetime.min.time(), TZ)
    key, model = gemini_settings()
    failed = False

    print(f"{'engine':10} {'correct':>9} {'accuracy':>9} {'target':>7}  result")
    for engine in [e.strip() for e in args.engines.split(",") if e.strip()]:
        if engine == "gemini" and not (key and model):
            print(f"{engine:10} {'-':>9} {'-':>9} {'90%':>7}  skipped: GEMINI_API_KEY/GEMINI_MODEL not set")
            continue
        if engine == "tesseract" and not tesseract_available():
            print(f"{engine:10} {'-':>9} {'-':>9} {'60%':>7}  skipped: Tesseract not installed")
            continue
        hits, total, notes, misses = 0, 0, [], []
        for item in spec["images"]:
            image = (folder / item["file"]).read_bytes()
            try:
                rows = read_with(engine, image, import_date, now, key, model)
            except Exception as exc:  # one unreadable image counts as all of its rows missed
                rows, notes = [], notes + [f"{item['file']}: {exc}"]
            result = matches(rows, item["rows"])
            hits, total = hits + sum(result), total + len(result)
            misses += [lab["title"] for lab, ok in zip(item["rows"], result) if not ok]
            del image
        accuracy = hits / total if total else 0.0
        ok = accuracy >= THRESHOLDS[engine]
        failed |= not ok
        print(f"{engine:10} {f'{hits}/{total}':>9} {accuracy:>8.0%} {THRESHOLDS[engine]:>7.0%}  "
              f"{'PASS' if ok else 'FAIL'}")
        for note in notes:
            print(f"    note: {note}")
        if args.show_misses and misses:
            print("    missed: " + "; ".join(misses))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

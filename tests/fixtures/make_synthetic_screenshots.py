"""Generate synthetic Teams-style Assignments screenshots and their labels (R66).

Usage: python tests/fixtures/make_synthetic_screenshots.py [out_dir]
Default out_dir: tests/fixtures/teams_synthetic. Output is deterministic. Every PNG carries
the text chunk autoplanner-synthetic=1, so a real screenshot can never pass for a fixture.
The data is fictional; deadlines are written out by hand (not computed by the resolver).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

IMPORT_DATE = "2026-10-14"  # a Wednesday
MARKER = ("autoplanner-synthetic", "1")
WIDTH, HEADER, CARD = 1100, 130, 132
ACCENT, TEXT, MUTED, LINE = (98, 100, 167), (36, 36, 36), (97, 97, 97), (224, 224, 224)

# (title, course, due text, expected deadline in IST)
IMAGES = [
    [
        ("Assignment 4: Graph algorithms", "E0 251 Data Structures and Algorithms",
         "Due tomorrow at 11:59 PM", "2026-10-15T23:59:00+05:30"),
        ("Problem set 5", "MA 261 Probability Models", "Due Friday at 5:00 PM", "2026-10-16T17:00:00+05:30"),
        ("Lab 3 report: histogram equalisation", "E9 241 Digital Image Processing",
         "Due Oct 20, 11:59 PM", "2026-10-20T23:59:00+05:30"),
        ("Mini-project milestone 2", "DS 221 Scalable Systems", "Due Wednesday at 9:00 AM",
         "2026-10-21T09:00:00+05:30"),
        ("Reading response: MapReduce", "DS 221 Scalable Systems", "Due today at 6:00 PM",
         "2026-10-14T18:00:00+05:30"),
    ],
    [
        ("Quiz 3", "MA 261 Probability Models", "Due October 22, 2026 11:30 AM", "2026-10-22T11:30:00+05:30"),
        ("Assignment 5: Dynamic programming", "E0 251 Data Structures and Algorithms",
         "Due Oct 27, 11:59 PM", "2026-10-27T23:59:00+05:30"),
        ("Lab 4 report: edge detection", "E9 241 Digital Image Processing", "Due Monday at 11:59 PM",
         "2026-10-19T23:59:00+05:30"),
        ("Term paper outline", "HS 202 Technology and Society", "Due 3 Jan", "2027-01-03T23:59:00+05:30"),
        ("Problem set 4 resubmission", "MA 261 Probability Models", "Past due Oct 13, 11:59 PM",
         "2026-10-13T23:59:00+05:30"),
    ],
    [
        ("Midterm preparation worksheet", "E9 241 Digital Image Processing", "Due Thursday at 2:00 PM",
         "2026-10-15T14:00:00+05:30"),
        ("Systems lab 2: MPI basics", "DS 221 Scalable Systems", "Due tomorrow at 9:00 AM",
         "2026-10-15T09:00:00+05:30"),
        ("Chapter 24 exercises", "E0 251 Data Structures and Algorithms", "Due Oct 19, 11:59 PM",
         "2026-10-19T23:59:00+05:30"),
        ("Project proposal", "HS 202 Technology and Society", "Due November 2, 2026 5:00 PM",
         "2026-11-02T17:00:00+05:30"),
        ("Weekly reflection", "HS 202 Technology and Society", "Due Sunday at 11:59 PM",
         "2026-10-18T23:59:00+05:30"),
    ],
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)  # Pillow's bundled font: same on every OS


def render(rows: list[tuple[str, str, str, str]]) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEADER + CARD * len(rows) + 24), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 28), "Assignments", fill=TEXT, font=font(36))
    draw.text((40, 84), "Upcoming", fill=ACCENT, font=font(22))
    draw.text((180, 84), "Past due", fill=MUTED, font=font(22))
    draw.text((300, 84), "Completed", fill=MUTED, font=font(22))
    draw.line((40, 120, WIDTH - 40, 120), fill=LINE, width=2)
    for i, (title, course, due, _) in enumerate(rows):
        top = HEADER + i * CARD
        draw.rectangle((40, top + 14, 46, top + CARD - 14), fill=ACCENT)
        draw.text((70, top + 14), title, fill=TEXT, font=font(30))
        draw.text((70, top + 56), course, fill=MUTED, font=font(24))
        draw.text((70, top + 90), due, fill=TEXT, font=font(24))
        draw.line((40, top + CARD - 2, WIDTH - 40, top + CARD - 2), fill=LINE, width=1)
    return image


def generate(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    info = PngInfo()
    info.add_text(*MARKER)
    labels = {"import_date": IMPORT_DATE, "images": []}
    paths = []
    for number, rows in enumerate(IMAGES, 1):
        path = out_dir / f"teams_{number}.png"
        render(rows).save(path, format="PNG", pnginfo=info, optimize=False)
        paths.append(path)
        labels["images"].append({"file": path.name, "rows": [
            {"title": t, "course": c, "due_text": d, "deadline": dl} for t, c, d, dl in rows]})
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8", newline="\n")
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "teams_synthetic"
    for p in generate(target):
        print(p)

"""
Rebuild original/custom/chart_authored_levels.json by scanning every notes.chart under original/custom.

One JSON file maps folder name -> { chartModifiedUtc, count, letters, detail } (same schema as the desktop app).

Also removes legacy per-song .chart_authored_levels files next to charts.

Run from repo root:  python tools/scan_chart_authored_levels.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUSTOM = ROOT / "original" / "custom"
INDEX_JSON = CUSTOM / "chart_authored_levels.json"
LEGACY_SIDECAR = ".chart_authored_levels"

_RX = {
    "E": re.compile(r"\[\s*EasySingle\s*\]", re.I),
    "M": re.compile(r"\[\s*MediumSingle\s*\]", re.I),
    "H": re.compile(r"\[\s*HardSingle\s*\]", re.I),
    "X": re.compile(r"\[\s*ExpertSingle\s*\]", re.I),
}


def _scan_text(text: str) -> tuple[int, str, str]:
    e = bool(_RX["E"].search(text))
    m = bool(_RX["M"].search(text))
    h = bool(_RX["H"].search(text))
    x = bool(_RX["X"].search(text))
    if not (e or m or h or x):
        low = text.lower()
        e = "easysingle" in low
        m = "mediumsingle" in low
        h = "hardsingle" in low
        x = "expertsingle" in low
    letters = "".join(s for ok, s in [(e, "E"), (m, "M"), (h, "H"), (x, "X")] if ok)
    labels = []
    if e:
        labels.append("Easy")
    if m:
        labels.append("Medium")
    if h:
        labels.append("Hard")
    if x:
        labels.append("Expert")
    detail = ", ".join(labels) if labels else "No guitar single sections"
    count = sum([e, m, h, x])
    return count, letters, detail


def _delete_legacy_sidecars() -> int:
    n = 0
    for p in CUSTOM.rglob(LEGACY_SIDECAR):
        if p.is_file():
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


def main() -> None:
    if not CUSTOM.is_dir():
        print(f"No folder: {CUSTOM}", file=sys.stderr)
        sys.exit(1)

    removed = _delete_legacy_sidecars()
    if removed:
        print(f"Removed {removed} legacy {LEGACY_SIDECAR} file(s).")

    index: dict[str, dict[str, object]] = {}
    for song_dir in sorted(CUSTOM.iterdir()):
        if not song_dir.is_dir():
            continue
        legacy = song_dir / LEGACY_SIDECAR
        if legacy.is_file():
            try:
                legacy.unlink()
            except OSError:
                pass
        chart = song_dir / "notes.chart"
        if not chart.is_file():
            continue
        text = chart.read_text(encoding="utf-8", errors="replace")
        chart_utc = datetime.fromtimestamp(chart.stat().st_mtime, tz=timezone.utc)
        count, letters, detail = _scan_text(text)
        line0 = chart_utc.isoformat().replace("+00:00", "Z")
        index[song_dir.name] = {
            "chartModifiedUtc": line0,
            "count": count,
            "letters": letters,
            "detail": detail,
        }
        print(f"  OK {song_dir.name} -> {count} ({letters or '-'})")

    INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(INDEX_JSON)
    print(f"Wrote {INDEX_JSON.relative_to(ROOT)} ({len(index)} songs).")


if __name__ == "__main__":
    main()

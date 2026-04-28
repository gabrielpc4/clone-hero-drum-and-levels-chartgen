"""
patch_songs.py
Patches all Songs/*/notes.mid files without re-running drum chart generation.

Per song:
  1. Backs up notes.mid as notes.YYYY-MM-DD-HH-MM.patch-backup.mid
  2. Strips star power (pitch 116) from PART GUITAR
  3. Strips PS/Moonscraper SysEx forced-type events from PART GUITAR
  4. Strips star power (116) and drum fill markers (120-124) from PART DRUMS
  5. If original/custom/<song>/notes.chart exists, replaces PART GUITAR from the chart
     (chart ``N 7`` exports as green in MIDI) and copies notes.chart beside notes.mid.

Expert drums are unchanged; Expert guitar lanes are replaced when merging from charter.
Songs with only notes.chart in Songs/ (no notes.mid) are skipped.
"""
from __future__ import annotations
import os, sys, shutil, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "chart_generation"))

from midi_repair import load_midi_file
from parse_chart import chart_file_to_midi
import mido

SONGS_DIR  = ROOT / "Songs"
CUSTOM_DIR = ROOT / "original" / "custom"

GUITAR_STRIP = {116}
DRUMS_STRIP  = {116, 120, 121, 122, 123, 124}


def _decode_abs(track: mido.MidiTrack) -> list[tuple[int, object]]:
    abs_t = 0
    events: list[tuple[int, object]] = []
    for msg in track:
        abs_t += msg.time
        events.append((abs_t, msg))
    return events


def _build_track(name: str, events: list[tuple[int, object]]) -> mido.MidiTrack:
    events = [(t, m) for t, m in events if m.type != "end_of_track"]
    events.sort(key=lambda e: e[0])
    tr = mido.MidiTrack()
    tr.name = name
    last = 0
    for abs_t, msg in events:
        tr.append(msg.copy(time=abs_t - last))
        last = abs_t
    tr.append(mido.MetaMessage("end_of_track", time=0))
    return tr


def _load_all_chartered_guitar(chart_path: Path) -> list[tuple[int, object]]:
    """Return all guitar note and non-note events from a .chart file."""
    try:
        chart_mid = chart_file_to_midi(str(chart_path))
    except Exception as exc:
        print(f"    WARNING: cannot read chart: {exc}")
        return []

    guitar = next((t for t in chart_mid.tracks if t.name == "PART GUITAR"), None)
    if guitar is None:
        return []

    # Return all events except end_of_track
    events = [
        (abs_t, msg)
        for abs_t, msg in _decode_abs(guitar)
        if msg.type != "end_of_track"
    ]
    return events


def patch_song(notes_mid: Path, chart_path: Path | None) -> str:
    # --- backup ---
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
    backup = notes_mid.parent / f"notes.{ts}.patch-backup.mid"
    shutil.copy2(notes_mid, backup)

    mid = load_midi_file(str(notes_mid))

    # --- optional: all chartered guitar from .chart ---
    chartered_guitar: list[tuple[int, object]] = []
    if chart_path and chart_path.exists():
        chartered_guitar = _load_all_chartered_guitar(chart_path)

    new_tracks: list[mido.MidiTrack] = []
    stats: list[str] = []

    for tr in mid.tracks:
        name = tr.name or ""

        if name == "PART GUITAR":
            if chartered_guitar:
                if chart_path is not None and chart_path.exists():
                    shutil.copy2(chart_path, notes_mid.parent / "notes.chart")
                # Use entire chartered guitar track
                stats.append(
                    f"guitar: from chart ({len([e for e in chartered_guitar if e[1].type == 'note_on'])} note_ons), notes.chart copied"
                )
                new_tracks.append(_build_track("PART GUITAR", chartered_guitar))
            else:
                # Strip SP and SysEx from original, keep as-is
                events = _decode_abs(tr)
                sp_before = sum(1 for _, m in events if m.type == "note_on" and m.note == 116)

                clean = []
                for abs_t, msg in events:
                    # Strip star power
                    if msg.type in ("note_on", "note_off") and msg.note in GUITAR_STRIP:
                        continue
                    # Strip PS/Moonscraper SysEx forced-type markers
                    if (msg.type == "sysex" and len(msg.data) >= 2
                            and msg.data[0] == 0x50 and msg.data[1] == 0x53):
                        continue
                    clean.append((abs_t, msg))

                if sp_before:
                    stats.append(f"guitar: stripped {sp_before} SP events")
                else:
                    stats.append("nothing to strip")

                new_tracks.append(_build_track("PART GUITAR", clean))

        elif name == "PART DRUMS":
            # DRUMS: do NOT patch — Expert was hand-modified and must be preserved untouched
            new_tracks.append(tr)

        else:
            new_tracks.append(tr)

    out = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat)
    out.tracks.extend(new_tracks)
    out.save(str(notes_mid))

    return " | ".join(stats) if stats else "nothing to strip"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Patch Songs/*/notes.mid from original/custom charts.")
    parser.add_argument(
        "--song",
        metavar="SUBSTRING",
        help="Only patch folders whose name contains this substring (case-sensitive).",
    )
    args = parser.parse_args()

    print(f"Patching songs in: {SONGS_DIR}\n")

    for song_dir in sorted(SONGS_DIR.iterdir()):
        if args.song is not None and args.song not in song_dir.name:
            continue
        notes_mid = song_dir / "notes.mid"
        if not notes_mid.exists():
            continue

        chart_path = CUSTOM_DIR / song_dir.name / "notes.chart"
        if not chart_path.exists():
            chart_path = None

        print(f"  {song_dir.name}")
        try:
            result = patch_song(notes_mid, chart_path)
            print(f"    {result}")
        except Exception as exc:
            print(f"    ERROR: {exc}")

    print("\nAll done.")


if __name__ == "__main__":
    main()

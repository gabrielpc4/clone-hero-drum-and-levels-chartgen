# -*- coding: utf-8 -*-
"""
Generate or replace `PART VOCALS` in an existing notes.mid from a downloaded
dated source MIDI. Creates a timestamped backup first, then overwrites in place
through a temporary file.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_src_root = os.path.join(_repo_root, "src")
_src_chart = os.path.join(_src_root, "chart_generation")
_src_songsterr = os.path.join(_src_root, "songsterr_parsing")
_diff_tools = os.path.join(_repo_root, "tools", "difficulty_classification")
for _path_value in (_src_root, _src_chart, _src_songsterr, _diff_tools):
    if _path_value not in sys.path:
        sys.path.insert(0, _path_value)

from midi_repair import load_midi_file  # noqa: E402
from songsterr_import.vocal_pipeline import generate_songsterr_vocals_synced_to_measure_markers  # noqa: E402
from classification_logic import apply_vocal_classification_to_song_ini  # noqa: E402
from classification_logic import build_classification_report  # noqa: E402


def _log(message: str) -> None:
    print("[gen-vocals] " + message, flush=True)


def _make_backup_path(notes_path: str) -> str:
    parent = os.path.dirname(notes_path)
    base = os.path.splitext(os.path.basename(notes_path))[0]
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    candidate = os.path.join(parent, f"{base}.{stamp}.backup")
    if not os.path.exists(candidate):
        return candidate

    suffix = os.urandom(4).hex()
    return os.path.join(parent, f"{base}.{stamp}.{suffix}.backup")


def _estimate_vocal_score(repo_root: Path, folder_name: str) -> int | None:
    report = build_classification_report(repo_root)

    for row in report["classification_rows"]:
        if row["folder"].lower() == folder_name.lower():
            return row["diff_vocals"]

    return None


def _apply_vocal_score_to_song_ini(song_ini_path: Path, vocal_score: int | None) -> None:
    if not song_ini_path.is_file():
        _log(f"SKIP song.ini not found: {song_ini_path}")
        return

    if vocal_score is None:
        _log(f"SKIP diff_vocals update without score: {song_ini_path}")
        return

    apply_vocal_classification_to_song_ini(song_ini_path, vocal_score)
    _log(f"song.ini diff_vocals={vocal_score}: {song_ini_path}")


def process_one_notes_mid(
    target_notes_path: str,
    source_mid_path: str,
    custom_song_dir: str | None = None,
) -> int:
    target_notes_path = os.path.normpath(os.path.abspath(target_notes_path))
    source_mid_path = os.path.normpath(os.path.abspath(source_mid_path))

    if not os.path.isfile(target_notes_path):
        _log(f"ERROR: target notes.mid not found: {target_notes_path}")
        return 1

    if not os.path.isfile(source_mid_path):
        _log(f"ERROR: source MIDI not found: {source_mid_path}")
        return 1

    _log(f"target_notes: {target_notes_path}")
    _log(f"source_mid: {source_mid_path}")

    backup_path = _make_backup_path(target_notes_path)
    _log(f"backup: {backup_path}")
    try:
        shutil.copy2(target_notes_path, backup_path)
    except OSError as ex:
        _log(f"ERROR: backup failed: {ex}")
        return 1

    parent = os.path.dirname(target_notes_path)
    fd, tmp_path = tempfile.mkstemp(
        prefix="notes_gen_vocals_",
        suffix=".mid",
        dir=parent,
    )
    os.close(fd)

    try:
        source_mid = load_midi_file(source_mid_path)
        target_mid = load_midi_file(target_notes_path)
        generation_result = generate_songsterr_vocals_synced_to_measure_markers(
            source_mid,
            target_mid,
            initial_offset_ticks=0,
        )
        generation_result.output_mid.save(tmp_path)
        os.replace(tmp_path, target_notes_path)
        _log(f"source_track: {generation_result.source_track_name}")
        _log(f"vocal_notes: {generation_result.note_count}")
        _log(f"vocal_phrases: {generation_result.phrase_count}")
        _log("OK: notes.mid updated in place")
    except Exception as ex:
        _log(f"ERROR: {type(ex).__name__}: {ex}")
        _log("traceback:\n" + traceback.format_exc())
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return 1

    custom_song_path = Path(custom_song_dir).resolve() if custom_song_dir else None
    if custom_song_path is None:
        custom_song_path = Path(source_mid_path).resolve().parent

    vocal_score = None
    if custom_song_path.name:
        vocal_score = _estimate_vocal_score(Path(_repo_root), custom_song_path.name)
        if vocal_score is None:
            _log(f"WARN: diff_vocals not found for folder {custom_song_path.name!r}")
        else:
            _log(f"diff_vocals: {vocal_score}")

    _apply_vocal_score_to_song_ini(custom_song_path / "song.ini", vocal_score)
    _apply_vocal_score_to_song_ini(Path(target_notes_path).with_name("song.ini"), vocal_score)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PART VOCALS in an existing notes.mid")
    parser.add_argument("target_notes_mid", help="Path to the target notes.mid to update in place")
    parser.add_argument("source_mid", help="Path to the dated source MIDI that contains the vocal track")
    parser.add_argument(
        "--custom-song-dir",
        default=None,
        help="Optional custom song folder under original/custom used to update song.ini metadata",
    )
    args = parser.parse_args()
    return process_one_notes_mid(
        args.target_notes_mid,
        args.source_mid,
        custom_song_dir=args.custom_song_dir,
    )


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
Regenerate Easy / Medium / Hard for PART GUITAR and PART DRUMS from Expert in an existing notes.mid.
Creates a timestamped backup next to the file, then writes the result in place (via a temp file + os.replace).

With --scan-songs, runs on every subfolder of Songs/ that has notes.mid, skipping Harmonix (official) charts.
"""
from __future__ import annotations

import argparse
import configparser
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_src_chart = os.path.join(_repo_root, "src", "chart_generation")
_src_diff = os.path.join(_repo_root, "src", "difficulty_generation")
for _p in (_src_chart, _src_diff):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from midi_writer import write_reduced_midi  # noqa: E402


def _log(message: str) -> None:
    print("[gen-diff] " + message, flush=True)


def _make_backup_path(notes_path: str) -> str:
    parent = os.path.dirname(notes_path)
    base = os.path.splitext(os.path.basename(notes_path))[0]
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    candidate = os.path.join(parent, f"{base}.{stamp}.backup")
    if not os.path.exists(candidate):
        return candidate
    suffix = os.urandom(4).hex()
    return os.path.join(parent, f"{base}.{stamp}.{suffix}.backup")


def is_harmonix_pack_song(song_dir: str) -> bool:
    """True for official RB/Harmonix content we should not auto-regenerate from Expert."""
    base = os.path.basename(song_dir.rstrip("/\\"))
    if base.lower().endswith(" (harmonix)"):
        return True
    ini = os.path.join(song_dir, "song.ini")
    if not os.path.isfile(ini):
        return False
    try:
        cp = configparser.ConfigParser(interpolation=None)
        read_ok = cp.read(ini, encoding="utf-8-sig")
        if not read_ok or not cp.has_section("song"):
            return False
        ch = cp.get("song", "charter", fallback="").strip().lower()
        return ch == "harmonix"
    except (OSError, configparser.Error, UnicodeDecodeError) as ex:
        _log(f"WARN: song.ini not parsed for {base!r} ({ex}); not treating as Harmonix")
        return False


def process_one_notes_mid(notes_path: str) -> int:
    """
    Backs up and regenerates a single notes.mid. Logs with [gen-diff] prefix.
    Returns 0 on success, 1 on failure.
    """
    notes_path = os.path.normpath(os.path.abspath(notes_path))
    if not os.path.isfile(notes_path):
        _log(f"ERROR: file not found: {notes_path}")
        return 1

    _log(f"input: {notes_path}")

    backup_path = _make_backup_path(notes_path)
    _log(f"backup: {backup_path}")
    try:
        shutil.copy2(notes_path, backup_path)
    except OSError as ex:
        _log(f"ERROR: backup failed: {ex}")
        return 1

    parent = os.path.dirname(notes_path)
    fd, tmp_path = tempfile.mkstemp(
        prefix="notes_gen_diff_",
        suffix=".mid",
        dir=parent,
    )
    os.close(fd)
    try:
        info = write_reduced_midi(
            notes_path,
            tmp_path,
            replace_diffs=("Easy", "Medium", "Hard"),
            parts=("PART GUITAR", "PART DRUMS"),
        )
        _log(f"ticks_per_beat: {info.get('ticks_per_beat')}")
        npp = info.get("notes_per_part_diff") or {}
        for part in ("PART GUITAR", "PART DRUMS"):
            if part in npp:
                _log(f"{part} generated note counts (E/M/H): {npp[part]}")
        os.replace(tmp_path, notes_path)
        _log("OK: notes.mid updated in place")
        return 0
    except Exception as ex:
        _log(f"ERROR: {type(ex).__name__}: {ex}")
        _log("traceback:\n" + traceback.format_exc())
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return 1


def run_scan_songs(songs_dir: str) -> int:
    """
    For each subfolder of songs_dir, skip Harmonix; if notes.mid exists, run process_one_notes_mid.
    """
    songs_dir = os.path.normpath(os.path.abspath(songs_dir))
    if not os.path.isdir(songs_dir):
        _log(f"ERROR: Songs directory not found: {songs_dir}")
        return 1

    _log(f"batch: scanning {songs_dir}")
    ok_count = 0
    skip_harmonix = 0
    skip_no_notes = 0
    fail_count = 0
    subdirs = [e for e in os.listdir(songs_dir) if os.path.isdir(os.path.join(songs_dir, e))]
    subdirs.sort(key=str.lower)
    for entry in subdirs:
        song_dir = os.path.join(songs_dir, entry)
        notes = os.path.join(song_dir, "notes.mid")
        if is_harmonix_pack_song(song_dir):
            _log(f"SKIP (Harmonix): {entry}")
            skip_harmonix += 1
            continue
        if not os.path.isfile(notes):
            _log(f"SKIP (no notes.mid): {entry}")
            skip_no_notes += 1
            continue
        _log(f"--- {entry} ---")
        code = process_one_notes_mid(notes)
        if code == 0:
            ok_count += 1
        else:
            fail_count += 1
    _log(
        f"summary: {ok_count} ok, {skip_harmonix} skipped (Harmonix), "
        f"{skip_no_notes} skipped (no notes.mid), {fail_count} failed"
    )
    if fail_count > 0:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate E/M/H from Expert in notes.mid")
    parser.add_argument("notes_mid", nargs="?", default=None, help="Path to a single notes.mid to update in place")
    parser.add_argument(
        "--scan-songs",
        action="store_true",
        help="Process every song folder under --songs-dir (or repository Songs/) except Harmonix; backup each",
    )
    parser.add_argument(
        "--songs-dir",
        default=None,
        help="Override Songs root (default: <repo>/Songs next to this script's parent)",
    )
    args = parser.parse_args()

    if args.scan_songs:
        default_songs = os.path.join(_repo_root, "Songs")
        out_dir = os.path.normpath(args.songs_dir) if args.songs_dir else default_songs
        return run_scan_songs(out_dir)

    if not args.notes_mid:
        parser.error("pass notes_mid or use --scan-songs")
    return process_one_notes_mid(args.notes_mid)


if __name__ == "__main__":
    sys.exit(main())

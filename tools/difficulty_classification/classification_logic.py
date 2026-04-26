from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import mido

from baseline_data import BASELINE_DRUM_DIFFS
from baseline_data import BASELINE_GUITAR_DIFFS
from baseline_data import GUITAR_SCALE_MAPPING
from baseline_data import MANUAL_DRUM_OVERRIDES
from baseline_data import MANUAL_GUITAR_OVERRIDES
from baseline_data import MANUAL_VOCAL_OVERRIDES

IGNORE_MIDI_FILENAMES = {
    "notes.mid",
    "notes.gen.mid",
    "notes.generated.mid",
    "notes.songsterr.mid",
    "notes.measure-debug.mid",
}

SONG_FOLDER_RELATIVE_PATHS = [
    Path("original") / "custom",
    Path("original") / "harmonix",
]

KICK_PITCHES = {35, 36}
SNARE_PITCHES = {37, 38, 40}
CYMBAL_PITCHES = {17, 18, 19, 20, 21, 42, 46, 49, 51, 52, 53, 55, 56, 57, 67, 68}
TOM_PITCHES = {41, 43, 45, 47, 48, 50}

DRUM_WEIGHT_BY_METRIC = {
    "events_per_beat": 0.20,
    "raw_hits_per_beat": 0.20,
    "kick_density": 0.20,
    "tom_ratio": 0.15,
    "simultaneous_ratio": 0.10,
    "kick_run_half": 0.10,
    "raw_hit_count": 0.05,
}

VOCAL_WEIGHT_BY_METRIC = {
    "pitch_range": 0.30,
    "leap_ratio": 0.20,
    "long_note_ratio": 0.20,
    "very_long_note_ratio": 0.10,
    "raw_notes_per_beat": 0.10,
    "fast_ratio": 0.05,
    "run_half": 0.05,
}


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def iter_song_folders(repo_root: Path) -> List[Path]:
    folder_paths: List[Path] = []

    for relative_path in SONG_FOLDER_RELATIVE_PATHS:
        base_folder = repo_root / relative_path

        if not base_folder.exists():
            continue

        for folder_path in sorted(path for path in base_folder.iterdir() if path.is_dir()):
            folder_paths.append(folder_path)

    return folder_paths


def choose_songsterr_midi(folder_path: Path) -> Path:
    midi_paths: List[Path] = []

    for midi_path in sorted(folder_path.glob("*.mid")):
        midi_name = midi_path.name

        if midi_name in IGNORE_MIDI_FILENAMES:
            continue

        if midi_name.startswith("notes.generated-"):
            continue

        if midi_name[:-4].count("-") < 2:
            continue

        midi_paths.append(midi_path)

    if not midi_paths:
        raise FileNotFoundError(f"No Songsterr MIDI found in {folder_path}")

    return midi_paths[-1]


def summarize_track(track: mido.MidiTrack) -> Tuple[str, int, set[int]]:
    track_name = ""
    note_count = 0
    channel_values: set[int] = set()

    for message in track:
        if message.type == "track_name" and not track_name:
            track_name = message.name

        if message.type == "note_on" and message.velocity > 0:
            note_count += 1
            channel_values.add(message.channel)

    return track_name, note_count, channel_values


def decode_note_pairs(track: mido.MidiTrack) -> Tuple[str, List[dict]]:
    absolute_tick = 0
    open_notes: Dict[Tuple[int, int], List[Tuple[int, int]]] = defaultdict(list)
    note_pairs: List[dict] = []
    track_name = ""

    for message in track:
        absolute_tick += message.time

        if message.type == "track_name" and not track_name:
            track_name = message.name

        if message.type == "note_on" and message.velocity > 0:
            open_notes[(message.channel, message.note)].append((absolute_tick, message.velocity))
            continue

        if message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            note_key = (message.channel, message.note)

            if not open_notes[note_key]:
                continue

            start_tick, velocity_value = open_notes[note_key].pop(0)
            note_pairs.append(
                {
                    "start_tick": start_tick,
                    "end_tick": absolute_tick,
                    "pitch": message.note,
                    "channel": message.channel,
                    "velocity": velocity_value,
                }
            )

    return track_name, note_pairs


def group_note_events(note_pairs: List[dict]) -> List[dict]:
    note_pairs_by_tick: Dict[int, List[dict]] = defaultdict(list)

    for note_pair in note_pairs:
        note_pairs_by_tick[note_pair["start_tick"]].append(note_pair)

    grouped_events: List[dict] = []

    for tick_value in sorted(note_pairs_by_tick):
        bucket = note_pairs_by_tick[tick_value]
        grouped_events.append(
            {
                "tick": tick_value,
                "pitches": sorted(note_pair["pitch"] for note_pair in bucket),
                "end_tick": max(note_pair["end_tick"] for note_pair in bucket),
                "size": len(bucket),
            }
        )

    return grouped_events


def notes_per_beat_from_events(grouped_events: List[dict], ticks_per_beat: int) -> float:
    if len(grouped_events) < 2:
        return 0.0

    span_beats = (grouped_events[-1]["tick"] - grouped_events[0]["tick"]) / ticks_per_beat

    if span_beats <= 0:
        return 0.0

    return len(grouped_events) / span_beats


def raw_density_from_pairs(note_pairs: List[dict], ticks_per_beat: int) -> float:
    if len(note_pairs) < 2:
        return 0.0

    ordered_pairs = sorted(note_pairs, key=lambda note_pair: note_pair["start_tick"])
    span_beats = (ordered_pairs[-1]["start_tick"] - ordered_pairs[0]["start_tick"]) / ticks_per_beat

    if span_beats <= 0:
        return 0.0

    return len(ordered_pairs) / span_beats


def longest_run(onset_ticks: List[int], max_gap_ticks: float) -> int:
    if not onset_ticks:
        return 0

    best_length = 1
    current_length = 1

    for index in range(1, len(onset_ticks)):
        if onset_ticks[index] - onset_ticks[index - 1] <= max_gap_ticks:
            current_length += 1
        else:
            best_length = max(best_length, current_length)
            current_length = 1

    return max(best_length, current_length)


def fast_ratio(onset_ticks: List[int], threshold_ticks: float) -> float:
    if len(onset_ticks) < 2:
        return 0.0

    fast_count = sum(
        1
        for index in range(1, len(onset_ticks))
        if onset_ticks[index] - onset_ticks[index - 1] <= threshold_ticks
    )

    return fast_count / (len(onset_ticks) - 1)


def choose_guitar_track(midi_file: mido.MidiFile) -> Optional[mido.MidiTrack]:
    scored_tracks: List[Tuple[int, int]] = []

    for track_index, track in enumerate(midi_file.tracks):
        track_name, note_count, channel_values = summarize_track(track)
        lowered_name = track_name.lower()

        if note_count == 0:
            continue

        if 9 in channel_values:
            continue

        if any(
            token in lowered_name
            for token in [
                "bass",
                "shavo",
                "vocal",
                "serj",
                "drum",
                "john",
                "string",
                "arrangement",
                "choir",
                "synth",
                "keyboard",
                "piano",
            ]
        ):
            continue

        score_value = note_count

        if "guitar" in lowered_name or "daron" in lowered_name:
            score_value += 1000

        if any(token in lowered_name for token in ["lead", "solo", "main", "left", "right", "rhythm"]):
            score_value += 500

        if any(token in lowered_name for token in ["clean", "acoustic", "extra", "overdub", "fx"]):
            score_value -= 300

        scored_tracks.append((score_value, track_index))

    if not scored_tracks:
        return None

    best_index = max(scored_tracks)[1]
    return midi_file.tracks[best_index]


def choose_drum_track(midi_file: mido.MidiFile) -> Optional[mido.MidiTrack]:
    scored_tracks: List[Tuple[int, int, set[int]]] = []

    for track_index, track in enumerate(midi_file.tracks):
        track_name, note_count, channel_values = summarize_track(track)
        lowered_name = track_name.lower()

        if note_count == 0:
            continue

        score_value = note_count

        if 9 in channel_values:
            score_value += 5000

        if "drum" in lowered_name or "john" in lowered_name or "perc" in lowered_name:
            score_value += 500

        scored_tracks.append((score_value, track_index, channel_values))

    if not scored_tracks:
        return None

    _, best_index, best_channels = max(scored_tracks)

    if 9 not in best_channels:
        return None

    return midi_file.tracks[best_index]


def choose_vocal_track(midi_file: mido.MidiFile) -> Optional[mido.MidiTrack]:
    scored_tracks: List[Tuple[int, int]] = []

    for track_index, track in enumerate(midi_file.tracks):
        track_name, note_count, _ = summarize_track(track)
        lowered_name = track_name.lower()

        if note_count == 0:
            continue

        if "vocal" not in lowered_name and "lyrics" not in lowered_name:
            continue

        score_value = note_count

        if lowered_name == "vocals" or "lead vocals" in lowered_name or "lead vocal" in lowered_name:
            score_value += 1000

        if "backup" in lowered_name or "backing" in lowered_name or "harmony" in lowered_name:
            score_value -= 500

        scored_tracks.append((score_value, track_index))

    if not scored_tracks:
        return None

    best_index = max(scored_tracks)[1]
    return midi_file.tracks[best_index]


def categorize_drum_pitch(pitch_value: int) -> str:
    if pitch_value in KICK_PITCHES:
        return "kick"

    if pitch_value in SNARE_PITCHES:
        return "snare"

    if pitch_value in CYMBAL_PITCHES:
        return "cymbal"

    if pitch_value in TOM_PITCHES:
        return "tom"

    return "other"


def parse_drum_metrics(track: Optional[mido.MidiTrack], ticks_per_beat: int) -> Optional[dict]:
    if track is None:
        return None

    track_name, note_pairs = decode_note_pairs(track)
    drum_pairs = [note_pair for note_pair in note_pairs if note_pair["channel"] == 9]

    if not drum_pairs:
        return None

    note_pairs_by_tick: Dict[int, List[dict]] = defaultdict(list)

    for note_pair in drum_pairs:
        note_pairs_by_tick[note_pair["start_tick"]].append(note_pair)

    event_ticks = sorted(note_pairs_by_tick)
    kick_ticks: List[int] = []
    category_counts: Dict[str, int] = defaultdict(int)
    simultaneous_count = 0

    for tick_value in event_ticks:
        bucket = note_pairs_by_tick[tick_value]

        if len(bucket) >= 2:
            simultaneous_count += 1

        for note_pair in bucket:
            category_name = categorize_drum_pitch(note_pair["pitch"])
            category_counts[category_name] += 1

            if category_name == "kick":
                kick_ticks.append(note_pair["start_tick"])

    event_rows = [{"tick": tick_value} for tick_value in event_ticks]

    return {
        "track_name": track_name,
        "event_count": len(event_ticks),
        "raw_hit_count": len(drum_pairs),
        "events_per_beat": notes_per_beat_from_events(event_rows, ticks_per_beat),
        "raw_hits_per_beat": raw_density_from_pairs(drum_pairs, ticks_per_beat),
        "kick_count": category_counts["kick"],
        "snare_count": category_counts["snare"],
        "cymbal_count": category_counts["cymbal"],
        "tom_count": category_counts["tom"],
        "other_count": category_counts["other"],
        "kick_density": raw_density_from_pairs(
            [note_pair for note_pair in drum_pairs if categorize_drum_pitch(note_pair["pitch"]) == "kick"],
            ticks_per_beat,
        ),
        "tom_ratio": category_counts["tom"] / max(1, len(drum_pairs)),
        "simultaneous_ratio": simultaneous_count / max(1, len(event_ticks)),
        "kick_run_quarter": longest_run(sorted(kick_ticks), ticks_per_beat / 4),
        "kick_run_half": longest_run(sorted(kick_ticks), ticks_per_beat / 2),
    }


def parse_vocal_metrics(track: Optional[mido.MidiTrack], ticks_per_beat: int) -> Optional[dict]:
    if track is None:
        return None

    track_name, note_pairs = decode_note_pairs(track)
    vocal_pairs = [note_pair for note_pair in note_pairs if note_pair["channel"] != 9]
    grouped_events = group_note_events(vocal_pairs)

    if not grouped_events:
        return None

    onset_ticks = [grouped_event["tick"] for grouped_event in grouped_events]
    durations = [grouped_event["end_tick"] - grouped_event["tick"] for grouped_event in grouped_events]
    representative_pitches = [
        int(round(sum(grouped_event["pitches"]) / len(grouped_event["pitches"])))
        for grouped_event in grouped_events
    ]

    leap_count = 0

    for index in range(1, len(representative_pitches)):
        if abs(representative_pitches[index] - representative_pitches[index - 1]) >= 7:
            leap_count += 1

    return {
        "track_name": track_name,
        "event_count": len(grouped_events),
        "raw_note_count": len(vocal_pairs),
        "events_per_beat": notes_per_beat_from_events(grouped_events, ticks_per_beat),
        "raw_notes_per_beat": raw_density_from_pairs(vocal_pairs, ticks_per_beat),
        "pitch_range": max(representative_pitches) - min(representative_pitches),
        "long_note_ratio": sum(1 for duration in durations if duration >= ticks_per_beat) / len(durations),
        "very_long_note_ratio": sum(1 for duration in durations if duration >= ticks_per_beat * 2) / len(durations),
        "leap_ratio": leap_count / max(1, len(representative_pitches) - 1),
        "fast_ratio": fast_ratio(onset_ticks, ticks_per_beat / 4),
        "run_half": longest_run(onset_ticks, ticks_per_beat / 2),
    }


def build_songsterr_metrics(repo_root: Path) -> dict:
    rows: List[dict] = []
    exceptions = {
        "missing_drums": [],
        "missing_vocals": [],
        "missing_guitar": [],
    }

    for folder_path in iter_song_folders(repo_root):
        songsterr_midi_path = choose_songsterr_midi(folder_path)
        midi_file = mido.MidiFile(songsterr_midi_path)

        guitar_track = choose_guitar_track(midi_file)
        drum_track = choose_drum_track(midi_file)
        vocal_track = choose_vocal_track(midi_file)

        drum_metrics = parse_drum_metrics(drum_track, midi_file.ticks_per_beat)
        vocal_metrics = parse_vocal_metrics(vocal_track, midi_file.ticks_per_beat)

        guitar_track_name = None

        if guitar_track is not None:
            guitar_track_name = summarize_track(guitar_track)[0]
        else:
            exceptions["missing_guitar"].append(folder_path.name)

        if drum_metrics is None:
            exceptions["missing_drums"].append(folder_path.name)

        if vocal_metrics is None:
            exceptions["missing_vocals"].append(folder_path.name)

        rows.append(
            {
                "folder": folder_path.name,
                "collection": folder_path.parent.name,
                "midi": songsterr_midi_path.name,
                "guitar_track_name": guitar_track_name,
                "drums": drum_metrics,
                "vocals": vocal_metrics,
            }
        )

    rows.sort(key=lambda row: row["folder"])
    exceptions["missing_drums"].sort()
    exceptions["missing_vocals"].sort()
    exceptions["missing_guitar"].sort()

    return {
        "rows": rows,
        "exceptions": exceptions,
    }


def percentile(sorted_values: List[float], value: float) -> float:
    return sum(1 for current in sorted_values if current <= value) / len(sorted_values)


def weighted_scores(rows: List[dict], instrument_name: str, weight_by_metric: Dict[str, float]) -> Dict[str, float]:
    available_rows = [row for row in rows if row[instrument_name] is not None]

    if not available_rows:
        return {}

    metric_values: Dict[str, List[float]] = {}

    for metric_name in weight_by_metric:
        metric_values[metric_name] = sorted(row[instrument_name][metric_name] for row in available_rows)

    folder_scores: Dict[str, float] = {}

    for row in available_rows:
        total_score = 0.0

        for metric_name, weight_value in weight_by_metric.items():
            metric_value = row[instrument_name][metric_name]
            total_score += percentile(metric_values[metric_name], metric_value) * weight_value

        folder_scores[row["folder"]] = round(total_score, 4)

    return folder_scores


def bucket_drum_score(score_value: float) -> int:
    if score_value <= 0.20:
        return 1

    if score_value <= 0.32:
        return 2

    if score_value <= 0.48:
        return 3

    if score_value <= 0.64:
        return 4

    return 5


def bucket_vocal_score(score_value: float) -> int:
    if score_value <= 0.24:
        return 1

    if score_value <= 0.36:
        return 2

    if score_value <= 0.48:
        return 3

    if score_value <= 0.58:
        return 4

    if score_value <= 0.68:
        return 5

    return 6


def detect_text_encoding(file_path: Path) -> str:
    try:
        file_path.read_text(encoding="utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def load_song_ini(song_ini_path: Path) -> Tuple[List[str], Dict[str, str], str]:
    encoding_name = detect_text_encoding(song_ini_path)
    lines = song_ini_path.read_text(encoding=encoding_name).splitlines()
    values: Dict[str, str] = {}

    for line in lines:
        if "=" not in line:
            continue

        key_name, value = [part.strip() for part in line.split("=", 1)]
        values[key_name] = value

    return lines, values, encoding_name


def build_final_scores(
    folder_name: str,
    raw_drum_scores: Dict[str, float],
    raw_vocal_scores: Dict[str, float],
) -> Tuple[int, Optional[int], Optional[int], dict]:
    debug_info = {
        "guitar_source": None,
        "drum_source": None,
        "vocal_source": None,
        "raw_drum_score": raw_drum_scores.get(folder_name),
        "raw_vocal_score": raw_vocal_scores.get(folder_name),
    }

    if folder_name in MANUAL_GUITAR_OVERRIDES:
        guitar_score = MANUAL_GUITAR_OVERRIDES[folder_name]
        debug_info["guitar_source"] = "manual_override"
    else:
        baseline_guitar = BASELINE_GUITAR_DIFFS.get(folder_name)

        if baseline_guitar is None:
            guitar_score = 3
            debug_info["guitar_source"] = "fallback_default"
        elif baseline_guitar == 0:
            guitar_score = 3
            debug_info["guitar_source"] = "zero_baseline_fallback"
        else:
            guitar_score = GUITAR_SCALE_MAPPING[baseline_guitar]
            debug_info["guitar_source"] = "baseline_mapping"

    if folder_name in MANUAL_DRUM_OVERRIDES:
        drum_score = MANUAL_DRUM_OVERRIDES[folder_name]
        debug_info["drum_source"] = "manual_override"
    elif folder_name in BASELINE_DRUM_DIFFS:
        drum_score = BASELINE_DRUM_DIFFS[folder_name]
        debug_info["drum_source"] = "baseline_existing"
    elif folder_name in raw_drum_scores:
        drum_score = bucket_drum_score(raw_drum_scores[folder_name])
        debug_info["drum_source"] = "songsterr_metrics"
    else:
        drum_score = None
        debug_info["drum_source"] = "missing_track"

    if folder_name in MANUAL_VOCAL_OVERRIDES:
        vocal_score = MANUAL_VOCAL_OVERRIDES[folder_name]
        debug_info["vocal_source"] = "manual_override"
    elif folder_name in raw_vocal_scores:
        vocal_score = bucket_vocal_score(raw_vocal_scores[folder_name])
        debug_info["vocal_source"] = "songsterr_metrics"
    else:
        vocal_score = None
        debug_info["vocal_source"] = "missing_track"

    return guitar_score, drum_score, vocal_score, debug_info


def build_classification_report(repo_root: Path) -> dict:
    metrics_report = build_songsterr_metrics(repo_root)
    metric_rows = metrics_report["rows"]
    raw_drum_scores = weighted_scores(metric_rows, "drums", DRUM_WEIGHT_BY_METRIC)
    raw_vocal_scores = weighted_scores(metric_rows, "vocals", VOCAL_WEIGHT_BY_METRIC)
    classification_rows: List[dict] = []

    for folder_path in iter_song_folders(repo_root):
        song_ini_path = folder_path / "song.ini"
        _, _, encoding_name = load_song_ini(song_ini_path)
        guitar_score, drum_score, vocal_score, debug_info = build_final_scores(
            folder_path.name,
            raw_drum_scores,
            raw_vocal_scores,
        )
        metric_row = next(row for row in metric_rows if row["folder"] == folder_path.name)

        classification_rows.append(
            {
                "folder": folder_path.name,
                "collection": folder_path.parent.name,
                "song_ini_path": str(song_ini_path),
                "songsterr_midi": metric_row["midi"],
                "song_ini_encoding": encoding_name,
                "guitar_track_name": metric_row["guitar_track_name"],
                "drum_track_name": None if metric_row["drums"] is None else metric_row["drums"]["track_name"],
                "vocal_track_name": None if metric_row["vocals"] is None else metric_row["vocals"]["track_name"],
                "diff_guitar": guitar_score,
                "diff_drums_real": drum_score,
                "diff_vocals": vocal_score,
                "drum_metrics": metric_row["drums"],
                "vocal_metrics": metric_row["vocals"],
                "debug": debug_info,
            }
        )

    return {
        "repo_root": str(repo_root),
        "exceptions": metrics_report["exceptions"],
        "classification_rows": classification_rows,
    }


def apply_classification_to_song_ini(song_ini_path: Path, guitar_score: int, drum_score: Optional[int], vocal_score: Optional[int]) -> None:
    original_lines, _, encoding_name = load_song_ini(song_ini_path)
    filtered_lines: List[str] = []

    for line in original_lines:
        if "=" not in line:
            filtered_lines.append(line)
            continue

        key_name = line.split("=", 1)[0].strip()

        if key_name.startswith("diff_"):
            continue

        if key_name in {"five_lane_drums", "pro_drums"}:
            continue

        filtered_lines.append(line)

    insert_index: Optional[int] = None

    for index, line in enumerate(filtered_lines):
        if line.strip().startswith("song_length ="):
            insert_index = index + 1
            break

    if insert_index is None:
        for index, line in enumerate(filtered_lines):
            if line.strip().startswith("year ="):
                insert_index = index + 1
                break

    if insert_index is None:
        if filtered_lines:
            insert_index = 1
        else:
            insert_index = 0

    difficulty_lines = [f"diff_guitar = {guitar_score}"]

    if drum_score is not None:
        difficulty_lines.append(f"diff_drums_real = {drum_score}")

    if vocal_score is not None:
        difficulty_lines.append(f"diff_vocals = {vocal_score}")

    difficulty_lines.append("five_lane_drums = 0")
    difficulty_lines.append("pro_drums = True")

    updated_lines = filtered_lines[:insert_index] + difficulty_lines + filtered_lines[insert_index:]
    song_ini_path.write_text("\n".join(updated_lines) + "\n", encoding=encoding_name)


def apply_classification_report(report: dict) -> None:
    for row in report["classification_rows"]:
        apply_classification_to_song_ini(
            Path(row["song_ini_path"]),
            row["diff_guitar"],
            row["diff_drums_real"],
            row["diff_vocals"],
        )


def write_report_json(report: dict, output_path: Path) -> None:
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report_summary_lines(report: dict) -> List[str]:
    summary_lines: List[str] = []
    rows = report["classification_rows"]
    exceptions = report["exceptions"]

    summary_lines.append(f"songs={len(rows)}")
    summary_lines.append(f"missing_drums={len(exceptions['missing_drums'])}")
    summary_lines.append(f"missing_vocals={len(exceptions['missing_vocals'])}")
    summary_lines.append(f"missing_guitar={len(exceptions['missing_guitar'])}")

    for instrument_key in ["diff_guitar", "diff_drums_real", "diff_vocals"]:
        counts: Dict[str, int] = defaultdict(int)

        for row in rows:
            value = row[instrument_key]

            if value is None:
                counts["missing"] += 1
            else:
                counts[str(value)] += 1

        ordered_keys = sorted(counts, key=lambda key_name: (key_name == "missing", key_name))
        counts_text = ", ".join(f"{key_name}:{counts[key_name]}" for key_name in ordered_keys)
        summary_lines.append(f"{instrument_key} -> {counts_text}")

    return summary_lines


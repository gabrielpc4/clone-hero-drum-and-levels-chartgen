"""
Importa um MIDI de transcrição externa (Songsterr/Guitar Pro/MuseScore) e gera
PART DRUMS Expert no formato Harmonix/Clone Hero.

O sync agora acontece em três camadas:
1. tick src -> segundos src, usando o tempo map do MIDI externo
2. escolha de uma track melódica src e alinhamento grosseiro com PART GUITAR ref
3. warp temporal piecewise-linear para corrigir drift ao longo da música

As regras de mapeamento GM -> lanes RB continuam iguais.
"""
from __future__ import annotations

import argparse
import os
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from statistics import median
from typing import Callable, Dict, List, Optional, Tuple

import mido

sys.path.insert(0, os.path.dirname(__file__))

from parse_chart import TempoMap, build_tempo_map, parse_part
from parse_drums import LANE_BLUE, LANE_GREEN, LANE_KICK, LANE_SNARE, LANE_YELLOW

GM_TO_RB: Dict[int, Tuple[int, bool]] = {
    35: (LANE_KICK, False),
    36: (LANE_KICK, False),
    37: (LANE_SNARE, False),
    38: (LANE_SNARE, False),
    39: (LANE_SNARE, False),
    40: (LANE_SNARE, False),
    42: (LANE_YELLOW, True),
    44: (LANE_YELLOW, True),
    46: (LANE_BLUE, True),
    49: (LANE_GREEN, True),
    51: (LANE_BLUE, True),
    52: (LANE_GREEN, True),
    53: (LANE_BLUE, True),
    55: (LANE_GREEN, True),
    57: (LANE_GREEN, True),
    59: (LANE_BLUE, True),
}

TOM_PITCHES = (41, 43, 45, 47, 48, 50)
SYNC_PRIMARY_HINTS = ("guitar", "ibanez", "gibson", "iceman", "strat", "tele", "fender", "lead", "rhythm")
SYNC_SECONDARY_HINTS = ("bass", "thunderbird")
SYNC_EXCLUDED_HINTS = ("drum", "perc", "vocal", "voice", "keys", "keyboard", "piano", "strings", "tempo", "conductor", "event")


@dataclass
class SyncCandidate:
    track_index: int
    track_name: str
    hint_rank: int
    onset_ticks: List[int]
    onset_seconds: List[float]
    coarse_shift_seconds: float = 0.0
    coarse_match_count: int = 0
    coarse_mean_error_seconds: float = 0.0
    warped_match_count: int = 0

    @property
    def onset_count(self) -> int:
        return len(self.onset_seconds)


@dataclass
class WarpAnchor:
    source_seconds: float
    reference_seconds: float
    match_count: int


@dataclass
class TimeWarp:
    anchors: List[WarpAnchor]
    base_shift_seconds: float

    def map_seconds(self, source_seconds: float) -> float:
        if not self.anchors:
            return source_seconds + self.base_shift_seconds

        if source_seconds <= self.anchors[0].source_seconds:
            delta_seconds = self.anchors[0].reference_seconds - self.anchors[0].source_seconds

            return source_seconds + delta_seconds

        if source_seconds >= self.anchors[-1].source_seconds:
            delta_seconds = self.anchors[-1].reference_seconds - self.anchors[-1].source_seconds

            return source_seconds + delta_seconds

        anchor_positions = [anchor.source_seconds for anchor in self.anchors]
        right_index = bisect_right(anchor_positions, source_seconds)
        left_anchor = self.anchors[right_index - 1]
        right_anchor = self.anchors[right_index]
        source_gap_seconds = right_anchor.source_seconds - left_anchor.source_seconds

        if source_gap_seconds <= 0:
            delta_seconds = left_anchor.reference_seconds - left_anchor.source_seconds

            return source_seconds + delta_seconds

        progress = (source_seconds - left_anchor.source_seconds) / source_gap_seconds

        return left_anchor.reference_seconds + progress * (right_anchor.reference_seconds - left_anchor.reference_seconds)


@dataclass
class SyncSelection:
    sync_mode: str
    candidate: Optional[SyncCandidate]
    time_warp: TimeWarp
    base_match_count: int
    beat_span_ratio: Optional[float] = None


def build_tom_pitch_map(drum_track) -> Dict[int, int]:
    """{pitch_gm -> lane_rb} baseado nos toms usados: mais agudo=Y, medio=B, floor=G."""
    used_pitches = set()

    for message in drum_track:
        if message.type != "note_on":
            continue

        if message.velocity <= 0:
            continue

        if message.channel != 9:
            continue

        if message.note not in TOM_PITCHES:
            continue

        used_pitches.add(message.note)

    if not used_pitches:
        return {}

    sorted_desc = sorted(used_pitches, reverse=True)
    pitch_to_lane: Dict[int, int] = {}
    pitch_count = len(sorted_desc)

    if pitch_count == 1:
        pitch_to_lane[sorted_desc[0]] = LANE_YELLOW
    elif pitch_count == 2:
        pitch_to_lane[sorted_desc[0]] = LANE_YELLOW
        pitch_to_lane[sorted_desc[1]] = LANE_BLUE
    else:
        third_size = pitch_count / 3

        for index, pitch_value in enumerate(sorted_desc):
            if index < round(third_size):
                pitch_to_lane[pitch_value] = LANE_YELLOW
            elif index < round(2 * third_size):
                pitch_to_lane[pitch_value] = LANE_BLUE
            else:
                pitch_to_lane[pitch_value] = LANE_GREEN

    return pitch_to_lane


def classify_open_hat_mode(drum_track) -> bool:
    """True -> GM46 vira amarelo; False -> GM46 vira azul."""
    closed_count = sum(
        1
        for message in drum_track
        if message.type == "note_on"
        and message.velocity > 0
        and message.channel == 9
        and message.note == 42
    )
    open_count = sum(
        1
        for message in drum_track
        if message.type == "note_on"
        and message.velocity > 0
        and message.channel == 9
        and message.note == 46
    )
    total_count = closed_count + open_count

    if total_count == 0:
        return False

    return (open_count / total_count) >= 0.70


def _track_name(track: mido.MidiTrack) -> str:
    track_name = getattr(track, "name", "")

    if track_name:
        return track_name

    for message in track:
        if message.type == "track_name":
            return message.name

    return ""


def _hint_rank(track_name: str) -> int:
    lower_name = track_name.lower()

    if any(keyword in lower_name for keyword in SYNC_EXCLUDED_HINTS):
        return -1

    if any(keyword in lower_name for keyword in SYNC_PRIMARY_HINTS):
        return 3

    if any(keyword in lower_name for keyword in SYNC_SECONDARY_HINTS):
        return 2

    if lower_name.strip():
        return 1

    return 0


def _extract_non_drum_note_ticks(track: mido.MidiTrack) -> List[int]:
    absolute_tick = 0
    note_ticks: List[int] = []

    for message in track:
        absolute_tick += message.time

        if message.type != "note_on":
            continue

        if message.velocity <= 0:
            continue

        if message.channel == 9:
            continue

        note_ticks.append(absolute_tick)

    return note_ticks


def _collapse_onsets(note_ticks: List[int], tempo_map: TempoMap, merge_threshold_seconds: float = 0.04) -> Tuple[List[int], List[float]]:
    collapsed_ticks: List[int] = []
    collapsed_seconds: List[float] = []

    for note_tick in sorted(note_ticks):
        note_seconds = tempo_map.tick_to_seconds(note_tick)

        if collapsed_seconds and note_seconds - collapsed_seconds[-1] <= merge_threshold_seconds:
            continue

        collapsed_ticks.append(note_tick)
        collapsed_seconds.append(note_seconds)

    return collapsed_ticks, collapsed_seconds


def _reference_guitar_onsets(ref_mid: mido.MidiFile, ref_tempo_map: TempoMap) -> Tuple[List[int], List[float]]:
    part_charts = parse_part(ref_mid, "PART GUITAR")
    expert_chart = part_charts.get("Expert")

    if expert_chart is None or not expert_chart.notes:
        raise RuntimeError("PART GUITAR Expert nao encontrado no chart de referencia")

    onset_ticks = sorted({note.tick for note in expert_chart.notes})
    onset_seconds = [ref_tempo_map.tick_to_seconds(note_tick) for note_tick in onset_ticks]

    return onset_ticks, onset_seconds


def _source_sync_candidates(
    src_mid: mido.MidiFile,
    src_tempo_map: TempoMap,
    sync_track_index: Optional[int],
    sync_track_contains: Optional[str],
) -> List[SyncCandidate]:
    candidates: List[SyncCandidate] = []
    query_text = None

    if sync_track_contains is not None:
        query_text = sync_track_contains.lower()

    for track_index, track in enumerate(src_mid.tracks):
        track_name = _track_name(track)
        lower_name = track_name.lower()

        if sync_track_index is not None and track_index != sync_track_index:
            continue

        if query_text is not None and query_text not in lower_name:
            continue

        hint_rank = _hint_rank(track_name)

        if hint_rank < 0:
            continue

        note_ticks = _extract_non_drum_note_ticks(track)

        if len(note_ticks) < 24:
            continue

        onset_ticks, onset_seconds = _collapse_onsets(note_ticks, src_tempo_map)

        if len(onset_seconds) < 24:
            continue

        candidates.append(
            SyncCandidate(
                track_index=track_index,
                track_name=track_name,
                hint_rank=hint_rank,
                onset_ticks=onset_ticks,
                onset_seconds=onset_seconds,
            )
        )

    if sync_track_index is not None and not candidates:
        raise RuntimeError(f"Nenhuma track valida encontrada no indice {sync_track_index}")

    if sync_track_contains is not None and not candidates:
        raise RuntimeError(f"Nenhuma track valida contem '{sync_track_contains}'")

    return candidates


def _search_subset(onset_seconds: List[float], max_events: int = 240, max_seconds: float = 120.0) -> List[float]:
    subset = [value for value in onset_seconds if value <= max_seconds][:max_events]

    if len(subset) >= 24:
        return subset

    return onset_seconds[:max_events]


def _match_constant_shift(
    source_seconds: List[float],
    reference_seconds: List[float],
    shift_seconds: float,
    tolerance_seconds: float,
) -> List[Tuple[float, float]]:
    matches: List[Tuple[float, float]] = []
    source_index = 0
    reference_index = 0

    while source_index < len(source_seconds) and reference_index < len(reference_seconds):
        shifted_source = source_seconds[source_index] + shift_seconds
        reference_value = reference_seconds[reference_index]
        difference = reference_value - shifted_source

        if abs(difference) <= tolerance_seconds:
            matches.append((source_seconds[source_index], reference_value))
            source_index += 1
            reference_index += 1
        elif shifted_source < reference_value:
            source_index += 1
        else:
            reference_index += 1

    return matches


def _match_piecewise_warp(
    source_seconds: List[float],
    reference_seconds: List[float],
    time_warp: TimeWarp,
    tolerance_seconds: float,
) -> List[Tuple[float, float]]:
    matches: List[Tuple[float, float]] = []
    source_index = 0
    reference_index = 0

    while source_index < len(source_seconds) and reference_index < len(reference_seconds):
        warped_source = time_warp.map_seconds(source_seconds[source_index])
        reference_value = reference_seconds[reference_index]
        difference = reference_value - warped_source

        if abs(difference) <= tolerance_seconds:
            matches.append((source_seconds[source_index], reference_value))
            source_index += 1
            reference_index += 1
        elif warped_source < reference_value:
            source_index += 1
        else:
            reference_index += 1

    return matches


def _mean_shift_error(match_pairs: List[Tuple[float, float]], shift_seconds: float) -> float:
    if not match_pairs:
        return float("inf")

    total_error = sum(abs((reference_value - source_value) - shift_seconds) for source_value, reference_value in match_pairs)

    return total_error / len(match_pairs)


def _best_constant_shift(source_seconds: List[float], reference_seconds: List[float]) -> Tuple[float, List[Tuple[float, float]], float]:
    if not source_seconds or not reference_seconds:
        return 0.0, [], float("inf")

    bin_seconds = 0.05
    tolerance_seconds = 0.12
    source_subset = _search_subset(source_seconds)
    reference_subset = _search_subset(reference_seconds)
    shift_bins: Dict[int, int] = {}

    for source_value in source_subset:
        for reference_value in reference_subset:
            shift_value = reference_value - source_value
            shift_bin = round(shift_value / bin_seconds)
            shift_bins[shift_bin] = shift_bins.get(shift_bin, 0) + 1

    candidate_shifts: List[float] = []

    if shift_bins:
        top_bins = sorted(shift_bins.items(), key=lambda item: (-item[1], abs(item[0])))[:12]

        for shift_bin, _ in top_bins:
            for neighbor_offset in (-1, 0, 1):
                shift_value = (shift_bin + neighbor_offset) * bin_seconds

                if shift_value not in candidate_shifts:
                    candidate_shifts.append(shift_value)
    else:
        candidate_shifts.append(reference_seconds[0] - source_seconds[0])

    best_shift_seconds = reference_seconds[0] - source_seconds[0]
    best_matches: List[Tuple[float, float]] = []
    best_error_seconds = float("inf")

    for shift_value in candidate_shifts:
        initial_matches = _match_constant_shift(source_seconds, reference_seconds, shift_value, tolerance_seconds)

        if not initial_matches:
            continue

        refined_shift = median(reference_value - source_value for source_value, reference_value in initial_matches)
        refined_matches = _match_constant_shift(source_seconds, reference_seconds, refined_shift, tolerance_seconds)
        refined_error = _mean_shift_error(refined_matches, refined_shift)

        if len(refined_matches) > len(best_matches):
            best_shift_seconds = refined_shift
            best_matches = refined_matches
            best_error_seconds = refined_error
            continue

        if len(refined_matches) == len(best_matches) and refined_error < best_error_seconds:
            best_shift_seconds = refined_shift
            best_matches = refined_matches
            best_error_seconds = refined_error

    return best_shift_seconds, best_matches, best_error_seconds


def _time_slice(sorted_seconds: List[float], start_seconds: float, end_seconds: float) -> List[float]:
    left_index = bisect_left(sorted_seconds, start_seconds)
    right_index = bisect_right(sorted_seconds, end_seconds)

    return sorted_seconds[left_index:right_index]


def _best_local_shift(
    source_seconds: List[float],
    reference_seconds: List[float],
    expected_shift_seconds: float,
) -> Optional[Tuple[float, List[Tuple[float, float]], float]]:
    search_radius_seconds = 1.5
    bin_seconds = 0.02
    tolerance_seconds = 0.10
    shift_bins: Dict[int, int] = {}

    for source_value in source_seconds:
        for reference_value in reference_seconds:
            shift_value = reference_value - source_value

            if abs(shift_value - expected_shift_seconds) > search_radius_seconds:
                continue

            shift_bin = round(shift_value / bin_seconds)
            shift_bins[shift_bin] = shift_bins.get(shift_bin, 0) + 1

    if not shift_bins:
        return None

    expected_bin = round(expected_shift_seconds / bin_seconds)
    top_bins = sorted(shift_bins.items(), key=lambda item: (-item[1], abs(item[0] - expected_bin)))[:6]
    best_shift_seconds = expected_shift_seconds
    best_matches: List[Tuple[float, float]] = []
    best_error_seconds = float("inf")

    for shift_bin, _ in top_bins:
        trial_shift = shift_bin * bin_seconds
        initial_matches = _match_constant_shift(source_seconds, reference_seconds, trial_shift, tolerance_seconds)

        if not initial_matches:
            continue

        refined_shift = median(reference_value - source_value for source_value, reference_value in initial_matches)

        if abs(refined_shift - expected_shift_seconds) > search_radius_seconds:
            continue

        refined_matches = _match_constant_shift(source_seconds, reference_seconds, refined_shift, tolerance_seconds)
        refined_error = _mean_shift_error(refined_matches, refined_shift)

        if len(refined_matches) > len(best_matches):
            best_shift_seconds = refined_shift
            best_matches = refined_matches
            best_error_seconds = refined_error
            continue

        if len(refined_matches) == len(best_matches) and refined_error < best_error_seconds:
            best_shift_seconds = refined_shift
            best_matches = refined_matches
            best_error_seconds = refined_error

    if not best_matches:
        return None

    return best_shift_seconds, best_matches, best_error_seconds


def _filter_warp_anchors(raw_anchors: List[WarpAnchor]) -> List[WarpAnchor]:
    if not raw_anchors:
        return []

    filtered_anchors: List[WarpAnchor] = []

    for candidate_anchor in sorted(raw_anchors, key=lambda anchor: anchor.source_seconds):
        if not filtered_anchors:
            filtered_anchors.append(candidate_anchor)
            continue

        previous_anchor = filtered_anchors[-1]
        source_gap_seconds = candidate_anchor.source_seconds - previous_anchor.source_seconds
        reference_gap_seconds = candidate_anchor.reference_seconds - previous_anchor.reference_seconds

        if source_gap_seconds <= 0:
            continue

        if source_gap_seconds < 2.0:
            total_matches = previous_anchor.match_count + candidate_anchor.match_count

            if total_matches <= 0:
                continue

            merged_source_seconds = (
                previous_anchor.source_seconds * previous_anchor.match_count
                + candidate_anchor.source_seconds * candidate_anchor.match_count
            ) / total_matches
            merged_reference_seconds = (
                previous_anchor.reference_seconds * previous_anchor.match_count
                + candidate_anchor.reference_seconds * candidate_anchor.match_count
            ) / total_matches

            filtered_anchors[-1] = WarpAnchor(
                source_seconds=merged_source_seconds,
                reference_seconds=merged_reference_seconds,
                match_count=total_matches,
            )
            continue

        if reference_gap_seconds <= 0:
            continue

        slope_ratio = reference_gap_seconds / source_gap_seconds

        if slope_ratio < 0.5 or slope_ratio > 1.5:
            continue

        filtered_anchors.append(candidate_anchor)

    return filtered_anchors


def _progress_warp_anchors(source_seconds: List[float], reference_seconds: List[float]) -> List[WarpAnchor]:
    anchor_total = min(64, len(source_seconds), len(reference_seconds))

    if anchor_total < 2:
        return []

    progress_anchors: List[WarpAnchor] = []
    last_source_seconds = None
    last_reference_seconds = None

    for anchor_index in range(anchor_total):
        progress_ratio = anchor_index / (anchor_total - 1)
        source_index = round(progress_ratio * (len(source_seconds) - 1))
        reference_index = round(progress_ratio * (len(reference_seconds) - 1))

        source_value = source_seconds[source_index]
        reference_value = reference_seconds[reference_index]

        if last_source_seconds is not None and source_value <= last_source_seconds:
            continue

        if last_reference_seconds is not None and reference_value <= last_reference_seconds:
            continue

        progress_anchors.append(
            WarpAnchor(
                source_seconds=source_value,
                reference_seconds=reference_value,
                match_count=1,
            )
        )
        last_source_seconds = source_value
        last_reference_seconds = reference_value

    return progress_anchors


def _extend_warp_anchors(base_anchors: List[WarpAnchor], source_seconds: List[float]) -> List[WarpAnchor]:
    if not base_anchors:
        return []

    extended_anchors = list(base_anchors)
    first_delta_seconds = extended_anchors[0].reference_seconds - extended_anchors[0].source_seconds
    last_delta_seconds = extended_anchors[-1].reference_seconds - extended_anchors[-1].source_seconds
    first_source_seconds = source_seconds[0]
    last_source_seconds = source_seconds[-1]

    if first_source_seconds < extended_anchors[0].source_seconds:
        extended_anchors.insert(
            0,
            WarpAnchor(
                source_seconds=first_source_seconds,
                reference_seconds=first_source_seconds + first_delta_seconds,
                match_count=extended_anchors[0].match_count,
            ),
        )

    if last_source_seconds > extended_anchors[-1].source_seconds:
        extended_anchors.append(
            WarpAnchor(
                source_seconds=last_source_seconds,
                reference_seconds=last_source_seconds + last_delta_seconds,
                match_count=extended_anchors[-1].match_count,
            )
        )

    return extended_anchors


def _build_time_warp(source_seconds: List[float], reference_seconds: List[float], coarse_shift_seconds: float) -> TimeWarp:
    if not source_seconds or not reference_seconds:
        return TimeWarp(anchors=[], base_shift_seconds=coarse_shift_seconds)

    raw_anchors: List[WarpAnchor] = []
    window_seconds = 16.0
    step_seconds = 8.0
    half_window_seconds = window_seconds / 2
    center_seconds = source_seconds[0]
    last_source_seconds = source_seconds[-1]
    expected_shift_seconds = coarse_shift_seconds

    while center_seconds <= last_source_seconds:
        source_window = _time_slice(
            source_seconds,
            center_seconds - half_window_seconds,
            center_seconds + half_window_seconds,
        )

        if len(source_window) < 8:
            center_seconds += step_seconds
            continue

        reference_window = _time_slice(
            reference_seconds,
            center_seconds + expected_shift_seconds - half_window_seconds - 1.5,
            center_seconds + expected_shift_seconds + half_window_seconds + 1.5,
        )

        if len(reference_window) < 8:
            center_seconds += step_seconds
            continue

        local_result = _best_local_shift(source_window, reference_window, expected_shift_seconds)

        if local_result is not None:
            local_shift_seconds, local_matches, _ = local_result
            anchor_source_seconds = median(source_value for source_value, _ in local_matches)
            anchor_reference_seconds = median(reference_value for _, reference_value in local_matches)
            raw_anchors.append(
                WarpAnchor(
                    source_seconds=anchor_source_seconds,
                    reference_seconds=anchor_reference_seconds,
                    match_count=len(local_matches),
                )
            )
            expected_shift_seconds = local_shift_seconds

        center_seconds += step_seconds

    local_anchors = _extend_warp_anchors(_filter_warp_anchors(raw_anchors), source_seconds)
    progress_anchors = _extend_warp_anchors(_progress_warp_anchors(source_seconds, reference_seconds), source_seconds)
    warp_candidates = []

    if local_anchors:
        local_warp = TimeWarp(anchors=local_anchors, base_shift_seconds=coarse_shift_seconds)
        local_matches = _match_piecewise_warp(source_seconds, reference_seconds, local_warp, tolerance_seconds=0.10)
        warp_candidates.append((len(local_matches), len(local_anchors), local_anchors))

    if progress_anchors:
        progress_warp = TimeWarp(anchors=progress_anchors, base_shift_seconds=coarse_shift_seconds)
        progress_matches = _match_piecewise_warp(source_seconds, reference_seconds, progress_warp, tolerance_seconds=0.10)
        warp_candidates.append((len(progress_matches), len(progress_anchors), progress_anchors))

    if not warp_candidates:
        return TimeWarp(anchors=[], base_shift_seconds=coarse_shift_seconds)

    _, _, best_anchors = max(warp_candidates, key=lambda item: (item[0], item[1]))

    return TimeWarp(anchors=best_anchors, base_shift_seconds=coarse_shift_seconds)


def _rank_sync_candidates(candidates: List[SyncCandidate], reference_seconds: List[float]) -> List[SyncCandidate]:
    ranked_candidates: List[SyncCandidate] = []

    for candidate in candidates:
        shift_seconds, match_pairs, error_seconds = _best_constant_shift(candidate.onset_seconds, reference_seconds)
        candidate.coarse_shift_seconds = shift_seconds
        candidate.coarse_match_count = len(match_pairs)
        candidate.coarse_mean_error_seconds = error_seconds
        ranked_candidates.append(candidate)

    ranked_candidates.sort(
        key=lambda candidate: (
            -candidate.coarse_match_count,
            -candidate.hint_rank,
            candidate.coarse_mean_error_seconds,
            -candidate.onset_count,
            candidate.track_index,
        )
    )

    return ranked_candidates


def _print_candidate_diagnostics(candidates: List[SyncCandidate]) -> None:
    if not candidates:
        print("Sync tracks: nenhuma candidata encontrada")

        return

    print("Sync tracks candidatas:")

    for candidate in candidates[:8]:
        display_name = candidate.track_name if candidate.track_name else "<sem nome>"
        display_error_ms = candidate.coarse_mean_error_seconds * 1000
        print(
            "  "
            f"[{candidate.track_index:02d}] {display_name} | "
            f"onsets={candidate.onset_count} | "
            f"coarse_shift={candidate.coarse_shift_seconds:+.3f}s | "
            f"matches={candidate.coarse_match_count} | "
            f"error={display_error_ms:.1f}ms | "
            f"hint={candidate.hint_rank}"
        )


def _print_beat_candidates(candidates: List[SyncCandidate], src_tpb: int) -> None:
    if not candidates:
        print("Beat tracks: nenhuma candidata encontrada")

        return

    print("Beat tracks candidatas:")

    for candidate in candidates[:8]:
        display_name = candidate.track_name if candidate.track_name else "<sem nome>"
        first_beat = candidate.onset_ticks[0] / src_tpb
        print(
            "  "
            f"[{candidate.track_index:02d}] {display_name} | "
            f"first_beat={first_beat:.2f} | "
            f"onsets={candidate.onset_count} | "
            f"hint={candidate.hint_rank}"
        )


def _auto_sync_is_low_confidence(
    sync_selection: SyncSelection,
    reference_onset_count: int,
    anchor_warp_enabled: bool,
) -> bool:
    selected_candidate = sync_selection.candidate

    if selected_candidate is None:
        return True

    possible_matches = max(1, min(selected_candidate.onset_count, reference_onset_count))
    match_ratio = sync_selection.base_match_count / possible_matches

    if sync_selection.sync_mode == "beat":
        if selected_candidate.onset_ticks[0] / max(selected_candidate.onset_ticks[-1], 1) > 0.25:
            return True

        if match_ratio < 0.25:
            return True
    else:
        if selected_candidate.coarse_match_count < 12:
            return True

        if match_ratio < 0.08:
            return True

        if anchor_warp_enabled and len(sync_selection.time_warp.anchors) < 2:
            return True

    return False


def _manual_sync_override_enabled(args: argparse.Namespace) -> bool:
    if args.sync_mode != "auto":
        return True

    if args.disable_anchor_warp:
        return True

    if args.sync_track_index is not None:
        return True

    if args.sync_track_contains is not None:
        return True

    if args.offset_seconds != 0.0:
        return True

    if args.offset_beats != 0.0:
        return True

    return False


def _matched_onset_indices(
    source_seconds: List[float],
    reference_seconds: List[float],
    time_warp: TimeWarp,
    tolerance_seconds: float = 0.10,
) -> List[Tuple[int, int]]:
    matches: List[Tuple[int, int]] = []
    source_index = 0
    reference_index = 0

    while source_index < len(source_seconds) and reference_index < len(reference_seconds):
        warped_source = time_warp.map_seconds(source_seconds[source_index])
        reference_value = reference_seconds[reference_index]
        difference = reference_value - warped_source

        if abs(difference) <= tolerance_seconds:
            matches.append((source_index, reference_index))
            source_index += 1
            reference_index += 1
        elif warped_source < reference_value:
            source_index += 1
        else:
            reference_index += 1

    return matches


def _build_tick_anchor_mapper(
    source_ticks: List[int],
    reference_ticks: List[int],
    matched_indices: List[Tuple[int, int]],
) -> Tuple[Callable[[int], int], int]:
    anchor_pairs: List[Tuple[int, int]] = []
    last_source_tick = None
    last_reference_tick = None

    for source_index, reference_index in matched_indices:
        source_tick = source_ticks[source_index]
        reference_tick = reference_ticks[reference_index]

        if last_source_tick is not None and source_tick <= last_source_tick:
            continue

        if last_reference_tick is not None and reference_tick <= last_reference_tick:
            continue

        anchor_pairs.append((source_tick, reference_tick))
        last_source_tick = source_tick
        last_reference_tick = reference_tick

    if len(anchor_pairs) < 2:
        raise RuntimeError("Warp temporal encontrou poucas ancoras em tick")

    source_anchor_ticks = [source_tick for source_tick, _ in anchor_pairs]
    reference_anchor_ticks = [reference_tick for _, reference_tick in anchor_pairs]

    def map_tick(source_tick: int) -> int:
        if source_tick <= source_anchor_ticks[0]:
            return reference_anchor_ticks[0] + (source_tick - source_anchor_ticks[0])

        if source_tick >= source_anchor_ticks[-1]:
            return reference_anchor_ticks[-1] + (source_tick - source_anchor_ticks[-1])

        right_index = bisect_right(source_anchor_ticks, source_tick)
        left_source_tick = source_anchor_ticks[right_index - 1]
        right_source_tick = source_anchor_ticks[right_index]
        left_reference_tick = reference_anchor_ticks[right_index - 1]
        right_reference_tick = reference_anchor_ticks[right_index]
        source_gap_ticks = right_source_tick - left_source_tick

        if source_gap_ticks <= 0:
            return left_reference_tick

        progress = (source_tick - left_source_tick) / source_gap_ticks

        return int(round(left_reference_tick + progress * (right_reference_tick - left_reference_tick)))

    return map_tick, len(anchor_pairs)


def _choose_beat_candidate(candidates: List[SyncCandidate]) -> Optional[SyncCandidate]:
    if not candidates:
        return None

    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate.onset_ticks[0],
            -candidate.hint_rank,
            -candidate.onset_count,
            candidate.track_index,
        ),
    )

    return ranked_candidates[0]


def _source_beat_span_ratio(
    candidates: List[SyncCandidate],
    reference_ticks: List[int],
    src_tpb: int,
    ref_tpb: int,
) -> Optional[float]:
    if not candidates or not reference_ticks:
        return None

    source_first_tick = min(candidate.onset_ticks[0] for candidate in candidates)
    source_last_tick = max(candidate.onset_ticks[-1] for candidate in candidates)
    reference_first_tick = reference_ticks[0]
    reference_last_tick = reference_ticks[-1]
    source_span_beats = (source_last_tick - source_first_tick) / src_tpb
    reference_span_beats = (reference_last_tick - reference_first_tick) / ref_tpb

    if reference_span_beats <= 0:
        return None

    return source_span_beats / reference_span_beats


def _select_sync_mode(
    args: argparse.Namespace,
    candidates: List[SyncCandidate],
    reference_ticks: List[int],
    src_tpb: int,
    ref_tpb: int,
) -> Tuple[str, Optional[float]]:
    if args.sync_mode != "auto":
        return args.sync_mode, None

    beat_span_ratio = _source_beat_span_ratio(candidates, reference_ticks, src_tpb, ref_tpb)

    if beat_span_ratio is None:
        return "time", None

    if 0.88 <= beat_span_ratio <= 1.12:
        return "beat", beat_span_ratio

    return "time", beat_span_ratio


def _build_sync_mapper(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    args: argparse.Namespace,
) -> Tuple[Callable[[int], int], SyncSelection]:
    src_tempo_map = build_tempo_map(src_mid)
    ref_tempo_map = build_tempo_map(ref_mid)
    reference_ticks, reference_seconds = _reference_guitar_onsets(ref_mid, ref_tempo_map)
    candidates = _source_sync_candidates(src_mid, src_tempo_map, args.sync_track_index, args.sync_track_contains)
    ranked_candidates = _rank_sync_candidates(candidates, reference_seconds)
    anchor_warp_enabled = not args.disable_anchor_warp
    sync_mode, beat_span_ratio = _select_sync_mode(args, candidates, reference_ticks, src_mid.ticks_per_beat, ref_mid.ticks_per_beat)
    sync_selection = SyncSelection(
        sync_mode=sync_mode,
        candidate=None,
        time_warp=TimeWarp(anchors=[], base_shift_seconds=0.0),
        base_match_count=0,
        beat_span_ratio=beat_span_ratio,
    )

    if sync_mode == "beat":
        beat_candidates = sorted(
            candidates,
            key=lambda candidate: (
                candidate.onset_ticks[0],
                -candidate.hint_rank,
                -candidate.onset_count,
                candidate.track_index,
            ),
        )

        _print_beat_candidates(beat_candidates, src_mid.ticks_per_beat)

        selected_candidate = _choose_beat_candidate(beat_candidates)

        if selected_candidate is None:
            raise RuntimeError("Nao encontrei track valida para beat-sync")

        sync_selection.candidate = selected_candidate
        sync_selection.base_match_count = selected_candidate.onset_count
        reference_first_beat = reference_ticks[0] / ref_mid.ticks_per_beat
        source_first_beat = selected_candidate.onset_ticks[0] / src_mid.ticks_per_beat
        beat_shift = reference_first_beat - source_first_beat
        display_name = selected_candidate.track_name if selected_candidate.track_name else "<sem nome>"

        print(f"Sync mode: beat (ratio span={beat_span_ratio:.3f})" if beat_span_ratio is not None else "Sync mode: beat")
        print(f"Sync escolhida: [{selected_candidate.track_index}] {display_name}")
        print(f"  beat shift: {beat_shift:+.3f}")
        print(f"  first beat src/ref: {source_first_beat:.2f} -> {reference_first_beat:.2f}")

        def base_source_tick_to_reference_tick(source_tick: int) -> int:
            mapped_beat = (source_tick / src_mid.ticks_per_beat) + beat_shift

            return int(round(mapped_beat * ref_mid.ticks_per_beat))
    else:
        _print_candidate_diagnostics(ranked_candidates)

        if ranked_candidates:
            selected_candidate = ranked_candidates[0]
            sync_selection.candidate = selected_candidate

            if anchor_warp_enabled:
                time_warp = _build_time_warp(
                    selected_candidate.onset_seconds,
                    reference_seconds,
                    selected_candidate.coarse_shift_seconds,
                )
            else:
                time_warp = TimeWarp(anchors=[], base_shift_seconds=selected_candidate.coarse_shift_seconds)

            matched_indices = _matched_onset_indices(
                selected_candidate.onset_seconds,
                reference_seconds,
                time_warp,
                tolerance_seconds=0.10,
            )
            selected_candidate.warped_match_count = len(matched_indices)
            sync_selection.time_warp = time_warp
            sync_selection.base_match_count = len(matched_indices)
            possible_matches = max(1, min(selected_candidate.onset_count, len(reference_seconds)))
            warped_match_ratio = len(matched_indices) / possible_matches
            display_name = selected_candidate.track_name if selected_candidate.track_name else "<sem nome>"

            print(f"Sync mode: time (ratio span={beat_span_ratio:.3f})" if beat_span_ratio is not None else "Sync mode: time")
            print(f"Sync escolhida: [{selected_candidate.track_index}] {display_name}")
            print(f"  coarse shift: {selected_candidate.coarse_shift_seconds:+.3f}s")
            print(f"  coarse matches: {selected_candidate.coarse_match_count}")
            print(f"  warp anchors: {len(time_warp.anchors)}")
            print(
                "  warped matches: "
                f"{len(matched_indices)}/{possible_matches} "
                f"({warped_match_ratio:.0%})"
            )

            if time_warp.anchors:
                first_anchor = time_warp.anchors[0]
                last_anchor = time_warp.anchors[-1]
                print(
                    "  anchor span: "
                    f"{first_anchor.source_seconds:.1f}s->{first_anchor.reference_seconds:.1f}s .. "
                    f"{last_anchor.source_seconds:.1f}s->{last_anchor.reference_seconds:.1f}s"
                )

            base_source_tick_to_reference_tick, anchor_count = _build_tick_anchor_mapper(
                selected_candidate.onset_ticks,
                reference_ticks,
                matched_indices,
            )
            print(f"  tick anchors: {anchor_count}")
        elif anchor_warp_enabled or not _manual_sync_override_enabled(args):
            raise RuntimeError(
                "Nao encontrei track melódica valida para auto-sync. "
                "Use --sync-track-index / --sync-track-contains ou rode com "
                "--disable-anchor-warp e offsets manuais."
            )
        else:
            def base_source_tick_to_reference_tick(source_tick: int) -> int:
                return source_tick
    if sync_selection.candidate is None and (anchor_warp_enabled or not _manual_sync_override_enabled(args)):
        raise RuntimeError(
            "Nao encontrei track valida para construir o sync."
        )

    if _auto_sync_is_low_confidence(sync_selection, len(reference_seconds), anchor_warp_enabled):
        if not _manual_sync_override_enabled(args):
            raise RuntimeError(
                "Auto-sync com confianca baixa. Revise as tracks candidatas acima ou use "
                "--sync-mode / --sync-track-index / --sync-track-contains / --disable-anchor-warp / "
                "--offset-seconds / --offset-beats."
            )

        print("  Aviso: sync automatico com confianca baixa; seguindo por override manual.")

    if args.offset_seconds != 0.0:
        print(f"  offset manual em segundos: {args.offset_seconds:+.3f}s")

    if args.offset_beats != 0.0:
        print(f"  offset manual em beats ref: {args.offset_beats:+.3f}")

    def source_tick_to_reference_tick(source_tick: int) -> int:
        reference_tick = base_source_tick_to_reference_tick(source_tick)

        if args.offset_seconds != 0.0:
            reference_seconds_value = ref_tempo_map.tick_to_seconds(reference_tick) + args.offset_seconds
            reference_tick = ref_tempo_map.seconds_to_tick(reference_seconds_value)

        if args.offset_beats != 0.0:
            reference_tick += int(round(args.offset_beats * ref_mid.ticks_per_beat))

        return reference_tick

    return source_tick_to_reference_tick, sync_selection


def build_drums_track(
    src_mid: mido.MidiFile,
    source_tick_to_target_tick: Callable[[int], int],
    target_tpb: int,
    drop_before_src_beat: float = 0.0,
    dedup_beats: float = 1 / 16,
) -> mido.MidiTrack:
    """Converte drums src -> PART DRUMS ref preservando o mapping de lanes."""
    src_tpb = src_mid.ticks_per_beat
    drum_track = next(
        (
            track
            for track in src_mid.tracks
            if any(message.type == "note_on" and message.channel == 9 and message.velocity > 0 for message in track)
        ),
        None,
    )

    if drum_track is None:
        raise RuntimeError("Nenhuma track de bateria (canal 9) encontrada")

    open_hat_yellow = classify_open_hat_mode(drum_track)
    tom_lane_map = build_tom_pitch_map(drum_track)
    lane_letters = ["K", "S", "Y", "B", "G"]
    print(f"  Open HH -> {'Y (folgado)' if open_hat_yellow else 'B (ride/accent)'}")
    print(f"  Tom map: {[(pitch_value, lane_letters[lane_value]) for pitch_value, lane_value in sorted(tom_lane_map.items())]}")

    def resolve_lane(pitch_value: int) -> Tuple[Optional[int], bool]:
        if pitch_value in tom_lane_map:
            return tom_lane_map[pitch_value], False

        if pitch_value == 46:
            if open_hat_yellow:
                return LANE_YELLOW, True

            return LANE_BLUE, True

        lane_result = GM_TO_RB.get(pitch_value)

        if lane_result is None:
            return None, False

        return lane_result

    dedup_gap_ticks = int(round(src_tpb * dedup_beats))
    last_note_by_lane: Dict[Tuple[int, bool], int] = {}
    skipped_flams = set()
    snare_flam_second_to_first: Dict[Tuple[int, int], int] = {}
    absolute_source_tick = 0

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if message.velocity <= 0:
            continue

        if message.channel != 9:
            continue

        lane_value, is_cymbal = resolve_lane(message.note)

        if lane_value is None:
            continue

        lane_key = (lane_value, is_cymbal)
        previous_tick = last_note_by_lane.get(lane_key)

        if previous_tick is not None and absolute_source_tick - previous_tick <= dedup_gap_ticks:
            if lane_value == LANE_SNARE:
                snare_flam_second_to_first[(absolute_source_tick, message.note)] = previous_tick
            else:
                skipped_flams.add((absolute_source_tick, message.note))

            continue

        last_note_by_lane[lane_key] = absolute_source_tick

    absolute_source_tick = 0
    mapped_events = []

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if message.velocity <= 0:
            continue

        if message.channel != 9:
            continue

        if (absolute_source_tick, message.note) in skipped_flams:
            continue

        flam_first_tick = snare_flam_second_to_first.get((absolute_source_tick, message.note))

        if flam_first_tick is not None:
            source_tick = flam_first_tick
        else:
            source_tick = absolute_source_tick

        source_beat = source_tick / src_tpb

        if source_beat < drop_before_src_beat:
            continue

        lane_value, is_cymbal = resolve_lane(message.note)

        if lane_value is None:
            continue

        if flam_first_tick is not None:
            lane_value = LANE_YELLOW
            is_cymbal = False

        target_tick = source_tick_to_target_tick(source_tick)

        if target_tick < 0:
            continue

        mapped_events.append((target_tick, 96 + lane_value, lane_value, is_cymbal))

    unique_events = []
    seen_events = set()

    for event_value in sorted(mapped_events):
        event_key = (event_value[0], event_value[2])

        if event_key in seen_events:
            continue

        seen_events.add(event_key)
        unique_events.append(event_value)

    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="PART DRUMS", time=0))
    track.append(mido.MetaMessage("text", text="[mix 0 drums0]", time=0))

    output_events = []

    for tick_value, pitch_value, lane_value, _ in unique_events:
        output_events.append((tick_value, mido.Message("note_on", note=pitch_value, velocity=100, time=0)))
        output_events.append((tick_value + 1, mido.Message("note_off", note=pitch_value, velocity=0, time=0)))

    lane_to_marker_pitch = {
        LANE_YELLOW: 110,
        LANE_BLUE: 111,
        LANE_GREEN: 112,
    }
    tom_ticks_by_lane: Dict[int, List[int]] = {
        LANE_YELLOW: [],
        LANE_BLUE: [],
        LANE_GREEN: [],
    }

    for tick_value, _, lane_value, is_cymbal in unique_events:
        if lane_value in tom_ticks_by_lane and not is_cymbal:
            tom_ticks_by_lane[lane_value].append(tick_value)

    for lane_value, lane_ticks in tom_ticks_by_lane.items():
        for tick_value in sorted(set(lane_ticks)):
            marker_pitch = lane_to_marker_pitch[lane_value]
            output_events.append((tick_value, mido.Message("note_on", note=marker_pitch, velocity=100, time=0)))
            output_events.append(
                (
                    tick_value + target_tpb // 8,
                    mido.Message("note_off", note=marker_pitch, velocity=0, time=0),
                )
            )

    output_events.sort(key=lambda item: item[0])
    last_tick = 0

    for absolute_tick, message in output_events:
        track.append(message.copy(time=absolute_tick - last_tick))
        last_tick = absolute_tick

    track.append(mido.MetaMessage("end_of_track", time=0))

    return track


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid", help="MIDI externo contendo a bateria")
    argument_parser.add_argument("ref_mid", help="notes.mid do chart (referencia)")
    argument_parser.add_argument("out_mid", help="onde gravar o chart resultante")
    argument_parser.add_argument(
        "--offset-beats",
        type=float,
        default=0.0,
        help="shift manual extra no tempo do chart de referencia, em beats. Positivo atrasa no ref.",
    )
    argument_parser.add_argument(
        "--offset-seconds",
        type=float,
        default=0.0,
        help="shift manual extra em segundos apos o auto-sync. Positivo atrasa no ref.",
    )
    argument_parser.add_argument(
        "--drop-before-src-beat",
        type=float,
        default=None,
        help="dropa notas src antes deste beat (remove count-in / baqueta).",
    )
    argument_parser.add_argument(
        "--dedup-beats",
        type=float,
        default=1 / 16,
        help="pares mesma-lane com gap <= N beats viram R+Y (snare) ou dedup (outros). Default 1/16.",
    )
    argument_parser.add_argument(
        "--sync-track-index",
        type=int,
        default=None,
        help="forca o indice da track src usada para ancorar o sync automatico.",
    )
    argument_parser.add_argument(
        "--sync-track-contains",
        default=None,
        help="forca a track src cujo nome contenha este texto (case-insensitive).",
    )
    argument_parser.add_argument(
        "--disable-anchor-warp",
        action="store_true",
        help="desliga o warp local e usa apenas source-time -> ref-time + shift constante.",
    )
    argument_parser.add_argument(
        "--sync-mode",
        choices=("auto", "beat", "time"),
        default="auto",
        help="estrategia de sync. auto escolhe beat ou time conforme a divergencia entre os mapas.",
    )
    args = argument_parser.parse_args()

    if args.sync_track_index is not None and args.sync_track_contains is not None:
        raise RuntimeError("Use apenas um entre --sync-track-index e --sync-track-contains")

    src_mid = mido.MidiFile(args.src_mid)
    ref_mid = mido.MidiFile(args.ref_mid)
    source_tick_to_reference_tick, sync_selection = _build_sync_mapper(src_mid, ref_mid, args)
    selected_candidate = sync_selection.candidate

    if args.drop_before_src_beat is not None:
        drop_before_src_beat = args.drop_before_src_beat
    elif selected_candidate is not None and selected_candidate.onset_ticks:
        drop_before_src_beat = selected_candidate.onset_ticks[0] / src_mid.ticks_per_beat
    else:
        drop_before_src_beat = 0.0

    print(f"  drop antes de src_beat {drop_before_src_beat:.2f}")

    new_drums_track = build_drums_track(
        src_mid,
        source_tick_to_reference_tick,
        ref_mid.ticks_per_beat,
        drop_before_src_beat=drop_before_src_beat,
        dedup_beats=args.dedup_beats,
    )

    absolute_tick = 0
    first_drum_tick = None

    for message in new_drums_track:
        absolute_tick += message.time

        if message.type == "note_on" and message.velocity > 0 and 96 <= message.note <= 100:
            first_drum_tick = absolute_tick
            break

    if first_drum_tick is not None:
        print(f"  -> 1a drum: tick={first_drum_tick} beat={first_drum_tick / ref_mid.ticks_per_beat:.2f}")

    print(
        "  Se o audio nao bater: ajuste "
        "--offset-seconds / --offset-beats e, se preciso, force a track com "
        "--sync-track-index ou --sync-track-contains"
    )

    output_mid = mido.MidiFile(type=ref_mid.type, ticks_per_beat=ref_mid.ticks_per_beat)
    replaced_drums = False

    for track in ref_mid.tracks:
        if track.name == "PART DRUMS":
            output_mid.tracks.append(new_drums_track)
            replaced_drums = True
        else:
            output_mid.tracks.append(track)

    if not replaced_drums:
        output_mid.tracks.append(new_drums_track)

    output_mid.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

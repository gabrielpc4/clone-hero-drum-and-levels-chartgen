from __future__ import annotations

from typing import Dict, Optional, Tuple

import mido

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_YELLOW

from .constants import (
    GM_TO_RB,
    LOW_TOM_PITCHES,
    TOM_PITCHES,
    TOM_TO_LANE,
    UPPER_TOM_PITCHES,
    should_keep_source_hit,
)


def build_tom_pitch_map(
    drum_track: mido.MidiTrack,
    minimum_snare_velocity: int | None = None,
) -> Dict[int, int]:
    """Mapeia toms GM usando o papel nominal de cada pitch."""
    used_pitches = set()

    for message in drum_track:
        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if message.note not in TOM_PITCHES:
            continue

        used_pitches.add(message.note)

    if not used_pitches:
        return {}

    uses_upper_tom_register = any(pitch_value in used_pitches for pitch_value in (48, 50))

    if not uses_upper_tom_register:
        lowered_kit_order = [47, 45, 43, 41]
        available_lowered_pitches = [
            pitch_value
            for pitch_value in lowered_kit_order
            if pitch_value in used_pitches
        ]

        if available_lowered_pitches:
            lowered_pitch_map: Dict[int, int] = {}
            highest_pitch = available_lowered_pitches[0]
            lowered_pitch_map[highest_pitch] = LANE_YELLOW

            if len(available_lowered_pitches) >= 2:
                second_pitch = available_lowered_pitches[1]
                lowered_pitch_map[second_pitch] = LANE_BLUE

            for pitch_value in available_lowered_pitches[2:]:
                lowered_pitch_map[pitch_value] = LANE_GREEN

            return lowered_pitch_map

    return {
        pitch_value: TOM_TO_LANE[pitch_value]
        for pitch_value in sorted(used_pitches)
    }


def build_tom_lane_overrides(
    drum_track: mido.MidiTrack,
    minimum_snare_velocity: int | None = None,
) -> Dict[Tuple[int, int], int]:
    tom_ticks: list[Tuple[int, list[int]]] = []
    absolute_source_tick = 0
    current_tick = None
    current_tick_notes: list[int] = []

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if current_tick is None:
            current_tick = absolute_source_tick

        if absolute_source_tick != current_tick:
            tom_ticks.append((current_tick, current_tick_notes))
            current_tick = absolute_source_tick
            current_tick_notes = []

        current_tick_notes.append(message.note)

    if current_tick is not None:
        tom_ticks.append((current_tick, current_tick_notes))

    overrides: Dict[Tuple[int, int], int] = {}
    current_run: list[Tuple[int, list[int]]] = []

    def flush_run() -> None:
        nonlocal current_run

        if not current_run:
            return

        saw_upper_tom_before_low = False
        saw_low_tom = False
        low_run_pitches = set()

        for _, tick_notes in current_run:
            upper_tom_notes = [pitch_value for pitch_value in tick_notes if pitch_value in UPPER_TOM_PITCHES]
            low_tom_notes = [pitch_value for pitch_value in tick_notes if pitch_value in LOW_TOM_PITCHES]

            if not saw_low_tom and upper_tom_notes:
                saw_upper_tom_before_low = True

            if low_tom_notes:
                saw_low_tom = True
                low_run_pitches.update(low_tom_notes)

        if saw_upper_tom_before_low or len(low_run_pitches) < 2:
            current_run = []
            return

        highest_low_pitch = max(low_run_pitches)
        lowest_low_pitch = min(low_run_pitches)

        for tick_value, tick_notes in current_run:
            for pitch_value in tick_notes:
                if pitch_value == highest_low_pitch:
                    overrides[(tick_value, pitch_value)] = LANE_BLUE
                elif pitch_value == lowest_low_pitch:
                    overrides[(tick_value, pitch_value)] = LANE_GREEN

        current_run = []

    for tick_value, tick_notes in tom_ticks:
        tom_notes = [pitch_value for pitch_value in tick_notes if pitch_value in TOM_PITCHES]

        if not tom_notes:
            flush_run()
            continue

        current_run.append((tick_value, tom_notes))

    flush_run()

    return overrides


def build_open_hat_lane_overrides(
    drum_track: mido.MidiTrack,
    minimum_snare_velocity: int | None = None,
) -> Dict[Tuple[int, int], int]:
    hat_hits: list[Tuple[int, int]] = []
    absolute_source_tick = 0

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if message.note not in (42, 46):
            continue

        hat_hits.append((absolute_source_tick, message.note))

    overrides: Dict[Tuple[int, int], int] = {}

    for hit_index in range(1, len(hat_hits) - 1):
        current_tick, current_note = hat_hits[hit_index]
        previous_tick, previous_note = hat_hits[hit_index - 1]
        next_tick, next_note = hat_hits[hit_index + 1]

        if current_note != 46:
            continue

        if previous_note != 42 or next_note != 42:
            continue

        has_alternating_open_pattern = False

        if hit_index >= 2 and hat_hits[hit_index - 2][1] == 46:
            has_alternating_open_pattern = True

        if hit_index + 2 < len(hat_hits) and hat_hits[hit_index + 2][1] == 46:
            has_alternating_open_pattern = True

        if has_alternating_open_pattern:
            continue

        previous_gap = current_tick - previous_tick
        next_gap = next_tick - current_tick
        reference_gap = max(1, min(previous_gap, next_gap))

        if abs(previous_gap - next_gap) > reference_gap * 0.5:
            continue

        overrides[(current_tick, current_note)] = LANE_BLUE

    return overrides


def build_closed_hat_skips(
    drum_track: mido.MidiTrack,
    minimum_snare_velocity: int | None = None,
) -> set[Tuple[int, int]]:
    hat_hits: list[Tuple[int, int]] = []
    absolute_source_tick = 0

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if message.note not in (42, 46):
            continue

        hat_hits.append((absolute_source_tick, message.note))

    skipped_closed_hats: set[Tuple[int, int]] = set()

    for hit_index in range(1, len(hat_hits) - 1):
        current_tick, current_note = hat_hits[hit_index]
        previous_tick, previous_note = hat_hits[hit_index - 1]
        next_tick, next_note = hat_hits[hit_index + 1]

        if current_note != 42:
            continue

        if previous_note != 46 or next_note != 46:
            continue

        previous_gap = current_tick - previous_tick
        next_gap = next_tick - current_tick
        reference_gap = max(1, min(previous_gap, next_gap))

        if abs(previous_gap - next_gap) > reference_gap * 0.5:
            continue

        skipped_closed_hats.add((current_tick, current_note))

    return skipped_closed_hats


def resolve_lane(
    pitch_value: int,
    tom_lane_map: Dict[int, int],
) -> Tuple[Optional[int], bool]:
    if pitch_value in tom_lane_map:
        return tom_lane_map[pitch_value], False

    if pitch_value == 46:
        return LANE_YELLOW, True

    lane_result = GM_TO_RB.get(pitch_value)

    if lane_result is None:
        return None, False

    return lane_result

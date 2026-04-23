from __future__ import annotations

from typing import Dict, Optional, Tuple

import mido

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_YELLOW

from .constants import GM_TO_RB, TOM_PITCHES


def build_tom_pitch_map(drum_track: mido.MidiTrack) -> Dict[int, int]:
    """Mapeia pitches de tom GM para lanes Y/B/G."""
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


def classify_open_hat_mode(drum_track: mido.MidiTrack) -> bool:
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
    ride_count = sum(
        1
        for message in drum_track
        if message.type == "note_on"
        and message.velocity > 0
        and message.channel == 9
        and message.note in (51, 53, 59)
    )
    total_count = closed_count + open_count

    if total_count == 0:
        return False

    if open_count > 0 and ride_count >= max(16, int(open_count * 0.40)):
        return True

    return (open_count / total_count) >= 0.70


def resolve_lane(
    pitch_value: int,
    tom_lane_map: Dict[int, int],
    open_hat_yellow: bool,
) -> Tuple[Optional[int], bool]:
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

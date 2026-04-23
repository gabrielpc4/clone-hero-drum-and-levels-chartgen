from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import mido

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_SNARE, LANE_YELLOW

from .constants import LANE_LETTERS
from .mapping import build_tom_pitch_map, classify_open_hat_mode, resolve_lane
from .source import select_source_drum_track, track_name


def build_drums_track(
    src_mid: mido.MidiFile,
    drop_before_src_beat: float = 0.0,
    dedup_beats: float = 1 / 16,
) -> mido.MidiTrack:
    src_tpb = src_mid.ticks_per_beat
    drum_selection = select_source_drum_track(src_mid)
    drum_track = drum_selection.track
    open_hat_yellow = classify_open_hat_mode(drum_track)
    tom_lane_map = build_tom_pitch_map(drum_track)

    display_name = drum_selection.track_name if drum_selection.track_name else "<sem nome>"
    print(
        f"  Drum track: {display_name} | "
        f"mapped_hits={drum_selection.mapped_hits} | "
        f"channel9_hits={drum_selection.channel9_hits}"
    )
    print(f"  Open HH -> {'Y (folgado)' if open_hat_yellow else 'B (ride/accent)'}")
    print(
        f"  Tom map: "
        f"{[(pitch_value, LANE_LETTERS[lane_value]) for pitch_value, lane_value in sorted(tom_lane_map.items())]}"
    )

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

        lane_value, is_cymbal = resolve_lane(message.note, tom_lane_map, open_hat_yellow)

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
        source_tick = flam_first_tick if flam_first_tick is not None else absolute_source_tick

        if source_tick / src_tpb < drop_before_src_beat:
            continue

        lane_value, is_cymbal = resolve_lane(message.note, tom_lane_map, open_hat_yellow)

        if lane_value is None:
            continue

        if flam_first_tick is not None:
            lane_value = LANE_YELLOW
            is_cymbal = False

        mapped_events.append((source_tick, 96 + lane_value, lane_value, is_cymbal))

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
                    tick_value + src_tpb // 8,
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


def first_drum_tick(part_drums_track: mido.MidiTrack) -> Optional[int]:
    absolute_tick = 0

    for message in part_drums_track:
        absolute_tick += message.time

        if message.type == "note_on" and message.velocity > 0 and 96 <= message.note <= 100:
            return absolute_tick

    return None


def build_output_midi(src_mid: mido.MidiFile, part_drums_track: mido.MidiTrack) -> mido.MidiFile:
    output_mid = mido.MidiFile(type=src_mid.type, ticks_per_beat=src_mid.ticks_per_beat)
    replaced_drums = False

    for track in src_mid.tracks:
        if track_name(track) == "PART DRUMS":
            output_mid.tracks.append(part_drums_track)
            replaced_drums = True
        else:
            output_mid.tracks.append(track.copy())

    if not replaced_drums:
        output_mid.tracks.append(part_drums_track)

    return output_mid

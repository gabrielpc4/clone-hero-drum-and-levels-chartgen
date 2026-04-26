from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import mido

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_SNARE, LANE_YELLOW

from .constants import LANE_LETTERS, should_keep_source_hit
from .mapping import (
    build_closed_hat_skips,
    build_open_hat_lane_overrides,
    build_tom_lane_overrides,
    build_tom_pitch_map,
    resolve_lane,
)
from .source import select_source_drum_track, track_name


@dataclass
class MappedDrumEvent:
    source_tick: int
    pitch: int
    lane: int
    is_cymbal: bool


def collect_mapped_drum_events(
    src_mid: mido.MidiFile,
    dedup_beats: float = 1 / 16,
    minimum_snare_velocity: int | None = None,
    convert_flams_to_double_note: bool = True,
) -> list[MappedDrumEvent]:
    src_tpb = src_mid.ticks_per_beat
    drum_selection = select_source_drum_track(
        src_mid,
        minimum_snare_velocity=minimum_snare_velocity,
    )
    drum_track = drum_selection.track
    closed_hat_skips = build_closed_hat_skips(
        drum_track,
        minimum_snare_velocity=minimum_snare_velocity,
    )
    open_hat_lane_overrides = build_open_hat_lane_overrides(
        drum_track,
        minimum_snare_velocity=minimum_snare_velocity,
    )
    tom_lane_map = build_tom_pitch_map(
        drum_track,
        minimum_snare_velocity=minimum_snare_velocity,
    )
    tom_lane_overrides = build_tom_lane_overrides(
        drum_track,
        minimum_snare_velocity=minimum_snare_velocity,
    )

    display_name = drum_selection.track_name if drum_selection.track_name else "<sem nome>"
    print(
        f"  Drum track: {display_name} | "
        f"mapped_hits={drum_selection.mapped_hits} | "
        f"channel9_hits={drum_selection.channel9_hits}"
    )
    print(f"  Open HH -> Y por padrao; B apenas quando isolado entre closed hats")
    print(
        f"  Tom map: "
        f"{[(pitch_value, LANE_LETTERS[lane_value]) for pitch_value, lane_value in sorted(tom_lane_map.items())]}"
    )

    dedup_gap_ticks = int(round(src_tpb * dedup_beats))
    weak_snare_gap_ticks = max(1, src_tpb // 8)
    should_filter_weak_snares = minimum_snare_velocity is not None
    last_note_by_lane: Dict[Tuple[int, bool], int] = {}
    last_snare_tick_by_pitch: Dict[int, int] = {}
    skipped_flams = set()
    skipped_weak_snares = set()
    snare_flam_second_to_first: Dict[Tuple[int, int], int] = {}
    absolute_source_tick = 0

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if (absolute_source_tick, message.note) in closed_hat_skips:
            continue

        overridden_lane_value = tom_lane_overrides.get((absolute_source_tick, message.note))

        if overridden_lane_value is not None:
            lane_value, is_cymbal = overridden_lane_value, False
        elif (absolute_source_tick, message.note) in open_hat_lane_overrides:
            lane_value, is_cymbal = open_hat_lane_overrides[(absolute_source_tick, message.note)], True
        else:
            lane_value, is_cymbal = resolve_lane(message.note, tom_lane_map)

        if lane_value is None:
            continue

        if lane_value == LANE_SNARE:
            previous_same_pitch_tick = last_snare_tick_by_pitch.get(message.note)

            if (
                should_filter_weak_snares
                and previous_same_pitch_tick is not None
                and absolute_source_tick - previous_same_pitch_tick <= weak_snare_gap_ticks
            ):
                skipped_weak_snares.add((previous_same_pitch_tick, message.note))

            last_snare_tick_by_pitch[message.note] = absolute_source_tick

        lane_key = (lane_value, is_cymbal)
        previous_tick = last_note_by_lane.get(lane_key)

        if (
            convert_flams_to_double_note
            and previous_tick is not None
            and absolute_source_tick - previous_tick <= dedup_gap_ticks
        ):
            if lane_value == LANE_SNARE:
                skipped_weak_snares.discard((previous_tick, message.note))
                snare_flam_second_to_first[(absolute_source_tick, message.note)] = previous_tick
            else:
                skipped_flams.add((absolute_source_tick, message.note))

            continue

        last_note_by_lane[lane_key] = absolute_source_tick

    absolute_source_tick = 0
    mapped_events: list[MappedDrumEvent] = []

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if (absolute_source_tick, message.note) in closed_hat_skips:
            continue

        if (absolute_source_tick, message.note) in skipped_weak_snares:
            continue

        if (absolute_source_tick, message.note) in skipped_flams:
            continue

        flam_first_tick = snare_flam_second_to_first.get((absolute_source_tick, message.note))
        source_tick = flam_first_tick if flam_first_tick is not None else absolute_source_tick

        overridden_lane_value = tom_lane_overrides.get((absolute_source_tick, message.note))

        if overridden_lane_value is not None:
            lane_value, is_cymbal = overridden_lane_value, False
        elif (absolute_source_tick, message.note) in open_hat_lane_overrides:
            lane_value, is_cymbal = open_hat_lane_overrides[(absolute_source_tick, message.note)], True
        else:
            lane_value, is_cymbal = resolve_lane(message.note, tom_lane_map)

        if lane_value is None:
            continue

        if flam_first_tick is not None:
            lane_value = LANE_YELLOW
            is_cymbal = False

        mapped_events.append(
            MappedDrumEvent(
                source_tick=source_tick,
                pitch=96 + lane_value,
                lane=lane_value,
                is_cymbal=is_cymbal,
            )
        )

    unique_events = []
    seen_events = set()

    for event_value in sorted(mapped_events, key=lambda event: (event.source_tick, event.lane, event.pitch)):
        event_key = (event_value.source_tick, event_value.lane)

        if event_key in seen_events:
            continue

        seen_events.add(event_key)
        unique_events.append(event_value)

    return unique_events


def build_part_drums_track(
    mapped_events: list[MappedDrumEvent],
    target_tpb: int,
    tick_mapper: Callable[[int], int],
) -> mido.MidiTrack:
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="PART DRUMS", time=0))
    track.append(mido.MetaMessage("text", text="[mix 0 drums0]", time=0))

    output_events = []

    for event_value in mapped_events:
        tick_value = tick_mapper(event_value.source_tick)
        pitch_value = event_value.pitch
        lane_value = event_value.lane
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

    for event_value in mapped_events:
        tick_value = tick_mapper(event_value.source_tick)
        lane_value = event_value.lane
        is_cymbal = event_value.is_cymbal
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


def build_drums_track(
    src_mid: mido.MidiFile,
    dedup_beats: float = 1 / 16,
    minimum_snare_velocity: int | None = None,
    convert_flams_to_double_note: bool = True,
) -> mido.MidiTrack:
    mapped_events = collect_mapped_drum_events(
        src_mid,
        dedup_beats=dedup_beats,
        minimum_snare_velocity=minimum_snare_velocity,
        convert_flams_to_double_note=convert_flams_to_double_note,
    )

    return build_part_drums_track(
        mapped_events,
        target_tpb=src_mid.ticks_per_beat,
        tick_mapper=lambda source_tick: source_tick,
    )


def first_drum_tick(part_drums_track: mido.MidiTrack) -> Optional[int]:
    absolute_tick = 0

    for message in part_drums_track:
        absolute_tick += message.time

        if message.type == "note_on" and message.velocity > 0 and 96 <= message.note <= 100:
            return absolute_tick

    return None


def build_output_midi(template_mid: mido.MidiFile, part_drums_track: mido.MidiTrack) -> mido.MidiFile:
    output_mid = mido.MidiFile(type=template_mid.type, ticks_per_beat=template_mid.ticks_per_beat)
    replaced_drums = False

    for track in template_mid.tracks:
        if track_name(track) == "PART DRUMS":
            output_mid.tracks.append(part_drums_track)
            replaced_drums = True
        else:
            output_mid.tracks.append(track.copy())

    if not replaced_drums:
        output_mid.tracks.append(part_drums_track)

    return output_mid

from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import replace

import mido

from songsterr_import.source import select_source_drum_track
from songsterr_import.writer import MappedDrumEvent, build_part_drums_track, collect_mapped_drum_events


DEBUG_TICKS_PER_BEAT = 192
DEBUG_MEASURE_TICKS = DEBUG_TICKS_PER_BEAT * 4
DEBUG_GAP_TICKS = DEBUG_MEASURE_TICKS
DEBUG_TEMPO = 500000
PART_DRUMS_NAME = "PART DRUMS"


def _measure_markers(src_mid: mido.MidiFile) -> list[tuple[int, str]]:
    drum_track = select_source_drum_track(src_mid).track
    absolute_tick = 0
    markers: list[tuple[int, str]] = []

    for message in drum_track:
        absolute_tick += message.time

        if message.type != "marker":
            continue

        marker_text = getattr(message, "text", "")

        if not isinstance(marker_text, str):
            continue

        if not marker_text.startswith("MEASURE_"):
            continue

        markers.append((absolute_tick, marker_text))

    if not markers:
        raise RuntimeError("Nao encontrei markers MEASURE_n no track de bateria do Songsterr")

    return markers


def _track_end_tick(track: mido.MidiTrack) -> int:
    return sum(message.time for message in track)


def _measure_boundaries(src_mid: mido.MidiFile) -> list[tuple[int, int, str]]:
    drum_track = select_source_drum_track(src_mid).track
    markers = _measure_markers(src_mid)
    track_end_tick = _track_end_tick(drum_track)
    boundaries: list[tuple[int, int, str]] = []

    for marker_index, (start_tick, marker_text) in enumerate(markers):
        if marker_index + 1 < len(markers):
            end_tick = markers[marker_index + 1][0]
        else:
            end_tick = track_end_tick

        boundaries.append((start_tick, end_tick, marker_text))

    return boundaries


def _measure_index_for_tick(measure_boundaries: list[tuple[int, int, str]], source_tick: int) -> int | None:
    measure_starts = [start_tick for start_tick, _, _ in measure_boundaries]
    boundary_index = bisect_right(measure_starts, source_tick) - 1

    if boundary_index < 0:
        return None

    start_tick, end_tick, _ = measure_boundaries[boundary_index]

    if source_tick >= end_tick:
        return None

    return boundary_index


def _debug_tick_for_source_tick(
    source_tick: int,
    measure_index: int,
    measure_boundaries: list[tuple[int, int, str]],
) -> int:
    measure_start_tick, measure_end_tick, _ = measure_boundaries[measure_index]
    measure_length_ticks = max(1, measure_end_tick - measure_start_tick)
    measure_progress = (source_tick - measure_start_tick) / measure_length_ticks
    debug_measure_start_tick = measure_index * (DEBUG_MEASURE_TICKS + DEBUG_GAP_TICKS)
    within_measure_tick = int(round(measure_progress * max(1, DEBUG_MEASURE_TICKS - 1)))

    return debug_measure_start_tick + within_measure_tick


def build_measure_debug_mid(
    src_mid: mido.MidiFile,
    drop_before_src_beat: float = 0.0,
    dedup_beats: float = 1 / 16,
) -> mido.MidiFile:
    mapped_events = collect_mapped_drum_events(
        src_mid,
        drop_before_src_beat=drop_before_src_beat,
        dedup_beats=dedup_beats,
    )
    measure_boundaries = _measure_boundaries(src_mid)
    debug_events: list[MappedDrumEvent] = []

    for event_value in mapped_events:
        measure_index = _measure_index_for_tick(measure_boundaries, event_value.source_tick)

        if measure_index is None:
            continue

        debug_tick = _debug_tick_for_source_tick(
            event_value.source_tick,
            measure_index=measure_index,
            measure_boundaries=measure_boundaries,
        )
        debug_events.append(replace(event_value, source_tick=debug_tick))

    part_drums_track = build_part_drums_track(
        debug_events,
        target_tpb=DEBUG_TICKS_PER_BEAT,
        tick_mapper=lambda source_tick: source_tick,
    )

    conductor_track = mido.MidiTrack()
    conductor_track.append(mido.MetaMessage("set_tempo", tempo=DEBUG_TEMPO, time=0))
    conductor_track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=4,
            denominator=4,
            clocks_per_click=24,
            notated_32nd_notes_per_beat=8,
            time=0,
        )
    )
    conductor_track.append(mido.MetaMessage("end_of_track", time=0))

    events_track = mido.MidiTrack()
    events_track.append(mido.MetaMessage("track_name", name="EVENTS", time=0))

    previous_tick = 0

    for measure_index, (measure_start_tick, measure_end_tick, marker_text) in enumerate(measure_boundaries):
        debug_measure_start_tick = measure_index * (DEBUG_MEASURE_TICKS + DEBUG_GAP_TICKS)
        measure_length_ticks = measure_end_tick - measure_start_tick
        events_track.append(
            mido.MetaMessage(
                "marker",
                text=f"{marker_text} src={measure_start_tick}->{measure_end_tick} len={measure_length_ticks}",
                time=debug_measure_start_tick - previous_tick,
            )
        )
        previous_tick = debug_measure_start_tick

    events_track.append(mido.MetaMessage("end_of_track", time=0))

    output_mid = mido.MidiFile(type=1, ticks_per_beat=DEBUG_TICKS_PER_BEAT)
    output_mid.tracks.append(conductor_track)
    output_mid.tracks.append(part_drums_track)
    output_mid.tracks.append(events_track)

    return output_mid


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid")
    argument_parser.add_argument("out_mid")
    argument_parser.add_argument("--drop-before-src-beat", type=float, default=0.0)
    argument_parser.add_argument("--dedup-beats", type=float, default=1 / 16)
    args = argument_parser.parse_args()

    src_mid = mido.MidiFile(args.src_mid)
    output_mid = build_measure_debug_mid(
        src_mid,
        drop_before_src_beat=args.drop_before_src_beat,
        dedup_beats=args.dedup_beats,
    )
    output_mid.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

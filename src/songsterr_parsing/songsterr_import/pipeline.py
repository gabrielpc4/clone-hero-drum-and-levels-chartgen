from __future__ import annotations

from dataclasses import dataclass

import mido

from .measure_marker_sync import MeasureMarkerSync, build_measure_marker_tick_mapper
from .writer import (
    apply_expert_cymbal_alternation_to_part_drums_track,
    build_output_midi,
    build_part_drums_track,
    collect_mapped_drum_events,
    first_drum_tick,
)


@dataclass
class GenerationResult:
    output_mid: mido.MidiFile
    first_drum_tick: int | None
    measure_sync: MeasureMarkerSync | None = None


def generate_songsterr_drums_synced_to_measure_markers(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    initial_offset_seconds: float = 0.0,
    initial_offset_ticks: int = 0,
    minimum_snare_velocity: int | None = None,
    apply_expert_cymbal_alternation_whole_chart: bool = False,
    thin_all_cymbal_lines: bool = False,
) -> GenerationResult:
    mapped_events = collect_mapped_drum_events(
        src_mid,
        minimum_snare_velocity=minimum_snare_velocity,
    )
    tick_mapper, measure_sync = build_measure_marker_tick_mapper(
        src_mid,
        ref_mid,
        initial_offset_seconds=initial_offset_seconds,
        initial_offset_ticks=initial_offset_ticks,
    )
    part_drums_track = build_part_drums_track(
        mapped_events,
        target_tpb=ref_mid.ticks_per_beat,
        tick_mapper=tick_mapper,
    )
    if apply_expert_cymbal_alternation_whole_chart:
        part_drums_track, removed_cymbals = apply_expert_cymbal_alternation_to_part_drums_track(
            part_drums_track,
            ref_mid.ticks_per_beat,
            thin_all_cymbal_lines=thin_all_cymbal_lines,
        )
        print(
            f"  expert_cymbal 1/8 Y/B thin (G immune, steady runs only): "
            f"removed={removed_cymbals} note(s)"
        )
    output_mid = build_output_midi(ref_mid, part_drums_track)

    return GenerationResult(
        output_mid=output_mid,
        first_drum_tick=first_drum_tick(part_drums_track),
        measure_sync=measure_sync,
    )

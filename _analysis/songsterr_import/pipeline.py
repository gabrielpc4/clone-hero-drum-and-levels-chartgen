from __future__ import annotations

from dataclasses import dataclass

import mido

from .alignment import FirstNoteAlignment, build_first_note_audio_mapper
from .writer import (
    build_drums_track,
    build_output_midi,
    build_part_drums_track,
    collect_mapped_drum_events,
    first_drum_tick,
)


@dataclass
class GenerationResult:
    output_mid: mido.MidiFile
    first_drum_tick: int | None
    alignment: FirstNoteAlignment | None = None


def generate_songsterr_drums(
    src_mid: mido.MidiFile,
    drop_before_src_beat: float = 0.0,
    dedup_beats: float = 1 / 16,
) -> GenerationResult:
    part_drums_track = build_drums_track(
        src_mid,
        drop_before_src_beat=drop_before_src_beat,
        dedup_beats=dedup_beats,
    )
    output_mid = build_output_midi(src_mid, part_drums_track)

    return GenerationResult(
        output_mid=output_mid,
        first_drum_tick=first_drum_tick(part_drums_track),
    )


def generate_songsterr_drums_aligned_first_note(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    audio_path: str,
    drop_before_src_beat: float = 0.0,
    dedup_beats: float = 1 / 16,
) -> GenerationResult:
    mapped_events = collect_mapped_drum_events(
        src_mid,
        drop_before_src_beat=drop_before_src_beat,
        dedup_beats=dedup_beats,
    )
    tick_mapper, alignment = build_first_note_audio_mapper(
        src_mid,
        ref_mid,
        mapped_events,
        audio_path,
    )
    part_drums_track = build_part_drums_track(
        mapped_events,
        target_tpb=ref_mid.ticks_per_beat,
        tick_mapper=tick_mapper,
    )
    output_mid = build_output_midi(ref_mid, part_drums_track)

    return GenerationResult(
        output_mid=output_mid,
        first_drum_tick=first_drum_tick(part_drums_track),
        alignment=alignment,
    )

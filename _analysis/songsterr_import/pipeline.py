from __future__ import annotations

from dataclasses import dataclass

import mido

from .writer import build_drums_track, build_output_midi, first_drum_tick


@dataclass
class GenerationResult:
    output_mid: mido.MidiFile
    first_drum_tick: int | None


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

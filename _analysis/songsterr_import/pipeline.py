from __future__ import annotations

from dataclasses import dataclass

import mido
from parse_chart import build_tempo_map

from .alignment import FirstNoteAlignment, build_first_note_audio_mapper
from .audio import detect_first_dramatic_rise
from .songsterr_sync import SongsterrVideoSync, build_songsterr_video_tick_mapper
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
    video_sync: SongsterrVideoSync | None = None


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


def generate_songsterr_drums_synced_to_songsterr_video(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    songsterr_url: str,
    preferred_video_id: str | None = None,
    audio_path: str | None = None,
    drop_before_src_beat: float = 0.0,
    dedup_beats: float = 1 / 16,
) -> GenerationResult:
    mapped_events = collect_mapped_drum_events(
        src_mid,
        drop_before_src_beat=drop_before_src_beat,
        dedup_beats=dedup_beats,
    )
    tick_mapper, video_sync = build_songsterr_video_tick_mapper(
        src_mid,
        ref_mid,
        songsterr_url=songsterr_url,
        preferred_video_id=preferred_video_id,
    )
    if mapped_events and audio_path is not None:
        reference_tempo_map = build_tempo_map(ref_mid)
        base_tick_mapper = tick_mapper
        first_source_tick = min(event.source_tick for event in mapped_events)
        first_target_tick = base_tick_mapper(first_source_tick)
        first_target_seconds = reference_tempo_map.tick_to_seconds(first_target_tick)
        audio_rise = detect_first_dramatic_rise(audio_path)
        audio_offset_seconds = audio_rise.rise_seconds - first_target_seconds

        def tick_mapper_with_audio_offset(source_tick: int) -> int:
            warped_target_tick = base_tick_mapper(source_tick)
            warped_target_seconds = reference_tempo_map.tick_to_seconds(warped_target_tick)

            return reference_tempo_map.seconds_to_tick(warped_target_seconds + audio_offset_seconds)

        tick_mapper = tick_mapper_with_audio_offset
        video_sync.audio_offset_seconds = audio_offset_seconds
        video_sync.first_note_target_seconds = first_target_seconds
        video_sync.first_note_audio_seconds = audio_rise.rise_seconds

    part_drums_track = build_part_drums_track(
        mapped_events,
        target_tpb=ref_mid.ticks_per_beat,
        tick_mapper=tick_mapper,
    )
    output_mid = build_output_midi(ref_mid, part_drums_track)

    return GenerationResult(
        output_mid=output_mid,
        first_drum_tick=first_drum_tick(part_drums_track),
        video_sync=video_sync,
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import mido

from parse_chart import build_tempo_map

from .audio import (
    AudioRiseDetection,
    detect_audio_peak_times,
    detect_audio_rise_candidates,
    detect_first_dramatic_rise,
)
from .writer import MappedDrumEvent


@dataclass
class FirstNoteAlignment:
    audio_rise: AudioRiseDetection
    source_first_tick: int
    target_first_tick: int
    beat_offset: float


def _select_audio_rise_with_pattern(
    audio_path: str,
    source_onset_seconds: list[float],
) -> AudioRiseDetection:
    rise_candidates = detect_audio_rise_candidates(audio_path)
    peak_times = detect_audio_peak_times(audio_path)
    source_first_seconds = source_onset_seconds[0]

    if not rise_candidates or len(source_onset_seconds) < 4 or not peak_times:
        return detect_first_dramatic_rise(audio_path)

    source_intervals = [current_seconds - source_first_seconds for current_seconds in source_onset_seconds[1:8]]
    constrained_candidates = [
        candidate
        for candidate in rise_candidates
        if (source_first_seconds - 1.0) <= candidate.rise_seconds <= (source_first_seconds + 10.0)
    ]

    if constrained_candidates:
        rise_candidates = constrained_candidates

    best_candidate = None
    best_key = None

    for candidate in rise_candidates:
        match_count = 0
        distance_sum = 0.0

        for interval_seconds in source_intervals:
            expected_time = candidate.rise_seconds + interval_seconds
            nearest_time = min(peak_times, key=lambda peak_time: abs(peak_time - expected_time))
            distance_seconds = abs(nearest_time - expected_time)

            if distance_seconds <= 0.08:
                match_count += 1
                distance_sum += distance_seconds

        ranking_key = (
            match_count >= 4,
            match_count,
            -distance_sum,
            -candidate.score,
            -abs(candidate.rise_seconds - source_first_seconds),
            candidate.rise_seconds >= source_first_seconds,
            -candidate.rise_seconds,
        )

        if best_key is None or ranking_key > best_key:
            best_key = ranking_key
            best_candidate = candidate

        if match_count >= 4:
            return candidate

    if best_candidate is not None:
        return best_candidate

    return detect_first_dramatic_rise(audio_path)


def build_first_note_audio_mapper(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    mapped_events: list[MappedDrumEvent],
    audio_path: str,
) -> tuple[Callable[[int], int], FirstNoteAlignment]:
    if not mapped_events:
        raise RuntimeError("Não há notas de bateria mapeadas para alinhar")

    src_tempo_map = build_tempo_map(src_mid)
    source_onset_ticks = sorted({event.source_tick for event in mapped_events})
    source_onset_seconds = [src_tempo_map.tick_to_seconds(source_tick) for source_tick in source_onset_ticks[:12]]
    audio_rise = _select_audio_rise_with_pattern(audio_path, source_onset_seconds)
    ref_tempo_map = build_tempo_map(ref_mid)
    source_first_tick = min(event.source_tick for event in mapped_events)
    target_first_tick = ref_tempo_map.seconds_to_tick(audio_rise.rise_seconds)
    source_first_beat = source_first_tick / src_mid.ticks_per_beat
    target_first_beat = target_first_tick / ref_mid.ticks_per_beat
    beat_offset = target_first_beat - source_first_beat

    def tick_mapper(source_tick: int) -> int:
        source_beat = source_tick / src_mid.ticks_per_beat

        return int(round((source_beat + beat_offset) * ref_mid.ticks_per_beat))

    return tick_mapper, FirstNoteAlignment(
        audio_rise=audio_rise,
        source_first_tick=source_first_tick,
        target_first_tick=target_first_tick,
        beat_offset=beat_offset,
    )

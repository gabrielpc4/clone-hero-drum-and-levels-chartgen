from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable

import mido

from parse_chart import build_tempo_map, read_conductor_track

from .source import select_source_drum_track


DEFAULT_INITIAL_OFFSET_TICKS = 768


@dataclass
class MeasureMarkerSync:
    source_measure_count: int
    target_measure_count: int
    paired_measure_count: int
    initial_measure_offset: int
    initial_offset_seconds: float
    initial_offset_ticks: int
    split_measure_count: int


def measure_start_ticks(mid: mido.MidiFile) -> list[int]:
    _, time_signatures = read_conductor_track(mid)

    if not time_signatures:
        time_signatures = [(0, 4, 4)]

    end_tick = max(sum(message.time for message in track) for track in mid.tracks)
    measure_ticks: list[int] = []

    for signature_index, (signature_tick, numerator_value, denominator_value) in enumerate(time_signatures):
        if signature_index + 1 < len(time_signatures):
            next_signature_tick = time_signatures[signature_index + 1][0]
        else:
            next_signature_tick = end_tick + 1

        ticks_per_measure = int(mid.ticks_per_beat * numerator_value * (4 / denominator_value))
        current_measure_tick = signature_tick

        while current_measure_tick < next_signature_tick:
            measure_ticks.append(current_measure_tick)
            current_measure_tick += ticks_per_measure

    return measure_ticks


def build_tick_anchor_mapper(
    source_anchor_ticks: list[int],
    target_anchor_ticks: list[int],
) -> Callable[[int], int]:
    if len(source_anchor_ticks) != len(target_anchor_ticks):
        raise RuntimeError("Os anchors em tick precisam ter o mesmo tamanho")

    if len(source_anchor_ticks) < 2:
        raise RuntimeError("Sao necessarios pelo menos dois anchors em tick para o warp")

    def map_tick(source_tick: int) -> int:
        if source_tick <= source_anchor_ticks[0]:
            return target_anchor_ticks[0] + (source_tick - source_anchor_ticks[0])

        if source_tick >= source_anchor_ticks[-1]:
            return target_anchor_ticks[-1] + (source_tick - source_anchor_ticks[-1])

        right_index = bisect_right(source_anchor_ticks, source_tick)
        left_source_tick = source_anchor_ticks[right_index - 1]
        right_source_tick = source_anchor_ticks[right_index]
        left_target_tick = target_anchor_ticks[right_index - 1]
        right_target_tick = target_anchor_ticks[right_index]
        source_gap_ticks = right_source_tick - left_source_tick

        if source_gap_ticks <= 0:
            return left_target_tick

        progress_ratio = (source_tick - left_source_tick) / source_gap_ticks

        return int(round(left_target_tick + progress_ratio * (right_target_tick - left_target_tick)))

    return map_tick


def _source_measure_marker_ticks(src_mid: mido.MidiFile) -> list[int]:
    drum_track = select_source_drum_track(src_mid).track
    absolute_tick = 0
    marker_ticks: list[int] = []

    for message in drum_track:
        absolute_tick += message.time

        if message.type != "marker":
            continue

        marker_text = getattr(message, "text", "")

        if not isinstance(marker_text, str):
            continue

        if not marker_text.startswith("MEASURE_"):
            continue

        marker_ticks.append(absolute_tick)

    if len(marker_ticks) < 2:
        raise RuntimeError("O MIDI fonte nao tem markers MEASURE_n suficientes no track de bateria")

    return sorted(set(marker_ticks))


def _resolve_initial_target_measure_offset(
    target_measure_ticks: list[int],
    initial_offset_ticks: int,
) -> tuple[int, int]:
    if initial_offset_ticks <= 0 or len(target_measure_ticks) < 2:
        return 0, initial_offset_ticks

    remaining_offset_ticks = initial_offset_ticks
    target_measure_offset = 0

    while target_measure_offset + 1 < len(target_measure_ticks):
        current_measure_length = target_measure_ticks[target_measure_offset + 1] - target_measure_ticks[target_measure_offset]

        if remaining_offset_ticks < current_measure_length:
            break

        remaining_offset_ticks -= current_measure_length
        target_measure_offset += 1

    return target_measure_offset, remaining_offset_ticks


def _build_adaptive_measure_anchors(
    source_measure_ticks: list[int],
    target_measure_ticks: list[int],
    source_tempo_map,
    target_tempo_map,
) -> tuple[list[int], list[int], int, int]:
    source_anchor_ticks = [source_measure_ticks[0]]
    target_anchor_ticks = [target_measure_ticks[0]]
    source_measure_index = 0
    target_measure_index = 0
    split_measure_count = 0
    consumed_target_measure_count = 1

    while source_measure_index + 1 < len(source_measure_ticks) and target_measure_index + 1 < len(target_measure_ticks):
        source_start_tick = source_measure_ticks[source_measure_index]
        source_end_tick = source_measure_ticks[source_measure_index + 1]
        source_start_seconds = source_tempo_map.tick_to_seconds(source_start_tick)
        source_end_seconds = source_tempo_map.tick_to_seconds(source_end_tick)
        source_measure_seconds = source_end_seconds - source_start_seconds

        one_target_end_tick = target_measure_ticks[target_measure_index + 1]
        one_target_seconds = (
            target_tempo_map.tick_to_seconds(one_target_end_tick)
            - target_tempo_map.tick_to_seconds(target_measure_ticks[target_measure_index])
        )

        choose_two_target_measures = False

        if target_measure_index + 2 < len(target_measure_ticks):
            two_target_end_tick = target_measure_ticks[target_measure_index + 2]
            two_target_seconds = (
                target_tempo_map.tick_to_seconds(two_target_end_tick)
                - target_tempo_map.tick_to_seconds(target_measure_ticks[target_measure_index])
            )

            if abs(source_measure_seconds - two_target_seconds) + 0.05 < abs(source_measure_seconds - one_target_seconds):
                choose_two_target_measures = True

        if choose_two_target_measures:
            midpoint_target_tick = target_measure_ticks[target_measure_index + 1]
            target_span_seconds = (
                target_tempo_map.tick_to_seconds(target_measure_ticks[target_measure_index + 2])
                - target_tempo_map.tick_to_seconds(target_measure_ticks[target_measure_index])
            )
            midpoint_ratio = (
                target_tempo_map.tick_to_seconds(midpoint_target_tick)
                - target_tempo_map.tick_to_seconds(target_measure_ticks[target_measure_index])
            ) / max(target_span_seconds, 1e-9)
            midpoint_source_seconds = source_start_seconds + midpoint_ratio * source_measure_seconds
            midpoint_source_tick = source_tempo_map.seconds_to_tick(midpoint_source_seconds)

            if source_start_tick < midpoint_source_tick < source_end_tick:
                source_anchor_ticks.append(midpoint_source_tick)
                target_anchor_ticks.append(midpoint_target_tick)
                split_measure_count += 1

            source_anchor_ticks.append(source_end_tick)
            target_anchor_ticks.append(target_measure_ticks[target_measure_index + 2])
            source_measure_index += 1
            target_measure_index += 2
            consumed_target_measure_count += 2
            continue

        source_anchor_ticks.append(source_end_tick)
        target_anchor_ticks.append(one_target_end_tick)
        source_measure_index += 1
        target_measure_index += 1
        consumed_target_measure_count += 1

    return source_anchor_ticks, target_anchor_ticks, consumed_target_measure_count, split_measure_count


def build_measure_marker_tick_mapper(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    initial_offset_seconds: float = 0.0,
    initial_offset_ticks: int = DEFAULT_INITIAL_OFFSET_TICKS,
) -> tuple[callable, MeasureMarkerSync]:
    source_measure_ticks = _source_measure_marker_ticks(src_mid)
    target_measure_ticks = measure_start_ticks(ref_mid)
    if min(len(source_measure_ticks), len(target_measure_ticks)) < 2:
        raise RuntimeError("Nao ha compassos suficientes para montar o sync por MEASURE_n")

    source_tempo_map = build_tempo_map(src_mid)
    resolved_initial_offset_ticks = initial_offset_ticks

    if initial_offset_seconds != 0.0:
        reference_tempo_map = build_tempo_map(ref_mid)
        first_target_seconds = reference_tempo_map.tick_to_seconds(target_measure_ticks[0])
        shifted_target_seconds = first_target_seconds + initial_offset_seconds
        resolved_initial_offset_ticks += (
            reference_tempo_map.seconds_to_tick(shifted_target_seconds) - target_measure_ticks[0]
        )

    initial_measure_offset, residual_initial_offset_ticks = _resolve_initial_target_measure_offset(
        target_measure_ticks,
        resolved_initial_offset_ticks,
    )
    shifted_target_measure_ticks = [
        tick_value + residual_initial_offset_ticks
        for tick_value in target_measure_ticks[initial_measure_offset:]
    ]
    target_tempo_map = build_tempo_map(ref_mid)
    source_anchor_ticks, target_anchor_ticks, consumed_target_measure_count, split_measure_count = _build_adaptive_measure_anchors(
        source_measure_ticks,
        shifted_target_measure_ticks,
        source_tempo_map=source_tempo_map,
        target_tempo_map=target_tempo_map,
    )

    tick_mapper = build_tick_anchor_mapper(
        source_anchor_ticks,
        target_anchor_ticks,
    )

    return tick_mapper, MeasureMarkerSync(
        source_measure_count=len(source_measure_ticks),
        target_measure_count=len(target_measure_ticks),
        paired_measure_count=consumed_target_measure_count,
        initial_measure_offset=initial_measure_offset,
        initial_offset_seconds=initial_offset_seconds,
        initial_offset_ticks=resolved_initial_offset_ticks,
        split_measure_count=split_measure_count,
    )

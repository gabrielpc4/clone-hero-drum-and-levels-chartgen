from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import mido

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_SNARE, LANE_YELLOW

# Expert Y/B/G (cymbals) e markers de tom; alternância 1/8 do import = writer (G imune), não 1:1 C#
# Expert kick / snare / Y / B / G: 96, 97, 98, 99, 100 (parse_drums)
EXPERT_CYMBAL_PITCHES = (98, 99, 100)
EXPERT_SNARE_PITCH = 97
TOM_MARKER_PITCH_BY_EXPERT = {98: 110, 99: 111, 100: 112}

from .constants import should_keep_source_hit
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
    minimum_snare_velocity: int | None = None,
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
        f"  source_drum_track: name={display_name} "
        f"mapped_hits={drum_selection.mapped_hits} "
        f"channel9_hits={drum_selection.channel9_hits}"
    )

    weak_snare_gap_ticks = max(1, src_tpb // 8)
    should_filter_weak_snares = minimum_snare_velocity is not None
    last_snare_tick_by_pitch: Dict[int, int] = {}
    skipped_weak_snares = set()
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

        source_tick = absolute_source_tick

        overridden_lane_value = tom_lane_overrides.get((absolute_source_tick, message.note))

        if overridden_lane_value is not None:
            lane_value, is_cymbal = overridden_lane_value, False
        elif (absolute_source_tick, message.note) in open_hat_lane_overrides:
            lane_value, is_cymbal = open_hat_lane_overrides[(absolute_source_tick, message.note)], True
        else:
            lane_value, is_cymbal = resolve_lane(message.note, tom_lane_map)

        if lane_value is None:
            continue

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


def _build_tom_intervals_for_marker(
    part_drums_track: mido.MidiTrack, marker_pitch: int
) -> list[tuple[int, int]]:
    """
    Intervalos [start, end) em que o marker 110/111/112 indica "tom" na lane
    (paridade com CymbalAlternationService.BuildTomIntervals + IsTickInsideTomInterval).
    """
    abs_tick = 0
    is_active = False
    start_tick = 0
    intervals: list[tuple[int, int]] = []
    for message in part_drums_track:
        abs_tick += message.time
        if message.type == "note_on" and (int(message.note) if hasattr(message, "note") else -1) == marker_pitch:
            if message.velocity > 0:
                if not is_active:
                    is_active = True
                    start_tick = abs_tick
            else:
                if is_active:
                    intervals.append((start_tick, abs_tick))
                    is_active = False
        elif message.type == "note_off" and int(message.note) == marker_pitch:
            if is_active:
                intervals.append((start_tick, abs_tick))
                is_active = False
    if is_active:
        intervals.append((start_tick, 10**18))
    return intervals


def _expert_cymbal_tick_is_tom(
    tick: int, expert_pitch: int, tom_by_expert: dict[int, list[tuple[int, int]]]
) -> bool:
    for start_t, end_t in tom_by_expert.get(expert_pitch, ()):
        if start_t <= tick < end_t:
            return True
    return False


def _eighth_duration_ticks(ticks_per_beat: int) -> int:
    """
    Colcheia = metade de uma semínima em ticks (semínima = tpb); alinha a passo 1/16
    com nota 1/8 a cada duas linhas. O compasso não muda tpb, só a divisão da barra.
    """
    return max(1, int(ticks_per_beat) // 2)


def _gap_is_steady_musical_eighth(gap: int, eighth_duration_ticks: int) -> bool:
    """Colcheia estável entre dois hits: intervalo de ~1/2 semínima (não 32a nem pausa de colcheia)."""
    e = max(1, int(eighth_duration_ticks))
    gap_int = int(gap)
    low = max(1, int(0.72 * e))
    high = int(1.32 * e) + 1
    return low <= gap_int <= high


def _iter_musical_eighth_runs(
    cymbals_sorted: list[tuple[int, int]], eighth_duration_ticks: int
) -> list[tuple[int, int]]:
    """
    Cortes (start_idx, end_idx) inclusivos, comprimento >= 2, onde pares consecutivos
    formam cadeia de 1/8. Outros intervalos = quebra (virada, pausa, acorde no mesmo tick).
    """
    n = len(cymbals_sorted)
    if n < 2:
        return []
    e = max(1, int(eighth_duration_ticks))
    runs: list[tuple[int, int]] = []
    start = 0
    while start < n:
        end = start
        while end + 1 < n and _gap_is_steady_musical_eighth(
            cymbals_sorted[end + 1][0] - cymbals_sorted[end][0], e
        ):
            end += 1
        if end > start:
            runs.append((start, end))
        start = end + 1
    return runs


def _expert_snare_on_ticks_sorted(part_drums_track: mido.MidiTrack) -> list[int]:
    """Instantes (ticks) de note_on Expert com caixa (97) no PART DRUMS."""
    out: list[int] = []
    abs_t = 0
    for message in part_drums_track:
        abs_t += message.time
        if message.type != "note_on" or message.velocity <= 0:
            continue
        if int(message.note) == EXPERT_SNARE_PITCH:
            out.append(abs_t)
    out.sort()
    return out


def _cymbal_run_includes_expert_snare_in_span(
    tick_first: int, tick_last: int, snare_ticks_sorted: list[int]
) -> bool:
    """Há pelo menos uma caixa (97) entre o primeiro e o último prato da cadeia (inclusive)."""
    if not snare_ticks_sorted or tick_last < tick_first:
        return False
    insert = bisect.bisect_left(snare_ticks_sorted, tick_first)
    if insert < len(snare_ticks_sorted) and snare_ticks_sorted[insert] <= tick_last:
        return True
    return False


def _yb_cymbals_to_thin_in_run_segment(
    yb_only: list[tuple[int, int]],
    has_virtual_at_start: bool,
) -> set[tuple[int, int]]:
    """
    Só 98/99. Bursts de 2+ da *nova* cor: mantém todos, último revira a fase (virtual).
    Paridade: com virtual, remove 0,2,4; sem, remove 1,3,5.
    """
    to_remove: set[tuple[int, int]] = set()
    if len(yb_only) < 2:
        return to_remove

    has_virtual = has_virtual_at_start
    yb_index = 0
    k = 0
    while yb_index < len(yb_only):
        t0, p0 = yb_only[yb_index]
        if (
            yb_index + 1 < len(yb_only)
            and p0 == yb_only[yb_index + 1][1]
            and yb_index > 0
            and yb_only[yb_index - 1][1] != p0
        ):
            block_end = yb_index
            while block_end < len(yb_only) and yb_only[block_end][1] == p0:
                block_end += 1
            if block_end - yb_index >= 2:
                yb_index = block_end
                k = 0
                has_virtual = True
                continue
        is_remove = (k % 2 == 0) if has_virtual else (k % 2 == 1)
        if is_remove:
            to_remove.add((t0, p0))
        yb_index += 1
        k += 1
    return to_remove


def _yb_cymbals_to_thin_in_steady_musical_eighth_run(
    run_segment: list[tuple[int, int]],
) -> set[tuple[int, int]]:
    """
    Pitch 100 (G) é imune, mas ainda pode quebrar/reiniciar a fase:
    - G sozinho em um tick vira âncora virtual para o próximo trecho Y/B.
    - G junto com Y/B no mesmo tick reinicia a sequência, mas não vira virtual
      para o Y/B daquele mesmo tick.
    """
    to_remove: set[tuple[int, int]] = set()
    grouped_by_tick: list[tuple[int, list[int]]] = []

    for tick_value, pitch_value in run_segment:
        if grouped_by_tick and grouped_by_tick[-1][0] == tick_value:
            grouped_by_tick[-1][1].append(pitch_value)
            continue

        grouped_by_tick.append((tick_value, [pitch_value]))

    current_chunk: list[tuple[int, int]] = []
    current_chunk_has_virtual = False
    next_chunk_has_virtual = False

    def flush_current_chunk() -> None:
        nonlocal current_chunk
        nonlocal current_chunk_has_virtual
        nonlocal to_remove

        if not current_chunk:
            return

        to_remove |= _yb_cymbals_to_thin_in_run_segment(
            current_chunk,
            current_chunk_has_virtual,
        )
        current_chunk = []
        current_chunk_has_virtual = False

    for tick_value, pitches_at_tick in grouped_by_tick:
        has_green = 100 in pitches_at_tick
        yb_pitches = [pitch_value for pitch_value in pitches_at_tick if pitch_value in (98, 99)]

        if has_green:
            flush_current_chunk()

            if yb_pitches:
                current_chunk_has_virtual = False
                current_chunk = [(tick_value, pitch_value) for pitch_value in yb_pitches]
                next_chunk_has_virtual = False
            else:
                next_chunk_has_virtual = True

            continue

        if yb_pitches and not current_chunk:
            current_chunk_has_virtual = next_chunk_has_virtual
            next_chunk_has_virtual = False

        for pitch_value in yb_pitches:
            current_chunk.append((tick_value, pitch_value))

    flush_current_chunk()
    return to_remove


def apply_expert_cymbal_alternation_to_part_drums_track(
    part_drums_track: mido.MidiTrack,
    ticks_per_beat: int,
) -> tuple[mido.MidiTrack, int]:
    """
    Afinar colcheias Y/B Expert em cadeias estáveis (1/8) na grade musical; 100 (G) imune.
    Fora de cadeia de 1/8 (virada, 32a, acorde rítmico) não altera. 2+ da *nova* cor: mantém
    e o último ancora a nova fase. Tom: mesmos intervalos 110/111/112.
    Só aplica se existir caixa Expert (97) nesse arco: sequência longa de só pratos, ou
    pratos + bumbo (96) sem 97, não afinar.
    """
    _eighth = _eighth_duration_ticks(ticks_per_beat)
    snare_ticks = _expert_snare_on_ticks_sorted(part_drums_track)

    tom_by_expert: dict[int, list[tuple[int, int]]] = {
        p: _build_tom_intervals_for_marker(
            part_drums_track, TOM_MARKER_PITCH_BY_EXPERT[p]
        )
        for p in EXPERT_CYMBAL_PITCHES
    }

    candidates: list[tuple[int, int]] = []
    abs_t = 0
    for message in part_drums_track:
        abs_t += message.time
        if message.type != "note_on" or message.velocity <= 0:
            continue
        pitch = int(message.note)
        if pitch not in EXPERT_CYMBAL_PITCHES:
            continue
        if _expert_cymbal_tick_is_tom(abs_t, pitch, tom_by_expert):
            continue
        candidates.append((abs_t, pitch))

    if not candidates:
        return part_drums_track, 0

    candidates.sort(key=lambda item: (item[0], item[1]))
    run_ranges = _iter_musical_eighth_runs(candidates, _eighth)
    to_remove: set[tuple[int, int]] = set()
    for st, en in run_ranges:
        part = [candidates[i] for i in range(st, en + 1)]
        tick_first, tick_last = part[0][0], part[-1][0]
        if not _cymbal_run_includes_expert_snare_in_span(
            tick_first, tick_last, snare_ticks
        ):
            continue
        to_remove |= _yb_cymbals_to_thin_in_steady_musical_eighth_run(part)

    if not to_remove:
        return part_drums_track, 0

    # Reconstrói o track: remove pares (note_on, note_off) para cada (tick, pitch) em to_remove
    abs_events: list[tuple[int, mido.Message]] = []
    abs_t = 0
    for message in part_drums_track:
        abs_t += message.time
        if message.is_meta and message.type == "end_of_track":
            continue
        abs_events.append((abs_t, message))

    new_events: list[tuple[int, mido.Message]] = []
    index = 0
    while index < len(abs_events):
        abs_tick, msg = abs_events[index]
        if (
            msg.type == "note_on"
            and msg.velocity > 0
            and int(msg.note) in (98, 99)
            and (abs_tick, int(msg.note)) in to_remove
        ):
            removed_pitch = int(msg.note)
            index += 1
            while index < len(abs_events):
                at2, m2 = abs_events[index]
                is_close = (m2.type == "note_on" and m2.velocity == 0 and int(m2.note) == removed_pitch) or (
                    m2.type == "note_off" and int(m2.note) == removed_pitch
                )
                if is_close:
                    index += 1
                    break
                new_events.append((at2, m2))
                index += 1
            continue
        new_events.append((abs_tick, msg))
        index += 1

    if not new_events:
        new_track = mido.MidiTrack()
        new_track.append(mido.MetaMessage("end_of_track", time=0))
        return new_track, len(to_remove)

    new_events.sort(key=lambda item: item[0])
    out = mido.MidiTrack()
    last = 0
    for t_time, m in new_events:
        m2 = m.copy(time=t_time - last)
        out.append(m2)
        last = t_time
    out.append(mido.MetaMessage("end_of_track", time=0))
    return out, len(to_remove)


def build_drums_track(
    src_mid: mido.MidiFile,
    minimum_snare_velocity: int | None = None,
) -> mido.MidiTrack:
    mapped_events = collect_mapped_drum_events(
        src_mid,
        minimum_snare_velocity=minimum_snare_velocity,
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


def build_output_midi_with_track_replacements(
    template_mid: mido.MidiFile,
    replacement_tracks: Dict[str, mido.MidiTrack],
) -> mido.MidiFile:
    output_mid = mido.MidiFile(type=template_mid.type, ticks_per_beat=template_mid.ticks_per_beat)
    replaced_track_names = set()

    for track in template_mid.tracks:
        current_track_name = track_name(track)

        if current_track_name in replacement_tracks:
            output_mid.tracks.append(replacement_tracks[current_track_name])
            replaced_track_names.add(current_track_name)
            continue

        output_mid.tracks.append(track.copy())

    for current_track_name, replacement_track in replacement_tracks.items():
        if current_track_name in replaced_track_names:
            continue

        output_mid.tracks.append(replacement_track)

    return output_mid


def build_output_midi(template_mid: mido.MidiFile, part_drums_track: mido.MidiTrack) -> mido.MidiFile:
    return build_output_midi_with_track_replacements(
        template_mid,
        {"PART DRUMS": part_drums_track},
    )

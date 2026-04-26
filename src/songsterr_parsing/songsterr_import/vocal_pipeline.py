from __future__ import annotations

from dataclasses import dataclass

import mido

from chart_generation.parse_vocals import (
    VocalChart,
    VocalPhrase,
    build_minimal_vocal_text_events,
    group_source_vocal_notes,
    infer_vocal_phrases,
    map_vocal_notes_to_target,
)

from .measure_marker_sync import MeasureMarkerSync, build_measure_marker_tick_mapper
from .vocal_source import collect_track_vocal_notes, select_source_vocal_track
from .writer import build_output_midi_with_track_replacements


@dataclass
class VocalGenerationResult:
    output_mid: mido.MidiFile
    source_track_name: str
    note_count: int
    phrase_count: int
    measure_sync: MeasureMarkerSync | None = None


def build_part_vocals_track(vocal_chart: VocalChart) -> mido.MidiTrack:
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="PART VOCALS", time=0))
    output_events: list[tuple[int, int, object]] = []

    for tick_value, text_value in vocal_chart.text_events:
        output_events.append((tick_value, 0, mido.MetaMessage("text", text=text_value, time=0)))

    for note_value in vocal_chart.notes:
        output_events.append(
            (
                note_value.tick,
                1,
                mido.Message("note_on", note=note_value.pitch, velocity=note_value.velocity, channel=0, time=0),
            )
        )
        output_events.append(
            (
                note_value.end_tick,
                3,
                mido.Message("note_off", note=note_value.pitch, velocity=0, channel=0, time=0),
            )
        )

    for phrase_value in vocal_chart.phrases:
        output_events.append(
            (
                phrase_value.start_tick,
                1,
                mido.Message("note_on", note=105, velocity=100, channel=0, time=0),
            )
        )
        output_events.append(
            (
                phrase_value.end_tick,
                2,
                mido.Message("note_off", note=105, velocity=0, channel=0, time=0),
            )
        )

    output_events.sort(key=lambda event_value: (event_value[0], event_value[1]))
    last_tick = 0

    for absolute_tick, _, message in output_events:
        track.append(message.copy(time=absolute_tick - last_tick))
        last_tick = absolute_tick

    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def generate_songsterr_vocals_synced_to_measure_markers(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    initial_offset_seconds: float = 0.0,
    initial_offset_ticks: int = 0,
) -> VocalGenerationResult:
    vocal_selection = select_source_vocal_track(src_mid)
    source_note_values = collect_track_vocal_notes(vocal_selection.track)
    if not source_note_values:
        raise RuntimeError("A track vocal selecionada nao tinha notas mapeaveis")

    print(
        "  source_vocal_track: "
        + f"name={vocal_selection.track_name or '<sem nome>'} "
        + f"notes={vocal_selection.note_count} "
        + f"grouped_notes={vocal_selection.grouped_note_count}"
    )

    grouped_source_notes = group_source_vocal_notes(source_note_values)
    tick_mapper, measure_sync = build_measure_marker_tick_mapper(
        src_mid,
        ref_mid,
        initial_offset_seconds=initial_offset_seconds,
        initial_offset_ticks=initial_offset_ticks,
    )
    mapped_note_values = map_vocal_notes_to_target(grouped_source_notes, tick_mapper)
    if not mapped_note_values:
        raise RuntimeError("Nao foi possivel gerar notas vocais apos o mapeamento de tempo")

    phrase_values: list[VocalPhrase] = infer_vocal_phrases(
        mapped_note_values,
        ticks_per_beat=ref_mid.ticks_per_beat,
    )
    text_events = build_minimal_vocal_text_events(
        phrase_values,
        ticks_per_beat=ref_mid.ticks_per_beat,
    )
    vocal_chart = VocalChart(
        ticks_per_beat=ref_mid.ticks_per_beat,
        notes=mapped_note_values,
        phrases=phrase_values,
        text_events=text_events,
    )
    part_vocals_track = build_part_vocals_track(vocal_chart)
    output_mid = build_output_midi_with_track_replacements(
        ref_mid,
        {"PART VOCALS": part_vocals_track},
    )

    return VocalGenerationResult(
        output_mid=output_mid,
        source_track_name=vocal_selection.track_name,
        note_count=len(mapped_note_values),
        phrase_count=len(phrase_values),
        measure_sync=measure_sync,
    )

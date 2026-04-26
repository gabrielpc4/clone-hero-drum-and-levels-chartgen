from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from songsterr_parsing.songsterr_import.vocal_source import SourceVocalNote


@dataclass
class VocalNote:
    tick: int
    end_tick: int
    pitch: int
    velocity: int = 100


@dataclass
class VocalPhrase:
    start_tick: int
    end_tick: int


@dataclass
class VocalChart:
    ticks_per_beat: int
    notes: list[VocalNote] = field(default_factory=list)
    phrases: list[VocalPhrase] = field(default_factory=list)
    text_events: list[tuple[int, str]] = field(default_factory=list)


def _note_duration(note_value: SourceVocalNote) -> int:
    return max(1, note_value.end_tick - note_value.start_tick)


def _choose_representative_source_note(
    note_values: list[SourceVocalNote],
    previous_pitch: int | None,
) -> SourceVocalNote:
    if previous_pitch is None:
        ordered_notes = sorted(
            note_values,
            key=lambda note_value: (-_note_duration(note_value), -note_value.velocity, note_value.pitch),
        )
        return ordered_notes[0]

    ordered_notes = sorted(
        note_values,
        key=lambda note_value: (
            abs(note_value.pitch - previous_pitch),
            -_note_duration(note_value),
            -note_value.velocity,
            note_value.pitch,
        ),
    )
    return ordered_notes[0]


def group_source_vocal_notes(note_values: list[SourceVocalNote]) -> list[VocalNote]:
    note_values_by_tick: dict[int, list[SourceVocalNote]] = defaultdict(list)

    for note_value in note_values:
        note_values_by_tick[note_value.start_tick].append(note_value)

    grouped_notes: list[VocalNote] = []
    previous_pitch: int | None = None

    for tick_value in sorted(note_values_by_tick):
        chosen_note = _choose_representative_source_note(
            note_values_by_tick[tick_value],
            previous_pitch=previous_pitch,
        )
        end_tick = max(chosen_note.end_tick, chosen_note.start_tick + 1)
        grouped_notes.append(
            VocalNote(
                tick=chosen_note.start_tick,
                end_tick=end_tick,
                pitch=chosen_note.pitch,
                velocity=chosen_note.velocity,
            )
        )
        previous_pitch = chosen_note.pitch

    return grouped_notes


def map_vocal_notes_to_target(
    note_values: list[VocalNote],
    tick_mapper,
) -> list[VocalNote]:
    mapped_source_notes: list[SourceVocalNote] = []

    for note_value in note_values:
        mapped_start_tick = tick_mapper(note_value.tick)
        mapped_end_tick = tick_mapper(note_value.end_tick)
        mapped_source_notes.append(
            SourceVocalNote(
                start_tick=mapped_start_tick,
                end_tick=max(mapped_end_tick, mapped_start_tick + 1),
                pitch=note_value.pitch,
                channel=0,
                velocity=note_value.velocity,
            )
        )

    mapped_notes = group_source_vocal_notes(mapped_source_notes)

    for note_value in mapped_notes:
        note_value.end_tick = max(note_value.end_tick, note_value.tick + 1)

    return mapped_notes


def _ceil_to_grid(tick_value: int, grid_size: int) -> int:
    if grid_size <= 1:
        return tick_value

    return ((tick_value + grid_size - 1) // grid_size) * grid_size


def _aligned_phrase_end(note_end_tick: int, ticks_per_beat: int) -> int:
    half_beat_ticks = max(1, ticks_per_beat // 2)
    aligned_tick = _ceil_to_grid(note_end_tick, half_beat_ticks)
    return max(aligned_tick, note_end_tick + 1)


def infer_vocal_phrases(note_values: list[VocalNote], ticks_per_beat: int) -> list[VocalPhrase]:
    if not note_values:
        return []

    phrase_values: list[VocalPhrase] = []
    current_phrase_start = note_values[0].tick
    current_phrase_note_count = 0

    for index, note_value in enumerate(note_values):
        current_phrase_note_count += 1
        next_note_value = note_values[index + 1] if index + 1 < len(note_values) else None
        phrase_duration = note_value.end_tick - current_phrase_start
        should_end_phrase = next_note_value is None

        if next_note_value is not None:
            gap_to_next_note = next_note_value.tick - note_value.end_tick

            if gap_to_next_note >= int(round(ticks_per_beat * 1.25)):
                should_end_phrase = True
            elif gap_to_next_note >= int(round(ticks_per_beat * 0.75)) and current_phrase_note_count >= 6:
                should_end_phrase = True
            elif phrase_duration >= ticks_per_beat * 8 and gap_to_next_note >= ticks_per_beat // 2:
                should_end_phrase = True
            elif current_phrase_note_count >= 16 and gap_to_next_note >= ticks_per_beat // 2:
                should_end_phrase = True

        if not should_end_phrase:
            continue

        phrase_end_tick = _aligned_phrase_end(note_value.end_tick, ticks_per_beat)
        phrase_values.append(
            VocalPhrase(
                start_tick=current_phrase_start,
                end_tick=max(phrase_end_tick, current_phrase_start + 1),
            )
        )

        if next_note_value is not None:
            current_phrase_start = next_note_value.tick
            current_phrase_note_count = 0

    return phrase_values


def build_minimal_vocal_text_events(
    phrase_values: list[VocalPhrase],
    ticks_per_beat: int,
) -> list[tuple[int, str]]:
    if not phrase_values:
        return []

    text_events: list[tuple[int, str]] = []
    play_lead_in_ticks = ticks_per_beat * 2
    first_phrase = phrase_values[0]
    text_events.append((max(0, first_phrase.start_tick - play_lead_in_ticks), "[play]"))

    for previous_phrase, next_phrase in zip(phrase_values, phrase_values[1:]):
        if next_phrase.start_tick - previous_phrase.end_tick < ticks_per_beat * 2:
            continue

        text_events.append((previous_phrase.end_tick, "[idle]"))
        text_events.append((max(0, next_phrase.start_tick - play_lead_in_ticks), "[play]"))

    text_events.append((phrase_values[-1].end_tick, "[idle]"))
    text_events.sort(key=lambda event_value: (event_value[0], event_value[1]))
    return text_events


def build_vocal_chart(note_values: list[SourceVocalNote], ticks_per_beat: int) -> VocalChart:
    grouped_notes = group_source_vocal_notes(note_values)
    phrase_values = infer_vocal_phrases(grouped_notes, ticks_per_beat=ticks_per_beat)
    text_events = build_minimal_vocal_text_events(phrase_values, ticks_per_beat=ticks_per_beat)

    return VocalChart(
        ticks_per_beat=ticks_per_beat,
        notes=grouped_notes,
        phrases=phrase_values,
        text_events=text_events,
    )

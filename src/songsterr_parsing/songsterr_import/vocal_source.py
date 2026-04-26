from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import mido

from .source import track_name

MINIMUM_VOCAL_PITCH = 36
MAXIMUM_VOCAL_PITCH = 84


@dataclass
class SourceVocalNote:
    start_tick: int
    end_tick: int
    pitch: int
    channel: int
    velocity: int


@dataclass
class VocalTrackSelection:
    track: mido.MidiTrack
    track_name: str
    note_count: int
    grouped_note_count: int


def decode_vocal_note_pairs(track: mido.MidiTrack) -> list[SourceVocalNote]:
    absolute_tick = 0
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    note_pairs: list[SourceVocalNote] = []

    for message in track:
        absolute_tick += message.time

        if message.type == "note_on" and message.velocity > 0:
            open_notes[(message.channel, message.note)].append((absolute_tick, message.velocity))
            continue

        if message.type != "note_off" and not (message.type == "note_on" and message.velocity == 0):
            continue

        note_key = (getattr(message, "channel", None), getattr(message, "note", None))
        if not open_notes[note_key]:
            continue

        start_tick, velocity_value = open_notes[note_key].pop(0)
        note_pairs.append(
            SourceVocalNote(
                start_tick=start_tick,
                end_tick=absolute_tick,
                pitch=message.note,
                channel=message.channel,
                velocity=velocity_value,
            )
        )

    return note_pairs


def collect_track_vocal_notes(track: mido.MidiTrack) -> list[SourceVocalNote]:
    filtered_notes: list[SourceVocalNote] = []

    for note_value in decode_vocal_note_pairs(track):
        if note_value.channel == 9:
            continue

        if note_value.pitch < MINIMUM_VOCAL_PITCH or note_value.pitch > MAXIMUM_VOCAL_PITCH:
            continue

        filtered_notes.append(note_value)

    return filtered_notes


def _vocal_track_hint_rank(track_name_value: str) -> int:
    lower_name = track_name_value.lower()
    rank_value = 0

    if lower_name == "vocals":
        rank_value += 7

    if "lead vocal" in lower_name or "lead vocals" in lower_name:
        rank_value += 6

    if "vocals 1" in lower_name or "vocal 1" in lower_name:
        rank_value += 5

    if "main vocal" in lower_name or "main vocals" in lower_name:
        rank_value += 5

    if "lead" in lower_name:
        rank_value += 3

    if "vocal" in lower_name or "lyrics" in lower_name:
        rank_value += 2

    if "vocals 2" in lower_name or "vocal 2" in lower_name:
        rank_value -= 3

    if "backup" in lower_name or "backing" in lower_name or "harmony" in lower_name:
        rank_value -= 4

    if "extra vocal" in lower_name or "extra vocals" in lower_name:
        rank_value -= 3

    return rank_value


def select_source_vocal_track(src_mid: mido.MidiFile) -> VocalTrackSelection:
    vocal_candidates = []

    for track_index, track in enumerate(src_mid.tracks):
        current_track_name = track_name(track)
        lower_name = current_track_name.lower()

        if "vocal" not in lower_name and "lyrics" not in lower_name:
            continue

        note_values = collect_track_vocal_notes(track)
        if not note_values:
            continue

        grouped_tick_count = len({note_value.start_tick for note_value in note_values})
        vocal_candidates.append(
            (
                _vocal_track_hint_rank(current_track_name),
                grouped_tick_count,
                len(note_values),
                -track_index,
                current_track_name,
                track,
            )
        )

    if not vocal_candidates:
        raise RuntimeError("Nenhuma track vocal nomeada com notas dentro do range esperado foi encontrada")

    vocal_candidates.sort(reverse=True)
    _, grouped_tick_count, note_count, _, current_track_name, track = vocal_candidates[0]

    return VocalTrackSelection(
        track=track,
        track_name=current_track_name,
        note_count=note_count,
        grouped_note_count=grouped_tick_count,
    )

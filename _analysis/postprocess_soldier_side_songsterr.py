from __future__ import annotations

import mido


PART_DRUMS_NAME = "PART DRUMS"
SNARE_NOTE = 97
YELLOW_NOTE = 98
BLUE_NOTE = 99
GREEN_NOTE = 100
YELLOW_TOM_MARKER = 110
BLUE_TOM_MARKER = 111
GREEN_TOM_MARKER = 112

RIDE_SECTION_START_TICK = 62976
RIDE_SECTION_END_TICK = 76992
YELLOW_ACCENT_TICKS = {
    63744,
    66816,
    69888,
}
RIDE_WITH_SNARE_TICKS = {
    69504,
}
DEFAULT_NOTE_DURATION_TICKS = 1


def _absolute_messages(track: mido.MidiTrack) -> list[tuple[int, mido.Message]]:
    absolute_tick = 0
    absolute_messages: list[tuple[int, mido.Message]] = []

    for message in track:
        absolute_tick += message.time
        absolute_messages.append((absolute_tick, message.copy(time=0)))

    return absolute_messages


def _rebuild_track_from_absolute_messages(absolute_messages: list[tuple[int, mido.Message]]) -> mido.MidiTrack:
    rebuilt_track = mido.MidiTrack()
    previous_tick = 0

    for absolute_tick, message in sorted(absolute_messages, key=lambda item: item[0]):
        rebuilt_track.append(message.copy(time=absolute_tick - previous_tick))
        previous_tick = absolute_tick

    return rebuilt_track


def _find_part_drums_track(output_mid: mido.MidiFile) -> tuple[int, mido.MidiTrack]:
    for track_index, track in enumerate(output_mid.tracks):
        if getattr(track, "name", "") == PART_DRUMS_NAME:
            return track_index, track

    raise RuntimeError("Nao encontrei PART DRUMS no MIDI gerado")


def _build_cymbal_note_on_indices(absolute_messages: list[tuple[int, mido.Message]]) -> dict[int, int]:
    yellow_tom_ticks = {
        absolute_tick
        for absolute_tick, message in absolute_messages
        if message.type == "note_on" and message.velocity > 0 and message.note == YELLOW_TOM_MARKER
    }
    blue_tom_ticks = {
        absolute_tick
        for absolute_tick, message in absolute_messages
        if message.type == "note_on" and message.velocity > 0 and message.note == BLUE_TOM_MARKER
    }
    green_tom_ticks = {
        absolute_tick
        for absolute_tick, message in absolute_messages
        if message.type == "note_on" and message.velocity > 0 and message.note == GREEN_TOM_MARKER
    }

    cymbal_note_on_indices: dict[int, int] = {}

    for message_index, (absolute_tick, message) in enumerate(absolute_messages):
        if message.type != "note_on" or message.velocity <= 0:
            continue

        if message.note == YELLOW_NOTE and absolute_tick not in yellow_tom_ticks:
            cymbal_note_on_indices[absolute_tick] = message_index
        elif message.note == BLUE_NOTE and absolute_tick not in blue_tom_ticks:
            cymbal_note_on_indices[absolute_tick] = message_index
        elif message.note == GREEN_NOTE and absolute_tick not in green_tom_ticks:
            cymbal_note_on_indices[absolute_tick] = message_index

    return cymbal_note_on_indices


def _find_matching_note_off_index(
    absolute_messages: list[tuple[int, mido.Message]],
    note_on_index: int,
) -> int | None:
    _, note_on_message = absolute_messages[note_on_index]
    pending_count = 1

    for message_index in range(note_on_index + 1, len(absolute_messages)):
        _, message = absolute_messages[message_index]

        if message.note != note_on_message.note:
            continue

        if message.type == "note_on" and message.velocity > 0:
            pending_count += 1
            continue

        if message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            pending_count -= 1

            if pending_count == 0:
                return message_index

    return None


def _change_cymbal_note(
    absolute_messages: list[tuple[int, mido.Message]],
    cymbal_note_on_indices: dict[int, int],
    target_tick: int,
    target_note: int,
) -> None:
    note_on_index = cymbal_note_on_indices.get(target_tick)

    if note_on_index is None:
        return

    note_off_index = _find_matching_note_off_index(absolute_messages, note_on_index)
    _, note_on_message = absolute_messages[note_on_index]
    note_on_message.note = target_note

    if note_off_index is not None:
        _, note_off_message = absolute_messages[note_off_index]
        note_off_message.note = target_note


def _has_note_at_tick(
    absolute_messages: list[tuple[int, mido.Message]],
    target_tick: int,
    target_note: int,
) -> bool:
    for absolute_tick, message in absolute_messages:
        if absolute_tick != target_tick:
            continue

        if message.type != "note_on" or message.velocity <= 0:
            continue

        if message.note == target_note:
            return True

    return False


def _add_note_at_tick(
    absolute_messages: list[tuple[int, mido.Message]],
    target_tick: int,
    target_note: int,
) -> None:
    if _has_note_at_tick(absolute_messages, target_tick, target_note):
        return

    # This section already uses 1-tick cymbals, so matching that keeps the edit invisible.
    absolute_messages.append(
        (
            target_tick,
            mido.Message("note_on", note=target_note, velocity=100, time=0),
        )
    )
    absolute_messages.append(
        (
            target_tick + DEFAULT_NOTE_DURATION_TICKS,
            mido.Message("note_off", note=target_note, velocity=0, time=0),
        )
    )


def apply_soldier_side_songsterr_postprocess(output_mid: mido.MidiFile) -> mido.MidiFile:
    track_index, part_drums_track = _find_part_drums_track(output_mid)
    absolute_messages = _absolute_messages(part_drums_track)
    cymbal_note_on_indices = _build_cymbal_note_on_indices(absolute_messages)

    for absolute_tick in sorted(cymbal_note_on_indices):
        if absolute_tick < RIDE_SECTION_START_TICK or absolute_tick > RIDE_SECTION_END_TICK:
            continue

        if absolute_tick in YELLOW_ACCENT_TICKS:
            target_note = YELLOW_NOTE
        else:
            target_note = BLUE_NOTE

        _change_cymbal_note(
            absolute_messages,
            cymbal_note_on_indices,
            target_tick=absolute_tick,
            target_note=target_note,
        )

    for absolute_tick in sorted(RIDE_WITH_SNARE_TICKS):
        if absolute_tick not in cymbal_note_on_indices:
            _add_note_at_tick(
                absolute_messages,
                target_tick=absolute_tick,
                target_note=BLUE_NOTE,
            )
        else:
            _change_cymbal_note(
                absolute_messages,
                cymbal_note_on_indices,
                target_tick=absolute_tick,
                target_note=BLUE_NOTE,
            )

    output_mid.tracks[track_index] = _rebuild_track_from_absolute_messages(absolute_messages)
    return output_mid

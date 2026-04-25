from __future__ import annotations

import argparse

import mido

from parse_chart import load_reference_midi
from songsterr_import.constants import DEFAULT_MINIMUM_SNARE_VELOCITY, should_keep_source_hit
from songsterr_import.measure_marker_sync import DEFAULT_INITIAL_OFFSET_TICKS, build_measure_marker_tick_mapper
from songsterr_import.source import select_source_drum_track


PART_DRUMS_NAME = "PART DRUMS"
YELLOW_NOTE = 98
BLUE_NOTE = 99
GREEN_NOTE = 100
YELLOW_TOM_MARKER = 110
BLUE_TOM_MARKER = 111
GREEN_TOM_MARKER = 112


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


def _find_part_drums_track(output_mid: mido.MidiFile) -> mido.MidiTrack:
    for track in output_mid.tracks:
        if getattr(track, "name", "") == PART_DRUMS_NAME:
            return track

    raise RuntimeError("Nao encontrei PART DRUMS no MIDI gerado")


def _build_tick_mapper(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    initial_offset_ticks: int,
) -> callable:
    tick_mapper, _ = build_measure_marker_tick_mapper(
        src_mid,
        ref_mid,
        initial_offset_ticks=initial_offset_ticks,
    )

    return tick_mapper


def _build_cymbal_note_indices(
    absolute_messages: list[tuple[int, mido.Message] | None],
) -> tuple[dict[int, int], set[int], set[int]]:
    yellow_tom_ticks = {
        absolute_tick
        for item in absolute_messages
        if item is not None
        for absolute_tick, message in [item]
        if message.type == "note_on" and message.velocity > 0 and message.note == YELLOW_TOM_MARKER
    }
    blue_tom_ticks = {
        absolute_tick
        for item in absolute_messages
        if item is not None
        for absolute_tick, message in [item]
        if message.type == "note_on" and message.velocity > 0 and message.note == BLUE_TOM_MARKER
    }
    green_tom_ticks = {
        absolute_tick
        for item in absolute_messages
        if item is not None
        for absolute_tick, message in [item]
        if message.type == "note_on" and message.velocity > 0 and message.note == GREEN_TOM_MARKER
    }

    cymbal_note_on_indices: dict[int, int] = {}

    for index, item in enumerate(absolute_messages):
        if item is None:
            continue

        absolute_tick, message = item

        if message.type != "note_on" or message.velocity <= 0:
            continue

        if message.note == YELLOW_NOTE and absolute_tick not in yellow_tom_ticks:
            cymbal_note_on_indices[absolute_tick] = index
        elif message.note == BLUE_NOTE and absolute_tick not in blue_tom_ticks:
            cymbal_note_on_indices[absolute_tick] = index
        elif message.note == GREEN_NOTE and absolute_tick not in green_tom_ticks:
            cymbal_note_on_indices[absolute_tick] = index

    return cymbal_note_on_indices, blue_tom_ticks, green_tom_ticks


def _find_matching_note_off_index(
    absolute_messages: list[tuple[int, mido.Message] | None],
    note_on_index: int,
) -> int | None:
    note_on_item = absolute_messages[note_on_index]

    if note_on_item is None:
        return None

    _, note_on_message = note_on_item
    pending_count = 1

    for index in range(note_on_index + 1, len(absolute_messages)):
        current_item = absolute_messages[index]

        if current_item is None:
            continue

        _, message = current_item

        if message.note != note_on_message.note:
            continue

        if message.type == "note_on" and message.velocity > 0:
            pending_count += 1
            continue

        if message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            pending_count -= 1

            if pending_count == 0:
                return index

    return None


def _change_cymbal_note(
    absolute_messages: list[tuple[int, mido.Message] | None],
    cymbal_note_on_indices: dict[int, int],
    target_tick: int,
    target_note: int,
) -> None:
    note_on_index = cymbal_note_on_indices.get(target_tick)

    if note_on_index is None:
        return

    note_off_index = _find_matching_note_off_index(absolute_messages, note_on_index)
    note_on_item = absolute_messages[note_on_index]

    if note_on_item is None:
        return

    _, note_on_message = note_on_item
    note_on_message.note = target_note

    if note_off_index is not None:
        note_off_item = absolute_messages[note_off_index]

        if note_off_item is None:
            return

        _, note_off_message = note_off_item
        note_off_message.note = target_note


def _remove_cymbal_note(
    absolute_messages: list[tuple[int, mido.Message] | None],
    cymbal_note_on_indices: dict[int, int],
    target_tick: int,
) -> None:
    note_on_index = cymbal_note_on_indices.get(target_tick)

    if note_on_index is None:
        return

    note_off_index = _find_matching_note_off_index(absolute_messages, note_on_index)
    absolute_messages[note_on_index] = None  # type: ignore[assignment]

    if note_off_index is not None:
        absolute_messages[note_off_index] = None  # type: ignore[assignment]


def _swap_blue_green_cymbals(
    absolute_messages: list[tuple[int, mido.Message] | None],
) -> None:
    cymbal_note_on_indices, _, _ = _build_cymbal_note_indices(absolute_messages)

    for target_tick, note_on_index in list(cymbal_note_on_indices.items()):
        note_on_item = absolute_messages[note_on_index]

        if note_on_item is None:
            continue

        _, note_on_message = note_on_item

        if note_on_message.note == BLUE_NOTE:
            new_note = GREEN_NOTE
        elif note_on_message.note == GREEN_NOTE:
            new_note = BLUE_NOTE
        else:
            continue

        note_off_index = _find_matching_note_off_index(absolute_messages, note_on_index)
        note_on_message.note = new_note

        if note_off_index is not None:
            note_off_item = absolute_messages[note_off_index]

            if note_off_item is None:
                continue

            _, note_off_message = note_off_item
            note_off_message.note = new_note


def _apply_hat_pattern_corrections(
    absolute_messages: list[tuple[int, mido.Message] | None],
    src_mid: mido.MidiFile,
    tick_mapper,
    minimum_snare_velocity: int | None = None,
) -> None:
    drum_track = select_source_drum_track(
        src_mid,
        minimum_snare_velocity=minimum_snare_velocity,
    ).track
    source_hat_hits: list[tuple[int, int]] = []
    absolute_source_tick = 0

    for message in drum_track:
        absolute_source_tick += message.time

        if message.type != "note_on":
            continue

        if not should_keep_source_hit(message.note, message.velocity, minimum_snare_velocity):
            continue

        if message.channel != 9:
            continue

        if message.note not in (42, 46):
            continue

        source_hat_hits.append((absolute_source_tick, message.note))

    pattern_start_index = 0

    while pattern_start_index <= len(source_hat_hits) - 4:
        pattern_notes = [source_hat_hits[pattern_start_index + offset][1] for offset in range(4)]

        if pattern_notes != [46, 42, 42, 46]:
            pattern_start_index += 1
            continue

        target_ticks = [
            tick_mapper(source_hat_hits[pattern_start_index + offset][0])
            for offset in range(4)
        ]
        cymbal_note_on_indices, _, _ = _build_cymbal_note_indices(absolute_messages)
        _change_cymbal_note(absolute_messages, cymbal_note_on_indices, target_ticks[0], YELLOW_NOTE)
        cymbal_note_on_indices, _, _ = _build_cymbal_note_indices(absolute_messages)
        _remove_cymbal_note(absolute_messages, cymbal_note_on_indices, target_ticks[1])
        cymbal_note_on_indices, _, _ = _build_cymbal_note_indices(absolute_messages)
        _change_cymbal_note(absolute_messages, cymbal_note_on_indices, target_ticks[2], YELLOW_NOTE)
        cymbal_note_on_indices, _, _ = _build_cymbal_note_indices(absolute_messages)
        _change_cymbal_note(absolute_messages, cymbal_note_on_indices, target_ticks[3], BLUE_NOTE)
        pattern_start_index += 4


def apply_bubbles_songsterr_postprocess(
    output_mid: mido.MidiFile,
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    initial_offset_ticks: int = DEFAULT_INITIAL_OFFSET_TICKS,
    minimum_snare_velocity: int | None = None,
) -> mido.MidiFile:
    tick_mapper = _build_tick_mapper(
        src_mid,
        ref_mid,
        initial_offset_ticks=initial_offset_ticks,
    )
    part_drums_track = _find_part_drums_track(output_mid)
    absolute_messages = _absolute_messages(part_drums_track)
    _swap_blue_green_cymbals(absolute_messages)
    _apply_hat_pattern_corrections(
        absolute_messages,
        src_mid,
        tick_mapper,
        minimum_snare_velocity=minimum_snare_velocity,
    )
    filtered_messages = [item for item in absolute_messages if item is not None]
    rebuilt_track = _rebuild_track_from_absolute_messages(filtered_messages)

    for track_index, track in enumerate(output_mid.tracks):
        if track is part_drums_track:
            output_mid.tracks[track_index] = rebuilt_track
            break

    return output_mid


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid")
    argument_parser.add_argument("out_mid")
    argument_parser.add_argument("--ref-path", required=True)
    argument_parser.add_argument("--initial-offset-ticks", type=int, default=DEFAULT_INITIAL_OFFSET_TICKS)
    argument_parser.add_argument(
        "--minimum-snare-velocity",
        type=int,
        default=None,
        help=(
            "ignora apenas caixas com velocity abaixo deste valor; "
            f"omita para incluir todas, ou passe {DEFAULT_MINIMUM_SNARE_VELOCITY} "
            "para reativar o filtro antigo."
        ),
    )
    args = argument_parser.parse_args()

    src_mid = mido.MidiFile(args.src_mid)
    ref_mid = load_reference_midi(args.ref_path)
    output_mid = mido.MidiFile(args.out_mid)
    apply_bubbles_songsterr_postprocess(
        output_mid,
        src_mid,
        ref_mid,
        initial_offset_ticks=args.initial_offset_ticks,
        minimum_snare_velocity=args.minimum_snare_velocity,
    )
    output_mid.save(args.out_mid)


if __name__ == "__main__":
    main()

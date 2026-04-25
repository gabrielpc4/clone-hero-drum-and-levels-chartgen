from __future__ import annotations

import argparse

import mido


DRUM_TRACK_NAME = "Drums | John Dolmayan"
KICK_NOTE = 35
SNARE_NOTE = 38
CLOSED_HAT_NOTE = 42
YELLOW_HAT_NOTE = 46
GREEN_CRASH_NOTE = 49
BLUE_CYMBAL_NOTE = 51
MAX_FAST_HAT_GAP_TICKS = 3840
MIN_FAST_HAT_CLUSTER_LENGTH = 24


def _absolute_hits(track: mido.MidiTrack) -> list[tuple[int, int]]:
    absolute_tick = 0
    hits: list[tuple[int, int]] = []

    for message in track:
        absolute_tick += message.time

        if message.type != "note_on":
            continue

        if message.velocity <= 0:
            continue

        if getattr(message, "channel", None) != 9:
            continue

        hits.append((absolute_tick, message.note))

    return hits


def _crash_kick_ticks(track: mido.MidiTrack) -> list[int]:
    hits = _absolute_hits(track)
    hits_by_tick: dict[int, set[int]] = {}

    for absolute_tick, note_value in hits:
        hits_by_tick.setdefault(absolute_tick, set()).add(note_value)

    return [
        absolute_tick
        for absolute_tick, note_values in sorted(hits_by_tick.items())
        if KICK_NOTE in note_values and (
            GREEN_CRASH_NOTE in note_values
            or BLUE_CYMBAL_NOTE in note_values
            or YELLOW_HAT_NOTE in note_values
        )
    ]


def _fast_hat_clusters(track: mido.MidiTrack) -> list[list[int]]:
    hat_like_ticks = [
        absolute_tick
        for absolute_tick, note_value in _absolute_hits(track)
        if note_value in (CLOSED_HAT_NOTE, GREEN_CRASH_NOTE, BLUE_CYMBAL_NOTE)
    ]

    if not hat_like_ticks:
        return []

    clusters: list[list[int]] = []
    current_cluster = [hat_like_ticks[0]]

    for previous_tick, current_tick in zip(hat_like_ticks, hat_like_ticks[1:]):
        if current_tick - previous_tick <= MAX_FAST_HAT_GAP_TICKS:
            current_cluster.append(current_tick)
            continue

        if len(current_cluster) >= MIN_FAST_HAT_CLUSTER_LENGTH:
            clusters.append(current_cluster)

        current_cluster = [current_tick]

    if len(current_cluster) >= MIN_FAST_HAT_CLUSTER_LENGTH:
        clusters.append(current_cluster)

    return clusters


def _preserved_closed_hat_ticks_from_clusters(fast_hat_clusters: list[list[int]]) -> set[int]:
    preserved_ticks: set[int] = set()

    for cluster_ticks in fast_hat_clusters:
        preserved_ticks.update(cluster_ticks)

    return preserved_ticks


def _rewrite_track(
    track: mido.MidiTrack,
    crash_kick_ticks: set[int],
    crash_swap_ticks: set[int],
    snare_hat_ticks: set[int],
    preserved_closed_hat_ticks: set[int],
) -> mido.MidiTrack:
    rebuilt_track = mido.MidiTrack()
    absolute_tick = 0
    output_messages: list[tuple[int, object]] = []

    for message in track:
        absolute_tick += message.time

        new_message = message.copy(time=0)

        if (
            new_message.type == "note_on"
            and new_message.velocity > 0
            and getattr(new_message, "channel", None) == 9
        ):
            if absolute_tick in snare_hat_ticks and new_message.note == CLOSED_HAT_NOTE:
                continue

            if (
                absolute_tick in preserved_closed_hat_ticks
                and new_message.note in (CLOSED_HAT_NOTE, GREEN_CRASH_NOTE, BLUE_CYMBAL_NOTE)
            ):
                new_message.note = CLOSED_HAT_NOTE
            elif new_message.note == CLOSED_HAT_NOTE:
                new_message.note = BLUE_CYMBAL_NOTE

            if absolute_tick in crash_swap_ticks and new_message.note == GREEN_CRASH_NOTE:
                new_message.note = YELLOW_HAT_NOTE
            elif (
                absolute_tick in crash_kick_ticks
                and absolute_tick not in crash_swap_ticks
                and new_message.note in (BLUE_CYMBAL_NOTE, YELLOW_HAT_NOTE)
            ):
                new_message.note = GREEN_CRASH_NOTE
            elif (
                new_message.note in (YELLOW_HAT_NOTE, GREEN_CRASH_NOTE)
                and absolute_tick not in crash_kick_ticks
            ):
                new_message.note = BLUE_CYMBAL_NOTE

        output_messages.append((absolute_tick, new_message))

    previous_tick = 0

    for absolute_tick, new_message in output_messages:
        rebuilt_track.append(new_message.copy(time=absolute_tick - previous_tick))
        previous_tick = absolute_tick

    return rebuilt_track


def apply_soldier_side_mid_fixes(mid_path: str, original_mid_path: str | None = None) -> None:
    source_mid_path = original_mid_path or mid_path
    midi_file = mido.MidiFile(source_mid_path)
    drum_track_index = next(
        index for index, track in enumerate(midi_file.tracks) if getattr(track, "name", "") == DRUM_TRACK_NAME
    )
    drum_track = midi_file.tracks[drum_track_index]
    hits = _absolute_hits(drum_track)
    hits_by_tick: dict[int, set[int]] = {}

    for absolute_tick, note_value in hits:
        hits_by_tick.setdefault(absolute_tick, set()).add(note_value)

    crash_kick_ticks = _crash_kick_ticks(drum_track)
    crash_swap_ticks = {
        absolute_tick
        for index, absolute_tick in enumerate(crash_kick_ticks)
        if index % 2 == 0
    }
    snare_hat_ticks = {
        absolute_tick
        for absolute_tick, note_values in hits_by_tick.items()
        if SNARE_NOTE in note_values and CLOSED_HAT_NOTE in note_values
    }
    fast_hat_clusters = _fast_hat_clusters(drum_track)
    preserved_closed_hat_ticks = _preserved_closed_hat_ticks_from_clusters(fast_hat_clusters)

    midi_file.tracks[drum_track_index] = _rewrite_track(
        drum_track,
        crash_kick_ticks=set(crash_kick_ticks),
        crash_swap_ticks=crash_swap_ticks,
        snare_hat_ticks=snare_hat_ticks,
        preserved_closed_hat_ticks=preserved_closed_hat_ticks,
    )
    midi_file.save(mid_path)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("mid_path")
    argument_parser.add_argument("--original-mid")
    args = argument_parser.parse_args()
    apply_soldier_side_mid_fixes(args.mid_path, original_mid_path=args.original_mid)


if __name__ == "__main__":
    main()

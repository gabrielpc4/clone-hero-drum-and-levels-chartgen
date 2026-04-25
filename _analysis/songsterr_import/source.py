from __future__ import annotations

from dataclasses import dataclass

import mido

from .constants import GM_TO_RB, TOM_PITCHES, should_keep_source_hit


@dataclass
class DrumTrackSelection:
    track: mido.MidiTrack
    track_name: str
    mapped_hits: int
    channel9_hits: int


def track_name(track: mido.MidiTrack) -> str:
    current_track_name = getattr(track, "name", "")

    if current_track_name:
        return current_track_name

    for message in track:
        if message.type == "track_name":
            return message.name

    return ""


def _channel_9_note_count(track: mido.MidiTrack) -> int:
    return sum(
        1
        for message in track
        if message.type == "note_on"
        and should_keep_source_hit(message.velocity)
        and message.channel == 9
    )


def _mapped_drum_note_count(track: mido.MidiTrack) -> int:
    return sum(
        1
        for message in track
        if message.type == "note_on"
        and should_keep_source_hit(message.velocity)
        and message.channel == 9
        and (message.note in GM_TO_RB or message.note in TOM_PITCHES)
    )


def _drum_track_hint_rank(track_name_value: str) -> int:
    lower_name = track_name_value.lower()

    if "drum" in lower_name:
        return 3

    if "kit" in lower_name:
        return 2

    if "perc" in lower_name or "percussion" in lower_name:
        return 1

    return 0


def _is_auxiliary_percussion_track(track_name_value: str) -> bool:
    lower_name = track_name_value.lower()

    return "perc" in lower_name or "percussion" in lower_name


def select_source_drum_track(src_mid: mido.MidiFile) -> DrumTrackSelection:
    drum_candidates = []

    for track_index, track in enumerate(src_mid.tracks):
        channel9_hits = _channel_9_note_count(track)

        if channel9_hits == 0:
            continue

        current_track_name = track_name(track)
        drum_candidates.append(
            (
                _mapped_drum_note_count(track),
                _drum_track_hint_rank(current_track_name),
                channel9_hits,
                -track_index,
                current_track_name,
                track,
            )
        )

    if not drum_candidates:
        raise RuntimeError("Nenhuma track de bateria (canal 9) encontrada")

    has_primary_drum_candidate = any(
        mapped_hits > 0 and not _is_auxiliary_percussion_track(current_track_name)
        for mapped_hits, _, _, _, current_track_name, _ in drum_candidates
    )

    if has_primary_drum_candidate:
        drum_candidates = [
            candidate
            for candidate in drum_candidates
            if not _is_auxiliary_percussion_track(candidate[4])
        ]

    drum_candidates.sort(reverse=True)
    mapped_hits, _, channel9_hits, _, current_track_name, track = drum_candidates[0]

    return DrumTrackSelection(
        track=track,
        track_name=current_track_name,
        mapped_hits=mapped_hits,
        channel9_hits=channel9_hits,
    )

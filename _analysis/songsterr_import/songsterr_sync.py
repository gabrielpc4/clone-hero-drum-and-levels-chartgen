from __future__ import annotations

import json
import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen

import mido

from parse_chart import build_tempo_map, read_conductor_track


SONGSTERR_URL_PATTERN = re.compile(r"-s(\d+)(?:$|[/?#])")


@dataclass
class SongsterrVideoSync:
    song_id: int
    revision_id: int
    video_id: str
    feature: str | None
    anchor_count: int
    source_measure_count: int
    initial_offset_seconds: float
    audio_offset_seconds: float = 0.0
    first_note_target_seconds: float | None = None
    first_note_audio_seconds: float | None = None
    snapped_anchor_count: int = 0


def _fetch_json(url: str) -> object:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_song_id(songsterr_url: str) -> int:
    match = SONGSTERR_URL_PATTERN.search(songsterr_url)

    if match is None:
        raise RuntimeError(
            "Nao foi possivel extrair o songId da URL do Songsterr. "
            "Use uma URL no formato ...-s443."
        )

    return int(match.group(1))


def _default_video_id(meta_payload: dict) -> str:
    for video_entry in meta_payload.get("videos", []):
        if video_entry.get("feature") is None and video_entry.get("videoId"):
            return str(video_entry["videoId"])

    for video_entry in meta_payload.get("videos", []):
        if video_entry.get("videoId"):
            return str(video_entry["videoId"])

    raise RuntimeError("A revisao do Songsterr nao expoe nenhum video para sincronizacao")


def _select_video_points_entry(
    video_points_payload: list[dict],
    preferred_video_id: str | None,
) -> dict:
    selected_video_id = preferred_video_id

    if selected_video_id is not None:
        for video_entry in video_points_payload:
            if str(video_entry.get("videoId")) == selected_video_id:
                return video_entry

        raise RuntimeError(
            f"Nao encontrei video-points para o video '{selected_video_id}' nesta revisao do Songsterr"
        )

    for video_entry in video_points_payload:
        if video_entry.get("feature") is None and video_entry.get("videoId"):
            return video_entry

    if not video_points_payload:
        raise RuntimeError("O Songsterr nao retornou anchors de video para esta revisao")

    return video_points_payload[0]


def _measure_start_ticks(mid: mido.MidiFile) -> list[int]:
    _, time_signatures = read_conductor_track(mid)

    if not time_signatures:
        time_signatures = [(0, 4, 4)]

    end_tick = max(sum(message.time for message in track) for track in mid.tracks)
    measure_start_ticks: list[int] = []

    for signature_index, (signature_tick, numerator_value, denominator_value) in enumerate(time_signatures):
        if signature_index + 1 < len(time_signatures):
            next_signature_tick = time_signatures[signature_index + 1][0]
        else:
            next_signature_tick = end_tick + 1

        ticks_per_measure = int(mid.ticks_per_beat * numerator_value * (4 / denominator_value))
        current_measure_tick = signature_tick

        while current_measure_tick < next_signature_tick:
            measure_start_ticks.append(current_measure_tick)
            current_measure_tick += ticks_per_measure

    return measure_start_ticks


def _half_measure_grid_ticks(mid: mido.MidiFile) -> list[int]:
    _, time_signatures = read_conductor_track(mid)

    if not time_signatures:
        time_signatures = [(0, 4, 4)]

    end_tick = max(sum(message.time for message in track) for track in mid.tracks)
    grid_ticks: list[int] = []

    for signature_index, (signature_tick, numerator_value, denominator_value) in enumerate(time_signatures):
        if signature_index + 1 < len(time_signatures):
            next_signature_tick = time_signatures[signature_index + 1][0]
        else:
            next_signature_tick = end_tick + 1

        ticks_per_measure = int(mid.ticks_per_beat * numerator_value * (4 / denominator_value))
        half_measure_ticks = max(1, ticks_per_measure // 2)
        current_measure_tick = signature_tick

        while current_measure_tick < next_signature_tick:
            grid_ticks.append(current_measure_tick)

            midpoint_tick = current_measure_tick + half_measure_ticks

            if midpoint_tick < next_signature_tick:
                grid_ticks.append(midpoint_tick)

            current_measure_tick += ticks_per_measure

    return sorted(set(grid_ticks))


def _snap_anchor_ticks_to_grid(
    raw_target_ticks: list[int],
    reference_grid_ticks: list[int],
) -> tuple[list[int], int]:
    snapped_ticks: list[int] = []
    snapped_anchor_count = 0
    minimum_grid_index = 0

    for raw_target_tick in raw_target_ticks:
        insertion_index = bisect_right(reference_grid_ticks, raw_target_tick, lo=minimum_grid_index)
        candidate_indices: list[int] = []

        if minimum_grid_index < len(reference_grid_ticks):
            candidate_indices.append(minimum_grid_index)

        if insertion_index < len(reference_grid_ticks):
            candidate_indices.append(insertion_index)

        if insertion_index - 1 >= minimum_grid_index:
            candidate_indices.append(insertion_index - 1)

        best_index = None
        best_distance = None

        for candidate_index in sorted(set(candidate_indices)):
            candidate_tick = reference_grid_ticks[candidate_index]
            candidate_distance = abs(candidate_tick - raw_target_tick)

            if best_distance is None or candidate_distance < best_distance:
                best_distance = candidate_distance
                best_index = candidate_index

        if best_index is None:
            snapped_ticks.append(raw_target_tick)
            continue

        snapped_tick = reference_grid_ticks[best_index]

        if snapped_tick != raw_target_tick:
            snapped_anchor_count += 1

        snapped_ticks.append(snapped_tick)
        minimum_grid_index = best_index + 1

    return snapped_ticks, snapped_anchor_count


def _build_tick_anchor_mapper(
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


def _build_seconds_warp(
    source_anchor_seconds: list[float],
    target_anchor_seconds: list[float],
) -> Callable[[float], float]:
    if len(source_anchor_seconds) != len(target_anchor_seconds):
        raise RuntimeError("Os anchors de origem e destino precisam ter o mesmo tamanho")

    if len(source_anchor_seconds) < 2:
        raise RuntimeError("Sao necessarios pelo menos dois anchors para montar o warp do Songsterr")

    def warp_seconds(source_seconds: float) -> float:
        if source_seconds <= source_anchor_seconds[0]:
            left_index = 0
        elif source_seconds >= source_anchor_seconds[-1]:
            left_index = len(source_anchor_seconds) - 2
        else:
            left_index = bisect_right(source_anchor_seconds, source_seconds) - 1

        right_index = left_index + 1
        left_source_seconds = source_anchor_seconds[left_index]
        right_source_seconds = source_anchor_seconds[right_index]
        left_target_seconds = target_anchor_seconds[left_index]
        right_target_seconds = target_anchor_seconds[right_index]

        if right_source_seconds == left_source_seconds:
            return left_target_seconds

        progress_ratio = (source_seconds - left_source_seconds) / (right_source_seconds - left_source_seconds)

        return left_target_seconds + progress_ratio * (right_target_seconds - left_target_seconds)

    return warp_seconds


def build_songsterr_video_tick_mapper(
    src_mid: mido.MidiFile,
    ref_mid: mido.MidiFile,
    songsterr_url: str,
    preferred_video_id: str | None = None,
    audio_offset_seconds: float = 0.0,
) -> tuple[Callable[[int], int], SongsterrVideoSync]:
    song_id = parse_song_id(songsterr_url)
    meta_payload = _fetch_json(f"https://www.songsterr.com/api/meta/{song_id}")

    if not isinstance(meta_payload, dict):
        raise RuntimeError("Resposta inesperada do Songsterr meta")

    revision_id = meta_payload.get("revisionId")

    if not isinstance(revision_id, int):
        raise RuntimeError("A resposta meta do Songsterr nao trouxe revisionId valido")

    selected_video_id = preferred_video_id or _default_video_id(meta_payload)
    video_points_payload = _fetch_json(f"https://www.songsterr.com/api/video-points/{song_id}/{revision_id}/list")

    if not isinstance(video_points_payload, list):
        raise RuntimeError("Resposta inesperada do Songsterr video-points")

    video_entry = _select_video_points_entry(video_points_payload, selected_video_id)
    video_points = video_entry.get("points")

    if not isinstance(video_points, list) or len(video_points) < 2:
        raise RuntimeError("O Songsterr nao retornou pontos suficientes para sincronizacao")

    reference_tempo_map = build_tempo_map(ref_mid)
    source_measure_ticks = _measure_start_ticks(src_mid)
    usable_anchor_count = min(len(source_measure_ticks), len(video_points))

    if usable_anchor_count < 2:
        raise RuntimeError("Nao foi possivel cruzar os compassos do Songsterr com os video-points")

    source_anchor_ticks = source_measure_ticks[:usable_anchor_count]
    target_anchor_seconds = [float(point_value) + audio_offset_seconds for point_value in video_points[:usable_anchor_count]]
    raw_target_anchor_ticks = [reference_tempo_map.seconds_to_tick(target_seconds) for target_seconds in target_anchor_seconds]
    reference_grid_ticks = _half_measure_grid_ticks(ref_mid)
    target_anchor_ticks, snapped_anchor_count = _snap_anchor_ticks_to_grid(raw_target_anchor_ticks, reference_grid_ticks)
    tick_mapper = _build_tick_anchor_mapper(source_anchor_ticks, target_anchor_ticks)

    return tick_mapper, SongsterrVideoSync(
        song_id=song_id,
        revision_id=revision_id,
        video_id=str(video_entry.get("videoId") or selected_video_id),
        feature=video_entry.get("feature"),
        anchor_count=usable_anchor_count,
        source_measure_count=len(source_measure_ticks),
        initial_offset_seconds=float(video_points[0]),
        audio_offset_seconds=audio_offset_seconds,
        snapped_anchor_count=snapped_anchor_count,
    )

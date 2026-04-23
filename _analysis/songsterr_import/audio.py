from __future__ import annotations

import array
import math
import subprocess
from dataclasses import dataclass
from statistics import mean

LOW_FREQUENCY_RISE_FILTER = "highpass=f=35,lowpass=f=220"
DRUM_PEAK_FILTER = "highpass=f=120,lowpass=f=5000"


@dataclass
class AudioRiseDetection:
    rise_seconds: float
    frame_seconds: float
    current_energy: float
    baseline_energy: float
    score: float


def _decode_audio_to_mono_samples(
    audio_path: str,
    sample_rate: int,
    filter_expression: str,
) -> array.array:
    ffmpeg_command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        audio_path,
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-af",
        filter_expression,
        "-f",
        "f32le",
        "-",
    ]
    completed_process = subprocess.run(
        ffmpeg_command,
        capture_output=True,
        check=False,
    )

    if completed_process.returncode != 0:
        error_text = completed_process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Falha ao decodificar áudio com ffmpeg: {error_text}")

    samples = array.array("f")
    samples.frombytes(completed_process.stdout)

    return samples


def _frame_rms_values(
    samples: array.array,
    frame_size: int,
) -> list[float]:
    frame_values: list[float] = []

    for start_index in range(0, max(0, len(samples) - frame_size + 1), frame_size):
        frame = samples[start_index : start_index + frame_size]

        if not frame:
            continue

        frame_values.append(math.sqrt(sum(sample * sample for sample in frame) / len(frame)))

    return frame_values


def _audio_frame_values(
    audio_path: str,
    sample_rate: int,
    frame_seconds: float,
    filter_expression: str,
) -> tuple[list[float], int]:
    samples = _decode_audio_to_mono_samples(audio_path, sample_rate, filter_expression)
    frame_size = max(1, int(round(sample_rate * frame_seconds)))

    return _frame_rms_values(samples, frame_size), frame_size


def detect_first_dramatic_rise(
    audio_path: str,
    sample_rate: int = 2000,
    frame_seconds: float = 0.02,
    warmup_seconds: float = 1.0,
    baseline_seconds: float = 0.8,
    sustain_seconds: float = 0.08,
    rise_ratio_threshold: float = 2.8,
    delta_ratio_threshold: float = 1.5,
    filter_expression: str = LOW_FREQUENCY_RISE_FILTER,
) -> AudioRiseDetection:
    frame_values, _ = _audio_frame_values(audio_path, sample_rate, frame_seconds, filter_expression)

    if not frame_values:
        raise RuntimeError("Não foi possível extrair envelope do áudio")

    warmup_frames = max(1, int(round(warmup_seconds / frame_seconds)))
    baseline_frames = max(3, int(round(baseline_seconds / frame_seconds)))
    sustain_frames = max(2, int(round(sustain_seconds / frame_seconds)))
    noise_floor = mean(frame_values[: min(len(frame_values), baseline_frames)])

    candidates = detect_audio_rise_candidates(
        audio_path,
        sample_rate=sample_rate,
        frame_seconds=frame_seconds,
        warmup_seconds=warmup_seconds,
        baseline_seconds=baseline_seconds,
        sustain_seconds=sustain_seconds,
        rise_ratio_threshold=rise_ratio_threshold,
        delta_ratio_threshold=delta_ratio_threshold,
        filter_expression=filter_expression,
    )

    if candidates:
        return candidates[0]

    best_index = baseline_frames
    best_score = float("-inf")
    best_current_energy = frame_values[best_index]
    best_baseline_energy = noise_floor

    for frame_index in range(max(warmup_frames, baseline_frames), len(frame_values) - sustain_frames):
        current_energy = frame_values[frame_index]
        baseline_energy = mean(frame_values[frame_index - baseline_frames : frame_index])
        sustain_energy = mean(frame_values[frame_index : frame_index + sustain_frames])
        current_score = (current_energy - baseline_energy) * max(0.0, sustain_energy - baseline_energy)

        if current_score > best_score:
            best_index = frame_index
            best_score = current_score
            best_current_energy = current_energy
            best_baseline_energy = baseline_energy

    return AudioRiseDetection(
        rise_seconds=best_index * frame_seconds,
        frame_seconds=frame_seconds,
        current_energy=best_current_energy,
        baseline_energy=best_baseline_energy,
        score=best_score,
    )


def detect_audio_rise_candidates(
    audio_path: str,
    sample_rate: int = 2000,
    frame_seconds: float = 0.02,
    warmup_seconds: float = 1.0,
    baseline_seconds: float = 0.8,
    sustain_seconds: float = 0.08,
    rise_ratio_threshold: float = 1.9,
    delta_ratio_threshold: float = 1.15,
    filter_expression: str = LOW_FREQUENCY_RISE_FILTER,
) -> list[AudioRiseDetection]:
    frame_values, _ = _audio_frame_values(audio_path, sample_rate, frame_seconds, filter_expression)

    if not frame_values:
        return []

    warmup_frames = max(1, int(round(warmup_seconds / frame_seconds)))
    baseline_frames = max(3, int(round(baseline_seconds / frame_seconds)))
    sustain_frames = max(2, int(round(sustain_seconds / frame_seconds)))
    noise_floor = mean(frame_values[: min(len(frame_values), baseline_frames)])
    candidates: list[AudioRiseDetection] = []

    for frame_index in range(max(warmup_frames, baseline_frames), len(frame_values) - sustain_frames):
        current_energy = frame_values[frame_index]
        previous_energy = frame_values[frame_index - 1]
        next_energy = frame_values[frame_index + 1]
        baseline_energy = mean(frame_values[frame_index - baseline_frames : frame_index])
        sustain_energy = mean(frame_values[frame_index : frame_index + sustain_frames])
        safe_floor = max(noise_floor, 1e-6)
        rise_ratio = current_energy / max(baseline_energy, safe_floor)
        delta_ratio = current_energy / max(previous_energy, safe_floor)
        sustain_ratio = sustain_energy / max(baseline_energy, safe_floor)
        current_score = (rise_ratio - 1.0) * (sustain_ratio - 1.0)

        if current_energy < safe_floor * 1.5:
            continue

        if current_energy < next_energy:
            continue

        if rise_ratio < rise_ratio_threshold:
            continue

        if delta_ratio < delta_ratio_threshold:
            continue

        if sustain_ratio < 1.25:
            continue

        candidates.append(
            AudioRiseDetection(
                rise_seconds=frame_index * frame_seconds,
                frame_seconds=frame_seconds,
                current_energy=current_energy,
                baseline_energy=baseline_energy,
                score=current_score,
            )
        )

    return candidates


def detect_audio_peak_times(
    audio_path: str,
    sample_rate: int = 2000,
    frame_seconds: float = 0.02,
    warmup_seconds: float = 1.0,
    peak_floor_ratio: float = 1.35,
    filter_expression: str = DRUM_PEAK_FILTER,
) -> list[float]:
    frame_values, _ = _audio_frame_values(audio_path, sample_rate, frame_seconds, filter_expression)

    if not frame_values:
        return []

    warmup_frames = max(1, int(round(warmup_seconds / frame_seconds)))
    baseline_frames = max(3, int(round(0.8 / frame_seconds)))
    noise_floor = mean(frame_values[: min(len(frame_values), baseline_frames)])
    minimum_peak_value = max(noise_floor * peak_floor_ratio, 1e-6)
    peak_times: list[float] = []

    for frame_index in range(max(1, warmup_frames), len(frame_values) - 1):
        current_value = frame_values[frame_index]
        previous_value = frame_values[frame_index - 1]
        next_value = frame_values[frame_index + 1]

        if current_value < minimum_peak_value:
            continue

        if current_value < previous_value:
            continue

        if current_value < next_value:
            continue

        peak_times.append(frame_index * frame_seconds)

    return peak_times

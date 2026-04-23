from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportContext:
    reference_path: str | None
    audio_path: str | None
    auto_detected: bool


REFERENCE_FILENAMES = (
    "notes.chart",
    "notes.mid",
)

AUDIO_FILENAMES = (
    "song.opus",
    "song.ogg",
    "song.wav",
    "song.flac",
    "song.mp3",
    "song.m4a",
)


def _unique_candidate_dirs(*paths: str | None) -> list[Path]:
    candidate_dirs: list[Path] = []
    seen_dirs = set()

    for raw_path in paths:
        if raw_path is None:
            continue

        current_dir = Path(raw_path).expanduser().resolve().parent

        if current_dir in seen_dirs:
            continue

        seen_dirs.add(current_dir)
        candidate_dirs.append(current_dir)

    return candidate_dirs


def _first_existing_path(candidate_dirs: list[Path], filenames: tuple[str, ...]) -> str | None:
    for candidate_dir in candidate_dirs:
        for filename in filenames:
            candidate_path = candidate_dir / filename

            if candidate_path.is_file():
                return str(candidate_path)

    return None


def resolve_import_context(
    src_mid_path: str,
    out_mid_path: str,
    explicit_ref_path: str | None,
    explicit_audio_path: str | None,
    disable_first_note_audio_align: bool,
) -> ImportContext:
    if disable_first_note_audio_align:
        return ImportContext(reference_path=None, audio_path=None, auto_detected=False)

    candidate_dirs = _unique_candidate_dirs(
        explicit_ref_path,
        explicit_audio_path,
        out_mid_path,
        src_mid_path,
    )

    reference_path = explicit_ref_path or _first_existing_path(candidate_dirs, REFERENCE_FILENAMES)
    audio_path = explicit_audio_path or _first_existing_path(candidate_dirs, AUDIO_FILENAMES)
    auto_detected = explicit_ref_path is None and explicit_audio_path is None and reference_path is not None and audio_path is not None

    if (explicit_ref_path is not None or explicit_audio_path is not None) and (reference_path is None or audio_path is None):
        raise RuntimeError(
            "Nao foi possivel resolver o contexto de alinhamento por audio. "
            "Passe --ref-path e --audio-path validos ou use --disable-first-note-audio-align."
        )

    if reference_path is None or audio_path is None:
        return ImportContext(reference_path=None, audio_path=None, auto_detected=False)

    return ImportContext(
        reference_path=reference_path,
        audio_path=audio_path,
        auto_detected=auto_detected,
    )

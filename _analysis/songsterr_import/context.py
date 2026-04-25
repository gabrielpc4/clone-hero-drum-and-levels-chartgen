from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportContext:
    reference_path: str | None
    auto_detected: bool


REFERENCE_FILENAMES = (
    "notes.chart",
    "notes.mid",
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
) -> ImportContext:
    candidate_dirs = _unique_candidate_dirs(
        explicit_ref_path,
        out_mid_path,
        src_mid_path,
    )

    reference_path = explicit_ref_path or _first_existing_path(candidate_dirs, REFERENCE_FILENAMES)
    auto_detected = explicit_ref_path is None and reference_path is not None

    if explicit_ref_path is not None and reference_path is None:
        raise RuntimeError(
            "Nao foi possivel resolver notes.mid ou notes.chart para o sync por compassos. "
            "Passe --ref-path valido."
        )

    return ImportContext(
        reference_path=reference_path,
        auto_detected=bool(auto_detected and reference_path is not None),
    )

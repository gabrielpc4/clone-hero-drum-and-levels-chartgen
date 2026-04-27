"""
Minimal repairs for standard MIDI files (MThd + MTrk) that mido refuses, e.g.:

- MThd header: `ntracks` larger than the number of `MTrk` blocks (remaining bytes
  track body *without* the 8-byte header) — wraps in `MTrk`+length.
- After the last declared track, there are still bytes (correct header) —
  merges into the last track size and aligns `ntracks` with the number of `MTrk` read
  (case 6 MThd, 5 blocks, garbage after; or 5/5 and last under-declared).
"""
from __future__ import annotations
import io
import struct
from typing import List, Tuple

import mido

_MAX_TRAILING_CHUNK = 1_000_000


def _mtrk_scan(data: bytes) -> Tuple[List[Tuple[int, int]], int]:
    """
    List of (MTrk offset, body size) and offset of the 1st byte that *doesn't*
    continue the MTrk chunk sequence, or `len(data)` if the file is
    aligned without extra bytes.
    """
    if len(data) < 14 or data[0:4] != b"MThd":
        return [], 0
    header_len = struct.unpack(">I", data[4:8])[0]
    o = 8 + header_len
    tracks: List[Tuple[int, int]] = []
    while o + 8 <= len(data):
        if data[o : o + 4] != b"MTrk":
            break
        tlen = struct.unpack(">I", data[o + 4 : o + 8])[0]
        end = o + 8 + tlen
        if end > len(data):
            return tracks, o
        tracks.append((o, tlen))
        o = end
    return tracks, o


def _repair_fewer_mtrk_merge_orphan_onto_last(data: bytes) -> bytes:
    """
    When MThd announces more tracks than the number of MTrk headers in the
    file, most of these files are: last track under-declared; the rest
    of the file (body) belongs to that track, not to a track with a missing header.
    Merges into the last MTrk and adjusts `ntracks` = number of real tracks.
    """
    if len(data) < 14 or data[0:4] != b"MThd":
        return data
    tracks, pos = _mtrk_scan(data)
    if not tracks or pos >= len(data):
        return data
    n_found = len(tracks)
    n_decl = struct.unpack(">H", data[10:12])[0]
    orphan = data[pos:]
    if n_found >= n_decl or len(orphan) == 0 or len(orphan) > _MAX_TRAILING_CHUNK:
        return data
    if orphan[:4] == b"MTrk" or (len(orphan) >= 3 and orphan[:3] == b"RIF"):
        return data
    last_off, last_len = tracks[-1]
    b = bytearray(data)
    struct.pack_into(">I", b, last_off + 4, last_len + len(orphan))
    struct.pack_into(">H", b, 10, n_found)
    return bytes(b)


def repair_type1_midi_bytes(data: bytes) -> bytes:
    """
    Other cases: missing MTrk block (bytes after without \"MTrk\");
    or last track under-declared with `num_tracks` already equal to number of tracks;
    or correction of `num_tracks` with coherent file.
    """
    if len(data) < 14 or data[0:4] != b"MThd" or data[4:8] == b"":
        return data
    fmt, ntrks, _ = struct.unpack(">HHH", data[8:14])
    if fmt not in (0, 1):
        return data
    tracks, pos = _mtrk_scan(data)
    if not tracks:
        return data
    n_found = len(tracks)
    n_decl = ntrks
    orphan = data[pos:] if pos < len(data) else b""
    if n_found < n_decl and 0 < len(orphan) <= _MAX_TRAILING_CHUNK:
        if not orphan.startswith(b"MTrk"):
            if len(orphan) >= 3 and orphan[0:3] == b"RIF":
                return data
            return data[:pos] + b"MTrk" + struct.pack(">I", len(orphan)) + orphan
    if n_found == n_decl and 0 < len(orphan) <= _MAX_TRAILING_CHUNK:
        if not orphan.startswith(b"MTrk"):
            if len(orphan) >= 3 and orphan[0:3] == b"RIF":
                return data
            last_off, last_len = tracks[-1]
            b = bytearray(data)
            struct.pack_into(">I", b, last_off + 4, last_len + len(orphan))
            return bytes(b)
    if len(orphan) == 0 and n_decl != n_found:
        b = bytearray(data)
        struct.pack_into(">H", b, 10, n_found)
        return bytes(b)
    return data


def load_midi_file(path: str) -> mido.MidiFile:
    """
    Tenta o ficheiro em bruto; se o mido falhar, aplica reparações na ordem:
    fundir órfão na última pista quando faltam MTrk; depois reparo de wrap /
    fim de pista; por fim o mesmo reparo sobre a versão já fundida.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    merged = _repair_fewer_mtrk_merge_orphan_onto_last(raw)
    type1_on_raw = repair_type1_midi_bytes(raw)
    type1_on_merged = (
        repair_type1_midi_bytes(merged) if merged != raw else merged
    )
    first_error: Exception | None = None
    seen: set[bytes] = set()
    for candidate in (raw, merged, type1_on_raw, type1_on_merged):
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return mido.MidiFile(file=io.BytesIO(candidate), clip=True)
        except (OSError, ValueError) as ex:
            if first_error is None:
                first_error = ex
            continue
    if first_error is not None:
        raise first_error
    raise OSError("could not load MIDI file")

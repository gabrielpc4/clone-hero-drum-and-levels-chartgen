"""
Reparos mínimos para ficheiros MIDI padrão (MThd + MTrk) que o mido recusa, ex.:

- Cabeçalho MThd: `ntracks` maior do que o nº de blocos `MTrk` (bytes restantes
  corpo de pista *sem* os 8 bytes de cabeçalho) — envolve em `MTrk`+length.
- Após a última pista declarada, ainda existem bytes (cabeçalho certo) —
  funde no tamanho da última pista e alinha `ntracks` com o nº de `MTrk` lidos
  (caso 6 MThd, 5 blocos, lixo a seguir; ou 5/5 e última subdeclarada).
"""
from __future__ import annotations
import io
import struct
from typing import List, Tuple

import mido

_MAX_TRAILING_CHUNK = 1_000_000


def _mtrk_scan(data: bytes) -> Tuple[List[Tuple[int, int]], int]:
    """
    Lista de (offset MTrk, tamanho do corpo) e offset do 1.º byte que *não*
    continua a sequência de chunks MTrk, ou `len(data)` se o ficheiro fica
    alinhado sem bytes extra.
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
    Quando o MThd anuncia mais pistas do que o nº de cabeçalhos MTrk no
    ficheiro, a maioria destes ficheiros é: última pista subdeclarada; o resto
    do ficheiro (corpo) pertence a essa pista, não a uma pista com cabeçalho
    em falta. Funde no último MTrk e ajusta `ntracks` = nº de pistas reais.
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
    Outros casos: bloco MTrk em falta (bytes a seguir sem \"MTrk\");
    ou última pista subdeclarada com `num_tracks` já igual ao nº de pistas;
    ou correção de `num_tracks` com ficheiro coerente.
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

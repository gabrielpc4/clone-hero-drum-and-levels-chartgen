"""
Guitar: reduce Expert to Easy / Medium / Hard (PART GUITAR).

Keeps the Expert's notes (Easy can **discard** events; see below). Only the
**difficulty** changes: fret range, chord size, anchor shift,
R11/R16 in sustains, R17 in bursts.

**Medium** (`_medium_rapid_chord_simplify`): in very rapid alternation, three (or
more) becomes two; pairs of *different* shapes (not the same repeated) become
singles. When going 2→1, if the **Expert** in the same section has orange (O), keeps
the note "on the right" (highest fret); otherwise keeps the "on the left".

**Easy** (`_easy_enforce_min_gap_eighth_of_bar`): minimum **1/8 of measure** between
consecutive onsets (4/4 → `tpb/2` ticks); with `time_sigs` from map, the eighth of
measure follows `num`/`denom` (1/8 of bar duration).

See `reduce_note` and `DIFF_CONF` per level.
"""
from __future__ import annotations
import os, sys
import bisect
from collections import defaultdict
from statistics import median, mean
from typing import List, Tuple, Optional, Dict
sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import Chart, Note, FRET_NAMES

# Lane laranja (Direita) em G R Y B O; usado p/ escolher qual fret manter 2→1
FRET_LARANJA = FRET_NAMES.index("O")

DIFF_CONF = {
    "Easy":   dict(max_chord_size=2, allowed_frets=(0, 1, 2),       anchor_shift=-1.0),
    "Medium": dict(max_chord_size=2, allowed_frets=(0, 1, 2, 3),    anchor_shift=-0.5),
    "Hard":   dict(max_chord_size=2, allowed_frets=(0, 1, 2, 3, 4), anchor_shift= 0.0),
}

def classify_sustain_mode(expert: Chart) -> str:
    if not expert.notes: return "melodic"
    # Exclude zero/trivial durations (dur <= 1) from the median — triplet ghost notes
    # would otherwise drag the median below 100 even in melodically sustained songs.
    meaningful = [n.duration for n in expert.notes if n.duration > 1]
    if not meaningful:
        return "aggressive"
    return "aggressive" if median(meaningful) < 100 else "melodic"


def classify_power_chord_mode(expert: Chart) -> bool:
    """Heurística R17: a música é dominada por power chords paradinhos a ponto do Easy
       precisar manter acordes? Critério: ≥50% dos acordes Expert são pwr-spread≤2 E
       gap mediano entre notas Expert ≥ 100 ticks."""
    notes = sorted(expert.notes, key=lambda n: n.tick)
    if len(notes) < 10: return False
    pwr = sum(1 for n in notes if len(n.frets)==2 and (n.frets[-1]-n.frets[0])<=2)
    pwr_ratio = pwr / len(notes)
    gaps = [b.tick-a.tick for a, b in zip(notes, notes[1:])]
    med_gap = median(gaps) if gaps else 0
    return pwr_ratio >= 0.5 and med_gap >= 100


def sub_beat(tick: int, tpb: int) -> int:
    return (tick % tpb) // (tpb // 4)


def find_runs(notes: List[Note], tpb: int) -> List[List[int]]:
    """Devolve índices (no array notes) de cada run."""
    eighth = tpb // 2
    runs, cur = [], []
    for i, n in enumerate(notes):
        if cur and n.tick - notes[cur[-1]].tick > eighth:
            runs.append(cur); cur = []
        cur.append(i)
    if cur: runs.append(cur)
    return runs


def transpose_chord_shape(expert_frets: Tuple[int, ...], allowed: Tuple[int, ...],
                          anchor_fret: Optional[float] = None) -> Tuple[int, ...]:
    """Acha posição que preserva o shape do acorde dentro de allowed e fica perto do anchor."""
    if not expert_frets: return expert_frets
    if all(f in allowed for f in expert_frets): return expert_frets
    expert_centroid = sum(expert_frets) / len(expert_frets)
    base = expert_frets[0]
    intervals = tuple(f - base for f in expert_frets)
    candidates: List[Tuple[int, ...]] = []
    for new_base in allowed:
        cand = tuple(new_base + iv for iv in intervals)
        if all(f in allowed for f in cand):
            candidates.append(cand)
    if not candidates:
        # Comprimir: cada gap > 1 vira 1
        compressed = [0]
        for prev, cur in zip(expert_frets, expert_frets[1:]):
            step = 1 if cur > prev else 0
            compressed.append(compressed[-1] + max(step, 1))
        for new_base in allowed:
            cand = tuple(new_base + c for c in compressed)
            if all(f in allowed for f in cand):
                candidates.append(cand)
    if not candidates:
        m = max(allowed)
        return tuple(min(m, f) for f in expert_frets)
    if anchor_fret is None:
        anchor_fret = expert_centroid

    def candidate_sort_key(candidate: Tuple[int, ...]) -> Tuple[float, float, float]:
        candidate_centroid = sum(candidate) / len(candidate)
        return (
            abs(candidate_centroid - expert_centroid),
            abs(candidate_centroid - anchor_fret),
            abs(candidate[0] - expert_frets[0]),
        )

    candidates.sort(key=candidate_sort_key)
    return candidates[0]


def reduce_single_fret(fret: int, allowed: Tuple[int, ...],
                       anchor_shift_int: int = 0) -> int:
    """Single notes: clipa para faixa permitida (não aplica shift global —
    a Harmonix shifteia algumas músicas mas não todas; sem sinal claro do Expert
    para decidir, manter fret original quando ele cabe)."""
    if fret in allowed: return fret
    if fret > max(allowed): return max(allowed)
    if fret < min(allowed): return min(allowed)
    return fret


def reduce_triple_chord_to_double(expert_frets: Tuple[int, ...]) -> Tuple[int, ...]:
    """
    Escolhe um equivalente de 2 notas para acordes de 3 notas.

    Regra:
    - shape equilibrado -> extremos
    - shape mais "apertado" embaixo -> par de baixo
    - shape mais "apertado" em cima -> par de cima

    Isso evita colapsar shapes diferentes no mesmo par quando o Expert muda o
    desenho do acorde para sugerir região mais alta ou mais baixa.
    """
    if len(expert_frets) <= 2:
        return expert_frets

    if len(expert_frets) != 3:
        return (expert_frets[0], expert_frets[-1])

    low_fret = expert_frets[0]
    middle_fret = expert_frets[1]
    high_fret = expert_frets[2]

    lower_gap = middle_fret - low_fret
    upper_gap = high_fret - middle_fret

    if lower_gap == upper_gap:
        return (low_fret, high_fret)

    if lower_gap < upper_gap:
        return (low_fret, middle_fret)

    return (middle_fret, high_fret)


def reduce_triple_chord_to_medium_double(expert_frets: Tuple[int, ...]) -> Tuple[int, ...]:
    """
    Medium: escolhe um par de uma tríade priorizando as notas que já cabem em GRYB.

    Exemplos desejados:
    - YBO -> YB
    - GYB -> GB
    - RBO -> RB
    - GRY -> GY
    - GRB -> GR
    """
    if len(expert_frets) <= 2:
        return expert_frets

    in_range_frets = tuple(fret_value for fret_value in expert_frets if fret_value <= 3)

    if len(in_range_frets) >= 2:
        if len(in_range_frets) == 2:
            return in_range_frets

        low_fret = in_range_frets[0]
        middle_fret = in_range_frets[1]
        high_fret = in_range_frets[2]
        lower_gap = middle_fret - low_fret
        upper_gap = high_fret - middle_fret

        if upper_gap <= lower_gap:
            return (low_fret, high_fret)

        return (low_fret, middle_fret)

    return reduce_triple_chord_to_double(expert_frets)


def transpose_medium_double_chord(expert_frets: Tuple[int, int]) -> Tuple[int, ...]:
    """
    Medium (GRYB) for dyads with orange:

    When the chord already fits, keep it. When only the top is in O, we prefer
    to preserve the bottom note and only "bring O to B". This prevents different
    ascending progressions from becoming the same shape.

    Examples:
    - RO -> RB
    - YO -> YB
    - BO -> YB (avoids BB)
    """
    if len(expert_frets) != 2:
        return expert_frets

    low_fret, high_fret = expert_frets

    if high_fret <= 3:
        return expert_frets

    if high_fret != 4:
        return expert_frets

    target_high = 3

    if low_fret < target_high:
        return (low_fret, target_high)

    shifted_pair = tuple(
        max(0, fret_value - 1)
        for fret_value in expert_frets
    )

    if len(set(shifted_pair)) == 2:
        return shifted_pair

    return (2, 3)


def reduce_note(en: Note, diff: str, sub: int, isolated: bool,
                in_burst: bool, power_chord_mode: bool,
                anchor: Optional[float]) -> Optional[Note]:
    cfg = DIFF_CONF[diff]
    if en.is_open or not en.frets:
        return Note(en.tick, en.end_tick, (), True, 0, False)

    # Compute anchor shift como inteiro (round) para single notes
    anchor_shift_int = 0
    if anchor is not None:
        # Diferença entre fret base do Expert e o que esperamos no nível alvo
        shift = cfg["anchor_shift"]  # negativo para Easy/Medium
        anchor_shift_int = round(shift)

    if diff == "Easy":
        if len(en.frets) >= 2:
            spread = en.frets[-1] - en.frets[0]
            # R17: power-chord mode mantém acordes mesmo em bursts (Chop Suey)
            if power_chord_mode and spread <= 3:
                # Escolhe um shape de 2 notas que preserve a sensação de grave/agudo
                # do acorde original antes de deslocar para o range do Easy.
                pair = reduce_triple_chord_to_double(en.frets)
                # Shift sistemático -1 (R14) preservando intervalo se possível
                shifted = (pair[0] - 1, pair[1] - 1)
                # Transpor para faixa permitida (mantém shape se cabe)
                new = transpose_chord_shape(shifted, cfg["allowed_frets"], anchor)
                if len(new) > 2: new = (new[0], new[-1])
                return Note(en.tick, en.end_tick, new, False, 0, False)
            base = en.frets[0]
            return Note(en.tick, en.end_tick,
                        (reduce_single_fret(base, cfg["allowed_frets"]),),
                        False, 0, False)
        return Note(en.tick, en.end_tick,
                    (reduce_single_fret(en.frets[0], cfg["allowed_frets"]),),
                    False, 0, False)

    # Medium / Hard
    if len(en.frets) == 1:
        return Note(en.tick, en.end_tick,
                    (reduce_single_fret(en.frets[0], cfg["allowed_frets"], anchor_shift_int),),
                    False, en.forced_hopo if diff in ("Hard", "Medium") else 0, False)
    new = en.frets
    if len(new) > cfg["max_chord_size"]:
        if diff == "Medium":
            new = reduce_triple_chord_to_medium_double(new)
        else:
            new = reduce_triple_chord_to_double(new)

    if diff == "Medium" and len(new) == 2:
        new = transpose_medium_double_chord(new)

    new = transpose_chord_shape(new, cfg["allowed_frets"], anchor)
    return Note(en.tick, en.end_tick, new, False,
                en.forced_hopo if diff == "Hard" else 0, False)


def compute_section_anchors(expert: Chart, window_beats: int = 4):
    """Devolve dict[window_index] -> fret_centroid do Expert."""
    tpb = expert.ticks_per_beat
    win = tpb * window_beats
    out: Dict[int, List[int]] = {}
    for n in expert.notes:
        out.setdefault(n.tick // win, []).extend(n.frets)
    return {w: mean(fs) for w, fs in out.items() if fs}, win


def compute_section_has_fret(
    expert: Chart,
    target_fret: int,
    window_beats: int = 4,
) -> Dict[int, bool]:
    """Devolve dict[window_index] -> se existe ao menos uma nota com `target_fret`."""
    tpb = expert.ticks_per_beat
    win = tpb * window_beats
    out: Dict[int, bool] = {}

    for note_value in expert.notes:
        if target_fret not in note_value.frets:
            continue

        out[note_value.tick // win] = True

    return out


def compute_window_fret_shift(expert_centroid: float, allowed_max: int, target_offset: float) -> int:
    """Quanto deslocar single notes desta janela:
       shift = round(target_centroid - expert_centroid).
       Se o expert_centroid já cabe próximo do target, shift=0."""
    target = max(0, expert_centroid + target_offset)
    shift = round(target - expert_centroid)
    return shift


def _single_note_run_shift_for_allowed_range(
    run_notes: List[Note],
    allowed_frets: Tuple[int, ...],
) -> int:
    """
    Escolhe um shift inteiro único para uma frase melódica de singles.

    A ideia é preservar o contorno local quando o Expert/Hard "anda para a direita"
    do braço. Em vez de clipar cada nota isoladamente, deslocamos a frase toda o
    mínimo necessário para fazer o topo caber na dificuldade alvo.

    Se a frase já cabe, não desloca.
    """
    if not run_notes:
        return 0

    run_frets = [note.frets[0] for note in run_notes if note.frets]

    if not run_frets:
        return 0

    allowed_max = max(allowed_frets)
    run_max = max(run_frets)

    if run_max <= allowed_max:
        return 0

    return allowed_max - run_max


def _single_note_run_ranges(
    notes: List[Note],
    tpb: int,
    minimum_note_count: int = 1,
    maximum_gap_override: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """
    Faixas [start, end) de frases contíguas de notas simples fretted.

    Não atravessa opens nem acordes.
    """
    if not notes:
        return []

    max_gap = max(1, tpb // 2)

    if maximum_gap_override is not None:
        max_gap = max(1, int(maximum_gap_override))
    run_ranges: List[Tuple[int, int]] = []
    run_start_index: Optional[int] = None

    previous_tick: Optional[int] = None

    for note_index, note_value in enumerate(notes):
        is_simple_fretted_note = (
            not note_value.is_open
            and len(note_value.frets) == 1
        )

        if not is_simple_fretted_note:
            if (
                run_start_index is not None
                and (note_index - run_start_index) >= minimum_note_count
            ):
                run_ranges.append((run_start_index, note_index))
            previous_tick = None
            run_start_index = None
            continue

        if run_start_index is None:
            run_start_index = note_index
            previous_tick = note_value.tick
            continue

        if previous_tick is not None and (note_value.tick - previous_tick) > max_gap:
            if (note_index - run_start_index) >= minimum_note_count:
                run_ranges.append((run_start_index, note_index))
            run_start_index = note_index

        previous_tick = note_value.tick

    if (
        run_start_index is not None
        and (len(notes) - run_start_index) >= minimum_note_count
    ):
        run_ranges.append((run_start_index, len(notes)))

    return run_ranges


def _single_note_run_shifts(
    notes: List[Note],
    tpb: int,
    allowed_frets: Tuple[int, ...],
) -> Dict[int, int]:
    """
    Dict[index_in_notes] -> shift para frases contíguas de notas simples fretted.

    Não atravessa opens nem acordes. Também não deixa um único fret fora da
    faixa "puxar" a frase inteira para a esquerda: o shift é aplicado só em
    clusters locais que realmente precisam dele, com um pequeno lead-in.
    """
    if not notes:
        return {}

    max_gap = max(1, tpb // 2)
    shifts_by_index: Dict[int, int] = {}
    run_ranges = _single_note_run_ranges(notes, tpb)

    for run_start_index, run_end_exclusive in run_ranges:
        run_notes = notes[run_start_index:run_end_exclusive]
        allowed_max = max(allowed_frets)
        overflow_positions = [
            local_index
            for local_index, note_value in enumerate(run_notes)
            if note_value.frets and note_value.frets[0] > allowed_max
        ]

        if not overflow_positions:
            continue

        cluster_start = overflow_positions[0]
        cluster_end = overflow_positions[0]
        cluster_ranges: List[Tuple[int, int]] = []

        for local_index in overflow_positions[1:]:
            previous_note = run_notes[cluster_end]
            current_note = run_notes[local_index]

            if (current_note.tick - previous_note.tick) > max_gap:
                cluster_ranges.append((cluster_start, cluster_end))
                cluster_start = local_index
                cluster_end = local_index
                continue

            cluster_end = local_index

        cluster_ranges.append((cluster_start, cluster_end))

        for local_start, local_end in cluster_ranges:
            shifted_start = local_start

            if (
                local_start > 0
                and run_notes[local_start - 1].frets
                and run_notes[local_start - 1].frets[0] == allowed_max
            ):
                shifted_start = local_start - 1

            shifted_end_exclusive = min(len(run_notes), local_end + 2)
            shift_notes = run_notes[shifted_start:shifted_end_exclusive]
            run_shift = _single_note_run_shift_for_allowed_range(
                shift_notes,
                allowed_frets,
            )

            if run_shift == 0:
                continue

            for local_note_index in range(shifted_start, shifted_end_exclusive):
                absolute_note_index = run_start_index + local_note_index
                existing_shift = shifts_by_index.get(absolute_note_index, 0)
                shifts_by_index[absolute_note_index] = min(existing_shift, run_shift)

    return shifts_by_index


def _easy_single_note_run_remaps(
    notes: List[Note],
    tpb: int,
    allowed_frets: Tuple[int, ...],
) -> Dict[int, int]:
    """
    Easy: em frases de singles com overflow, usa remapeamento cíclico (`fret % 3`)
    para manter sensação de escala em vez de chapar tudo no topo.
    """
    if not notes:
        return {}

    lane_count = len(allowed_frets)
    allowed_max = max(allowed_frets)
    remaps_by_index: Dict[int, int] = {}
    run_ranges = _single_note_run_ranges(
        notes,
        tpb,
        minimum_note_count=4,
        maximum_gap_override=tpb * 2,
    )

    for run_start_index, run_end_exclusive in run_ranges:
        run_notes = notes[run_start_index:run_end_exclusive]

        if not any(note_value.frets and note_value.frets[0] > allowed_max for note_value in run_notes):
            continue

        for local_note_index, note_value in enumerate(run_notes):
            if not note_value.frets:
                continue

            original_fret = note_value.frets[0]
            remaps_by_index[run_start_index + local_note_index] = original_fret % lane_count

    return remaps_by_index


def _time_sig_num_denom_at_tick(
    time_sigs: List[Tuple[int, int, int]], tick: int
) -> Tuple[int, int]:
    """(num, denom) of the active measure; without map, assume 4/4 (denom=4, quarter note beat)."""
    if not time_sigs:
        return 4, 4
    change_ticks = [s[0] for s in time_sigs]
    i = bisect.bisect_right(change_ticks, tick) - 1
    if i < 0:
        return 4, 4
    return time_sigs[i][1], time_sigs[i][2]


def _time_sig_start_num_denom_at_tick(
    time_sigs: List[Tuple[int, int, int]], tick: int
) -> Tuple[int, int, int]:
    """(start_tick, num, denom) of the active measure; without map, assume 4/4 from 0."""
    if not time_sigs:
        return 0, 4, 4

    change_ticks = [s[0] for s in time_sigs]
    i = bisect.bisect_right(change_ticks, tick) - 1

    if i < 0:
        return 0, 4, 4

    start_tick, num, denom = time_sigs[i]
    return start_tick, num, denom


def _eighth_of_measure_ticks(tpb: int, num: int, denom: int) -> int:
    """
    Duration of 1/8 of measure in ticks: `1/8 * (num * (1 beat))`.
    Beat = denom in time signature: /4=quarter, /8=eighth, etc. (`tpb` = 1 quarter).
    """
    if denom < 1:
        return max(1, tpb // 2)
    one_beat_ticks = (tpb * 4) // denom
    bar_ticks = max(1, num) * one_beat_ticks
    return max(1, bar_ticks // 8)


def _enforce_min_gap_fraction_of_bar(
    notes: List[Note],
    tpb: int,
    time_sigs: List[Tuple[int, int, int]],
    fraction_divisor: int,
) -> List[Note]:
    if not notes or tpb < 1:
        return notes

    if fraction_divisor < 1:
        return notes

    ordered = sorted(notes, key=lambda n: n.tick)
    out_list: List[Note] = []
    last_tick: Optional[int] = None

    for n in ordered:
        n_num, n_denom = _time_sig_num_denom_at_tick(time_sigs, n.tick)
        bar_ticks = max(1, _eighth_of_measure_ticks(tpb, n_num, n_denom) * 8)
        need_gap = max(1, bar_ticks // fraction_divisor)

        if last_tick is not None and (n.tick - last_tick) < need_gap:
            continue

        out_list.append(n)
        last_tick = n.tick

    return out_list


def _easy_enforce_min_gap_eighth_of_bar(
    notes: List[Note], tpb: int, time_sigs: List[Tuple[int, int, int]]
) -> List[Note]:
    return _enforce_min_gap_fraction_of_bar(
        notes,
        tpb,
        time_sigs,
        fraction_divisor=8,
    )


def _easy_snap_to_beat_divisions_of_bar(
    notes: List[Note],
    tpb: int,
    time_sigs: List[Tuple[int, int, int]],
) -> List[Note]:
    """
    Easy: only allows notes at main divisions of the measure.

    In 4/4 this becomes 1, 2, 3, 4 (one note per quarter). In other measures,
    uses the beat unit of the active time signature (`denom`) and keeps at most
    one note per beat-slot, choosing the closest to the beat line.
    """
    if not notes or tpb < 1:
        return notes

    ordered = sorted(notes, key=lambda n: n.tick)
    best_note_by_slot: Dict[Tuple[int, int, int, int], Tuple[int, int, Note]] = {}

    for note_value in ordered:
        sig_start_tick, num, denom = _time_sig_start_num_denom_at_tick(
            time_sigs,
            note_value.tick,
        )
        beat_ticks = max(1, (tpb * 4) // max(1, denom))
        slot_index = max(0, (note_value.tick - sig_start_tick) // beat_ticks)
        snapped_tick = sig_start_tick + (slot_index * beat_ticks)
        slot_key = (sig_start_tick, num, denom, slot_index)
        distance_to_beat = abs(note_value.tick - snapped_tick)
        candidate = (distance_to_beat, note_value.tick, note_value)
        current_best = best_note_by_slot.get(slot_key)

        if current_best is None or candidate < current_best:
            best_note_by_slot[slot_key] = candidate

    snapped_notes: List[Note] = []

    for _, _, kept_note in sorted(best_note_by_slot.values(), key=lambda item: item[1]):
        sig_start_tick, _, denom = _time_sig_start_num_denom_at_tick(
            time_sigs,
            kept_note.tick,
        )
        beat_ticks = max(1, (tpb * 4) // max(1, denom))
        slot_index = max(0, (kept_note.tick - sig_start_tick) // beat_ticks)
        snapped_tick = sig_start_tick + (slot_index * beat_ticks)
        duration_ticks = max(0, kept_note.end_tick - kept_note.tick)
        snapped_notes.append(
            Note(
                snapped_tick,
                snapped_tick + duration_ticks,
                kept_note.frets,
                kept_note.is_open,
                kept_note.forced_hopo,
                kept_note.is_tap,
            )
        )

    snapped_notes.sort(key=lambda n: n.tick)
    return snapped_notes


def _medium_enforce_min_gap_eighth_of_bar(
    notes: List[Note],
    tpb: int,
    time_sigs: List[Tuple[int, int, int]],
    expert_sorted: List[Note],
) -> List[Note]:
    if not notes or tpb < 1:
        return notes

    ordered = sorted(notes, key=lambda n: n.tick)
    expert_by_tick: Dict[int, Note] = {}
    best_single_by_slot: Dict[Tuple[int, int, int, int], Tuple[int, int, Note]] = {}
    extra_long_single_by_slot: Dict[Tuple[int, int, int, int], Note] = {}
    kept_chords: List[Note] = []

    for expert_note in expert_sorted:
        if expert_note.tick not in expert_by_tick:
            expert_by_tick[expert_note.tick] = expert_note

    for note_value in ordered:
        expert_note = expert_by_tick.get(note_value.tick)
        expert_is_chord = (
            expert_note is not None
            and not expert_note.is_open
            and len(expert_note.frets) >= 2
        )

        if expert_is_chord:
            need_gap = max(1, tpb // 4)

            if not kept_chords:
                kept_chords.append(note_value)
                continue

            previous_note = kept_chords[-1]

            if (note_value.tick - previous_note.tick) >= need_gap:
                kept_chords.append(note_value)
                continue

            previous_duration = previous_note.end_tick - previous_note.tick
            current_duration = note_value.end_tick - note_value.tick

            if current_duration > previous_duration:
                kept_chords[-1] = note_value
        else:
            sig_start_tick, num, denom = _time_sig_start_num_denom_at_tick(
                time_sigs,
                note_value.tick,
            )
            bar_ticks = max(1, _eighth_of_measure_ticks(tpb, num, denom) * 8)
            slot_ticks = max(1, bar_ticks // 8)
            slot_index = max(0, (note_value.tick - sig_start_tick) // slot_ticks)
            snapped_tick = sig_start_tick + (slot_index * slot_ticks)
            slot_key = (sig_start_tick, num, denom, slot_index)
            distance_to_slot = abs(note_value.tick - snapped_tick)
            candidate = (distance_to_slot, note_value.tick, note_value)
            current_best = best_single_by_slot.get(slot_key)

            if current_best is None or candidate < current_best:
                best_single_by_slot[slot_key] = candidate

            current_duration = note_value.end_tick - note_value.tick
            current_long = extra_long_single_by_slot.get(slot_key)

            if current_long is None:
                if current_best is not None and current_best[2].tick != note_value.tick:
                    best_duration = current_best[2].end_tick - current_best[2].tick
                    if current_duration > best_duration:
                        extra_long_single_by_slot[slot_key] = note_value
                continue

            long_duration = current_long.end_tick - current_long.tick
            if current_duration > long_duration and note_value.tick != best_single_by_slot[slot_key][2].tick:
                extra_long_single_by_slot[slot_key] = note_value

    kept_singles: List[Note] = [
        best_note
        for _, _, best_note in sorted(best_single_by_slot.values(), key=lambda item: item[1])
    ]

    for slot_key, long_note in extra_long_single_by_slot.items():
        best_note = best_single_by_slot[slot_key][2]
        if long_note.tick == best_note.tick:
            continue
        kept_singles.append(long_note)

    merged_notes = kept_singles + kept_chords
    merged_notes.sort(key=lambda n: n.tick)
    return merged_notes


def _medium_thin_rapid_chord_runs(
    notes: List[Note],
    tpb: int,
) -> List[Note]:
    """
    Medium: when chords alternate between at most 2 shapes at 8th-note speed or
    faster for 4+ consecutive chords, thin the run to one chord per beat.

    This prevents fast-strummed chord passages (e.g. RY/YB alternating at 16th
    or 8th note speed) from carrying their full density into Medium, while leaving
    isolated or slow chord changes untouched.
    """
    if not notes:
        return notes

    max_gap = max(1, tpb // 2)   # 8th note — "rapid" threshold
    min_run = 4                   # minimum consecutive chords to qualify
    beat = tpb                    # thin to one per quarter note

    ordered = sorted(notes, key=lambda n: n.tick)
    n_notes = len(ordered)
    to_remove: set = set()

    i = 0
    while i < n_notes:
        note = ordered[i]
        if note.is_open or len(note.frets) < 2:
            i += 1
            continue

        # Build a consecutive rapid chord run
        run = [i]
        shapes: set = {tuple(sorted(note.frets))}
        j = i + 1
        while j < n_notes:
            curr = ordered[j]
            if curr.is_open or len(curr.frets) < 2:
                break
            if curr.tick - ordered[j - 1].tick > max_gap:
                break
            shapes.add(tuple(sorted(curr.frets)))
            if len(shapes) > 2:
                break
            run.append(j)
            j += 1

        if len(run) >= min_run and len(shapes) <= 2:
            # Keep the first chord in each quarter-note slot, remove the rest
            slots_used: set = set()
            for idx in run:
                slot = ordered[idx].tick // beat
                if slot not in slots_used:
                    slots_used.add(slot)
                else:
                    to_remove.add(idx)
            i = j
        else:
            i += 1

    return [n for idx, n in enumerate(ordered) if idx not in to_remove]


def _medium_guitar_solo_feel(
    notes: List[Note],
    tpb: int,
    time_sigs: List[Tuple[int, int, int]],
    expert_sorted: List[Note],
) -> List[Note]:
    """
    Medium guitar singles: keep the on-beat note every beat, plus alternating one
    between-beat note.

    Pattern (only toggled when between-beat notes actually exist):
      beat A (allowed)  -> on-beat note + first between-beat note  -> flag=restricted
      beat B (restricted) -> on-beat note only                     -> flag=allowed
      beat C (allowed)  -> on-beat note + first between-beat note  -> flag=restricted
      ...

    If a beat has no between-beat notes the flag is NOT toggled, so the next beat
    that does have extras will still get one.  Chords are filtered with the same
    minimum-gap rule as before (>= tpb//4).
    """
    if not notes or tpb < 1:
        return notes

    ordered = sorted(notes, key=lambda n: n.tick)
    expert_by_tick: Dict[int, Note] = {}
    for n in expert_sorted:
        if n.tick not in expert_by_tick:
            expert_by_tick[n.tick] = n

    chord_notes: List[Note] = []
    single_notes: List[Note] = []
    for n in ordered:
        ex = expert_by_tick.get(n.tick)
        is_chord = ex is not None and not ex.is_open and len(ex.frets) >= 2
        if is_chord:
            chord_notes.append(n)
        else:
            single_notes.append(n)

    # Chord gap filter (unchanged from original logic)
    kept_chords: List[Note] = []
    for n in chord_notes:
        need_gap = max(1, tpb // 4)
        if not kept_chords or (n.tick - kept_chords[-1].tick) >= need_gap:
            kept_chords.append(n)
        else:
            prev = kept_chords[-1]
            if (n.end_tick - n.tick) > (prev.end_tick - prev.tick):
                kept_chords[-1] = n

    if not single_notes:
        return sorted(kept_chords, key=lambda n: n.tick)

    def eighth_ticks_at(t: int) -> int:
        _, _, denom = _time_sig_start_num_denom_at_tick(time_sigs, t)
        beat = max(1, (tpb * 4) // max(1, denom))
        return max(1, beat // 2)

    # Build 8th-note grid positions from 0 through the last note
    eighth_starts: List[int] = []
    t = 0
    last_tick = single_notes[-1].tick
    while t <= last_tick + eighth_ticks_at(last_tick):
        eighth_starts.append(t)
        t += eighth_ticks_at(t)

    # A note is "on the 8th" if it falls within 1/4 of an 8th note of the grid position
    kept_singles: List[Note] = []
    can_include_extra = True

    for bi, eighth_t in enumerate(eighth_starts):
        next_eighth_t = eighth_starts[bi + 1] if bi + 1 < len(eighth_starts) else eighth_t + eighth_ticks_at(eighth_t)
        tolerance = max(1, (next_eighth_t - eighth_t) // 4)

        interval = [n for n in single_notes if eighth_t <= n.tick < next_eighth_t]
        if not interval:
            continue

        on_eighth = [n for n in interval if abs(n.tick - eighth_t) <= tolerance]
        between = [n for n in interval if abs(n.tick - eighth_t) > tolerance]

        # If nothing lands close to the 8th, treat the first note as the representative
        if not on_eighth:
            on_eighth = [interval[0]]
            between = interval[1:]

        # Always keep the on-8th note
        kept_singles.append(on_eighth[0])

        if can_include_extra and between:
            # Include the first between-8th note (16th) and restrict the next interval
            kept_singles.append(between[0])
            can_include_extra = False
        elif not can_include_extra:
            # This was the restricted interval; re-allow extras for the next one
            can_include_extra = True
        # If can_include_extra is True but no between notes: don't toggle the flag

    return sorted(kept_chords + kept_singles, key=lambda n: n.tick)


def _medium_preserve_constant_low_chord_progression(
    notes: List[Note],
    expert_sorted: List[Note],
    tpb: int,
) -> List[Note]:
    """
    Medium: em runs de acordes cujo grave do Expert fica fixo, se surgir laranja
    mantemos um shift local de -1 enquanto a nota aguda ainda estiver em B/O.

    Exemplo:
    GR -> GY -> GO -> GB
    vira
    GR -> GY -> GB -> GY

    Isso evita que GO e o GB seguinte virem o mesmo shape no Medium.
    """
    if not notes:
        return notes

    expert_by_tick: Dict[int, Note] = {}

    for expert_note in expert_sorted:
        if expert_note.tick not in expert_by_tick:
            expert_by_tick[expert_note.tick] = expert_note

    ordered_notes = [
        Note(
            note_value.tick,
            note_value.end_tick,
            note_value.frets,
            note_value.is_open,
            note_value.forced_hopo,
            note_value.is_tap,
        )
        for note_value in sorted(notes, key=lambda n: n.tick)
    ]

    max_gap = max(1, tpb)
    run_start_index: Optional[int] = None
    previous_tick: Optional[int] = None
    previous_low_fret: Optional[int] = None

    def flush_run(run_end_exclusive: int) -> None:
        nonlocal run_start_index
        nonlocal previous_low_fret

        if run_start_index is None:
            return

        if run_end_exclusive - run_start_index < 2:
            run_start_index = None
            previous_low_fret = None
            return

        previous_high_fret: Optional[int] = None
        active_orange_pair: Optional[Tuple[int, int]] = None

        for note_index in range(run_start_index, run_end_exclusive):
            medium_note = ordered_notes[note_index]
            expert_note = expert_by_tick.get(medium_note.tick)

            if expert_note is None or expert_note.is_open or len(expert_note.frets) < 2:
                shift_active = False
                continue

            expert_pair = expert_note.frets

            if len(expert_pair) > 2:
                expert_pair = reduce_triple_chord_to_double(expert_pair)

            expert_low = expert_pair[0]
            expert_high = expert_pair[-1]
            shifted_pair: Optional[Tuple[int, int]] = None

            if expert_high >= 4:
                if expert_low == 0:
                    if previous_high_fret == 4 and active_orange_pair is not None:
                        shifted_pair = active_orange_pair
                    elif previous_high_fret == 3:
                        shifted_pair = (1, 3)
                    else:
                        shifted_pair = (0, 3)

                active_orange_pair = shifted_pair
            elif expert_high == 3 and previous_high_fret == 4:
                if expert_low == 0:
                    shifted_pair = (0, 2)

                active_orange_pair = None
            elif expert_high <= 2:
                active_orange_pair = None

            if shifted_pair is not None and len(set(shifted_pair)) == 2:
                ordered_notes[note_index] = Note(
                    medium_note.tick,
                    medium_note.end_tick,
                    shifted_pair,
                    False,
                    medium_note.forced_hopo,
                    medium_note.is_tap,
                )

            previous_high_fret = expert_high

        run_start_index = None
        previous_low_fret = None

    for note_index, note_value in enumerate(ordered_notes):
        expert_note = expert_by_tick.get(note_value.tick)
        is_candidate = (
            expert_note is not None
            and not expert_note.is_open
            and len(expert_note.frets) >= 2
        )

        if not is_candidate:
            flush_run(note_index)
            previous_tick = None
            continue

        expert_pair = expert_note.frets

        if len(expert_pair) > 2:
            expert_pair = reduce_triple_chord_to_double(expert_pair)

        current_low_fret = expert_pair[0]

        if run_start_index is None:
            run_start_index = note_index
            previous_tick = note_value.tick
            previous_low_fret = current_low_fret
            continue

        if (
            previous_tick is not None
            and (note_value.tick - previous_tick) <= max_gap
            and previous_low_fret == current_low_fret
        ):
            previous_tick = note_value.tick
            previous_low_fret = current_low_fret
            continue

        flush_run(note_index)
        run_start_index = note_index
        previous_tick = note_value.tick
        previous_low_fret = current_low_fret

    flush_run(len(ordered_notes))
    return ordered_notes


def _chord_shape_ignoring_order(frets: Tuple[int, ...]) -> Tuple[int, ...]:
    if len(frets) < 2:
        return ()
    return tuple(sorted(frets))


def _medium_rapid_chord_simplify(
    notes: List[Note],
    tpb: int,
    expert_sorted: List[Note],
) -> List[Note]:
    """
    Só após a redução normal. Dentro de segmentos consecutivos com intervalo
    **≤ 1/16** da semínima, a partir de `snap` (3+ notas de acorde → 2, extremas):
    - 3+ notas (Expert) vira par no `snap` antes de comparar formas.
    - Em alternação muito rápida **entre formas de par diferentes**, cada par
      vira **uma** nota. Se a forma for **igual** à vizinha, mantém o par (não
      toca, mesmo toque repetido de acorde).
    - 2→1: se **alguma** nota do **Expert** no mesmo trecho (ticks do segmento)
      tiver laranja, mantém o fret **mais alto** (direita); senão o **mais baixo**
      (esquerda).
    """
    if not notes or tpb < 4:
        return notes
    max_gap_rapid = max(1, tpb // 4)
    by_tick = sorted(notes, key=lambda n: n.tick)
    nlen = len(by_tick)

    def to_double(n: Note) -> Note:
        if n.is_open or not n.frets or len(n.frets) < 3:
            return n
        return Note(
            n.tick,
            n.end_tick,
            (n.frets[0], n.frets[-1]),
            False,
            n.forced_hopo,
            n.is_tap,
        )

    snap: List[Note] = [to_double(m) for m in by_tick]
    out: List[Note] = [
        Note(m.tick, m.end_tick, m.frets, m.is_open, m.forced_hopo, m.is_tap) for m in snap
    ]

    segments: List[Tuple[int, int]] = []
    seg0 = 0
    for idx in range(1, nlen):
        if snap[idx].tick - snap[idx - 1].tick > max_gap_rapid:
            segments.append((seg0, idx))
            seg0 = idx
    segments.append((seg0, nlen))

    exp_ticks = [n.tick for n in expert_sorted]
    n_exp = len(expert_sorted)

    def expert_segment_includes_laranja(tick_lo: int, tick_hi: int) -> bool:
        if not expert_sorted or n_exp == 0:
            return False
        i_lo = bisect.bisect_left(exp_ticks, tick_lo)
        i_hi = bisect.bisect_right(exp_ticks, tick_hi)
        for eidx in range(i_lo, i_hi):
            f = expert_sorted[eidx].frets
            if f and (FRET_LARANJA in f):
                return True
        return False

    def is_double_chord(m: Note) -> bool:
        if m.is_open or not m.frets:
            return False
        return len(m.frets) == 2

    def chord_shape2(m: Note) -> Optional[Tuple[int, ...]]:
        if not is_double_chord(m):
            return None
        return _chord_shape_ignoring_order(m.frets)

    for a, bnd in segments:
        t_lo_rapid = snap[a].tick
        t_hi_rapid = snap[bnd - 1].tick
        preserve_direita = expert_segment_includes_laranja(t_lo_rapid, t_hi_rapid)

        for j in range(a, bnd):
            current = snap[j]
            s_cur = chord_shape2(current)
            if s_cur is None:
                continue
            s_prev = chord_shape2(snap[j - 1]) if j > a else None
            s_next = chord_shape2(snap[j + 1]) if j + 1 < bnd else None
            prev_d = is_double_chord(snap[j - 1]) if j > a else False
            next_d = is_double_chord(snap[j + 1]) if j + 1 < bnd else False
            if j > a and prev_d and s_prev is not None and s_cur == s_prev:
                continue
            if j + 1 < bnd and next_d and s_next is not None and s_cur == s_next:
                continue
            to_single = (prev_d and s_prev is not None and s_prev != s_cur) or (
                next_d and s_next is not None and s_next != s_cur
            )
            if to_single and out[j].frets and len(out[j].frets) == 2:
                c = out[j]
                if preserve_direita:
                    one_f = max(c.frets)
                else:
                    one_f = min(c.frets)
                out[j] = Note(
                    c.tick, c.end_tick, (one_f,),
                    False, c.forced_hopo, c.is_tap,
                )

    return out


def _medium_restore_expert_hopos(
    notes: List[Note],
    expert_sorted: List[Note],
    tpb: int,
) -> List[Note]:
    """
    After medium reduction some notes lose their HOPO status because intervening
    notes were removed, increasing the gap to the previous medium note beyond
    Clone Hero's auto-HOPO threshold (≈ tpb//3 at 120 BPM / 170 ms default).

    For every medium single note whose Expert counterpart was an auto-HOPO or
    forced-HOPO, but whose medium predecessor gap now exceeds the threshold,
    this pass adds forced_hopo=+1 so Clone Hero keeps the HOPO.

    Only single-fret notes are considered (chords are never HOPOs).
    """
    if not notes:
        return notes

    threshold = max(1, tpb // 3)

    # Build expert lookup: tick -> Note
    expert_by_tick: Dict[int, Note] = {}
    for n in expert_sorted:
        if n.tick not in expert_by_tick:
            expert_by_tick[n.tick] = n

    # For each expert single, find its previous note (any shape) with a different fret
    expert_singles = [n for n in expert_sorted if not n.is_open and len(n.frets) == 1]
    expert_prev_gap: Dict[int, int] = {}   # tick -> gap from previous note in Expert
    for i, n in enumerate(expert_singles):
        for j in range(i - 1, -1, -1):
            prev = expert_singles[j]
            if prev.frets != n.frets:
                expert_prev_gap[n.tick] = n.tick - prev.tick
                break

    ordered = sorted(notes, key=lambda n: n.tick)

    # Compute each medium single's gap from the previous medium note with a different fret
    medium_prev_gap: Dict[int, int] = {}   # index in ordered -> gap
    for i, n in enumerate(ordered):
        if n.is_open or len(n.frets) != 1:
            continue
        for j in range(i - 1, -1, -1):
            prev = ordered[j]
            if not prev.is_open and prev.frets != n.frets:
                medium_prev_gap[i] = n.tick - prev.tick
                break

    result = list(ordered)
    for i, n in enumerate(ordered):
        if n.is_open or len(n.frets) != 1:
            continue
        if n.forced_hopo != 0:
            continue  # already has an explicit flag

        ex = expert_by_tick.get(n.tick)
        if ex is None or ex.is_open or len(ex.frets) != 1:
            continue

        # Was the Expert note a HOPO?
        ex_forced = ex.forced_hopo == +1
        ex_auto = expert_prev_gap.get(n.tick, 99999) <= threshold
        if not ex_forced and not ex_auto:
            continue  # not a HOPO in Expert — nothing to restore

        # Is the Medium note still auto-HOPO?
        med_gap = medium_prev_gap.get(i, 99999)
        if med_gap <= threshold:
            continue  # still within threshold — no action needed

        # Gap grew beyond threshold: force HOPO
        result[i] = Note(n.tick, n.end_tick, n.frets, n.is_open, +1, n.is_tap)

    return result


def _medium_short_chord_to_single(
    notes: List[Note],
    expert_sorted: List[Note],
    tpb: int,
) -> List[Note]:
    """
    Medium: any chord whose Expert duration is shorter than a 16th note (tpb//4)
    is a decorative melodic tap, not a sustained power chord — reduce it to the
    lower fret.  Long-duration power chords (dur >= tpb//4) are left unchanged.
    """
    threshold = max(1, tpb // 4)
    expert_by_tick: Dict[int, Note] = {}
    for n in expert_sorted:
        if n.tick not in expert_by_tick:
            expert_by_tick[n.tick] = n

    result: List[Note] = []
    prev_fret: Optional[int] = None
    prev_expert_shape: Optional[tuple] = None
    for n in notes:
        if n.is_open or len(n.frets) < 2:
            result.append(n)
            if not n.is_open and n.frets:
                prev_fret = n.frets[-1]
            prev_expert_shape = None
            continue
        ex = expert_by_tick.get(n.tick)
        if ex is not None and (ex.end_tick - ex.tick) < threshold:
            expert_shape = tuple(sorted(ex.frets))
            hi = max(n.frets)
            lo = min(n.frets)
            if expert_shape == prev_expert_shape:
                # Same expert chord repeated — no real movement, hold the same fret
                chosen = prev_fret if prev_fret is not None else hi
            elif prev_fret is None or hi != prev_fret:
                chosen = hi
            elif lo != prev_fret:
                chosen = lo
            else:
                chosen = hi
            result.append(Note(n.tick, n.end_tick, (chosen,), False, n.forced_hopo, n.is_tap))
            prev_fret = chosen
            prev_expert_shape = expert_shape
        else:
            result.append(n)
            prev_fret = max(n.frets)
            prev_expert_shape = None
    return result


def _medium_sustained_landing_chord_to_single(
    notes: List[Note],
    tpb: int,
) -> List[Note]:
    """
    Medium: a long sustained chord (dur >= 4 beats) that lands immediately after
    a single note (gap <= 1 beat) is a melodic landing, not a rhythm power chord.
    Reduce it to the lower fret kept as a single sustain.

    Short rhythm chords (dur < 4 beats) are intentional chord sections — left alone.
    """
    if not notes:
        return notes

    ordered = sorted(notes, key=lambda n: n.tick)
    min_sustain = tpb * 4
    max_gap = tpb

    result = list(ordered)
    for i, n in enumerate(ordered):
        if n.is_open or len(n.frets) < 2:
            continue
        if (n.end_tick - n.tick) < min_sustain:
            continue
        if i == 0:
            continue
        prev = ordered[i - 1]
        if len(prev.frets) != 1:
            continue
        if (n.tick - prev.tick) > max_gap:
            continue
        result[i] = Note(n.tick, n.end_tick, (min(n.frets),), False, n.forced_hopo, n.is_tap)

    return result


def _medium_strip_overlapping_sustains(
    notes: List[Note],
    tpb: int,
) -> List[Note]:
    """
    Medium: if a sustained note has other notes landing inside its hold window,
    the player would need to fret new notes while holding — too hard for Medium.
    Strip the sustain (set duration to zero) in those cases.
    Only considers sustains longer than a quarter note to avoid touching short ties.
    """
    ordered = sorted(notes, key=lambda n: n.tick)
    min_sustain = max(1, tpb)          # only care about holds >= 1 quarter note
    grace = max(1, tpb // 4)          # ignore notes that start within this window of the hold start

    note_ticks = [n.tick for n in ordered]

    result: List[Note] = []
    for n in ordered:
        dur = n.end_tick - n.tick
        if dur < min_sustain:
            result.append(n)
            continue

        # Check whether any other note falls strictly inside the hold window
        window_start = n.tick + grace
        window_end = n.end_tick
        lo = bisect.bisect_left(note_ticks, window_start)
        hi = bisect.bisect_left(note_ticks, window_end)
        has_overlap = any(
            ordered[i].tick != n.tick
            for i in range(lo, hi)
        )

        if has_overlap:
            result.append(Note(n.tick, n.tick, n.frets, n.is_open, n.forced_hopo, n.is_tap))
        else:
            result.append(n)
    return result


def _find_expert_alternating_anchor_ticks(
    expert_sorted: List[Note],
    tpb: int,
    min_run: int = 4,
) -> set:
    """
    Detects ticks where Expert plays a 'constant anchor' single note alternating with
    other single notes (e.g., O R O Y O R O Y — O is the anchor every other beat).
    Returns the set of anchor ticks so Medium can omit those notes.
    """
    singles: List[Note] = [n for n in expert_sorted if not n.is_open and len(n.frets) == 1]
    n = len(singles)
    anchor_ticks: set = set()
    max_step = tpb * 2 + tpb // 4  # max 2 beats between two anchor notes (one note in between)

    i = 0
    while i < n:
        anchor_fret = singles[i].frets[0]
        run_indices = [i]
        j = i + 2
        while j < n:
            between = j - 1
            if singles[between].frets[0] == anchor_fret:
                break
            if singles[j].tick - singles[j - 2].tick > max_step:
                break
            if singles[j].frets[0] != anchor_fret:
                break
            run_indices.append(j)
            j += 2

        if len(run_indices) >= min_run:
            for idx in run_indices:
                anchor_ticks.add(singles[idx].tick)
            i = j
        else:
            i += 1

    return anchor_ticks


def _medium_remove_alternating_anchor_notes(
    notes: List[Note],
    anchor_ticks: set,
) -> List[Note]:
    """Removes medium notes at ticks where Expert has a constant alternating anchor note."""
    return [n for n in notes if n.tick not in anchor_ticks]


def reduce_chart(expert: Chart, target_diff: str) -> Chart:
    cfg = DIFF_CONF[target_diff]
    tpb = expert.ticks_per_beat
    sustain_mode = classify_sustain_mode(expert)
    pc_mode = classify_power_chord_mode(expert)
    anchors, win = compute_section_anchors(expert)
    section_has_orange = compute_section_has_fret(expert, FRET_LARANJA)
    notes = sorted(expert.notes, key=lambda n: n.tick)
    runs = find_runs(notes, tpb)
    in_burst = [False] * len(notes)
    for run in runs:
        if len(run) > 2:
            for i in run: in_burst[i] = True

    # Pré-computa shift por janela (R14):
    # Regra ajustada nos dados das 6 músicas (avg shift Medium ~ -0.36):
    # - Se centroid Expert > allowed_max: shift para caber (-N).
    # - Se diff=Easy e centroid Expert >= 1.5 → shift -1.
    # - Se diff=Medium e centroid Expert >= 1.5 → shift -1.
    # - Senão shift=0 (mantém Expert frets).
    # BYOB (centroid baixo, ~0.4) cai no caso shift=0.
    window_shift: Dict[int, int] = {}
    allowed_max = max(cfg["allowed_frets"])
    for w, exp_cent in anchors.items():
        if exp_cent > allowed_max:
            window_shift[w] = -int(round(exp_cent - allowed_max))
        elif target_diff == "Easy" and exp_cent >= 1.5:
            window_shift[w] = -1

    easy_single_run_remap: Dict[int, int] = {}
    single_run_shift: Dict[int, int] = {}

    if target_diff == "Easy":
        easy_single_run_remap = _easy_single_note_run_remaps(
            notes,
            tpb,
            cfg["allowed_frets"],
        )

    if target_diff in ("Easy", "Medium"):
        single_run_shift = _single_note_run_shifts(
            notes,
            tpb,
            cfg["allowed_frets"],
        )

    out: List[Note] = []
    for i, en in enumerate(notes):
        sub = sub_beat(en.tick, tpb)
        gap_prev = (en.tick - notes[i-1].tick) if i > 0 else 99999
        gap_next = (notes[i+1].tick - en.tick) if i+1 < len(notes) else 99999
        isolated = gap_prev > tpb // 2 and gap_next > tpb // 2

        anchor = anchors.get(en.tick // win)
        if anchor is not None: anchor += cfg["anchor_shift"]

        # Aplicar shift pré-computado a este single (só Easy/Medium)
        wshift = window_shift.get(en.tick // win, 0) if target_diff in ("Easy","Medium") else 0
        run_shift = single_run_shift.get(i, 0)
        total_shift = wshift + run_shift
        en_shifted = en

        if target_diff == "Easy" and len(en.frets) == 1 and i in easy_single_run_remap:
            new_f = easy_single_run_remap[i]
            en_shifted = Note(en.tick, en.end_tick, (new_f,), False, en.forced_hopo, en.is_tap)
        elif total_shift != 0 and len(en.frets) == 1:
            new_f = max(0, min(allowed_max, en.frets[0] + total_shift))
            en_shifted = Note(en.tick, en.end_tick, (new_f,), False, en.forced_hopo, en.is_tap)

        n_red = reduce_note(en_shifted, target_diff, sub, isolated, in_burst[i], pc_mode, anchor)
        if n_red is None: continue

        # R11/R16
        if sustain_mode == "aggressive" and target_diff in ("Easy", "Medium"):
            if n_red.end_tick - n_red.tick < tpb:
                n_red = Note(n_red.tick, n_red.tick, n_red.frets, n_red.is_open, n_red.forced_hopo, False)

        out.append(n_red)

    if target_diff == "Easy" and out:
        out = _easy_enforce_min_gap_eighth_of_bar(out, tpb, list(expert.time_sigs))
        out = _easy_snap_to_beat_divisions_of_bar(out, tpb, list(expert.time_sigs))

    if target_diff in ("Medium", "Hard") and out:
        anchor_ticks = _find_expert_alternating_anchor_ticks(notes, tpb)
        if anchor_ticks:
            out = _medium_remove_alternating_anchor_notes(out, anchor_ticks)

    if target_diff == "Medium" and out:
        out = _medium_thin_rapid_chord_runs(out, tpb)

    if target_diff == "Medium" and out:
        out = _medium_guitar_solo_feel(out, tpb, list(expert.time_sigs), notes)
        out = _medium_preserve_constant_low_chord_progression(out, notes, tpb)

    if target_diff == "Medium" and out:
        out = _medium_rapid_chord_simplify(out, tpb, notes)

    if target_diff == "Medium" and out:
        out = _medium_short_chord_to_single(out, notes, tpb)

    if target_diff == "Medium" and out:
        out = _medium_sustained_landing_chord_to_single(out, tpb)

    if target_diff == "Medium" and out:
        out = _medium_strip_overlapping_sustains(out, tpb)

    # Must run last — gaps are only final after all note-removal passes above
    if target_diff == "Medium" and out:
        out = _medium_restore_expert_hopos(out, notes, tpb)

    return Chart(
        instrument=expert.instrument, difficulty=target_diff,
        ticks_per_beat=tpb, notes=out,
        overdrive=list(expert.overdrive), solos=list(expert.solos),
        tempos=list(expert.tempos), time_sigs=list(expert.time_sigs),
    )


if __name__ == "__main__":
    import mido, glob
    base = "songs/harmonix"
    for f in sorted(glob.glob(f"{base}/System*")):
        from parse_chart import parse_part
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        official = parse_part(mid, "PART GUITAR")
        sm = classify_sustain_mode(official["Expert"]); pcm = classify_power_chord_mode(official["Expert"])
        print(f"\n=== {name}  pc_mode={pcm}  sustain_mode={sm} ===")
        for diff in ("Hard", "Medium", "Easy"):
            gen = reduce_chart(official["Expert"], diff)
            off = official[diff]
            ot, gt = {n.tick for n in off.notes}, {n.tick for n in gen.notes}
            inter = ot & gt
            print(f"  {diff}: official={len(ot)} gen={len(gt)}  prec={len(inter)/max(len(gt),1):.2f} rec={len(inter)/max(len(ot),1):.2f}")

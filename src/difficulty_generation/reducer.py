"""
Guitar: reduce Expert para Easy / Medium / Hard (PART GUITAR).

Mantém as notas do Expert (Easy pode **descartar** eventos; ver abaixo). Só a
**dificuldade** muda: faixa de frets, tamanho de acorde, shift de âncora,
R11/R16 em sustains, R17 em bursts.

**Medium** (`_medium_rapid_chord_simplify`): em alternação muito rápida, três (ou
mais) vira duas; pares de formas *diferentes* (não a mesma repetida) viram
singles. Ao vira 2→1, se o **Expert** no mesmo trecho tiver laranja (O), mantém
a nota “da direita” (fret mais alta); senão mantém a “da esquerda”.

**Easy** (`_easy_enforce_min_gap_eighth_of_bar`): mínimo **1/8 de compasso** entre
onset consecutivo (4/4 → `tpb/2` ticks); com `time_sigs` do mapa, o oitavo de
compasso acompanha `num`/`denom` (1/8 da duração da barra).

Ver `reduce_note` e `DIFF_CONF` por nível.
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
    return "aggressive" if median(n.duration for n in expert.notes) < 100 else "melodic"


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
        anchor_fret = sum(expert_frets) / len(expert_frets)
    candidates.sort(key=lambda c: abs(sum(c)/len(c) - anchor_fret))
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
                # Shape com 2 notas (lowest+highest do Expert), comprimido para caber em GRY
                pair = (en.frets[0], en.frets[-1])
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
                    False, en.forced_hopo if diff == "Hard" else 0, False)
    new = en.frets
    if len(new) > cfg["max_chord_size"]:
        new = (new[0], new[-1])
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


def compute_window_fret_shift(expert_centroid: float, allowed_max: int, target_offset: float) -> int:
    """Quanto deslocar single notes desta janela:
       shift = round(target_centroid - expert_centroid).
       Se o expert_centroid já cabe próximo do target, shift=0."""
    target = max(0, expert_centroid + target_offset)
    shift = round(target - expert_centroid)
    return shift


def _time_sig_num_denom_at_tick(
    time_sigs: List[Tuple[int, int, int]], tick: int
) -> Tuple[int, int]:
    """(num, denom) do compasso ativo; sem mapa, assume 4/4 (denom=4, semínima com batida)."""
    if not time_sigs:
        return 4, 4
    change_ticks = [s[0] for s in time_sigs]
    i = bisect.bisect_right(change_ticks, tick) - 1
    if i < 0:
        return 4, 4
    return time_sigs[i][1], time_sigs[i][2]


def _eighth_of_measure_ticks(tpb: int, num: int, denom: int) -> int:
    """
    Duração de 1/8 de compasso em ticks: `1/8 * (num * (1 batida))`.
    Batida = denom na partitura: /4=semínima, /8=colcheia, etc. (`tpb` = 1 semínima).
    """
    if denom < 1:
        return max(1, tpb // 2)
    one_beat_ticks = (tpb * 4) // denom
    bar_ticks = max(1, num) * one_beat_ticks
    return max(1, bar_ticks // 8)


def _easy_enforce_min_gap_eighth_of_bar(
    notes: List[Note], tpb: int, time_sigs: List[Tuple[int, int, int]]
) -> List[Note]:
    if not notes or tpb < 1:
        return notes
    ordered = sorted(notes, key=lambda n: n.tick)
    out_list: List[Note] = []
    last_tick: Optional[int] = None
    for n in ordered:
        n_num, n_denom = _time_sig_num_denom_at_tick(time_sigs, n.tick)
        need_gap = _eighth_of_measure_ticks(tpb, n_num, n_denom)
        if last_tick is not None and (n.tick - last_tick) < need_gap:
            continue
        out_list.append(n)
        last_tick = n.tick
    return out_list


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


def reduce_chart(expert: Chart, target_diff: str) -> Chart:
    cfg = DIFF_CONF[target_diff]
    tpb = expert.ticks_per_beat
    sustain_mode = classify_sustain_mode(expert)
    pc_mode = classify_power_chord_mode(expert)
    anchors, win = compute_section_anchors(expert)
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
        elif target_diff in ("Easy", "Medium") and exp_cent >= 1.5:
            window_shift[w] = -1

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
        en_shifted = en
        if wshift != 0 and len(en.frets) == 1:
            new_f = max(0, min(allowed_max, en.frets[0] + wshift))
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

    if target_diff == "Medium" and out:
        out = _medium_rapid_chord_simplify(out, tpb, notes)

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

"""
Gerador v3 — pipeline com filtro de densidade-alvo.

Pipeline:
  1. classify modes (sustain, power-chord)
  2. score every Expert note by (sub-beat, duration, isolation, run-position, sustain)
  3. keep top-N notes  where  N = round(|Expert| * TARGET_DENSITY[diff])
  4. transform frets via R8 + R14 (anchor by section)
  5. apply R11/R16 sustain rules + R13 force-HOPO
"""
from __future__ import annotations
import os, sys
from collections import defaultdict
from statistics import median, mean
from typing import List, Tuple, Optional, Set, Dict
sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import Chart, Note, FRET_NAMES

DIFF_CONF = {
    "Easy":   dict(max_chord_size=2, allowed_frets=(0, 1, 2),       anchor_shift=-1.0),
    "Medium": dict(max_chord_size=2, allowed_frets=(0, 1, 2, 3),    anchor_shift=-0.5),
    "Hard":   dict(max_chord_size=2, allowed_frets=(0, 1, 2, 3, 4), anchor_shift= 0.0),
}

# Densidade-alvo média (fallback) — usada se o modelo adaptativo não puder rodar.
TARGET_DENSITY = {"Easy": 0.23, "Medium": 0.38, "Hard": 0.65}

# Modelo linear ajustado nas 6 músicas SOAD (RMSE ~0.03 em Easy/Medium, ~0.05 em Hard):
#   target = a + b * notes_per_beat + c * fração-de-notas-on-beat
# Features computadas em compute_song_features().
DENSITY_MODEL = {
    "Easy":   ( 0.134, -0.0121, 0.3693),
    "Medium": ( 0.423, -0.0599, 0.3731),
    "Hard":   ( 0.819, -0.1182, 0.4771),
}


def compute_song_features(expert: Chart):
    """Devolve (notes_per_beat, sub0_ratio) usados pelo modelo de densidade."""
    notes = sorted(expert.notes, key=lambda n: n.tick)
    if not notes: return (0.0, 0.0)
    tpb = expert.ticks_per_beat
    span = (notes[-1].tick - notes[0].tick) / tpb
    npb = len(notes) / span if span > 0 else 0
    sub0 = sum(1 for n in notes if (n.tick % tpb) // (tpb // 4) == 0) / len(notes)
    return npb, sub0


def predict_target_density(expert: Chart, diff: str) -> float:
    npb, sub0 = compute_song_features(expert)
    a, b, c = DENSITY_MODEL[diff]
    pred = a + b * npb + c * sub0
    # Clamp a faixa observada (segurança em músicas extremas)
    bounds = {"Easy": (0.10, 0.35), "Medium": (0.20, 0.55), "Hard": (0.40, 0.90)}
    lo, hi = bounds[diff]
    return max(lo, min(hi, pred))


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


def score_expert_notes(expert: Chart, diff: str) -> Dict[int, float]:
    """Atribui um score a cada nota Expert (chave = índice em sorted).
       Score = peso por (sub-beat, duração, posição-na-run, isolamento, fret-change)."""
    tpb = expert.ticks_per_beat
    notes = sorted(expert.notes, key=lambda n: n.tick)
    runs = find_runs(notes, tpb)
    scores: Dict[int, float] = {}
    for run in runs:
        run_size = len(run)
        for pos_in_run, gi in enumerate(run):
            n = notes[gi]
            sub = sub_beat(n.tick, tpb)

            # 1) Sub-beat base (R5) — sub1/sub3 vale mais em Hard (preserva 16ths)
            if sub == 0:   s = 100
            elif sub == 2: s = 60
            elif diff == "Hard": s = 35   # 16ths fracos em Hard ainda contam
            else:          s = 5

            # 2) Duração — sustains longos são SAGRADOS (sobescrevem sub-beat)
            if   n.duration >= 2*tpb: s += 120  # ≥ 2 beats: dominante
            elif n.duration >= tpb:   s += 80   # ≥ 1 beat
            elif n.duration >= tpb//2: s += 40  # ≥ 1/2 beat
            elif n.duration >= tpb//4: s += 10

            # 3) Posição na run (bordas) (R9)
            if run_size > 1:
                if pos_in_run == 0 or pos_in_run == run_size - 1: s += 18
                # Penalidade para meio de run rápida em Easy/Medium
                if diff in ("Easy", "Medium") and 0 < pos_in_run < run_size-1 and sub in (1, 3):
                    s -= 30

            # 4) Isolamento (R15)
            gap_prev = (n.tick - notes[gi-1].tick) if gi > 0 else 99999
            gap_next = (notes[gi+1].tick - n.tick) if gi+1 < len(notes) else 99999
            if gap_prev > tpb and gap_next > tpb:
                s += 30

            # 5) Mudança de fret-set vs anterior — uma "voz nova" é mais importante que repetição
            if gi == 0 or notes[gi-1].frets != n.frets:
                s += 8

            # 6) Bonus pequeno para acorde
            if len(n.frets) >= 2: s += 8

            scores[gi] = s
    return scores


def select_kept_indices(expert: Chart, diff: str) -> Set[int]:
    """Decimação por janela de 1 beat — top-K por beat, K = round(local * target_ratio)."""
    notes = sorted(expert.notes, key=lambda n: n.tick)
    if not notes: return set()
    tpb = expert.ticks_per_beat
    target_ratio = predict_target_density(expert, diff)
    scores = score_expert_notes(expert, diff)

    by_beat: Dict[int, List[int]] = defaultdict(list)
    for i, n in enumerate(notes):
        by_beat[n.tick // tpb].append(i)

    cap_per_beat = {"Easy": 1, "Medium": 3, "Hard": 6}[diff]
    fallback_threshold = {"Easy": 110, "Medium": 90, "Hard": 50}[diff]

    kept: Set[int] = set()
    for beat, idxs in by_beat.items():
        local = len(idxs)
        n_keep = max(0, round(local * target_ratio))
        n_keep = min(n_keep, cap_per_beat)

        if n_keep == 0 and local >= 1:
            best = max(idxs, key=lambda i: scores[i])
            if scores[best] >= fallback_threshold:
                n_keep = 1

        if n_keep == 0: continue
        for i in sorted(idxs, key=lambda i: -scores[i])[:n_keep]:
            kept.add(i)
    return kept


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


def reduce_chart(expert: Chart, target_diff: str) -> Chart:
    cfg = DIFF_CONF[target_diff]
    tpb = expert.ticks_per_beat
    sustain_mode = classify_sustain_mode(expert)
    pc_mode = classify_power_chord_mode(expert)
    anchors, win = compute_section_anchors(expert)
    notes = sorted(expert.notes, key=lambda n: n.tick)
    kept_idxs = select_kept_indices(expert, target_diff)
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
        if i not in kept_idxs: continue
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

    return Chart(
        instrument=expert.instrument, difficulty=target_diff,
        ticks_per_beat=tpb, notes=out,
        overdrive=list(expert.overdrive), solos=list(expert.solos),
        tempos=list(expert.tempos), time_sigs=list(expert.time_sigs),
    )


if __name__ == "__main__":
    import mido, glob
    base = "/Users/gabrielcarvalho/Downloads/system"
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

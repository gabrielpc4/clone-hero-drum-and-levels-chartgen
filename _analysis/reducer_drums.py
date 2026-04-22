"""
Gerador de chart drums Easy/Medium/Hard a partir do Expert (PART DRUMS).

Implementa as regras D-R1 a D-R12 documentadas em §14 do HANDOFF.md.

Pipeline:
  1. Para cada nota Expert (kick / snare / Y / B / G, com is_cymbal):
     - Decidir se mantém esse tick na dificuldade alvo
     - Aplicar conversão de lane (D-R1, D-R1.1, D-R9, D-R10, D-R11)
     - Aplicar regra D-R3 (kick paired only em E/M)
  2. 2x kick (pitch 95): drop sempre (D-R7)
  3. Markers 110/111/112: preservar mas só consultados em Hard/Expert
  4. Drum fills 120-124: preservar
"""
from __future__ import annotations
import os, sys
from collections import defaultdict, Counter
from statistics import median
from typing import Dict, List, Set, Tuple
sys.path.insert(0, os.path.dirname(__file__))
from parse_drums import (parse_drums, DrumNote, DrumChart, DIFF_BASE_DRUMS,
                         LANE_NAMES, LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN)


# Densidade-alvo por lane e dificuldade — calibrada via regressão sobre as 6 músicas SOAD.
# Para toms: ratio observado de notas-do-mesmo-lane na redução vs Expert.
TOM_RATIOS = {
    "Easy":   {LANE_KICK: 0.10, LANE_SNARE: 0.58, LANE_YELLOW: 0.38,
               LANE_BLUE: 0.74, LANE_GREEN: 0.71},
    "Medium": {LANE_KICK: 0.30, LANE_SNARE: 0.60, LANE_YELLOW: 0.76,
               LANE_BLUE: 0.72, LANE_GREEN: 0.83},
    "Hard":   {LANE_KICK: 0.62, LANE_SNARE: 0.77, LANE_YELLOW: 0.77,
               LANE_BLUE: 0.93, LANE_GREEN: 1.00},
}
# Cymbals — só Hard usa (E/M = 0 cymbals).
CYMBAL_RATIOS_HARD = {LANE_YELLOW: 0.93, LANE_BLUE: 0.46, LANE_GREEN: 0.25}
# Em E/M, conversão cymbal→tom acontece numa fração baixa do total.
CYMBAL_TO_TOM_FRACTION = {"Easy": 0.20, "Medium": 0.30}


def is_paired_kick(en: DrumNote, expert_notes_by_tick: Dict[int, List[DrumNote]]) -> bool:
    """Kick está paired (D-R3) se há outra nota Expert no mesmo tick."""
    others = [n for n in expert_notes_by_tick.get(en.tick, []) if n.lane != LANE_KICK]
    return bool(others)


def detect_lane_consolidation(expert: DrumChart) -> Dict[int, int]:
    """Detecta D-R9: lanes pouco usadas devem ser consolidadas em E/M.
       Retorna mapping {lane_origem -> lane_destino} para Easy/Medium.

       Critérios (qualquer um aciona consolidação Blue → Yellow):
         (a) Blue-tom Expert < 1/3 das Yellow-tom (Blue raro)
         (b) Y-cym Expert é dominante (>50 e >= Blue-tom): a parte rítmica
             principal é hi-hat amarelo, então tudo Blue consolida em Y."""
    counts = Counter()
    for n in expert.notes:
        counts[(n.lane, n.is_cymbal)] += 1
    y_tom = counts.get((LANE_YELLOW, False), 0)
    b_tom = counts.get((LANE_BLUE, False), 0)
    y_cym = counts.get((LANE_YELLOW, True), 0)
    mapping = {}
    blue_rare = b_tom < y_tom / 3
    # Y-cym presente significa que o riff principal usa hi-hat amarelo;
    # nesses casos, em E/M, Blue-tom tende a consolidar para Yellow.
    y_cym_active = y_cym > 50
    if blue_rare or y_cym_active:
        mapping[LANE_BLUE] = LANE_YELLOW
    return mapping


def detect_green_cym_strategy(expert: DrumChart) -> str:
    """Estratégia para Green-cym do Expert em Hard (D-R10):
       - Se >30 Green-cym: tende a virar Blue-cym
       - Se <=30: pode preservar Green-cym
       Em E/M: Green-cym vira Blue-tom (não Green-tom!)."""
    n_green_cym = sum(1 for n in expert.notes
                      if n.lane == LANE_GREEN and n.is_cymbal)
    return "to_blue_cym" if n_green_cym > 30 else "keep"


def reduce_drums(expert: DrumChart, target_diff: str) -> DrumChart:
    """Pipeline completo de redução de drums."""
    tpb = expert.ticks_per_beat
    target = TOM_RATIOS[target_diff]
    lane_consol = detect_lane_consolidation(expert)
    green_cym_strategy = detect_green_cym_strategy(expert)

    # Index Expert por tick (para checar paired kick)
    expert_by_tick: Dict[int, List[DrumNote]] = defaultdict(list)
    for n in expert.notes:
        if n.is_2x_kick: continue  # D-R7
        expert_by_tick[n.tick].append(n)

    # Indexa Expert por (lane,is_cym) para selecionar quais sobrevivem por lane
    by_lane_cym: Dict[Tuple[int, bool], List[DrumNote]] = defaultdict(list)
    for n in expert.notes:
        if n.is_2x_kick: continue
        by_lane_cym[(n.lane, n.is_cymbal)].append(n)

    # Para cada (lane, is_cym), selecionar top-N por taxa-alvo
    # Score: + on-beat (sub0=100, sub2=60, outros=10), + paired-with-snare bonus
    def score(n: DrumNote) -> float:
        sub = (n.tick % tpb) // (tpb // 4)
        s = 100 if sub == 0 else 60 if sub == 2 else 10
        # bonus se paired com snare
        others = expert_by_tick.get(n.tick, [])
        if any(o.lane == LANE_SNARE for o in others if o is not n):
            s += 30
        return s

    kept_notes: List[DrumNote] = []

    # ---- Snare (D-R2): preservar conforme target ----
    snare_notes = by_lane_cym.get((LANE_SNARE, False), [])
    n_snare = max(0, round(len(snare_notes) * target[LANE_SNARE]))
    chosen = sorted(snare_notes, key=lambda n: -score(n))[:n_snare]
    for n in chosen:
        kept_notes.append(DrumNote(tick=n.tick, lane=LANE_SNARE, is_cymbal=False, velocity=n.velocity))

    # ---- Toms (Y/B/G), aplicar consolidação D-R9 ----
    for src_lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN):
        tom_notes = by_lane_cym.get((src_lane, False), [])
        if not tom_notes: continue
        # Consolidação só em E/M
        dst_lane = src_lane
        if target_diff in ("Easy", "Medium"):
            dst_lane = lane_consol.get(src_lane, src_lane)
        # Selecionar quais manter
        n_keep = max(0, round(len(tom_notes) * target[src_lane]))
        chosen = sorted(tom_notes, key=lambda n: -score(n))[:n_keep]
        for n in chosen:
            kept_notes.append(DrumNote(tick=n.tick, lane=dst_lane, is_cymbal=False, velocity=n.velocity))

    # ---- Cymbals (Y/B/G) — D-R1, D-R1.1, D-R10, D-R11 ----
    for src_lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN):
        cym_notes = by_lane_cym.get((src_lane, True), [])
        if not cym_notes: continue

        # Override por preferência do usuário (2026-04-22):
        # cymbal Expert PRESERVA como cymbal em E/M também (sobrescreve D-R1).
        # A frequência de retenção continua proporcional ao target_lane do nível,
        # mas o destino mantém o is_cymbal=True.
        if target_diff == "Hard":
            cym_target = CYMBAL_RATIOS_HARD.get(src_lane, 0.5)
        else:
            # Em E/M, usar fração do tom_target da própria lane (proporcional)
            cym_target = target.get(src_lane, 0.5) * 0.7
        n_keep = max(0, round(len(cym_notes) * cym_target))
        chosen = sorted(cym_notes, key=lambda n: -score(n))[:n_keep]
        for n in chosen:
            # G-cym pode virar B-cym em Hard (D-R10) ou em E/M (consistência visual)
            if src_lane == LANE_GREEN and green_cym_strategy == "to_blue_cym":
                kept_notes.append(DrumNote(tick=n.tick, lane=LANE_BLUE, is_cymbal=True, velocity=n.velocity))
            else:
                kept_notes.append(DrumNote(tick=n.tick, lane=src_lane, is_cymbal=True, velocity=n.velocity))

    # ---- Kick (D-R3, D-R4) — só paired em E/M ----
    kick_notes = by_lane_cym.get((LANE_KICK, False), [])
    if kick_notes:
        # Filtrar paired vs solo
        paired = [n for n in kick_notes if is_paired_kick(n, expert_by_tick)]
        solo = [n for n in kick_notes if not is_paired_kick(n, expert_by_tick)]
        if target_diff in ("Easy", "Medium"):
            # Só paired (D-R3)
            n_keep = max(0, round(len(kick_notes) * target[LANE_KICK]))
            chosen = sorted(paired, key=lambda n: -score(n))[:n_keep]
        else:  # Hard
            n_keep = max(0, round(len(kick_notes) * target[LANE_KICK]))
            # Hard prefere paired mas pode pegar solo
            ranked = sorted(kick_notes, key=lambda n: -(score(n) + (20 if is_paired_kick(n, expert_by_tick) else 0)))
            chosen = ranked[:n_keep]
        for n in chosen:
            kept_notes.append(DrumNote(tick=n.tick, lane=LANE_KICK, is_cymbal=False, velocity=n.velocity))

    # Sort final
    kept_notes.sort(key=lambda n: (n.tick, n.lane))

    # Filtro anti-16ths-consecutivos em E/M/H (preferência do usuário 2026-04-22):
    # qualquer par de notas mesma-lane com gap ≤ 1/16 nota é considerado "rápido demais"
    # para Easy/Medium/Hard — só Expert tolera 16ths consecutivos.
    if target_diff in ("Easy", "Medium", "Hard"):
        kept_notes = filter_fast_clusters(kept_notes, tpb, target_diff)

    return DrumChart(
        difficulty=target_diff, ticks_per_beat=tpb, notes=kept_notes,
        overdrive=list(expert.overdrive), drum_fills=list(expert.drum_fills),
        cymbal_flags=dict(expert.cymbal_flags),
    )


def filter_fast_clusters(notes: List[DrumNote], tpb: int, diff: str) -> List[DrumNote]:
    """Bane notas mesma-lane (e mesmo cymbal flag) com gap absoluto ≤ 1/16 nota,
       inclusive em snare e kick. Apenas Expert tolera notas tão próximas.
         Hard:   espaçamento mínimo entre notas mantidas = 1/8 (= colcheia).
         Medium: idem (1/8).
         Easy:   espaçamento mínimo = 1/4 (= semínima).
       Implementação greedy temporal: percorre o cluster e mantém apenas notas
       cujo tick fica ≥ min_gap após a última nota mantida. Robusto a notas
       off-grid (32nds humanizadas etc.)."""
    if not notes: return notes
    by_lane: Dict[Tuple[int, bool], List[DrumNote]] = defaultdict(list)
    for n in notes:
        by_lane[(n.lane, n.is_cymbal)].append(n)

    out: List[DrumNote] = []
    sixteenth = tpb // 4  # 120 ticks @ tpb=480
    min_gap = tpb // 2 if diff in ("Hard", "Medium") else tpb  # 240 ou 480

    for (lane, is_cym), lane_notes in by_lane.items():
        lane_notes.sort(key=lambda n: n.tick)
        i = 0
        while i < len(lane_notes):
            cluster = [lane_notes[i]]
            while i + 1 < len(lane_notes) and lane_notes[i+1].tick - cluster[-1].tick <= sixteenth:
                cluster.append(lane_notes[i+1])
                i += 1
            if len(cluster) == 1:
                out.append(cluster[0])
            else:
                last_tick = None
                for n in cluster:
                    if last_tick is None or n.tick - last_tick >= min_gap:
                        out.append(n); last_tick = n.tick
            i += 1
    out.sort(key=lambda n: (n.tick, n.lane))
    return out


def compare_drum_charts(off: DrumChart, gen: DrumChart) -> dict:
    """F1/precision/recall por (tick, lane, is_cymbal). Compara nota-a-nota."""
    def key(n): return (n.tick, n.lane, n.is_cymbal)
    off_k = {key(n) for n in off.notes}
    gen_k = {key(n) for n in gen.notes}
    inter = off_k & gen_k
    off_n, gen_n, in_n = len(off_k), len(gen_k), len(inter)
    rec = in_n / max(off_n, 1)
    prec = in_n / max(gen_n, 1)
    f1 = 2 * rec * prec / max(rec + prec, 1e-9)
    # Mesma análise ignorando is_cymbal (lane-only match)
    off_kt = {(n.tick, n.lane) for n in off.notes}
    gen_kt = {(n.tick, n.lane) for n in gen.notes}
    inter_lane = off_kt & gen_kt
    rec_lane = len(inter_lane) / max(len(off_kt), 1)
    prec_lane = len(inter_lane) / max(len(gen_kt), 1)
    f1_lane = 2 * rec_lane * prec_lane / max(rec_lane + prec_lane, 1e-9)
    return dict(
        official=off_n, generated=gen_n,
        f1_strict=round(f1, 3), f1_lane_only=round(f1_lane, 3),
        precision=round(prec, 3), recall=round(rec, 3),
    )


if __name__ == "__main__":
    import glob, mido
    base = "/Users/gabrielcarvalho/Downloads/system"
    print(f"{'Música':12s} {'diff':6s}  {'F1strict':>8s} {'F1lane':>7s} {'prec':>5s} {'rec':>5s}  {'off→gen'}")
    avg = {"Easy": [], "Medium": [], "Hard": []}
    for f in sorted(glob.glob(f"{base}/System*")):
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        ch = parse_drums(mid)
        for diff in ("Hard", "Medium", "Easy"):
            gen = reduce_drums(ch["Expert"], diff)
            r = compare_drum_charts(ch[diff], gen)
            avg[diff].append(r["f1_strict"])
            print(f"{name:12s} {diff:6s}  {r['f1_strict']:>8.2f} {r['f1_lane_only']:>7.2f} "
                  f"{r['precision']:>5.2f} {r['recall']:>5.2f}  {r['official']}→{r['generated']}")
    print("\nF1 médio (strict, considerando cymbal vs tom):")
    for d, vs in avg.items():
        print(f"  {d}: {sum(vs)/len(vs):.3f}  (range {min(vs):.2f}-{max(vs):.2f})")

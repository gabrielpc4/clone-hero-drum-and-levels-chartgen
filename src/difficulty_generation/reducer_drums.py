"""
Gerador de chart drums Easy/Medium/Hard a partir do Expert (PART DRUMS).

Implementa as regras D-R1 a D-R12 documentadas em §14 do HANDOFF.md.

Pipeline:
  1. Para cada nota Expert (kick / snare / Y / B / G, com is_cymbal):
     - Decidir se mantém esse tick na dificuldade alvo
     - Aplicar conversão de lane (D-R1, D-R1.1, D-R9, D-R11)
     - Aplicar regra D-R3 (Easy sem bumbo; Medium: kick paired)
  2. 2x kick (pitch 95): drop sempre (D-R7)
  3. Markers 110/111/112: preservar mas só consultados em Hard/Expert
  4. Drum fills 120-124: preservar
"""
from __future__ import annotations
import os, sys
from collections import defaultdict, Counter
from typing import Callable, Dict, List, Optional, Set, Tuple
sys.path.insert(0, os.path.dirname(__file__))
from parse_drums import (parse_drums, DrumNote, DrumChart, DIFF_BASE_DRUMS,
                         LANE_NAMES, LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN)


# Densidade-alvo por lane e dificuldade — calibrada via regressão sobre as 6 músicas SOAD.
# Snare propositalmente alta (1.0 em Hard) — quem corta colcheias rápidas é o
# filter_fast_clusters; o filtro principal não deve dropar snare por proporção.
TOM_RATIOS = {
    "Easy":   {LANE_KICK: 0.10, LANE_SNARE: 0.85, LANE_YELLOW: 0.38,
               LANE_BLUE: 0.74, LANE_GREEN: 0.71},
    "Medium": {LANE_KICK: 0.30, LANE_SNARE: 0.95, LANE_YELLOW: 0.76,
               LANE_BLUE: 0.72, LANE_GREEN: 0.83},
    "Hard":   {LANE_KICK: 0.62, LANE_SNARE: 1.00, LANE_YELLOW: 0.77,
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


def _expert_by_tick_excluding_2x(expert: DrumChart) -> Dict[int, List[DrumNote]]:
    m: Dict[int, List[DrumNote]] = defaultdict(list)
    for n in expert.notes:
        if n.is_2x_kick:
            continue
        m[n.tick].append(n)
    return m


def _is_tom(n: DrumNote) -> bool:
    return n.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN) and not n.is_cymbal


def _expert_group_has_snare_or_tom(group: List[DrumNote]) -> bool:
    """Snare ou tom (pad Y/B/G) no mesmo tick — o kick nesses níveis nunca acompanha."""
    if any(m.lane == LANE_SNARE for m in group):
        return True
    if any(_is_tom(m) for m in group):
        return True
    return False


def _expert_group_has_green_cym_and_kick(group: List[DrumNote]) -> bool:
    """No Expert: bumbo + crash (verde) no mesmo tick (bumbo+crash, foot+crash)."""
    if not any(m.lane == LANE_KICK and not m.is_2x_kick for m in group):
        return False
    if not any(m.lane == LANE_GREEN and m.is_cymbal for m in group):
        return False
    return True


def _medium_foot_protection_ticks_from_expert(
    expert_by_tick: Dict[int, List[DrumNote]],
) -> Set[int]:
    """
    Ticks onde o Expert teria padrão bumbo+crash (e Medium pode omitir o bumbo):
    ainda se usam para isentar o crash (verde) no 1/16 e no 1/4 de prato.
    """
    out: Set[int] = set()
    for t, grp in expert_by_tick.items():
        if not _expert_group_has_green_cym_and_kick(grp):
            continue
        if _expert_group_has_snare_or_tom(grp):
            continue
        out.add(t)
    return out


def _medium_tick_allows_kick(
    tick: int,
    tpb: int,
    time_sigs: List[Tuple[int, int, int]],
    expert_by_tick: Dict[int, List[DrumNote]],
) -> bool:
    """Medium: bumbo só no 1.º tempo; não há bumbo no padrão Expert crash+foot (fora do 1.º, não se recupera bumbo)."""
    grp = expert_by_tick.get(tick, [])
    if _expert_group_has_snare_or_tom(grp):
        return False
    return _is_kick_on_downbeat_in_bar(tick, tpb, time_sigs)


def _active_time_signature_at(
    tick: int, time_sigs: List[Tuple[int, int, int]]
) -> Tuple[int, int, int]:
    """
    (sig_start_tick, numerator, denominator) da assinatura ativa em `tick`
    (última com sig_start <= tick; se vazio, 4/4 a partir de 0).
    """
    if not time_sigs:
        return (0, 4, 4)
    best: Tuple[int, int, int] = (0, 4, 4)
    for sig_start, num, den in sorted(time_sigs, key=lambda x: x[0]):
        if sig_start <= tick:
            best = (sig_start, num, den)
        else:
            break
    return best


def _measure_len_ticks(numerator: int, denominator: int, tpb: int) -> int:
    if denominator <= 0:
        return 4 * tpb
    return max(1, int(tpb * numerator * 4 / denominator))


def _is_kick_on_quarter_beat_in_bar(
    tick: int, tpb: int, time_sigs: List[Tuple[int, int, int]]
) -> bool:
    """
    Kick alinhado a um tempo de semínima dentro do compasso (tempos 1..N
    consoante o numerador/TS), não só ao 1.º. Equivale a: posição no compasso
    a partir de `time_sigs` tem offset múltiplo de `tpb` (1 semínima).
    """
    sig_start, num, den = _active_time_signature_at(tick, time_sigs)
    mlen = _measure_len_ticks(num, den, tpb)
    pos_in_bar = (tick - sig_start) % mlen
    return (pos_in_bar % tpb) == 0


def _is_kick_on_downbeat_in_bar(
    tick: int, tpb: int, time_sigs: List[Tuple[int, int, int]]
) -> bool:
    """
    1.º tempo / nota mais forte do compasso (início de compasso no TS do MIDI).
    """
    sig_start, num, den = _active_time_signature_at(tick, time_sigs)
    mlen = _measure_len_ticks(num, den, tpb)
    return (tick - sig_start) % mlen == 0


def _kicks_from_expert_with_tick_rule(
    ex_notes: List[DrumNote],
    expert_by_tick: Dict[int, List[DrumNote]],
    time_sigs: List[Tuple[int, int, int]],
    tpb: int,
    tick_allows_kick: Callable[[int], bool],
) -> List[DrumNote]:
    out: List[DrumNote] = []
    for tick in sorted({n.tick for n in ex_notes if n.lane == LANE_KICK}):
        if not tick_allows_kick(tick):
            continue
        grp = expert_by_tick.get(tick, [])
        if _expert_group_has_snare_or_tom(grp):
            continue
        out.append(
            DrumNote(
                tick=tick,
                lane=LANE_KICK,
                is_cymbal=False,
                velocity=_kick_velocity_for_tick(expert_by_tick, tick),
            )
        )
    return out


def _kick_velocity_for_tick(
    expert_by_tick: Dict[int, List[DrumNote]], tick: int
) -> int:
    for n in expert_by_tick.get(tick, []):
        if n.lane == LANE_KICK and not n.is_2x_kick:
            return n.velocity
    return 100


def _drums_chart_from_expert_base(
    expert: DrumChart, difficulty: str, notes: List[DrumNote]
) -> DrumChart:
    return DrumChart(
        difficulty=difficulty,
        ticks_per_beat=expert.ticks_per_beat,
        notes=notes,
        overdrive=list(expert.overdrive),
        drum_fills=list(expert.drum_fills),
        cymbal_flags=dict(expert.cymbal_flags),
        time_signatures=list(expert.time_signatures),
    )


def _reduce_drums_expert_to_hard(expert: DrumChart) -> DrumChart:
    """
    Hard a partir do Expert:
    - Mantém todas as notas não-kick do Expert (2x excluído) — incluindo todos os pratos.
    - Kicks: as mesmas regras de kick do Medium, descritas em
      _reduce_drums_expert_to_medium, mas com grelha de **semínima** (1..N
      tempos no compasso) — i.e. a antiga regra de kick do Medium.
    """
    tpb = expert.ticks_per_beat
    ex_notes = [n for n in expert.notes if not n.is_2x_kick]
    expert_by_tick = _expert_by_tick_excluding_2x(expert)
    time_sigs = list(expert.time_signatures) if expert.time_signatures else [(0, 4, 4)]
    out: List[DrumNote] = []
    for n in ex_notes:
        if n.lane == LANE_KICK:
            continue
        out.append(
            DrumNote(
                tick=n.tick,
                lane=n.lane,
                is_cymbal=n.is_cymbal,
                velocity=n.velocity,
            )
        )
    out.extend(
        _kicks_from_expert_with_tick_rule(
            ex_notes,
            expert_by_tick,
            time_sigs,
            tpb,
            lambda t: _is_kick_on_quarter_beat_in_bar(t, tpb, time_sigs),
        )
    )
    out.sort(key=lambda n: (n.tick, n.lane, n.is_cymbal))
    return _drums_chart_from_expert_base(expert, "Hard", out)


def _filter_faster_than_sixteenth(
    notes: List[DrumNote],
    tpb: int,
    expert_by_tick: Optional[Dict[int, List[DrumNote]]] = None,
) -> List[DrumNote]:
    """
    Per voice (lane, is_cymbal): greedy retain by time, drop a note if gap from
    the previous *kept* in that voice is < one 1/16 note.
    Toms in Hard share one voice; here (Medium) Y/B/G toms and cymbals are separate
    voices, matching filter_fast_clusters' Easy/Medium style.
    Não aplica a voz do bumbo nem a do crash (G-cym) nesse *tick* quando a entrada
    já tem bumbo+crash (verde) juntos, para não deixar cair o padrão denso
    a seguir a outro G (crash). No Medium, `expert_by_tick` reaproveita o mesmo
    sítio ainda com crash só (bumbo aqui ou omitido — proteção do crash (verde)).
    """
    if not notes:
        return notes
    sixteenth = max(1, tpb // 4)  # one 1/16 note
    by_tick: Dict[int, List[DrumNote]] = defaultdict(list)
    for n in notes:
        by_tick[n.tick].append(n)
    # Mesmo no Medium denso, não deixar cair bumbo+crash (verde) no mesmo tick
    # só porque outro G (crash) a 1/16; vozes bumbo e crash (G-cym) têm isenção a esse par.
    bumbo_crash_ticks: Set[int] = set()
    for t, grp in by_tick.items():
        if not any(m.lane == LANE_KICK and not m.is_2x_kick for m in grp):
            continue
        if not any(m.lane == LANE_GREEN and m.is_cymbal for m in grp):
            continue
        bumbo_crash_ticks.add(t)
    if expert_by_tick is not None:
        bumbo_crash_ticks |= _medium_foot_protection_ticks_from_expert(
            expert_by_tick
        )

    voices: Dict[str, List[DrumNote]] = defaultdict(list)
    for n in notes:
        if n.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN) and n.is_cymbal:
            voice_id = f"cym{n.lane}"
        else:
            voice_id = f"L{n.lane}"
        voices[voice_id].append(n)

    out: List[DrumNote] = []
    for voice_id, vnotes in voices.items():
        vnotes.sort(key=lambda x: x.tick)
        last_tick: Optional[int] = None
        for n in vnotes:
            dist_ok = last_tick is None or n.tick - last_tick >= sixteenth
            n_is_bumbo = voice_id == f"L{LANE_KICK}"
            n_is_crash = voice_id == f"cym{LANE_GREEN}"
            if dist_ok or (
                n.tick in bumbo_crash_ticks
                and (n_is_bumbo or n_is_crash)
            ):
                out.append(n)
                last_tick = n.tick
    out.sort(key=lambda n: (n.tick, n.lane, n.is_cymbal))
    return out


def _cym_metal_min_quarter_of_bar_ticks(
    tick: int, tpb: int, time_sigs: List[Tuple[int, int, int]]
) -> int:
    """
    1/4 de compasso no TS ativo: distância mínima no Medium entre *qualquer* prato
    (Y=hi-hat, B=ride, G=crash) no mesmo eixo de tempo, em 4/4 = uma semínima em ticks.
    """
    _, num, den = _active_time_signature_at(tick, time_sigs)
    mlen = _measure_len_ticks(num, den, tpb)
    return max(1, mlen // 4)


def _filter_medium_cymbals_min_quarter_of_bar(
    notes: List[DrumNote],
    tpb: int,
    time_sigs: List[Tuple[int, int, int]],
    expert_by_tick: Optional[Dict[int, List[DrumNote]]] = None,
) -> List[DrumNote]:
    """
    Pratos: hi-hat (Y), **ride (B)**, **crash (G)** — Pro Drums, `is_cymbal`, numa voz
    de tempo comum, gap >= 1/4 de compasso (ver `_cym_metal_min_quarter_of_bar_ticks`).

    Se dois fiquem demasiado próximos, dá prioridade a quem cai no mesmo tick
    que a snare (o outro cai; se empata, fica o primeiro no tempo).
    Crash (verde) alinhado a bumbo (na chart ou só no Expert p/ Medium) não ser
    descartado por outro prato recente — padrão bumbo+crash do Expert.
    """
    if not notes:
        return notes
    sgs = time_sigs if time_sigs else [(0, 4, 4)]
    snare_ticks: Set[int] = {n.tick for n in notes if n.lane == LANE_SNARE}
    other: List[DrumNote] = []
    cymbals: List[DrumNote] = []
    for n in notes:
        is_pro_cym = n.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN) and n.is_cymbal
        if is_pro_cym:
            cymbals.append(n)
        else:
            other.append(n)
    if not cymbals:
        return notes
    ticks_foot: Set[int] = {
        n.tick
        for n in other
        if n.lane == LANE_KICK and not n.is_2x_kick
    }
    if expert_by_tick is not None:
        ticks_foot |= _medium_foot_protection_ticks_from_expert(expert_by_tick)

    def _last_kept_is_crash_cym_with_foot(
        t: Optional[int], m: Optional[DrumNote]
    ) -> bool:
        if t is None or m is None:
            return False
        return m.lane == LANE_GREEN and m.is_cymbal and t in ticks_foot

    cymbals.sort(key=lambda n: (n.tick, n.lane))
    kept: List[DrumNote] = []
    last_tick: Optional[int] = None
    last_metal: Optional[DrumNote] = None
    for n in cymbals:
        if last_tick is not None and last_metal is not None:
            g_low = _cym_metal_min_quarter_of_bar_ticks(last_tick, tpb, sgs)
            g_hi = _cym_metal_min_quarter_of_bar_ticks(n.tick, tpb, sgs)
            min_ok = max(g_low, g_hi)
            if n.tick - last_tick < min_ok:
                crash_cym_mesmo_tick_que_bumbo = (
                    n.lane == LANE_GREEN
                    and n.is_cymbal
                    and n.tick in ticks_foot
                )
                if crash_cym_mesmo_tick_que_bumbo:
                    kept.append(n)
                    last_metal = n
                    last_tick = n.tick
                    continue
                last_s = last_tick in snare_ticks
                n_s = n.tick in snare_ticks
                if n_s and not last_s:
                    if not _last_kept_is_crash_cym_with_foot(last_tick, last_metal):
                        kept.pop()
                        kept.append(n)
                        last_metal = n
                        last_tick = n.tick
                continue
        kept.append(n)
        last_metal = n
        last_tick = n.tick
    out = other + kept
    out.sort(key=lambda x: (x.tick, x.lane, x.is_cymbal))
    return out


def _expert_ticks_kick_with_non_kick_midi(
    expert_by_tick: Dict[int, List[DrumNote]]
) -> Set[int]:
    """
    Ticks do Expert com kick (não 2x) + outra voz, sem snare+tom a bloquear
    a linha (como no Medium) — sítios onde bumbo costuma acompanhar mãos.
    """
    s: Set[int] = set()
    for t, grp in expert_by_tick.items():
        if not any(n.lane == LANE_KICK and not n.is_2x_kick for n in grp):
            continue
        if _expert_group_has_snare_or_tom(grp):
            continue
        if not any(
            n.lane != LANE_KICK and not n.is_2x_kick for n in grp
        ):
            continue
        s.add(t)
    return s


def _nudge_solo_kicks_toward_nearest_grouped(
    notes: List[DrumNote], expert_by_tick: Dict[int, List[DrumNote]]
) -> List[DrumNote]:
    """
    Remonta a lista de notas: tick só com bumbo, sem mão, aproxima o bumbo
    do tick com outra nota mais perto, preferindo ticks do Expert com
    kick+outro hit; se não houver, qualquer tick que já tenha mão.
    """
    for _ in range(800):
        by: Dict[int, List[DrumNote]] = defaultdict(list)
        for n in notes:
            by[n.tick].append(n)
        solo: List[int] = []
        for t, g in by.items():
            if not g:
                continue
            if all(n.lane == LANE_KICK for n in g):
                solo.append(t)
        if not solo:
            return notes
        tick_ex_paired = _expert_ticks_kick_with_non_kick_midi(expert_by_tick)
        ticks_com_mao: Set[int] = {
            t
            for t, g in by.items()
            if any(n.lane != LANE_KICK for n in g)
        }
        t0 = min(solo)
        # Expert "paired" só se no Medium ainda houver mão nesse tick — senão
        # mover o bumbo para aí cria de novo tick só bumbo (ou repõe 29952).
        paired_que_ja_tem_mao: Set[int] = tick_ex_paired & ticks_com_mao

        def _nearest(anchor: int, pool: Set[int]) -> Optional[int]:
            cands = [u for u in pool if u != anchor]
            if not cands:
                return None
            return min(cands, key=lambda u: abs(u - anchor))

        u0: Optional[int] = None
        if paired_que_ja_tem_mao:
            u0 = _nearest(t0, paired_que_ja_tem_mao)
        if u0 is None:
            u0 = _nearest(t0, ticks_com_mao)
        if u0 is None:
            return [n for n in notes if not (n.lane == LANE_KICK and n.tick == t0)]
        v_kick = _kick_velocity_for_tick(expert_by_tick, u0)
        sem_k0 = [n for n in notes if not (n.lane == LANE_KICK and n.tick == t0)]
        ja_kick = any(n.lane == LANE_KICK and n.tick == u0 for n in sem_k0)
        if not ja_kick:
            sem_k0.append(
                DrumNote(
                    tick=u0,
                    lane=LANE_KICK,
                    is_cymbal=False,
                    velocity=v_kick,
                )
            )
        notes = sem_k0
        notes.sort(key=lambda n: (n.tick, n.lane, n.is_cymbal))
    return notes


def _reduce_drums_expert_to_medium(expert: DrumChart) -> DrumChart:
    """
    Medium a partir do Expert:
    1) Kick **só no 1.º tempo** do compasso (não bumbo no padrão crash+foot do
       Expert fora disso), com as mesmas exclusões de snare/tom. O Hard
       continua a aceitar semínimas no compasso. Nunca kick com snare ou tom
       (Y/B/G pad) no mesmo tick, ainda que exista prato nesse tick.
    2) Eliminar qualquer voz com intervalo < 1/16 entre notas consecutivas
       (por lane/cym, como em _filter_faster_than_sixteenth).
    3) Pratos (Y=hi-hat, B=ride, G=crash) com is_cymbal: espaçamento >= 1/4 de
       compasso; se ainda forem demasiado perto, preferir o que cai com a
       snare. **Crash (verde) com bumbo nesse tick** fica (não cair o crash
       por hi-hat, ride, etc. a 1/4 de bar).
    4) Bumbo nunca fica sozinho no tick: se sobrar só pedal, reaproxima do
       tick (Expert) com kick+outro hit, senão do tick com mão mais perto.
    """
    tpb = expert.ticks_per_beat
    time_sigs = list(expert.time_signatures) if expert.time_signatures else [(0, 4, 4)]
    ex_notes = [n for n in expert.notes if not n.is_2x_kick]
    expert_by_tick = _expert_by_tick_excluding_2x(expert)
    out: List[DrumNote] = []
    for n in ex_notes:
        if n.lane == LANE_KICK:
            continue
        out.append(
            DrumNote(
                tick=n.tick,
                lane=n.lane,
                is_cymbal=n.is_cymbal,
                velocity=n.velocity,
            )
        )
    out.extend(
        _kicks_from_expert_with_tick_rule(
            ex_notes,
            expert_by_tick,
            time_sigs,
            tpb,
            lambda t: _medium_tick_allows_kick(
                t, tpb, time_sigs, expert_by_tick
            ),
        )
    )
    out.sort(key=lambda n: (n.tick, n.lane, n.is_cymbal))
    out = _filter_faster_than_sixteenth(out, tpb, expert_by_tick)
    out = _filter_medium_cymbals_min_quarter_of_bar(
        out, tpb, time_sigs, expert_by_tick
    )
    out = _nudge_solo_kicks_toward_nearest_grouped(out, expert_by_tick)
    return _drums_chart_from_expert_base(expert, "Medium", out)


def reduce_drums(expert: DrumChart, target_diff: str) -> DrumChart:
    """Pipeline completo de redução de drums."""
    tpb = expert.ticks_per_beat
    if target_diff == "Hard":
        return _reduce_drums_expert_to_hard(expert)
    if target_diff == "Medium":
        return _reduce_drums_expert_to_medium(expert)
    target = TOM_RATIOS[target_diff]
    lane_consol = detect_lane_consolidation(expert)

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

    # ---- Cymbals (Y/B/G) — D-R1, D-R1.1, D-R11 (lane da cor Expert, sem G→B) ----
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
            kept_notes.append(
                DrumNote(
                    tick=n.tick,
                    lane=src_lane,
                    is_cymbal=True,
                    velocity=n.velocity,
                )
            )

    # ---- Kick (D-R3, D-R4) — sem pedal no Easy; E/M: só paired (D-R3) ----
    kick_notes = by_lane_cym.get((LANE_KICK, False), [])
    if kick_notes and target_diff != "Easy":
        paired = [k for k in kick_notes if is_paired_kick(k, expert_by_tick)]
        if target_diff == "Medium":
            n_keep = max(0, round(len(kick_notes) * target[LANE_KICK]))
            chosen = sorted(paired, key=lambda n: -score(n))[:n_keep]
        else:
            n_keep = max(0, round(len(kick_notes) * target[LANE_KICK]))
            ranked = sorted(
                kick_notes,
                key=lambda n: -(
                    score(n)
                    + (20 if is_paired_kick(n, expert_by_tick) else 0)
                ),
            )
            chosen = ranked[:n_keep]
        for n in chosen:
            kept_notes.append(
                DrumNote(
                    tick=n.tick,
                    lane=LANE_KICK,
                    is_cymbal=False,
                    velocity=n.velocity,
                )
            )

    # Sort final
    kept_notes.sort(key=lambda n: (n.tick, n.lane))

    # Filtro anti-16ths-consecutivos em E/M/H (preferência do usuário 2026-04-22):
    # qualquer par de notas mesma-lane com gap ≤ 1/16 nota é considerado "rápido demais"
    # para Easy/Medium/Hard — só Expert tolera 16ths consecutivos.
    if target_diff in ("Easy", "Medium", "Hard"):
        kept_notes = filter_fast_clusters(kept_notes, tpb, target_diff)

    return DrumChart(
        difficulty=target_diff,
        ticks_per_beat=tpb,
        notes=kept_notes,
        overdrive=list(expert.overdrive),
        drum_fills=list(expert.drum_fills),
        cymbal_flags=dict(expert.cymbal_flags),
        time_signatures=list(expert.time_signatures),
    )


def filter_fast_clusters(notes: List[DrumNote], tpb: int, diff: str) -> List[DrumNote]:
    """Bane notas com gap absoluto ≤ 1/16 nota, dentro de cada "voz".
       Voz = grupo de notas que disputam o mesmo limiar de espaçamento.

       Em Hard, **tambores Y/B/G são tratados como UMA SÓ voz** (em vez de uma
       voz por lane), o que permite preservar viradas: o min_gap=1/16 conta
       entre tambores diferentes, não entre cada par de notas da mesma lane.
       Snare, kick e cada cor de prato continuam vozes separadas.

       Em Medium/Easy, cada (lane, is_cymbal) é uma voz separada (mais agressivo).

       Espaçamento mínimo entre notas mantidas (greedy temporal):
         Hard:   1/16 para a voz de tambores (Y/B/G juntos); 1/8 para snare/kick/pratos
         Medium: 1/8 para todos
         Easy:   1/4 (semínima) para todos
    """
    if not notes: return notes
    sixteenth = tpb // 4  # 120 ticks @ tpb=480

    # Define vozes (agora que is_cymbal já é interpretado corretamente,
    # não precisamos mais da heurística de ostinato)
    voices: Dict[str, List[DrumNote]] = defaultdict(list)
    for n in notes:
        is_tom = n.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN) and not n.is_cymbal
        if diff == "Hard" and is_tom:
            voice_id = "TOMS_HARD"
        elif n.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN) and n.is_cymbal:
            voice_id = f"cym{n.lane}"
        else:
            voice_id = f"L{n.lane}"
        voices[voice_id].append(n)

    out: List[DrumNote] = []
    for voice_id, voice_notes in voices.items():
        is_toms_hard = voice_id == "TOMS_HARD"
        is_kick_hard = diff == "Hard" and voice_id == f"L{LANE_KICK}"
        is_snare_hard = diff == "Hard" and voice_id == f"L{LANE_SNARE}"
        if diff == "Easy":
            min_gap = tpb            # 1/4
        elif diff == "Medium":
            min_gap = tpb // 2       # 1/8
        else:  # Hard
            if is_toms_hard or is_kick_hard or is_snare_hard:
                min_gap = tpb // 4   # toms / kick / snare → 1/16
            else:
                min_gap = tpb // 2   # pratos → 1/8

        # Greedy temporal direto: percorre as notas em ordem e mantém só as
        # que estão a ≥ min_gap da última mantida. Garante a regra mesmo para
        # gaps off-grid (ex.: 180 ticks entre 1/16 e 1/8).
        voice_notes.sort(key=lambda n: n.tick)
        last_tick = None
        for n in voice_notes:
            if last_tick is None or n.tick - last_tick >= min_gap:
                out.append(n); last_tick = n.tick
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
    base = "songs/harmonix"
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

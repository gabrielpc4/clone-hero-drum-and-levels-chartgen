"""
Alinhamento Expert↔Hard↔Medium↔Easy de PART GUITAR para todas as 6 músicas.

Para cada tick onde o Expert tem nota, registra (E, M, H, X) — cada um sendo
None ou um Note. Depois cruzamos para responder:

  Q1. Toda nota em E/M/H está em algum tick do Expert?
  Q2. Densidade real (nota mantida vs descartada) por beat-position e por seção.
  Q3. Quando o Expert é acorde, qual fret sobrevive na redução?
  Q4. Sustains: qual a distribuição de duração e o limiar de preservação?
"""
from __future__ import annotations
import os, glob, json
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple
import mido

import sys
sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part, Note, Chart, FRET_NAMES, DIFF_BASE


def build_alignment(charts: Dict[str, Chart]):
    """Devolve list aligned: cada item = {tick, E, M, H, X} para todo tick presente em qualquer dificuldade."""
    by_tick: Dict[int, Dict[str, Optional[Note]]] = defaultdict(lambda: {"Easy": None, "Medium": None, "Hard": None, "Expert": None})
    for diff, c in charts.items():
        for n in c.notes:
            by_tick[n.tick][diff] = n
    return [dict(tick=t, **by_tick[t]) for t in sorted(by_tick)]


def temporal_subset_check(charts: Dict[str, Chart]):
    """Q1: cada tick em E/M/H aparece em Expert?"""
    expert_ticks = {n.tick for n in charts["Expert"].notes}
    out = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_ticks = {n.tick for n in charts[diff].notes}
        only_in_diff = diff_ticks - expert_ticks
        out[diff] = dict(
            total=len(diff_ticks),
            in_expert=len(diff_ticks & expert_ticks),
            only_in_diff=len(only_in_diff),
            example_orphans=sorted(only_in_diff)[:5],
        )
    return out


def chord_reduction_stats(charts: Dict[str, Chart]):
    """Q3: quando Expert é acorde de N notas, o que aparece nas reduções?"""
    expert_by_tick = {n.tick: n for n in charts["Expert"].notes}
    stats: Dict[str, Dict] = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_by_tick = {n.tick: n for n in charts[diff].notes}
        # Para cada tick onde Expert tem >= 2 notas E a redução também tem nota
        kept_count = Counter()        # qual posição do acorde foi mantida (lowest=0, mid=1, highest=last)
        kept_fret = Counter()         # quais frets concretos sobreviveram
        size_change = Counter()       # (size_expert, size_reduced)
        # Para acordes onde a redução também é acorde
        intersection_pattern = Counter()
        for tick, en in expert_by_tick.items():
            if len(en.frets) < 2:
                continue
            rn = diff_by_tick.get(tick)
            if rn is None:
                size_change[(len(en.frets), 0)] += 1
                continue
            size_change[(len(en.frets), len(rn.frets))] += 1
            # Quando sobra exatamente uma nota: posição relativa
            if len(rn.frets) == 1:
                rfret = rn.frets[0]
                if rfret in en.frets:
                    pos = en.frets.index(rfret)
                    if pos == 0:
                        kept_count["lowest"] += 1
                    elif pos == len(en.frets) - 1:
                        kept_count["highest"] += 1
                    else:
                        kept_count["middle"] += 1
                    kept_fret[FRET_NAMES[rfret]] += 1
                else:
                    kept_count["transposed_outside"] += 1
                    kept_fret[FRET_NAMES[rfret] + "*"] += 1
            elif len(rn.frets) >= 2:
                # tipo de interseção
                inter = set(en.frets) & set(rn.frets)
                pattern = f"E{len(en.frets)}→R{len(rn.frets)} inter={len(inter)}"
                intersection_pattern[pattern] += 1
        stats[diff] = dict(
            size_change=dict(size_change),
            kept_position=dict(kept_count),
            kept_fret=dict(kept_fret),
            intersection_pattern=dict(intersection_pattern),
        )
    return stats


def fret_transposition_stats(charts: Dict[str, Chart]):
    """Q3b: para notas SINGLE no Expert que sobreviveram (também single), qual a matriz Expert→reduced?"""
    expert_by_tick = {n.tick: n for n in charts["Expert"].notes}
    out: Dict[str, Dict] = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_by_tick = {n.tick: n for n in charts[diff].notes}
        matrix = Counter()  # (expert_fret, reduced_fret)
        for tick, en in expert_by_tick.items():
            if len(en.frets) != 1:
                continue
            rn = diff_by_tick.get(tick)
            if rn is None or len(rn.frets) != 1:
                continue
            matrix[(FRET_NAMES[en.frets[0]], FRET_NAMES[rn.frets[0]])] += 1
        out[diff] = dict(matrix)
    return out


def density_by_beat_position(charts: Dict[str, Chart]):
    """Q2: dividindo o tempo em sub-beat (16ths = TPB/4), qual a chance de uma nota Expert sobreviver
       em cada offset dentro do beat?"""
    tpb = charts["Expert"].ticks_per_beat
    sub = tpb // 4  # 16th note
    expert_by_tick = {n.tick: n for n in charts["Expert"].notes}
    out: Dict[str, Dict] = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_ticks = {n.tick for n in charts[diff].notes}
        bucket_total = Counter()
        bucket_kept = Counter()
        for tick in expert_by_tick:
            offset = (tick % tpb) // sub  # 0=on-beat, 1=&, 2=mid, 3=ah... aproximado
            bucket_total[offset] += 1
            if tick in diff_ticks:
                bucket_kept[offset] += 1
        out[diff] = {f"sub{i}": (bucket_kept[i], bucket_total[i],
                                  round(bucket_kept[i]/bucket_total[i], 3) if bucket_total[i] else 0)
                     for i in range(4)}
    return out


def sustain_threshold_stats(charts: Dict[str, Chart]):
    """Q4: distribuição de durações (em ticks) das notas Expert, separadas por:
       - foram mantidas com sustain (dur reduced ~ dur expert)
       - foram mantidas como hit (dur reduced << dur expert)
       - foram dropadas
    """
    tpb = charts["Expert"].ticks_per_beat
    expert_by_tick = {n.tick: n for n in charts["Expert"].notes}
    buckets = ["<1/16", "1/16-1/8", "1/8-1/4", "1/4-1/2", "1/2-1", "1-2beats", ">2beats"]
    def bucket(d):
        if d < tpb//4: return "<1/16"
        if d < tpb//2: return "1/16-1/8"
        if d < tpb: return "1/8-1/4"
        if d < 2*tpb: return "1/4-1/2"
        if d < 4*tpb: return "1/2-1"
        if d < 8*tpb: return "1-2beats"
        return ">2beats"
    out: Dict[str, Dict] = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_by_tick = {n.tick: n for n in charts[diff].notes}
        per_bucket = {b: dict(total=0, dropped=0, kept_hit=0, kept_sustain=0) for b in buckets}
        for tick, en in expert_by_tick.items():
            b = bucket(en.duration)
            per_bucket[b]["total"] += 1
            rn = diff_by_tick.get(tick)
            if rn is None:
                per_bucket[b]["dropped"] += 1
            elif rn.duration < tpb//4:  # virou hit
                per_bucket[b]["kept_hit"] += 1
            else:
                per_bucket[b]["kept_sustain"] += 1
        out[diff] = per_bucket
    return out


def run():
    base = "songs/harmonix"
    songs = sorted(glob.glob(f"{base}/System*"))
    all_results = {}
    for f in songs:
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        charts = parse_part(mid, "PART GUITAR")
        all_results[name] = dict(
            q1_subset=temporal_subset_check(charts),
            q2_density_by_beat=density_by_beat_position(charts),
            q3_chord_reduction=chord_reduction_stats(charts),
            q3b_single_transposition=fret_transposition_stats(charts),
            q4_sustain=sustain_threshold_stats(charts),
        )
    # JSON-safe: tuple keys → "a→b" strings
    def jsonify(o):
        if isinstance(o, dict):
            return {("→".join(map(str, k)) if isinstance(k, tuple) else str(k)): jsonify(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [jsonify(x) for x in o]
        return o
    out_path = os.path.join(base, "src", "alignment_report.json")
    with open(out_path, "w") as fh:
        json.dump(jsonify(all_results), fh, indent=2, default=str)
    print(f"Saved {out_path}")
    return all_results


if __name__ == "__main__":
    res = run()
    # Resumo direto no terminal
    for song, r in res.items():
        print(f"\n========== {song} ==========")
        print("[Q1 subconjunto temporal]")
        for d, v in r["q1_subset"].items():
            print(f"  {d}: total={v['total']}, em_expert={v['in_expert']}, órfãs={v['only_in_diff']}")
        print("[Q2 densidade por offset 16th do beat — (kept, total, ratio)]")
        for d, v in r["q2_density_by_beat"].items():
            print(f"  {d}: {v}")
        print("[Q3 redução de acorde — size_change (E_size, R_size)]")
        for d, v in r["q3_chord_reduction"].items():
            print(f"  {d}: size_change={v['size_change']}")
            print(f"          kept_position={v['kept_position']}")
            print(f"          intersection={v['intersection_pattern']}")
        print("[Q4 sustain por duração — bucket: total/dropped/kept_hit/kept_sustain]")
        for d, v in r["q4_sustain"].items():
            print(f"  {d}:")
            for b, vals in v.items():
                if vals["total"]:
                    print(f"    {b:>10s}: {vals}")

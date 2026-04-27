"""
Alinhamento drums Expert↔reduções para validar regras D-R1 a D-R7.

Q1. As reduções são subconjuntos temporais do Expert por LANE? (Cada nota Easy
    em lane L cai num tick onde Expert também tem nota em lane L?)
Q2. Cymbal Expert sobrevive como cymbal, vira tom da mesma cor, ou some em Hard?
Q3. Kick decimation: que kicks Expert sobrevivem em E/M? (sub-beat, downbeat,
    paired com snare/tom?)
Q4. 2x kick em BYOB: como é reduzido em Hard/Medium/Easy?
Q5. Snare retention: confirmar D-R2 (sagrada).
Q6. Cymbal aggregation: quando Hard mantém cymbal vs converte para tom?
"""
from __future__ import annotations
import os, sys, glob
from collections import Counter, defaultdict
import mido

sys.path.insert(0, os.path.dirname(__file__))
from parse_drums import (parse_drums, DrumNote, DrumChart, DIFF_BASE_DRUMS,
                         LANE_NAMES, LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN)


def temporal_subset_per_lane(charts):
    """Q1: lane-aware subset check.
       Para cada (diff, lane), conta quantas notas estão em ticks que o Expert
       também tem nota *na mesma lane*."""
    out = {}
    expert_by_lane = defaultdict(set)
    for n in charts["Expert"].notes:
        expert_by_lane[n.lane].add(n.tick)
    for diff in ("Easy", "Medium", "Hard"):
        out[diff] = {}
        for lane in range(5):
            diff_ticks = {n.tick for n in charts[diff].notes if n.lane == lane}
            in_expert = diff_ticks & expert_by_lane[lane]
            out[diff][LANE_NAMES[lane]] = dict(
                total=len(diff_ticks),
                in_expert=len(in_expert),
                only_in_diff=len(diff_ticks - expert_by_lane[lane]),
            )
    return out


def cymbal_conversion_check(charts):
    """Q2: para cada cymbal Expert (Y-cym, B-cym, G-cym), o que acontece em Hard/Medium/Easy?"""
    expert_cyms = [n for n in charts["Expert"].notes
                   if n.is_cymbal and n.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN)]
    out = {}
    for diff in ("Hard", "Medium", "Easy"):
        diff_by_lane_tick = {(n.lane, n.tick): n for n in charts[diff].notes}
        per_lane = defaultdict(lambda: Counter())
        for en in expert_cyms:
            rn = diff_by_lane_tick.get((en.lane, en.tick))
            if rn is None:
                outcome = "dropped_or_moved_lane"
            elif rn.is_cymbal:
                outcome = "kept_as_cymbal"
            else:
                outcome = "converted_to_tom"
            per_lane[LANE_NAMES[en.lane]][outcome] += 1
        out[diff] = {k: dict(v) for k, v in per_lane.items()}
    return out


def kick_decimation(charts):
    """Q3: dos kicks Expert, qual fração sobrevive em E/M/H? Distribuição por sub-beat."""
    tpb = charts["Expert"].ticks_per_beat
    expert_kicks = sorted(n.tick for n in charts["Expert"].notes if n.lane == LANE_KICK)
    out = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_ticks = {n.tick for n in charts[diff].notes if n.lane == LANE_KICK}
        kept_subs = Counter()
        dropped_subs = Counter()
        for tk in expert_kicks:
            sub = (tk % tpb) // (tpb // 4)
            beat_in_bar = (tk // tpb) % 4
            if tk in diff_ticks:
                kept_subs[(beat_in_bar, sub)] += 1
            else:
                dropped_subs[(beat_in_bar, sub)] += 1
        # Also count: kick paired with another hit (snare or tom) at the same tick
        expert_other_at_tick = defaultdict(set)
        for n in charts["Expert"].notes:
            if n.lane != LANE_KICK:
                expert_other_at_tick[n.tick].add(n.lane)
        kept_with_pair = 0; kept_solo = 0
        dropped_with_pair = 0; dropped_solo = 0
        for tk in expert_kicks:
            paired = bool(expert_other_at_tick[tk])
            if tk in diff_ticks:
                if paired: kept_with_pair += 1
                else: kept_solo += 1
            else:
                if paired: dropped_with_pair += 1
                else: dropped_solo += 1
        out[diff] = dict(
            total_expert_kicks=len(expert_kicks),
            kept=len(diff_ticks),
            ratio=round(len(diff_ticks)/max(len(expert_kicks),1), 3),
            paired_kept=kept_with_pair, paired_dropped=dropped_with_pair,
            solo_kept=kept_solo, solo_dropped=dropped_solo,
            kept_by_beatXsub_top10={f"b{b}.s{s}": c for (b, s), c in kept_subs.most_common(10)},
        )
    return out


def kick_2x_reduction(charts, mid):
    """Q4: 2x kick (pitch 95) is Expert only. How do E/M/H handle these ticks?
       (Checks if the Expert additional kick becomes simple kick or disappears.)"""
    track = next(t for t in mid.tracks if t.name == "PART DRUMS")
    abs_t = 0
    kick_2x_ticks = []
    for msg in track:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.note == 95:
            kick_2x_ticks.append(abs_t)
    out = dict(total_2x_kicks=len(kick_2x_ticks))
    if not kick_2x_ticks:
        return out
    # For each 2x kick, check if that position also has kick in Hard/Medium/Easy
    for diff in ("Easy", "Medium", "Hard"):
        diff_kick_ticks = {n.tick for n in charts[diff].notes if n.lane == LANE_KICK}
        out[f"{diff}_kept"] = sum(1 for t in kick_2x_ticks if t in diff_kick_ticks)
    return out


def snare_retention(charts):
    """Q5: confirmar D-R2."""
    out = {}
    expert_snare = {n.tick for n in charts["Expert"].notes if n.lane == LANE_SNARE}
    for diff in ("Easy", "Medium", "Hard"):
        diff_snare = {n.tick for n in charts[diff].notes if n.lane == LANE_SNARE}
        kept = expert_snare & diff_snare
        out[diff] = dict(
            expert=len(expert_snare),
            diff=len(diff_snare),
            intersection=len(kept),
            recall=round(len(kept)/max(len(expert_snare),1), 3),
        )
    return out


def main():
    base = "songs/harmonix"
    for f in sorted(glob.glob(f"{base}/System*")):
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        ch = parse_drums(mid)
        print(f"\n========== {name} ==========")

        print("[Q1] Subset temporal por lane (total / em-Expert / só-na-redução):")
        sub = temporal_subset_per_lane(ch)
        for diff in ("Easy","Medium","Hard"):
            for lane in LANE_NAMES:
                v = sub[diff][lane]
                if v["total"] == 0: continue
                marker = " ⚠" if v["only_in_diff"] > 0 else ""
                print(f"  {diff} {lane:7s}: {v['total']:4d} / {v['in_expert']:4d} / {v['only_in_diff']:4d}{marker}")

        print("\n[Q2] Cymbal Expert: kept_cym / convertido_tom / dropado:")
        cyc = cymbal_conversion_check(ch)
        for diff in ("Hard","Medium","Easy"):
            for lane, outcomes in cyc[diff].items():
                print(f"  {diff} {lane}: {dict(outcomes)}")

        print("\n[Q3] Kick decimation:")
        kd = kick_decimation(ch)
        for diff, v in kd.items():
            print(f"  {diff}: total={v['total_expert_kicks']} kept={v['kept']} ({v['ratio']*100:.1f}%) "
                  f"paired_kept/dropped={v['paired_kept']}/{v['paired_dropped']} "
                  f"solo_kept/dropped={v['solo_kept']}/{v['solo_dropped']}")

        print("\n[Q4] 2x kick reduction:")
        kx = kick_2x_reduction(ch, mid)
        print(f"  {kx}")

        print("\n[Q5] Snare retention (confirmar D-R2):")
        sr = snare_retention(ch)
        for diff, v in sr.items():
            print(f"  {diff}: expert={v['expert']} diff={v['diff']} kept={v['intersection']} recall={v['recall']}")


if __name__ == "__main__":
    main()

"""
Final investigations of Stage 2:

E) HOPO/Tap propagation:
   - Force-HOPO ON/OFF (pitches +5/+6 relative to base) — appear in all 4 difficulties?
   - Tap (pitch 104) — preserved in reductions?

F) Anchor-per-section:
   - Partition the song into windows (4 beats / 1 measure?) and see, within each window,
     what the "center of gravity" of the fret is in Expert vs reductions.
   - Hypothesis: Harmonix keeps the center/region of the neck, just softening the spread.

G) Drop vs single in Easy/Medium:
   - For Expert chords that were not preserved, what decides between becoming single or disappearing?
   - Candidate variables: position in beat, duration, neighborhood (isolated or in run),
     local density, within SP, in transition between different chords.

H) Sustain mode (R11):
   - Compute a per-song metric that separates Aerials/Chop Suey/Hypnotize/BYOB (preserves)
     from Spiders/Toxicity (converts).
"""
from __future__ import annotations
import os, glob, mido
from collections import Counter, defaultdict
from statistics import mean, median
import sys; sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part, FRET_NAMES


# ---------- E ----------
def hopo_tap_propagation(charts, mid):
    """Conta marcadores force-HOPO e taps por dificuldade."""
    out = {}
    # Tap é marcador de faixa inteira (pitch 104), não tem dificuldade
    track = next(t for t in mid.tracks if t.name == "PART GUITAR")
    abs_t = 0
    tap_events = 0
    for msg in track:
        abs_t += msg.time
        if msg.type=="note_on" and msg.velocity>0 and msg.note==104:
            tap_events += 1
    for diff, c in charts.items():
        on = sum(1 for n in c.notes if n.forced_hopo == +1)
        off = sum(1 for n in c.notes if n.forced_hopo == -1)
        out[diff] = dict(force_hopo_on=on, force_hopo_off=off)
    out["track_tap_markers_(pitch104)"] = tap_events
    return out


# ---------- F ----------
def section_anchor(charts, window_beats=4):
    """Para cada janela, calcula o fret médio no Expert e nas reduções; mede se o centro se mantém."""
    tpb = charts["Expert"].ticks_per_beat
    win_size = tpb * window_beats
    expert = charts["Expert"].notes
    if not expert:
        return {}
    end_tick = max(n.tick for n in expert)
    n_windows = end_tick // win_size + 1
    out = {}
    for diff, c in charts.items():
        windows_x = []
        windows_d = []
        for w in range(n_windows):
            t0 = w * win_size; t1 = t0 + win_size
            x_frets = [f for n in expert if t0 <= n.tick < t1 for f in n.frets]
            d_frets = [f for n in c.notes if t0 <= n.tick < t1 for f in n.frets]
            if x_frets and d_frets:
                windows_x.append(mean(x_frets))
                windows_d.append(mean(d_frets))
        # Diferenças
        diffs = [d - x for x, d in zip(windows_x, windows_d)]
        out[diff] = dict(
            n_windows_compared=len(diffs),
            mean_shift_left=round(-mean(diffs), 3) if diffs else 0,  # positivo = redução está mais à esquerda
            median_shift_left=round(-median(diffs), 3) if diffs else 0,
            max_shift_left=round(-min(diffs), 3) if diffs else 0,
        )
    return out


# ---------- G ----------
def drop_vs_single_predictors(charts):
    """Para cada acorde Expert, registra: foi dropado (R_size=0) ou virou single (R_size=1)?
       Mede correlação com beat-position, duração, isolamento."""
    tpb = charts["Expert"].ticks_per_beat
    expert = sorted(charts["Expert"].notes, key=lambda n: n.tick)
    expert_ticks = [n.tick for n in expert]
    out = {}
    for diff in ("Easy", "Medium"):  # Hard quase nunca dropa só pra single
        diff_by_tick = {n.tick: n for n in charts[diff].notes}
        rows_drop = Counter()
        rows_single = Counter()
        for i, en in enumerate(expert):
            if len(en.frets) < 2: continue
            rn = diff_by_tick.get(en.tick)
            if rn is None:
                outcome = "drop"
            elif len(rn.frets) == 1:
                outcome = "single"
            else:
                continue  # acorde preservado, não nos interessa aqui

            # Features
            sub = (en.tick % tpb) // (tpb//4)  # 0=on-beat, 1,2,3
            dur_bucket = "<1/16" if en.duration < tpb//4 else "1/16-1/8" if en.duration < tpb//2 else "1/8-1/4" if en.duration < tpb else ">=1/4"
            # Isolamento: gap até nota Expert anterior e seguinte
            gap_prev = en.tick - expert_ticks[i-1] if i > 0 else 99999
            gap_next = expert_ticks[i+1] - en.tick if i+1 < len(expert_ticks) else 99999
            isolated = "isolated(>1/2beat both sides)" if gap_prev > tpb//2 and gap_next > tpb//2 else "in_run"

            key = (sub, dur_bucket, isolated)
            (rows_drop if outcome == "drop" else rows_single)[key] += 1

        # Para cada combinação de features, taxa de single (vs drop)
        all_keys = set(rows_drop) | set(rows_single)
        per_key = {}
        for k in sorted(all_keys, key=lambda x: -(rows_drop[x]+rows_single[x])):
            tot = rows_drop[k] + rows_single[k]
            per_key[str(k)] = dict(total=tot, single=rows_single[k], drop=rows_drop[k],
                                   single_rate=round(rows_single[k]/tot, 2))
        out[diff] = dict(rows=per_key)
    return out


# ---------- H ----------
def sustain_mode(charts):
    """Métrica para classificar 'modo de sustain' da música:
       fração de notas Expert com duração >= 1/2 beat (sustain visível)."""
    tpb = charts["Expert"].ticks_per_beat
    notes = charts["Expert"].notes
    long_count = sum(1 for n in notes if n.duration >= tpb//2)
    return dict(
        total_expert_notes=len(notes),
        long_ge_half_beat=long_count,
        ratio_long=round(long_count/len(notes), 3) if notes else 0,
        median_duration=median(n.duration for n in notes) if notes else 0,
        mean_duration=round(mean(n.duration for n in notes), 1) if notes else 0,
    )


def main():
    base = "songs/harmonix"
    songs = sorted(glob.glob(f"{base}/System*"))
    for f in songs:
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        charts = parse_part(mid, "PART GUITAR")
        print(f"\n========== {name} ==========")

        # E
        ht = hopo_tap_propagation(charts, mid)
        print(f"[E] HOPO/Tap: {ht}")

        # F
        sa = section_anchor(charts, window_beats=4)
        print(f"[F] Section anchor (deslocamento médio do fret_centroid em direção a G):")
        for d, v in sa.items():
            print(f"    {d}: {v}")

        # G
        dvs = drop_vs_single_predictors(charts)
        print(f"[G] Drop vs single — top 10 buckets por dificuldade:")
        for d, v in dvs.items():
            print(f"    {d}:")
            for k, vals in list(v["rows"].items())[:10]:
                print(f"      {k}  -> {vals}")

        # H
        sm = sustain_mode(charts)
        print(f"[H] Sustain-mode metrics: {sm}")


if __name__ == "__main__":
    main()

"""
Validação detalhada: gera reduções e mede:
  - precision/recall de ticks
  - fret-set exatamente igual quando ticks coincidem
  - similaridade de fret-centroid (R14)
  - distribuição (E_size, R_size) gerada vs oficial
"""
import os, sys, glob, mido
from collections import Counter
from statistics import mean
sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part, FRET_NAMES
from reducer import reduce_chart, classify_sustain_mode


def compare(official, generated):
    off_by = {n.tick: n for n in official.notes}
    gen_by = {n.tick: n for n in generated.notes}
    off_ticks, gen_ticks = set(off_by), set(gen_by)
    inter = off_ticks & gen_ticks
    fret_exact = sum(1 for t in inter if off_by[t].frets == gen_by[t].frets)
    fret_same_size = sum(1 for t in inter if len(off_by[t].frets) == len(gen_by[t].frets))
    # fret-centroid em janelas de 4 beats
    tpb = official.ticks_per_beat
    win = tpb * 4
    end = max((max(off_ticks), max(gen_ticks))) if off_ticks or gen_ticks else 0
    centroid_diffs = []
    for w in range(end // win + 1):
        t0, t1 = w*win, (w+1)*win
        of = [f for n in official.notes if t0 <= n.tick < t1 for f in n.frets]
        gf = [f for n in generated.notes if t0 <= n.tick < t1 for f in n.frets]
        if of and gf:
            centroid_diffs.append(mean(gf) - mean(of))
    return dict(
        official=len(off_ticks),
        generated=len(gen_ticks),
        intersection=len(inter),
        recall=len(inter)/max(len(off_ticks), 1),
        precision=len(inter)/max(len(gen_ticks), 1),
        f1=2 * (len(inter)/max(len(off_ticks),1)) * (len(inter)/max(len(gen_ticks),1)) /
            max((len(inter)/max(len(off_ticks),1)) + (len(inter)/max(len(gen_ticks),1)), 1e-9),
        fret_exact_in_intersection=fret_exact,
        fret_exact_rate=fret_exact / max(len(inter), 1),
        same_chord_size_rate=fret_same_size / max(len(inter), 1),
        centroid_mean_abs_error=round(mean(abs(d) for d in centroid_diffs), 3) if centroid_diffs else None,
        chord_size_dist_official=dict(Counter(len(n.frets) for n in official.notes)),
        chord_size_dist_generated=dict(Counter(len(n.frets) for n in generated.notes)),
    )


def main():
    base = "songs/harmonix"
    rows = []
    for f in sorted(glob.glob(f"{base}/System*")):
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        official = parse_part(mid, "PART GUITAR")
        mode = classify_sustain_mode(official["Expert"])
        print(f"\n=== {name}  mode={mode} ===")
        for diff in ("Hard", "Medium", "Easy"):
            gen = reduce_chart(official["Expert"], diff)
            r = compare(official[diff], gen)
            rows.append((name, diff, r))
            print(f"  {diff:6s}: prec={r['precision']:.2f}  rec={r['recall']:.2f}  f1={r['f1']:.2f}  "
                  f"fret_exact={r['fret_exact_rate']:.2f}  size_match={r['same_chord_size_rate']:.2f}  "
                  f"cent_err={r['centroid_mean_abs_error']}  "
                  f"sizes_off={r['chord_size_dist_official']} vs gen={r['chord_size_dist_generated']}")
    # Tabela resumo
    print("\n\n##### Resumo F1 por dificuldade #####")
    by_diff = {"Hard": [], "Medium": [], "Easy": []}
    for _, d, r in rows: by_diff[d].append(r["f1"])
    for d, vs in by_diff.items():
        print(f"  {d}: F1 médio = {mean(vs):.3f}  (min {min(vs):.2f}, max {max(vs):.2f})")


if __name__ == "__main__":
    main()

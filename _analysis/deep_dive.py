"""
Sub-investigações:
A) Notas órfãs (existem em E/M/H mas não no Expert) — entender quem/porquê.
B) Transposições "fora do acorde" — qual fret Expert vira qual fret reduzido?
C) Bursts rápidos: como Harmonix decima sequências de 16ths/32ths no Expert?
D) Anchor de fret: a sequência reduzida tende a ficar num só fret?
"""
from __future__ import annotations
import os, glob, mido
from collections import Counter, defaultdict
import sys; sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part, FRET_NAMES


def investigate_orphans(charts):
    """A — listar e contextualizar órfãs por dificuldade."""
    expert_ticks = {n.tick for n in charts["Expert"].notes}
    expert_by_tick = {n.tick: n for n in charts["Expert"].notes}
    out = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_by_tick = {n.tick: n for n in charts[diff].notes}
        orphans = []
        for tick, rn in diff_by_tick.items():
            if tick in expert_ticks: continue
            # Pega o tick Expert mais próximo
            before = max((t for t in expert_ticks if t < tick), default=None)
            after = min((t for t in expert_ticks if t > tick), default=None)
            orphans.append(dict(
                tick=tick,
                frets=[FRET_NAMES[f] for f in rn.frets],
                expert_before=before, gap_before=(tick-before if before else None),
                expert_after=after,  gap_after=(after-tick if after else None),
                fret_before=[FRET_NAMES[f] for f in expert_by_tick[before].frets] if before else None,
                fret_after=[FRET_NAMES[f] for f in expert_by_tick[after].frets]   if after else None,
            ))
        out[diff] = orphans
    return out


def investigate_transposition(charts):
    """B — para cada acorde Expert que virou single 'transposed_outside', qual o mapeamento real?"""
    expert_by_tick = {n.tick: n for n in charts["Expert"].notes}
    out = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_by_tick = {n.tick: n for n in charts[diff].notes}
        mapping = Counter()  # (expert_chord_tuple, reduced_tuple)
        for tick, en in expert_by_tick.items():
            rn = diff_by_tick.get(tick)
            if rn is None or len(en.frets) < 2: continue
            efrets = tuple(FRET_NAMES[f] for f in en.frets)
            rfrets = tuple(FRET_NAMES[f] for f in rn.frets)
            # Só nos importam casos onde a redução *não* é subconjunto do expert
            if not set(rn.frets).issubset(set(en.frets)):
                mapping[(efrets, rfrets)] += 1
        out[diff] = dict(mapping)
    return out


def investigate_bursts(charts):
    """C — em sequências de notas Expert separadas por <= 1/8 (240 ticks),
    quantas notas sobrevivem? Em que posições da sequência (1ª, última, alternadas)?"""
    tpb = charts["Expert"].ticks_per_beat
    eighth = tpb // 2  # 240 ticks
    expert = sorted(charts["Expert"].notes, key=lambda n: n.tick)
    # Particiona Expert em runs (gap > 1/8 quebra o run)
    runs = []
    cur = []
    for n in expert:
        if cur and n.tick - cur[-1].tick > eighth:
            runs.append(cur); cur = []
        cur.append(n)
    if cur: runs.append(cur)
    out = {}
    for diff in ("Easy", "Medium", "Hard"):
        diff_ticks = {n.tick for n in charts[diff].notes}
        size_to_keep = defaultdict(lambda: defaultdict(int))  # run_size -> kept_size -> count
        positions_kept = defaultdict(Counter)                 # run_size -> tuple(positions) -> count
        for run in runs:
            n = len(run)
            if n < 2: continue   # ignorar run de 1 (não é burst)
            kept_idxs = tuple(i for i, note in enumerate(run) if note.tick in diff_ticks)
            size_to_keep[n][len(kept_idxs)] += 1
            # Normalizar para posições relativas (start=0, end=n-1, etc.)
            positions_kept[n][kept_idxs] += 1
        # Resumo
        per_size = {}
        for n in sorted(size_to_keep):
            top = positions_kept[n].most_common(5)
            per_size[n] = dict(
                runs=sum(size_to_keep[n].values()),
                kept_size_distribution=dict(size_to_keep[n]),
                top_position_patterns=[(list(p), c) for p, c in top],
            )
        out[diff] = per_size
    return out


def investigate_anchor(charts):
    """D — em sequências reduzidas, com que frequência o mesmo fret aparece consecutivamente?"""
    out = {}
    for diff in ("Easy", "Medium", "Hard"):
        notes = sorted(charts[diff].notes, key=lambda n: n.tick)
        if not notes: continue
        same_run_lengths = []
        cur = 1
        last_frets = notes[0].frets
        for n in notes[1:]:
            if n.frets == last_frets:
                cur += 1
            else:
                same_run_lengths.append(cur); cur = 1
                last_frets = n.frets
        same_run_lengths.append(cur)
        out[diff] = dict(
            mean_repeat=round(sum(same_run_lengths)/len(same_run_lengths), 2),
            max_repeat=max(same_run_lengths),
            histogram_top=Counter(same_run_lengths).most_common(5),
        )
    return out


def main():
    base = "/Users/gabrielcarvalho/Downloads/system"
    songs = sorted(glob.glob(f"{base}/System*"))
    for f in songs:
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        charts = parse_part(mid, "PART GUITAR")

        print(f"\n========== {name} ==========")

        # A
        orphans = investigate_orphans(charts)
        print("[A] Órfãs:")
        for d, lst in orphans.items():
            if lst:
                print(f"  {d}: {len(lst)} órfãs")
                for o in lst[:5]:
                    print(f"    tick={o['tick']} frets={o['frets']}  before(t={o['expert_before']},gap={o['gap_before']},frets={o['fret_before']})  after(t={o['expert_after']},gap={o['gap_after']},frets={o['fret_after']})")

        # B
        trans = investigate_transposition(charts)
        print("[B] Acorde Expert → redução fora-do-acorde:")
        for d, m in trans.items():
            if m:
                print(f"  {d}:")
                for (ef, rf), cnt in sorted(m.items(), key=lambda x:-x[1])[:10]:
                    print(f"    {ef} -> {rf}  x{cnt}")

        # C
        bursts = investigate_bursts(charts)
        print("[C] Bursts (run de notas Expert ≤ 1/8 entre si):")
        for d, per_size in bursts.items():
            print(f"  {d}:")
            for n in sorted(per_size):
                if per_size[n]['runs'] < 3 and n>5: continue  # foco em runs comuns
                print(f"    run={n}: {per_size[n]['runs']} ocorrências; kept_size={per_size[n]['kept_size_distribution']}; top={per_size[n]['top_position_patterns'][:3]}")

        # D
        anchor = investigate_anchor(charts)
        print("[D] Anchor — repetição consecutiva do MESMO fret/acorde:")
        for d, v in anchor.items():
            print(f"  {d}: {v}")


if __name__ == "__main__":
    main()

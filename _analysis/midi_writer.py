"""
Writer MIDI: pega um notes.mid original (Harmonix), gera reduções E/M/H da PART GUITAR
a partir do Expert e escreve um novo notes.mid no formato CH/RB.

Estratégia:
  - copia todas as faixas EXCETO PART GUITAR
  - reconstrói PART GUITAR com:
      - notas Expert preservadas (pitches 96-100)
      - novas notas Hard (pitches 84-88) geradas pelo reducer
      - novas notas Medium (pitches 72-76)
      - novas notas Easy (pitches 60-64)
      - marcadores compartilhados (overdrive=116, solos=103/105/106 — preservar do original)
      - animações de mão (40-59 — preservar do original)

Comparação: se gerarmos `notes.gen.mid` no mesmo diretório de uma música existente,
podemos diff vs o `notes.mid` original.
"""
from __future__ import annotations
import os, sys, copy
import mido
sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part, FRET_NAMES, DIFF_BASE
from reducer import reduce_chart


def _abs_to_delta(events_abs):
    """Lista de (abs_tick, MetaMessage|Message) → MidiTrack com delta times."""
    events_abs.sort(key=lambda e: e[0])
    track = mido.MidiTrack()
    last = 0
    for abs_t, msg in events_abs:
        delta = abs_t - last
        track.append(msg.copy(time=delta))
        last = abs_t
    return track


def _decode_track_abs(track):
    """Devolve eventos de um MidiTrack como (abs_tick, msg) sem alterar."""
    abs_t = 0; out = []
    for msg in track:
        abs_t += msg.time
        out.append((abs_t, msg))
    return out


def _make_guitar_track_from_charts(orig_track, charts_by_diff, replace_diffs=("Easy","Medium","Hard")):
    """Constrói nova PART GUITAR mantendo:
        - todas as notas que NÃO sejam dos pitches das difficulties em replace_diffs
        - mas SUBSTITUI os pitches dessas dificuldades pelos charts gerados.
       O Expert (pitches 96-102) é preservado intocado. Marcadores 40-59, 103-116 idem.
    """
    pitches_to_strip = set()
    for diff in replace_diffs:
        base = DIFF_BASE[diff]
        # Easy: 58 (open), 60-64 (G..O), 65/66 (force HOPO on/off)
        for p in [base-2, base, base+1, base+2, base+3, base+4, base+5, base+6]:
            pitches_to_strip.add(p)

    # Eventos originais que sobrevivem
    surviving = []
    for abs_t, msg in _decode_track_abs(orig_track):
        if msg.type in ("note_on", "note_off"):
            if msg.note in pitches_to_strip: continue
        surviving.append((abs_t, msg))

    # Eventos novos das dificuldades reduzidas
    new_events = []
    for diff in replace_diffs:
        base = DIFF_BASE[diff]
        c = charts_by_diff[diff]
        for n in c.notes:
            if n.is_open or not n.frets:
                pitch = base - 2
                new_events.append((n.tick, mido.Message("note_on",  note=pitch, velocity=100, time=0)))
                new_events.append((n.end_tick if n.end_tick > n.tick else n.tick + 1,
                                   mido.Message("note_off", note=pitch, velocity=0, time=0)))
                continue
            for f in n.frets:
                pitch = base + f
                new_events.append((n.tick, mido.Message("note_on",  note=pitch, velocity=100, time=0)))
                end = n.end_tick if n.end_tick > n.tick else n.tick + 1
                new_events.append((end, mido.Message("note_off", note=pitch, velocity=0, time=0)))
            if n.forced_hopo == +1:
                new_events.append((n.tick, mido.Message("note_on",  note=base+5, velocity=100, time=0)))
                new_events.append((n.tick+1, mido.Message("note_off", note=base+5, velocity=0, time=0)))
            elif n.forced_hopo == -1:
                new_events.append((n.tick, mido.Message("note_on",  note=base+6, velocity=100, time=0)))
                new_events.append((n.tick+1, mido.Message("note_off", note=base+6, velocity=0, time=0)))

    # Junta tudo
    all_events = surviving + new_events
    # End-of-track precisa ficar no final — vamos remover qualquer EOT existente e re-adicionar
    all_events = [e for e in all_events if not (e[1].type == "end_of_track")]
    if all_events:
        max_t = max(e[0] for e in all_events)
    else:
        max_t = 0
    new_track = _abs_to_delta(all_events)
    new_track.name = "PART GUITAR"
    new_track.append(mido.MetaMessage("end_of_track", time=0))
    return new_track


def write_reduced_midi(input_mid_path: str, output_mid_path: str,
                       replace_diffs=("Easy","Medium","Hard")) -> dict:
    """Lê o notes.mid original, gera reduções para PART GUITAR e escreve novo arquivo."""
    mid = mido.MidiFile(input_mid_path)
    orig_charts = parse_part(mid, "PART GUITAR")
    expert = orig_charts["Expert"]
    new_charts = {}
    for d in replace_diffs:
        new_charts[d] = reduce_chart(expert, d)
    # Constrói nova PART GUITAR
    out_mid = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat)
    for tr in mid.tracks:
        if tr.name == "PART GUITAR":
            new_tr = _make_guitar_track_from_charts(tr, new_charts, replace_diffs)
            out_mid.tracks.append(new_tr)
        else:
            out_mid.tracks.append(tr)
    out_mid.save(output_mid_path)
    return dict(
        input=input_mid_path,
        output=output_mid_path,
        ticks_per_beat=mid.ticks_per_beat,
        difficulties_generated=list(replace_diffs),
        notes_per_diff={d: len(new_charts[d].notes) for d in replace_diffs},
    )


def diff_midi(orig_path: str, gen_path: str) -> dict:
    """Compara um notes.mid gerado vs o original, focado em PART GUITAR."""
    orig = mido.MidiFile(orig_path); gen = mido.MidiFile(gen_path)
    a = parse_part(orig, "PART GUITAR")
    b = parse_part(gen, "PART GUITAR")
    out = {}
    for d in ("Easy","Medium","Hard","Expert"):
        ao = {n.tick for n in a[d].notes}
        bo = {n.tick for n in b[d].notes}
        inter = ao & bo
        out[d] = dict(
            orig_notes=len(ao), gen_notes=len(bo),
            common_ticks=len(inter),
            recall=len(inter)/max(len(ao),1),
            precision=len(inter)/max(len(bo),1),
        )
    return out


if __name__ == "__main__":
    import glob, json
    base = "/Users/gabrielcarvalho/Downloads/system"
    # Roda em todas as músicas e gera notes.gen.mid no mesmo diretório
    for f in sorted(glob.glob(f"{base}/System*")):
        in_p  = os.path.join(f, "notes.mid")
        out_p = os.path.join(f, "notes.gen.mid")
        info = write_reduced_midi(in_p, out_p)
        diff = diff_midi(in_p, out_p)
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        print(f"\n=== {name} ===")
        print(f"  saída: {out_p}")
        print(f"  notas geradas: {info['notes_per_diff']}")
        print(f"  Expert intacto? {diff['Expert']['recall']:.2f} recall  {diff['Expert']['precision']:.2f} prec")
        for d in ("Easy","Medium","Hard"):
            r = diff[d]
            print(f"  {d}: orig={r['orig_notes']} gen={r['gen_notes']} prec={r['precision']:.2f} rec={r['recall']:.2f}")

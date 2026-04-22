"""
Writer MIDI: pega um notes.mid original (Harmonix), gera reduções E/M/H da
PART GUITAR e PART DRUMS a partir do Expert e escreve novo notes.mid.

Estratégia:
  - copia todas as faixas EXCETO PART GUITAR e PART DRUMS
  - PART GUITAR: substitui E/M/H gerados pelo reducer; preserva Expert + markers
  - PART DRUMS: substitui E/M/H pelos drum charts gerados; preserva Expert,
    markers cymbal (110/111/112), drum fills (120-124), 2x kick (95), animações
"""
from __future__ import annotations
import os, sys, copy
import mido
sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part, FRET_NAMES, DIFF_BASE
from reducer import reduce_chart
from parse_drums import parse_drums, DIFF_BASE_DRUMS, LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN
from reducer_drums import reduce_drums


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


def _make_drums_track_from_charts(orig_track, drum_charts_by_diff, replace_diffs=("Easy","Medium","Hard")):
    """Reconstrói PART DRUMS:
       - Strip pitches das dificuldades a serem substituídas (60-64 / 72-76 / 84-88)
       - Mantém Expert (96-100), 2x kick (95), markers Pro (110/111/112), SP (116),
         drum fills (120-124), animações (24-51), P1/P2 (105/106) e text events
       - Adiciona notas geradas com pitches corretos por dificuldade.
    """
    pitches_to_strip = set()
    for diff in replace_diffs:
        base = DIFF_BASE_DRUMS[diff]
        for p in range(base, base + 5):  # kick + snare + 3 pads
            pitches_to_strip.add(p)

    surviving = []
    for abs_t, msg in _decode_track_abs(orig_track):
        if msg.type in ("note_on", "note_off"):
            if msg.note in pitches_to_strip: continue
        surviving.append((abs_t, msg))

    new_events = []
    for diff in replace_diffs:
        base = DIFF_BASE_DRUMS[diff]
        c = drum_charts_by_diff[diff]
        for n in c.notes:
            pitch = base + n.lane  # lane 0..4 → kick..green
            new_events.append((n.tick, mido.Message("note_on",  note=pitch, velocity=n.velocity, time=0)))
            # Drum notes têm duração mínima — usa 1 tick (gem instantâneo)
            new_events.append((n.tick + 1, mido.Message("note_off", note=pitch, velocity=0, time=0)))

    all_events = surviving + new_events
    all_events = [e for e in all_events if not (e[1].type == "end_of_track")]
    new_track = _abs_to_delta(all_events)
    new_track.name = "PART DRUMS"
    new_track.append(mido.MetaMessage("end_of_track", time=0))
    return new_track


def write_reduced_midi(input_mid_path: str, output_mid_path: str,
                       replace_diffs=("Easy","Medium","Hard"),
                       parts=("PART GUITAR", "PART DRUMS")) -> dict:
    """Lê o notes.mid original, gera reduções para as PARTs especificadas e escreve novo arquivo."""
    mid = mido.MidiFile(input_mid_path)
    info = dict(input=input_mid_path, output=output_mid_path,
                ticks_per_beat=mid.ticks_per_beat,
                difficulties_generated=list(replace_diffs), parts=list(parts),
                notes_per_part_diff={})

    # Pre-compute all replacements
    guitar_charts = None
    drums_charts = None
    if "PART GUITAR" in parts:
        gc = parse_part(mid, "PART GUITAR")
        guitar_charts = {d: reduce_chart(gc["Expert"], d) for d in replace_diffs}
        info["notes_per_part_diff"]["PART GUITAR"] = {d: len(guitar_charts[d].notes) for d in replace_diffs}
    if "PART DRUMS" in parts:
        dc = parse_drums(mid)
        drums_charts = {d: reduce_drums(dc["Expert"], d) for d in replace_diffs}
        info["notes_per_part_diff"]["PART DRUMS"] = {d: len(drums_charts[d].notes) for d in replace_diffs}

    out_mid = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat)
    for tr in mid.tracks:
        if tr.name == "PART GUITAR" and guitar_charts:
            out_mid.tracks.append(_make_guitar_track_from_charts(tr, guitar_charts, replace_diffs))
        elif tr.name == "PART DRUMS" and drums_charts:
            out_mid.tracks.append(_make_drums_track_from_charts(tr, drums_charts, replace_diffs))
        else:
            out_mid.tracks.append(tr)
    out_mid.save(output_mid_path)
    return info


def diff_midi_parts(orig_path: str, gen_path: str) -> dict:
    """Compara notes.gen vs original em PART GUITAR e PART DRUMS."""
    orig = mido.MidiFile(orig_path); gen = mido.MidiFile(gen_path)
    out = {"guitar": {}, "drums": {}}
    ag = parse_part(orig, "PART GUITAR"); bg = parse_part(gen, "PART GUITAR")
    for d in ("Easy","Medium","Hard","Expert"):
        ao = {n.tick for n in ag[d].notes}; bo = {n.tick for n in bg[d].notes}
        inter = ao & bo
        out["guitar"][d] = dict(orig=len(ao), gen=len(bo),
                                recall=round(len(inter)/max(len(ao),1), 2),
                                precision=round(len(inter)/max(len(bo),1), 2))
    ad = parse_drums(orig); bd = parse_drums(gen)
    for d in ("Easy","Medium","Hard","Expert"):
        ao = {(n.tick, n.lane, n.is_cymbal) for n in ad[d].notes}
        bo = {(n.tick, n.lane, n.is_cymbal) for n in bd[d].notes}
        inter = ao & bo
        out["drums"][d] = dict(orig=len(ao), gen=len(bo),
                               recall=round(len(inter)/max(len(ao),1), 2),
                               precision=round(len(inter)/max(len(bo),1), 2))
    return out


def diff_midi(orig_path: str, gen_path: str) -> dict:
    """Compatibilidade: retorna só guitar (forma antiga)."""
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
    for f in sorted(glob.glob(f"{base}/System*")):
        in_p  = os.path.join(f, "notes.mid")
        out_p = os.path.join(f, "notes.gen.mid")
        info = write_reduced_midi(in_p, out_p)
        diff = diff_midi_parts(in_p, out_p)
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        print(f"\n=== {name} ===  saída: {os.path.basename(out_p)}")
        for part in ("guitar","drums"):
            ex = diff[part]['Expert']
            print(f"  {part:6s} Expert intacto: rec={ex['recall']:.2f} prec={ex['precision']:.2f}")
            for d in ("Easy","Medium","Hard"):
                r = diff[part][d]
                print(f"  {part:6s} {d}: orig={r['orig']} gen={r['gen']} prec={r['precision']:.2f} rec={r['recall']:.2f}")

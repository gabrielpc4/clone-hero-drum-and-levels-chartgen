"""
Importa um MIDI de transcrição externa (Songsterr/Guitar Pro/MuseScore) e gera
PART DRUMS Expert no formato Harmonix/Clone Hero.

Uso:
    python3 import_songsterr.py <externo.mid> <chart_ref.mid> <saida.mid>
        [--offset-beats N] [--drop-before-src-beat N] [--dedup-beats N]

  externo.mid    é o MIDI baixado (Songsterr, GP exportado, MuseScore)
  chart_ref.mid  é o notes.mid do chart (Harmonix ou custom) com PART GUITAR
  saida.mid      caminho de saída

Alinhamento (beat-mode): cada nota do src no beat musical B cai no beat
musical B + offset do ref. offset default = (1ª nota guitar ref) - (1ª nota
guitar src). Override com --offset-beats.

Mapa GM→RB:
  36,35           → Kick
  37,38,39,40     → Snare
  42,44           → Yellow cymbal (hi-hat fechado/pedal)
  46              → Yellow (hi-hat folgado) ou Blue (ride/accent) — decisão
                    por modo da música (ver classify_open_mode)
  49,52,55,57     → Green cymbal (crashes, china, splash)
  51,53,59        → Blue cymbal (ride)
  41,43,45,47,48,50 → Toms Y/B/G — mapeados dinamicamente (build_tom_pitch_map)
"""
from __future__ import annotations
import os, sys, argparse
from typing import List, Tuple, Dict, Optional
import mido

sys.path.insert(0, os.path.dirname(__file__))
from parse_drums import DIFF_BASE_DRUMS, LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN

GM_TO_RB: Dict[int, Tuple[int, bool]] = {
    35: (LANE_KICK,   False),
    36: (LANE_KICK,   False),
    37: (LANE_SNARE,  False),
    38: (LANE_SNARE,  False),
    39: (LANE_SNARE,  False),
    40: (LANE_SNARE,  False),
    42: (LANE_YELLOW, True),
    44: (LANE_YELLOW, True),
    46: (LANE_BLUE,   True),   # override dinâmico (Y se dominante na música)
    49: (LANE_GREEN,  True),
    51: (LANE_BLUE,   True),
    52: (LANE_GREEN,  True),
    53: (LANE_BLUE,   True),
    55: (LANE_GREEN,  True),
    57: (LANE_GREEN,  True),
    59: (LANE_BLUE,   True),
}

TOM_PITCHES = (41, 43, 45, 47, 48, 50)


def build_tom_pitch_map(drum_track) -> Dict[int, int]:
    """{pitch_gm → lane_rb} baseado nos toms usados: mais agudo=Y, médio=B, floor=G."""
    used = set()
    for msg in drum_track:
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9 \
           and msg.note in TOM_PITCHES:
            used.add(msg.note)
    if not used:
        return {}
    sorted_desc = sorted(used, reverse=True)
    n = len(sorted_desc)
    out = {}
    if n == 1:
        out[sorted_desc[0]] = LANE_YELLOW
    elif n == 2:
        out[sorted_desc[0]] = LANE_YELLOW
        out[sorted_desc[1]] = LANE_BLUE
    else:
        third = n / 3
        for i, p in enumerate(sorted_desc):
            if i < round(third):       out[p] = LANE_YELLOW
            elif i < round(2 * third): out[p] = LANE_BLUE
            else:                      out[p] = LANE_GREEN
    return out


def _first_guitar_beat_ref(ref_mid: mido.MidiFile) -> Optional[float]:
    tpb = ref_mid.ticks_per_beat
    gt = next((t for t in ref_mid.tracks if t.name == "PART GUITAR"), None)
    if gt is None: return None
    abs_t = 0
    for msg in gt:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and 96 <= msg.note <= 100:
            return abs_t / tpb
    return None


def _first_guitar_beat_src(src_mid: mido.MidiFile) -> Optional[float]:
    HINTS = ("guitar", "gibson", "ibanez", "iceman", "strat", "tele",
             "fender", "bass", "thunderbird")
    tpb = src_mid.ticks_per_beat
    first = None
    for t in src_mid.tracks:
        name = next((m.name for m in t if m.type == "track_name"), "").lower()
        if not any(k in name for k in HINTS): continue
        abs_t = 0
        for msg in t:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel != 9:
                b = abs_t / tpb
                first = b if first is None else min(first, b)
                break
    return first


def classify_open_hat_mode(drum_track) -> bool:
    """True → open HH (GM 46) é 'folgado' (amarelo); False → 'ride/accent' (azul).
    Critério: se open ≥ 70% dos hi-hats totais, é folgado."""
    n_closed = sum(1 for msg in drum_track
                   if msg.type == "note_on" and msg.velocity > 0
                   and msg.channel == 9 and msg.note == 42)
    n_open = sum(1 for msg in drum_track
                 if msg.type == "note_on" and msg.velocity > 0
                 and msg.channel == 9 and msg.note == 46)
    total = n_closed + n_open
    return total > 0 and (n_open / total) >= 0.70


def build_drums_track(src_mid: mido.MidiFile, beat_offset: float,
                      target_tpb: int, drop_before_src_beat: float = 0.0,
                      dedup_beats: float = 1/16) -> mido.MidiTrack:
    """Converte drums src → PART DRUMS ref em beat-mode.
       Flam dedup: pares mesma-lane+is_cymbal com gap ≤ dedup_beats viram:
         - Snare: 1ª permanece R, 2ª vira Y-tom NO MESMO TICK (R+Y simultâneos)
         - Outros: 2ª descartada
    """
    src_tpb = src_mid.ticks_per_beat
    drum_track = next((t for t in src_mid.tracks
                       if any(m.type == "note_on" and m.channel == 9 and m.velocity > 0 for m in t)),
                      None)
    if drum_track is None:
        raise RuntimeError("Nenhuma track de bateria (canal 9) encontrada")

    open_hat_yellow = classify_open_hat_mode(drum_track)
    tom_lane_map = build_tom_pitch_map(drum_track)
    print(f"  Open HH → {'Y (folgado)' if open_hat_yellow else 'B (ride/accent)'}")
    print(f"  Tom map: {[(p, ['K','S','Y','B','G'][l]) for p, l in sorted(tom_lane_map.items())]}")

    def resolve_lane(pitch: int) -> Tuple[Optional[int], bool]:
        if pitch in tom_lane_map:
            return (tom_lane_map[pitch], False)
        if pitch == 46:
            return (LANE_YELLOW if open_hat_yellow else LANE_BLUE, True)
        lr = GM_TO_RB.get(pitch)
        if lr is None: return (None, False)
        return lr

    # Flam detection (pass 1): gap ≤ dedup_beats na mesma lane+is_cym.
    dedup_gap = int(round(src_tpb * dedup_beats))
    last_by_lane: Dict[Tuple[int, bool], int] = {}
    dedup_skipped: set = set()
    flam_snare_second: Dict[Tuple[int, int], int] = {}  # {(tick,pitch): tick_1ª}
    abs_src = 0
    for msg in drum_track:
        abs_src += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
            lane, is_cym = resolve_lane(msg.note)
            if lane is None: continue
            key = (lane, is_cym)
            last = last_by_lane.get(key)
            if last is not None and abs_src - last <= dedup_gap:
                if lane == LANE_SNARE:
                    flam_snare_second[(abs_src, msg.note)] = last
                else:
                    dedup_skipped.add((abs_src, msg.note))
            else:
                last_by_lane[key] = abs_src

    # Pass 2: gera events em beat-mode
    abs_src = 0
    events_abs = []  # (tick, pitch, lane, is_cym)
    for msg in drum_track:
        abs_src += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
            if (abs_src, msg.note) in dedup_skipped: continue
            flam_first = flam_snare_second.get((abs_src, msg.note))
            src_tick = flam_first if flam_first is not None else abs_src
            src_beat = src_tick / src_tpb
            if src_beat < drop_before_src_beat: continue
            tgt_beat = src_beat + beat_offset
            if tgt_beat < 0: continue
            lane, is_cym = resolve_lane(msg.note)
            if lane is None: continue
            if flam_first is not None:
                lane, is_cym = LANE_YELLOW, False
            tgt_tick = int(round(tgt_beat * target_tpb))
            events_abs.append((tgt_tick, 96 + lane, lane, is_cym))

    # Remove (tick, lane) duplicados (ex: crash1+crash2 simultâneos mesmo GM)
    seen, uniq = set(), []
    for ev in sorted(events_abs):
        k = (ev[0], ev[2])
        if k in seen: continue
        seen.add(k); uniq.append(ev)

    # Monta track MIDI
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="PART DRUMS", time=0))
    track.append(mido.MetaMessage("text", text="[mix 0 drums0]", time=0))

    events = []
    for tick, pitch, lane, _ in uniq:
        events.append((tick,     mido.Message("note_on",  note=pitch, velocity=100, time=0)))
        events.append((tick + 1, mido.Message("note_off", note=pitch, velocity=0,   time=0)))

    # Tom markers (110/111/112) cobrindo ticks de notas tom
    by_lane: Dict[int, List[int]] = {LANE_YELLOW: [], LANE_BLUE: [], LANE_GREEN: []}
    for tick, _, lane, is_cym in uniq:
        if lane in by_lane and not is_cym:
            by_lane[lane].append(tick)
    marker_pitch = {LANE_YELLOW: 110, LANE_BLUE: 111, LANE_GREEN: 112}
    for lane, ticks in by_lane.items():
        for t in sorted(set(ticks)):
            events.append((t,     mido.Message("note_on",  note=marker_pitch[lane], velocity=100, time=0)))
            events.append((t + target_tpb // 8, mido.Message("note_off", note=marker_pitch[lane], velocity=0, time=0)))

    events.sort(key=lambda e: e[0])
    last_t = 0
    for abs_t, msg in events:
        track.append(msg.copy(time=abs_t - last_t))
        last_t = abs_t
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src_mid", help="MIDI externo contendo a bateria")
    ap.add_argument("ref_mid", help="notes.mid do chart (referência)")
    ap.add_argument("out_mid", help="onde gravar o chart resultante")
    ap.add_argument("--offset-beats", type=float, default=None,
                    help="override manual do offset em beats (ref = src + N). "
                         "Default: (1ª nota guitar ref) - (1ª nota guitar src).")
    ap.add_argument("--drop-before-src-beat", type=float, default=None,
                    help="dropa notas src antes deste beat (remove contagem de baqueta).")
    ap.add_argument("--dedup-beats", type=float, default=1/16,
                    help="pares mesma-lane com gap ≤ N beats viram R+Y (snare) ou dedup (outros). Default 1/16.")
    args = ap.parse_args()

    src = mido.MidiFile(args.src_mid)
    ref = mido.MidiFile(args.ref_mid)

    # Offset default: primeira nota PART GUITAR ref vs primeira nota guitar src
    if args.offset_beats is not None:
        beat_offset = args.offset_beats
        method = "override"
    else:
        ref_gt = _first_guitar_beat_ref(ref)
        src_gt = _first_guitar_beat_src(src)
        if ref_gt is not None and src_gt is not None:
            beat_offset = ref_gt - src_gt
            method = f"guitar-first (ref {ref_gt:.2f} ↔ src {src_gt:.2f})"
        else:
            beat_offset = 0.0
            method = "fallback=0"

    drop_beat = args.drop_before_src_beat if args.drop_before_src_beat is not None else (_first_guitar_beat_src(src) or 0.0)
    print(f"Alinhamento ({method}): beat_ref = beat_src + {beat_offset:+.3f}")
    print(f"  drop antes de src_beat {drop_beat:.2f}")

    new_drums = build_drums_track(src, beat_offset, ref.ticks_per_beat,
                                  drop_before_src_beat=drop_beat,
                                  dedup_beats=args.dedup_beats)

    # Diagnóstico: 1ª drum gerada
    abs_t = 0; first_drum_tick = None
    for m in new_drums:
        abs_t += m.time
        if m.type == "note_on" and m.velocity > 0 and 96 <= m.note <= 100:
            first_drum_tick = abs_t; break
    if first_drum_tick is not None:
        print(f"  → 1ª drum: tick={first_drum_tick} beat={first_drum_tick/ref.ticks_per_beat:.2f}")
    print(f"  Se o áudio não bater: ajuste --offset-beats N (+ atrasa no ref, − adianta)")

    # Clona ref substituindo PART DRUMS
    out = mido.MidiFile(type=ref.type, ticks_per_beat=ref.ticks_per_beat)
    replaced = False
    for t in ref.tracks:
        if t.name == "PART DRUMS":
            out.tracks.append(new_drums); replaced = True
        else:
            out.tracks.append(t)
    if not replaced:
        out.tracks.append(new_drums)
    out.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

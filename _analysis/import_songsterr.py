"""
Importa um MIDI de transcrição externa (Songsterr/Guitar Pro/MuseScore) e gera
PART DRUMS Expert no formato Harmonix/Clone Hero.

Problema principal: o MIDI externo e o notes.mid do chart têm offsets iniciais
diferentes (e possivelmente TPB e/ou tempo diferentes). Solução: usar a guitarra
como "âncora" — alinhar onsets de guitarra entre as duas fontes para descobrir
a transformação temporal, e aplicar essa transformação nos onsets de drums.

Uso:
    python3 import_songsterr.py <externo.mid> <chart_ref.mid> <saida.mid>

Onde:
  externo.mid    é o MIDI baixado (Songsterr, GP exportado, MuseScore)
  chart_ref.mid  é o notes.mid do chart (Harmonix ou custom) que contém
                 PART GUITAR já sincronizado com o áudio
  saida.mid      é onde escrevemos o chart resultante (PART DRUMS + PART GUITAR
                 preservados do chart_ref; o externo só é usado como fonte de
                 bateria e de âncora para alinhamento)

Mapa GM → RB drums:
  36       → Kick
  35       → Kick (acoustic bass drum)
  37       → Snare (side stick / rimclick)
  38, 40   → Snare
  39       → Snare (hand clap)
  41, 43   → Green tom (floor toms)
  42       → Yellow cymbal (hi-hat fechado)
  44       → Yellow cymbal (pedal hi-hat) — mas pode ser drop
  45, 47   → Blue tom (low-mid)
  46       → Blue cymbal (hi-hat aberto → na convenção RB costuma virar blue
              cymbal "open hi-hat", mas podemos optar por Y-cym se preferido)
  48, 50   → Yellow tom (hi-mid / high)
  49, 57   → Green cymbal (crashes)
  51, 59   → Blue cymbal (rides)
  52       → Green cymbal (china)
  53       → Blue cymbal (ride bell)
  55       → Green cymbal (splash)
"""
from __future__ import annotations
import os, sys, argparse, bisect
from typing import List, Tuple, Dict
import mido

sys.path.insert(0, os.path.dirname(__file__))
from parse_chart import parse_part
from parse_drums import DIFF_BASE_DRUMS, LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN

# (pitch GM) -> (lane RB, is_cymbal)
GM_TO_RB: Dict[int, Tuple[int, bool]] = {
    35: (LANE_KICK,   False),
    36: (LANE_KICK,   False),
    37: (LANE_SNARE,  False),
    38: (LANE_SNARE,  False),
    39: (LANE_SNARE,  False),
    40: (LANE_SNARE,  False),
    41: (LANE_GREEN,  False),   # low floor tom
    42: (LANE_YELLOW, True),    # closed hi-hat
    43: (LANE_GREEN,  False),   # high floor tom
    44: (LANE_YELLOW, True),    # pedal hi-hat — poderia dropar; mantemos como hat
    45: (LANE_BLUE,   False),   # low tom
    46: (LANE_BLUE,   True),    # open hi-hat → blue cymbal em RB
    47: (LANE_BLUE,   False),   # low-mid tom
    48: (LANE_YELLOW, False),   # hi-mid tom
    49: (LANE_GREEN,  True),    # crash 1
    50: (LANE_YELLOW, False),   # high tom
    51: (LANE_BLUE,   True),    # ride 1
    52: (LANE_GREEN,  True),    # china
    53: (LANE_BLUE,   True),    # ride bell
    55: (LANE_GREEN,  True),    # splash
    57: (LANE_GREEN,  True),    # crash 2
    59: (LANE_BLUE,   True),    # ride 2
}


def _tempo_map(track0, tpb: int) -> List[Tuple[int, float]]:
    """(tick, secs_per_tick) breakpoints a partir de set_tempo events."""
    out = []
    abs_t = 0
    cur = 500000 / tpb / 1_000_000  # 120 BPM default
    out.append((0, cur))
    for msg in track0:
        abs_t += msg.time
        if msg.type == "set_tempo":
            cur = msg.tempo / tpb / 1_000_000
            out.append((abs_t, cur))
    return out


def tick_to_seconds(tick: int, tempo_map: List[Tuple[int, float]]) -> float:
    """Converte tick absoluto em segundos usando o mapa de tempo."""
    sec = 0.0
    for (t0, spt), (t1, _) in zip(tempo_map, tempo_map[1:] + [(float("inf"), 0.0)]):
        if tick < t1:
            return sec + (tick - t0) * spt
        sec += (t1 - t0) * spt
    return sec


def tick_to_beats(tick: int, tpb: int) -> float:
    """Tick → beat index (float). Independe de BPM (não usa tempo map)."""
    return tick / tpb


def beats_to_tick(beat: float, tpb: int) -> int:
    return int(round(beat * tpb))


def extract_note_times_secs(track, tempo_map, channel_filter=None) -> List[float]:
    """Tempos de ataque em segundos."""
    times = []
    abs_t = 0
    for msg in track:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            if channel_filter is not None and msg.channel != channel_filter:
                continue
            times.append(tick_to_seconds(abs_t, tempo_map))
    return times


def extract_note_beats(track, tpb: int, channel_filter=None) -> List[float]:
    """Tempos de ataque em BEATS (musicais, independente de BPM)."""
    out = []
    abs_t = 0
    for msg in track:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            if channel_filter is not None and msg.channel != channel_filter:
                continue
            out.append(tick_to_beats(abs_t, tpb))
    return out


def _score_alignment(ref_sorted: List[float], src_times: List[float],
                     offset: float, scale: float, tol: float = 0.030) -> int:
    """Conta quantas src caem a ≤ tol de alguma ref após t' = offset + scale*t."""
    score = 0
    for t in src_times:
        shifted = offset + scale * t
        idx = bisect.bisect_left(ref_sorted, shifted)
        for j in (idx - 1, idx):
            if 0 <= j < len(ref_sorted) and abs(ref_sorted[j] - shifted) <= tol:
                score += 1; break
    return score


def _iterative_refine(ref_sorted: List[float], src_times: List[float],
                      offset: float, scale: float, tol: float,
                      iters: int = 8) -> Tuple[float, float, int]:
    """ICP-style: pareia cada src com ref mais próximo (após aplicar oferta
    atual), faz regressão linear nos pares dentro de tol, atualiza (offset, scale)."""
    cur_off, cur_scale = offset, scale
    for _ in range(iters):
        xs, ys = [], []
        for t in src_times:
            shifted = cur_off + cur_scale * t
            idx = bisect.bisect_left(ref_sorted, shifted)
            for j in (idx - 1, idx):
                if 0 <= j < len(ref_sorted) and abs(ref_sorted[j] - shifted) <= tol:
                    xs.append(t); ys.append(ref_sorted[j]); break
        if len(xs) < 20: break
        # Regressão linear y = a + b*x
        n = len(xs)
        sx = sum(xs); sy = sum(ys)
        sxx = sum(x*x for x in xs); sxy = sum(x*y for x,y in zip(xs,ys))
        denom = n * sxx - sx * sx
        if denom == 0: break
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
        cur_off, cur_scale = a, b
    score = _score_alignment(ref_sorted, src_times, cur_off, cur_scale, tol=tol)
    return cur_off, cur_scale, score


def _collapse_chords(times: List[float], eps: float = 0.015) -> List[float]:
    """Colapsa notas em ±eps (15ms) em um único 'gem-event' (mínimo)."""
    out = []
    last = -1e9
    for t in sorted(times):
        if t - last > eps:
            out.append(t); last = t
    return out


def find_music_start_beat_ref(ref_mid: mido.MidiFile) -> float:
    """Acha o beat onde a música começa no chart de referência. Usa o primeiro
    marcador de seção encontrado em EVENTS (ex.: '[section gtr_intro_a]',
    '[section intro]', '[music_start]'). Fallback: primeira nota de PART GUITAR."""
    tpb = ref_mid.ticks_per_beat
    ev = next((t for t in ref_mid.tracks if t.name == "EVENTS"), None)
    if ev is not None:
        abs_t = 0
        for msg in ev:
            abs_t += msg.time
            if msg.type in ("text", "marker"):
                txt = msg.text
                if txt.startswith("[section ") or txt == "[music_start]":
                    return abs_t / tpb
    gt = next((t for t in ref_mid.tracks if t.name == "PART GUITAR"), None)
    if gt is not None:
        abs_t = 0
        for msg in gt:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and 96 <= msg.note <= 100:
                return abs_t / tpb
    return 0.0


def find_music_start_beat_src(src_mid: mido.MidiFile) -> float:
    """Primeiro evento musical 'real' no MIDI externo — primeira nota de
    qualquer track cujo nome contenha guitarra/bass/ibanez/gibson/iceman/etc.
    Ignora drums (contagem de baqueta) e vocais (vocalizações pré-música)."""
    tpb = src_mid.ticks_per_beat
    GUITAR_HINTS = ("guitar", "gibson", "ibanez", "iceman", "strat", "tele",
                    "bass", "thunderbird", "rickenbacker")
    first = None
    for t in src_mid.tracks:
        name = next((m.name for m in t if m.type == "track_name"), "").lower()
        if not any(k in name for k in GUITAR_HINTS): continue
        abs_t = 0
        for msg in t:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                b = abs_t / tpb
                first = b if first is None else min(first, b)
                break
    return first if first is not None else 0.0


def find_guitar_track(src_mid: mido.MidiFile) -> mido.MidiTrack:
    """Heurística: track com mais notas em canais 0-8 (não drums) e nome
    contendo 'guitar', 'ibanez', 'gibson', etc."""
    best = None; best_count = 0
    for t in src_mid.tracks:
        name = ""
        for msg in t:
            if msg.type == "track_name": name = msg.name.lower(); break
        if "drum" in name or "vocals" in name: continue
        count = sum(1 for msg in t if msg.type == "note_on" and msg.velocity > 0 and msg.channel != 9)
        # Preferência para guitarras elétricas ("ibanez", "gibson", "iceman", "electric")
        kw_bonus = 500 if any(k in name for k in ("ibanez", "iceman", "electric", "strat", "tele", "malakian")) else 0
        score = count + kw_bonus
        if score > best_count:
            best_count, best = score, t
    return best


def build_drums_track(src_mid: mido.MidiFile, beat_offset: float,
                      target_tpb: int) -> mido.MidiTrack:
    """Converte notas de bateria (canal 9) do src para o domínio de ticks do
    target. Trabalha em BEATS: cada nota em beat B_src → beat (B_src + offset)
    no target → tick = (B_src + offset) * target_tpb.
    Remapeia GM → RB pitches e gera PART DRUMS Expert com tom markers
    (110/111/112) cobrindo ticks de notas tom."""
    src_tpb = src_mid.ticks_per_beat
    drum_track = next((t for t in src_mid.tracks
                       if any(m.type == "note_on" and m.channel == 9 for m in t)), None)
    if drum_track is None:
        raise RuntimeError("Nenhum track de bateria (canal 9) encontrado")

    # Pré-coleta hi-hats (closed=GM42, open=GM46) para classificar GM46 como
    # accent (= azul, B-cym) vs seção sustentada de open (= amarelo, Y-cym).
    # Heurística: se na janela ±2 beats em torno da nota open há ≥3 closed
    # e o open é minoria, então é um accent → azul. Caso contrário → amarelo.
    abs_src = 0
    hh_closed_beats: List[float] = []
    hh_open_beats:   List[float] = []
    for msg in drum_track:
        abs_src += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
            beat = abs_src / src_tpb
            if msg.note == 42: hh_closed_beats.append(beat)
            elif msg.note == 46: hh_open_beats.append(beat)
    hh_closed_beats.sort()
    open_is_accent: Dict[float, bool] = {}
    WINDOW = 2.0  # beats
    for ob in hh_open_beats:
        # quantos closed na janela?
        lo = bisect.bisect_left(hh_closed_beats, ob - WINDOW)
        hi = bisect.bisect_right(hh_closed_beats, ob + WINDOW)
        n_closed = hi - lo
        # quantos open na mesma janela?
        n_open = sum(1 for o in hh_open_beats if abs(o - ob) <= WINDOW)
        # accent: ≥3 closed na vizinhança e open é minoria
        open_is_accent[ob] = (n_closed >= 3 and n_closed > n_open)

    abs_src = 0
    events_abs = []  # (tick_target, pitch, lane, is_cym)
    for msg in drum_track:
        abs_src += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
            src_beat = abs_src / src_tpb
            tgt_beat = src_beat + beat_offset
            if tgt_beat < 0: continue
            rb = GM_TO_RB.get(msg.note)
            if rb is None: continue
            lane, is_cym = rb
            # Override: open hi-hat (GM 46) só fica em B-cym (azul) quando é accent.
            if msg.note == 46 and not open_is_accent.get(src_beat, False):
                lane, is_cym = LANE_YELLOW, True
            target_tick = int(round(tgt_beat * target_tpb))
            pitch_expert = 96 + lane
            events_abs.append((target_tick, pitch_expert, lane, is_cym))

    # Remove duplicatas (mesma lane no mesmo tick) — comum em GM (crash1+crash2 simultâneos)
    seen = set()
    uniq = []
    for ev in sorted(events_abs):
        key = (ev[0], ev[2])
        if key in seen: continue
        seen.add(key); uniq.append(ev)

    # Emite track com notas Expert + tom markers (110/111/112) cobrindo ticks
    # onde a lane é tom (is_cym=False e lane in Y/B/G).
    # Estratégia simples: para cada nota tom Y/B/G, emite um marker de 1 tick
    # no mesmo tempo (Moonscraper vai interpretar como tom só nessa posição).
    # Para simplicidade inicial, emitimos marker com duração até a próxima
    # nota da mesma cor (ou fallback curto).
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="PART DRUMS", time=0))
    track.append(mido.MetaMessage("text", text="[mix 0 drums0]", time=0))

    # Eventos (abs_tick, msg)
    events = []
    for tick, pitch, lane, is_cym in uniq:
        events.append((tick,     mido.Message("note_on",  note=pitch, velocity=100, time=0)))
        events.append((tick + 1, mido.Message("note_off", note=pitch, velocity=0,   time=0)))

    # Tom markers: agrupar por lane
    by_lane = {LANE_YELLOW: [], LANE_BLUE: [], LANE_GREEN: []}
    for tick, pitch, lane, is_cym in uniq:
        if lane in by_lane and not is_cym:
            by_lane[lane].append(tick)
    tom_marker_pitch = {LANE_YELLOW: 110, LANE_BLUE: 111, LANE_GREEN: 112}
    for lane, ticks in by_lane.items():
        for t in sorted(set(ticks)):
            events.append((t,     mido.Message("note_on",  note=tom_marker_pitch[lane], velocity=100, time=0)))
            events.append((t + target_tpb // 8, mido.Message("note_off", note=tom_marker_pitch[lane], velocity=0, time=0)))

    events.sort(key=lambda e: e[0])
    last = 0
    for abs_t, msg in events:
        delta = abs_t - last
        track.append(msg.copy(time=delta))
        last = abs_t
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src_mid", help="MIDI externo (Songsterr/GP/MuseScore) contendo a bateria")
    ap.add_argument("ref_mid", help="notes.mid do chart (referência de guitarra alinhada ao áudio)")
    ap.add_argument("out_mid", help="onde gravar o chart resultante")
    args = ap.parse_args()

    src = mido.MidiFile(args.src_mid)
    ref = mido.MidiFile(args.ref_mid)

    ref_start = find_music_start_beat_ref(ref)
    src_start = find_music_start_beat_src(src)
    beat_offset = ref_start - src_start
    print(f"Início musical — ref: beat {ref_start:.2f}  src: beat {src_start:.2f}")
    print(f"Alinhamento: beat_ref = beat_src + {beat_offset:+.3f}")

    new_drums = build_drums_track(src, beat_offset, ref.ticks_per_beat)
    print(f"PART DRUMS gerado: {sum(1 for m in new_drums if m.type=='note_on' and m.velocity>0)} eventos")

    # Monta saída: clona a ref, substitui PART DRUMS
    out = mido.MidiFile(type=ref.type, ticks_per_beat=ref.ticks_per_beat)
    for t in ref.tracks:
        if t.name == "PART DRUMS":
            out.tracks.append(new_drums)
        else:
            out.tracks.append(t)
    # Se ref não tinha PART DRUMS, adiciona
    if not any(t.name == "PART DRUMS" for t in ref.tracks):
        out.tracks.append(new_drums)
    out.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

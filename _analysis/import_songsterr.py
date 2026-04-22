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

# Mapa base GM → (lane RB, is_cymbal) para pitches NÃO-tom. Os toms (GM 41,43,
# 45,47,48,50) são mapeados dinamicamente por _tom_pitch_to_lane() com base nos
# pitches efetivamente usados na track — isso evita colapsar dois toms distintos
# (ex: GM 48 Hi-Mid + GM 50 High) em uma mesma lane.
GM_TO_RB: Dict[int, Tuple[int, bool]] = {
    35: (LANE_KICK,   False),
    36: (LANE_KICK,   False),
    37: (LANE_SNARE,  False),
    38: (LANE_SNARE,  False),
    39: (LANE_SNARE,  False),
    40: (LANE_SNARE,  False),
    42: (LANE_YELLOW, True),    # closed hi-hat
    44: (LANE_YELLOW, True),    # pedal hi-hat
    46: (LANE_BLUE,   True),    # open hi-hat → blue cymbal em RB (override dinâmico)
    49: (LANE_GREEN,  True),    # crash 1
    51: (LANE_BLUE,   True),    # ride 1
    52: (LANE_GREEN,  True),    # china
    53: (LANE_BLUE,   True),    # ride bell
    55: (LANE_GREEN,  True),    # splash
    57: (LANE_GREEN,  True),    # crash 2
    59: (LANE_BLUE,   True),    # ride 2
}

TOM_PITCHES = (41, 43, 45, 47, 48, 50)  # todos os toms GM, ordenados crescente


def build_tom_pitch_map(drum_track) -> Dict[int, int]:
    """Retorna {pitch_gm → lane_rb} com base nos toms usados pela track.
       Regra: ordenar pitches usados DECRESCENTE (mais agudo primeiro) e
       distribuir por 3 lanes (Y=mais agudo, B=meio, G=floor) via particionamento.
    """
    used = set()
    for msg in drum_track:
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9 \
           and msg.note in TOM_PITCHES:
            used.add(msg.note)
    if not used:
        return {}
    sorted_desc = sorted(used, reverse=True)  # mais agudo primeiro
    n = len(sorted_desc)
    out = {}
    if n == 1:
        out[sorted_desc[0]] = LANE_YELLOW
    elif n == 2:
        out[sorted_desc[0]] = LANE_YELLOW
        out[sorted_desc[1]] = LANE_BLUE
    else:
        # Divide em 3 tercos
        third = n / 3
        for i, p in enumerate(sorted_desc):
            if i < round(third):
                out[p] = LANE_YELLOW
            elif i < round(2 * third):
                out[p] = LANE_BLUE
            else:
                out[p] = LANE_GREEN
    return out


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


def _first_drum_beat_ref(ref_mid: mido.MidiFile) -> float | None:
    """Primeira nota de bateria Expert do ref (se existir PART DRUMS). None se
    não há PART DRUMS com notas — caso típico em custom songs."""
    tpb = ref_mid.ticks_per_beat
    dt = next((t for t in ref_mid.tracks if t.name == "PART DRUMS"), None)
    if dt is None: return None
    abs_t = 0
    for msg in dt:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and 96 <= msg.note <= 100:
            return abs_t / tpb
    return None


def _first_drum_beat_src(src_mid: mido.MidiFile) -> float | None:
    """Primeira nota de bateria do src (canal 9) IGNORANDO side stick
    (GM 37 — típica contagem de baqueta)."""
    tpb = src_mid.ticks_per_beat
    for t in src_mid.tracks:
        if not any(m.type == "note_on" and m.channel == 9 and m.velocity > 0 for m in t):
            continue
        abs_t = 0
        for msg in t:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9 and msg.note != 37:
                return abs_t / tpb
    return None


def _first_guitar_beat_ref(ref_mid: mido.MidiFile) -> float | None:
    tpb = ref_mid.ticks_per_beat
    gt = next((t for t in ref_mid.tracks if t.name == "PART GUITAR"), None)
    if gt is None: return None
    abs_t = 0
    for msg in gt:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and 96 <= msg.note <= 100:
            return abs_t / tpb
    return None


def _first_guitar_beat_src(src_mid: mido.MidiFile) -> float | None:
    """Primeira nota de qualquer track cujo nome sugere guitarra/baixo.
    Ignora vocais e drums."""
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


def _collect_all_src_onsets(src_mid: mido.MidiFile) -> List[float]:
    """Onsets (em beats src) apenas das tracks de GUITARRA do src. Exclui
    bateria, baixo, piano, strings, vocais — aproximando a 'pool' ao conteúdo
    que a PART GUITAR do ref representa."""
    GUITAR_HINTS = ("guitar", "gibson", "ibanez", "iceman", "strat", "tele",
                    "fender", "electric", "rhythm", "lead", "acoustic", "j-200", "blues king")
    EXCLUDE = ("bass", "thunderbird", "piano", "yamaha u1", "string", "arrange",
               "vocal", "vocals")
    tpb = src_mid.ticks_per_beat
    out = []
    for t in src_mid.tracks:
        name = next((m.name for m in t if m.type == "track_name"), "").lower()
        if any(k in name for k in EXCLUDE): continue
        if not any(k in name for k in GUITAR_HINTS): continue
        abs_t = 0
        for msg in t:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel != 9:
                out.append(abs_t / tpb)
    return out


def _part_guitar_onsets_ref(ref_mid: mido.MidiFile) -> List[float]:
    tpb = ref_mid.ticks_per_beat
    gt = next((t for t in ref_mid.tracks if t.name == "PART GUITAR"), None)
    if gt is None: return []
    out = []
    abs_t = 0
    for msg in gt:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and 96 <= msg.note <= 100:
            out.append(abs_t / tpb)
    return out


def _density_by_bar(onsets: List[float], bar_beats: int = 4) -> List[int]:
    """Vetor de densidade por compasso (4 beats cada). Índice = número do
    compasso; valor = quantos onsets caíram dentro."""
    if not onsets: return []
    max_bar = int(max(onsets) // bar_beats) + 1
    v = [0] * max_bar
    for o in onsets:
        b = int(o // bar_beats)
        if 0 <= b < max_bar: v[b] += 1
    return v


def _cross_correlate(ref_v: List[int], src_v: List[int]) -> int:
    """Acha o deslocamento inteiro k que maximiza correlação de Pearson
    entre ref_v e src_v[k:k+len(ref_v)]. Retorna k em compassos."""
    nr, ns = len(ref_v), len(src_v)
    if nr == 0 or ns == 0: return 0
    import math
    rmean = sum(ref_v) / nr
    rcenter = [x - rmean for x in ref_v]
    rnorm = math.sqrt(sum(x*x for x in rcenter)) or 1.0

    best = (-2.0, 0)  # (correlation, k)
    k_min, k_max = -nr + 1, ns - 1  # faixa onde há ao menos 1 bar de overlap
    for k in range(k_min, k_max + 1):
        # Segmento do src alinhado: src[k..k+nr-1] (ou overlap parcial)
        lo = max(0, k); hi = min(ns, k + nr)
        if hi - lo < min(8, nr // 4): continue  # precisa overlap mínimo
        src_seg = src_v[lo:hi]
        ref_seg = rcenter[lo-k:hi-k]
        smean = sum(src_seg) / len(src_seg)
        scenter = [x - smean for x in src_seg]
        snorm = math.sqrt(sum(x*x for x in scenter)) or 1.0
        dot = sum(a*b for a,b in zip(ref_seg, scenter))
        corr = dot / (rnorm * snorm)
        if corr > best[0]: best = (corr, k)
    return best[1]


def align_by_guitar_stencil(ref_mid: mido.MidiFile, src_mid: mido.MidiFile,
                            bar_beats: int = 4) -> float:
    """Alinhamento por correlação de densidade por compasso. Neutraliza
    diferenças de quantização sub-beat preservando a estrutura macro da
    música (intro esparsa, verso médio, refrão denso, etc.)."""
    ref = _part_guitar_onsets_ref(ref_mid)
    src = _collect_all_src_onsets(src_mid)
    if not ref or not src: return 0.0
    ref_v = _density_by_bar(ref, bar_beats)
    src_v = _density_by_bar(src, bar_beats)
    k_bars = _cross_correlate(ref_v, src_v)
    # Offset em beats: ref_beat = src_beat + k*bar_beats
    # (se k > 0, ref começa k compassos à frente do src equivalente)
    return float(k_bars * bar_beats)


def resolve_alignment(ref_mid: mido.MidiFile, src_mid: mido.MidiFile,
                      override_offset: float | None = None) -> Tuple[float, float, str]:
    """Resolve (beat_offset, src_anchor_beat, method).

    CASO REAL (custom): ref só tem PART GUITAR, src é MIDI externo.
    Default: alinha primeira nota de PART GUITAR ref com primeira nota de
    qualquer track de guitarra/baixo do src. Funciona quando o chart CH
    charteia a intro (mesmo início que o Songsterr).

    Quando falha (ex: Toxicity — Songsterr tem acústica que a custom não
    inclui), passar `--offset-beats N` manual após ver no Moonscraper.
    """
    if override_offset is not None:
        src_anchor = _first_guitar_beat_src(src_mid) or 0.0
        return override_offset, src_anchor, "override"
    ref_gt = _first_guitar_beat_ref(ref_mid)
    src_gt = _first_guitar_beat_src(src_mid)
    if ref_gt is not None and src_gt is not None:
        return (ref_gt - src_gt), src_gt, "guitar-first"
    return 0.0, 0.0, "fallback-zero"


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


def _build_anchor_pairs(ref_mid: mido.MidiFile, src_mid: mido.MidiFile,
                        ref_tm, src_tm, beat_offset_sec: float,
                        max_gap_sec: float = 0.8) -> List[Tuple[float, float]]:
    """Constrói pares (src_sec, ref_sec) de correspondência entre onsets da
    PART GUITAR do ref e onsets das guitarras do src, usando greedy monotônico.

    Cada nota da PART GUITAR ref procura a mais próxima no src (após aplicar
    offset) dentro de max_gap_sec. Se achar e ainda for temporalmente coerente
    com pares anteriores, vira âncora."""
    # Colapsa acordes (Songsterr emite cada corda individualmente)
    ref_onsets = _collapse_chords(
        [tick_to_seconds(t, ref_tm) for t in _part_guitar_tick_onsets(ref_mid)],
        eps=0.03)
    src_onsets = _collapse_chords(
        [tick_to_seconds(t, src_tm) for t in _src_guitar_tick_onsets(src_mid)],
        eps=0.03)
    if not ref_onsets or not src_onsets: return []

    pairs: List[Tuple[float, float]] = [(0.0, beat_offset_sec)]  # âncora inicial
    src_sorted = sorted(src_onsets)
    last_src, last_ref = 0.0, beat_offset_sec
    for r in sorted(ref_onsets):
        expected_src = last_src + (r - last_ref)  # estimativa linear do src correspondente
        # Busca src mais próximo à expected_src dentro de ±max_gap
        lo = bisect.bisect_left(src_sorted, expected_src - max_gap_sec)
        hi = bisect.bisect_right(src_sorted, expected_src + max_gap_sec)
        best_s = None; best_d = max_gap_sec + 1
        for j in range(lo, hi):
            s = src_sorted[j]
            if s <= last_src: continue  # monotônico
            d = abs(s - expected_src)
            if d < best_d: best_d = d; best_s = s
        if best_s is not None:
            pairs.append((best_s, r))
            last_src, last_ref = best_s, r
    return pairs


def _part_guitar_tick_onsets(ref_mid: mido.MidiFile) -> List[int]:
    tpb = ref_mid.ticks_per_beat
    gt = next((t for t in ref_mid.tracks if t.name == "PART GUITAR"), None)
    if gt is None: return []
    out = []; abs_t = 0
    for msg in gt:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and 96 <= msg.note <= 100:
            out.append(abs_t)
    return out


def _src_guitar_tick_onsets(src_mid: mido.MidiFile) -> List[int]:
    """Onsets (ticks) de todas as tracks de guitarra do src."""
    HINTS = ("guitar", "gibson", "ibanez", "iceman", "strat", "tele", "fender")
    EXCLUDE = ("bass","thunderbird","vocal","piano","string","arrange","drums")
    out = []
    for t in src_mid.tracks:
        name = next((m.name for m in t if m.type=="track_name"), "").lower()
        if any(k in name for k in EXCLUDE): continue
        if not any(k in name for k in HINTS): continue
        abs_t = 0
        for msg in t:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel != 9:
                out.append(abs_t)
    return sorted(out)


def _interpolate_time(src_sec: float, pairs: List[Tuple[float, float]]) -> float:
    """Interpola o tempo ref_sec correspondente a src_sec usando o conjunto
    piecewise-linear de pares âncora. Extrapola linearmente fora do range."""
    if not pairs: return src_sec
    src_vals = [p[0] for p in pairs]
    # bisect para achar segmento
    idx = bisect.bisect_left(src_vals, src_sec)
    if idx == 0:
        # Extrapola usando primeiro segmento
        if len(pairs) >= 2:
            s0, r0 = pairs[0]; s1, r1 = pairs[1]
            if s1 > s0:
                return r0 + (src_sec - s0) * (r1 - r0) / (s1 - s0)
        return pairs[0][1] + (src_sec - pairs[0][0])
    if idx >= len(pairs):
        s0, r0 = pairs[-2]; s1, r1 = pairs[-1]
        if s1 > s0:
            return r1 + (src_sec - s1) * (r1 - r0) / (s1 - s0)
        return r1 + (src_sec - s1)
    s0, r0 = pairs[idx-1]; s1, r1 = pairs[idx]
    if s1 == s0: return r0
    return r0 + (src_sec - s0) * (r1 - r0) / (s1 - s0)


def _sec_to_tick(sec: float, tempo_map: List[Tuple[int, float]]) -> int:
    """Inverse de tick_to_seconds usando o mesmo mapa."""
    if sec <= 0: return 0
    cur_sec = 0.0
    for (t0, spt), (t1, _) in zip(tempo_map, tempo_map[1:] + [(10**9, 0.0)]):
        seg_sec = (t1 - t0) * spt
        if cur_sec + seg_sec >= sec:
            return t0 + int((sec - cur_sec) / spt) if spt > 0 else t0
        cur_sec += seg_sec
    return tempo_map[-1][0] + int((sec - cur_sec) / tempo_map[-1][1]) if tempo_map[-1][1] > 0 else tempo_map[-1][0]


def _guitar_duration_sec(mid: mido.MidiFile, tempo_map, tracks_filter=None) -> Tuple[float, float]:
    """Devolve (sec_first_note, sec_last_note) para tracks filtradas."""
    first = None; last = None
    for t in mid.tracks:
        if tracks_filter and not tracks_filter(t): continue
        abs_t = 0
        for msg in t:
            abs_t += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel != 9:
                s = tick_to_seconds(abs_t, tempo_map)
                if first is None or s < first: first = s
                if last is None or s > last: last = s
    return (first or 0.0, last or 0.0)


def build_drums_track(src_mid: mido.MidiFile, beat_offset: float,
                      target_tpb: int, drop_before_src_beat: float = 0.0,
                      ref_tempo_map=None, time_scale: float = 1.0,
                      sync_mode: str = "auto",
                      dedup_beats: float = 1/16,
                      ref_mid: "mido.MidiFile | None" = None) -> mido.MidiTrack:
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

    # Classifica o papel do open hi-hat (GM 46) na música inteira:
    #   - Se open domina (>= 70% do total de hi-hat events), é "hi-hat folgado"
    #     (sustain wash): vai pra Y-cym (amarelo).
    #   - Senão, open tipicamente representa ride ou accent e vai pra B-cym (azul).
    #     Nesse modo, ainda fazemos fallback contextual: se um open aparece em
    #     cluster onde só tem open (sem closed próximo), mantém Y-cym.
    n_closed = sum(1 for msg in drum_track
                   if msg.type == "note_on" and msg.velocity > 0
                   and msg.channel == 9 and msg.note == 42)
    n_open = sum(1 for msg in drum_track
                 if msg.type == "note_on" and msg.velocity > 0
                 and msg.channel == 9 and msg.note == 46)
    total_hh = n_closed + n_open
    open_mode_yellow = total_hh > 0 and (n_open / total_hh) >= 0.70
    # print útil para diagnóstico
    print(f"Hi-hat Songsterr: {n_closed} closed, {n_open} open  "
          f"→ open vai pra {'Y-cym (amarelo, dominante)' if open_mode_yellow else 'B-cym (azul, ride/accent)'}")

    src_tm = _tempo_map(src_mid.tracks[0], src_tpb)
    # Auto: escolhe "beat" se BPMs batem aproximadamente, "sec" se divergem.
    if sync_mode == "auto":
        def _bpm_avg(tm):
            if len(tm) < 2: return 60.0 / (tm[0][1] * src_tpb if tm else 500000 / 1_000_000)
            # tempo map é (tick, sec_per_tick). bpm = 60 / (sec_per_tick * tpb)
            avgs = [60 / (spt * (src_tpb if tm is src_tm else target_tpb))
                    for _, spt in tm]
            return sum(avgs) / len(avgs)
        # razão BPM — se |razão - 1| > 0.15, usa sec-mode (BPMs divergem)
        try:
            bpm_src = _bpm_avg(src_tm); bpm_ref = _bpm_avg(ref_tempo_map)
            ratio = bpm_src / bpm_ref if bpm_ref > 0 else 1.0
            sync_mode = "sec" if abs(ratio - 1.0) > 0.15 else "beat"
        except Exception:
            sync_mode = "beat"

    # Flam detection — pares mesma-lane+cymbal com gap ≤ dedup_beats.
    # Default 1/16 beat (~30ms). Tratamento por lane:
    #   - Snare: segunda nota vira Y-tom (preserva sensação de baqueta dupla
    #     como "vermelho+amarelo").
    #   - Outras lanes: segunda nota descartada (simples dedup).
    # Mapeamento dinâmico de toms (48, 50, 45... → Y/B/G) baseado nos pitches
    # efetivamente usados na track de bateria do src.
    tom_lane_map = build_tom_pitch_map(drum_track)

    def _resolve_lane(pitch: int) -> Tuple[int, bool]:
        """Retorna (lane, is_cymbal) considerando open-hat mode e tom map."""
        if pitch in tom_lane_map:
            return (tom_lane_map[pitch], False)
        if pitch == 46:
            return (LANE_YELLOW if open_mode_yellow else LANE_BLUE, True)
        return GM_TO_RB.get(pitch, (None, None))

    dedup_gap_ticks = int(round(src_tpb * dedup_beats))
    last_tick_by_lane: Dict[Tuple[int, bool], int] = {}
    # Chave usa (tick, pitch) — não só tick — porque várias lanes podem compartilhar
    # o mesmo tick (ex: crash+kick simultâneos, que NÃO é flam).
    dedup_skipped: set = set()          # {(tick, pitch)}
    flam_snare_second: set = set()      # {(tick, pitch)}
    abs_src = 0
    for msg in drum_track:
        abs_src += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
            lane_raw, is_cym_raw = _resolve_lane(msg.note)
            if lane_raw is None: continue
            key = (lane_raw, is_cym_raw)
            last = last_tick_by_lane.get(key)
            if last is not None and abs_src - last <= dedup_gap_ticks:
                if lane_raw == LANE_SNARE:
                    flam_snare_second.add((abs_src, msg.note))
                    last_tick_by_lane[key] = abs_src
                else:
                    dedup_skipped.add((abs_src, msg.note))
            else:
                last_tick_by_lane[key] = abs_src

    abs_src = 0
    events_abs = []
    if sync_mode == "sec":
        anchor_src_sec = tick_to_seconds(int(drop_before_src_beat * src_tpb), src_tm)
        anchor_ref_tick = int((drop_before_src_beat + beat_offset) * target_tpb)
        anchor_ref_sec = tick_to_seconds(anchor_ref_tick, ref_tempo_map)
        # Multi-anchor: se ref_mid fornecido, usa guitarra do ref como ground
        # truth de tempo ao longo da música; interpola piecewise-linear.
        # Multi-anchor (opcional): alinha guitarra ref ↔ guitarra src ao longo
        # da música. Desabilitado por padrão — matches falsos nas guitarras
        # Songsterr introduzem ruído. Ativar apenas se quiser experimentar.
        anchor_pairs = []
        if ref_mid is not None and os.environ.get("IMPORT_MULTI_ANCHOR") == "1":
            anchor_pairs = _build_anchor_pairs(
                ref_mid, src_mid, ref_tempo_map, src_tm,
                beat_offset_sec=(anchor_ref_sec - anchor_src_sec))
            print(f"  {len(anchor_pairs)} âncoras guitar↔guitar construídas")
        for msg in drum_track:
            abs_src += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
                if (abs_src, msg.note) in dedup_skipped: continue
                if abs_src / src_tpb < drop_before_src_beat: continue
                src_sec = tick_to_seconds(abs_src, src_tm)
                if anchor_pairs:
                    target_sec = _interpolate_time(src_sec, anchor_pairs)
                else:
                    target_sec = anchor_ref_sec + time_scale * (src_sec - anchor_src_sec)
                if target_sec < 0: continue
                lane, is_cym = _resolve_lane(msg.note)
                if lane is None: continue
                if (abs_src, msg.note) in flam_snare_second:
                    lane, is_cym = LANE_YELLOW, False
                target_tick = _sec_to_tick(target_sec, ref_tempo_map)
                events_abs.append((target_tick, 96 + lane, lane, is_cym))
    else:  # "beat" mode
        for msg in drum_track:
            abs_src += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
                if (abs_src, msg.note) in dedup_skipped: continue
                src_beat = abs_src / src_tpb
                if src_beat < drop_before_src_beat: continue
                tgt_beat = src_beat + beat_offset
                if tgt_beat < 0: continue
                lane, is_cym = _resolve_lane(msg.note)
                if lane is None: continue
                if (abs_src, msg.note) in flam_snare_second:
                    lane, is_cym = LANE_YELLOW, False
                target_tick = int(round(tgt_beat * target_tpb))
                events_abs.append((target_tick, 96 + lane, lane, is_cym))

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
    ap.add_argument("--offset-beats", type=float, default=None,
                    help="override manual do offset em beats (ref = src + N)")
    ap.add_argument("--drop-before-src-beat", type=float, default=None,
                    help="override: dropa notas src antes deste beat")
    ap.add_argument("--time-scale", type=float, default=None,
                    help="escala temporal src→ref em sync-mode=sec. Default: auto "
                         "(razão de durações das guitarras ref/src).")
    ap.add_argument("--sync-mode", choices=("auto", "beat", "sec"), default="auto",
                    help="auto (default): beat-mode se BPMs batem, sec-mode caso contrário. "
                         "beat: preserva posição em beats musicais. "
                         "sec: preserva posição em segundos (bom quando tempo map do src é correto).")
    ap.add_argument("--dedup-beats", type=float, default=1/16,
                    help="pares mesma-lane com gap ≤ N beats viram 1 nota (flams). Default 1/16.")
    args = ap.parse_args()

    src = mido.MidiFile(args.src_mid)
    ref = mido.MidiFile(args.ref_mid)

    beat_offset, src_anchor, method = resolve_alignment(ref, src, args.offset_beats)
    drop_beat = args.drop_before_src_beat if args.drop_before_src_beat is not None else src_anchor
    ref_tm = _tempo_map(ref.tracks[0], ref.ticks_per_beat)
    src_tm = _tempo_map(src.tracks[0], src.ticks_per_beat)

    # Escala temporal: por padrão calculada pela razão de durações das
    # guitarras (primeira↔primeira, última↔última de ref vs src). Corrige
    # drift linear quando o tempo map do Songsterr não bate perfeitamente
    # com o áudio.
    if args.time_scale is not None:
        time_scale = args.time_scale
        scale_src = "override"
    else:
        ref_onsets_sec = [tick_to_seconds(t, ref_tm) for t in _part_guitar_tick_onsets(ref)]
        src_onsets_sec = [tick_to_seconds(t, src_tm) for t in _src_guitar_tick_onsets(src)]
        if len(ref_onsets_sec) >= 2 and len(src_onsets_sec) >= 2:
            dur_ref = max(ref_onsets_sec) - min(ref_onsets_sec)
            dur_src = max(src_onsets_sec) - min(src_onsets_sec)
            time_scale = dur_ref / dur_src if dur_src > 0 else 1.0
            scale_src = f"auto (dur_ref={dur_ref:.1f}s / dur_src={dur_src:.1f}s)"
        else:
            time_scale = 1.0
            scale_src = "default=1.0"

    print(f"Alinhamento ({method}): beat_ref = beat_src + {beat_offset:+.3f}"
          f"  drop antes de src_beat {drop_beat:.2f}")
    print(f"Escala temporal: {time_scale:.4f} [{scale_src}]")

    new_drums = build_drums_track(src, beat_offset, ref.ticks_per_beat,
                                  drop_before_src_beat=drop_beat,
                                  ref_tempo_map=ref_tm, time_scale=time_scale,
                                  sync_mode=args.sync_mode,
                                  dedup_beats=args.dedup_beats,
                                  ref_mid=ref)

    # Diagnóstico: beats/seg da primeira drum gerada (usuário pode checar no Moonscraper)
    ref_tm = _tempo_map(ref.tracks[0], ref.ticks_per_beat)
    drum_ticks = [m.note for m in new_drums if m.type=="note_on" and m.velocity>0]  # placeholder
    abs_t = 0; first_drum_tick = None
    for m in new_drums:
        abs_t += m.time
        if m.type == "note_on" and m.velocity > 0 and 96 <= m.note <= 100:
            first_drum_tick = abs_t; break
    if first_drum_tick is not None:
        print(f"  → 1ª drum gerada: tick={first_drum_tick} beat={first_drum_tick/ref.ticks_per_beat:.2f} "
              f"sec={tick_to_seconds(first_drum_tick, ref_tm):.2f}")
    print(f"  Se o áudio não bater: ajuste com --offset-beats N (positivo atrasa no target, negativo adianta)")
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

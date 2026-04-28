"""
Parser de PART DRUMS — Harmonix RB MIDI / Clone Hero.

Estrutura confirmada nas 6 músicas SOAD:

Pitches por dificuldade (Kick / Snare / Yellow / Blue / Green):
    Terminologia: amarelo = tipicamente hi-hat, azul = ride, verde = crash.
    Easy   : 60, 61, 62, 63, 64
    Medium : 72, 73, 74, 75, 76
    Hard   : 84, 85, 86, 87, 88
    Expert : 96, 97, 98, 99, 100
Pitch 95 = 2x bass pedal (Expert+) — kick adicional para "double bass" mode.

Pro Drums tom markers (frase-marker, dura vários beats):
    110 = Yellow lane = TOM (tambor) durante o intervalo on/off
    111 = Blue   lane = TOM
    112 = Green  lane = TOM
    Quando OFF (padrão), Y/B/G são PRATO (cymbal). Convenção RBN/RB3+:
    notas amarelas/azuis/verdes são pratos por padrão, e o marker converte
    para tom somente no intervalo em que está ativo.
    Estes flags só afetam Hard e Expert (E/M não exibem cymbal vs tom no
    jogo padrão, mas CH/Moonscraper preserva a distinção).

Marcadores de track (compartilhados entre dificuldades):
    105/106 = Player 1/Player 2 (RB1) ou solo markers
    116     = Overdrive (Star Power)
    120-124 = Drum fill / BRE (5 pitches simultâneos formam 1 fill)
    127     = (raro)

Animações (ignorar para chart):
    24      = kick foot animation
    25-51   = stick/hand animations no kit

Velocity:
    100 padrão (todas as notas das charts SOAD usam vel=100).
    Em RB3+ podem aparecer vel=127 (accent) e vel=1-50 (ghost) — não vimos nas SOAD.

Text events em PART DRUMS:
    [mix N drumsK...] = mix automix marker (qual stem audio tocar)
    [idle], [intense], [play], etc. = drummer animations de palco
    Não afetam a chart de notas.
"""
from __future__ import annotations
import mido
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional

DIFF_BASE_DRUMS = {"Easy": 60, "Medium": 72, "Hard": 84, "Expert": 96}
LANE_NAMES = ["Kick", "Snare", "Yellow", "Blue", "Green"]
LANE_KICK, LANE_SNARE, LANE_YELLOW, LANE_BLUE, LANE_GREEN = 0, 1, 2, 3, 4

TOM_FLAG_PITCHES = {LANE_YELLOW: 110, LANE_BLUE: 111, LANE_GREEN: 112}


def remove_blue_cymbal_when_green_cymbal_co_occurs(notes: List[Any]) -> List[Any]:
    """
    If blue cymbal and green cymbal appear on the same tick, drop the blue cymbal.
    Kick/snare/yellow and any tom hits are unchanged.
    """
    if not notes:
        return notes
    by_tick: Dict[int, List[int]] = defaultdict(list)
    for i, n in enumerate(notes):
        by_tick[n.tick].append(i)
    drop: set[int] = set()
    for idxs in by_tick.values():
        has_green_cymbal = any(
            notes[j].lane == LANE_GREEN and notes[j].is_cymbal for j in idxs
        )
        if not has_green_cymbal:
            continue
        for j in idxs:
            m = notes[j]
            if m.lane == LANE_BLUE and m.is_cymbal:
                drop.add(j)
    return [n for i, n in enumerate(notes) if i not in drop]


@dataclass
class DrumNote:
    tick: int
    # 0=Kick, 1=Snare, 2/3/4 = Y/B/G (Y hi-hat, B ride, G crash in Pro Drums)
    lane: int
    is_cymbal: bool = False  # only Y/B/G (cymbal vs tom)
    is_2x_kick: bool = False
    velocity: int = 100

    @property
    def lane_name(self) -> str:
        n = LANE_NAMES[self.lane]
        if self.lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN):
            return f"{n}{'-cym' if self.is_cymbal else '-tom'}"
        return n


@dataclass
class DrumChart:
    difficulty: str
    ticks_per_beat: int
    notes: List[DrumNote] = field(default_factory=list)
    overdrive: List[Tuple[int, int]] = field(default_factory=list)
    drum_fills: List[Tuple[int, int]] = field(default_factory=list)
    cymbal_flags: Dict[int, List[Tuple[int, int]]] = field(default_factory=dict)
    # (tick, numerator, denominator) from MIDI; denominator is notated value (2,4,8,…).
    time_signatures: List[Tuple[int, int, int]] = field(default_factory=lambda: [(0, 4, 4)])


def collect_time_signatures_from_midi_file(mid: mido.MidiFile) -> List[Tuple[int, int, int]]:
    out: List[Tuple[int, int, int]] = []
    for tr in mid.tracks:
        t = 0
        for msg in tr:
            t += msg.time
            if msg.is_meta and msg.type == "time_signature":
                out.append((t, int(msg.numerator), int(msg.denominator)))
    out.sort(key=lambda x: x[0])
    if not out:
        return [(0, 4, 4)]
    return out


def _decode_note_pairs(track):
    abs_t = 0
    open_notes: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    out = []  # (start, end, pitch, vel)
    for msg in track:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes[msg.note].append((abs_t, msg.velocity))
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            if open_notes[msg.note]:
                start, vel = open_notes[msg.note].pop(0)
                out.append((start, abs_t, msg.note, vel))
    return out


def parse_drums(mid: mido.MidiFile) -> Dict[str, DrumChart]:
    """Devolve {difficulty -> DrumChart}."""
    track = next((t for t in mid.tracks if t.name == "PART DRUMS"), None)
    if track is None: return {}

    pairs = _decode_note_pairs(track)
    tpb = mid.ticks_per_beat

    # Markers compartilhados
    overdrive: List[Tuple[int, int]] = []
    drum_fills: List[Tuple[int, int]] = []
    tom_intervals: Dict[int, List[Tuple[int, int]]] = {LANE_YELLOW: [], LANE_BLUE: [], LANE_GREEN: []}
    fill_starts: Dict[int, List[int]] = defaultdict(list)
    for s, e, p, v in pairs:
        if p == 116:
            overdrive.append((s, e))
        elif p == 110:
            tom_intervals[LANE_YELLOW].append((s, e))
        elif p == 111:
            tom_intervals[LANE_BLUE].append((s, e))
        elif p == 112:
            tom_intervals[LANE_GREEN].append((s, e))
        elif 120 <= p <= 124:
            fill_starts[p].append((s, e))
    if fill_starts.get(120):
        for (s, e) in fill_starts[120]:
            drum_fills.append((s, e))

    # Convenção Pro Drums: Y/B/G são PRATO por padrão; marker 110/111/112 ativa
    # converte a mesma cor em TOM naquele intervalo.
    def in_tom_marker(tick: int, lane: int) -> bool:
        if lane not in (LANE_YELLOW, LANE_BLUE, LANE_GREEN): return False
        for s, e in tom_intervals[lane]:
            if s <= tick < e: return True
        return False

    time_sigs = collect_time_signatures_from_midi_file(mid)
    charts: Dict[str, DrumChart] = {}
    for diff, base in DIFF_BASE_DRUMS.items():
        c = DrumChart(
            difficulty=diff,
            ticks_per_beat=tpb,
            overdrive=overdrive,
            drum_fills=drum_fills,
            cymbal_flags=tom_intervals,  # keeps field name for compat
            time_signatures=time_sigs,
        )
        for s, e, p, v in pairs:
            offset = p - base
            if 0 <= offset <= 4:
                lane = offset
                # Y/B/G: default=cymbal, marker=tom
                if lane in (LANE_YELLOW, LANE_BLUE, LANE_GREEN):
                    is_cym = not in_tom_marker(s, lane)
                else:
                    is_cym = False
                c.notes.append(DrumNote(tick=s, lane=lane, is_cymbal=is_cym, velocity=v))
            elif p == 95 and diff == "Expert":
                c.notes.append(DrumNote(tick=s, lane=LANE_KICK, is_2x_kick=True, velocity=v))
        c.notes.sort(key=lambda n: (n.tick, n.lane))
        c.notes = remove_blue_cymbal_when_green_cymbal_co_occurs(c.notes)
        charts[diff] = c
    return charts


def chart_summary(c: DrumChart) -> dict:
    """Resumo: contagem por lane (com cymbal/tom split em Y/B/G)."""
    counts = defaultdict(int)
    for n in c.notes:
        counts[n.lane_name] += 1
    return dict(counts)


if __name__ == "__main__":
    import glob, os
    base = "songs/harmonix"
    for f in sorted(glob.glob(f"{base}/System*")):
        name = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        ch = parse_drums(mid)
        print(f"\n=== {name} ===")
        for diff in ("Easy","Medium","Hard","Expert"):
            s = chart_summary(ch[diff])
            tot = sum(s.values())
            print(f"  {diff:6s} total={tot:4d}  {dict(s)}")
        print(f"  cymbal_flags: Y={len(ch['Expert'].cymbal_flags[LANE_YELLOW])} "
              f"B={len(ch['Expert'].cymbal_flags[LANE_BLUE])} "
              f"G={len(ch['Expert'].cymbal_flags[LANE_GREEN])}")
        print(f"  overdrive_phrases={len(ch['Expert'].overdrive)}  drum_fills={len(ch['Expert'].drum_fills)}")

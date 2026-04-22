"""
Harmonix RB-format MIDI parser for Clone Hero charts.

Per-instrument tracks (PART GUITAR / PART BASS / PART DRUMS / PART VOCALS).
Per-difficulty note ranges within a 5-fret part:
    Easy   : open=58, G=60, R=61, Y=62, B=63, O=64, ForceHOPO_on=65, ForceHOPO_off=66
    Medium : open=70, G=72, R=73, Y=74, B=75, O=76, ForceHOPO_on=77, ForceHOPO_off=78
    Hard   : open=82, G=84, R=85, Y=86, B=87, O=88, ForceHOPO_on=89, ForceHOPO_off=90
    Expert : open=94, G=96, R=97, Y=98, B=99, O=100,ForceHOPO_on=101,ForceHOPO_off=102
Common markers: 103=SP(rb2)|Solo(rb1 alt), 104=Tap(CH), 105/106=P1/P2 (RB1) or Solo,
                108=Lyric phrase, 116=Overdrive/StarPower, 120-124=BRE/Drum-fill,
                40-59=hand-position animations (ignored for chart logic).
"""
from __future__ import annotations
import mido
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

DIFF_BASE = {"Easy": 60, "Medium": 72, "Hard": 84, "Expert": 96}
FRET_NAMES = ["G", "R", "Y", "B", "O"]  # offset 0..4 from base

@dataclass
class Note:
    """One playable gem on the chart."""
    tick: int           # start tick (absolute)
    end_tick: int       # end tick (absolute) — for sustain length
    frets: Tuple[int, ...]  # fret indices 0..4 played simultaneously; () == open strum
    is_open: bool = False   # True if this is an open-strum (no fret)
    forced_hopo: int = 0    # +1 force-hopo-on, -1 force-hopo-off, 0 none
    is_tap: bool = False    # CH tap marker (pitch 104)

    @property
    def is_chord(self) -> bool:
        return len(self.frets) > 1

    @property
    def duration(self) -> int:
        return self.end_tick - self.tick

@dataclass
class Chart:
    """All notes for one (instrument, difficulty) pair, plus part-level markers."""
    instrument: str
    difficulty: str
    ticks_per_beat: int
    notes: List[Note] = field(default_factory=list)
    overdrive: List[Tuple[int, int]] = field(default_factory=list)  # (start,end) tick ranges
    solos: List[Tuple[int, int]] = field(default_factory=list)
    tempos: List[Tuple[int, int]] = field(default_factory=list)     # (tick, tempo_us_per_beat)
    time_sigs: List[Tuple[int, int, int]] = field(default_factory=list)  # (tick, num, denom)


def _decode_note_pairs(track):
    """Yield (start_tick, end_tick, pitch) for every note on/off pair in order."""
    abs_t = 0
    open_notes: Dict[int, List[int]] = defaultdict(list)
    out: List[Tuple[int,int,int]] = []
    for msg in track:
        abs_t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes[msg.note].append(abs_t)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            if open_notes[msg.note]:
                start = open_notes[msg.note].pop(0)
                out.append((start, abs_t, msg.note))
    return out


def parse_part(mid: mido.MidiFile, part_name: str) -> Dict[str, Chart]:
    """Return {difficulty -> Chart} for the named PART track."""
    track = next((t for t in mid.tracks if t.name == part_name), None)
    if track is None:
        return {}

    pairs = _decode_note_pairs(track)

    # Tempo / time-sig from track 0 (conductor track).
    tempos, sigs = [], []
    abs_t = 0
    for msg in mid.tracks[0]:
        abs_t += msg.time
        if msg.type == "set_tempo":
            tempos.append((abs_t, msg.tempo))
        elif msg.type == "time_signature":
            sigs.append((abs_t, msg.numerator, msg.denominator))

    # Part-level markers (overdrive=116, solos=103/105/106).
    overdrive: List[Tuple[int,int]] = []
    solos: List[Tuple[int,int]] = []
    for s, e, p in pairs:
        if p == 116:
            overdrive.append((s, e))
        elif p in (103, 105):
            solos.append((s, e))

    # Build per-difficulty charts.
    charts: Dict[str, Chart] = {}
    for diff, base in DIFF_BASE.items():
        c = Chart(instrument=part_name, difficulty=diff, ticks_per_beat=mid.ticks_per_beat,
                  overdrive=overdrive, solos=solos, tempos=tempos, time_sigs=sigs)
        # Group simultaneous fret events at the same tick into chords.
        gem_buckets: Dict[int, List[Tuple[int,int]]] = defaultdict(list)  # tick -> [(fret, end_tick)]
        force_on: List[int] = []
        force_off: List[int] = []
        opens: List[Tuple[int,int]] = []
        for s, e, p in pairs:
            offset = p - base
            if 0 <= offset <= 4:
                gem_buckets[s].append((offset, e))
            elif offset == -2:  # open strum
                opens.append((s, e))
            elif offset == 5:
                force_on.append(s)
            elif offset == 6:
                force_off.append(s)
        # Convert buckets to Note list
        for tick in sorted(gem_buckets):
            gems = gem_buckets[tick]
            frets = tuple(sorted(g[0] for g in gems))
            end = max(g[1] for g in gems)
            n = Note(tick=tick, end_tick=end, frets=frets)
            if tick in force_on: n.forced_hopo = +1
            elif tick in force_off: n.forced_hopo = -1
            c.notes.append(n)
        for s, e in opens:
            n = Note(tick=s, end_tick=e, frets=(), is_open=True)
            c.notes.append(n)
        c.notes.sort(key=lambda n: n.tick)
        charts[diff] = c
    return charts


def chart_summary(c: Chart) -> dict:
    notes = c.notes
    total = len(notes)
    chords = sum(1 for n in notes if n.is_chord)
    sustains = sum(1 for n in notes if n.duration >= c.ticks_per_beat // 4)  # ≥ 16th
    fret_use = defaultdict(int)
    chord_size = defaultdict(int)
    for n in notes:
        for f in n.frets: fret_use[FRET_NAMES[f]] += 1
        chord_size[len(n.frets)] += 1
    return dict(
        total_notes=total,
        chords=chords,
        single_notes=total - chords,
        sustain_count=sustains,
        fret_use=dict(fret_use),
        chord_size=dict(chord_size),
    )


if __name__ == "__main__":
    import sys, json, glob, os
    base = "/Users/gabrielcarvalho/Downloads/system"
    folders = sorted(glob.glob(f"{base}/System*"))
    for f in folders:
        song = os.path.basename(f).replace("System of a Down - ","").replace(" (Harmonix)","")
        mid = mido.MidiFile(os.path.join(f, "notes.mid"))
        charts = parse_part(mid, "PART GUITAR")
        print(f"\n=== {song} :: PART GUITAR ===")
        for diff in ["Easy","Medium","Hard","Expert"]:
            s = chart_summary(charts[diff])
            print(f"  {diff:6s} notes={s['total_notes']:4d}  chords={s['chords']:4d}  "
                  f"sus={s['sustain_count']:4d}  frets={s['fret_use']}  chord_size={s['chord_size']}")

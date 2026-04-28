"""
Harmonix RB-format MIDI parser for Clone Hero charts.

Per-instrument tracks (PART GUITAR / PART BASS / PART DRUMS / PART VOCALS).
Per-difficulty guitar gems (PART GUITAR): ``N 7`` (open in .chart) is exported as **green**
(same MIDI pitch as ``N 0``) for Clone Hero compatibility.
    Easy   : G=60, R=61, Y=62, B=63, O=64, ForceHOPO_on=65, ForceHOPO_off=66
    Medium : G=72, R=73, Y=74, B=75, O=76, ForceHOPO_on=77, ForceHOPO_off=78
    Hard   : G=84, R=85, Y=86, B=87, O=88, ForceHOPO_on=89, ForceHOPO_off=90
    Expert : G=96, R=97, Y=98, B=99, O=100,ForceHOPO_on=101,ForceHOPO_off=102
Common markers: 103=SP(rb2)|Solo(rb1 alt), 104=Tap(CH), 105/106=P1/P2 (RB1) or Solo,
                108=Lyric phrase, 116=Overdrive/StarPower, 120-124=BRE/Drum-fill,
                40-59=hand-position animations (ignored for chart logic).
"""
from __future__ import annotations
import mido
import re
from bisect import bisect_right
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
    frets: Tuple[int, ...]  # fret indices 0..4 played simultaneously
    is_open: bool = False   # legacy: true only if sourced from MIDI that still marks open separately
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


@dataclass
class TempoMap:
    """Converts MIDI ticks <-> seconds respecting tempo changes."""
    ticks_per_beat: int
    change_ticks: List[int]
    change_seconds: List[float]
    tempos: List[int]

    def tick_to_seconds(self, tick: int) -> float:
        idx = bisect_right(self.change_ticks, tick) - 1
        idx = max(idx, 0)

        base_tick = self.change_ticks[idx]
        base_seconds = self.change_seconds[idx]
        tempo = self.tempos[idx]

        return base_seconds + mido.tick2second(tick - base_tick, self.ticks_per_beat, tempo)

    def seconds_to_tick(self, seconds: float) -> int:
        idx = bisect_right(self.change_seconds, seconds) - 1
        idx = max(idx, 0)

        base_tick = self.change_ticks[idx]
        base_seconds = self.change_seconds[idx]
        tempo = self.tempos[idx]

        delta_tick = mido.second2tick(seconds - base_seconds, self.ticks_per_beat, tempo)

        return int(round(base_tick + delta_tick))


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


def read_conductor_track(mid: mido.MidiFile) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int, int]]]:
    """Lê track 0 e devolve tempo map + time signatures."""
    tempos: List[Tuple[int, int]] = []
    sigs: List[Tuple[int, int, int]] = []
    abs_t = 0

    for msg in mid.tracks[0]:
        abs_t += msg.time

        if msg.type == "set_tempo":
            if tempos and tempos[-1][0] == abs_t:
                tempos[-1] = (abs_t, msg.tempo)
            else:
                tempos.append((abs_t, msg.tempo))
        elif msg.type == "time_signature":
            sigs.append((abs_t, msg.numerator, msg.denominator))

    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, 500000))

    return tempos, sigs


def build_tempo_map(mid: mido.MidiFile) -> TempoMap:
    """Pré-calcula segmentos para converter ticks <-> segundos."""
    tempos, _ = read_conductor_track(mid)

    change_ticks = [tick for tick, _ in tempos]
    tempo_values = [tempo for _, tempo in tempos]
    change_seconds = [0.0]

    for index in range(1, len(tempos)):
        previous_tick, previous_tempo = tempos[index - 1]
        current_tick, _ = tempos[index]

        elapsed_seconds = mido.tick2second(
            current_tick - previous_tick,
            mid.ticks_per_beat,
            previous_tempo,
        )

        change_seconds.append(change_seconds[-1] + elapsed_seconds)

    return TempoMap(
        ticks_per_beat=mid.ticks_per_beat,
        change_ticks=change_ticks,
        change_seconds=change_seconds,
        tempos=tempo_values,
    )


def _append_abs_messages(track: mido.MidiTrack, abs_messages: List[Tuple[int, object]]) -> None:
    abs_messages.sort(key=lambda item: item[0])
    last_tick = 0

    for absolute_tick, message in abs_messages:
        track.append(message.copy(time=absolute_tick - last_tick))
        last_tick = absolute_tick

    track.append(mido.MetaMessage("end_of_track", time=0))


def _parse_chart_sections(chart_text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_section_name = None
    inside_section_body = False

    for raw_line in chart_text.splitlines():
        stripped_line = raw_line.strip()

        if not stripped_line:
            continue

        if stripped_line.startswith("[") and stripped_line.endswith("]"):
            current_section_name = stripped_line[1:-1]
            sections[current_section_name] = []
            inside_section_body = False
            continue

        if stripped_line == "{":
            inside_section_body = True
            continue

        if stripped_line == "}":
            inside_section_body = False
            current_section_name = None
            continue

        if current_section_name is None or not inside_section_body:
            continue

        sections[current_section_name].append(stripped_line)

    return sections


def _chart_song_resolution(song_lines: List[str]) -> int:
    for line in song_lines:
        match = re.match(r'^Resolution\s*=\s*"?(\d+)"?$', line)

        if match is not None:
            return int(match.group(1))

    return 192


def _chart_sync_track(sync_lines: List[str]) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int, int]]]:
    tempos: List[Tuple[int, int]] = []
    time_signatures: List[Tuple[int, int, int]] = []

    for line in sync_lines:
        tempo_match = re.match(r"^(\d+)\s*=\s*B\s+(\d+)$", line)

        if tempo_match is not None:
            tick_value = int(tempo_match.group(1))
            bpm_milli = int(tempo_match.group(2))
            tempo_us_per_beat = int(round(60_000_000_000 / bpm_milli))
            tempos.append((tick_value, tempo_us_per_beat))
            continue

        signature_match = re.match(r"^(\d+)\s*=\s*TS\s+(\d+)(?:\s+(\d+))?$", line)

        if signature_match is not None:
            tick_value = int(signature_match.group(1))
            numerator_value = int(signature_match.group(2))
            denominator_power = signature_match.group(3)

            if denominator_power is None:
                denominator_value = 4
            else:
                denominator_value = 2 ** int(denominator_power)

            time_signatures.append((tick_value, numerator_value, denominator_value))

    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, 500000))

    return tempos, time_signatures


def _chart_note_rows(section_lines: List[str]) -> Dict[int, List[Tuple[int, int]]]:
    notes_by_tick: Dict[int, List[Tuple[int, int]]] = defaultdict(list)

    for line in section_lines:
        note_match = re.match(r"^(\d+)\s*=\s*N\s+(\d+)\s+(-?\d+)$", line)

        if note_match is None:
            continue

        tick_value = int(note_match.group(1))
        note_value = int(note_match.group(2))
        duration_value = int(note_match.group(3))
        notes_by_tick[tick_value].append((note_value, duration_value))

    return notes_by_tick


def _chart_phrase_rows(section_lines: List[str]) -> List[Tuple[int, int, int]]:
    """Parse `S phrase_type duration` entries (star power, solos, etc.)."""
    results = []
    for line in section_lines:
        m = re.match(r"^(\d+)\s*=\s*S\s+(\d+)\s+(\d+)$", line)
        if m:
            results.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return results


def _chart_events(event_lines: List[str]) -> List[Tuple[int, str]]:
    chart_events: List[Tuple[int, str]] = []

    for line in event_lines:
        event_match = re.match(r'^(\d+)\s*=\s*E\s+"(.*)"$', line)

        if event_match is None:
            continue

        chart_events.append((int(event_match.group(1)), event_match.group(2)))

    return chart_events


_CHART_DIFF_PITCH: List[Tuple[str, int, int, int]] = [
    # (section_name, green_base, force_on_pitch, force_off_pitch)
    ("ExpertSingle", 96, 101, 102),
    ("HardSingle",   84, 89,  90),
    ("MediumSingle", 72, 77,  78),
    ("EasySingle",   60, 65,  66),
]


def _chart_guitar_track(sections: Dict[str, List[str]]) -> mido.MidiTrack:
    """Build PART GUITAR from all four difficulty sections, star power, and tap markers."""
    chart_track = mido.MidiTrack()
    chart_track.append(mido.MetaMessage("track_name", name="PART GUITAR", time=0))
    abs_messages: List[Tuple[int, object]] = []

    # Tap (pitch 104) and star power (pitch 116) are global markers — collect and
    # deduplicate across all difficulty sections before emitting.
    tap_ticks: set = set()

    for section_name, base, force_on, force_off in _CHART_DIFF_PITCH:
        lines = sections.get(section_name, [])
        if not lines:
            continue

        note_pitch_map = {
            0: base,        # G
            1: base + 1,    # R
            2: base + 2,    # Y
            3: base + 3,    # B
            4: base + 4,    # O
            5: force_on,    # Force HOPO on
            7: base,        # chart "open" (N 7) -> green in MIDI (same as N 0)
            # Note 6 (tap) handled separately below to avoid duplicates
        }

        for tick_value, note_rows in _chart_note_rows(lines).items():
            for note_value, duration_value in note_rows:
                if note_value == 6:
                    tap_ticks.add(tick_value)
                    continue
                midi_pitch = note_pitch_map.get(note_value)
                if midi_pitch is None:
                    continue
                note_length = max(1, duration_value)
                abs_messages.append((tick_value, mido.Message("note_on", note=midi_pitch, velocity=100, time=0)))
                abs_messages.append((tick_value + note_length, mido.Message("note_off", note=midi_pitch, velocity=0, time=0)))

        # Star power / overdrive (pitch 116) intentionally not emitted — removed by design

    # Emit tap markers once per tick (pitch 104 is a global track marker)
    for tick_value in sorted(tap_ticks):
        abs_messages.append((tick_value, mido.Message("note_on", note=104, velocity=100, time=0)))
        abs_messages.append((tick_value + 1, mido.Message("note_off", note=104, velocity=0, time=0)))

    _append_abs_messages(chart_track, abs_messages)
    return chart_track


def _chart_drums_track(expert_drums_lines: List[str], ticks_per_beat: int) -> mido.MidiTrack:
    chart_track = mido.MidiTrack()
    chart_track.append(mido.MetaMessage("track_name", name="PART DRUMS", time=0))
    chart_track.append(mido.MetaMessage("text", text="[mix 0 drums0]", time=0))
    abs_messages: List[Tuple[int, object]] = []
    notes_by_tick = _chart_note_rows(expert_drums_lines)
    playable_pitch_map = {
        0: 96,
        1: 97,
        2: 98,
        3: 99,
        4: 100,
        32: 95,
    }
    cymbal_marker_map = {
        2: 66,
        3: 67,
        4: 68,
    }
    tom_marker_map = {
        2: 110,
        3: 111,
        4: 112,
    }

    for tick_value, note_rows in notes_by_tick.items():
        note_values = {note_value for note_value, _ in note_rows}

        for note_value, duration_value in note_rows:
            midi_pitch = playable_pitch_map.get(note_value)

            if midi_pitch is None:
                continue

            note_length = max(1, duration_value)
            abs_messages.append((tick_value, mido.Message("note_on", note=midi_pitch, velocity=100, time=0)))
            abs_messages.append((tick_value + note_length, mido.Message("note_off", note=midi_pitch, velocity=0, time=0)))

            cymbal_marker = cymbal_marker_map.get(note_value)
            tom_marker = tom_marker_map.get(note_value)

            if cymbal_marker is not None and tom_marker is not None and cymbal_marker not in note_values:
                abs_messages.append((tick_value, mido.Message("note_on", note=tom_marker, velocity=100, time=0)))
                abs_messages.append((tick_value + max(1, ticks_per_beat // 8), mido.Message("note_off", note=tom_marker, velocity=0, time=0)))

    _append_abs_messages(chart_track, abs_messages)

    return chart_track


def _chart_events_track(event_lines: List[str]) -> mido.MidiTrack:
    chart_track = mido.MidiTrack()
    chart_track.append(mido.MetaMessage("track_name", name="EVENTS", time=0))
    abs_messages = [
        (tick_value, mido.MetaMessage("text", text=text_value, time=0))
        for tick_value, text_value in _chart_events(event_lines)
    ]
    _append_abs_messages(chart_track, abs_messages)

    return chart_track


def chart_file_to_midi(chart_path: str) -> mido.MidiFile:
    with open(chart_path, encoding="utf-8") as chart_file:
        chart_text = chart_file.read()

    sections = _parse_chart_sections(chart_text)
    ticks_per_beat = _chart_song_resolution(sections.get("Song", []))
    tempos, time_signatures = _chart_sync_track(sections.get("SyncTrack", []))
    midi_file = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    conductor_track = mido.MidiTrack()
    abs_messages: List[Tuple[int, object]] = []

    for tick_value, tempo_value in tempos:
        abs_messages.append((tick_value, mido.MetaMessage("set_tempo", tempo=tempo_value, time=0)))

    for tick_value, numerator_value, denominator_value in time_signatures:
        abs_messages.append(
            (
                tick_value,
                mido.MetaMessage(
                    "time_signature",
                    numerator=numerator_value,
                    denominator=denominator_value,
                    clocks_per_click=24,
                    notated_32nd_notes_per_beat=8,
                    time=0,
                ),
            )
        )

    _append_abs_messages(conductor_track, abs_messages)
    midi_file.tracks.append(conductor_track)

    if any(sections.get(s) for s, *_ in _CHART_DIFF_PITCH):
        midi_file.tracks.append(_chart_guitar_track(sections))

    if sections.get("ExpertDrums"):
        midi_file.tracks.append(_chart_drums_track(sections["ExpertDrums"], ticks_per_beat))

    if sections.get("Events"):
        midi_file.tracks.append(_chart_events_track(sections["Events"]))

    return midi_file


def load_reference_midi(reference_path: str) -> mido.MidiFile:
    if reference_path.lower().endswith(".chart"):
        return chart_file_to_midi(reference_path)

    return mido.MidiFile(reference_path)


def parse_part(mid: mido.MidiFile, part_name: str) -> Dict[str, Chart]:
    """Return {difficulty -> Chart} for the named PART track."""
    track = next((t for t in mid.tracks if t.name == part_name), None)
    if track is None:
        return {}

    pairs = _decode_note_pairs(track)

    tempos, sigs = read_conductor_track(mid)

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
        for s, e, p in pairs:
            offset = p - base
            if offset in (-2, -1):  # legacy "open" MIDI pitches -> green
                gem_buckets[s].append((0, e))
            elif 0 <= offset <= 4:
                gem_buckets[s].append((offset, e))
            elif offset == 5:
                force_on.append(s)
            elif offset == 6:
                force_off.append(s)
        # Convert buckets to Note list
        for tick in sorted(gem_buckets):
            gems = gem_buckets[tick]
            frets = tuple(sorted({g[0] for g in gems}))
            end = max(g[1] for g in gems)
            n = Note(tick=tick, end_tick=end, frets=frets)
            if tick in force_on: n.forced_hopo = +1
            elif tick in force_off: n.forced_hopo = -1
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
    base = "songs/harmonix"
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

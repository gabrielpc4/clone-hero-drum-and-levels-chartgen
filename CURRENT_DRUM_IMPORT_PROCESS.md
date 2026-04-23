# Current Songsterr Drum Import Process

## Goal

Generate a `PART DRUMS` Expert track for Clone Hero from an external Songsterr MIDI.

Current scope is intentionally simple:

- keep the original Songsterr timing
- keep the original Songsterr song start
- do not sync to the reference chart yet
- focus only on converting drum notes into valid Clone Hero drum lanes

There is now one optional helper on top of this baseline:

- detect the first strong drum-like rise in the song audio and use it to place the first generated drum note
- this is still intentionally limited to the **first note only**

This is the current baseline from which future sync improvements should be built.

## What The Importer Does Today

The active importer is:

- `_analysis/import_songsterr.py`

It is now only a thin CLI wrapper around small modules in:

- `_analysis/songsterr_import/constants.py`
- `_analysis/songsterr_import/source.py`
- `_analysis/songsterr_import/mapping.py`
- `_analysis/songsterr_import/writer.py`
- `_analysis/songsterr_import/pipeline.py`

The importer does **not** read the reference chart anymore.

Exception:

- by default, the importer tries to auto-detect `notes.chart` or `notes.mid` and song audio in the same song folder
- if both are found, it reads the reference chart only to place the generated drums on the target TPB and uses the song audio only to align the first drum hit

### Current generation steps

1. Load the external Songsterr MIDI.
2. Choose the best source drum track from channel 9 tracks.
3. Map GM drum pitches to Clone Hero drum lanes.
4. Apply small cleanup rules:
  - dynamic tom mapping
  - open hi-hat classification
  - flam dedup
  - duplicate same-lane cleanup
  - tom marker preservation for Pro Drums
5. Write a `PART DRUMS` track back into a MIDI that keeps the original Songsterr timing.

### Optional first-note alignment

If the importer can resolve chart reference + song audio:

- the importer detects the first strong drum-like rise in the song audio
- it aligns the first mapped Songsterr drum hit to that audio rise
- the rest of the Songsterr drum timing is preserved relative to that first aligned hit

This is still much simpler than the older full-song sync experiments.

## Important Current Rules

### Drum track selection

The importer no longer grabs the first channel-9 track blindly.

It ranks candidate drum tracks by:

- how many channel-9 hits they have
- how many of those hits map to known GM drum pitches
- track name hints such as `drum`, `kit`, and `percussion`

This matters because some files have both a real drums track and a separate percussion track.

### Lane mapping

The main GM-to-Clone-Hero mapping currently lives in:

- `_analysis/songsterr_import/constants.py`

Important current details:

- `35`, `36` -> kick
- `37` to `40` -> snare
- `42`, `44` -> yellow cymbal
- `46` -> yellow or blue cymbal depending on the hi-hat heuristic
- `49`, `52`, `55`, `57` -> green cymbal
- `51`, `53`, `59` -> blue cymbal
- `41`, `43`, `45`, `47`, `48`, `50` -> dynamic tom mapping
- `18` -> green cymbal special-case

### Open hi-hat heuristic

`GM 46` is classified by the current heuristic in:

- `_analysis/songsterr_import/mapping.py`

In short:

- if the file already uses clear ride pitches often enough, `46` is treated as yellow hi-hat
- otherwise, if open hi-hats dominate the hi-hat pattern, `46` is also treated as yellow
- otherwise it is treated as blue

### Flam cleanup

If two hits on the same lane happen very close together:

- on snare, the second hit is converted into a simultaneous yellow tom hit
- on other lanes, the duplicate is removed

This is controlled by `--dedup-beats`.

### Tom markers

The importer preserves Pro Drums tom markers:

- yellow tom -> `110`
- blue tom -> `111`
- green tom -> `112`

## Deliberate Non-Goals Right Now

The current importer does **not** do any of the following:

- align to the audio of the reference chart
- align to `PART GUITAR`
- reconcile different BPM maps
- reconcile different time signatures like `4/4` vs `6/8`
- snap to a reference timing grid
- use manual anchors

All of that was intentionally removed from the active generation path.

## Commands

### Basic generation

```bash
python3 _analysis/import_songsterr.py "<songsterr.mid>" "<out.mid>"
```

### Optional cleanup controls

```bash
python3 _analysis/import_songsterr.py "<songsterr.mid>" "<out.mid>" \
  --drop-before-src-beat 24 \
  --dedup-beats 0.0625
```

Current options:

- `--drop-before-src-beat`
- `--dedup-beats`
- `--ref-path`
- `--audio-path`
- `--disable-first-note-audio-align`

Default behavior:

- try to auto-detect chart reference + audio and align the first note by default
- use `--ref-path` and `--audio-path` only to override the detected files
- use `--disable-first-note-audio-align` if you explicitly want to turn this off

There are no legacy sync arguments anymore.

## What Gets Generated

The output file is a MIDI that:

- keeps the original Songsterr timing and TPB
- keeps the original source tracks
- replaces an existing `PART DRUMS` if one already exists
- otherwise appends a new `PART DRUMS`

### Typical output names

We currently save generated files as:

- `notes.songsterr.mid`

Examples already present in the repo:

- `System of a Down - Toxicity (Harmonix)/notes.songsterr.mid`
- `System of a Down - B.Y.O.B. (Harmonix)/notes.songsterr.mid`
- `custom/System of a Down - Lonely Day (thardwardy)/notes.songsterr.mid`

## Validation Workflow

Validation is still useful, but it is separate from production generation.

### Harmonix validation songs

For Harmonix songs, the official `notes.mid` contains `PART DRUMS` Expert, so it can be used as ground truth to compare timing and lane choices.

### Custom validation

Some customs already contain `[ExpertDrums]` inside `notes.chart`.
That can also be used as ground truth for validation.

The parser support for this lives in:

- `_analysis/parse_chart.py`

Relevant functions there:

- `chart_file_to_midi()`
- `load_reference_midi()`

These are useful for validation and analysis, but they are **not** part of the active importer path anymore.

## Sync To Whisky

The helper script is:

- `sync_to_whisky.sh`

What it does:

- copies Harmonix originals to `SOAD-oficial`
- copies generated Harmonix results to `SOAD-gerado`
- copies custom folders to `SOAD-custom`
- converts `.opus` files to `.ogg`
- creates timestamped MIDI copies for easy identification
- sanitizes folder names for Windows so they do not end with `.` or space

### Where files end up

In Whisky:

- Harmonix official chart:
  - `SOAD-oficial/<song>/notes.mid`
- Harmonix generated Songsterr result:
  - `SOAD-gerado/<song>/notes.mid`
  - `SOAD-gerado/<song>/notes.songsterr-<dd-mm-hh-mm>.mid`
- Custom chart folder:
  - `SOAD-custom/<song>/...`

For customs, the generated file remains:

- `SOAD-custom/<song>/notes.songsterr.mid`

Example:

- `SOAD-custom/Lonely Day (thardwardy)/notes.songsterr.mid`

## Current Real Examples

### Lonely Day custom

Input files:

- `custom/System of a Down - Lonely Day (thardwardy)/notes.chart`
- `custom/System of a Down - Lonely Day (thardwardy)/System of a Down-Lonely Day-04-20-2026.mid`

Generated output:

- `custom/System of a Down - Lonely Day (thardwardy)/notes.songsterr.mid`

### B.Y.O.B. Harmonix

Input files:

- `System of a Down - B.Y.O.B. (Harmonix)/notes.mid`
- `System of a Down - B.Y.O.B. (Harmonix)/System of a Down-B.Y.O.B.-03-31-2026.mid`

Generated output:

- `System of a Down - B.Y.O.B. (Harmonix)/notes.songsterr.mid`

## Current State Summary

This is the current baseline:

- modular code
- no sync logic
- no legacy CLI
- simple drum generation only

Any future timing work should be added in separate modules on top of this baseline, not by growing `_analysis/import_songsterr.py` back into a giant file.
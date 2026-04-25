# Current Songsterr Drum Import Process

## Goal

Generate a `PART DRUMS` Expert track for Clone Hero from an external Songsterr MIDI.

Current scope uses a single default sync strategy:

- read `MEASURE_n` markers from the Songsterr source MIDI
- read measure starts from the Clone Hero `notes.chart` / `notes.mid`
- map Songsterr measures onto the reference-chart measures
- allow a global tick offset on top of that mapping
- convert the mapped drum notes into valid Clone Hero drum lanes

This is the active production path now.

## What The Importer Does Today

The active importer is:

- `_analysis/import_songsterr.py`

It is now only a thin CLI wrapper around small modules in:

- `_analysis/songsterr_import/constants.py`
- `_analysis/songsterr_import/source.py`
- `_analysis/songsterr_import/mapping.py`
- `_analysis/songsterr_import/writer.py`
- `_analysis/songsterr_import/pipeline.py`

The importer now **does** read the reference chart by default.

It tries to auto-detect:

- `notes.chart`
- or `notes.mid`

in the same folder as the Songsterr MIDI or output file.

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
5. Read `MEASURE_n` markers from the source drum track.
6. Read measure starts from the reference chart tempo/signature map.
7. Build an adaptive measure-to-measure warp:
  - normally `1` Songsterr measure -> `1` chart measure
  - when the durations match better, `1` Songsterr measure -> `2` chart measures
8. Apply the global tick offset (default `768`).
9. Write a `PART DRUMS` track back into a MIDI using the reference chart TPB.

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
- `42` -> yellow cymbal
- `44` -> ignored
- `46` -> yellow by default, with contextual overrides when needed
- `49`, `52`, `55`, `57` -> green cymbal
- `51`, `53`, `59` -> blue cymbal
- `41`, `43`, `45`, `47`, `48`, `50` -> dynamic tom mapping
- `18` -> green cymbal special-case

### Open hi-hat heuristic

`GM 46` is classified by the current heuristic in:

- `_analysis/songsterr_import/mapping.py`

In short:

- `46` is yellow by default
- some specific patterns can still override it contextually

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

The current importer does **not** use:

- Songsterr `video-points`
- audio-based first-note sync
- per-note snap-to-grid
- guitar-guided snap

Those older experimental sync paths were removed from the active generation code.

## Commands

### Basic generation

```bash
python3 _analysis/import_songsterr.py "<songsterr.mid>" "<out.mid>"
```

Default behavior:

- auto-detect `notes.chart` / `notes.mid`
- sync by `MEASURE_n`
- apply `--initial-offset-ticks 768`

### Optional cleanup controls

```bash
python3 _analysis/import_songsterr.py "<songsterr.mid>" "<out.mid>" \
  --initial-offset-ticks 960 \
  --drop-before-src-beat 24 \
  --dedup-beats 0.0625
```

Current options:

- `--initial-offset-ticks`
- `--drop-before-src-beat`
- `--dedup-beats`
- `--ref-path`

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

These are useful for validation and analysis, and the reference chart is also part of the active importer path now.

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
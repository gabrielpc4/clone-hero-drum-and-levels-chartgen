# Clone Hero Drum Chart Generator

A toolkit for creating and maintaining Clone Hero drum charts from existing MIDI and chart files.

The project focuses on turning drum performances from external sources into playable `PART DRUMS` tracks while preserving the timing, structure, and other instrument tracks of an existing Clone Hero chart. It also includes tools for vocal tracks, difficulty generation, chart analysis, and synchronizing generated charts into a Clone Hero song library.

## Features

- Import drum performances from Songsterr MIDI files.
- Map General MIDI drum notes to Clone Hero lanes, cymbals, and toms.
- Align imported notes to the timing of a reference `notes.mid` or `notes.chart`.
- Handle changing time signatures and measure-based timing markers.
- Optionally filter low-velocity snare hits.
- Optionally apply Expert cymbal alternation rules.
- Generate lead vocal tracks from compatible MIDI sources.
- Generate missing difficulty levels from existing charts.
- Analyze chart timing, alignment, and difficulty data.
- Copy generated charts into the repository's `Songs` library layout.
- Provide a Windows desktop workflow for Songsterr import and chart maintenance.

## Project layout

```text
src/
  chart_generation/       Chart parsing, synchronization, and MIDI writing
  difficulty_generation/  Difficulty reduction and analysis
  songsterr_parsing/      Songsterr import and source processing

tools/                     Workflow scripts and analysis utilities
Songs/                     Charts prepared for the Clone Hero library
original/                  Source charts and working material
custom/                    Community chart material
Custom/                    Additional chart assets and utilities
requirements.txt           Python dependencies
copy_song_to_clone_hero.ps1
                          Windows chart synchronization script
```

## Requirements

- Python 3
- `mido`
- `requests`
- Windows PowerShell for the synchronization scripts
- .NET 8 SDK for the optional desktop application

Install the Python dependencies with:

```bash
python -m pip install -r requirements.txt
```

When running Python modules from the repository root, configure the source path as needed:

```powershell
$env:PYTHONPATH = "src;src/chart_generation"
```

## Importing a drum chart

The importer uses the external MIDI for the performance and a reference chart for final timing:

```bash
python src/songsterr_parsing/import_songsterr.py \
  "path/to/source.mid" \
  "path/to/notes.generated.mid" \
  --ref-path "path/to/notes.mid"
```

Useful options include:

```text
--initial-offset-ticks N
--filter-weak-snares
--expert-cymbal-alternation-whole
```

If `--ref-path` is omitted, the importer looks for a suitable `notes.chart` or `notes.mid` near the source and output files. The generated MIDI is based on the reference chart, so existing timing and non-drum tracks remain intact.

## Generating vocals

To create a new MIDI containing a lead vocal track:

```bash
python src/songsterr_parsing/import_vocals.py \
  "path/to/vocal-source.mid" \
  "path/to/notes.generated.mid" \
  --ref-path "path/to/notes.mid"
```

The source must contain a recognizable vocal or lyrics track with notes in the expected vocal range. The current pipeline generates pitch and phrase markers, but does not generate lyrics or harmony parts.

## Syncing a chart to Clone Hero

After generating `notes.generated.mid`, publish it into the `Songs` directory with:

```powershell
.\copy_song_to_clone_hero.ps1 `
  "C:\path\to\source-song-folder" `
  "System of a Down - Example"
```

The script writes the generated MIDI as `Songs/<song>/notes.mid` and copies supporting song files while excluding extra MIDI and chart files.

## Songsterr authentication

The optional Songsterr downloader requires an authenticated session. The desktop application can store the session cookies locally and pass them to the downloader. Do not commit cookie files, tokens, or exported session data to this repository.

## FFmpeg

FFmpeg executables are not bundled with the repository. If a local workflow requires FFmpeg, install it separately and configure the relevant tool to use the local executable path.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

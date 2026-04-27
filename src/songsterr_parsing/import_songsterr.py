"""
Imports a MIDI from Songsterr and generates a `PART DRUMS` Expert for Clone Hero
using, by default, sync via `MEASURE_n` against the chart measures.

Usage:
  python3 import_songsterr.py <external.mid> <output.mid>
"""
from __future__ import annotations

import argparse
import os
import sys

import mido

_songsterr_parsing_dir = os.path.dirname(os.path.abspath(__file__))
_chart_generation_dir = os.path.normpath(os.path.join(_songsterr_parsing_dir, "..", "chart_generation"))
# parse_chart lives in chart_generation; songsterr_import/ in songsterr_parsing.
sys.path.insert(0, _chart_generation_dir)
sys.path.insert(0, _songsterr_parsing_dir)

from parse_chart import load_reference_midi
from songsterr_import.context import resolve_import_context
from songsterr_import.constants import DEFAULT_MINIMUM_SNARE_VELOCITY
from songsterr_import.measure_marker_sync import DEFAULT_INITIAL_OFFSET_TICKS
from songsterr_import.pipeline import generate_songsterr_drums_synced_to_measure_markers


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid", help="External MIDI containing the drums")
    argument_parser.add_argument("out_mid", help="Where to save the generated MIDI")
    argument_parser.add_argument(
        "--ref-path",
        help="notes.mid or notes.chart used as reference for the destination measures.",
    )
    argument_parser.add_argument(
        "--initial-offset-ticks",
        type=int,
        default=DEFAULT_INITIAL_OFFSET_TICKS,
        help=(
            "global offset in ticks/positions applied after the mapping "
            f"measure-by-measure via MEASURE_n (default: {DEFAULT_INITIAL_OFFSET_TICKS})."
        ),
    )
    argument_parser.add_argument(
        "--expert-cymbal-alternation-whole",
        action="store_true",
        help=(
            "after building PART DRUMS, fine-tune 98/99 in 1/8 chains with snare 97 in that arc; "
            "cymbals only or cymbals+kick (without 97) do not fine-tune. 100 G immune. Tom 110/111/112; turn break chain."
        ),
    )
    argument_parser.add_argument(
        "--thin-all-cymbal-lines",
        action="store_true",
        help="when used with --expert-cymbal-alternation-whole, thin Y/B cymbals in all steady 1/8 runs (not just those with snare activity).",
    )
    args = argument_parser.parse_args()

    src_mid = mido.MidiFile(args.src_mid)
    import_context = resolve_import_context(
        src_mid_path=args.src_mid,
        out_mid_path=args.out_mid,
        explicit_ref_path=args.ref_path,
    )
    if import_context.reference_path is None:
        raise RuntimeError(
            "O sync padrao precisa de notes.mid ou notes.chart. "
            "Passe --ref-path ou deixe o arquivo ao lado do MIDI."
        )

    ref_mid = load_reference_midi(import_context.reference_path)
    print("Diagnostico de sync: alinhamento por markers MEASURE_n")

    generation_result = generate_songsterr_drums_synced_to_measure_markers(
        src_mid,
        ref_mid,
        initial_offset_ticks=args.initial_offset_ticks,
        minimum_snare_velocity=None,
        apply_expert_cymbal_alternation_whole_chart=args.expert_cymbal_alternation_whole,
        thin_all_cymbal_lines=args.thin_all_cymbal_lines,
    )
    if generation_result.measure_sync is not None:
        print(
            f"  compassos: source={generation_result.measure_sync.source_measure_count} "
            f"target={generation_result.measure_sync.target_measure_count} "
            f"paired={generation_result.measure_sync.paired_measure_count}"
        )
        print(f"  split_2x={generation_result.measure_sync.split_measure_count}")
        print(
            f"  offset: ticks={generation_result.measure_sync.initial_offset_ticks:+d} "
            f"measures={generation_result.measure_sync.initial_measure_offset}"
        )

    if generation_result.first_drum_tick is not None:
        print(
            f"  first_drum: tick={generation_result.first_drum_tick} "
            f"beat={generation_result.first_drum_tick / generation_result.output_mid.ticks_per_beat:.2f}"
        )

    generation_result.output_mid.save(args.out_mid)
    print("  status: midi_gerado")


if __name__ == "__main__":
    main()

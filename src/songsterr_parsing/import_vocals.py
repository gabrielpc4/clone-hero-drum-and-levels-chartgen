"""
Importa um MIDI auxiliar e gera uma `PART VOCALS` lead-only usando o sync por
`MEASURE_n` contra os compassos da chart de referencia.

Uso:
  python3 import_vocals.py <externo.mid> <saida.mid>
"""
from __future__ import annotations

import argparse
import os
import sys

_songsterr_parsing_dir = os.path.dirname(os.path.abspath(__file__))
_src_root = os.path.normpath(os.path.join(_songsterr_parsing_dir, ".."))
_chart_generation_dir = os.path.normpath(os.path.join(_songsterr_parsing_dir, "..", "chart_generation"))
sys.path.insert(0, _src_root)
sys.path.insert(0, _chart_generation_dir)
sys.path.insert(0, _songsterr_parsing_dir)

from midi_repair import load_midi_file
from parse_chart import load_reference_midi
from songsterr_import.context import resolve_import_context
from songsterr_import.vocal_pipeline import generate_songsterr_vocals_synced_to_measure_markers


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid", help="MIDI externo contendo uma track vocal")
    argument_parser.add_argument("out_mid", help="onde gravar o MIDI gerado")
    argument_parser.add_argument(
        "--ref-path",
        help="notes.mid ou notes.chart usado como referencia para os compassos de destino.",
    )
    argument_parser.add_argument(
        "--initial-offset-ticks",
        type=int,
        default=0,
        help="deslocamento global em ticks aplicado depois do mapeamento compasso-a-compasso por MEASURE_n.",
    )
    args = argument_parser.parse_args()

    src_mid = load_midi_file(args.src_mid)
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
    print("Diagnostico de sync: alinhamento vocal por markers MEASURE_n")
    generation_result = generate_songsterr_vocals_synced_to_measure_markers(
        src_mid,
        ref_mid,
        initial_offset_ticks=args.initial_offset_ticks,
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

    print(f"  source_track={generation_result.source_track_name}")
    print(f"  vocal_notes={generation_result.note_count}")
    print(f"  vocal_phrases={generation_result.phrase_count}")
    generation_result.output_mid.save(args.out_mid)
    print("  status: midi_gerado")


if __name__ == "__main__":
    main()

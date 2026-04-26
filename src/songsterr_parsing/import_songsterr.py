"""
Importa um MIDI do Songsterr e gera uma `PART DRUMS` Expert para Clone Hero
usando, por padrao, o sync por `MEASURE_n` contra os compassos da chart.

Uso:
  python3 import_songsterr.py <externo.mid> <saida.mid>
"""
from __future__ import annotations

import argparse
import os
import sys

import mido

_songsterr_parsing_dir = os.path.dirname(os.path.abspath(__file__))
_chart_generation_dir = os.path.normpath(os.path.join(_songsterr_parsing_dir, "..", "chart_generation"))
# parse_chart vive em chart_generation; songsterr_import/ em songsterr_parsing.
sys.path.insert(0, _chart_generation_dir)
sys.path.insert(0, _songsterr_parsing_dir)

from parse_chart import load_reference_midi
from songsterr_import.context import resolve_import_context
from songsterr_import.constants import DEFAULT_MINIMUM_SNARE_VELOCITY
from songsterr_import.measure_marker_sync import DEFAULT_INITIAL_OFFSET_TICKS
from songsterr_import.pipeline import generate_songsterr_drums_synced_to_measure_markers


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid", help="MIDI externo contendo a bateria")
    argument_parser.add_argument("out_mid", help="onde gravar o MIDI gerado")
    argument_parser.add_argument(
        "--ref-path",
        help="notes.mid ou notes.chart usado como referencia para os compassos de destino.",
    )
    argument_parser.add_argument(
        "--initial-offset-ticks",
        type=int,
        default=DEFAULT_INITIAL_OFFSET_TICKS,
        help=(
            "deslocamento global em ticks/posicoes aplicado depois do mapeamento "
            f"compasso-a-compasso por MEASURE_n (padrao: {DEFAULT_INITIAL_OFFSET_TICKS})."
        ),
    )
    argument_parser.add_argument(
        "--dedup-beats",
        type=float,
        default=1 / 16,
        help="pares mesma-lane com gap <= N beats: flam (caixa R+Y) ou dedup (outros) quando a conversao de flams esta ativa.",
    )
    argument_parser.add_argument(
        "--filter-weak-snares",
        action="store_true",
        help=f"ignora caixas com velocity abaixo de {DEFAULT_MINIMUM_SNARE_VELOCITY} (ghosts). O padrao e incluir todas (notas 'soft').",
    )
    argument_parser.add_argument(
        "--no-convert-flams",
        action="store_true",
        help="nao aplica a logica de flam (dois bumbos/duas notas juntinhas) nem dedup por proximidade; cada nota source vira mapeada sem merge.",
    )
    args = argument_parser.parse_args()

    src_mid = mido.MidiFile(args.src_mid)
    convert_flams = not args.no_convert_flams
    if args.filter_weak_snares:
        print(f"  snare: filtrar notas com velocity < {DEFAULT_MINIMUM_SNARE_VELOCITY}")
    else:
        print("  snare: incluir notas 'soft' (todos os velocities)")
    print(
        f"  flam / same-lane (convert flams to double / dedup janela): {convert_flams} "
        f"dedup_beats={args.dedup_beats!r}"
    )
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
    print("Modo padrao: sync por MEASURE_n do Songsterr contra compassos da chart")
    if import_context.auto_detected:
        print(f"  ref detectado automaticamente: {import_context.reference_path}")

    snare_filter = (
        DEFAULT_MINIMUM_SNARE_VELOCITY if args.filter_weak_snares else None
    )
    generation_result = generate_songsterr_drums_synced_to_measure_markers(
        src_mid,
        ref_mid,
        initial_offset_ticks=args.initial_offset_ticks,
        dedup_beats=args.dedup_beats,
        minimum_snare_velocity=snare_filter,
        convert_flams_to_double_note=convert_flams,
    )
    if generation_result.measure_sync is not None:
        print(
            f"  compassos-src={generation_result.measure_sync.source_measure_count} "
            f"compassos-ref={generation_result.measure_sync.target_measure_count} "
            f"compassos-pareados={generation_result.measure_sync.paired_measure_count}"
        )
        print(f"  compassos divididos em 2x={generation_result.measure_sync.split_measure_count}")
        print(
            f"  offset manual={generation_result.measure_sync.initial_offset_ticks:+d} ticks "
            f"(pula {generation_result.measure_sync.initial_measure_offset} compassos da chart)"
        )

    if generation_result.first_drum_tick is not None:
        print(
            f"  -> 1a drum: tick={generation_result.first_drum_tick} "
            f"beat={generation_result.first_drum_tick / generation_result.output_mid.ticks_per_beat:.2f}"
        )

    generation_result.output_mid.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

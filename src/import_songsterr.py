"""
Importa um MIDI do Songsterr e gera uma PART DRUMS Expert para Clone Hero
usando, por padrao, o sync por MEASURE_n contra os compassos da chart.

Uso:
  python3 import_songsterr.py <externo.mid> <saida.mid>
"""
from __future__ import annotations

import argparse
import os
import sys

import mido

sys.path.insert(0, os.path.dirname(__file__))

from parse_chart import load_reference_midi
from postprocess_bubbles_songsterr import apply_bubbles_songsterr_postprocess
from postprocess_soldier_side_songsterr import apply_soldier_side_songsterr_postprocess
from songsterr_import.context import resolve_import_context
from songsterr_import.constants import DEFAULT_MINIMUM_SNARE_VELOCITY
from songsterr_import.measure_marker_sync import DEFAULT_INITIAL_OFFSET_TICKS
from songsterr_import.pipeline import generate_songsterr_drums_synced_to_measure_markers


def _should_run_bubbles_postprocess(src_mid_path: str, out_mid_path: str) -> bool:
    return "system of a down - bubbles" in src_mid_path.lower() or "system of a down - bubbles" in out_mid_path.lower()


def _should_run_soldier_side_postprocess(src_mid_path: str, out_mid_path: str) -> bool:
    return "system of a down - soldier side" in src_mid_path.lower() or "system of a down - soldier side" in out_mid_path.lower()


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
        "--drop-before-src-beat",
        type=float,
        default=0.0,
        help="dropa notas src antes deste beat (remove count-in / baqueta).",
    )
    argument_parser.add_argument(
        "--dedup-beats",
        type=float,
        default=1 / 16,
        help="pares mesma-lane com gap <= N beats viram R+Y (snare) ou dedup (outros).",
    )
    argument_parser.add_argument(
        "--minimum-snare-velocity",
        type=int,
        default=None,
        help=(
            "ignora apenas caixas com velocity abaixo deste valor; "
            f"omita para incluir todas, ou passe {DEFAULT_MINIMUM_SNARE_VELOCITY} "
            "para reativar o filtro antigo."
        ),
    )
    args = argument_parser.parse_args()

    src_mid = mido.MidiFile(args.src_mid)
    print(f"  drop antes de src_beat {args.drop_before_src_beat:.2f}")
    if args.minimum_snare_velocity is None:
        print("  min snare velocity: inclui todas as caixas")
    else:
        print(f"  min snare velocity: {args.minimum_snare_velocity}")
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

    generation_result = generate_songsterr_drums_synced_to_measure_markers(
        src_mid,
        ref_mid,
        initial_offset_ticks=args.initial_offset_ticks,
        drop_before_src_beat=args.drop_before_src_beat,
        dedup_beats=args.dedup_beats,
        minimum_snare_velocity=args.minimum_snare_velocity,
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

    if import_context.reference_path is not None and _should_run_bubbles_postprocess(args.src_mid, args.out_mid):
        print("  aplicando post-processamento especifico da Bubbles")
        generation_result.output_mid = apply_bubbles_songsterr_postprocess(
            generation_result.output_mid,
            src_mid,
            ref_mid,
            initial_offset_ticks=args.initial_offset_ticks,
            minimum_snare_velocity=args.minimum_snare_velocity,
        )

    if _should_run_soldier_side_postprocess(args.src_mid, args.out_mid):
        print("  aplicando post-processamento especifico da Soldier Side")
        generation_result.output_mid = apply_soldier_side_songsterr_postprocess(generation_result.output_mid)

    generation_result.output_mid.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

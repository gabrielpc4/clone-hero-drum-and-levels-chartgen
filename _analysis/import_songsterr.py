"""
Importa um MIDI externo (Songsterr/Guitar Pro/MuseScore) e gera uma PART DRUMS
Expert no formato Harmonix/Clone Hero.

Versao simples:
- preserva o tempo original do Songsterr
- preserva o ponto inicial original do Songsterr
- nao tenta sincronizar com chart de referencia
- so faz o mapeamento das notas de bateria GM -> lanes de Clone Hero

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
from songsterr_import.pipeline import (
    generate_songsterr_drums,
    generate_songsterr_drums_aligned_first_note,
)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("src_mid", help="MIDI externo contendo a bateria")
    argument_parser.add_argument("out_mid", help="onde gravar o MIDI gerado")
    argument_parser.add_argument(
        "--ref-path",
        help="notes.mid ou notes.chart usado como referencia para o mapeamento da primeira nota.",
    )
    argument_parser.add_argument(
        "--audio-path",
        help="arquivo de audio da musica usado para detectar a primeira subida dramatica.",
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
    args = argument_parser.parse_args()

    src_mid = mido.MidiFile(args.src_mid)
    if (args.ref_path is None) != (args.audio_path is None):
        raise RuntimeError("Use --ref-path e --audio-path juntos")

    print(f"  drop antes de src_beat {args.drop_before_src_beat:.2f}")

    if args.ref_path is not None and args.audio_path is not None:
        ref_mid = load_reference_midi(args.ref_path)
        print("Modo simples + alinhamento da primeira nota por audio")
        generation_result = generate_songsterr_drums_aligned_first_note(
            src_mid,
            ref_mid,
            args.audio_path,
            drop_before_src_beat=args.drop_before_src_beat,
            dedup_beats=args.dedup_beats,
        )
        if generation_result.alignment is not None:
            print(
                f"  subida detectada em {generation_result.alignment.audio_rise.rise_seconds:.3f}s "
                f"(score={generation_result.alignment.audio_rise.score:.3f})"
            )
            print(
                f"  1a drum src tick={generation_result.alignment.source_first_tick} "
                f"-> target tick={generation_result.alignment.target_first_tick}"
            )
            print(f"  beat offset aplicado={generation_result.alignment.beat_offset:+.3f}")
    else:
        print("Modo simples: preservando tempo original do Songsterr")
        generation_result = generate_songsterr_drums(
            src_mid,
            drop_before_src_beat=args.drop_before_src_beat,
            dedup_beats=args.dedup_beats,
        )

    if generation_result.first_drum_tick is not None:
        print(
            f"  -> 1a drum: tick={generation_result.first_drum_tick} "
            f"beat={generation_result.first_drum_tick / src_mid.ticks_per_beat:.2f}"
        )

    generation_result.output_mid.save(args.out_mid)
    print(f"Escrito: {args.out_mid}")


if __name__ == "__main__":
    main()

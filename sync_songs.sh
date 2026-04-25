#!/usr/bin/env bash
# Copia `notes.songsterr.mid` (geracao/sinc atual) para `Songs/.../notes.mid` e o
# resto dos ficheiros da origem, exceto outros `*.mid` e `*.chart`, para
# o Clone Hero.
#
# Uso:
#   ./sync_songs.sh <pasta-origem> <destino-sob-Songs>
#
# Exemplo:
#   ./sync_songs.sh "original/custom/System of a Down - Soil (Wagsii)" \
#     "System of a Down - Soil"
#   -> `original/.../notes.songsterr.mid` vira `Songs/System of a Down - Soil/notes.mid`
#   e os demais ficheiros (audio, jpg, etc.) sao copiados para a mesma pasta de
#   destino, sem `*.mid` / `*.chart` extra da origem.

set -euo pipefail

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Uso: $0 <pasta-origem> <destino-sob-Songs>" >&2
  echo "  Origem: pasta com notes.songsterr.mid (ex. original/custom/...)." >&2
  echo "  Destino: nome (ou Songs/...) da pasta alvo em Songs/, ex.: 'System of a Down - Soil'" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$1" ]; then
  echo "❌ Origem nao e uma pasta ou nao existe: $1" >&2
  exit 1
fi

SOURCE_DIR="$(cd "$1" && pwd)"

# Normaliza segundo arg para subcaminho sob Songs/
raw_dest="$2"
if [[ "$raw_dest" == Songs/* ]]; then
  song_rel_path="${raw_dest#Songs/}"
elif [[ "$raw_dest" == songs/* ]]; then
  song_rel_path="${raw_dest#songs/}"
else
  song_rel_path="$raw_dest"
fi

if [ -z "$song_rel_path" ] || [ "$song_rel_path" = "." ] || [ "$song_rel_path" = ".." ]; then
  echo "❌ Destino invalido: indique a pasta da musica sob Songs/ (ex.: 'System of a Down - Soil'), nao 'Songs' sozinho. Recebido: '$2'" >&2
  exit 1
fi

if [[ "$song_rel_path" == *..* ]]; then
  echo "❌ '..' nao e permitido no destino. Use so o caminho desejado em Songs/." >&2
  exit 1
fi

DEST_SONG_DIR="${REPO_DIR}/Songs/${song_rel_path}"
mkdir -p "$DEST_SONG_DIR"

SONGSTERR_MID="${SOURCE_DIR}/notes.songsterr.mid"
if [ ! -f "$SONGSTERR_MID" ]; then
  echo "❌ Falta notes.songsterr.mid em: $SOURCE_DIR" >&2
  exit 1
fi

for item in "$SOURCE_DIR"/*; do
  if [ ! -e "$item" ]; then
    continue
  fi

  base_name="$(basename "$item")"
  case "$base_name" in
    *.mid|*.chart)
      continue
      ;;
  esac
  cp -a "$item" "$DEST_SONG_DIR/"
done

cp -a "$SONGSTERR_MID" "$DEST_SONG_DIR/notes.mid"

echo "✅ Sync concluido: notes.songsterr.mid -> Songs/${song_rel_path}/notes.mid"
echo "   Origem: $SOURCE_DIR"
echo "   Destino: $DEST_SONG_DIR"

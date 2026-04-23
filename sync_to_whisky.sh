#!/usr/bin/env bash
# Sincroniza as charts deste repo para o Desktop do bottle do Whisky,
# para abrir no Moonscraper (Mac → Wine → Windows app).
#
# Cria duas pastas no Desktop do bottle:
#   SOAD-oficial/<música>/  → notes.mid original + song.ini + album.jpg
#   SOAD-gerado/<música>/   → notes.mid apontando para a versão mais recente
#                              + cópias notes.songsterr-<dd-mm-hh-mm>.mid ou
#                              notes.gen-<dd-mm-hh-mm>.mid para identificar a sync
#
# Áudio (.opus) é deixado de fora (Moonscraper não precisa).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WHISKY_BOTTLES="$HOME/Library/Containers/com.isaacmarovitz.Whisky/Bottles"
RUN_STAMP="$(date '+%d-%m-%H-%M')"

if [ ! -d "$WHISKY_BOTTLES" ]; then
  echo "❌ Whisky não encontrado em $WHISKY_BOTTLES" >&2
  exit 1
fi

# Detecta a bottle (assume único — se houver mais, pega o mais recente)
BOTTLE_UUID="$(ls -1t "$WHISKY_BOTTLES" | head -1)"
if [ -z "$BOTTLE_UUID" ]; then
  echo "❌ Nenhuma bottle do Whisky encontrada em $WHISKY_BOTTLES" >&2
  exit 1
fi

DESKTOP="$WHISKY_BOTTLES/$BOTTLE_UUID/drive_c/users/crossover/Desktop"
if [ ! -d "$DESKTOP" ]; then
  echo "❌ Desktop não encontrado em $DESKTOP" >&2
  exit 1
fi

OFICIAL="$DESKTOP/SOAD-oficial"
GERADO="$DESKTOP/SOAD-gerado"
CUSTOM="$DESKTOP/SOAD-custom"

# Limpa runs anteriores
rm -rf "$OFICIAL" "$GERADO" "$CUSTOM"
mkdir -p "$OFICIAL" "$GERADO" "$CUSTOM"

# Converte/copia áudio .opus para a pasta destino. Moonscraper não lê .opus,
# então transcodamos para .ogg (Vorbis, qualidade 6 ~ 192kbps). Cache: se o
# .ogg já existe em cache/ com mtime ≥ ao do .opus, reaproveita.
CACHE_DIR="$REPO_DIR/_cache_ogg"
mkdir -p "$CACHE_DIR"

copy_audio_as_ogg() {
  local src_folder="$1" dst_folder="$2"
  for opus in "$src_folder"/*.opus; do
    [ -f "$opus" ] || continue
    local base="$(basename "$opus" .opus)"
    # Hash do caminho absoluto + mtime para chave de cache estável por song
    local key="$(echo -n "$opus" | shasum -a 1 | cut -c1-12)-$base"
    local cached="$CACHE_DIR/$key.ogg"
    if [ ! -f "$cached" ] || [ "$opus" -nt "$cached" ]; then
      ffmpeg -loglevel error -y -i "$opus" -c:a libvorbis -q:a 6 "$cached"
    fi
    cp "$cached" "$dst_folder/$base.ogg"
  done
}

copy_mid_with_timestamp() {
  local src_mid="$1" dst_folder="$2" plain_name="$3"
  cp "$src_mid" "$dst_folder/$plain_name.mid"
  cp "$src_mid" "$dst_folder/$plain_name-$RUN_STAMP.mid"
}

sanitize_windows_name() {
  local raw_name="$1"
  local sanitized_name="$raw_name"

  while [[ "$sanitized_name" == *"." || "$sanitized_name" == *" " ]]; do
    sanitized_name="${sanitized_name%?}"
  done

  printf '%s' "$sanitized_name"
}

count=0
for src in "$REPO_DIR"/System*/; do
  song_full="$(basename "$src")"
  # Nome curto: tira "System of a Down - " e "(Harmonix)"
  short_name="$(echo "$song_full" | sed -e 's/System of a Down - //' -e 's/ (Harmonix)//')"
  short_name="$(sanitize_windows_name "$short_name")"

  off_dir="$OFICIAL/$short_name"
  gen_dir="$GERADO/$short_name"
  mkdir -p "$off_dir" "$gen_dir"

  # Original
  cp "$src/notes.mid" "$off_dir/notes.mid"
  [ -f "$src/song.ini" ]  && cp "$src/song.ini"  "$off_dir/"
  [ -f "$src/album.jpg" ] && cp "$src/album.jpg" "$off_dir/"
  copy_audio_as_ogg "$src" "$off_dir"

  # Gerado: prioriza import Songsterr; fallback para notes.gen.mid do reducer.
  if [ -f "$src/notes.songsterr.mid" ]; then
    cp "$src/notes.songsterr.mid" "$gen_dir/notes.mid"
    copy_mid_with_timestamp "$src/notes.songsterr.mid" "$gen_dir" "notes.songsterr"
    [ -f "$src/notes.gen.mid" ] && copy_mid_with_timestamp "$src/notes.gen.mid" "$gen_dir" "notes.gen"
  elif [ -f "$src/notes.gen.mid" ]; then
    cp "$src/notes.gen.mid" "$gen_dir/notes.mid"
    copy_mid_with_timestamp "$src/notes.gen.mid" "$gen_dir" "notes.gen"
  else
    echo "⚠️  $short_name: notes.songsterr.mid e notes.gen.mid não existem"
  fi
  [ -f "$src/song.ini" ]  && cp "$src/song.ini"  "$gen_dir/"
  [ -f "$src/album.jpg" ] && cp "$src/album.jpg" "$gen_dir/"
  copy_audio_as_ogg "$src" "$gen_dir"

  count=$((count + 1))
done

# Custom songs (charts da comunidade em custom/)
custom_count=0
if [ -d "$REPO_DIR/custom" ]; then
  for src in "$REPO_DIR/custom"/*/; do
    [ -d "$src" ] || continue
    song_full="$(basename "$src")"
    short_name="$(echo "$song_full" | sed -e 's/System of a Down - //')"
    short_name="$(sanitize_windows_name "$short_name")"
    dst="$CUSTOM/$short_name"
    mkdir -p "$dst"
    # Copia todos os arquivos não-opus, e transcoda .opus → .ogg para Moonscraper
    for f in "$src"/*; do
      [ -f "$f" ] || continue
      case "$f" in *.opus) continue;; esac
      cp "$f" "$dst/"
    done
    copy_audio_as_ogg "$src" "$dst"
    custom_count=$((custom_count + 1))
  done
fi

echo "✅ Copiadas $count músicas Harmonix (oficial+gerado) e $custom_count custom."
echo "🕒 Timestamp desta sync: $RUN_STAMP"
echo ""
echo "📂 Caminhos no Mac:"
echo "    $OFICIAL"
echo "    $GERADO"
echo "    $CUSTOM"
echo ""
echo "🖱  No Moonscraper (Whisky), abra File → Open File → Desktop:"
echo "    SOAD-oficial/<música>/notes.mid   (chart oficial Harmonix)"
echo "    SOAD-gerado/<música>/notes.mid    (atalho para a versão mais recente)"
echo "    SOAD-gerado/<música>/notes.songsterr-$RUN_STAMP.mid ou notes.gen-$RUN_STAMP.mid"
echo "    SOAD-custom/<música>/notes.chart  (charts da comunidade)"

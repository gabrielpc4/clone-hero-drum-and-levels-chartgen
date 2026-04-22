#!/usr/bin/env bash
# Sincroniza as charts deste repo para o Desktop do bottle do Whisky,
# para abrir no Moonscraper (Mac → Wine → Windows app).
#
# Cria duas pastas no Desktop do bottle:
#   SOAD-oficial/<música>/  → notes.mid original + song.ini + album.jpg
#   SOAD-gerado/<música>/   → notes.gen.mid renomeado para notes.mid + song.ini + album.jpg
#
# Áudio (.opus) é deixado de fora (Moonscraper não precisa).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WHISKY_BOTTLES="$HOME/Library/Containers/com.isaacmarovitz.Whisky/Bottles"

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

# Limpa runs anteriores
rm -rf "$OFICIAL" "$GERADO"
mkdir -p "$OFICIAL" "$GERADO"

count=0
for src in "$REPO_DIR"/System*/; do
  song_full="$(basename "$src")"
  # Nome curto: tira "System of a Down - " e "(Harmonix)"
  short_name="$(echo "$song_full" | sed -e 's/System of a Down - //' -e 's/ (Harmonix)//')"

  off_dir="$OFICIAL/$short_name"
  gen_dir="$GERADO/$short_name"
  mkdir -p "$off_dir" "$gen_dir"

  # Original
  cp "$src/notes.mid" "$off_dir/notes.mid"
  [ -f "$src/song.ini" ]  && cp "$src/song.ini"  "$off_dir/"
  [ -f "$src/album.jpg" ] && cp "$src/album.jpg" "$off_dir/"
  [ -f "$src/song.opus" ] && cp "$src/song.opus" "$off_dir/"

  # Gerado (notes.gen.mid renomeado para notes.mid)
  if [ -f "$src/notes.gen.mid" ]; then
    cp "$src/notes.gen.mid" "$gen_dir/notes.mid"
  else
    echo "⚠️  $short_name: notes.gen.mid não existe, gere com 'python3 _analysis/midi_writer.py'"
  fi
  [ -f "$src/song.ini" ]  && cp "$src/song.ini"  "$gen_dir/"
  [ -f "$src/album.jpg" ] && cp "$src/album.jpg" "$gen_dir/"
  [ -f "$src/song.opus" ] && cp "$src/song.opus" "$gen_dir/"

  count=$((count + 1))
done

echo "✅ Copiadas $count músicas para o Desktop do Whisky."
echo ""
echo "📂 Caminhos no Mac:"
echo "    $OFICIAL"
echo "    $GERADO"
echo ""
echo "🖱  No Moonscraper (dentro do Whisky), abra File → Open File → Desktop:"
echo "    SOAD-oficial/<música>/notes.mid   (chart oficial Harmonix)"
echo "    SOAD-gerado/<música>/notes.mid    (chart gerado pelo nosso reducer)"

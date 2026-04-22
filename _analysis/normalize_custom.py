"""
Normaliza metadados das músicas em custom/:
  1. Prefixo da pasta e artist → "System of a Down"
  2. Album: correções de casing/pontuação
  3. Genre → "Nu Metal" (convenção Harmonix)
  4. Charter "Fuck the System": remove tags <color=...> HTML

Uso:
  python3 _analysis/normalize_custom.py            → dry-run (mostra o que mudaria)
  python3 _analysis/normalize_custom.py --apply    → aplica as mudanças
"""
from __future__ import annotations
import os, re, sys, shutil

BASE = "/Users/gabrielcarvalho/Downloads/system/custom"

ARTIST_CANONICAL = "System of a Down"
GENRE_CANONICAL  = "Nu Metal"

ALBUM_MAP = {
    "Steal This Album":                         "Steal This Album!",
    "System Of A Down":                         "System of a Down",
    "Protect The Land/Genocidal Humanoidz":     "Protect The Land / Genocidal Humanoidz",
}

ARTIST_PREFIX_VARIANTS = {
    "System Of A Down", "System of a Down",
    "System Of a Down", "System of A Down",
}


def normalize_charter(s: str) -> str:
    """Remove tags <color=...>...</color> usadas só para estilização."""
    return re.sub(r"</?color[^>]*>", "", s).strip()


def new_folder_name(old: str) -> str:
    """Substitui o prefixo '... - ' pela forma canônica, preservando o resto."""
    for variant in ARTIST_PREFIX_VARIANTS:
        prefix = variant + " - "
        if old.startswith(prefix):
            return ARTIST_CANONICAL + " - " + old[len(prefix):]
    return old


def normalize_song_ini(text: str) -> tuple[str, dict]:
    """Aplica as normalizações no conteúdo de um song.ini.
    Devolve (novo_texto, diff)."""
    diff = {}
    lines = text.splitlines(keepends=True)
    out_lines = []
    for line in lines:
        m = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*?)(\s*)$", line)
        if not m:
            out_lines.append(line); continue
        lead, key, eq, val, trail = m.groups()
        key_lc = key.lower()
        new_val = val

        if key_lc == "artist" and val in ARTIST_PREFIX_VARIANTS:
            new_val = ARTIST_CANONICAL
        elif key_lc == "album" and val in ALBUM_MAP:
            new_val = ALBUM_MAP[val]
        elif key_lc == "genre":
            new_val = GENRE_CANONICAL
        elif key_lc == "charter":
            cleaned = normalize_charter(val)
            if cleaned != val:
                new_val = cleaned

        if new_val != val:
            diff[key_lc] = (val, new_val)
            out_lines.append(f"{lead}{key}{eq}{new_val}\n")
        else:
            out_lines.append(line)
    return "".join(out_lines), diff


def run(apply: bool):
    folders = sorted(os.listdir(BASE))
    renamed, edited = 0, 0
    for d in folders:
        old_path = os.path.join(BASE, d)
        if not os.path.isdir(old_path): continue
        new_name = new_folder_name(d)
        ini_path = os.path.join(old_path, "song.ini")
        ini_diff = {}
        if os.path.isfile(ini_path):
            try:
                text = open(ini_path, encoding="utf-8").read()
            except UnicodeDecodeError:
                text = open(ini_path, encoding="latin-1").read()
            new_text, ini_diff = normalize_song_ini(text)
        if new_name != d or ini_diff:
            print(f"\n{d}")
            if new_name != d:
                print(f"  RENAME → {new_name}")
                renamed += 1
            for k, (old, new) in ini_diff.items():
                print(f"  {k}: {old!r} → {new!r}")
            if ini_diff: edited += 1
            if apply:
                if ini_diff:
                    with open(ini_path, "w", encoding="utf-8") as f:
                        f.write(new_text)
                if new_name != d:
                    shutil.move(old_path, os.path.join(BASE, new_name))
    print(f"\n{'APLICADO' if apply else 'DRY-RUN'}: {renamed} pastas renomeadas, {edited} song.ini editados")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)

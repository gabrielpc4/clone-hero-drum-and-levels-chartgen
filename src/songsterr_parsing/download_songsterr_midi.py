"""
Baixa o MIDI de uma aba Songsterr (cookies ajudam no POST; Plus pode ser necessário).

Ordem: (1) tenta POST /api/edits/download com payload da parte completa (JSON da
pista, como o site faz), para obter MIDI com markers; (2) tenta POST simples por
índice de pista; (3) fallback para /api/revision `source` (.gp) + Node/alphatab.
Alguns tabs continuam a falhar no servidor do Songsterr com HTTP 500.

Uso:
  python download_songsterr_midi.py "https://www.songsterr.com/a/wsa/...-s21961" "C:\\saida\\songsterr_in.mid" --cookie-file cookies.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

SONGSTERR_BASE = "https://www.songsterr.com"
_PART_HOSTS_WITH_IMAGE: tuple[str, ...] = (
    "dqsljvtekg760",
    "d34shlm8p2ums2",
    "d3cqchs6g3b5ew",
)
_PART_HOSTS_LEGACY: tuple[str, ...] = (
    "d3rrfvx08uyjp1",
    "dodkcbujl0ebx",
    "dj1usja78sinh",
)

# Browser-like headers: some Songsterr endpoints 500 on bare script requests.
_POST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": SONGSTERR_BASE,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}


def _load_cookie_file(path: Path) -> requests.cookies.RequestsCookieJar:
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    jar = requests.cookies.RequestsCookieJar()
    if isinstance(data, dict) and "cookies" in data:
        item_list: list[dict[str, Any]] = list(data["cookies"])
    elif isinstance(data, list):
        item_list = list(data)
    else:
        raise SystemExit("Formato de cookies: array JSON de {name, value, domain?, path?} ou {cookies: [...]}")

    for item in item_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain") or ".songsterr.com"
        path_s = item.get("path") or "/"
        if not name or value is None:
            continue
        jar.set(name, str(value), domain=domain, path=path_s)
    return jar


def _parse_song_id_from_url(url: str) -> int:
    s = url.strip()
    m = re.search(r"(?:-s|song[_-]?id=|/song/|songs/)(\d+)", s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    parsed = urlparse(s)
    parts = [p for p in parsed.path.split("/") if p]
    for segment in parts:
        m2 = re.search(r"-s(\d+)$", segment, re.IGNORECASE)
        if m2:
            return int(m2.group(1))
    raise SystemExit("Não foi possível obter o songId do URL. Inclua um link com o sufixo -s< id > ou use --song-id.")


def _drum_part_index(tracks: list[dict[str, Any]]) -> int | None:
    for i, t in enumerate(tracks):
        if t.get("instrumentId") == 1024 or t.get("isDrums") is True:
            return i
    return None


def _fetch_json(session: requests.Session, method: str, rel: str, referer: str | None = None) -> Any:
    url = rel if rel.startswith("http") else f"{SONGSTERR_BASE}{rel}"
    h = {
        "User-Agent": _POST_HEADERS["User-Agent"],
        "Accept": "application/json",
    }
    if referer is not None:
        h["Referer"] = referer
    r = session.request(method, url, timeout=60, headers=h)
    r.raise_for_status()
    if "application/json" in r.headers.get("Content-Type", ""):
        return r.json()
    return None


def _http_error_excerpt(r: requests.Response) -> str:
    try:
        t = r.text.strip()
    except Exception:
        return str(len(r.content or b"")) + " bytes (no text)"
    return (t[:2000] + "…") if len(t) > 2000 else t


def _post_export_server_error_hint(response: requests.Response) -> str | None:
    if response.status_code < 500:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    err = str(data.get("error") or data.get("message") or "")
    if "measures" in err or "not iterable" in err:
        return (
            "O Songsterr devolveu erro 500 na exportação (falha no servidor deles, ex. 'measures' no corpo). "
            "Isto ocorre em tabs sem URL pública .gp no campo `source` de /api/revision; este script não consegue "
            "obter o MIDI nesse caso até o site corrigir a API ou fornecerem outro link."
        )
    return None


def _post_download_midi(
    session: requests.Session, post_url: str, body: dict[str, Any], page_url: str
) -> requests.Response:
    headers = {**_POST_HEADERS, "Referer": page_url or f"{SONGSTERR_BASE}/a/wsa/"}
    return session.post(post_url, json=body, timeout=120, headers=headers)


def _published_gp_source_url(revision: Any) -> str | None:
    if not isinstance(revision, dict):
        return None
    src = revision.get("source")
    if not isinstance(src, str):
        return None
    t = src.strip()
    if not t.lower().startswith("http"):
        return None
    if ".gp" in t or "gp.songsterr.com" in t:
        return t
    return None


def _download_bytes(session: requests.Session, url: str, referer: str) -> bytes:
    h = {**_POST_HEADERS, "Referer": referer, "Accept": "*/*"}
    r = session.get(url, timeout=120, headers=h)
    r.raise_for_status()
    return r.content


def _part_payload_urls(song_id: int, revision_id: int, image: str, part_index: int) -> list[str]:
    urls: list[str] = []
    image_clean = image.strip()
    if image_clean:
        for host in _PART_HOSTS_WITH_IMAGE:
            urls.append(f"https://{host}.cloudfront.net/{song_id}/{revision_id}/{image_clean}/{part_index}.json")
    for host in _PART_HOSTS_LEGACY:
        urls.append(f"https://{host}.cloudfront.net/part/{revision_id}/{part_index}")
    return urls


def _download_part_payload(
    session: requests.Session,
    song_id: int,
    revision_id: int,
    image: str,
    part_index: int,
    referer: str,
) -> dict[str, Any] | None:
    headers = {
        "User-Agent": _POST_HEADERS["User-Agent"],
        "Accept": "application/json",
        "Referer": referer,
    }
    for url in _part_payload_urls(song_id, revision_id, image, part_index):
        try:
            response = session.get(url, headers=headers, timeout=60)
        except requests.RequestException:
            continue
        if not response.ok:
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("measures"), list) and payload.get("measures"):
            return payload
    return None


def _this_script_dir() -> Path:
    return Path(__file__).resolve().parent


def _convert_gp_bytes_to_midi_node(gp_data: bytes, out_mid: Path) -> str | None:
    node = shutil.which("node")
    if not node:
        return "comando 'node' não está no PATH (instale Node.js LTS)"
    d = _this_script_dir()
    mjs = d / "gp7_to_midi.mjs"
    if not mjs.is_file():
        return f"falta {mjs}"
    if not (d / "node_modules" / "@coderline" / "alphatab" / "package.json").is_file():
        return (
            "falta dependência: na pasta " + str(d) + " execute: npm install"
        )
    fd, gp_tmp = tempfile.mkstemp(suffix=".gp", prefix="songsterr_")
    proc: subprocess.CompletedProcess[str] | None = None
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(gp_data)
        cmd = [node, str(mjs), gp_tmp, str(out_mid)]
        proc = subprocess.run(  # noqa: S603 — argv from fixed dir + which(node)
            cmd,
            cwd=str(d),
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        try:
            os.unlink(gp_tmp)
        except OSError:
            pass
    if proc is None or proc.returncode != 0:
        if proc is None:
            msg = ""
        else:
            msg = (proc.stderr or proc.stdout or "").strip()
        if len(msg) > 5000:
            msg = msg[:5000] + "…"
        code = proc.returncode if proc is not None else -1
        return "node gp7_to_midi falhou (código " + str(code) + "): " + (msg or "(sem saída)")
    return None


def _download_midi_from_gp_if_available(
    session: requests.Session, revision_id: int, out_path: Path, page_referer: str
) -> bool:
    try:
        rev = _fetch_json(session, "GET", f"/api/revision/{int(revision_id)}", referer=page_referer)
    except Exception as ex:
        print("Não usei o fallback do .gp: /api/revision: " + str(ex), file=sys.stderr)
        return False
    gp_url = _published_gp_source_url(rev)
    if not gp_url:
        return False
    gp_data = _download_bytes(session, gp_url, page_referer)
    if len(gp_data) < 64:
        return False
    err = _convert_gp_bytes_to_midi_node(gp_data, out_path)
    if err is not None:
        print("MIDI a partir de .gp (source): " + err, file=sys.stderr)
        return False
    return out_path.is_file() and out_path.stat().st_size > 32


def _download_midi_from_post(
    session: requests.Session, body: dict[str, Any], out_path: Path, ref: str
) -> bool:
    post_url = f"{SONGSTERR_BASE}/api/edits/download"
    r = _post_download_midi(session, post_url, body, ref)
    if r.status_code in (500, 502, 503, 504):
        time.sleep(2.0)
        r = _post_download_midi(session, post_url, body, ref)
    if r.status_code in (401, 403):
        try:
            err = r.json()
        except Exception:
            err = r.text
        print(
            f"POST /api/edits/download: exportação não autorizada (HTTP {r.status_code}): {err!r}",
            file=sys.stderr,
        )
        return False
    if r.status_code >= 500 or not r.ok:
        extra = _post_export_server_error_hint(r)
        if extra is not None:
            print(extra, file=sys.stderr)
        print("POST /api/edits/download falhou: " + str(r.status_code) + " " + _http_error_excerpt(r), file=sys.stderr)
        return False
    _write_download_result(r, out_path)
    return out_path.is_file() and out_path.stat().st_size > 32


def _download_midi(
    session: requests.Session,
    song_id: int,
    out_path: Path,
    part_id_override: int | None,
    page_url: str,
) -> None:
    ref = (page_url.strip() or f"{SONGSTERR_BASE}/a/wsa/")
    meta = _fetch_json(session, "GET", f"/api/meta/{song_id}", referer=ref)
    if not isinstance(meta, dict):
        raise SystemExit("Resposta inválida de /api/meta")
    revision_id = meta.get("revisionId")
    if revision_id is None:
        raise SystemExit("api/meta não contém revisionId")
    tracks = meta.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise SystemExit("api/meta não contém tracks")
    image = meta.get("image")
    image_hash = image if isinstance(image, str) else ""

    if part_id_override is not None:
        part_index = int(part_id_override)
    else:
        drum = _drum_part_index(tracks)
        if drum is None:
            ptd = meta.get("popularTrackDrum")
            if ptd is not None:
                part_index = int(ptd)
            else:
                raise SystemExit("Não encontrei pista de bateria; use --part-index.")
        else:
            part_index = drum

    body: dict[str, Any] = {
        "revisionId": int(revision_id),
        "songId": int(song_id),
        "parts": [part_index],
        "lyrics": [],
        "midi": True,
    }
    part_payload = _download_part_payload(
        session=session,
        song_id=int(song_id),
        revision_id=int(revision_id),
        image=image_hash,
        part_index=int(part_index),
        referer=ref,
    )
    if part_payload is not None:
        body_with_part_payload = {
            "revisionId": int(revision_id),
            "songId": int(song_id),
            "parts": [part_payload],
            "lyrics": [],
            "midi": True,
        }
        if _download_midi_from_post(session, body_with_part_payload, out_path, ref):
            return
    if _download_midi_from_post(session, body, out_path, ref):
        return
    if _download_midi_from_gp_if_available(session, int(revision_id), out_path, ref):
        return
    raise SystemExit(
        "Não foi possível obter o MIDI por POST (payload completo e simples). Se /api/revision tiver `source` com .gp, "
        "instale dependências: na pasta "
        + str(_this_script_dir())
        + " execute `npm install` e use Node no PATH. Caso `source` esteja vazio e o POST 500, o Songsterr não "
        "exportou o tab; confirme login Plus/cookies e tente outro tab ou mais tarde."
    )


def _write_download_result(response: requests.Response, out_path: Path) -> None:
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        data = response.json()
        if isinstance(data, dict) and data.get("code"):
            code = data.get("code", "")
            msg = data.get("message") or data.get("error", "")
            raise SystemExit(f"API Songsterr: {code} {msg}".strip())
        for key in ("url", "link", "downloadUrl", "fileUrl", "signedUrl", "path"):
            if key in data and data[key]:
                u = str(data[key])
                if u.startswith("http"):
                    s2 = requests.get(u, timeout=120)
                    s2.raise_for_status()
                    out_path.write_bytes(s2.content)
                    return
        for key in ("data", "result", "file"):
            inner = data.get(key)
            if isinstance(inner, dict) and "url" in inner:
                u2 = str(inner["url"])
                s3 = requests.get(u2, timeout=120)
                s3.raise_for_status()
                out_path.write_bytes(s3.content)
                return
        if "source" in data and isinstance(data["source"], str) and data["source"].startswith("http"):
            s4 = requests.get(data["source"], timeout=120)
            s4.raise_for_status()
            out_path.write_bytes(s4.content)
            return
        raise SystemExit("Resposta JSON inesperada; atualize o parser com a estrutura real. Corpo: " + json.dumps(data)[:2000])
    if "mid" in content_type or "octet-stream" in content_type or "audio" in content_type or response.content[:4] in (b"MThd", b"RIFF"):
        out_path.write_bytes(response.content)
        return
    text_start = response.text[:200].lstrip()
    if text_start.startswith("MThd") or (response.content and response.content[0:4] == b"MThd"):
        out_path.write_bytes(response.content)
        return
    raise SystemExit("Tipo de resposta não suportado: " + content_type + " tamanho=" + str(len(response.content)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Baixa MIDI do Songsterr (com cookies de sessão).")
    ap.add_argument("songsterr_url", help="URL da aba (ex. /a/wsa/...-s21961)")
    ap.add_argument("output_mid", help="Arquivo .mid de saída")
    ap.add_argument("--cookie-file", required=True, type=Path, help="JSON de cookies (exportado a partir do WebView2 / manual)")
    ap.add_argument("--song-id", type=int, default=None, help="Substitui o songId se o URL não tiver -sN")
    ap.add_argument("--part-index", type=int, default=None, help="Índice da pista no editor (bateria por padrão)")
    args = ap.parse_args()
    if not args.cookie_file.is_file():
        raise SystemExit(f"Arquivo de cookies inexistente: {args.cookie_file}")
    out = Path(args.output_mid).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    song_id = args.song_id if args.song_id is not None else _parse_song_id_from_url(args.songsterr_url)

    session = requests.Session()
    session.cookies = _load_cookie_file(args.cookie_file)
    _download_midi(session, song_id, out, args.part_index, args.songsterr_url.strip() or f"{SONGSTERR_BASE}/")
    if not out.is_file() or out.stat().st_size < 32:
        raise SystemExit("Arquivo de saída muito pequeno; o download pode ter falhado.")


if __name__ == "__main__":
    main()

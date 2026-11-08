"""
Motion graphics: sobrepõe um clipe de "overlay" (título animado, lower
third, transição gráfica...) em cima do vídeo já montado — tudo via FFmpeg,
sem nenhuma lib paga. Aceita dois tipos de arquivo de overlay, bem comuns
em bancos royalty-free (Mixkit, Pixabay, Videvo):

- Fundo transparente de verdade (canal alfa): .webm com VP9+alpha, ou .mov
  ProRes 4444 — a gente detecta isso sozinho olhando o pix_fmt do ffprobe.
- Fundo verde (chroma key): qualquer vídeo comum com fundo verde — a gente
  aplica remoção de verde (colorkey) antes de sobrepor.
"""
import json
import os
import subprocess

from . import render as R

_ALPHA_PREFIXES = ("yuva",)
_ALPHA_EXACT = {"rgba", "bgra", "argb", "abgr"}


def has_alpha_channel(path: str) -> bool:
    """Olha o pix_fmt do primeiro stream de vídeo via ffprobe — se for um
    dos formatos com canal alfa (prefixo "yuva..." tipo yuva420p/yuva444p10le,
    ou rgba/bgra/argb/abgr), o arquivo já tem fundo transparente de verdade
    (não precisa de chroma key). Isso cobre bem .mov ProRes 4444. Alguns
    .webm com VP9+alpha guardam o canal alfa separado do pix_fmt principal
    e podem não ser detectados aqui — nesse caso, use mode="alpha" na mão
    ao chamar overlay_motion_graphic, ou prefira um arquivo com fundo verde
    (chroma key), que funciona em qualquer formato."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt", "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(out.stdout).get("streams", [])
        if not streams:
            return False
        pix_fmt = streams[0].get("pix_fmt", "")
        return pix_fmt.startswith(_ALPHA_PREFIXES) or pix_fmt in _ALPHA_EXACT
    except Exception:
        return False


def overlay_motion_graphic(
    base_video_path: str,
    overlay_path: str,
    out_path: str,
    start: float = 0.0,
    mode: str = "auto",
    chromakey_color: str = "0x00FF00",
    similarity: float = 0.18,
    blend: float = 0.08,
):
    """Sobrepõe overlay_path em cima de base_video_path a partir do segundo
    `start`, pela duração do próprio overlay (ou o que sobrar do vídeo base,
    o que for menor). O áudio final é sempre o do vídeo base — o overlay
    normalmente é só gráfico/mudo, mesmo quando tem trilha própria.

    mode: "auto" (detecta canal alfa sozinho), "alpha" (força overlay com
    canal alfa) ou "chromakey" (força remoção de fundo verde).
    """
    base_video_path = os.path.abspath(base_video_path)
    overlay_path = os.path.abspath(overlay_path)
    out_path = os.path.abspath(out_path)

    base_duration = R.ffprobe_duration(base_video_path)
    overlay_duration = R.ffprobe_duration(overlay_path)
    # não deixa o overlay começar depois do vídeo já ter acabado
    start = max(0.0, min(start, max(0.0, base_duration - 0.1)))
    end = min(base_duration, start + overlay_duration)

    if mode == "auto":
        mode = "alpha" if has_alpha_channel(overlay_path) else "chromakey"

    if mode == "chromakey":
        overlay_filter = (
            f"[1:v]colorkey={chromakey_color}:{similarity:.3f}:{blend:.3f}[ovkeyed];"
            f"[ovkeyed]setpts=PTS+{start:.3f}/TB[ov]"
        )
    else:
        overlay_filter = f"[1:v]format=yuva420p,setpts=PTS+{start:.3f}/TB[ov]"

    filter_complex = (
        f"{overlay_filter};"
        f"[0:v][ov]overlay=enable='between(t,{start:.3f},{end:.3f})':shortest=0[vout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", base_video_path,
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    R._run(cmd)
    return out_path

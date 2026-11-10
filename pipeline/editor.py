"""
Editor manual por linha do tempo (estilo CapCut/Premiere): várias faixas de
vídeo/imagem (camadas, a de cima fica na frente) e várias faixas de áudio.
Cada clipe tem posição na linha do tempo, trecho usado da mídia original,
volume, opacidade, tamanho, posição na tela e fade. O export monta tudo de
uma vez só com um único comando FFmpeg (filter_complex).

Formato do projeto recebido do navegador:
{
  "width": 1920, "height": 1080, "fps": 30,
  "tracks": [   # na ordem da tela: a primeira faixa é a camada mais de cima
    {"type": "video"|"audio", "muted": false, "hidden": false,
     "clips": [{"asset_id", "start", "dur", "in", "volume", "opacity",
                "scale", "x", "y", "fade_in", "fade_out"}]}
  ]
}
"""
import json
import math
import os
import array
import subprocess
import sys
import tempfile
from functools import lru_cache

from . import captions as C
from . import render as R

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
SAMPLE_RATE = 48000
MAX_CANVAS = 4096


def audio_peaks(path: str, rate: int = 8000, samples_per_peak: int = 80) -> list[float]:
    """Calcula picos mono por janela, sem carregar o áudio inteiro na memória."""
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-vn",
         "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    peaks = []
    try:
        while True:
            data = process.stdout.read(samples_per_peak * 2)
            if not data:
                break
            samples = array.array("h")
            samples.frombytes(data)
            if sys.byteorder != "little":
                samples.byteswap()
            peaks.append(round(max(abs(sample) for sample in samples) / 32768, 4))
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(f"Não foi possível gerar as ondas de áudio: {stderr.strip()}")
    finally:
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    return peaks


def probe_media(path: str) -> dict:
    """Descobre tipo (video/audio/image), duração, tamanho e se tem áudio."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    ext = os.path.splitext(path)[1].lower()

    if ext in IMAGE_EXTS and video:
        kind = "image"
    elif video:
        kind = "video"
    elif audio:
        kind = "audio"
    else:
        raise ValueError("Arquivo sem vídeo, imagem ou áudio reconhecível.")

    width = height = 0
    if video:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        rotation = 0
        try:
            rotation = int(float((video.get("tags") or {}).get("rotate", 0)))
        except (TypeError, ValueError):
            pass
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(float(sd["rotation"]))
        if abs(rotation) % 180 == 90:
            width, height = height, width

    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if kind == "image":
        duration = 0.0

    return {
        "kind": kind,
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": bool(audio) and kind != "image",
        "vp9_alpha": bool(video and video.get("codec_name") == "vp9"
                          and (video.get("tags") or {}).get("alpha_mode") == "1"),
    }


def _num(value, default, lo=None, hi=None):
    try:
        x = float(value)
    except (TypeError, ValueError):
        x = default
    if not math.isfinite(x):
        x = default
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def _even(n: float) -> int:
    n = max(2, int(round(n)))
    return n - (n % 2)


@lru_cache(maxsize=1)
def _filter_script_option():
    help_text = subprocess.run(
        ["ffmpeg", "-hide_banner", "-h", "full"],
        capture_output=True, text=True, check=True,
    ).stdout
    return "-filter_complex_script" if "-filter_complex_script" in help_text else "-/filter_complex"


def _build_command(project: dict, assets: dict, out_path: str, script_path: str, normalize_flag: bool, audio_only=False):
    width = _even(_num(project.get("width"), 1920, 2, MAX_CANVAS))
    height = _even(_num(project.get("height"), 1080, 2, MAX_CANVAS))
    fps = int(_num(project.get("fps"), 30, 1, 60))

    tracks = project.get("tracks", [])
    total = 0.0
    for track in tracks:
        for clip in track.get("clips", []):
            if clip.get("asset_id") not in assets:
                raise ValueError("Um dos clipes usa uma mídia que não existe mais — reenvie o arquivo.")
            dur = _num(clip.get("dur"), 0, 0)
            if dur >= 0.04:
                total = max(total, _num(clip.get("start"), 0, 0) + dur)

    if total <= 0:
        raise ValueError("A linha do tempo está vazia — adicione pelo menos um clipe antes de exportar.")

    inputs = [
        "-f", "lavfi", "-t", f"{total:.3f}", "-i", f"color=c=black:s={width}x{height}:r={fps}",
        "-f", "lavfi", "-t", f"{total:.3f}", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
    ]
    next_index = 2
    filters = []
    audio_items = []
    current = "0:v"
    overlay_count = 0

    # A primeira faixa da lista é a de cima, então compõe de trás pra frente.
    for track in reversed(tracks):
        ttype = track.get("type")
        hidden = bool(track.get("hidden"))
        muted = bool(track.get("muted"))
        for clip in track.get("clips", []):
            asset = assets[clip["asset_id"]]
            dur = _num(clip.get("dur"), 0, 0)
            if dur < 0.04:
                continue
            start = _num(clip.get("start"), 0, 0)
            src_in = _num(clip.get("in"), 0, 0)
            volume = _num(clip.get("volume"), 1.0, 0, 4.0)
            fade_in = _num(clip.get("fade_in"), 0, 0, dur)
            fade_out = _num(clip.get("fade_out"), 0, 0, dur)
            path = os.path.abspath(asset["path"])
            kind = asset["kind"]

            if ttype == "video" and kind in ("video", "image"):
                if audio_only and (kind != "video" or not asset.get("has_audio") or muted or volume <= 0):
                    continue
                idx = next_index
                next_index += 1
                if kind == "image":
                    inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", path]
                else:
                    inputs += ["-ss", f"{src_in:.3f}", "-t", f"{dur:.3f}"]
                    if not audio_only and path.lower().endswith(".webm"):
                        if "vp9_alpha" not in asset:
                            asset["vp9_alpha"] = probe_media(path)["vp9_alpha"]
                        if asset["vp9_alpha"]:
                            inputs += ["-c:v", "libvpx-vp9"]
                    inputs += ["-i", path]

                if not hidden and not audio_only:
                    scale = _num(clip.get("scale"), 1.0, 0.05, 8.0)
                    opacity = _num(clip.get("opacity"), 1.0, 0, 1.0)
                    cx = _num(clip.get("x"), 0.5, -2, 3)
                    cy = _num(clip.get("y"), 0.5, -2, 3)
                    aw = max(1, asset.get("width") or width)
                    ah = max(1, asset.get("height") or height)
                    fit = min(width / aw, height / ah)
                    w = _even(aw * fit * scale)
                    h = _even(ah * fit * scale)
                    ox = int(round(width * cx - w / 2))
                    oy = int(round(height * cy - h / 2))

                    chain = f"[{idx}:v]setpts=PTS-STARTPTS,fps={fps},scale={w}:{h},format=yuva420p"
                    if opacity < 0.999:
                        chain += f",colorchannelmixer=aa={opacity:.3f}"
                    if fade_in > 0.01:
                        chain += f",fade=t=in:st=0:d={fade_in:.3f}:alpha=1"
                    if fade_out > 0.01:
                        chain += f",fade=t=out:st={max(0, dur - fade_out):.3f}:d={fade_out:.3f}:alpha=1"
                    chain += f",setpts=PTS+{start:.3f}/TB[cv{overlay_count}]"
                    filters.append(chain)
                    nxt = f"ov{overlay_count}"
                    filters.append(
                        f"[{current}][cv{overlay_count}]overlay=x={ox}:y={oy}:format=auto:eof_action=pass[{nxt}]"
                    )
                    current = nxt
                    overlay_count += 1

                if kind == "video" and asset.get("has_audio") and not clip.get("audio_disabled") and not muted and volume > 0:
                    audio_items.append((idx, start, dur, volume, fade_in, fade_out))

            elif ttype == "audio" and asset.get("has_audio") and kind in ("audio", "video"):
                if audio_only and (muted or volume <= 0):
                    continue
                idx = next_index
                next_index += 1
                inputs += ["-ss", f"{src_in:.3f}", "-t", f"{dur:.3f}", "-i", path]
                if not muted and volume > 0:
                    audio_items.append((idx, start, dur, volume, fade_in, fade_out))

    audio_labels = []
    for n, (idx, start, dur, volume, fade_in, fade_out) in enumerate(audio_items):
        chain = (
            f"[{idx}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={volume:.3f}"
        )
        if fade_in > 0.01:
            chain += f",afade=t=in:st=0:d={fade_in:.3f}"
        if fade_out > 0.01:
            chain += f",afade=t=out:st={max(0, dur - fade_out):.3f}:d={fade_out:.3f}"
        delay_ms = int(round(start * 1000))
        chain += f",adelay={delay_ms}|{delay_ms}[ca{n}]"
        filters.append(chain)
        audio_labels.append(f"[ca{n}]")

    if not audio_only:
        if project.get("captions"):
            filters.append(f"[{current}]subtitles=captions.ass[captioned]")
            current = "captioned"
        filters.append(f"[{current}]format=yuv420p[vout]")
    amix = f"amix=inputs={len(audio_labels) + 1}:duration=first:dropout_transition=0"
    if normalize_flag:
        amix += ":normalize=0"
    filters.append("[1:a]" + "".join(audio_labels) + f"{amix},alimiter=limit=0.97[aout]")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(";\n".join(filters))

    if audio_only:
        if not audio_items:
            raise ValueError("Não há áudio ativo na linha do tempo para legendar.")
        return (["ffmpeg", "-y"] + inputs
                + [_filter_script_option(), script_path, "-map", "[aout]",
                   "-t", f"{total:.3f}", "-ac", "1", "-ar", "16000",
                   "-c:a", "pcm_s16le", os.path.abspath(out_path)])

    return (
        ["ffmpeg", "-y"] + inputs
        + [_filter_script_option(), script_path,
           "-map", "[vout]", "-map", "[aout]",
           "-t", f"{total:.3f}", "-r", str(fps),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE),
           "-movflags", "+faststart", os.path.abspath(out_path)]
    )


def export_timeline(project: dict, assets: dict, out_path: str, progress_cb=None) -> str:
    """assets: {asset_id: {"path", "kind", "width", "height", "has_audio", ...}}"""
    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    report(10, "Montando a linha do tempo...")
    with tempfile.TemporaryDirectory(prefix="timeline_") as tmp:
        script_path = os.path.join(tmp, "graph.txt")
        if project.get("captions"):
            C.build_ass_for_cues(project["captions"], os.path.join(tmp, "captions.ass"),
                                 _even(_num(project.get("width"), 1920, 2, MAX_CANVAS)),
                                 _even(_num(project.get("height"), 1080, 2, MAX_CANVAS)))
        cmd = _build_command(project, assets, out_path, script_path, normalize_flag=True)
        report(30, "Renderizando o vídeo (pode demorar um pouco)...")
        try:
            R._run(cmd, cwd=tmp)
        except RuntimeError as e:
            # FFmpeg antigo (< 4.4) não conhece amix normalize=0
            if "normalize" not in str(e):
                raise
            cmd = _build_command(project, assets, out_path, script_path, normalize_flag=False)
            R._run(cmd, cwd=tmp)
    report(100, "Pronto!")
    return out_path


def extract_timeline_audio(project: dict, assets: dict, out_path: str):
    with tempfile.TemporaryDirectory(prefix="timeline_audio_") as tmp:
        script_path = os.path.join(tmp, "graph.txt")
        cmd = _build_command(project, assets, out_path, script_path, normalize_flag=True, audio_only=True)
        try:
            R._run(cmd)
        except RuntimeError as e:
            if "normalize" not in str(e):
                raise
            cmd = _build_command(project, assets, out_path, script_path, normalize_flag=False, audio_only=True)
            R._run(cmd)

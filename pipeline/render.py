"""
Corte, montagem com transições e trilha sonora — tudo via FFmpeg (já
instalado no sistema, gratuito e sem limites de uso).
"""
import json
import os
import subprocess
import tempfile

from . import captions as C
from . import timewarp as TW

ASPECTS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}


_CRASH_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ultimo_erro.log")


def _log_crash(msg: str):
    """Grava o ultimo erro de ffmpeg num arquivo de texto na raiz do
    projeto, pra dar pra ler mesmo sem ver a janela preta do terminal."""
    try:
        import datetime
        with open(_CRASH_LOG, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}]\n{msg}\n")
    except Exception:
        pass


def _run(cmd: list[str], cwd: str | None = None):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        msg = (
            "Comando ffmpeg falhou:\n"
            + " ".join(cmd)
            + "\n\n--- stderr ---\n"
            + result.stderr[-4000:]
        )
        _log_crash(msg)
        raise RuntimeError(msg)
    return result


def ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def _atempo_chain(speed: float) -> str:
    """O filtro atempo só aceita entre 0.5 e 2.0 por vez — encadeia quantos
    forem necessários pra chegar na velocidade pedida."""
    factors = []
    remaining = speed
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    factors.append(remaining)
    return ",".join(f"atempo={f:.6f}" for f in factors)


def _zoom_filter(piece_duration: float, intensidade: float, width: int, height: int, fps: int = 30) -> str:
    total_frames = max(1, round(piece_duration * fps))
    step = (intensidade - 1.0) / total_frames
    return (
        f"zoompan=z='min(1+{step:.8f}*on,{intensidade:.4f})':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
    )


def cut_segment(
    video_path: str,
    segment: dict,
    out_path: str,
    width=1080,
    height=1920,
    burn_captions=True,
    effects: list[dict] | None = None,
    callouts: list[dict] | None = None,
    estilo_legenda: str = "padrao",
):
    """Corta um trecho do vídeo bruto, redimensiona pro formato alvo e
    (opcionalmente) já queima a legenda desse trecho.

    effects: lista opcional de {"tipo": "zoom"|"camera_lenta", "inicio",
    "fim", ...} com tempos RELATIVOS ao início do segmento. Quando presente,
    o clipe é dividido em pedaços e cada um recebe seu tratamento antes de
    ser reunido de novo — sem efeitos, segue o caminho simples de sempre.
    estilo_legenda: nome de um preset visual da legenda (ver
    pipeline/captions.py STYLE_PRESETS — "padrao", "impacto", "minimalista",
    "topo").
    """
    start = segment["start"]
    duration = segment["end"] - segment["start"]
    effects = effects or []

    # Caminhos absolutos: como o ffmpeg vai rodar com o diretório de trabalho
    # trocado pra pasta da legenda (ver nota abaixo sobre o ".ass"), as
    # referências de entrada/saída precisam ser absolutas pra não dependerem
    # de onde o processo foi iniciado.
    video_path = os.path.abspath(video_path)
    out_path = os.path.abspath(out_path)

    ass_path = out_path + ".ass" if burn_captions else None

    if not effects:
        return _cut_segment_simple(video_path, segment, out_path, width, height, ass_path, estilo_legenda)

    pieces = TW.build_pieces(duration, effects)
    remap, _ = TW.time_map_from_pieces(pieces)

    if ass_path:
        C.build_ass_for_segment(
            segment, ass_path, width=width, height=height,
            time_remap=remap, callouts=callouts, style=estilo_legenda,
        )

    filter_parts = []
    concat_labels = []
    for i, piece in enumerate(pieces):
        vbase = f"vb{i}"
        vout = f"v{i}"
        aout = f"a{i}"
        filter_parts.append(
            f"[0:v]trim=start={piece['start']:.3f}:end={piece['end']:.3f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            f"setsar=1,fps=30[{vbase}]"
        )
        filter_parts.append(
            f"[0:a]atrim=start={piece['start']:.3f}:end={piece['end']:.3f},asetpts=PTS-STARTPTS[ab{i}]"
        )

        eff = piece["effect"]
        if eff and eff["tipo"] == "zoom":
            piece_dur = piece["end"] - piece["start"]
            filter_parts.append(f"[{vbase}]{_zoom_filter(piece_dur, eff['intensidade'], width, height)}[{vout}]")
            filter_parts.append(f"[ab{i}]anull[{aout}]")
        elif eff and eff["tipo"] == "camera_lenta":
            mult = 1.0 / eff["velocidade"]
            filter_parts.append(f"[{vbase}]setpts={mult:.6f}*PTS[{vout}]")
            filter_parts.append(f"[ab{i}]{_atempo_chain(eff['velocidade'])}[{aout}]")
        else:
            filter_parts.append(f"[{vbase}]null[{vout}]")
            filter_parts.append(f"[ab{i}]anull[{aout}]")

        concat_labels.append(f"[{vout}][{aout}]")

    filter_parts.append(f"{''.join(concat_labels)}concat=n={len(pieces)}:v=1:a=1[vcat][acat]")

    vmap = "[vcat]"
    if ass_path:
        # Em vez de escapar o caminho completo (com letra de drive e tudo)
        # dentro da string do filtro — o que depende de regras de escape do
        # ffmpeg que variam entre builds e já causou o erro "original_size"
        # em vídeos de usuário real — a gente roda o ffmpeg com o diretório
        # de trabalho JÁ dentro da pasta da legenda e referencia só o nome
        # do arquivo. Sem letra de drive, sem dois-pontos, sem escape nenhum
        # necessário: muito mais robusto no Windows.
        filter_parts.append(f"[vcat]subtitles={os.path.basename(ass_path)}[vfinal]")
        vmap = "[vfinal]"

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        # -ss e -t ANTES do -i: assim os dois valem como opções de LEITURA da
        # entrada (só decodifica esse trecho do vídeo bruto). Se -t viesse
        # depois do -i (como opção de saída), ele truncaria o resultado no
        # tamanho do trecho ORIGINAL, cortando o efeito de câmera lenta.
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
        "-filter_complex", filter_complex,
        "-map", vmap, "-map", "[acat]",
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        out_path,
    ]
    _run(cmd, cwd=os.path.dirname(ass_path) if ass_path else None)

    if ass_path and os.path.exists(ass_path):
        os.remove(ass_path)

    return out_path


def _cut_segment_simple(video_path, segment, out_path, width, height, ass_path, estilo_legenda="padrao"):
    """Caminho rápido/original: sem efeitos de zoom ou câmera lenta."""
    video_path = os.path.abspath(video_path)
    out_path = os.path.abspath(out_path)
    if ass_path:
        ass_path = os.path.abspath(ass_path)

    start = segment["start"]
    duration = segment["end"] - segment["start"]

    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
    ]

    if ass_path:
        C.build_ass_for_segment(segment, ass_path, width=width, height=height, style=estilo_legenda)
        # Mesmo motivo do caminho com efeitos (ver cut_segment): referencia
        # só o NOME do arquivo .ass e roda o ffmpeg com o diretório de
        # trabalho já dentro dessa pasta — evita por completo o problema de
        # escapar a letra de drive do Windows (ex: "C:") dentro da string
        # do filtro, que já causou o erro "original_size" com vídeo real.
        vf_parts.append(f"subtitles={os.path.basename(ass_path)}")

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        out_path,
    ]
    _run(cmd, cwd=os.path.dirname(ass_path) if ass_path else None)

    if ass_path and os.path.exists(ass_path):
        os.remove(ass_path)

    return out_path


def cut_raw_segment(video_path: str, start: float, end: float, out_path: str):
    """Corta um trecho do vídeo bruto SEM redimensionar, cortar (crop) ou
    legendar — usado pelo editor simples (cortar/reordenar/remover), onde a
    ideia é só recortar pedaços do jeito que o usuário marcou, mantendo o
    vídeo como ele é. Reencoda com parâmetros fixos (mesmo fps/codec de
    sempre) pra garantir que vários pedaços colados depois com
    concat_with_crossfade fiquem compatíveis entre si."""
    video_path = os.path.abspath(video_path)
    out_path = os.path.abspath(out_path)
    duration = max(0.04, end - start)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        out_path,
    ]
    _run(cmd)
    return out_path


def concat_with_crossfade(clip_paths: list[str], out_path: str, crossfade: float = 0.4):
    """Concatena os clipes já cortados. Com 1 clipe só, apenas copia. Com
    mais de um, usa xfade/acrossfade pra uma transição suave entre eles."""
    if len(clip_paths) == 1:
        _run(["ffmpeg", "-y", "-i", clip_paths[0], "-c", "copy", out_path])
        return out_path

    durations = [ffprobe_duration(p) for p in clip_paths]

    # crossfade não pode ser maior que o menor clipe
    safe_crossfade = min(crossfade, min(durations) * 0.4)
    safe_crossfade = max(safe_crossfade, 0.0)

    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    if safe_crossfade <= 0:
        # sem transição: concat demuxer simples (mais robusto)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            for p in clip_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")
            list_path = f.name
        try:
            _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                  "-c:a", "aac", "-b:a", "192k", out_path])
        finally:
            os.remove(list_path)
        return out_path

    filter_parts = []
    v_prev, a_prev = "0:v", "0:a"
    running_offset = durations[0]
    for i in range(1, len(clip_paths)):
        v_out, a_out = f"v{i}", f"a{i}"
        offset = max(0.0, running_offset - safe_crossfade)
        filter_parts.append(f"[{v_prev}][{i}:v]xfade=transition=fade:duration={safe_crossfade:.3f}:offset={offset:.3f}[{v_out}]")
        filter_parts.append(f"[{a_prev}][{i}:a]acrossfade=d={safe_crossfade:.3f}[{a_out}]")
        v_prev, a_prev = v_out, a_out
        running_offset += durations[i] - safe_crossfade

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{v_prev}]", "-map", f"[{a_prev}]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    _run(cmd)
    return out_path


def mix_sfx(video_path: str, sfx_events: list[dict], out_path: str, volume: float = 0.9):
    """Mistura efeitos sonoros pontuais (whoosh, clique etc.) na timeline já
    montada. sfx_events: lista de {"tempo": segundos_no_video_final, "arquivo": caminho}.
    Se a lista vier vazia, só copia o vídeo (nada a fazer)."""
    if not sfx_events:
        _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", out_path])
        return out_path

    inputs = ["-i", video_path]
    for ev in sfx_events:
        inputs += ["-i", ev["arquivo"]]

    delayed_labels = []
    filter_chain = []
    for i, ev in enumerate(sfx_events, start=1):
        delay_ms = max(0, round(ev["tempo"] * 1000))
        label = f"sfx{i}"
        delayed_labels.append(f"[{label}]")
        # adelay precisa do valor pra cada canal (estéreo = dois valores)
        filter_chain.append(f"[{i}:a]volume={volume},adelay={delay_ms}|{delay_ms}[{label}]")

    mix_inputs = "[0:a]" + "".join(delayed_labels)
    n_inputs = 1 + len(sfx_events)
    filter_chain.append(f"{mix_inputs}amix=inputs={n_inputs}:duration=first:dropout_transition=0:normalize=0[aout]")

    filter_complex = ";".join(filter_chain)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    _run(cmd)
    return out_path


def mix_background_music(video_path: str, music_path: str, out_path: str, music_volume: float = 0.18):
    """Adiciona música de fundo com 'duck' automático (a música baixa
    sozinha quando tem fala), via sidechaincompress do ffmpeg."""
    filter_complex = (
        f"[1:a]aloop=loop=-1:size=2e9,volume={music_volume}[music];"
        f"[0:a][music]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=400:makeup=1[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path, "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_path,
    ]
    _run(cmd)
    return out_path

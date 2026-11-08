"""
Exports que fecham a "ponte" com o resto do seu fluxo de trabalho:
- .srt da legenda do vídeo final (caso queira editar/reusar em outro lugar)
- transcript completo do vídeo bruto (texto simples com timestamps)
- .fcpxml com os cortes já marcados, pra abrir DIRETO no Adobe Premiere Pro
  (File > Import) com uma sequência pré-montada a partir do vídeo bruto
  original — sem precisar de nenhum plugin pago.
"""
import os
from urllib.parse import quote


def _xml_attr(value: str) -> str:
    """Escapa um valor pra entrar com segurança dentro de um atributo XML
    (aspas duplas). Sem isso, um nome de arquivo com "&", "<" etc quebra o
    fcpxml e o Premiere não consegue nem abrir o arquivo."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _file_uri(path: str) -> str:
    """Monta uma URI file:// válida pro Premiere achar o vídeo bruto
    original. Dois problemas comuns que isso evita:
    1. No Windows, o caminho tem letra de drive (ex: "C:\\Users\\...") e
       precisa de TRÊS barras depois de "file:" (file:///C:/Users/...), e
       não duas — com só duas, "C:" é lido como um nome de servidor e o
       Premiere não encontra o arquivo.
    2. Espaços, acentos e outros caracteres (comuns em nomes de vídeo em
       português, como "vídeo bruto.mp4") precisam ser "percent-encoded"
       pra uma URI válida — sem isso o link também não resolve."""
    abspath = os.path.abspath(path).replace("\\", "/")
    if not abspath.startswith("/"):
        abspath = "/" + abspath
    # safe="/:" mantém a barra e os dois-pontos da letra de drive (ex:
    # "/C:/Users/...") sem virar "%3A" — o jeito mais comum de escrever
    # isso em URIs file:// no Windows, mais fácil de reconhecer.
    return "file://" + quote(abspath, safe="/:")


def _srt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def compute_final_offsets(selected_segments: list[dict], crossfade: float = 0.0) -> list[float]:
    """Calcula em que instante (no vídeo final já montado) cada segmento
    selecionado começa, considerando a sobreposição das transições."""
    offsets = []
    running = 0.0
    for i, seg in enumerate(selected_segments):
        dur = seg["end"] - seg["start"]
        if i == 0:
            offsets.append(running)
            running += dur
        else:
            running = max(0.0, running - crossfade)
            offsets.append(running)
            running += dur
    return offsets


def write_srt(selected_segments: list[dict], out_path: str, crossfade: float = 0.0):
    offsets = compute_final_offsets(selected_segments, crossfade=crossfade)
    lines = []
    for i, (offset, seg) in enumerate(zip(offsets, selected_segments), start=1):
        dur = seg["end"] - seg["start"]
        lines.append(str(i))
        lines.append(f"{_srt_ts(offset)} --> {_srt_ts(offset + dur)}")
        lines.append(seg["text"].strip())
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def write_transcript(segments: list[dict], out_path: str):
    lines = []
    for seg in segments:
        lines.append(f"[{_srt_ts(seg['start'])} - {_srt_ts(seg['end'])}] {seg['text'].strip()}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def _to_fcp_time(seconds: float, fps: int = 30) -> str:
    frames = max(0, round(seconds * fps))
    return f"{frames}/{fps}s"


def write_fcpxml(source_video_path: str, selected_segments: list[dict], out_path: str,
                  width=1080, height=1920, fps=30):
    """Gera um Final Cut Pro XML com uma sequência cujos clipes apontam pro
    VÍDEO BRUTO ORIGINAL (não pro reel já renderizado), cada um com o
    in/out do trecho selecionado — assim ele chega no Premiere como uma
    timeline editável, com os cortes prontos, pra você refinar manualmente.

    Compatibilidade: testado com a leitura de fcpxml 1.9 pelo Premiere Pro;
    versões diferentes do Premiere podem variar um pouco no import — se
    algo não importar certinho, me avisa que ajusto o formato.
    """
    file_uri = _file_uri(source_video_path)
    total_source_dur = max((s["end"] for s in selected_segments), default=1.0)

    offsets = []
    running = 0.0
    clips_xml = []
    for i, seg in enumerate(selected_segments):
        dur = seg["end"] - seg["start"]
        offset_time = _to_fcp_time(running, fps)
        start_time = _to_fcp_time(seg["start"], fps)
        dur_time = _to_fcp_time(dur, fps)
        clips_xml.append(
            f'            <asset-clip ref="r2" name="destaque-{i+1:02d}" '
            f'offset="{offset_time}" start="{start_time}" duration="{dur_time}" format="r1"/>'
        )
        running += dur

    seq_dur = _to_fcp_time(running, fps)
    asset_dur = _to_fcp_time(total_source_dur, fps)

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
    <resources>
        <format id="r1" name="FFVideoFormat{height}p{fps}" width="{width}" height="{height}"/>
        <asset id="r2" name="{_xml_attr(os.path.basename(source_video_path))}" src="{file_uri}"
               hasVideo="1" hasAudio="1" format="r1" duration="{asset_dur}"/>
    </resources>
    <library>
        <event name="Video Magico">
            <project name="Destaques Automaticos">
                <sequence format="r1" duration="{seq_dur}">
                    <spine>
{os.linesep.join(clips_xml)}
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>
'''
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return out_path

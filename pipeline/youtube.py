"""
Importa vídeo direto de um link do YouTube — baixa com o yt-dlp (open-source,
gratuito, sem chave de API, sem limite de uso) e entrega pro mesmo pipeline
de edição que já existe (modo automático e modo chat).

Baixar vídeo do YouTube deve ser usado só com vídeos seus ou que você tenha
autorização/direito de reaproveitar — os Termos de Uso do YouTube restringem
o download, então o app não faz isso escondido: sempre avisa o que tá
baixando.
"""
import os
import re

import yt_dlp

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)


class YoutubeDownloadError(Exception):
    pass


def is_youtube_url(text: str) -> bool:
    """Reconhece links do youtube.com/watch, youtu.be, /shorts/ e /live/."""
    return bool(YOUTUBE_RE.search((text or "").strip()))


def download_youtube(url: str, out_dir: str, progress_cb=None) -> str:
    """Baixa o vídeo do link pra um .mp4 dentro de out_dir e devolve o
    caminho do arquivo baixado. Usa o próprio FFmpeg (já instalado pelo
    Video Mágico) pra juntar vídeo+áudio quando vêm em streams separados.

    Limita a 1080p pra não baixar arquivo gigante sem necessidade — como o
    corte final é redimensionado de qualquer forma, não compensa baixar em
    resolução maior.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "%(id)s.%(ext)s")

    def hook(d):
        if not progress_cb:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            pct = (100.0 * downloaded / total) if total else 0.0
            progress_cb(min(pct, 99.0), f"Baixando do YouTube... {pct:.0f}%")
        elif d.get("status") == "finished":
            progress_cb(99.0, "Download concluído, preparando o vídeo...")

    ydl_opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        # o FFmpeg (empacotado junto com o Video Mágico) já está no PATH
        # desta sessão — o yt-dlp acha ele sozinho pra juntar vídeo+áudio.
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise YoutubeDownloadError(_friendly_message(str(e))) from e
    except Exception as e:  # qualquer outro erro inesperado do yt-dlp
        raise YoutubeDownloadError(str(e)) from e

    if info is None:
        raise YoutubeDownloadError("Não consegui baixar esse vídeo.")

    # com merge_output_format="mp4", o arquivo final sempre acaba em .mp4,
    # mesmo que o yt-dlp tenha baixado vídeo/áudio em streams separados.
    candidate = os.path.join(out_dir, f"{info['id']}.mp4")
    if os.path.exists(candidate):
        return candidate

    # fallback: formato único já em mp4 (sem precisar mesclar)
    guessed = ydl.prepare_filename(info)
    if os.path.exists(guessed):
        return guessed

    raise YoutubeDownloadError(
        "O download terminou mas não encontrei o arquivo final. Tente de novo."
    )


def _friendly_message(raw: str) -> str:
    """Traduz os erros mais comuns do yt-dlp pra uma mensagem mais clara."""
    low = raw.lower()
    if "private video" in low:
        return "Esse vídeo é privado — não dá pra baixar."
    if "video unavailable" in low:
        return "Esse vídeo não está disponível (pode ter sido removido ou é restrito de região)."
    if "sign in to confirm" in low or "age" in low and "restrict" in low:
        return "Esse vídeo tem restrição de idade/login e não dá pra baixar sem conta."
    if "unable to download webpage" in low or "unable to download api page" in low or "proxy" in low:
        return "Não consegui acessar o YouTube — confira sua conexão com a internet."
    # mantém a mensagem original (encurtada) como último recurso
    return raw.split("\n")[0][:300]

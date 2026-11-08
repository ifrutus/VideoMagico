"""
Gera legendas estilo "TikTok" (poucas palavras por vez, destacadas) em
formato ASS a partir dos timestamps por palavra do Whisper. ASS é queimado
no vídeo pelo próprio FFmpeg (via libass) — nenhuma ferramenta externa.
"""
import os


def _ass_text(text: str) -> str:
    """Limpa um texto antes de colocar numa linha "Dialogue" do .ass: troca
    quebra de linha por espaço (cada Dialogue tem que ser UMA linha física,
    senão corrompe o arquivo) e troca chaves "{" "}" por parênteses (em ASS
    elas são código de formatação — se a fala transcrita tiver uma chave por
    acaso, isso evitava que ela quebrasse a legenda)."""
    return text.replace("\n", " ").replace("\r", " ").replace("{", "(").replace("}", ")")


def _fmt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{fontsize},{cor_legenda},&H000000FF,&H00000000,&H64000000,{bold},0,1,{outline},1,{alinhamento},60,60,{marginv},1
Style: Destaque,{fontname},{fontsize_destaque},{cor_destaque},&H000000FF,&H00000000,&H64000000,1,0,1,{outline_destaque},1,8,60,60,{marginv_topo},1

[Events]
Format: Layer, Start, End, Style, Text
"""

# "Estilo visual da legenda": presets prontos de fonte/cor/posição. Cada
# cor é no formato ASS "&HAABBGGRR" (alfa-azul-verde-vermelho, ao contrário
# do RGB normal). alinhamento: 2 = embaixo/centro, 8 = topo/centro (padrão
# numpad do ASS).
STYLE_PRESETS = {
    "padrao": {
        "fontname": "Arial",
        "cor_legenda": "&H00FFFFFF",   # branco
        "cor_destaque": "&H0000D7FF",  # dourado
        "bold": 1,
        "outline": 4,
        "outline_destaque": 5,
        "fontsize_scale": 0.045,
        "fontsize_destaque_scale": 0.06,
        "alinhamento": 2,
        "marginv_scale": 0.10,
    },
    "impacto": {
        # MrBeast-style: fonte bem grande, amarelo berrante, borda grossa.
        "fontname": "Arial Black",
        "cor_legenda": "&H0000FFFF",   # amarelo
        "cor_destaque": "&H0000D7FF",  # dourado
        "bold": 1,
        "outline": 6,
        "outline_destaque": 6,
        "fontsize_scale": 0.065,
        "fontsize_destaque_scale": 0.075,
        "alinhamento": 2,
        "marginv_scale": 0.12,
    },
    "minimalista": {
        # discreta: fonte menor, branco puro, borda fina, sem negrito.
        "fontname": "Arial",
        "cor_legenda": "&H00FFFFFF",
        "cor_destaque": "&H00FFFFFF",
        "bold": 0,
        "outline": 2,
        "outline_destaque": 2,
        "fontsize_scale": 0.032,
        "fontsize_destaque_scale": 0.038,
        "alinhamento": 2,
        "marginv_scale": 0.08,
    },
    "topo": {
        # igual ao padrão, mas a legenda normal fica no TOPO em vez de
        # embaixo (útil quando a parte de baixo do vídeo tem algo importante
        # — texto de digitação, produto, etc.).
        "fontname": "Arial",
        "cor_legenda": "&H00FFFFFF",
        "cor_destaque": "&H0000D7FF",
        "bold": 1,
        "outline": 4,
        "outline_destaque": 5,
        "fontsize_scale": 0.045,
        "fontsize_destaque_scale": 0.06,
        "alinhamento": 8,
        "marginv_scale": 0.08,
    },
}


def build_ass_for_segment(
    segment: dict,
    out_path: str,
    width=1080,
    height=1920,
    max_words_per_cue=4,
    time_remap=None,
    callouts=None,
    style: str = "padrao",
):
    """Cria um .ass cujos tempos são RELATIVOS ao início do próprio
    segmento (0 = início do clipe cortado), pra poder ser queimado direto
    no clipe individual antes da montagem final.

    time_remap: função opcional tempo_relativo -> tempo_relativo_no_clipe
    (usada quando o segmento tem efeito de câmera lenta/acelerado, que
    estica/encolhe a duração de um trecho).
    callouts: lista opcional de {"inicio", "fim", "texto"} em tempo ABSOLUTO
    do vídeo bruto (mesma referência de segment["start"]) — texto de
    destaque extra, além da legenda normal.
    style: nome de um preset em STYLE_PRESETS ("padrao", "impacto",
    "minimalista", "topo") — controla fonte, cor e posição da legenda.
    """
    preset = STYLE_PRESETS.get(style) or STYLE_PRESETS["padrao"]
    seg_start = segment["start"]
    words = segment.get("words") or []
    fontsize = max(32, int(height * preset["fontsize_scale"]))
    fontsize_destaque = max(40, int(height * preset["fontsize_destaque_scale"]))
    marginv = int(height * preset["marginv_scale"])
    marginv_topo = int(height * 0.08)

    remap = time_remap or (lambda t: t)

    lines = [ASS_HEADER.format(
        width=width, height=height, fontsize=fontsize, marginv=marginv,
        fontsize_destaque=fontsize_destaque, marginv_topo=marginv_topo,
        fontname=preset["fontname"], cor_legenda=preset["cor_legenda"],
        cor_destaque=preset["cor_destaque"], bold=preset["bold"],
        outline=preset["outline"], outline_destaque=preset["outline_destaque"],
        alinhamento=preset["alinhamento"],
    )]

    if not words:
        # sem timestamps por palavra (fallback): mostra a frase inteira
        start = remap(0.0)
        end = remap(segment["end"] - seg_start)
        text = _ass_text(segment["text"].strip().upper())
        lines.append(f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Default,{text}")
    else:
        chunk = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= max_words_per_cue:
                _flush_chunk(lines, chunk, seg_start, remap)
                chunk = []
        if chunk:
            _flush_chunk(lines, chunk, seg_start, remap)

    for c in (callouts or []):
        start = remap(max(0.0, c["inicio"] - seg_start))
        end = remap(max(0.0, c["fim"] - seg_start))
        if end <= start:
            continue
        text = _ass_text(c["texto"].strip().upper())
        if text:
            lines.append(f"Dialogue: 1,{_fmt_ts(start)},{_fmt_ts(end)},Destaque,{text}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return out_path


def _flush_chunk(lines, chunk, seg_start, remap):
    start = remap(max(0.0, chunk[0]["start"] - seg_start))
    end = remap(max(start + 0.05, chunk[-1]["end"] - seg_start))
    text = _ass_text("".join(w["word"] for w in chunk).strip().upper())
    if text:
        lines.append(f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Default,{text}")


def ffmpeg_escape_path(path: str) -> str:
    """Escapa um caminho de arquivo pra usar dentro de um filtro do ffmpeg
    (ex: subtitles=caminho).

    No Windows, caminho vem tipo "C:\\Users\\...\\clip.ass". Tentar escapar
    TODAS as barras invertidas (dobrando cada uma) quebra o parser do
    filtro "subtitles" em vários builds do ffmpeg (o libass acaba lendo o
    caminho errado e reclama de uma opção interna chamada "original_size").
    O jeito confiável e bem conhecido é trocar as barras invertidas por
    barras normais (o Windows aceita os dois formatos) e só escapar os
    dois-pontos (o da letra do drive, tipo "C:")."""
    abspath = os.path.abspath(path)
    normalized = abspath.replace("\\", "/")
    return normalized.replace(":", "\\:")

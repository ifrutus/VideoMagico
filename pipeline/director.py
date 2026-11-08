"""
"Diretor de edição" por chat: conversa em português normal vira um plano de
edição estruturado. Usa um LLM rodando LOCAL via Ollama (https://ollama.com,
gratuito, sem API paga, sem créditos) — nada disso sai do seu computador.

Se o Ollama não estiver rodando, as funções aqui levantam um erro claro
explicando o que falta (não trava o resto do app).
"""
import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"

PLAN_SCHEMA_EXAMPLE = {
    "duracao_alvo_segundos": 45,
    "segmentos": [{"start": 12.3, "end": 18.9, "motivo": "fala da colheita"}],
    "efeitos": [
        {"tipo": "zoom", "inicio": 14.0, "fim": 14.8, "intensidade": 1.15},
        {"tipo": "camera_lenta", "inicio": 20.0, "fim": 22.0, "velocidade": 0.5},
        {"tipo": "som", "tempo": 15.0, "arquivo": "whoosh.mp3"},
        {"tipo": "texto_destaque", "inicio": 14.0, "fim": 16.0, "texto": "OLHA SÓ"},
        {"tipo": "motion_graphic", "tempo": 12.3, "arquivo": "titulo_abertura.webm"},
    ],
    "resposta_para_usuario": "Beleza! Cortei focando na colheita e coloquei um zoom quando você fala 'incrível'.",
}


class OllamaError(RuntimeError):
    pass


def _transcript_as_text(transcript: dict) -> str:
    lines = []
    for seg in transcript["segments"]:
        lines.append(f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text'].strip()}")
    return "\n".join(lines)


def build_system_prompt(
    transcript: dict,
    video_duration: float,
    sfx_files: list[str],
    motion_graphics_files: list[str] | None = None,
) -> str:
    sfx_list = ", ".join(sfx_files) if sfx_files else "(nenhum arquivo de som disponível ainda)"
    mg_list = ", ".join(motion_graphics_files) if motion_graphics_files else "(nenhum motion graphic disponível ainda)"
    return f"""Você é um editor de vídeo que conversa em português do Brasil e devolve
APENAS um JSON válido (sem texto fora do JSON) descrevendo um plano de edição.

O vídeo bruto dura {video_duration:.1f} segundos. Este é o transcript completo,
com timestamps em segundos desde o início do vídeo:

{_transcript_as_text(transcript)}

Sons disponíveis pra usar em efeitos do tipo "som" (use exatamente esses nomes
de arquivo, ou não inclua efeito de som nenhum): {sfx_list}

Motion graphics (títulos animados, lower thirds, transições gráficas)
disponíveis pra usar em efeitos do tipo "motion_graphic" (use exatamente esses
nomes de arquivo, ou não inclua esse efeito): {mg_list}

Responda SEMPRE com um JSON no formato abaixo (pode omitir "efeitos" se não
fizer sentido nenhum efeito ainda). Todo timestamp é em segundos, relativo ao
vídeo bruto original (não ao vídeo cortado). Cada efeito precisa cair DENTRO
de algum item de "segmentos". "duracao_alvo_segundos" é a duração aproximada
que o vídeo final deve ter.

{json.dumps(PLAN_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

Regras importantes:
- "segmentos" são os melhores trechos do vídeo bruto pra virar o corte final,
  na ordem que devem aparecer.
- Tipos de efeito válidos: "zoom", "camera_lenta", "som", "texto_destaque",
  "motion_graphic".
- Em "camera_lenta", velocidade menor que 1 é câmera lenta (0.5 = metade da
  velocidade), maior que 1 é acelerado.
- Em "motion_graphic", "tempo" é o instante em que o motion graphic COMEÇA a
  aparecer (ele dura o tempo próprio do arquivo, normalmente poucos segundos)
  — só use se a pessoa pedir um título/abertura/transição gráfica.
- Sempre preencha "resposta_para_usuario" com uma frase curta e natural
  explicando o que você fez, como se estivesse conversando com a pessoa.
- Quando o usuário pedir um ajuste (ex: "tira o efeito de zoom", "corta mais
  curto"), atualize o plano anterior em vez de recomeçar do zero, mantendo o
  que não foi pedido pra mudar.
"""


def call_ollama(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 120.0,
) -> str:
    """Manda a conversa (lista de {"role": ..., "content": ...}) pro Ollama e
    devolve o texto da resposta (deve ser um JSON, por causa do format=json)."""
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.4},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise OllamaError(
            "Não consegui falar com o Ollama em "
            f"{base_url}. Ele precisa estar instalado e rodando no seu "
            "computador (é grátis — veja o README). Detalhe técnico: " + str(e)
        ) from e

    message = body.get("message") or {}
    content = message.get("content")
    if not content:
        raise OllamaError(f"O Ollama respondeu num formato inesperado: {body}")
    return content


def parse_and_validate_plan(
    raw_response: str,
    video_duration: float,
    available_sfx: list[str],
    default_duration: float = 45.0,
    available_motion_graphics: list[str] | None = None,
) -> dict:
    """Valida a saída do LLM de forma defensiva: mesmo com format=json, os
    VALORES podem vir bobos (timestamp fora do vídeo, arquivo de som que não
    existe, efeito fora de qualquer segmento) — aqui a gente limpa isso."""
    try:
        raw = json.loads(raw_response)
    except json.JSONDecodeError as e:
        raise OllamaError(f"O Ollama não devolveu um JSON válido: {e}\nResposta: {raw_response[:500]}") from e

    def clamp(value, lo, hi):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return lo
        return max(lo, min(hi, value))

    segments = []
    for seg in raw.get("segmentos", []) or []:
        try:
            start = clamp(seg["start"], 0, video_duration)
            end = clamp(seg["end"], 0, video_duration)
        except (KeyError, TypeError):
            continue
        if end - start < 0.3:
            continue
        segments.append({"start": start, "end": end, "motivo": str(seg.get("motivo", ""))[:200]})

    segments.sort(key=lambda s: s["start"])

    def in_any_segment(t_start, t_end=None):
        t_end = t_end if t_end is not None else t_start
        return any(s["start"] <= t_start and t_end <= s["end"] for s in segments)

    effects = []
    for eff in raw.get("efeitos", []) or []:
        tipo = eff.get("tipo")
        try:
            if tipo == "zoom":
                inicio = clamp(eff["inicio"], 0, video_duration)
                fim = clamp(eff["fim"], 0, video_duration)
                if fim <= inicio or not in_any_segment(inicio, fim):
                    continue
                intensidade = clamp(eff.get("intensidade", 1.15), 1.02, 1.5)
                effects.append({"tipo": "zoom", "inicio": inicio, "fim": fim, "intensidade": intensidade})

            elif tipo == "camera_lenta":
                inicio = clamp(eff["inicio"], 0, video_duration)
                fim = clamp(eff["fim"], 0, video_duration)
                if fim <= inicio or not in_any_segment(inicio, fim):
                    continue
                velocidade = clamp(eff.get("velocidade", 0.5), 0.25, 3.0)
                effects.append({"tipo": "camera_lenta", "inicio": inicio, "fim": fim, "velocidade": velocidade})

            elif tipo == "som":
                tempo = clamp(eff["tempo"], 0, video_duration)
                arquivo = eff.get("arquivo")
                if arquivo not in available_sfx or not in_any_segment(tempo):
                    continue
                effects.append({"tipo": "som", "tempo": tempo, "arquivo": arquivo})

            elif tipo == "texto_destaque":
                inicio = clamp(eff["inicio"], 0, video_duration)
                fim = clamp(eff["fim"], 0, video_duration)
                texto = str(eff.get("texto", "")).strip()[:60]
                if fim <= inicio or not texto or not in_any_segment(inicio, fim):
                    continue
                effects.append({"tipo": "texto_destaque", "inicio": inicio, "fim": fim, "texto": texto})

            elif tipo == "motion_graphic":
                tempo = clamp(eff["tempo"], 0, video_duration)
                arquivo = eff.get("arquivo")
                if arquivo not in (available_motion_graphics or []) or not in_any_segment(tempo):
                    continue
                effects.append({"tipo": "motion_graphic", "tempo": tempo, "arquivo": arquivo})
        except (KeyError, TypeError):
            continue

    duracao_alvo = clamp(raw.get("duracao_alvo_segundos", default_duration), 5, 600)
    resposta = str(raw.get("resposta_para_usuario") or "Prontinho, apliquei as mudanças.")[:800]

    return {
        "duracao_alvo_segundos": duracao_alvo,
        "segmentos": segments,
        "efeitos": effects,
        "resposta_para_usuario": resposta,
    }

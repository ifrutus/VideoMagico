"""
Heurística 100% local (sem LLM pago) pra decidir quais trechos do vídeo bruto
viram "destaques": combina energia de áudio (fala animada/alto volume),
palavras-chave de empolgação e descarte de trechos com pouca fala (silêncio
morto). É a "mágica" v1 — dá pra trocar por um ranking mais esperto (ex: LLM
local via Ollama) depois, sem mudar o resto do pipeline.
"""
import re

import numpy as np
import librosa

DEFAULT_KEYWORDS = [
    "incrível", "incrivel", "uau", "nossa", "olha isso", "olha só", "olha so",
    "surreal", "impressionante", "demais", "espetacular", "sensacional",
    "gente", "não acredito", "nao acredito", "adorei", "perfeito",
]

# Hesitação/respiro ("eeeeeh", "hmmm", "ããã"...) que o Whisper às vezes
# transcreve como se fosse uma palavra. Dois sinais, pra não arriscar cortar
# uma palavra de verdade por engano:
# 1) a mesma letra repetida 3+ vezes em seguida — o jeito clássico de
#    escrever um som "esticado" (eeeeeh, aaah, hmmm);
# 2) uma lista pequena e explícita de interjeições sem conteúdo (comparação
#    exata, não "contém", pra não pegar palavra de verdade por acidente).
_ELONGATION_RE = re.compile(r"(.)\1{2,}", re.IGNORECASE)
_EXPLICIT_FILLERS = {"ahn", "hum", "hmm", "uhum", "uhn", "err", "ahm", "hm"}


def _is_filler_word(word: str) -> bool:
    """Decide se uma "palavra" transcrita é só hesitação/respiro, sem
    conteúdo de fala de verdade."""
    cleaned = re.sub(r"[^\wà-úÀ-Ú]", "", word or "").lower()
    if not cleaned:
        return True
    if _ELONGATION_RE.search(cleaned):
        return True
    return cleaned in _EXPLICIT_FILLERS


def trim_filler_edges(segment: dict) -> dict:
    """Encurta o início/fim de um segmento pra tirar hesitação colada na
    BORDA do trecho (ex: segmento começa com "eeeeeh, então..." ou termina
    com "...e tal, ahn") — sem isso, mesmo selecionando o trecho certo, o
    corte "respirava" antes/depois da fala de verdade.

    Não remove hesitação que esteja no MEIO do trecho (entre duas falas de
    verdade) — isso precisaria dividir o clipe em pedaços, uma melhoria
    separada. Se o trecho inteiro for só hesitação, devolve sem mudar (quem
    chama já descarta isso pelo contador de palavras reais)."""
    words = segment.get("words") or []
    if not words:
        return segment

    first_i = 0
    while first_i < len(words) and _is_filler_word(words[first_i]["word"]):
        first_i += 1
    last_i = len(words) - 1
    while last_i >= 0 and _is_filler_word(words[last_i]["word"]):
        last_i -= 1

    if first_i > last_i:
        return segment  # trecho é só hesitação, nada de real pra aproveitar

    kept_words = words[first_i : last_i + 1]
    trimmed = dict(segment)
    trimmed["start"] = max(segment["start"], kept_words[0]["start"] - 0.1)
    trimmed["end"] = min(segment["end"], kept_words[-1]["end"] + 0.1)
    trimmed["words"] = kept_words
    trimmed["text"] = "".join(w["word"] for w in kept_words).strip() or segment["text"]
    return trimmed


def compute_energy_curve(audio_path: str, hop_length: int = 512):
    """Curva de energia (RMS) do áudio ao longo do tempo."""
    y, sr = librosa.load(audio_path, sr=None, mono=True)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    return times, rms


def _segment_energy(times, rms, start: float, end: float) -> float:
    mask = (times >= start) & (times <= end)
    if not mask.any():
        return 0.0
    return float(np.mean(rms[mask]))


def score_segments(
    whisper_segments: list[dict],
    times: np.ndarray,
    rms: np.ndarray,
    keywords: list[str] | None = None,
    min_words: int = 3,
) -> list[dict]:
    """Pontua cada segmento transcrito (0 a 1) e descarta trechos curtos
    demais pra serem um "momento" (normalmente silêncio/hesitação).

    Antes de pontuar, encurta a hesitação colada na borda de cada segmento
    (ver trim_filler_edges) — assim o início/fim já usado no resto do
    pipeline (pontuação por energia, corte do clipe, duração) é o trecho
    "limpo", sem o "eeeeeh" antes ou depois da fala de verdade."""
    keywords = keywords or DEFAULT_KEYWORDS
    trimmed_segments = [trim_filler_edges(s) for s in whisper_segments]
    energies = [_segment_energy(times, rms, s["start"], s["end"]) for s in trimmed_segments]
    max_energy = max(energies) if energies else 1.0
    max_energy = max_energy or 1.0

    scored = []
    for seg, energy in zip(trimmed_segments, energies):
        # conta só palavras com conteúdo de verdade (sem hesitação) — um
        # segmento tipo "eeeh aqui eeeh incrível eeeh" não deve passar pelo
        # filtro de palavras mínimas só por ter 5 "palavras" no total.
        real_words = [w for w in (seg.get("words") or []) if not _is_filler_word(w["word"])]
        word_count = len(real_words) if seg.get("words") else len(seg["text"].split())
        if word_count < min_words:
            continue

        text_lower = seg["text"].lower()
        keyword_hits = sum(1 for kw in keywords if kw in text_lower)

        norm_energy = energy / max_energy
        score = 0.7 * norm_energy + 0.3 * min(keyword_hits, 2) / 2

        scored.append({**seg, "score": score, "energy": norm_energy, "keyword_hits": keyword_hits})

    return scored


_RITMO_BOUNDS = {
    # (duração mínima, duração máxima) de CADA trecho escolhido — None = sem
    # limite. "rápido" favorece trechos curtos e mais cortes (edição mais
    # agitada); "lento" descarta trechos curtos demais pra respirar mais
    # entre os cortes (edição mais contemplativa).
    "rapido": (None, 4.0),
    "equilibrado": (None, None),
    "lento": (3.5, None),
}


def ritmo_to_duration_bounds(ritmo: str) -> tuple[float | None, float | None]:
    """Traduz a preferência de estilo "ritmo_cortes" (config.json / web) nos
    limites de duração de trecho usados por select_highlights."""
    return _RITMO_BOUNDS.get((ritmo or "").strip().lower(), _RITMO_BOUNDS["equilibrado"])


def select_highlights(
    scored_segments: list[dict],
    target_duration: float = 60.0,
    min_segment_duration: float | None = None,
    max_segment_duration: float | None = None,
) -> list[dict]:
    """Escolhe os trechos com maior pontuação até bater a duração alvo, e
    devolve na ordem cronológica original (fica mais natural de assistir).

    min_segment_duration/max_segment_duration filtram quais trechos entram
    na disputa ANTES de escolher — é o que dá o "ritmo" da edição (ver
    ritmo_to_duration_bounds)."""
    candidates = scored_segments
    if min_segment_duration is not None:
        candidates = [s for s in candidates if (s["end"] - s["start"]) >= min_segment_duration]
    if max_segment_duration is not None:
        candidates = [s for s in candidates if (s["end"] - s["start"]) <= max_segment_duration]
    if not candidates:
        # limite deixou a lista vazia (ex: vídeo só tem trechos longos e o
        # ritmo pedido era "rápido") — melhor usar os originais do que não
        # gerar nada.
        candidates = scored_segments

    ranked = sorted(candidates, key=lambda s: s["score"], reverse=True)

    selected = []
    total = 0.0
    for seg in ranked:
        dur = seg["end"] - seg["start"]
        if selected and total + dur > target_duration:
            continue
        selected.append(seg)
        total += dur
        if total >= target_duration:
            break

    selected.sort(key=lambda s: s["start"])
    return selected

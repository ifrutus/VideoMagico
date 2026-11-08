"""
Transcrição 100% local usando faster-whisper (Whisper open-source rodando via
CTranslate2). Sem API, sem internet depois do primeiro download do modelo,
sem custo por minuto de áudio.
"""
from faster_whisper import WhisperModel

_MODEL_CACHE = {}


def _get_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    key = (model_size, device, compute_type)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _MODEL_CACHE[key]


def transcribe(
    audio_path: str,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict:
    """
    Transcreve um arquivo de áudio e devolve segmentos com timestamps por
    palavra (necessário pra gerar legenda estilo "palavra por palavra").

    model_size: tiny, base, small, medium, large-v3 (quanto maior, melhor a
    qualidade e mais lento/pesado — todos gratuitos, baixados uma vez do
    Hugging Face na primeira execução).
    """
    model = _get_model(model_size, device, compute_type)
    segments_iter, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language=language,
        vad_filter=True,  # ignora trechos de silêncio automaticamente
    )

    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({"start": w.start, "end": w.end, "word": w.word})
        segments.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "words": words,
            }
        )

    return {"language": info.language, "segments": segments}

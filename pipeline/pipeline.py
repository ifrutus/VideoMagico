"""
Orquestra o pipeline completo: bruto.mp4 entra, "destaques editados" saem.
Cada etapa usa só ferramentas open-source/gratuitas (ver README.md).
"""
import os
import shutil

from . import transcribe as T
from . import scenes as SC
from . import highlights as H
from . import render as R
from . import exports as E
from . import motion_graphics as MG


def extract_audio(video_path: str, out_wav: str):
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", out_wav]
    # Usa o mesmo _run do render.py (em vez de subprocess.run direto) pra
    # ganhar duas coisas de graça: uma mensagem de erro com o stderr real do
    # ffmpeg (bem mais útil que o "CalledProcessError" genérico de antes) e
    # o log automático em ultimo_erro.log, dá pra achar o motivo mesmo sem
    # ver a janela do terminal.
    R._run(cmd)


def _assemble_reel(
    input_path: str,
    selected: list[dict],
    out_dir: str,
    width: int,
    height: int,
    crossfade: float,
    music_path: str | None,
    report,
    pct_start: int = 65,
    pct_end: int = 94,
    motion_graphic_path: str | None = None,
    estilo_legenda: str = "padrao",
) -> dict:
    """Pedaço reaproveitável que faz UM reel a partir de uma lista de
    trechos já escolhidos: corta cada trecho com legenda, concatena com
    transição, mistura música (se tiver) e gera srt/transcript/fcpxml pra
    ESSE reel. Usado tanto pelo modo "um reel só" (run_pipeline) quanto pelo
    modo "N cortes numa pasta" (run_pipeline_multi) — cada corte é só uma
    chamada a esta função, com um out_dir diferente."""
    os.makedirs(out_dir, exist_ok=True)
    span = max(1, pct_end - pct_start)

    report(pct_start, f"Cortando {len(selected)} trecho(s) com legenda...")
    clip_paths = []
    for i, seg in enumerate(selected):
        clip_out = os.path.join(out_dir, f"_tmp_clip_{i:03d}.mp4")
        R.cut_segment(input_path, seg, clip_out, width=width, height=height, estilo_legenda=estilo_legenda)
        clip_paths.append(clip_out)

    report(pct_start + int(span * 0.5), "Montando com transições...")
    assembled = os.path.join(out_dir, "_tmp_assembled.mp4")
    R.concat_with_crossfade(clip_paths, assembled, crossfade=crossfade)

    with_music = os.path.join(out_dir, "_tmp_with_music.mp4")
    if music_path and os.path.exists(music_path):
        report(pct_start + int(span * 0.70), "Adicionando trilha sonora...")
        R.mix_background_music(assembled, music_path, with_music)
    else:
        shutil.copy(assembled, with_music)

    final_path = os.path.join(out_dir, "corte.mp4")
    if motion_graphic_path and os.path.exists(motion_graphic_path):
        report(pct_start + int(span * 0.85), "Aplicando motion graphics...")
        MG.overlay_motion_graphic(with_music, motion_graphic_path, final_path, start=0.0)
    else:
        shutil.copy(with_music, final_path)

    srt_path = E.write_srt(selected, os.path.join(out_dir, "legenda.srt"), crossfade=crossfade)
    fcpxml_path = E.write_fcpxml(
        input_path, selected, os.path.join(out_dir, "corte_premiere.fcpxml"),
        width=width, height=height,
    )

    for p in clip_paths + [assembled, with_music]:
        try:
            os.remove(p)
        except OSError:
            pass

    return {
        "final_video": final_path,
        "srt": srt_path,
        "fcpxml": fcpxml_path,
        "selected_segments": selected,
        "num_clips": len(selected),
        "total_duration": sum(s["end"] - s["start"] for s in selected),
    }


def run_pipeline(
    input_path: str,
    work_dir: str,
    target_duration: float = 60.0,
    aspect: str = "9:16",
    crossfade: float = 0.4,
    music_path: str | None = None,
    model_size: str = "base",
    language: str | None = None,
    motion_graphic_path: str | None = None,
    ritmo_cortes: str = "equilibrado",
    estilo_legenda: str = "padrao",
    progress_cb=None,
) -> dict:
    """Gera UM reel só, com os melhores momentos até bater target_duration.
    Pra gerar VÁRIOS cortes separados de uma vez (modo "10 cortes numa
    pasta"), veja run_pipeline_multi."""
    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    os.makedirs(work_dir, exist_ok=True)
    width, height = R.ASPECTS.get(aspect, R.ASPECTS["9:16"])

    report(5, "Extraindo áudio...")
    audio_path = os.path.join(work_dir, "audio.wav")
    extract_audio(input_path, audio_path)

    report(15, "Transcrevendo com Whisper (local, grátis)...")
    transcript = T.transcribe(audio_path, model_size=model_size, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Não consegui detectar fala nesse vídeo. Confira se o áudio está "
            "presente e audível no arquivo enviado."
        )

    report(35, "Detectando cortes de cena...")
    try:
        SC.detect_scenes(input_path)
    except Exception:
        pass  # cena é só um sinal extra; se falhar, seguimos só com áudio

    report(50, "Analisando energia de áudio...")
    times, rms = H.compute_energy_curve(audio_path)

    report(58, "Selecionando os melhores momentos...")
    scored = H.score_segments(transcript["segments"], times, rms)
    min_dur, max_dur = H.ritmo_to_duration_bounds(ritmo_cortes)
    selected = H.select_highlights(scored, target_duration=target_duration, min_segment_duration=min_dur, max_segment_duration=max_dur)
    if not selected:
        raise RuntimeError(
            "Não encontrei trechos com fala suficiente pra gerar destaques. "
            "Tente um vídeo com mais fala ou reduza a duração alvo."
        )

    reel = _assemble_reel(
        input_path, selected, work_dir, width, height, crossfade, music_path,
        report, pct_start=65, pct_end=94, motion_graphic_path=motion_graphic_path,
        estilo_legenda=estilo_legenda,
    )
    transcript_path = E.write_transcript(transcript["segments"], os.path.join(work_dir, "transcript_completo.txt"))

    # os nomes de arquivo do modo "um reel só" são os antigos (final.mp4,
    # destaques_premiere.fcpxml), mantidos pra não quebrar quem já baixa por
    # esse caminho (app.py).
    final_path = os.path.join(work_dir, "final.mp4")
    shutil.move(reel["final_video"], final_path)
    fcpxml_path = os.path.join(work_dir, "destaques_premiere.fcpxml")
    shutil.move(reel["fcpxml"], fcpxml_path)

    try:
        os.remove(audio_path)
    except OSError:
        pass

    report(100, "Concluído!")
    return {
        "final_video": final_path,
        "srt": reel["srt"],
        "transcript": transcript_path,
        "fcpxml": fcpxml_path,
        "selected_segments": selected,
        "language": transcript["language"],
        "num_clips": reel["num_clips"],
        "total_duration": reel["total_duration"],
    }


def run_pipeline_multi(
    input_path: str,
    work_dir: str,
    num_cortes: int = 10,
    duracao_maxima_por_corte: float = 60.0,
    aspect: str = "9:16",
    crossfade: float = 0.4,
    music_path: str | None = None,
    model_size: str = "base",
    language: str | None = None,
    motion_graphic_path: str | None = None,
    ritmo_cortes: str = "equilibrado",
    estilo_legenda: str = "padrao",
    progress_cb=None,
) -> dict:
    """Gera até `num_cortes` cortes SEPARADOS (cada um com até
    `duracao_maxima_por_corte` segundos), um por subpasta
    (corte_01/, corte_02/, ...) dentro de work_dir — como os concorrentes
    (Opus Clip, Klap): em vez de UM reel juntando os melhores momentos,
    cada "melhor momento" (ou grupo de momentos próximos) vira o SEU
    próprio vídeo pronto, já com legenda e sem os respiros/hesitações nas
    bordas.

    A transcrição e a detecção de destaques são feitas uma única vez; cada
    corte consome um grupo de trechos do "pool" de destaques (do mais
    pontuado pro menos) sem repetir trecho entre cortes."""
    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    os.makedirs(work_dir, exist_ok=True)
    width, height = R.ASPECTS.get(aspect, R.ASPECTS["9:16"])

    report(5, "Extraindo áudio...")
    audio_path = os.path.join(work_dir, "audio.wav")
    extract_audio(input_path, audio_path)

    report(15, "Transcrevendo com Whisper (local, grátis)...")
    transcript = T.transcribe(audio_path, model_size=model_size, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Não consegui detectar fala nesse vídeo. Confira se o áudio está "
            "presente e audível no arquivo enviado."
        )

    report(30, "Detectando cortes de cena...")
    try:
        SC.detect_scenes(input_path)
    except Exception:
        pass

    report(40, "Analisando energia de áudio...")
    times, rms = H.compute_energy_curve(audio_path)

    report(48, "Selecionando os melhores momentos...")
    pool = H.score_segments(transcript["segments"], times, rms)
    if not pool:
        raise RuntimeError(
            "Não encontrei trechos com fala suficiente pra gerar destaques. "
            "Tente um vídeo com mais fala."
        )

    cortes = []
    pct_span = 48.0
    min_dur, max_dur = H.ritmo_to_duration_bounds(ritmo_cortes)
    for i in range(max(1, num_cortes)):
        if not pool:
            break
        selected = H.select_highlights(pool, target_duration=duracao_maxima_por_corte, min_segment_duration=min_dur, max_segment_duration=max_dur)
        if not selected:
            break

        usados = {(s["start"], s["end"]) for s in selected}
        pool = [s for s in pool if (s["start"], s["end"]) not in usados]

        pct_now = 48 + int(pct_span * (i / max(1, num_cortes)))
        report(pct_now, f"Gerando corte {i + 1} de até {num_cortes}...")

        corte_dir = os.path.join(work_dir, f"corte_{i + 1:02d}")
        reel = _assemble_reel(
            input_path, selected, corte_dir, width, height, crossfade, music_path,
            report, pct_start=pct_now, pct_end=min(96, pct_now + int(pct_span / max(1, num_cortes))),
            motion_graphic_path=motion_graphic_path, estilo_legenda=estilo_legenda,
        )
        cortes.append({
            "pasta": corte_dir,
            "final_video": reel["final_video"],
            "srt": reel["srt"],
            "fcpxml": reel["fcpxml"],
            "total_duration": reel["total_duration"],
            "num_trechos": reel["num_clips"],
        })

    if not cortes:
        raise RuntimeError(
            "Não encontrei trechos com fala suficiente pra gerar nenhum corte. "
            "Tente um vídeo com mais fala."
        )

    report(97, "Gerando transcript completo...")
    transcript_path = E.write_transcript(transcript["segments"], os.path.join(work_dir, "transcript_completo.txt"))

    try:
        os.remove(audio_path)
    except OSError:
        pass

    report(100, "Concluído!")
    return {
        "work_dir": work_dir,
        "transcript": transcript_path,
        "language": transcript["language"],
        "cortes": cortes,
        "num_cortes_gerados": len(cortes),
    }


def _flatten_words(transcript_segments: list[dict]) -> list[dict]:
    words = []
    for seg in transcript_segments:
        words.extend(seg.get("words") or [])
    words.sort(key=lambda w: w["start"])
    return words


def _words_in_range(all_words: list[dict], start: float, end: float) -> list[dict]:
    return [w for w in all_words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]


def _text_in_range(transcript_segments: list[dict], start: float, end: float) -> str:
    parts = [
        seg["text"].strip()
        for seg in transcript_segments
        if seg["end"] >= start and seg["start"] <= end
    ]
    return " ".join(parts)


def run_edit_plan(
    input_path: str,
    work_dir: str,
    transcript: dict,
    plan: dict,
    aspect: str = "9:16",
    crossfade: float = 0.4,
    music_path: str | None = None,
    sfx_dir: str | None = None,
    motion_graphics_dir: str | None = None,
    estilo_legenda: str = "padrao",
    progress_cb=None,
) -> dict:
    """Igual ao run_pipeline, mas os trechos e efeitos vêm de um PLANO (do
    diretor de IA por chat, ver pipeline/director.py) em vez da heurística
    automática. A transcrição já vem pronta (feita uma vez só, no início da
    conversa) — aqui só corta, aplica os efeitos e monta."""
    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    os.makedirs(work_dir, exist_ok=True)
    width, height = R.ASPECTS.get(aspect, R.ASPECTS["9:16"])

    segments_plan = plan.get("segmentos") or []
    if not segments_plan:
        raise RuntimeError("O plano de edição não tem nenhum trecho selecionado.")

    all_words = _flatten_words(transcript["segments"])
    effects_all = plan.get("efeitos") or []

    selected = []
    for sp in segments_plan:
        s, e = sp["start"], sp["end"]
        selected.append({
            "start": s,
            "end": e,
            "text": _text_in_range(transcript["segments"], s, e) or sp.get("motivo", ""),
            "words": _words_in_range(all_words, s, e),
        })

    report(15, f"Cortando {len(selected)} clipe(s) com os efeitos pedidos...")
    clip_paths = []
    for i, seg in enumerate(selected):
        seg_effects = []
        seg_callouts = []
        for eff in effects_all:
            if eff["tipo"] in ("zoom", "camera_lenta"):
                if seg["start"] <= eff["inicio"] and eff["fim"] <= seg["end"]:
                    seg_effects.append({
                        **eff,
                        "inicio": eff["inicio"] - seg["start"],
                        "fim": eff["fim"] - seg["start"],
                    })
            elif eff["tipo"] == "texto_destaque":
                if seg["start"] <= eff["inicio"] and eff["fim"] <= seg["end"]:
                    seg_callouts.append(eff)

        clip_out = os.path.join(work_dir, f"clip_{i:03d}.mp4")
        R.cut_segment(
            input_path, seg, clip_out, width=width, height=height,
            effects=seg_effects, callouts=seg_callouts, estilo_legenda=estilo_legenda,
        )
        clip_paths.append(clip_out)

    report(60, "Montando com transições...")
    assembled = os.path.join(work_dir, "assembled.mp4")
    R.concat_with_crossfade(clip_paths, assembled, crossfade=crossfade)

    with_music = os.path.join(work_dir, "with_music.mp4")
    if music_path and os.path.exists(music_path):
        report(75, "Adicionando trilha sonora...")
        R.mix_background_music(assembled, music_path, with_music)
    else:
        shutil.copy(assembled, with_music)

    offsets = E.compute_final_offsets(selected, crossfade=crossfade)
    sfx_events = []
    if sfx_dir:
        for offset, seg in zip(offsets, selected):
            for eff in effects_all:
                if eff["tipo"] == "som" and seg["start"] <= eff["tempo"] <= seg["end"]:
                    sfx_path = os.path.join(sfx_dir, eff["arquivo"])
                    if os.path.exists(sfx_path):
                        sfx_events.append({
                            "tempo": offset + (eff["tempo"] - seg["start"]),
                            "arquivo": sfx_path,
                        })

    motion_graphic_events = []
    if motion_graphics_dir:
        for offset, seg in zip(offsets, selected):
            for eff in effects_all:
                if eff["tipo"] == "motion_graphic" and seg["start"] <= eff["tempo"] <= seg["end"]:
                    mg_path = os.path.join(motion_graphics_dir, eff["arquivo"])
                    if os.path.exists(mg_path):
                        motion_graphic_events.append({
                            "tempo": offset + (eff["tempo"] - seg["start"]),
                            "arquivo": mg_path,
                        })

    after_sfx = os.path.join(work_dir, "after_sfx.mp4")
    if sfx_events:
        report(85, "Adicionando efeitos sonoros...")
        R.mix_sfx(with_music, sfx_events, after_sfx)
    else:
        shutil.copy(with_music, after_sfx)

    final_path = os.path.join(work_dir, "final.mp4")
    if motion_graphic_events:
        report(90, "Aplicando motion graphics...")
        current = after_sfx
        tmp_mg_paths = []
        for i, ev in enumerate(motion_graphic_events):
            is_last = i == len(motion_graphic_events) - 1
            next_path = final_path if is_last else os.path.join(work_dir, f"_tmp_mg_{i:03d}.mp4")
            MG.overlay_motion_graphic(current, ev["arquivo"], next_path, start=ev["tempo"])
            if current != after_sfx:
                tmp_mg_paths.append(current)
            current = next_path
        for p in tmp_mg_paths:
            try:
                os.remove(p)
            except OSError:
                pass
    else:
        shutil.copy(after_sfx, final_path)

    report(94, "Gerando legenda, transcript e XML pro Premiere...")
    srt_path = E.write_srt(selected, os.path.join(work_dir, "legenda.srt"), crossfade=crossfade)
    transcript_path = E.write_transcript(transcript["segments"], os.path.join(work_dir, "transcript_completo.txt"))
    fcpxml_path = E.write_fcpxml(
        input_path, selected, os.path.join(work_dir, "destaques_premiere.fcpxml"),
        width=width, height=height,
    )

    for p in clip_paths + [assembled, with_music, after_sfx]:
        try:
            os.remove(p)
        except OSError:
            pass

    report(100, "Concluído!")
    return {
        "final_video": final_path,
        "srt": srt_path,
        "transcript": transcript_path,
        "fcpxml": fcpxml_path,
        "selected_segments": selected,
        "num_clips": len(selected),
        "total_duration": sum(s["end"] - s["start"] for s in selected),
    }

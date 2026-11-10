"""
App web local — roda inteiramente no seu computador (python app.py),
sem hospedagem paga, sem conta, sem créditos. Abra http://localhost:8000
depois de rodar.
"""
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import tempfile
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pipeline.pipeline import run_pipeline, run_pipeline_multi, run_edit_plan, extract_audio
from pipeline import director as D
from pipeline import transcribe as T
from pipeline import render as R
from pipeline import youtube as YT
from pipeline import editor as ED
from pipeline import captions as C
from pipeline.notify import _open_folder
from watcher import load_config, watch_loop, ENTRADA, SAIDA

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
MUSIC_DIR = os.path.join(BASE_DIR, "music")
SFX_DIR = os.path.join(BASE_DIR, "sfx")
MOTION_GRAPHICS_DIR = os.path.join(BASE_DIR, "motion_graphics")
EDITOR_DIR = os.path.join(BASE_DIR, "editor_jobs")

for d in (UPLOAD_DIR, JOBS_DIR, MUSIC_DIR, SFX_DIR, MOTION_GRAPHICS_DIR, EDITOR_DIR):
    os.makedirs(d, exist_ok=True)

_MOTION_GRAPHIC_EXTS = (".webm", ".mov", ".mp4")


def _motion_graphics_files() -> list[str]:
    return sorted(
        f for f in os.listdir(MOTION_GRAPHICS_DIR)
        if f.lower().endswith(_MOTION_GRAPHIC_EXTS) and not f.startswith("README")
    )

app = FastAPI(title="Vídeo Mágico")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

JOBS: dict[str, dict] = {}

FILE_KEYS = {
    "final": ("final_video", "video/mp4"),
    "srt": ("srt", "text/plain"),
    "transcript": ("transcript", "text/plain"),
    "fcpxml": ("fcpxml", "application/xml"),
}


def process_job(job_id: str, source: dict, options: dict, numero_de_cortes: int = 1, duracao_maxima_por_corte: float = 60.0):
    def progress_cb(pct, msg):
        JOBS[job_id]["progress"] = pct
        JOBS[job_id]["message"] = msg

    try:
        JOBS[job_id]["status"] = "processing"

        if source["type"] == "youtube":
            JOBS[job_id]["message"] = "Baixando do YouTube..."
            yt_dir = os.path.join(UPLOAD_DIR, job_id)
            input_path = YT.download_youtube(source["url"], yt_dir, progress_cb=progress_cb)
        else:
            input_path = source["path"]

        work_dir = os.path.join(JOBS_DIR, job_id)
        JOBS[job_id]["work_dir"] = work_dir

        if numero_de_cortes > 1:
            # run_pipeline_multi usa "num_cortes"/"duracao_maxima_por_corte"
            # em vez de "target_duration" (que é só do modo "um reel só").
            multi_options = {k: v for k, v in options.items() if k != "target_duration"}
            result = run_pipeline_multi(
                input_path, work_dir,
                num_cortes=numero_de_cortes,
                duracao_maxima_por_corte=duracao_maxima_por_corte,
                progress_cb=progress_cb, **multi_options,
            )
            JOBS[job_id]["multi"] = True
        else:
            result = run_pipeline(input_path, work_dir, progress_cb=progress_cb, **options)
            JOBS[job_id]["multi"] = False

        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["result"] = result
    except YT.YoutubeDownloadError as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = f"Não consegui baixar esse vídeo do YouTube: {e}"
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    music_files = sorted(
        f for f in os.listdir(MUSIC_DIR) if f.lower().endswith((".mp3", ".wav", ".m4a", ".aac"))
    )
    motion_graphics_files = _motion_graphics_files()
    return templates.TemplateResponse(
        request, "index.html",
        {"music_files": music_files, "motion_graphics_files": motion_graphics_files},
    )


@app.post("/upload")
async def upload(
    file: UploadFile | None = File(None),
    youtube_url: str = Form(""),
    duration: float = Form(60.0),
    aspect: str = Form("9:16"),
    crossfade: float = Form(0.4),
    music: str = Form(""),
    model_size: str = Form("base"),
    numero_de_cortes: int = Form(1),
    duracao_maxima_por_corte: float = Form(60.0),
    motion_graphic: str = Form(""),
    ritmo_cortes: str = Form("equilibrado"),
    estilo_legenda: str = Form("padrao"),
):
    job_id = uuid.uuid4().hex[:12]
    youtube_url = youtube_url.strip()
    numero_de_cortes = max(1, min(30, int(numero_de_cortes or 1)))

    if file is not None and file.filename:
        safe_name = f"{job_id}_{os.path.basename(file.filename)}"
        input_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(input_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        source = {"type": "file", "path": input_path}
    elif youtube_url:
        if not YT.is_youtube_url(youtube_url):
            raise HTTPException(400, "Isso não parece um link do YouTube válido.")
        source = {"type": "youtube", "url": youtube_url}
    else:
        raise HTTPException(400, "Envie um vídeo ou cole um link do YouTube.")

    music_path = os.path.join(MUSIC_DIR, music) if music else None
    motion_graphic_path = os.path.join(MOTION_GRAPHICS_DIR, motion_graphic) if motion_graphic else None
    options = dict(
        target_duration=duration,
        aspect=aspect,
        crossfade=crossfade,
        music_path=music_path,
        model_size=model_size,
        motion_graphic_path=motion_graphic_path,
        ritmo_cortes=ritmo_cortes,
        estilo_legenda=estilo_legenda,
    )

    JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Na fila..."}
    thread = threading.Thread(
        target=process_job,
        args=(job_id, source, options, numero_de_cortes, duracao_maxima_por_corte),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")

    safe = {k: v for k, v in job.items() if k not in ("result",)}
    if job.get("status") == "done":
        result = job["result"]
        if job.get("multi"):
            safe["cortes"] = [
                {
                    "numero": i + 1,
                    "video": f"/download/{job_id}/corte/{i + 1}/video",
                    "srt": f"/download/{job_id}/corte/{i + 1}/srt",
                    "fcpxml": f"/download/{job_id}/corte/{i + 1}/fcpxml",
                    "duracao": round(c.get("total_duration", 0), 1),
                }
                for i, c in enumerate(result.get("cortes", []))
            ]
            safe["transcript"] = f"/download/{job_id}/transcript"
            safe["summary"] = {
                "num_cortes_gerados": result.get("num_cortes_gerados"),
                "language": result.get("language"),
            }
        else:
            safe["files"] = {kind: f"/download/{job_id}/{kind}" for kind in FILE_KEYS}
            safe["summary"] = {
                "num_clips": result.get("num_clips"),
                "total_duration": round(result.get("total_duration", 0), 1),
                "language": result.get("language"),
            }
    return JSONResponse(safe)


@app.get("/download/{job_id}/{kind}")
def download(job_id: str, kind: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "arquivo não disponível")
    if kind == "transcript":
        path = job["result"]["transcript"]
        return FileResponse(path, filename=os.path.basename(path), media_type="text/plain")
    if kind not in FILE_KEYS:
        raise HTTPException(404, "tipo inválido")

    key, media_type = FILE_KEYS[kind]
    path = job["result"][key]
    return FileResponse(path, filename=os.path.basename(path), media_type=media_type)


_CORTE_KEYS = {
    "video": ("final_video", "video/mp4"),
    "srt": ("srt", "text/plain"),
    "fcpxml": ("fcpxml", "application/xml"),
}


@app.get("/download/{job_id}/corte/{numero}/{kind}")
def download_corte(job_id: str, numero: int, kind: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done" or not job.get("multi"):
        raise HTTPException(404, "arquivo não disponível")
    if kind not in _CORTE_KEYS:
        raise HTTPException(404, "tipo inválido")

    cortes = job["result"].get("cortes", [])
    if numero < 1 or numero > len(cortes):
        raise HTTPException(404, "corte não encontrado")

    key, media_type = _CORTE_KEYS[kind]
    path = cortes[numero - 1][key]
    nome_pasta = os.path.basename(cortes[numero - 1]["pasta"])
    filename = f"{nome_pasta}{os.path.splitext(path)[1]}"
    return FileResponse(path, filename=filename, media_type=media_type)


@app.post("/open-folder/{job_id}")
def open_folder(job_id: str):
    """Abre a pasta do resultado no Explorer/Finder — só faz sentido porque
    o app roda 100% local (o navegador e o servidor estão na mesma
    máquina)."""
    job = JOBS.get(job_id)
    if not job or not job.get("work_dir"):
        raise HTTPException(404, "pasta não encontrada")
    _open_folder(job["work_dir"])
    return {"ok": True}


EDITOR_ASSETS: dict[str, dict] = {}
EDITOR_JOBS: dict[str, dict] = {}
EDITOR_CAPTION_JOBS: dict[str, dict] = {}
EDITOR_WAVEFORM_LOCK = threading.Lock()
EDITOR_ASSETS_DIR = os.path.join(EDITOR_DIR, "assets")
os.makedirs(EDITOR_ASSETS_DIR, exist_ok=True)


def _save_asset_meta(asset: dict):
    with open(os.path.join(os.path.dirname(asset["path"]), "meta.json"), "w", encoding="utf-8") as f:
        json.dump(asset, f, ensure_ascii=False)


def _public_asset(asset: dict) -> dict:
    data = {k: v for k, v in asset.items() if k != "path"}
    data["url"] = f"/editor/asset/{asset['id']}?v={asset.get('version', 0)}"
    return data


def _rehydrate_editor_assets():
    """Se o app reiniciar com o navegador ainda aberto, as mídias já enviadas
    continuam em disco (editor_jobs/assets/<id>/) — só a lista em memória se
    perderia. Isso recria a lista a partir do meta.json de cada pasta."""
    for name in os.listdir(EDITOR_ASSETS_DIR):
        meta_path = os.path.join(EDITOR_ASSETS_DIR, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                asset = json.load(f)
            if os.path.isfile(asset["path"]):
                EDITOR_ASSETS[asset["id"]] = asset
        except Exception:
            pass


_rehydrate_editor_assets()


@app.get("/editor", response_class=HTMLResponse)
def editor_page(request: Request):
    return templates.TemplateResponse(request, "editor.html")


@app.get("/editor/assets")
def editor_assets_list():
    assets = sorted(EDITOR_ASSETS.values(), key=lambda a: a.get("created", 0))
    return [_public_asset(a) for a in assets]


@app.post("/editor/assets")
async def editor_asset_upload(
    file: UploadFile = File(...),
    design: str = Form(""),
    replace_id: str = Form(""),
):
    """Salva uma mídia (vídeo, áudio ou imagem) na biblioteca do editor.
    `design` guarda as camadas do editor de imagem (pra reabrir e editar de
    novo) e `replace_id` troca o arquivo de uma imagem já existente mantendo
    o mesmo id (os clipes na linha do tempo continuam apontando pra ela)."""
    if not file.filename:
        raise HTTPException(400, "Envie um arquivo.")

    existing = EDITOR_ASSETS.get(replace_id) if replace_id else None
    asset_id = existing["id"] if existing else uuid.uuid4().hex[:12]
    asset_dir = os.path.join(EDITOR_ASSETS_DIR, asset_id)
    os.makedirs(asset_dir, exist_ok=True)
    ext = re.sub(r"[^A-Za-z0-9.]", "", os.path.splitext(file.filename)[1])[:8] or ".bin"
    path = os.path.join(asset_dir, f"file{ext}")
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        info = ED.probe_media(path)
    except Exception:
        if not existing:
            shutil.rmtree(asset_dir, ignore_errors=True)
        raise HTTPException(400, "Não consegui ler esse arquivo — confira se ele não está corrompido.")

    if existing and existing["path"] != path and os.path.isfile(existing["path"]):
        os.remove(existing["path"])

    asset = {
        "id": asset_id,
        "name": existing["name"] if existing else file.filename,
        "path": path,
        "created": existing["created"] if existing else time.time(),
        "version": (existing.get("version", 0) + 1) if existing else 0,
        "design": design or (existing.get("design", "") if existing else ""),
        **info,
    }
    EDITOR_ASSETS[asset_id] = asset
    _save_asset_meta(asset)
    return _public_asset(asset)


@app.get("/editor/asset/{asset_id}")
def editor_asset(asset_id: str):
    asset = EDITOR_ASSETS.get(asset_id)
    if not asset:
        raise HTTPException(404, "mídia não encontrada")
    media_type = mimetypes.guess_type(asset["path"])[0] or "application/octet-stream"
    return FileResponse(asset["path"], media_type=media_type)


@app.get("/editor/assets/{asset_id}/waveform")
def editor_waveform(asset_id: str):
    asset = EDITOR_ASSETS.get(asset_id)
    if not asset or not asset.get("has_audio"):
        raise HTTPException(404, "Mídia com áudio não encontrada.")
    cache_path = os.path.join(os.path.dirname(asset["path"]), f"waveform-{asset.get('version', 0)}.json")
    try:
        with EDITOR_WAVEFORM_LOCK:
            if os.path.isfile(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    return JSONResponse(json.load(f))
            peaks = ED.audio_peaks(asset["path"])
            result = {"peaks": peaks, "peaks_per_second": 100}
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, separators=(",", ":"))
        return JSONResponse(result)
    except (OSError, RuntimeError, ValueError) as e:
        raise HTTPException(500, f"Não foi possível gerar as ondas de áudio: {e}") from e


@app.delete("/editor/assets/{asset_id}")
def editor_asset_delete(asset_id: str):
    asset = EDITOR_ASSETS.pop(asset_id, None)
    if asset:
        shutil.rmtree(os.path.dirname(asset["path"]), ignore_errors=True)
    return {"ok": True}


@app.post("/editor/captions")
async def editor_captions(request: Request):
    project = await request.json()
    if not any(t.get("clips") for t in project.get("tracks", [])):
        raise HTTPException(400, "Adicione um vídeo ou áudio à linha do tempo.")
    job_id = uuid.uuid4().hex[:12]
    EDITOR_CAPTION_JOBS[job_id] = {"status": "queued", "message": "Preparando áudio..."}
    assets = dict(EDITOR_ASSETS)

    def run():
        job = EDITOR_CAPTION_JOBS[job_id]
        try:
            job["status"] = "processing"
            with tempfile.TemporaryDirectory(prefix="editor_captions_") as tmp:
                audio = os.path.join(tmp, "audio.wav")
                ED.extract_timeline_audio(project, assets, audio)
                job["message"] = "Transcrevendo com Whisper. Na primeira vez o modelo é baixado e pode demorar..."
                transcript = T.transcribe(audio, model_size="base", language=None)
                cues = C.cues_from_transcript(transcript)
            job["captions"] = cues
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/editor/captions/{job_id}")
def editor_captions_status(job_id: str):
    job = EDITOR_CAPTION_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Processo de legendagem não encontrado.")
    return JSONResponse(job)


@app.post("/editor/export")
async def editor_export(request: Request):
    project = await request.json()
    if not any(t.get("clips") for t in project.get("tracks", [])):
        raise HTTPException(400, "Adicione pelo menos um clipe antes de exportar.")

    job_id = uuid.uuid4().hex[:12]
    EDITOR_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Na fila..."}

    def run():
        def progress_cb(pct, msg):
            EDITOR_JOBS[job_id]["progress"] = pct
            EDITOR_JOBS[job_id]["message"] = msg

        try:
            EDITOR_JOBS[job_id]["status"] = "processing"
            out_dir = os.path.join(EDITOR_DIR, job_id)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "editado.mp4")
            ED.export_timeline(project, dict(EDITOR_ASSETS), out_path, progress_cb=progress_cb)
            EDITOR_JOBS[job_id]["status"] = "done"
            EDITOR_JOBS[job_id]["output_path"] = out_path
        except Exception as e:
            EDITOR_JOBS[job_id]["status"] = "error"
            EDITOR_JOBS[job_id]["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/editor/status/{job_id}")
def editor_status(job_id: str):
    job = EDITOR_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")
    safe = {k: v for k, v in job.items() if k != "output_path"}
    if job.get("status") == "done":
        safe["video_url"] = f"/editor/download/{job_id}"
    return JSONResponse(safe)


@app.get("/editor/download/{job_id}")
def editor_download(job_id: str):
    job = EDITOR_JOBS.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "arquivo não disponível")
    return FileResponse(job["output_path"], filename="editado.mp4", media_type="video/mp4")


SESSIONS: dict[str, dict] = {}


def _sfx_files() -> list[str]:
    return sorted(f for f in os.listdir(SFX_DIR) if f.lower().endswith((".mp3", ".wav", ".m4a", ".aac")))


def process_chat_start(session_id: str, source: dict, model_size: str, language: str | None):
    session = SESSIONS[session_id]

    def progress_cb(pct, msg):
        session["progress"] = pct
        session["message"] = msg

    try:
        if source["type"] == "youtube":
            session["status"] = "transcribing"
            session["message"] = "Baixando do YouTube..."
            yt_dir = os.path.join(UPLOAD_DIR, session_id)
            input_path = YT.download_youtube(source["url"], yt_dir, progress_cb=progress_cb)
            session["input_path"] = input_path
        else:
            input_path = source["path"]

        session["status"] = "transcribing"
        session["progress"] = 0
        session["message"] = "Transcrevendo o vídeo (local, grátis)..."

        audio_path = os.path.join(JOBS_DIR, f"chat_{session_id}_audio.wav")
        extract_audio(input_path, audio_path)
        transcript = T.transcribe(audio_path, model_size=model_size, language=language)
        if os.path.exists(audio_path):
            os.remove(audio_path)

        if not transcript["segments"]:
            raise RuntimeError(
                "Não consegui detectar fala nesse vídeo. Confira se o áudio "
                "está presente e audível no arquivo enviado."
            )

        session["transcript"] = transcript
        session["video_duration"] = R.ffprobe_duration(input_path)
        session["status"] = "ready"
        session["message"] = "Pronto! Me diga como você quer editar esse vídeo."
    except YT.YoutubeDownloadError as e:
        session["status"] = "error"
        session["error"] = f"Não consegui baixar esse vídeo do YouTube: {e}"
    except Exception as e:
        session["status"] = "error"
        session["error"] = str(e)


def process_chat_turn(session_id: str):
    session = SESSIONS[session_id]

    def progress_cb(pct, msg):
        session["progress"] = pct
        session["message"] = msg

    try:
        session["status"] = "thinking"
        session["progress"] = 0
        session["message"] = "Pensando no plano de edição (Ollama local)..."

        config = load_config()
        sfx_files = _sfx_files()
        motion_graphics_files = _motion_graphics_files()

        system_prompt = D.build_system_prompt(
            session["transcript"], session["video_duration"], sfx_files,
            motion_graphics_files=motion_graphics_files,
        )
        messages = [{"role": "system", "content": system_prompt}] + session["history"]

        raw = D.call_ollama(messages, model=config["ollama_model"], base_url=config["ollama_base_url"])
        plan = D.parse_and_validate_plan(
            raw, session["video_duration"], sfx_files,
            default_duration=config.get("duracao_alvo_segundos", 45),
            available_motion_graphics=motion_graphics_files,
        )
        session["plan"] = plan
        session["history"].append({"role": "assistant", "content": raw})

        session["status"] = "rendering"
        session["message"] = "Renderizando o vídeo..."
        session["turn_counter"] += 1
        work_dir = os.path.join(JOBS_DIR, f"chat_{session_id}", f"turn_{session['turn_counter']:03d}")

        music_path = None
        if config.get("musica"):
            candidate = os.path.join(MUSIC_DIR, config["musica"])
            if os.path.exists(candidate):
                music_path = candidate

        result = run_edit_plan(
            session["input_path"], work_dir, session["transcript"], plan,
            aspect=config.get("formato", "9:16"),
            crossfade=config.get("transicao_segundos", 0.4),
            music_path=music_path,
            sfx_dir=SFX_DIR,
            motion_graphics_dir=MOTION_GRAPHICS_DIR,
            estilo_legenda=config.get("estilo_legenda", "padrao"),
            progress_cb=progress_cb,
        )

        session["result"] = result
        session["status"] = "done"
        session["progress"] = 100
        session["message"] = plan["resposta_para_usuario"]
        session["display_history"].append({"role": "assistant", "content": plan["resposta_para_usuario"]})
    except D.OllamaError as e:
        session["status"] = "error"
        session["error"] = str(e)
    except Exception as e:
        session["status"] = "error"
        session["error"] = f"Deu um erro processando esse pedido: {e}"


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html")


@app.post("/chat/start")
async def chat_start(
    file: UploadFile | None = File(None),
    youtube_url: str = Form(""),
    model_size: str = Form("base"),
    idioma: str = Form("pt"),
):
    session_id = uuid.uuid4().hex[:12]
    youtube_url = youtube_url.strip()

    if file is not None and file.filename:
        safe_name = f"{session_id}_{os.path.basename(file.filename)}"
        input_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(input_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        source = {"type": "file", "path": input_path}
    elif youtube_url:
        if not YT.is_youtube_url(youtube_url):
            raise HTTPException(400, "Isso não parece um link do YouTube válido.")
        source = {"type": "youtube", "url": youtube_url}
    else:
        raise HTTPException(400, "Envie um vídeo ou cole um link do YouTube.")

    SESSIONS[session_id] = {
        # pro caso "youtube", input_path só é preenchido depois do download
        # (dentro de process_chat_start) — fica None até lá.
        "input_path": source.get("path"),
        "status": "transcribing",
        "progress": 0,
        "message": "Transcrevendo...",
        "error": None,
        "history": [],
        "display_history": [],
        "plan": None,
        "result": None,
        "turn_counter": 0,
        "transcript": None,
        "video_duration": None,
    }

    thread = threading.Thread(
        target=process_chat_start,
        args=(session_id, source, model_size, idioma or None),
        daemon=True,
    )
    thread.start()
    return {"session_id": session_id}


@app.post("/chat/{session_id}/message")
async def chat_message(session_id: str, text: str = Form(...)):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "sessão não encontrada")
    if session["status"] not in ("ready", "done", "error"):
        raise HTTPException(409, "ainda processando a mensagem anterior, espera terminar")
    if not text.strip():
        raise HTTPException(400, "mensagem vazia")

    session["display_history"].append({"role": "user", "content": text})
    session["history"].append({"role": "user", "content": text})
    session["error"] = None

    thread = threading.Thread(target=process_chat_turn, args=(session_id,), daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/chat/{session_id}/status")
def chat_status(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "sessão não encontrada")

    safe = {
        "status": session["status"],
        "progress": session["progress"],
        "message": session["message"],
        "error": session["error"],
        "display_history": session["display_history"],
    }
    if session.get("result"):
        safe["files"] = {kind: f"/chat/{session_id}/download/{kind}" for kind in FILE_KEYS}
    return JSONResponse(safe)


@app.get("/chat/{session_id}/download/{kind}")
def chat_download(session_id: str, kind: str):
    session = SESSIONS.get(session_id)
    if not session or not session.get("result"):
        raise HTTPException(404, "arquivo não disponível")
    if kind not in FILE_KEYS:
        raise HTTPException(404, "tipo inválido")

    key, media_type = FILE_KEYS[kind]
    path = session["result"][key]
    return FileResponse(path, filename=os.path.basename(path), media_type=media_type)


if __name__ == "__main__":
    import time
    import webbrowser

    import uvicorn

    # o modo "arrasta e pronto" roda em segundo plano, no MESMO processo do
    # site — assim um clique só liga as duas formas de usar o Vídeo Mágico.
    watcher_thread = threading.Thread(target=watch_loop, daemon=True)
    watcher_thread.start()
    print(f"Modo 'arrasta e pronto' também está ativo: arraste vídeos pra {ENTRADA}")
    print(f"(os resultados aparecem em {SAIDA})")

    def _open_browser():
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:8000")

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)

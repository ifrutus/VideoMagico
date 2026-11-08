const dropzone = document.getElementById("dropzone");
const dropzoneText = document.getElementById("dropzone-text");
const fileInput = document.getElementById("file-input");
const uploadStep = document.getElementById("upload-step");
const editorStep = document.getElementById("editor-step");

const sourceVideo = document.getElementById("source-video");
const startInput = document.getElementById("start-input");
const endInput = document.getElementById("end-input");
const useCurrentStart = document.getElementById("use-current-start");
const useCurrentEnd = document.getElementById("use-current-end");
const addClipBtn = document.getElementById("add-clip-btn");

const clipsList = document.getElementById("clips-list");
const noClipsHint = document.getElementById("no-clips-hint");
const exportBtn = document.getElementById("export-btn");

const exportProgress = document.getElementById("export-progress");
const exportProgressFill = document.getElementById("export-progress-fill");
const exportProgressMsg = document.getElementById("export-progress-msg");

const exportResult = document.getElementById("export-result");
const resultVideo = document.getElementById("result-video");
const dlResult = document.getElementById("dl-result");

const errorArea = document.getElementById("editor-error");
const resumeNote = document.getElementById("resume-note");
const restartLink = document.getElementById("restart-link");

const STORAGE_KEY = "video_magico_editor_state_v1";

let sourceId = null;
let videoDuration = 0;
let videoUrl = null;
let clips = []; // { start, end }
let dragIndex = null;

// --- salvar/restaurar progresso (pra não perder os cortes marcados se a
// página recarregar ou o servidor reiniciar pra atualizar) ---

function saveState() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            sourceId, videoDuration, videoUrl, clips,
        }));
    } catch (err) {
        // armazenamento local indisponível (ex: aba anônima) — segue sem salvar
    }
}

function clearState() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (err) { /* ignora */ }
}

async function tryResume() {
    let saved = null;
    try {
        saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    } catch (err) {
        return;
    }
    if (!saved || !saved.sourceId) return;

    try {
        const res = await fetch(saved.videoUrl, { headers: { Range: "bytes=0-1" } });
        if (!res.ok && res.status !== 206) throw new Error("vídeo não existe mais");
    } catch (err) {
        clearState();
        return;
    }

    sourceId = saved.sourceId;
    videoDuration = saved.videoDuration;
    videoUrl = saved.videoUrl;
    clips = saved.clips || [];
    sourceVideo.src = videoUrl;
    uploadStep.hidden = true;
    editorStep.hidden = false;
    resumeNote.hidden = clips.length === 0;
    renderClips();
}

restartLink.addEventListener("click", e => {
    e.preventDefault();
    clearState();
    sourceId = null;
    videoDuration = 0;
    videoUrl = null;
    clips = [];
    sourceVideo.src = "";
    resumeNote.hidden = true;
    exportResult.hidden = true;
    editorStep.hidden = true;
    uploadStep.hidden = false;
    dropzoneText.textContent = "Arraste um vídeo aqui ou clique pra escolher";
});

tryResume();

function showError(msg) {
    errorArea.hidden = false;
    errorArea.textContent = msg;
}

function formatTime(seconds) {
    seconds = Math.max(0, seconds);
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1).padStart(4, "0");
    return `${m}:${s}`;
}

// aceita "12.5" (segundos) ou "1:05" (minuto:segundo)
function parseTime(text) {
    text = (text || "").trim();
    if (!text) return null;
    if (text.includes(":")) {
        const [m, s] = text.split(":");
        const mins = parseFloat(m);
        const secs = parseFloat(s);
        if (isNaN(mins) || isNaN(secs)) return null;
        return mins * 60 + secs;
    }
    const n = parseFloat(text);
    return isNaN(n) ? null : n;
}

// --- upload ---

dropzone.addEventListener("click", () => fileInput.click());

["dragenter", "dragover"].forEach(evt =>
    dropzone.addEventListener(evt, e => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    })
);
["dragleave", "drop"].forEach(evt =>
    dropzone.addEventListener(evt, e => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
    })
);
dropzone.addEventListener("drop", e => {
    const files = e.dataTransfer.files;
    if (files.length) uploadFile(files[0]);
});
fileInput.addEventListener("change", () => {
    if (fileInput.files.length) uploadFile(fileInput.files[0]);
});

async function uploadFile(file) {
    dropzoneText.textContent = `Enviando ${file.name}...`;
    const formData = new FormData();
    formData.set("file", file);
    try {
        const res = await fetch("/editor/upload", { method: "POST", body: formData });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        sourceId = data.source_id;
        videoDuration = data.duration;
        videoUrl = data.video_url;
        sourceVideo.src = videoUrl;
        clips = [];
        uploadStep.hidden = true;
        editorStep.hidden = false;
        resumeNote.hidden = true;
        saveState();
    } catch (err) {
        dropzoneText.textContent = "Arraste um vídeo aqui ou clique pra escolher";
        showError("Erro ao enviar o vídeo: " + err.message);
    }
}

// --- marcar início/fim ---

useCurrentStart.addEventListener("click", () => {
    startInput.value = sourceVideo.currentTime.toFixed(2);
});
useCurrentEnd.addEventListener("click", () => {
    endInput.value = sourceVideo.currentTime.toFixed(2);
});

addClipBtn.addEventListener("click", () => {
    const start = parseTime(startInput.value);
    const end = parseTime(endInput.value);
    errorArea.hidden = true;

    if (start === null || end === null) {
        showError("Preencha início e fim (em segundos, ex: 12.5, ou minuto:segundo, ex: 1:05).");
        return;
    }
    if (end <= start) {
        showError("O fim precisa ser depois do início.");
        return;
    }
    if (videoDuration && (start > videoDuration || end > videoDuration + 0.5)) {
        showError(`Esse vídeo tem ${formatTime(videoDuration)} — o corte marcado passa disso.`);
        return;
    }

    clips.push({ start, end });
    startInput.value = "";
    endInput.value = "";
    renderClips();
    saveState();
});

// --- lista de cortes (arrastar pra reordenar) ---

function renderClips() {
    clipsList.innerHTML = "";
    noClipsHint.hidden = clips.length > 0;
    exportBtn.disabled = clips.length === 0;

    clips.forEach((clip, i) => {
        const li = document.createElement("li");
        li.className = "clip-card";
        li.draggable = true;
        li.dataset.index = i;
        li.innerHTML = `
            <span class="drag-handle">⠿</span>
            <span class="clip-label"><b>Corte ${i + 1}</b>: ${formatTime(clip.start)} → ${formatTime(clip.end)}
                (${(clip.end - clip.start).toFixed(1)}s)</span>
            <button type="button" data-action="preview" data-index="${i}">▶ prévia</button>
            <button type="button" data-action="remove" data-index="${i}">✕ remover</button>
        `;
        clipsList.appendChild(li);
    });
}

clipsList.addEventListener("click", e => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const idx = parseInt(btn.dataset.index, 10);
    if (btn.dataset.action === "remove") {
        clips.splice(idx, 1);
        renderClips();
        saveState();
    } else if (btn.dataset.action === "preview") {
        previewClip(clips[idx]);
    }
});

function previewClip(clip) {
    sourceVideo.currentTime = clip.start;
    sourceVideo.play();
    const onTick = () => {
        if (sourceVideo.currentTime >= clip.end) {
            sourceVideo.pause();
            sourceVideo.removeEventListener("timeupdate", onTick);
        }
    };
    sourceVideo.addEventListener("timeupdate", onTick);
}

clipsList.addEventListener("dragstart", e => {
    const li = e.target.closest(".clip-card");
    if (!li) return;
    dragIndex = parseInt(li.dataset.index, 10);
    li.classList.add("dragging");
});
clipsList.addEventListener("dragend", e => {
    const li = e.target.closest(".clip-card");
    if (li) li.classList.remove("dragging");
    clipsList.querySelectorAll(".drag-over").forEach(el => el.classList.remove("drag-over"));
});
clipsList.addEventListener("dragover", e => {
    e.preventDefault();
    const li = e.target.closest(".clip-card");
    if (li) li.classList.add("drag-over");
});
clipsList.addEventListener("dragleave", e => {
    const li = e.target.closest(".clip-card");
    if (li) li.classList.remove("drag-over");
});
clipsList.addEventListener("drop", e => {
    e.preventDefault();
    const li = e.target.closest(".clip-card");
    if (!li || dragIndex === null) return;
    const dropIndex = parseInt(li.dataset.index, 10);
    const [moved] = clips.splice(dragIndex, 1);
    clips.splice(dropIndex, 0, moved);
    dragIndex = null;
    renderClips();
    saveState();
});

// --- exportar ---

exportBtn.addEventListener("click", async () => {
    errorArea.hidden = true;
    exportResult.hidden = true;
    exportBtn.disabled = true;
    exportProgress.hidden = false;
    exportProgressFill.style.width = "0%";
    exportProgressMsg.textContent = "Enviando pedido...";

    try {
        const res = await fetch("/editor/export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source_id: sourceId, segments: clips }),
        });
        if (!res.ok) throw new Error(await res.text());
        const { job_id } = await res.json();
        pollExport(job_id);
    } catch (err) {
        showError("Erro ao exportar: " + err.message);
        exportBtn.disabled = false;
        exportProgress.hidden = true;
    }
});

function pollExport(jobId) {
    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/editor/status/${jobId}`);
            const data = await res.json();

            if (data.status === "error") {
                clearInterval(interval);
                showError("Erro ao exportar: " + data.error);
                exportBtn.disabled = false;
                exportProgress.hidden = true;
                return;
            }

            exportProgressFill.style.width = (data.progress || 0) + "%";
            exportProgressMsg.textContent = data.message || "Processando...";

            if (data.status === "done") {
                clearInterval(interval);
                exportBtn.disabled = false;
                exportProgress.hidden = true;
                exportResult.hidden = false;
                resultVideo.src = data.video_url;
                dlResult.href = data.video_url;
            }
        } catch (err) {
            clearInterval(interval);
            showError("Perdi a conexão com o servidor: " + err.message);
            exportBtn.disabled = false;
        }
    }, 1500);
}

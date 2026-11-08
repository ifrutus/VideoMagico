const dropzone = document.getElementById("dropzone");
const dropzoneText = document.getElementById("dropzone-text");
const fileInput = document.getElementById("file-input");
const youtubeInput = document.getElementById("youtube-input");
const form = document.getElementById("upload-form");
const submitBtn = document.getElementById("submit-btn");

const progressArea = document.getElementById("progress-area");
const progressFill = document.getElementById("progress-fill");
const progressMsg = document.getElementById("progress-msg");

const resultArea = document.getElementById("result-area");
const resultSummary = document.getElementById("result-summary");
const resultVideo = document.getElementById("result-video");
const resultSingle = document.getElementById("result-single");
const resultMulti = document.getElementById("result-multi");
const cortesList = document.getElementById("cortes-list");
const btnAbrirPasta = document.getElementById("btn-abrir-pasta");

const numeroDeCortesInput = document.getElementById("numero-de-cortes");
const duracaoAlvoLabel = document.getElementById("duracao-alvo-label");
const duracaoPorCorteLabel = document.getElementById("duracao-por-corte-label");

const errorArea = document.getElementById("error-area");

let selectedFile = null;
let currentJobId = null;

function syncDurationFields() {
    const multi = parseInt(numeroDeCortesInput.value || "1", 10) > 1;
    duracaoAlvoLabel.hidden = multi;
    duracaoPorCorteLabel.hidden = !multi;
}
numeroDeCortesInput.addEventListener("input", syncDurationFields);
syncDurationFields();

btnAbrirPasta.addEventListener("click", async () => {
    if (!currentJobId) return;
    try {
        await fetch(`/open-folder/${currentJobId}`, { method: "POST" });
    } catch (err) {
        alert("Não consegui abrir a pasta: " + err.message);
    }
});

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
    if (files.length) setFile(files[0]);
});

fileInput.addEventListener("change", () => {
    if (fileInput.files.length) setFile(fileInput.files[0]);
});

function setFile(file) {
    selectedFile = file;
    dropzoneText.textContent = `Selecionado: ${file.name}`;
    youtubeInput.value = ""; // arquivo e link do YouTube são alternativas, não os dois
}

youtubeInput.addEventListener("input", () => {
    if (youtubeInput.value.trim()) {
        selectedFile = null;
        fileInput.value = "";
        dropzoneText.textContent = "Arraste um vídeo aqui ou clique pra escolher";
    }
});

form.addEventListener("submit", async e => {
    e.preventDefault();
    const youtubeUrl = youtubeInput.value.trim();
    if (!selectedFile && !youtubeUrl) {
        alert("Escolha um vídeo ou cole um link do YouTube primeiro.");
        return;
    }

    errorArea.hidden = true;
    resultArea.hidden = true;
    btnAbrirPasta.hidden = true;
    currentJobId = null;
    submitBtn.disabled = true;
    progressArea.hidden = false;
    progressFill.style.width = "0%";
    progressMsg.textContent = selectedFile ? "Enviando vídeo..." : "Pedido enviado, baixando do YouTube...";

    const formData = new FormData(form);
    if (selectedFile) {
        formData.set("file", selectedFile);
        formData.delete("youtube_url");
    } else {
        formData.delete("file");
        formData.set("youtube_url", youtubeUrl);
    }

    try {
        const res = await fetch("/upload", { method: "POST", body: formData });
        if (!res.ok) throw new Error(await res.text());
        const { job_id } = await res.json();
        pollStatus(job_id);
    } catch (err) {
        showError("Erro ao enviar o vídeo: " + err.message);
        submitBtn.disabled = false;
    }
});

function pollStatus(jobId) {
    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/status/${jobId}`);
            const data = await res.json();

            if (data.status === "error") {
                clearInterval(interval);
                showError("Erro ao processar: " + data.error);
                submitBtn.disabled = false;
                progressArea.hidden = true;
                return;
            }

            progressFill.style.width = (data.progress || 0) + "%";
            progressMsg.textContent = data.message || "Processando...";

            if (data.status === "done") {
                clearInterval(interval);
                submitBtn.disabled = false;
                progressArea.hidden = true;
                showResult(jobId, data);
            }
        } catch (err) {
            clearInterval(interval);
            showError("Perdi a conexão com o servidor: " + err.message);
            submitBtn.disabled = false;
        }
    }, 1500);
}

function showResult(jobId, data) {
    resultArea.hidden = false;
    currentJobId = jobId;
    btnAbrirPasta.hidden = false;
    const s = data.summary || {};

    if (data.cortes) {
        resultSingle.hidden = true;
        resultMulti.hidden = false;
        resultSummary.textContent =
            `${s.num_cortes_gerados ?? data.cortes.length} corte(s) prontos, já legendados e sem os ` +
            `respiros/hesitações nas bordas · idioma detectado: ${s.language ?? "?"}`;

        cortesList.innerHTML = "";
        for (const corte of data.cortes) {
            const card = document.createElement("div");
            card.className = "corte-card";
            card.innerHTML = `
                <h3>Corte ${corte.numero} <span class="corte-duracao">(${corte.duracao}s)</span></h3>
                <video controls src="${corte.video}"></video>
                <div class="downloads">
                    <a href="${corte.video}" download>⬇ Vídeo</a>
                    <a href="${corte.srt}" download>⬇ Legenda</a>
                    <a href="${corte.fcpxml}" download>⬇ Premiere</a>
                </div>
            `;
            cortesList.appendChild(card);
        }
    } else {
        resultSingle.hidden = false;
        resultMulti.hidden = true;
        resultSummary.textContent = `${s.num_clips ?? "?"} corte(s) selecionado(s) · ${s.total_duration ?? "?"}s · idioma detectado: ${s.language ?? "?"}`;

        resultVideo.src = data.files.final;
        document.getElementById("dl-final").href = data.files.final;
        document.getElementById("dl-srt").href = data.files.srt;
        document.getElementById("dl-transcript").href = data.files.transcript;
        document.getElementById("dl-fcpxml").href = data.files.fcpxml;
    }
}

function showError(msg) {
    errorArea.hidden = false;
    errorArea.textContent = msg;
}

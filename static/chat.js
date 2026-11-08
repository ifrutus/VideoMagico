const dropzone = document.getElementById("dropzone");
const dropzoneText = document.getElementById("dropzone-text");
const fileInput = document.getElementById("file-input");
const youtubeInput = document.getElementById("youtube-input");
const startBtn = document.getElementById("start-btn");

const uploadStep = document.getElementById("upload-step");
const chatStep = document.getElementById("chat-step");

const messagesEl = document.getElementById("messages");
const form = document.getElementById("message-form");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");

const turnProgress = document.getElementById("turn-progress");
const turnProgressFill = document.getElementById("turn-progress-fill");
const turnProgressMsg = document.getElementById("turn-progress-msg");

const resultVideo = document.getElementById("result-video");
const noResult = document.getElementById("no-result");
const downloads = document.getElementById("downloads");

let selectedFile = null;
let sessionId = null;
let renderedCount = 0; // quantas mensagens do display_history já desenhamos

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
    startBtn.disabled = false;
}

youtubeInput.addEventListener("input", () => {
    const url = youtubeInput.value.trim();
    if (url) {
        selectedFile = null;
        fileInput.value = "";
        dropzoneText.textContent = "Arraste o vídeo bruto aqui ou clique pra escolher";
    }
    startBtn.disabled = !url && !selectedFile;
});

startBtn.addEventListener("click", async () => {
    const youtubeUrl = youtubeInput.value.trim();
    if (!selectedFile && !youtubeUrl) return;
    startBtn.disabled = true;
    startBtn.textContent = selectedFile ? "Enviando e transcrevendo..." : "Baixando do YouTube...";

    const formData = new FormData();
    if (selectedFile) {
        formData.append("file", selectedFile);
    } else {
        formData.append("youtube_url", youtubeUrl);
    }

    try {
        const res = await fetch("/chat/start", { method: "POST", body: formData });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        sessionId = data.session_id;
        uploadStep.hidden = true;
        chatStep.hidden = false;
        addSystemMessage("Transcrevendo o vídeo (local, grátis)... isso pode levar um tempinho.");
        pollStatus();
    } catch (err) {
        alert("Erro ao enviar o vídeo: " + err.message);
        startBtn.disabled = false;
        startBtn.textContent = "Começar a conversa";
    }
});

form.addEventListener("submit", async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !sessionId) return;

    input.value = "";
    sendBtn.disabled = true;

    try {
        const formData = new FormData();
        formData.append("text", text);
        const res = await fetch(`/chat/${sessionId}/message`, { method: "POST", body: formData });
        if (!res.ok) {
            const errText = await res.text();
            throw new Error(errText);
        }
        pollStatus();
    } catch (err) {
        addSystemMessage("Erro ao mandar a mensagem: " + err.message, true);
        sendBtn.disabled = false;
    }
});

function addBubble(role, text) {
    const div = document.createElement("div");
    div.className = "msg " + (role === "user" ? "user" : "assistant");
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addSystemMessage(text, isError) {
    const div = document.createElement("div");
    div.className = "msg system-error";
    if (!isError) div.style.opacity = "0.8";
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function syncDisplayHistory(history) {
    for (let i = renderedCount; i < history.length; i++) {
        addBubble(history[i].role, history[i].content);
    }
    renderedCount = history.length;
}

let polling = false;

function pollStatus() {
    if (polling) return;
    polling = true;

    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/chat/${sessionId}/status`);
            const data = await res.json();

            syncDisplayHistory(data.display_history || []);

            const busy = ["transcribing", "thinking", "rendering"].includes(data.status);
            sendBtn.disabled = busy;
            input.disabled = busy;

            if (busy) {
                turnProgress.hidden = false;
                turnProgressFill.style.width = (data.progress || 0) + "%";
                turnProgressMsg.textContent = data.message || "Processando...";
            } else {
                turnProgress.hidden = true;
            }

            if (data.status === "error") {
                clearInterval(interval);
                polling = false;
                addSystemMessage("⚠ " + data.error, true);
                return;
            }

            if (data.status === "ready" && renderedCount === 0) {
                clearInterval(interval);
                polling = false;
                addSystemMessage("Pronto! Me diga como você quer editar esse vídeo.");
                return;
            }

            if (data.status === "done" && data.files) {
                clearInterval(interval);
                polling = false;
                showResult(data.files);
            }

            if (data.status === "ready" && renderedCount > 0) {
                clearInterval(interval);
                polling = false;
            }
        } catch (err) {
            clearInterval(interval);
            polling = false;
            addSystemMessage("Perdi a conexão com o servidor: " + err.message, true);
        }
    }, 1200);
}

function showResult(files) {
    noResult.hidden = true;
    downloads.hidden = false;
    resultVideo.src = files.final + "?t=" + Date.now();
    document.getElementById("dl-final").href = files.final;
    document.getElementById("dl-srt").href = files.srt;
    document.getElementById("dl-transcript").href = files.transcript;
    document.getElementById("dl-fcpxml").href = files.fcpxml;
}

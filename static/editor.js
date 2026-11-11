/* Editor de vídeo por linha do tempo (várias faixas de vídeo/imagem e de áudio).
   O navegador só monta o "projeto" (JSON) e mostra uma prévia no canvas; quem
   renderiza o vídeo final é o servidor (FFmpeg) — ver pipeline/editor.py. */
(function () {
    "use strict";

    const $ = id => document.getElementById(id);
    const STORAGE_KEY = "video_magico_timeline_v2";
    const HEAD_W = 120;
    const MIN_DUR = 0.1;
    const IMAGE_DEFAULT_DUR = 5;
    const EPS = 0.001;

    const scrollEl = $("tl-scroll");
    const inner = $("tl-inner");
    const preview = $("preview");
    const pctx = preview.getContext("2d");
    const stageEl = document.querySelector(".preview-stage");

    const state = { assets: [], project: null, selectedId: null, playhead: 0, playing: false, zoom: 80 };
    let selectedIds = new Set();
    let selectedCaptions = new Set();
    let undoStack = [];
    let redoStack = [];
    let draggingAssetId = null;
    let idCounter = Date.now();
    let saveTimer = null;
    let playBase = 0;
    let playStart = 0;
    let rafId = null;
    let renderQueued = false;
    let activeTool = "select";

    const nid = prefix => prefix + (idCounter++).toString(36);
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

    // ---------- projeto ----------

    function mkTrack(type) {
        return { id: nid("t"), type, muted: false, hidden: false, clips: [] };
    }

    function emptyProject(width = 1920, height = 1080) {
        return { width, height, fps: 30, tracks: [mkTrack("video"), mkTrack("video"), mkTrack("audio"), mkTrack("audio")] };
    }

    function assetById(id) { return state.assets.find(a => a.id === id); }
    function assetOf(clip) { return assetById(clip.asset_id); }

    function findClip(id) {
        for (const track of state.project.tracks) {
            const clip = track.clips.find(c => c.id === id);
            if (clip) return { clip, track };
        }
        return null;
    }

    const selectedInfo = () => (state.selectedId ? findClip(state.selectedId) : null);
    const clipEnd = c => c.start + c.dur;

    function allClips() {
        return state.project.tracks.flatMap(track => track.clips.map(clip => ({ clip, track })));
    }

    function expandGroups(ids) {
        const all = allClips();
        const groups = new Set(all.filter(item => ids.has(item.clip.id) && item.clip.group_id).map(item => item.clip.group_id));
        return new Set(all.filter(item => ids.has(item.clip.id) || groups.has(item.clip.group_id)).map(item => item.clip.id));
    }

    function selectClips(ids, primary) {
        selectedIds = expandGroups(new Set(ids));
        state.selectedId = selectedIds.has(primary) ? primary : (selectedIds.values().next().value || null);
        refreshSelection();
    }

    function selectedItems() {
        return allClips().filter(item => selectedIds.has(item.clip.id));
    }

    function movingCaptions(items) {
        return (state.project.captions || []).filter(cue => selectedCaptions.has(cue)
            || items.some(({ clip }) => cue.start >= clip.start && cue.start < clipEnd(clip)));
    }

    function captionPositions(cues) {
        return cues.map(cue => ({ cue, start: cue.start, end: cue.end }));
    }

    function moveCaptions(positions, delta) {
        positions.forEach(({ cue, start, end }) => {
            cue.start = start + delta;
            cue.end = end + delta;
        });
        inner.querySelectorAll(".caption-cue").forEach(el => {
            const cue = (state.project.captions || [])[Number(el.dataset.index)];
            if (cue) el.style.left = `${cue.start * state.zoom}px`;
        });
    }

    function totalDuration() {
        let t = 0;
        state.project.tracks.forEach(tr => tr.clips.forEach(c => { t = Math.max(t, clipEnd(c)); }));
        return t;
    }

    function warnCaptionsPastEnd(captions) {
        if (captions.some(({ cue }) => cue.end > totalDuration() + EPS)) {
            toast("Parte da legenda está depois do fim da montagem e não aparecerá na exportação.", 6000);
        }
    }

    function canPlace(track, asset) {
        if (track.type === "video") return asset.kind === "video" || asset.kind === "image";
        return !!asset.has_audio;
    }

    function formatTime(s) {
        s = Math.max(0, s);
        const m = Math.floor(s / 60);
        const sec = (s % 60).toFixed(1).padStart(4, "0");
        return `${m}:${sec}`;
    }

    function toast(msg, ms = 3000) {
        const el = $("toast");
        el.textContent = msg;
        el.hidden = false;
        clearTimeout(toast.timer);
        toast.timer = setTimeout(() => { el.hidden = true; }, ms);
    }

    // ---------- histórico e persistência ----------

    const snap = () => JSON.stringify(state.project);

    function checkpoint(snapshot) {
        undoStack.push(snapshot || snap());
        if (undoStack.length > 80) undoStack.shift();
        redoStack = [];
        updateUndoButtons();
    }

    function restore(json) {
        state.project = JSON.parse(json);
        selectedCaptions.clear();
        selectedIds = new Set([...selectedIds].filter(id => findClip(id)));
        selectedIds = expandGroups(selectedIds);
        if (!selectedIds.has(state.selectedId)) state.selectedId = selectedIds.values().next().value || null;
        syncAspectSelect();
        changed();
    }

    function undo() {
        if (!undoStack.length) return;
        redoStack.push(snap());
        restore(undoStack.pop());
    }

    function redo() {
        if (!redoStack.length) return;
        undoStack.push(snap());
        restore(redoStack.pop());
    }

    function updateUndoButtons() {
        $("undo-btn").disabled = !undoStack.length;
        $("redo-btn").disabled = !redoStack.length;
    }

    function save() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => {
            try { localStorage.setItem(STORAGE_KEY, snap()); } catch (err) { /* sem armazenamento local */ }
        }, 300);
    }

    function loadSaved() {
        try {
            const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
            if (saved && Array.isArray(saved.tracks)) {
                saved.tracks.forEach(tr => { tr.clips = tr.clips.filter(c => assetById(c.asset_id)); });
                return saved;
            }
        } catch (err) { /* ignora */ }
        return null;
    }

    // ---------- biblioteca de mídia ----------

    const mediaList = $("media-drop");

    async function fetchAssets() {
        const res = await fetch("/editor/assets");
        state.assets = res.ok ? await res.json() : [];
    }

    async function uploadAsset(blob, name, design = "", replaceId = "") {
        const fd = new FormData();
        fd.append("file", blob, name);
        fd.append("design", design);
        fd.append("replace_id", replaceId);
        const res = await fetch("/editor/assets", { method: "POST", body: fd });
        if (!res.ok) {
            let detail = "falha no envio";
            try { detail = (await res.json()).detail || detail; } catch (err) { /* ignora */ }
            throw new Error(detail);
        }
        const asset = await res.json();
        const i = state.assets.findIndex(a => a.id === asset.id);
        if (i >= 0) state.assets[i] = asset; else state.assets.push(asset);
        renderMedia();
        if (i >= 0) changed();
        return asset;
    }

    async function importFiles(files) {
        for (const file of files) {
            toast(`Enviando ${file.name}...`, 60000);
            try {
                await uploadAsset(file, file.name);
            } catch (err) {
                toast(`${file.name}: ${err.message}`, 6000);
                continue;
            }
            toast(`${file.name} adicionado à biblioteca`);
        }
    }

    function renderMedia() {
        mediaList.querySelectorAll(".media-item").forEach(n => n.remove());
        $("media-empty").hidden = state.assets.length > 0;
        state.assets.forEach(a => {
            const item = document.createElement("div");
            item.className = "media-item";
            item.draggable = true;
            let thumb = "🎵";
            if (a.kind === "image") thumb = `<img src="${a.url}" alt="">`;
            else if (a.kind === "video") thumb = `<video src="${a.url}#t=0.5" preload="metadata" muted></video>`;
            const info = a.kind === "image" ? `${a.width}×${a.height}` : formatTime(a.duration);
            item.innerHTML = `<div class="media-thumb">${thumb}</div><div class="media-meta"><div class="n"></div><div class="d">${info}</div></div><div class="media-actions"></div>`;
            item.querySelector(".n").textContent = a.name;
            item.title = "Arraste pra linha do tempo (ou duplo clique pra adicionar no cursor)";
            const actions = item.querySelector(".media-actions");
            if (a.kind === "image") actions.appendChild(mkBtn("✎", "Editar imagem", () => openImageEditor(a)));
            actions.appendChild(mkBtn("🗑", "Remover da biblioteca", () => removeAsset(a)));
            item.addEventListener("dragstart", e => {
                draggingAssetId = a.id;
                e.dataTransfer.setData("application/x-asset", a.id);
                e.dataTransfer.effectAllowed = "copy";
            });
            item.addEventListener("dragend", () => { draggingAssetId = null; clearLaneHighlights(); });
            item.addEventListener("dblclick", () => addAssetToTimeline(a.id));
            mediaList.appendChild(item);
        });
    }

    function mkBtn(text, title, fn) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = text;
        b.title = title;
        b.addEventListener("click", e => { e.stopPropagation(); fn(); });
        return b;
    }

    async function removeAsset(asset) {
        const used = state.project.tracks.some(t => t.clips.some(c => c.asset_id === asset.id));
        if (!confirm(used ? "Essa mídia está na linha do tempo — remover também apaga os clipes dela. Continuar?" : "Remover essa mídia da biblioteca?")) return;
        checkpoint();
        state.project.tracks.forEach(t => { t.clips = t.clips.filter(c => c.asset_id !== asset.id); });
        state.assets = state.assets.filter(a => a.id !== asset.id);
        await fetch(`/editor/assets/${asset.id}`, { method: "DELETE" });
        renderMedia();
        changed();
    }

    $("import-btn").addEventListener("click", () => $("file-input").click());
    $("file-input").addEventListener("change", e => {
        const files = [...e.target.files];
        e.target.value = "";
        importFiles(files);
    });
    mediaList.addEventListener("dragover", e => {
        if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); mediaList.classList.add("dragover"); }
    });
    mediaList.addEventListener("dragleave", () => mediaList.classList.remove("dragover"));
    mediaList.addEventListener("drop", e => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault();
        mediaList.classList.remove("dragover");
        importFiles([...e.dataTransfer.files]);
    });

    // ---------- operações na linha do tempo ----------

    function fitStart(track, clipId, desired, dur) {
        const others = track.clips.filter(c => c.id !== clipId);
        const valid = s => s >= -EPS && others.every(o => s >= clipEnd(o) - EPS || s + dur <= o.start + EPS);
        desired = Math.max(0, desired);
        if (valid(desired)) return desired;
        const candidates = [0];
        others.forEach(o => { candidates.push(clipEnd(o), o.start - dur); });
        const ok = candidates.filter(valid).sort((a, b) => Math.abs(a - desired) - Math.abs(b - desired));
        return ok.length ? Math.max(0, ok[0]) : desired;
    }

    function canMoveItems(items, delta, ignoreSelected = true) {
        const ids = new Set(items.map(item => item.clip.id));
        return items.every(({ clip, track }) => {
            const start = clip.start + delta;
            return start >= -EPS && track.clips.every(other =>
                (ignoreSelected && ids.has(other.id)) ||
                start >= clipEnd(other) - EPS || start + clip.dur <= other.start + EPS);
        });
    }

    function addAssetToTimeline(assetId, trackId, start) {
        const asset = assetById(assetId);
        if (!asset) return;
        const tracks = state.project.tracks;
        let track = trackId ? tracks.find(t => t.id === trackId) : tracks.find(t => canPlace(t, asset));
        if (!track || !canPlace(track, asset)) {
            toast(asset.kind === "audio" ? "Áudio só entra em faixa de áudio." : "Essa mídia não cabe nessa faixa.");
            return;
        }
        checkpoint();
        const dur = asset.kind === "image" ? IMAGE_DEFAULT_DUR : Math.max(MIN_DUR, asset.duration);
        const clip = {
            id: nid("c"), asset_id: asset.id, start: 0, dur, in: 0,
            volume: 1, opacity: 1, scale: 1, x: 0.5, y: 0.5, fade_in: 0, fade_out: 0,
        };
        clip.start = fitStart(track, clip.id, start ?? state.playhead, dur);
        track.clips.push(clip);
        const ids = [clip.id];
        if (track.type === "video" && asset.kind === "video" && asset.has_audio) {
            ids.push(separateAudio(clip).id);
        }
        state.selectedId = clip.id;
        selectedIds = new Set(ids);
        selectedCaptions.clear();
        changed();
    }

    function separateAudio(clip) {
        let track = state.project.tracks.find(t => t.type === "audio"
            && Math.abs(fitStart(t, "", clip.start, clip.dur) - clip.start) < EPS);
        if (!track) {
            track = mkTrack("audio");
            state.project.tracks.push(track);
        }
        clip.group_id = clip.group_id || nid("g");
        clip.audio_disabled = true;
        const audio = { ...clip, id: nid("c") };
        delete audio.audio_disabled;
        track.clips.push(audio);
        return audio;
    }

    function splitAt(info, t, splitSelection = false) {
        const { clip } = info;
        const all = allClips();
        const items = splitSelection
            ? all.filter(item => selectedIds.has(item.clip.id) && t > item.clip.start + 0.05 && t < clipEnd(item.clip) - 0.05)
            : all.filter(item => item.clip.id === clip.id || (clip.group_id && item.clip.group_id === clip.group_id));
        if (!items.length) return toast("Coloque o cursor dentro dos clipes selecionados.");
        const groups = new Set(items.map(item => item.clip.group_id).filter(Boolean));
        if (all.some(item => groups.has(item.clip.group_id) && !items.includes(item))) {
            return toast("O corte precisa ficar dentro de todos os clipes vinculados, longe das pontas.");
        }
        if (items.some(({ clip: c }) => t <= c.start + 0.05 || t >= clipEnd(c) - 0.05)) {
            return toast("O corte precisa ficar dentro de todos os clipes vinculados, longe das pontas.");
        }
        checkpoint();
        const rightGroups = new Map([...groups].map(group => [group, nid("g")]));
        items.forEach(({ clip: c, track }) => {
            const right = Object.assign({}, c, {
                id: nid("c"), start: t, in: c.in + (t - c.start), dur: clipEnd(c) - t, fade_in: 0,
            });
            if (c.group_id) right.group_id = rightGroups.get(c.group_id);
            c.dur = t - c.start;
            c.fade_in = Math.min(c.fade_in, c.dur);
            c.fade_out = 0;
            right.fade_out = Math.min(right.fade_out, right.dur);
            track.clips.push(right);
        });
        changed();
    }

    function splitSelected() {
        const info = selectedInfo();
        if (!info) return toast("Selecione um clipe pra dividir.");
        splitAt(info, state.playhead, true);
    }

    function joinPrevious() {
        const info = selectedInfo();
        if (!info) return toast("Selecione o clipe que você quer encostar no anterior.");
        const { clip, track } = info;
        const previous = track.clips.filter(c => c.id !== clip.id && clipEnd(c) <= clip.start + EPS)
            .sort((a, b) => clipEnd(b) - clipEnd(a))[0];
        if (!previous) return toast("Não há clipe anterior nesta faixa.");
        const start = clipEnd(previous);
        if (Math.abs(clip.start - start) <= EPS) return toast("Os clipes já estão encostados.");
        const items = allClips().filter(item => item.clip.id === clip.id || (clip.group_id && item.clip.group_id === clip.group_id));
        const delta = start - clip.start;
        if (!canMoveItems(items, delta)) return toast("Não há espaço para mover todos os clipes vinculados.");
        const captions = captionPositions(movingCaptions(items));
        if (captions.some(item => item.start + delta < 0)) return toast("Não há espaço para mover as legendas antes do início.");
        checkpoint();
        items.forEach(item => { item.clip.start += delta; });
        moveCaptions(captions, delta);
        changed();
        if (captions.some(({ cue }) => cue.end > totalDuration() + EPS)) warnCaptionsPastEnd(captions);
        else toast("Clipes encostados; continuam editáveis.");
    }

    function duplicateSelected() {
        const items = selectedItems();
        if (!items.length) return;
        const delta = Math.max(...items.map(item => item.clip.dur));
        if (!canMoveItems(items, delta, false)) return toast("Não há espaço para duplicar os clipes selecionados.");
        checkpoint();
        const groups = new Map();
        const copies = items.map(({ clip, track }) => {
            const copy = { ...clip, id: nid("c"), start: clip.start + delta };
            if (clip.group_id) {
                if (!groups.has(clip.group_id)) groups.set(clip.group_id, nid("g"));
                copy.group_id = groups.get(clip.group_id);
            }
            track.clips.push(copy);
            return copy.id;
        });
        selectedIds = new Set(copies);
        selectedCaptions.clear();
        state.selectedId = copies[0];
        changed();
    }

    function deleteSelected() {
        if (!selectedIds.size && !selectedCaptions.size) return;
        checkpoint();
        state.project.tracks.forEach(track => { track.clips = track.clips.filter(c => !selectedIds.has(c.id)); });
        if (state.project.captions) state.project.captions = state.project.captions.filter(cue => !selectedCaptions.has(cue));
        selectedIds.clear();
        selectedCaptions.clear();
        state.selectedId = null;
        changed();
    }

    function addTrack(type) {
        checkpoint();
        const tracks = state.project.tracks;
        if (type === "video") {
            tracks.unshift(mkTrack("video"));
        } else {
            tracks.push(mkTrack("audio"));
        }
        changed();
    }

    function removeTrack(track) {
        if (track.clips.length && !confirm("Essa faixa tem clipes. Apagar a faixa e tudo nela?")) return;
        checkpoint();
        state.project.tracks = state.project.tracks.filter(t => t !== track);
        selectedIds = expandGroups(new Set([...selectedIds].filter(id => findClip(id))));
        if (!selectedIds.has(state.selectedId)) state.selectedId = selectedIds.values().next().value || null;
        changed();
    }

    // ---------- desenho da linha do tempo ----------

    let rulerLane = null;

    function trackLabel(track) {
        const same = state.project.tracks.filter(t => t.type === track.type);
        const idx = same.indexOf(track);
        return track.type === "video" ? `V${same.length - idx}` : `A${idx + 1}`;
    }

    function rulerStep() {
        const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
        return steps.find(s => s * state.zoom >= 70) || 600;
    }

    function renderTimeline() {
        const zoom = state.zoom;
        const captionEnd = (state.project.captions || []).reduce((end, cue) => Math.max(end, cue.end), 0);
        const seconds = Math.max(Math.max(totalDuration(), captionEnd) + 20, 60);
        const laneW = Math.max(seconds * zoom, scrollEl.clientWidth - HEAD_W);
        inner.style.width = (HEAD_W + laneW) + "px";
        inner.innerHTML = "";

        const ruler = document.createElement("div");
        ruler.className = "tl-ruler";
        ruler.innerHTML = `<div class="tl-corner"></div>`;
        rulerLane = document.createElement("div");
        rulerLane.className = "tl-ruler-lane";
        rulerLane.style.width = laneW + "px";
        const step = rulerStep();
        for (let t = 0; t * zoom < laneW; t += step) {
            const tick = document.createElement("div");
            tick.className = "tick";
            tick.style.left = t * zoom + "px";
            tick.textContent = formatTime(t).replace(/\.0$/, "");
            rulerLane.appendChild(tick);
            const half = document.createElement("div");
            half.className = "tick minor";
            half.style.left = (t + step / 2) * zoom + "px";
            rulerLane.appendChild(half);
        }
        rulerLane.addEventListener("pointerdown", startScrub);
        ruler.appendChild(rulerLane);
        inner.appendChild(ruler);

        inner.appendChild(buildCaptionRow(laneW));
        state.project.tracks.forEach(track => inner.appendChild(buildRow(track, laneW)));

        const ph = document.createElement("div");
        ph.className = "playhead";
        ph.id = "playhead";
        inner.appendChild(ph);
        updatePlayheadUI(false);
    }

    function buildCaptionRow(laneW) {
        const row = document.createElement("div");
        row.className = "tl-row caption-track";
        const head = document.createElement("div");
        head.className = "tl-head";
        const name = document.createElement("span");
        name.className = "name caption-track-name";
        name.textContent = "Legendas";
        head.appendChild(name);
        head.appendChild(mkBtn("✎", "Gerar ou revisar legendas", () => openCaptions()));
        row.appendChild(head);

        const lane = document.createElement("div");
        lane.className = "caption-lane";
        lane.style.width = laneW + "px";
        lane.addEventListener("pointerdown", e => {
            if (e.target === lane && e.button === 0 && activeTool === "select") startMarquee(e, lane);
        });
        const cues = state.project.captions || [];
        if (!cues.length) {
            const empty = document.createElement("button");
            empty.type = "button";
            empty.className = "caption-empty";
            empty.textContent = "+ Gerar legendas automáticas";
            empty.addEventListener("click", () => openCaptions());
            lane.appendChild(empty);
        }
        cues.forEach((cue, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "caption-cue" + (selectedCaptions.has(cue) ? " selected" : "");
            button.dataset.index = index;
            button.style.left = `${cue.start * state.zoom}px`;
            button.style.width = `${Math.max(4, (cue.end - cue.start) * state.zoom)}px`;
            button.textContent = cue.text || "(sem texto)";
            button.title = `${formatTime(cue.start)} – ${formatTime(cue.end)}: ${cue.text} — clique para editar; arraste para mover`;
            button.setAttribute("aria-label", `Editar legenda ${index + 1}: ${cue.text}`);
            let suppressClick = false;
            button.addEventListener("pointerdown", e => {
                if (e.button !== 0 || activeTool !== "select") return;
                e.stopPropagation();
                const additive = e.ctrlKey || e.metaKey || e.shiftKey;
                if (!selectedCaptions.has(cue)) {
                    if (!additive) { selectedIds.clear(); state.selectedId = null; selectedCaptions.clear(); }
                    selectedCaptions.add(cue);
                    refreshSelection();
                }
                suppressClick = additive;
                startCaptionDrag(e, () => { suppressClick = true; });
            });
            button.addEventListener("click", e => {
                if (suppressClick || e.ctrlKey || e.metaKey || e.shiftKey) { suppressClick = false; return; }
                pause();
                seek(cue.start);
                openCaptions(index);
            });
            lane.appendChild(button);
        });
        row.appendChild(lane);
        return row;
    }

    function buildRow(track, laneW) {
        const row = document.createElement("div");
        row.className = "tl-row";
        const head = document.createElement("div");
        head.className = "tl-head";
        const name = document.createElement("span");
        name.className = "name " + (track.type === "video" ? "v" : "a");
        name.textContent = trackLabel(track);
        head.appendChild(name);
        if (track.type === "video") {
            head.appendChild(toggleBtn("👁", "Mostrar/ocultar a camada", !track.hidden, () => { track.hidden = !track.hidden; }));
        }
        head.appendChild(toggleBtn("🔊", "Ligar/desligar o som da faixa", !track.muted, () => { track.muted = !track.muted; }));
        head.appendChild(mkBtn("✕", "Apagar faixa", () => removeTrack(track)));
        row.appendChild(head);

        const lane = document.createElement("div");
        lane.className = "tl-lane";
        lane.dataset.track = track.id;
        lane.style.width = laneW + "px";
        lane.addEventListener("pointerdown", e => {
            if (e.target !== lane) return;
            if (e.button !== 0) return;
            if (activeTool === "select") startMarquee(e, lane);
            else startScrub(e, lane);
        });
        lane.addEventListener("dragover", e => {
            const asset = draggingAssetId && assetById(draggingAssetId);
            if (!asset) return;
            e.preventDefault();
            const ok = canPlace(track, asset);
            e.dataTransfer.dropEffect = ok ? "copy" : "none";
            lane.classList.toggle("drop-ok", ok);
            lane.classList.toggle("drop-bad", !ok);
        });
        lane.addEventListener("dragleave", () => lane.classList.remove("drop-ok", "drop-bad"));
        lane.addEventListener("drop", e => {
            const id = e.dataTransfer.getData("application/x-asset");
            clearLaneHighlights();
            if (!id) return;
            e.preventDefault();
            const x = e.clientX - lane.getBoundingClientRect().left;
            addAssetToTimeline(id, track.id, Math.max(0, x / state.zoom));
        });
        track.clips.forEach(clip => lane.appendChild(buildClip(clip, track)));
        row.appendChild(lane);
        return row;
    }

    function toggleBtn(text, title, on, fn) {
        const b = mkBtn(text, title, () => { checkpoint(); fn(); changed(); });
        if (!on) b.style.opacity = "0.35";
        return b;
    }

    function clearLaneHighlights() {
        document.querySelectorAll(".tl-lane").forEach(l => l.classList.remove("drop-ok", "drop-bad"));
    }

    function buildClip(clip, track) {
        const asset = assetOf(clip);
        const el = document.createElement("div");
        const kind = track.type === "audio" ? "audio" : asset.kind;
        el.className = `clip ${kind}` + (selectedIds.has(clip.id) ? " selected" : "");
        el.dataset.id = clip.id;
        if (asset.kind === "image" && track.type === "video") {
            el.style.backgroundImage = `linear-gradient(rgba(60,30,90,.55), rgba(60,30,90,.55)), url("${asset.url}")`;
            el.style.backgroundSize = "cover";
        }
        el.innerHTML = '<canvas class="waveform" aria-hidden="true"></canvas><div class="handle l"></div><span class="label"></span><div class="handle r"></div>';
        el.querySelector(".label").textContent = asset.name;
        if (clip.group_id) el.querySelector(".label").textContent += " 🔗";
        if (asset.has_audio && (track.type === "audio" || !clip.audio_disabled)) drawWaveform(el, clip, asset);
        positionClip(el, clip);
        el.addEventListener("pointerdown", e => {
            if (e.button !== 0) return;
            e.stopPropagation();
            if (!selectedIds.has(clip.id)) {
                if (!e.ctrlKey && !e.metaKey && !e.shiftKey) selectedCaptions.clear();
                const ids = (e.ctrlKey || e.metaKey || e.shiftKey) ? [...selectedIds, clip.id] : [clip.id];
                selectClips(ids, clip.id);
            } else {
                state.selectedId = clip.id;
                refreshSelection();
            }
            if (activeTool === "blade") {
                const lane = el.parentElement;
                const t = Math.round(((e.clientX - lane.getBoundingClientRect().left) / state.zoom) * state.project.fps) / state.project.fps;
                seek(t);
                splitAt({ clip, track }, t);
                return;
            }
            const mode = e.target.classList.contains("l") ? "trimL" : e.target.classList.contains("r") ? "trimR" : "move";
            if (selectedIds.size > 1) startGroupDrag(e, clip, mode);
            else startClipDrag(e, clip, el, mode);
        });
        el.addEventListener("contextmenu", e => {
            e.preventDefault();
            if (!selectedIds.has(clip.id)) { selectedCaptions.clear(); selectClips([clip.id], clip.id); }
            showClipMenu(e.clientX, e.clientY);
        });
        return el;
    }

    function positionClip(el, clip) {
        el.style.left = clip.start * state.zoom + "px";
        el.style.width = Math.max(4, clip.dur * state.zoom) + "px";
    }

    function refreshSelection() {
        inner.querySelectorAll(".clip").forEach(el => el.classList.toggle("selected", selectedIds.has(el.dataset.id)));
        inner.querySelectorAll(".caption-cue").forEach(el => {
            el.classList.toggle("selected", selectedCaptions.has((state.project.captions || [])[Number(el.dataset.index)]));
        });
        updateInspector();
    }

    const waveformCache = new Map();

    function drawWaveform(el, clip, asset) {
        if (!waveformCache.has(asset.url)) {
            const request = fetch(`/editor/assets/${asset.id}/waveform?v=${asset.version || 0}`)
                .then(async res => {
                    if (!res.ok) {
                        const body = await res.json();
                        throw new Error(body.detail || "Falha ao gerar ondas de áudio.");
                    }
                    return res.json();
                })
                .catch(err => {
                    toast(`Ondas de ${asset.name}: ${err.message}`, 7000);
                    return null;
                });
            waveformCache.set(asset.url, request);
        }
        waveformCache.get(asset.url).then(data => {
            if (!data || !el.isConnected) return;
            const canvas = el.querySelector(".waveform");
            canvas.width = Math.max(1, Math.min(4096, Math.ceil(clip.dur * state.zoom)));
            canvas.height = 44;
            const ctx = canvas.getContext("2d");
            ctx.strokeStyle = "#b8f5d6";
            ctx.beginPath();
            for (let x = 0; x < canvas.width; x++) {
                const from = Math.floor((clip.in + clip.dur * x / canvas.width) * data.peaks_per_second);
                const to = Math.max(from + 1, Math.ceil((clip.in + clip.dur * (x + 1) / canvas.width) * data.peaks_per_second));
                let peak = 0;
                for (let i = from; i < Math.min(to, data.peaks.length); i++) peak = Math.max(peak, data.peaks[i]);
                const h = peak * 20;
                ctx.moveTo(x + 0.5, 22 - h);
                ctx.lineTo(x + 0.5, 22 + h);
            }
            ctx.stroke();
        });
    }

    function startMarquee(e, lane) {
        const x0 = e.clientX, y0 = e.clientY;
        const additive = e.ctrlKey || e.metaKey || e.shiftKey;
        const original = additive ? new Set(selectedIds) : new Set();
        const originalCaptions = additive ? new Set(selectedCaptions) : new Set();
        let box = null;
        const move = ev => {
            if (!box && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 4) return;
            if (!box) {
                box = document.createElement("div");
                box.className = "selection-box";
                document.body.appendChild(box);
            }
            const left = Math.min(x0, ev.clientX), right = Math.max(x0, ev.clientX);
            const top = Math.min(y0, ev.clientY), bottom = Math.max(y0, ev.clientY);
            Object.assign(box.style, { left: `${left}px`, top: `${top}px`, width: `${right-left}px`, height: `${bottom-top}px` });
            const ids = new Set(original);
            inner.querySelectorAll(".tl-lane .clip").forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.left < right && rect.right > left && rect.top < bottom && rect.bottom > top) ids.add(el.dataset.id);
            });
            selectedCaptions = new Set(originalCaptions);
            inner.querySelectorAll(".caption-cue").forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.left < right && rect.right > left && rect.top < bottom && rect.bottom > top) {
                    selectedCaptions.add(state.project.captions[Number(el.dataset.index)]);
                }
            });
            selectClips(ids);
        };
        const up = ev => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            if (box) box.remove();
            else {
                selectedCaptions = originalCaptions;
                selectClips(original);
                seek((ev.clientX - lane.getBoundingClientRect().left) / state.zoom);
            }
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    const clipMenu = $("clip-menu");
    function showClipMenu(x, y) {
        const items = selectedItems();
        const info = selectedInfo();
        $("separate-audio").disabled = !info || info.track.type !== "video"
            || !assetOf(info.clip)?.has_audio || !!info.clip.audio_disabled;
        $("group-clips").disabled = items.length < 2;
        $("ungroup-clips").disabled = !items.some(item => item.clip.group_id);
        clipMenu.hidden = false;
        clipMenu.style.left = `${Math.max(0, Math.min(x, window.innerWidth - clipMenu.offsetWidth))}px`;
        clipMenu.style.top = `${Math.max(0, Math.min(y, window.innerHeight - clipMenu.offsetHeight))}px`;
    }
    document.addEventListener("pointerdown", e => {
        if (!clipMenu.contains(e.target)) clipMenu.hidden = true;
    });
    $("separate-audio").addEventListener("click", () => {
        const info = selectedInfo();
        if (!info || info.track.type !== "video" || !assetOf(info.clip)?.has_audio || info.clip.audio_disabled) return;
        checkpoint();
        const audio = separateAudio(info.clip);
        selectedIds = expandGroups(new Set([info.clip.id, audio.id]));
        clipMenu.hidden = true;
        changed();
    });
    $("group-clips").addEventListener("click", () => {
        const items = selectedItems();
        if (items.length < 2) return;
        checkpoint();
        const group = nid("g");
        items.forEach(item => { item.clip.group_id = group; });
        clipMenu.hidden = true;
        changed();
    });
    $("ungroup-clips").addEventListener("click", () => {
        const items = selectedItems();
        if (!items.some(item => item.clip.group_id)) return;
        checkpoint();
        items.forEach(item => { delete item.clip.group_id; });
        selectedIds = new Set(state.selectedId ? [state.selectedId] : []);
        clipMenu.hidden = true;
        changed();
    });

    function startGroupDrag(e, anchor, mode) {
        const items = selectedItems().map(item => ({ ...item, original: { ...item.clip } }));
        const captions = mode === "move" ? captionPositions(movingCaptions(items)) : [];
        const startX = e.clientX, startY = e.clientY;
        const before = snap();
        let moved = false;
        if (mode !== "move" && items.some(item => Math.abs(item.clip.start - anchor.start) > EPS || Math.abs(clipEnd(item.clip) - clipEnd(anchor)) > EPS)) {
            toast("Para aparar juntos, selecione clipes com as mesmas pontas.");
            return;
        }
        const onMove = ev => {
            if (!moved && Math.hypot(ev.clientX - startX, ev.clientY - startY) < 3) return;
            if (!moved) { checkpoint(before); moved = true; }
            let delta = (ev.clientX - startX) / state.zoom;
            const previous = items.map(item => ({ ...item.clip }));
            items.forEach(item => Object.assign(item.clip, item.original));
            if (mode === "move") {
                delta = Math.max(delta, -Math.min(...items.map(item => item.original.start), ...captions.map(item => item.start)));
                if (!canMoveItems(items, delta)) {
                    items.forEach((item, index) => Object.assign(item.clip, previous[index]));
                    return;
                }
                items.forEach(item => { item.clip.start = item.original.start + delta; });
                moveCaptions(captions, delta);
            } else {
                const ids = new Set(items.map(item => item.clip.id));
                let min = -Infinity, max = Infinity;
                items.forEach(({ clip, track, original }) => {
                    const asset = assetOf(clip);
                    if (mode === "trimL") {
                        const prev = track.clips.filter(c => !ids.has(c.id) && clipEnd(c) <= original.start + EPS)
                            .reduce((v, c) => Math.max(v, clipEnd(c)), 0);
                        min = Math.max(min, prev - original.start, asset.kind === "image" ? -original.start : -original.in);
                        max = Math.min(max, original.dur - MIN_DUR);
                    } else {
                        const next = track.clips.filter(c => !ids.has(c.id) && c.start >= original.start + original.dur - EPS)
                            .reduce((v, c) => Math.min(v, c.start), Infinity);
                        min = Math.max(min, MIN_DUR - original.dur);
                        max = Math.min(max, next - original.start - original.dur,
                            asset.kind === "image" ? Infinity : asset.duration - original.in - original.dur);
                    }
                });
                delta = clamp(delta, min, max);
                items.forEach(({ clip, original }) => {
                    if (mode === "trimL") {
                        clip.start = original.start + delta;
                        clip.dur = original.dur - delta;
                        if (assetOf(clip).kind !== "image") clip.in = original.in + delta;
                    } else clip.dur = original.dur + delta;
                });
            }
            items.forEach(({ clip }) => {
                const element = inner.querySelector(`.clip[data-id="${clip.id}"]`);
                if (element) positionClip(element, clip);
            });
            updateInspector(true);
            queueRender();
        };
        const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            if (moved) { changed(); warnCaptionsPastEnd(captions); }
            else if (!e.ctrlKey && !e.metaKey && !e.shiftKey) selectClips([anchor.id], anchor.id);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    // ---------- arrastar / aparar clipes ----------

    function startCaptionDrag(e, suppressClick) {
        const items = selectedItems().map(item => ({ ...item, original: { ...item.clip } }));
        const captions = captionPositions(movingCaptions(items));
        const startX = e.clientX, startY = e.clientY;
        const before = snap();
        let moved = false;
        const move = ev => {
            if (!moved && Math.hypot(ev.clientX - startX, ev.clientY - startY) < 3) return;
            if (!moved) { checkpoint(before); moved = true; suppressClick(); }
            const delta = Math.max((ev.clientX - startX) / state.zoom,
                -Math.min(...items.map(item => item.original.start), ...captions.map(item => item.start)));
            const previous = items.map(item => item.clip.start);
            items.forEach(item => { item.clip.start = item.original.start; });
            if (!canMoveItems(items, delta)) {
                items.forEach((item, index) => { item.clip.start = previous[index]; });
                return;
            }
            items.forEach(item => {
                item.clip.start = item.original.start + delta;
                const el = inner.querySelector(`.clip[data-id="${item.clip.id}"]`);
                if (el) positionClip(el, item.clip);
            });
            moveCaptions(captions, delta);
            queueRender();
        };
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            if (moved) { changed(); warnCaptionsPastEnd(captions); }
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    function snapPoints(excludeId) {
        const pts = [0, state.playhead];
        state.project.tracks.forEach(t => t.clips.forEach(c => {
            if (c.id !== excludeId) pts.push(c.start, clipEnd(c));
        }));
        return pts;
    }

    function nearest(value, pts) {
        const threshold = 8 / state.zoom;
        let best = null;
        let bestD = threshold;
        pts.forEach(p => {
            const d = Math.abs(p - value);
            if (d < bestD) { bestD = d; best = p; }
        });
        return best;
    }

    function showSnap(t) {
        let line = document.getElementById("snap-line");
        if (t == null) { if (line) line.remove(); return; }
        if (!line) {
            line = document.createElement("div");
            line.id = "snap-line";
            line.className = "snap-line";
            inner.appendChild(line);
        }
        line.style.left = (HEAD_W + t * state.zoom) + "px";
    }

    function startClipDrag(e, clip, el, mode) {
        const asset = assetOf(clip);
        const info = findClip(clip.id);
        let track = info.track;
        const before = snap();
        const startX = e.clientX;
        const startY = e.clientY;
        const orig = { start: clip.start, dur: clip.dur, in: clip.in };
        const captions = mode === "move" ? captionPositions(movingCaptions([{ clip }])) : [];
        let moved = false;
        const pts = snapPoints(clip.id);

        const onMove = ev => {
            const dx = (ev.clientX - startX) / state.zoom;
            if (!moved && Math.abs(ev.clientX - startX) < 3 && Math.abs(ev.clientY - startY) < 3) return;
            if (!moved) { moved = true; checkpoint(before); }
            let snapped = null;

            if (mode === "move") {
                const minStart = Math.max(0, orig.start - Math.min(...captions.map(item => item.start), orig.start));
                let start = Math.max(minStart, orig.start + dx);
                const s1 = nearest(start, pts);
                const s2 = nearest(start + orig.dur, pts);
                if (s1 != null && (s2 == null || Math.abs(s1 - start) <= Math.abs(s2 - start - orig.dur))) {
                    start = s1; snapped = s1;
                } else if (s2 != null) {
                    start = s2 - orig.dur; snapped = s2;
                }
                start = Math.max(minStart, start);
                const lanes = document.elementsFromPoint(ev.clientX, ev.clientY).filter(n => n.classList && n.classList.contains("tl-lane"));
                const target = lanes.length ? state.project.tracks.find(t => t.id === lanes[0].dataset.track) : null;
                const destination = target && target !== track && canPlace(target, asset) ? target : track;
                const fitted = fitStart(destination, clip.id, start, clip.dur);
                if (fitted < minStart - EPS) { showSnap(null); return; }
                if (destination !== track) {
                    track.clips = track.clips.filter(c => c.id !== clip.id);
                    destination.clips.push(clip);
                    track = destination;
                    inner.querySelector(`.tl-lane[data-track="${destination.id}"]`).appendChild(el);
                }
                clip.start = fitted;
                if (Math.abs(clip.start - start) > EPS) snapped = null;
                moveCaptions(captions, clip.start - orig.start);
            } else if (mode === "trimL") {
                const others = track.clips.filter(c => c.id !== clip.id && clipEnd(c) <= orig.start + EPS);
                const prevEnd = others.reduce((m, c) => Math.max(m, clipEnd(c)), 0);
                const right = orig.start + orig.dur;
                let ns = orig.start + dx;
                const s = nearest(ns, pts);
                if (s != null) { ns = s; snapped = s; }
                const minStart = Math.max(prevEnd, asset.kind === "image" ? 0 : orig.start - orig.in);
                ns = clamp(ns, minStart, right - MIN_DUR);
                clip.start = ns;
                clip.dur = right - ns;
                clip.in = asset.kind === "image" ? 0 : orig.in + (ns - orig.start);
            } else if (mode === "trimR") {
                const next = track.clips.filter(c => c.id !== clip.id && c.start >= orig.start + orig.dur - EPS)
                    .reduce((m, c) => Math.min(m, c.start), Infinity);
                let ne = orig.start + orig.dur + dx;
                const s = nearest(ne, pts);
                if (s != null) { ne = s; snapped = s; }
                const maxEnd = Math.min(next, asset.kind === "image" ? Infinity : orig.start + (asset.duration - orig.in));
                ne = clamp(ne, orig.start + MIN_DUR, maxEnd);
                clip.dur = ne - orig.start;
            }
            positionClip(el, clip);
            showSnap(snapped);
            updateInspector(true);
            queueRender();
        };

        const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            showSnap(null);
            if (moved) { changed(); warnCaptionsPastEnd(captions); }
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    // ---------- cursor (playhead) ----------

    function startScrub(e, lane) {
        const laneEl = lane || rulerLane;
        const seekFromEvent = ev => seek((ev.clientX - laneEl.getBoundingClientRect().left) / state.zoom);
        seekFromEvent(e);
        const move = ev => seekFromEvent(ev);
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    function updatePlayheadUI(autoScroll) {
        const ph = $("playhead");
        if (ph) ph.style.left = (HEAD_W + state.playhead * state.zoom) + "px";
        $("time-label").textContent = `${formatTime(state.playhead)} / ${formatTime(totalDuration())}`;
        if (autoScroll) {
            const x = state.playhead * state.zoom;
            const viewW = scrollEl.clientWidth - HEAD_W;
            if (x < scrollEl.scrollLeft || x > scrollEl.scrollLeft + viewW - 20) {
                scrollEl.scrollLeft = Math.max(0, x - 40);
            }
        }
    }

    function seek(t) {
        state.playhead = Math.max(0, t);
        if (state.playing) { playBase = state.playhead; playStart = performance.now(); }
        syncMedia(state.playhead, state.playing);
        renderPreview();
        updatePlayheadUI(false);
    }

    // ---------- prévia (canvas + elementos de mídia) ----------

    const media = new Map();
    const imageCache = new Map();

    function imageEntry(url) {
        let e = imageCache.get(url);
        if (!e) {
            const img = new Image();
            e = { img, ready: false };
            img.onload = () => { e.ready = true; queueRender(); };
            img.src = url;
            imageCache.set(url, e);
        }
        return e;
    }

    function getMedia(clip, track) {
        const asset = assetOf(clip);
        if (!asset || asset.kind === "image") return null;
        let m = media.get(clip.id);
        if (m && m.url === asset.url && m.trackType === track.type) return m.el;
        if (m) { m.el.pause(); m.el.removeAttribute("src"); }
        const el = track.type === "video" ? document.createElement("video") : new Audio();
        el.preload = "auto";
        el.playsInline = true;
        el.src = asset.url;
        el.addEventListener("seeked", queueRender);
        el.addEventListener("loadeddata", queueRender);
        media.set(clip.id, { el, url: asset.url, trackType: track.type });
        return el;
    }

    function gcMedia() {
        const alive = new Set();
        state.project.tracks.forEach(t => t.clips.forEach(c => alive.add(c.id)));
        media.forEach((m, id) => {
            if (!alive.has(id)) { m.el.pause(); m.el.removeAttribute("src"); media.delete(id); }
        });
    }

    function fadeFactor(clip, t) {
        const lt = t - clip.start;
        let f = 1;
        if (clip.fade_in > 0) f *= clamp(lt / clip.fade_in, 0, 1);
        if (clip.fade_out > 0) f *= clamp((clip.dur - lt) / clip.fade_out, 0, 1);
        return clamp(f, 0, 1);
    }

    function queueRender() {
        if (renderQueued) return;
        renderQueued = true;
        requestAnimationFrame(() => { renderQueued = false; renderPreview(); });
    }

    function fitPreview() {
        const { width, height } = state.project;
        const maxW = stageEl.clientWidth - 20;
        const maxH = stageEl.clientHeight - 20;
        const k = Math.min(maxW / width, maxH / height);
        preview.style.width = Math.max(40, width * k) + "px";
        preview.style.height = Math.max(40, height * k) + "px";
    }

    function renderPreview() {
        const { width, height } = state.project;
        if (preview.width !== width || preview.height !== height) {
            preview.width = width;
            preview.height = height;
            fitPreview();
        }
        pctx.globalAlpha = 1;
        pctx.fillStyle = "#000";
        pctx.fillRect(0, 0, width, height);
        const t = state.playhead;

        [...state.project.tracks].reverse().forEach(track => {
            if (track.type !== "video" || track.hidden) return;
            track.clips.forEach(clip => {
                if (t < clip.start || t >= clipEnd(clip)) return;
                const asset = assetOf(clip);
                if (!asset) return;
                let src = null;
                let nw = asset.width;
                let nh = asset.height;
                if (asset.kind === "image") {
                    const e = imageEntry(asset.url);
                    if (e.ready) src = e.img;
                } else {
                    const el = getMedia(clip, track);
                    if (el && el.readyState >= 2) {
                        src = el;
                        nw = el.videoWidth || nw;
                        nh = el.videoHeight || nh;
                    }
                }
                if (!src || !nw || !nh) return;
                const fit = Math.min(width / nw, height / nh);
                const w = nw * fit * clip.scale;
                const h = nh * fit * clip.scale;
                pctx.globalAlpha = clamp(clip.opacity, 0, 1) * fadeFactor(clip, t);
                pctx.drawImage(src, clip.x * width - w / 2, clip.y * height - h / 2, w, h);
            });
        });
        pctx.globalAlpha = 1;
        const cues = (state.project.captions || []).filter(c => t >= c.start && t < c.end);
        const fontSize = Math.max(32, Math.floor(height * 0.045));
        pctx.font = `bold ${fontSize}px Arial`;
        pctx.textAlign = "center";
        pctx.textBaseline = "bottom";
        pctx.lineJoin = "round";
        pctx.lineWidth = 8;
        pctx.strokeStyle = "#000";
        pctx.fillStyle = "#fff";
        cues.forEach(cue => {
            const text = cue.text.toUpperCase();
            const y = height - Math.floor(height * 0.10);
            pctx.strokeText(text, width / 2, y, width - 120);
            pctx.fillText(text, width / 2, y, width - 120);
        });
    }

    function syncMedia(t, playing) {
        state.project.tracks.forEach(track => {
            track.clips.forEach(clip => {
                const asset = assetOf(clip);
                if (!asset || asset.kind === "image") return;
                if (track.type === "audio" && !asset.has_audio) return;
                const active = t >= clip.start && t < clipEnd(clip);
                const upcoming = clip.start > t && clip.start - t < 1;
                if (!active && !upcoming && !media.has(clip.id)) return;
                const el = getMedia(clip, track);
                if (!el) return;
                if (active) {
                    el.muted = track.muted || (track.type === "video" && !!clip.audio_disabled);
                    el.volume = clamp(clip.volume * fadeFactor(clip, t), 0, 1);
                    const target = clip.in + (t - clip.start);
                    if (playing) {
                        if (Math.abs(el.currentTime - target) > 0.3) el.currentTime = target;
                        if (el.paused) el.play().catch(() => {});
                    } else {
                        if (!el.paused) el.pause();
                        if (Math.abs(el.currentTime - target) > 0.03) el.currentTime = target;
                    }
                } else {
                    if (!el.paused) el.pause();
                    if (upcoming && Math.abs(el.currentTime - clip.in) > 0.1) el.currentTime = clip.in;
                }
            });
        });
    }

    function pauseAll() {
        media.forEach(m => { if (!m.el.paused) m.el.pause(); });
    }

    function play() {
        const total = totalDuration();
        if (total <= 0) return;
        if (state.playhead >= total - 0.05) state.playhead = 0;
        state.playing = true;
        playBase = state.playhead;
        playStart = performance.now();
        $("play-btn").textContent = "⏸";
        loop();
    }

    function pause() {
        state.playing = false;
        cancelAnimationFrame(rafId);
        pauseAll();
        $("play-btn").textContent = "▶";
    }

    function loop() {
        if (!state.playing) return;
        const t = playBase + (performance.now() - playStart) / 1000;
        const total = totalDuration();
        if (t >= total) {
            state.playhead = total;
            pause();
            renderPreview();
            updatePlayheadUI(false);
            return;
        }
        state.playhead = t;
        syncMedia(t, true);
        renderPreview();
        updatePlayheadUI(true);
        rafId = requestAnimationFrame(loop);
    }

    $("play-btn").addEventListener("click", () => (state.playing ? pause() : play()));
    $("start-btn").addEventListener("click", () => seek(0));

    // ---------- propriedades do clipe ----------

    const inspectorBody = $("inspector-body");
    const CONTROLS = [
        { id: "insp-volume", key: "volume", factor: 100, unit: "%" },
        { id: "insp-opacity", key: "opacity", factor: 100, unit: "%" },
        { id: "insp-scale", key: "scale", factor: 100, unit: "%" },
        { id: "insp-x", key: "x", factor: 100, unit: "%" },
        { id: "insp-y", key: "y", factor: 100, unit: "%" },
        { id: "insp-fade-in", key: "fade_in", factor: 1 },
        { id: "insp-fade-out", key: "fade_out", factor: 1 },
    ];
    let pendingSnap = null;

    function updateInspector(onlyDuration) {
        const info = selectedInfo();
        $("inspector-empty").hidden = !!info;
        inspectorBody.hidden = !info;
        if (!info) return;
        const { clip, track } = info;
        const asset = assetOf(clip);
        if (document.activeElement !== $("insp-dur")) $("insp-dur").value = clip.dur.toFixed(2);
        if (onlyDuration) return;

        $("insp-name").textContent = asset.name;
        $("edit-image-btn").hidden = asset.kind !== "image";
        inspectorBody.querySelector('[data-for="audio"]').hidden = !(track.type === "audio" || (asset.has_audio && !clip.audio_disabled));
        inspectorBody.querySelector('[data-for="visual"]').hidden = track.type !== "video";
        CONTROLS.forEach(c => {
            const el = $(c.id);
            if (document.activeElement === el) return;
            el.value = c.factor === 1 ? clip[c.key] : Math.round(clip[c.key] * c.factor);
            const val = $(c.id + "-val");
            if (val) val.textContent = Math.round(clip[c.key] * c.factor) + c.unit;
        });
    }

    inspectorBody.addEventListener("pointerdown", () => { pendingSnap = snap(); });
    inspectorBody.addEventListener("keydown", () => { if (!pendingSnap) pendingSnap = snap(); });

    CONTROLS.forEach(c => {
        $(c.id).addEventListener("input", e => {
            const info = selectedInfo();
            if (!info) return;
            if (pendingSnap) { checkpoint(pendingSnap); pendingSnap = null; }
            const raw = parseFloat(e.target.value);
            info.clip[c.key] = c.factor === 1 ? Math.max(0, raw || 0) : (raw || 0) / c.factor;
            const val = $(c.id + "-val");
            if (val) val.textContent = Math.round(info.clip[c.key] * c.factor) + c.unit;
            renderPreview();
            syncMedia(state.playhead, false);
            save();
        });
    });

    $("insp-dur").addEventListener("change", e => {
        const info = selectedInfo();
        if (!info) return;
        const { clip } = info;
        const items = allClips().filter(item => item.clip.id === clip.id || (clip.group_id && item.clip.group_id === clip.group_id));
        if (items.some(item => Math.abs(item.clip.start - clip.start) > EPS || Math.abs(item.clip.dur - clip.dur) > EPS)) {
            e.target.value = clip.dur.toFixed(2);
            return toast("Para alterar a duração juntos, os clipes vinculados precisam ter as mesmas pontas.");
        }
        let dur = Math.max(MIN_DUR, parseFloat(e.target.value) || clip.dur);
        const ids = new Set(items.map(item => item.clip.id));
        items.forEach(item => {
            const asset = assetOf(item.clip);
            if (asset.kind !== "image") dur = Math.min(dur, asset.duration - item.clip.in);
            const next = item.track.clips.filter(c => !ids.has(c.id) && c.start >= clipEnd(item.clip) - EPS)
                .reduce((m, c) => Math.min(m, c.start), Infinity);
            dur = Math.min(dur, next - item.clip.start);
        });
        checkpoint();
        items.forEach(item => { item.clip.dur = Math.max(MIN_DUR, dur); });
        changed();
    });

    $("reset-pos-btn").addEventListener("click", () => {
        const info = selectedInfo();
        if (!info) return;
        checkpoint();
        Object.assign(info.clip, { x: 0.5, y: 0.5, scale: 1 });
        changed();
    });
    $("split-btn").addEventListener("click", splitSelected);
    $("dup-btn").addEventListener("click", duplicateSelected);
    $("del-btn").addEventListener("click", deleteSelected);
    $("edit-image-btn").addEventListener("click", () => {
        const info = selectedInfo();
        if (info) openImageEditor(assetOf(info.clip));
    });

    // ---------- editor de imagem ----------

    function currentFrameBlob() {
        pause();
        renderPreview();
        return new Promise(resolve => preview.toBlob(resolve, "image/png"));
    }

    function openImageEditor(asset) {
        pause();
        const { width, height } = state.project;
        ImageEditor.open({
            asset: asset || null,
            preset: asset ? null : (width === height ? "1080x1080" : height > width ? "1080x1920" : "1280x720"),
            assets: () => state.assets,
            upload: uploadAsset,
            getFrame: currentFrameBlob,
            onSaved: () => {
                toast("Imagem salva na biblioteca ✔ — arraste pra linha do tempo");
                renderMedia();
                changed();
                ImageEditor.close();
            },
        });
    }

    $("cover-btn").addEventListener("click", () => openImageEditor(null));

    // ---------- topo: formato, projeto, exportar ----------

    function syncAspectSelect() {
        const sel = $("aspect-select");
        const key = `${state.project.width}x${state.project.height}`;
        if (![...sel.options].some(o => o.value === key)) {
            const opt = document.createElement("option");
            opt.value = key;
            opt.textContent = key.replace("x", "×");
            sel.appendChild(opt);
        }
        sel.value = key;
    }

    $("aspect-select").addEventListener("change", e => {
        const [w, h] = e.target.value.split("x").map(Number);
        checkpoint();
        state.project.width = w;
        state.project.height = h;
        changed();
    });

    $("new-project-btn").addEventListener("click", () => {
        if (!confirm("Limpar a linha do tempo e começar um projeto novo? (As mídias continuam na biblioteca.)")) return;
        pause();
        checkpoint();
        const { width, height } = state.project;
        state.project = emptyProject(width, height);
        state.selectedId = null;
        selectedIds.clear();
        selectedCaptions.clear();
        state.playhead = 0;
        changed();
    });

    $("undo-btn").addEventListener("click", undo);
    $("redo-btn").addEventListener("click", redo);
    $("add-video-track").addEventListener("click", () => addTrack("video"));
    $("add-audio-track").addEventListener("click", () => addTrack("audio"));
    $("zoom-range").addEventListener("input", e => {
        state.zoom = parseInt(e.target.value, 10);
        renderTimeline();
    });

    // ---------- ferramentas e transições ----------

    function setTool(tool) {
        activeTool = tool;
        ["select", "blade"].forEach(name => {
            const button = $(`tool-${name}`);
            button.classList.toggle("tool-active", name === tool);
            button.setAttribute("aria-pressed", String(name === tool));
        });
        inner.classList.toggle("blade-mode", tool === "blade");
        $("tool-hint").textContent = tool === "blade"
            ? "Lâmina: clique no ponto do clipe onde deseja cortar. V: voltar à seleção."
            : "Selecione e arraste os clipes. C: lâmina · V: seleção · S: dividir no cursor";
    }

    $("tool-select").addEventListener("click", () => setTool("select"));
    $("tool-blade").addEventListener("click", () => setTool("blade"));
    $("tool-join").addEventListener("click", joinPrevious);

    const transitionModal = $("transition-modal");
    let transitionPair = null;
    let transitionImporting = false;

    function transitionError(message) {
        $("transition-error").hidden = !message;
        $("transition-error").textContent = message;
    }

    function updateTransitionAssets(selectedId) {
        const select = $("transition-asset");
        select.replaceChildren();
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Selecione um vídeo de efeito...";
        select.appendChild(placeholder);
        state.assets.filter(a => a.kind === "video" && a.duration >= MIN_DUR).forEach(asset => {
            const option = document.createElement("option");
            option.value = asset.id;
            option.textContent = `${asset.name} (${formatTime(asset.duration)})`;
            select.appendChild(option);
        });
        select.value = selectedId || "";
    }

    function updateTransitionKind() {
        const overlay = $("transition-kind").value === "overlay";
        $("transition-fade-settings").hidden = overlay;
        $("transition-overlay-settings").hidden = !overlay;
        transitionError("");
    }

    function transitionClips() {
        if (!transitionPair) return null;
        const first = findClip(transitionPair.first);
        const second = findClip(transitionPair.second);
        if (!first || !second || first.track !== second.track || first.track.type !== "video"
            || Math.abs(clipEnd(first.clip) - second.clip.start) > EPS) return null;
        return { first: first.clip, second: second.clip };
    }

    $("tool-transition").addEventListener("click", () => {
        const info = selectedInfo();
        if (!info || info.track.type !== "video") return toast("Selecione o primeiro clipe de vídeo/imagem para criar uma transição.");
        const next = info.track.clips.filter(c => c.id !== info.clip.id && c.start >= clipEnd(info.clip) - EPS)
            .sort((a, b) => a.start - b.start)[0];
        if (!next || Math.abs(next.start - clipEnd(info.clip)) > EPS) {
            return toast("Encoste o próximo clipe nesta mesma faixa antes de adicionar uma transição.");
        }
        transitionPair = { first: info.clip.id, second: next.id };
        $("transition-pair").textContent = `${assetOf(info.clip).name} → ${assetOf(next).name}`;
        $("transition-kind").value = "both";
        updateTransitionAssets();
        updateTransitionKind();
        transitionModal.hidden = false;
    });

    $("transition-kind").addEventListener("change", updateTransitionKind);
    $("transition-close").addEventListener("click", () => {
        if (!transitionImporting) transitionModal.hidden = true;
    });
    $("transition-import").addEventListener("click", () => $("transition-file").click());
    $("transition-file").addEventListener("change", async e => {
        const file = e.target.files[0];
        e.target.value = "";
        if (!file) return;
        transitionImporting = true;
        $("transition-import").disabled = true;
        $("transition-apply").disabled = true;
        $("transition-close").disabled = true;
        transitionError("");
        try {
            const asset = await uploadAsset(file, file.name);
            if (asset.kind !== "video" || asset.duration < MIN_DUR) {
                throw new Error("O arquivo foi importado, mas não é um vídeo de efeito válido.");
            }
            updateTransitionAssets(asset.id);
        } catch (err) {
            transitionError(`Não foi possível usar o efeito: ${err.message}`);
        } finally {
            transitionImporting = false;
            $("transition-import").disabled = false;
            $("transition-apply").disabled = false;
            $("transition-close").disabled = false;
        }
    });

    $("transition-apply").addEventListener("click", () => {
        const clips = transitionClips();
        if (!clips) return transitionError("Os clipes mudaram ou não estão mais encostados. Feche e selecione a junção novamente.");
        const { first, second } = clips;
        const kind = $("transition-kind").value;
        if (kind === "overlay") {
            const asset = assetById($("transition-asset").value);
            if (!asset || asset.kind !== "video" || asset.duration < MIN_DUR) {
                return transitionError("Selecione ou importe um vídeo de efeito válido.");
            }
            const half = Math.min(asset.duration / 2, first.dur, second.dur);
            if (half < MIN_DUR / 2) return transitionError("Os clipes são curtos demais para este efeito.");
            checkpoint();
            const track = mkTrack("video");
            const clip = {
                id: nid("c"), asset_id: asset.id, start: second.start - half, dur: half * 2,
                in: Math.max(0, asset.duration / 2 - half), volume: 0, opacity: 1,
                scale: 1, x: 0.5, y: 0.5, fade_in: 0, fade_out: 0,
            };
            track.clips.push(clip);
            state.project.tracks.unshift(track);
            state.selectedId = clip.id;
            selectedIds = new Set([clip.id]);
        } else {
            const duration = Number($("transition-duration").value);
            if (!Number.isFinite(duration) || duration < 0.05 || duration > 10) {
                return transitionError("Informe uma duração entre 0,05 e 10 segundos.");
            }
            if ((kind === "both" || kind === "out") && duration > first.dur
                || (kind === "both" || kind === "in") && duration > second.dur) {
                return transitionError("A duração do fade não pode ser maior que a do clipe.");
            }
            checkpoint();
            if (kind === "both" || kind === "out") first.fade_out = duration;
            if (kind === "both" || kind === "in") second.fade_in = duration;
            allClips().forEach(({ clip, track }) => {
                if (track.type !== "audio" || !clip.group_id) return;
                if ((kind === "both" || kind === "out") && clip.group_id === first.group_id) clip.fade_out = Math.min(duration, clip.dur);
                if ((kind === "both" || kind === "in") && clip.group_id === second.group_id) clip.fade_in = Math.min(duration, clip.dur);
            });
        }
        transitionModal.hidden = true;
        setTool("select");
        changed();
        toast(kind === "overlay" ? "Efeito adicionado em uma nova faixa." : "Transição aplicada aos clipes.");
    });

    // ---------- legendas automáticas ----------

    const captionsModal = $("captions-modal");
    let captionJobRunning = false;

    function audioSignature() {
        return JSON.stringify({
            duration: totalDuration(),
            tracks: state.project.tracks.map(track => ({
                type: track.type, muted: track.muted,
                clips: track.clips.filter(clip => assetOf(clip)?.has_audio && !(track.type === "video" && clip.audio_disabled)).map(clip => ({
                    asset: clip.asset_id, version: assetOf(clip).version,
                    start: clip.start, dur: clip.dur, in: clip.in, volume: clip.volume,
                    fade_in: clip.fade_in, fade_out: clip.fade_out,
                })),
            })),
        });
    }

    function captionsStale() {
        return (state.project.captions || []).length > 0
            && state.project.captionAudioSignature !== audioSignature();
    }

    function renderCaptions() {
        const list = $("captions-list");
        list.replaceChildren();
        const cues = state.project.captions || [];
        $("captions-clear").disabled = captionJobRunning || !cues.length;
        $("captions-generate").disabled = captionJobRunning;
        cues.forEach((cue, index) => {
            const row = document.createElement("div");
            row.className = "caption-row";
            const time = document.createElement("span");
            time.textContent = `${formatTime(cue.start)} – ${formatTime(cue.end)}`;
            const input = document.createElement("input");
            input.value = cue.text;
            input.setAttribute("aria-label", `Texto da legenda ${index + 1}`);
            input.disabled = captionJobRunning;
            input.addEventListener("change", () => {
                if (cue.text === input.value.trim()) return;
                checkpoint();
                cue.text = input.value.trim();
                changed();
            });
            const remove = mkBtn("✕", "Excluir legenda", () => {
                checkpoint();
                selectedCaptions.delete(cue);
                state.project.captions.splice(index, 1);
                changed();
                renderCaptions();
            });
            remove.disabled = captionJobRunning;
            row.append(time, input, remove);
            list.appendChild(row);
        });
        if (!captionJobRunning) {
            $("captions-status").textContent = captionsStale()
                ? "O áudio da montagem mudou. Confira a sincronização das legendas ou gere-as novamente."
                : cues.length ? `${cues.length} legenda(s). Clique no texto para corrigir.` : "Nenhuma legenda gerada.";
        }
    }

    function openCaptions(index) {
        captionsModal.hidden = false;
        renderCaptions();
        if (index !== undefined) {
            const input = $("captions-list").querySelectorAll("input")[index];
            if (input) {
                input.focus();
                input.select();
                input.scrollIntoView({ block: "nearest" });
            }
        }
    }

    $("captions-btn").addEventListener("click", () => openCaptions());
    $("captions-close").addEventListener("click", () => { captionsModal.hidden = true; });
    $("captions-clear").addEventListener("click", () => {
        if (!confirm("Remover todas as legendas deste projeto?")) return;
        checkpoint();
        selectedCaptions.clear();
        state.project.captions = [];
        delete state.project.captionAudioSignature;
        changed();
        renderCaptions();
    });
    $("captions-generate").addEventListener("click", async () => {
        if (totalDuration() <= 0) {
            $("captions-status").textContent = "Adicione um vídeo ou áudio à linha do tempo.";
            return;
        }
        if ((state.project.captions || []).length && !confirm("Substituir as legendas existentes?")) return;
        const signature = audioSignature();
        captionJobRunning = true;
        renderCaptions();
        $("captions-status").textContent = "Preparando áudio...";
        try {
            const response = await fetch("/editor/captions", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: snap(),
            });
            if (!response.ok) throw new Error((await response.json()).detail || "Falha ao iniciar a legendagem.");
            const { job_id } = await response.json();
            let job;
            do {
                await new Promise(resolve => setTimeout(resolve, 1000));
                const status = await fetch(`/editor/captions/${job_id}`);
                if (!status.ok) throw new Error("Não foi possível consultar a legendagem.");
                job = await status.json();
                $("captions-status").textContent = job.message || "Processando...";
            } while (job.status === "queued" || job.status === "processing");
            if (job.status !== "done") throw new Error(job.error || "Erro ao gerar legendas.");
            if (signature !== audioSignature()) throw new Error("A montagem mudou durante a transcrição. Gere as legendas novamente.");
            if (!job.captions.length) throw new Error("Nenhuma fala foi encontrada no áudio. As legendas anteriores foram preservadas.");
            checkpoint();
            selectedCaptions.clear();
            state.project.captions = job.captions;
            state.project.captionAudioSignature = signature;
            changed();
            captionJobRunning = false;
            renderCaptions();
        } catch (err) {
            captionJobRunning = false;
            renderCaptions();
            $("captions-status").textContent = err.message;
        }
    });

    const exportModal = $("export-modal");

    $("export-btn").addEventListener("click", async () => {
        pause();
        if (totalDuration() <= 0) return toast("A linha do tempo está vazia.");
        if (captionsStale() && !confirm("O áudio da montagem mudou depois da geração das legendas; elas podem estar fora de sincronia. Exportar mesmo assim?")) return;
        exportModal.hidden = false;
        $("export-progress").hidden = false;
        $("export-result").hidden = true;
        $("export-error").hidden = true;
        $("export-progress-fill").style.width = "2%";
        $("export-progress-msg").textContent = "Enviando o projeto...";
        try {
            const res = await fetch("/editor/export", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: snap(),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "falha ao iniciar a exportação");
            pollExport((await res.json()).job_id);
        } catch (err) {
            showExportError(err.message);
        }
    });

    function showExportError(msg) {
        $("export-progress").hidden = true;
        $("export-error").hidden = false;
        $("export-error").textContent = msg;
    }

    async function pollExport(jobId) {
        try {
            const res = await fetch(`/editor/status/${jobId}`);
            const job = await res.json();
            $("export-progress-fill").style.width = (job.progress || 0) + "%";
            $("export-progress-msg").textContent = job.message || "Processando...";
            if (job.status === "done") {
                $("export-progress").hidden = true;
                $("export-result").hidden = false;
                $("result-video").src = job.video_url;
                $("dl-result").href = job.video_url;
                return;
            }
            if (job.status === "error") return showExportError(job.error || "Erro ao exportar.");
        } catch (err) { /* tenta de novo */ }
        setTimeout(() => pollExport(jobId), 1000);
    }

    $("export-close").addEventListener("click", () => {
        exportModal.hidden = true;
        $("result-video").pause();
    });

    // ---------- atalhos ----------

    document.addEventListener("keydown", e => {
        if (ImageEditor.isOpen() || !exportModal.hidden || !captionsModal.hidden || !transitionModal.hidden) return;
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)
            && document.activeElement.type !== "range";
        if (typing) return;
        const key = e.key.toLowerCase();
        if ((e.ctrlKey || e.metaKey) && key === "z") {
            e.preventDefault();
            e.shiftKey ? redo() : undo();
        } else if ((e.ctrlKey || e.metaKey) && key === "y") {
            e.preventDefault();
            redo();
        } else if (e.key === " ") {
            e.preventDefault();
            state.playing ? pause() : play();
        } else if (key === "s" && !e.ctrlKey && !e.metaKey) {
            splitSelected();
        } else if (key === "c" && !e.ctrlKey && !e.metaKey && !e.altKey) {
            setTool("blade");
        } else if (key === "v" && !e.ctrlKey && !e.metaKey && !e.altKey) {
            setTool("select");
        } else if (e.key === "Delete" || e.key === "Backspace") {
            e.preventDefault();
            deleteSelected();
        } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            seek(state.playhead - (e.shiftKey ? 1 : 1 / state.project.fps));
        } else if (e.key === "ArrowRight") {
            e.preventDefault();
            seek(state.playhead + (e.shiftKey ? 1 : 1 / state.project.fps));
        } else if (e.key === "Home") {
            seek(0);
        }
    });

    window.addEventListener("resize", () => {
        if (!state.project) return;
        fitPreview();
        renderTimeline();
    });

    // ---------- atualização geral ----------

    function changed() {
        renderTimeline();
        gcMedia();
        updateInspector();
        syncMedia(state.playhead, state.playing);
        renderPreview();
        updateUndoButtons();
        save();
    }

    async function init() {
        try { await fetchAssets(); } catch (err) { state.assets = []; }
        state.project = loadSaved() || emptyProject();
        state.zoom = parseInt($("zoom-range").value, 10);
        syncAspectSelect();
        renderMedia();
        fitPreview();
        changed();
        fitPreview();
    }

    init();
})();

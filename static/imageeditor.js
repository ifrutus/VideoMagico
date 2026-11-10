/* Editor de imagem em camadas (capas, imagens de referência, setas, textos...).
   Tudo roda no navegador (canvas); ao salvar vira um PNG na biblioteca do
   editor de vídeo, junto com o "design" (camadas) pra dar pra reabrir e
   editar depois. */
(function () {
    "use strict";

    const $ = id => document.getElementById(id);
    const modal = $("img-modal");
    const canvas = $("ie-canvas");
    const ctx = canvas.getContext("2d");
    const stage = $("ie-stage");
    const layersEl = $("ie-layers");
    const propsEl = $("ie-props");
    const presetSel = $("ie-preset");
    const bgInput = $("ie-bg");
    const transparentChk = $("ie-transparent");
    const addAssetSel = $("ie-add-asset");

    const FONTS = ["Arial", "Impact", "Segoe UI", "Verdana", "Trebuchet MS", "Georgia", "Times New Roman", "Courier New", "Comic Sans MS"];
    const FILTER_DEFAULTS = { brightness: 100, contrast: 100, saturate: 100, blur: 0, grayscale: 0, sepia: 0, hue: 0 };

    let doc = null;
    let opts = null;
    let selectedId = null;
    let history = [];
    let drag = null;
    let pendingSnap = null;
    let nextId = 1;
    const images = new Map();

    // ---------- util ----------

    function snapshot() {
        return JSON.stringify(doc);
    }

    function pushHistory(snap) {
        history.push(snap || snapshot());
        if (history.length > 60) history.shift();
    }

    function undo() {
        if (!history.length) return;
        doc = JSON.parse(history.pop());
        if (!doc.layers.find(l => l.id === selectedId)) selectedId = null;
        syncDocControls();
        refreshAll();
    }

    function getPath(obj, path) {
        return path.split(".").reduce((o, k) => (o ? o[k] : undefined), obj);
    }

    function setPath(obj, path, value) {
        const keys = path.split(".");
        const last = keys.pop();
        const target = keys.reduce((o, k) => o[k], obj);
        target[last] = value;
    }

    function selected() {
        return doc.layers.find(l => l.id === selectedId) || null;
    }

    function uid() {
        return "L" + (nextId++);
    }

    function assetById(id) {
        return opts.assets().find(a => a.id === id);
    }

    function loadImage(url) {
        let entry = images.get(url);
        if (!entry) {
            const img = new Image();
            entry = { img, ready: false };
            img.onload = () => { entry.ready = true; render(true); };
            img.src = url;
            images.set(url, entry);
        }
        return entry;
    }

    // ---------- medidas e desenho ----------

    function fontString(L) {
        return `${L.italic ? "italic " : ""}${L.bold ? "bold " : ""}${L.size}px "${L.font}", sans-serif`;
    }

    function textMetrics(L) {
        ctx.save();
        ctx.font = fontString(L);
        const lines = String(L.text || "").split("\n");
        const lineH = L.size * 1.2;
        const w = Math.max(10, ...lines.map(t => ctx.measureText(t).width));
        ctx.restore();
        return { lines, lineH, w, h: lineH * lines.length };
    }

    function layerSize(L) {
        if (L.type === "text") {
            const m = textMetrics(L);
            const pad = L.bgOn ? L.size * 0.3 : L.strokeW;
            return { w: m.w + pad * 2, h: m.h + pad * 2 };
        }
        if (L.type === "arrow") return { w: L.w, h: Math.max(L.thick * 4, 20) };
        return { w: L.w, h: L.h };
    }

    function filterString(f) {
        return `brightness(${f.brightness}%) contrast(${f.contrast}%) saturate(${f.saturate}%) blur(${f.blur}px) grayscale(${f.grayscale}%) sepia(${f.sepia}%) hue-rotate(${f.hue}deg)`;
    }

    function drawLayer(c, L) {
        c.save();
        c.translate(L.x, L.y);
        c.rotate(L.rot * Math.PI / 180);
        c.globalAlpha = L.opacity / 100;

        if (L.type === "image") {
            const a = assetById(L.assetId);
            if (a) {
                const entry = loadImage(a.url);
                if (entry.ready) {
                    c.filter = filterString(L.f);
                    if (L.flip) c.scale(-1, 1);
                    c.drawImage(entry.img, -L.w / 2, -L.h / 2, L.w, L.h);
                }
            }
        } else if (L.type === "text") {
            const m = textMetrics(L);
            const sz = layerSize(L);
            if (L.bgOn) {
                c.fillStyle = L.bg;
                c.fillRect(-sz.w / 2, -sz.h / 2, sz.w, sz.h);
            }
            c.font = fontString(L);
            c.textAlign = "center";
            c.textBaseline = "middle";
            c.lineJoin = "round";
            if (L.shadow) {
                c.shadowColor = "rgba(0,0,0,0.75)";
                c.shadowBlur = L.size * 0.15;
                c.shadowOffsetX = L.size * 0.05;
                c.shadowOffsetY = L.size * 0.05;
            }
            m.lines.forEach((line, i) => {
                const y = (i - (m.lines.length - 1) / 2) * m.lineH;
                if (L.strokeW > 0) {
                    c.strokeStyle = L.stroke;
                    c.lineWidth = L.strokeW * 2;
                    c.strokeText(line, 0, y);
                }
                c.fillStyle = L.color;
                c.fillText(line, 0, y);
            });
        } else if (L.type === "rect" || L.type === "ellipse") {
            c.beginPath();
            if (L.type === "ellipse") {
                c.ellipse(0, 0, Math.abs(L.w) / 2, Math.abs(L.h) / 2, 0, 0, Math.PI * 2);
            } else if (L.radius > 0 && c.roundRect) {
                c.roundRect(-L.w / 2, -L.h / 2, L.w, L.h, L.radius);
            } else {
                c.rect(-L.w / 2, -L.h / 2, L.w, L.h);
            }
            if (L.fillOn) { c.fillStyle = L.fill; c.fill(); }
            if (L.strokeW > 0) { c.strokeStyle = L.stroke; c.lineWidth = L.strokeW; c.stroke(); }
        } else if (L.type === "arrow") {
            const head = L.thick * 3.5;
            c.strokeStyle = L.color;
            c.fillStyle = L.color;
            c.lineWidth = L.thick;
            c.lineCap = "round";
            c.beginPath();
            c.moveTo(-L.w / 2, 0);
            c.lineTo(L.w / 2 - head, 0);
            c.stroke();
            c.beginPath();
            c.moveTo(L.w / 2, 0);
            c.lineTo(L.w / 2 - head, -head * 0.7);
            c.lineTo(L.w / 2 - head, head * 0.7);
            c.closePath();
            c.fill();
        }
        c.restore();
    }

    function uiScale() {
        const rect = canvas.getBoundingClientRect();
        return rect.width ? canvas.width / rect.width : 1;
    }

    function drawSelection(L) {
        const s = uiScale();
        const { w, h } = layerSize(L);
        ctx.save();
        ctx.translate(L.x, L.y);
        ctx.rotate(L.rot * Math.PI / 180);
        ctx.strokeStyle = "#6ee7a8";
        ctx.lineWidth = 2 * s;
        ctx.setLineDash([6 * s, 4 * s]);
        ctx.strokeRect(-w / 2, -h / 2, w, h);
        ctx.setLineDash([]);
        ctx.fillStyle = "#6ee7a8";
        const hs = 12 * s;
        ctx.fillRect(w / 2 - hs / 2, h / 2 - hs / 2, hs, hs);
        ctx.beginPath();
        ctx.moveTo(0, -h / 2);
        ctx.lineTo(0, -h / 2 - 28 * s);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(0, -h / 2 - 28 * s, 7 * s, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    }

    function paint(c, withUI) {
        c.clearRect(0, 0, doc.width, doc.height);
        if (!doc.transparent) {
            c.fillStyle = doc.bg;
            c.fillRect(0, 0, doc.width, doc.height);
        }
        doc.layers.forEach(L => drawLayer(c, L));
        if (withUI) {
            const L = selected();
            if (L) drawSelection(L);
        }
    }

    function render(withUI = true) {
        if (!doc) return;
        if (canvas.width !== doc.width) canvas.width = doc.width;
        if (canvas.height !== doc.height) canvas.height = doc.height;
        paint(ctx, withUI);
    }

    function fitCanvas() {
        if (!doc) return;
        const maxW = stage.clientWidth - 28;
        const maxH = stage.clientHeight - 28;
        const k = Math.min(maxW / doc.width, maxH / doc.height, 1);
        canvas.style.width = Math.max(50, doc.width * k) + "px";
        canvas.style.height = Math.max(50, doc.height * k) + "px";
    }

    // ---------- camadas ----------

    function baseLayer(type, extra) {
        return Object.assign({ id: uid(), type, x: doc.width / 2, y: doc.height / 2, rot: 0, opacity: 100 }, extra);
    }

    function addLayer(L) {
        pushHistory();
        doc.layers.push(L);
        selectedId = L.id;
        refreshAll();
    }

    function addByType(type) {
        const base = Math.min(doc.width, doc.height);
        if (type === "text") {
            addLayer(baseLayer("text", {
                text: "Seu texto aqui", font: "Impact", size: Math.round(base * 0.12), color: "#ffffff",
                bold: false, italic: false, stroke: "#000000", strokeW: Math.round(base * 0.008),
                shadow: true, bgOn: false, bg: "#000000",
            }));
        } else if (type === "rect" || type === "ellipse") {
            addLayer(baseLayer(type, {
                w: base * 0.4, h: base * 0.25, fillOn: true, fill: "#ffd24d", stroke: "#000000",
                strokeW: 0, radius: 0,
            }));
        } else if (type === "arrow") {
            addLayer(baseLayer("arrow", { w: base * 0.3, thick: Math.round(base * 0.02), color: "#ff3b3b" }));
        }
    }

    function addImageLayer(asset) {
        const aw = asset.width || 800;
        const ah = asset.height || 600;
        const k = Math.min(doc.width / aw, doc.height / ah, 1);
        addLayer(baseLayer("image", {
            assetId: asset.id, w: aw * k, h: ah * k, flip: false, f: Object.assign({}, FILTER_DEFAULTS),
        }));
    }

    function layerTitle(L) {
        if (L.type === "text") return "T  " + String(L.text).split("\n")[0].slice(0, 22);
        if (L.type === "image") {
            const a = assetById(L.assetId);
            return "🖼  " + (a ? a.name : "imagem");
        }
        return { rect: "▭  Retângulo", ellipse: "◯  Elipse", arrow: "➜  Seta" }[L.type];
    }

    function renderLayerList() {
        layersEl.innerHTML = "";
        [...doc.layers].reverse().forEach(L => {
            const li = document.createElement("li");
            if (L.id === selectedId) li.classList.add("sel");
            li.innerHTML = `<span class="t"></span><button data-a="up" title="Trazer pra frente">▲</button><button data-a="down" title="Enviar pra trás">▼</button><button data-a="dup" title="Duplicar">⧉</button><button data-a="del" title="Excluir">✕</button>`;
            li.querySelector(".t").textContent = layerTitle(L);
            li.addEventListener("click", e => {
                const act = e.target.dataset && e.target.dataset.a;
                if (act) {
                    layerAction(L, act);
                    return;
                }
                selectedId = L.id;
                refreshAll();
            });
            layersEl.appendChild(li);
        });
    }

    function layerAction(L, act) {
        pushHistory();
        const i = doc.layers.indexOf(L);
        if (act === "up" && i < doc.layers.length - 1) {
            [doc.layers[i], doc.layers[i + 1]] = [doc.layers[i + 1], doc.layers[i]];
        } else if (act === "down" && i > 0) {
            [doc.layers[i], doc.layers[i - 1]] = [doc.layers[i - 1], doc.layers[i]];
        } else if (act === "dup") {
            const copy = JSON.parse(JSON.stringify(L));
            copy.id = uid();
            copy.x += 30;
            copy.y += 30;
            doc.layers.splice(i + 1, 0, copy);
            selectedId = copy.id;
        } else if (act === "del") {
            doc.layers.splice(i, 1);
            if (selectedId === L.id) selectedId = null;
        }
        refreshAll();
    }

    // ---------- painel de propriedades ----------

    function ctl(label, kind, key, extra = {}) {
        const L = selected();
        const v = getPath(L, key);
        const attrs = `data-k="${key}" data-kind="${kind}"`;
        if (kind === "range") {
            return `<label>${label} <span>${Math.round(v)}${extra.unit || ""}</span><input type="range" ${attrs} min="${extra.min}" max="${extra.max}" step="${extra.step || 1}" value="${v}"></label>`;
        }
        if (kind === "number") {
            return `<label>${label}<input type="number" ${attrs} min="${extra.min ?? 0}" step="${extra.step || 1}" value="${Math.round(v)}"></label>`;
        }
        if (kind === "color") return `<label>${label}<input type="color" ${attrs} value="${v}"></label>`;
        if (kind === "check") return `<label class="chk"><input type="checkbox" ${attrs} ${v ? "checked" : ""}> ${label}</label>`;
        if (kind === "textarea") return `<label>${label}<textarea ${attrs} rows="3"></textarea></label>`;
        if (kind === "select") {
            const options = extra.options.map(o => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("");
            return `<label>${label}<select ${attrs}>${options}</select></label>`;
        }
        return "";
    }

    function renderProps() {
        const L = selected();
        if (!L) {
            propsEl.innerHTML = '<p class="hint">Clique num elemento da imagem (ou numa camada) pra editar. Arraste pra mover, quadradinho verde pra redimensionar, bolinha pra girar.</p>';
            return;
        }
        let html = "";
        if (L.type === "text") {
            html += ctl("Texto", "textarea", "text");
            html += ctl("Fonte", "select", "font", { options: FONTS });
            html += ctl("Tamanho", "range", "size", { min: 8, max: 600, unit: "px" });
            html += ctl("Cor", "color", "color");
            html += `<div class="row">${ctl("Negrito", "check", "bold")}${ctl("Itálico", "check", "italic")}${ctl("Sombra", "check", "shadow")}</div>`;
            html += `<h3>Contorno</h3>${ctl("Cor do contorno", "color", "stroke")}${ctl("Espessura", "range", "strokeW", { min: 0, max: 60, unit: "px" })}`;
            html += `<h3>Fundo do texto</h3>${ctl("Usar fundo", "check", "bgOn")}${ctl("Cor do fundo", "color", "bg")}`;
        } else if (L.type === "rect" || L.type === "ellipse") {
            html += `<div class="row">${ctl("Largura", "number", "w", { min: 4 })}${ctl("Altura", "number", "h", { min: 4 })}</div>`;
            html += ctl("Preencher", "check", "fillOn") + ctl("Cor de preenchimento", "color", "fill");
            html += ctl("Cor da borda", "color", "stroke") + ctl("Espessura da borda", "range", "strokeW", { min: 0, max: 80, unit: "px" });
            if (L.type === "rect") html += ctl("Cantos arredondados", "range", "radius", { min: 0, max: 300, unit: "px" });
        } else if (L.type === "arrow") {
            html += ctl("Cor", "color", "color") + ctl("Espessura", "range", "thick", { min: 2, max: 120, unit: "px" });
            html += ctl("Comprimento", "range", "w", { min: 40, max: 3000, unit: "px" });
        } else if (L.type === "image") {
            html += `<div class="row">${ctl("Largura", "number", "w", { min: 4 })}${ctl("Altura", "number", "h", { min: 4 })}</div>`;
            html += `<div class="row"><button type="button" data-fit="contain">Caber</button><button type="button" data-fit="cover">Preencher</button></div>`;
            html += ctl("Espelhar", "check", "flip");
            html += "<h3>Ajustes</h3>";
            html += ctl("Brilho", "range", "f.brightness", { min: 0, max: 200, unit: "%" });
            html += ctl("Contraste", "range", "f.contrast", { min: 0, max: 200, unit: "%" });
            html += ctl("Saturação", "range", "f.saturate", { min: 0, max: 300, unit: "%" });
            html += ctl("Desfoque", "range", "f.blur", { min: 0, max: 40, unit: "px" });
            html += ctl("Preto e branco", "range", "f.grayscale", { min: 0, max: 100, unit: "%" });
            html += ctl("Sépia", "range", "f.sepia", { min: 0, max: 100, unit: "%" });
            html += ctl("Matiz", "range", "f.hue", { min: 0, max: 360, unit: "°" });
        }
        html += "<h3>Geral</h3>";
        html += ctl("Opacidade", "range", "opacity", { min: 0, max: 100, unit: "%" });
        html += ctl("Rotação", "range", "rot", { min: -180, max: 180, unit: "°" });
        propsEl.innerHTML = html;

        const ta = propsEl.querySelector("textarea");
        if (ta) ta.value = L.text;

        propsEl.querySelectorAll("[data-fit]").forEach(btn => btn.addEventListener("click", () => {
            const a = assetById(L.assetId);
            if (!a) return;
            pushHistory();
            const aw = a.width || L.w;
            const ah = a.height || L.h;
            const k = btn.dataset.fit === "cover"
                ? Math.max(doc.width / aw, doc.height / ah)
                : Math.min(doc.width / aw, doc.height / ah);
            L.w = aw * k;
            L.h = ah * k;
            L.x = doc.width / 2;
            L.y = doc.height / 2;
            refreshAll();
        }));
    }

    propsEl.addEventListener("pointerdown", () => { pendingSnap = snapshot(); });
    propsEl.addEventListener("keydown", () => { if (!pendingSnap) pendingSnap = snapshot(); });

    propsEl.addEventListener("input", e => {
        const el = e.target;
        const L = selected();
        if (!L || !el.dataset.k) return;
        if (pendingSnap) {
            pushHistory(pendingSnap);
            pendingSnap = null;
        }
        const kind = el.dataset.kind;
        let value;
        if (kind === "check") value = el.checked;
        else if (kind === "range" || kind === "number") value = parseFloat(el.value) || 0;
        else value = el.value;
        setPath(L, el.dataset.k, value);
        if (kind === "range") {
            const span = el.parentElement.querySelector("span");
            if (span) span.textContent = Math.round(value) + (span.textContent.replace(/[-\d.]/g, ""));
        }
        render(true);
        if (el.dataset.k === "text") renderLayerList();
    });

    // ---------- interação no canvas ----------

    function canvasPoint(e) {
        const r = canvas.getBoundingClientRect();
        return { x: (e.clientX - r.left) * canvas.width / r.width, y: (e.clientY - r.top) * canvas.height / r.height };
    }

    function toLocal(L, p) {
        const a = -L.rot * Math.PI / 180;
        const dx = p.x - L.x;
        const dy = p.y - L.y;
        return { x: dx * Math.cos(a) - dy * Math.sin(a), y: dx * Math.sin(a) + dy * Math.cos(a) };
    }

    function hitHandle(L, p) {
        const s = uiScale();
        const { w, h } = layerSize(L);
        const l = toLocal(L, p);
        if (Math.hypot(l.x, l.y - (-h / 2 - 28 * s)) < 12 * s) return "rotate";
        if (Math.abs(l.x - w / 2) < 10 * s && Math.abs(l.y - h / 2) < 10 * s) return "scale";
        return null;
    }

    function hitLayer(p) {
        for (let i = doc.layers.length - 1; i >= 0; i--) {
            const L = doc.layers[i];
            const { w, h } = layerSize(L);
            const l = toLocal(L, p);
            if (Math.abs(l.x) <= w / 2 && Math.abs(l.y) <= h / 2) return L;
        }
        return null;
    }

    canvas.addEventListener("pointerdown", e => {
        if (!doc) return;
        const p = canvasPoint(e);
        const cur = selected();
        const handle = cur && hitHandle(cur, p);
        let L = cur;
        let mode = handle;
        if (!handle) {
            L = hitLayer(p);
            mode = "move";
        }
        if (!L) {
            selectedId = null;
            refreshAll();
            return;
        }
        if (L.id !== selectedId) {
            selectedId = L.id;
            renderLayerList();
            renderProps();
        }
        const size = layerSize(L);
        drag = {
            mode, L, start: p, snap: snapshot(), moved: false,
            x0: L.x, y0: L.y, w0: L.w, h0: L.h, size0: L.size, thick0: L.thick, strokeW0: L.strokeW,
            dist0: Math.max(1, Math.hypot(p.x - L.x, p.y - L.y)), half: size,
        };
        canvas.setPointerCapture(e.pointerId);
        render(true);
    });

    canvas.addEventListener("pointermove", e => {
        if (!drag) {
            if (doc) {
                const p = canvasPoint(e);
                const cur = selected();
                const h = cur && hitHandle(cur, p);
                canvas.style.cursor = h === "rotate" ? "grab" : h === "scale" ? "nwse-resize" : hitLayer(p) ? "move" : "default";
            }
            return;
        }
        const p = canvasPoint(e);
        const { L } = drag;
        if (!drag.moved) {
            drag.moved = true;
            pushHistory(drag.snap);
        }
        if (drag.mode === "move") {
            L.x = drag.x0 + (p.x - drag.start.x);
            L.y = drag.y0 + (p.y - drag.start.y);
            const cx = doc.width / 2;
            const cy = doc.height / 2;
            if (Math.abs(L.x - cx) < 8 * uiScale()) L.x = cx;
            if (Math.abs(L.y - cy) < 8 * uiScale()) L.y = cy;
        } else if (drag.mode === "scale") {
            const k = Math.max(0.05, Math.hypot(p.x - L.x, p.y - L.y) / drag.dist0);
            if (L.type === "text") {
                L.size = Math.max(8, drag.size0 * k);
                L.strokeW = drag.strokeW0 * k;
            } else if (L.type === "arrow") {
                L.w = Math.max(20, drag.w0 * k);
                L.thick = Math.max(2, drag.thick0 * k);
            } else {
                L.w = Math.max(4, drag.w0 * k);
                L.h = Math.max(4, drag.h0 * k);
            }
        } else if (drag.mode === "rotate") {
            let deg = Math.atan2(p.y - L.y, p.x - L.x) * 180 / Math.PI + 90;
            if (deg > 180) deg -= 360;
            if (e.shiftKey) deg = Math.round(deg / 15) * 15;
            L.rot = Math.round(deg);
        }
        render(true);
    });

    function endDrag() {
        if (!drag) return;
        const moved = drag.moved;
        drag = null;
        if (moved) renderProps();
    }
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);

    canvas.addEventListener("dblclick", () => {
        const ta = propsEl.querySelector("textarea");
        if (ta) { ta.focus(); ta.select(); }
    });

    // ---------- documento ----------

    function newDoc(width, height) {
        return { version: 1, width, height, bg: "#101820", transparent: false, layers: [] };
    }

    function syncDocControls() {
        const key = `${doc.width}x${doc.height}`;
        if (![...presetSel.options].some(o => o.value === key)) {
            const opt = document.createElement("option");
            opt.value = key;
            opt.textContent = `Personalizado ${doc.width}×${doc.height}`;
            presetSel.appendChild(opt);
        }
        presetSel.value = key;
        bgInput.value = doc.bg;
        transparentChk.checked = doc.transparent;
        stage.classList.toggle("checker", doc.transparent);
        fitCanvas();
    }

    function refreshAll() {
        renderLayerList();
        renderProps();
        render(true);
    }

    function fillAssetSelect() {
        addAssetSel.innerHTML = '<option value="">Imagem da biblioteca…</option>';
        opts.assets().filter(a => a.kind === "image").forEach(a => {
            const o = document.createElement("option");
            o.value = a.id;
            o.textContent = a.name;
            addAssetSel.appendChild(o);
        });
    }

    function open(options) {
        opts = options;
        history = [];
        selectedId = null;
        nextId = 1;
        const asset = options.asset;
        if (asset && asset.design) {
            doc = JSON.parse(asset.design);
            doc.layers.forEach(l => {
                const n = parseInt(String(l.id).replace("L", ""), 10);
                if (n >= nextId) nextId = n + 1;
            });
            opts.replaceId = asset.id;
            opts.name = asset.name;
        } else if (asset) {
            doc = newDoc(asset.width || 1280, asset.height || 720);
            doc.transparent = false;
            opts.replaceId = "";
            opts.name = asset.name.replace(/\.[^.]+$/, "") + " (editada).png";
        } else {
            const [w, h] = (options.preset || "1280x720").split("x").map(Number);
            doc = newDoc(w, h);
            opts.replaceId = "";
            opts.name = "imagem.png";
        }
        modal.hidden = false;
        fillAssetSelect();
        syncDocControls();
        if (asset && !asset.design) addImageLayerSilently(asset);
        $("ie-add-frame").hidden = !options.getFrame;
        refreshAll();
        requestAnimationFrame(() => { fitCanvas(); render(true); });
    }

    function addImageLayerSilently(asset) {
        const aw = asset.width || 800;
        const ah = asset.height || 600;
        const L = baseLayer("image", { assetId: asset.id, w: aw, h: ah, flip: false, f: Object.assign({}, FILTER_DEFAULTS) });
        doc.layers.push(L);
    }

    function close() {
        modal.hidden = true;
        doc = null;
    }

    function toBlob() {
        return new Promise(resolve => {
            const off = document.createElement("canvas");
            off.width = doc.width;
            off.height = doc.height;
            paint(off.getContext("2d"), false);
            off.toBlob(resolve, "image/png");
        });
    }

    async function save() {
        const btn = $("ie-save");
        btn.disabled = true;
        try {
            const blob = await toBlob();
            const asset = await opts.upload(blob, opts.name, JSON.stringify(doc), opts.replaceId);
            opts.replaceId = asset.id;
            opts.name = asset.name;
            opts.onSaved(asset);
        } catch (err) {
            alert("Não consegui salvar a imagem: " + err.message);
        } finally {
            btn.disabled = false;
        }
    }

    async function download() {
        const blob = await toBlob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = (opts.name || "imagem.png").replace(/\.[^.]+$/, "") + ".png";
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    }

    // ---------- eventos da barra ----------

    document.querySelectorAll("[data-add]").forEach(b => b.addEventListener("click", () => addByType(b.dataset.add)));
    $("ie-close").addEventListener("click", close);
    $("ie-undo").addEventListener("click", undo);
    $("ie-save").addEventListener("click", save);
    $("ie-download").addEventListener("click", download);

    presetSel.addEventListener("change", () => {
        pushHistory();
        const [w, h] = presetSel.value.split("x").map(Number);
        const kx = w / doc.width;
        const ky = h / doc.height;
        doc.layers.forEach(L => { L.x *= kx; L.y *= ky; });
        doc.width = w;
        doc.height = h;
        fitCanvas();
        refreshAll();
    });
    bgInput.addEventListener("input", () => { doc.bg = bgInput.value; render(true); });
    bgInput.addEventListener("pointerdown", () => { pendingSnap = snapshot(); });
    bgInput.addEventListener("change", () => { if (pendingSnap) { pushHistory(pendingSnap); pendingSnap = null; } });
    transparentChk.addEventListener("change", () => {
        pushHistory();
        doc.transparent = transparentChk.checked;
        stage.classList.toggle("checker", doc.transparent);
        render(true);
    });

    $("ie-add-file").addEventListener("click", () => $("ie-file").click());
    $("ie-file").addEventListener("change", async e => {
        const file = e.target.files[0];
        e.target.value = "";
        if (!file) return;
        try {
            const asset = await opts.upload(file, file.name, "", "");
            fillAssetSelect();
            if (asset.kind !== "image") throw new Error("esse arquivo não é uma imagem");
            addImageLayer(asset);
        } catch (err) {
            alert("Não consegui adicionar a imagem: " + err.message);
        }
    });
    addAssetSel.addEventListener("change", () => {
        const a = assetById(addAssetSel.value);
        addAssetSel.value = "";
        if (a) addImageLayer(a);
    });
    $("ie-add-frame").addEventListener("click", async () => {
        try {
            const blob = await opts.getFrame();
            if (!blob) return;
            const asset = await opts.upload(blob, "frame.png", "", "");
            fillAssetSelect();
            addImageLayer(asset);
        } catch (err) {
            alert("Não consegui capturar o frame: " + err.message);
        }
    });

    document.addEventListener("keydown", e => {
        if (!doc || modal.hidden) return;
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) {
            e.preventDefault();
            undo();
        } else if (!typing && (e.key === "Delete" || e.key === "Backspace") && selected()) {
            e.preventDefault();
            layerAction(selected(), "del");
        } else if (!typing && selected() && e.key.startsWith("Arrow")) {
            e.preventDefault();
            const L = selected();
            const step = e.shiftKey ? 20 : 2;
            pushHistory();
            if (e.key === "ArrowLeft") L.x -= step;
            if (e.key === "ArrowRight") L.x += step;
            if (e.key === "ArrowUp") L.y -= step;
            if (e.key === "ArrowDown") L.y += step;
            render(true);
        }
    });

    window.addEventListener("resize", () => { fitCanvas(); render(true); });

    window.ImageEditor = { open, close, isOpen: () => !modal.hidden };
})();

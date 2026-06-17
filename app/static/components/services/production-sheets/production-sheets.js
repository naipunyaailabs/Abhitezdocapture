/**
 * Production Sheets Extractor — reduced "green column" set for the four
 * Abhitex daily production registers (Length Heming / Length Cuting /
 * FNS to Job / Cross Cuting).
 *
 * Columns: LOT NO, STYLE CODE, IO NUMBER, ShadeCode, TeamCode, PCS, KGS
 * Plus: a DATE field and a detected sheet type captured per page.
 *
 * ── Architecture (multi-file / up-to-50-page safe) ───────────────────────────
 * Each uploaded FILE becomes a "job". Jobs are run through a bounded
 * concurrency pool (PS_CONCURRENCY at a time) so 50 files extract without
 * overwhelming the server, and one job's failure or progress never affects
 * another's. Every extracted PAGE gets a STABLE unique id; the UI is keyed on
 * that id (never on array position), so a re-render while other pages are still
 * streaming in can never jump to or overwrite the wrong page. The header
 * subtitle has a SINGLE authoritative writer (_renderProgress) computed from
 * job state — there are no competing per-stream counters fighting over it.
 */

console.log("[ProductionSheets] Module loading...");

const PS_COLUMNS = [
    "LOT NO", "STYLE CODE", "IO NUMBER", "ShadeCode", "TeamCode", "PCS", "KGS"
];

// Mirrors SHEET_TYPES in the backend service (title + TeamCode header label).
const PS_SHEET_TYPES = {
    length_heming: { title: "LENGTH HEMING PROD",   team_header: "TeamCode",  label: "Length Heming" },
    length_cuting: { title: "LENGTH CUTING  PROD",  team_header: "TeamCode",  label: "Length Cutting" },
    fns_to_job:    { title: "FNS TO CONT /OUTSIDE", team_header: "TEAM CODE", label: "FNS to Job" },
    cross_cuting:  { title: "CROSS  CUTING  PROD",  team_header: "TEAM CODE", label: "Cross Cutting" },
};
const PS_DEFAULT_TYPE = "length_heming";

// How many files to extract concurrently. Kept at 1 (strictly sequential):
// each file extraction already fires multiple vision calls (detect + date +
// N voting passes) on the backend, so running files in parallel overwhelmed
// the LLM API — rows came back empty while the lighter date/shift call still
// succeeded. Sequential is reliable and matches the original working behavior.
const PS_CONCURRENCY = 1;

function psMeta(type) {
    return PS_SHEET_TYPES[type] || PS_SHEET_TYPES[PS_DEFAULT_TYPE];
}

class ProductionSheetsModule {
    constructor() {
        // pages:   ordered list of page records, each with a stable .id.
        // jobs:    one per uploaded file, tracks per-file extraction status.
        // activePageId: which page is shown on the right (stable id, not index).
        this.state = { pages: [], jobs: [], activePageId: null };
        this._uid = 0;
        this._injectOverlay();
        console.log("[ProductionSheets] Module initialized");
    }

    _nextId(prefix) { return `${prefix}-${++this._uid}`; }

    // ─── OVERLAY ─────────────────────────────────────────────
    _injectOverlay() {
        const el = document.createElement('div');
        el.id = 'ps-overlay';
        el.className = 'ps-overlay';
        el.innerHTML = `
            <div class="ps-container">
                <div class="ps-header">
                    <div class="ps-header-left">
                        <div class="ps-logo-badge">🧾</div>
                        <div>
                            <h2 class="ps-title">Production <span>Sheets</span></h2>
                            <p class="ps-subtitle" id="ps-subtitle">Processing...</p>
                        </div>
                    </div>
                    <div class="ps-header-right">
                        <button class="ps-btn-export" id="ps-export-btn" onclick="productionSheets.exportExcel()">📊 Export Excel</button>
                        <button class="ps-btn-close" onclick="productionSheets.close()">×</button>
                    </div>
                </div>
                <div class="ps-progress-track" id="ps-progress-track"><div class="ps-progress-fill" id="ps-progress-fill"></div></div>
                <div class="ps-main">
                    <div class="ps-source-panel">
                        <div class="ps-panel-title">
                            📄 Source Document
                            <span class="ps-page-counter" id="ps-page-counter"></span>
                        </div>
                        <div class="ps-page-list" id="ps-page-tabs"></div>
                        <div class="ps-image-viewer" id="ps-image-viewer">
                            <p style="color:#64748b;text-align:center;padding:2rem;">Loading...</p>
                        </div>
                    </div>
                    <div class="ps-data-panel">
                        <div class="ps-panel-title">✏️ Extracted Sheet (Editable)</div>
                        <div class="ps-meta-row">
                            <label>Sheet:</label>
                            <select id="ps-type-select" onchange="productionSheets.onTypeEdit(this.value)">
                                <option value="length_heming">Length Heming</option>
                                <option value="length_cuting">Length Cutting</option>
                                <option value="fns_to_job">FNS to Job</option>
                                <option value="cross_cuting">Cross Cutting</option>
                            </select>
                            <label>DATE:</label>
                            <input type="text" id="ps-date-input" placeholder="Page date" oninput="productionSheets.onDateEdit(this.value)">
                            <label>SHIFT:</label>
                            <select id="ps-shift-select" onchange="productionSheets.onShiftEdit(this.value)">
                                <option value="">–</option>
                                <option value="DAY">DAY</option>
                                <option value="NIGHT">NIGHT</option>
                            </select>
                        </div>
                        <div class="ps-table-toolbar">
                            <button class="ps-toolbar-btn add" onclick="productionSheets.addRow()">+ Row</button>
                            <button class="ps-toolbar-btn copy" onclick="productionSheets.copyTable()">Copy</button>
                        </div>
                        <div class="ps-table-wrapper">
                            <table class="ps-table" id="ps-table">
                                <thead id="ps-thead"></thead>
                                <tbody id="ps-tbody"></tbody>
                            </table>
                        </div>
                        <div class="ps-stats-bar">
                            <div class="ps-stat">Rows: <span id="ps-row-count">0</span></div>
                            <div class="ps-stat">Pages: <span id="ps-page-count">0</span></div>
                            <div class="ps-stat">Avg Confidence: <span id="ps-conf">–</span></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(el);
    }

    // ─── ENTRY POINT ─────────────────────────────────────────
    async processFiles(files) {
        const allowed = /\.(pdf|png|jpg|jpeg|bmp|tiff?|webp)$/i;
        const list = Array.from(files).filter(f => allowed.test(f.name));
        if (!list.length) {
            alert("No supported files selected (PDF or image).");
            return;
        }

        // Reset state for a fresh batch. Each file → one job.
        this.state.pages = [];
        this.state.activePageId = null;
        this.state.jobs = list.map(file => ({
            id: this._nextId("job"),
            file,
            status: "queued",          // queued | extracting | done | failed
            totalPages: null,          // filled from the stream metadata event
            error: null,
        }));

        this._show();
        this._renderTabs();
        this._renderActivePage();
        this._renderProgress();

        await this._runPool(this.state.jobs, PS_CONCURRENCY);

        this._renderProgress();
    }

    /** Run an array of jobs through a bounded-concurrency worker pool. */
    async _runPool(jobs, concurrency) {
        let cursor = 0;
        const worker = async () => {
            while (cursor < jobs.length) {
                const job = jobs[cursor++];
                await this._runJob(job);
            }
        };
        const workers = [];
        for (let i = 0; i < Math.min(concurrency, jobs.length); i++) {
            workers.push(worker());
        }
        await Promise.all(workers);
    }

    /** Extract one file (job). Fully isolated: never touches other jobs. */
    async _runJob(job) {
        job.status = "extracting";
        job.error = null;
        this._renderProgress();
        try {
            await this._uploadOneStreaming(job);
            job.status = "done";
        } catch (e) {
            console.error("[ProductionSheets] extract failed:", job.file.name, e);
            job.status = "failed";
            job.error = String(e);
        }
        this._renderProgress();
    }

    async _uploadOneStreaming(job) {
        const token = this._getToken();
        const fd = new FormData();
        fd.append("document", job.file);

        const res = await fetch("/api/production-sheets/extract-streaming", {
            method: "POST",
            headers: { "Authorization": `Bearer ${token}` },
            body: fd,
        });
        if (!res.ok) {
            const t = await res.text();
            throw new Error(`Server ${res.status}: ${t}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const handleEvent = (event) => {
            if (event.type === "metadata") {
                job.totalPages = event.total_pages || 1;
            } else if (event.type === "page") {
                this._addPage(job, event);
            } else if (event.type === "page_error") {
                console.error(`[ProductionSheets] ${job.file.name} page ${event.page_number} error:`, event.error);
                this._addPageError(job, event);
            } else if (event.type === "error") {
                throw new Error(event.error);
            }
            // "complete" is informational; job completion is tracked by _runJob.
        };

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.trim()) continue;
                try { handleEvent(JSON.parse(line)); }
                catch (e) { console.error("[ProductionSheets] parse line failed:", line, e); }
            }
        }
        if (buffer.trim()) {
            try { handleEvent(JSON.parse(buffer)); }
            catch (e) { console.error("[ProductionSheets] parse final buffer failed:", buffer); }
        }
    }

    /** Insert a freshly-extracted page, keeping pages grouped & ordered by job. */
    _addPage(job, event) {
        const page = {
            id: this._nextId("page"),
            jobId: job.id,
            fileName: job.file.name,
            status: "done",
            ...event,
        };
        this._insertPageForJob(job, page);

        // Auto-show the very first page that arrives in the whole batch.
        if (this.state.activePageId === null) {
            this.state.activePageId = page.id;
            this._renderActivePage();
        }
        this._renderTabs();
        this._renderProgress();
    }

    _addPageError(job, event) {
        const page = {
            id: this._nextId("page"),
            jobId: job.id,
            fileName: job.file.name,
            status: "failed",
            error: event.error || "extraction failed",
            page_number: event.page_number,
            sheet_type: PS_DEFAULT_TYPE,
            rows: [],
        };
        this._insertPageForJob(job, page);
        this._renderTabs();
        this._renderProgress();
    }

    /**
     * Insert a page so that all pages from the same job stay contiguous and in
     * the job's original order. With parallel jobs, pages from different files
     * can arrive interleaved; this keeps the list stable and readable.
     */
    _insertPageForJob(job, page) {
        const jobOrder = this.state.jobs.indexOf(job);
        const pages = this.state.pages;
        // Find the first page belonging to a later job; insert just before it.
        let insertAt = pages.length;
        for (let i = 0; i < pages.length; i++) {
            const pj = this.state.jobs.findIndex(j => j.id === pages[i].jobId);
            if (pj > jobOrder) { insertAt = i; break; }
        }
        pages.splice(insertAt, 0, page);
    }

    // ─── PROGRESS (single authoritative writer) ──────────────
    _renderProgress() {
        const jobs = this.state.jobs;
        const total = jobs.length;
        const done = jobs.filter(j => j.status === "done").length;
        const failed = jobs.filter(j => j.status === "failed").length;
        const running = jobs.filter(j => j.status === "extracting").length;
        const finished = done + failed;

        const sub = document.getElementById("ps-subtitle");
        if (finished >= total && total > 0) {
            const okPages = this.state.pages.filter(p => p.status === "done").length;
            sub.textContent = failed
                ? `${done}/${total} file(s) done · ${failed} failed · ${okPages} page(s) extracted`
                : `✅ ${total} file(s), ${okPages} page(s) completed`;
        } else if (running > 0) {
            // Sequential mode: name the file currently being read.
            const current = jobs.find(j => j.status === "extracting");
            const name = current ? current.file.name : "";
            sub.textContent = `Extracting ${finished + 1}/${total}: ${name} …`;
        } else {
            sub.textContent = `Preparing ${total} file(s)…`;
        }

        // Progress bar.
        const fill = document.getElementById("ps-progress-fill");
        const track = document.getElementById("ps-progress-track");
        if (fill && track) {
            const pct = total ? Math.round((finished / total) * 100) : 0;
            fill.style.width = `${pct}%`;
            track.style.display = (finished >= total && total > 0) ? "none" : "block";
        }

        this._updateStats();
    }

    _updateStats() {
        const okPages = this.state.pages.filter(p => p.status === "done");
        const totalRows = okPages.reduce((s, p) => s + (p.rows || []).length, 0);
        document.getElementById("ps-row-count").textContent = totalRows;
        document.getElementById("ps-page-count").textContent = okPages.length;

        const confs = okPages.map(p => p.confidence).filter(c => c);
        const avgConf = confs.length ? (confs.reduce((a, b) => a + b, 0) / confs.length) : 0;
        document.getElementById("ps-conf").textContent = avgConf ? `${Math.round(avgConf * 100)}%` : "–";

        const counter = document.getElementById("ps-page-counter");
        if (counter) counter.textContent = this.state.pages.length ? `${this.state.pages.length} page(s)` : "";
    }

    // ─── RENDER ──────────────────────────────────────────────
    _statusDot(status) {
        const map = {
            done:       { cls: "ok",       title: "Extracted" },
            failed:     { cls: "fail",     title: "Failed" },
            extracting: { cls: "running",  title: "Extracting…" },
            queued:     { cls: "queued",   title: "Queued" },
        };
        const s = map[status] || map.queued;
        return `<span class="ps-dot ${s.cls}" title="${s.title}"></span>`;
    }

    _renderTabs() {
        const wrap = document.getElementById("ps-page-tabs");
        const pages = this.state.pages || [];

        // Horizontal tab strip: P1 · P2 · P3 … in extraction order, each with a
        // status dot. Failed tabs carry an inline retry. A single trailing
        // "extracting…" ghost tab shows the pipeline is still working.
        const items = [];

        pages.forEach((p, i) => {
            const label = p.status === "failed"
                ? `P${i + 1} · failed`
                : `P${i + 1} · ${this._esc(psMeta(p.sheet_type).label)}`;
            const active = p.id === this.state.activePageId ? "active" : "";
            const retry = p.status === "failed"
                ? `<button class="ps-tab-retry" title="Retry this page" onclick="event.stopPropagation(); productionSheets.retryPage('${p.id}')">↻</button>`
                : "";
            items.push(`
                <button class="ps-tab ${active} ${p.status}" data-page-id="${p.id}" onclick="productionSheets.switchPage('${p.id}')">
                    ${this._statusDot(p.status)}<span class="ps-tab-label">${label}</span>${retry}
                </button>
            `);
        });

        // One trailing ghost tab while any file is still queued/extracting.
        const pending = this.state.jobs.some(j => j.status === "queued" || j.status === "extracting");
        if (pending) {
            items.push(`
                <span class="ps-tab ghost extracting">
                    ${this._statusDot("extracting")}<span class="ps-tab-label">extracting…</span>
                </span>
            `);
        }

        wrap.innerHTML = items.join("") || `<p style="color:#64748b;padding:0.4rem 0.5rem;">No pages yet.</p>`;

        // Keep the active tab visible as the strip grows past the viewport.
        const activeEl = wrap.querySelector(".ps-tab.active");
        if (activeEl) activeEl.scrollIntoView({ inline: "nearest", block: "nearest" });
    }

    switchPage(id) {
        this.state.activePageId = id;
        this._renderTabs();
        this._renderActivePage();
    }

    _activePage() {
        return this.state.pages.find(p => p.id === this.state.activePageId) || null;
    }

    /** Re-run extraction for a single failed page's source file. */
    async retryPage(pageId) {
        const page = this.state.pages.find(p => p.id === pageId);
        if (!page) return;
        const job = this.state.jobs.find(j => j.id === page.jobId);
        if (!job) return;

        // Drop the failed page(s) for this job; the stream will re-add them.
        this.state.pages = this.state.pages.filter(p => p.jobId !== job.id);
        if (!this.state.pages.some(p => p.id === this.state.activePageId)) {
            this.state.activePageId = this.state.pages[0]?.id || null;
        }
        this._renderTabs();
        this._renderActivePage();
        await this._runJob(job);
    }

    _renderActivePage() {
        const page = this._activePage();
        if (!page) {
            document.getElementById("ps-image-viewer").innerHTML = `<p style="color:#64748b;text-align:center;padding:2rem;">No page selected.</p>`;
            document.getElementById("ps-thead").innerHTML = "";
            document.getElementById("ps-tbody").innerHTML = "";
            document.getElementById("ps-date-input").value = "";
            const shiftSelReset = document.getElementById("ps-shift-select");
            if (shiftSelReset) shiftSelReset.value = "";
            return;
        }

        // Image
        const viewer = document.getElementById("ps-image-viewer");
        if (page.status === "failed") {
            viewer.innerHTML = `<p style="color:#f87171;text-align:center;padding:2rem;">⚠️ Extraction failed for this page.<br><span style="color:#94a3b8;font-size:0.85rem;">${this._esc(page.error || "")}</span></p>`;
        } else {
            viewer.innerHTML = page.image_url
                ? `<img src="${page.image_url}" alt="${this._esc(page.fileName)}" />`
                : `<p style="color:#64748b;text-align:center;padding:2rem;">No image available.</p>`;
        }

        // Sheet type + DATE
        const type = page.sheet_type || PS_DEFAULT_TYPE;
        document.getElementById("ps-type-select").value = PS_SHEET_TYPES[type] ? type : PS_DEFAULT_TYPE;
        document.getElementById("ps-date-input").value = page.date || "";
        const shiftSel = document.getElementById("ps-shift-select");
        if (shiftSel) {
            const sh = (page.shift || "").toUpperCase();
            shiftSel.value = (sh === "DAY" || sh === "NIGHT") ? sh : "";
        }

        // Table — TeamCode header label depends on the sheet type.
        const teamHeader = psMeta(type).team_header;
        const thead = document.getElementById("ps-thead");
        const tbody = document.getElementById("ps-tbody");
        thead.innerHTML = `<tr>${PS_COLUMNS.map(c => `<th>${this._esc(c === "TeamCode" ? teamHeader : c)}</th>`).join("")}<th></th></tr>`;
        tbody.innerHTML = (page.rows || []).map((row, ri) => `
            <tr>
                ${PS_COLUMNS.map(col => `<td contenteditable="true" oninput="productionSheets.onCellEdit(${ri}, '${this._esc(col)}', this.innerText)">${this._esc(row[col] || "")}</td>`).join("")}
                <td><button class="ps-row-del" onclick="productionSheets.deleteRow(${ri})">×</button></td>
            </tr>
        `).join("");
    }

    onTypeEdit(val) {
        const page = this._activePage();
        if (!page || !PS_SHEET_TYPES[val]) return;
        const meta = psMeta(val);
        page.sheet_type = val;
        page.sheet_title = meta.title;
        page.sheet_label = meta.label;
        page.team_header = meta.team_header;
        this._renderTabs();
        this._renderActivePage();
    }

    onDateEdit(val) {
        const page = this._activePage();
        if (page) page.date = val;
    }

    onShiftEdit(val) {
        const page = this._activePage();
        if (page) {
            const sh = (val || "").toUpperCase();
            page.shift = (sh === "DAY" || sh === "NIGHT") ? sh : "";
        }
    }

    onCellEdit(rowIdx, col, val) {
        const page = this._activePage();
        if (page && page.rows && page.rows[rowIdx]) {
            page.rows[rowIdx][col] = val.trim();
        }
    }

    addRow() {
        const page = this._activePage();
        if (!page) return;
        page.rows = page.rows || [];
        const empty = {};
        for (const c of PS_COLUMNS) empty[c] = "";
        page.rows.push(empty);
        this._renderActivePage();
        this._updateStats();
    }

    deleteRow(rowIdx) {
        const page = this._activePage();
        if (!page || !page.rows) return;
        page.rows.splice(rowIdx, 1);
        this._renderActivePage();
        this._updateStats();
    }

    copyTable() {
        const page = this._activePage();
        if (!page) return;
        const teamHeader = psMeta(page.sheet_type).team_header;
        const headerLine = PS_COLUMNS.map(c => c === "TeamCode" ? teamHeader : c);
        const lines = [headerLine.join("\t")];
        for (const r of (page.rows || [])) {
            lines.push(PS_COLUMNS.map(c => r[c] || "").join("\t"));
        }
        navigator.clipboard.writeText(lines.join("\n")).then(() => {
            this._setSubtitle("Copied to clipboard.");
        });
    }

    async exportExcel() {
        // Only export successfully-extracted pages, in display order.
        const pages = (this.state.pages || []).filter(p => p.status === "done");
        if (!pages.length) {
            alert("Nothing to export yet.");
            return;
        }
        const payload = {
            pages: pages.map(p => {
                const meta = psMeta(p.sheet_type);
                return {
                    sheet_type: p.sheet_type || PS_DEFAULT_TYPE,
                    sheet_title: p.sheet_title || meta.title,
                    sheet_label: p.sheet_label || meta.label,
                    team_header: p.team_header || meta.team_header,
                    date: p.date || "",
                    shift: p.shift || "",
                    rows: p.rows || [],
                };
            }),
            title: "Production_Sheets_Export",
        };
        const token = this._getToken();
        const res = await fetch("/api/production-sheets/export", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            alert("Export failed: " + res.status);
            return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `Production_Sheets_${Date.now()}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    // ─── HELPERS ─────────────────────────────────────────────
    _show() { document.getElementById("ps-overlay").classList.add("active"); }
    close() { document.getElementById("ps-overlay").classList.remove("active"); }
    _setSubtitle(t) { document.getElementById("ps-subtitle").textContent = t; }

    _getToken() {
        return localStorage.getItem("token") ||
               document.cookie.split(";").find(c => c.trim().startsWith("token="))?.split("=")[1] || "";
    }

    _esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
}

const productionSheets = new ProductionSheetsModule();
console.log("[ProductionSheets] Module ready.");

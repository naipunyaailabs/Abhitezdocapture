/**
 * Production Sheets Extractor — reduced "green column" set for the four
 * Abhitex daily production registers (Length Heming / Length Cuting /
 * FNS to Job / Cross Cuting).
 *
 * Columns: LOT NO, STYLE CODE, IO NUMBER, ShadeCode, TeamCode, PCS, KGS
 * Plus: a DATE field and a detected sheet type captured per page.
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

function psMeta(type) {
    return PS_SHEET_TYPES[type] || PS_SHEET_TYPES[PS_DEFAULT_TYPE];
}

class ProductionSheetsModule {
    constructor() {
        this.state = { queue: [], currentIndex: 0, results: [], allPages: [], activePageIndex: 0 };
        this._injectOverlay();
        console.log("[ProductionSheets] Module initialized");
    }

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
                <div class="ps-main">
                    <div class="ps-source-panel">
                        <div class="ps-panel-title">📄 Source Document</div>
                        <div class="ps-page-tabs" id="ps-page-tabs"></div>
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
                    <div class="ps-loading" id="ps-loading">
                        <div class="ps-spinner"></div>
                        <p class="ps-loading-text">Extracting production sheet data...</p>
                        <p class="ps-loading-sub">Vision AI is reading your document</p>
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
        this.state.queue = list;
        this.state.currentIndex = 0;
        this.state.results = [];
        this.state.allPages = [];
        this.state.activePageIndex = 0;
        this._show();
        await this._processQueue();
    }

    async _processQueue() {
        const total = this.state.queue.length;
        this.state.allPages = this.state.allPages || [];
        let totalConfs = [];

        for (let i = 0; i < total; i++) {
            this.state.currentIndex = i;
            const file = this.state.queue[i];
            this._setSubtitle(`Processing ${i + 1}/${total}: ${file.name} (streaming...)`);
            this._setLoading(false);
            this._show();
            try {
                await this._uploadOneStreaming(file, totalConfs);
            } catch (e) {
                console.error("[ProductionSheets] extract failed:", e);
                this._setSubtitle(`Error processing ${file.name}: ${String(e)}`);
            }
        }

        this._setLoading(false);
        this._updateStats(totalConfs);
        this._setSubtitle(`${this.state.results.length} file(s), ${this.state.allPages.length} page(s) completed`);
    }

    async _uploadOneStreaming(file, confsArray) {
        const token = this._getToken();
        const fd = new FormData();
        fd.append("document", file);

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
        let pageCount = 0;
        let totalPages = 0;
        let firstPageArrived = false;

        const handleEvent = (event) => {
            if (event.type === "metadata") {
                totalPages = event.total_pages || 1;
            } else if (event.type === "page") {
                this.state.allPages.push(event);
                pageCount++;
                if (!firstPageArrived) {
                    firstPageArrived = true;
                    this.state.activePageIndex = 0;
                    this._renderTabs();
                    this._renderActivePage();
                } else {
                    this._renderTabs();
                }
                const totalRows = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
                document.getElementById("ps-row-count").textContent = totalRows;
                document.getElementById("ps-page-count").textContent = this.state.allPages.length;
                this._setSubtitle(`✅ Page ${pageCount} done · ${Math.max(0, totalPages - pageCount)} extracting in background...`);
                if (event.confidence) confsArray.push(event.confidence);
            } else if (event.type === "page_error") {
                console.error(`[ProductionSheets] Page ${event.page_number} error:`, event.error);
                pageCount++;
                this._renderTabs();
                this._setSubtitle(`⚠️ Page ${pageCount} failed · ${Math.max(0, totalPages - pageCount)} extracting...`);
            } else if (event.type === "error") {
                throw new Error(event.error);
            }
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

        this.state.results.push({ file: file.name, data: { pages: this.state.allPages } });
    }

    _updateStats(confsArray) {
        const totalRows = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
        document.getElementById("ps-row-count").textContent = totalRows;
        document.getElementById("ps-page-count").textContent = this.state.allPages.length;
        const avgConf = confsArray.length ? (confsArray.reduce((a, b) => a + b) / confsArray.length) : 0;
        document.getElementById("ps-conf").textContent = avgConf ? `${Math.round(avgConf * 100)}%` : "–";
    }

    // ─── RENDER ──────────────────────────────────────────────
    _renderTabs() {
        const wrap = document.getElementById("ps-page-tabs");
        const pages = this.state.allPages || [];
        wrap.innerHTML = pages.map((p, i) => {
            const label = psMeta(p.sheet_type).label;
            return `<button class="ps-tab ${i === this.state.activePageIndex ? 'active' : ''}" onclick="productionSheets.switchPage(${i})">P${i + 1} · ${this._esc(label)}</button>`;
        }).join("");
    }

    switchPage(i) {
        this.state.activePageIndex = i;
        this._renderTabs();
        this._renderActivePage();
    }

    _renderActivePage() {
        const pages = this.state.allPages || [];
        const page = pages[this.state.activePageIndex];
        if (!page) {
            document.getElementById("ps-image-viewer").innerHTML = `<p style="color:#64748b;text-align:center;padding:2rem;">No page to display.</p>`;
            document.getElementById("ps-thead").innerHTML = "";
            document.getElementById("ps-tbody").innerHTML = "";
            document.getElementById("ps-date-input").value = "";
            return;
        }

        // Image
        const viewer = document.getElementById("ps-image-viewer");
        viewer.innerHTML = page.image_url
            ? `<img src="${page.image_url}" alt="Page ${this.state.activePageIndex + 1}" />`
            : `<p style="color:#64748b;text-align:center;padding:2rem;">No image available.</p>`;

        // Sheet type + DATE
        const type = page.sheet_type || PS_DEFAULT_TYPE;
        document.getElementById("ps-type-select").value = PS_SHEET_TYPES[type] ? type : PS_DEFAULT_TYPE;
        document.getElementById("ps-date-input").value = page.date || "";

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
        const page = this.state.allPages?.[this.state.activePageIndex];
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
        const page = this.state.allPages?.[this.state.activePageIndex];
        if (page) page.date = val;
    }

    onCellEdit(rowIdx, col, val) {
        const page = this.state.allPages?.[this.state.activePageIndex];
        if (page && page.rows && page.rows[rowIdx]) {
            page.rows[rowIdx][col] = val.trim();
        }
    }

    addRow() {
        const page = this.state.allPages?.[this.state.activePageIndex];
        if (!page) return;
        page.rows = page.rows || [];
        const empty = {};
        for (const c of PS_COLUMNS) empty[c] = "";
        page.rows.push(empty);
        this._renderActivePage();
        document.getElementById("ps-row-count").textContent = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
    }

    deleteRow(rowIdx) {
        const page = this.state.allPages?.[this.state.activePageIndex];
        if (!page || !page.rows) return;
        page.rows.splice(rowIdx, 1);
        this._renderActivePage();
        document.getElementById("ps-row-count").textContent = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
    }

    copyTable() {
        const page = this.state.allPages?.[this.state.activePageIndex];
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
        const pages = this.state.allPages || [];
        if (!pages.length) {
            alert("Nothing to export.");
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
    _setLoading(on) { document.getElementById("ps-loading").style.display = on ? "flex" : "none"; }

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

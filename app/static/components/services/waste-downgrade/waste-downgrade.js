/**
 * Waste & Downgrade Extractor — Fixed schema for the
 * Wastage + Downgrade register sheet.
 *
 * Columns: IO NO, A-GRADE, B-GRADE, C-GRADE, D-GRADE,
 *          CHINDI, POUCHA, SELVAGE, PATTI, Total
 * Plus: one DATE field captured per page.
 */

console.log("[WasteDowngrade] Module loading...");

const WD_COLUMNS = [
    "IO NO", "A-GRADE", "B-GRADE", "C-GRADE", "D-GRADE",
    "CHINDI", "POUCHA", "SELVAGE", "PATTI", "Total"
];

class WasteDowngradeModule {
    constructor() {
        this.state = {
            queue: [],
            currentIndex: 0,
            results: [],
            activePageIndex: 0,
        };
        this._injected = false;
        this._injectOverlay();
        this._injected = true;
        console.log("[WasteDowngrade] Module initialized");
    }

    // ─── OVERLAY ─────────────────────────────────────────────
    _injectOverlay() {
        const el = document.createElement('div');
        el.id = 'wd-overlay';
        el.className = 'wd-overlay';
        el.innerHTML = `
            <div class="wd-container">
                <div class="wd-header">
                    <div class="wd-header-left">
                        <div class="wd-logo-badge">♻️</div>
                        <div>
                            <h2 class="wd-title">Waste &amp; <span>Downgrade</span></h2>
                            <p class="wd-subtitle" id="wd-subtitle">Processing...</p>
                        </div>
                    </div>
                    <div class="wd-header-right">
                        <button class="wd-btn-export" id="wd-export-btn" onclick="wasteDowngrade.exportExcel()">📊 Export Excel</button>
                        <button class="wd-btn-close" onclick="wasteDowngrade.close()">×</button>
                    </div>
                </div>
                <div class="wd-main">
                    <div class="wd-source-panel">
                        <div class="wd-panel-title">📄 Source Document</div>
                        <div class="wd-page-tabs" id="wd-page-tabs"></div>
                        <div class="wd-image-viewer" id="wd-image-viewer">
                            <p style="color:#64748b;text-align:center;padding:2rem;">Loading...</p>
                        </div>
                    </div>
                    <div class="wd-data-panel">
                        <div class="wd-panel-title">✏️ Extracted Sheet (Editable)</div>
                        <div class="wd-date-row">
                            <label>DATE:</label>
                            <input type="text" id="wd-date-input" placeholder="Page date" oninput="wasteDowngrade.onDateEdit(this.value)">
                        </div>
                        <div class="wd-table-toolbar">
                            <button class="wd-toolbar-btn add" onclick="wasteDowngrade.addRow()">+ Row</button>
                            <button class="wd-toolbar-btn copy" onclick="wasteDowngrade.copyTable()">Copy</button>
                        </div>
                        <div class="wd-table-wrapper">
                            <table class="wd-table" id="wd-table">
                                <thead id="wd-thead"></thead>
                                <tbody id="wd-tbody"></tbody>
                            </table>
                        </div>
                        <div class="wd-stats-bar">
                            <div class="wd-stat">Rows: <span id="wd-row-count">0</span></div>
                            <div class="wd-stat">Pages: <span id="wd-page-count">0</span></div>
                            <div class="wd-stat">Avg Confidence: <span id="wd-conf">–</span></div>
                        </div>
                    </div>
                    <div class="wd-loading" id="wd-loading">
                        <div class="wd-spinner"></div>
                        <p class="wd-loading-text">Extracting Waste &amp; Downgrade data...</p>
                        <p class="wd-loading-sub">Vision AI is reading your document</p>
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
        this.state.allPages = []; // Initialize allPages for progressive display
        this.state.activePageIndex = 0;
        this._show();
        await this._processQueue();
    }

    async _processQueue() {
        const total = this.state.queue.length;
        
        // Initialize allPages if not already done
        this.state.allPages = this.state.allPages || [];
        let totalConfs = [];
        
        for (let i = 0; i < total; i++) {
            this.state.currentIndex = i;
            const file = this.state.queue[i];
            this._setSubtitle(`Processing ${i + 1}/${total}: ${file.name} (streaming...)`);
            this._setLoading(false); // Keep UI responsive during streaming
            this._show();
            
            try {
                // Use streaming endpoint for progressive display
                await this._uploadOneStreaming(file, totalConfs);
            } catch (e) {
                console.error("[WasteDowngrade] extract failed:", e);
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
        
        const res = await fetch("/api/waste-downgrade/extract-streaming", {
            method: "POST",
            headers: { "Authorization": `Bearer ${token}` },
            body: fd,
        });
        
        if (!res.ok) {
            const t = await res.text();
            throw new Error(`Server ${res.status}: ${t}`);
        }
        
        // Read streaming response (NDJSON - newline-delimited JSON)
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let pageCount = 0;
        let totalPages = 0;
        let firstPageArrived = false;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop(); // Keep incomplete line in buffer
            
            for (const line of lines) {
                if (!line.trim()) continue;
                
                try {
                    const event = JSON.parse(line);
                    
                    if (event.type === "metadata") {
                        totalPages = event.total_pages || 1;
                        console.log(`[WasteDowngrade] Streaming start: ${totalPages} pages`);
                    } 
                    else if (event.type === "page") {
                        // A page has completed extraction - add it to allPages immediately
                        this.state.allPages.push(event);
                        pageCount++;
                        
                        // AUTO-DISPLAY FIRST PAGE IMMEDIATELY
                        if (!firstPageArrived) {
                            firstPageArrived = true;
                            this.state.activePageIndex = 0; // Set active to first page
                            this._renderTabs();
                            this._renderActivePage(); // Display page 1 right away
                            console.log(`[WasteDowngrade] 🎯 Page 1 displayed immediately!`);
                        } else {
                            // Remaining pages just add tabs (user will see them appear)
                            this._renderTabs();
                        }
                        
                        // Update stats
                        const totalRows = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
                        document.getElementById("wd-row-count").textContent = totalRows;
                        document.getElementById("wd-page-count").textContent = this.state.allPages.length;
                        
                        this._setSubtitle(`✅ Page ${pageCount} done · ${totalPages - pageCount} extracting in background...`);
                        console.log(`[WasteDowngrade] Page ${event.page_number} completed (confidence: ${Math.round(event.confidence * 100)}%)`);
                        
                        if (event.confidence) {
                            confsArray.push(event.confidence);
                        }
                    } 
                    else if (event.type === "page_error") {
                        console.error(`[WasteDowngrade] Page ${event.page_number} error:`, event.error);
                        pageCount++; // Count failed pages too
                        this._renderTabs();
                        this._setSubtitle(`⚠️ Page ${pageCount} failed · ${Math.max(0, totalPages - pageCount)} extracting...`);
                    } 
                    else if (event.type === "complete") {
                        console.log(`[WasteDowngrade] ✨ Streaming complete - all pages done`);
                    } 
                    else if (event.type === "error") {
                        throw new Error(event.error);
                    }
                } catch (e) {
                    console.error("[WasteDowngrade] Failed to parse stream line:", line, e);
                }
            }
        }
        
        // Process final buffer if any
        if (buffer.trim()) {
            try {
                const event = JSON.parse(buffer);
                if (event.type === "page") {
                    this.state.allPages.push(event);
                    if (!firstPageArrived) {
                        firstPageArrived = true;
                        this.state.activePageIndex = 0;
                        this._renderTabs();
                        this._renderActivePage();
                    } else {
                        this._renderTabs();
                    }
                }
            } catch (e) {
                console.error("[WasteDowngrade] Failed to parse final buffer:", buffer);
            }
        }
        
        this.state.results.push({ file: file.name, data: { pages: this.state.allPages } });
    }

    _updateStats(confsArray) {
        const totalRows = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
        document.getElementById("wd-row-count").textContent = totalRows;
        document.getElementById("wd-page-count").textContent = this.state.allPages.length;
        const avgConf = confsArray.length ? (confsArray.reduce((a,b)=>a+b) / confsArray.length) : 0;
        document.getElementById("wd-conf").textContent = avgConf ? `${Math.round(avgConf * 100)}%` : "–";
    }

    // ─── RENDER ──────────────────────────────────────────────
    _renderMerged() {
        const allPages = [];
        let confSum = 0, confN = 0;
        for (const r of this.state.results) {
            if (!r.data) continue;
            for (const p of (r.data.pages || [])) {
                allPages.push({ ...p, _file: r.file });
            }
            if (typeof r.data.average_confidence === "number") {
                confSum += r.data.average_confidence;
                confN += 1;
            }
        }
        this.state.allPages = allPages;
        this.state.activePageIndex = 0;

        const totalRows = allPages.reduce((s, p) => s + (p.rows || []).length, 0);
        document.getElementById("wd-row-count").textContent = totalRows;
        document.getElementById("wd-page-count").textContent = allPages.length;
        const avgConf = confN ? (confSum / confN) : 0;
        document.getElementById("wd-conf").textContent = avgConf ? `${Math.round(avgConf * 100)}%` : "–";

        this._renderTabs();
        this._renderActivePage();
        this._setSubtitle(`${this.state.results.length} file(s), ${allPages.length} page(s), ${totalRows} row(s)`);
    }

    _renderTabs() {
        const wrap = document.getElementById("wd-page-tabs");
        const pages = this.state.allPages || [];
        wrap.innerHTML = pages.map((p, i) =>
            `<button class="wd-tab ${i === this.state.activePageIndex ? 'active' : ''}" onclick="wasteDowngrade.switchPage(${i})">Page ${i + 1}</button>`
        ).join("");
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
            document.getElementById("wd-image-viewer").innerHTML = `<p style="color:#64748b;text-align:center;padding:2rem;">No page to display.</p>`;
            document.getElementById("wd-thead").innerHTML = "";
            document.getElementById("wd-tbody").innerHTML = "";
            document.getElementById("wd-date-input").value = "";
            return;
        }

        // Image
        const viewer = document.getElementById("wd-image-viewer");
        viewer.innerHTML = page.image_url
            ? `<img src="${page.image_url}" alt="Page ${this.state.activePageIndex + 1}" />`
            : `<p style="color:#64748b;text-align:center;padding:2rem;">No image available.</p>`;

        // DATE
        document.getElementById("wd-date-input").value = page.date || "";

        // Table
        const thead = document.getElementById("wd-thead");
        const tbody = document.getElementById("wd-tbody");
        thead.innerHTML = `<tr>${WD_COLUMNS.map(c => `<th>${this._esc(c)}</th>`).join("")}<th></th></tr>`;
        tbody.innerHTML = (page.rows || []).map((row, ri) => `
            <tr>
                ${WD_COLUMNS.map(col => `<td contenteditable="true" oninput="wasteDowngrade.onCellEdit(${ri}, '${this._esc(col)}', this.innerText)">${this._esc(row[col] || "")}</td>`).join("")}
                <td><button class="wd-row-del" onclick="wasteDowngrade.deleteRow(${ri})">×</button></td>
            </tr>
        `).join("");
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
        for (const c of WD_COLUMNS) empty[c] = "";
        page.rows.push(empty);
        this._renderActivePage();
        document.getElementById("wd-row-count").textContent = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
    }

    deleteRow(rowIdx) {
        const page = this.state.allPages?.[this.state.activePageIndex];
        if (!page || !page.rows) return;
        page.rows.splice(rowIdx, 1);
        this._renderActivePage();
        document.getElementById("wd-row-count").textContent = this.state.allPages.reduce((s, p) => s + (p.rows || []).length, 0);
    }

    copyTable() {
        const page = this.state.allPages?.[this.state.activePageIndex];
        if (!page) return;
        const lines = [WD_COLUMNS.join("\t")];
        for (const r of (page.rows || [])) {
            lines.push(WD_COLUMNS.map(c => r[c] || "").join("\t"));
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
            pages: pages.map(p => ({ date: p.date || "", rows: p.rows || [] })),
            title: "Waste_Downgrade_Export",
        };
        const token = this._getToken();
        const res = await fetch("/api/waste-downgrade/export", {
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
        a.download = `Waste_Downgrade_${Date.now()}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    // ─── HELPERS ─────────────────────────────────────────────
    _show() { document.getElementById("wd-overlay").classList.add("active"); }
    close() { document.getElementById("wd-overlay").classList.remove("active"); }
    _setSubtitle(t) { document.getElementById("wd-subtitle").textContent = t; }
    _setLoading(on) { document.getElementById("wd-loading").style.display = on ? "flex" : "none"; }

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

const wasteDowngrade = new WasteDowngradeModule();
console.log("[WasteDowngrade] Module ready.");

/**
 * Lot History Cards Extraction — Abhitex "Lot History Card (Grey Folding)" form.
 *
 * Each page = one card. Captured:
 *   Header: I.O. No, Dye Lot No, Shade No, Quality M.No
 *   Rope 1 / Rope 2 / Rope 3 : list of { Roll No, Total Pcs, Wt (kg), Code }
 */

console.log("[LotHistoryCards] Module loading...");

const LHC_HEADER_FIELDS = ["I.O. No", "Dye Lot No", "Shade No", "Quality M.No"];
const LHC_ROPE_COLUMNS = ["Roll No", "Total Pcs", "Wt (kg)", "Code"];
const LHC_ROPE_KEYS = ["Rope 1", "Rope 2", "Rope 3"];

class LotHistoryCardsModule {
    constructor() {
        this.state = {
            queue: [],
            currentIndex: 0,
            results: [],
            allPages: [],
            activePageIndex: 0,
        };
        this._injectOverlay();
        console.log("[LotHistoryCards] Module initialized");
    }

    // ─── OVERLAY ─────────────────────────────────────────────
    _injectOverlay() {
        const el = document.createElement('div');
        el.id = 'lhc-overlay';
        el.className = 'lhc-overlay';
        el.innerHTML = `
            <div class="lhc-container">
                <div class="lhc-header">
                    <div class="lhc-header-left">
                        <div class="lhc-logo-badge">🧵</div>
                        <div>
                            <h2 class="lhc-title">Lot History <span>Cards</span></h2>
                            <p class="lhc-subtitle" id="lhc-subtitle">Processing...</p>
                        </div>
                    </div>
                    <div class="lhc-header-right">
                        <button class="lhc-btn-export" id="lhc-export-btn" onclick="lotHistoryCards.exportExcel()">📊 Export Excel</button>
                        <button class="lhc-btn-close" onclick="lotHistoryCards.close()">×</button>
                    </div>
                </div>
                <div class="lhc-main">
                    <div class="lhc-source-panel">
                        <div class="lhc-panel-title">📄 Source Document</div>
                        <div class="lhc-page-tabs" id="lhc-page-tabs"></div>
                        <div class="lhc-image-viewer" id="lhc-image-viewer">
                            <p style="color:#64748b;text-align:center;padding:2rem;">Loading...</p>
                        </div>
                    </div>
                    <div class="lhc-data-panel">
                        <div class="lhc-panel-title">✏️ Extracted Card (Editable)</div>
                        <div class="lhc-data-scroll" id="lhc-data-scroll"></div>
                        <div class="lhc-stats-bar">
                            <div class="lhc-stat">Cards: <span id="lhc-card-count">0</span></div>
                            <div class="lhc-stat">Rolls: <span id="lhc-roll-count">0</span></div>
                        </div>
                    </div>
                    <div class="lhc-loading" id="lhc-loading">
                        <div class="lhc-spinner"></div>
                        <p class="lhc-loading-text">Extracting Lot History Cards...</p>
                        <p class="lhc-loading-sub">Vision AI is reading your document</p>
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
        this._show();
        await this._processQueue();
    }

    async _processQueue() {
        const total = this.state.queue.length;
        for (let i = 0; i < total; i++) {
            this.state.currentIndex = i;
            const file = this.state.queue[i];
            this._setSubtitle(`Processing ${i + 1}/${total}: ${file.name}`);
            this._setLoading(true);
            try {
                const data = await this._uploadOne(file);
                this.state.results.push({ file: file.name, data });
            } catch (e) {
                console.error("[LotHistoryCards] extract failed:", e);
                this.state.results.push({ file: file.name, error: String(e) });
            }
        }
        this._setLoading(false);
        this._renderMerged();
    }

    async _uploadOne(file) {
        const token = this._getToken();
        const fd = new FormData();
        fd.append("document", file);
        const res = await fetch("/api/lot-history-cards/extract", {
            method: "POST",
            headers: { "Authorization": `Bearer ${token}` },
            body: fd,
        });
        if (!res.ok) {
            const t = await res.text();
            throw new Error(`Server ${res.status}: ${t}`);
        }
        const json = await res.json();
        if (!json.success) throw new Error(json.detail || "Extraction failed");
        return json.data;
    }

    // ─── RENDER ──────────────────────────────────────────────
    _rollCount(page) {
        return LHC_ROPE_KEYS.reduce((s, k) => s + (page[k] || []).length, 0);
    }

    _renderMerged() {
        const allPages = [];
        for (const r of this.state.results) {
            if (!r.data) continue;
            for (const p of (r.data.pages || [])) {
                allPages.push({ ...p, _file: r.file });
            }
        }
        this.state.allPages = allPages;
        this.state.activePageIndex = 0;

        const totalRolls = allPages.reduce((s, p) => s + this._rollCount(p), 0);
        document.getElementById("lhc-card-count").textContent = allPages.length;
        document.getElementById("lhc-roll-count").textContent = totalRolls;

        this._renderTabs();
        this._renderActivePage();
        this._setSubtitle(`${this.state.results.length} file(s), ${allPages.length} card(s), ${totalRolls} roll(s)`);
    }

    _renderTabs() {
        const wrap = document.getElementById("lhc-page-tabs");
        const pages = this.state.allPages || [];
        wrap.innerHTML = pages.map((p, i) =>
            `<button class="lhc-tab ${i === this.state.activePageIndex ? 'active' : ''}" onclick="lotHistoryCards.switchPage(${i})">Card ${i + 1}</button>`
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
        const viewer = document.getElementById("lhc-image-viewer");
        const scroll = document.getElementById("lhc-data-scroll");

        if (!page) {
            viewer.innerHTML = `<p style="color:#64748b;text-align:center;padding:2rem;">No card to display.</p>`;
            scroll.innerHTML = "";
            return;
        }

        viewer.innerHTML = page.image_url
            ? `<img src="${page.image_url}" alt="Card ${this.state.activePageIndex + 1}" />`
            : `<p style="color:#64748b;text-align:center;padding:2rem;">No image available.</p>`;

        page.header = page.header || {};
        const conf = (page.confidence && page.confidence.sections) || {};
        const notes = (page.confidence && page.confidence.notes) || {};

        // Header fields
        let html = `<div class="lhc-section-head">
            <span class="lhc-section-title">Header</span>
            ${this._confBadge(conf.header)}
        </div>`;
        html += `<div class="lhc-header-fields">`;
        for (const f of LHC_HEADER_FIELDS) {
            html += `
                <div class="lhc-field">
                    <label>${this._esc(f)}</label>
                    <input type="text" value="${this._esc(page.header[f] || "")}"
                        oninput="lotHistoryCards.onHeaderEdit('${this._esc(f)}', this.value)">
                </div>`;
        }
        html += `</div>`;

        // Rope blocks
        for (const ropeKey of LHC_ROPE_KEYS) {
            const rolls = page[ropeKey] || [];
            html += `
                <div class="lhc-rope-block">
                    <div class="lhc-rope-head">
                        <span class="lhc-rope-title">${this._esc(ropeKey)}</span>
                        ${this._confBadge(conf[ropeKey], notes[ropeKey])}
                        <button class="lhc-toolbar-btn" onclick="lotHistoryCards.addRow('${ropeKey}')">+ Roll</button>
                    </div>
                    ${notes[ropeKey] ? `<div class="lhc-conf-note">⚠ ${this._esc(notes[ropeKey])} — please verify this section.</div>` : ""}
                    <div class="lhc-table-wrapper">
                        <table class="lhc-table">
                            <thead><tr>${LHC_ROPE_COLUMNS.map(c => `<th>${this._esc(c)}</th>`).join("")}<th></th></tr></thead>
                            <tbody>
                                ${rolls.map((roll, ri) => `
                                    <tr>
                                        ${LHC_ROPE_COLUMNS.map(col => `<td contenteditable="true" oninput="lotHistoryCards.onCellEdit('${ropeKey}', ${ri}, '${this._esc(col)}', this.innerText)">${this._esc(roll[col] || "")}</td>`).join("")}
                                        <td><button class="lhc-row-del" onclick="lotHistoryCards.deleteRow('${ropeKey}', ${ri})">×</button></td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>`;
        }

        scroll.innerHTML = html;
    }

    // ─── EDITING ─────────────────────────────────────────────
    _activePage() {
        return this.state.allPages?.[this.state.activePageIndex];
    }

    onHeaderEdit(field, val) {
        const page = this._activePage();
        if (!page) return;
        page.header = page.header || {};
        page.header[field] = val.trim();
    }

    onCellEdit(ropeKey, rowIdx, col, val) {
        const page = this._activePage();
        if (page && page[ropeKey] && page[ropeKey][rowIdx]) {
            page[ropeKey][rowIdx][col] = val.trim();
        }
    }

    addRow(ropeKey) {
        const page = this._activePage();
        if (!page) return;
        page[ropeKey] = page[ropeKey] || [];
        const empty = {};
        for (const c of LHC_ROPE_COLUMNS) empty[c] = "";
        page[ropeKey].push(empty);
        this._renderActivePage();
        this._refreshRollCount();
    }

    deleteRow(ropeKey, rowIdx) {
        const page = this._activePage();
        if (!page || !page[ropeKey]) return;
        page[ropeKey].splice(rowIdx, 1);
        this._renderActivePage();
        this._refreshRollCount();
    }

    _refreshRollCount() {
        const total = (this.state.allPages || []).reduce((s, p) => s + this._rollCount(p), 0);
        document.getElementById("lhc-roll-count").textContent = total;
    }

    // ─── EXPORT ──────────────────────────────────────────────
    async exportExcel() {
        const pages = this.state.allPages || [];
        if (!pages.length) {
            alert("Nothing to export.");
            return;
        }
        const payload = {
            pages: pages.map(p => {
                const out = { header: p.header || {} };
                for (const k of LHC_ROPE_KEYS) out[k] = p[k] || [];
                return out;
            }),
            title: "Lot_History_Cards_Export",
        };
        const token = this._getToken();
        const res = await fetch("/api/lot-history-cards/export", {
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
        a.download = `Lot_History_Cards_${Date.now()}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    // ─── HELPERS ─────────────────────────────────────────────
    _show() { document.getElementById("lhc-overlay").classList.add("active"); }
    close() { document.getElementById("lhc-overlay").classList.remove("active"); }
    _setSubtitle(t) { document.getElementById("lhc-subtitle").textContent = t; }
    _setLoading(on) { document.getElementById("lhc-loading").style.display = on ? "flex" : "none"; }

    _getToken() {
        return localStorage.getItem("token") ||
               document.cookie.split(";").find(c => c.trim().startsWith("token="))?.split("=")[1] || "";
    }

    /**
     * Confidence badge for a section. `score` is 0-100, derived by reconciling
     * the extracted roll values against the card's PRINTED column totals (an
     * independent ground truth). null/undefined = no printed total to verify
     * against. Colors: green ≥ 85 (verified), amber 60-84 (review), red < 60
     * (mismatch). `note` (optional) explains a reconciliation mismatch.
     */
    _confBadge(score, note) {
        if (score === null || score === undefined) {
            return `<span class="lhc-conf lhc-conf-na" title="No printed total on the card to cross-check this section against.">— </span>`;
        }
        let level = "low";
        if (score >= 85) level = "high";
        else if (score >= 60) level = "mid";
        const base = level === "high"
            ? "Matches the card's printed total."
            : "Does NOT match the card's printed total — verify the values.";
        const tip = note ? `${base} (${note})` : base;
        return `<span class="lhc-conf lhc-conf-${level}" title="${this._esc(tip)}">
            <span class="lhc-conf-dot"></span>${score}%
        </span>`;
    }

    _esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
}

const lotHistoryCards = new LotHistoryCardsModule();
console.log("[LotHistoryCards] Module ready.");

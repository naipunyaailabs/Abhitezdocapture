/**
 * Register AI Extractor — My Templates Only
 * Extracts structured table data from handwritten/printed registers
 * using user-saved templates.
 */

console.log("[Register] Module loading...");

class RegisterExtractorModule {
    constructor() {
        this.state = {
            templates: [],
            selectedTemplate: null,
            pendingFiles: null,
            result: null,
            editableRows: [],
            headers: [],
            activePageIndex: 0,
            isLoading: false,
            editingTemplate: null,   // null = create mode, object = edit mode
        };
        this._injected = false;
        this.init();
    }

    init() {
        if (!this._injected) {
            this._injectOverlay();
            this._injectTemplatePicker();
            this._injectTemplateModal();
            this._injected = true;
        }
        console.log("[Register] Module initialized");
    }

    // ─── OVERLAY (Results) ────────────────────────────────────────────────────

    _injectOverlay() {
        const el = document.createElement('div');
        el.id = 'reg-overlay';
        el.className = 'reg-overlay';
        el.innerHTML = `
            <div class="reg-container">
                <div class="reg-header">
                    <div class="reg-header-left">
                        <div class="reg-logo-badge">📒</div>
                        <div>
                            <h2 class="reg-title">Register <span>Extractor</span></h2>
                            <p class="reg-subtitle" id="reg-subtitle">Processing...</p>
                        </div>
                    </div>
                    <div class="reg-header-right">
                        <button class="reg-btn-export" id="reg-export-btn" onclick="registerExtractor.exportExcel()">
                            📊 Export Excel
                        </button>
                        <button class="reg-btn-close" onclick="registerExtractor.close()">×</button>
                    </div>
                </div>
                <div class="reg-main" style="position:relative;">
                    <!-- Source Panel -->
                    <div class="reg-source-panel">
                        <div class="reg-panel-title">📄 Source Document</div>
                        <div class="reg-page-tabs" id="reg-page-tabs"></div>
                        <div class="reg-image-viewer" id="reg-image-viewer">
                            <p style="color:#475569;text-align:center;padding:2rem;font-size:0.85rem;">Loading...</p>
                        </div>
                    </div>
                    <!-- Data Panel -->
                    <div class="reg-data-panel">
                        <div class="reg-panel-title">✏️ Extracted Table (Editable)</div>
                        <div class="reg-table-toolbar">
                            <input class="reg-search" id="reg-search" placeholder="Search rows..." oninput="registerExtractor.filterRows(this.value)">
                            <button class="reg-toolbar-btn add" onclick="registerExtractor.addRow()">+ Row</button>
                            <button class="reg-toolbar-btn copy" id="reg-copy-btn" onclick="registerExtractor.copyTable()">Copy</button>
                        </div>
                        <div class="reg-table-wrapper">
                            <table class="reg-table" id="reg-table">
                                <thead id="reg-thead"></thead>
                                <tbody id="reg-tbody"></tbody>
                            </table>
                        </div>
                        <div class="reg-stats-bar">
                            <div class="reg-stat">Rows: <span id="reg-row-count">0</span></div>
                            <div class="reg-stat">Pages: <span id="reg-page-count">0</span></div>
                            <div class="reg-stat">Avg Confidence: <span id="reg-conf">–</span></div>
                        </div>
                    </div>
                    <!-- Loading -->
                    <div class="reg-loading" id="reg-loading">
                        <div class="reg-spinner"></div>
                        <p class="reg-loading-text">Extracting register data...</p>
                        <p class="reg-loading-sub">Vision AI is reading your document</p>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(el);
    }

    // ─── TEMPLATE PICKER ─────────────────────────────────────────────────────

    _injectTemplatePicker() {
        const el = document.createElement('div');
        el.id = 'reg-tmpl-overlay';
        el.className = 'reg-tmpl-overlay';
        el.innerHTML = `
            <div class="reg-tmpl-panel">
                <div class="reg-tmpl-header">
                    <div class="reg-tmpl-icon">📒</div>
                    <div>
                        <h2>Abhitex Register Extractor</h2>
                        <p>Select one of your saved templates to extract data from your document.</p>
                    </div>
                </div>
                <!-- Templates list -->
                <div id="reg-tmpl-list" class="reg-tmpl-list">
                    <p style="color:#64748b;font-size:0.875rem;text-align:center;padding:1.5rem 0;">Loading templates...</p>
                </div>
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;">
                    <span id="reg-selected-info" style="font-size:0.8rem;color:#a5b4fc;display:none;">
                        ✓ Template selected
                    </span>
                    <button class="reg-btn-new" onclick="registerExtractor.openCreateModal()">
                        ＋ New Template
                    </button>
                </div>
                <div class="reg-tmpl-panel-actions">
                    <button class="reg-btn reg-btn-secondary" onclick="registerExtractor.closePicker()">Cancel</button>
                    <button class="reg-btn reg-btn-primary" id="reg-start-btn" onclick="registerExtractor.startExtraction()" disabled>
                        🚀 Start Extraction
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(el);
    }

    // ─── TEMPLATE CREATE/EDIT MODAL ───────────────────────────────────────────

    _injectTemplateModal() {
        const el = document.createElement('div');
        el.id = 'reg-modal-overlay';
        el.className = 'reg-modal-overlay';
        el.innerHTML = `
            <div class="reg-modal">
                <div class="reg-modal-header">
                    <span class="reg-modal-title" id="reg-modal-title">Create Template</span>
                    <button class="reg-modal-close" onclick="registerExtractor.closeModal()">×</button>
                </div>
                <div class="reg-modal-body">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
                        <div class="reg-form-group">
                            <label>Template Name *</label>
                            <input id="reg-tmpl-name" placeholder="e.g. Textile Production Log">
                        </div>
                        <div class="reg-form-group">
                            <label>Register Type</label>
                            <input id="reg-tmpl-type" placeholder="e.g. production, stock, ledger" value="custom">
                        </div>
                    </div>
                    <div class="reg-form-group">
                        <label>Description (optional)</label>
                        <textarea id="reg-tmpl-desc" rows="2" placeholder="Describe when to use this template..."></textarea>
                    </div>
                    <div class="reg-form-group">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
                            <label style="margin:0;">Columns * <span style="color:#475569;font-weight:400;" id="reg-col-count">(0 defined)</span></label>
                        </div>
                        <div id="reg-col-list" style="display:flex;flex-direction:column;gap:0.4rem;max-height:260px;overflow-y:auto;padding-right:2px;"></div>
                        <button class="reg-add-col-btn" onclick="registerExtractor.addColumn()">＋ Add Column</button>
                        <p style="font-size:0.72rem;color:#475569;margin-top:0.4rem;">
                            Hints help the AI identify specific content (e.g. "4-digit lot number" or "decimal weight in KGS").
                        </p>
                    </div>
                </div>
                <div class="reg-modal-footer">
                    <button class="reg-btn reg-btn-secondary" onclick="registerExtractor.closeModal()">Cancel</button>
                    <button class="reg-btn reg-btn-primary" id="reg-modal-save-btn" onclick="registerExtractor.saveTemplate()">
                        💾 Save Template
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(el);
    }

    // ─── OPEN / CLOSE ─────────────────────────────────────────────────────────

    open(files) {
        this.state.pendingFiles = files;
        this.state.selectedTemplate = null;
        this._updateStartBtn();
        document.getElementById('reg-tmpl-overlay').classList.add('active');
        this._loadTemplates();
    }

    closePicker() { document.getElementById('reg-tmpl-overlay').classList.remove('active'); }

    close() {
        document.getElementById('reg-overlay').classList.remove('active');
        document.getElementById('reg-tmpl-overlay').classList.remove('active');
    }

    openCreateModal() {
        this.state.editingTemplate = null;
        document.getElementById('reg-modal-title').textContent = 'Create Template';
        document.getElementById('reg-tmpl-name').value = '';
        document.getElementById('reg-tmpl-type').value = 'custom';
        document.getElementById('reg-tmpl-desc').value = '';
        document.getElementById('reg-col-list').innerHTML = '';
        this.addColumn(); this.addColumn(); this.addColumn();
        this._updateColCount();
        document.getElementById('reg-modal-overlay').classList.add('active');
    }

    openEditModal(tmpl) {
        this.state.editingTemplate = tmpl;
        document.getElementById('reg-modal-title').textContent = 'Edit Template';
        document.getElementById('reg-tmpl-name').value = tmpl.name || '';
        document.getElementById('reg-tmpl-type').value = tmpl.register_type || 'custom';
        document.getElementById('reg-tmpl-desc').value = tmpl.description || '';
        const list = document.getElementById('reg-col-list');
        list.innerHTML = '';
        const hints = tmpl.extraction_hints || {};
        (tmpl.columns || []).forEach(col => this._appendColRow(col, hints[col] || ''));
        this._updateColCount();
        document.getElementById('reg-modal-overlay').classList.add('active');
    }

    closeModal() {
        document.getElementById('reg-modal-overlay').classList.remove('active');
    }

    // ─── TEMPLATES CRUD ───────────────────────────────────────────────────────

    async _loadTemplates() {
        const listEl = document.getElementById('reg-tmpl-list');
        listEl.innerHTML = '<p style="color:#64748b;font-size:0.875rem;text-align:center;padding:1.5rem 0;">Loading templates...</p>';
        try {
            const token = this._getToken();
            const res = await fetch('/api/register/user-templates', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const json = await res.json();
            if (json.success) {
                this.state.templates = json.data.templates || [];
                this._renderTemplateList();
            } else {
                listEl.innerHTML = `<p style="color:#f87171;font-size:0.85rem;text-align:center;padding:1.5rem 0;">${json.detail || 'Failed to load templates'}</p>`;
            }
        } catch (e) {
            listEl.innerHTML = `<p style="color:#f87171;font-size:0.85rem;text-align:center;padding:1.5rem 0;">Error loading templates.</p>`;
        }
    }

    _renderTemplateList() {
        const listEl = document.getElementById('reg-tmpl-list');
        const templates = this.state.templates;
        if (!templates.length) {
            listEl.innerHTML = `
                <div class="reg-tmpl-empty">
                    <div class="reg-tmpl-empty-icon">📋</div>
                    <p>No templates yet. Create your first template to get started.</p>
                </div>`;
            return;
        }
        listEl.innerHTML = templates.map(t => {
            const isSelected = this.state.selectedTemplate?.id === t.id;
            const colTags = (t.columns || []).slice(0, 6).map(c =>
                `<span class="reg-col-tag">${c}</span>`).join('');
            const more = t.columns?.length > 6 ? `<span class="reg-col-tag">+${t.columns.length - 6} more</span>` : '';
            return `
                <div class="reg-tmpl-item${isSelected ? ' selected' : ''}" onclick="registerExtractor.selectTemplate('${t.id}')">
                    <div class="reg-tmpl-item-info">
                        <div class="reg-tmpl-item-name">${this._esc(t.name)}</div>
                        ${t.description ? `<div class="reg-tmpl-item-desc">${this._esc(t.description)}</div>` : ''}
                        <div class="reg-tmpl-cols">${colTags}${more}</div>
                    </div>
                    <div class="reg-tmpl-actions">
                        <button class="reg-tmpl-btn-icon" title="Edit" onclick="event.stopPropagation(); registerExtractor.openEditModal(${JSON.stringify(t).replace(/"/g,'&quot;')})">✏️</button>
                        <button class="reg-tmpl-btn-icon del" title="Delete" onclick="event.stopPropagation(); registerExtractor.confirmDelete('${t.id}', '${this._esc(t.name)}')">🗑️</button>
                    </div>
                </div>`;
        }).join('');
    }

    selectTemplate(id) {
        const tmpl = this.state.templates.find(t => t.id === id);
        this.state.selectedTemplate = (this.state.selectedTemplate?.id === id) ? null : tmpl;
        this._updateStartBtn();
        this._renderTemplateList();
    }

    _updateStartBtn() {
        const btn = document.getElementById('reg-start-btn');
        const info = document.getElementById('reg-selected-info');
        if (!btn) return;
        if (this.state.selectedTemplate) {
            btn.disabled = false;
            if (info) {
                info.style.display = 'block';
                info.textContent = `✓ "${this.state.selectedTemplate.name}" (${this.state.selectedTemplate.columns?.length || 0} cols)`;
            }
        } else {
            btn.disabled = true;
            if (info) info.style.display = 'none';
        }
    }

    // ─── COLUMN MANAGEMENT (modal) ────────────────────────────────────────────

    addColumn() {
        this._appendColRow('', '');
        this._updateColCount();
    }

    _appendColRow(name = '', hint = '') {
        const list = document.getElementById('reg-col-list');
        const row = document.createElement('div');
        row.className = 'reg-col-row';
        row.innerHTML = `
            <input placeholder="Column name" value="${this._esc(name)}" oninput="registerExtractor._updateColCount()">
            <input placeholder="Extraction hint (optional)" value="${this._esc(hint)}">
            <button class="reg-col-remove" onclick="registerExtractor._removeCol(this)" title="Remove">×</button>
        `;
        list.appendChild(row);
    }

    _removeCol(btn) {
        const list = document.getElementById('reg-col-list');
        if (list.children.length <= 1) { alert('At least one column is required.'); return; }
        btn.closest('.reg-col-row').remove();
        this._updateColCount();
    }

    _updateColCount() {
        const list = document.getElementById('reg-col-list');
        const defined = Array.from(list?.querySelectorAll('.reg-col-row') || [])
            .filter(r => r.querySelector('input')?.value?.trim()).length;
        const el = document.getElementById('reg-col-count');
        if (el) el.textContent = `(${defined} defined)`;
    }

    _getColData() {
        const rows = document.querySelectorAll('#reg-col-list .reg-col-row');
        const columns = [], hints = {};
        rows.forEach(row => {
            const inputs = row.querySelectorAll('input');
            const name = inputs[0]?.value?.trim();
            const hint = inputs[1]?.value?.trim();
            if (name) {
                columns.push(name);
                if (hint) hints[name] = hint;
            }
        });
        return { columns, hints: Object.keys(hints).length ? hints : null };
    }

    // ─── SAVE TEMPLATE ────────────────────────────────────────────────────────

    async saveTemplate() {
        const name = document.getElementById('reg-tmpl-name').value.trim();
        const register_type = document.getElementById('reg-tmpl-type').value.trim() || 'custom';
        const description = document.getElementById('reg-tmpl-desc').value.trim();
        const { columns, hints } = this._getColData();

        if (!name) { alert('Template name is required.'); return; }
        if (!columns.length) { alert('At least one column is required.'); return; }

        const saveBtn = document.getElementById('reg-modal-save-btn');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';

        try {
            const token = this._getToken();
            const payload = { name, register_type, description, columns, extraction_hints: hints };
            let url = '/api/register/user-templates';
            let method = 'POST';

            if (this.state.editingTemplate) {
                url = `/api/register/user-templates/${this.state.editingTemplate.id}`;
                method = 'PUT';
            }

            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(payload),
            });
            const json = await res.json();
            if (!json.success) throw new Error(json.detail || 'Failed to save template');

            // Update local state
            if (this.state.editingTemplate) {
                this.state.templates = this.state.templates.map(t =>
                    t.id === this.state.editingTemplate.id ? json.data : t);
                if (this.state.selectedTemplate?.id === this.state.editingTemplate.id) {
                    this.state.selectedTemplate = json.data;
                    this._updateStartBtn();
                }
            } else {
                this.state.templates.unshift(json.data);
            }
            this._renderTemplateList();
            this.closeModal();
        } catch (e) {
            alert(e.message || 'Error saving template.');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = '💾 Save Template';
        }
    }

    // ─── DELETE TEMPLATE ──────────────────────────────────────────────────────

    confirmDelete(id, name) {
        if (!confirm(`Delete template "${name}"? This cannot be undone.`)) return;
        this._deleteTemplate(id);
    }

    async _deleteTemplate(id) {
        try {
            const token = this._getToken();
            const res = await fetch(`/api/register/user-templates/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            const json = await res.json();
            if (!json.success) throw new Error(json.detail || 'Delete failed');
            this.state.templates = this.state.templates.filter(t => t.id !== id);
            if (this.state.selectedTemplate?.id === id) {
                this.state.selectedTemplate = null;
                this._updateStartBtn();
            }
            this._renderTemplateList();
        } catch (e) {
            alert(e.message || 'Error deleting template.');
        }
    }

    // ─── EXTRACTION ───────────────────────────────────────────────────────────

    async startExtraction() {
        if (!this.state.pendingFiles || !this.state.selectedTemplate) return;

        this.closePicker();
        const overlay = document.getElementById('reg-overlay');
        overlay.classList.add('active');
        document.getElementById('reg-loading').classList.add('active');

        const fd = new FormData();
        fd.append('document', this.state.pendingFiles[0]);
        fd.append('user_template_id', this.state.selectedTemplate.id);

        try {
            const token = this._getToken();
            const res = await fetch('/api/register/extract', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: fd,
            });
            const json = await res.json();
            if (!json.success) throw new Error(json.detail || 'Extraction failed');

            const data = json.data;
            this.state.result = data;
            this.state.headers = data.headers || [];
            this.state.editableRows = (data.rows || []).map(r => ({ ...r }));
            this.state.activePageIndex = 0;

            this._renderResults();
        } catch (e) {
            alert('Extraction error: ' + (e.message || 'Unknown error'));
            overlay.classList.remove('active');
        } finally {
            document.getElementById('reg-loading').classList.remove('active');
        }
    }

    // ─── RENDER RESULTS ───────────────────────────────────────────────────────

    _renderResults() {
        const data = this.state.result;
        const headers = this.state.headers;

        // Subtitle
        const sub = document.getElementById('reg-subtitle');
        if (sub) sub.textContent = `${data.total_rows} rows · ${data.total_pages} page(s) · ${data.filename}`;

        // Stats
        const confPct = Math.round((data.average_confidence || 0) * 100);
        document.getElementById('reg-row-count').textContent = data.total_rows || 0;
        document.getElementById('reg-page-count').textContent = data.total_pages || 0;
        document.getElementById('reg-conf').textContent = `${confPct}%`;

        // Page tabs
        const tabs = document.getElementById('reg-page-tabs');
        const pages = data.pages || [];
        tabs.innerHTML = pages.map((p, i) =>
            `<button class="reg-page-tab${i === 0 ? ' active' : ''}" onclick="registerExtractor._switchPage(${i})">
                P${p.page_number}
            </button>`
        ).join('');

        this._renderImage(0);
        this._renderTable(this.state.editableRows);
    }

    _switchPage(idx) {
        this.state.activePageIndex = idx;
        document.querySelectorAll('.reg-page-tab').forEach((t, i) =>
            t.classList.toggle('active', i === idx));
        this._renderImage(idx);
    }

    _renderImage(idx) {
        const pages = this.state.result?.pages || [];
        const viewer = document.getElementById('reg-image-viewer');
        if (!pages[idx]) { viewer.innerHTML = ''; return; }
        viewer.innerHTML = `<img src="${pages[idx].image_url}" alt="Page ${pages[idx].page_number}">`;
    }

    _renderTable(rows) {
        const headers = this.state.headers;
        const thead = document.getElementById('reg-thead');
        const tbody = document.getElementById('reg-tbody');

        // Headers
        thead.innerHTML = `<tr>
            <th class="reg-row-num">#</th>
            ${headers.map(h => `<th>${this._esc(h)}</th>`).join('')}
        </tr>`;

        // Rows
        if (!rows || !rows.length) {
            tbody.innerHTML = `<tr><td colspan="${headers.length + 1}" style="text-align:center;color:#475569;padding:2rem;">No rows extracted</td></tr>`;
            return;
        }
        tbody.innerHTML = rows.map((row, ri) => `
            <tr>
                <td class="reg-row-num">${ri + 1}</td>
                ${headers.map(h =>
                    `<td><input value="${this._esc(row[h] || '')}" onchange="registerExtractor._updateCell(${ri}, '${this._esc(h)}', this.value)" oninput="registerExtractor._updateCell(${ri}, '${this._esc(h)}', this.value)"></td>`
                ).join('')}
            </tr>`).join('');
    }

    filterRows(search) {
        const headers = this.state.headers;
        const filtered = search
            ? this.state.editableRows.filter(row =>
                headers.some(h => String(row[h] || '').toLowerCase().includes(search.toLowerCase())))
            : this.state.editableRows;
        this._renderTable(filtered);
    }

    _updateCell(rowIdx, col, value) {
        if (this.state.editableRows[rowIdx]) {
            this.state.editableRows[rowIdx][col] = value;
        }
    }

    addRow() {
        const blank = {};
        this.state.headers.forEach(h => { blank[h] = ''; });
        this.state.editableRows.push(blank);
        this._renderTable(this.state.editableRows);
        document.getElementById('reg-row-count').textContent = this.state.editableRows.length;
    }

    copyTable() {
        if (!this.state.editableRows.length) return;
        const rows = [
            this.state.headers.join('\t'),
            ...this.state.editableRows.map(r => this.state.headers.map(h => r[h] || '').join('\t')),
        ];
        navigator.clipboard.writeText(rows.join('\n')).then(() => {
            const btn = document.getElementById('reg-copy-btn');
            if (btn) { btn.textContent = 'Copied!'; setTimeout(() => { btn.textContent = 'Copy'; }, 2000); }
        });
    }

    // ─── EXPORT ───────────────────────────────────────────────────────────────

    async exportExcel() {
        if (!this.state.editableRows.length) return;
        const btn = document.getElementById('reg-export-btn');
        btn.disabled = true;
        btn.textContent = '⏳ Exporting...';
        try {
            const token = this._getToken();
            const res = await fetch('/api/register/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    rows: this.state.editableRows,
                    headers: this.state.headers,
                    title: `Register_${Date.now()}`,
                }),
            });
            if (!res.ok) throw new Error('Export failed');
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `Register_Export.xlsx`; a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            alert(e.message || 'Export error');
        } finally {
            btn.disabled = false;
            btn.textContent = '📊 Export Excel';
        }
    }

    // ─── HELPERS ──────────────────────────────────────────────────────────────

    _getToken() {
        return localStorage.getItem('token') ||
               document.cookie.split(';').find(c => c.trim().startsWith('token='))?.split('=')[1] || '';
    }

    _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}

// Global instance
const registerExtractor = new RegisterExtractorModule();

// ─── Entry point called from the service card form ───────────────────────────

function handleRegisterSubmit() {
    const filesInput = document.getElementById('reg-input-files');
    const folderInput = document.getElementById('reg-input-folder');

    const filesFromInput = filesInput?.files;
    const filesFromFolder = folderInput?.files;

    let files = null;
    if (filesFromInput && filesFromInput.length > 0) {
        files = Array.from(filesFromInput).filter(f =>
            /\.(pdf|png|jpg|jpeg|bmp|tiff?|webp)$/i.test(f.name));
    } else if (filesFromFolder && filesFromFolder.length > 0) {
        files = Array.from(filesFromFolder).filter(f =>
            /\.(pdf|png|jpg|jpeg|bmp|tiff?|webp)$/i.test(f.name));
    }

    if (!files || !files.length) {
        alert('Please select at least one supported file (PDF, image).');
        return;
    }

    // For now use first file (batch support can be added later)
    registerExtractor.open(files);
}

function switchRegisterMode(mode) {
    const filesGroup = document.getElementById('reg-files-input-group');
    const folderGroup = document.getElementById('reg-folder-input-group');
    const filesBtn = document.getElementById('reg-mode-files');
    const folderBtn = document.getElementById('reg-mode-folder');
    if (mode === 'files') {
        filesGroup.style.display = '';
        folderGroup.style.display = 'none';
        filesBtn?.classList.add('active');
        folderBtn?.classList.remove('active');
    } else {
        filesGroup.style.display = 'none';
        folderGroup.style.display = '';
        filesBtn?.classList.remove('active');
        folderBtn?.classList.add('active');
    }
}

console.log("[Register] Module ready.");

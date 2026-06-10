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
            // One entry per uploaded file: { filename, result, editableRows, headers,
            //   activePageIndex, status: 'pending'|'processing'|'success'|'error', error? }
            results: [],
            activeResultIndex: 0,
            isLoading: false,
            editingTemplate: null,   // null = create mode, object = edit mode
        };
        this._injected = false;
        this.init();
    }

    // Convenience accessors — operate on the currently selected file's result.
    get _activeResult() { return this.state.results[this.state.activeResultIndex] || null; }

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
                <div class="reg-file-tabs" id="reg-file-tabs" style="display:none;"></div>
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

        const files = Array.from(this.state.pendingFiles);
        const total = files.length;

        // Reset state for this batch
        this.state.results = files.map(f => ({
            filename: f.name,
            result: null,
            editableRows: [],
            headers: [],
            activePageIndex: 0,
            status: 'pending',
        }));
        this.state.activeResultIndex = 0;
        this._renderFileTabs();

        // Show file tabs strip only when there are multiple files
        const fileTabs = document.getElementById('reg-file-tabs');
        if (fileTabs) fileTabs.style.display = total > 1 ? '' : 'none';

        const loadingEl = document.getElementById('reg-loading');
        const loadingTextEl = loadingEl?.querySelector('.reg-loading-text');
        const loadingSubEl = loadingEl?.querySelector('.reg-loading-sub');
        loadingEl?.classList.add('active');

        const token = this._getToken();
        let firstSuccessShown = false;

        for (let i = 0; i < total; i++) {
            const file = files[i];
            this.state.results[i].status = 'processing';
            this._renderFileTabs();

            if (loadingTextEl) {
                loadingTextEl.textContent = total > 1
                    ? `Extracting file ${i + 1} of ${total}...`
                    : 'Extracting register data...';
            }
            if (loadingSubEl) loadingSubEl.textContent = file.name;

            try {
                const fd = new FormData();
                fd.append('document', file);
                fd.append('user_template_id', this.state.selectedTemplate.id);

                const res = await fetch('/api/register/extract', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` },
                    body: fd,
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    throw new Error(json.detail || `Extraction failed (HTTP ${res.status})`);
                }

                const data = json.data;
                const pages = data.pages || [];
                const orderedRows = [];
                pages.forEach(p => {
                    (p.rows || []).forEach(r => {
                        const clone = { ...r };
                        clone._page = p.page_number;
                        orderedRows.push(clone);
                    });
                });

                this.state.results[i].result = data;
                this.state.results[i].headers = data.headers || [];
                this.state.results[i].editableRows = orderedRows;
                this.state.results[i].activePageIndex = 0;
                this.state.results[i].status = 'success';

                // Once the first file succeeds, hide the loading overlay so the user
                // can already interact with that result while the rest stream in.
                if (!firstSuccessShown) {
                    firstSuccessShown = true;
                    this.state.activeResultIndex = i;
                    loadingEl?.classList.remove('active');
                    this._renderResults();
                } else if (this.state.activeResultIndex === i) {
                    this._renderResults();
                }
            } catch (e) {
                this.state.results[i].status = 'error';
                this.state.results[i].error = e.message || 'Unknown error';
                console.error(`[Register] Failed on ${file.name}:`, e);
            }
            this._renderFileTabs();
        }

        loadingEl?.classList.remove('active');

        // If every file failed, surface the first error and close.
        if (!firstSuccessShown) {
            const firstErr = this.state.results.find(r => r.status === 'error')?.error || 'Extraction failed';
            alert('Extraction error: ' + firstErr);
            overlay.classList.remove('active');
            return;
        }

        // If some files failed, let the user know how many.
        const failed = this.state.results.filter(r => r.status === 'error');
        if (failed.length) {
            console.warn(`[Register] ${failed.length} of ${total} file(s) failed.`);
        }
    }

    _renderFileTabs() {
        const el = document.getElementById('reg-file-tabs');
        if (!el) return;
        const results = this.state.results;
        if (results.length <= 1) { el.innerHTML = ''; return; }
        el.innerHTML = results.map((r, i) => {
            const icon = r.status === 'success' ? '✓'
                       : r.status === 'error'   ? '✕'
                       : r.status === 'processing' ? '⏳'
                       : '·';
            const cls = [
                'reg-file-tab',
                i === this.state.activeResultIndex ? 'active' : '',
                `status-${r.status}`,
            ].filter(Boolean).join(' ');
            const disabled = r.status !== 'success';
            const title = r.error ? `${r.filename} — ${r.error}` : r.filename;
            return `<button class="${cls}" ${disabled ? 'disabled' : ''} title="${this._esc(title)}" onclick="registerExtractor.switchFile(${i})">
                <span class="reg-file-tab-icon">${icon}</span>
                <span class="reg-file-tab-name">${this._esc(r.filename)}</span>
            </button>`;
        }).join('');
    }

    switchFile(i) {
        const r = this.state.results[i];
        if (!r || r.status !== 'success') return;
        this.state.activeResultIndex = i;
        this._renderFileTabs();
        this._renderResults();
    }

    // ─── RENDER RESULTS ───────────────────────────────────────────────────────

    _renderResults() {
        const active = this._activeResult;
        if (!active || !active.result) return;
        const data = active.result;

        // Subtitle
        const sub = document.getElementById('reg-subtitle');
        if (sub) sub.textContent = `${data.total_rows} rows · ${data.total_pages} page(s) · ${data.filename}`;

        // Stats
        const confPct = Math.round((data.average_confidence || 0) * 100);
        document.getElementById('reg-row-count').textContent = data.total_rows || 0;
        document.getElementById('reg-page-count').textContent = data.total_pages || 0;
        document.getElementById('reg-conf').textContent = `${confPct}%`;

        // Page tabs — index 0 = "All", then one tab per page in order
        const tabs = document.getElementById('reg-page-tabs');
        const pages = data.pages || [];
        const tabsHtml = [
            `<button class="reg-page-tab${active.activePageIndex === 0 ? ' active' : ''}" onclick="registerExtractor._switchPage(0)">All</button>`,
            ...pages.map((p, i) =>
                `<button class="reg-page-tab${active.activePageIndex === i + 1 ? ' active' : ''}" onclick="registerExtractor._switchPage(${i + 1})">P${p.page_number}</button>`
            ),
        ];
        tabs.innerHTML = tabsHtml.join('');

        const searchEl = document.getElementById('reg-search');
        if (searchEl) searchEl.value = '';

        this._renderImage(active.activePageIndex);
        this._renderTable(this._getVisibleRows());
    }

    _getVisibleRows() {
        const active = this._activeResult;
        if (!active) return [];
        const idx = active.activePageIndex;
        if (!idx) return active.editableRows;
        const pages = active.result?.pages || [];
        const pageNum = pages[idx - 1]?.page_number;
        if (!pageNum) return active.editableRows;

        const tagged = active.editableRows.filter(r => r._page === pageNum);
        if (tagged.length) return tagged;

        // Fallback: if rows lack the _page tag (older cached data), slice them
        // from the canonical array based on per-page row counts.
        let start = 0;
        for (let i = 0; i < idx - 1; i++) {
            start += (pages[i]?.rows || []).length;
        }
        const count = (pages[idx - 1]?.rows || []).length;
        return active.editableRows.slice(start, start + count);
    }

    _switchPage(idx) {
        const active = this._activeResult;
        if (!active) return;
        active.activePageIndex = idx;
        document.querySelectorAll('.reg-page-tab').forEach((t, i) =>
            t.classList.toggle('active', i === idx));
        this._renderImage(idx);
        const searchEl = document.getElementById('reg-search');
        if (searchEl) searchEl.value = '';
        const visible = this._getVisibleRows();
        this._renderTable(visible);
        this._updateStats(visible);
    }

    _updateStats(visibleRows) {
        const active = this._activeResult;
        if (!active) return;
        const total = active.editableRows.length;
        const totalPages = (active.result?.pages || []).length;
        const idx = active.activePageIndex;
        const rowCountEl = document.getElementById('reg-row-count');
        const pageCountEl = document.getElementById('reg-page-count');
        if (rowCountEl) {
            rowCountEl.textContent = idx === 0
                ? total
                : `${visibleRows.length} (of ${total})`;
        }
        if (pageCountEl) {
            pageCountEl.textContent = idx === 0
                ? totalPages
                : `${idx} of ${totalPages}`;
        }
    }

    _renderImage(idx) {
        const active = this._activeResult;
        const pages = active?.result?.pages || [];
        const viewer = document.getElementById('reg-image-viewer');
        // idx 0 = "All" — show first page's image as default
        const pageIdx = idx === 0 ? 0 : idx - 1;
        if (!pages[pageIdx]) { viewer.innerHTML = ''; return; }
        viewer.innerHTML = `<img src="${pages[pageIdx].image_url}" alt="Page ${pages[pageIdx].page_number}">`;
    }

    _renderTable(rows) {
        const active = this._activeResult;
        if (!active) return;
        const headers = active.headers;
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
        // Edits must apply to the canonical editableRows array, not the (possibly filtered) view.
        tbody.innerHTML = rows.map((row, ri) => {
            const realIdx = active.editableRows.indexOf(row);
            return `
            <tr>
                <td class="reg-row-num">${ri + 1}</td>
                ${headers.map(h =>
                    `<td><input value="${this._esc(row[h] || '')}" onchange="registerExtractor._updateCell(${realIdx}, '${this._esc(h)}', this.value)" oninput="registerExtractor._updateCell(${realIdx}, '${this._esc(h)}', this.value)"></td>`
                ).join('')}
            </tr>`;
        }).join('');
    }

    filterRows(search) {
        const active = this._activeResult;
        if (!active) return;
        const headers = active.headers;
        const base = this._getVisibleRows();
        const filtered = search
            ? base.filter(row =>
                headers.some(h => String(row[h] || '').toLowerCase().includes(search.toLowerCase())))
            : base;
        this._renderTable(filtered);
    }

    _updateCell(rowIdx, col, value) {
        const active = this._activeResult;
        if (active?.editableRows[rowIdx]) {
            active.editableRows[rowIdx][col] = value;
        }
    }

    addRow() {
        const active = this._activeResult;
        if (!active) return;
        const blank = {};
        active.headers.forEach(h => { blank[h] = ''; });
        // Tag new row with the currently viewed page (or 0 for "All")
        const idx = active.activePageIndex;
        const pages = active.result?.pages || [];
        blank._page = idx ? (pages[idx - 1]?.page_number || 0) : 0;
        active.editableRows.push(blank);
        this._renderTable(this._getVisibleRows());
        document.getElementById('reg-row-count').textContent = active.editableRows.length;
    }

    copyTable() {
        const active = this._activeResult;
        if (!active?.editableRows.length) return;
        const rows = [
            active.headers.join('\t'),
            ...active.editableRows.map(r => active.headers.map(h => r[h] || '').join('\t')),
        ];
        navigator.clipboard.writeText(rows.join('\n')).then(() => {
            const btn = document.getElementById('reg-copy-btn');
            if (btn) { btn.textContent = 'Copied!'; setTimeout(() => { btn.textContent = 'Copy'; }, 2000); }
        });
    }

    // ─── EXPORT ───────────────────────────────────────────────────────────────

    async exportExcel() {
        // Combine rows from every successfully-extracted file into a single sheet.
        // Headers come from the first successful file; if later files use different
        // headers, their extra columns are appended so no data is lost.
        const successes = this.state.results.filter(r => r.status === 'success' && r.editableRows.length);
        if (!successes.length) return;

        const headers = [];
        const seen = new Set();
        successes.forEach(r => {
            (r.headers || []).forEach(h => {
                if (!seen.has(h)) { seen.add(h); headers.push(h); }
            });
        });

        const combinedRows = [];
        successes.forEach(r => {
            r.editableRows.forEach(row => {
                const clean = {};
                headers.forEach(h => { clean[h] = row[h] || ''; });
                combinedRows.push(clean);
            });
        });

        const btn = document.getElementById('reg-export-btn');
        btn.disabled = true;
        const origText = btn.textContent;
        btn.textContent = '⏳ Exporting...';
        try {
            const token = this._getToken();
            const res = await fetch('/api/register/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    rows: combinedRows,
                    headers,
                    title: `Register_Export_${Date.now()}`,
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
            btn.textContent = origText;
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

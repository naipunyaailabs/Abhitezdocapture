/**
 * ExtractIQ - Intelligent Handwritten Data Extraction Module
 * User defines input fields → AI extracts data → Editable + Exportable as Excel
 */

console.log("ExtractIQ Module loading...");

class ExtractIQModule {
    constructor() {
        this.state = {
            records: [],
            activePageIndex: 0,
            isLoading: false,
            processedAt: null,
            fieldDefinitions: [],
            pendingFiles: null
        };
        this.init();
    }

    init() {
        if (!document.getElementById('eiq-overlay')) {
            this.injectOverlay();
        }
        if (!document.getElementById('eiq-setup-overlay')) {
            this.injectSetupPanel();
        }
        console.log("ExtractIQ Module initialized");
    }

    // ─── SETUP PANEL (Field Definition) ──────────────────────

    injectSetupPanel() {
        const setup = document.createElement('div');
        setup.id = 'eiq-setup-overlay';
        setup.className = 'eiq-setup-overlay';
        setup.innerHTML = `
            <div class="eiq-setup-panel">
                <div class="eiq-setup-header">
                    <div class="eiq-setup-icon">🧠</div>
                    <h2>ExtractIQ — Define Your Fields</h2>
                    <p>Add the columns/fields you want to extract from your documents.<br>
                       The AI will map handwritten & printed data to these fields.</p>
                </div>

                <div class="eiq-field-list" id="eiq-field-list">
                    <!-- Dynamic field rows will be inserted here -->
                </div>

                <button class="eiq-add-field-btn" onclick="extractIQ.addField()">
                    ＋ Add Another Field
                </button>

                <div class="eiq-setup-actions">
                    <button class="eiq-btn-cancel" onclick="extractIQ.closeSetup()">Cancel</button>
                    <button class="eiq-btn-start" id="eiq-start-btn" onclick="extractIQ.startExtraction()">
                        🚀 Start Extraction
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(setup);
    }

    // ─── MAIN OVERLAY (Extraction Results) ───────────────────

    injectOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'eiq-overlay';
        overlay.className = 'eiq-overlay';
        overlay.innerHTML = `
            <div class="eiq-container">
                <div class="eiq-header">
                    <div class="eiq-header-left">
                        <div class="eiq-logo-badge">🧠</div>
                        <div>
                            <h2 class="eiq-title">Extract<span>IQ</span></h2>
                            <p class="eiq-subtitle" id="eiq-processed-time">Processing...</p>
                        </div>
                    </div>
                    <div class="eiq-header-right">
                        <button class="eiq-btn eiq-btn-export" onclick="extractIQ.exportAll()">
                            📊 Export Excel
                        </button>
                        <button class="eiq-btn eiq-btn-close" onclick="extractIQ.close()">×</button>
                    </div>
                </div>

                <div class="eiq-main">
                    <!-- Left: Source Document -->
                    <div class="eiq-source-panel">
                        <h3 class="eiq-panel-title">
                            <span class="eiq-panel-title-icon">📄</span> Source Document
                        </h3>
                        <div class="eiq-page-nav">
                            <div id="eiq-page-tabs" class="eiq-tabs"></div>
                        </div>
                        <div id="eiq-image-viewer" class="eiq-image-viewer">
                            <div class="eiq-loading-placeholder">Upload a document to begin extraction...</div>
                        </div>
                    </div>

                    <!-- Right: Extracted Data -->
                    <div class="eiq-data-panel">
                        <h3 class="eiq-panel-title">
                            <span class="eiq-panel-title-icon">✏️</span> Extracted Data
                        </h3>
                        <div class="eiq-fields-table-wrapper">
                            <table class="eiq-fields-table" id="eiq-fields-table">
                                <thead>
                                    <tr>
                                        <th>Field Name</th>
                                        <th>Extracted Value (Editable)</th>
                                    </tr>
                                </thead>
                                <tbody id="eiq-fields-body">
                                </tbody>
                            </table>
                        </div>
                        <div class="eiq-page-summary" id="eiq-page-summary"></div>
                    </div>
                </div>

                <!-- Loading Overlay -->
                <div id="eiq-loading" class="eiq-loading">
                    <div class="eiq-spinner-container">
                        <div class="eiq-spinner-ring"></div>
                        <div class="eiq-spinner-ring"></div>
                        <div class="eiq-spinner-ring"></div>
                    </div>
                    <p class="eiq-loading-text" id="eiq-loading-text">Analyzing document...</p>
                    <p class="eiq-loading-subtext">ExtractIQ is reading handwritten content with Vision AI</p>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    // ─── FIELD MANAGEMENT ────────────────────────────────────

    openSetup(files) {
        this.state.pendingFiles = files;
        this.state.fieldDefinitions = [];

        const setupOverlay = document.getElementById('eiq-setup-overlay');
        const fieldList = document.getElementById('eiq-field-list');

        // Start with 3 default empty fields
        fieldList.innerHTML = '';
        this.addField();
        this.addField();
        this.addField();

        setupOverlay.classList.add('active');
    }

    addField() {
        const fieldList = document.getElementById('eiq-field-list');
        const index = fieldList.children.length;
        const fieldNum = index + 1;

        const item = document.createElement('div');
        item.className = 'eiq-field-item';
        item.dataset.index = index;
        item.innerHTML = `
            <div class="eiq-field-num">${fieldNum}</div>
            <div class="eiq-field-inputs">
                <input type="text" class="eiq-field-input eiq-field-key" 
                       placeholder="Field key (e.g., name, date, amount)"
                       oninput="extractIQ.autoFillLabel(this)">
                <input type="text" class="eiq-field-input eiq-field-label-input" 
                       placeholder="Display label (auto-filled)">
            </div>
            <button class="eiq-field-remove" onclick="extractIQ.removeField(this)" title="Remove field">×</button>
        `;
        fieldList.appendChild(item);

        // Focus the new field
        item.querySelector('.eiq-field-key').focus();
    }

    autoFillLabel(inputEl) {
        const fieldItem = inputEl.closest('.eiq-field-item');
        const labelInput = fieldItem.querySelector('.eiq-field-label-input');
        const key = inputEl.value.trim();

        // Auto-fill label only if user hasn't manually typed one
        if (!labelInput.dataset.manual) {
            labelInput.value = key
                .replace(/[_-]/g, ' ')
                .replace(/\b\w/g, l => l.toUpperCase());
        }
    }

    removeField(btn) {
        const fieldList = document.getElementById('eiq-field-list');
        if (fieldList.children.length <= 1) {
            alert("You need at least one field.");
            return;
        }
        btn.closest('.eiq-field-item').remove();
        this.reindexFields();
    }

    reindexFields() {
        const items = document.querySelectorAll('#eiq-field-list .eiq-field-item');
        items.forEach((item, i) => {
            item.dataset.index = i;
            item.querySelector('.eiq-field-num').textContent = i + 1;
        });
    }

    collectFieldDefinitions() {
        const items = document.querySelectorAll('#eiq-field-list .eiq-field-item');
        const fields = [];

        items.forEach(item => {
            const key = item.querySelector('.eiq-field-key').value.trim();
            let label = item.querySelector('.eiq-field-label-input').value.trim();

            if (key) {
                // Sanitize key: lowercase, no spaces, replace special chars with underscore
                const sanitizedKey = key.toLowerCase()
                    .replace(/\s+/g, '_')
                    .replace(/[^a-z0-9_]/g, '');

                if (!label) {
                    label = sanitizedKey.replace(/_/g, ' ')
                        .replace(/\b\w/g, l => l.toUpperCase());
                }

                fields.push({
                    key: sanitizedKey,
                    label: label,
                    description: ""
                });
            }
        });

        return fields;
    }

    closeSetup() {
        document.getElementById('eiq-setup-overlay').classList.remove('active');
        this.state.pendingFiles = null;
    }

    // ─── EXTRACTION PROCESS ──────────────────────────────────

    async startExtraction() {
        const fieldDefs = this.collectFieldDefinitions();

        if (fieldDefs.length === 0) {
            alert("Please define at least one field with a key name.");
            return;
        }

        // Check for duplicate keys
        const keys = fieldDefs.map(f => f.key);
        const uniqueKeys = new Set(keys);
        if (uniqueKeys.size !== keys.length) {
            alert("Duplicate field keys found. Each field must have a unique key.");
            return;
        }

        this.state.fieldDefinitions = fieldDefs;
        const filesToProcess = this.state.pendingFiles;

        // Close setup and start processing
        this.closeSetup();
        await this.processFiles(filesToProcess);
    }

    async processFiles(files) {
        if (!files || files.length === 0) {
            alert("No files to process.");
            return;
        }

        const token = localStorage.getItem('token');
        if (!token) {
            alert("Session expired. Please login again.");
            return;
        }

        // Reset state
        this.state.records = [];
        this.state.activePageIndex = 0;
        this.state.processedAt = new Date();

        // Show overlay and loading
        document.getElementById('eiq-overlay').classList.add('active');

        try {
            // Filter for supported files
            const supportedExts = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'];
            const validFiles = Array.from(files).filter(f => {
                const ext = '.' + f.name.split('.').pop().toLowerCase();
                return supportedExts.includes(ext);
            });

            if (validFiles.length === 0) {
                throw new Error("No supported files found. Supported: PDF, JPG, PNG, BMP, TIFF, WebP");
            }

            const fieldsJSON = JSON.stringify(this.state.fieldDefinitions);

            for (let i = 0; i < validFiles.length; i++) {
                const file = validFiles[i];
                this.showLoading(`Processing file ${i + 1} of ${validFiles.length}: ${file.name}...`);

                const formData = new FormData();
                formData.append('document', file);
                formData.append('fields', fieldsJSON);

                const response = await fetch('/api/extract-iq/extract', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` },
                    body: formData
                });

                if (!response.ok) {
                    const errText = await response.text();
                    throw new Error(`Error processing ${file.name} (${response.status}): ${errText.substring(0, 200)}`);
                }

                const result = await response.json();

                if (result.success && result.data && result.data.records) {
                    this.state.records = this.state.records.concat(result.data.records);
                    // Store field definitions from response if available
                    if (result.data.field_definitions) {
                        this.state.fieldDefinitions = result.data.field_definitions;
                    }
                } else {
                    console.warn(`Extraction failed for ${file.name}`, result.detail);
                }
            }

            if (this.state.records.length > 0) {
                this.render();
            } else {
                alert("Extraction failed - no records returned from any file.");
                this.close();
            }
        } catch (e) {
            console.error("ExtractIQ Error:", e);
            alert(`ExtractIQ Failed: ${e.message}`);
            if (this.state.records.length > 0) {
                this.render();
            } else {
                this.close();
            }
        } finally {
            this.hideLoading();
        }
    }

    // ─── RENDERING ───────────────────────────────────────────

    render() {
        const timeEl = document.getElementById('eiq-processed-time');
        if (timeEl && this.state.processedAt) {
            const opts = { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
            timeEl.textContent = `Processed: ${this.state.processedAt.toLocaleDateString('en-IN', opts)}`;
        }

        this.renderTabs();
        this.renderActivePage();
        this.renderSummary();
    }

    renderTabs() {
        const container = document.getElementById('eiq-page-tabs');
        if (!container) return;

        container.innerHTML = this.state.records.map((r, i) => `
            <button class="eiq-tab ${i === this.state.activePageIndex ? 'active' : ''}" 
                    onclick="extractIQ.switchPage(${i})">
                Page ${i + 1}
            </button>
        `).join('');
    }

    renderActivePage() {
        const record = this.state.records[this.state.activePageIndex];
        if (!record) return;

        // Render image
        const viewer = document.getElementById('eiq-image-viewer');
        if (viewer && record.image_url) {
            viewer.innerHTML = `<img src="${record.image_url}" alt="Page ${record.page_number}" class="eiq-page-img" />`;
        }

        // Render fields table
        const tbody = document.getElementById('eiq-fields-body');
        if (!tbody) return;

        const fields = record.fields || {};

        if (Object.keys(fields).length === 0) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;padding:2rem;color:#475569;">No fields extracted. The document may be unreadable.</td></tr>';
            return;
        }

        let rows = '';

        // Use field definitions order
        const fieldOrder = this.state.fieldDefinitions.map(f => f.key);

        // Also add any fields that came back but weren't in definitions
        const allFieldKeys = Object.keys(fields);
        for (const key of allFieldKeys) {
            if (!fieldOrder.includes(key)) {
                fieldOrder.push(key);
            }
        }

        for (const key of fieldOrder) {
            if (!(key in fields)) continue;

            const field = fields[key];
            const rawValue = field.edited_value !== undefined ? field.edited_value : (field.value || '');
            const value = (rawValue === null || rawValue === undefined) ? '' : String(rawValue);
            const confidence = field.confidence || 0;
            const isModified = field.is_modified || false;

            const fieldLabel = this.formatFieldName(key);

            let rowClass = '';
            if (isModified) {
                rowClass = 'eiq-row-modified';
            } else if (value && value.trim() !== '') {
                if (confidence >= 0.9) rowClass = 'eiq-row-high-conf';
                else if (confidence < 0.6) rowClass = 'eiq-row-low-conf';
            }

            const displayValue = value || '';
            const placeholder = value ? '' : 'Not found — enter manually';

            rows += `
                <tr class="${rowClass}">
                    <td class="eiq-field-name">
                        <span class="eiq-field-label">${fieldLabel}</span>
                        ${confidence > 0 ? `<span class="eiq-conf-indicator" style="color: ${this.getConfidenceColor(confidence)}">${(confidence * 100).toFixed(0)}%</span>` : ''}
                    </td>
                    <td class="eiq-field-value">
                        <textarea class="eiq-editable-field ${!value ? 'eiq-field-empty' : ''}" 
                                  data-field="${key}"
                                  placeholder="${placeholder}"
                                  oninput="extractIQ.updateField('${key}', this.value)">${this.escapeHtml(displayValue)}</textarea>
                    </td>
                </tr>
            `;
        }

        tbody.innerHTML = rows;
    }

    getConfidenceColor(conf) {
        if (conf >= 0.9) return '#22c55e';
        if (conf >= 0.6) return '#fbbf24';
        return '#fb923c';
    }

    renderSummary() {
        const summary = document.getElementById('eiq-page-summary');
        if (!summary) return;

        const total = this.state.records.length;
        const current = this.state.activePageIndex + 1;
        const fieldCount = this.state.fieldDefinitions.length;

        summary.innerHTML = `
            <div class="eiq-summary-info">
                <span class="eiq-summary-badge">Page ${current} of ${total}</span>
                <span class="eiq-separator">|</span>
                <span>${fieldCount} fields × ${total} pages</span>
                <span class="eiq-separator">|</span>
                <span>${total} record(s) will be exported</span>
            </div>
        `;
    }

    formatFieldName(key) {
        // Check if we have a label from field definitions
        const def = this.state.fieldDefinitions.find(f => f.key === key);
        if (def && def.label) return def.label;
        // Fallback: auto-format
        return key.replace(/[_-]/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // ─── INTERACTIONS ────────────────────────────────────────

    switchPage(index) {
        if (index >= 0 && index < this.state.records.length) {
            this.state.activePageIndex = index;
            this.render();
        }
    }

    updateField(key, value) {
        const record = this.state.records[this.state.activePageIndex];
        if (record && record.fields && record.fields[key]) {
            record.fields[key].edited_value = value;
            record.fields[key].is_modified = true;
        }
    }

    // ─── EXPORT ──────────────────────────────────────────────

    async exportAll() {
        const token = localStorage.getItem('token');
        if (!token) {
            alert("Session expired. Please login again.");
            return;
        }

        if (this.state.records.length === 0) {
            alert("No records to export.");
            return;
        }

        this.showLoading('Generating Excel file...');

        try {
            const response = await fetch('/api/extract-iq/export', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    validated_records: this.state.records,
                    field_definitions: this.state.fieldDefinitions
                })
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `ExtractIQ_${this.state.records.length}_Records_${Date.now()}.xlsx`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            } else {
                const err = await response.json().catch(() => ({ detail: 'Export failed' }));
                alert(err.detail || "Export failed");
            }
        } catch (e) {
            console.error("Export error:", e);
            alert("Network error during export");
        } finally {
            this.hideLoading();
        }
    }

    // ─── UI CONTROLS ─────────────────────────────────────────

    close() {
        const overlay = document.getElementById('eiq-overlay');
        if (overlay) overlay.classList.remove('active');
    }

    showLoading(text) {
        const el = document.getElementById('eiq-loading');
        const textEl = document.getElementById('eiq-loading-text');
        if (el) {
            el.style.display = 'flex';
            if (textEl) textEl.textContent = text;
        }
    }

    hideLoading() {
        const el = document.getElementById('eiq-loading');
        if (el) el.style.display = 'none';
    }
}

// Global instance
window.extractIQ = new ExtractIQModule();

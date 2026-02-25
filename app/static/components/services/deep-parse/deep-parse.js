/**
 * Deep Parse - Multi-Page PDF Validation Module
 * Side-by-side document view with editable extracted fields
 */

console.log("Deep Parse Module loading...");

class DeepParseModule {
    constructor() {
        this.state = {
            records: [],
            activePageIndex: 0,
            isLoading: false,
            processedAt: null
        };
        this.init();
    }

    init() {
        if (!document.getElementById('deep-parse-overlay')) {
            this.injectOverlay();
        }
        console.log("Deep Parse Module initialized");
    }

    injectOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'deep-parse-overlay';
        overlay.className = 'dp-overlay';
        overlay.innerHTML = `
            <div class="dp-container">
                <div class="dp-header">
                    <div class="dp-header-left">
                        <h2 class="dp-title">Structured Data</h2>
                        <p class="dp-subtitle" id="dp-processed-time">Processing...</p>
                    </div>
                    <div class="dp-header-right">
                        <button class="dp-btn dp-btn-primary" onclick="deepParse.exportAll()">Export Excel</button>
                        <button class="dp-btn dp-btn-close" onclick="deepParse.close()">&times;</button>
                    </div>
                </div>
                
                <div class="dp-main">
                    <!-- Left: Source Document -->
                    <div class="dp-source-panel">
                        <h3 class="dp-panel-title">Source Document</h3>
                        <div class="dp-page-nav">
                            <div id="dp-page-tabs" class="dp-tabs"></div>
                        </div>
                        <div id="dp-image-viewer" class="dp-image-viewer">
                            <div class="dp-loading-placeholder">Loading document...</div>
                        </div>
                    </div>
                    
                    <!-- Right: Extracted Data -->
                    <div class="dp-data-panel">
                        <h3 class="dp-panel-title">Extracted Data</h3>
                        <div class="dp-fields-table-wrapper">
                            <table class="dp-fields-table" id="dp-fields-table">
                                <thead>
                                    <tr>
                                        <th>Field Name</th>
                                        <th>Extracted Value (Editable)</th>
                                    </tr>
                                </thead>
                                <tbody id="dp-fields-body">
                                </tbody>
                            </table>
                        </div>
                        <div class="dp-page-summary" id="dp-page-summary"></div>
                    </div>
                </div>
                
                <!-- Loading Overlay -->
                <div id="dp-loading" class="dp-loading">
                    <div class="dp-spinner"></div>
                    <p id="dp-loading-text">Analyzing document...</p>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    async processFiles(files) {
        console.log("processFiles called with:", files);
        if (!files || files.length === 0) {
            alert("Please select PDF file(s) first.");
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
        document.getElementById('deep-parse-overlay').classList.add('active');

        try {
            // Filter for PDFs only
            const pdfFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.pdf'));

            if (pdfFiles.length === 0) {
                throw new Error("No PDF files found in the selection/folder.");
            }

            for (let i = 0; i < pdfFiles.length; i++) {
                const file = pdfFiles[i];
                this.showLoading(`Processing file ${i + 1} of ${pdfFiles.length}: ${file.name}...`);

                const formData = new FormData();
                formData.append('document', file);

                console.log(`Fetching /api/deep-parse/extract for ${file.name}...`);
                const response = await fetch('/api/deep-parse/extract', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` },
                    body: formData
                });

                if (!response.ok) {
                    const errText = await response.text();
                    throw new Error(`Error processing ${file.name} (${response.status}): ${errText.substring(0, 200)}`);
                }

                const result = await response.json();
                console.log(`API Response for ${file.name}:`, result);

                if (result.success && result.data && result.data.records) {
                    // Append records from this file to the total batch
                    this.state.records = this.state.records.concat(result.data.records);
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
            console.error("Deep Parse Error:", e);
            alert(`Deep Parse Failed: ${e.message}`);
            // We keep established records if some succeeded
            if (this.state.records.length > 0) {
                this.render();
            } else {
                this.close();
            }
        } finally {
            this.hideLoading();
        }
    }

    render() {
        // Update processed time
        const timeEl = document.getElementById('dp-processed-time');
        if (timeEl && this.state.processedAt) {
            timeEl.textContent = `Processed on ${this.state.processedAt.toLocaleDateString()} ${this.state.processedAt.toLocaleTimeString()}`;
        }

        this.renderTabs();
        this.renderActivePage();
        this.renderSummary();
    }

    renderTabs() {
        const container = document.getElementById('dp-page-tabs');
        if (!container) return;

        container.innerHTML = this.state.records.map((r, i) => `
            <button class="dp-tab ${i === this.state.activePageIndex ? 'active' : ''}" 
                    onclick="deepParse.switchPage(${i})">
                Page ${i + 1}
            </button>
        `).join('');
    }

    renderActivePage() {
        const record = this.state.records[this.state.activePageIndex];
        if (!record) return;

        // Render image
        const viewer = document.getElementById('dp-image-viewer');
        if (viewer && record.image_url) {
            viewer.innerHTML = `<img src="${record.image_url}" alt="Page ${record.page_number}" class="dp-page-img" />`;
        }

        // Render fields table
        const tbody = document.getElementById('dp-fields-body');
        if (!tbody) return;

        const fields = record.fields || {};

        // Check if fields object is empty
        if (Object.keys(fields).length === 0) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;padding:2rem;color:#64748b;">No fields extracted. This may be due to poor OCR or processing error.</td></tr>';
            return;
        }

        let rows = '';
        let hasAnyValue = false;

        const fieldOrder = [
            "document_id", "supplier_name", "gst_no", "invoice_no", "invoice_date",
            "buyer_name", "buyer_gst", "buyer_address",
            "challan_no", "challan_date", "gate_entry_no", "gate_entry_date",
            "po_number", "item_code", "item_description",
            "hsn_code", "quantity", "unit_price", "total_amount",
            "cgst_amount", "sgst_amount", "igst_amount", "total_tax_amount", "grand_total", "discount"
        ];

        for (const key of fieldOrder) {
            if (!(key in fields)) continue;

            const field = fields[key];
            const rawValue = field.edited_value !== undefined ? field.edited_value : (field.value || '');
            const value = (rawValue === null || rawValue === undefined) ? '' : String(rawValue);
            const confidence = field.confidence || 0;
            const isModified = field.is_modified || false;

            if (value && value.trim() !== '') {
                hasAnyValue = true;
            }

            // Format field name nicely
            const fieldLabel = this.formatFieldName(key);

            // Determine row class based on confidence/modification
            let rowClass = '';
            if (isModified) {
                rowClass = 'row-modified';
            } else if (value && value.trim() !== '') {
                if (confidence >= 0.9) rowClass = 'row-high-conf';
                else if (confidence < 0.7) rowClass = 'row-low-conf';
            }

            const displayValue = value || '';
            const placeholder = value ? '' : 'Not found - you can manually enter data';

            rows += `
                <tr class="${rowClass}">
                    <td class="dp-field-name">
                        <span class="dp-field-label">Extracted &gt; ${fieldLabel}</span>
                        ${confidence > 0 ? `<span class="dp-conf-indicator" style="color: ${this.getConfidenceColor(confidence)}">${(confidence * 100).toFixed(0)}%</span>` : ''}
                    </td>
                    <td class="dp-field-value">
                        <textarea class="dp-editable-field ${!value ? 'field-empty' : ''}" 
                                  data-field="${key}"
                                  placeholder="${placeholder}"
                                  oninput="deepParse.updateField('${key}', this.value)">${this.escapeHtml(displayValue)}</textarea>
                    </td>
                </tr>
            `;
        }

        tbody.innerHTML = rows;
    }

    getConfidenceColor(conf) {
        if (conf >= 0.9) return '#22c55e';
        if (conf >= 0.7) return '#fbbf24';
        return '#ef4444';
    }

    renderSummary() {
        const summary = document.getElementById('dp-page-summary');
        if (!summary) return;

        const total = this.state.records.length;
        const current = this.state.activePageIndex + 1;

        summary.innerHTML = `
            <div class="dp-summary-info">
                <span>Page ${current} of ${total}</span>
                <span class="dp-separator">|</span>
                <span>${total} record(s) will be exported</span>
            </div>
        `;
    }

    formatFieldName(key) {
        const fieldLabels = {
            "document_id": "Document ID",
            "supplier_name": "Supplier Name",
            "gst_no": "GST No.",
            "invoice_no": "Invoice No.",
            "invoice_date": "Invoice Date",
            "buyer_name": "Buyer Name",
            "buyer_gst": "Buyer GST",
            "buyer_address": "Buyer Address",
            "challan_no": "Challan No.",
            "challan_date": "Challan Date",
            "gate_entry_no": "Gate Entry No.",
            "gate_entry_date": "Gate Entry Date",
            "po_number": "PO Number",
            "item_code": "Item Code",
            "item_description": "Item Description",
            "hsn_code": "HSN Code",
            "quantity": "Quantity",
            "unit_price": "Unit Price",
            "total_amount": "Total Amount",
            "cgst_amount": "CGST Amount",
            "sgst_amount": "SGST Amount",
            "igst_amount": "IGST Amount",
            "total_tax_amount": "Total Tax Amount",
            "grand_total": "Grand Total",
            "discount": "Discount"
        };
        return fieldLabels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

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

        this.showLoading('Generating Excel with all pages...');

        try {
            const response = await fetch('/api/deep-parse/export', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    validated_records: this.state.records
                })
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `DeepParse_${this.state.records.length}_Records_${Date.now()}.xlsx`;
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

    close() {
        const overlay = document.getElementById('deep-parse-overlay');
        if (overlay) {
            overlay.classList.remove('active');
        }
    }

    showLoading(text) {
        const el = document.getElementById('dp-loading');
        const textEl = document.getElementById('dp-loading-text');
        if (el) {
            el.style.display = 'flex';
            if (textEl) textEl.textContent = text;
        }
    }

    hideLoading() {
        const el = document.getElementById('dp-loading');
        if (el) el.style.display = 'none';
    }
}

// Global instance
window.deepParse = new DeepParseModule();

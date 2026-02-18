const API_BASE = '';

function openLogin() { document.getElementById('login-modal').style.display = 'flex'; }
function closeLogin() { document.getElementById('login-modal').style.display = 'none'; }

function scrollToId(id) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function showOverlay(title, content, isJson = false, isExcel = false, docUrl = null, isImage = false) {
    const panel = document.getElementById('overlay');
    const body = document.getElementById('result-body');
    const exportBtn = document.getElementById('excel-export-btn');

    document.getElementById('result-title').innerText = title;
    document.getElementById('result-meta').innerText = `Processed on ${new Date().toLocaleString()}`;

    exportBtn.style.display = isExcel ? 'block' : 'none';
    window.currentExportData = isExcel ? content : null;

    if (docUrl) {
        panel.classList.add('wide');

        let previewHtml;
        if (isImage) {
            previewHtml = `<div style="height:100%; overflow:auto; display:flex; justify-content:center; align-items:flex-start;"><img src="${docUrl}" style="max-width:100%; height:auto; border-radius:8px;"></div>`;
        } else {
            previewHtml = `<iframe src="${docUrl}" style="width:100%; height:100%; border:none; border-radius:8px; background:#fff;"></iframe>`;
        }

        let contentHtml;
        if (isExcel) {
            contentHtml = renderAsTable(content);
        } else if (isJson) {
            contentHtml = `<pre style="background: rgba(255,255,255,0.03); padding: 2rem; border-radius: 16px; border: 1px solid var(--glass-border); color: #fbbf24; font-family: monospace; font-size: 0.9rem;">${JSON.stringify(content, null, 2)}</pre>`;
        } else {
            const trimmed = content.trim();
            if (trimmed.startsWith('<') && (trimmed.includes('prose') || trimmed.includes('div'))) {
                contentHtml = trimmed;
            } else {
                contentHtml = marked.parse(content);
            }
        }

        body.innerHTML = `
            <div class="split-container">
                <div class="split-file">
                    <h3 style="margin-top:0; font-size:1.1rem; color:var(--text-muted);">Source Document</h3>
                    ${previewHtml}
                </div>
                <div class="split-data">
                    <h3 style="margin-top:0; font-size:1.1rem; color:var(--text-muted);">Extracted Data</h3>
                    ${contentHtml}
                </div>
            </div>
        `;
    } else {
        panel.classList.remove('wide');
        if (isExcel) {
            body.innerHTML = renderAsTable(content);
        } else if (isJson) {
            body.innerHTML = `<pre style="background: rgba(255,255,255,0.03); padding: 2rem; border-radius: 16px; border: 1px solid var(--glass-border); color: #fbbf24; font-family: monospace; font-size: 0.9rem;">${JSON.stringify(content, null, 2)}</pre>`;
        } else {
            const trimmed = content.trim();
            if (trimmed.startsWith('<') && (trimmed.includes('prose') || trimmed.includes('div'))) {
                body.innerHTML = trimmed;
            } else {
                body.innerHTML = marked.parse(content);
            }
        }
    }

    panel.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function flattenObject(obj, prefix = '') {
    let items = {};
    for (const [key, value] of Object.entries(obj)) {
        const newKey = prefix ? `${prefix}.${key}` : key;
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            Object.assign(items, flattenObject(value, newKey));
        } else if (Array.isArray(value)) {
            items[newKey] = value.map(item => typeof item === 'object' ? JSON.stringify(item) : item).join('; ');
        } else {
            items[newKey] = value;
        }
    }
    return items;
}

function renderAsTable(data) {
    let html = '<div style="overflow-x: auto; margin-top: 1rem;"><table class="prose" style="width: 100%; border-collapse: collapse;">';
    html += '<thead><tr><th style="background:#fbbf24; color:#000; padding: 1rem; border: 1px solid var(--glass-border); text-align: left;">Field Name</th><th style="background:#fbbf24; color:#000; padding: 1rem; border: 1px solid var(--glass-border); text-align: left;">Extracted Value</th></tr></thead><tbody>';

    const flatData = flattenObject(data);

    for (const [key, value] of Object.entries(flatData)) {
        const displayKey = key.split('.').map(s => s.charAt(0).toUpperCase() + s.slice(1).replace('_', ' ')).join(' > ');
        html += `<tr><td style="font-weight:700; color:#fbbf24; padding: 0.75rem; border: 1px solid var(--glass-border); font-size: 0.85rem;">${displayKey}</td><td style="padding: 0.75rem; border: 1px solid var(--glass-border); font-size: 0.85rem; color: var(--text-main);">${value === null ? '<span style="color:rgba(255,255,255,0.2)">—</span>' : value}</td></tr>`;
    }
    html += '</tbody></table></div>';
    return html;
}

function exportToExcel() {
    if (!window.currentExportData) return;
    const flatData = flattenObject(window.currentExportData);

    const dataForExcel = Object.entries(flatData)
        .map(([key, value]) => ({ 'Field': key, 'Value': value }));

    const worksheet = XLSX.utils.json_to_sheet(dataForExcel);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Extraction");
    XLSX.writeFile(workbook, `Docapture_Extraction_${Date.now()}.xlsx`);
}

function closeOverlay() {
    const panel = document.getElementById('overlay');
    panel.classList.remove('active');
    panel.classList.remove('wide'); // Reset width
    document.body.style.overflow = 'auto';

    // Clean up potentially large object URLs to free memory
    const iframes = panel.querySelectorAll('iframe');
    iframes.forEach(iframe => {
        if (iframe.src.startsWith('blob:')) {
            URL.revokeObjectURL(iframe.src);
        }
    });
}

function showPreview(event, containerId) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    const files = event.target.files;

    if (!files || files.length === 0) return;

    Array.from(files).forEach(file => {
        const previewItem = document.createElement('div');
        previewItem.className = 'preview-item';

        if (file.type.startsWith('image/')) {
            const reader = new FileReader();
            const img = document.createElement('img');
            reader.onload = (e) => { img.src = e.target.result; };
            reader.readAsDataURL(file);
            previewItem.appendChild(img);
        } else if (file.type === 'application/pdf') {
            const iframe = document.createElement('iframe');
            iframe.src = URL.createObjectURL(file);
            previewItem.appendChild(iframe);
        } else {
            const icon = document.createElement('div');
            icon.innerHTML = '📄';
            icon.style.fontSize = '2rem';
            icon.style.textAlign = 'center';
            icon.style.marginBottom = '0.5rem';
            previewItem.appendChild(icon);
        }

        const name = document.createElement('div');
        name.className = 'preview-file-name';
        name.innerText = file.name;
        previewItem.appendChild(name);

        container.appendChild(previewItem);
    });
}

async function handleLogin(event) {
    event.preventDefault();
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const btn = event.target.querySelector('button');
    const originalText = btn.innerHTML;

    btn.innerHTML = 'Signing in...';
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });

        const result = await response.json();
        if (response.ok && result.token) {
            localStorage.setItem('token', result.token);
            localStorage.setItem('user', JSON.stringify(result.user));
            // Set cookie for server-side dashboard auth
            document.cookie = `token=${result.token}; path=/; max-age=${60 * 60 * 24 * 7}; SameSite=Lax`;
            updateAuthUI();
            closeLogin();
            // Redirect to dashboard
            window.location.href = '/dashboard';
        } else {
            const errBox = document.querySelector('.login-error');
            const msg = result.detail || 'Authentication failed';
            if (errBox) {
                errBox.textContent = msg;
                errBox.style.display = 'block';
            } else {
                alert(msg);
            }
        }
    } catch (e) {
        alert('Connection error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function updateAuthUI() {
    const user = JSON.parse(localStorage.getItem('user'));
    if (user) {
        const authSection = document.getElementById('auth-section');
        if (authSection) {
            authSection.innerHTML = `
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <a href="/dashboard" class="btn-premium btn-primary" style="padding: 0.5rem 1.25rem; font-size: 0.85rem; text-decoration: none;">Dashboard</a>
                    <button class="btn-premium btn-outline" style="padding: 0.5rem 1rem; font-size: 0.85rem;" onclick="logout()">Sign Out</button>
                </div>
            `;
        }
    }
}

function logout() {
    localStorage.clear();
    document.cookie = 'token=; path=/; max-age=0';
    window.location.href = '/';
}

async function handleService(event, endpoint, title) {
    event.preventDefault();
    const token = localStorage.getItem('token');
    if (!token) return openLogin();

    const form = event.target;
    const btn = form.querySelector('button');
    const originalText = btn.innerHTML;

    btn.innerHTML = '<span style="display: flex; align-items: center; gap: 10px;">Computing...</span>';
    btn.disabled = true;

    const formData = new FormData(form);

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });

        const result = await response.json();
        if (result.success) {
            let data = result.data.result;
            let content = data.summary || data.comparison || data.html;

            let docUrl = null;
            let isImage = false;

            const fileInput = form.querySelector('input[type="file"]');
            if (fileInput && fileInput.files.length > 0) {
                const file = fileInput.files[0];
                docUrl = URL.createObjectURL(file);
                isImage = file.type.startsWith('image/');
            }

            if (endpoint === '/extract' || endpoint === '/invoice/extract') {
                showOverlay(title, data, false, true, docUrl, isImage);
            } else {
                showOverlay(title, content, false, false, null, false); // No preview for others yet
            }
        } else {
            alert(result.detail || 'Processing failed');
        }
    } catch (e) {
        alert('Request failed');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function handleJsonService(event, endpoint, title) {
    event.preventDefault();
    const token = localStorage.getItem('token');
    if (!token) return openLogin();

    const btn = event.target.querySelector('button');
    const originalText = btn.innerHTML;
    btn.innerHTML = 'Processing...';
    btn.disabled = true;

    const body = {
        title: document.getElementById('rfp-title').value,
        organization: document.getElementById('rfp-org').value,
        deadline: document.getElementById('rfp-deadline').value,
        sections: [{ title: 'Overview', content: 'AI Managed' }]
    };

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });

        const result = await response.json();
        if (result.success) {
            showOverlay(title, result.data.result, true);
        } else {
            alert(result.detail || 'Generation failed');
        }
    } catch (e) {
        alert('Network error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function handleReconciliation(event) {
    event.preventDefault();
    const token = localStorage.getItem('token');
    if (!token) return openLogin();

    const form = event.target;
    const btn = form.querySelector('button');
    const originalText = btn.innerHTML;

    btn.innerHTML = 'Reconciling...';
    btn.disabled = true;

    const formData = new FormData(form);

    try {
        const response = await fetch(`${API_BASE}/reconcile`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });

        const result = await response.json();
        if (result.success) {
            const data = result.data.result;

            let html = `
                <div class="reconciliation-results">
                    <h3 style="color:var(--text-main); margin-bottom:1rem;">Reconciliation Summary</h3>
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2rem;">
                        <div style="background:rgba(255,255,255,0.03); padding:1rem; border-radius:12px; border:1px solid var(--glass-border); text-align:center;">
                            <label style="display:block; font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:0.5rem;">Bank Items</label>
                            <div style="font-size:1.5rem; font-weight:700; color:#fff;">${data.summary.total_bank}</div>
                        </div>
                        <div style="background:rgba(255,255,255,0.03); padding:1rem; border-radius:12px; border:1px solid var(--glass-border); text-align:center;">
                            <label style="display:block; font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:0.5rem;">Ledger Entries</label>
                            <div style="font-size:1.5rem; font-weight:700; color:#fff;">${data.summary.total_ledger}</div>
                        </div>
                        <div style="background:rgba(34,197,94,0.1); padding:1rem; border-radius:12px; border:1px solid rgba(34,197,94,0.2); text-align:center;">
                            <label style="display:block; font-size:0.75rem; color:#22c55e; text-transform:uppercase; margin-bottom:0.5rem;">Matched</label>
                            <div style="font-size:1.5rem; font-weight:700; color:#22c55e;">${data.summary.matched_count}</div>
                        </div>
                        <div style="background:rgba(239,68,68,0.1); padding:1rem; border-radius:12px; border:1px solid rgba(239,68,68,0.2); text-align:center;">
                            <label style="display:block; font-size:0.75rem; color:#ef4444; text-transform:uppercase; margin-bottom:0.5rem;">Discrepancies</label>
                            <div style="font-size:1.5rem; font-weight:700; color:#ef4444;">${data.summary.discrepancy_count}</div>
                        </div>
                    </div>
                    
                    <h3 style="color:var(--text-main); margin-bottom:1rem;">Matched Transactions</h3>
                    <div style="max-height: 400px; overflow-y: auto; background:rgba(255,255,255,0.02); border:1px solid var(--glass-border); border-radius:12px;">
                        <table style="width:100%; border-collapse:collapse; font-size:0.85rem;">
                            <thead style="position:sticky; top:0; background:#1e293b; z-index:10;">
                                <tr>
                                    <th style="padding:1rem; text-align:left; border-bottom:1px solid var(--glass-border);">Bank Item</th>
                                    <th style="padding:1rem; text-align:left; border-bottom:1px solid var(--glass-border);">Ledger Item</th>
                                    <th style="padding:1rem; text-align:center; border-bottom:1px solid var(--glass-border);">Confidence</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.matches.map(m => `
                                    <tr>
                                        <td style="padding:1rem; border-bottom:1px solid rgba(255,255,255,0.05);">
                                            <div style="font-weight:600;">$${m.bank_transaction.amount.toFixed(2)}</div>
                                            <div style="color:var(--text-muted); font-size:0.75rem;">${m.bank_transaction.date} • ${m.bank_transaction.description}</div>
                                        </td>
                                        <td style="padding:1rem; border-bottom:1px solid rgba(255,255,255,0.05);">
                                            <div style="font-weight:600;">$${m.ledger_entry.amount.toFixed(2)}</div>
                                            <div style="color:var(--text-muted); font-size:0.75rem;">${m.ledger_entry.date} • ${m.ledger_entry.description}</div>
                                        </td>
                                        <td style="padding:1rem; text-align:center; border-bottom:1px solid rgba(255,255,255,0.05);">
                                            <div style="background:rgba(251,191,36,0.1); color:#fbbf24; padding:0.25rem 0.5rem; border-radius:4px; font-weight:600;">
                                                ${(m.match_score * 100).toFixed(0)}%
                                            </div>
                                            <div style="color:var(--text-muted); font-size:0.7rem; margin-top:0.25rem;">${m.match_reason}</div>
                                        </td>
                                    </tr>
                                `).join('')}
                                ${data.matches.length === 0 ? '<tr><td colspan="3" style="padding:2rem; text-align:center; color:var(--text-muted);">No matches found</td></tr>' : ''}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
            showOverlay('Reconciliation Report', html);
        } else {
            alert(result.detail || 'Reconciliation failed');
        }
    } catch (e) {
        console.error(e);
        alert('Network error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function initTheme() {
    const theme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    // Ensure DOM is ready or function called at end of body
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => updateThemeUI(theme));
    } else {
        updateThemeUI(theme);
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const target = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', target);
    localStorage.setItem('theme', target);
    updateThemeUI(target);
}

function updateThemeUI(theme) {
    const btn = document.getElementById('theme-btn');
    const logo = document.querySelector('.logo img');
    const modalLogo = document.querySelector('#login-modal img');

    if (theme === 'light') {
        if (btn) btn.innerHTML = '☀️';
        if (logo) logo.src = '/static/assets/docapture-logo.png';
        if (modalLogo) modalLogo.src = '/static/assets/docapture-logo.png';
    } else {
        if (btn) btn.innerHTML = '🌙';
        if (logo) logo.src = '/static/assets/docapture-dark-logo.png';
        if (modalLogo) modalLogo.src = '/static/assets/docapture-dark-logo.png';
    }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    updateAuthUI();
    initTheme();
});

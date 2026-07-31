/**
 * token_lite_guard Dashboard
 * Single-page application logic
 */

'use strict';

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------
const state = {
  keys: [],
  customProviders: [],
  chart: null,
  chartDays: 7,
  refreshTimer: null,
  activeTab: 'overview',
};

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------
const api = {
  async request(method, path, body = undefined) {
    const options = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined) options.body = JSON.stringify(body);
    const res = await fetch(path, options);
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({ detail: res.statusText }));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  },
  get: (path)         => api.request('GET', path),
  post: (path, body)  => api.request('POST', path, body),
  put: (path, body)   => api.request('PUT', path, body),
  del: (path)         => api.request('DELETE', path),
};

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
function switchTab(tabId, btn) {
  document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`section-${tabId}`).classList.add('active');
  if (btn) btn.classList.add('active');
  state.activeTab = tabId;

  // Lazy load tab data
  if (tabId === 'providers') { loadBuiltinProviders(); loadCustomProviders(); }
  if (tabId === 'logs') loadRecentLogs();
  if (tabId === 'keys') loadKeys();
}

// ---------------------------------------------------------------------------
// Utility functions
// ---------------------------------------------------------------------------
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtNum(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtCost(n) {
  if (n == null) return '—';
  if (n === 0) return '$0.00';
  if (n < 0.0001) return '$' + n.toFixed(8);
  if (n < 0.01)   return '$' + n.toFixed(6);
  return '$' + n.toFixed(4);
}

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function timeAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso + 'Z')) / 1000);
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text)
    .then(() => showToast('Copied to clipboard', 'success', 2000))
    .catch(() => showToast('Copy failed', 'error'));
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slide-in 0.25s ease reverse';
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

// ---------------------------------------------------------------------------
// Modal management
// ---------------------------------------------------------------------------
function openModal(id) {
  document.getElementById(id).classList.add('open');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

function handleOverlayClick(event, modalId) {
  if (event.target === document.getElementById(modalId)) closeModal(modalId);
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(m => m.classList.remove('open'));
  }
});

// ---------------------------------------------------------------------------
// Overview stats
// ---------------------------------------------------------------------------
async function loadOverview() {
  try {
    const data = await api.get('/api/stats/overview');
    document.getElementById('stat-total-tokens').textContent = fmtNum(data.total_tokens);
    document.getElementById('stat-tokens-today').textContent = `${fmtNum(data.tokens_today)} today`;
    document.getElementById('stat-total-cost').textContent = fmtCost(data.total_cost_usd);
    document.getElementById('stat-active-keys').textContent = data.active_keys;
    document.getElementById('stat-requests-today').textContent = fmtNum(data.requests_today);
    document.getElementById('stat-blocked-today').textContent = `${data.blocked_today} blocked today`;

    const ts = new Date().toLocaleTimeString();
    document.getElementById('server-status-label').textContent = `Running — ${ts}`;
  } catch (e) {
    console.error('Overview load failed:', e);
  }
}

// ---------------------------------------------------------------------------
// Usage chart
// ---------------------------------------------------------------------------
async function loadChart(days = 7) {
  try {
    const data = await api.get(`/api/stats/usage-chart?days=${days}`);
    const labels = data.map(d => new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
    const tokens = data.map(d => d.tokens);
    const costs = data.map(d => d.cost);
    const ctx = document.getElementById('usage-chart').getContext('2d');

    if (state.chart) state.chart.destroy();

    state.chart = new Chart(ctx, {
      data: {
        labels,
        datasets: [
          {
            type: 'bar',
            label: 'Tokens',
            data: tokens,
            backgroundColor: 'rgba(56, 139, 253, 0.2)',
            borderColor: 'rgba(56, 139, 253, 0.8)',
            borderWidth: 1,
            borderRadius: 3,
            yAxisID: 'y',
          },
          {
            type: 'line',
            label: 'Cost (USD)',
            data: costs,
            borderColor: 'rgba(188, 140, 255, 0.9)',
            backgroundColor: 'rgba(188, 140, 255, 0.08)',
            borderWidth: 2,
            pointRadius: 3,
            fill: true,
            tension: 0.3,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#8b949e', font: { size: 12 }, boxWidth: 12 } },
          tooltip: {
            backgroundColor: '#1c2230',
            borderColor: 'rgba(56, 139, 253, 0.3)',
            borderWidth: 1,
            titleColor: '#e6edf3',
            bodyColor: '#8b949e',
            callbacks: {
              label: ctx => ctx.datasetIndex === 0
                ? ` Tokens: ${ctx.raw.toLocaleString()}`
                : ` Cost: ${fmtCost(ctx.raw)}`,
            },
          },
        },
        scales: {
          x: { grid: { color: 'rgba(48,54,61,0.5)' }, ticks: { color: '#484f58', font: { size: 11 } } },
          y: {
            position: 'left',
            grid: { color: 'rgba(48,54,61,0.5)' },
            ticks: { color: '#388bfd', font: { size: 11 }, callback: v => fmtNum(v) },
          },
          y1: {
            position: 'right',
            grid: { display: false },
            ticks: { color: '#bc8cff', font: { size: 11 }, callback: v => fmtCost(v) },
          },
        },
      },
    });
  } catch (e) {
    console.error('Chart load failed:', e);
  }
}

function changeChartRange(days, btn) {
  state.chartDays = days;
  document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  loadChart(days);
}

// ---------------------------------------------------------------------------
// Top models
// ---------------------------------------------------------------------------
async function loadModelStats() {
  try {
    const data = await api.get('/api/stats/by-model?days=30');
    const container = document.getElementById('model-stats-body');
    if (!data.length) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-title">No model data</div><div class="empty-state-desc">Proxied requests will appear here.</div></div>`;
      return;
    }
    const maxT = Math.max(...data.map(d => d.total_tokens), 1);
    container.innerHTML = data.slice(0, 8).map(d => {
      const pct = (d.total_tokens / maxT * 100).toFixed(1);
      const badge = d.provider === 'anthropic' ? 'badge-purple' :
                    d.provider === 'google'    ? 'badge-cyan' :
                    d.provider === 'mistral'   ? 'badge-amber' : 'badge-blue';
      return `<div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
          <span style="font-size:12px;font-weight:500;color:var(--text-primary);">${esc(d.model)}</span>
          <span class="badge ${badge}">${esc(d.provider)}</span>
        </div>
        <div class="budget-bar-track"><div class="budget-bar-fill" style="width:${pct}%"></div></div>
        <div style="display:flex;justify-content:space-between;margin-top:3px;">
          <span class="budget-text">${fmtNum(d.total_tokens)} tokens</span>
          <span class="budget-text">${fmtCost(d.cost_usd)}</span>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    console.error('Model stats failed:', e);
  }
}

// ---------------------------------------------------------------------------
// Virtual keys
// ---------------------------------------------------------------------------
async function loadKeys() {
  try {
    const keys = await api.get('/api/keys');
    state.keys = keys;
    renderKeysTable(keys);
  } catch (e) {
    showToast('Failed to load keys: ' + e.message, 'error');
  }
}

function renderKeysTable(keys) {
  const tbody = document.getElementById('keys-tbody');
  if (!keys.length) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-state-title">No virtual keys</div><div class="empty-state-desc">Create a key to start proxying requests.</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = keys.map(k => {
    const pct = k.usage_percentage;
    const barClass = pct >= 90 ? 'danger' : pct >= 70 ? 'warn' : '';
    const unlimited = k.budget_tokens === 0;
    const budget = unlimited
      ? '<span style="color:var(--text-secondary);font-size:12px;">Unlimited</span>'
      : `<div class="budget-bar-wrap">
           <div class="budget-bar-track"><div class="budget-bar-fill ${barClass}" style="width:${pct.toFixed(1)}%"></div></div>
           <div class="budget-text">${fmtNum(k.used_tokens)} / ${fmtNum(k.budget_tokens)} (${pct.toFixed(1)}%)</div>
         </div>`;
    const status = k.is_active
      ? '<span class="badge badge-green">Active</span>'
      : '<span class="badge badge-muted">Inactive</span>';
    return `
      <tr>
        <td><div class="td-name">${esc(k.name)}</div>${k.notes ? `<div class="td-sub">${esc(k.notes)}</div>` : ''}</td>
        <td><span class="key-display" title="Click to copy" onclick="copyToClipboard('${esc(k.key_hash)}')">${esc(k.key_hash.slice(0, 20))}...</span></td>
        <td><span class="badge badge-blue">${esc(k.provider)}</span></td>
        <td>${budget}</td>
        <td>${status}</td>
        <td style="font-size:12px;color:var(--text-secondary);">${fmtDate(k.created_at)}</td>
        <td>
          <div class="actions-cell">
            <button class="btn btn-ghost btn-icon btn-sm" title="Edit" onclick="openEditKeyModal(${k.id})">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M11.013 1.427a1.75 1.75 0 012.474 0l1.086 1.086a1.75 1.75 0 010 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 01-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.609zm1.414 1.06a.25.25 0 00-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 000-.354l-1.086-1.086zM11.189 6.25L9.75 4.81l-6.286 6.287a.25.25 0 00-.064.108l-.558 1.953 1.953-.558a.251.251 0 00.108-.064l6.286-6.286z"/></svg>
            </button>
            <button class="btn btn-ghost btn-icon btn-sm" title="Reset budget" onclick="resetKeyBudget(${k.id}, '${esc(k.name)}')">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M8 2.5A5.5 5.5 0 1013.5 8a.75.75 0 011.5 0 7 7 0 11-3.45-6.04V.75a.75.75 0 011.5 0v3.5a.75.75 0 01-.75.75h-3.5a.75.75 0 010-1.5h1.63A5.479 5.479 0 008 2.5z"/></svg>
            </button>
            <button class="btn btn-ghost btn-icon btn-sm" title="${k.is_active ? 'Deactivate' : 'Activate'}" onclick="toggleKey(${k.id}, ${k.is_active})">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">${k.is_active ? '<path d="M5.75 3a.75.75 0 01.75.75v8.5a.75.75 0 01-1.5 0v-8.5A.75.75 0 015.75 3zm4.5 0a.75.75 0 01.75.75v8.5a.75.75 0 01-1.5 0v-8.5a.75.75 0 01.75-.75z"/>' : '<path d="M4.5 3.62v8.76a.75.75 0 001.165.626l7.25-4.38a.75.75 0 000-1.252L5.665 2.994A.75.75 0 004.5 3.62z"/>'}</svg>
            </button>
            <button class="btn btn-danger btn-icon btn-sm" title="Delete" onclick="deleteKey(${k.id}, '${esc(k.name)}')">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M11 1.75V3h2.25a.75.75 0 010 1.5H2.75a.75.75 0 010-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75zM4.496 6.675a.75.75 0 10-1.492.15l.66 6.6A1.75 1.75 0 005.405 15h5.19a1.75 1.75 0 001.741-1.575l.66-6.6a.75.75 0 00-1.492-.15l-.66 6.6a.25.25 0 01-.249.225h-5.19a.25.25 0 01-.249-.225l-.66-6.6z"/></svg>
            </button>
          </div>
        </td>
      </tr>`;
  }).join('');
}

// Create key
async function createKey() {
  const name = document.getElementById('new-key-name').value.trim();
  if (!name) { showToast('Key name is required', 'error'); return; }
  const budget = parseInt(document.getElementById('new-key-budget').value, 10) || 0;
  const provider = document.getElementById('new-key-provider').value;
  const notes = document.getElementById('new-key-notes').value.trim();
  const btn = document.getElementById('btn-create-key');
  btn.disabled = true; btn.textContent = 'Creating...';
  try {
    const key = await api.post('/api/keys', { name, budget_tokens: budget, provider, notes });
    closeModal('create-key-modal');
    showToast(`Key "${key.name}" created. Value: ${key.key_hash}`, 'success', 8000);
    await loadKeys(); await loadOverview();
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Create Key';
  }
}

// Edit key
function openEditKeyModal(keyId) {
  const k = state.keys.find(x => x.id === keyId);
  if (!k) return;
  document.getElementById('edit-key-id').value = keyId;
  document.getElementById('edit-key-name').value = k.name;
  document.getElementById('edit-key-budget').value = k.budget_tokens;
  document.getElementById('edit-key-active').checked = k.is_active;
  document.getElementById('edit-key-notes').value = k.notes || '';
  openModal('edit-key-modal');
}

async function saveKeyEdit() {
  const id = document.getElementById('edit-key-id').value;
  const name = document.getElementById('edit-key-name').value.trim();
  if (!name) { showToast('Name is required', 'error'); return; }
  const budget = parseInt(document.getElementById('edit-key-budget').value, 10) || 0;
  const is_active = document.getElementById('edit-key-active').checked;
  const notes = document.getElementById('edit-key-notes').value.trim();
  try {
    await api.put(`/api/keys/${id}`, { name, budget_tokens: budget, is_active, notes });
    closeModal('edit-key-modal');
    showToast('Key updated', 'success');
    await loadKeys();
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
  }
}

async function toggleKey(id, currentlyActive) {
  try {
    await api.put(`/api/keys/${id}`, { is_active: !currentlyActive });
    showToast(`Key ${currentlyActive ? 'deactivated' : 'activated'}`, 'info');
    await loadKeys();
  } catch (e) { showToast('Failed: ' + e.message, 'error'); }
}

async function resetKeyBudget(id, name) {
  if (!confirm(`Reset the token usage counter for key "${name}" back to zero?`)) return;
  try {
    await api.request('POST', `/api/keys/${id}/reset`);
    showToast(`Budget reset for "${name}"`, 'success');
    await loadKeys(); await loadOverview();
  } catch (e) { showToast('Failed: ' + e.message, 'error'); }
}

async function deleteKey(id, name) {
  if (!confirm(`Permanently delete key "${name}"?\n\nUsage logs will be retained.`)) return;
  try {
    await api.del(`/api/keys/${id}`);
    showToast(`Key "${name}" deleted`, 'info');
    await loadKeys(); await loadOverview();
  } catch (e) { showToast('Failed: ' + e.message, 'error'); }
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------
async function loadBuiltinProviders() {
  try {
    const providers = await api.get('/api/providers/builtin');
    const grid = document.getElementById('builtin-providers-grid');
    grid.innerHTML = providers.map(p => `
      <div class="provider-card ${p.configured ? 'configured' : 'unconfigured'}">
        <div class="provider-card-header">
          <div>
            <div class="provider-name">${esc(p.name)}</div>
            <div class="provider-id">${esc(p.id)}</div>
          </div>
          <span class="badge ${p.configured ? 'badge-green' : 'badge-muted'}">${p.configured ? 'Configured' : 'Not configured'}</span>
        </div>
        <div class="provider-description">${esc(p.description)}</div>
        ${p.base_url ? `<div class="provider-url">${esc(p.base_url)}</div>` : ''}
      </div>
    `).join('');
  } catch (e) {
    console.error('Failed to load built-in providers:', e);
  }
}

async function loadCustomProviders() {
  try {
    const providers = await api.get('/api/providers');
    state.customProviders = providers;
    renderCustomProvidersTable(providers);
  } catch (e) {
    showToast('Failed to load custom providers: ' + e.message, 'error');
  }
}

function renderCustomProvidersTable(providers) {
  const tbody = document.getElementById('custom-providers-tbody');
  if (!providers.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-state-title">No custom providers</div><div class="empty-state-desc">Add an OpenAI-compatible endpoint to start using it with virtual keys.</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = providers.map(p => {
    const inputCost = p.input_cost_per_1m != null ? `$${p.input_cost_per_1m.toFixed(2)}` : '—';
    const outputCost = p.output_cost_per_1m != null ? `$${p.output_cost_per_1m.toFixed(2)}` : '—';
    const authBadge = { bearer: 'badge-blue', 'x-api-key': 'badge-purple', 'api-key': 'badge-amber', none: 'badge-muted' }[p.auth_style] || 'badge-muted';
    return `
      <tr>
        <td><div class="td-name">${esc(p.display_name)}</div><div class="td-sub">ID: ${esc(p.name)}</div></td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-secondary);">${esc(p.base_url)}</td>
        <td><span class="badge ${authBadge}">${esc(p.auth_style)}</span></td>
        <td style="font-size:12px;color:var(--text-secondary);">${inputCost} / ${outputCost}</td>
        <td><span class="badge ${p.is_active ? 'badge-green' : 'badge-muted'}">${p.is_active ? 'Active' : 'Inactive'}</span></td>
        <td>
          <div class="actions-cell">
            <button class="btn btn-ghost btn-sm" onclick="openEditProviderModal(${p.id})">Edit</button>
            <button class="btn btn-danger btn-sm" onclick="deleteProvider(${p.id}, '${esc(p.display_name)}')">Delete</button>
          </div>
        </td>
      </tr>`;
  }).join('');
}

async function createProvider() {
  const name = document.getElementById('np-name').value.trim();
  const display_name = document.getElementById('np-display-name').value.trim();
  const base_url = document.getElementById('np-base-url').value.trim();
  if (!name || !display_name || !base_url) {
    showToast('Identifier, display name, and base URL are required', 'error'); return;
  }
  const btn = document.getElementById('btn-create-provider');
  btn.disabled = true; btn.textContent = 'Adding...';
  try {
    await api.post('/api/providers', {
      name, display_name, base_url,
      api_key: document.getElementById('np-api-key').value || null,
      auth_style: document.getElementById('np-auth-style').value,
      description: document.getElementById('np-description').value.trim() || null,
      input_cost_per_1m: parseFloat(document.getElementById('np-input-cost').value) || null,
      output_cost_per_1m: parseFloat(document.getElementById('np-output-cost').value) || null,
    });
    closeModal('create-provider-modal');
    showToast(`Provider "${display_name}" added`, 'success');
    await loadCustomProviders();
    // Reset form
    ['np-name','np-display-name','np-base-url','np-api-key','np-description','np-input-cost','np-output-cost'].forEach(id => {
      document.getElementById(id).value = '';
    });
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Add Provider';
  }
}

function openEditProviderModal(id) {
  const p = state.customProviders.find(x => x.id === id);
  if (!p) return;
  document.getElementById('ep-id').value = id;
  document.getElementById('ep-display-name').value = p.display_name;
  document.getElementById('ep-base-url').value = p.base_url;
  document.getElementById('ep-auth-style').value = p.auth_style;
  document.getElementById('ep-api-key').value = '';
  document.getElementById('ep-input-cost').value = p.input_cost_per_1m ?? '';
  document.getElementById('ep-output-cost').value = p.output_cost_per_1m ?? '';
  document.getElementById('ep-description').value = p.description || '';
  document.getElementById('ep-test-result').className = 'test-result';
  document.getElementById('ep-test-result').textContent = '';
  openModal('edit-provider-modal');
}

async function saveProviderEdit() {
  const id = document.getElementById('ep-id').value;
  const display_name = document.getElementById('ep-display-name').value.trim();
  const base_url = document.getElementById('ep-base-url').value.trim();
  if (!display_name || !base_url) { showToast('Display name and base URL are required', 'error'); return; }
  const apiKey = document.getElementById('ep-api-key').value;
  const body = {
    display_name, base_url,
    auth_style: document.getElementById('ep-auth-style').value,
    description: document.getElementById('ep-description').value.trim() || null,
    input_cost_per_1m: parseFloat(document.getElementById('ep-input-cost').value) || null,
    output_cost_per_1m: parseFloat(document.getElementById('ep-output-cost').value) || null,
  };
  if (apiKey) body.api_key = apiKey;
  try {
    await api.put(`/api/providers/${id}`, body);
    closeModal('edit-provider-modal');
    showToast('Provider updated', 'success');
    await loadCustomProviders();
  } catch (e) { showToast('Failed: ' + e.message, 'error'); }
}

async function testProvider() {
  const id = document.getElementById('ep-id').value;
  if (!id) return;
  const resultDiv = document.getElementById('ep-test-result');
  resultDiv.className = 'test-result';
  resultDiv.textContent = 'Testing connection...';
  resultDiv.style.display = 'block';
  try {
    const result = await api.request('POST', `/api/providers/${id}/test`);
    resultDiv.className = `test-result ${result.success ? 'ok' : 'fail'}`;
    resultDiv.textContent = result.success
      ? `Connection successful (HTTP ${result.status_code})`
      : `Connection failed: ${result.error || `HTTP ${result.status_code}`}`;
  } catch (e) {
    resultDiv.className = 'test-result fail';
    resultDiv.textContent = 'Test request failed: ' + e.message;
  }
}

async function deleteProvider(id, name) {
  if (!confirm(`Delete provider "${name}"?\n\nVirtual keys targeting this provider will no longer work.`)) return;
  try {
    await api.del(`/api/providers/${id}`);
    showToast(`Provider "${name}" deleted`, 'info');
    await loadCustomProviders();
  } catch (e) { showToast('Failed: ' + e.message, 'error'); }
}

// ---------------------------------------------------------------------------
// Activity log
// ---------------------------------------------------------------------------
async function loadRecentLogs(limit = 100) {
  try {
    const logs = await api.get(`/api/stats/recent-logs?limit=${limit}`);

    // Overview preview (5 rows)
    const previewBody = document.getElementById('overview-logs-body');
    if (previewBody) {
      if (!logs.length) {
        previewBody.innerHTML = `<div class="empty-state"><div class="empty-state-title">No activity recorded</div><div class="empty-state-desc">Configure your AI tool to use <code>http://localhost:8000/v1</code> as the base URL.</div></div>`;
      } else {
        previewBody.innerHTML = logs.slice(0, 5).map(renderLogRow).join('');
      }
    }

    // Full table
    const tbody = document.getElementById('logs-tbody');
    if (tbody) {
      if (!logs.length) {
        tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="empty-state-title">No activity recorded</div></div></td></tr>`;
      } else {
        tbody.innerHTML = logs.map(log => {
          const statusClass = { success: 'badge-green', error: 'badge-red', blocked: 'badge-amber' }[log.status] || 'badge-muted';
          return `<tr>
            <td><span class="badge ${statusClass}">${esc(log.status)}</span></td>
            <td style="font-size:12px;">${esc(log.key_name)}</td>
            <td style="font-size:12px;">${esc(log.model)}</td>
            <td><span class="badge badge-blue" style="font-size:10px;">${esc(log.provider)}</span></td>
            <td style="font-size:12px;font-variant-numeric:tabular-nums;">${log.input_tokens.toLocaleString()}</td>
            <td style="font-size:12px;font-variant-numeric:tabular-nums;">${log.output_tokens.toLocaleString()}</td>
            <td style="font-size:12px;">${fmtCost(log.cost_usd)}</td>
            <td style="font-size:12px;color:var(--text-secondary);">${log.latency_ms != null ? log.latency_ms + 'ms' : '—'}</td>
            <td style="font-size:11px;color:var(--text-muted);white-space:nowrap;">${timeAgo(log.timestamp)}</td>
          </tr>`;
        }).join('');
      }
    }
  } catch (e) {
    console.error('Failed to load logs:', e);
  }
}

function renderLogRow(log) {
  const dotClass = { success: 'success', error: 'error', blocked: 'blocked' }[log.status] || 'error';
  return `<div class="log-row">
    <div class="log-dot ${dotClass}"></div>
    <div class="log-info">
      <div class="log-model">${esc(log.model)}</div>
      <div class="log-key">${esc(log.key_name)}</div>
    </div>
    <div class="log-tokens">
      <div>${fmtNum(log.total_tokens)}</div>
      <div>${fmtCost(log.cost_usd)}</div>
    </div>
    <div class="log-time">${timeAgo(log.timestamp)}</div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Auto-refresh
// ---------------------------------------------------------------------------
function startAutoRefresh() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => {
    loadOverview();
    if (state.activeTab === 'logs') loadRecentLogs();
    else loadRecentLogs(5);
  }, 15_000);
}

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------
async function init() {
  await Promise.all([
    loadOverview(),
    loadChart(7),
    loadModelStats(),
    loadKeys(),
    loadRecentLogs(20),
  ]);
  startAutoRefresh();
}

init().catch(console.error);

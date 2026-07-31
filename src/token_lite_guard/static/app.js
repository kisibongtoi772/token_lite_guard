/**
 * token_lite_guard Dashboard — Vanilla JS SPA
 * Auto-refreshes every 15 seconds for live monitoring
 */

'use strict';

// ─── State ─────────────────────────────────────────────────────
const state = {
  keys: [],
  chart: null,
  chartDays: 7,
  refreshTimer: null,
};

// ─── API Client ─────────────────────────────────────────────────
const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Request failed');
    }
    return res.json();
  },
  async put(path, body) {
    const res = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Request failed');
    }
    return res.json();
  },
  async del(path) {
    const res = await fetch(path, { method: 'DELETE' });
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
  },
  async postNoBody(path) {
    const res = await fetch(path, { method: 'POST' });
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
  },
};

// ─── Toast Notifications ────────────────────────────────────────
function showToast(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icon = { success: '✓', error: '✕', info: 'ℹ' }[type] || 'ℹ';
  toast.innerHTML = `<span style="font-weight:700">${icon}</span> ${escapeHtml(message)}`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'toast-in 0.3s ease reverse';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ─── Utility ────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatNumber(n) {
  if (n === null || n === undefined) return '—';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function formatCost(n) {
  if (n === null || n === undefined) return '—';
  if (n < 0.01) return '$' + n.toFixed(6);
  return '$' + n.toFixed(4);
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function timeAgo(iso) {
  const seconds = Math.floor((Date.now() - new Date(iso + 'Z')) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast('Copied to clipboard!', 'success', 2000);
  }).catch(() => {
    showToast('Failed to copy', 'error');
  });
}

// ─── Overview Stats ─────────────────────────────────────────────
async function loadOverview() {
  try {
    const data = await api.get('/api/stats/overview');

    document.getElementById('stat-total-tokens').textContent = formatNumber(data.total_tokens);
    document.getElementById('stat-tokens-today').textContent = `${formatNumber(data.tokens_today)} today`;
    document.getElementById('stat-total-cost').textContent = formatCost(data.total_cost_usd);
    document.getElementById('stat-active-keys').textContent = data.active_keys;
    document.getElementById('stat-requests-today').textContent = formatNumber(data.requests_today);
    document.getElementById('stat-blocked-today').textContent = `${data.blocked_today} blocked today`;

    const now = new Date().toLocaleTimeString();
    document.getElementById('last-refresh').textContent = `Last updated: ${now} — auto-refreshes every 15s`;
  } catch (e) {
    console.error('Failed to load overview:', e);
  }
}

// ─── Usage Chart ─────────────────────────────────────────────────
async function loadChart(days = 7) {
  try {
    const data = await api.get(`/api/stats/usage-chart?days=${days}`);

    const labels = data.map(d => {
      const date = new Date(d.date);
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const tokenValues = data.map(d => d.tokens);
    const costValues = data.map(d => d.cost);

    const ctx = document.getElementById('usage-chart').getContext('2d');

    if (state.chart) {
      state.chart.destroy();
    }

    state.chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Tokens',
            data: tokenValues,
            backgroundColor: 'rgba(99, 179, 237, 0.25)',
            borderColor: 'rgba(99, 179, 237, 0.8)',
            borderWidth: 2,
            borderRadius: 6,
            yAxisID: 'y',
          },
          {
            label: 'Cost (USD)',
            data: costValues,
            type: 'line',
            borderColor: 'rgba(183, 148, 244, 0.9)',
            backgroundColor: 'rgba(183, 148, 244, 0.08)',
            borderWidth: 2,
            pointBackgroundColor: 'rgba(183, 148, 244, 1)',
            pointRadius: 4,
            fill: true,
            tension: 0.4,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            labels: { color: '#94a3b8', font: { size: 12 } },
          },
          tooltip: {
            backgroundColor: 'rgba(15, 22, 41, 0.95)',
            borderColor: 'rgba(99, 179, 237, 0.3)',
            borderWidth: 1,
            titleColor: '#e2e8f0',
            bodyColor: '#94a3b8',
            callbacks: {
              label: (ctx) => {
                if (ctx.datasetIndex === 0) return ` Tokens: ${ctx.raw.toLocaleString()}`;
                return ` Cost: $${ctx.raw.toFixed(4)}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#475569', font: { size: 11 } },
          },
          y: {
            position: 'left',
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: {
              color: '#63b3ed',
              font: { size: 11 },
              callback: v => formatNumber(v),
            },
          },
          y1: {
            position: 'right',
            grid: { display: false },
            ticks: {
              color: '#b794f4',
              font: { size: 11 },
              callback: v => '$' + v.toFixed(4),
            },
          },
        },
      },
    });
  } catch (e) {
    console.error('Failed to load chart:', e);
  }
}

function changeChartRange(days, btn) {
  state.chartDays = days;
  document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  loadChart(days);
}

// ─── Model Stats ─────────────────────────────────────────────────
async function loadModelStats() {
  try {
    const data = await api.get('/api/stats/by-model?days=30');
    const container = document.getElementById('model-stats-body');

    if (!data.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📊</div>
          <div class="empty-state-text">No data yet. Make your first request!</div>
        </div>`;
      return;
    }

    const maxTokens = Math.max(...data.map(d => d.total_tokens), 1);

    container.innerHTML = data.slice(0, 6).map(d => {
      const pct = (d.total_tokens / maxTokens) * 100;
      const providerClass = d.provider === 'anthropic' ? 'badge-anthropic' : 'badge-openai';
      return `
        <div class="quick-stat-item">
          <div class="quick-stat-label">
            <span class="badge ${providerClass}">${d.provider}</span>
            ${escapeHtml(d.model)}
          </div>
          <div>
            <div class="quick-stat-value">${formatNumber(d.total_tokens)}</div>
            <div class="budget-bar-track" style="margin-top:4px;">
              <div class="budget-bar-fill" style="width:${pct.toFixed(1)}%"></div>
            </div>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    console.error('Failed to load model stats:', e);
  }
}

// ─── Virtual Keys ────────────────────────────────────────────────
async function loadKeys() {
  try {
    const keys = await api.get('/api/keys');
    state.keys = keys;
    renderKeysTable(keys);
  } catch (e) {
    console.error('Failed to load keys:', e);
    showToast('Failed to load keys: ' + e.message, 'error');
  }
}

function renderKeysTable(keys) {
  const tbody = document.getElementById('keys-tbody');

  if (!keys.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="empty-state">
            <div class="empty-state-icon">🔑</div>
            <div class="empty-state-text">No virtual keys yet. Create one to get started!</div>
          </div>
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = keys.map(key => {
    const usedPct = key.usage_percentage;
    const barClass = usedPct >= 90 ? 'danger' : usedPct >= 70 ? 'warn' : '';
    const statusBadge = key.is_active
      ? '<span class="badge badge-active">● Active</span>'
      : '<span class="badge badge-inactive">○ Inactive</span>';
    const providerBadge = key.provider === 'anthropic'
      ? '<span class="badge badge-anthropic">Anthropic</span>'
      : '<span class="badge badge-openai">OpenAI</span>';

    const budgetDisplay = key.budget_tokens === 0
      ? '<span style="color:var(--accent-green)">∞ Unlimited</span>'
      : `<div class="budget-bar-wrap">
          <div class="budget-bar-track">
            <div class="budget-bar-fill ${barClass}" style="width:${usedPct.toFixed(1)}%"></div>
          </div>
          <div class="budget-text">${formatNumber(key.used_tokens)} / ${formatNumber(key.budget_tokens)} (${usedPct.toFixed(1)}%)</div>
        </div>`;

    const truncatedKey = key.key_hash.slice(0, 16) + '...';

    return `
      <tr>
        <td>
          <div class="key-name">${escapeHtml(key.name)}</div>
          ${key.notes ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${escapeHtml(key.notes)}</div>` : ''}
        </td>
        <td>
          <span class="key-value" title="Click to copy" onclick="copyToClipboard('${escapeHtml(key.key_hash)}')">
            ${escapeHtml(truncatedKey)}
          </span>
        </td>
        <td>${providerBadge}</td>
        <td>${budgetDisplay}</td>
        <td>${statusBadge}</td>
        <td style="color:var(--text-muted);font-size:12px;">${formatDate(key.created_at)}</td>
        <td>
          <div class="actions-cell">
            <button class="btn btn-ghost btn-icon btn-sm" title="Edit" onclick="openEditModal(${key.id})">✏️</button>
            <button class="btn btn-ghost btn-icon btn-sm" title="Reset budget" onclick="resetBudget(${key.id}, '${escapeHtml(key.name)}')">🔄</button>
            <button class="btn btn-ghost btn-icon btn-sm" title="${key.is_active ? 'Deactivate' : 'Activate'}" onclick="toggleKey(${key.id}, ${key.is_active})">
              ${key.is_active ? '⏸' : '▶️'}
            </button>
            <button class="btn btn-danger btn-icon btn-sm" title="Delete" onclick="deleteKey(${key.id}, '${escapeHtml(key.name)}')">🗑</button>
          </div>
        </td>
      </tr>`;
  }).join('');
}

// ─── Create Key Modal ────────────────────────────────────────────
function openCreateModal() {
  document.getElementById('new-key-name').value = '';
  document.getElementById('new-key-budget').value = '100000';
  document.getElementById('new-key-notes').value = '';
  document.getElementById('new-key-provider').value = 'openai';
  document.getElementById('create-modal').classList.add('open');
  setTimeout(() => document.getElementById('new-key-name').focus(), 100);
}

function closeCreateModal() {
  document.getElementById('create-modal').classList.remove('open');
}

function handleModalOverlayClick(e) {
  if (e.target === document.getElementById('create-modal')) closeCreateModal();
}

async function createKey() {
  const name = document.getElementById('new-key-name').value.trim();
  const budget = parseInt(document.getElementById('new-key-budget').value, 10) || 0;
  const notes = document.getElementById('new-key-notes').value.trim();
  const provider = document.getElementById('new-key-provider').value;

  if (!name) {
    showToast('Please enter a key name', 'error');
    document.getElementById('new-key-name').focus();
    return;
  }

  const btn = document.getElementById('btn-create-key');
  btn.disabled = true;
  btn.textContent = 'Creating...';

  try {
    const key = await api.post('/api/keys', { name, budget_tokens: budget, notes, provider });
    closeCreateModal();
    showToast(`Key "${key.name}" created! Copy it now: ${key.key_hash}`, 'success', 6000);
    await loadKeys();
    await loadOverview();
  } catch (e) {
    showToast('Failed to create key: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Key';
  }
}

// ─── Edit Key Modal ──────────────────────────────────────────────
function openEditModal(keyId) {
  const key = state.keys.find(k => k.id === keyId);
  if (!key) return;

  document.getElementById('edit-key-id').value = keyId;
  document.getElementById('edit-key-name').value = key.name;
  document.getElementById('edit-key-budget').value = key.budget_tokens;
  document.getElementById('edit-key-notes').value = key.notes || '';
  document.getElementById('edit-modal').classList.add('open');
  setTimeout(() => document.getElementById('edit-key-name').focus(), 100);
}

function closeEditModal() {
  document.getElementById('edit-modal').classList.remove('open');
}

function handleEditOverlayClick(e) {
  if (e.target === document.getElementById('edit-modal')) closeEditModal();
}

async function saveKeyEdit() {
  const id = document.getElementById('edit-key-id').value;
  const name = document.getElementById('edit-key-name').value.trim();
  const budget = parseInt(document.getElementById('edit-key-budget').value, 10) || 0;
  const notes = document.getElementById('edit-key-notes').value.trim();

  if (!name) { showToast('Name cannot be empty', 'error'); return; }

  try {
    await api.put(`/api/keys/${id}`, { name, budget_tokens: budget, notes });
    closeEditModal();
    showToast('Key updated successfully', 'success');
    await loadKeys();
  } catch (e) {
    showToast('Failed to update: ' + e.message, 'error');
  }
}

// ─── Key Actions ─────────────────────────────────────────────────
async function toggleKey(keyId, currentlyActive) {
  try {
    await api.put(`/api/keys/${keyId}`, { is_active: !currentlyActive });
    showToast(`Key ${currentlyActive ? 'deactivated' : 'activated'}`, 'info');
    await loadKeys();
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
  }
}

async function resetBudget(keyId, keyName) {
  if (!confirm(`Reset token usage counter for "${keyName}"?\n\nThis will set used_tokens back to 0.`)) return;
  try {
    await api.postNoBody(`/api/keys/${keyId}/reset`);
    showToast(`Budget reset for "${keyName}"`, 'success');
    await loadKeys();
    await loadOverview();
  } catch (e) {
    showToast('Failed to reset: ' + e.message, 'error');
  }
}

async function deleteKey(keyId, keyName) {
  if (!confirm(`Delete key "${keyName}"?\n\nThis action cannot be undone. Usage logs will be preserved.`)) return;
  try {
    await api.del(`/api/keys/${keyId}`);
    showToast(`Key "${keyName}" deleted`, 'info');
    await loadKeys();
    await loadOverview();
  } catch (e) {
    showToast('Failed to delete: ' + e.message, 'error');
  }
}

// ─── Recent Logs ─────────────────────────────────────────────────
async function loadRecentLogs() {
  try {
    const logs = await api.get('/api/stats/recent-logs?limit=20');
    const container = document.getElementById('logs-body');

    if (!logs.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📭</div>
          <div class="empty-state-text">No activity yet. Configure your AI tool to use http://localhost:8000/v1 as the base URL.</div>
        </div>`;
      return;
    }

    container.innerHTML = logs.map(log => `
      <div class="log-row">
        <div class="log-status-dot ${log.status}"></div>
        <div class="log-info">
          <div class="log-model">${escapeHtml(log.model)}</div>
          <div class="log-key">🔑 ${escapeHtml(log.key_name)}${log.latency_ms ? ` · ${log.latency_ms}ms` : ''}</div>
        </div>
        <div class="log-tokens">
          <div>${formatNumber(log.total_tokens)} tok</div>
          <div style="color:var(--text-muted);font-size:10px;">${formatCost(log.cost_usd)}</div>
        </div>
        <div class="log-time">${timeAgo(log.timestamp)}</div>
      </div>
    `).join('');
  } catch (e) {
    console.error('Failed to load logs:', e);
  }
}

// ─── Keyboard shortcuts ───────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeCreateModal();
    closeEditModal();
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    openCreateModal();
  }
});

// ─── Auto-refresh ────────────────────────────────────────────────
function startAutoRefresh() {
  loadOverview();
  loadRecentLogs();

  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => {
    loadOverview();
    loadRecentLogs();
  }, 15_000);
}

// ─── Init ────────────────────────────────────────────────────────
async function init() {
  await Promise.all([
    loadOverview(),
    loadChart(7),
    loadKeys(),
    loadModelStats(),
    loadRecentLogs(),
  ]);
  startAutoRefresh();
}

init().catch(console.error);

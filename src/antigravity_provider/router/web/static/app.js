/**
 * Hermes Hub Web Client
 * Vanilla JavaScript (ES2022) — No npm, no build, no framework.
 * Single source of truth: docs/web-api/CONTRACT.md
 */

// ── CONFIGURATION & STATE ──
const USE_MOCK_FIXTURE = false;

let lastAppliedSeq = -1;
let currentSnapshot = null;
let activeView = 'accounts';
let pollTimer = null;
let pollIntervalMs = 5000;
let authToken = localStorage.getItem('hermes_hub_token') || '';
let cachedEvents = [];
let currentSettings = {};

// ── DOM ELEMENTS ──
const elements = {
  navItems: document.querySelectorAll('.nav-item'),
  viewPanes: document.querySelectorAll('.view-pane'),
  pageTitle: document.getElementById('page-title'),
  navAccountsCount: document.getElementById('nav-accounts-count'),
  headerReadinessBadge: document.getElementById('header-readiness-badge'),
  headerReadinessText: document.getElementById('header-readiness-text'),
  sourceText: document.getElementById('source-text'),
  sourceDot: document.querySelector('#source-indicator .status-dot'),
  accountsContainer: document.getElementById('accounts-container'),
  accountsSearch: document.getElementById('accounts-search'),
  filterProvider: document.getElementById('filter-provider'),
  filterHealth: document.getElementById('filter-health'),
  accountsStatsSummary: document.getElementById('accounts-stats-summary'),
  btnRefreshAll: document.getElementById('btn-refresh-all'),
  btnAddAccount: document.getElementById('btn-add-account'),
  modalBackdrop: document.getElementById('modal-backdrop'),
  modalTitle: document.getElementById('modal-title'),
  modalBody: document.getElementById('modal-body'),
  modalFooter: document.getElementById('modal-footer'),
  modalCloseBtn: document.getElementById('modal-close-btn'),
  toastContainer: document.getElementById('toast-container'),
};

// ── INITIALIZATION ──
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initEventListeners();
  initSettings();
  fetchSnapshot();
  startPolling();
});

// ── NAVIGATION ──
function initNavigation() {
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      switchView(view);
    });
  });
}

function switchView(viewName) {
  activeView = viewName;
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });
  document.querySelectorAll('.view-pane').forEach((pane) => {
    pane.classList.toggle('active', pane.id === `view-${viewName}`);
  });

  const titles = {
    accounts: 'Аккаунты и квоты',
    overview: 'Обзор системы',
    routing: 'Маршрутизация запросов',
    providers: 'Модели и провайдеры',
    team: 'Команда агентов',
    analytics: 'Аналитика и телеметрия',
    health: 'Состояние и диагностика',
    logs: 'Журнал событий',
    settings: 'Настройки Hermes Hub',
  };
  if (elements.pageTitle) {
    elements.pageTitle.textContent = titles[viewName] || 'Hermes Hub';
  }

  if (currentSnapshot) {
    renderCurrentView();
  }
}

// ── EVENT LISTENERS ──
function initEventListeners() {
  if (elements.accountsSearch) elements.accountsSearch.addEventListener('input', () => renderAccountsView());
  if (elements.filterProvider) elements.filterProvider.addEventListener('change', () => renderAccountsView());
  if (elements.filterHealth) elements.filterHealth.addEventListener('change', () => renderAccountsView());

  if (elements.btnRefreshAll) {
    elements.btnRefreshAll.addEventListener('click', () => {
      executeAction('refresh_all', {});
    });
  }

  if (elements.btnAddAccount) {
    elements.btnAddAccount.addEventListener('click', () => {
      openAddAccountWizard();
    });
  }

  if (elements.modalCloseBtn) elements.modalCloseBtn.addEventListener('click', closeModal);
  if (elements.modalBackdrop) {
    elements.modalBackdrop.addEventListener('click', (e) => {
      if (e.target === elements.modalBackdrop) closeModal();
    });
  }

  // Logs view filters
  const logsSearch = document.getElementById('logs-search');
  const logsFilterLevel = document.getElementById('logs-filter-level');
  const logsFilterCategory = document.getElementById('logs-filter-category');
  const btnRefreshLogs = document.getElementById('btn-refresh-logs');

  if (logsSearch) logsSearch.addEventListener('input', () => renderLogsList());
  if (logsFilterLevel) logsFilterLevel.addEventListener('change', () => renderLogsList());
  if (logsFilterCategory) logsFilterCategory.addEventListener('change', () => renderLogsList());
  if (btnRefreshLogs) btnRefreshLogs.addEventListener('click', () => fetchLogs());

  // Settings view buttons
  const btnSaveHub = document.getElementById('btn-save-hub-settings');
  if (btnSaveHub) btnSaveHub.addEventListener('click', () => saveHubServerSettings());

  const themeSel = document.getElementById('setting-theme');
  if (themeSel) {
    themeSel.addEventListener('change', () => {
      applyTheme(themeSel.value);
    });
  }
}

// ── SNAPSHOT INGESTION & MONOTONIC SEQ ──
async function fetchSnapshot() {
  const urlParams = new URLSearchParams(window.location.search);
  const forceFixture = USE_MOCK_FIXTURE || urlParams.get('fixture') === '1' || window.location.protocol === 'file:';

  if (forceFixture) {
    try {
      const res = await fetch('snapshot.example.json');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSourceIndicator(true, 'Фикстура (snapshot.example.json)');
      applySnapshot(data);
      return;
    } catch (err) {
      console.error('Failed to load snapshot.example.json:', err);
      setSourceIndicator(false, 'Ошибка фикстуры');
      return;
    }
  }

  try {
    const headers = {};
    if (authToken) headers['X-Hub-Token'] = authToken;

    const res = await fetch('/api/snapshot', { headers });
    if (!res.ok) {
      if (res.status === 404 || res.status === 502 || res.status === 503) {
        throw new Error(`Server returned ${res.status}`);
      }
      const errBody = await res.json().catch(() => ({}));
      showToast(errBody.error || `Ошибка сервера: ${res.status}`, 'error');
      setSourceIndicator(false, `Ошибка /api/snapshot (${res.status})`);
      return;
    }

    const data = await res.json();
    setSourceIndicator(true, 'Live API (/api/snapshot)');
    applySnapshot(data);
  } catch (err) {
    console.warn('Live API unavailable, attempting snapshot.example.json fallback:', err);
    try {
      const fallbackRes = await fetch('snapshot.example.json');
      if (fallbackRes.ok) {
        const fallbackData = await fallbackRes.json();
        setSourceIndicator(true, 'Фикстура (fallback)');
        applySnapshot(fallbackData);
        return;
      }
    } catch (e) {}

    setSourceIndicator(false, 'Сервер недоступен');
  }
}

function applySnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return;

  // Monotonic seq check: reject out-of-order stale responses
  if (typeof snapshot.seq === 'number') {
    if (snapshot.seq < lastAppliedSeq) {
      console.warn(`[Hub] Stale snapshot rejected: seq ${snapshot.seq} < lastAppliedSeq ${lastAppliedSeq}`);
      return;
    }
    lastAppliedSeq = snapshot.seq;
  }

  const isFirstLoad = !currentSnapshot;
  currentSnapshot = snapshot;
  updateGlobalHeader();

  if (isFirstLoad) {
    const params = new URLSearchParams(window.location.search);
    const targetView = params.get('view');
    const targetModal = params.get('modal');
    const targetProfile = params.get('profile');

    if (targetView) {
      switchView(targetView);
    } else {
      renderCurrentView();
    }

    if (targetModal === 'grok_wizard') {
      openAddAccountWizard();
      showWizardStep2('grok');
    } else if (targetModal === 'antigravity_wizard') {
      openAddAccountWizard();
      showWizardStep2('antigravity');
    } else if (targetModal === 'account_details') {
      openAccountDetailsModal(targetProfile || 'ag-w1');
    } else if (targetModal === 'agent_model') {
      const targetRole = params.get('role') || 'coder-primary';
      const ag = (currentSnapshot.agents || []).find(a => a.role_id === targetRole) || (currentSnapshot.agents || [])[1];
      if (ag) openAgentModelModal(ag.role_id, ag.assigned_profile_id);
    }
  } else {
    renderCurrentView();
  }
}

function setSourceIndicator(healthy, text) {
  if (elements.sourceDot) {
    elements.sourceDot.className = `status-dot ${healthy ? 'healthy' : 'error'}`;
  }
  if (elements.sourceText) {
    elements.sourceText.textContent = text;
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  if (pollIntervalMs > 0) {
    pollTimer = setInterval(fetchSnapshot, pollIntervalMs);
  }
}

// ── ACTIONS EXECUTION (POST /api/action) ──
async function executeAction(actionName, actionData = {}) {
  showToast(`Выполняется «${actionName}»...`, 'info');
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['X-Hub-Token'] = authToken;

    const res = await fetch('/api/action', {
      method: 'POST',
      headers,
      body: JSON.stringify({ action: actionName, data: actionData }),
    });

    const result = await res.json().catch(() => ({ ok: false, message: `Ошибка парсинга ответа (${res.status})` }));

    if (result.ok) {
      showToast(result.message || 'Действие выполнено успешно', 'success');
      fetchSnapshot();
      return result;
    } else {
      showToast(result.message || 'Отказ выполнения действия', 'warning');
      return result;
    }
  } catch (err) {
    console.error(`Action ${actionName} failed:`, err);
    showToast(`Ошибка сети: ${err.message}`, 'error');
    return { ok: false, message: `Ошибка сети: ${err.message}` };
  }
}

// ── GLOBAL HEADER ──
function updateGlobalHeader() {
  if (!currentSnapshot) return;

  const totalAccounts = Object.keys(currentSnapshot.all_profiles || {}).length;
  if (elements.navAccountsCount) elements.navAccountsCount.textContent = totalAccounts;

  const readiness = currentSnapshot.readiness || {};
  const isHealthy = readiness.state === 'healthy';
  const readyRoles = readiness.roles_ready_count || 0;
  const totalRoles = readiness.total_roles || 6;

  if (elements.headerReadinessBadge) {
    elements.headerReadinessBadge.className = `header-readiness-badge ${isHealthy ? 'text-healthy' : 'text-warning'}`;
  }
  if (elements.headerReadinessText) {
    elements.headerReadinessText.textContent = readiness.title_ru
      ? `${readiness.title_ru} (${readyRoles}/${totalRoles} ролей)`
      : 'Система готова';
  }

  const kpiReadiness = document.getElementById('kpi-system-readiness');
  const kpiSummary = document.getElementById('kpi-readiness-summary');
  const kpiTotalAccounts = document.getElementById('kpi-total-accounts');
  const kpiAccountsSub = document.getElementById('kpi-accounts-sub');
  const kpiReadyRoles = document.getElementById('kpi-ready-roles');
  const kpiRolesSub = document.getElementById('kpi-roles-sub');
  const kpiProvidersCount = document.getElementById('kpi-providers-count');

  if (kpiReadiness) kpiReadiness.textContent = readiness.title_ru || 'Работает';
  if (kpiSummary) kpiSummary.textContent = readiness.summary_ru || 'Все маршруты доступны';
  if (kpiTotalAccounts) kpiTotalAccounts.textContent = totalAccounts;
  if (kpiAccountsSub) kpiAccountsSub.textContent = `Подключено: ${readiness.accounts_connected_count || totalAccounts}`;
  if (kpiReadyRoles) kpiReadyRoles.textContent = `${readyRoles}/${totalRoles}`;
  if (kpiRolesSub) kpiRolesSub.textContent = `${readyRoles} из ${totalRoles} ролей маршрутизации активны`;
  if (kpiProvidersCount) kpiProvidersCount.textContent = (currentSnapshot.providers || []).length || 5;
}

// ── VIEW ROUTER ──
function renderCurrentView() {
  if (!currentSnapshot) return;
  switch (activeView) {
    case 'accounts':
      renderAccountsView();
      break;
    case 'overview':
      renderOverviewView();
      break;
    case 'routing':
      renderRoutingView();
      break;
    case 'providers':
      renderProvidersView();
      break;
    case 'team':
      renderTeamView();
      break;
    case 'analytics':
      renderAnalyticsView();
      break;
    case 'health':
      renderHealthView();
      break;
    case 'logs':
      renderLogsView();
      break;
    case 'settings':
      renderSettingsView();
      break;
  }
}

// ═══════════════════════════════════════════════════════════════
//  1. ACCOUNTS VIEW (Compact Fixed-Height Cards & Quotas)
// ═══════════════════════════════════════════════════════════════
function renderAccountsView() {
  const container = elements.accountsContainer;
  if (!container || !currentSnapshot) return;

  const searchQuery = (elements.accountsSearch ? elements.accountsSearch.value : '').trim().toLowerCase();
  const providerFilter = elements.filterProvider ? elements.filterProvider.value : 'all';
  const healthFilter = elements.filterHealth ? elements.filterHealth.value : 'all';

  const providerNames = {
    antigravity: 'Google Antigravity',
    'openai-codex': 'OpenAI Codex',
    'opencode-go': 'OpenCode Go',
    claude: 'Claude (Anthropic)',
    grok: 'Grok (xAI)',
  };

  const profilesByProv = currentSnapshot.profiles_by_provider || {};
  let totalProfiles = 0;
  let visibleProfiles = 0;
  let html = '';

  for (const [providerId, profiles] of Object.entries(profilesByProv)) {
    if (providerFilter !== 'all' && providerFilter !== providerId) continue;

    const filtered = profiles.filter((p) => {
      totalProfiles++;
      const matchesSearch =
        !searchQuery ||
        (p.display_name && p.display_name.toLowerCase().includes(searchQuery)) ||
        (p.account_identity && p.account_identity.toLowerCase().includes(searchQuery)) ||
        (p.email && p.email.toLowerCase().includes(searchQuery)) ||
        (p.profile_id && p.profile_id.toLowerCase().includes(searchQuery)) ||
        (p.assigned_roles && p.assigned_roles.some((r) => r.toLowerCase().includes(searchQuery))) ||
        (p.preferred_models && p.preferred_models.some((m) => m.toLowerCase().includes(searchQuery)));

      const matchesHealth =
        healthFilter === 'all' ||
        p.health_state === healthFilter ||
        (healthFilter === 'disabled' && (p.is_cold_spare || !p.enabled || p.health_state === 'disabled'));

      return matchesSearch && matchesHealth;
    });

    if (filtered.length === 0) continue;
    visibleProfiles += filtered.length;

    html += `
      <div class="provider-group">
        <div class="provider-group-header">
          <div class="provider-group-title">
            <span class="provider-dot" style="color: var(--prov-${providerId.replace('openai-', '').replace('-go', '')})">●</span>
            <span>${providerNames[providerId] || providerId}</span>
          </div>
          <div class="provider-group-count">${filtered.length} аккаунт(ов)</div>
        </div>
        <div class="accounts-grid">
          ${filtered.map((p) => renderAccountCard(p)).join('')}
        </div>
      </div>
    `;
  }

  container.innerHTML = html || '<div class="view-header-note">Аккаунты по заданным фильтрам не найдены.</div>';
  if (elements.accountsStatsSummary) {
    elements.accountsStatsSummary.innerHTML = `Показано: <strong>${visibleProfiles}</strong> из <strong>${totalProfiles}</strong> аккаунтов`;
  }

  container.querySelectorAll('.account-card').forEach((card) => {
    card.addEventListener('click', (e) => {
      // If click was on refresh button, skip modal
      if (e.target.closest('.btn-ghost')) return;
      const profileId = card.dataset.profileId;
      openAccountDetailsModal(profileId);
    });
  });
}

function renderAccountCard(profile) {
  const isMain = profile.is_main_account || profile.is_main_orchestrator;
  const roles = (profile.assigned_roles || []).join(', ') || 'Роль: Н/Д';
  const identity = profile.email || profile.account_identity || profile.display_name || profile.profile_id;
  const healthState = profile.health_state || 'unknown';
  const healthLabel = profile.health_label_ru || (profile.enabled ? 'Работает' : 'Отключён');
  const plan = profile.plan_code && profile.plan_code !== 'UNKNOWN' ? profile.plan_code : '';

  const quotaSnap = profile.quota_snapshot || (currentSnapshot.quotas || {})[profile.profile_id];
  const buckets = (quotaSnap && quotaSnap.buckets) ? quotaSnap.buckets : [];
  const unavailableReason = quotaSnap ? quotaSnap.unavailable_reason : null;

  let quotaGridHtml = '';

  if (buckets.length > 0) {
    const visibleBuckets = buckets.slice(0, 4);
    quotaGridHtml = `
      <div class="account-quota-grid ${visibleBuckets.length === 1 ? 'single-cell' : ''}">
        ${visibleBuckets.map((b) => renderQuotaCell(b, unavailableReason)).join('')}
      </div>
    `;
  } else {
    let reasonText = unavailableReason;
    if (!unavailableReason && quotaSnap && quotaSnap.is_loading) {
      reasonText = 'Загрузка квот…';
    } else if (!reasonText) {
      reasonText = (profile.health_state === 'not_configured' || profile.health_state === 'auth_required')
        ? 'Аккаунт не подключён'
        : 'Провайдер не отдаёт лимиты';
    }
    quotaGridHtml = `
      <div class="account-quota-grid single-cell">
        <div class="quota-cell">
          <div class="quota-cell-top">
            <span class="quota-cell-title">Квота</span>
            <span class="quota-cell-value text-muted">Н/Д</span>
          </div>
          <div class="quota-bar-track">
            <div class="quota-bar-fill" style="width: 0%; background-color: var(--status-disabled);"></div>
          </div>
          <div class="quota-cell-reset" title="${escapeHtml(reasonText)}">${escapeHtml(reasonText)}</div>
        </div>
      </div>
    `;
  }

  return `
    <div class="account-card ${isMain ? 'main-account' : ''}" data-profile-id="${escapeHtml(profile.profile_id)}">
      <div class="account-card-header">
        <div class="account-provider-tag">
          <span>${escapeHtml(profile.provider_display_name || profile.provider)}</span>
        </div>
        <div class="account-badges">
          ${plan ? `<span class="badge badge-plan">${escapeHtml(plan)}</span>` : ''}
          <span class="badge badge-status ${healthState}">● ${escapeHtml(healthLabel)}</span>
        </div>
      </div>

      <div class="account-identity-row">
        <div class="account-email" title="${escapeHtml(identity)}">${escapeHtml(identity)}</div>
        <div class="account-meta" title="${escapeHtml(profile.display_name)} • ${escapeHtml(roles)}">
          ${escapeHtml(profile.display_name)} • ${escapeHtml(roles)}
        </div>
      </div>

      ${quotaGridHtml}
    </div>
  `;
}

function renderQuotaCell(bucket, unavailableReason) {
  const remaining = bucket.remaining_percent;
  let formattedValue = 'Н/Д';
  let barWidth = 0;
  let colorClass = 'var(--status-disabled)';

  if (typeof remaining === 'number') {
    formattedValue = `${remaining.toFixed(1)}%`;
    barWidth = Math.max(0, Math.min(100, remaining));
    if (remaining <= 0) colorClass = 'var(--status-error)';
    else if (remaining < 20) colorClass = 'var(--status-warning)';
    else colorClass = 'var(--status-healthy)';
  } else if (unavailableReason) {
    formattedValue = 'Н/Д';
  }

  let resetText = bucket.reset_at
    ? `Сброс: ${formatIsoDate(bucket.reset_at)}`
    : (bucket.period ? `Период: ${bucket.period}` : (unavailableReason || 'Период провайдера'));

  return `
    <div class="quota-cell">
      <div class="quota-cell-top">
        <span class="quota-cell-title" title="${escapeHtml(bucket.display_name)}">${escapeHtml(bucket.display_name)}</span>
        <span class="quota-cell-value" style="color: ${colorClass}">${formattedValue}</span>
      </div>
      <div class="quota-bar-track">
        <div class="quota-bar-fill" style="width: ${barWidth}%; background-color: ${colorClass}"></div>
      </div>
      <div class="quota-cell-reset" title="${escapeHtml(resetText)}">${escapeHtml(resetText)}</div>
    </div>
  `;
}

// ═══════════════════════════════════════════════════════════════
//  2. OVERVIEW VIEW
// ═══════════════════════════════════════════════════════════════
function renderOverviewView() {
  if (!currentSnapshot) return;

  const diagramBox = document.getElementById('overview-route-diagram');
  if (diagramBox) {
    const roles = currentSnapshot.routing || {};
    let diagramHtml = '';

    for (const [roleId, pipeline] of Object.entries(roles)) {
      const nodes = pipeline.nodes || [];

      diagramHtml += `
        <div class="diagram-column">
          <div class="diagram-column-header">${escapeHtml(pipeline.role_name_ru || roleId)}</div>
          ${nodes.map((node, idx) => `
            <div class="diagram-node ${node.is_active ? 'active' : ''}">
              <div style="display:flex; justify-content:space-between; font-weight:600; font-size:11px;">
                <span>${idx === 0 ? '★ Основной' : `Резерв ${idx}`}</span>
                <span class="${node.is_active ? 'text-healthy' : 'text-muted'}">${node.is_active ? '● Активен' : 'Ожидание'}</span>
              </div>
              <div style="font-size:12px; font-weight:700; margin-top:2px;">${escapeHtml(node.display_name || node.profile_id)}</div>
              <div style="font-size:10px; color:var(--text-muted);">${escapeHtml(node.provider)} • ${escapeHtml(node.model)}</div>
            </div>
          `).join('')}
        </div>
      `;
    }
    diagramBox.innerHTML = diagramHtml || '<div class="empty-text">Нет данных маршрутизации.</div>';
  }

  const provSummaryBox = document.getElementById('overview-providers-summary');
  if (provSummaryBox) {
    const providers = currentSnapshot.providers || [];
    provSummaryBox.innerHTML = providers.map((prov) => `
      <div class="provider-summary-card">
        <div class="provider-summary-title">${escapeHtml(prov.provider_name || prov.provider_id)}</div>
        <div class="provider-summary-stats">
          Онлайн: <strong>${prov.online_count}/${prov.connected_count}</strong> •
          Требуют входа: <strong>${prov.auth_required_count}</strong> •
          Холодный резерв: <strong>${prov.cold_spare_count}</strong>
        </div>
        <div class="provider-models-tag">
          Модели: ${prov.discovered_models && prov.discovered_models.length ? escapeHtml(prov.discovered_models.join(', ')) : 'Н/Д — список моделей ещё не получен'}
        </div>
      </div>
    `).join('') || '<div class="empty-text">Нет данных провайдеров.</div>';
  }
}

// ═══════════════════════════════════════════════════════════════
//  3. ROUTING VIEW
// ═══════════════════════════════════════════════════════════════
function renderRoutingView() {
  const container = document.getElementById('routing-pipelines-container');
  if (!container || !currentSnapshot) return;

  const routing = currentSnapshot.routing || {};
  let html = '';

  for (const [roleId, pipeline] of Object.entries(routing)) {
    const nodes = pipeline.nodes || [];

    html += `
      <div class="pipeline-card">
        <div class="pipeline-header">
          <div>
            <div class="pipeline-title">${escapeHtml(pipeline.role_name_ru || roleId)}</div>
            <div style="font-size:11px; color:var(--text-muted);">
              Модель по умолчанию: <strong>${escapeHtml(pipeline.default_model || '—')}</strong> •
              ${pipeline.session_affinity ? 'Session Affinity включена' : 'Без affinity'}
            </div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="openEditRouteModal('${escapeHtml(roleId)}')">
            Изменить цепочку →
          </button>
        </div>

        <div class="pipeline-chain-flow">
          ${nodes.map((node, index) => `
            <div class="pipeline-node-chip ${node.is_active ? 'active' : ''}">
              <div style="display:flex; justify-content:space-between; font-size:10px;">
                <strong style="color:var(--text-accent);">${index === 0 ? 'Основной' : `Резерв ${index}`}</strong>
                <span class="${node.is_active ? 'text-healthy' : 'text-muted'}">${node.is_active ? '● АКТИВЕН' : ''}</span>
              </div>
              <div style="font-size:12px; font-weight:700;">${escapeHtml(node.display_name || node.profile_id)}</div>
              <div style="font-size:10px; color:var(--text-muted);">${escapeHtml(node.provider)} • ${escapeHtml(node.model)}</div>
              ${node.failover_reason ? `<div style="font-size:9px; color:var(--status-warning); margin-top:2px;">⚠ ${escapeHtml(node.failover_reason)}</div>` : ''}
            </div>
          `).join('') || '<div class="empty-text">Цепочка не настроена.</div>'}
        </div>
      </div>
    `;
  }

  container.innerHTML = html || '<div class="empty-text">Маршруты отсутствуют.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  4. PROVIDERS & MODELS VIEW
// ═══════════════════════════════════════════════════════════════
function renderProvidersView() {
  const container = document.getElementById('providers-full-container');
  if (!container || !currentSnapshot) return;

  const providers = currentSnapshot.providers || [];
  container.innerHTML = providers.map((prov) => `
    <div class="section-card" style="margin-bottom:16px;">
      <div class="section-card-header">
        <div>
          <div class="section-card-title">${escapeHtml(prov.provider_name || prov.provider_id)}</div>
          <div class="section-card-subtitle">
            Всего слотов: <strong>${prov.total_slots}</strong> • Подключено: <strong>${prov.connected_count}</strong> • Онлайн: <strong>${prov.online_count}</strong>
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(prov.provider_id)}')">
          ↻ Запросить модели
        </button>
      </div>

      <div style="padding:14px;">
        <div style="font-weight:600; font-size:12px; margin-bottom:6px; color:var(--text-secondary);">
          Обнаруженные модели:
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;">
          ${(prov.discovered_models && prov.discovered_models.length > 0)
            ? prov.discovered_models.map(m => `<span class="account-model-tag" style="font-size:11px; padding:4px 8px;">${escapeHtml(m)}</span>`).join('')
            : '<span style="color:var(--text-muted); font-size:12px;">Н/Д — список моделей ещё не получен от провайдера</span>'
          }
        </div>
      </div>
    </div>
  `).join('') || '<div class="empty-text">Нет данных провайдеров.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  5. TEAM VIEW
// ═══════════════════════════════════════════════════════════════
function renderTeamView() {
  const container = document.getElementById('team-cards-container');
  if (!container || !currentSnapshot) return;

  const agents = currentSnapshot.agents || [];
  container.innerHTML = agents.map((ag) => `
    <div class="agent-card ${ag.is_main_orchestrator ? 'is-orchestrator' : ''}">
      <div class="agent-card-header">
        <div>
          <div class="agent-role-title">${escapeHtml(ag.role_name_ru || ag.role_id)}</div>
          <div class="agent-role-desc">${escapeHtml(ag.role_description_ru || '')}</div>
        </div>
        <span class="agent-status-badge ${ag.is_active ? 'active' : 'idle'}">
          ${ag.is_active ? '● АКТИВЕН' : 'ОЖИДАНИЕ'}
        </span>
      </div>

      <div class="agent-assigned-info">
        <div style="font-size:11px; color:var(--text-muted);">Назначенный аккаунт:</div>
        <div style="font-weight:700; font-size:13px;">${escapeHtml(ag.assigned_display_name || ag.assigned_profile_id || 'Не назначен')}</div>
        <div style="font-size:11px; color:var(--text-secondary); margin-top:2px;">
          Провайдер: <strong>${escapeHtml(ag.provider_display_name || ag.provider)}</strong> • Модель: <strong>${escapeHtml(ag.model || 'default')}</strong>
        </div>
      </div>

      <div class="agent-card-footer">
        <button class="btn btn-secondary btn-sm" onclick="openAgentModelModal('${escapeHtml(ag.role_id)}', '${escapeHtml(ag.assigned_profile_id)}')">
          Выбрать модель
        </button>
        <button class="btn btn-secondary btn-sm" onclick="openEditRouteModal('${escapeHtml(ag.role_id)}')">
          Маршрут
        </button>
      </div>
    </div>
  `).join('') || '<div class="empty-text">Список агентов пуст.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  6. ANALYTICS VIEW (P0-1 Real Telemetry & Honesty)
// ═══════════════════════════════════════════════════════════════
function renderAnalyticsView() {
  if (!currentSnapshot) return;
  const metrics = currentSnapshot.metrics || {};
  const telemetry = metrics.telemetry || {};
  const global = telemetry.global || {};

  // KPI 1: Total Calls
  const totalCallsEl = document.getElementById('analytics-total-calls');
  const callsBreakdownEl = document.getElementById('analytics-calls-breakdown');
  if (totalCallsEl) {
    totalCallsEl.textContent = global.total_calls !== null && global.total_calls !== undefined ? global.total_calls : 'Н/Д';
  }
  if (callsBreakdownEl) {
    const succ = global.successful_calls ?? 0;
    const fail = global.failed_calls ?? 0;
    callsBreakdownEl.textContent = `Успешно: ${succ} • Сбоев: ${fail} (окно: 24ч)`;
  }

  // KPI 2: Error Rate
  const errorRateEl = document.getElementById('analytics-error-rate');
  const errorRateSubEl = document.getElementById('analytics-error-rate-sub');
  if (errorRateEl) {
    if (global.error_rate !== null && global.error_rate !== undefined) {
      const pct = (global.error_rate * 100).toFixed(1);
      errorRateEl.textContent = `${pct}%`;
      errorRateEl.className = `kpi-value ${global.error_rate > 0.5 ? 'text-error' : (global.error_rate > 0.2 ? 'text-warning' : 'text-healthy')}`;
    } else {
      errorRateEl.textContent = 'Н/Д';
      errorRateEl.className = 'kpi-value text-muted';
    }
  }
  if (errorRateSubEl) {
    errorRateSubEl.textContent = global.failed_calls ? `${global.failed_calls} отказов из ${global.total_calls || 0} вызовов` : 'Отказов не зафиксировано';
  }

  // KPI 3: Latency
  const latencyEl = document.getElementById('analytics-latency-p50');
  const latencySubEl = document.getElementById('analytics-latency-sub');
  if (latencyEl) {
    if (global.latency_p50_ms !== null && global.latency_p50_ms !== undefined) {
      latencyEl.textContent = `${global.latency_p50_ms.toFixed(1)} ms`;
    } else {
      latencyEl.textContent = 'Н/Д';
    }
  }
  if (latencySubEl) {
    const p95Str = global.latency_p95_ms != null
      ? (global.latency_p95_ms >= 1000 ? `${(global.latency_p95_ms / 1000).toFixed(1)} s` : `${global.latency_p95_ms.toFixed(1)} ms`)
      : 'Н/Д';
    const maxStr = global.latency_max_ms != null
      ? (global.latency_max_ms >= 1000 ? `${(global.latency_max_ms / 1000).toFixed(1)} s` : `${global.latency_max_ms.toFixed(1)} ms`)
      : 'Н/Д';
    latencySubEl.textContent = `p95: ${p95Str} • max: ${maxStr}`;
  }

  // KPI 4: Tokens (Honesty rule: null means N/D, never 0)
  const tokensEl = document.getElementById('analytics-tokens-total');
  const tokensSubEl = document.getElementById('analytics-tokens-sub');
  const hasTokens = global.total_tokens !== null && global.total_tokens !== undefined;
  if (tokensEl) {
    if (hasTokens) {
      tokensEl.textContent = global.total_tokens.toLocaleString('ru-RU');
    } else {
      tokensEl.textContent = 'Н/Д';
    }
  }
  if (tokensSubEl) {
    if (hasTokens) {
      tokensSubEl.textContent = 'Учитывается провайдером';
    } else {
      tokensSubEl.textContent = 'Н/Д: провайдеры не отдают данные о токенах';
    }
  }

  // Providers Table
  const provTableBox = document.getElementById('analytics-providers-table');
  if (provTableBox) {
    const byProv = telemetry.by_provider || {};
    const provKeys = Object.keys(byProv);
    if (provKeys.length === 0) {
      provTableBox.innerHTML = '<div class="empty-text">Нет данных телеметрии по провайдерам.</div>';
    } else {
      const rowsHtml = provKeys.map((pId) => {
        const pData = byProv[pId] || {};
        const errPct = pData.error_rate != null ? (pData.error_rate * 100).toFixed(1) : 'Н/Д';
        const p50 = pData.latency_p50_ms != null ? `${pData.latency_p50_ms.toFixed(1)} ms` : 'Н/Д';
        const p95 = pData.latency_p95_ms != null
          ? (pData.latency_p95_ms >= 1000 ? `${(pData.latency_p95_ms / 1000).toFixed(1)} s` : `${pData.latency_p95_ms.toFixed(1)} ms`)
          : 'Н/Д';
        const barColor = (pData.error_rate || 0) > 0.5 ? 'var(--status-error)' : 'var(--status-healthy)';
        const barW = Math.min(100, Math.max(0, (pData.error_rate || 0) * 100));

        return `
          <tr>
            <td><strong>${escapeHtml(pId)}</strong></td>
            <td>${pData.total_calls ?? 'Н/Д'}</td>
            <td class="text-healthy">${pData.successful_calls ?? 0}</td>
            <td class="${(pData.failed_calls || 0) > 0 ? 'text-error' : 'text-muted'}">${pData.failed_calls ?? 0}</td>
            <td>
              <div class="cell-bar-container">
                <span>${errPct}${errPct !== 'Н/Д' ? '%' : ''}</span>
                <div class="cell-bar-track">
                  <div class="cell-bar-fill" style="width:${barW}%; background:${barColor};"></div>
                </div>
              </div>
            </td>
            <td>${p50}</td>
            <td>${p95}</td>
            <td class="text-muted">Н/Д (не отдаются)</td>
          </tr>
        `;
      }).join('');

      provTableBox.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Провайдер</th>
              <th>Всего вызовов</th>
              <th>Успешно</th>
              <th>Сбои</th>
              <th>Доля ошибок</th>
              <th>p50</th>
              <th>p95</th>
              <th>Токены</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      `;
    }
  }

  // Roles Table
  const rolesTableBox = document.getElementById('analytics-roles-table');
  if (rolesTableBox) {
    const byRole = telemetry.by_role || {};
    const roleKeys = Object.keys(byRole);
    if (roleKeys.length === 0) {
      rolesTableBox.innerHTML = '<div class="empty-text">Нет данных телеметрии по ролям агентов.</div>';
    } else {
      const rowsHtml = roleKeys.map((rId) => {
        const rData = byRole[rId] || {};
        const errPct = rData.error_rate != null ? (rData.error_rate * 100).toFixed(1) : '0.0';
        const p50 = rData.latency_p50_ms != null ? `${rData.latency_p50_ms.toFixed(1)} ms` : 'Н/Д';
        const p95 = rData.latency_p95_ms != null
          ? (rData.latency_p95_ms >= 1000 ? `${(rData.latency_p95_ms / 1000).toFixed(1)} s` : `${rData.latency_p95_ms.toFixed(1)} ms`)
          : 'Н/Д';
        const roleInfo = (currentSnapshot.routing || {})[rId];
        const rName = (roleInfo && roleInfo.role_name_ru) || rId;

        return `
          <tr>
            <td><strong>${escapeHtml(rName)}</strong> <span style="font-size:10px; color:var(--text-muted);">(${escapeHtml(rId)})</span></td>
            <td>${rData.total_calls ?? 'Н/Д'}</td>
            <td class="text-healthy">${(rData.total_calls ?? 0) - (rData.failed_calls ?? 0)}</td>
            <td class="${(rData.failed_calls || 0) > 0 ? 'text-error' : 'text-muted'}">${rData.failed_calls ?? 0}</td>
            <td>${errPct}%</td>
            <td>${p50}</td>
            <td>${p95}</td>
          </tr>
        `;
      }).join('');

      rolesTableBox.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Роль агента</th>
              <th>Всего вызовов</th>
              <th>Успешно</th>
              <th>Сбои</th>
              <th>Доля ошибок</th>
              <th>p50</th>
              <th>p95</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      `;
    }
  }
}

// ═══════════════════════════════════════════════════════════════
//  7. HEALTH VIEW (P0-2 Host & System Diagnostics)
// ═══════════════════════════════════════════════════════════════
function renderHealthView() {
  if (!currentSnapshot) return;
  const readiness = currentSnapshot.readiness || {};
  const metrics = currentSnapshot.metrics || {};
  const host = metrics.host || {};

  // 1. Readiness Banner
  const bannerBox = document.getElementById('health-readiness-banner');
  if (bannerBox) {
    const st = (readiness.state || 'healthy').toLowerCase();
    bannerBox.className = `readiness-banner ${st}`;
    bannerBox.innerHTML = `
      <div class="readiness-banner-header">
        <div class="readiness-banner-title">
          <span class="status-dot ${st}"></span>
          <span>${escapeHtml(readiness.title_ru || 'Система готова к работе')}</span>
        </div>
        <span class="badge ${st === 'healthy' ? 'healthy' : ''}">${escapeHtml(readiness.state || 'HEALTHY')}</span>
      </div>
      <div class="readiness-banner-summary">
        ${escapeHtml(readiness.summary_ru || 'Все настроенные маршруты и профили доступны.')}
      </div>
      <div class="readiness-banner-stats">
        <span>Ролей в строю: <strong>${readiness.roles_ready_count ?? 0} / ${readiness.total_roles ?? 6}</strong></span>
        <span>Аккаунтов подключено: <strong>${readiness.accounts_connected_count ?? 0} / ${readiness.total_accounts ?? 0}</strong></span>
        <span>Провайдеров онлайн: <strong>${readiness.providers_ready_count ?? 5} / ${readiness.total_providers ?? 5}</strong></span>
      </div>
    `;
  }

  // 2. Host Resources Grid
  const hostBox = document.getElementById('health-host-resources');
  if (hostBox) {
    const cpuPct = host.cpu_percent != null ? host.cpu_percent.toFixed(1) : 'Н/Д';
    const cpuVal = host.cpu_percent != null ? host.cpu_percent : 0;

    const memPct = host.memory_percent != null ? host.memory_percent.toFixed(1) : 'Н/Д';
    const memMb = host.memory_used_mb != null ? (host.memory_used_mb >= 1024 ? `${(host.memory_used_mb / 1024).toFixed(1)} GB` : `${host.memory_used_mb.toFixed(0)} MB`) : '';
    const memVal = host.memory_percent != null ? host.memory_percent : 0;

    const diskPct = host.disk_percent != null ? host.disk_percent.toFixed(1) : 'Н/Д';
    const diskGb = host.disk_used_gb != null ? `${host.disk_used_gb.toFixed(1)} GB` : '';
    const diskVal = host.disk_percent != null ? host.disk_percent : 0;

    const netSpeed = host.net_speed_mbps != null ? `${host.net_speed_mbps.toFixed(1)} Mbps` : 'Н/Д';
    const netSub = host.net_speed_mbps != null ? 'Активное соединение' : 'Н/Д: замер скорости сети отключён';

    hostBox.innerHTML = `
      <div class="host-resource-card">
        <div class="host-resource-header">
          <span class="host-resource-title">CPU (Процессор)</span>
          <span class="host-resource-value">${cpuPct}${cpuPct !== 'Н/Д' ? '%' : ''}</span>
        </div>
        <div class="host-resource-bar">
          <div class="host-resource-fill" style="width:${Math.min(100, Math.max(0, cpuVal))}%; background:${cpuVal > 85 ? 'var(--status-error)' : 'var(--accent)'};"></div>
        </div>
        <div class="host-resource-sub">Нагрузка хост-системы</div>
      </div>

      <div class="host-resource-card">
        <div class="host-resource-header">
          <span class="host-resource-title">RAM (Оперативная память)</span>
          <span class="host-resource-value">${memPct}${memPct !== 'Н/Д' ? '%' : ''}</span>
        </div>
        <div class="host-resource-bar">
          <div class="host-resource-fill" style="width:${Math.min(100, Math.max(0, memVal))}%; background:${memVal > 85 ? 'var(--status-error)' : 'var(--accent)'};"></div>
        </div>
        <div class="host-resource-sub">${memMb ? `Использовано: ${memMb}` : 'Статус использования RAM'}</div>
      </div>

      <div class="host-resource-card">
        <div class="host-resource-header">
          <span class="host-resource-title">Диск (Хранилище)</span>
          <span class="host-resource-value">${diskPct}${diskPct !== 'Н/Д' ? '%' : ''}</span>
        </div>
        <div class="host-resource-bar">
          <div class="host-resource-fill" style="width:${Math.min(100, Math.max(0, diskVal))}%; background:${diskVal > 90 ? 'var(--status-error)' : 'var(--accent)'};"></div>
        </div>
        <div class="host-resource-sub">${diskGb ? `Занято: ${diskGb}` : 'Статус дискового пространства'}</div>
      </div>

      <div class="host-resource-card">
        <div class="host-resource-header">
          <span class="host-resource-title">Сеть (Пропускная способность)</span>
          <span class="host-resource-value text-muted">${netSpeed}</span>
        </div>
        <div class="host-resource-bar">
          <div class="host-resource-fill" style="width:0%; background:var(--text-muted);"></div>
        </div>
        <div class="host-resource-sub">${netSub}</div>
      </div>
    `;
  }

  // 3. Warnings List
  const warningsBox = document.getElementById('health-warnings-list');
  if (warningsBox) {
    const warnings = readiness.warnings || [];
    if (warnings.length === 0) {
      warningsBox.innerHTML = `
        <div style="padding:14px; color:var(--status-healthy); font-size:12px; display:flex; align-items:center; gap:8px;">
          <span>✓</span>
          <span>Все системы работают штатно: сбоев конфигурации и деградации маршрутов не обнаружено.</span>
        </div>
      `;
    } else {
      warningsBox.innerHTML = warnings.map((w) => `
        <div class="warning-item">
          <span class="warning-icon">⚠️</span>
          <div class="warning-text">${escapeHtml(w)}</div>
        </div>
      `).join('');
    }
  }
}

// ═══════════════════════════════════════════════════════════════
//  8. LOGS VIEW (P0-3 GET /api/events with Filtering & Search)
// ═══════════════════════════════════════════════════════════════
async function fetchLogs() {
  const container = document.getElementById('logs-container');
  if (container && cachedEvents.length === 0) {
    container.innerHTML = '<div class="empty-text">⏳ Загрузка журнала событий...</div>';
  }

  try {
    const headers = {};
    if (authToken) headers['X-Hub-Token'] = authToken;

    const res = await fetch('/api/events?limit=100', { headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    cachedEvents = data.events || [];
    renderLogsList();
  } catch (err) {
    console.error('Failed to fetch events:', err);
    if (container) {
      container.innerHTML = `<div class="empty-text text-error">Не удалось получить события: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderLogsView() {
  fetchLogs();
}

function renderLogsList() {
  const container = document.getElementById('logs-container');
  if (!container) return;

  const searchInput = document.getElementById('logs-search');
  const levelSelect = document.getElementById('logs-filter-level');
  const catSelect = document.getElementById('logs-filter-category');

  const q = (searchInput ? searchInput.value : '').trim().toLowerCase();
  const levelFilter = levelSelect ? levelSelect.value : 'all';
  const catFilter = catSelect ? catSelect.value : 'all';

  let filtered = cachedEvents.filter((ev) => {
    if (levelFilter !== 'all' && (ev.level || 'info').toLowerCase() !== levelFilter.toLowerCase()) {
      return false;
    }
    if (catFilter !== 'all' && (ev.category || '').toLowerCase() !== catFilter.toLowerCase()) {
      return false;
    }
    if (q) {
      const msg = (ev.message || '').toLowerCase();
      const det = (ev.details || '').toLowerCase();
      if (!msg.includes(q) && !det.includes(q)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-text">Нет событий, соответствующих выбранным фильтрам.</div>';
    return;
  }

  container.innerHTML = filtered.map((ev) => {
    const lvl = (ev.level || 'info').toLowerCase();
    return `
      <div class="log-entry">
        <span class="log-timestamp">${escapeHtml(ev.timestamp || '—')}</span>
        <span class="log-badge ${lvl}">${escapeHtml(lvl.toUpperCase())}</span>
        <span class="log-category">${escapeHtml((ev.category || 'system').toUpperCase())}</span>
        <div class="log-content">
          <div class="log-message">${escapeHtml(ev.message || '')}</div>
          ${ev.details ? `<div class="log-details">${escapeHtml(ev.details)}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ═══════════════════════════════════════════════════════════════
//  9. SETTINGS VIEW (P0-4 GET /api/settings & save_settings)
// ═══════════════════════════════════════════════════════════════
async function loadServerSettings() {
  try {
    const headers = {};
    if (authToken) headers['X-Hub-Token'] = authToken;

    const res = await fetch('/api/settings', { headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentSettings = data;
    populateSettingsForm(data);
  } catch (err) {
    console.error('Failed to load settings:', err);
  }
}

function populateSettingsForm(s) {
  const hostInput = document.getElementById('setting-server-host');
  const portInput = document.getElementById('setting-server-port');
  const tokenBadge = document.getElementById('setting-token-status-badge');
  const quotaSel = document.getElementById('setting-quota-interval');
  const themeSel = document.getElementById('setting-theme');

  const pathHome = document.getElementById('path-hermes-home');
  const pathConfig = document.getElementById('path-config-dir');
  const pathLog = document.getElementById('path-log-file');

  if (hostInput) hostInput.value = s.web_api_host || '127.0.0.1';
  if (portInput) portInput.value = s.web_api_port || 5800;
  if (tokenBadge) {
    tokenBadge.textContent = s.web_api_token_configured ? '✓ Токен задан' : 'Токен не задан';
    tokenBadge.className = `badge ${s.web_api_token_configured ? 'healthy' : ''}`;
  }
  if (quotaSel && s.quota_refresh_interval_sec) {
    quotaSel.value = String(s.quota_refresh_interval_sec);
  }
  if (themeSel && s.theme) {
    themeSel.value = s.theme;
    applyTheme(s.theme);
  }

  if (pathHome) pathHome.textContent = s.hermes_home || '~/.hermes';
  if (pathConfig) pathConfig.textContent = s.config_dir || '~/.hermes/config';
  if (pathLog) pathLog.textContent = s.log_file || '~/.hermes/logs/hermes-hub.log';
}

function applyTheme(theme) {
  if (theme === 'light') {
    document.body.setAttribute('data-theme', 'light');
    document.body.classList.add('theme-light');
  } else {
    document.body.removeAttribute('data-theme');
    document.body.classList.remove('theme-light');
  }
}

function renderSettingsView() {
  loadServerSettings();
}

async function saveHubServerSettings() {
  const hostInput = document.getElementById('setting-server-host');
  const portInput = document.getElementById('setting-server-port');
  const tokenInput = document.getElementById('setting-server-token-input');
  const quotaSel = document.getElementById('setting-quota-interval');
  const themeSel = document.getElementById('setting-theme');

  const payload = {
    web_api_host: hostInput ? hostInput.value.trim() : '127.0.0.1',
    web_api_port: portInput ? parseInt(portInput.value, 10) || 5800 : 5800,
    quota_refresh_interval_sec: quotaSel ? parseInt(quotaSel.value, 10) || 300 : 300,
    theme: themeSel ? themeSel.value : 'system',
  };

  if (tokenInput && tokenInput.value.trim()) {
    payload.web_api_token = tokenInput.value.trim();
  }

  const res = await executeAction('save_settings', payload);
  if (res.ok) {
    if (themeSel) applyTheme(themeSel.value);
    showToast('Настройки сервера успешно сохранены', 'success');
    if (tokenInput) tokenInput.value = '';
    loadServerSettings();
  }
}

// ── MODALS (Account Details, Model Choice, Routing, Wizard) ──
function openAccountDetailsModal(profileId) {
  if (!currentSnapshot) return;
  const profile = (currentSnapshot.all_profiles || {})[profileId];
  if (!profile) return;

  const provSummary = (currentSnapshot.providers || []).find(p => p.provider_id === profile.provider);
  const discoveredModels = (provSummary && provSummary.discovered_models) ? provSummary.discovered_models : [];
  const currentModel = (profile.preferred_models && profile.preferred_models.length) ? profile.preferred_models[0] : '';
  const qs = profile.quota_snapshot;
  const buckets = (qs && qs.buckets) ? qs.buckets : [];

  let modelBlockHtml = '';
  if (discoveredModels.length > 0) {
    modelBlockHtml = `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <label style="display:block; font-weight:600; font-size:12px; margin-bottom:6px;">Предпочитаемая модель профиля:</label>
        <div style="display:flex; gap:8px;">
          <select id="modal-model-select" class="select-filter" style="flex:1;">
            ${discoveredModels.map(m => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
          </select>
          <button class="btn btn-secondary btn-sm" onclick="handleSaveProfileModel('${escapeHtml(profileId)}')">Сохранить</button>
        </div>
      </div>
    `;
  } else {
    modelBlockHtml = `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <div style="font-size:12px; color:var(--status-warning); margin-bottom:6px;">
          ⚠ Список моделей ещё не получен от провайдера ${escapeHtml(profile.provider_display_name || profile.provider)}.
        </div>
        <button class="btn btn-secondary btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(profile.provider)}', '${escapeHtml(profileId)}')">↻ Запросить список моделей</button>
      </div>
    `;
  }

  elements.modalTitle.textContent = `Учетная запись: ${profile.display_name || profileId}`;
  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    <div style="margin-bottom:14px;">
      <div style="font-size:14px; font-weight:700;">${escapeHtml(profile.account_identity || profile.email || profileId)}</div>
      <div style="font-size:12px; color:var(--text-muted);">
        Провайдер: <strong>${escapeHtml(profile.provider_display_name || profile.provider)}</strong> •
        Тариф: <strong>${escapeHtml(profile.plan || 'Неизвестен')}</strong> •
        Статус: <strong class="text-healthy">${escapeHtml(profile.health_label_ru || 'Работает')}</strong>
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">
        Назначенные роли: <strong>${escapeHtml((profile.assigned_roles || []).join(', ') || 'Нет')}</strong>
      </div>
    </div>

    ${modelBlockHtml}

    <h3 style="font-size:13px; font-weight:700; margin-bottom:8px; border-bottom:1px solid var(--border-subtle); padding-bottom:4px;">
      Квоты и корзины провайдера
    </h3>
    <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:16px;">
      ${buckets.map((b) => `
        <div style="background:var(--surface-muted); padding:8px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle);">
          <div style="display:flex; justify-content:space-between; font-weight:600;">
            <span>${escapeHtml(b.display_name)}</span>
            <span>${b.remaining_percent !== null && b.remaining_percent !== undefined ? `${b.remaining_percent.toFixed(1)}%` : 'Н/Д'}</span>
          </div>
          <div class="quota-bar-track" style="margin:4px 0;">
            <div class="quota-bar-fill" style="width:${b.remaining_percent || 0}%; background-color:var(--status-healthy);"></div>
          </div>
          <div style="font-size:10px; color:var(--text-muted);">
            ${b.reset_at ? `Сброс: ${formatIsoDate(b.reset_at)}` : (b.period ? `Период: ${b.period}` : 'Без отметки сброса')}
          </div>
        </div>
      `).join('') || '<div class="empty-text">Данные о квотах отсутствуют (провайдер не отдал лимиты).</div>'}
    </div>
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-secondary" onclick="handleTestProfile('${escapeHtml(profileId)}')">⚡ Проверить подключение</button>
    <button class="btn btn-secondary" onclick="executeAction('set_main', { profile_id: '${escapeHtml(profileId)}' })">★ Сделать основным</button>
    <button class="btn btn-secondary" onclick="executeAction('delete_credentials', { profile_id: '${escapeHtml(profileId)}' })">Удалить ключ</button>
    <button class="btn btn-primary" onclick="closeModal()">Закрыть</button>
  `;

  showModal();
}

async function handleSaveProfileModel(profileId) {
  const sel = document.getElementById('modal-model-select');
  if (!sel) return;
  const model = sel.value;
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Сохранение модели...</div>';
  }
  const res = await executeAction('set_model', { profile_id: profileId, model: model });
  if (feedbackArea) {
    if (res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Модель сохранена')}</div>`;
      if (currentSnapshot && currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
        currentSnapshot.all_profiles[profileId].preferred_models = [model];
      }
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(res.message || 'Ошибка сохранения модели')}</div>`;
    }
  }
}

function openAgentModelModal(roleId, profileId) {
  if (!currentSnapshot) return;
  const profile = (currentSnapshot.all_profiles || {})[profileId];
  if (!profile) return;

  const provSummary = (currentSnapshot.providers || []).find(p => p.provider_id === profile.provider);
  const discoveredModels = (provSummary && provSummary.discovered_models) ? provSummary.discovered_models : [];
  const currentModel = (profile.preferred_models && profile.preferred_models.length) ? profile.preferred_models[0] : '';
  const roleName = ((currentSnapshot.routing || {})[roleId]?.role_name_ru) || roleId;

  elements.modalTitle.textContent = `Выбор модели для роли: ${roleName}`;
  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    <div style="margin-bottom:12px; font-size:12px; color:var(--text-muted);">
      Профиль агента: <strong>${escapeHtml(profile.display_name)} (${profileId})</strong> • Провайдер: <strong>${escapeHtml(profile.provider_display_name || profile.provider)}</strong>
    </div>
    ${discoveredModels.length > 0 ? `
      <div style="margin-bottom:16px;">
        <label style="display:block; font-weight:600; margin-bottom:6px;">Выберите модель из обнаруженного списка:</label>
        <select id="role-model-select" class="select-filter" style="width:100%;">
          ${discoveredModels.map(m => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
        </select>
      </div>
    ` : `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:16px;">
        <div style="font-size:12px; color:var(--status-warning); margin-bottom:6px;">
          ⚠ Список моделей ещё не получен от провайдера ${escapeHtml(profile.provider_display_name || profile.provider)}.
        </div>
        <button class="btn btn-secondary btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(profile.provider)}')">↻ Запросить список моделей</button>
      </div>
    `}
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
    ${discoveredModels.length > 0 ? `<button class="btn btn-primary" onclick="handleSaveRoleModel('${escapeHtml(roleId)}', '${escapeHtml(profileId)}')">Сохранить модель</button>` : ''}
  `;

  showModal();
}

async function handleSaveRoleModel(roleId, profileId) {
  const sel = document.getElementById('role-model-select');
  if (!sel) return;
  const model = sel.value;
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Сохранение модели...</div>';
  }
  const res = await executeAction('set_model', { profile_id: profileId, model: model, role_id: roleId });
  if (feedbackArea) {
    if (res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Модель сохранена')}</div>`;
      if (currentSnapshot) {
        if (currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
          currentSnapshot.all_profiles[profileId].preferred_models = [model];
        }
        if (currentSnapshot.routing && currentSnapshot.routing[roleId]) {
          currentSnapshot.routing[roleId].default_model = model;
        }
        if (currentSnapshot.agents) {
          const ag = currentSnapshot.agents.find(a => a.role_id === roleId);
          if (ag) ag.model = model;
        }
      }
      setTimeout(() => {
        closeModal();
        renderCurrentView();
      }, 700);
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(res.message || 'Ошибка сохранения модели')}</div>`;
    }
  }
}

async function handleRefreshProviderModels(providerId, profileId = null) {
  showToast(`Запрос списка моделей для ${providerId}...`, 'info');
  const res = await executeAction('refresh_models', { provider: providerId });
  if (res.ok) {
    showToast('Запрос обновления моделей отправлен', 'success');
    if (profileId) {
      setTimeout(() => openAccountDetailsModal(profileId), 500);
    }
  }
}

async function handleTestProfile(profileId) {
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Запуск тестового запроса к провайдеру...</div>';
  }
  const res = await executeAction('test', { profile_id: profileId });
  if (feedbackArea) {
    if (res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Тест успешно пройден')}</div>`;
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(res.message || 'Тест завершился с ошибкой')}</div>`;
    }
  }
}

// ── Add Account Wizard (P0-5 Headless Server Honesty) ──
function openAddAccountWizard() {
  elements.modalTitle.textContent = 'Мастер подключения учетной записи';
  showWizardStep1();
  showModal();
}

function showWizardStep1() {
  elements.modalBody.innerHTML = `
    <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
      Шаг 1 из 3: Выберите провайдера ИИ
    </div>
    <div style="display:grid; grid-template-columns:1fr; gap:8px;">
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('grok')">
        <span style="font-size:18px; color:var(--prov-grok);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">Grok (xAI)</div>
          <div style="font-size:11px; color:var(--text-muted);">Device Code OAuth (работает на сервере) или API Key</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('openai-codex')">
        <span style="font-size:18px; color:var(--prov-codex);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">OpenAI Codex</div>
          <div style="font-size:11px; color:var(--text-muted);">Device Code OAuth (работает на сервере) или API Key</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('opencode-go')">
        <span style="font-size:18px; color:var(--prov-opencode);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">OpenCode Go</div>
          <div style="font-size:11px; color:var(--text-muted);">API Key / Токен подписки</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('claude')">
        <span style="font-size:18px; color:var(--prov-claude);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">Claude (Anthropic)</div>
          <div style="font-size:11px; color:var(--text-muted);">API Key или OAuth (требует SSH проброс портов)</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('antigravity')">
        <span style="font-size:18px; color:var(--prov-antigravity);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">Google Antigravity</div>
          <div style="font-size:11px; color:var(--text-muted);">OAuth редирект (требует браузер или перенос профиля)</div>
        </div>
      </button>
    </div>
  `;
  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
  `;
}

function showWizardStep2(providerId) {
  let bodyHtml = '';

  if (providerId === 'grok' || providerId === 'openai-codex') {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация ${providerId === 'grok' ? 'Grok (xAI)' : 'OpenAI Codex'} (Device Code OAuth)
      </div>
      <div style="background:var(--surface-muted); padding:14px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <div style="font-weight:700; margin-bottom:6px;">1. Откройте ссылку на любом устройстве:</div>
        <div style="display:flex; gap:8px; margin-bottom:12px;">
          <input type="text" class="input-text" style="flex:1;" id="wiz-auth-url" value="${providerId === 'grok' ? 'https://x.ai/device' : 'https://auth.openai.com/device'}" readonly>
          <button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('wiz-auth-url').value); showToast('Ссылка скопирована', 'success');">📋 Копировать</button>
        </div>

        <div style="font-weight:700; margin-bottom:6px;">2. Введите код подтверждения:</div>
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
          <div style="font-family:var(--font-mono); font-size:22px; font-weight:700; color:var(--text-accent); letter-spacing:2px;" id="wiz-auth-code">
            ${providerId === 'grok' ? 'GRK-7842' : 'CDX-9104'}
          </div>
          <button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('wiz-auth-code').innerText); showToast('Код скопирован', 'success');">📋 Копировать код</button>
        </div>

        <div style="font-size:11px; color:var(--text-muted);">
          3. Подтвердите доступ в браузере. Hub автоматически зафиксирует авторизацию.
        </div>
      </div>
    `;
  } else if (providerId === 'antigravity') {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация Google Antigravity
      </div>
      <div class="modal-feedback info" style="margin-bottom:14px;">
        <strong>Для серверов (Headless режим):</strong><br>
        Провайдер Antigravity требует интерактивного входа через консоль <code>agy</code>. Авторизация напрямую через веб-интерфейс невозможна.
        <div style="margin-top:6px;">
          <strong>Что делать:</strong><br>
          1. Зайти по SSH на сервер и выполнить вход в консоли, подставив каталог профиля:<br>
          <code>python -c "from antigravity_provider.agy_subprocess import launch_native_agy_login as L; L('ag-w1').wait()"</code><br>
          2. ИЛИ авторизоваться на локальном ПК и перенести директорию <code>~/.hermes/agy_profiles</code> на сервер.
        </div>
      </div>
    `;
  } else if (providerId === 'claude') {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация Claude
      </div>
      <div class="modal-feedback info" style="margin-bottom:14px;">
        <strong>Для серверов (Headless режим):</strong><br>
        Провайдер Claude использует локальный OAuth redirect (localhost). На сервере без браузера редирект придёт на локальную машину.
        <div style="margin-top:6px;">
          <strong>Альтернативные действия:</strong><br>
          1. Использовать API Key напрямую.<br>
          2. Пробросить порт через SSH: <code>ssh -L 8085:localhost:8085 user@server</code>
        </div>
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">Впишите API Key / Сгенерированный токен:</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="Вставьте токен или нажмите Далее...">
      </div>
    `;
  } else {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Ввод API ключа ${providerId}
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">API Key / Subscription Token:</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="sk-...">
      </div>
    `;
  }

  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    ${bodyHtml}
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
    <button class="btn btn-primary" onclick="showWizardStep3('${providerId}')">Продолжить →</button>
  `;
}

function showWizardStep3(providerId) {
  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
      Шаг 3 из 3: Назначение роли для нового аккаунта
    </div>
    <div style="margin-bottom:14px;">
      <label style="display:block; font-weight:600; margin-bottom:4px;">Целевая роль в роутере:</label>
      <select class="select-filter" style="width:100%;" id="wiz-target-role">
        <option value="coder-primary">Кодер 1 (Primary Coder)</option>
        <option value="coder-secondary">Кодер 2 (Secondary Coder)</option>
        <option value="orchestrator">Оркестратор (Fallback Router)</option>
        <option value="reviewer">Ревьюер кода (Reviewer)</option>
        <option value="research">Исследователь (Researcher)</option>
        <option value="fast">Быстрый агент (Fast / Flash)</option>
        <option value="spare">Резервный пул (Spare Pool)</option>
      </select>
    </div>
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="showWizardStep2('${providerId}')">← Назад</button>
    <button class="btn btn-primary" onclick="finishAddAccount('${providerId}')">✓ Завершить подключение</button>
  `;
}

async function finishAddAccount(providerId) {
  const roleSelect = document.getElementById('wiz-target-role');
  const targetRole = roleSelect ? roleSelect.value : 'coder-primary';

  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Сохранение учетной записи в роутере...</div>';
  }

  const res = await executeAction('add_account', {
    provider: providerId,
    target_role: targetRole,
  });

  if (res.ok) {
    showToast('Аккаунт успешно добавлен в маршрутизацию', 'success');
    closeModal();
    fetchSnapshot();
  } else {
    if (feedbackArea) {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(res.message || 'Не удалось завершить подключение')}</div>`;
    }
  }
}

// ── Routing Pipeline Modal ──
function openEditRouteModal(roleId) {
  if (!currentSnapshot) return;
  const pipeline = (currentSnapshot.routing || {})[roleId];
  if (!pipeline) return;

  const nodes = [...(pipeline.nodes || [])];

  function renderRows() {
    return nodes.map((node, index) => `
      <div style="display:flex; align-items:center; justify-content:space-between; background:var(--surface-muted); padding:8px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:6px;">
        <div>
          <span style="font-weight:700; color:var(--text-accent); margin-right:8px;">${index + 1}.</span>
          <strong style="font-size:13px;">${escapeHtml(node.display_name || node.profile_id)}</strong>
          <span style="font-size:11px; color:var(--text-muted); margin-left:6px;">(${escapeHtml(node.provider)})</span>
        </div>
        <div style="display:flex; gap:4px;">
          <button class="btn btn-secondary btn-sm" onclick="moveRouteNode('${roleId}', ${index}, -1)" ${index === 0 ? 'disabled' : ''}>↑</button>
          <button class="btn btn-secondary btn-sm" onclick="moveRouteNode('${roleId}', ${index}, 1)" ${index === nodes.length - 1 ? 'disabled' : ''}>↓</button>
          <button class="btn btn-ghost btn-sm text-error" onclick="removeRouteNode('${roleId}', ${index})">✕</button>
        </div>
      </div>
    `).join('') || '<div class="empty-text">Цепочка пуста.</div>';
  }

  window.activeRouteNodes = nodes;

  elements.modalTitle.textContent = `Цепочка маршрутизации: ${pipeline.role_name_ru || roleId}`;
  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    <div style="font-size:12px; color:var(--text-muted); margin-bottom:12px;">
      Первый профиль — основной (Primary). Нижестоящие профили используются как резервы в порядке переключения.
    </div>
    <div id="route-nodes-list-container">
      ${renderRows()}
    </div>
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
    <button class="btn btn-primary" onclick="saveRouteChain('${escapeHtml(roleId)}')">Сохранить цепочку</button>
  `;

  showModal();
}

window.moveRouteNode = function(roleId, index, delta) {
  const nodes = window.activeRouteNodes;
  const target = index + delta;
  if (target >= 0 && target < nodes.length) {
    const temp = nodes[index];
    nodes[index] = nodes[target];
    nodes[target] = temp;
    openEditRouteModal(roleId);
  }
};

window.removeRouteNode = function(roleId, index) {
  const nodes = window.activeRouteNodes;
  nodes.splice(index, 1);
  openEditRouteModal(roleId);
};

async function saveRouteChain(roleId) {
  const chain = (window.activeRouteNodes || []).map((n) => n.profile_id);
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Сохранение конфигурации...</div>';
  }

  const res = await executeAction('edit_route', {
    role_id: roleId,
    chain: chain,
  });

  if (res.ok) {
    showToast(`Цепочка '${roleId}' сохранена`, 'success');
    closeModal();
    fetchSnapshot();
  } else {
    if (feedbackArea) {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(res.message || 'Ошибка сохранения')}</div>`;
    }
  }
}

// ── SETTINGS MANAGEMENT ──
function initSettings() {
  const btnSave = document.getElementById('btn-save-client-settings');
  const tokenInput = document.getElementById('setting-client-token-input');
  const pollSelect = document.getElementById('setting-poll-interval');

  if (tokenInput && authToken) {
    tokenInput.value = authToken;
  }

  if (btnSave) {
    btnSave.addEventListener('click', () => {
      if (tokenInput) {
        authToken = tokenInput.value.trim();
        localStorage.setItem('hermes_hub_token', authToken);
      }
      if (pollSelect) {
        pollIntervalMs = parseInt(pollSelect.value, 10);
        startPolling();
      }
      showToast('Параметры веб-клиента сохранены', 'success');
      fetchSnapshot();
    });
  }
}

// ── MODAL HELPERS ──
function showModal() {
  if (elements.modalBackdrop) elements.modalBackdrop.classList.remove('hidden');
}

function closeModal() {
  if (elements.modalBackdrop) elements.modalBackdrop.classList.add('hidden');
}

// ── TOAST NOTIFICATIONS ──
function showToast(message, type = 'info') {
  if (!elements.toastContainer) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  elements.toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ── UTILITIES ──
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatIsoDate(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString('ru-RU', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch (e) {
    return isoStr;
  }
}

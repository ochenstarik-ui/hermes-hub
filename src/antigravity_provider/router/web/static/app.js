/**
 * Hermes Hub Web Client
 * Vanilla JavaScript (ES2022) — No npm, no build, no framework.
 * Single source of truth: docs/web-api/CONTRACT.md
 */

// ── CONFIGURATION & STATE ──
// Set USE_MOCK_FIXTURE = true to develop strictly offline against snapshot.example.json
const USE_MOCK_FIXTURE = false;

let lastAppliedSeq = -1;
let currentSnapshot = null;
let activeView = 'accounts';
let pollTimer = null;
let pollIntervalMs = 5000;
let authToken = localStorage.getItem('hermes_hub_token') || '';

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
  elements.navItems.forEach((btn) => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      switchView(view);
    });
  });
}

function switchView(viewName) {
  activeView = viewName;
  elements.navItems.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });
  elements.viewPanes.forEach((pane) => {
    pane.classList.toggle('active', pane.id === `view-${viewName}`);
  });

  const titles = {
    accounts: 'Аккаунты и квоты',
    overview: 'Обзор системы',
    routing: 'Маршрутизация запросов',
    providers: 'Модели и провайдеры',
    team: 'Команда агентов',
    logs: 'Журнал событий',
    settings: 'Параметры веб-клиента',
  };
  elements.pageTitle.textContent = titles[viewName] || 'Hermes Hub';

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

  const btnClearLogs = document.getElementById('btn-clear-logs');
  if (btnClearLogs) {
    btnClearLogs.addEventListener('click', () => {
      const logsBox = document.getElementById('logs-container');
      if (logsBox) logsBox.innerHTML = '<div class="empty-text">Журнал очищен пользователем.</div>';
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
    } catch (e) {
      // ignore
    }
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
    case 'logs':
      renderLogsView();
      break;
  }
}

// ═══════════════════════════════════════════════════════════════
//  1. ACCOUNTS VIEW (P0-1 Compact Fixed-Height Cards & Quotas)
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
    card.addEventListener('click', () => {
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
        <span class="quota-cell-value" style="color: ${colorClass};">${escapeHtml(formattedValue)}</span>
      </div>
      <div class="quota-bar-track">
        <div class="quota-bar-fill" style="width: ${barWidth}%; background-color: ${colorClass};"></div>
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
              ${node.failover_reason ? `<div style="font-size:9px; color:var(--status-warning);">Причина: ${escapeHtml(node.failover_reason)}</div>` : ''}
            </div>
            ${index < nodes.length - 1 ? '<span class="pipeline-arrow">→</span>' : ''}
          `).join('')}
        </div>
      </div>
    `;
  }

  container.innerHTML = html || '<div class="empty-text">Маршрутизация не настроена.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  4. PROVIDERS VIEW
// ═══════════════════════════════════════════════════════════════
function renderProvidersView() {
  const container = document.getElementById('providers-full-container');
  if (!container || !currentSnapshot) return;

  const providers = currentSnapshot.providers || [];
  container.innerHTML = providers.map((prov) => `
    <div class="section-card" style="margin-bottom:14px;">
      <div class="section-card-header">
        <div>
          <div class="section-card-title">${escapeHtml(prov.provider_name || prov.provider_id)}</div>
          <div class="section-card-subtitle">
            Обновлено: ${prov.last_refresh_at ? formatIsoDate(prov.last_refresh_at) : 'Н/Д — обнаружение ещё не запускалось'}
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="executeAction('refresh_data', { provider: '${escapeHtml(prov.provider_id)}' })">
          Обновить модели
        </button>
      </div>

      <div style="font-size:12px; margin-bottom:10px;">
        Онлайн: <strong class="text-healthy">${prov.online_count}/${prov.connected_count}</strong> •
        Требуют авторизации: <strong class="text-warning">${prov.auth_required_count}</strong> •
        Квота исчерпана: <strong class="text-error">${prov.quota_exhausted_count}</strong> •
        Холодный резерв: <strong>${prov.cold_spare_count}</strong>
      </div>

      <div class="provider-models-tag">
        <strong>Обнаруженные модели:</strong><br>
        ${prov.discovered_models && prov.discovered_models.length ? escapeHtml(prov.discovered_models.join(' • ')) : 'Н/Д — список моделей ещё не получен от провайдера'}
      </div>
    </div>
  `).join('') || '<div class="empty-text">Список провайдеров пуст.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  5. TEAM VIEW (P0-1 / P1-3 Model Choice on Agent Cards)
// ═══════════════════════════════════════════════════════════════
function renderTeamView() {
  const container = document.getElementById('team-cards-container');
  if (!container || !currentSnapshot) return;

  const agents = currentSnapshot.agents || [];
  container.innerHTML = agents.map((agent) => `
    <div class="team-agent-card ${agent.is_main_orchestrator ? 'orchestrator' : ''}">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <span style="font-weight:700; font-size:14px;">${escapeHtml(agent.role_name_ru || agent.role_id)}</span>
        ${agent.is_main_orchestrator ? '<span class="badge badge-plan">👑 ЛИДЕР</span>' : ''}
      </div>
      <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">${escapeHtml(agent.role_description_ru || '')}</div>
      <div style="background:var(--surface-muted); padding:8px 10px; border-radius:var(--radius-sm); font-size:12px; margin-bottom:8px;">
        <div>Профиль: <strong>${escapeHtml(agent.assigned_profile_id || 'Не назначен')}</strong></div>
        <div>Провайдер: <strong>${escapeHtml(agent.provider_display_name || agent.provider)}</strong></div>
        <div style="margin-top:2px;">Модель: <strong class="text-accent">${escapeHtml(agent.model || '—')}</strong></div>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; gap:6px;">
        <span class="text-healthy">● ${escapeHtml(agent.status_label_ru || 'Работает')}</span>
        <div style="display:flex; gap:4px;">
          <button class="btn btn-secondary btn-sm" onclick="openAgentModelModal('${escapeHtml(agent.role_id)}', '${escapeHtml(agent.assigned_profile_id)}')">
            Сменить модель
          </button>
          <button class="btn btn-ghost btn-sm" onclick="openAccountDetailsModal('${escapeHtml(agent.assigned_profile_id)}')">
            Детали →
          </button>
        </div>
      </div>
    </div>
  `).join('') || '<div class="empty-text">Команда агентов пуста.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  6. LOGS VIEW
// ═══════════════════════════════════════════════════════════════
function renderLogsView() {
  const container = document.getElementById('logs-container');
  if (!container || !currentSnapshot) return;
  const logs = currentSnapshot.metrics?.recent_events || [];
  if (logs.length > 0) {
    container.innerHTML = logs.map((log) => `
      <div style="padding:6px 0; border-bottom:1px solid var(--border-subtle); font-family:var(--font-mono); font-size:11px;">
        <span class="text-muted">[${escapeHtml(log.time || '')}]</span>
        <span class="text-accent">${escapeHtml(log.role || '')}</span>:
        <span>${escapeHtml(log.message || '')}</span>
      </div>
    `).join('');
  }
}

// ═══════════════════════════════════════════════════════════════
//  MODALS & WIZARDS
// ═══════════════════════════════════════════════════════════════

function openAccountDetailsModal(profileId) {
  if (!currentSnapshot) return;
  const profile = (currentSnapshot.all_profiles || {})[profileId];
  if (!profile) return;

  const quotaSnap = profile.quota_snapshot || (currentSnapshot.quotas || {})[profileId];
  const buckets = (quotaSnap && quotaSnap.buckets) ? quotaSnap.buckets : [];

  const provSummary = (currentSnapshot.providers || []).find(p => p.provider_id === profile.provider);
  const discoveredModels = (provSummary && provSummary.discovered_models) ? provSummary.discovered_models : [];
  const currentModel = (profile.preferred_models && profile.preferred_models.length) ? profile.preferred_models[0] : '';

  let modelBlockHtml = '';
  if (discoveredModels.length > 0) {
    modelBlockHtml = `
      <h3 style="font-size:13px; font-weight:700; margin:14px 0 6px; border-bottom:1px solid var(--border-subtle); padding-bottom:4px;">
        Выбор модели по умолчанию
      </h3>
      <div style="display:flex; gap:8px; align-items:center; margin-bottom:16px;">
        <select id="modal-model-select" class="select-filter" style="flex:1;">
          ${discoveredModels.map(m => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
        </select>
        <button class="btn btn-secondary btn-sm" onclick="handleSaveProfileModel('${escapeHtml(profileId)}')">Сохранить модель</button>
        <button class="btn btn-ghost btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(profile.provider)}', '${escapeHtml(profileId)}')">↻ Обновить список</button>
      </div>
    `;
  } else {
    modelBlockHtml = `
      <h3 style="font-size:13px; font-weight:700; margin:14px 0 6px; border-bottom:1px solid var(--border-subtle); padding-bottom:4px;">
        Выбор модели по умолчанию
      </h3>
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:16px;">
        <div style="font-size:12px; color:var(--status-warning); margin-bottom:6px;">
          ⚠ Список моделей ещё не получен от провайдера ${escapeHtml(profile.provider_display_name || profile.provider)}.
        </div>
        <button class="btn btn-secondary btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(profile.provider)}', '${escapeHtml(profileId)}')">↻ Запросить список моделей</button>
      </div>
    `;
  }

  elements.modalTitle.textContent = `Учетная запись: ${profile.display_name} (${profileId})`;
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
  const res = await executeAction('refresh_data', { provider: providerId });
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
        Шаг 2 из 3: Авторизация ${providerId === 'grok' ? 'Grok (xAI)' : 'OpenAI Codex'}
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
  } else if (providerId === 'antigravity' || providerId === 'claude') {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация ${providerId === 'antigravity' ? 'Google Antigravity' : 'Claude'}
      </div>
      <div class="modal-feedback info" style="margin-bottom:14px;">
        <strong>⚠️ Внимание (Headless Сервер):</strong><br>
        Провайдер ${providerId} использует локальный OAuth redirect (localhost). На сервере без браузера редирект придёт на локальную машину.
        <div style="margin-top:6px;">
          <strong>Рекомендуемые варианты:</strong><br>
          1. Использовать API Key провайдера.<br>
          2. Пробросить порт через SSH: <code>ssh -L 8085:localhost:8085 user@server</code><br>
          3. Авторизоваться на локальном ПК и скопировать <code>~/.hermes/agy_profiles</code> на сервер.
        </div>
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">Вставьте API Key / Токен авторизации:</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="Введите ключ или токен...">
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
  const tokenInput = document.getElementById('setting-auth-token');
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

/**
 * Hermes Hub Web Client
 * Vanilla JavaScript (ES2022) — No npm, no build, no framework.
 * Single source of truth: docs/web-api/CONTRACT.md
 */

// ── CONFIGURATION & STATE ──
const USE_MOCK_FIXTURE = false;

let lastAppliedSeq = -1;
// Какой профиль сейчас открыт в окне аккаунта: нужно, чтобы перерисовывать
// его по свежему снапшоту, а не оставлять с заглушкой.
let _openAccountModalProfile = null;
let currentSnapshot = null;
let activeView = 'overview';
let pollTimer = null;
let pollIntervalMs = 5000;
let authToken = localStorage.getItem('hermes_hub_token') || '';
let cachedEvents = [];
let currentSettings = {};
let currentDragState = null;
let latestUpdateInfo = null;

const CANONICAL_ROLE_DESCRIPTIONS = {
  orchestrator: 'Главный оркестратор команды и маршрутизатор запросов',
  'coder-primary': 'Основная разработка кода и реализация задач',
  'coder-secondary': 'Вспомогательная разработка и параллельные задачи',
  reviewer: 'Ревью кода, аудит изменений и контроль качества',
  research: 'Read-only поиск в кодовой базе и сбор фактов',
  fast: 'Оперативные вызовы, быстрые проверки и тесты',
};

function getProviderIdFromName(name) {
  if (!name) return '';
  const n = name.toLowerCase();
  if (n.includes('antigravity') || n.includes('google')) return 'antigravity';
  if (n.includes('codex') || n.includes('openai')) return 'openai-codex';
  if (n.includes('opencode') || n.includes('go')) return 'opencode-go';
  if (n.includes('claude') || n.includes('anthropic')) return 'claude';
  if (n.includes('grok') || n.includes('xai')) return 'grok';
  return name;
}

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
  checkUpdates(true);
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
    overview: 'Обзор системы',
    accounts: 'Аккаунты и квоты',
    routing: 'Главный экран управления маршрутизацией',
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

  const btnAutoAssign = document.getElementById('btn-auto-assign');
  if (btnAutoAssign) {
    btnAutoAssign.addEventListener('click', () => {
      executeAction('auto_assign_all', {});
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

  // Updates event listeners
  const btnHeaderUpdate = document.getElementById('header-update-badge');
  if (btnHeaderUpdate) {
    btnHeaderUpdate.addEventListener('click', () => openUpdateModal());
  }

  const btnCheckUpdates = document.getElementById('btn-check-updates');
  if (btnCheckUpdates) {
    btnCheckUpdates.addEventListener('click', () => checkUpdates(false));
  }

  const btnApplyUpdate = document.getElementById('btn-apply-update');
  if (btnApplyUpdate) {
    btnApplyUpdate.addEventListener('click', () => applyUpdate());
  }

  // Preflight check listener
  const btnPreflight = document.getElementById('btn-run-preflight');
  if (btnPreflight) {
    btnPreflight.addEventListener('click', () => runPreflightChecks());
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
    if (res.status === 401) {
      handleUnauthorized();
      return;
    }
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
    // Раньше здесь при недоступном API молча подставлялась
    // snapshot.example.json — 63 чужих профиля с почтами user@example.test —
    // и индикатор ставился в зелёное. Экран выглядел здоровой панелью,
    // которая не имеет отношения к этому серверу: при работе через SSH-туннель
    // достаточно промахнуться портом или потерять туннель, чтобы принять
    // пример за свои данные. Осознанная работа с фикстурой осталась —
    // ?fixture=1 и открытие файлом, — но подставлять её вместо ответа сервера
    // нельзя: отсутствие данных должно читаться как отсутствие данных.
    console.warn('Live API unavailable:', err);
    setSourceIndicator(false, 'Сервер недоступен');
    showToast('Сервер не отвечает. Данные на экране могут быть устаревшими.', 'error');
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

  // Открытое окно аккаунта рисовалось один раз и на опрос не реагировало.
  // Если его открыть до того, как придут живые квоты, оно навсегда
  // оставалось с заглушкой («Grok 2h — Н/Д») и со статусом «Не проверялся»
  // даже после успешной проверки. Перерисовываем по свежему снапшоту.
  if (_openAccountModalProfile) {
    try {
      openAccountDetailsModal(_openAccountModalProfile, true);
    } catch (e) {
      console.warn('[Hub] Не удалось обновить окно аккаунта:', e);
    }
  }

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

// Подключён ли профиль на самом деле.
//
// A26 определял это как «health_state не равен not_configured», а поле
// authenticated в модели вообще отсутствует, поэтому первая половина условия
// была мертва. Через фильтр проходили холодный резерв (health_state
// "disabled") и непроверенные пустые слоты: при нуле настоящих аккаунтов
// страница показывала три карточки «Холодный резерв», а «Обзор» предлагал
// назначать роли на пустые слоты — то самое мышление слотами, ради отмены
// которого задание и делалось.
//
// Authoritative признак — auth_state: у подключённого AUTHENTICATED, у
// пустого слота и у холодного резерва NOT_CONFIGURED. Состояния
// AUTH_REQUIRED и AUTH_EXPIRED означают подключённый аккаунт, которому нужен
// повторный вход, — их показываем.
function isConnectedProfile(p) {
  if (!p) return false;
  const st = String(p.auth_state || '').toUpperCase();
  if (st) return st !== 'NOT_CONFIGURED';
  // Запасной путь, если поле не пришло: судим по наличию опознанного аккаунта.
  return Boolean(p.email);
}

// ── КОПИРОВАНИЕ В БУФЕР ──
//
// navigator.clipboard существует только в защищённом контексте: HTTPS или
// localhost. Когда хаб открыт по сети (http://192.168.1.81:5800), его нет
// вовсе, и кнопки «Копировать» молча не работали — хуже того, показывали
// «Ссылка скопирована», потому что промис никто не проверял.
// Запасной путь — execCommand('copy'), он работает и по HTTP.
async function copyToClipboard(text, okMessage) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      showToast(okMessage || 'Скопировано', 'success');
      return true;
    }
  } catch (err) {
    console.warn('clipboard API недоступен:', err);
  }

  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (ok) {
      showToast(okMessage || 'Скопировано', 'success');
      return true;
    }
  } catch (err) {
    console.warn('execCommand copy не сработал:', err);
  }

  // Молчать нельзя: владелец решит, что скопировалось, и вставит старое.
  showToast('Скопировать не удалось — выделите текст в поле и нажмите Ctrl+C', 'warning');
  return false;
}

// ── ЗАПРОС ТОКЕНА ПРИ 401 ──
//
// Сервер, привязанный не к localhost, требует X-Hub-Token. Раньше клиент этого
// случая не знал вовсе: 401 попадал в общую ветку ошибок и превращался в
// красный тост «Ошибка сервера: 401», который повторялся на каждом опросе.
// Владелец видел пустую панель и не имел ни одной подсказки, что нужен токен
// и где его взять. Теперь спрашиваем прямо, один раз.
let _tokenPromptOpen = false;

function handleUnauthorized() {
  if (_tokenPromptOpen) return;
  _tokenPromptOpen = true;
  // Опрос останавливаем, иначе окно ввода будет перекрываться новыми 401
  // каждые несколько секунд. Отдельной stopPolling в клиенте нет — таймер
  // гасится напрямую, как это делает startPolling перед перезапуском.
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  setSourceIndicator(false, 'Требуется токен доступа');

  elements.modalTitle.textContent = 'Требуется токен доступа';
  elements.modalBody.innerHTML = `
    <div class="modal-feedback info" style="margin-bottom:14px;">
      Этот хаб открыт по сети, поэтому запросы к нему требуют токен.
      Он был показан при выполнении <code>enable_lan_access.py</code> и хранится
      на сервере в <code>~/.hermes/hub_settings.json</code>.
    </div>
    <label style="display:block; font-weight:600; margin-bottom:4px;">Токен доступа:</label>
    <input type="password" class="input-text" style="width:100%;" id="auth-token-input"
           placeholder="Вставьте токен" autocomplete="off">
    <div id="auth-token-feedback" style="font-size:12px; color:var(--text-muted); margin-top:8px;">
      Токен сохранится в этом браузере и больше спрашиваться не будет.
    </div>
  `;
  elements.modalFooter.innerHTML = `
    <button class="btn btn-primary" onclick="saveAuthTokenFromPrompt()">Сохранить и продолжить</button>
  `;
  showModal();
  setTimeout(() => {
    const el = document.getElementById('auth-token-input');
    if (el) el.focus();
  }, 50);
}

async function saveAuthTokenFromPrompt() {
  const input = document.getElementById('auth-token-input');
  const feedback = document.getElementById('auth-token-feedback');
  if (!input) return;
  const value = (input.value || '').trim();
  if (!value) {
    feedback.innerHTML = '<span style="color:var(--status-warning);">Поле пустое.</span>';
    return;
  }

  // Заголовки HTTP переносят только ASCII. Без этой проверки fetch бросает
  // TypeError и обработчик умирает целиком, не показав ничего: так бывает,
  // если вместе с токеном скопировали русский текст или лишний символ.
  if (!/^[!-~]+$/.test(value)) {
    feedback.innerHTML = '<span style="color:var(--status-error);">В токене посторонние символы. Скопируйте только сам токен, без кавычек, пробелов и текста вокруг.</span>';
    return;
  }

  feedback.textContent = 'Проверяем…';
  let res;
  try {
    res = await fetch('/api/snapshot', { headers: { 'X-Hub-Token': value } });
  } catch (err) {
    feedback.innerHTML = `<span style="color:var(--status-error);">Не удалось обратиться к серверу: ${escapeHtml(err.message)}</span>`;
    return;
  }
  if (res.status === 401) {
    feedback.innerHTML = '<span style="color:var(--status-error);">Токен не подошёл. Проверьте, что скопирован целиком.</span>';
    return;
  }
  if (!res.ok) {
    feedback.innerHTML = `<span style="color:var(--status-error);">Сервер ответил ${res.status}.</span>`;
    return;
  }

  authToken = value;
  localStorage.setItem('hermes_hub_token', authToken);
  const tokenInput = document.getElementById('setting-client-token-input');
  if (tokenInput) tokenInput.value = authToken;

  _tokenPromptOpen = false;
  closeModal();
  showToast('Токен принят', 'success');
  startPolling();
  fetchSnapshot();
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

    if (res.status === 401) {
      handleUnauthorized();
      return { ok: false, message: 'Требуется токен доступа' };
    }

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

  const readiness = currentSnapshot.readiness || {};
  const allProfiles = Object.values(currentSnapshot.all_profiles || {});
  const connectedAccounts = readiness.accounts_connected_count ?? allProfiles.filter(
    (p) => isConnectedProfile(p)
  ).length;

  if (elements.navAccountsCount) elements.navAccountsCount.textContent = connectedAccounts;

  const isHealthy = readiness.state === 'healthy';
  const readyRoles = readiness.roles_ready_count || 0;
  const totalRoles = readiness.total_roles ?? 0;

  if (elements.headerReadinessBadge) {
    elements.headerReadinessBadge.className = `header-readiness-badge ${isHealthy ? 'text-healthy' : 'text-warning'}`;
  }
  if (elements.headerReadinessText) {
    elements.headerReadinessText.textContent = readiness.title_ru
      ? `${readiness.title_ru} (${readyRoles}/${totalRoles} ролей)`
      : 'Н/Д: состояние ещё не измерено';
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
  if (kpiTotalAccounts) kpiTotalAccounts.textContent = connectedAccounts;
  if (kpiAccountsSub) kpiAccountsSub.textContent = `Подключено: ${connectedAccounts}`;
  if (kpiReadyRoles) kpiReadyRoles.textContent = `${readyRoles}/${totalRoles}`;
  if (kpiRolesSub) kpiRolesSub.textContent = `${readyRoles} из ${totalRoles} ролей маршрутизации активны`;
  if (kpiProvidersCount) kpiProvidersCount.textContent = (currentSnapshot.providers || []).length || 5;
}

// ── VIEW ROUTER ──
function renderCurrentView() {
  if (!currentSnapshot) return;
  switch (activeView) {
    case 'overview':
      renderOverviewView();
      break;
    case 'accounts':
      renderAccountsView();
      break;
    case 'routing':
      renderRoutingView();
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
//  1. ACCOUNTS VIEW (P0-2 Only Connected Accounts & Empty State)
// ═══════════════════════════════════════════════════════════════
function renderAccountsView() {
  const container = elements.accountsContainer;
  if (!container || !currentSnapshot) return;

  const allProfiles = Object.values(currentSnapshot.all_profiles || {});
  const totalConnectedInSystem = allProfiles.filter(
    (p) => isConnectedProfile(p)
  ).length;

  if (totalConnectedInSystem === 0) {
    container.innerHTML = `
      <div class="accounts-empty-state">
        <div class="empty-state-icon">👥</div>
        <h3>Нет подключённых аккаунтов</h3>
        <p>Подключите ваш первый аккаунт провайдера ИИ для распределения ролей и работы с Hermes Hub.</p>
        <button class="btn btn-primary" onclick="openAddAccountWizard()">+ Подключить аккаунт</button>
      </div>
    `;
    if (elements.accountsStatsSummary) {
      elements.accountsStatsSummary.innerHTML = 'Показано: <strong>0</strong> из <strong>0</strong> подключённых аккаунтов';
    }
    return;
  }

  const searchQuery = (elements.accountsSearch ? elements.accountsSearch.value : '').trim().toLowerCase();
  const providerFilter = elements.filterProvider ? elements.filterProvider.value : 'all';
  const healthFilter = elements.filterHealth ? elements.filterHealth.value : 'all';

  const providerNames = {
    antigravity: 'Google Antigravity',
    'openai-codex': 'OpenAI Codex',
    'opencode-go': 'OpenCode Go',
    claude: 'Claude (Anthropic)',
    grok: 'Grok (xAI)',
    local: 'Local LLM',
    'local-llm': 'Local LLM',
    'llama.cpp': 'Local LLM (llama.cpp)',
    ollama: 'Ollama',
    vllm: 'vLLM',
  };

  const profilesByProv = currentSnapshot.profiles_by_provider || {};
  let totalProfiles = 0;
  let visibleProfiles = 0;
  let html = '';

  for (const [providerId, profiles] of Object.entries(profilesByProv)) {
    if (providerFilter !== 'all' && providerFilter !== providerId) continue;

    const filtered = profiles.filter((p) => {
      const isConnected = isConnectedProfile(p);
      if (!isConnected) return false;

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

    filtered.sort((a, b) => {
      const rank = (p) => {
        if (p.health_state === 'not_configured') return 5;
        if (p.is_cold_spare || !p.enabled || p.health_state === 'disabled') return 4;
        if (p.health_state === 'not_tested') return 3;
        if (p.health_state === 'auth_required' || p.health_state === 'auth_expired') return 2;
        if (p.health_state === 'healthy') return 0;
        return 1;
      };
      const d = rank(a) - rank(b);
      if (d !== 0) return d;
      return (a.display_name || '').localeCompare(b.display_name || '', 'ru');
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
    elements.accountsStatsSummary.innerHTML = `Показано: <strong>${visibleProfiles}</strong> из <strong>${totalProfiles}</strong> подключённых аккаунтов`;
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
//  1. OVERVIEW VIEW (P0-3, P0-4 Diagram Model Select & Counters)
// ═══════════════════════════════════════════════════════════════
function renderOverviewView() {
  if (typeof renderWorkflowOverview === 'function') {
    renderWorkflowOverview(currentSnapshot);
    return;
  }
  if (!currentSnapshot) return;

  const providers = currentSnapshot.providers || [];
  const readiness = currentSnapshot.readiness || {};
  let totalSlots = 0;
  let connectedSlots = 0;
  let onlineSlots = 0;
  let authRequiredSlots = 0;

  providers.forEach((p) => {
    totalSlots += p.total_slots || 0;
    connectedSlots += p.connected_count || 0;
    onlineSlots += p.online_count || 0;
    authRequiredSlots += p.auth_required_count || 0;
  });

  const kpiSystem = document.getElementById('kpi-system-readiness');
  const kpiSystemSub = document.getElementById('kpi-readiness-summary');
  if (kpiSystem) {
    kpiSystem.textContent = readiness.title_ru || 'Система готова';
    kpiSystem.className = `kpi-value ${readiness.state === 'healthy' ? 'text-healthy' : (readiness.state === 'warning' ? 'text-warning' : 'text-error')}`;
  }
  if (kpiSystemSub) {
    kpiSystemSub.textContent = readiness.summary_ru || 'Все ключевые роли обеспечены';
  }

  const kpiAccounts = document.getElementById('kpi-total-accounts');
  const kpiAccountsSub = document.getElementById('kpi-accounts-sub');
  if (kpiAccounts) {
    kpiAccounts.textContent = `${connectedSlots}/${totalSlots} слотов`;
  }
  if (kpiAccountsSub) {
    kpiAccountsSub.textContent = `Онлайн: ${onlineSlots} • Требуют входа: ${authRequiredSlots}`;
  }

  const kpiRoles = document.getElementById('kpi-ready-roles');
  const kpiRolesSub = document.getElementById('kpi-roles-sub');
  if (kpiRoles) {
    kpiRoles.textContent = `${readiness.roles_ready_count || 0}/${readiness.total_roles || 6}`;
  }
  if (kpiRolesSub) {
    kpiRolesSub.textContent = (readiness.roles_ready_count >= readiness.total_roles)
      ? 'Все роли обеспечены'
      : 'Требуется подключение аккаунтов';
  }

  const kpiProviders = document.getElementById('kpi-providers-count');
  const kpiProvidersSub = document.getElementById('kpi-providers-sub');
  if (kpiProviders) {
    const connectedProviders = providers.filter((p) => (p.connected_count || 0) > 0).length;
    kpiProviders.textContent = `${connectedProviders}/${providers.length}`;
  }
  if (kpiProvidersSub) {
    kpiProvidersSub.textContent = 'Подключено провайдеров ИИ';
  }

  const diagramBox = document.getElementById('overview-route-diagram');
  if (diagramBox) {
    const roles = currentSnapshot.routing || {};
    const allConnectedProfiles = Object.values(currentSnapshot.all_profiles || {}).filter(
      (p) => isConnectedProfile(p)
    );
    let diagramHtml = '';

    for (const [roleId, pipeline] of Object.entries(roles)) {
      const nodes = pipeline.nodes || [];

      diagramHtml += `
        <div class="diagram-column">
          <div class="diagram-column-header">${escapeHtml(pipeline.role_name_ru || roleId)}</div>
          ${nodes.map((node, idx) => {
            const profile = (currentSnapshot.all_profiles || {})[node.profile_id];
            const provId = profile?.provider || getProviderIdFromName(node.provider);
            const provSummary = (currentSnapshot.providers || []).find((p) => p.provider_id === provId || p.provider_name === node.provider);
            const discoveredModels = (provSummary && provSummary.discovered_models && provSummary.discovered_models.length > 0) ? provSummary.discovered_models : [];
            const currentModel = node.model || (profile && profile.preferred_models && profile.preferred_models[0]) || '';

            const hasCurrentInConnected = allConnectedProfiles.some((p) => p.profile_id === node.profile_id);
            let accountControlHtml = '';
            if (allConnectedProfiles.length > 0) {
              accountControlHtml = `
                <select class="diagram-account-select" title="Сменить назначенный аккаунт" onchange="handleNodeAccountChange('${escapeHtml(roleId)}', this.value, ${idx === 0})">
                  ${allConnectedProfiles.map((p) => `<option value="${escapeHtml(p.profile_id)}" ${p.profile_id === node.profile_id ? 'selected' : ''}>${escapeHtml(p.email || p.account_identity || p.display_name || p.profile_id)} (${escapeHtml(p.provider)})</option>`).join('')}
                  ${!hasCurrentInConnected && node.profile_id ? `<option value="${escapeHtml(node.profile_id)}" selected>${escapeHtml(node.display_name || node.profile_id)}</option>` : ''}
                </select>
              `;
            }

            let modelControlHtml = '';
            if (discoveredModels.length > 0) {
              modelControlHtml = `
                <select class="diagram-model-select" title="Сменить рабочую модель" onchange="handleNodeModelChange('${escapeHtml(roleId)}', '${escapeHtml(node.profile_id)}', this.value)">
                  ${discoveredModels.map((m) => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
                </select>
              `;
            } else {
              modelControlHtml = `
                <div style="font-size:10px; color:var(--text-muted); display:flex; align-items:center; justify-content:space-between;">
                  <span>Список моделей ещё не получен</span>
                  <button class="btn btn-secondary btn-xs" onclick="handleRefreshProviderModels('${escapeHtml(provId)}')">↻</button>
                </div>
              `;
            }

            return `
              <div class="diagram-node ${node.is_active ? 'active' : ''}">
                <div style="display:flex; justify-content:space-between; font-weight:600; font-size:11px;">
                  <span>${idx === 0 ? '★ Основной' : `Резерв ${idx}`}</span>
                  <span class="${node.is_active ? 'text-healthy' : 'text-muted'}">${node.is_active ? '● Активен' : 'Ожидание'}</span>
                </div>
                <div style="font-size:12px; font-weight:700; margin-top:2px;">${escapeHtml(node.account_identity && node.account_identity !== 'Аккаунт не добавлен' ? node.account_identity : (node.display_name || node.profile_id))}</div>
                <div style="font-size:10px; color:var(--text-secondary); margin-bottom:4px;">${escapeHtml(node.display_name || node.profile_id)} (${escapeHtml(node.provider)})</div>
                ${accountControlHtml}
                ${modelControlHtml}
              </div>
            `;
          }).join('') || '<div class="empty-text">Цепочка не задана</div>'}
        </div>
      `;
    }
    diagramBox.innerHTML = diagramHtml || '<div class="empty-text">Нет данных маршрутизации.</div>';
  }

  const provSummaryBox = document.getElementById('overview-providers-summary');
  if (provSummaryBox) {
    provSummaryBox.innerHTML = providers.map((prov) => `
      <div class="provider-summary-card">
        <div class="provider-summary-title">${escapeHtml(prov.provider_name || prov.provider_id)}</div>
        <div class="provider-summary-stats">
          Всего слотов: <strong>${prov.total_slots}</strong> •
          Подключено: <strong>${prov.connected_count}</strong> •
          Онлайн: <strong>${prov.online_count}</strong> •
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
//  2. ROUTING VIEW (P0-1, P0-2 Main Routing Control Center)
// ═══════════════════════════════════════════════════════════════

function getProviderIcon(provider) {
  const map = {
    'openai-codex': 'codex.png',
    'google-antigravity': 'антигравити.png',
    'opencode-go': 'opencode.png',
    'anthropic-claude': 'claude.png',
    'deepseek': 'deepseek.png',
    'grok': 'grok.jfif'
  };
  return map[provider] || 'llama.png';
}

function renderRoutingView() {
  const leftCol = document.getElementById('routing-roles-container');
  const rightCol = document.getElementById('routing-available-container');
  if (!leftCol || !rightCol || !currentSnapshot) return;

  const routing = currentSnapshot.routing || {};
  const agents = currentSnapshot.agents || [];
  const profiles = currentSnapshot.profiles || {};

  // Render Left Column (Roles)
  let rolesHtml = '';
  for (const [roleId, pipeline] of Object.entries(routing)) {
    const chain = pipeline.preferred_chain || [];
    const agentInfo = agents.find((a) => a.role_id === roleId);
    
    let isImportant = ['manager', 'developer-1', 'developer-2'].includes(roleId);
    let badgeHtml = isImportant ? `<span class="role-badge"><i class="fa-solid fa-star"></i> Важная роль</span>` : '';
    let roleDesc = CANONICAL_ROLE_DESCRIPTIONS[roleId] || '';

    rolesHtml += `
      <div class="role-section" data-role="${escapeHtml(roleId)}">
        <div class="role-header">
          <div>
            <h4><i class="fa-solid fa-network-wired" style="color:var(--accent);"></i> ${escapeHtml(pipeline.role_name_ru || roleId)} ${badgeHtml}</h4>
            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(roleDesc)}</div>
          </div>
          <div style="display:flex; align-items:center; gap:12px;">
            <span style="font-size:12px; color:var(--text-secondary);">${chain.length} аккаунта</span>
            <button class="btn btn-secondary btn-sm" onclick="openAddNodeToChainModal('${escapeHtml(roleId)}')">
              + Добавить аккаунт
            </button>
            <i class="fa-solid fa-ellipsis-vertical" style="color:var(--text-muted); cursor:pointer;"></i>
          </div>
        </div>
        <div class="grid-header">
          <div><!-- drag handle --></div>
          <div>Приоритет</div>
          <div>Аккаунт</div>
          <div>Модель</div>
          <div>Провайдер</div>
          <div>Квоты</div>
          <div>Сброс</div>
          <div>Статус</div>
          <div><!-- remove --></div>
        </div>
        <div class="role-chain-list" id="chain-${escapeHtml(roleId)}" style="min-height: 10px;">
    `;

    chain.forEach((pid, index) => {
      const prof = profiles[pid] || {};
      const prov = prof.provider || 'unknown';
      const icon = getProviderIcon(prov);
      
      rolesHtml += `
        <div class="account-row draggable-item" draggable="true" data-pid="${escapeHtml(pid)}" data-role="${escapeHtml(roleId)}">
          <div class="drag-handle"><i class="fa-solid fa-grip-vertical"></i></div>
          <div style="font-weight:600; color:var(--text-primary); text-align:center;">${index + 1}</div>
          <div style="display:flex; align-items:center; gap:8px;">
            <img src="/static/${icon}" class="provider-logo-sm" onerror="this.src='/static/llama.png'">
            <div>
              <div style="font-weight:600;">${escapeHtml(pid)}</div>
              <div style="font-size:10px; color:var(--text-muted);">${escapeHtml(prof.account_id || '')}</div>
            </div>
          </div>
          <div>
            <select class="form-control" style="padding:2px 4px; font-size:11px;" disabled>
              <option>${escapeHtml(prof.default_model || 'Default')}</option>
            </select>
          </div>
          <div style="display:flex; align-items:center; gap:4px;">
            <img src="/static/${icon}" class="provider-logo-sm" onerror="this.src='/static/llama.png'">
            ${escapeHtml(prov)}
          </div>
          <div>
            <div class="cell-bar-track"><div class="cell-bar-fill" style="width:70%; background:var(--status-healthy);"></div></div>
            <div class="cell-bar-track" style="margin-top:4px;"><div class="cell-bar-fill" style="width:40%; background:var(--status-healthy);"></div></div>
          </div>
          <div style="font-size:10px; color:var(--text-muted);">
            26 авг.,<br>18:42
          </div>
          <div>
            <span style="color:var(--status-healthy);">● Активен</span>
          </div>
          <div style="text-align:center; cursor:pointer; color:var(--status-warning);" onclick="removeProfileFromChain('${escapeHtml(roleId)}', '${escapeHtml(pid)}')">
            <i class="fa-solid fa-xmark"></i>
          </div>
        </div>
      `;
    });

    rolesHtml += `
        </div>
        <div class="drop-zone" data-role="${escapeHtml(roleId)}">
          <i class="fa-solid fa-arrows-up-down"></i> Перетащите аккаунт сюда для добавления в конец списка
        </div>
      </div>
    `;
  }
  leftCol.innerHTML = rolesHtml;

  // Render Right Column (Available Accounts)
  let availHtml = '';
  const searchEl = document.getElementById('routing-account-search');
  const q = searchEl ? searchEl.value.toLowerCase() : '';
  
  let count = 0;
  for (const [pid, prof] of Object.entries(profiles)) {
    if (q && !pid.toLowerCase().includes(q) && !(prof.provider||'').toLowerCase().includes(q)) continue;
    count++;
    const icon = getProviderIcon(prof.provider);
    availHtml += `
      <div class="available-account-card draggable-item" draggable="true" data-pid="${escapeHtml(pid)}" data-source="available">
        <img src="/static/${icon}" style="width:24px; height:24px; border-radius:4px;" onerror="this.src='/static/llama.png'">
        <div style="flex:1;">
          <div style="font-weight:600; font-size:12px;">${escapeHtml(pid)}</div>
          <div style="font-size:10px; color:var(--text-muted);">${escapeHtml(prof.provider || '')}</div>
        </div>
        <div style="width:40px;">
           <div class="cell-bar-track"><div class="cell-bar-fill" style="width:80%; background:var(--status-healthy);"></div></div>
        </div>
        <button class="btn btn-secondary btn-sm" style="padding:2px 6px;" onclick="quickAddProfile('${escapeHtml(pid)}')"><i class="fa-solid fa-plus"></i></button>
      </div>
    `;
  }
  rightCol.innerHTML = availHtml;
  const countEl = document.getElementById('available-accounts-count');
  if (countEl) countEl.innerText = `${count} аккаунтов`;

  setupDragAndDrop();
}

function quickAddProfile(pid) {
    const routing = currentSnapshot.routing || {};
    let role = 'manager';
    if (!routing[role]) role = Object.keys(routing)[0];
    if (!role) return;
    addProfileToChain(role, pid);
}

function setupDragAndDrop() {
  let draggedEl = null;
  let dragPid = null;
  let sourceRole = null;

  document.querySelectorAll('.draggable-item').forEach(el => {
    el.addEventListener('dragstart', (e) => {
      draggedEl = el;
      dragPid = el.dataset.pid;
      sourceRole = el.dataset.role || null;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', dragPid);
      setTimeout(() => el.style.opacity = '0.5', 0);
    });
    el.addEventListener('dragend', (e) => {
      el.style.opacity = '1';
      document.querySelectorAll('.drag-over').forEach(d => d.classList.remove('drag-over'));
      draggedEl = null;
    });
  });

  // Drop zones (the "add to end" zones)
  document.querySelectorAll('.drop-zone').forEach(zone => {
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', (e) => {
      zone.classList.remove('drag-over');
    });
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const targetRole = zone.dataset.role;
      if (!targetRole || !dragPid) return;
      
      handleDropMove(dragPid, sourceRole, targetRole, -1);
    });
  });

  // Reordering inside role-chain-list
  document.querySelectorAll('.account-row').forEach(row => {
    row.addEventListener('dragover', (e) => {
      e.preventDefault();
      row.classList.add('drag-over');
    });
    row.addEventListener('dragleave', (e) => {
      row.classList.remove('drag-over');
    });
    row.addEventListener('drop', (e) => {
      e.preventDefault();
      row.classList.remove('drag-over');
      const targetRole = row.dataset.role;
      if (!targetRole || !dragPid) return;
      
      const list = row.parentNode;
      const children = Array.from(list.children);
      const insertIndex = children.indexOf(row);
      
      handleDropMove(dragPid, sourceRole, targetRole, insertIndex);
    });
  });
}

function handleDropMove(pid, sourceRole, targetRole, insertIndex) {
  const routing = currentSnapshot.routing;
  if (!routing || !routing[targetRole]) return;
  
  const targetChain = [...(routing[targetRole].preferred_chain || [])];
  
  if (sourceRole && sourceRole === targetRole) {
    const oldIndex = targetChain.indexOf(pid);
    if (oldIndex > -1) {
      targetChain.splice(oldIndex, 1);
    }
    if (insertIndex === -1) {
      targetChain.push(pid);
    } else {
      let idx = insertIndex;
      if (oldIndex > -1 && oldIndex < insertIndex) idx--;
      targetChain.splice(idx, 0, pid);
    }
    updateRoleChain(targetRole, targetChain);
  } else {
    if (targetChain.includes(pid)) {
        showToast(`Аккаунт ${pid} уже есть в роли ${targetRole}`, 'warning');
        return;
    }
    if (insertIndex === -1) {
      targetChain.push(pid);
    } else {
      targetChain.splice(insertIndex, 0, pid);
    }
    updateRoleChain(targetRole, targetChain);
  }
}

async function updateRoleChain(roleId, newChain) {
  try {
    const resp = await fetch(`/api/v1/router/roles/${encodeURIComponent(roleId)}/chain`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newChain)
    });
    if (!resp.ok) throw new Error(await resp.text());
    showToast(`Цепочка для ${roleId} обновлена`, 'success');
    await fetchSnapshot();
  } catch (e) {
    showToast(`Ошибка сохранения: ${e.message}`, 'error');
  }
}

async function removeProfileFromChain(roleId, pid) {
    const routing = currentSnapshot.routing;
    if (!routing || !routing[roleId]) return;
    const chain = [...(routing[roleId].preferred_chain || [])];
    const idx = chain.indexOf(pid);
    if (idx > -1) {
        chain.splice(idx, 1);
        await updateRoleChain(roleId, chain);
    }
}

function openAddNodeToChainModal(roleId) {
  if (!currentSnapshot) return;
  const pipeline = (currentSnapshot.routing || {})[roleId];
  if (!pipeline) return;

  const currentChain = (pipeline.nodes || []).map((n) => n.profile_id);
  const allProfiles = currentSnapshot.all_profiles || {};
  const available = Object.values(allProfiles).filter((p) => !currentChain.includes(p.profile_id));

  elements.modalTitle.textContent = `Добавить профиль в цепочку: ${pipeline.role_name_ru || roleId}`;
  if (available.length === 0) {
    elements.modalBody.innerHTML = `
      <div class="view-header-note">Все зарегистрированные профили уже включены в эту цепочку.</div>
    `;
    elements.modalFooter.innerHTML = `<button class="btn btn-ghost" onclick="closeModal()">Закрыть</button>`;
  } else {
    elements.modalBody.innerHTML = `
      <div id="modal-feedback-area"></div>
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Выберите доступный профиль для включения в цепочку отказоустойчивости:
      </div>
      <div style="margin-bottom:16px;">
        <select id="add-node-profile-select" class="select-filter" style="width:100%;">
          ${available.map((p) => `
            <option value="${escapeHtml(p.profile_id)}">
              ${escapeHtml(p.display_name || p.profile_id)} (${escapeHtml(p.provider_display_name || p.provider)}) — ${escapeHtml(p.email || p.account_identity || 'без email')}
            </option>
          `).join('')}
        </select>
      </div>
    `;
    elements.modalFooter.innerHTML = `
      <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" onclick="handleAddNodeToChain('${escapeHtml(roleId)}')">+ Добавить в цепочку</button>
    `;
  }
  showModal();
}

async function handleAddNodeToChain(roleId) {
  const sel = document.getElementById('add-node-profile-select');
  if (!sel) return;
  const newProfileId = sel.value;
  if (!newProfileId) return;

  const pipeline = (currentSnapshot.routing || {})[roleId];
  const currentChain = (pipeline?.nodes || []).map((n) => n.profile_id);
  const newChain = [...currentChain, newProfileId];

  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Добавление профиля в цепочку...</div>';
  }

  const res = await executeAction('save_chain', { role_id: roleId, chain: newChain });
  if (res.ok) {
    showToast(`Профиль добавлен в цепочку '${pipeline?.role_name_ru || roleId}'`, 'success');
    closeModal();
    fetchSnapshot();
  } else {
    if (feedbackArea) {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(res.message || 'Ошибка сохранения')}</div>`;
    }
  }
}

// ── SETTINGS MANAGEMENT ──
function renderSettingsView() {
  if (!currentSnapshot) return;
  const paths = currentSnapshot.system_paths || {};
  const s = currentSnapshot.settings || {};

  const elHome = document.getElementById('path-hermes-home');
  const elConfig = document.getElementById('path-config-dir');
  const elLog = document.getElementById('path-log-file');

  if (elHome) elHome.textContent = paths.hermes_home || '—';
  if (elConfig) elConfig.textContent = paths.config_dir || '—';
  if (elLog) elLog.textContent = paths.log_file || '—';

  const quotaThresholdSel = document.getElementById('setting-quota-threshold-percent');
  const quotaActionSel = document.getElementById('setting-quota-threshold-action');
  const emailMaskingSel = document.getElementById('setting-email-masking-mode');
  const monitorIntervalInput = document.getElementById('setting-monitoring-interval');

  if (quotaThresholdSel && s.quota_threshold_percent !== undefined) {
    quotaThresholdSel.value = String(Math.round(s.quota_threshold_percent));
  }
  if (quotaActionSel && s.quota_threshold_action) {
    quotaActionSel.value = s.quota_threshold_action;
  }
  if (emailMaskingSel && s.email_masking_mode) {
    emailMaskingSel.value = s.email_masking_mode;
  }
  if (monitorIntervalInput && s.monitoring_interval_seconds !== undefined) {
    monitorIntervalInput.value = s.monitoring_interval_seconds;
  }
}

async function saveHubServerSettings() {
  const quotaThresholdSel = document.getElementById('setting-quota-threshold-percent');
  const quotaActionSel = document.getElementById('setting-quota-threshold-action');
  const emailMaskingSel = document.getElementById('setting-email-masking-mode');
  const monitorIntervalInput = document.getElementById('setting-monitoring-interval');

  const newSettings = {
    quota_threshold_percent: quotaThresholdSel ? parseFloat(quotaThresholdSel.value) || 10.0 : 10.0,
    quota_threshold_action: quotaActionSel ? quotaActionSel.value : 'notify',
    email_masking_mode: emailMaskingSel ? emailMaskingSel.value : 'none',
    monitoring_interval_seconds: monitorIntervalInput ? parseInt(monitorIntervalInput.value, 10) || 30 : 30,
  };

  showToast('Сохранение настроек сервера...', 'info');
  const res = await executeAction('save_settings', newSettings);
  if (res.ok) {
    showToast('Настройки сервера успешно сохранены', 'success');
    fetchSnapshot();
  } else {
    showToast(res.message || 'Ошибка сохранения настроек сервера', 'error');
  }
}

// ── PREFLIGHT READINESS CHECKS ──
async function runPreflightChecks() {
  const container = document.getElementById('preflight-results-container');
  const btn = document.getElementById('btn-run-preflight');
  if (btn) btn.disabled = true;
  if (container) {
    container.innerHTML = '<div class="loading-state" style="padding:12px; font-size:13px; color:var(--text-secondary);">⏳ Запуск zero-quota проверки зависимостей и окружения...</div>';
  }
  try {
    const res = await executeAction('run_preflight', {});
    if (!res) throw new Error('Сервер не вернул ответ');
    const report = res.data || {};
    renderPreflightReport(report, container);
    showToast(res.message || 'Проверка готовности завершена', res.ok ? 'success' : 'warning');
  } catch (err) {
    if (container) {
      container.innerHTML = `<div class="modal-feedback error">❌ Ошибка выполнения проверки: ${escapeHtml(err.message || String(err))}</div>`;
    }
    showToast('Ошибка при запуске проверки готовности', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderPreflightReport(report, container) {
  if (!container) return;
  const checks = report.checks || [];
  const passed = report.passed_count || 0;
  const failed = report.failed_count || 0;
  const warn = report.warn_count || 0;

  const statusBadge = `<span class="badge ${failed === 0 ? 'healthy' : 'error'}">${failed === 0 ? 'Все проверки пройдены' : `Обнаружено ошибок: ${failed}`}</span>`;

  let html = `
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; padding:10px 14px; background:var(--surface-muted); border-radius:var(--radius-sm);">
      <div style="font-weight:600; font-size:13px;">Результат: ${statusBadge}</div>
      <div style="font-size:12px; color:var(--text-muted);">
        Пройдено: <strong style="color:var(--status-healthy);">${passed}</strong> • 
        Ошибок: <strong style="color:var(--status-error);">${failed}</strong> • 
        Предупреждений: <strong style="color:var(--status-warning);">${warn}</strong>
      </div>
    </div>
    <div class="preflight-list" style="display:flex; flex-direction:column; gap:8px;">
  `;

  checks.forEach((item) => {
    const badgeClass = item.status === 'PASS' ? 'healthy' : (item.status === 'WARN' ? 'warning' : 'error');
    const icon = item.status === 'PASS' ? '✓' : (item.status === 'WARN' ? '⚠' : '✕');
    html += `
      <div class="preflight-item" style="padding:10px 14px; background:var(--surface-card); border:1px solid var(--border-subtle); border-radius:var(--radius-sm);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
          <div style="font-weight:600; font-size:13px; display:flex; align-items:center; gap:8px;">
            <span class="badge ${badgeClass}" style="padding:2px 8px; font-size:11px;">${icon} ${escapeHtml(item.status)}</span>
            <span>${escapeHtml(item.name || item.check_id)}</span>
          </div>
        </div>
        <div style="font-size:12px; color:var(--text-secondary); margin-left:4px;">${escapeHtml(item.message || '')}</div>
        ${item.remediation ? `<div style="font-size:12px; color:var(--status-warning); margin-top:4px; margin-left:4px; font-style:italic;">💡 Рекомендация: ${escapeHtml(item.remediation)}</div>` : ''}
      </div>
    `;
  });

  html += '</div>';
  container.innerHTML = html;
}


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
  _openAccountModalProfile = null;
  stopDeviceAuthPolling();
  // Опрос входа по ссылке иначе продолжал бы стучать в закрытое окно.
  stopRedirectAuthPolling();
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

// ─────────────────────────────────────────────────────────────
//  Авторизация по коду устройства (Grok, OpenAI Codex)
// ─────────────────────────────────────────────────────────────

let _deviceAuthTimer = null;

function stopDeviceAuthPolling() {
  if (_deviceAuthTimer) {
    clearInterval(_deviceAuthTimer);
    _deviceAuthTimer = null;
  }
}

async function startDeviceAuth(providerId) {
  stopDeviceAuthPolling();
  const box = document.getElementById('device-auth-box');
  if (!box) return;

  const res = await executeAction('start_device_auth', { provider: providerId });
  if (!res || !res.ok) {
    box.innerHTML = `<div class="modal-feedback error">${escapeHtml((res && res.message) || 'Не удалось начать авторизацию')}</div>`;
    return;
  }

  const d = res.data || {};
  window._wiz_device_session = d.session_id;
  window._wiz_device_profile = d.profile_id;

  box.innerHTML = `
    <div style="font-weight:700; margin-bottom:6px;">1. Откройте ссылку:</div>
    <div style="display:flex; gap:8px; margin-bottom:12px;">
      <input type="text" class="input-text" style="flex:1;" id="wiz-auth-url" value="${escapeHtml(d.url || '')}" readonly>
      <button class="btn btn-secondary btn-sm" onclick="window.open(document.getElementById('wiz-auth-url').value, '_blank')">Открыть</button>
      <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(document.getElementById('wiz-auth-url').value, 'Ссылка скопирована')">Копировать</button>
    </div>
    <div style="font-weight:700; margin-bottom:6px;">2. Введите код:</div>
    <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
      <div style="font-family:var(--font-mono); font-size:22px; font-weight:700; color:var(--text-accent); letter-spacing:2px;" id="wiz-auth-code">${escapeHtml(d.code || '')}</div>
      <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(document.getElementById('wiz-auth-code').innerText, 'Код скопирован')">Копировать код</button>
    </div>
    <div id="device-auth-status" style="font-size:12px; color:var(--text-muted);">
      3. Подтвердите доступ — окно обновится само. Код живёт недолго, не откладывайте.
    </div>
  `;

  _deviceAuthTimer = setInterval(() => pollDeviceAuth(providerId), 3000);
}

async function pollDeviceAuth(providerId) {
  const status = document.getElementById('device-auth-status');
  if (!status) {
    stopDeviceAuthPolling();
    return;
  }

  const res = await executeAction('poll_device_auth', {
    provider: providerId,
    session_id: window._wiz_device_session,
  });

  if (!res) return;

  const state = (res.data || {}).status;
  if (res.ok && state === 'completed') {
    stopDeviceAuthPolling();
    status.innerHTML = '<span style="color:var(--status-healthy); font-weight:600;">Аккаунт подключён</span>';
    showToast('Аккаунт подключён', 'success');
    fetchSnapshot();
    return;
  }
  if (!res.ok) {
    // Отказ и просроченный код — конечные исходы, а не ожидание.
    stopDeviceAuthPolling();
    status.innerHTML = `<span style="color:var(--status-error); font-weight:600;">${escapeHtml(res.message || 'Авторизация не завершена')}</span>`;
  }
}

// Профили, реально участвующие в цепочках маршрутизации.
//
// Судить по assigned_roles нельзя: холодный резерв и ag-spare-2 значатся с
// ролью "spare", которой среди шести маршрутизируемых ролей нет. Поэтому
// берём состав самих цепочек — это точно и не зависит от названий ролей.
function profilesInRouting() {
  const routing = (currentSnapshot || {}).routing || {};
  const ids = new Set();
  Object.values(routing).forEach((pipeline) => {
    ((pipeline && pipeline.nodes) || []).forEach((n) => {
      if (n && n.profile_id) ids.add(n.profile_id);
    });
  });
  return ids;
}

// Список слотов провайдера из снимка: занятые помечены, свободные идут первыми.
function buildSlotOptions(providerId) {
  const profiles = ((currentSnapshot || {}).profiles_by_provider || {})[providerId] || [];
  if (!profiles.length) {
    return '<option value="">Список слотов ещё не получен</option>';
  }
  // Роль слота показываем прямо в списке. Без этого выбор вслепую: слоты
  // ag-spare-* и ag-cold-* не входят ни в одну цепочку, поэтому подключённый
  // в них аккаунт честно не появляется ни в «Обзоре», ни в «Маршрутизации» —
  // и выглядит это как пропажа.
  const routed = profilesInRouting();
  const free = [];
  const used = [];
  const idle = [];
  profiles.forEach((p) => {
    const isFree = p.health_state === 'not_configured';
    const inRouting = routed.has(p.profile_id);
    const roles = (p.assigned_roles || []).join(', ');
    const who = p.email || p.account_identity || '';
    const state = isFree ? 'свободен' : `занят${who ? ': ' + who : ''}`;
    const label = inRouting
      ? `${p.profile_id} — ${state} · ${roles || 'в маршрутизации'}`
      : `${p.profile_id} — ${state} · не участвует в маршрутизации`;
    const opt = `<option value="${escapeHtml(p.profile_id)}">${escapeHtml(label)}</option>`;
    if (!inRouting) idle.push(opt);
    else if (isFree) free.push(opt);
    else used.push(opt);
  });
  // Свободные слоты с ролью — первыми: именно они дают работающий маршрут.
  return free.concat(used, idle).join('');
}

let _redirectAuthTimer = null;

function stopRedirectAuthPolling() {
  if (_redirectAuthTimer) {
    clearInterval(_redirectAuthTimer);
    _redirectAuthTimer = null;
  }
}

// Вход по ссылке для Antigravity и Claude.
//
// Смысл: браузер не обязан быть на той машине, где работает Hub. Владелец
// открывает ссылку у себя, подтверждает доступ и возвращает результат сюда.
// Antigravity кладёт код в адресную строку (браузер при этом покажет ошибку
// соединения, если слушатель на другой машине — это нормально, адрес всё
// равно годен). Claude показывает код прямо на странице.
async function startRedirectAuth(providerId) {
  stopRedirectAuthPolling();
  const box = document.getElementById('redirect-auth-box');
  if (!box) return;

  // Слот выбирает владелец, а не догадка сервера.
  //
  // find_free_slot определяет занятость по файлу учётных данных, но agy на
  // Windows хранит их в keyring — файла нет ни у одного слота, поэтому все
  // десять считаются свободными и всегда возвращается первый, ag-orch-fallback.
  // Вход в него затёр бы работающий аккаунт. Список ниже строится из снимка,
  // который знает настоящее состояние, и показывает, что занято.
  const slot = document.getElementById('wiz-redirect-slot');
  const chosen = slot ? slot.value : '';

  const res = await executeAction('start_redirect_auth', {
    provider: providerId,
    profile_id: chosen || undefined,
  });
  if (!res || !res.ok) {
    box.innerHTML = `<div class="modal-feedback error">${escapeHtml((res && res.message) || 'Не удалось начать авторизацию')}</div>`;
    return;
  }

  const d = res.data || {};
  window._wiz_redirect_session = d.session_id;
  window._wiz_redirect_provider = providerId;
  window._wiz_redirect_slot_id = d.profile_id;

  const pastesUrl = d.paste_kind !== 'code';
  const label = pastesUrl
    ? 'Вставьте адрес из адресной строки браузера целиком:'
    : 'Вставьте код, показанный на странице:';
  const placeholder = pastesUrl ? 'http://127.0.0.1:…/oauth-callback?code=…' : 'Код со страницы провайдера';

  // Если хаб открыт не с этой же машины, браузер после подтверждения уйдёт на
  // 127.0.0.1:<порт> СВОЕЙ машины, где никто не слушает: получается тупик,
  // из которого адрес с кодом ещё надо как-то выковырять. Проброс этого порта
  // убирает проблему целиком — возврат попадает прямо в слушатель хаба и вход
  // завершается сам. Показываем готовую команду, а вставку оставляем запасным
  // путём.
  const host = window.location.hostname;
  const isRemote = host !== '127.0.0.1' && host !== 'localhost' && host !== '';
  const cbPort = d.port || 0;

  const tunnelNote = pastesUrl && isRemote && cbPort
    ? `<div class="modal-feedback info" style="margin-top:10px; font-size:12px;">
         <strong>Проще всего — пробросить порт возврата.</strong> Выполните у себя
         в терминале, до подтверждения доступа:
         <div style="display:flex; gap:6px; margin:6px 0;">
           <input type="text" class="input-text" style="flex:1; font-family:var(--font-mono); font-size:11px;"
                  id="wiz-redirect-tunnel" readonly
                  value="ssh -L ${cbPort}:127.0.0.1:${cbPort} ${escapeHtml(host)}">
           <button class="btn btn-secondary btn-sm"
                   onclick="copyToClipboard(document.getElementById('wiz-redirect-tunnel').value, 'Команда скопирована')">Копировать</button>
         </div>
         Тогда вход завершится сам и вставлять ничего не придётся.
       </div>`
    : '';

  const localNote = pastesUrl && d.redirect_uri
    ? `<div style="font-size:12px; color:var(--text-muted); margin-top:8px;">
         Без проброса браузер после подтверждения уйдёт на <code>${escapeHtml(d.redirect_uri)}</code>
         и покажет «страница недоступна» — это ожидаемо, хаб на другой машине.
         Скопируйте из адресной строки весь адрес целиком либо только значение
         <code>code=</code> — принимается и то, и другое.
       </div>`
    : '';

  box.innerHTML = `
    <div style="font-weight:700; margin-bottom:6px;">1. Откройте ссылку — на любой машине, где есть браузер:</div>
    <div style="display:flex; gap:8px; margin-bottom:12px;">
      <input type="text" class="input-text" style="flex:1;" id="wiz-redirect-url" value="${escapeHtml(d.url || '')}" readonly>
      <button class="btn btn-secondary btn-sm" onclick="window.open(document.getElementById('wiz-redirect-url').value, '_blank')">Открыть</button>
      <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(document.getElementById('wiz-redirect-url').value, 'Ссылка скопирована')">Копировать</button>
    </div>
    <div style="font-weight:700; margin-bottom:6px;">2. ${escapeHtml(label)}</div>
    <div style="display:flex; gap:8px; margin-bottom:6px;">
      <input type="text" class="input-text" style="flex:1;" id="wiz-redirect-paste" placeholder="${escapeHtml(placeholder)}">
      <button class="btn btn-primary btn-sm" onclick="submitRedirectCallback()">Завершить вход</button>
    </div>
    ${tunnelNote}
    ${localNote}
    <div id="redirect-auth-status" style="font-size:12px; color:var(--text-muted); margin-top:10px;">
      Слот: ${escapeHtml(d.profile_id || '—')}. Ссылка действует 20 минут.
    </div>
  `;

  // Если браузер открыт на этой же машине, слушатель поймает возврат сам —
  // тогда вставлять ничего не придётся.
  _redirectAuthTimer = setInterval(pollRedirectAuth, 3000);
}

async function submitRedirectCallback() {
  const input = document.getElementById('wiz-redirect-paste');
  const status = document.getElementById('redirect-auth-status');
  if (!input || !status) return;

  const value = (input.value || '').trim();
  if (!value) {
    status.innerHTML = '<span style="color:var(--status-warning);">Поле пустое — вставьте значение из браузера.</span>';
    return;
  }

  status.innerHTML = 'Проверяем…';
  const res = await executeAction('submit_redirect_callback', {
    session_id: window._wiz_redirect_session,
    provider: window._wiz_redirect_provider,
    callback_url: value,
  });

  if (res && res.ok) {
    stopRedirectAuthPolling();
    status.innerHTML = '<span style="color:var(--status-healthy); font-weight:600;">Аккаунт подключён</span>' + redirectSlotRoleNote();
    showToast('Аккаунт подключён', 'success');
    fetchSnapshot();
    return;
  }
  // Промах при вставке не заканчивает сессию: ссылка ещё годна, можно
  // вставить снова. Поэтому опрос не останавливаем.
  status.innerHTML = `<span style="color:var(--status-error);">${escapeHtml((res && res.message) || 'Не удалось завершить вход')}</span>`;
}

// Если слот не входит ни в одну цепочку, аккаунт не появится ни в «Обзоре»,
// ни в «Маршрутизации» — и это выглядит как пропажа. Говорим об этом сразу.
function redirectSlotRoleNote() {
  const pid = window._wiz_redirect_slot_id;
  if (!pid) return '';
  const all = (currentSnapshot || {}).all_profiles || [];
  const prof = all.find((p) => p.profile_id === pid);
  const roles = prof ? (prof.assigned_roles || []) : [];
  if (profilesInRouting().has(pid)) {
    return `<div style="margin-top:6px; font-size:12px; color:var(--text-muted);">Роль: ${escapeHtml(roles.join(', '))}</div>`;
  }
  return `<div class="modal-feedback info" style="margin-top:8px; font-size:12px;">
      Слот <code>${escapeHtml(pid)}</code> не входит ни в одну цепочку, поэтому в
      «Обзоре» и «Маршрутизации» аккаунт не появится. Добавьте его нужной роли
      в разделе «Маршрутизация» кнопкой «+ Добавить».
    </div>`;
}

async function pollRedirectAuth() {
  const status = document.getElementById('redirect-auth-status');
  if (!status) {
    stopRedirectAuthPolling();
    return;
  }
  const res = await executeAction('poll_redirect_auth', {
    session_id: window._wiz_redirect_session,
    provider: window._wiz_redirect_provider,
  });
  if (!res) return;

  if (res.ok && (res.data || {}).status === 'completed') {
    stopRedirectAuthPolling();
    status.innerHTML = '<span style="color:var(--status-healthy); font-weight:600;">Аккаунт подключён</span>';
    showToast('Аккаунт подключён', 'success');
    fetchSnapshot();
    return;
  }
  if (!res.ok) {
    // Конечный отказ провайдера — например, доступ отклонён.
    stopRedirectAuthPolling();
    status.innerHTML = `<span style="color:var(--status-error); font-weight:600;">${escapeHtml(res.message || 'Авторизация не завершена')}</span>`;
  }
}

async function handleDeleteCredentials(profileId) {
  // Подтверждение обязательно: действие необратимо, аккаунт придётся
  // подключать заново.
  if (!confirm(`Удалить учётные данные профиля ${profileId}? Аккаунт придётся подключить заново.`)) {
    return;
  }
  const res = await executeAction('delete_credentials', { profile_id: profileId });
  if (res && res.ok) {
    closeModal();
    fetchSnapshot();
  }
}

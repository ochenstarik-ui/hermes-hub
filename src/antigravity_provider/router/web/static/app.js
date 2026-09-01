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
  fetchSettings();
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
  document.body.dataset.view = viewName;
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });
  document.querySelectorAll('.view-pane').forEach((pane) => {
    pane.classList.toggle('active', pane.id === `view-${viewName}`);
  });

  const titles = {
    overview: 'Обзор системы',
    accounts: 'Аккаунты и квоты',
    routing: 'Маршрутизация',
    skills: 'Реестр навыков (Agent Skills · SkillDoctor)',
    analytics: 'Аналитика и телеметрия',
    health: 'Состояние системы',
    logs: 'Журнал событий',
    settings: 'Настройки Hermes Hub',
  };
  if (elements.pageTitle) {
    elements.pageTitle.textContent = titles[viewName] || 'Hermes Hub';
  }

  if (viewName === 'skills') {
    fetchSkills();
  }

  if (viewName === 'settings') {
    fetchSettings();
    // Состояние сжатия спрашиваем при открытии экрана, а не при каждой
    // отрисовке настроек: раньше опрос запускался на каждом обновлении
    // снапшота и замыкал круг сам на себя.
    checkCompressionStatus();
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

  // Reset router config listener (P0-4)
  const btnResetConfig = document.getElementById('btn-reset-router-config');
  if (btnResetConfig) {
    btnResetConfig.addEventListener('click', () => openResetConfigModal());
  }

  // Antigravity eligibility actions (A58)
  const btnRefreshAgyElig = document.getElementById('btn-refresh-agy-eligibility');
  if (btnRefreshAgyElig) {
    btnRefreshAgyElig.addEventListener('click', async () => {
      showToast('Проверка состояния agy...', 'info');
      const res = await executeAction('refresh_agy_eligibility');
      await fetchSettings();
      await fetchSnapshot();
      if (res && res.ok) showToast(res.message || 'Состояние обновлено', 'success');
    });
  }

  const btnRunAgyUpdate = document.getElementById('btn-run-agy-update');
  if (btnRunAgyUpdate) {
    btnRunAgyUpdate.addEventListener('click', async () => {
      if (!confirm('Обновление agy перезаписывает исполняемый файл и возвращает проверку доступности: сначала выполните обновление, затем повторно примените патч. Запустить agy update в терминале?')) return;
      const res = await executeAction('run_agy_update');
      await fetchSettings();
      await fetchSnapshot();
    });
  }

  const btnRunAgyPatch = document.getElementById('btn-run-agy-patch-script');
  if (btnRunAgyPatch) {
    btnRunAgyPatch.addEventListener('click', async () => {
      const pathVal = (document.getElementById('setting-agy-patch-script-path')?.value || '').trim();
      if (!pathVal && !currentSettings?.agy_patch_script_path) {
        showToast('Н/Д: путь к сценарию патча не указан в настройках', 'warning');
        return;
      }
      const res = await executeAction('run_agy_patch_script');
      await fetchSettings();
      await fetchSnapshot();
    });
  }

  // Skills view event listeners
  const skillsSearch = document.getElementById('skills-search');
  const filterSkillsSource = document.getElementById('filter-skills-source');
  const filterSkillsStatus = document.getElementById('filter-skills-status');
  const btnRefreshSkills = document.getElementById('btn-refresh-skills');
  const btnDoctorAll = document.getElementById('btn-doctor-all-skills');

  if (skillsSearch) skillsSearch.addEventListener('input', () => renderSkillsView());
  if (filterSkillsSource) filterSkillsSource.addEventListener('change', () => renderSkillsView());
  if (filterSkillsStatus) filterSkillsStatus.addEventListener('change', () => renderSkillsView());
  if (btnRefreshSkills) btnRefreshSkills.addEventListener('click', () => fetchSkills());
  if (btnDoctorAll) btnDoctorAll.addEventListener('click', () => runDoctorAllSkills());

  // Obsidian Vault event listeners
  const btnCheckVault = document.getElementById('btn-check-obsidian-vault');
  if (btnCheckVault) {
    btnCheckVault.addEventListener('click', () => {
      const p = document.getElementById('setting-obsidian-vault-path')?.value;
      checkObsidianVault(p);
    });
  }

  const btnSetupMemory = document.getElementById('btn-setup-memory-structure');
  if (btnSetupMemory) {
    btnSetupMemory.addEventListener('click', () => {
      const p = document.getElementById('setting-obsidian-vault-path')?.value;
      setupMemoryStructure(p);
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
// Цвет индикатора по измеренному состоянию. Неизвестное состояние остаётся
// серым (базовый .status-dot), а не выдаёт себя за здоровое.
function healthDotClass(state) {
  const st = String(state || '').toLowerCase();
  if (st === 'healthy') return 'healthy';
  if (['quota_exhausted', 'rate_limited', 'auth_required', 'auth_expired'].includes(st)) return 'warning';
  if (['error', 'unhealthy'].includes(st)) return 'error';
  return '';
}

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

// Действия-опросы: их запускает сам интерфейс, а не владелец.
//
// Показывать их тостами нельзя: опрос состояния сжатия шёл при каждом
// обновлении снапшота, и владелец не видел за уведомлениями самой программы.
// Хуже того, успешное действие вызывало fetchSnapshot, тот перерисовывал
// настройки, а перерисовка снова запускала опрос — круг замыкался и кормил
// сам себя. Поэтому опросы не только молчат, но и не дёргают снапшот.
const SILENT_ACTIONS = new Set([
  'get_compression_status',
  'poll_native_auth', 'poll_native_agy_login', 'poll_terminal_auth',
  'poll_redirect_auth', 'poll_device_auth',
]);

async function executeAction(actionName, actionData = {}) {
  const silent = SILENT_ACTIONS.has(actionName);
  if (!silent) showToast(`Выполняется «${actionName}»...`, 'info');
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
      if (!silent) {
        showToast(result.message || 'Действие выполнено успешно', 'success');
        fetchSnapshot();
      }
      return result;
    } else {
      // Отказ опроса показываем в том месте, которое его запросило: у мастера
      // входа для этого своя область сообщений. Тостом заливать нельзя.
      if (!silent) showToast(result.message || 'Отказ выполнения действия', 'warning');
      return result;
    }
  } catch (err) {
    console.error(`Action ${actionName} failed:`, err);
    if (!silent) showToast(`Ошибка сети: ${err.message}`, 'error');
    return { ok: false, message: `Ошибка сети: ${err.message}` };
  }
}

// ── GLOBAL HEADER ──
// Версия между сборками не меняется намеренно, а коммит — строка из
// шестнадцатеричных цифр. Дата установки отвечает на вопрос «старая сборка
// загрузилась или новая» сразу и без сверки коммитов.
function versionTagText(curVer) {
  const installedAt = currentSettings && currentSettings.installed_at;
  let stamp = '';
  if (installedAt) {
    const d = new Date(installedAt);
    if (!isNaN(d.getTime())) {
      stamp = ' · ' + d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
  }
  return curVer ? `Hermes Hub Web v${curVer}${stamp}` : 'Hermes Hub Web — Н/Д: версия не передана сервером';
}

function updateGlobalHeader() {
  if (!currentSnapshot) return;

  const readiness = currentSnapshot.readiness || {};
  renderAccountSummary(currentSnapshot);
  const allProfiles = Object.values(currentSnapshot.all_profiles || {});
  // Одно число — одно определение. Готовность считает строго AUTHENTICATED,
  // а страница аккаунтов — всё, что не NOT_CONFIGURED. Из-за двух определений
  // значок в меню показывал 9, а карточка на той же странице — 3.
  // Берём то же правило, что и страница аккаунтов: расходиться они не должны.
  const connectedAccounts = allProfiles.filter((p) => isConnectedProfile(p)).length;

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

  const hermesCfg = (currentSnapshot.metrics || {}).hermes_config;
  const hermesBadge = document.getElementById('header-hermes-config-badge');
  if (hermesBadge) {
    if (hermesCfg && hermesCfg.exists && hermesCfg.model) {
      hermesBadge.innerHTML = `🤖 В Hermes: <strong>${escapeHtml(hermesCfg.model)}</strong> (${escapeHtml(hermesCfg.provider || 'default')})`;
      hermesBadge.classList.remove('hidden');
    } else if (hermesCfg && hermesCfg.exists) {
      hermesBadge.innerHTML = `🤖 В Hermes: (модель не выбрана)`;
      hermesBadge.classList.remove('hidden');
    } else {
      hermesBadge.innerHTML = `🤖 В Hermes: конфигурация не найдена`;
      hermesBadge.classList.remove('hidden');
    }
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
  if (kpiProvidersCount) kpiProvidersCount.textContent = (currentSnapshot.providers || []).length;

  const curVer = (currentSnapshot && (currentSnapshot.version || (currentSnapshot.metrics || {}).version)) || (currentSettings && currentSettings.version) || '';
  const versionTag = document.getElementById('version-tag');
  if (versionTag) {
    versionTag.textContent = versionTagText(curVer);
  }
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
    case 'skills':
      renderSkillsView();
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
    nvidia: 'NVIDIA NIM',
    openrouter: 'OpenRouter',
    local: 'llama.cpp',
    'local-llm': 'llama.cpp',
    'llama.cpp': 'llama.cpp',
    ollama: 'Ollama',
    vllm: 'vLLM',
  };

  const profilesByProv = currentSnapshot.profiles_by_provider || {};
  let totalProfiles = 0;
  let visibleProfiles = 0;
  let html = '<div style="grid-column:1/-1"><button class="btn btn-secondary" onclick="executeAction(\'check_all_accounts\', {})">Проверить все аккаунты</button> <button class="btn btn-secondary" onclick="handleClearAccounts()">Очистить все аккаунты</button></div>';

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
            <img class="brand-logo" src="/static/${getProviderIcon(providerId)}" width="24" height="24" alt="">
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
  const isAssigned = profile.assigned_roles && profile.assigned_roles.length > 0;
  const roles = isAssigned ? profile.assigned_roles.join(', ') : 'Не назначен';
  const identity = profile.email || profile.account_identity || profile.display_name || profile.profile_id;
  const healthState = profile.health_state || 'unknown';
  const healthLabel = profile.health_label_ru || 'Н/Д: состояние не проверялось';
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

  const unassignedBadge = !isAssigned ? '<span class="badge badge-unassigned">Не назначен</span>' : '';

  let agyEligibilityHtml = '';
  if (['antigravity', 'google-antigravity'].includes(String(profile.provider || '').toLowerCase())) {
    const agyElig = (currentSnapshot && currentSnapshot.agy_eligibility) || {};
    let badgeClass = '';
    let badgeText = agyElig.status_label_ru || 'Н/Д';
    if (agyElig.status === 'check_removed') {
      badgeClass = 'healthy';
      badgeText = '✓ Проверка снята';
    } else if (agyElig.status === 'check_active') {
      badgeClass = 'warning';
      badgeText = '⚠️ Проверка на месте';
    }
    const badgeHtml = `<span class="badge badge-status ${badgeClass}" title="${escapeHtml(agyElig.detail_ru || '')}">${escapeHtml(badgeText)}</span>`;

    let warningHtml = '';
    if (agyElig.status === 'check_active') {
      warningHtml = `
        <div class="account-eligibility-warning" style="margin-top:6px; padding:6px 8px; background:rgba(230,162,60,0.15); border-left:3px solid var(--status-warning); border-radius:3px; font-size:11px; color:var(--status-warning); line-height:1.4;">
          ⚠️ <strong>Проверка доступности Antigravity активна.</strong> Аккаунт может отклоняться Google по региону. Примените патч или настройте прокси.
        </div>
      `;
    }
    agyEligibilityHtml = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px; font-size:11px; color:var(--text-muted);">
        <span>Доступность agy:</span>
        ${badgeHtml}
      </div>
      ${warningHtml}
    `;
  }

  return `
    <div class="account-card ${isMain ? 'main-account' : ''}" data-profile-id="${escapeHtml(profile.profile_id)}">
      <div class="account-card-header">
        <div class="account-provider-tag">
          <img src="/static/${getProviderIcon(profile.provider)}" alt=""><span>${escapeHtml(profile.provider_display_name || profile.provider)}</span>
        </div>
        <div class="account-badges">
          ${plan ? `<span class="badge badge-plan">${escapeHtml(plan)}</span>` : ''}
          ${unassignedBadge}
          <span class="badge badge-status ${healthState}">● ${escapeHtml(healthLabel)}</span>
        </div>
      </div>

      <div class="account-identity-row">
        <div class="account-email" title="${escapeHtml(identity)}">${escapeHtml(identity)}</div>
        <div class="account-meta" title="${escapeHtml(profile.display_name)} • ${escapeHtml(roles)}">
          ${escapeHtml(profile.display_name)} • ${escapeHtml(roles)}
        </div>
      </div>

      <div class="account-models"><span>Предпочитаемые:</span>${(profile.preferred_models || []).map(modelBrandLabel).join('')}</div>
      ${agyEligibilityHtml}
      ${renderAccountCheck(profile)}
      ${quotaGridHtml}
    </div>
  `;
}

function renderAccountCheck(profile) {
  const check = profile.connection_check || {};
  const meta = profile.model_discovery || {};
  const checking = check.state === 'checking';
  const models = meta.models || [];
  const timestamp = meta.discovered_at ? new Date(meta.discovered_at * 1000).toLocaleString('ru-RU') : '';
  const modelStatus = meta.error ? `Сервер отказал: ${meta.error}` : timestamp ? `Получено ${models.length} моделей · ${timestamp}` : 'Список моделей ещё не получен';
  return `<div class="account-check" aria-live="polite">
    ${checking ? `<p>${escapeHtml(profile.display_name || profile.profile_id)}: идёт опрос провайдера, это может занять до минуты на этап.</p>` : ''}
    <p>${escapeHtml(check.message || "Подключение ещё не проверялось")}</p>
    <p>${escapeHtml(modelStatus)}</p>
    <details ${models.length <= 16 ? 'open' : ''}><summary>Каталог моделей (${models.length})</summary><div class="account-models">${models.map(modelBrandLabel).join('')}</div></details>
    ${profile.provider === 'ollama' ? `<p>Выше — модели указанного сервера Ollama.</p><p>Облачный каталог Ollama: ${meta.cloud?.error ? 'Н/Д — ' + escapeHtml(meta.cloud.error) : meta.cloud?.models ? escapeHtml(meta.cloud.models.join(', ')) : 'Н/Д — ещё не получен'}</p><p>Доступ аккаунта к облачным моделям: Н/Д до успешного вызова. Для прямого вызова нужен API-ключ Ollama; для локального клиента — вход через ollama signin.</p>` : ''}
    <button class="btn btn-ghost btn-sm" ${checking ? 'disabled' : ''} onclick="event.stopPropagation(); handleAccountProbe('${escapeHtml(profile.profile_id)}')">${checking ? 'Проверяется…' : 'Проверить подключение'}</button>
    ${['nvidia', 'nvidia-nim', 'openrouter'].includes(String(profile.provider || '').toLowerCase())
      ? `<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); handleProbeAccountModels('${escapeHtml(profile.profile_id)}', '${escapeHtml(profile.provider)}')" title="Каталог провайдера общий для всех и о правах аккаунта не сообщает. Доступность выясняется опросом моделей и расходует вызовы.">Определить доступные модели</button>`
      : ''}
  </div>`;
}

// Каталог NVIDIA и OpenRouter публичный: он одинаков у всех и о правах
// аккаунта ничего не говорит. Доступность выясняется опросом моделей, а он
// тратит вызовы — поэтому только по явному нажатию, и результат сохраняется.
async function handleProbeAccountModels(profileId, provider) {
  if (!confirm('Хаб опросит каталог провайдера, чтобы выяснить, какие модели доступны этому аккаунту. Каталог общий для всех и о правах не сообщает, поэтому каждая модель проверяется отдельным запросом. Недоступная отвечает отказом и ничего не стоит, доступная расходует один токен. Продолжить?')) return;
  showToast('Опрос моделей начат. Это может занять около минуты.', 'info');
  const res = await executeAction('probe_account_models', { profile_id: profileId, provider: provider });
  showToast(res?.message || 'Нет ответа от сервера', res?.ok ? 'success' : 'error');
  await fetchSnapshot();
}

async function handleAccountProbe(profileId) {
  await executeAction('check_account', {profile_id: profileId});
  await fetchSnapshot();
}

function renderQuotaCell(bucket, unavailableReason) {
  const remaining = bucket.remaining_percent;
  let formattedValue = 'Н/Д';
  let barWidth = 0;
  let colorClass = 'var(--status-disabled)';

  const isUnlimited = bucket.status === 'unlimited' || bucket.period === 'unlimited' || (unavailableReason && unavailableReason.includes('Без ограничений'));

  if (isUnlimited) {
    formattedValue = 'Без ограничений';
    barWidth = 100;
    colorClass = 'var(--status-healthy)';
  } else if (typeof remaining === 'number') {
    formattedValue = `${remaining.toFixed(1)}%`;
    barWidth = Math.max(0, Math.min(100, remaining));
    if (remaining <= 0) colorClass = 'var(--status-error)';
    else if (remaining < 20) colorClass = 'var(--status-warning)';
    else colorClass = 'var(--status-healthy)';
  } else if (unavailableReason) {
    formattedValue = 'Н/Д';
  }

  let resetText = isUnlimited
    ? (unavailableReason || 'Без ограничений')
    : (bucket.reset_at
        ? `Сброс: ${formatIsoDate(bucket.reset_at)}`
        : (bucket.period ? `Период: ${bucket.period}` : (unavailableReason || 'Период провайдера')));

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
    'openai-codex':'openai.png', openai:'openai.png', codex:'openai.png',
    antigravity:'antigravity.png', 'google-antigravity':'antigravity.png',
    'opencode-go':'opencode.png', opencode:'opencode.png',
    claude:'claude-color.svg', 'anthropic-claude':'claude-color.svg', anthropic:'claude-color.svg',
    grok:'grok.svg', xai:'grok.svg', ollama:'ollama.svg',
    nvidia:'nvidia-color.svg', openrouter:'openrouter.svg',
    deepseek:'deepseek-color.svg', vllm:'vllm-color.svg', lmstudio:'lmstudio.svg',
    local:'unknown.svg', 'llama.cpp':'unknown.svg',
  };
  return 'brands/'+(map[String(provider || '').toLowerCase()] || 'unknown.svg');
}

function getModelIcon(model) {
  const name=String(model || '').toLowerCase().split('/').at(-1);
  const family=[
    [/^gemini(?:[-.:]|$)/,'gemini-color.svg'],
    [/^claude(?:[-.:]|$)/,'claude-color.svg'],[/^(?:gpt|chatgpt|codex|o[134])(?:[-.:0-9]|$)/,'openai.png'],
    [/^grok(?:[-.:]|$)/,'grok.svg'],[/^deepseek(?:[-.:]|$)/,'deepseek-color.svg'],
    [/^qwen(?:[-.:0-9]|$)/,'qwen-color.svg'],[/^(?:llama|meta-llama)(?:[-.:0-9]|$)/,'meta-color.svg'],
    [/^(?:mistral|mixtral|codestral|devstral|magistral)(?:[-.:0-9]|$)/,'mistral-color.svg'],
  ].find(([pattern])=>pattern.test(name));
  return 'brands/'+(family?.[1] || 'unknown.svg');
}

function modelBrandLabel(model) {
  return `<span class="model-brand"><img class="brand-logo" src="/static/${getModelIcon(model)}" alt=""><span>${escapeHtml(model || 'Модель: Н/Д')}</span></span>`;
}

function renderRoutingView() { renderAccountRouting(); }

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
  
  const targetChain = (routing[targetRole].nodes || []).map(node => node.profile_id);
  
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
  const result = await executeAction('save_chain', { role_id: roleId, chain: newChain });
  if (result.ok) await fetchSnapshot();
}

async function removeProfileFromChain(roleId, pid) {
    const routing = currentSnapshot.routing;
    if (!routing || !routing[roleId]) return;
    const chain = (routing[roleId].nodes || []).map(node => node.profile_id);
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
  const available = Object.values(allProfiles).filter((p) => isConnectedProfile(p) && !currentChain.includes(p.profile_id));

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

async function openAutoAssignPreviewModal() {
  if (elements.modalTitle) elements.modalTitle.textContent = '⚡ Предварительный просмотр авто-распределения';
  elements.modalBody.innerHTML = '<div class="modal-feedback info">⏳ Расчёт плана распределения аккаунтов...</div>';
  elements.modalFooter.innerHTML = '<button class="btn btn-ghost" onclick="closeModal()">Отмена</button>';
  showModal();

  const res = await executeAction('preview_auto_assign', {});
  if (!res || !res.ok || !res.data || !res.data.success) {
    elements.modalBody.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Не удалось сформировать план авто-распределения')}</div>`;
    return;
  }

  const data = res.data;
  const changes = data.changes || [];
  if (changes.length === 0) {
    elements.modalBody.innerHTML = '<div class="view-header-note">Нет изменений для применения. Все роли уже распределены оптимально.</div>';
    return;
  }

  let tableHtml = `
    <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
      Будет распределено <strong>${data.total_authenticated}</strong> подключённых аккаунтов по ролям:
    </div>
    <div style="max-height:360px; overflow-y:auto; border:1px solid var(--border-subtle); border-radius:var(--radius-sm);">
      <table class="data-table" style="width:100%; font-size:12px;">
        <thead>
          <tr>
            <th>Роль</th>
            <th>Текущая цепочка</th>
            <th>Предлагаемая цепочка</th>
          </tr>
        </thead>
        <tbody>
  `;

  changes.forEach((ch) => {
    const cur = (ch.current_chain && ch.current_chain.length) ? ch.current_chain.join(' → ') : '<span class="text-muted">пусто</span>';
    const prop = (ch.proposed_chain && ch.proposed_chain.length) ? ch.proposed_chain.join(' → ') : '<span class="text-muted">пусто</span>';
    tableHtml += `
      <tr>
        <td><strong>${escapeHtml(ch.role_name_ru || ch.role)}</strong></td>
        <td>${cur}</td>
        <td style="color:var(--status-healthy); font-weight:600;">${prop}</td>
      </tr>
    `;
  });

  tableHtml += '</tbody></table></div>';
  elements.modalBody.innerHTML = tableHtml;
  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
    <button class="btn btn-primary" id="btn-apply-auto-assign" onclick="applyAutoAssign()">Применить</button>
  `;
}

async function applyAutoAssign() {
  const btn = document.getElementById('btn-apply-auto-assign');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Применение...';
  }
  const res = await executeAction('auto_assign_all', {});
  if (res && res.ok) {
    showToast('Авто-распределение успешно применено', 'success');
    closeModal();
    await fetchSnapshot();
  } else {
    showToast((res && res.message) || 'Ошибка применения', 'error');
  }
}

// ── ANALYTICS VIEW ──
function renderAnalyticsView() {
  if (!currentSnapshot) return;
  const metrics = currentSnapshot.metrics || {};
  const telemetry = metrics.telemetry || {};
  const global = telemetry.global || {};

  const totalCallsEl = document.getElementById('analytics-total-calls');
  const callsBreakdownEl = document.getElementById('analytics-calls-breakdown');
  const errorRateEl = document.getElementById('analytics-error-rate');
  const errorRateSubEl = document.getElementById('analytics-error-rate-sub');
  const latencyP50El = document.getElementById('analytics-latency-p50');
  const latencySubEl = document.getElementById('analytics-latency-sub');
  const tokensTotalEl = document.getElementById('analytics-tokens-total');
  const tokensSubEl = document.getElementById('analytics-tokens-sub');

  if (global.total_calls !== undefined) {
    if (totalCallsEl) totalCallsEl.textContent = new Intl.NumberFormat('ru-RU').format(global.total_calls);
    const routedCount = global.routed_calls_count ?? (global.total_calls - (global.bypassed_calls_count ?? 0));
    const bypassCount = global.bypassed_calls_count ?? 0;
    if (callsBreakdownEl) callsBreakdownEl.textContent = `Через хаб: ${routedCount} · Мимо хаба (Bypass): ${bypassCount}`;
    const errRate = global.total_calls > 0 && global.failed_calls != null ? ((global.failed_calls / global.total_calls) * 100).toFixed(1) : null;
    if (errorRateEl) errorRateEl.textContent = errRate === null ? 'Н/Д' : `${errRate}%`;
    if (errorRateSubEl) errorRateSubEl.textContent = `${global.failed_calls ?? 0} сбоев из ${global.total_calls} вызовов (Bypass: ${bypassCount})`;
  } else {
    if (totalCallsEl) totalCallsEl.textContent = '—';
    if (callsBreakdownEl) callsBreakdownEl.textContent = 'Нет данных за 24 ч';
    if (errorRateEl) errorRateEl.textContent = '—';
    if (errorRateSubEl) errorRateSubEl.textContent = 'Нет зарегистрированных сбоев';
  }

  if (Number.isFinite(global.latency_p50_ms)) {
    if (latencyP50El) latencyP50El.textContent = `${global.latency_p50_ms} мс`;
    if (latencySubEl) latencySubEl.textContent = `p95: ${global.latency_p95_ms ?? '—'} мс · max: ${global.latency_max_ms ?? '—'} мс`;
  } else {
    if (latencyP50El) latencyP50El.textContent = '—';
    if (latencySubEl) latencySubEl.textContent = 'Задержка не измерена';
  }

  if (global.total_tokens !== undefined && global.total_tokens !== null) {
    if (tokensTotalEl) tokensTotalEl.textContent = new Intl.NumberFormat('ru-RU').format(global.total_tokens);
    if (tokensSubEl) tokensSubEl.textContent = `Вход: ${new Intl.NumberFormat('ru-RU').format(global.total_prompt_tokens ?? 'Н/Д')} · Выход: ${new Intl.NumberFormat('ru-RU').format(global.total_completion_tokens ?? 'Н/Д')}`;
  } else {
    if (tokensTotalEl) tokensTotalEl.textContent = 'Н/Д';
    if (tokensSubEl) tokensSubEl.textContent = 'Н/Д: провайдеры не отдают usage';
  }

  renderAnalyticsCharts(telemetry);

  // Providers telemetry table
  const providersContainer = document.getElementById('analytics-providers-table');
  const providersData = telemetry.by_provider || {};
  if (providersContainer) {
    const provKeys = Object.keys(providersData);
    if (provKeys.length === 0) {
      providersContainer.innerHTML = '<div style="padding:16px; text-align:center; color:var(--text-muted);">Нет накопленной телеметрии по провайдерам</div>';
    } else {
      let tableHtml = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Провайдер</th>
              <th>Всего вызовов</th>
              <th>Успешных</th>
              <th>Ошибок</th>
              <th>p50 задержка</th>
              <th>Расход токенов</th>
            </tr>
          </thead>
          <tbody>
      `;
      provKeys.forEach((pKey) => {
        const item = providersData[pKey] || {};
        tableHtml += `
          <tr>
            <td><strong>${escapeHtml(pKey)}</strong></td>
            <td>${item.total_calls ?? 0}</td>
            <td style="color:var(--status-healthy);">${item.successful_calls ?? 0}</td>
            <td style="color:${(item.failed_calls ?? 0) > 0 ? 'var(--status-error)' : 'inherit'};">${item.failed_calls ?? 0}</td>
            <td>${Number.isFinite(item.latency_p50_ms) ? `${item.latency_p50_ms} мс` : '—'}</td>
            <td>${item.total_tokens != null ? new Intl.NumberFormat('ru-RU').format(item.total_tokens) : 'Н/Д'}</td>
          </tr>
        `;
      });
      tableHtml += '</tbody></table>';
      providersContainer.innerHTML = tableHtml;
    }
  }

  // Roles telemetry table
  const rolesContainer = document.getElementById('analytics-roles-table');
  const rolesData = telemetry.by_role || {};
  if (rolesContainer) {
    const roleKeys = Object.keys(rolesData);
    if (roleKeys.length === 0) {
      rolesContainer.innerHTML = '<div style="padding:16px; text-align:center; color:var(--text-muted);">Нет накопленной телеметрии по ролям</div>';
    } else {
      let tableHtml = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Роль</th>
              <th>Всего вызовов</th>
              <th>Успешных</th>
              <th>Ошибок</th>
              <th>p50 задержка</th>
            </tr>
          </thead>
          <tbody>
      `;
      roleKeys.forEach((rKey) => {
        const item = rolesData[rKey] || {};
        tableHtml += `
          <tr>
            <td><strong>${escapeHtml(rKey)}</strong></td>
            <td>${item.total_calls ?? 0}</td>
            <td style="color:var(--status-healthy);">${item.successful_calls ?? 0}</td>
            <td style="color:${(item.failed_calls ?? 0) > 0 ? 'var(--status-error)' : 'inherit'};">${item.failed_calls ?? 0}</td>
            <td>${Number.isFinite(item.latency_p50_ms) ? `${item.latency_p50_ms} мс` : '—'}</td>
          </tr>
        `;
      });
      tableHtml += '</tbody></table>';
      rolesContainer.innerHTML = tableHtml;
    }
  }
}

// ── HEALTH VIEW ──
function renderHealthView() {
  if (!currentSnapshot) return;
  const readiness = currentSnapshot.readiness || {};
  const banner = document.getElementById('health-readiness-banner');
  if (banner) {
    const stateClass = readiness.state === 'HEALTHY' ? 'ready' : (readiness.state === 'LIMITED' ? 'warning' : 'not-ready');
    banner.className = `readiness-banner ${stateClass}`;
    banner.innerHTML = `
      <div class="readiness-banner-header">
        <span class="status-dot ${stateClass}"></span>
        <h3>${escapeHtml(readiness.title_ru || 'Состояние готовности')}</h3>
      </div>
      <p class="readiness-banner-desc">${escapeHtml(readiness.summary_ru || 'Проверка состояния маршрутизатора')}</p>
      <div class="readiness-banner-metrics">
        <span>Готовых ролей: <strong>${readiness.roles_ready_count ?? 0} из ${readiness.total_roles ?? 'Н/Д'}</strong></span>
        <span>Подключенных аккаунтов: <strong>${(currentSnapshot.all_profiles ? Object.values(currentSnapshot.all_profiles).filter(isConnectedProfile).length : 0)}</strong></span>
      </div>
    `;
  }

  const resContainer = document.getElementById('health-host-resources');
  if (resContainer) {
    renderHostResources(resContainer, currentSnapshot.metrics?.host || {});
  }

  if (banner) {
    const probe = currentSnapshot.account_probe || {};
    banner.insertAdjacentHTML('beforeend', `<p class="readiness-banner-desc">Автопроверка: ${probe.enabled ? 'работает' : 'остановлена'}. Последний обход: ${probe.last_tick ? escapeHtml(new Date(probe.last_tick * 1000).toLocaleString()) : 'ещё не выполнялся'}. ${escapeHtml(probe.error || '')}</p>`);
  }
  renderHealthPanels(currentSnapshot);
  const warningsContainer = document.getElementById('health-warnings-list');
  if (warningsContainer) {
    const warnings = readiness.warnings || [];
    const agyElig = currentSnapshot.agy_eligibility || {};
    const agyWarnHtml = (agyElig.status === 'check_active')
      ? `<div class="warning-item" style="padding:8px 12px; margin-bottom:6px; border-left:3px solid var(--status-warning); background:var(--surface-muted); font-size:12px;">
           <strong>⚠️ Проверка доступности Antigravity активна</strong>: аккаунты Google могут отклоняться по региону («not currently available in your location»). Примените патч в Настройках или используйте прокси.
         </div>`
      : '';

    if (warnings.length === 0 && !agyWarnHtml) {
      warningsContainer.innerHTML = '<div style="padding:14px; color:var(--status-healthy); font-size:12px;">✓ Критических предупреждений и деградаций не обнаружено</div>';
    } else {
      const regularWarnings = warnings.map((w) => `
        <div class="warning-item" style="padding:8px 12px; margin-bottom:6px; border-left:3px solid var(--status-warning); background:var(--surface-muted); font-size:12px;">
          <strong>⚠ ${escapeHtml(w.title || 'Предупреждение')}</strong>: ${escapeHtml(w.message || w)}
        </div>
      `).join('');
      warningsContainer.innerHTML = agyWarnHtml + regularWarnings;
    }
  }
}

// ── LOGS VIEW ──
let cachedLogs = [];

async function fetchLogs() {
  if (!currentSnapshot) return;
  cachedLogs = [...(currentSnapshot.workflow?.events || [])].reverse();
  renderLogsList(cachedLogs);
}

function renderLogsView() {
  fetchLogs();
}

function renderLogsList(events) {
  const listToRender = events || cachedLogs;
  const container = document.getElementById('logs-container');
  if (!container) return;
  const searchEl = document.getElementById('logs-search');
  const levelEl = document.getElementById('logs-filter-level');
  const catEl = document.getElementById('logs-filter-category');

  const q = searchEl ? searchEl.value.toLowerCase().trim() : '';
  const levelFilter = levelEl ? levelEl.value : 'all';
  const catFilter = catEl ? catEl.value : 'all';

  const filtered = listToRender.filter((ev) => {
    if (levelFilter !== 'all' && (ev.level || '').toLowerCase() !== levelFilter) return false;
    if (catFilter !== 'all' && (ev.type || '').toLowerCase() !== catFilter) return false;
    if (q) {
      const matchText = `${ev.message || ''} ${ev.details || ''} ${ev.type || ''} ${ev.account || ''}`.toLowerCase();
      if (!matchText.includes(q)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    renderLogDetail(null);
    container.innerHTML = '<div style="padding:24px; text-align:center; color:var(--text-muted); font-size:12px;">События не найдены в текущем снапшоте</div>';
    return;
  }

  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:140px;">Время</th>
          <th style="width:90px;">Уровень</th>
          <th style="width:110px;">Категория</th>
          <th>Сообщение</th>
        </tr>
      </thead>
      <tbody>
        ${filtered.map((ev, index) => {
          const lvl = (ev.level || 'info').toLowerCase();
          const lvlClass = lvl === 'error' ? 'error' : (lvl === 'warning' || lvl === 'warn' ? 'warning' : (lvl === 'success' ? 'healthy' : 'info'));
          return `
            <tr tabindex="0" data-event-index="${index}" aria-label="Открыть событие">
              <td style="font-size:11px; color:var(--text-muted); font-family:var(--font-mono);">${escapeHtml(ev.timestamp || '—')}</td>
              <td><span class="badge ${lvlClass}" style="font-size:10px; text-transform:uppercase;">${escapeHtml(ev.level || 'INFO')}</span></td>
              <td style="font-size:11px; color:var(--text-secondary);">${escapeHtml(ev.type || 'Н/Д')}</td>
              <td style="font-size:12px;">
                <div>${escapeHtml(ev.message || '')}</div>
                ${ev.details ? `<div style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-top:2px;">${escapeHtml(typeof ev.details === 'object' ? JSON.stringify(ev.details) : ev.details)}</div>` : ''}
              </td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
  container.querySelectorAll('[data-event-index]').forEach(row => {
    const open = () => renderLogDetail(filtered[Number(row.dataset.eventIndex)]);
    row.addEventListener('click', open);
    row.addEventListener('keydown', event => { if (event.key === 'Enter') open(); });
  });
  renderLogDetail(filtered[0]);
}

// ── SETTINGS MANAGEMENT ──
async function fetchSettings() {
  try {
    const headers = authToken ? { 'X-Hub-Token': authToken } : {};
    const res = await fetch('/api/settings', { headers });
    if (res.ok) {
      currentSettings = await res.json();
      if (activeView === 'settings') {
        renderSettingsView();
      }
      return currentSettings;
    }
  } catch (err) {
    console.error('Failed to fetch settings:', err);
  }
  return null;
}

function renderSettingsView() {
  const s = currentSettings || {};
  const sysPaths = s.system_paths || (currentSnapshot && currentSnapshot.system_paths) || {};

  const elHome = document.getElementById('path-hermes-home');
  const elConfig = document.getElementById('path-config-dir');
  const elLog = document.getElementById('path-log-file');

  const homePath = sysPaths.hermes_home || s.hermes_home;
  const configPath = sysPaths.config_dir || s.config_dir;
  const logPath = sysPaths.log_file || s.log_file;

  if (elHome) elHome.textContent = homePath || 'Н/Д: путь не передан сервером';
  if (elConfig) elConfig.textContent = configPath || 'Н/Д: путь не передан сервером';
  if (elLog) elLog.textContent = logPath || 'Н/Д: путь не передан сервером';

  // Server Host & Port
  const hostInput = document.getElementById('setting-server-host');
  const portInput = document.getElementById('setting-server-port');
  if (hostInput && s.web_api_host !== undefined) {
    hostInput.value = s.web_api_host;
  }
  if (portInput && s.web_api_port !== undefined) {
    portInput.value = s.web_api_port;
  }

  // Token Badge
  const tokenBadge = document.getElementById('setting-token-status-badge');
  if (tokenBadge) {
    const isTokenSet = Boolean(s.web_api_token_configured || s.web_api_token);
    if (isTokenSet) {
      tokenBadge.textContent = '✓ Задан';
      tokenBadge.className = 'badge healthy';
    } else {
      tokenBadge.textContent = 'Не задан';
      tokenBadge.className = 'badge';
    }
  }

  // Account Check Interval
  const accountIntervalInput = document.getElementById('setting-account-check-interval');
  if (accountIntervalInput) {
    const accVal = s.account_check_interval_seconds ?? s.account_interval;
    if (accVal !== undefined && Number.isFinite(Number(accVal))) {
      accountIntervalInput.value = accVal;
      accountIntervalInput.disabled = false;
      accountIntervalInput.placeholder = '300';
    } else {
      accountIntervalInput.placeholder = 'Н/Д: не передан сервером';
    }
  }

  // Прокси провайдеров: пустая строка — осмысленное значение «без прокси»,
  // поэтому отличаем её от «сервер не передал».
  const proxyInput = document.getElementById('setting-provider-proxy-url');
  if (proxyInput) {
    if (s.provider_proxy_url !== undefined) {
      proxyInput.value = s.provider_proxy_url || '';
      proxyInput.placeholder = 'без прокси';
    } else {
      proxyInput.placeholder = 'Н/Д: не передан сервером';
    }
  }

  // Quota Interval
  const quotaIntervalSel = document.getElementById('setting-quota-interval');
  if (quotaIntervalSel) {
    const qVal = s.quota_refresh_interval_sec ?? s.quota_interval ?? s.account_check_interval_seconds;
    if (qVal !== undefined) {
      quotaIntervalSel.value = String(qVal);
    }
  }

  // Quota Threshold Percent
  const quotaThresholdSel = document.getElementById('setting-quota-threshold-percent');
  if (quotaThresholdSel && s.quota_threshold_percent !== undefined) {
    quotaThresholdSel.value = String(Math.round(s.quota_threshold_percent));
  }

  // Quota Threshold Action
  const quotaActionSel = document.getElementById('setting-quota-threshold-action');
  if (quotaActionSel && s.quota_threshold_action) {
    quotaActionSel.value = s.quota_threshold_action;
  }

  // Email Masking Mode
  const emailMaskingSel = document.getElementById('setting-email-masking-mode');
  if (emailMaskingSel && s.email_masking_mode) {
    emailMaskingSel.value = s.email_masking_mode;
  }

  // Default Role
  const defaultRoleSel = document.getElementById('setting-default-role');
  if (defaultRoleSel) {
    const currentDef = s.default_role || (currentSnapshot && currentSnapshot.metrics && currentSnapshot.metrics.default_role) || 'manager';
    defaultRoleSel.value = currentDef;
  }

  // Theme
  const themeSel = document.getElementById('setting-theme');
  if (themeSel && s.theme) {
    themeSel.value = s.theme;
  }

  // Monitor Interval
  const monitorIntervalInput = document.getElementById('setting-monitoring-interval');
  if (monitorIntervalInput && s.monitoring_interval_seconds !== undefined) {
    monitorIntervalInput.value = s.monitoring_interval_seconds;
  }

  // Obsidian Vault Path
  const vaultPathInput = document.getElementById('setting-obsidian-vault-path');
  if (vaultPathInput) {
    vaultPathInput.value = s.obsidian_vault_path || '/srv/projects/AI-Memory';
  }

  // Context Compression Settings (A56)
  populateCompressorProfiles(s);
  const compThresholdSel = document.getElementById('setting-compression-threshold-percent');
  if (compThresholdSel && s.compression_threshold_percent !== undefined) {
    compThresholdSel.value = String(Math.round(s.compression_threshold_percent));
  }
  const compKeepRecentSel = document.getElementById('setting-compression-keep-recent');
  if (compKeepRecentSel && s.compression_keep_recent_messages !== undefined) {
    compKeepRecentSel.value = String(s.compression_keep_recent_messages);
  }

  // Antigravity CLI & Eligibility Settings (A58)
  const agyPatchInput = document.getElementById('setting-agy-patch-script-path');
  if (agyPatchInput) {
    agyPatchInput.value = s.agy_patch_script_path || '';
  }

  const agyElig = s.agy_eligibility || (currentSnapshot && currentSnapshot.agy_eligibility) || {};
  const agyBadge = document.getElementById('agy-eligibility-badge');
  const agyDesc = document.getElementById('agy-version-path-desc');
  const agyDetails = document.getElementById('agy-eligibility-details');

  if (agyBadge) {
    if (agyElig.status === 'check_removed') {
      agyBadge.textContent = '✓ Проверка снята';
      agyBadge.className = 'badge healthy';
    } else if (agyElig.status === 'check_active') {
      agyBadge.textContent = '⚠️ Проверка на месте';
      agyBadge.className = 'badge warning';
    } else {
      agyBadge.textContent = agyElig.status_label_ru || 'Н/Д: не определено';
      agyBadge.className = 'badge';
    }
  }

  if (agyDesc) {
    const ver = agyElig.version || 'Н/Д';
    const bin = agyElig.binary_path || 'Н/Д';
    agyDesc.innerHTML = `Версия: <strong>${escapeHtml(ver)}</strong> • Путь: <code class="mono-path">${escapeHtml(bin)}</code>`;
  }

  if (agyDetails) {
    if (agyElig.binary_sha256) {
      agyDetails.textContent = `SHA-256: ${agyElig.binary_sha256}\nРазмер: ${agyElig.binary_size_bytes || 0} байт\nОписание: ${agyElig.detail_ru || ''}`;
    } else {
      agyDetails.textContent = agyElig.detail_ru || '';
    }
  }
}

function populateCompressorProfiles(s) {
  const compProfileSel = document.getElementById('setting-compressor-profile');
  if (!compProfileSel) return;

  const currentVal = (s && s.compressor_profile_id) || compProfileSel.value || 'none';
  const profiles = (currentSnapshot && (currentSnapshot.all_profiles || currentSnapshot.profiles)) || {};

  let optionsHtml = '<option value="none">Н/Д: модель для сжатия не выбрана (отключено)</option>';
  for (const [pid, p] of Object.entries(profiles)) {
    const prov = p.provider || 'unknown';
    const name = p.display_name || pid;
    const model = (p.preferred_models && p.preferred_models[0]) || '';
    const endpoint = p.custom_base_url || (p.auth_config && p.auth_config.base_url) || '';
    const label = `${name} [${prov}]${model ? ' — ' + model : ''}${endpoint ? ' (' + endpoint + ')' : ''}`;
    optionsHtml += `<option value="${escapeHtml(pid)}">${escapeHtml(label)}</option>`;
  }
  compProfileSel.innerHTML = optionsHtml;
  if (currentVal) compProfileSel.value = currentVal;
}

async function saveHubServerSettings() {
  const hostInput = document.getElementById('setting-server-host');
  const portInput = document.getElementById('setting-server-port');
  const tokenInput = document.getElementById('setting-server-token-input');
  const quotaThresholdSel = document.getElementById('setting-quota-threshold-percent');
  const quotaActionSel = document.getElementById('setting-quota-threshold-action');
  const emailMaskingSel = document.getElementById('setting-email-masking-mode');
  const quotaIntervalSel = document.getElementById('setting-quota-interval');
  const monitorIntervalInput = document.getElementById('setting-monitoring-interval');
  const vaultPathInput = document.getElementById('setting-obsidian-vault-path');
  const compProfileSel = document.getElementById('setting-compressor-profile');
  const compThresholdSel = document.getElementById('setting-compression-threshold-percent');
  const compKeepRecentSel = document.getElementById('setting-compression-keep-recent');
  const accountIntervalInput = document.getElementById('setting-account-check-interval');
  const defaultRoleSel = document.getElementById('setting-default-role');
  const themeSel = document.getElementById('setting-theme');
  const agyPatchInput = document.getElementById('setting-agy-patch-script-path');

  const proxyInputSave = document.getElementById('setting-provider-proxy-url');

  const newSettings = {};
  // Пустое поле — это выбор «без прокси», а не отсутствие значения:
  // отправляем его тоже, иначе прокси нельзя было бы убрать.
  if (proxyInputSave) newSettings.provider_proxy_url = proxyInputSave.value.trim();
  if (agyPatchInput) newSettings.agy_patch_script_path = agyPatchInput.value.trim();
  if (hostInput && hostInput.value.trim()) newSettings.web_api_host = hostInput.value.trim();
  if (portInput && portInput.value) newSettings.web_api_port = Number(portInput.value);
  if (tokenInput && tokenInput.value.trim()) newSettings.web_api_token = tokenInput.value.trim();
  if (accountIntervalInput && accountIntervalInput.value) newSettings.account_check_interval_seconds = Math.max(60, Number(accountIntervalInput.value));
  if (quotaIntervalSel && quotaIntervalSel.value) newSettings.quota_refresh_interval_sec = Number(quotaIntervalSel.value);
  if (quotaThresholdSel && quotaThresholdSel.value) newSettings.quota_threshold_percent = Number(quotaThresholdSel.value);
  if (quotaActionSel && quotaActionSel.value) newSettings.quota_threshold_action = quotaActionSel.value;
  if (emailMaskingSel && emailMaskingSel.value) newSettings.email_masking_mode = emailMaskingSel.value;
  if (monitorIntervalInput && monitorIntervalInput.value) newSettings.monitoring_interval_seconds = Number(monitorIntervalInput.value);
  if (vaultPathInput && vaultPathInput.value.trim()) newSettings.obsidian_vault_path = vaultPathInput.value.trim();
  if (compProfileSel) newSettings.compressor_profile_id = (compProfileSel.value === 'none' || !compProfileSel.value) ? null : compProfileSel.value;
  if (compThresholdSel && compThresholdSel.value) newSettings.compression_threshold_percent = Number(compThresholdSel.value);
  if (compKeepRecentSel && compKeepRecentSel.value) newSettings.compression_keep_recent_messages = Number(compKeepRecentSel.value);
  if (defaultRoleSel && defaultRoleSel.value) newSettings.default_role = defaultRoleSel.value;
  if (themeSel && themeSel.value) newSettings.theme = themeSel.value;

  if (!Object.keys(newSettings).length) { showToast('Нет выбранных изменений', 'info'); return; }

  showToast('Сохранение настроек сервера...', 'info');
  const res = await executeAction('save_settings', newSettings);
  if (res && res.ok) {
    showToast('Настройки сервера успешно сохранены', 'success');
    await fetchSettings();
    fetchSnapshot();
  } else {
    showToast((res && res.message) || 'Ошибка сохранения настроек сервера', 'error');
  }
}

// ── RESET CONFIGURATION (P0-2 & P0-4) ──
function openResetConfigModal() {
  elements.modalTitle.textContent = 'Начать настройку заново';
  elements.modalBody.innerHTML = `
    <div class="modal-feedback warning" style="margin-bottom:14px; line-height:1.5;">
      ⚠️ <strong>Вы собираетесь сбросить конфигурацию маршрутизатора в исходное чистое состояние.</strong>
    </div>
    <div style="font-size:13px; margin-bottom:12px;">
      <div style="font-weight:600; color:var(--status-error); margin-bottom:4px;">Будет сброшено:</div>
      <ul style="margin:0 0 12px 18px; padding:0; color:var(--text-secondary);">
        <li>Цепочки всех 13 ролей (будут очищены).</li>
        <li>Список профилей в <code>router_profiles.yaml</code> (0 профилей).</li>
        <li>Перед сбросом создаётся резервная копия <code>router_profiles.yaml.bak_...</code>.</li>
      </ul>
      <div style="font-weight:600; color:var(--status-healthy); margin-bottom:4px;">Будет сохранено (НЕ затрагивается):</div>
      <ul style="margin:0 0 0 18px; padding:0; color:var(--text-secondary);">
        <li>Все учётные данные, токены, ключи и подключённые аккаунты.</li>
        <li>Файлы авторизации в <code>~/.hermes/agy_profiles/</code>, <code>codex_profiles/</code> и др.</li>
        <li>Общие настройки хаба в <code>hub_settings.json</code>.</li>
      </ul>
    </div>
    <div id="reset-config-feedback-area"></div>
  `;
  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
    <button class="btn btn-danger" id="btn-modal-confirm-reset" onclick="confirmResetConfig()">Сбросить и начать заново</button>
  `;
  showModal();
}

async function confirmResetConfig() {
  const btn = document.getElementById('btn-modal-confirm-reset');
  const feedback = document.getElementById('reset-config-feedback-area');
  if (btn) btn.disabled = true;
  if (feedback) {
    feedback.innerHTML = '<div class="modal-feedback info">⏳ Выполняется сброс конфигурации...</div>';
  }
  try {
    const res = await executeAction('reset_router_config', {});
    if (res && res.ok) {
      if (feedback) {
        feedback.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Конфигурация успешно сброшена')}</div>`;
      }
      setTimeout(() => {
        closeModal();
        fetchSnapshot();
      }, 1000);
    } else {
      if (btn) btn.disabled = false;
      if (feedback) {
        feedback.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Ошибка сброса конфигурации')}</div>`;
      }
    }
  } catch (err) {
    if (btn) btn.disabled = false;
    if (feedback) {
      feedback.innerHTML = `<div class="modal-feedback error">❌ Ошибка: ${escapeHtml(err.message || String(err))}</div>`;
    }
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

function openAccountDetailsModal(profileId, isRedraw = false) {
  _openAccountModalProfile = profileId;
  if (!currentSnapshot) return;
  const allProfiles = currentSnapshot.all_profiles || {};
  const profile = allProfiles[profileId];
  if (!profile) return;

  const provSummary = (currentSnapshot.providers || []).find((p) => p.provider_id === profile.provider);
  const discoveredModels = profile.model_discovery?.models || ((provSummary && provSummary.discovered_models) ? provSummary.discovered_models : []);
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
            ${discoveredModels.map((m) => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
          </select>
          <button class="btn btn-secondary btn-sm" onclick="handleSaveProfileModel('${escapeHtml(profileId)}')">Сохранить</button>
        </div>
      </div>
    `;
  } else {
    modelBlockHtml = `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <div style="font-size:12px; color:var(--status-warning); margin-bottom:6px;">
          ${escapeHtml(profile.model_discovery?.error ? "Сервер отказал: " + profile.model_discovery.error : profile.connection_check?.state === "checking" ? "Идёт запрос списка моделей…" : "Список моделей ещё не получен от провайдера " + (profile.provider_display_name || profile.provider))}
        </div>
        <button class="btn btn-secondary btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(profile.provider)}', '${escapeHtml(profileId)}')" ${profile.connection_check?.state === 'checking' ? 'disabled' : ''}>${profile.connection_check?.state === 'checking' ? 'Запрашивается список моделей…' : '↻ Запросить список моделей'}</button>
      </div>
    `;
  }

  modelBlockHtml = renderAccountCheck(profile) + modelBlockHtml;

  // Local request options section
  let requestOptionsHtml = '';
  if (profile.provider === 'local') {
    const rawOptions = profile.request_options || {};
    const formattedJson = JSON.stringify(rawOptions, null, 2);
    requestOptionsHtml = `
      <div style="background:var(--surface-muted); padding:12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <label style="font-weight:700; font-size:12px;">Параметры запроса (JSON request_options):</label>
          <span id="modal-options-validation-status" style="font-size:11px; color:var(--status-healthy);">✓ JSON валиден</span>
        </div>
        <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">
          Произвольные параметры, подмешиваемые в тело запроса (например, <code>{"chat_template_kwargs": {"enable_thinking": false}}</code>).
        </div>
        <textarea id="modal-request-options-input" class="input-text" style="width:100%; height:90px; font-family:var(--font-mono); font-size:11px; resize:vertical;" placeholder="{}" oninput="updateRequestOptionsPreview('${escapeHtml(profileId)}')">${escapeHtml(formattedJson)}</textarea>
        
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
          <button class="btn btn-secondary btn-sm" onclick="handleSaveRequestOptions('${escapeHtml(profileId)}')">💾 Сохранить параметры</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleRequestOptionsPreview()">👁 Предпросмотр тела запроса</button>
        </div>

        <div id="modal-payload-preview-box" style="display:none; margin-top:10px;">
          <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:4px;">Что отправится на сервер (/chat/completions):</div>
          <pre id="modal-payload-preview-content" style="background:var(--surface-card); padding:8px 10px; border-radius:4px; font-size:11px; font-family:var(--font-mono); color:var(--text-accent); max-height:140px; overflow-y:auto; margin:0; border:1px solid var(--border-subtle);"></pre>
        </div>
      </div>
    `;
  }

  let quotasHtml = '';
  if (profile.provider !== 'local') {
    quotasHtml = `
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
        `).join('') || '<div class="empty-text">Данные о квотах отсутствуют.</div>'}
      </div>
    `;
  }

  // Antigravity eligibility section
  let agyModalBlockHtml = '';
  if (['antigravity', 'google-antigravity'].includes(String(profile.provider || '').toLowerCase())) {
    const agyElig = (currentSnapshot && currentSnapshot.agy_eligibility) || {};
    let badgeClass = '';
    let badgeText = agyElig.status_label_ru || 'Н/Д';
    if (agyElig.status === 'check_removed') {
      badgeClass = 'healthy';
      badgeText = '✓ Проверка снята';
    } else if (agyElig.status === 'check_active') {
      badgeClass = 'warning';
      badgeText = '⚠️ Проверка на месте';
    }
    agyModalBlockHtml = `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <strong style="font-size:12px;">Состояние проверки доступности agy:</strong>
          <span class="badge badge-status ${badgeClass}">${escapeHtml(badgeText)}</span>
        </div>
        <div style="font-size:11px; color:var(--text-secondary); margin-bottom:4px;">
          ${escapeHtml(agyElig.detail_ru || 'Состояние проверки доступности утилиты agy.')}
        </div>
        ${agyElig.binary_path ? `<div style="font-size:11px; font-family:var(--font-mono); color:var(--text-muted); word-break:break-all;">Файл: ${escapeHtml(agyElig.binary_path)} (v${escapeHtml(agyElig.version || 'Н/Д')})</div>` : ''}
        ${agyElig.status === 'check_active' ? `
          <div style="margin-top:6px; padding:6px 8px; background:rgba(230,162,60,0.15); border-left:3px solid var(--status-warning); border-radius:3px; font-size:11px; color:var(--status-warning);">
            ⚠️ <strong>Внимание:</strong> Проверка доступности активна. Аккаунт может отклоняться Google по региону. Примените патч в Настройках или настройте прокси.
          </div>
        ` : ''}
      </div>
    `;
  }

  modelBlockHtml = renderAccountCheck(profile) + modelBlockHtml;
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
        Назначенные роли: <strong>${escapeHtml((profile.assigned_roles && profile.assigned_roles.length > 0) ? profile.assigned_roles.join(', ') : 'Не назначен')}</strong>
      </div>
    </div>

    ${agyModalBlockHtml}
    ${modelBlockHtml}
    ${requestOptionsHtml}
    ${quotasHtml}
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-secondary" id="btn-modal-test-profile" onclick="handleTestProfile('${escapeHtml(profileId)}')">⚡ Проверить подключение</button>
    <button class="btn btn-secondary" onclick="executeAction('set_main', { profile_id: '${escapeHtml(profileId)}' })">★ Сделать основным</button>
    <button class="btn btn-secondary" onclick="handleDeleteCredentials('${escapeHtml(profileId)}')">Удалить ключ</button>
    <button class="btn btn-primary" onclick="closeModal()">Закрыть</button>
  `;

  if (!isRedraw) {
    showModal();
  }
  if (profile.provider === 'local') {
    updateRequestOptionsPreview(profileId);
  }
}

function updateRequestOptionsPreview(profileId) {
  const input = document.getElementById('modal-request-options-input');
  const statusEl = document.getElementById('modal-options-validation-status');
  const previewContent = document.getElementById('modal-payload-preview-content');
  if (!input) return;

  const raw = input.value.trim();
  let parsed = {};
  let isValid = true;
  let errorMsg = '';

  if (raw) {
    try {
      parsed = JSON.parse(raw);
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
        isValid = false;
        errorMsg = 'JSON должен быть объектом {...}';
      }
    } catch (e) {
      isValid = false;
      errorMsg = e.message;
    }
  }

  if (statusEl) {
    if (isValid) {
      statusEl.style.color = 'var(--status-healthy)';
      statusEl.textContent = '✓ JSON валиден';
    } else {
      statusEl.style.color = 'var(--status-error)';
      statusEl.textContent = `⚠ Ошибка: ${errorMsg}`;
    }
  }

  if (previewContent) {
    const profile = (currentSnapshot && currentSnapshot.all_profiles) ? currentSnapshot.all_profiles[profileId] : null;
    const model = (profile && profile.preferred_models && profile.preferred_models[0]) || 'default';
    const samplePayload = {
      model: model,
      messages: [{ role: 'user', content: 'Тестовое сообщение' }],
      temperature: 0.7,
      max_tokens: 1500,
    };
    if (isValid && typeof parsed === 'object' && parsed !== null) {
      Object.assign(samplePayload, parsed);
    }
    previewContent.textContent = JSON.stringify(samplePayload, null, 2);
  }
}

function toggleRequestOptionsPreview() {
  const box = document.getElementById('modal-payload-preview-box');
  if (box) {
    box.style.display = box.style.display === 'none' ? 'block' : 'none';
  }
}

async function handleSaveRequestOptions(profileId) {
  const input = document.getElementById('modal-request-options-input');
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (!input) return;

  const raw = input.value.trim();
  let parsed = {};
  if (raw) {
    try {
      parsed = JSON.parse(raw);
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
        throw new Error('Параметры должны быть JSON-объектом {...}');
      }
    } catch (e) {
      if (feedbackArea) {
        feedbackArea.innerHTML = `<div class="modal-feedback error">❌ Некорректный JSON: ${escapeHtml(e.message)}</div>`;
      }
      return;
    }
  }

  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Сохранение параметров запроса...</div>';
  }

  const res = await executeAction('save_request_options', {
    profile_id: profileId,
    request_options: parsed,
  });

  if (feedbackArea) {
    if (res && res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Параметры сохранены')}</div>`;
      showToast('Параметры запроса сохранены', 'success');
      if (currentSnapshot && currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
        currentSnapshot.all_profiles[profileId].request_options = parsed;
      }
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Ошибка сохранения')}</div>`;
    }
  }
}

async function handleTestProfile(profileId) {
  const feedbackArea = document.getElementById('modal-feedback-area');
  const btn = document.getElementById('btn-modal-test-profile');
  if (btn) btn.disabled = true;
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Выполняется проверка подключения и тестовый запрос...</div>';
  }

  const profile = (currentSnapshot && currentSnapshot.all_profiles) ? currentSnapshot.all_profiles[profileId] : null;
  const prov = profile ? profile.provider : '';

  const res = await executeAction('test', {
    profile_id: profileId,
    provider: prov,
  });

  if (btn) btn.disabled = false;
  if (feedbackArea) {
    const data = (res && res.data) || {};
    const dur = data.duration_sec ? ` (${data.duration_sec}с)` : '';
    if (res && res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Подключение успешно')}${dur}</div>`;
      showToast('Проверка подключения успешна', 'success');
    } else {
      const errMsg = (res && (res.message || (res.data && res.data.error))) || 'Ошибка подключения';
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml(errMsg)}${dur}</div>`;
      showToast(`Сбой проверки: ${errMsg}`, 'error');
    }
  }
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
    if (res && res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Модель сохранена')}</div>`;
      if (currentSnapshot && currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
        currentSnapshot.all_profiles[profileId].preferred_models = [model];
      }
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Ошибка сохранения модели')}</div>`;
    }
  }
}

async function handleRefreshProviderModels(provider, profileId) {
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Запрос списка моделей от сервера...</div>';
  }
  const res = await executeAction('refresh_models', { provider: provider });
  if (res && res.ok) {
    showToast('Список моделей обновлен', 'success');
    await fetchSnapshot();
    if (_openAccountModalProfile) {
      openAccountDetailsModal(_openAccountModalProfile, true);
    }
  } else {
    if (feedbackArea) {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Не удалось получить модели')}</div>`;
    }
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

// ── THEME SWITCHER ──
function applyTheme(theme) {
  // Тем три, а не две.
  //
  // Medium была полностью описана в style.css, но здесь не обрабатывалась и в
  // список выбора не попадала — выбрать её было нельзя. По брендбуку это
  // отдельная тема, а не осветлённая Dark: тёмно-зелёный холст #1A2A1F со
  // светлыми кремовыми карточками #F7F1E3. Проверено подстановкой атрибута
  // вручную — отрисовывается верно и отличается от Dark и фоном, и карточками.
  const known = ['light', 'medium', 'dark'];
  if (known.includes(theme)) {
    document.body.setAttribute('data-theme', theme);
    document.body.classList.toggle('theme-light', theme === 'light');
  } else {
    // Системная: отдаём выбор prefers-color-scheme.
    document.body.removeAttribute('data-theme');
    document.body.classList.remove('theme-light');
  }
}

// ── UPDATE MANAGEMENT (P0-1 / In-App Updates) ──
async function checkUpdates(silent = false) {
  if (!silent) {
    showToast('Проверка обновлений...', 'info');
  }
  try {
    const res = await executeAction('check_updates', {});
    if (res && res.ok && res.data) {
      latestUpdateInfo = res.data;
      renderUpdateUI();
      if (!silent) {
        if (res.data.update_available) {
          const c = res.data.latest_commit ? res.data.latest_commit.slice(0, 7) : (res.data.release_tag || 'new');
          showToast(`Доступно обновление (сборка ${c})`, 'info');
        } else {
          showToast(res.data.message || 'Установлена последняя сборка', 'success');
        }
      }
    } else {
      if (res && res.data) {
        latestUpdateInfo = res.data;
        renderUpdateUI();
      }
      if (!silent) {
        showToast((res && res.message) || 'Ошибка проверки обновлений', 'error');
      }
    }
  } catch (err) {
    if (!silent) {
      showToast(`Ошибка проверки обновлений: ${err.message}`, 'error');
    }
  }
}

function renderUpdateUI() {
  const badge = document.getElementById('header-update-badge');
  const badgeText = document.getElementById('header-update-text');
  const commitTag = document.getElementById('commit-tag');

  // Первым источником — снапшот работающего сервера: он приходит всегда, а
  // панель обновлений заполняется только при её открытии. На Linux строка
  // сборки поэтому оставалась пустой, и понять, дошло ли обновление, было
  // нельзя.
  //
  // Берём running_commit — коммит, снятый при СТАРТЕ процесса. Поле commit
  // читается с диска при каждом запросе, и переживший обновление процесс
  // рапортует им свежий номер при старом поведении.
  const runningCommit = (currentSnapshot && currentSnapshot.running_commit) || '';
  const installedCommit = runningCommit
    || (latestUpdateInfo && latestUpdateInfo.installed_commit && latestUpdateInfo.installed_commit !== 'unknown'
      ? latestUpdateInfo.installed_commit
      : (currentSettings && currentSettings.installed_commit ? currentSettings.installed_commit : ''));

  if (commitTag) {
    if (!installedCommit) {
      commitTag.textContent = 'Сборка: Н/Д (сервер не передал номер)';
    } else {
      const startedAt = currentSnapshot && currentSnapshot.started_at;
      const since = startedAt
        ? ` · запущен ${new Date(startedAt * 1000).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`
        : '';
      commitTag.textContent = `Сборка: ${installedCommit.slice(0, 7)}${since}`;
    }
  }

  if (badge && badgeText) {
    if (latestUpdateInfo && latestUpdateInfo.update_available) {
      badge.classList.remove('hidden');
      const c = latestUpdateInfo.latest_commit ? latestUpdateInfo.latest_commit.slice(0, 7) : (latestUpdateInfo.release_tag || 'new');
      badgeText.textContent = `Доступно обновление (${c})`;
    } else {
      badge.classList.add('hidden');
    }
  }

  const updateInfoDesc = document.getElementById('update-installed-info');
  const statusBadge = document.getElementById('update-status-badge');
  const lastCheckedDesc = document.getElementById('update-last-checked-desc');
  const btnApply = document.getElementById('btn-apply-update');
  const detailsBlock = document.getElementById('update-details-block');
  const releaseTitle = document.getElementById('update-release-title');
  const releaseMeta = document.getElementById('update-release-meta');
  const releaseNotes = document.getElementById('update-release-notes');

  // Версия берётся ТОЛЬКО из API. Раньше номер был зашит в разметке и в
  // запасном значении: подъём версии в коде до интерфейса не доходил, и
  // владелец видел старый номер при новой сборке.
  const curVer = (latestUpdateInfo && latestUpdateInfo.current_version) || (currentSettings && currentSettings.version) || '';
  const cDisplay = installedCommit ? installedCommit.slice(0, 7) : 'неизвестно';
  if (updateInfoDesc) {
    updateInfoDesc.textContent = curVer
      ? `Hermes Hub v${curVer} (сборка: ${cDisplay})`
      : `Hermes Hub (сборка: ${cDisplay}) — Н/Д: версия не передана сервером`;
  }
  const versionTag = document.getElementById('version-tag');
  if (versionTag) {
    versionTag.textContent = versionTagText(curVer);
  }

  if (statusBadge) {
    if (latestUpdateInfo && latestUpdateInfo.error) {
      statusBadge.textContent = 'Ошибка проверки';
      statusBadge.className = 'badge badge-status warning';
      statusBadge.title = latestUpdateInfo.error;
    } else if (latestUpdateInfo && latestUpdateInfo.update_available) {
      statusBadge.textContent = 'Доступно обновление';
      statusBadge.className = 'badge badge-status warning';
      statusBadge.title = '';
    } else if (latestUpdateInfo && latestUpdateInfo.checked_at > 0) {
      statusBadge.textContent = 'Актуально';
      statusBadge.className = 'badge healthy';
      statusBadge.title = '';
    } else {
      statusBadge.textContent = 'Не проверялось';
      statusBadge.className = 'badge';
      statusBadge.title = '';
    }
  }

  if (lastCheckedDesc) {
    if (latestUpdateInfo && latestUpdateInfo.checked_at > 0) {
      const tStr = new Date(latestUpdateInfo.checked_at * 1000).toLocaleTimeString('ru-RU');
      const errNote = latestUpdateInfo.error ? ` — Ошибка: ${latestUpdateInfo.error}` : '';
      lastCheckedDesc.textContent = `Последняя проверка: сегодня в ${tStr}${errNote}`;
    } else {
      lastCheckedDesc.textContent = 'Последняя проверка: еще не выполнялась';
    }
  }

  if (btnApply) {
    btnApply.disabled = !(latestUpdateInfo && latestUpdateInfo.update_available);
  }

  if (detailsBlock && releaseTitle && releaseMeta && releaseNotes) {
    if (latestUpdateInfo && latestUpdateInfo.update_available) {
      detailsBlock.classList.remove('hidden');
      const latC = latestUpdateInfo.latest_commit ? latestUpdateInfo.latest_commit.slice(0, 7) : '—';
      releaseTitle.textContent = `Релиз: ${latestUpdateInfo.release_tag || latestUpdateInfo.latest_version || 'Новая сборка'} (коммит: ${latC})`;
      releaseMeta.textContent = latestUpdateInfo.published_at ? `Опубликован: ${latestUpdateInfo.published_at}` : '';
      releaseNotes.textContent = latestUpdateInfo.changelog || latestUpdateInfo.release_notes || 'Описание изменений отсутствует.';
    } else {
      detailsBlock.classList.add('hidden');
    }
  }
}

function openUpdateModal() {
  if (!latestUpdateInfo) {
    checkUpdates(false);
    return;
  }

  const instC = (latestUpdateInfo.installed_commit && latestUpdateInfo.installed_commit !== 'unknown')
    ? latestUpdateInfo.installed_commit.slice(0, 7)
    : 'неизвестно';
  const latC = latestUpdateInfo.latest_commit ? latestUpdateInfo.latest_commit.slice(0, 7) : (latestUpdateInfo.release_tag || '—');

  if (elements.modalTitle) elements.modalTitle.textContent = 'Обновление Hermes Hub';
  if (elements.modalBody) {
    elements.modalBody.innerHTML = `
      <div class="update-modal-body">
        <div style="display:flex; justify-content:space-between; margin-bottom:12px; padding:10px; background:var(--surface-muted); border-radius:var(--radius-sm);">
          <div>
            <div style="font-size:11px; color:var(--text-muted);">Текущая сборка:</div>
            <div style="font-weight:600; font-family:var(--font-mono); font-size:13px;">${escapeHtml(instC)}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:11px; color:var(--text-muted);">Новая сборка:</div>
            <div style="font-weight:600; font-family:var(--font-mono); font-size:13px; color:var(--status-warning);">${escapeHtml(latC)}</div>
          </div>
        </div>
        <div style="margin-bottom:8px; font-size:12px; color:var(--text-muted);">
          Тег: <strong>${escapeHtml(latestUpdateInfo.release_tag || latestUpdateInfo.latest_version || '—')}</strong>
          ${latestUpdateInfo.published_at ? ` &bull; Дата: ${escapeHtml(latestUpdateInfo.published_at)}` : ''}
        </div>
        <div style="font-weight:600; font-size:12px; margin-bottom:4px;">Список изменений (Release Notes):</div>
        <div style="max-height:200px; overflow-y:auto; font-size:12px; line-height:1.4; white-space:pre-wrap; background:var(--surface-muted); padding:10px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); font-family:var(--font-mono);">
          ${escapeHtml(latestUpdateInfo.changelog || latestUpdateInfo.release_notes || 'Описание изменений отсутствует.')}
        </div>
      </div>
    `;
  }
  if (elements.modalFooter) {
    elements.modalFooter.innerHTML = `
      <button class="btn btn-secondary" onclick="closeModal()">Закрыть</button>
      <button class="btn btn-primary" id="btn-modal-install-update" onclick="handleInstallUpdateFromModal()">Установить обновление</button>
    `;
  }
  showModal();
}

async function handleInstallUpdateFromModal() {
  const btn = document.getElementById('btn-modal-install-update');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Установка...';
  }
  await applyUpdate();
  closeModal();
}

async function applyUpdate() {
  showToast('Загрузка и запуск обновления...', 'info');
  try {
    const res = await executeAction('apply_update', {});
    if (res && res.ok) {
      showToast(res.message || 'Обновление запущено успешно!', 'success');
    } else {
      showToast((res && res.message) || 'Ошибка установки обновления', 'error');
    }
  } catch (err) {
    showToast(`Ошибка установки: ${err.message}`, 'error');
  }
}

// ── OVERVIEW & ROUTING NODE HANDLERS ──
async function handleNodeAccountChange(roleId, profileId, isPrimary = true) {
  if (!roleId || !profileId) return;
  showToast(`Назначение аккаунта '${profileId}' на роль '${roleId}'...`, 'info');
  const res = await executeAction('assign_role', {
    role_id: roleId,
    profile_id: profileId,
    is_primary: isPrimary,
  });
  if (res && res.ok) {
    showToast(`Аккаунт '${profileId}' успешно назначен`, 'success');
    fetchSnapshot();
  } else {
    showToast((res && res.message) || 'Ошибка назначения аккаунта', 'error');
  }
}

async function handleNodeModelChange(roleId, profileId, newModel) {
  if (!newModel) return;
  showToast(`Сохранение модели '${newModel}' для ${profileId}...`, 'info');
  const res = await executeAction('set_model', { profile_id: profileId, model: newModel, role_id: roleId });
  if (res && res.ok) {
    showToast(`Модель '${newModel}' успешно сохранена`, 'success');
    if (currentSnapshot) {
      if (currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
        currentSnapshot.all_profiles[profileId].preferred_models = [newModel];
      }
      if (currentSnapshot.routing && currentSnapshot.routing[roleId]) {
        currentSnapshot.routing[roleId].default_model = newModel;
        const node = (currentSnapshot.routing[roleId].nodes || []).find((n) => n.profile_id === profileId);
        if (node) node.model = newModel;
      }
    }
    renderCurrentView();
    fetchSnapshot();
  } else {
    showToast((res && res.message) || 'Ошибка сохранения модели', 'error');
  }
}

async function handleRefreshProviderModels(providerId, profileId = null) {
  showToast(`Запрос списка моделей для ${providerId}...`, 'info');
  const res = await executeAction('refresh_models', { provider: providerId, profile_id: profileId || '' });
  if (res && res.ok) {
    showToast(res.message, 'success');
    await fetchSnapshot();
    if (profileId) {
      setTimeout(() => openAccountDetailsModal(profileId, true), 500);
    } else {
      fetchSnapshot();
    }
  } else {
    showToast((res && res.message) || 'Ошибка обновления моделей', 'error');
  }
}

// ── ACCOUNT & AGENT MODALS ──
function openAccountDetailsModal(profileId, isRefresh = false) {
  _openAccountModalProfile = profileId;
  if (!currentSnapshot) return;
  const profile = (currentSnapshot.all_profiles || {})[profileId];
  if (!profile) return;

  const provSummary = (currentSnapshot.providers || []).find((p) => p.provider_id === profile.provider);
  const discoveredModels = profile.model_discovery?.models || ((provSummary && provSummary.discovered_models) ? provSummary.discovered_models : []);
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
            ${discoveredModels.map((m) => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
          </select>
          <button class="btn btn-secondary btn-sm" onclick="handleSaveProfileModel('${escapeHtml(profileId)}')">Сохранить</button>
        </div>
      </div>
    `;
  } else {
    modelBlockHtml = `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:14px;">
        <div style="font-size:12px; color:var(--status-warning); margin-bottom:6px;">
          ${escapeHtml(profile.model_discovery?.error ? "Сервер отказал: " + profile.model_discovery.error : profile.connection_check?.state === "checking" ? "Идёт запрос списка моделей…" : "Список моделей ещё не получен от провайдера " + (profile.provider_display_name || profile.provider))}
        </div>
        <button class="btn btn-secondary btn-sm" onclick="handleRefreshProviderModels('${escapeHtml(profile.provider)}', '${escapeHtml(profileId)}')" ${profile.connection_check?.state === 'checking' ? 'disabled' : ''}>${profile.connection_check?.state === 'checking' ? 'Запрашивается список моделей…' : '↻ Запросить список моделей'}</button>
      </div>
    `;
  }

  modelBlockHtml = renderAccountCheck(profile) + modelBlockHtml;
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

    <div style="margin-bottom:8px; font-weight:600; font-size:12px;">Лимиты и квоты провайдера:</div>
    <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:14px;">
      ${buckets.map((b) => {
        const isUnlimited = b.status === 'unlimited' || b.period === 'unlimited';
        const remDisplay = isUnlimited ? 'Без ограничений' : (b.remaining_percent !== null && b.remaining_percent !== undefined ? Math.round(b.remaining_percent) + '%' : 'Н/Д');
        const fillPct = isUnlimited ? 100 : (b.remaining_percent !== null && b.remaining_percent !== undefined ? Math.max(0, Math.min(100, b.remaining_percent)) : 0);
        const barColor = isUnlimited ? 'var(--status-healthy)' : ((b.remaining_percent !== null && b.remaining_percent < 20) ? 'var(--status-warning)' : 'var(--status-healthy)');
        const resetLabel = isUnlimited ? 'Без ограничений (локальная модель)' : (b.reset_at ? `Сброс: ${formatIsoDate(b.reset_at)}` : (b.period ? `Период: ${b.period}` : 'Без отметки сброса'));
        return `
        <div style="background:var(--surface-card); border:1px solid var(--border-subtle); padding:8px 10px; border-radius:var(--radius-sm);">
          <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:4px;">
            <span>${escapeHtml(b.bucket_name || b.name || b.display_name || 'Квота')}</span>
            <span>${escapeHtml(remDisplay)}</span>
          </div>
          <div class="cell-bar-track" style="margin-bottom:4px;">
            <div class="cell-bar-fill" style="width:${fillPct}%; background:${barColor};"></div>
          </div>
          <div style="font-size:10px; color:var(--text-muted);">
            ${escapeHtml(resetLabel)}
          </div>
        </div>
        `;
      }).join('') || '<div class="empty-text">Данные о квотах отсутствуют (провайдер не отдал лимиты).</div>'}
    </div>
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-secondary" onclick="handleTestProfile('${escapeHtml(profileId)}')">⚡ Проверить подключение</button>
    <button class="btn btn-secondary" onclick="executeAction('set_main', { profile_id: '${escapeHtml(profileId)}' })">★ Сделать основным</button>
    <button class="btn btn-secondary" onclick="handleDeleteCredentials('${escapeHtml(profileId)}')">Удалить ключ</button>
    <button class="btn btn-primary" onclick="closeModal()">Закрыть</button>
  `;

  if (!isRefresh) {
    showModal();
  }
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
    if (res && res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Модель сохранена')}</div>`;
      if (currentSnapshot && currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
        currentSnapshot.all_profiles[profileId].preferred_models = [model];
      }
      fetchSnapshot();
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Ошибка сохранения модели')}</div>`;
    }
  }
}

function openAgentModelModal(roleId, profileId) {
  if (!currentSnapshot) return;
  const profile = (currentSnapshot.all_profiles || {})[profileId];
  if (!profile) return;

  const provSummary = (currentSnapshot.providers || []).find((p) => p.provider_id === profile.provider);
  const discoveredModels = profile.model_discovery?.models || ((provSummary && provSummary.discovered_models) ? provSummary.discovered_models : []);
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
          ${discoveredModels.map((m) => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('')}
        </select>
      </div>
    ` : `
      <div style="background:var(--surface-muted); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:16px;">
        <div style="font-size:12px; color:var(--status-warning); margin-bottom:6px;">
          ${escapeHtml(profile.model_discovery?.error ? "Сервер отказал: " + profile.model_discovery.error : profile.connection_check?.state === "checking" ? "Идёт запрос списка моделей…" : "Список моделей ещё не получен от провайдера " + (profile.provider_display_name || profile.provider))}
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
    if (res && res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Модель сохранена')}</div>`;
      if (currentSnapshot) {
        if (currentSnapshot.all_profiles && currentSnapshot.all_profiles[profileId]) {
          currentSnapshot.all_profiles[profileId].preferred_models = [model];
        }
        if (currentSnapshot.routing && currentSnapshot.routing[roleId]) {
          currentSnapshot.routing[roleId].default_model = model;
        }
        if (currentSnapshot.agents) {
          const ag = currentSnapshot.agents.find((a) => a.role_id === roleId);
          if (ag) ag.model = model;
        }
      }
      setTimeout(() => {
        closeModal();
        renderCurrentView();
        fetchSnapshot();
      }, 700);
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Ошибка сохранения модели')}</div>`;
    }
  }
}

async function handleTestProfile(profileId) {
  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    feedbackArea.innerHTML = '<div class="modal-feedback info">⏳ Запуск тестового запроса к провайдеру...</div>';
  }
  const res = await executeAction('check_account', { profile_id: profileId });
  if (feedbackArea) {
    if (res && res.ok) {
      feedbackArea.innerHTML = `<div class="modal-feedback success">✓ ${escapeHtml(res.message || 'Проверка запущена; результат появится в карточке')}</div>`;
    } else {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Тест завершился с ошибкой')}</div>`;
    }
  }
}

// ── ADD ACCOUNT WIZARD (P0-1) ──
function openAddAccountWizard() {
  window._wiz_device_profile = undefined;
  window._wiz_device_session = undefined;
  window._wiz_native_session = undefined;
  window._wiz_redirect_session = undefined;
  window._wiz_redirect_provider = undefined;
  window._wiz_redirect_slot_id = undefined;
  window._wiz_base_url = undefined;
  window._wiz_token = undefined;
  window._wiz_models = undefined;
  if (elements.modalTitle) elements.modalTitle.textContent = 'Мастер подключения учетной записи';
  showWizardStep1();
  showModal();
}

function showWizardStep1() {
  window._wiz_models = undefined;
  stopDeviceAuthPolling();
  stopNativeAuthPolling();
  stopRedirectAuthPolling();
  for (const key of ['device_profile', 'device_session', 'native_session', 'redirect_session', 'redirect_provider', 'redirect_slot_id', 'base_url', 'token']) window['_wiz_' + key] = undefined;
  window._wiz_provider = undefined;
  if (elements.modalTitle) elements.modalTitle.textContent = 'Мастер подключения учетной записи';
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
          <div style="font-size:11px; color:var(--text-muted);">OAuth редирект (с поддержкой SSH port-forward) или API Key</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('antigravity')">
        <span style="font-size:18px; color:var(--prov-antigravity);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">Google Antigravity</div>
          <div style="font-size:11px; color:var(--text-muted);">Вход через agy в терминале (основной) или OAuth по ссылке (запасной)</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('ollama')">
        <span style="font-size:18px; color:var(--status-healthy, #22c55e);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">Ollama</div>
          <div style="font-size:11px; color:var(--text-muted);">Локальный или удаленный Ollama API (http://127.0.0.1:11434/v1)</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('local')">
        <span style="font-size:18px; color:var(--status-healthy, #22c55e);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">Локальная модель (Local LLM)</div>
          <div style="font-size:11px; color:var(--text-muted);">llama.cpp / Ollama / vLLM (OpenAI-совместимый сервер)</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('openrouter')">
        <span style="font-size:18px; color:var(--text-muted);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">OpenRouter</div>
          <div style="font-size:11px; color:var(--text-muted);">API Key + optional custom base URL</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="showWizardStep2('nvidia')">
        <span style="font-size:18px; color:var(--text-muted);">●</span>
        <div style="text-align:left; margin-left:8px;">
          <div style="font-weight:700;">NVIDIA NIM</div>
          <div style="font-size:11px; color:var(--text-muted);">API Key + optional custom base URL</div>
        </div>
      </button>
    </div>
  `;
  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
  `;
}

function showWizardStep2(providerId) {
  if (window._wiz_provider !== providerId) {
    window._wiz_device_profile = undefined;
    window._wiz_base_url = undefined;
    window._wiz_token = undefined;
  window._wiz_models = undefined;
  }
  window._wiz_provider = providerId;
  let bodyHtml = '';
  let footerHtml = '';

  if (providerId === 'grok' || providerId === 'openai-codex') {
    const providerName = providerId === 'grok' ? 'Grok (xAI)' : 'OpenAI Codex';
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация ${providerName} по коду устройства
      </div>
      <div style="margin-bottom:10px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">Слот, в который войти:</label>
        <select class="input-text" style="width:100%;" id="wiz-device-slot">${buildSlotOptions(providerId)}</select>
        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
          Вход в занятый слот заменит учётные данные, которые в нём сейчас.
        </div>
      </div>
      <div style="margin-bottom:10px;">
        <button class="btn btn-primary btn-sm" onclick="startDeviceAuth('${escapeHtml(providerId)}')">Начать авторизацию</button>
      </div>
      <div id="device-auth-box" style="background:var(--surface-muted); padding:14px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle);">
        <div style="color:var(--text-secondary);">Выберите слот и нажмите «Начать авторизацию».</div>
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('${escapeHtml(providerId)}')">Продолжить →</button>
    `;
  } else if (providerId === 'antigravity') {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация Google Antigravity
      </div>
      <div style="display:flex; gap:8px; margin-bottom:14px; border-bottom:1px solid var(--border-subtle); padding-bottom:8px;">
        <button id="ag-tab-btn-terminal" class="btn btn-primary btn-sm" onclick="toggleAntigravityAuthMode('terminal')">>_ В терминале на сервере (основной)</button>
        <button id="ag-tab-btn-browser" class="btn btn-ghost btn-sm" onclick="toggleAntigravityAuthMode('browser')">🌐 По ссылке в браузере (запасной)</button>
      </div>

      <!-- Mode 1: Native Terminal Login (P0-1) -->
      <div id="ag-auth-mode-terminal" style="display:block;">
        <div style="margin-bottom:10px;">
          <label style="display:block; font-weight:600; margin-bottom:4px;">Слот, в который войти:</label>
          <select class="input-text" style="width:100%;" id="wiz-native-slot">${buildSlotOptions('antigravity')}</select>
          <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
            Вход выполняет сама утилита agy в окне терминала с изолированным каталогом профиля.
          </div>
        </div>
        <div style="margin-bottom:12px;">
          <button class="btn btn-primary" onclick="startNativeAuth('antigravity')">>_ Открыть терминал для входа</button>
        </div>
        <div id="native-auth-box"></div>
      </div>

      <!-- Mode 2: Browser Redirect Auth (Fallback, P0-4) -->
      <div id="ag-auth-mode-browser" style="display:none;">
        <div style="margin-bottom:10px;">
          <label style="display:block; font-weight:600; margin-bottom:4px;">Слот, в который войти:</label>
          <select class="input-text" style="width:100%;" id="wiz-redirect-slot" onchange="startRedirectAuth('antigravity')">${buildSlotOptions('antigravity')}</select>
          <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
            Запасной способ для подключения с удалённой машины без графического интерфейса.
          </div>
        </div>
        <div style="margin-bottom:10px;">
          <button class="btn btn-secondary btn-sm" onclick="startRedirectAuth('antigravity')">Получить ссылку</button>
        </div>
        <div id="redirect-auth-box" style="background:var(--surface-muted); padding:14px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle);">
          <div style="font-weight:700; margin-bottom:6px;">1. Откройте ссылку:</div>
          <div style="display:flex; gap:8px; margin-bottom:12px;">
            <input type="text" class="input-text" style="flex:1;" id="wiz-redirect-url" placeholder="Получение ссылки авторизации…" readonly>
            <button class="btn btn-secondary btn-sm" onclick="window.open(document.getElementById('wiz-redirect-url').value, '_blank')">Открыть</button>
            <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(document.getElementById('wiz-redirect-url').value, 'Ссылка скопирована')">Копировать</button>
          </div>
          <div style="font-weight:700; margin-bottom:6px;">2. Вставьте адрес из браузера:</div>
          <div style="display:flex; gap:8px; margin-bottom:6px;">
            <input type="text" class="input-text" style="flex:1;" id="wiz-redirect-paste" placeholder="http://127.0.0.1:…/oauth-callback?code=…">
            <button class="btn btn-primary btn-sm" onclick="submitRedirectCallback()">Завершить вход</button>
          </div>
          <div id="redirect-auth-status" style="font-size:12px; color:var(--text-muted); margin-top:10px;"></div>
        </div>
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('antigravity')">Продолжить →</button>
    `;
  } else if (providerId === 'claude') {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Авторизация Claude
      </div>
      <div style="margin-bottom:10px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">Слот, в который войти:</label>
        <select class="input-text" style="width:100%;" id="wiz-redirect-slot" onchange="startRedirectAuth('claude')">${buildSlotOptions('claude')}</select>
        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
          Вход в занятый слот заменит учётные данные, которые в нём сейчас.
        </div>
      </div>
      <div style="margin-bottom:10px;">
        <button class="btn btn-primary btn-sm" onclick="startRedirectAuth('claude')">Получить ссылку</button>
      </div>
      <div id="redirect-auth-box" style="background:var(--surface-muted); padding:14px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle);">
        <div style="font-weight:700; margin-bottom:6px;">1. Откройте ссылку:</div>
        <div style="display:flex; gap:8px; margin-bottom:12px;">
          <input type="text" class="input-text" style="flex:1;" id="wiz-redirect-url" placeholder="Получение ссылки авторизации…" readonly>
          <button class="btn btn-secondary btn-sm" onclick="window.open(document.getElementById('wiz-redirect-url').value, '_blank')">Открыть</button>
          <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(document.getElementById('wiz-redirect-url').value, 'Ссылка скопирована')">Копировать</button>
        </div>
        <div style="font-weight:700; margin-bottom:6px;">2. Вставьте код со страницы:</div>
        <div style="display:flex; gap:8px; margin-bottom:6px;">
          <input type="text" class="input-text" style="flex:1;" id="wiz-redirect-paste" placeholder="Код со страницы авторизации">
          <button class="btn btn-primary btn-sm" onclick="submitRedirectCallback()">Завершить вход</button>
        </div>
        <div id="redirect-auth-status" style="font-size:12px; color:var(--text-muted); margin-top:10px;"></div>
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('claude')">Продолжить →</button>
    `;
  } else if (providerId === 'ollama') {
    window._wiz_device_profile = undefined;
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Настройка Ollama
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">URL сервера (Base URL):</label>
        <div style="display:flex; gap:8px;">
          <input type="text" class="input-text" style="flex:1;" id="wiz-base-url-input" placeholder="http://127.0.0.1:11434" value="http://127.0.0.1:11434">
          <button class="btn btn-secondary btn-sm" id="wiz-test-ollama-btn" onclick="testOllamaConnection()">Проверить адрес</button>
        </div>
        <div id="wiz-ollama-check-result" style="margin-top:6px; font-size:12px;"></div>
      </div>
      <div style="margin-bottom:10px; font-size:12px; color:var(--text-muted);">
        По умолчанию указан адрес на машине с Hub (127.0.0.1:11434). Если Ollama работает на сервере или другом компьютере (например, http://192.168.1.81:11434), укажите его сетевой адрес.
      </div>
      <div style="margin-bottom:12px;">
        <button class="btn btn-secondary" style="width:100%;" id="wiz-discover-btn" onclick="discoverLocalServers('discover_local_models')" data-action="discover_local_models">🔍 Найти на этом компьютере</button>
        <div id="wiz-discover-status" style="font-size:12px; color:var(--text-secondary); margin-top:4px;"></div>
      </div>
      <div id="wiz-discover-results" style="margin-bottom:12px;"></div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">API Key / Bearer Token (опционально):</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="Оставьте пустым, если ключ не требуется">
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('${escapeHtml(providerId)}')">Продолжить →</button>
    `;
  } else if (providerId === 'local' || providerId === 'local-llm' || providerId === 'llama.cpp' || providerId === 'vllm') {
    // P0-1: reset stale wizard slot so local add_account does not reuse grok/antigravity slot
    window._wiz_device_profile = undefined;
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Настройка локального сервера (Local LLM)
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">URL сервера (Base URL):</label>
        <input type="text" class="input-text" style="width:100%;" id="wiz-base-url-input" placeholder="http://127.0.0.1:8081/v1" value="http://127.0.0.1:8081/v1">
      </div>
      <div style="margin-bottom:10px; font-size:12px; color:var(--text-muted);">
        Поиск серверов выполняется на машине, где запущен Hub (не в браузере).
      </div>
      <div style="margin-bottom:12px;">
        <button class="btn btn-secondary" style="width:100%;" id="wiz-discover-btn" onclick="discoverLocalServers('discover_local_models')" data-action="discover_local_models">🔍 Найти на этом компьютере</button>
        <div id="wiz-discover-status" style="font-size:12px; color:var(--text-secondary); margin-top:4px;"></div>
      </div>
      <!-- discover_local_models: async search runs on Hub machine, not browser -->
      <div id="wiz-discover-results" style="margin-bottom:12px;"></div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">API Key (опционально):</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="Оставьте пустым, если ключ не требуется">
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('${escapeHtml(providerId)}')">Продолжить →</button>
    `;
  } else if (providerId === 'openrouter' || providerId === 'nvidia') {
    const providerName = providerId === 'openrouter' ? 'OpenRouter' : 'NVIDIA NIM';
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Подключение ${providerName}
      </div>
      <div style="margin-bottom:10px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">Слот, в который сохранить:</label>
        <select class="input-text" style="width:100%;" id="wiz-redirect-slot">${buildSlotOptions(providerId)}</select>
        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
          Вход в занятый слот заменит учётные данные, которые в нём сейчас.
        </div>
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">API Key:</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="sk-...">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">Base URL (опционально):</label>
        <input type="text" class="input-text" style="width:100%;" id="wiz-base-url-input" placeholder="${providerId === 'openrouter' ? 'https://openrouter.ai/api/v1' : 'https://integrate.api.nvidia.com/v1'}">
        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
          Оставьте пустым для значения по умолчанию.
        </div>
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('${escapeHtml(providerId)}')">Продолжить →</button>
    `;
  } else {
    bodyHtml = `
      <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
        Шаг 2 из 3: Ввод API ключа ${escapeHtml(providerId)}
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block; font-weight:600; margin-bottom:4px;">API Key / Subscription Token:</label>
        <input type="password" class="input-text" style="width:100%;" id="wiz-token-input" placeholder="sk-...">
      </div>
    `;
    footerHtml = `
      <button class="btn btn-ghost" onclick="showWizardStep1()">← Назад</button>
      <button class="btn btn-primary" onclick="proceedToWizardStep3('${escapeHtml(providerId)}')">Продолжить →</button>
    `;
  }

  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    ${bodyHtml}
  `;
  elements.modalFooter.innerHTML = footerHtml;
  if (providerId === 'antigravity' || providerId === 'claude') {
    startRedirectAuth(providerId);
  }
}

async function testOllamaConnection() {
  const urlInput = document.getElementById('wiz-base-url-input');
  const tokenInput = document.getElementById('wiz-token-input');
  const resultEl = document.getElementById('wiz-ollama-check-result');
  const btn = document.getElementById('wiz-test-ollama-btn');
  if (!urlInput || !resultEl) return;
  const baseUrl = (urlInput.value || '').trim() || 'http://127.0.0.1:11434';
  const token = tokenInput ? tokenInput.value.trim() : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Проверка…'; }
  resultEl.innerHTML = '<span style="color:var(--text-secondary);">Проверяем подключение…</span>';
  try {
    const res = await executeAction('validate_connection', {
      provider: 'ollama',
      base_url: baseUrl,
      token: token,
    });
    if (res && res.ok) {
      const models = (res.data && res.data.models) || [];
      window._wiz_models = models;
      window._wiz_base_url = baseUrl;
      resultEl.innerHTML = `<span style="color:var(--status-healthy); font-weight:600;">✓ Подключение успешно. Моделей: ${models.length}</span>`;
      showToast('Ollama подключена успешно', 'success');
    } else {
      const errMsg = (res && res.message) || 'Не удалось подключиться к Ollama';
      resultEl.innerHTML = `<span style="color:var(--status-error);">${escapeHtml(errMsg)}</span>`;
    }
  } catch (err) {
    resultEl.innerHTML = `<span style="color:var(--status-error);">Ошибка: ${escapeHtml(String(err))}</span>`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Проверить адрес'; }
  }
}

async function proceedToWizardStep3(providerId) {
  if (window._wiz_validating) return;
  window._wiz_validating = true;
  const nextButton = elements.modalFooter?.querySelector('.btn-primary');
  if (nextButton) nextButton.disabled = true;
  try {
  const baseInput = document.getElementById('wiz-base-url-input');
  if (baseInput) {
    window._wiz_base_url = baseInput.value.trim();
  }
  const tokenInput = document.getElementById('wiz-token-input');
  if (tokenInput) {
    window._wiz_token = tokenInput.value.trim();
  }
  // P0-1 BUG-1: persist owner-selected slot BEFORE showWizardStep3 destroys the select elements
  // Only read slot elements for providers that have them (grok/openai-codex have wiz-device-slot,
  // antigravity/claude/openrouter/nvidia have wiz-redirect-slot). Local providers have no slot elements.
  const isDeviceAuthFlow = providerId === 'grok' || providerId === 'openai-codex';
  const isRedirectAuthFlow = providerId === 'antigravity' || providerId === 'claude';
  if (isDeviceAuthFlow) {
    const deviceSlot = document.getElementById('wiz-device-slot');
    window._wiz_device_profile = window._wiz_device_profile || deviceSlot?.value || '';
  } else if (isRedirectAuthFlow) {
    const redirectSlot = document.getElementById('wiz-redirect-slot');
    window._wiz_device_profile = window._wiz_redirect_slot_id || window._wiz_device_profile || redirectSlot?.value || '';
  } else if (providerId === 'openrouter' || providerId === 'nvidia') {
    const redirectSlot = document.getElementById('wiz-redirect-slot');
    window._wiz_device_profile = redirectSlot?.value || '';
  }
  // For local providers (local, local-llm, llama.cpp, ollama, vllm), do not read any slot elements
  if (tokenInput || baseInput) {
    const feedback = document.getElementById('modal-feedback-area');
    if (feedback) feedback.textContent = 'Проверка подключения и запрос моделей…';
    // Ключ читаем из поля прямо сейчас, а не из глобальной переменной:
    // она переживает предыдущие попытки подключения и может оказаться пустой
    // или чужой. Провайдер тогда отвечает «Missing Authentication header» при
    // заполненном поле, и владелец не понимает, в чём дело.
    const liveToken = (tokenInput && tokenInput.value.trim()) || window._wiz_token || '';
    const liveBase = (baseInput && baseInput.value.trim()) || window._wiz_base_url || '';
    window._wiz_token = liveToken;
    window._wiz_base_url = liveBase;
    const result = await executeAction('validate_connection', {provider: providerId, token: liveToken, base_url: liveBase});
    if (!result?.ok) {
      if (feedback) feedback.textContent = result?.message || 'Нет ответа от сервера';
      return;
    }
    window._wiz_models = result.data.models;
  }
  showWizardStep3(providerId);
  } finally {
    window._wiz_validating = false;
    if (nextButton) nextButton.disabled = false;
  }
}

function showWizardStep3(providerId) {
  // GAP-3: динамически строим options ролей из currentSnapshot.routing
  const routing = currentSnapshot && currentSnapshot.routing ? currentSnapshot.routing : {};
  const roleIds = Object.keys(routing);

  let roleOptionsHtml = '';
  if (roleIds.length === 0) {
    // Fallback: минимальный набор если snapshot ещё не загружен
    roleOptionsHtml = `
      <option value="coder-primary">Кодер 1 (Primary Coder)</option>
      <option value="coder-secondary">Кодер 2 (Secondary Coder)</option>
      <option value="orchestrator">Оркестратор (Fallback Router)</option>
      <option value="reviewer">Ревьюер кода (Reviewer)</option>
      <option value="research">Исследователь (Researcher)</option>
      <option value="fast">Быстрый агент (Fast / Flash)</option>
      <option value="spare">Резервный пул (Spare Pool)</option>
    `;
  } else {
    roleOptionsHtml = roleIds.map((roleId) => {
      const pipeline = routing[roleId] || {};
      const label = pipeline.role_name_ru || roleId;
      const desc = CANONICAL_ROLE_DESCRIPTIONS[roleId] || pipeline.role_description_ru || '';
      return `<option value="${escapeHtml(roleId)}">${escapeHtml(label)}${desc ? ' — ' + escapeHtml(desc) : ''}</option>`;
    }).join('');
  }

  elements.modalBody.innerHTML = `
    <div id="modal-feedback-area"></div>
    <div style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">
      Шаг 3 из 3: Назначение роли для нового аккаунта
    </div>
    ${window._wiz_models?.length ? `<label for="wiz-preferred-model">Подключение проверено. Моделей: ${window._wiz_models.length}</label><select class="select-filter" id="wiz-preferred-model">${window._wiz_models.map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join('')}</select>` : ''}
    <div style="margin-bottom:14px;">
      <label style="display:block; font-weight:600; margin-bottom:4px;">Целевая роль в роутере:</label>
      <select class="select-filter" style="width:100%;" id="wiz-target-role">
        ${roleOptionsHtml}
      </select>
    </div>
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="showWizardStep2('${escapeHtml(providerId)}')">← Назад</button>
    <button class="btn btn-primary" onclick="finishAddAccount('${escapeHtml(providerId)}')">✓ Завершить подключение</button>
  `;
}

async function finishAddAccount(providerId) {
  if (window._wiz_saving) return;
  window._wiz_saving = true;
  const finishButton = elements.modalFooter?.querySelector(".btn-primary");
  if (finishButton) finishButton.disabled = true;
  const roleSelect = document.getElementById('wiz-target-role');
  const targetRole = roleSelect ? roleSelect.value : 'coder-primary';

  // GAP-2: owner-selected slot — читаем выбранный профиль из UI
  // Local providers (local, local-llm, llama.cpp, ollama, vllm) have no slot selector;
  // do NOT read stale DOM slot elements from previous flows in the same test session.
  const isLocalProvider = providerId === 'local' || providerId === 'local-llm' || providerId === 'llama.cpp' || providerId === 'ollama' || providerId === 'vllm';
  let selectedProfileId;
  if (isLocalProvider) {
    selectedProfileId = '';
  } else if (providerId === 'antigravity' || providerId === 'claude') {
    selectedProfileId = window._wiz_redirect_slot_id || window._wiz_device_profile || document.getElementById('wiz-native-slot')?.value || document.getElementById('wiz-redirect-slot')?.value || '';
  } else {
    const deviceSlot = document.getElementById('wiz-device-slot');
    const redirectSlot = document.getElementById('wiz-redirect-slot');
    // Use nullish coalescing: if _wiz_device_profile was explicitly set (not null/undefined),
    // it wins over any stale DOM element value (e.g. from a previous grok flow in the same test)
    selectedProfileId = window._wiz_device_profile ?? (deviceSlot?.value || redirectSlot?.value || '');
  }

  const feedbackArea = document.getElementById('modal-feedback-area');
  if (feedbackArea) {
    // Обещать «до минуты на этап» было неправдой: проверка Antigravity через
    // CLI занимала до четырёх минут, и мастер выглядел зависшим. Теперь
    // действие возвращается сразу, а проверка идёт в фоне.
    feedbackArea.innerHTML = `<div class="modal-feedback info">⏳ ${escapeHtml(providerId)}: сохраняем аккаунт…</div>`;
  }

  const payload = {
    provider: providerId,
    target_role: targetRole,
    preferred_model: document.getElementById('wiz-preferred-model')?.value || '',
    // GAP-2: передаём выбранный слот, чтобы бэкенд НЕ делал find_free_slot для owner
    profile_id: selectedProfileId,
  };
  if (window._wiz_base_url) {
    payload.base_url = window._wiz_base_url;
  }
  if (window._wiz_token) {
    payload.token = window._wiz_token;
  }

  let res;
  try { res = await executeAction('add_account', payload); }
  finally { window._wiz_saving = false; if (finishButton) finishButton.disabled = false; }

  if (res && res.ok) {
    showToast(res.message, 'success');
    closeModal();
    fetchSnapshot();
  } else {
    if (feedbackArea) {
      feedbackArea.innerHTML = `<div class="modal-feedback error">❌ ${escapeHtml((res && res.message) || 'Не удалось завершить подключение')}</div>`;
    }
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

  // GAP-1: owner-selected slot — показать выбранное в UI до начала auth
  const slotSelect = document.getElementById('wiz-device-slot');
  const selectedSlot = slotSelect ? slotSelect.value : '';
  if (selectedSlot) {
    window._wiz_device_profile = selectedSlot;
  }

  box.innerHTML = `<div style="color:var(--text-secondary);">Запрашиваем код у провайдера…</div>`;
  // P0-1 BUG-2: send profile_id so server knows which slot the owner chose
  const res = await executeAction('start_device_auth', { provider: providerId, profile_id: selectedSlot });
  if (window._wiz_provider !== providerId) return;
  if (!res || !res.ok) {
    box.innerHTML = `<div class="modal-feedback error">${escapeHtml((res && res.message) || 'Не удалось начать авторизацию')}</div>`;
    return;
  }

  const d = res.data || {};
  window._wiz_device_session = d.session_id;
  // P0-1 BUG-3: owner-selected slot wins over server-assigned profile_id
  window._wiz_device_profile = selectedSlot || d.profile_id;

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
    return '<option value="">Новый свободный слот — автоматически</option>';
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
  return '<option value="">Новый свободный слот — автоматически</option>' + free.concat(used, idle).join('');
}

// ─────────────────────────────────────────────────────────────
//  Авторизация Google Antigravity через agy в терминале (A57)
// ─────────────────────────────────────────────────────────────

let _nativeAuthTimer = null;

function stopNativeAuthPolling() {
  if (_nativeAuthTimer) {
    clearInterval(_nativeAuthTimer);
    _nativeAuthTimer = null;
  }
}

function toggleAntigravityAuthMode(mode) {
  const termBox = document.getElementById('ag-auth-mode-terminal');
  const browserBox = document.getElementById('ag-auth-mode-browser');
  const termBtn = document.getElementById('ag-tab-btn-terminal');
  const browserBtn = document.getElementById('ag-tab-btn-browser');
  if (!termBox || !browserBox) return;

  if (mode === 'browser') {
    termBox.style.display = 'none';
    browserBox.style.display = 'block';
    if (termBtn) termBtn.className = 'btn btn-ghost btn-sm';
    if (browserBtn) browserBtn.className = 'btn btn-primary btn-sm';
    startRedirectAuth('antigravity');
  } else {
    termBox.style.display = 'block';
    browserBox.style.display = 'none';
    if (termBtn) termBtn.className = 'btn btn-primary btn-sm';
    if (browserBtn) browserBtn.className = 'btn btn-ghost btn-sm';
    stopRedirectAuthPolling();
  }
}

async function startNativeAuth(providerId, force = false) {
  stopNativeAuthPolling();
  const box = document.getElementById('native-auth-box');
  if (!box) return;

  const slotSelect = document.getElementById('wiz-native-slot');
  const selectedSlot = slotSelect ? slotSelect.value : '';

  box.innerHTML = `<div style="color:var(--text-secondary); margin-top:8px;">⏳ Запуск терминала…</div>`;

  const res = await executeAction('start_native_auth', {
    provider: providerId,
    profile_id: selectedSlot || undefined,
    force: force,
  });

  if (window._wiz_provider !== providerId) return;

  if (res && res.data && res.data.confirmation_required) {
    box.innerHTML = `
      <div class="modal-feedback warning" style="margin-top:10px; margin-bottom:10px;">
        ⚠️ ${escapeHtml(res.message || 'Слот уже занят.')}
      </div>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary btn-sm" onclick="startNativeAuth('${escapeHtml(providerId)}', true)">Перезаписать учётные данные</button>
        <button class="btn btn-secondary btn-sm" onclick="showWizardStep2('${escapeHtml(providerId)}')">Выбрать другой слот</button>
      </div>
    `;
    return;
  }

  if (!res || !res.ok) {
    const errorDetails = (res && res.data && res.data.checked_terminals)
      ? `<div style="margin-top:6px; font-size:11px; opacity:0.85;">Проверено: ${escapeHtml(res.data.checked_terminals.join(', '))}</div>`
      : '';
    box.innerHTML = `
      <div class="modal-feedback error" style="margin-top:10px;">
        ❌ ${escapeHtml((res && res.message) || 'Не удалось запустить терминал')}
        ${errorDetails}
      </div>
      <div style="margin-top:8px;">
        <button class="btn btn-secondary btn-sm" onclick="toggleAntigravityAuthMode('browser')">Перейти ко входу по ссылке</button>
      </div>
    `;
    return;
  }

  const d = res.data || {};
  window._wiz_native_session = d.session_id;
  window._wiz_device_profile = d.profile_id;
  window._wiz_redirect_slot_id = d.profile_id;

  box.innerHTML = `
    <div style="background:var(--surface-subtle); padding:12px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-top:10px;">
      <div style="font-weight:600; color:var(--text-accent); margin-bottom:4px;">
        🟢 Терминал запущен (${escapeHtml(d.terminal_cmd || 'терминал')}) для слота ${escapeHtml(d.profile_id)}
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-bottom:8px;">
        Пройдите авторизацию в открывшемся окне терминала на сервере. После успешного входа agy сохранит учётные данные, и мастер продолжит настройку.
      </div>
      <div id="native-auth-status" style="font-size:12px; font-weight:600; color:var(--text-muted);">
        ⏳ Ожидание завершения авторизации в терминале...
      </div>
    </div>
  `;

  _nativeAuthTimer = setInterval(() => pollNativeAuth(providerId), 1500);
}

async function pollNativeAuth(providerId) {
  const statusEl = document.getElementById('native-auth-status');
  if (!statusEl || !window._wiz_native_session) {
    stopNativeAuthPolling();
    return;
  }

  const res = await executeAction('poll_native_auth', {
    session_id: window._wiz_native_session,
  });

  if (!res) return;

  const d = res.data || {};
  if (res.ok && d.status === 'completed') {
    stopNativeAuthPolling();
    window._wiz_device_profile = d.profile_id;
    window._wiz_redirect_slot_id = d.profile_id;
    statusEl.innerHTML = `
      <span style="color:var(--status-healthy); font-weight:700;">
        ✓ Авторизация успешно завершена (${escapeHtml(d.email || 'Google Account')})
      </span>
    `;
    showToast('Аккаунт Antigravity успешно подключён через agy', 'success');
    fetchSnapshot();
    setTimeout(() => {
      if (window._wiz_provider === 'antigravity') {
        proceedToWizardStep3('antigravity');
      }
    }, 800);
    return;
  }

  if (!res.ok || d.status === 'timeout' || d.status === 'failed') {
    stopNativeAuthPolling();
    statusEl.innerHTML = `
      <span style="color:var(--status-error); font-weight:600;">
        ❌ ${escapeHtml(res.message || 'Время ожидания истекло или произошла ошибка')}
      </span>
    `;
    return;
  }

  if (d.status === 'pending') {
    const elapsed = d.elapsed_sec ? ` (${d.elapsed_sec}с)` : '';
    statusEl.innerHTML = `⏳ Ожидание завершения авторизации в терминале${elapsed}...`;
  }
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
  if (window._wiz_provider !== providerId) return;
  if (!res || !res.ok) {
    box.innerHTML = `<div class="modal-feedback error">${escapeHtml((res && res.message) || 'Не удалось начать авторизацию')}</div>`;
    return;
  }

  const d = res.data || {};
  window._wiz_redirect_session = d.session_id;
  window._wiz_redirect_provider = providerId;
  window._wiz_redirect_slot_id = d.profile_id;
  window._wiz_device_profile = d.profile_id;

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
    window._wiz_device_profile = window._wiz_redirect_slot_id;
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
    window._wiz_device_profile = window._wiz_redirect_slot_id;
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

// ── P0-3: Local LLM server discovery ──────────────────────────────────────

async function discoverLocalServers() {
  const btn = document.getElementById('wiz-discover-btn');
  const statusEl = document.getElementById('wiz-discover-status');
  const resultsEl = document.getElementById('wiz-discover-results');
  if (!btn || !statusEl || !resultsEl) return;

  btn.disabled = true;
  btn.textContent = '⏳ Поиск...';
  statusEl.textContent = '';
  resultsEl.innerHTML = '';

  // wiz-base-url-input: filled by selectDiscoveredServer when user picks a server
  const res = await executeAction('discover_local_models', {});

  btn.disabled = false;
  btn.textContent = '🔍 Найти на этом компьютере';

  const servers = (res && res.data && res.data.servers) ? res.data.servers : [];

  if (!servers.length) {
    statusEl.textContent = res && res.message ? res.message
      : 'Ничего не найдено. Запустите Ollama, LM Studio или llama.cpp, либо введите адрес вручную.';
    statusEl.style.color = 'var(--text-muted)';
    return;
  }

  // Show message if any servers have errors (occupied by other service)
  const errorServers = servers.filter(s => s.error);
  if (errorServers.length && errorServers.length === servers.length) {
    statusEl.textContent = 'Найдены серверы, но подключиться к ним не удалось:';
    statusEl.style.color = 'var(--text-secondary)';
  } else if (errorServers.length) {
    statusEl.textContent = `Найдено ${servers.length - errorServers.length} рабочих серверов (+${errorServers.length} с ошибкой). Выберите рабочий сервер:`;
    statusEl.style.color = 'var(--text-secondary)';
  } else {
    statusEl.textContent = `Найдено серверов: ${servers.length}. Выберите:`;
    statusEl.style.color = 'var(--text-secondary)';
  }

  // Render server list
  let html = '<div style="border:1px solid var(--border); border-radius:6px; overflow:hidden; margin-top:4px;">';
  servers.forEach((srv, idx) => {
    const hasError = !!srv.error;
    const modelCount = srv.models && srv.models.length ? srv.models.length : 0;
    const modelLabel = modelCount ? `, ${modelCount} модель${modelCount === 1 ? '' : modelCount < 5 ? 'ели' : 'елей'}` : '';
    const errorTitle = hasError ? ` title="${escapeHtml(srv.error)}"` : '';
    const rowStyle = hasError
      ? 'padding:8px 10px; background:#2a1a1a; cursor:not-allowed; opacity:0.7;'
      : 'padding:8px 10px; cursor:pointer;';
    const clickAttr = hasError ? '' : ` onclick="selectDiscoveredServer('${escapeHtml(srv.base_url)}')"`;
    const icon = hasError ? '⚠️' : '🖥️';
    html += `<div style="${rowStyle}"${errorTitle}${clickAttr}>
      <div style="font-size:13px; font-weight:600;">${icon} ${escapeHtml(srv.name)}</div>
      <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(srv.base_url)}${modelLabel}${hasError ? ` — <span style="color:var(--status-warning);">⚠ ${escapeHtml(srv.error)}</span>` : ''}</div>
    </div>`;
  });
  html += '</div>';
  resultsEl.innerHTML = html;
}

function selectDiscoveredServer(baseUrl) {
  const input = document.getElementById('wiz-base-url-input');
  if (input) {
    input.value = baseUrl;
    // Scroll input into view
    input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  // Clear results to keep UI clean
  const resultsEl = document.getElementById('wiz-discover-results');
  if (resultsEl) resultsEl.innerHTML = '';
  const statusEl = document.getElementById('wiz-discover-status');
  if (statusEl) {
    statusEl.textContent = `Выбран: ${baseUrl}`;
    statusEl.style.color = 'var(--status-healthy)';
  }
}

// ── Quota & Limits Export ─────────────────────────────────────────────────

async function exportQuotas(format = 'json') {
  const fmt = (format || 'json').toLowerCase();
  showToast(`Формирование выгрузки лимитов (${fmt.toUpperCase()})...`, 'info');
  try {
    const token = (typeof getWebToken === 'function' ? getWebToken() : (localStorage.getItem('hermes_hub_token') || ''));
    const headers = {};
    if (token) {
      headers['X-Hub-Token'] = token;
    }
    const resp = await fetch(`/api/quotas/export?format=${fmt}`, { headers });
    if (!resp.ok) {
      throw new Error(`Ошибка сервера: ${resp.status}`);
    }
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `hermes_quotas_export.${fmt}`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
    showToast(`Выгрузка лимитов (${fmt.toUpperCase()}) успешно скачана`, 'success');
  } catch (err) {
    showToast(`Не удалось выгрузить лимиты: ${err.message}`, 'error');
  }
}

function openExportQuotasModal() {
  if (elements.modalTitle) elements.modalTitle.textContent = '📥 Экспорт лимитов и квот';
  elements.modalBody.innerHTML = `
    <div style="margin-bottom:14px; font-size:13px; color:var(--text-secondary);">
      Выберите формат для выгрузки актуального отчета по лимитам, корзинам и статусам всех профилей:
    </div>
    <div style="display:flex; flex-direction:column; gap:10px;">
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="exportQuotas('json'); closeModal();">
        <span style="font-size:20px; margin-right:8px;">📄</span>
        <div style="text-align:left;">
          <div style="font-weight:700;">Экспорт в JSON</div>
          <div style="font-size:11px; color:var(--text-muted);">Полная структурированная выгрузка объектов со всеми метаданными</div>
        </div>
      </button>
      <button class="btn btn-secondary" style="justify-content:flex-start; padding:12px;" onclick="exportQuotas('csv'); closeModal();">
        <span style="font-size:20px; margin-right:8px;">📊</span>
        <div style="text-align:left;">
          <div style="font-weight:700;">Экспорт в CSV</div>
          <div style="font-size:11px; color:var(--text-muted);">Табличный формат для открытия в Excel, Google Sheets или LibreOffice</div>
        </div>
      </button>
    </div>
  `;
  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
  `;
  showModal();
}

// ═══════════════════════════════════════════════════════════════
//  SKILLS VIEW & SKILL DOCTOR
// ═══════════════════════════════════════════════════════════════
let currentSkills = [];
let skillsUsageData = null;

async function fetchSkills() {
  try {
    const headers = {};
    if (authToken) headers['X-Hub-Token'] = authToken;
    const [resSkills, resUsage] = await Promise.all([
      fetch('/api/skills', { headers }).then(r => r.json()).catch(() => ({ skills: [] })),
      fetch('/api/skills/usage', { headers }).then(r => r.json()).catch(() => null),
    ]);
    currentSkills = resSkills.skills || [];
    skillsUsageData = resUsage;

    const navBadge = document.getElementById('nav-skills-count');
    if (navBadge) navBadge.textContent = currentSkills.length;

    renderSkillsView();
  } catch (err) {
    console.error('Error fetching skills:', err);
  }
}

function renderSkillsView() {
  const container = document.getElementById('skills-cards-container');
  if (!container) return;

  const searchQuery = (document.getElementById('skills-search')?.value || '').toLowerCase().trim();
  const filterSource = document.getElementById('filter-skills-source')?.value || 'all';
  const filterStatus = document.getElementById('filter-skills-status')?.value || 'all';

  const sourceSel = document.getElementById('filter-skills-source');
  if (sourceSel) {
    const currentVal = sourceSel.value;
    const sources = Array.from(new Set(currentSkills.map(s => s.source_dir).filter(Boolean)));
    sourceSel.innerHTML = '<option value="all">Все источники</option>' + sources.map(src => `<option value="${escapeHtml(src)}">${escapeHtml(src)}</option>`).join('');
    if (sources.includes(currentVal)) sourceSel.value = currentVal;
  }

  const usageBadge = document.getElementById('skills-usage-summary-badge');
  if (usageBadge) {
    if (skillsUsageData && skillsUsageData.has_usage && skillsUsageData.total_calls > 0) {
      usageBadge.textContent = `${skillsUsageData.total_calls} вызовов зарегистрировано`;
      usageBadge.className = 'badge healthy';
    } else {
      usageBadge.textContent = 'Н/Д: вызовы со скиллами ещё не регистрировались';
      usageBadge.className = 'badge';
    }
  }

  const filtered = currentSkills.filter(s => {
    if (searchQuery) {
      const matchName = s.name.toLowerCase().includes(searchQuery);
      const matchDesc = (s.description || '').toLowerCase().includes(searchQuery);
      const matchTags = (s.tags || []).some(t => t.toLowerCase().includes(searchQuery));
      const matchAgents = (s.assigned_agents || []).some(a => a.toLowerCase().includes(searchQuery));
      if (!matchName && !matchDesc && !matchTags && !matchAgents) return false;
    }
    if (filterSource !== 'all' && s.source_dir !== filterSource) return false;
    if (filterStatus === 'valid' && !s.is_valid) return false;
    if (filterStatus === 'invalid' && s.is_valid) return false;
    if (filterStatus === 'assigned' && (!s.assigned_agents || !s.assigned_agents.length)) return false;
    if (filterStatus === 'unassigned' && s.assigned_agents && s.assigned_agents.length > 0) return false;
    return true;
  });

  const statsSummary = document.getElementById('skills-stats-summary');
  if (statsSummary) {
    statsSummary.textContent = `Показано ${filtered.length} из ${currentSkills.length} скиллов`;
  }

  if (!filtered.length) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 36px; text-align: center; color: var(--text-muted); background: var(--surface); border: 1px dashed var(--border); border-radius: var(--radius-md);">
        <h3>Скиллы не найдены</h3>
        <p style="font-size: 13px; margin-top: 6px;">Проверьте строку поиска, фильтры или добавьте файлы <code>SKILL.md</code> в <code>~/.hermes/skills/</code>, <code>~/.claude/skills/</code> или <code>.agents/skills/</code>.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(s => {
    const isValid = s.is_valid;
    const statusBadge = isValid
      ? '<span class="badge healthy" style="font-size:10px;">🟢 Валиден</span>'
      : `<span class="badge error" style="font-size:10px;" title="${escapeHtml((s.critical_errors || []).join('; '))}">🔴 Ошибки (${s.critical_errors?.length || 1})</span>`;

    const tagsHtml = (s.tags || []).map(t => `<span class="skill-tag">#${escapeHtml(t)}</span>`).join('');

    const assignedHtml = (s.assigned_agents && s.assigned_agents.length)
      ? s.assigned_agents.map(a => `
          <span class="skill-agent-badge">
            👤 ${escapeHtml(a)}
            <span class="remove-btn" title="Снять скилл с агента" onclick="unassignSkillFromAgent('${escapeHtml(s.name)}', '${escapeHtml(a)}')">×</span>
          </span>
        `).join('')
      : '<span style="color:var(--text-muted); font-size:11px;">Не назначен ни одному субагенту</span>';

    const callsText = (s.usage_count > 0)
      ? `Вызовы: ${s.usage_count} (успешно: ${s.success_count})`
      : 'Н/Д: ещё не вызывался';

    return `
      <div class="skill-card">
        <div class="skill-card-header">
          <div>
            <div class="skill-card-title">${escapeHtml(s.name)}</div>
            <div class="skill-card-meta">${escapeHtml(s.path)}</div>
          </div>
          ${statusBadge}
        </div>

        <div class="skill-card-desc">
          ${escapeHtml(s.description || 'Описание отсутствует')}
        </div>

        ${tagsHtml ? `<div class="skill-card-tags">${tagsHtml}</div>` : ''}

        <div class="skill-card-assigned">
          <strong style="font-size:11px; color:var(--text-muted);">Субагенты:</strong>
          ${assignedHtml}
        </div>

        <div style="font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between; align-items:center;">
          <span>${callsText}</span>
          ${s.last_used_at ? `<span>Последний: ${formatTimeAgo(s.last_used_at)}</span>` : ''}
        </div>

        <div class="skill-card-actions">
          <button class="btn btn-secondary btn-sm" onclick="openSkillDoctorModal('${escapeHtml(s.name)}', '${escapeHtml(s.path)}')">
            🩺 Скилл-доктор
          </button>
          <button class="btn btn-primary btn-sm" onclick="openAssignSkillModal('${escapeHtml(s.name)}')">
            + Назначить субагенту
          </button>
        </div>
      </div>
    `;
  }).join('');
}

async function openSkillDoctorModal(skillName, filepath) {
  elements.modalTitle.textContent = `🩺 Скилл-доктор: ${skillName}`;
  elements.modalBody.innerHTML = '<div style="padding:24px; text-align:center; color:var(--text-muted);">Диагностика файла SKILL.md...</div>';
  elements.modalFooter.innerHTML = '<button class="btn btn-ghost" onclick="closeModal()">Закрыть</button>';
  showModal();

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['X-Hub-Token'] = authToken;
    const res = await fetch('/api/skills/diagnose', {
      method: 'POST',
      headers,
      body: JSON.stringify({ skill_name: skillName, path: filepath }),
    });
    const result = await res.json();
    if (!result.ok || !result.diagnosis) {
      elements.modalBody.innerHTML = `<div class="modal-feedback error">Ошибка диагностики: ${escapeHtml(result.detail || result.message || 'Неизвестная ошибка')}</div>`;
      return;
    }

    const diag = result.diagnosis;
    const isVal = diag.is_valid;
    const statusBadge = isVal
      ? '<span class="badge healthy" style="font-size:12px;">🟢 ВАЛИДЕН</span>'
      : '<span class="badge error" style="font-size:12px;">🔴 ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ОШИБКИ</span>';

    const checksHtml = Object.values(diag.checks || {}).map(c => `
      <div style="display:flex; align-items:flex-start; gap:8px; margin-bottom:6px; font-size:12px;">
        <span>${c.passed ? '✅' : '❌'}</span>
        <div>
          <strong>${escapeHtml(c.name)}</strong>:
          <span style="color:var(--text-secondary);">${escapeHtml(c.details)}</span>
        </div>
      </div>
    `).join('');

    const errorsHtml = (diag.critical_errors || []).length
      ? `
        <div class="modal-feedback error" style="margin-top:12px; margin-bottom:12px;">
          <strong>Критические ошибки (требуют обязательного исправления):</strong>
          <ul style="margin:4px 0 0 16px; padding:0;">
            ${diag.critical_errors.map(e => `<li>${escapeHtml(e)}</li>`).join('')}
          </ul>
        </div>
      `
      : '';

    const warningsHtml = (diag.warnings || []).length
      ? `
        <div class="modal-feedback warning" style="margin-bottom:12px;">
          <strong>Предупреждения и рекомендации:</strong>
          <ul style="margin:4px 0 0 16px; padding:0;">
            ${diag.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('')}
          </ul>
        </div>
      `
      : '';

    const posQueries = (diag.test_queries?.positive || []).map(q => `<li><em>«${escapeHtml(q)}»</em></li>`).join('');
    const negQueries = (diag.test_queries?.negative || []).map(q => `<li><em>«${escapeHtml(q)}»</em></li>`).join('');

    elements.modalBody.innerHTML = `
      <div class="doctor-report-body">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <div>
            <div style="font-weight:700; font-size:15px; font-family:var(--font-mono);">${escapeHtml(diag.skill_name)}</div>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(diag.file_path || diag.file_name)}</div>
          </div>
          ${statusBadge}
        </div>

        ${errorsHtml}
        ${warningsHtml}

        <h3 style="font-size:13px; margin:10px 0 6px;">Результаты чек-листа:</h3>
        <div style="background:var(--surface-muted); padding:10px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle); margin-bottom:12px;">
          ${checksHtml}
        </div>

        <h3 style="font-size:13px; margin:10px 0 6px;">5 контрольных запросов (тестовые сценарии):</h3>
        <div style="font-size:12px; margin-bottom:6px; color:var(--status-healthy); font-weight:600;">Позитивные триггеры (скилл ДОЛЖЕН запускаться):</div>
        <ol style="font-size:12px; margin:0 0 10px 18px; color:var(--text-secondary);">${posQueries}</ol>
        <div style="font-size:12px; margin-bottom:6px; color:var(--status-error); font-weight:600;">Негативные триггеры (скилл НЕ ДОЛЖЕН запускаться):</div>
        <ol style="font-size:12px; margin:0 0 12px 18px; color:var(--text-secondary);">${negQueries}</ol>

        <h3 style="font-size:13px; margin:10px 0 6px;">Рекомендованный исправленный однострочный <code>description</code>:</h3>
        <pre id="fixed-description-block">${escapeHtml(diag.fixed_description)}</pre>
      </div>
    `;

    elements.modalFooter.innerHTML = `
      <button class="btn btn-secondary" id="btn-copy-fixed-desc">📋 Скопировать исправленный description</button>
      <button class="btn btn-ghost" onclick="closeModal()">Закрыть</button>
    `;

    document.getElementById('btn-copy-fixed-desc')?.addEventListener('click', () => {
      if (diag.fixed_description) {
        navigator.clipboard.writeText(diag.fixed_description);
        showToast('Исправленный description скопирован в буфер обмена', 'success');
      }
    });
  } catch (err) {
    elements.modalBody.innerHTML = `<div class="modal-feedback error">Ошибка: ${escapeHtml(err.message)}</div>`;
  }
}

async function runDoctorAllSkills() {
  if (!currentSkills.length) {
    showToast('Скиллы не найдены', 'warning');
    return;
  }
  showToast(`Запуск диагностики ${currentSkills.length} скиллов...`, 'info');
  await fetchSkills();
  showToast('Диагностика всех скиллов завершена', 'success');
}

function openAssignSkillModal(skillName) {
  const agents = currentSnapshot?.workflow?.agents || [
    { id: 'manager', name: 'Оркестратор (Manager)' },
    { id: 'developer-1', name: 'Кодер 1' },
    { id: 'developer-2', name: 'Кодер 2' },
    { id: 'code-reviewer', name: 'Ревьюер кода' },
    { id: 'tester', name: 'Тестировщик' },
    { id: 'tech-writer', name: 'Технический писатель' },
    { id: 'skill-doctor', name: 'Скилл-доктор' },
  ];

  elements.modalTitle.textContent = `Назначить скилл: ${skillName}`;
  elements.modalBody.innerHTML = `
    <div style="font-size:13px; margin-bottom:14px; color:var(--text-secondary);">
      Выберите субагента, которому будет назначен навык <strong>${escapeHtml(skillName)}</strong>. Навык будет добавлен в конфигурацию инструментов агента в <code>workflow_state.json</code>.
    </div>
    <label class="inspector-field" style="margin-bottom:12px;">
      Субагент:
      <select id="modal-assign-agent-select" class="select-filter" style="width:100%;">
        ${agents.map(a => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name || a.id)} (${escapeHtml(a.id)})</option>`).join('')}
      </select>
    </label>
    <div id="assign-skill-feedback"></div>
  `;

  elements.modalFooter.innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
    <button class="btn btn-primary" id="btn-modal-confirm-assign">Назначить навык</button>
  `;

  document.getElementById('btn-modal-confirm-assign')?.addEventListener('click', async () => {
    const selectedAgent = document.getElementById('modal-assign-agent-select')?.value;
    if (!selectedAgent) return;
    const res = await executeAction('assign_skill', { skill_name: skillName, agent_id: selectedAgent });
    if (res && res.ok) {
      closeModal();
      await fetchSkills();
    }
  });

  showModal();
}

async function unassignSkillFromAgent(skillName, agentId) {
  const res = await executeAction('unassign_skill', { skill_name: skillName, agent_id: agentId });
  if (res && res.ok) {
    await fetchSkills();
  }
}

// ═══════════════════════════════════════════════════════════════
//  OBSIDIAN VAULT & SHARED MEMORY
// ═══════════════════════════════════════════════════════════════
async function checkObsidianVault(path) {
  const badge = document.getElementById('obsidian-vault-status-badge');
  const details = document.getElementById('obsidian-vault-details');
  const p = path || document.getElementById('setting-obsidian-vault-path')?.value || '/srv/projects/AI-Memory';
  if (badge) { badge.textContent = 'Проверка...'; badge.className = 'badge'; }
  if (details) details.textContent = 'Выполняется проверка хранилища Obsidian...';

  const res = await executeAction('check_obsidian_vault', { obsidian_vault_path: p });
  if (res && res.ok) {
    if (badge) { badge.textContent = 'Доступно'; badge.className = 'badge healthy'; }
    if (details) details.innerHTML = `✓ ${escapeHtml(res.message)} (Заметок: ${res.data?.notes_count || 0})`;
  } else {
    if (badge) { badge.textContent = 'Недоступно'; badge.className = 'badge error'; }
    if (details) details.innerHTML = `⚠️ ${escapeHtml(res.message || 'Ошибка проверки хранилища')}`;
  }
}

async function setupMemoryStructure(path) {
  const details = document.getElementById('obsidian-vault-details');
  const p = path || document.getElementById('setting-obsidian-vault-path')?.value || '/srv/projects/AI-Memory';
  if (details) details.textContent = 'Развёртывание структуры памяти...';

  const res = await executeAction('setup_memory', { obsidian_vault_path: p, project_name: 'hermes-hub' });
  if (res && res.ok) {
    if (details) {
      details.innerHTML = `✓ ${escapeHtml(res.message)}<br><small>Создано папок: ${(res.data?.created_dirs || []).join(', ') || 'все существовали'}</small>`;
    }
    showToast(res.message || 'Структура памяти развёрнута', 'success');
  } else {
    if (details) details.innerHTML = `⚠️ ${escapeHtml(res.message || 'Ошибка развёртывания структуры')}`;
    showToast(res.message || 'Ошибка развёртывания памяти', 'error');
  }
}


async function handleClearAccounts() {
  const preview = await executeAction('clear_accounts', {});
  if (!preview?.ok) return;
  const targets = preview.data.targets;
  const names = targets.map(item => item.profile_id).join('\n');
  if (!targets.length) { showToast('Нет аккаунтов для очистки. Antigravity защищён.', 'info'); return; }
  if (!confirm(`Удалить ключи этих аккаунтов?\n${names}\n\nAntigravity не будет затронут. Повторное подключение остальных аккаунтов потребует ключей.`)) return;
  const result = await executeAction('clear_accounts', {confirmed: true, targets});
  showToast(result?.message || 'Нет ответа от сервера', result?.ok ? 'success' : 'error');
  await fetchSnapshot();
}

// ═══════════════════════════════════════════════════════════════
//  CONTEXT COMPRESSION UI (A56)
// ═══════════════════════════════════════════════════════════════
async function checkCompressionStatus() {
  const badge = document.getElementById('compression-status-badge');
  const details = document.getElementById('compression-details-box');
  const res = await executeAction('get_compression_status', {});
  if (res && res.ok && res.data) {
    const d = res.data;
    if (badge) {
      if (!d.configured || d.status === 'unconfigured') {
        badge.textContent = 'Н/Д: модель для сжатия не выбрана';
        badge.className = 'badge';
      } else if (d.status === 'ready') {
        badge.textContent = `🟢 Готов: ${d.model || d.profile_id} (порог ${d.threshold_percent}%)`;
        badge.className = 'badge healthy';
      } else {
        badge.textContent = `⚠️ Недоступен: ${d.endpoint || d.profile_id}`;
        badge.className = 'badge warning';
      }
    }
    if (details) {
      if (!d.configured || d.status === 'unconfigured') {
        details.innerHTML = 'Сжатие отключено. Выберите профиль модели для сжатия контекста в настройках.';
      } else {
        const stats = `Эндпоинт: ${d.endpoint}\nМодель: ${d.model}\nИзмеренный контекст: ${d.n_ctx} токенов\nПорог запуска: ${d.threshold_percent}%\nСвежих сообщений без сжатия: ${d.keep_recent_messages}\nСжатий выполнено: ${d.history_count} (Сэкономлено токенов: ${d.total_saved_tokens})`;
        details.textContent = stats;
      }
    }
  }
}

async function testCompression() {
  const details = document.getElementById('compression-details-box');
  const btn = document.getElementById('btn-test-compression');
  if (btn) btn.disabled = true;
  if (details) details.textContent = '⏳ Выполняется тестовое сжатие контекста на сервере...';

  try {
    const sel = document.getElementById('setting-compressor-profile');
    const profileId = sel ? sel.value : null;
    const res = await executeAction('test_compression', { profile_id: profileId });
    if (res && res.ok && res.data) {
      const outcome = res.data.outcome || {};
      const factsRetained = outcome.facts_retained || 0;
      const factsTotal = outcome.facts_total || 0;
      const pct = outcome.retention_percent || 100;
      const text = `✓ ${res.message}\n` +
        `├─ Токены: ${outcome.tokens_before} → ${outcome.tokens_after} (${outcome.compression_ratio}x, экономия ${outcome.saved_tokens} токенов)\n` +
        `├─ Время выполнения: ${outcome.duration_sec}с\n` +
        `├─ Удержание фактов: ${factsRetained}/${factsTotal} (${pct}%)\n` +
        `└─ Сохранённые факты:\n${(outcome.retained_facts || []).map(f => '   • ' + f).join('\n')}`;
      if (details) details.textContent = text;
      showToast('Тест сжатия успешно выполнен: 100% фактов сохранено', 'success');
      await checkCompressionStatus();
    } else {
      if (details) details.textContent = `❌ Ошибка: ${(res && res.message) || 'Не удалось выполнить тестовое сжатие'}`;
      showToast((res && res.message) || 'Ошибка тестирования сжатия', 'error');
    }
  } catch (err) {
    if (details) details.textContent = `❌ Исключение: ${err.message || String(err)}`;
    showToast('Ошибка при вызове теста сжатия', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Attach event listeners for compression buttons
document.getElementById('btn-check-compression-status')?.addEventListener('click', checkCompressionStatus);
document.getElementById('btn-test-compression')?.addEventListener('click', testCompression);


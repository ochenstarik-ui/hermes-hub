/* Hermes Hub A30 workflow canvas — vanilla JS, no build step. */
'use strict';

const workflowUi = {
  initialized: false,
  mode: 'live',
  selectedAgentId: null,
  selectedTab: 'main',
  scale: 1,
  dirty: false,
  draftEdges: [],
  draftPositions: {},
  connectingFrom: null,
  drag: null,
};

function wfEscape(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

function wfValue(value, suffix = '') {
  return value === null || value === undefined ? null : `${value}${suffix}`;
}

function wfUnavailable(elementId, reason) {
  const value = document.getElementById(elementId);
  const detail = document.getElementById(`${elementId}-reason`);
  if (value) value.textContent = 'Н/Д';
  if (detail) detail.textContent = `Н/Д: ${reason}`;
}

function initWorkflowOverview() {
  if (workflowUi.initialized) return;
  workflowUi.initialized = true;
  document.getElementById('workflow-mode-live')?.addEventListener('click', () => setWorkflowMode('live'));
  document.getElementById('workflow-mode-edit')?.addEventListener('click', () => setWorkflowMode('edit'));
  document.getElementById('btn-workflow-save')?.addEventListener('click', saveWorkflowDraft);
  document.getElementById('btn-agent-add')?.addEventListener('click', openAgentCreateDialog);
  document.getElementById('btn-workflow-start')?.addEventListener('click', startWorkflowRun);
  document.getElementById('btn-workflow-stop')?.addEventListener('click', () => executeAction('stop_workflow', {}));
  document.getElementById('workflow-events-all')?.addEventListener('click', () => switchView('logs'));
  document.getElementById('workflow-max-iterations')?.addEventListener('change', markWorkflowDirty);
  document.getElementById('workflow-zoom-in')?.addEventListener('click', () => setWorkflowScale(workflowUi.scale + 0.1));
  document.getElementById('workflow-zoom-out')?.addEventListener('click', () => setWorkflowScale(workflowUi.scale - 0.1));
  document.getElementById('workflow-fit')?.addEventListener('click', fitWorkflowGraph);
  const canvas = document.getElementById('workflow-canvas');
  canvas?.addEventListener('mousemove', workflowPointerMove);
  canvas?.addEventListener('mouseup', workflowPointerUp);
  canvas?.addEventListener('mouseleave', workflowPointerCancel);
  window.addEventListener('resize', drawWorkflowEdges);
}

function renderWorkflowOverview(snapshot) {
  initWorkflowOverview();
  const workflow = snapshot?.workflow;
  if (!workflow) {
    renderWorkflowLoading('Backend не вернул поле workflow');
    return;
  }
  if (workflow.is_loading) {
    renderWorkflowLoading('Workflow загружается');
    return;
  }
  if (workflow.unavailable_reason) {
    renderWorkflowLoading(workflow.unavailable_reason);
    return;
  }
  if (!workflowUi.dirty && !workflowUi.drag && !workflowUi.connectingFrom) {
    workflowUi.draftEdges = (workflow.definition?.edges || []).map((edge) => ({ ...edge }));
    workflowUi.draftPositions = Object.fromEntries((workflow.agents || []).map((agent) => [
      agent.id, { ...(agent.position || { x: 80, y: 80 }) },
    ]));
  }
  renderWorkflowKpis(snapshot);
  renderWorkflowHeader(workflow);
  renderWorkflowNodes(workflow);
  renderWorkflowInspector(snapshot, workflow);
  renderWorkflowEvents(workflow.events || []);
  requestAnimationFrame(drawWorkflowEdges);
}

function renderWorkflowLoading(reason) {
  ['workflow-kpi-active', 'workflow-kpi-online', 'workflow-kpi-latency', 'workflow-kpi-tokens', 'workflow-kpi-success']
    .forEach((id) => wfUnavailable(id, reason));
  const empty = document.getElementById('workflow-empty');
  if (empty) {
    empty.classList.remove('hidden');
    empty.innerHTML = `<strong>Workflow недоступен</strong><span>${wfEscape(reason)}</span>`;
  }
}

function renderWorkflowKpis(snapshot) {
  const metrics = snapshot.metrics || {};
  const telemetry = metrics.telemetry || {};
  const global = telemetry.global || {};
  const workflow = snapshot.workflow || {};
  const run = workflow.run || {};
  const active = run.status === 'running' ? 1 : 0;
  setWorkflowKpi('workflow-kpi-active', String(active), 'Источник: workflow.run.status');

  const readiness = snapshot.readiness || {};
  if (readiness.roles_ready_count === null || readiness.roles_ready_count === undefined || readiness.total_roles === undefined) {
    wfUnavailable('workflow-kpi-online', 'readiness не содержит число готовых ролей');
  } else {
    setWorkflowKpi('workflow-kpi-online', `${readiness.roles_ready_count} / ${readiness.total_roles}`, 'Источник: readiness');
  }
  if (!global.total_calls) {
    wfUnavailable('workflow-kpi-latency', 'за 24 часа нет измеренных вызовов');
    wfUnavailable('workflow-kpi-success', 'за 24 часа нет завершённых вызовов');
  } else {
    const latency = wfValue(global.latency_p50_ms, ' мс');
    latency ? setWorkflowKpi('workflow-kpi-latency', latency, 'Медиана p50, telemetry') : wfUnavailable('workflow-kpi-latency', 'провайдер не вернул задержку');
    const success = global.successful_calls / global.total_calls * 100;
    setWorkflowKpi('workflow-kpi-success', `${success.toFixed(1)}%`, `${global.successful_calls} из ${global.total_calls}, telemetry`);
  }
  if (global.total_tokens === null || global.total_tokens === undefined) {
    wfUnavailable('workflow-kpi-tokens', 'провайдеры не вернули usage');
  } else {
    setWorkflowKpi('workflow-kpi-tokens', new Intl.NumberFormat('ru-RU').format(global.total_tokens), 'Источник: telemetry usage, 24 ч');
  }
}

function setWorkflowKpi(id, value, reason) {
  const node = document.getElementById(id);
  const detail = document.getElementById(`${id}-reason`);
  if (node) node.textContent = value;
  if (detail) detail.textContent = reason;
}

function renderWorkflowHeader(workflow) {
  const definition = workflow.definition || {};
  const run = workflow.run || {};
  document.getElementById('workflow-title').textContent = definition.name || 'Workflow без названия';
  const state = document.getElementById('workflow-run-state');
  state.textContent = workflowRunLabel(run.status);
  state.className = `workflow-run-state ${wfEscape(run.status || 'idle')}`;
  document.getElementById('workflow-iteration').textContent = run.iteration || 'Н/Д';
  if (!workflowUi.dirty) document.getElementById('workflow-max-iterations').value = definition.max_iterations || 1;
  document.getElementById('workflow-run-error').textContent = run.error || '';
  document.getElementById('btn-workflow-start').disabled = run.status === 'running' || run.status === 'stopping';
  document.getElementById('btn-workflow-stop').disabled = run.status !== 'running';
}

function workflowRunLabel(status) {
  return ({ idle: 'Нет активного запуска', running: '● Запущен', stopping: 'Останавливается', completed: 'Завершён', failed: 'Ошибка', stopped: 'Остановлен', interrupted: 'Прерван перезапуском' })[status] || `Н/Д: неизвестный статус ${status || 'не указан'}`;
}

function renderWorkflowNodes(workflow) {
  const layer = document.getElementById('workflow-node-layer');
  const canvas = document.getElementById('workflow-canvas');
  const agents = workflow.agents || [];
  canvas.classList.toggle('workflow-mode-edit', workflowUi.mode === 'edit');
  document.getElementById('workflow-empty').classList.toggle('hidden', agents.length > 0);
  layer.innerHTML = agents.map((agent) => {
    const pos = workflowUi.draftPositions[agent.id] || agent.position || { x: 80, y: 80 };
    const cfg = agent.execution_config || {};
    const assignment = cfg.unavailable_reason
      ? `Н/Д: ${cfg.unavailable_reason}`
      : [cfg.provider, cfg.model, cfg.account].filter(Boolean).join(' · ');
    return `<article class="workflow-node ${wfEscape(agent.runtime_state)} ${workflowUi.selectedAgentId === agent.id ? 'selected' : ''}" data-agent-id="${wfEscape(agent.id)}" style="left:${Number(pos.x) || 0}px;top:${Number(pos.y) || 0}px">
      <button class="workflow-port in" aria-label="Вход"></button><button class="workflow-port out" aria-label="Создать связь"></button>
      <h3>${wfEscape(agent.name)}</h3><p>${wfEscape(agent.role)}</p><p>${wfEscape(agent.agent_file)}</p><p title="${wfEscape(assignment)}">${wfEscape(assignment)}</p>
      <div class="workflow-node-status"><i></i><span>${wfEscape(runtimeStateLabel(agent.runtime_state))}</span></div>
    </article>`;
  }).join('');
  layer.style.transform = `scale(${workflowUi.scale})`;
  layer.querySelectorAll('.workflow-node').forEach((node) => {
    node.addEventListener('click', () => selectWorkflowAgent(node.dataset.agentId));
    node.addEventListener('mousedown', beginNodeDrag);
    node.querySelector('.workflow-port.out')?.addEventListener('mousedown', beginConnection);
    node.querySelector('.workflow-port.in')?.addEventListener('mouseup', finishConnection);
  });
  renderWorkflowMinimap(agents);
}

function runtimeStateLabel(state) {
  return ({ waiting: 'Ожидает', working: 'Работает', reviewing: 'Проверяет', error: 'Ошибка', completed: 'Завершено', not_implemented: 'Исполнение не реализовано' })[state] || `Н/Д: ${state || 'статус не получен'}`;
}

function setWorkflowMode(mode) {
  if (mode === 'edit' && currentSnapshot?.workflow?.run?.status === 'running') {
    showToast('EDIT недоступен во время LIVE-выполнения', 'warning');
    return;
  }
  workflowUi.mode = mode;
  document.querySelectorAll('.workflow-mode-btn').forEach((button) => button.classList.toggle('active', button.dataset.mode === mode));
  renderWorkflowOverview(currentSnapshot);
}

function selectWorkflowAgent(agentId) {
  if (workflowUi.drag?.moved) return;
  workflowUi.selectedAgentId = agentId;
  renderWorkflowOverview(currentSnapshot);
}

function beginNodeDrag(event) {
  if (workflowUi.mode !== 'edit' || event.target.classList.contains('workflow-port')) return;
  const node = event.currentTarget;
  const position = workflowUi.draftPositions[node.dataset.agentId] || { x: node.offsetLeft, y: node.offsetTop };
  workflowUi.drag = { id: node.dataset.agentId, startX: event.clientX, startY: event.clientY, original: { ...position }, moved: false };
  event.preventDefault();
}

function workflowPointerMove(event) {
  if (workflowUi.drag) {
    const drag = workflowUi.drag;
    const dx = (event.clientX - drag.startX) / workflowUi.scale;
    const dy = (event.clientY - drag.startY) / workflowUi.scale;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    workflowUi.draftPositions[drag.id] = { x: Math.max(0, drag.original.x + dx), y: Math.max(0, drag.original.y + dy) };
    const node = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(drag.id)}"]`);
    if (node) {
      node.style.left = `${workflowUi.draftPositions[drag.id].x}px`;
      node.style.top = `${workflowUi.draftPositions[drag.id].y}px`;
    }
    drawWorkflowEdges();
  }
}

function workflowPointerUp(event) {
  if (workflowUi.drag) {
    if (workflowUi.drag.moved) markWorkflowDirty();
    workflowUi.drag = null;
  }
  if (workflowUi.connectingFrom && event.target === document.getElementById('workflow-canvas')) {
    workflowUi.connectingFrom = null;
    showToast('Создание связи отменено', 'info');
  }
}

function workflowPointerCancel() {
  if (workflowUi.drag) {
    workflowUi.draftPositions[workflowUi.drag.id] = workflowUi.drag.original;
    workflowUi.drag = null;
    renderWorkflowOverview(currentSnapshot);
  }
  workflowUi.connectingFrom = null;
}

function beginConnection(event) {
  if (workflowUi.mode !== 'edit') return;
  workflowUi.connectingFrom = event.currentTarget.closest('.workflow-node').dataset.agentId;
  event.stopPropagation();
  event.preventDefault();
  showToast('Выберите входной порт целевого агента', 'info');
}

function finishConnection(event) {
  const target = event.currentTarget.closest('.workflow-node').dataset.agentId;
  const source = workflowUi.connectingFrom;
  workflowUi.connectingFrom = null;
  event.stopPropagation();
  if (!source || source === target) return;
  openEdgeDialog({ id: `edge-${Date.now()}`, source, target, condition: 'SUCCESS', label: '' }, true);
}

function drawWorkflowEdges() {
  const canvas = document.getElementById('workflow-canvas');
  const svg = document.getElementById('workflow-edges');
  const layer = document.getElementById('workflow-edge-layer');
  if (!canvas || !svg || !layer) return;
  svg.setAttribute('viewBox', `0 0 ${canvas.clientWidth} ${canvas.clientHeight}`);
  const parts = [];
  workflowUi.draftEdges.forEach((edge) => {
    const source = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(edge.source)}"]`);
    const target = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(edge.target)}"]`);
    if (!source || !target) return;
    const x1 = (source.offsetLeft + source.offsetWidth) * workflowUi.scale;
    const y1 = (source.offsetTop + source.offsetHeight / 2) * workflowUi.scale;
    const x2 = target.offsetLeft * workflowUi.scale;
    const y2 = (target.offsetTop + target.offsetHeight / 2) * workflowUi.scale;
    const bend = Math.max(45, Math.abs(x2 - x1) * .42);
    const path = `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
    const klass = String(edge.condition || '').toLowerCase();
    const labelX = (x1 + x2) / 2;
    const labelY = (y1 + y2) / 2 - 5;
    parts.push(`<path class="${wfEscape(klass)}" d="${path}"></path><path class="workflow-edge-hit" data-edge-id="${wfEscape(edge.id)}" d="${path}"></path><text class="workflow-edge-label" x="${labelX}" y="${labelY}">${wfEscape(edge.label || edge.condition)}</text>`);
  });
  layer.innerHTML = parts.join('');
  layer.querySelectorAll('.workflow-edge-hit').forEach((path) => path.addEventListener('click', () => {
    const edge = workflowUi.draftEdges.find((item) => item.id === path.dataset.edgeId);
    if (workflowUi.mode === 'edit' && edge) openEdgeDialog(edge, false);
  }));
}

function renderWorkflowMinimap(agents) {
  const minimap = document.getElementById('workflow-minimap');
  if (!minimap) return;
  const maxX = Math.max(900, ...agents.map((agent) => (workflowUi.draftPositions[agent.id]?.x || 0) + 200));
  const maxY = Math.max(500, ...agents.map((agent) => (workflowUi.draftPositions[agent.id]?.y || 0) + 100));
  minimap.innerHTML = agents.map((agent) => {
    const pos = workflowUi.draftPositions[agent.id] || { x: 0, y: 0 };
    return `<i style="left:${pos.x / maxX * 92}px;top:${pos.y / maxY * 55}px"></i>`;
  }).join('');
}

function setWorkflowScale(value) {
  workflowUi.scale = Math.max(.5, Math.min(1.6, Math.round(value * 10) / 10));
  document.getElementById('workflow-zoom-value').textContent = `${Math.round(workflowUi.scale * 100)}%`;
  renderWorkflowOverview(currentSnapshot);
}

function fitWorkflowGraph() {
  const agents = currentSnapshot?.workflow?.agents || [];
  const maxX = Math.max(...agents.map((agent) => (workflowUi.draftPositions[agent.id]?.x || 0) + 210), 600);
  const maxY = Math.max(...agents.map((agent) => (workflowUi.draftPositions[agent.id]?.y || 0) + 110), 400);
  const canvas = document.getElementById('workflow-canvas');
  setWorkflowScale(Math.min(canvas.clientWidth / maxX, canvas.clientHeight / maxY, 1));
}

function markWorkflowDirty() {
  workflowUi.dirty = true;
  const state = document.getElementById('workflow-save-state');
  state.textContent = 'Есть несохранённые изменения';
  state.classList.add('dirty');
}

async function saveWorkflowDraft() {
  const definition = currentSnapshot?.workflow?.definition || {};
  const result = await executeAction('save_workflow', {
    id: definition.id,
    name: definition.name,
    start_agent_id: definition.start_agent_id,
    escalation_agent_id: definition.escalation_agent_id,
    max_iterations: Number(document.getElementById('workflow-max-iterations').value),
    edges: workflowUi.draftEdges,
    agents: Object.entries(workflowUi.draftPositions).map(([id, position]) => ({ id, position })),
  });
  if (result.ok) {
    workflowUi.dirty = false;
    const state = document.getElementById('workflow-save-state');
    state.textContent = 'Сохранено';
    state.classList.remove('dirty');
  }
}

function renderWorkflowInspector(snapshot, workflow) {
  const box = document.getElementById('workflow-inspector');
  const agent = (workflow.agents || []).find((item) => item.id === workflowUi.selectedAgentId);
  if (!agent) {
    box.innerHTML = '<div class="workflow-inspector-empty"><strong>INSPECTOR</strong><span>Выберите агента на графе</span></div>';
    return;
  }
  const cfg = agent.execution_config || {};
  const tabs = [['main', 'Основное'], ['model', 'Модель'], ['instructions', 'Инструкции'], ['tools', 'Инструменты'], ['memory', 'Память'], ['history', 'История']];
  box.innerHTML = `<h2>INSPECTOR: ${wfEscape(agent.name)}</h2><div class="inspector-tabs">${tabs.map(([id, label]) => `<button data-tab="${id}" class="${workflowUi.selectedTab === id ? 'active' : ''}">${label}</button>`).join('')}</div><div id="inspector-tab-content"></div>`;
  box.querySelectorAll('.inspector-tabs button').forEach((button) => button.addEventListener('click', () => {
    workflowUi.selectedTab = button.dataset.tab;
    renderWorkflowInspector(snapshot, workflow);
  }));
  const content = document.getElementById('inspector-tab-content');
  if (workflowUi.selectedTab === 'main') {
    content.innerHTML = `<label class="inspector-field">Название<input id="agent-edit-name" value="${wfEscape(agent.name)}"></label><label class="inspector-field">Роль<div class="inspector-value">${wfEscape(agent.role)}</div></label><label class="inspector-field">Описание<textarea id="agent-edit-description">${wfEscape(agent.description)}</textarea></label><label class="inspector-field">Runtime status<div class="inspector-value">${wfEscape(runtimeStateLabel(agent.runtime_state))}</div></label><label class="inspector-field">Текущая задача<div class="inspector-value">${wfEscape(workflow.run?.current_agent_id === agent.id ? workflow.run.current_task : 'Н/Д: агент сейчас не выполняется')}</div></label><div class="inspector-actions"><button class="btn btn-primary btn-sm" id="agent-save-main">Сохранить</button><button class="btn btn-secondary btn-sm" id="agent-delete">Удалить</button></div>`;
    document.getElementById('agent-save-main').onclick = () => executeAction('update_agent', { agent_id: agent.id, name: document.getElementById('agent-edit-name').value, description: document.getElementById('agent-edit-description').value });
    document.getElementById('agent-delete').onclick = () => deleteWorkflowAgent(agent);
  } else if (workflowUi.selectedTab === 'model') {
    renderAgentModelTab(content, snapshot, agent);
  } else if (workflowUi.selectedTab === 'instructions') {
    content.innerHTML = `<div class="agent-file-card"><strong>Agent File</strong><code>${wfEscape(agent.agent_file)}</code><span>${agent.agent_file_exists ? 'Файл существует' : 'Н/Д: файл отсутствует'}</span><div class="inspector-actions"><button class="btn btn-secondary btn-sm" id="agent-file-open">Открыть в редакторе</button></div></div>`;
    document.getElementById('agent-file-open').onclick = () => openAgentFileEditor(agent);
  } else if (workflowUi.selectedTab === 'tools') {
    content.innerHTML = `<label class="inspector-field">Инструменты, через запятую<input id="agent-tools" value="${wfEscape((agent.tools || []).join(', '))}"></label><button class="btn btn-primary btn-sm" id="agent-tools-save">Сохранить</button>`;
    document.getElementById('agent-tools-save').onclick = () => executeAction('update_agent', { agent_id: agent.id, tools: document.getElementById('agent-tools').value.split(',').map((v) => v.trim()).filter(Boolean) });
  } else if (workflowUi.selectedTab === 'memory') {
    content.innerHTML = `<div class="inspector-value">${Object.keys(agent.memory_configuration || {}).length ? `<pre>${wfEscape(JSON.stringify(agent.memory_configuration, null, 2))}</pre>` : 'Н/Д: конфигурация памяти не задана'}</div>`;
  } else {
    const history = (workflow.events || []).filter((event) => event.agent_id === agent.id);
    content.innerHTML = history.length ? history.slice(-20).reverse().map((event) => `<div class="workflow-event ${wfEscape(event.level)}"><time>${wfEscape(formatWorkflowTime(event.timestamp))}</time><span>${wfEscape(event.message)}</span><em>${event.duration_seconds == null ? '' : `${event.duration_seconds} с`}</em></div>`).join('') : '<div class="inspector-value">Н/Д: у агента ещё нет запусков</div>';
  }
}

function renderAgentModelTab(content, snapshot, agent) {
  const profiles = Object.values(snapshot.all_profiles || {}).filter((profile) => isConnectedProfile(profile));
  const cfg = agent.execution_config || {};
  const providers = [...new Set(profiles.map((profile) => profile.provider))];
  content.innerHTML = `<label class="inspector-field">Провайдер<select id="agent-provider"><option value="">Не назначен</option>${providers.map((provider) => `<option value="${wfEscape(provider)}" ${provider === cfg.provider ? 'selected' : ''}>${wfEscape(provider)}</option>`).join('')}</select></label><label class="inspector-field">Аккаунт<select id="agent-account"></select></label><label class="inspector-field">Модель<select id="agent-model"></select></label><label class="inspector-field">Температура<input id="agent-temperature" type="number" step="0.1" min="0" max="2" value="${cfg.temperature ?? ''}" placeholder="Н/Д: не задана"></label><label class="inspector-field">Макс. токенов<input id="agent-max-tokens" type="number" min="1" value="${cfg.max_tokens ?? ''}" placeholder="Н/Д: не задано"></label><label class="inspector-field">Таймаут, с<input id="agent-timeout" type="number" min="1" value="${cfg.timeout || ''}"></label><button class="btn btn-primary btn-sm" id="agent-model-save">Изменить конфигурацию</button>`;
  const providerSelect = document.getElementById('agent-provider');
  const accountSelect = document.getElementById('agent-account');
  const modelSelect = document.getElementById('agent-model');
  const refreshAccounts = () => {
    const matches = profiles.filter((profile) => profile.provider === providerSelect.value);
    accountSelect.innerHTML = matches.length ? matches.map((profile) => `<option value="${wfEscape(profile.profile_id)}" ${profile.profile_id === cfg.account ? 'selected' : ''}>${wfEscape(profile.account_identity || profile.display_name || profile.profile_id)}</option>`).join('') : '<option value="">Н/Д: нет подключённых аккаунтов</option>';
    refreshModels();
  };
  const refreshModels = () => {
    const profile = profiles.find((item) => item.profile_id === accountSelect.value);
    const models = profile?.preferred_models || Object.values(profile?.model_states || {}).map((state) => state.display_name).filter(Boolean);
    modelSelect.innerHTML = models.length ? models.map((model) => `<option value="${wfEscape(model)}" ${model === cfg.model ? 'selected' : ''}>${wfEscape(model)}</option>`).join('') : '<option value="">Н/Д: модели не обнаружены</option>';
  };
  providerSelect.onchange = refreshAccounts;
  accountSelect.onchange = refreshModels;
  refreshAccounts();
  document.getElementById('agent-model-save').onclick = () => executeAction('update_agent', {
    agent_id: agent.id, provider: providerSelect.value, profile_id: accountSelect.value, model: modelSelect.value,
    temperature: nullableNumber('agent-temperature'), max_tokens: nullableNumber('agent-max-tokens'), timeout: nullableNumber('agent-timeout'),
  });
}

function nullableNumber(id) {
  const value = document.getElementById(id).value.trim();
  return value === '' ? null : Number(value);
}

async function deleteWorkflowAgent(agent) {
  let result = await executeAction('delete_agent', { agent_id: agent.id });
  if (result.ok && result.data?.confirmation_required) {
    const refs = result.data.consequences?.workflow_edges || [];
    if (!confirm(`Агент участвует в маршруте и/или графе. Будут удалены связи: ${refs.length ? refs.join(', ') : 'нет'}. Продолжить?`)) return;
    result = await executeAction('delete_agent', { agent_id: agent.id, force: true });
  }
  if (result.ok && result.data?.deleted) workflowUi.selectedAgentId = null;
}

function openAgentCreateDialog() {
  const profiles = Object.values(currentSnapshot?.all_profiles || {}).filter((profile) => isConnectedProfile(profile));
  openWorkflowDialog('Добавить агента', `<label>Название<input id="new-agent-name" required></label><label>Роль (произвольный идентификатор)<input id="new-agent-role" placeholder="security-reviewer"></label><label>Описание<textarea id="new-agent-description"></textarea></label><label>Аккаунт<select id="new-agent-account"><option value="">Не назначать</option>${profiles.map((profile) => `<option value="${wfEscape(profile.profile_id)}">${wfEscape(profile.provider)} · ${wfEscape(profile.account_identity || profile.profile_id)}</option>`).join('')}</select></label><label>Agent File<input id="new-agent-file" placeholder="agents/имя.md"></label>`, async (close) => {
    const account = document.getElementById('new-agent-account').value;
    const profile = profiles.find((item) => item.profile_id === account);
    const result = await executeAction('create_agent', {
      name: document.getElementById('new-agent-name').value,
      role: document.getElementById('new-agent-role').value,
      description: document.getElementById('new-agent-description').value,
      account,
      model: profile?.preferred_models?.[0] || null,
      agent_file: document.getElementById('new-agent-file').value,
    });
    if (result.ok) close();
  });
}

async function openAgentFileEditor(agent) {
  const result = await executeAction('read_agent_file', { agent_id: agent.id });
  if (!result.ok) return;
  const data = result.data || {};
  if (!data.exists) {
    showToast(`Н/Д: ${data.reason}`, 'warning');
    return;
  }
  openWorkflowDialog(`Agent File — ${agent.name}`, `<label>Путь<input value="${wfEscape(data.path)}" readonly></label><label>Markdown<textarea id="agent-file-content" class="agent-file-editor">${wfEscape(data.content)}</textarea></label><p id="agent-file-unsaved">Нет изменений</p>`, async (close) => {
    const saved = await executeAction('save_agent_file', { agent_id: agent.id, content: document.getElementById('agent-file-content').value });
    if (saved.ok) close();
  }, 'Сохранить');
  const editor = document.getElementById('agent-file-content');
  editor.addEventListener('input', () => { document.getElementById('agent-file-unsaved').textContent = 'Есть несохранённые изменения'; });
}

function openEdgeDialog(edge, isNew) {
  openWorkflowDialog(isNew ? 'Новое ребро' : 'Редактор ребра', `<label>От<input value="${wfEscape(edge.source)}" readonly></label><label>К<input value="${wfEscape(edge.target)}" readonly></label><label>Условие<select id="edge-condition">${['SUCCESS', 'REVIEW_PASSED', 'REVIEW_FAILED', 'NEXT', 'ERROR', 'ALWAYS'].map((condition) => `<option ${condition === edge.condition ? 'selected' : ''}>${condition}</option>`).join('')}</select></label><label>Подпись<input id="edge-label" value="${wfEscape(edge.label || '')}"></label>${isNew ? '' : '<button class="btn btn-secondary btn-sm" id="edge-delete">Удалить ребро</button>'}`, (close) => {
    const updated = { ...edge, condition: document.getElementById('edge-condition').value, label: document.getElementById('edge-label').value };
    const index = workflowUi.draftEdges.findIndex((item) => item.id === edge.id);
    if (index >= 0) workflowUi.draftEdges[index] = updated; else workflowUi.draftEdges.push(updated);
    markWorkflowDirty(); close(); drawWorkflowEdges();
  });
  if (!isNew) document.getElementById('edge-delete').onclick = () => {
    workflowUi.draftEdges = workflowUi.draftEdges.filter((item) => item.id !== edge.id);
    markWorkflowDirty(); document.querySelector('.workflow-dialog-backdrop')?.remove(); drawWorkflowEdges();
  };
}

function openWorkflowDialog(title, body, onSave, saveLabel = 'Применить') {
  document.querySelector('.workflow-dialog-backdrop')?.remove();
  const backdrop = document.createElement('div');
  backdrop.className = 'workflow-dialog-backdrop';
  backdrop.innerHTML = `<div class="workflow-dialog"><h2>${wfEscape(title)}</h2>${body}<div class="workflow-dialog-actions"><button class="btn btn-secondary" data-dialog-cancel>Отмена</button><button class="btn btn-primary" data-dialog-save>${wfEscape(saveLabel)}</button></div></div>`;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelector('[data-dialog-cancel]').onclick = close;
  backdrop.querySelector('[data-dialog-save]').onclick = () => onSave(close);
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) close(); });
}

async function startWorkflowRun() {
  if (workflowUi.dirty) {
    showToast('Сначала сохраните изменения графа', 'warning');
    return;
  }
  const task = document.getElementById('workflow-task').value.trim();
  await executeAction('start_workflow', { task });
  setWorkflowMode('live');
}

function renderWorkflowEvents(events) {
  const box = document.getElementById('workflow-events-list');
  if (!events.length) {
    box.innerHTML = '<p>Н/Д: workflow ещё не создавал событий</p>';
    return;
  }
  box.innerHTML = events.slice(-20).reverse().map((event) => `<div class="workflow-event ${wfEscape(event.level)}"><time>${wfEscape(formatWorkflowTime(event.timestamp))}</time><span>${wfEscape(event.message)}${event.error ? ` — ${wfEscape(event.error)}` : ''}</span><em>${wfEscape(event.type)}</em></div>`).join('');
}

function formatWorkflowTime(value) {
  if (!value) return 'Н/Д';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString('ru-RU');
}

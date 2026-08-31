/* Hermes Hub A30 workflow canvas — vanilla JS, no build step. */
'use strict';

const workflowUi = {
  initialized: false,
  mode: 'live',
  selectedAgentId: null,
  selectedTab: 'main',
  scale: 1,
  panX: 0,
  panY: 0,
  isPanning: false,
  panStart: { x: 0, y: 0 },
  dirty: false,
  draftEdges: [],
  draftPositions: {},
  connectingFrom: null,
  drag: null,
  fitted: false,
  inspectorClosed: false,
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

function updateCanvasTransform() {
  const viewport = document.getElementById('workflow-viewport');
  if (viewport) {
    viewport.style.transform = `translate(${workflowUi.panX}px, ${workflowUi.panY}px) scale(${workflowUi.scale})`;
  }
  const zoomVal = document.getElementById('workflow-zoom-value');
  if (zoomVal) {
    zoomVal.textContent = `${Math.round(workflowUi.scale * 100)}%`;
  }
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
  document.getElementById('canvas-select').onclick = () => setWorkflowMode('live');
  document.getElementById('canvas-add').onclick = openAgentCreateDialog;
  document.getElementById('canvas-fit').onclick = fitWorkflowGraph;
  document.getElementById('canvas-arrange').onclick = arrangeWorkflowNodes;
  document.getElementById('canvas-connect').onclick = () => { setWorkflowMode('edit'); showToast('Потяните из правого порта агента в левый порт получателя', 'info'); };
  const canvas = document.getElementById('workflow-canvas');
  canvas?.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    setWorkflowScale(workflowUi.scale * zoomFactor, mouseX, mouseY);
  }, { passive: false });
  canvas?.addEventListener('mousedown', (e) => {
    if (e.target.closest('.workflow-node') || e.target.closest('.workflow-port') || e.target.closest('.workflow-minimap') || e.target.closest('.workflow-dialog') || e.target.closest('.canvas-tools')) return;
    if (e.button === 0 || e.button === 1) {
      workflowUi.isPanning = true;
      workflowUi.panStart = { x: e.clientX - workflowUi.panX, y: e.clientY - workflowUi.panY };
      canvas.style.cursor = 'grabbing';
    }
  });
  window.addEventListener('mousemove', workflowPointerMove);
  window.addEventListener('mouseup', workflowPointerUp);
  window.addEventListener('blur', workflowPointerCancel);
  window.addEventListener('resize', () => {
    drawWorkflowEdges();
  });
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
  if (!workflowUi.selectedAgentId && !workflowUi.inspectorClosed) workflowUi.selectedAgentId = workflow.definition?.start_agent_id || workflow.agents?.[0]?.id;
  renderWorkflowNodes(workflow);
  renderWorkflowInspector(snapshot, workflow);
  renderWorkflowEvents(workflow.events || []);
  renderWorkflowStatistics(workflow);
  if (!workflowUi.fitted && workflow.agents?.length) { workflowUi.fitted = true; requestAnimationFrame(focusWorkflowStart); }
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
    wfUnavailable('workflow-kpi-status', 'readiness не содержит данных');
  } else {
    const readyCount = readiness.roles_ready_count;
    const totalCount = readiness.total_roles;
    setWorkflowKpi('workflow-kpi-online', `${readyCount} / ${totalCount}`, 'Источник: readiness');
    if (readyCount === totalCount && totalCount > 0) {
      setWorkflowKpi('workflow-kpi-status', 'Все сервисы работают', `Отлично (${readyCount}/${totalCount} ролей)`);
    } else if (readyCount > 0) {
      setWorkflowKpi('workflow-kpi-status', 'Частично готов', `${readyCount} из ${totalCount} ролей готовы`);
    } else {
      setWorkflowKpi('workflow-kpi-status', 'Требует настройки', '0 ролей настроено');
    }
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
    const assignment = `${cfg.model || 'Модель: Н/Д'} • ${cfg.account || 'Аккаунт: Н/Д'}`;
    return `<article class="workflow-node ${wfEscape(agent.runtime_state)} ${workflowUi.selectedAgentId === agent.id ? 'selected' : ''}" data-agent-id="${wfEscape(agent.id)}" style="left:${Number(pos.x) || 0}px;top:${Number(pos.y) || 0}px">
      <button class="workflow-port in" aria-label="Вход"></button><button class="workflow-port out" aria-label="Создать связь"></button>
      <span class="agent-node-icon" aria-hidden="true"><img class="brand-logo" src="/static/${getModelIcon(cfg.model)}" alt=""></span><h3>${wfEscape(agent.name)}</h3><p title="${wfEscape(agent.agent_file)}">${wfEscape(agent.agent_file?.split('/').pop() || 'Agent File: Н/Д')}</p><p class="node-assignment" title="${wfEscape(cfg.unavailable_reason || assignment)}">${wfEscape(assignment)}</p>
      <div class="workflow-node-status"><i></i><span>${wfEscape(runtimeStateLabel(agent.runtime_state))}</span></div>
    </article>`;
  }).join('');
  updateCanvasTransform();
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
  document.body.dataset.workflowMode = mode;
  document.querySelectorAll('.workflow-mode-btn').forEach((button) => button.classList.toggle('active', button.dataset.mode === mode));
  renderWorkflowOverview(currentSnapshot);
}

function selectWorkflowAgent(agentId) {
  if (workflowUi.drag?.moved) return;
  workflowUi.inspectorClosed = false;
  workflowUi.selectedAgentId = agentId;
  renderWorkflowOverview(currentSnapshot);
}

function beginNodeDrag(event) {
  if (workflowUi.mode !== 'edit' || event.target.classList.contains('workflow-port')) return;
  const node = event.currentTarget;
  const position = workflowUi.draftPositions[node.dataset.agentId] || { x: node.offsetLeft, y: node.offsetTop };
  workflowUi.drag = { id: node.dataset.agentId, startX: event.clientX, startY: event.clientY, original: { ...position }, moved: false };
  event.stopPropagation();
  event.preventDefault();
}

function workflowPointerMove(event) {
  if (workflowUi.isPanning) {
    workflowUi.panX = event.clientX - workflowUi.panStart.x;
    workflowUi.panY = event.clientY - workflowUi.panStart.y;
    updateCanvasTransform();
    return;
  }
  if (workflowUi.drag) {
    const drag = workflowUi.drag;
    const dx = (event.clientX - drag.startX) / workflowUi.scale;
    const dy = (event.clientY - drag.startY) / workflowUi.scale;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    workflowUi.draftPositions[drag.id] = { x: drag.original.x + dx, y: drag.original.y + dy };
    const node = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(drag.id)}"]`);
    if (node) {
      node.style.left = `${workflowUi.draftPositions[drag.id].x}px`;
      node.style.top = `${workflowUi.draftPositions[drag.id].y}px`;
    }
    drawWorkflowEdges();
  }
}

function workflowPointerUp(event) {
  if (workflowUi.isPanning) {
    workflowUi.isPanning = false;
    const canvas = document.getElementById('workflow-canvas');
    if (canvas) canvas.style.cursor = '';
  }
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
  if (workflowUi.isPanning) {
    workflowUi.isPanning = false;
    const canvas = document.getElementById('workflow-canvas');
    if (canvas) canvas.style.cursor = '';
  }
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

function roundedWorkflowPath(points, radius = 18) {
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i-1], corner = points[i], next = points[i+1];
    const before = Math.hypot(corner.x-prev.x,corner.y-prev.y);
    const after = Math.hypot(next.x-corner.x,next.y-corner.y);
    const r = Math.min(radius,before/2,after/2);
    if (!r) continue;
    const x = corner.x+(prev.x-corner.x)*r/before, y = corner.y+(prev.y-corner.y)*r/before;
    const nx = corner.x+(next.x-corner.x)*r/after, ny = corner.y+(next.y-corner.y)*r/after;
    path += ` L ${x} ${y} Q ${corner.x} ${corner.y} ${nx} ${ny}`;
  }
  const end = points.at(-1);
  return path + ` L ${end.x} ${end.y}`;
}

function workflowEdgeRoute(source, target, lane = 0) {
  const sx = source.x+source.width/2, tx = target.x+target.width/2;
  const sy = source.y+source.height/2, ty = target.y+target.height/2;
  // Downward branches leave the bottom and enter the top of the next row.
  if (target.y >= source.y+source.height+32) {
    const y = (source.y+source.height+target.y)/2;
    return {points:[{x:sx,y:source.y+source.height+5},{x:sx,y},{x:tx,y},{x:tx,y:target.y-7}],x:(sx+tx)/2,y:y-10,width:Math.max(100,Math.abs(tx-sx)-24)};
  }
  // Forward transitions between peers use the open horizontal corridor.
  if (Math.abs(sy-ty)<40 && target.x >= source.x+source.width+24) {
    const x1=source.x+source.width+5, x2=target.x-7;
    return {points:[{x:x1,y:sy},{x:x2,y:ty}],x:(x1+x2)/2,y:Math.min(sy,ty)-16,width:Math.max(50,x2-x1-10)};
  }
  // Feedback between peers runs below their row, separate from forward arrows.
  if (Math.abs(sy-ty)<40) {
    const y=Math.max(source.y+source.height,target.y+target.height)+38+lane*28;
    return {points:[{x:sx,y:source.y+source.height+5},{x:sx,y},{x:tx,y},{x:tx,y:target.y+target.height+7}],x:(sx+tx)/2,y:y+14,width:Math.max(90,Math.abs(tx-sx)-30)};
  }
  // Upward return travels outside both nodes and enters from the right.
  const x=Math.max(source.x+source.width,target.x+target.width)+48+lane*24;
  return {points:[{x:source.x+source.width+5,y:sy},{x,y:sy},{x,y:ty},{x:target.x+target.width+7,y:ty}],x:(x+target.x+target.width)/2,y:ty-14,width:Math.max(80,x-target.x-target.width-24)};
}

function workflowLabelLines(text, width) {
  const limit=Math.max(8,Math.floor(width/5.7));
  const words=String(text).split(/\s+/), lines=[];
  let line='';
  for (const word of words) {
    if (line && (line+' '+word).length>limit) { lines.push(line); line=''; }
    line+=(line?' ':'')+word;
  }
  if(line) lines.push(line);
  return lines;
}

function drawWorkflowEdges() {
  const svg = document.getElementById('workflow-edges');
  const layer = document.getElementById('workflow-edge-layer');
  if (!svg || !layer) return;
  const parts = [], labels = [];
  let feedbackLane=0;
  workflowUi.draftEdges.forEach((edge) => {
    const source = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(edge.source)}"]`);
    const target = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(edge.target)}"]`);
    if (!source || !target) return;
    const rect=node=>({x:node.offsetLeft,y:node.offsetTop,width:node.offsetWidth,height:node.offsetHeight});
    const condition=String(edge.condition || '').toUpperCase();
    const tone=['REVIEW_FAILED','ERROR'].includes(condition)?'return':['SUCCESS','REVIEW_PASSED'].includes(condition)?'success':'next';
    const route=workflowEdgeRoute(rect(source),rect(target),tone==='return'?feedbackLane++:0);
    const path=roundedWorkflowPath(route.points);
    const lines=workflowLabelLines(edge.label || condition,Math.min(220,route.width));
    const width=Math.max(...lines.map(line=>line.length))*5.7+12, height=lines.length*13+6;
    labels.push(`<g class="edge-label-group edge-${tone}"><title>${wfEscape(edge.label || condition)} · ${wfEscape(condition)}</title><rect class="workflow-label-bg" x="${route.x-width/2}" y="${route.y-height/2}" width="${width}" height="${height}" rx="4"/><text class="workflow-edge-label" x="${route.x}" y="${route.y-(lines.length-1)*6.5+3}">${lines.map((line,i)=>`<tspan x="${route.x}" dy="${i?13:0}">${wfEscape(line)}</tspan>`).join('')}</text></g>`);
    parts.push(`<path class="workflow-link edge-${tone}" d="${path}" marker-end="url(#wf-arrow-${tone})"></path><path class="workflow-edge-hit" data-edge-id="${wfEscape(edge.id)}" d="${path}"></path>`);
  });
  layer.innerHTML = parts.join('');
  document.getElementById('workflow-label-layer').innerHTML = labels.join('');
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

function setWorkflowScale(value, focusX, focusY) {
  const canvas = document.getElementById('workflow-canvas');
  if (!canvas) return;
  const oldScale = workflowUi.scale;
  const newScale = Math.max(0.1, Math.min(2.5, Math.round(value * 100) / 100));
  if (focusX === undefined || focusY === undefined) {
    focusX = canvas.clientWidth / 2;
    focusY = canvas.clientHeight / 2;
  }
  workflowUi.panX = focusX - (focusX - workflowUi.panX) * (newScale / oldScale);
  workflowUi.panY = focusY - (focusY - workflowUi.panY) * (newScale / oldScale);
  workflowUi.scale = newScale;
  updateCanvasTransform();
}

function focusWorkflowStart() {
  const canvas = document.getElementById('workflow-canvas');
  const node = document.querySelector('.workflow-node.selected') || document.querySelector('.workflow-node');
  if (!canvas || !node) return;
  workflowUi.scale = .85;
  workflowUi.panX = canvas.clientWidth / 2 - (node.offsetLeft + node.offsetWidth / 2) * workflowUi.scale;
  workflowUi.panY = 60 - node.offsetTop * workflowUi.scale;
  updateCanvasTransform();
}

function fitWorkflowGraph() {
  const canvas = document.getElementById('workflow-canvas');
  if (!canvas) return;
  const agents = currentSnapshot?.workflow?.agents || [];
  if (!agents.length) {
    workflowUi.scale = 1;
    workflowUi.panX = 0;
    workflowUi.panY = 0;
    updateCanvasTransform();
    return;
  }
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  agents.forEach((agent) => {
    const pos = workflowUi.draftPositions[agent.id] || agent.position || { x: 80, y: 80 };
    minX = Math.min(minX, pos.x);
    const node = document.querySelector(`.workflow-node[data-agent-id="${CSS.escape(agent.id)}"]`);
    maxX = Math.max(maxX, pos.x + (node?.offsetWidth || 250));
    minY = Math.min(minY, pos.y);
    maxY = Math.max(maxY, pos.y + (node?.offsetHeight || 124));
  });
  document.querySelectorAll('.workflow-label-bg').forEach(label => {
    const x = Number(label.getAttribute('x')), y = Number(label.getAttribute('y'));
    minX = Math.min(minX, x); minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + Number(label.getAttribute('width')));
    maxY = Math.max(maxY, y + Number(label.getAttribute('height')));
  });
  document.querySelectorAll('.workflow-link').forEach(path => {
    const box = path.getBBox();
    minX = Math.min(minX, box.x); minY = Math.min(minY, box.y);
    maxX = Math.max(maxX, box.x+box.width); maxY = Math.max(maxY, box.y+box.height);
  });
  const width = maxX - minX || 200;
  const height = maxY - minY || 120;
  const pad = 60;
  const cW = canvas.clientWidth || 800;
  const cH = canvas.clientHeight || 500;
  const fitScale = Math.max(0.1, Math.min(1.4, Math.min((cW - pad * 2) / width, (cH - pad * 2) / height)));

  const viewport = document.getElementById('workflow-viewport');
  if (viewport) viewport.style.transition = 'transform 0.25s ease-out';

  workflowUi.scale = fitScale;
  workflowUi.panX = (cW - width * fitScale) / 2 - minX * fitScale;
  workflowUi.panY = (cH - height * fitScale) / 2 - minY * fitScale;
  updateCanvasTransform();

  setTimeout(() => {
    if (viewport) viewport.style.transition = '';
  }, 260);
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
  if (box.contains(document.activeElement) && document.activeElement.matches('input,select,textarea')) return;
  const agent = (workflow.agents || []).find((item) => item.id === workflowUi.selectedAgentId);
  if (!agent) {
    box.innerHTML = '<div class="workflow-inspector-empty"><strong>INSPECTOR</strong><span>Выберите агента на графе</span></div>';
    return;
  }
  const cfg = agent.execution_config || {};
  const tabs = [['main', 'Основное'], ['model', 'Модель'], ['instructions', 'Инструкции'], ['tools', 'Инструменты'], ['memory', 'Память'], ['execution', 'Выполнение'], ['history', 'История']];
  box.innerHTML = `<div class="inspector-heading"><h2>Инспектор: ${wfEscape(agent.name)}</h2><button id="inspector-close" aria-label="Закрыть инспектор">×</button></div><div class="inspector-tabs">${tabs.map(([id, label]) => `<button data-tab="${id}" class="${workflowUi.selectedTab === id ? 'active' : ''}">${label}</button>`).join('')}</div><div id="inspector-tab-content"></div>`;
  document.getElementById('inspector-close').onclick = () => { workflowUi.selectedAgentId = null; workflowUi.inspectorClosed = true; renderWorkflowOverview(snapshot); };
  box.querySelectorAll('.inspector-tabs button').forEach((button) => button.addEventListener('click', () => {
    workflowUi.selectedTab = button.dataset.tab;
    renderWorkflowInspector(snapshot, workflow);
  }));
  const content = document.getElementById('inspector-tab-content');
  if (workflowUi.selectedTab === 'main') {
    content.innerHTML = `<label class="inspector-field">Название<input id="agent-edit-name" value="${wfEscape(agent.name)}"></label><label class="inspector-field">Роль<div class="inspector-value">${wfEscape(agent.role)}</div></label><label class="inspector-field">Описание<textarea id="agent-edit-description">${wfEscape(agent.description)}</textarea></label><label class="inspector-field">Runtime status<div class="inspector-value">${wfEscape(runtimeStateLabel(agent.runtime_state))}</div></label><label class="inspector-field">Текущая задача<div class="inspector-value">${wfEscape(workflow.run?.current_agent_id === agent.id ? workflow.run.current_task : 'Н/Д: агент сейчас не выполняется')}</div></label><div class="inspector-actions"><button class="btn btn-primary btn-sm" id="agent-save-main">Сохранить</button><button class="btn btn-secondary btn-sm" id="agent-delete">Удалить</button></div>`;
    document.getElementById('agent-save-main').onclick = () => executeAction('update_agent', { agent_id: agent.id, name: document.getElementById('agent-edit-name').value, description: document.getElementById('agent-edit-description').value });
    document.getElementById('agent-delete').onclick = () => deleteWorkflowAgent(agent);
    appendAgentInspectorSummary(content, agent, workflow);
  } else if (workflowUi.selectedTab === 'execution') {
    content.innerHTML = `<h3>Политика выполнения</h3><pre class="inspector-value">${wfEscape(JSON.stringify(agent.execution_policy || {},null,2))}</pre><p class="inspector-value">Таймаут: ${wfEscape(cfg.timeout ?? 'Н/Д: не задан')} с</p><p class="inspector-value">${wfEscape(workflowRunLabel(workflow.run?.status))}</p>`;
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
  let initialRendering = true;
  const refreshAccounts = () => {
    const matches = profiles.filter((profile) => profile.provider === providerSelect.value);
    accountSelect.innerHTML = matches.length ? matches.map((profile) => `<option value="${wfEscape(profile.profile_id)}" ${profile.profile_id === cfg.account ? 'selected' : ''}>${wfEscape(profile.account_identity || profile.display_name || profile.profile_id)}</option>`).join('') : '<option value="">Н/Д: нет подключённых аккаунтов</option>';
    refreshModels();
  };
  const refreshModels = () => {
    const profile = profiles.find((item) => item.profile_id === accountSelect.value);
    const selected = initialRendering || (profile?.profile_id === cfg.account && providerSelect.value === cfg.provider) ? cfg.model : '';
    modelSelect.innerHTML = modelOptions(snapshot, profile || { provider: providerSelect.value }, selected);
  };
  providerSelect.onchange = refreshAccounts;
  accountSelect.onchange = refreshModels;
  refreshAccounts();
  initialRendering = false;
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

function appendAgentInspectorSummary(content, agent, workflow) {
  const editor = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'Изменить имя и описание';
  editor.append(summary);
  while (content.firstChild) editor.append(content.firstChild);
  const cfg = agent.execution_config || {};
  const value = (item, reason) => wfEscape(item ?? `Н/Д: ${reason}`);
  const events = (workflow.events || []).filter(event => event.agent_id === agent.id);
  const latest = events.at(-1);
  content.innerHTML = `<section class="inspector-section"><h3>${wfEscape(agent.name)}</h3><p>${wfEscape(agent.role)} · ${wfEscape(runtimeStateLabel(agent.runtime_state))}</p><p>${wfEscape(agent.description || 'Описание не задано')}</p><dl><dt>Текущая задача</dt><dd>${value(workflow.run?.current_agent_id === agent.id ? workflow.run.current_task : null, 'агент сейчас не выполняется')}</dd><dt>Итерация</dt><dd>${value(workflow.run?.current_agent_id === agent.id ? workflow.run.iteration : null,'нет текущего шага')}</dd><dt>Последнее событие</dt><dd>${latest ? wfEscape(formatWorkflowTime(latest.timestamp)) : 'Н/Д: событий нет'}</dd><dt>Время выполнения</dt><dd>${value(latest?.duration_seconds,'не измерено')}</dd></dl></section>
    <section class="inspector-section"><h3>Конфигурация исполнения</h3><dl><dt>Провайдер</dt><dd>${value(cfg.provider || null,'не назначен')}</dd><dt>Аккаунт</dt><dd>${value(cfg.account || null,'не назначен')}</dd><dt>Модель</dt><dd>${value(cfg.model || null,'не назначена')}</dd><dt>Температура</dt><dd>${value(cfg.temperature,'не задана')}</dd><dt>Макс. токенов</dt><dd>${value(cfg.max_tokens,'не задано')}</dd><dt>Таймаут</dt><dd>${value(cfg.timeout,'не задан')} с</dd></dl><button class="btn btn-secondary btn-sm" id="inspector-model-open">Изменить конфигурацию</button></section>
    <section class="inspector-section"><h3>Agent File</h3><code>${wfEscape(agent.agent_file || 'Н/Д: не задан')}</code><p>${agent.agent_file_exists ? 'Файл доступен' : 'Н/Д: файл отсутствует'}</p><button class="btn btn-secondary btn-sm" id="inspector-file-open">Открыть</button></section>
    <section class="inspector-section"><h3>Инструменты</h3><div class="tool-chips">${agent.tools?.length ? agent.tools.map(tool => `<span>${wfEscape(tool)}</span>`).join('') : 'Н/Д: инструменты не назначены'}</div></section>
    <section class="inspector-section"><h3>Быстрые действия</h3><button class="btn btn-secondary btn-sm" id="inspector-task-open">Перейти к запуску workflow</button></section>`;
  content.append(editor);
  document.getElementById('inspector-model-open').onclick = () => { workflowUi.selectedTab = 'model'; renderWorkflowInspector(currentSnapshot, workflow); };
  document.getElementById('inspector-file-open').onclick = () => openAgentFileEditor(agent);
  document.getElementById('inspector-task-open').onclick = () => document.getElementById('workflow-task').focus();
}

function renderWorkflowStatistics(workflow) {
  const events = workflow.events || [];
  const node = document.getElementById('workflow-statistics-content');
  const run = workflow.run || {};
  node.innerHTML = `<dl><dt>Текущий запуск</dt><dd>${wfEscape(workflowRunLabel(run.status))}</dd><dt>Событий в снапшоте</dt><dd>${events.length}</dd><dt>Событий с ошибкой</dt><dd>${events.filter(event => event.level === 'error').length}</dd></dl><p>Н/Д: API не передаёт агрегаты завершённых workflow. Кольцевая диаграмма не построена.</p>`;
  document.getElementById('workflow-active-task').textContent = run.status === 'running' ? run.current_task || 'Н/Д: текст текущей задачи не передан' : 'Нет выполняющихся workflow';
}

function arrangeWorkflowNodes() {
  if (workflowUi.mode !== 'edit') setWorkflowMode('edit');
  if (workflowUi.mode !== 'edit') return;
  const agents = currentSnapshot?.workflow?.agents || [];
  const start = currentSnapshot?.workflow?.definition?.start_agent_id;
  const ordered = [...agents].sort((a,b) => (a.id === start ? -1 : b.id === start ? 1 : 0));
  ordered.forEach((agent,index) => {
    workflowUi.draftPositions[agent.id] = index === 0 ? {x:430,y:60} : {x:70+((index-1)%3)*360,y:250+Math.floor((index-1)/3)*240};
  });
  markWorkflowDirty();
  renderWorkflowOverview(currentSnapshot);
  fitWorkflowGraph();
}

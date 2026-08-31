/* Shared workspace presentation. All measurements come from HubSnapshot. */
'use strict';
document.addEventListener('DOMContentLoaded', initWorkspaceChrome);

function initWorkspaceChrome() {
  document.getElementById('hub-search-open').onclick = openWorkspaceSearch;
  document.getElementById('hub-settings').onclick = () => switchView('settings');
  document.getElementById('hub-notifications').onclick = () => switchView('logs');
  document.getElementById('analytics-refresh').onclick = fetchSnapshot;
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      openWorkspaceSearch();
    }
  });
  document.querySelectorAll('input,select,textarea').forEach(input => {
    if (!input.labels?.length && !input.hasAttribute('aria-label')) {
      const label = input.closest('.setting-row')?.querySelector('.setting-label')?.textContent;
      input.setAttribute('aria-label', label || input.placeholder || input.id);
    }
  });
}

function openWorkspaceSearch() {
  elements.modalTitle.textContent = 'Поиск по хабу';
  elements.modalBody.innerHTML = '<input id="workspace-search" class="input-text" aria-label="Поиск экранов и агентов" placeholder="Экран, агент, аккаунт…"><div class="command-results" id="workspace-results"></div>';
  elements.modalFooter.innerHTML = '<button class="btn btn-secondary" onclick="closeModal()">Закрыть</button>';
  showModal();
  const input = document.getElementById('workspace-search');
  const render = () => {
    const entries = [...document.querySelectorAll('.nav-item')].map(button => ({
      label: button.querySelector('.nav-label').textContent, action: () => switchView(button.dataset.view),
    }));
    for (const agent of currentSnapshot?.workflow?.agents || []) entries.push({
      label: `Агент · ${agent.name}`, action: () => { switchView('overview'); selectWorkflowAgent(agent.id); fitWorkflowGraph(); },
    });
    for (const profile of Object.values(currentSnapshot?.all_profiles || {})) entries.push({
      label: `Аккаунт · ${profile.display_name || profile.profile_id}`, action: () => { switchView('accounts'); openAccountDetailsModal(profile.profile_id); },
    });
    const target = document.getElementById('workspace-results');
    target.replaceChildren();
    for (const entry of entries.filter(item => item.label.toLowerCase().includes(input.value.toLowerCase())).slice(0,15)) {
      const button = document.createElement('button');
      button.className = 'btn btn-secondary';
      button.textContent = entry.label;
      button.onclick = () => { closeModal(); entry.action(); };
      target.append(button);
    }
    if (!target.children.length) target.textContent = 'Совпадений нет';
  };
  input.oninput = render;
  render();
  input.focus();
}

function renderAccountSummary(snapshot) {
  const profiles = Object.values(snapshot.all_profiles || {}).filter(isConnectedProfile);
  const items = [
    ['Всего аккаунтов', profiles.length, 'Подключённые профили'],
    ['Работает', profiles.filter(p => p.health_state === 'healthy').length, 'Проверенное состояние'],
    ['Лимит исчерпан', profiles.filter(p => p.health_state === 'quota_exhausted').length, 'По состоянию аккаунта'],
    ['Отключено', profiles.filter(p => !p.enabled).length, 'Сохранены в системе'],
    ['Стоимость', 'Н/Д', 'API не передаёт измеренную стоимость'],
  ];
  document.getElementById('account-summary').innerHTML = items.map(([label,value,reason]) => `<div><span>${label}</span><strong>${value}</strong><small>${reason}</small></div>`).join('');
}

function renderAnalyticsCharts(telemetry) {
  renderMetricBars('analytics-token-chart', telemetry.by_provider, 'total_tokens', 'Н/Д: провайдеры ещё не вернули usage');
  renderMetricBars('analytics-role-chart', telemetry.by_role, 'total_calls', 'Н/Д: вызовы по ролям ещё не измерены');
}

function renderMetricBars(id, series, key, reason) {
  const entries = Object.entries(series || {}).filter(([,item]) => Number.isFinite(item[key]));
  const total = entries.reduce((sum,[,item]) => sum + item[key],0);
  const node = document.getElementById(id);
  if (!entries.length || total === 0) { node.textContent = reason; return; }
  node.innerHTML = entries.map(([name,item]) => `<div class="metric-bar"><span>${escapeHtml(name)}</span><meter min="0" max="${total}" value="${item[key]}" aria-label="${escapeHtml(name)}"></meter><strong>${new Intl.NumberFormat('ru-RU').format(item[key])}</strong></div>`).join('');
}

function renderHostResources(container, host) {
  const measured = (value,unit) => Number.isFinite(value) ? `${value}${unit}` : 'Н/Д';
  const items = [
    ['CPU', measured(host.cpu_percent,'%'), 'Загрузка процессора'],
    ['Память', measured(host.memory_percent,'%'), Number.isFinite(host.memory_used_mb) ? `${Math.round(host.memory_used_mb)} / ${Math.round(host.memory_total_mb)} МБ` : 'Н/Д: RAM не измерена'],
    ['GPU', 'Н/Д', 'API не передаёт GPU'],
    ['Диск', measured(host.disk_percent,'%'), Number.isFinite(host.disk_used_gb) ? `${host.disk_used_gb} / ${host.disk_total_gb} ГБ` : 'Н/Д: диск не измерен'],
    ['Сеть', measured(host.net_speed_mbps,' Мбит/с'), Number.isFinite(host.net_speed_mbps) ? 'Скорость между замерами счётчиков' : 'Н/Д: требуется второй замер'],
  ];
  container.innerHTML = items.map(([label,value,reason]) => `<div class="resource-card"><div class="resource-label">${label}</div><div class="resource-value">${value}</div><div class="resource-sub">${value === 'Н/Д' ? `Н/Д: ${label} не получен от API` : reason}</div></div>`).join('');
}

function renderLogDetail(event) {
  const node = document.getElementById('log-detail');
  if (!node) return;
  if (!event) { node.innerHTML = '<h2>Детали события</h2><p>Н/Д: в снапшоте нет событий workflow.</p>'; return; }
  node.innerHTML = `<h2>Детали события</h2><p>${escapeHtml(event.message)}</p><p>Уровень: ${escapeHtml(event.level || 'Н/Д')}</p><p>Агент: ${escapeHtml(event.agent_id || 'Н/Д: не указан')}</p><p>Время: ${escapeHtml(event.timestamp)}</p><pre>${escapeHtml(JSON.stringify({type:event.type,run_id:event.run_id,iteration:event.iteration,provider:event.provider,account:event.account,model:event.model,duration_seconds:event.duration_seconds,error:event.error},null,2))}</pre>`;
}

function providerModels(snapshot, provider) {
  const summary = (snapshot.providers || []).find(item => item.provider_id === provider);
  return { models: summary?.discovered_models || [], received: Boolean(summary?.last_refresh_at) };
}

function modelOptions(snapshot, profile, selected) {
  const { models, received } = providerModels(snapshot, profile.provider);
  let html = '';
  if (selected && !models.includes(selected)) html += `<option value="${escapeHtml(selected)}" selected disabled>${escapeHtml(selected)} · доступность не подтверждена</option>`;
  if (!models.length) html += `<option value="" disabled ${selected ? '' : 'selected'}>${received ? 'Доступных моделей нет' : 'Список моделей ещё не получен'}</option>`;
  html += models.map(model => `<option value="${escapeHtml(model)}" ${model === selected ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('');
  if (!selected && models.length) html = '<option value="" selected disabled>Выберите модель</option>'+html;
  return html;
}

function routeQuota(profile, snapshot) {
  const quota = profile.quota_snapshot || snapshot.quotas?.[profile.profile_id] || {};
  if (!quota.buckets?.length) return `<div class="route-quota">${quota.is_loading ? 'Квоты загружаются' : 'Н/Д: '+escapeHtml(quota.unavailable_reason || 'провайдер не передаёт квоту')}</div>`;
  return quota.buckets.map(bucket => {
    const pct = bucket.remaining_percent;
    if (!Number.isFinite(pct)) return `<div class="route-quota">${escapeHtml(bucket.label || 'Квота')}: Н/Д</div>`;
    return `<div class="route-quota">${escapeHtml(bucket.label || 'Квота')}: ${pct}%<div class="quota-bar-track"><div class="quota-bar-fill" style="width:${Math.max(0,Math.min(100,pct))}%;background:var(--status-${pct < 20 ? 'error' : pct < 50 ? 'warning' : 'healthy'})"></div></div></div>`;
  }).join('');
}

function renderAccountRouting() {
  if (!currentSnapshot) return;
  const snapshot = currentSnapshot;
  const profiles = snapshot.all_profiles || {};
  const routing = snapshot.routing || {};
  const left = document.getElementById('routing-roles-container');

  const defRoleSelect = document.getElementById('routing-default-role-select');
  if (defRoleSelect) {
    const currentDef = snapshot.metrics?.default_role || 'manager';
    defRoleSelect.value = currentDef;
    defRoleSelect.onchange = async () => {
      const res = await executeAction('set_default_role', { default_role: defRoleSelect.value });
      if (res && res.ok) {
        showToast(`Роль по умолчанию изменена на '${defRoleSelect.value}'`, 'success');
        await fetchSnapshot();
      }
    };
  }

  left.innerHTML = Object.entries(routing).map(([roleId,pipeline]) => {
    const agent = (snapshot.workflow?.agents || []).find(item => item.role === roleId);
    const role = (snapshot.agents || []).find(item => item.role_id === roleId);

    let responderStatusHtml = '';
    if (!pipeline.will_bypass && pipeline.effective_answering_profile) {
      const respProfile = profiles[pipeline.effective_answering_profile] || { profile_id: pipeline.effective_answering_profile };
      const respModel = pipeline.effective_answering_model || 'default';
      const nodeIdx = (pipeline.nodes || []).findIndex(n => n.profile_id === pipeline.effective_answering_profile);
      const prioLabel = nodeIdx === 0 ? 'Основной (#1)' : `Запасной (#${nodeIdx + 1})`;
      responderStatusHtml = `<div class="role-answering-status healthy">🟢 Сейчас ответит: <strong>${escapeHtml(respProfile.display_name || pipeline.effective_answering_profile)}</strong> (${escapeHtml(respModel)}) — ${prioLabel}</div>`;
    } else {
      const reason = pipeline.bypass_reason || 'цепочка пуста — вызов уйдёт мимо хаба в Hermes';
      responderStatusHtml = `<div class="role-answering-status warning">⚠️ Сейчас ответит: <strong>никто</strong> (${escapeHtml(reason)})</div>`;
    }

    const rows = (pipeline.nodes || []).map((node,index) => {
      const profile = profiles[node.profile_id] || {profile_id:node.profile_id,provider:node.provider};
      const quota = profile.quota_snapshot || snapshot.quotas?.[node.profile_id] || {};
      const reset = (quota.buckets || []).map(b => b.reset_time_formatted || b.reset_after_formatted).filter(Boolean).join('; ');
      return `<div class="account-row draggable-item" draggable="true" data-pid="${escapeHtml(node.profile_id)}" data-role="${escapeHtml(roleId)}"><div class="drag-handle">⠿</div><div class="route-priority">${index ? 'Резерв '+index : 'Основной'}</div><div><strong>${escapeHtml(profile.display_name || node.profile_id)}</strong><div class="text-muted">${escapeHtml(node.account_identity || profile.account_identity || node.provider)}</div></div><div><select data-route-model="${escapeHtml(node.profile_id)}" data-role="${escapeHtml(roleId)}" aria-label="Модель ${escapeHtml(node.profile_id)}">${modelOptions(snapshot,profile,node.model)}</select></div><div>${routeQuota(profile,snapshot)}</div><div class="text-muted">${escapeHtml(reset || 'Н/Д: нет времени сброса')}</div><div><span class="status-dot ${healthDotClass(node.status)}"></span> ${escapeHtml(node.status_label_ru || 'Не проверялся')}${node.is_active ? '<br>Используется' : ''}</div><button class="route-remove" data-remove-profile="${escapeHtml(node.profile_id)}" data-role="${escapeHtml(roleId)}" aria-label="Удалить из маршрута">×</button></div>`;
    }).join('');
    return `<section class="role-section"><header class="role-header"><div><h4>${escapeHtml(agent?.name || pipeline.role_name_ru || roleId)}</h4><p class="text-muted">${escapeHtml(agent?.description || role?.role_description_ru || '')}</p></div><button class="btn btn-secondary btn-sm" data-add-role="${escapeHtml(roleId)}">+ Добавить аккаунт</button></header>${responderStatusHtml}<div class="grid-header"><span></span><span>Приоритет</span><span>Аккаунт</span><span>Модель</span><span>Квота · остаток</span><span>Сброс</span><span>Статус</span><span></span></div><div class="role-chain-list">${rows || '<p class="inspector-value">Аккаунты не назначены. Добавьте подключённый аккаунт.</p>'}</div><div class="drop-zone" data-role="${escapeHtml(roleId)}">+ Перетащите аккаунт в конец маршрута</div><p class="inspector-value">Session Affinity: ${pipeline.session_affinity ? 'включена' : 'отключена'} · Порядок применяется к следующим назначениям</p></section>`;
  }).join('') || '<p class="view-header-note">Агенты ещё не созданы. Добавьте агента на «Обзоре».</p>';
  left.querySelectorAll('[data-add-role]').forEach(button => button.onclick = () => openAddNodeToChainModal(button.dataset.addRole));
  left.querySelectorAll('[data-remove-profile]').forEach(button => button.onclick = () => removeProfileFromChain(button.dataset.role,button.dataset.removeProfile));
  left.querySelectorAll('[data-route-model]').forEach(select => select.onchange = () => executeAction('set_model',{profile_id:select.dataset.routeModel,model:select.value}));
  renderAvailableRoutingAccounts(snapshot);
  setupDragAndDrop();
}

function renderAvailableRoutingAccounts(snapshot) {
  const profiles = Object.values(snapshot.all_profiles || {}).filter(isConnectedProfile);
  const provider = document.getElementById('routing-filter-provider');
  const status = document.getElementById('routing-filter-status');
  for (const [select,field,title] of [[provider,'provider','Все провайдеры'],[status,'health_state','Все состояния']]) {
    const selected = select.value;
    select.innerHTML = `<option value="all">${title}</option>`+[...new Set(profiles.map(p => p[field]))].map(value=>`<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
    select.value = [...select.options].some(option => option.value === selected) ? selected : 'all';
    select.onchange = renderAccountRouting;
  }
  const search = document.getElementById('routing-account-search');
  search.oninput = renderAccountRouting;
  const query = search.value.toLowerCase();
  const filtered = profiles.filter(p => (provider.value === 'all' || p.provider === provider.value) && (status.value === 'all' || p.health_state === status.value) && [p.profile_id,p.display_name,p.account_identity,p.provider,...providerModels(snapshot,p.provider).models].join(' ').toLowerCase().includes(query));
  document.getElementById('available-accounts-count').textContent = `${filtered.length} из ${profiles.length}`;
  const container = document.getElementById('routing-available-container');
  container.innerHTML = filtered.map(p=>`<article class="available-account-card draggable-item" draggable="true" data-pid="${escapeHtml(p.profile_id)}" data-source="available"><img src="/static/${getProviderIcon(p.provider)}" width="28" height="28" alt=""><div><strong>${escapeHtml(p.display_name || p.profile_id)}</strong><p class="text-muted">${escapeHtml(p.account_identity || p.provider)}</p><p>${escapeHtml(p.health_label_ru || 'Не проверялся')}</p>${routeQuota(p,snapshot)}<small>Модели: ${providerModels(snapshot,p.provider).received ? providerModels(snapshot,p.provider).models.length : 'список ещё не получен'}</small></div><button class="btn btn-secondary btn-sm" data-route-add="${escapeHtml(p.profile_id)}" aria-label="Добавить аккаунт в маршрут">+</button></article>`).join('') || '<p class="inspector-value">Нет подходящих подключённых аккаунтов. Подключите аккаунт на странице «Аккаунты».</p>';
  container.querySelectorAll('[data-route-add]').forEach(button=>button.onclick=()=>{
    elements.modalTitle.textContent='Выберите агента';
    elements.modalBody.innerHTML='<div class="command-results">'+Object.entries(snapshot.routing || {}).map(([id,route])=>`<button class="btn btn-secondary" data-target-role="${escapeHtml(id)}">${escapeHtml(route.role_name_ru || id)}</button>`).join('')+'</div>';
    elements.modalFooter.innerHTML=''; showModal();
    elements.modalBody.querySelectorAll('[data-target-role]').forEach(target=>target.onclick=()=>{closeModal();handleDropMove(button.dataset.routeAdd,null,target.dataset.targetRole,-1);});
  });
}

function initSnapshotSettings() {
  // The snapshot intentionally has no server settings. Never present defaults
  // as fetched values or write untouched defaults back to the server.
  for (const id of ['setting-server-host','setting-server-port','setting-server-token-input','setting-quota-interval']) {
    const input = document.getElementById(id);
    input.disabled = true;
    input.title = 'Н/Д: настройки сервера не входят в /api/snapshot';
    if (input.tagName === 'SELECT') input.innerHTML = '<option>Н/Д: нет в снапшоте</option>';
    else input.placeholder = 'Н/Д: нет в снапшоте';
  }
  document.getElementById('setting-token-status-badge').textContent = 'Н/Д: не передаётся';
  for (const id of ['setting-quota-threshold-percent','setting-quota-threshold-action','setting-email-masking-mode']) {
    const input = document.getElementById(id);
    const unknown = document.createElement('option');
    unknown.value = ''; unknown.textContent = 'Н/Д: текущее значение не передано'; unknown.selected = true; unknown.disabled = true;
    input.prepend(unknown);
  }
  document.getElementById('setting-source-mode').innerHTML = '<option>Live API (/api/snapshot)</option>';
  document.getElementById('setting-source-mode').disabled = true;
  document.getElementById('setting-source-mode').closest('.setting-row').querySelector('.setting-desc').textContent = 'Рабочие данные поступают только из снапшота. Автоматической подмены демонстрационными данными нет.';
}

document.addEventListener('DOMContentLoaded', initSnapshotSettings);

function arrangeSettingsPanels() {
  const view = document.getElementById('view-settings');
  const first = view.querySelector('.settings-card');
  const groups = [
    ['Общие настройки',['setting-default-role','setting-theme']],
    ['Управление квотами',['setting-quota-interval','setting-quota-threshold-percent','setting-quota-threshold-action']],
    ['Безопасность и API',['setting-server-host','setting-server-token-input','setting-email-masking-mode']],
  ];
  for (const [title,ids] of groups) {
    const card = document.createElement('section'); card.className='settings-card';
    const heading=document.createElement('h2'); heading.className='settings-group-title'; heading.textContent=title; card.append(heading);
    for (const id of ids) card.append(document.getElementById(id).closest('.setting-row'));
    if (title === 'Управление квотами') card.append(document.getElementById('btn-save-hub-settings').closest('.settings-actions'));
    view.insertBefore(card, first);
  }
  first.remove();
}
document.addEventListener('DOMContentLoaded', arrangeSettingsPanels);

function renderHealthPanels(snapshot) {
  const box=document.getElementById('health-workspace');
  if (!box) return;
  const providers=snapshot.providers || [];
  box.innerHTML=`<section class="section-card"><h2 class="section-card-title">Подключения провайдеров</h2>${providers.map(provider=>`<dl><dt>${escapeHtml(provider.provider_name)}</dt><dd>${provider.connected_count} подключено · ${provider.online_count} готово</dd></dl>`).join('') || '<p>Подключений нет</p>'}</section><section class="section-card"><h2 class="section-card-title">Хранилища и температуры</h2><p>Загрузка системного диска показана выше.</p><p>Н/Д: API не передаёт список томов, температуры и состояние резервного копирования.</p></section><section class="section-card"><h2 class="section-card-title">Состояние в реальном времени</h2><dl><dt>Активных вызовов</dt><dd>${snapshot.metrics?.active_calls_total ?? 'Н/Д'}</dd><dt>Снапшот</dt><dd>${snapshot.is_stale ? 'Устарел' : 'Актуален'}</dd></dl><p>Н/Д: API не передаёт uptime отдельных служб и историю сетевой активности.</p><button class="btn btn-secondary" id="health-events-open">Журнал событий →</button></section>`;
  document.getElementById('health-events-open').onclick=()=>switchView('logs');
}

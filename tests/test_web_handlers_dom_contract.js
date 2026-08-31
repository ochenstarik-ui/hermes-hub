/**
 * Test contract for Hermes Hub Web Client app.js handlers.
 * Tests that all dangling handlers are defined, can be called in a simulated browser environment,
 * and that startup execution (DOMContentLoaded checkUpdates) does not throw ReferenceError.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const appJsPath = path.resolve(__dirname, '../src/antigravity_provider/router/web/static/app.js');
const appJsCode = fs.readFileSync(appJsPath, 'utf8');

const executedActions = [];

function createMockElement(id = '', tag = 'div') {
  const el = {
    id,
    tagName: tag.toUpperCase(),
    value: '',
    textContent: '',
    innerText: '',
    innerHTML: '',
    className: '',
    disabled: false,
    dataset: {},
    classList: {
      _classes: new Set(),
      add: function (...cls) { cls.forEach(c => this._classes.add(c)); },
      remove: function (...cls) { cls.forEach(c => this._classes.delete(c)); },
      toggle: function (cls, force) {
        if (force !== undefined) {
          if (force) this._classes.add(cls); else this._classes.delete(cls);
        } else {
          if (this._classes.has(cls)) this._classes.delete(cls); else this._classes.add(cls);
        }
      },
      contains: function (cls) { return this._classes.has(cls); },
    },
    style: {},
    setAttribute: () => {},
    removeAttribute: () => {},
    getAttribute: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
    appendChild: (child) => child,
    removeChild: (child) => child,
    remove: () => {},
    focus: () => {},
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  return el;
}

const elementsMap = new Map();
function getOrCreateElement(id, tag = 'div') {
  if (!elementsMap.has(id)) {
    elementsMap.set(id, createMockElement(id, tag));
  }
  return elementsMap.get(id);
}

const mockDoc = {
  addEventListener: (event, cb) => {
    if (event === 'DOMContentLoaded') {
      mockDoc._domContentLoadedCb = cb;
    }
  },
  getElementById: (id) => getOrCreateElement(id),
  querySelector: (sel) => getOrCreateElement(sel.replace(/^[#.]/, '')),
  querySelectorAll: (sel) => [getOrCreateElement(sel.replace(/^[#.]/, ''))],
  createElement: (tag) => createMockElement('', tag),
  body: getOrCreateElement('body'),
  location: { search: '', protocol: 'http:', hostname: '127.0.0.1' },
};

const mockWindow = {
  // P0-1: expose elementsMap so app.js can call elementsMap.clear() on openAddAccountWizard
  elementsMap,
  location: { search: '', protocol: 'http:', hostname: '127.0.0.1' },
  document: mockDoc,
  localStorage: {
    _data: {},
    getItem: (k) => mockWindow.localStorage._data[k] || '',
    setItem: (k, v) => { mockWindow.localStorage._data[k] = String(v); },
    removeItem: (k) => { delete mockWindow.localStorage._data[k]; },
  },
  setInterval: (fn) => setTimeout(fn, 100000),
  clearInterval: (id) => clearTimeout(id),
  setTimeout: (fn, ms) => {
    // If setTimeout with 0 or small ms, don't block
    return setTimeout(fn, ms);
  },
  clearTimeout: (id) => clearTimeout(id),
  fetch: async (url, opts = {}) => {
    if (url.includes('/api/action')) {
      const payload = JSON.parse(opts.body || '{}');
      executedActions.push(payload);
      const act = payload.action;
      if (act === 'start_device_auth') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            message: 'Код устройства получен',
            data: { session_id: 'sess-dev-1', url: 'https://grok.com/device', code: 'GRK-1234', profile_id: 'grok-1' }
          }),
        };
      }
      if (act === 'start_redirect_auth') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            message: 'Ссылка получена',
            data: { session_id: 'sess-redir-1', url: 'https://accounts.google.com/o/oauth2/auth?...', port: 5801, profile_id: 'ag-w1', provider: payload.data?.provider || 'antigravity' }
          }),
        };
      }
      if (act === 'check_updates') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            message: 'Проверка обновлений завершена',
            data: { update_available: true, current_version: '0.1.1', latest_commit: 'abcdef123456', installed_commit: '1234567890ab' }
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, message: 'Action executed', data: {} }),
      };
    }
    if (url.includes('/api/snapshot')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          seq: 1,
          all_profiles: {
            'ag-w1': { profile_id: 'ag-w1', provider: 'antigravity', display_name: 'Antigravity 1', preferred_models: ['gemini-2.5-pro'] }
          },
          routing: {
            'coder-primary': { role_name_ru: 'Основной кодер', nodes: [{ profile_id: 'ag-w1', provider: 'antigravity' }] }
          },
          providers: [
            { provider_id: 'antigravity', provider_name: 'Google Antigravity', discovered_models: ['gemini-2.5-pro', 'gemini-2.5-flash'] }
          ],
          agents: [],
          settings: {},
        }),
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({}),
    };
  },
  console: {
    log: () => {},
    warn: () => {},
    error: () => {},
    info: () => {},
  },
  URLSearchParams: class {
    constructor(str) { this.str = str; }
    get() { return null; }
  },
};

mockWindow.window = mockWindow;
mockWindow.document = mockDoc;
mockDoc.defaultView = mockWindow;

const sandbox = {
  ...mockWindow,
  global: mockWindow,
  globalThis: mockWindow,
};
// P0-1: expose elementsMap in sandbox so app.js can call elementsMap.clear()
sandbox.elementsMap = elementsMap;

vm.createContext(sandbox);

try {
  vm.runInContext(appJsCode, sandbox);
} catch (err) {
  console.error('FAILED TO EVALUATE app.js in sandbox:', err);
  process.exit(1);
}

const requiredHandlers = [
  'openAddAccountWizard',
  'handleNodeAccountChange',
  'handleNodeModelChange',
  'handleRefreshProviderModels',
  'checkUpdates',
];

for (const handler of requiredHandlers) {
  if (typeof sandbox[handler] !== 'function') {
    console.error(`RED ERROR: ${handler} is NOT defined as a function in app.js!`);
    process.exit(1);
  }
}

async function runTests() {
  console.log('1. Testing DOMContentLoaded startup without ReferenceError...');
  assert(typeof mockDoc._domContentLoadedCb === 'function', 'DOMContentLoaded listener was not registered');
  mockDoc._domContentLoadedCb();

  console.log('2. Testing checkUpdates handler execution...');
  await sandbox.checkUpdates(true);
  const checkAction = executedActions.find(a => a.action === 'check_updates');
  assert(checkAction, 'checkUpdates did not trigger check_updates action');

  console.log('3. Testing openAddAccountWizard & Step 1...');
  sandbox.openAddAccountWizard();
  const modalBody = getOrCreateElement('modal-body');
  assert(modalBody.innerHTML.includes('Шаг 1 из 3'), 'Wizard Step 1 did not render');

  console.log('4. Testing showWizardStep2 for grok (device auth flow)...');
  sandbox.showWizardStep2('grok');
  // GAP-1: grok/codex now shows slot picker first; startDeviceAuth is user-initiated
  const deviceSlot = getOrCreateElement('wiz-device-slot');
  deviceSlot.value = 'ag-w1';
  await sandbox.startDeviceAuth('grok');
  const devAuthAction = executedActions.find(a => a.action === 'start_device_auth');
  assert(devAuthAction, 'startDeviceAuth(grok) did not trigger start_device_auth action');
  // P0-1 BUG-2: startDeviceAuth must send profile_id in payload
  assert(
    devAuthAction.data && devAuthAction.data.profile_id === 'ag-w1',
    `BUG-2: startDeviceAuth must include profile_id='ag-w1' in start_device_auth payload, got: ${JSON.stringify(devAuthAction.data)}`
  );

  console.log('4b. Testing slot persistence through proceedToWizardStep3 -> finishAddAccount...');
  // Reset: fresh wizard, grok flow with owner-selected slot
  sandbox.openAddAccountWizard();
  sandbox.showWizardStep2('grok');
  const slotForStep3 = getOrCreateElement('wiz-device-slot');
  slotForStep3.value = 'owner-slot-42';
  // proceedToWizardStep3 replaces modalBody (destroying wiz-device-slot)
  sandbox.proceedToWizardStep3('grok');
  // finishAddAccount reads from destroyed selects — P0-1 BUG-1: profile_id must survive
  const targetRoleForStep3 = getOrCreateElement('wiz-target-role');
  targetRoleForStep3.value = 'coder-primary';
  await sandbox.finishAddAccount('grok');
  const addAccFromStep3 = executedActions.find(a => a.action === 'add_account');
  assert(addAccFromStep3, 'finishAddAccount did not trigger add_account after step3');
  // P0-1 BUG-1: profile_id must be owner-selected slot, NOT empty
  assert(
    addAccFromStep3.data && addAccFromStep3.data.profile_id === 'owner-slot-42',
    `BUG-1: finishAddAccount profile_id must be 'owner-slot-42' (owner choice persisted), got: ${JSON.stringify(addAccFromStep3.data)}`
  );

  console.log('5. Testing showWizardStep2 for antigravity (redirect auth flow)...');
  sandbox.showWizardStep2('antigravity');
  const redirectSlot = getOrCreateElement('wiz-redirect-slot');
  redirectSlot.value = 'ag-w1';
  await sandbox.startRedirectAuth('antigravity');
  const redirAuthAction = executedActions.find(a => a.action === 'start_redirect_auth');
  assert(redirAuthAction, 'startRedirectAuth(antigravity) did not trigger start_redirect_auth action');

  console.log('6. Testing showWizardStep2 for local and finishAddAccount...');
  // Reset wizard state (including elementsMap) before local flow to prevent stale slot elements
  sandbox.openAddAccountWizard();
  sandbox.showWizardStep2('local');
  const baseInput = getOrCreateElement('wiz-base-url-input');
  baseInput.value = 'http://127.0.0.1:8081/v1';
  sandbox.proceedToWizardStep3('local');
  const targetRole = getOrCreateElement('wiz-target-role');
  targetRole.value = 'coder-primary';
  await sandbox.finishAddAccount('local');
  // Use [...].reverse().find() to get the LAST add_account action (test 6's, not test 4b's)
  const addAccAction = [...executedActions].reverse().find(a => a.action === 'add_account');
  assert(addAccAction, 'finishAddAccount did not trigger add_account action');
  assert.strictEqual(addAccAction.data.base_url, 'http://127.0.0.1:8081/v1');
  // P0-1: local flow has no slot selector, profile_id should be empty/undefined
  assert(
    !addAccAction.data.profile_id,
    `BUG-1: local flow should not have a device slot profile_id, got: ${JSON.stringify(addAccAction.data)}`
  );

  console.log('7. Testing handleNodeAccountChange...');
  await sandbox.handleNodeAccountChange('coder-primary', 'ag-w1', true);
  const assignRoleAction = executedActions.find(a => a.action === 'assign_role');
  assert(assignRoleAction, 'handleNodeAccountChange did not trigger assign_role action');
  assert.strictEqual(assignRoleAction.data.profile_id, 'ag-w1');

  console.log('8. Testing handleNodeModelChange...');
  await sandbox.handleNodeModelChange('coder-primary', 'ag-w1', 'gemini-2.5-flash');
  const setModelAction = executedActions.find(a => a.action === 'set_model');
  assert(setModelAction, 'handleNodeModelChange did not trigger set_model action');
  assert.strictEqual(setModelAction.data.model, 'gemini-2.5-flash');

  console.log('9. Testing handleRefreshProviderModels...');
  await sandbox.handleRefreshProviderModels('antigravity');
  const refreshModelsAction = executedActions.find(a => a.action === 'refresh_models');
  assert(refreshModelsAction, 'handleRefreshProviderModels did not trigger refresh_models action');

  console.log('\nAll targeted Node.js DOM and contract test assertions PASSED successfully!');
  process.exit(0);
}

runTests().catch(err => {
  console.error('\nTEST FAILURE:', err);
  process.exit(1);
});

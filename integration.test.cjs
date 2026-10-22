const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('shows a connection warning when session restoration cannot reach the API', async () => {
  const app = { innerHTML: '' };
  const context = {
    window: {},
    state: { page: 'overview' },
    roles: {},
    demoRequests: [],
    document: {
      addEventListener() {},
      querySelector(selector) { return selector === '#app' ? app : null; },
      querySelectorAll() { return []; },
    },
    Headers,
    fetch: async () => { throw new TypeError('offline'); },
    login() {},
    wizard() { return ''; },
    render() {},
    toast() {},
    esc(value) { return String(value); },
    emptyStudent() {},
    selectedSupervisorId() {},
    readProject() {},
  };

  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'frontend', 'integration.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));

  assert.match(context.state.apiError, /تعذر الاتصال بالخادم/);
  assert.match(app.innerHTML, /role="alert"/);
  assert.match(app.innerHTML, /تعذر الاتصال بالخادم/);
});

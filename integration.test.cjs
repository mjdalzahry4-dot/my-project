const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('shows a connection warning when session restoration cannot reach the API', async () => {
  const app = { innerHTML: '' };
  const context = {
    window: { addEventListener() {} },
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

test('dashboard primary actions lead each role to its own workflow', async () => {
  const roles = {
    dean: { name: 'عميد تجريبي', label: 'عميد الكلية', system: 'رئيس النظام', initials: 'ع' },
    chair: { name: 'رئيس تجريبي', label: 'رئيس القسم', system: 'رئيس القسم', initials: 'ر' },
    supervisor: { name: 'مشرف تجريبي', label: 'المشرف الأكاديمي', system: 'مشرف أكاديمي', initials: 'م' },
    student: { name: 'طالب تجريبي', label: 'الطالب', system: 'طالب', initials: 'ط' },
  };
  const context = {
    window: { addEventListener() {}, sessionStorage: { getItem() { return ''; }, setItem() {}, removeItem() {} } },
    state: { role: 'student', apiUser: { display_name: 'طالب تجريبي' }, projects: [], groups: [], apiError: '' },
    roles, serverRequests: [], demoRequests: [],
    document: { addEventListener() {}, querySelector() { return { innerHTML: '' }; }, querySelectorAll() { return []; } },
    Headers,
    fetch: async () => ({ ok: false, status: 401, json: async () => ({ detail: 'unauthorized' }) }),
    login() {}, wizard() { return ''; }, render() {}, toast() {},
    esc(value) { return String(value); }, stat(label, value) { return `<span>${label}:${value}</span>`; },
    requestRows() { return ''; }, statusPill(value) { return value; }, connectionNotice() { return ''; },
    emptyStudent() {}, selectedSupervisorId() {}, readProject() {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'frontend', 'integration.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));

  const expectedActions = {
    dean: /data-page="requests"/,
    chair: /data-action="new-group"/,
    supervisor: /data-page="projects"/,
    student: /data-page="project"/,
  };
  for (const [role, expected] of Object.entries(expectedActions)) {
    context.state.role = role;
    const markup = context.dashboard();
    assert.match(markup, expected, `${role} should have a role-specific primary action`);
    if (role === 'student' || role === 'supervisor') assert.doesNotMatch(markup, /data-page="requests"/);
  }
  context.state.role = 'chair';
  context.state.page = 'drafts';
  assert.match(context.genericPage(), /لا توجد مسودات|استكمال الطلب/);
  context.state.page = 'calendar';
  assert.match(context.genericPage(), /لا توجد مواعيد قادمة/);
  assert.match(context.genericPage(), /appointment-form/);
  context.state.role = 'dean';
  context.state.page = 'users';
  context.state.users = [{ id: 'student-1', username: 'student.pending', display_name: 'طالب تجريبي', role: 'student', role_label: 'الطالب', account_status: 'activation_pending', department: null }];
  assert.match(context.genericPage(), /users-filter-form/);
  assert.match(context.genericPage(), /تفعيل الحساب/);
  context.state.apiToken = 'expired-test-token';
  await assert.rejects(context.apiRequest('/projects/'), /انتهت جلسة الدخول/);
  assert.equal(context.state.role, null, 'expired sessions should return to the sign-in screen');
});

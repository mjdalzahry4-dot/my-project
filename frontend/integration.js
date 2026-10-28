/* واجهة المرحلة الخامسة: ربط الشاشة بواجهات GPMS الفعلية. */
const API_BASE = (window.GPMS_API_BASE_URL || 'http://localhost:8001/api/v1').replace(/\/$/, '');
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const backendRoleToUi = { dean: 'dean', department_chair: 'chair', supervisor: 'supervisor', student: 'student' };
const apiRoleLabels = { dean: ['عميد الكلية', 'رئيس النظام'], chair: ['رئيس القسم', 'رئيس القسم'], supervisor: ['المشرف الأكاديمي', 'مشرف أكاديمي'], student: ['الطالب', 'طالب'] };
state.apiUser = null;
state.departments = [];
state.supervisors = [];
state.apiError = '';
state.apiToken = readStoredApiToken();
state.projects = [];
state.groups = [];
state.users = [];
state.userSearch = '';
state.userSearchInput = '';
state.userRoleFilter = 'all';
state.auditEvents = [];
state.draftRequestId = null;
state.projectNotes = [];
state.currentProjectId = null;
state.projectDetail = null;
state.deliverables = [];

async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (state.apiToken && !headers.has('Authorization')) headers.set('Authorization', `Token ${state.apiToken}`);
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, method, headers, credentials: 'omit' });
  } catch (error) {
    throw new Error('تعذر الاتصال بالخادم. تحقق من رابط API وإعدادات الاستضافة.');
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && state.apiToken && !path.endsWith('/auth/login/')) {
      clearStoredApiToken();
      throw new Error('انتهت جلسة الدخول. سجّل الدخول مرة أخرى للمتابعة.');
    }
    const labels = { group_code: 'رمز المجموعة', project_title: 'عنوان المشروع', project_description: 'وصف المشروع', academic_year: 'العام الدراسي', department_id: 'القسم', members: 'بيانات الطلاب', supervisor: 'بيانات المشرف', full_name: 'الاسم الكامل', username: 'اسم المستخدم', phone: 'رقم الجوال' };
    const messages = [];
    const collectMessages = value => {
      if (typeof value === 'string') messages.push(value);
      else if (Array.isArray(value)) value.forEach(collectMessages);
      else if (value && typeof value === 'object') Object.values(value).forEach(collectMessages);
    };
    if (data.detail) collectMessages(data.detail);
    else Object.entries(data).forEach(([field, value]) => {
      const start = messages.length;
      collectMessages(value);
      if (messages.length > start) messages[start] = `${labels[field] || field}: ${messages[start]}`;
    });
    throw new Error(messages.join(' ') || 'تعذر إتمام العملية. راجع الحقول المطلوبة ثم أعد المحاولة.');
  }
  return data;
}

function readStoredApiToken() {
  try { return window.sessionStorage?.getItem('gpms_api_token') || ''; }
  catch (_) { return ''; }
}

function saveStoredApiToken(token) {
  state.apiToken = token;
  try {
    if (token) window.sessionStorage?.setItem('gpms_api_token', token);
    else window.sessionStorage?.removeItem('gpms_api_token');
  } catch (_) { /* The in-memory token still works until this tab is closed. */ }
}

function clearStoredApiToken() {
  saveStoredApiToken('');
  state.apiUser = null;
  state.role = null;
}

function safeDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('ar-SA', { year: 'numeric', month: 'short', day: 'numeric' });
}

function uiRequest(item) {
  const revision = item.current_revision || {};
  const supervisor = revision.supervisor || {};
  const decision = (item.decisions || []).at(-1);
  const status = item.status === 'pending_approval' ? 'pending' : item.status;
  return {
    id: item.id, version: item.version, status,
    code: revision.group_code_proposed || '—',
    title: revision.project_title || 'طلب غير مكتمل',
    department: revision.department?.name || '—',
    departmentId: revision.department?.id || '',
    members: (revision.members || []).length,
    supervisor: supervisor.full_name || supervisor.username_proposed || 'مشرف مسجل',
    date: safeDate(item.submitted_at || item.created_at),
    year: revision.academic_year || '—',
    desc: revision.project_description || '',
    students: (revision.members || []).map(member => `${member.full_name} · ${member.username_proposed} · ${member.phone_proposed}`),
    memberDetails: revision.members || [], supervisorDetail: supervisor,
    notes: decision?.note || '', decisions: item.decisions || [], revision,
  };
}

async function loadRequests() {
  const list = await apiRequest('/group-requests/');
  serverRequests.splice(0, serverRequests.length, ...list.map(uiRequest));
}

async function loadPageData() {
  state.apiError = '';
  try {
    if (['overview', 'requests', 'detail', 'drafts'].includes(state.page) && state.role !== 'student' && state.role !== 'supervisor') await loadRequests();
    if (['groups', 'overview'].includes(state.page)) state.groups = await apiRequest('/groups/');
    if (state.page === 'users' && state.role === 'dean') state.users = await apiRequest('/users/');
    if (['projects', 'project', 'overview', 'notes'].includes(state.page)) {
      state.projects = await apiRequest('/projects/');
      if (['project', 'notes'].includes(state.page) && !state.currentProjectId) state.currentProjectId = state.projects[0]?.id || null;
    }
    if (state.page === 'deliverables' && ['student', 'supervisor'].includes(state.role)) {
      state.projects = await apiRequest('/projects/');
      if (!state.currentProjectId || !state.projects.some(project => project.id === state.currentProjectId)) state.currentProjectId = state.projects[0]?.id || null;
      state.deliverables = state.currentProjectId ? await apiRequest(`/projects/${state.currentProjectId}/deliverables/`) : [];
    }
    if (state.page === 'project' && state.currentProjectId) state.projectDetail = await apiRequest(`/projects/${state.currentProjectId}/`);
    if (state.page === 'notes' && state.currentProjectId) state.projectNotes = await apiRequest(`/projects/${state.currentProjectId}/notes/`);
    if (state.page === 'audit' && state.role === 'dean') state.auditEvents = await apiRequest('/audit-log/');
  } catch (error) {
    state.apiError = error.message;
  }
}

function connectionNotice() {
  return state.apiError ? `<div class="notice warn" role="alert">${esc(state.apiError)}</div>` : '';
}

function apiStatusName(value) {
  return value === 'pending_approval' ? 'pending' : value;
}

const originalLogin = login;
login = function connectedLogin() {
  document.querySelector('#app').innerHTML = `<div class="login-page"><section class="login-art"><div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div><div class="brand-sub">Graduation Projects Management System</div></div></div><div class="art-copy"><div class="eyebrow">GPMS · بوابتك الأكاديمية</div><h1>من فكرة التخرج<br>إلى إنجاز يُفتخر به</h1><p>مساحة موحّدة تجمع الطالب والمشرف والقسم والكلية في رحلة المشروع.</p></div><div class="art-foot">اتصال آمن بالخادم · صلاحيات حسب الحساب</div></section><section class="login-panel"><form class="login-box" id="login-form"><div class="eyebrow">مرحبًا بك</div><h2>تسجيل الدخول</h2><p>استخدم اسم المستخدم وكلمة المرور المسجلين في النظام.</p><div class="field"><label for="login-user">اسم المستخدم</label><input id="login-user" autocomplete="username" placeholder="اسم المستخدم" required /></div><div class="field"><label for="login-password">كلمة المرور</label><div class="input-wrap"><input id="login-password" type="password" autocomplete="current-password" placeholder="كلمة المرور" required /><button type="button" class="ghost-eye" data-action="toggle-password">إظهار</button></div></div>${connectionNotice()}<button type="submit" class="btn btn-primary btn-block">تسجيل الدخول <span>←</span></button><p class="help">لا يُسمح باختيار الدور يدويًا؛ يحدد النظام الصلاحيات من الحساب.</p></form></section></div>`;
};

function startAsAuthenticated(user) {
  const role = backendRoleToUi[user.role];
  if (!role) throw new Error('نوع الحساب غير مدعوم في الواجهة.');
  state.apiUser = user;
  state.role = role;
  roles[role].name = user.display_name || user.username;
  roles[role].label = apiRoleLabels[role][0];
  roles[role].system = apiRoleLabels[role][1];
  roles[role].initials = (user.display_name || user.username).trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('');
  state.page = 'overview';
  state.step = 0;
  loadPageData().finally(render);
}

const originalRender = render;
render = function connectedRender() {
  originalRender();
  if (!state.role) return;
  if (state.departmentMenuOpen) positionDepartmentMenu();
  const pills = document.querySelectorAll('.topbar .demo-pill');
  pills.forEach(pill => { pill.textContent = state.apiError ? 'تعذر الاتصال' : 'متصل بالخادم'; });
  const name = document.querySelector('.profile-name');
  if (name && state.apiUser) name.textContent = state.apiUser.display_name || state.apiUser.username;
};

const originalWizard = wizard;
wizard = function connectedWizard() {
  return originalWizard();
};

modalMarkup = function connectedModalMarkup() {
  if (!state.modal) return '';
  const modal = state.modal;
  const isSubmit = modal.kind === 'submit';
  const isDecision = ['approved', 'returned', 'rejected'].includes(modal.kind);
  const title = isSubmit ? 'إرسال الطلب إلى العميد؟' : modal.title;
  const message = isSubmit ? 'سيُنشأ الطلب على الخادم بحالة مسودة ثم يُرسل للمراجعة. لا تنشأ مجموعة أو حسابات قبل الاعتماد.' : isDecision ? 'سيُحفظ القرار وملاحظاته في النظام ويظهر أثره للمستخدمين المخولين.' : modal.message;
  const confirm = isSubmit ? 'حفظ وإرسال' : isDecision ? ({ approved: 'اعتماد', returned: 'إعادة للتعديل', rejected: 'رفض الطلب' }[modal.kind]) : modal.confirm;
  return `<div class="modal-backdrop" data-action="backdrop"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><h3 id="modal-title">${esc(title)}</h3><p>${esc(message)}</p>${modal.input ? `<div class="field"><label for="modal-note">${esc(modal.input)}</label><textarea id="modal-note" placeholder="اكتب ملاحظة واضحة ومحددة"></textarea></div>` : ''}<div class="modal-actions"><button class="btn btn-outline" data-action="close-modal">إلغاء</button><button class="btn ${modal.kind === 'rejected' ? 'btn-danger' : modal.kind === 'approved' ? 'btn-teal' : 'btn-primary'}" data-action="confirm-decision">${esc(confirm)}</button></div></div></div>`;
};

dashboard = function connectedDashboard() {
  const pending = serverRequests.filter(item => item.status === 'pending').length;
  const approved = serverRequests.filter(item => item.status === 'approved').length;
  const recent = serverRequests.slice(0, 5);
  const lead = state.apiUser?.display_name || state.apiUser?.username || roles[state.role].name;
  const roleAction = {
    dean: '<button class="btn btn-outline" data-page="requests">مراجعة الطلبات ←</button>',
    chair: '<button class="btn btn-teal" data-action="new-group">＋ إنشاء طلب مجموعة</button>',
    supervisor: '<button class="btn btn-outline" data-page="projects">مشاهدة المشاريع المسندة ←</button>',
    student: '<button class="btn btn-outline" data-page="project">فتح مشروعي ←</button>',
  }[state.role];
  let metrics;
  let sectionTitle;
  let sectionRows;
  let sectionAction;
  if (['dean', 'chair'].includes(state.role)) {
    metrics = `${stat('طلبات بانتظار الاعتماد',pending,'◷','من قاعدة البيانات','#d49513','#fff5de')}${stat('طلبات معتمدة',approved,'✓','من قاعدة البيانات')}${stat('المشاريع',state.projects.length,'◫','حسب صلاحية الحساب','#3979a3','#eaf3f8')}${stat('المجموعات',state.groups.length,'▧','حسب صلاحية الحساب','#755eb3','#f1edfa')}`;
    sectionTitle = 'أحدث الطلبات';
    sectionRows = recent.length ? requestRows(recent) : '<div class="empty-state">لا توجد طلبات مسجلة حتى الآن.</div>';
    sectionAction = `<button class="text-link" data-page="requests">عرض الكل ←</button>`;
  } else {
    const students = state.groups.reduce((count, group) => count + (group.members?.length || 0), 0);
    const projectLabel = state.role === 'student' ? 'مشاريعي' : 'مشاريع بإشرافي';
    const studentLabel = state.role === 'student' ? 'أعضاء مجموعتي' : 'الطلاب ضمن المشاريع';
    metrics = `${stat(projectLabel,state.projects.length,'◫','المشاريع المرتبطة بحسابك','#3979a3','#eaf3f8')}${stat('المجموعات',state.groups.length,'▧','حسب صلاحية الحساب','#755eb3','#f1edfa')}${stat(studentLabel,students,'♙','بحسب عضوية الفريق','#0d7a6e','#e9f4f1')}`;
    sectionTitle = state.role === 'student' ? 'مشروعي' : 'المشاريع المسندة';
    sectionRows = state.projects.length ? state.projects.map(project => `<div class="request-row"><div><div class="request-name">${esc(project.title)}</div><div class="request-meta">${esc(project.group.group_code)} · ${esc(project.group.department.name)}</div></div><span class="status active">${esc(project.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project-notes" data-project-id="${esc(project.id)}">ملاحظات الفريق</button></div>`).join('') : '<div class="empty-state">لا يوجد مشروع مرتبط بهذا الحساب حتى الآن.</div>';
    sectionAction = state.role === 'student' ? '<button class="text-link" data-page="deliverables">التسليمات ←</button>' : '<button class="text-link" data-page="notes">الملاحظات ←</button>';
  }
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">مساحة العمل · ${esc(state.apiUser?.department?.name || 'نظام إدارة مشاريع التخرج')}</div><h1>مرحبًا، ${esc(lead)} 👋</h1><p>${state.role === 'dean' ? 'تابع الطلبات والقرارات على مستوى الكلية.' : state.role === 'chair' ? 'أدر طلبات ومجموعات قسمك.' : state.role === 'supervisor' ? 'تابع المشاريع المسندة وملاحظات الفرق.' : 'تابع مشروعك وملفات التسليم.'}</p></div>${roleAction}</div><div class="stats-grid">${metrics}</div><section class="panel"><div class="panel-head"><div><h2 class="panel-title">${sectionTitle}</h2><div class="panel-sub">الحالة محفوظة على الخادم</div></div>${sectionAction}</div><div class="request-list">${sectionRows}</div></section>`;
};

requestRows = function connectedRequestRows(rows) {
  return rows.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.code)} · ${esc(item.department)}</div></div><div><span class="request-status-extra">${item.members} طلاب</span><div class="request-meta">${esc(item.date)}</div></div><div>${statusPill(item.status)}</div><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${serverRequests.indexOf(item)}">التفاصيل</button></div>`).join('');
};

tablePage = function connectedTablePage() {
  const rows = serverRequests.filter(item => (state.requestFilter === 'all' || item.status === state.requestFilter) && `${item.code} ${item.title} ${item.department}`.toLocaleLowerCase().includes(state.search.toLocaleLowerCase()));
  const canCreate = state.role === 'chair' ? '<button class="btn btn-teal" data-action="new-group">＋ إنشاء مجموعة</button>' : '';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">${state.role === 'dean' ? 'مراجعة واعتماد' : 'طلبات القسم'}</div><h1>${currentTitle()}</h1><p>الطلبات المعروضة من قاعدة البيانات وبحسب صلاحية حسابك.</p></div>${canCreate}</div><section class="table-panel" style="padding:19px"><div class="panel-head"><div><h2 class="panel-title">كل الطلبات</h2><div class="panel-sub">${rows.length} طلبات</div></div><button class="btn btn-outline btn-sm" data-action="refresh-data">تحديث</button></div><form id="request-filter-form" class="filters"><input type="search" id="request-search" value="${esc(state.search)}" placeholder="ابحث باسم المشروع أو الرقم..." aria-label="بحث الطلبات" /><select id="request-filter" aria-label="تصفية الحالة"><option value="all">كل الحالات</option>${Object.entries(statuses).filter(([key]) => !['active', 'draft'].includes(key)).map(([key, value]) => `<option value="${key}" ${state.requestFilter === key ? 'selected' : ''}>${value}</option>`).join('')}</select><button class="btn btn-outline btn-sm" type="submit">بحث</button></form><div class="table-scroll"><table class="data-table"><thead><tr><th>رقم الطلب / المشروع</th><th>القسم</th><th>الأعضاء</th><th>المشرف</th><th>تاريخ الإرسال</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>${rows.length ? rows.map(item => `<tr><td><div class="table-strong">${esc(item.title)}</div><small>${esc(item.code)}</small></td><td>${esc(item.department)}</td><td>${item.members}</td><td>${esc(item.supervisor)}</td><td>${esc(item.date)}</td><td>${statusPill(item.status)}</td><td><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${serverRequests.indexOf(item)}">عرض الطلب</button></td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">لا توجد طلبات تطابق البحث أو التصفية.</div></td></tr>'}</tbody></table></div>${connectionNotice()}</section>`;
};

detailPage = function connectedDetailPage() {
  const item = serverRequests[state.activeRequest];
  if (!item) return `${connectionNotice()}<div class="empty-state">تعذر العثور على الطلب. <button class="btn btn-outline" data-page="requests">العودة للطلبات</button></div>`;
  const revision = item.revision || {};
  const supervisor = item.supervisorDetail || {};
  const decisions = item.decisions.map(entry => `<div class="review-member">${esc(entry.decision)} · ${esc(entry.actor_name || '')}<div class="request-meta">${esc(entry.note || '')} · ${esc(safeDate(entry.created_at))}</div></div>`).join('');
  const members = item.memberDetails.map((member, index) => `<div class="review-member">${index + 1}. ${esc(member.full_name)} <span style="color:var(--muted)">· ${esc(member.username_proposed)} · ${esc(member.phone_proposed)}</span></div>`).join('');
  const actions = state.role === 'dean' && item.status === 'pending' ? `<div style="display:grid;gap:8px;margin-top:16px"><button class="btn btn-teal" data-action="decision" data-decision="approved">✓ اعتماد المجموعة كاملة</button><button class="btn btn-soft" data-action="decision" data-decision="returned">↶ إعادة للتعديل</button><button class="btn btn-danger" data-action="decision" data-decision="rejected">× رفض الطلب</button></div>` : '';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">${esc(item.code)} · تفاصيل الطلب</div><h1>${esc(item.title)}</h1><p>مقدم من ${esc(item.department)} · ${esc(item.date)}</p></div>${statusPill(item.status)}</div><div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2 class="panel-title">بيانات المشروع</h2><div class="panel-sub">العام الدراسي ${esc(item.year)}</div></div></div><div class="review-grid"><div class="review-item"><span>القسم</span><strong>${esc(item.department)}</strong></div><div class="review-item"><span>المجموعة</span><strong>${esc(item.code)}</strong></div><div class="review-item"><span>عدد الطلاب</span><strong>${item.members}</strong></div><div class="review-item"><span>المشرف المقترح</span><strong>${esc(supervisor.full_name || item.supervisor)}</strong></div><div class="review-item full"><span>وصف المشروع</span><strong>${esc(item.desc)}</strong></div></div><div class="review-section"><strong style="font-size:12px">أعضاء المجموعة</strong>${members}</div></section><section class="panel"><div class="panel-head"><div><h2 class="panel-title">سجل الطلب والقرارات</h2><div class="panel-sub">المراجعة الحالية رقم ${revision.revision_number || '—'}</div></div></div><div class="review-member">● &nbsp;${statusPill(item.status)}<div class="request-meta">${esc(item.date)}</div></div>${decisions || '<div class="request-meta">لا توجد قرارات سابقة.</div>'}${actions}</section></div><button class="btn btn-outline" data-page="requests">→ رجوع إلى الطلبات</button>`;
};

wizardStepContent = function connectedWizardContent() {
  if (state.step === 0) return `<h2>بيانات المجموعة والمشروع</h2><p class="lead">أدخل المعلومات الأساسية للطلب.</p><div class="form-grid"><div class="field"><label for="group-name">رمز المجموعة *</label><input id="group-name" placeholder="مثال: CS-2026-01" value="${esc(state.project.group)}" required /></div><div class="field"><label for="academic-year">العام الدراسي *</label><input id="academic-year" value="${esc(state.project.year)}" required /></div><div class="field full"><label for="project-title">عنوان المشروع المقترح *</label><input id="project-title" value="${esc(state.project.title)}" required /></div><div class="field full"><label for="project-desc">وصف المشروع وأهدافه الأولية *</label><textarea id="project-desc" required>${esc(state.project.desc)}</textarea></div><div class="field full department-picker-field"><label id="department-label" for="department-picker">القسم العلمي *</label><button id="department-picker" class="department-picker-trigger" type="button" role="combobox" aria-haspopup="listbox" aria-controls="department-options" aria-expanded="${state.departmentMenuOpen ? 'true' : 'false'}" aria-labelledby="department-label" data-action="toggle-department-menu"><span>${esc(state.departments.find(item => item.id === state.project.departmentId)?.name || 'اختر القسم العلمي')}</span><span aria-hidden="true">▾</span></button><input type="hidden" id="department" value="${esc(state.project.departmentId || '')}" /><div class="department-picker-menu ${state.departmentMenuOpen ? 'is-open' : ''}" id="department-options" role="listbox" aria-labelledby="department-label">${state.departments.length ? state.departments.map(department => `<button type="button" class="department-picker-option ${state.project.departmentId === department.id ? 'is-selected' : ''}" role="option" aria-selected="${state.project.departmentId === department.id}" data-action="select-department" data-department-id="${esc(department.id)}">${esc(department.name)}</button>`).join('') : '<div class="department-picker-empty">لا توجد أقسام متاحة للاختيار.</div>'}</div></div></div>`;
  if (state.step === 1) return `<div class="panel-head"><div><h2>أعضاء المجموعة</h2><p class="lead">أضف بيانات الطلاب. ينشأ الحساب غير مفعل بعد الاعتماد.</p></div><button class="btn btn-soft btn-sm" data-action="add-student">＋ إضافة طالب</button></div><div id="students-list">${state.students.map((student, index) => `<div class="member-card"><div class="member-head"><div class="member-title"><span class="member-index">${index + 1}</span>بيانات الطالب ${index + 1}</div>${state.students.length > 1 ? `<button class="btn btn-danger btn-sm" data-action="remove-student" data-index="${index}">حذف</button>` : ''}</div><div class="form-grid"><div class="field"><label>الاسم الكامل *</label><input data-student="name" data-index="${index}" value="${esc(student.name)}" /></div><div class="field"><label>اسم المستخدم *</label><input data-student="username" data-index="${index}" value="${esc(student.username)}" /></div><div class="field"><label>رقم الجوال *</label><input data-student="phone" data-index="${index}" value="${esc(student.phone)}" inputmode="tel" /></div></div></div>`).join('')}</div>`;
  if (state.step === 2) return `<h2>المشرف الأكاديمي</h2><p class="lead">اختر مشرفًا مسجلًا أو أدخل بيانات مشرف جديد.</p><div class="choice-row"><label class="choice-card"><input type="radio" name="supervisor-type" value="existing" ${state.supervisorType === 'existing' ? 'checked' : ''} /><span><span class="choice-title">حساب مشرف موجود</span></span></label><label class="choice-card"><input type="radio" name="supervisor-type" value="new" ${state.supervisorType === 'new' ? 'checked' : ''} /><span><span class="choice-title">إضافة مشرف جديد</span></span></label></div>${state.supervisorType === 'existing' ? `<div class="form-grid"><div class="field full"><label for="supervisor-existing">اختر المشرف *</label><select id="supervisor-existing">${state.supervisors.map(supervisor => `<option value="${esc(supervisor.id)}" ${state.selectedSupervisor === supervisor.id ? 'selected' : ''}>${esc(supervisor.full_name)}${supervisor.department ? ` — ${esc(supervisor.department)}` : ''}</option>`).join('')}</select>${!state.supervisors.length ? '<span class="help">لا يوجد مشرفون نشطون متاحون لهذا القسم.</span>' : ''}</div></div>` : `<div class="form-grid"><div class="field"><label for="supervisor-name">اسم المشرف *</label><input id="supervisor-name" value="${esc(state.supervisor.name)}" /></div><div class="field"><label for="supervisor-username">اسم المستخدم *</label><input id="supervisor-username" value="${esc(state.supervisor.username)}" /></div><div class="field"><label for="supervisor-phone">رقم الجوال *</label><input id="supervisor-phone" value="${esc(state.supervisor.phone)}" /></div><div class="field"><label for="supervisor-email">البريد الإلكتروني</label><input id="supervisor-email" type="email" value="${esc(state.supervisor.email)}" /></div><div class="field full"><label for="supervisor-specialty">التخصص</label><input id="supervisor-specialty" value="${esc(state.supervisor.specialty)}" /></div></div>`}`;
  return `<h2>مراجعة الطلب</h2><p class="lead">راجع المعلومات قبل حفظ الطلب وإرساله إلى العميد.</p><div class="review-section"><div class="review-grid"><div class="review-item"><span>رمز المجموعة</span><strong>${esc(state.project.group)}</strong></div><div class="review-item"><span>العام الدراسي</span><strong>${esc(state.project.year)}</strong></div><div class="review-item"><span>عنوان المشروع</span><strong>${esc(state.project.title)}</strong></div><div class="review-item"><span>القسم</span><strong>${esc(state.departments.find(item => item.id === state.project.departmentId)?.name || '')}</strong></div><div class="review-item full"><span>الوصف</span><strong>${esc(state.project.desc)}</strong></div></div></div><div class="review-section"><strong>الأعضاء (${state.students.length})</strong>${state.students.map(student => `<div class="review-member">${esc(student.name)} · ${esc(student.username)} · ${esc(student.phone)}</div>`).join('')}</div><div class="review-section"><strong>المشرف الأكاديمي</strong><div class="review-member">${state.supervisorType === 'existing' ? esc(state.supervisors.find(item => item.id === state.selectedSupervisor)?.full_name || '') : esc(state.supervisor.name)}</div></div><div class="notice warn">سيُحفظ الطلب كمسودة على الخادم ثم يرسل للعميد عند التأكيد.</div>`;
};

genericPage = function connectedGenericPage() {
  const titles = { drafts: 'المسودات المحفوظة', projects: 'المشاريع المسندة إليك', deliverables: 'التقارير والتسليمات', notes: 'الملاحظات', project: 'تفاصيل مشروعي', calendar: 'المواعيد القادمة', groups: 'المجموعات', users: 'المستخدمون', audit: 'سجل العمليات' };
  let content = '<div class="empty-state">لا توجد بيانات متاحة لهذا الحساب.</div>';
  if (state.page === 'drafts') {
    const drafts = serverRequests.filter(item => ['draft', 'returned'].includes(item.status));
    content = drafts.length ? `<div class="request-list">${drafts.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.code)} · ${esc(item.department)} · ${item.members} طلاب</div></div>${statusPill(item.status)}<button class="btn btn-outline btn-sm" data-action="resume-draft" data-request-id="${esc(item.id)}">استكمال الطلب</button></div>`).join('')}</div>` : '<div class="empty-state">لا توجد مسودات أو طلبات معادة للتعديل. يمكنك إنشاء طلب جديد والاحتفاظ به كمسودة من خطوة المراجعة.</div>';
  }
  if (state.page === 'groups' && state.groups.length) content = `<div class="request-list">${state.groups.map(group => `<div class="request-row"><div><div class="request-name">${esc(group.project_title || 'مجموعة مشاريع')}</div><div class="request-meta">${esc(group.group_code)} · ${esc(group.department.name)}</div></div><div>${group.members.length} طلاب</div><span class="status active">${esc(group.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project-notes" data-project-id="${esc(group.project_id)}">الملاحظات</button></div>`).join('')}</div>`;
  if (['projects', 'project'].includes(state.page) && state.projects.length) content = `<div class="request-list">${state.projects.map(project => `<div class="request-row"><div><div class="request-name">${esc(project.title)}</div><div class="request-meta">${esc(project.group.group_code)} · ${esc(project.group.department.name)}</div></div><div>${esc(project.group.academic_year)}</div><span class="status active">${esc(project.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project-notes" data-project-id="${esc(project.id)}">الملاحظات</button></div>`).join('')}</div>`;
  if (state.page === 'audit' && state.auditEvents.length) content = `<div class="request-list">${state.auditEvents.map(event => `<div class="request-row"><div><div class="request-name">${esc(event.action)}</div><div class="request-meta">${esc(event.actor || 'النظام')} · ${esc(event.entity_type)}</div></div><div>${esc(safeDate(event.occurred_at))}</div></div>`).join('')}</div>`;
  if (state.page === 'project' && state.projectDetail) {
    const project = state.projectDetail;
    content = `<div class="review-grid"><div class="review-item"><span>عنوان المشروع</span><strong>${esc(project.title)}</strong></div><div class="review-item"><span>رمز المجموعة</span><strong>${esc(project.group.group_code)}</strong></div><div class="review-item"><span>القسم</span><strong>${esc(project.group.department.name)}</strong></div><div class="review-item"><span>العام الدراسي</span><strong>${esc(project.group.academic_year)}</strong></div><div class="review-item full"><span>الوصف</span><strong>${esc(project.description)}</strong></div></div><button class="btn btn-teal" data-action="open-project-notes" data-project-id="${esc(project.id)}">عرض ملاحظات المشروع</button>`;
  }
  if (state.page === 'notes' && state.currentProjectId) content = `${state.projectNotes.length ? `<div class="request-list">${state.projectNotes.map(note => `<div class="review-member"><strong>${esc(note.author_name)}</strong> · ${esc(safeDate(note.created_at))}<p>${esc(note.body)}</p></div>`).join('')}</div>` : '<div class="empty-state">لا توجد ملاحظات لهذا المشروع.</div>'}<form id="project-note-form" class="field" style="margin-top:18px"><label for="project-note-body">إضافة ملاحظة للفريق</label><textarea id="project-note-body" required maxlength="5000"></textarea><button class="btn btn-teal" type="submit" style="margin-top:10px">حفظ الملاحظة</button></form>`;
  if (state.page === 'notes' && !state.currentProjectId) content = '<div class="empty-state">لا توجد مشاريع مرتبطة بالحساب بعد.</div>';
  if (state.page === 'notes' && state.currentProjectId && state.projects.length > 1) {
    const selectedProject = state.projects.find(project => project.id === state.currentProjectId);
    content = `<div class="field"><label for="note-project-picker">المشروع</label><select id="note-project-picker">${state.projects.map(project => `<option value="${esc(project.id)}" ${project.id === state.currentProjectId ? 'selected' : ''}>${esc(project.title)} · ${esc(project.group.group_code)}</option>`).join('')}</select></div>${content}`;
  }
  if (state.page === 'deliverables') {
    if (!state.currentProjectId) content = '<div class="empty-state">لا يوجد مشروع مرتبط بهذا الحساب حتى الآن.</div>';
    else {
      const project = state.projects.find(item => item.id === state.currentProjectId);
      const items = state.deliverables.length ? `<div class="request-list">${state.deliverables.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.original_filename)}</div><div class="request-meta">${esc(item.uploaded_by_name)} · ${esc(safeDate(item.created_at))} · ${Math.ceil(item.size_bytes / 1024)} كيلوبايت</div></div><a class="btn btn-outline btn-sm" href="${API_BASE}/deliverables/${encodeURIComponent(item.id)}/download/" data-download-id="${esc(item.id)}">تنزيل الملف</a></div>`).join('')}</div>` : '<div class="empty-state">لا توجد ملفات مرفوعة لهذا المشروع.</div>';
      const upload = state.role === 'student' ? `<form id="deliverable-upload-form" class="field" style="margin:16px 0" enctype="multipart/form-data"><label for="deliverable-file">إرفاق ملف للمشروع</label><input id="deliverable-file" name="file" type="file" required /><span class="help">الحد الأقصى 10 ميغابايت.</span><button class="btn btn-teal" type="submit" style="margin-top:10px">رفع الملف</button></form>` : '';
      content = `<div class="panel-head"><div><strong>${esc(project?.title || 'ملفات المشروع')}</strong><div class="panel-sub">${esc(project?.group?.group_code || '')}</div></div><button class="btn btn-outline btn-sm" data-action="refresh-data">تحديث</button></div>${upload}${items}`;
    }
  }
  if (['calendar', 'users'].includes(state.page) || (state.page === 'notes' && !state.currentProjectId)) content = '<div class="empty-state">لا تتوفر بيانات لهذه الوظيفة أو لا يوجد مشروع مرتبط بالحساب.</div>';
  if (state.page === 'calendar') content = '<div class="notice warn"><strong>لم يحدد القسم مواعيد تسليم بعد.</strong><p>ستظهر هنا المواعيد الرسمية ومراحل المشروع عند نشرها من إدارة القسم. إلى ذلك الوقت، تابع حالة المشروع وملفاته من «مشروعي» و«التسليمات».</p><button class="btn btn-outline btn-sm" data-page="project">مشاهدة مشروعي</button></div>';
  if (state.page === 'users') {
    const search = state.userSearch.trim().toLocaleLowerCase();
    const filtered = state.users.filter(user => (state.userRoleFilter === 'all' || user.role === state.userRoleFilter) && `${user.username} ${user.display_name} ${user.department?.name || ''}`.toLocaleLowerCase().includes(search));
    const roleOptions = [...new Map(state.users.map(user => [user.role, user.role_label])).entries()];
    const statusLabels = { active: 'نشط', activation_pending: 'بانتظار تفعيل الحساب', pending_approval: 'بانتظار اعتماد المجموعة', disabled: 'موقوف' };
    content = `<form id="users-filter-form" class="filters"><input type="search" id="users-search" value="${esc(state.userSearchInput)}" placeholder="ابحث بالاسم أو اسم المستخدم أو القسم" aria-label="بحث المستخدمين" /><select id="users-role-filter" aria-label="تصفية الدور"><option value="all">كل الأدوار</option>${roleOptions.map(([role, label]) => `<option value="${esc(role)}" ${state.userRoleFilter === role ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><button class="btn btn-outline btn-sm" type="submit">بحث</button><button class="btn btn-outline btn-sm" type="button" data-action="refresh-data">تحديث</button></form><div class="table-scroll"><table class="data-table"><thead><tr><th>الاسم</th><th>اسم المستخدم</th><th>الدور</th><th>القسم</th><th>حالة الحساب</th></tr></thead><tbody>${filtered.length ? filtered.map(user => `<tr><td>${esc(user.display_name)}</td><td>${esc(user.username)}</td><td>${esc(user.role_label)}</td><td>${esc(user.department?.name || '—')}</td><td>${esc(statusLabels[user.account_status] || user.account_status)}</td></tr>`).join('') : '<tr><td colspan="5"><div class="empty-state">لا يوجد مستخدمون يطابقون البحث.</div></td></tr>'}</tbody></table></div>`;
  }
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">GPMS · بيانات الخادم</div><h1>${titles[state.page] || currentTitle()}</h1><p>المعلومات معروضة بحسب صلاحيات حسابك.</p></div></div><section class="panel">${content}</section>`;
};

function selectedSupervisorId() { return state.selectedSupervisor || state.supervisors[0]?.id || ''; }

function validateRequestStep() {
  if (state.step === 0) {
    const project = readProject();
    if (!project.group.trim() || !project.year.trim() || !project.title.trim() || !project.desc.trim()) {
      toast('أكمل رمز المجموعة والعام الدراسي والعنوان والوصف قبل المتابعة.', 'error');
      return false;
    }
    if (!UUID_PATTERN.test(project.departmentId || '')) {
      toast('اختر القسم العلمي من القائمة قبل المتابعة.', 'error');
      return false;
    }
  }
  if (state.step === 1 && (!state.students.length || state.students.some(student => !student.name.trim() || !student.username.trim() || !student.phone.trim()))) {
    toast('أكمل الاسم واسم المستخدم ورقم الجوال لكل طالب قبل المتابعة.', 'error');
    return false;
  }
  if (state.step === 2) {
    if (state.supervisorType === 'existing' && !UUID_PATTERN.test(selectedSupervisorId())) {
      toast('اختر مشرفًا مسجلًا صالحًا أو اختر إضافة مشرف جديد.', 'error');
      return false;
    }
    if (state.supervisorType === 'new' && (!state.supervisor.name.trim() || !state.supervisor.username.trim() || !state.supervisor.phone.trim())) {
      toast('أكمل اسم المشرف واسم المستخدم ورقم الجوال قبل المتابعة.', 'error');
      return false;
    }
  }
  return true;
}

function positionDepartmentMenu() {
  const trigger = document.querySelector('#department-picker');
  const menu = document.querySelector('#department-options');
  if (!trigger || !menu || !state.departmentMenuOpen) return;
  const rect = trigger.getBoundingClientRect();
  const height = Math.min(320, Math.max(48, state.departments.length * 46 + 8), window.innerHeight - 24);
  const roomBelow = window.innerHeight - rect.bottom - 12;
  const roomAbove = rect.top - 12;
  const openAbove = roomBelow < height && roomAbove > roomBelow;
  const top = openAbove ? Math.max(12, rect.top - height - 6) : Math.min(window.innerHeight - height - 12, rect.bottom + 6);
  menu.style.position = 'fixed';
  menu.style.top = `${top}px`;
  menu.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - rect.width - 12))}px`;
  menu.style.width = `${rect.width}px`;
  menu.style.maxHeight = `${Math.max(48, Math.min(height, window.innerHeight - 24))}px`;
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || !state.departmentMenuOpen) return;
  state.departmentMenuOpen = false;
  document.querySelector('#department-options')?.classList.remove('is-open');
  document.querySelector('#department-picker')?.setAttribute('aria-expanded', 'false');
});
window.addEventListener('resize', () => { if (state.departmentMenuOpen) positionDepartmentMenu(); });

function buildRequestPayload() {
  const project = readProject();
  if (!project.year.trim()) throw new Error('أدخل العام الدراسي قبل متابعة الطلب.');
  if (!UUID_PATTERN.test(project.departmentId || '')) {
    throw new Error('القسم غير محدد أو أن معرّفه غير صالح. حدّث الصفحة ثم اختر القسم من القائمة.');
  }
  if (!state.students.length || state.students.some(student => !student.name.trim() || !student.username.trim() || !student.phone.trim())) {
    throw new Error('أكمل الاسم واسم المستخدم ورقم الجوال لكل طالب قبل حفظ الطلب.');
  }
  if (state.supervisorType === 'existing' && !UUID_PATTERN.test(selectedSupervisorId())) {
    throw new Error('لا يوجد مشرف مسجل صالح للاختيار. اختر «إضافة مشرف جديد» وأكمل بياناته، أو أضف حساب مشرف أولًا.');
  }
  if (state.supervisorType === 'new' && (!state.supervisor.name.trim() || !state.supervisor.username.trim() || !state.supervisor.phone.trim())) {
    throw new Error('أكمل اسم المشرف واسم المستخدم ورقم الجوال قبل حفظ الطلب.');
  }
  return {
      group_code: project.group.trim(), project_title: project.title.trim(), project_description: project.desc.trim(),
      academic_year: project.year.trim(), department_id: project.departmentId,
      members: state.students.map(student => ({ full_name: student.name.trim(), username: student.username.trim(), phone: student.phone.trim() })),
      supervisor: state.supervisorType === 'existing'
        ? { kind: 'existing', existing_user_id: selectedSupervisorId() }
        : { kind: 'new', full_name: state.supervisor.name.trim(), username: state.supervisor.username.trim(), phone: state.supervisor.phone.trim(), email: state.supervisor.email.trim(), specialty: state.supervisor.specialty.trim() },
  };
}

async function saveRealDraft() {
  try {
    const payload = buildRequestPayload();
    const created = state.draftRequestId
      ? await apiRequest(`/group-requests/${state.draftRequestId}/`, { method: 'PATCH', body: JSON.stringify(payload) })
      : await apiRequest('/group-requests/', { method: 'POST', body: JSON.stringify(payload) });
    state.draftRequestId = created.id;
    await loadRequests();
    state.page = 'drafts'; state.modal = null; render();
    toast('تم حفظ الطلب كمسودة. يمكنك استكماله لاحقًا.');
  } catch (error) {
    state.apiError = error.message; render(); toast(error.message, 'error');
  }
}

async function submitRealRequest() {
  try {
    const payload = buildRequestPayload();
    const created = state.draftRequestId
      ? await apiRequest(`/group-requests/${state.draftRequestId}/`, { method: 'PATCH', body: JSON.stringify(payload) })
      : await apiRequest('/group-requests/', { method: 'POST', body: JSON.stringify(payload) });
    state.draftRequestId = created.id;
    const submitted = await apiRequest(`/group-requests/${created.id}/submit/`, { method: 'POST', body: JSON.stringify({ version: created.version }) });
    state.draftRequestId = null;
    await loadRequests();
    state.activeRequest = serverRequests.findIndex(item => item.id === submitted.id);
    state.page = 'detail'; state.modal = null; render();
    toast('تم حفظ الطلب وإرساله إلى العميد.');
  } catch (error) {
    state.apiError = error.message; render(); toast(error.message, 'error');
  }
}

async function resumeDraft(requestId) {
  try {
    const item = serverRequests.find(request => request.id === requestId);
    if (!item || !['draft', 'returned'].includes(item.status)) throw new Error('هذه المسودة لم تعد قابلة للتعديل. حدّث القائمة.');
    const [departments, supervisors] = await Promise.all([apiRequest('/departments/'), apiRequest('/supervisors/')]);
    const revision = item.revision || {};
    const supervisor = item.supervisorDetail || {};
    state.departments = departments; state.supervisors = supervisors;
    state.project = { group: item.code, title: item.title, desc: item.desc, department: item.department, departmentId: item.departmentId, year: item.year };
    state.students = item.memberDetails.map(member => ({ name: member.full_name, username: member.username_proposed, phone: member.phone_proposed }));
    state.supervisorType = supervisor.supervisor_type === 'new' ? 'new' : 'existing';
    state.selectedSupervisor = supervisor.existing_user_id || '';
    state.supervisor = { name: supervisor.full_name || '', username: supervisor.username_proposed || '', phone: supervisor.phone_proposed || '', email: supervisor.email || '', specialty: supervisor.specialty || '' };
    state.draftRequestId = item.id; state.step = 0; state.page = 'wizard'; state.modal = null; state.apiError = '';
    render();
  } catch (error) {
    state.apiError = error.message; render(); toast(error.message, 'error');
  }
}

async function decideRealRequest() {
  const item = serverRequests[state.activeRequest];
  const modal = state.modal;
  if (!item || !modal) return;
  const note = document.querySelector('#modal-note')?.value.trim() || '';
  if (modal.kind !== 'approved' && !note) { toast('اكتب الملاحظات أو سبب الرفض أولًا.', 'error'); return; }
  try {
    const action = { approved: 'approve', returned: 'return', rejected: 'reject' }[modal.kind];
    await apiRequest(`/group-requests/${item.id}/${action}/`, { method: 'POST', body: JSON.stringify({ note }) });
    await loadRequests();
    state.activeRequest = serverRequests.findIndex(entry => entry.id === item.id);
    state.modal = null; render(); toast('تم حفظ القرار في النظام.');
  } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
}

document.addEventListener('click', async event => {
  const downloadLink = event.target.closest('[data-download-id]');
  if (downloadLink) {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const response = await fetch(downloadLink.href, { headers: { Authorization: `Token ${state.apiToken}` }, credentials: 'omit' });
      if (!response.ok) throw new Error('تعذر تنزيل الملف. تحقق من صلاحية الحساب.');
      const blobUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = blobUrl; anchor.download = downloadLink.closest('.request-row')?.querySelector('.request-name')?.textContent || 'attachment';
      document.body.append(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(blobUrl);
    } catch (error) { toast(error.message, 'error'); }
    return;
  }
  if (state.departmentMenuOpen && !event.target.closest('.department-picker-field')) {
    state.departmentMenuOpen = false;
    document.querySelector('#department-options')?.classList.remove('is-open');
    document.querySelector('#department-picker')?.setAttribute('aria-expanded', 'false');
  }
  const pageButton = event.target.closest('[data-page]');
  if (pageButton) {
    event.preventDefault(); event.stopImmediatePropagation();
    state.page = pageButton.dataset.page; state.modal = null;
    if (state.page === 'detail') return render();
    await loadPageData(); render(); return;
  }
  const actionButton = event.target.closest('[data-action]');
  if (!actionButton) return;
  const action = actionButton.dataset.action;
  if (action === 'decision') {
    event.preventDefault(); event.stopImmediatePropagation();
    const kind = actionButton.dataset.decision;
    const prompts = {
      approved: { title: 'اعتماد المجموعة كاملة؟', message: 'سيعتمد الطلب وينشئ المجموعة والمشروع وحسابات الطلاب غير المفعلة.' },
      returned: { title: 'إعادة الطلب للتعديل؟', message: 'أدخل ملاحظة توضّح التعديلات المطلوبة.', input: 'ملاحظات التعديل' },
      rejected: { title: 'رفض الطلب؟', message: 'أدخل سبب رفض الطلب.', input: 'سبب الرفض' },
    };
    if (prompts[kind]) { state.modal = { kind, ...prompts[kind] }; render(); }
    return;
  }
  if (action === 'next-step') {
    event.preventDefault(); event.stopImmediatePropagation();
    readProject();
    if (!validateRequestStep()) return;
    if (state.step < 3) {
      state.step += 1; render();
    } else {
      state.modal = { kind: 'submit', title: 'إرسال الطلب؟', message: 'سيُرسل الطلب إلى النظام للمراجعة.', confirm: 'إرسال' };
      render();
    }
    return;
  }
  if (action === 'toggle-department-menu') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.departmentMenuOpen = !state.departmentMenuOpen; render(); return;
  }
  if (action === 'select-department') {
    event.preventDefault(); event.stopImmediatePropagation();
    const department = state.departments.find(item => item.id === actionButton.dataset.departmentId);
    if (department) {
      state.project.departmentId = department.id;
      state.project.department = department.name;
    }
    state.departmentMenuOpen = false; render(); return;
  }
  if (action === 'logout') {
    event.preventDefault(); event.stopImmediatePropagation();
    try { await apiRequest('/auth/logout/', { method: 'POST', body: '{}' }); } catch (_) { /* انقطع الاتصال؛ نمسح الحالة المحلية على أي حال. */ }
    clearStoredApiToken(); state.page = 'overview'; state.modal = null; login(); return;
  }
  if (action === 'new-group') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const [departments, supervisors] = await Promise.all([apiRequest('/departments/'), apiRequest('/supervisors/')]);
      state.departments = departments; state.supervisors = supervisors;
      const userDepartment = departments.find(department => department.id === state.apiUser?.department?.id);
      const selectedDepartment = userDepartment || departments[0];
      state.project = { group: '', title: '', desc: '', department: selectedDepartment?.name || '', departmentId: selectedDepartment?.id || '', year: '2026–2027' };
      state.students = [emptyStudent()]; state.supervisorType = supervisors.length ? 'existing' : 'new'; state.selectedSupervisor = supervisors[0]?.id || '';
      state.supervisor = { name: '', username: '', phone: '', email: '', specialty: '' };
      state.draftRequestId = null; state.step = 0; state.page = 'wizard'; state.modal = null; render();
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'cancel-wizard') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.page = state.draftRequestId ? 'drafts' : 'overview'; state.modal = null; await loadPageData(); render(); return;
  }
  if (action === 'save-draft') {
    event.preventDefault(); event.stopImmediatePropagation(); await saveRealDraft(); return;
  }
  if (action === 'resume-draft') {
    event.preventDefault(); event.stopImmediatePropagation(); await resumeDraft(actionButton.dataset.requestId); return;
  }
  if (action === 'confirm-decision' && state.modal?.kind === 'submit') {
    event.preventDefault(); event.stopImmediatePropagation(); await submitRealRequest(); return;
  }
  if (action === 'confirm-decision' && ['approved', 'returned', 'rejected'].includes(state.modal?.kind)) {
    event.preventDefault(); event.stopImmediatePropagation(); await decideRealRequest(); return;
  }
  if (action === 'refresh-data') {
    event.preventDefault(); event.stopImmediatePropagation(); await loadPageData(); render(); toast('تم تحديث البيانات من الخادم.');
  }
  if (action === 'open-project-notes') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.currentProjectId = actionButton.dataset.projectId; state.page = 'notes';
    await loadPageData(); render(); return;
  }
}, true);

document.addEventListener('change', event => {
  if (event.target.id === 'department') {
    state.project.departmentId = event.target.value;
    state.project.department = state.departments.find(item => item.id === event.target.value)?.name || '';
  }
  if (event.target.id === 'supervisor-existing') state.selectedSupervisor = event.target.value;
  if (event.target.id === 'users-role-filter') { state.userRoleFilter = event.target.value; render(); }
  if (event.target.id === 'note-project-picker') {
    state.currentProjectId = event.target.value;
    loadPageData().finally(render);
  }
}, true);

document.addEventListener('submit', async event => {
  if (event.target.id === 'request-filter-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.search = document.querySelector('#request-search')?.value || '';
    state.requestFilter = document.querySelector('#request-filter')?.value || 'all';
    render(); return;
  }
  if (event.target.id === 'users-filter-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.userSearchInput = document.querySelector('#users-search')?.value || '';
    state.userSearch = state.userSearchInput;
    state.userRoleFilter = document.querySelector('#users-role-filter')?.value || 'all';
    render(); return;
  }
  if (event.target.id === 'deliverable-upload-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const file = document.querySelector('#deliverable-file')?.files?.[0];
    if (!file) { toast('اختر ملفًا قبل الرفع.', 'error'); return; }
    const submitButton = event.target.querySelector('[type="submit"]');
    submitButton.disabled = true; submitButton.textContent = 'جارٍ رفع الملف…';
    try {
      const formData = new FormData(); formData.append('file', file);
      await apiRequest(`/projects/${state.currentProjectId}/deliverables/`, { method: 'POST', body: formData });
      await loadPageData(); render(); toast('تم رفع الملف إلى المشروع.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'project-note-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      await apiRequest(`/projects/${state.currentProjectId}/notes/`, { method: 'POST', body: JSON.stringify({ body: document.querySelector('#project-note-body').value.trim(), visibility: 'team' }) });
      await loadPageData(); render(); toast('تم حفظ الملاحظة على الخادم.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'login-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const button = event.target.querySelector('[type="submit"]');
    button.disabled = true; button.textContent = 'جارٍ التحقق…';
    try {
      const result = await apiRequest('/auth/login/', { method: 'POST', body: JSON.stringify({ identifier: document.querySelector('#login-user').value.trim(), password: document.querySelector('#login-password').value }) });
      if (!result.token || !result.user) throw new Error('استجابة تسجيل الدخول من الخادم غير مكتملة.');
      saveStoredApiToken(result.token);
      startAsAuthenticated(result.user);
    } catch (error) {
      state.apiError = error.message; login(); toast(error.message, 'error');
    }
  }
}, true);

(async function restoreTokenLogin() {
  try {
    const result = await apiRequest('/auth/me/');
    startAsAuthenticated(result.user);
  } catch (error) {
    if (error.message.includes('الاتصال بالخادم')) state.apiError = error.message;
    else if (!state.apiToken) state.apiError = '';
    login();
  }
})();

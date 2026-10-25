/* واجهة المرحلة الخامسة: ربط الشاشة بواجهات GPMS الفعلية. */
const API_BASE = (window.GPMS_API_BASE_URL || 'https://MjdKhaled1.pythonanywhere.com/api/v1').replace(/\/$/, '');
const backendRoleToUi = { dean: 'dean', department_chair: 'chair', supervisor: 'supervisor', student: 'student' };
const apiRoleLabels = { dean: ['عميد الكلية', 'رئيس النظام'], chair: ['رئيس القسم', 'رئيس القسم'], supervisor: ['المشرف الأكاديمي', 'مشرف أكاديمي'], student: ['الطالب', 'طالب'] };
state.apiUser = null;
state.departments = [];
state.supervisors = [];
state.apiError = '';
state.csrfToken = '';
state.projects = [];
state.groups = [];
state.auditEvents = [];
state.draftRequestId = null;
state.projectNotes = [];
state.currentProjectId = null;
state.projectDetail = null;

async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    // إضافة التوكن إلى الطلبات
const token = localStorage.getItem('authToken');
if (token) {
    headers.set('Authorization', `Token ${token}`);
}
    const csrfData = await csrf.json();
    state.csrfToken = csrfData.csrfToken || '';
    if (state.csrfToken) headers.set('X-CSRFToken', state.csrfToken);
  }
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, method, headers, credentials: 'include' });
  } catch (error) {
    throw new Error('تعذر الاتصال بالخادم. شغّل واجهة API على المنفذ 8001 وتحقق من الاتصال المحلي.');
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail || Object.values(data).flat().find(value => typeof value === 'string') || 'تعذر إتمام العملية.';
    throw new Error(Array.isArray(detail) ? detail.join(' ') : detail);
  }
  return data;
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
  demoRequests.splice(0, demoRequests.length, ...list.map(uiRequest));
}

async function loadPageData() {
  state.apiError = '';
  try {
    if (['overview', 'requests', 'detail', 'drafts'].includes(state.page) && state.role !== 'student' && state.role !== 'supervisor') await loadRequests();
    if (['groups', 'overview'].includes(state.page)) state.groups = await apiRequest('/groups/');
    if (['projects', 'project', 'overview'].includes(state.page)) {
      state.projects = await apiRequest('/projects/');
      if (state.page === 'project' && !state.currentProjectId) state.currentProjectId = state.projects[0]?.id || null;
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
  const pills = document.querySelectorAll('.topbar .demo-pill');
  pills.forEach(pill => { pill.textContent = state.apiError ? 'تعذر الاتصال' : 'متصل بالخادم'; });
  const name = document.querySelector('.profile-name');
  if (name && state.apiUser) name.textContent = state.apiUser.display_name || state.apiUser.username;
};

const originalWizard = wizard;
wizard = function connectedWizard() {
  return originalWizard()
    .replace('مسودة تجريبية', 'طلب محفوظ على الخادم عند الإرسال')
    .replace('حفظ كمسودة والخروج', 'إلغاء الطلب')
    .replace('لا تحفظ هذه المسودة خارج جلسة المعاينة. لا تُنشأ حسابات أو عضويات حقيقية.', 'يُحفظ الطلب على الخادم عند الإرسال، ولا تُنشأ حسابات الأعضاء إلا بعد الاعتماد.');
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
  const pending = demoRequests.filter(item => item.status === 'pending').length;
  const approved = demoRequests.filter(item => item.status === 'approved').length;
  const recent = demoRequests.slice(0, 5);
  const lead = state.apiUser?.display_name || state.apiUser?.username || roles[state.role].name;
  const rows = recent.length ? requestRows(recent) : '<div class="empty-state">لا توجد طلبات مسجلة حتى الآن.</div>';
  const primaryAction = state.role === 'chair' ? '<button class="btn btn-teal" data-action="new-group">＋ إنشاء مجموعة</button>' : '<button class="btn btn-outline" data-page="requests">عرض الطلبات <span>←</span></button>';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">مساحة العمل · ${esc(state.apiUser?.department?.name || 'نظام إدارة مشاريع التخرج')}</div><h1>مرحبًا، ${esc(lead)} 👋</h1><p>ملخص البيانات المسجلة في النظام.</p></div>${primaryAction}</div><div class="stats-grid">${stat('طلبات بانتظار الاعتماد',pending,'◷','من قاعدة البيانات','#d49513','#fff5de')}${stat('طلبات معتمدة',approved,'✓','خلال العام الدراسي الحالي')}${stat('المشاريع المسندة',state.projects.length,'◫','حسب صلاحية الحساب','#3979a3','#eaf3f8')}${stat('المجموعات المسجلة',state.groups.length,'▧','حسب صلاحية الحساب','#755eb3','#f1edfa')}</div><section class="panel"><div class="panel-head"><div><h2 class="panel-title">أحدث الطلبات</h2><div class="panel-sub">الحالة محفوظة على الخادم</div></div><button class="text-link" data-page="requests">عرض الكل ←</button></div><div class="request-list">${rows}</div></section>`;
};

requestRows = function connectedRequestRows(rows) {
  return rows.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.code)} · ${esc(item.department)}</div></div><div><span class="request-status-extra">${item.members} طلاب</span><div class="request-meta">${esc(item.date)}</div></div><div>${statusPill(item.status)}</div><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${demoRequests.indexOf(item)}">التفاصيل</button></div>`).join('');
};

tablePage = function connectedTablePage() {
  const rows = demoRequests.filter(item => (state.requestFilter === 'all' || item.status === state.requestFilter) && `${item.code} ${item.title} ${item.department}`.toLocaleLowerCase().includes(state.search.toLocaleLowerCase()));
  const canCreate = state.role === 'chair' ? '<button class="btn btn-teal" data-action="new-group">＋ إنشاء مجموعة</button>' : '';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">${state.role === 'dean' ? 'مراجعة واعتماد' : 'طلبات القسم'}</div><h1>${currentTitle()}</h1><p>الطلبات المعروضة من قاعدة البيانات وبحسب صلاحية حسابك.</p></div>${canCreate}</div><section class="table-panel" style="padding:19px"><div class="panel-head"><div><h2 class="panel-title">كل الطلبات</h2><div class="panel-sub">${rows.length} طلبات</div></div><button class="btn btn-outline btn-sm" data-action="refresh-data">تحديث</button></div><div class="filters"><input type="search" id="request-search" value="${esc(state.search)}" placeholder="ابحث باسم المشروع أو الرقم..." aria-label="بحث الطلبات" /><select id="request-filter" aria-label="تصفية الحالة"><option value="all">كل الحالات</option>${Object.entries(statuses).filter(([key]) => !['active', 'draft'].includes(key)).map(([key, value]) => `<option value="${key}" ${state.requestFilter === key ? 'selected' : ''}>${value}</option>`).join('')}</select></div><div class="table-scroll"><table class="data-table"><thead><tr><th>رقم الطلب / المشروع</th><th>القسم</th><th>الأعضاء</th><th>المشرف</th><th>تاريخ الإرسال</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>${rows.length ? rows.map(item => `<tr><td><div class="table-strong">${esc(item.title)}</div><small>${esc(item.code)}</small></td><td>${esc(item.department)}</td><td>${item.members}</td><td>${esc(item.supervisor)}</td><td>${esc(item.date)}</td><td>${statusPill(item.status)}</td><td><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${demoRequests.indexOf(item)}">عرض الطلب</button></td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">لا توجد طلبات تطابق البحث أو التصفية.</div></td></tr>'}</tbody></table></div>${connectionNotice()}</section>`;
};

detailPage = function connectedDetailPage() {
  const item = demoRequests[state.activeRequest];
  if (!item) return `${connectionNotice()}<div class="empty-state">تعذر العثور على الطلب. <button class="btn btn-outline" data-page="requests">العودة للطلبات</button></div>`;
  const revision = item.revision || {};
  const supervisor = item.supervisorDetail || {};
  const decisions = item.decisions.map(entry => `<div class="review-member">${esc(entry.decision)} · ${esc(entry.actor_name || '')}<div class="request-meta">${esc(entry.note || '')} · ${esc(safeDate(entry.created_at))}</div></div>`).join('');
  const members = item.memberDetails.map((member, index) => `<div class="review-member">${index + 1}. ${esc(member.full_name)} <span style="color:var(--muted)">· ${esc(member.username_proposed)} · ${esc(member.phone_proposed)}</span></div>`).join('');
  const actions = state.role === 'dean' && item.status === 'pending' ? `<div style="display:grid;gap:8px;margin-top:16px"><button class="btn btn-teal" data-action="decision" data-decision="approved">✓ اعتماد المجموعة كاملة</button><button class="btn btn-soft" data-action="decision" data-decision="returned">↶ إعادة للتعديل</button><button class="btn btn-danger" data-action="decision" data-decision="rejected">× رفض الطلب</button></div>` : '';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">${esc(item.code)} · تفاصيل الطلب</div><h1>${esc(item.title)}</h1><p>مقدم من ${esc(item.department)} · ${esc(item.date)}</p></div>${statusPill(item.status)}</div><div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2 class="panel-title">بيانات المشروع</h2><div class="panel-sub">العام الدراسي ${esc(item.year)}</div></div></div><div class="review-grid"><div class="review-item"><span>القسم</span><strong>${esc(item.department)}</strong></div><div class="review-item"><span>المجموعة</span><strong>${esc(item.code)}</strong></div><div class="review-item"><span>عدد الطلاب</span><strong>${item.members}</strong></div><div class="review-item"><span>المشرف المقترح</span><strong>${esc(supervisor.full_name || item.supervisor)}</strong></div><div class="review-item full"><span>وصف المشروع</span><strong>${esc(item.desc)}</strong></div></div><div class="review-section"><strong style="font-size:12px">أعضاء المجموعة</strong>${members}</div></section><section class="panel"><div class="panel-head"><div><h2 class="panel-title">سجل الطلب والقرارات</h2><div class="panel-sub">المراجعة الحالية رقم ${revision.revision_number || '—'}</div></div></div><div class="review-member">● &nbsp;${statusPill(item.status)}<div class="request-meta">${esc(item.date)}</div></div>${decisions || '<div class="request-meta">لا توجد قرارات سابقة.</div>'}${actions}</section></div><button class="btn btn-outline" data-page="requests">→ رجوع إلى الطلبات</button>`;
};

wizardStepContent = function connectedWizardContent() {
  if (state.step === 0) return `<h2>بيانات المجموعة والمشروع</h2><p class="lead">أدخل المعلومات الأساسية للطلب.</p><div class="form-grid"><div class="field"><label for="group-name">رمز المجموعة *</label><input id="group-name" placeholder="مثال: CS-2026-01" value="${esc(state.project.group)}" required /></div><div class="field"><label for="academic-year">العام الدراسي *</label><input id="academic-year" value="${esc(state.project.year)}" required /></div><div class="field full"><label for="project-title">عنوان المشروع المقترح *</label><input id="project-title" value="${esc(state.project.title)}" required /></div><div class="field full"><label for="project-desc">وصف المشروع وأهدافه الأولية *</label><textarea id="project-desc" required>${esc(state.project.desc)}</textarea></div><div class="field full"><label for="department">القسم العلمي *</label><select id="department">${state.departments.map(department => `<option value="${esc(department.id)}" ${state.project.departmentId === department.id ? 'selected' : ''}>${esc(department.name)}</option>`).join('')}</select></div></div>`;
  if (state.step === 1) return `<div class="panel-head"><div><h2>أعضاء المجموعة</h2><p class="lead">أضف بيانات الطلاب. ينشأ الحساب غير مفعل بعد الاعتماد.</p></div><button class="btn btn-soft btn-sm" data-action="add-student">＋ إضافة طالب</button></div><div id="students-list">${state.students.map((student, index) => `<div class="member-card"><div class="member-head"><div class="member-title"><span class="member-index">${index + 1}</span>بيانات الطالب ${index + 1}</div>${state.students.length > 1 ? `<button class="btn btn-danger btn-sm" data-action="remove-student" data-index="${index}">حذف</button>` : ''}</div><div class="form-grid"><div class="field"><label>الاسم الكامل *</label><input data-student="name" data-index="${index}" value="${esc(student.name)}" /></div><div class="field"><label>اسم المستخدم *</label><input data-student="username" data-index="${index}" value="${esc(student.username)}" /></div><div class="field"><label>رقم الجوال *</label><input data-student="phone" data-index="${index}" value="${esc(student.phone)}" inputmode="tel" /></div></div></div>`).join('')}</div>`;
  if (state.step === 2) return `<h2>المشرف الأكاديمي</h2><p class="lead">اختر مشرفًا مسجلًا أو أدخل بيانات مشرف جديد.</p><div class="choice-row"><label class="choice-card"><input type="radio" name="supervisor-type" value="existing" ${state.supervisorType === 'existing' ? 'checked' : ''} /><span><span class="choice-title">حساب مشرف موجود</span></span></label><label class="choice-card"><input type="radio" name="supervisor-type" value="new" ${state.supervisorType === 'new' ? 'checked' : ''} /><span><span class="choice-title">إضافة مشرف جديد</span></span></label></div>${state.supervisorType === 'existing' ? `<div class="form-grid"><div class="field full"><label for="supervisor-existing">اختر المشرف *</label><select id="supervisor-existing">${state.supervisors.map(supervisor => `<option value="${esc(supervisor.id)}" ${state.selectedSupervisor === supervisor.id ? 'selected' : ''}>${esc(supervisor.full_name)}${supervisor.department ? ` — ${esc(supervisor.department)}` : ''}</option>`).join('')}</select>${!state.supervisors.length ? '<span class="help">لا يوجد مشرفون نشطون متاحون لهذا القسم.</span>' : ''}</div></div>` : `<div class="form-grid"><div class="field"><label for="supervisor-name">اسم المشرف *</label><input id="supervisor-name" value="${esc(state.supervisor.name)}" /></div><div class="field"><label for="supervisor-username">اسم المستخدم *</label><input id="supervisor-username" value="${esc(state.supervisor.username)}" /></div><div class="field"><label for="supervisor-phone">رقم الجوال *</label><input id="supervisor-phone" value="${esc(state.supervisor.phone)}" /></div><div class="field"><label for="supervisor-email">البريد الإلكتروني</label><input id="supervisor-email" type="email" value="${esc(state.supervisor.email)}" /></div><div class="field full"><label for="supervisor-specialty">التخصص</label><input id="supervisor-specialty" value="${esc(state.supervisor.specialty)}" /></div></div>`}`;
  return `<h2>مراجعة الطلب</h2><p class="lead">راجع المعلومات قبل حفظ الطلب وإرساله إلى العميد.</p><div class="review-section"><div class="review-grid"><div class="review-item"><span>رمز المجموعة</span><strong>${esc(state.project.group)}</strong></div><div class="review-item"><span>العام الدراسي</span><strong>${esc(state.project.year)}</strong></div><div class="review-item"><span>عنوان المشروع</span><strong>${esc(state.project.title)}</strong></div><div class="review-item"><span>القسم</span><strong>${esc(state.departments.find(item => item.id === state.project.departmentId)?.name || '')}</strong></div><div class="review-item full"><span>الوصف</span><strong>${esc(state.project.desc)}</strong></div></div></div><div class="review-section"><strong>الأعضاء (${state.students.length})</strong>${state.students.map(student => `<div class="review-member">${esc(student.name)} · ${esc(student.username)} · ${esc(student.phone)}</div>`).join('')}</div><div class="review-section"><strong>المشرف الأكاديمي</strong><div class="review-member">${state.supervisorType === 'existing' ? esc(state.supervisors.find(item => item.id === state.selectedSupervisor)?.full_name || '') : esc(state.supervisor.name)}</div></div><div class="notice warn">سيُحفظ الطلب كمسودة على الخادم ثم يرسل للعميد عند التأكيد.</div>`;
};

genericPage = function connectedGenericPage() {
  const titles = { drafts: 'المسودات المحفوظة', projects: 'المشاريع المسندة إليك', deliverables: 'التقارير والتسليمات', notes: 'الملاحظات', project: 'تفاصيل مشروعي', calendar: 'المواعيد القادمة', groups: 'المجموعات', users: 'المستخدمون', audit: 'سجل العمليات' };
  let content = '<div class="empty-state">لا توجد بيانات متاحة لهذا الحساب.</div>';
  if (state.page === 'groups' && state.groups.length) content = `<div class="request-list">${state.groups.map(group => `<div class="request-row"><div><div class="request-name">${esc(group.project_title || 'مجموعة مشاريع')}</div><div class="request-meta">${esc(group.group_code)} · ${esc(group.department.name)}</div></div><div>${group.members.length} طلاب</div><span class="status active">${esc(group.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project-notes" data-project-id="${esc(group.project_id)}">الملاحظات</button></div>`).join('')}</div>`;
  if (['projects', 'project'].includes(state.page) && state.projects.length) content = `<div class="request-list">${state.projects.map(project => `<div class="request-row"><div><div class="request-name">${esc(project.title)}</div><div class="request-meta">${esc(project.group.group_code)} · ${esc(project.group.department.name)}</div></div><div>${esc(project.group.academic_year)}</div><span class="status active">${esc(project.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project-notes" data-project-id="${esc(project.id)}">الملاحظات</button></div>`).join('')}</div>`;
  if (state.page === 'audit' && state.auditEvents.length) content = `<div class="request-list">${state.auditEvents.map(event => `<div class="request-row"><div><div class="request-name">${esc(event.action)}</div><div class="request-meta">${esc(event.actor || 'النظام')} · ${esc(event.entity_type)}</div></div><div>${esc(safeDate(event.occurred_at))}</div></div>`).join('')}</div>`;
  if (state.page === 'project' && state.projectDetail) {
    const project = state.projectDetail;
    content = `<div class="review-grid"><div class="review-item"><span>عنوان المشروع</span><strong>${esc(project.title)}</strong></div><div class="review-item"><span>رمز المجموعة</span><strong>${esc(project.group.group_code)}</strong></div><div class="review-item"><span>القسم</span><strong>${esc(project.group.department.name)}</strong></div><div class="review-item"><span>العام الدراسي</span><strong>${esc(project.group.academic_year)}</strong></div><div class="review-item full"><span>الوصف</span><strong>${esc(project.description)}</strong></div></div><button class="btn btn-teal" data-action="open-project-notes" data-project-id="${esc(project.id)}">عرض ملاحظات المشروع</button>`;
  }
  if (state.page === 'notes' && state.currentProjectId) content = `${state.projectNotes.length ? `<div class="request-list">${state.projectNotes.map(note => `<div class="review-member"><strong>${esc(note.author_name)}</strong> · ${esc(safeDate(note.created_at))}<p>${esc(note.body)}</p></div>`).join('')}</div>` : '<div class="empty-state">لا توجد ملاحظات لهذا المشروع.</div>'}<form id="project-note-form" class="field" style="margin-top:18px"><label for="project-note-body">إضافة ملاحظة للفريق</label><textarea id="project-note-body" required maxlength="5000"></textarea><button class="btn btn-teal" type="submit" style="margin-top:10px">حفظ الملاحظة</button></form>`;
  if (['deliverables', 'calendar', 'users'].includes(state.page) || (state.page === 'notes' && !state.currentProjectId)) content = '<div class="empty-state">لا تتوفر بيانات لهذه الوظيفة أو لا يوجد مشروع مرتبط بالحساب.</div>';
  if (state.page === 'drafts') content = '<div class="empty-state">تُحفظ الطلبات في النظام بحالة مسودة أو معادة للتعديل وتظهر ضمن قائمة الطلبات.</div>';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">GPMS · بيانات الخادم</div><h1>${titles[state.page] || currentTitle()}</h1><p>المعلومات معروضة بحسب صلاحيات حسابك.</p></div></div><section class="panel">${content}</section>`;
};

function selectedSupervisorId() { return state.selectedSupervisor || state.supervisors[0]?.id || ''; }

async function submitRealRequest() {
  try {
    const project = readProject();
    const payload = {
      group_code: project.group.trim(), project_title: project.title.trim(), project_description: project.desc.trim(),
      academic_year: project.year.trim(), department_id: project.departmentId,
      members: state.students.map(student => ({ full_name: student.name.trim(), username: student.username.trim(), phone: student.phone.trim() })),
      supervisor: state.supervisorType === 'existing'
        ? { kind: 'existing', existing_user_id: selectedSupervisorId() }
        : { kind: 'new', full_name: state.supervisor.name.trim(), username: state.supervisor.username.trim(), phone: state.supervisor.phone.trim(), email: state.supervisor.email.trim(), specialty: state.supervisor.specialty.trim() },
    };
    const created = state.draftRequestId
      ? await apiRequest(`/group-requests/${state.draftRequestId}/`, { method: 'PATCH', body: JSON.stringify(payload) })
      : await apiRequest('/group-requests/', { method: 'POST', body: JSON.stringify(payload) });
    state.draftRequestId = created.id;
    const submitted = await apiRequest(`/group-requests/${created.id}/submit/`, { method: 'POST', body: JSON.stringify({ version: created.version }) });
    state.draftRequestId = null;
    await loadRequests();
    state.activeRequest = demoRequests.findIndex(item => item.id === submitted.id);
    state.page = 'detail'; state.modal = null; render();
    toast('تم حفظ الطلب وإرساله إلى العميد.');
  } catch (error) {
    state.apiError = error.message; render(); toast(error.message, 'error');
  }
}

async function decideRealRequest() {
  const item = demoRequests[state.activeRequest];
  const modal = state.modal;
  if (!item || !modal) return;
  const note = document.querySelector('#modal-note')?.value.trim() || '';
  if (modal.kind !== 'approved' && !note) { toast('اكتب الملاحظات أو سبب الرفض أولًا.', 'error'); return; }
  try {
    const action = { approved: 'approve', returned: 'return', rejected: 'reject' }[modal.kind];
    await apiRequest(`/group-requests/${item.id}/${action}/`, { method: 'POST', body: JSON.stringify({ note }) });
    await loadRequests();
    state.activeRequest = demoRequests.findIndex(entry => entry.id === item.id);
    state.modal = null; render(); toast('تم حفظ القرار في النظام.');
  } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
}

document.addEventListener('click', async event => {
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
  if (action === 'logout') {
    event.preventDefault(); event.stopImmediatePropagation();
    try { await apiRequest('/auth/logout/', { method: 'POST', body: '{}' }); } catch (_) { /* انقطع الاتصال؛ نمسح الحالة المحلية على أي حال. */ }
    state.apiUser = null; state.role = null; state.page = 'overview'; state.modal = null; login(); return;
  }
  if (action === 'demo-login') { event.preventDefault(); event.stopImmediatePropagation(); return; }
  if (action === 'new-group') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const [departments, supervisors] = await Promise.all([apiRequest('/departments/'), apiRequest('/supervisors/')]);
      state.departments = departments; state.supervisors = supervisors;
      state.project = { group: '', title: '', desc: '', department: state.apiUser?.department?.name || '', departmentId: departments[0]?.id || '', year: '2026–2027' };
      state.students = [emptyStudent()]; state.supervisorType = 'existing'; state.selectedSupervisor = supervisors[0]?.id || '';
      state.supervisor = { name: '', username: '', phone: '', email: '', specialty: '' };
      state.step = 0; state.page = 'wizard'; state.modal = null; render();
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'cancel-wizard') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.page = 'overview'; state.modal = null; await loadPageData(); render(); return;
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
}, true);

document.addEventListener('submit', async event => {
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
      const authData = await apiRequest('/api-token-auth/', {
    method: 'POST',
    body: JSON.stringify({
        username: document.getElementById('username').value,
        password: document.getElementById('password').value
    })
});
localStorage.setItem('authToken', authData.token);
const userResponse = await apiRequest('/auth/me/');
startAsAuthenticated(userResponse.user);
    } catch (error) {
      state.apiError = error.message; login(); toast(error.message, 'error');
    }
  }
}, true);

(async function restoreSession() {
  try {
    const result = await apiRequest('/auth/me/');
    startAsAuthenticated(result.user);
  } catch (error) {
    state.apiError = error.message.includes('الاتصال بالخادم') ? error.message : '';
    login();
  }
})();

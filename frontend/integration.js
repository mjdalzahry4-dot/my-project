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
  
  // إضافة التوكن إلى جميع الطلبات
  const token = localStorage.getItem('authToken');
  if (token) {
    headers.set('Authorization', `Token ${token}`);
  }
  
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, method, headers });
  } catch (error) {
    throw new Error('تعذر الاتصال بالخادم. يرجى التحقق من الشبكة.');
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

  // ربط حدث إرسال النموذج
  const form = document.getElementById('login-form');
  if (form) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const username = document.getElementById('login-user').value;
      const password = document.getElementById('login-password').value;
      const button = form.querySelector('button[type="submit"]');
      
      if (button) { button.disabled = true; button.textContent = 'جاري التحقق...'; }

      try {
        // استخدام fetch مباشر لمسار التوكن
        const response = await fetch('https://MjdKhaled1.pythonanywhere.com/api-token-auth/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: username, password: password })
        });

        if (!response.ok) throw new Error('اسم المستخدم أو كلمة المرور غير صحيحة');
        
        const authData = await response.json();
        localStorage.setItem('authToken', authData.token);
        
        // جلب بيانات المستخدم باستخدام التوكن
        const userResponse = await apiRequest('/auth/me/');
        startAsAuthenticated(userResponse.user || userResponse);
        
      } catch (error) {
        if (typeof toast === 'function') {
            toast(error.message, 'error');
        } else {
            alert(error.message);
        }
        if (button) { button.disabled = false; button.textContent = 'تسجيل الدخول ←'; }
      }
    });
  }
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
  if (state.step === 2) return `<h2>المشرف الأكاديمي</h2><p class="lead">اختر مشرفًا مسجلًا أو أدخل بيانات مشرف جديد.</p><div class="choice-row"><label class="choice-card"><input type="radio" name="supervisor-type" value="existing" ${state.supervisorType === 'existing' ? 'checked' : ''} /><span><span class="choice-title">حساب مشرف موجود</span></span></label><label class="choice-card"><input type="radio" name="s

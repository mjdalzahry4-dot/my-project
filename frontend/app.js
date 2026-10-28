const roles = {
  dean: { label: 'عميد الكلية', system: 'رئيس النظام', name: '', initials: '' },
  chair: { label: 'رئيس القسم', system: 'رئيس القسم', name: '', initials: '' },
  supervisor: { label: 'المشرف الأكاديمي', system: 'مشرف أكاديمي', name: '', initials: '' },
  student: { label: 'الطالب', system: 'طالب', name: '', initials: '' },
};
const statuses = { pending: 'بانتظار اعتماد العميد', approved: 'معتمد', returned: 'معاد للتعديل', rejected: 'مرفوض', draft: 'مسودة', active: 'نشط' };
const navByRole = {
  dean: [['overview','▦','لوحة التحكم'],['requests','▤','طلبات الاعتماد'],['groups','◫','المجموعات'],['calendar','▦','المواعيد'],['users','♙','المستخدمون'],['audit','◷','سجل العمليات']],
  chair: [['overview','▦','لوحة التحكم'],['groups','◫','إدارة المجموعات'],['requests','▤','طلبات القسم'],['calendar','▦','المواعيد'],['drafts','▧','المسودات']],
  supervisor: [['overview','▦','لوحة المشرف'],['projects','◫','مشاريعي'],['deliverables','⇧','التقارير والتسليمات'],['calendar','▦','المواعيد'],['notes','▤','الملاحظات']],
  student: [['overview','▦','لوحة الطالب'],['project','◫','مشروعي'],['deliverables','⇧','التسليمات'],['calendar','▦','المواعيد']],
};
const serverRequests = [];
const state = {
  role: null, page: 'overview', step: 0, students: [emptyStudent()],
  project: { group: '', title: '', desc: '', department: '', departmentId: '', year: '' },
  supervisorType: 'existing', selectedSupervisor: '', supervisor: { name: '', username: '', phone: '', email: '', specialty: '' },
  search: '', requestFilter: 'all', modal: null, activeRequest: 0,
};

function emptyStudent() { return { name: '', username: '', phone: '' }; }
function esc(value = '') { return String(value).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c])); }
function toast(message, type = '') {
  const region = document.querySelector('#toast-region');
  if (!region) return;
  const item = document.createElement('div'); item.className = `toast ${type}`; item.textContent = message;
  region.append(item); setTimeout(() => item.remove(), 3200);
}
function login() {
  document.querySelector('#app').innerHTML = `<div class="login-page"><section class="login-art"><div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div><div class="brand-sub">Graduation Projects Management System</div></div></div><div class="art-copy"><div class="eyebrow">GPMS · بوابتك الأكاديمية</div><h1>من فكرة التخرج<br>إلى إنجاز يُفتخر به</h1><p>مساحة موحّدة تجمع الطالب والمشرف والقسم والكلية في رحلة المشروع.</p></div><div class="art-foot">الدخول بحساب النظام</div></section><section class="login-panel"><form class="login-box" id="login-form"><div class="eyebrow">مرحبًا بك</div><h2>تسجيل الدخول</h2><p>استخدم اسم المستخدم وكلمة المرور المسجلين في النظام.</p><div class="field"><label for="login-user">اسم المستخدم</label><input id="login-user" autocomplete="username" required /></div><div class="field"><label for="login-password">كلمة المرور</label><div class="input-wrap"><input id="login-password" type="password" autocomplete="current-password" required /><button type="button" class="ghost-eye" data-action="toggle-password">إظهار</button></div></div><button type="submit" class="btn btn-primary btn-block">تسجيل الدخول <span>←</span></button></form></section></div>`;
}
function currentTitle() {
  const titles = { overview:'لوحة التحكم', requests:state.role === 'dean' ? 'طلبات الاعتماد' : 'طلبات القسم', drafts:'المسودات', projects:'المشاريع المسندة', project:'تفاصيل المشروع', groups:'المجموعات', notes:'الملاحظات', users:'المستخدمون', audit:'سجل العمليات', deliverables:'التقارير والتسليمات', calendar:'المواعيد', wizard:'إنشاء مجموعة', detail:'تفاصيل الطلب' };
  return titles[state.page] || 'إدارة مشاريع التخرج';
}
function stat(label, value, icon, note = '', accent = '#0d7a6e', tint = '#e9f4f1') {
  return `<article class="stat-card" style="--accent:${accent};--tint:${tint}"><div class="stat-top"><span>${esc(label)}</span><span class="stat-icon">${icon}</span></div><div class="stat-num">${esc(value)}</div><div class="stat-note">${note}</div></article>`;
}
function statusPill(status) { return `<span class="status ${esc(status)}">${esc(statuses[status] || status)}</span>`; }
function requestRows(rows) {
  return rows.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.code)} · ${esc(item.department)}</div></div><div><span class="request-status-extra">${item.members} طلاب</span><div class="request-meta">${esc(item.date)}</div></div><div>${statusPill(item.status)}</div><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${serverRequests.indexOf(item)}">التفاصيل</button></div>`).join('');
}
function dashboard() {
  return `<div class="welcome-row"><div><div class="eyebrow">مساحة العمل</div><h1>مرحبًا، ${esc(state.apiUser?.display_name || state.apiUser?.username || '')}</h1><p>ملخص المعلومات المسجلة في النظام.</p></div></div><div class="empty-state">لا توجد بيانات مسجلة حتى الآن.</div>`;
}
function tablePage() {
  const rows = serverRequests.filter(item => (state.requestFilter === 'all' || item.status === state.requestFilter) && `${item.code} ${item.title} ${item.department}`.toLocaleLowerCase().includes(state.search.toLocaleLowerCase()));
  return `<div class="welcome-row"><h1>${currentTitle()}</h1></div><section class="panel"><input type="search" id="request-search" value="${esc(state.search)}" aria-label="بحث الطلبات" /><button class="btn btn-outline btn-sm" data-action="refresh-data">تحديث</button><div class="request-list">${rows.length ? requestRows(rows) : '<div class="empty-state">لا توجد طلبات.</div>'}</div></section>`;
}
function wizardStepContent() { return '<div class="empty-state">أدخل بيانات الطلب المطلوبة.</div>'; }
function wizard() {
  const labels = ['بيانات المشروع','أعضاء المجموعة','المشرف الأكاديمي','المراجعة والإرسال'];
  const saveDraft = state.role === 'chair' && state.step === 3 ? '<button class="btn btn-outline" data-action="save-draft">حفظ كمسودة</button>' : '';
  return `<div class="wizard-layout"><div class="steps">${labels.map((label, i) => `<div class="step ${state.step === i ? 'active' : state.step > i ? 'done' : ''}"><span class="step-number">${i + 1}</span>${label}</div>`).join('')}</div><section class="panel wizard-card">${wizardStepContent()}<div class="wizard-actions"><button class="btn btn-outline" data-action="cancel-wizard">إلغاء</button><div class="action-group">${saveDraft}${state.step ? '<button class="btn btn-outline" data-action="prev-step">السابق</button>' : ''}<button class="btn btn-primary" data-action="next-step">${state.step === 3 ? 'إرسال الطلب' : 'التالي'}</button></div></div></section></div>`;
}
function detailPage() { return '<div class="empty-state">لا توجد تفاصيل لعرضها.</div>'; }
function genericPage() { return `<div class="welcome-row"><h1>${currentTitle()}</h1></div><section class="panel"><div class="empty-state">لا توجد بيانات مسجلة.</div></section>`; }
function pageContent() {
  if (state.page === 'overview') return dashboard();
  if (state.page === 'requests') return tablePage();
  if (state.page === 'wizard') return wizard();
  if (state.page === 'detail') return detailPage();
  return genericPage();
}
function modalMarkup() {
  if (!state.modal) return '';
  const modal = state.modal;
  return `<div class="modal-backdrop" data-action="backdrop"><div class="modal" role="dialog" aria-modal="true"><h3>${esc(modal.title)}</h3><p>${esc(modal.message)}</p>${modal.input ? `<div class="field"><label for="modal-note">${esc(modal.input)}</label><textarea id="modal-note"></textarea></div>` : ''}<div class="modal-actions"><button class="btn btn-outline" data-action="close-modal">إلغاء</button><button class="btn btn-primary" data-action="confirm-decision">${esc(modal.confirm || 'تأكيد')}</button></div></div></div>`;
}
function readProject() {
  for (const [key, id] of Object.entries({ group:'group-name', title:'project-title', desc:'project-desc', department:'department', year:'academic-year' })) {
    const field = document.querySelector(`#${id}`); if (field) state.project[key] = field.value;
  }
  return state.project;
}
function render() {
  if (!state.role) return login();
  const role = roles[state.role];
  document.querySelector('#app').innerHTML = `<div class="shell"><aside class="sidebar" id="sidebar"><div class="side-brand"><div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div><div class="brand-sub">GPMS · النظام الأكاديمي</div></div></div></div><div class="side-label">القائمة الرئيسية</div><nav class="side-nav">${navByRole[state.role].map(([id, icon, label]) => `<button class="nav-item ${state.page === id ? 'active' : ''}" data-page="${id}"><span class="nav-icon">${icon}</span>${label}</button>`).join('')}</nav><div class="side-bottom"><div class="profile-chip"><div class="avatar">${esc(role.initials)}</div><div><div class="profile-name">${esc(role.name)}</div><div class="profile-role">${role.label} · ${role.system}</div></div><button class="logout" data-action="logout" aria-label="تسجيل الخروج">↪</button></div></div></aside><div class="mobile-overlay" id="mobile-overlay" data-action="close-menu"></div><div class="main-wrap"><header class="topbar"><button class="mobile-toggle" type="button" data-action="menu" aria-label="فتح القائمة" aria-expanded="false">☰</button><div><div class="top-title">${currentTitle()}</div><div class="breadcrumb">الرئيسية / ${currentTitle()}</div></div><div class="top-actions"><span class="top-date">${new Date().toLocaleDateString('ar-SA',{weekday:'long',year:'numeric',month:'long',day:'numeric'})}</span><span class="demo-pill">متصل بالخادم</span></div></header><main class="content">${pageContent()}</main></div>${modalMarkup()}</div>`;
}

document.addEventListener('click', event => {
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'toggle-password') { const input = document.querySelector('#login-password'); if (input) input.type = input.type === 'password' ? 'text' : 'password'; }
  if (action === 'menu') {
    document.querySelector('#sidebar')?.classList.add('open');
    document.querySelector('#mobile-overlay')?.classList.add('show');
    document.querySelector('.mobile-toggle')?.setAttribute('aria-expanded', 'true');
  }
  if (action === 'close-menu') {
    document.querySelector('#sidebar')?.classList.remove('open');
    document.querySelector('#mobile-overlay')?.classList.remove('show');
    document.querySelector('.mobile-toggle')?.setAttribute('aria-expanded', 'false');
  }
  if (action === 'open-request') { state.activeRequest = Number(event.target.closest('[data-action]').dataset.index); state.page = 'detail'; render(); }
  if (action === 'add-student') { state.students.push(emptyStudent()); render(); }
  if (action === 'remove-student') { state.students.splice(Number(event.target.closest('[data-action]').dataset.index), 1); render(); }
  if (action === 'prev-step') { state.step = Math.max(0, state.step - 1); render(); }
  if (action === 'next-step') { readProject(); if (state.step < 3) { state.step += 1; render(); } else { state.modal = { kind: 'submit', title: 'إرسال الطلب؟', message: 'سيُرسل الطلب إلى النظام للمراجعة.', confirm: 'إرسال' }; render(); } }
  if (action === 'close-modal' || action === 'backdrop' && event.target === event.target.closest('.modal-backdrop')) { state.modal = null; render(); }
});
document.addEventListener('input', event => {
  if (event.target.matches('[data-student]')) state.students[Number(event.target.dataset.index)][event.target.dataset.student] = event.target.value;
  if (event.target.id === 'request-search') { state.search = event.target.value; }
});
document.addEventListener('change', event => {
  if (event.target.id === 'request-filter') state.requestFilter = event.target.value;
  if (event.target.name === 'supervisor-type') state.supervisorType = event.target.value;
  if (event.target.id === 'supervisor-existing') state.selectedSupervisor = event.target.value;
});

login();

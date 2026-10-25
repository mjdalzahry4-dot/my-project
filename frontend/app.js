// 1. تعريف البيانات الأساسية
function emptyStudent() { return { name: '', username: '', phone: '' }; }

const roles = {
  dean: { label: 'عميد الكلية', system: 'رئيس النظام', name: 'د. أحمد العتيبي', initials: 'أع' },
  chair: { label: 'رئيس القسم', system: 'الوكيل', name: 'د. سارة الحربي', initials: 'سح' },
  supervisor: { label: 'المشرف الأكاديمي', system: 'مشرف أكاديمي', name: 'د. خالد المطيري', initials: 'خم' },
  student: { label: 'الطالب', system: 'طالب', name: 'ليان محمد', initials: 'لم' },
};

const statuses = { pending: 'بانتظار اعتماد العميد', approved: 'معتمد', returned: 'معاد للتعديل', rejected: 'مرفوض', draft: 'مسودة', active: 'نشط' };

const navByRole = {
  dean: [['overview','▦','لوحة التحكم'],['requests','▤','طلبات الاعتماد'],['groups','◫','المجموعات'],['users','♙','المستخدمون'],['audit','◷','سجل العمليات']],
  chair: [['overview','▦','لوحة التحكم'],['groups','◫','إدارة المجموعات'],['requests','▤','طلبات القسم'],['drafts','▧','المسودات']],
  supervisor: [['overview','▦','لوحة المشرف'],['projects','◫','مشاريعي'],['deliverables','⇧','التقارير والتسليمات'],['notes','▤','الملاحظات']],
  student: [['overview','▦','لوحة الطالب'],['project','◫','مشروعي'],['deliverables','⇧','التسليمات'],['calendar','▦','المواعيد']],
};

// تم إفراغ البيانات التجريبية هنا
const demoRequests = [];

const state = { 
  role: null, page: 'overview', step: 0, 
  students: [emptyStudent()], 
  project: { group: 'GP-027', title: '', desc: '', department: 'علوم الحاسب', year: '2026–2027' }, 
  supervisorType: 'existing', selectedSupervisor: 'د. خالد المطيري — علوم الحاسب', 
  supervisor: { name: '', username: '', phone: '', email: '', specialty: '' }, 
  search: '', requestFilter: 'all', modal: null, activeRequest: 0 
};

// 2. دوال المساعدة
function esc(value = '') { return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function toast(message, type = '') { const region = document.querySelector('#toast-region'); if (!region) return; const el = document.createElement('div'); el.className = `toast ${type}`; el.textContent = message; region.append(el); setTimeout(() => el.remove(), 3200); }
function stat(label, value, icon, note, accent = '#0d7a6e', tint = '#e9f4f1') { return `<article class="stat-card" style="--accent:${accent};--tint:${tint}"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon}</span></div><div class="stat-num">${value}</div><div class="stat-note">${note}</div></article>`; }
function statusPill(status) { return `<span class="status ${status}">${statuses[status] || status}</span>`; }

// 3. دالة تسجيل الدخول (الافتراضية)
function login() {
  document.querySelector('#app').innerHTML = `
    <div class="login-page">
      <section class="login-art">
        <div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div><div class="brand-sub">Graduation Projects Management System</div></div></div>
        <div class="art-copy"><div class="eyebrow">GPMS · بوابتك الأكاديمية</div><h1>من فكرة التخرج<br>إلى إنجاز يُفتخر به</h1><p>مساحة موحّدة تجمع الطالب والمشرف والقسم والكلية في رحلة المشروع.</p></div>
        <div class="art-foot">واجهة استعراضية · بيانات اصطناعية غير حقيقية</div>
      </section>
      <section class="login-panel">
        <form class="login-box" id="login-form">
          <div class="eyebrow">مرحبًا بك</div><h2>تسجيل الدخول</h2><p>أدخل بياناتك للوصول إلى مساحة العمل.</p>
          <div class="field"><label for="login-user">اسم المستخدم</label><input id="login-user" autocomplete="username" placeholder="اسم المستخدم" /></div>
          <div class="field"><label for="login-password">كلمة المرور</label><div class="input-wrap"><input id="login-password" type="password" autocomplete="current-password" placeholder="أدخل كلمة المرور" /><button type="button" class="ghost-eye" data-action="toggle-password">إظهار</button></div></div>
          <div class="demo-banner">هذه معاينة تجريبية. تسجيل الدخول هنا لا يتحقق من حساب أو كلمة مرور.</div>
          <button type="submit" class="btn btn-primary btn-block">دخول إلى المعاينة <span>←</span></button>
        </form>
      </section>
    </div>`;
}

// 4. دالة بدء التشغيل والرسم
function startAs(role) { state.role = role; state.page = 'overview'; state.step = 0; render(); }

function render() {
  if (!state.role) { login(); return; }
  const role = roles[state.role];
  document.querySelector('#app').innerHTML = `
    <div class="shell">
      <aside class="sidebar" id="sidebar">
        <div class="side-brand"><div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div><div class="brand-sub">GPMS · النظام الأكاديمي</div></div></div></div>
        <div class="side-label">القائمة الرئيسية</div>
        <nav class="side-nav">${navByRole[state.role].map(([id, icon, label]) => `<button class="nav-item ${state.page === id ? 'active' : ''}" data-page="${id}"><span class="nav-icon">${icon}</span>${label}</button>`).join('')}</nav>
        <div class="side-bottom"><div class="profile-chip"><div class="avatar">${role.initials}</div><div><div class="profile-name">${role.name}</div><div class="profile-role">${role.label} · ${role.system}</div></div><button class="logout" data-action="logout" aria-label="تسجيل الخروج" title="تسجيل الخروج">↪</button></div></div>
      </aside>
      <div class="main-wrap">
        <header class="topbar">
          <div style="display:flex;align-items:center;gap:12px"><button class="icon-btn mobile-toggle" data-action="menu" aria-label="فتح القائمة">☰</button><div><div class="top-title">${currentTitle()}</div><div class="breadcrumb">الرئيسية / ${currentTitle()}</div></div></div>
          <div class="top-actions"><span class="top-date">الأربعاء، 21 أكتوبر 2026</span><span class="demo-pill">◉ وضع تجريبي</span><button class="icon-btn" data-action="notifications" aria-label="الإشعارات">♧</button></div>
        </header>
        <main class="content">${pageContent()}</main>
      </div>
      ${modalMarkup()}
    </div>`;
}

function currentTitle() { const map = { overview: 'لوحة التحكم', requests: state.role === 'dean' ? 'طلبات اعتماد المجموعات' : 'طلبات القسم', groups: 'إدارة المجموعات', drafts: 'المسودات', projects: 'مشاريعي', deliverables: 'التقارير والتسليمات', notes: 'الملاحظات', project: 'مشروعي', calendar: 'المواعيد', wizard: 'إنشاء مجموعة جديدة', detail: 'تفاصيل طلب المجموعة', users: 'المستخدمون', audit: 'سجل العمليات' }; return map[state.page] || 'لوحة التحكم'; }

// 5. بناء الصفحات
function requestRows(rows) { return rows.map((r, i) => `<div class="request-row"><div><div class="request-name">${esc(r.title)}</div><div class="request-meta">${r.code} · ${r.department}</div></div><div><span class="request-status-extra">${r.members} طلاب</span><div class="request-meta">${r.date}</div></div><div>${statusPill(r.status)}</div><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${demoRequests.indexOf(r)}">التفاصيل</button></div>`).join(''); }

function dashboard() {
  const role = state.role; const welcome = role === 'dean' ? 'مرحبًا، د. أحمد' : 'مرحبًا، ' + roles[role].name;
  return `<div class="welcome-row"><div><div class="eyebrow">الأربعاء، 21 أكتوبر 2026</div><h1>${welcome} 👋</h1><p>إليك ملخص طلبات ومشاريع التخرج.</p></div></div><div class="stats-grid">${stat('طلبات بانتظار الاعتماد','0','◷','لا توجد طلبات جديدة')}${stat('مجموعات معتمدة','0','✓','خلال العام الدراسي الحالي')}${stat('مشاريع نشطة','0','◫','موزعة على الأقسام')}${stat('طلبات معادة للتعديل','0','↶','تحتاج متابعة من القسم')}</div><div class="panel"><div class="panel-head"><div><h2 class="panel-title">أحدث الطلبات</h2><div class="panel-sub">تتبع حالة الطلبات المرسلة حديثًا</div></div></div><div class="request-list">${demoRequests.length ? requestRows(demoRequests) : '<div class="empty-state">لا توجد طلبات حتى الآن.</div>'}</div></div>`;
}

function tablePage() {
  let rows = demoRequests.filter(r => { const matches = (`${r.code} ${r.title} ${r.department}`).toLowerCase().includes(state.search.toLowerCase()); return matches && (state.requestFilter === 'all' || r.status === state.requestFilter); });
  return `<div class="welcome-row"><div><h1>${currentTitle()}</h1></div></div><section class="table-panel" style="padding:19px"><div class="panel-head"><div><h2 class="panel-title">كل الطلبات</h2></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>المشروع</th><th>القسم</th><th>الحالة</th></tr></thead><tbody>${rows.length ? rows.map(r => `<tr><td>${esc(r.title)}</td><td>${r.department}</td><td>${statusPill(r.status)}</td></tr>`).join('') : '<tr><td colspan="3"><div class="empty-state">لا توجد طلبات.</div></td></tr>'}</tbody></table></div></section>`;
}

function wizard() {
  const labels = ['بيانات المشروع', 'أعضاء المجموعة', 'المشرف الأكاديمي', 'المراجعة والإرسال'];
  return `<div class="wizard-layout"><div class="welcome-row"><div><h1>إنشاء مجموعة جديدة</h1></div></div><div class="steps">${labels.map((label, i) => `<div class="step ${i === state.step ? 'active' : i < state.step ? 'done' : ''}"><span class="step-number">${i < state.step ? '✓' : i + 1}</span><span>${label}</span></div>`).join('')}</div><section class="panel wizard-card">${wizardStepContent()}<div class="wizard-actions"><button class="btn btn-outline" data-action="cancel-wizard">حفظ كمسودة والخروج</button><div class="action-group">${state.step > 0 ? '<button class="btn btn-outline" data-action="prev-step">→ السابق</button>' : ''}${state.step < 3 ? '<button class="btn btn-primary" data-action="next-step">التالي <span>←</span></button>' : '<button class="btn btn-teal" data-action="submit-request">إرسال الطلب إلى العميد</button>'}</div></div></section></div>`;
}

function wizardStepContent() {
  if (state.step === 0) return `<h2>بيانات المجموعة والمشروع</h2><div class="form-grid"><div class="field"><label>اسم المجموعة *</label><input id="group-name" value="${esc(state.project.group)}" /></div><div class="field full"><label>عنوان المشروع المقترح *</label><input id="project-title" value="${esc(state.project.title)}" /></div><div class="field full"><label>القسم العلمي *</label><select id="department"><option>علوم الحاسب</option><option>نظم المعلومات</option></select></div></div>`;
  if (state.step === 1) return `<h2>أعضاء المجموعة</h2><div class="empty-state">سيتم إضافة الحقول هنا.</div>`;
  if (state.step === 2) return `<h2>المشرف الأكاديمي</h2><div class="empty-state">سيتم إضافة الخيارات هنا.</div>`;
  if (state.step === 3) return `<h2>المراجعة والإرسال</h2><div class="empty-state">مراجعة البيانات قبل الإرسال.</div>`;
  return '';
}

function detailPage() { const r = demoRequests[state.activeRequest]; if (!r) return `<div class="empty-state">تعذر العثور على الطلب.</div>`; return `<div class="welcome-row"><div><h1>${esc(r.title)}</h1></div></div><button class="btn btn-outline" data-page="requests">→ رجوع</button>`; }
function modalMarkup() { if (!state.modal) return ''; return `<div class="modal-backdrop"><div class="modal"><h3>${esc(state.modal.title)}</h3></div></div>`; }

function pageContent() {
  switch (state.page) {
    case 'overview': return dashboard();
    case 'requests': return tablePage();
    case 'wizard': return wizard();
    case 'detail': return detailPage();
    default: return dashboard();
  }
}

// 6. مستمعو الأحداث (لجعل الأزرار تعمل)
document.addEventListener('click', (e) => {
  const target = e.target.closest('[data-page], [data-action]');
  if (!target) return;

  if (target.dataset.page) {
    state.page = target.dataset.page;
    if (state.page === 'wizard') state.step = 0;
    render();
    return;
  }

  const action = target.dataset.action;
  if (action === 'logout') {
    localStorage.removeItem('authToken');
    state.role = null;
    state.apiUser = null;
    if (typeof login === 'function') login(); else render();
  } else if (action === 'new-group') {
    state.page = 'wizard';
    state.step = 0;
    render();
  } else if (action === 'next-step') {
    state.step++;
    render();
  } else if (action === 'prev-step') {
    state.step--;
    render();
  } else if (action === 'cancel-wizard') {
    state.page = 'overview';
    render();
  }
});

// 7. بدء التشغيل
render();

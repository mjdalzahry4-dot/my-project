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
state.groupMemberships = null;
state.projectPlans = [];
state.projectIdeas = [];
state.projectCommittee = null;
state.committeeDepartmentId = '';
state.ideaQueue = [];
state.projectDeliverables = [];
state.readinessRequests = [];
state.defenseData = { referred_requests: [], committees: [] };
state.defenseRubric = [];
state.defenseEvaluationId = '';
state.defenseEvaluation = null;
state.postDefenseProjectId = '';
state.postDefense = null;
state.deliverables = [];
state.projectStages = [];
state.projectTasks = [];
state.notifications = [];
state.unreadNotifications = 0;
state.appointments = [];
state.editingAppointmentId = null;
state.activationLink = '';
state.activationToken = (() => {
  const match = String(window.location?.search || '').match(/[?&]activation=([^&]*)/);
  try { return match ? decodeURIComponent(match[1].replace(/\+/g, ' ')) : ''; }
  catch (_) { return ''; }
})();

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
    id: item.id, version: item.version, status, createdBy: item.created_by_name || '',
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
    if (['overview', 'requests', 'detail', 'drafts'].includes(state.page) && state.role !== 'supervisor') await loadRequests();
    if (['groups', 'overview'].includes(state.page)) state.groups = await apiRequest('/groups/');
    if (state.page === 'users' && ['dean', 'chair'].includes(state.role)) state.users = await apiRequest('/users/');
    if (state.page === 'committees' && ['dean', 'chair'].includes(state.role)) {
      if (state.role === 'dean') state.departments = await apiRequest('/departments/');
      else if (state.apiUser?.department) state.departments = [state.apiUser.department];
      if (!state.committeeDepartmentId || !state.departments.some(department => department.id === state.committeeDepartmentId)) state.committeeDepartmentId = state.departments[0]?.id || '';
      state.users = await apiRequest('/users/');
      state.projectCommittee = state.committeeDepartmentId ? await apiRequest(`/departments/${state.committeeDepartmentId}/project-committee/`) : null;
    }
    if (state.page === 'committees' && state.role === 'supervisor') state.ideaQueue = await apiRequest('/project-idea-reviews/');
    if (state.page === 'committees' && ['dean', 'chair', 'supervisor'].includes(state.role)) {
      state.defenseData = await apiRequest('/defense-committees/');
      if (state.role === 'dean') state.defenseRubric = await apiRequest('/defense-rubric/');
      state.defenseEvaluation = state.defenseEvaluationId ? await apiRequest(`/defense-committees/${encodeURIComponent(state.defenseEvaluationId)}/evaluation/`) : null;
      state.postDefense = state.postDefenseProjectId ? await apiRequest(`/projects/${encodeURIComponent(state.postDefenseProjectId)}/post-defense/`) : null;
    }
    if (state.page === 'calendar') {
      state.appointments = await apiRequest('/appointments/');
      if (['dean', 'chair'].includes(state.role)) {
        const required = [apiRequest('/projects/')];
        if (state.role === 'dean') required.push(apiRequest('/departments/'));
        const [projects, departments] = await Promise.all(required);
        state.projects = projects;
        if (departments) state.departments = departments;
      }
    }
    if (state.page === 'reports') {
      if (state.role === 'dean') state.departments = await apiRequest('/departments/');
      else if (state.role === 'chair' && state.apiUser?.department) state.departments = [state.apiUser.department];
    }
    if (['projects', 'project', 'overview', 'notes'].includes(state.page)) {
      state.projects = await apiRequest('/projects/');
      if (['project', 'notes'].includes(state.page) && !state.currentProjectId) state.currentProjectId = state.projects[0]?.id || null;
    }
    if (state.page === 'deliverables' && ['student', 'supervisor'].includes(state.role)) {
      state.projects = await apiRequest('/projects/');
      if (!state.currentProjectId || !state.projects.some(project => project.id === state.currentProjectId)) state.currentProjectId = state.projects[0]?.id || null;
      state.deliverables = state.currentProjectId ? await apiRequest(`/projects/${state.currentProjectId}/deliverables/`) : [];
      state.projectStages = state.currentProjectId ? await apiRequest(`/projects/${state.currentProjectId}/stages/`) : [];
      state.projectTasks = state.currentProjectId ? await apiRequest(`/projects/${state.currentProjectId}/tasks/`) : [];
    }
    if (state.page === 'project' && state.currentProjectId) {
      const [project, stages, tasks, plans, ideas, deliverables, readiness, postDefense] = await Promise.all([apiRequest(`/projects/${state.currentProjectId}/`), apiRequest(`/projects/${state.currentProjectId}/stages/`), apiRequest(`/projects/${state.currentProjectId}/tasks/`), apiRequest(`/projects/${state.currentProjectId}/plans/`), apiRequest(`/projects/${state.currentProjectId}/ideas/`), apiRequest(`/projects/${state.currentProjectId}/deliverables/`), apiRequest(`/projects/${state.currentProjectId}/discussion-readiness/`), apiRequest(`/projects/${state.currentProjectId}/post-defense/`)]);
      state.projectDetail = project;
      state.groupMemberships = state.role === 'chair' ? await apiRequest(`/groups/${encodeURIComponent(project.group.id)}/members/`) : null;
      if (state.role === 'chair') state.supervisors = await apiRequest('/supervisors/');
      state.projectStages = stages;
      state.projectTasks = tasks;
      state.projectPlans = plans;
      state.projectIdeas = ideas;
      state.projectDeliverables = deliverables;
      state.readinessRequests = readiness;
      state.postDefense = postDefense;
      state.postDefenseProjectId = state.currentProjectId;
      if (['dean', 'chair'].includes(state.role) || (state.role === 'supervisor' && state.apiUser?.department?.id === project.group.department.id)) state.projectCommittee = await apiRequest(`/departments/${project.group.department.id}/project-committee/`);
    }
    if (state.page === 'notes' && state.currentProjectId) state.projectNotes = await apiRequest(`/projects/${state.currentProjectId}/notes/`);
    if (state.page === 'audit' && state.role === 'dean') state.auditEvents = await apiRequest('/audit-log/');
    const notificationData = await apiRequest('/notifications/');
    state.notifications = notificationData.items || [];
    state.unreadNotifications = notificationData.unread_count || 0;
  } catch (error) {
    state.apiError = error.message;
  }
}

function renderTeamPresence(members) {
  return (members || []).filter(member => !member.left_at).map(member => `<article class="request-row"><div><strong>${esc(member.full_name)}${member.is_leader ? ' · قائد المجموعة' : ''}</strong><div class="request-meta">${member.is_online ? '<span class="status active">متصل الآن</span>' : '<span class="status">غير متصل</span>'}${member.last_activity_at ? ` · آخر نشاط: ${esc(safeDate(member.last_activity_at))}` : ' · لم يسجل نشاطًا بعد'}</div></div></article>`).join('') || '<div class="empty-state">لا توجد عضويات نشطة.</div>';
}

async function refreshTeamPresence() {
  if (state.page !== 'project' || !state.currentProjectId || !state.apiToken) return;
  try {
    const project = await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/`);
    if (state.page !== 'project' || project.id !== state.currentProjectId) return;
    state.projectDetail = project;
    const list = document.querySelector('#team-presence-list');
    if (list) list.innerHTML = renderTeamPresence(project.group.members);
  } catch (_) { /* تعرض الواجهة خطأ الاتصال العام؛ لا نمسح محتوى المشروع غير المتصل. */ }
}

if (typeof window.setInterval === 'function') window.setInterval(refreshTeamPresence, 60_000);

let notificationRefreshInFlight = false;
async function refreshNotifications() {
  if (!state.apiToken || notificationRefreshInFlight || (typeof document !== 'undefined' && document.visibilityState === 'hidden')) return;
  notificationRefreshInFlight = true;
  try {
    const data = await apiRequest('/notifications/');
    const items = data.items || [];
    const changed = state.unreadNotifications !== (data.unread_count || 0)
      || state.notifications.map(item => `${item.id}:${item.read_at || ''}`).join('|') !== items.map(item => `${item.id}:${item.read_at || ''}`).join('|');
    state.notifications = items;
    state.unreadNotifications = data.unread_count || 0;
    if (changed && state.role) render();
  } catch (_) { /* تعاد المحاولة في الدورة التالية؛ لا نمسح الإشعارات المحفوظة عند انقطاع الاتصال. */ }
  finally { notificationRefreshInFlight = false; }
}

if (typeof window.setInterval === 'function') window.setInterval(refreshNotifications, 30_000);

function renderDefenseEvaluation() {
  const data = state.defenseEvaluation;
  if (!data) return '';
  const scoresFor = (evaluation, criterionId, studentId = null) => evaluation?.scores?.find(row => row.criterion_id === criterionId && (row.student_id || null) === (studentId || null));
  const myEvaluation = data.my_evaluation;
  const canScore = state.role === 'supervisor' && !myEvaluation && !data.closed;
  const projectCriteria = data.criteria.filter(item => item.scope === 'project');
  const studentCriteria = data.criteria.filter(item => item.scope === 'student');
  const scoreField = (criterion, student = null) => {
    const saved = scoresFor(myEvaluation, criterion.id, student?.id || null);
    const key = `${criterion.id}:${student?.id || 'project'}`;
    return `<div class="field"><label>${esc(criterion.title)} · الوزن ${esc(criterion.weight)}%${student ? ` · ${esc(student.name)}` : ' · تقييم جماعي'}</label>${criterion.description ? `<span class="help">${esc(criterion.description)}</span>` : ''}<input data-eval-score data-criterion-id="${esc(criterion.id)}" data-student-id="${esc(student?.id || '')}" type="number" min="0" max="100" step="0.01" required ${canScore ? '' : 'disabled'} value="${esc(saved?.score || '')}"/><textarea data-eval-note data-note-key="${esc(key)}" maxlength="2000" placeholder="ملاحظة لهذا التقييم" ${canScore ? '' : 'disabled'}>${esc(saved?.note || '')}</textarea></div>`;
  };
  const scoreForm = canScore ? `<form id="defense-evaluation-form"><h3>تقييم جماعي للمشروع</h3><div class="form-grid">${projectCriteria.map(criterion => scoreField(criterion)).join('')}</div><h3>التقييم الفردي</h3>${data.students.map(student => `<section class="review-member"><strong>${esc(student.name)}</strong><div class="form-grid">${studentCriteria.map(criterion => scoreField(criterion, student)).join('')}</div></section>`).join('')}<p class="panel-sub">إرسالك نهائي ولا يمكن تعديله. تبقى درجات جميع الأعضاء سرية حتى يرسل كل عضو تقييمه.</p><button class="btn btn-teal" type="submit">إرسال التقييم السري</button></form>` : '';
  const meeting = data.meeting || {};
  const meetingMinutes = data.can_record_minutes ? `<form id="defense-minutes-form" class="form-grid"><h3 class="field full">محضر المناقشة</h3><div class="field full"><label>المحضر *</label><textarea name="minutes" maxlength="12000" required>${esc(meeting.minutes || '')}</textarea></div><div class="field full"><button class="btn btn-outline" type="submit">حفظ محضر اللجنة</button></div></form>` : meeting.minutes ? `<section class="review-member"><strong>محضر المناقشة · ${esc(safeDate(meeting.minutes_recorded_at))}</strong><p>${esc(meeting.minutes)}</p></section>` : '';
  const evaluations = data.evaluations.map(evaluation => `<article class="review-member"><strong>${esc(evaluation.reviewer_name)}</strong> · ${esc(safeDate(evaluation.submitted_at))}<div class="request-list">${evaluation.scores.map(row => { const criterion = data.criteria.find(item => item.id === row.criterion_id); const student = data.students.find(item => item.id === row.student_id); return `<div class="request-meta">${esc(criterion?.title || 'معيار')} ${student ? `· ${esc(student.name)}` : '· المشروع'}: <b>${esc(row.score)}</b>${row.note ? ` — ${esc(row.note)}` : ''}</div>`; }).join('')}</div></article>`).join('');
  return `<section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2 class="panel-title">تقييم لجنة المناقشة · ${esc(data.project_title)}</h2><p class="panel-sub">التقييمات المرسلة: ${data.submitted_count} من ${data.total_count} · ${data.closed ? 'أغلقت التقييمات السرية' : 'الدرجات مخفية حتى اكتمال الإرسال'}</p></div><div class="action-group"><button class="btn btn-outline btn-sm" data-action="open-post-defense" data-project-id="${esc(data.project_id)}">ملاحظات ما بعد المناقشة</button><button class="btn btn-outline btn-sm" data-action="close-defense-evaluation">إغلاق</button></div></div>${meeting.defense_at ? `<p class="request-meta">موعد المناقشة: ${esc(safeDate(meeting.defense_at))} · ${esc(meeting.location || '')}</p>` : '<p class="request-meta">لم يحدد موعد جلسة المناقشة بعد.</p>'}${meetingMinutes}${myEvaluation && !data.closed ? '<div class="notice warn">تم استلام تقييمك النهائي. لا يمكن تعديله، وستظهر التقييمات بعد إكمال بقية أعضاء اللجنة.</div>' : ''}${scoreForm}${data.evaluations.length ? `<h3>التقييمات بعد الإغلاق</h3>${evaluations}<p class="panel-sub">هذه درجات الأعضاء الفردية. لم تُحتسب نتيجة نهائية بعد لأن آلية دمج درجات الأعضاء غير مضبوطة في إعدادات النظام.</p>` : ''}</section>`;
}

function renderPostDefense() {
  const data = state.postDefense;
  if (!data?.committee_id) return '';
  const deliverables = state.projectDeliverables || [];
  const options = deliverables.map(file => `<option value="${esc(file.id)}">${esc(file.original_filename)} · ${esc(safeDate(file.created_at))}</option>`).join('');
  const revisionRows = data.revisions.map(item => `<article class="review-member"><strong>${esc(item.description)}</strong><div class="request-meta">المكلف: ${esc(item.assigned_to_name)} · الموعد: ${esc(safeDate(item.due_at))} · الحالة: ${esc({ open: 'مطلوب تنفيذها', submitted: 'بانتظار مراجعة المشرف', changes_requested: 'تحتاج استكمالًا', approved: 'معتمدة' }[item.status] || item.status)}</div>${item.evidence_id ? `<a href="${API_BASE}/deliverables/${encodeURIComponent(item.evidence_id)}/download/" data-download-id="${esc(item.evidence_id)}">دليل التنفيذ: ${esc(item.evidence_filename)}</a>` : ''}${item.supervisor_note ? `<p><b>ملاحظة المشرف:</b> ${esc(item.supervisor_note)}</p>` : ''}${state.role === 'student' && item.assigned_to === state.apiUser?.id && ['open', 'changes_requested'].includes(item.status) ? `<form class="post-defense-revision-submit-form" data-revision-id="${esc(item.id)}"><label>ملف دليل التنفيذ *</label><select name="evidence_id" required><option value="">اختر ملفًا رفعته للمشروع</option>${options}</select><button class="btn btn-teal btn-sm" type="submit">إرسال الدليل للمشرف</button></form>` : ''}${state.role === 'supervisor' && data.is_assigned_supervisor && item.status === 'submitted' ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="review-post-defense-revision" data-revision-id="${esc(item.id)}" data-decision="approved">اعتماد التعديل</button><button class="btn btn-outline btn-sm" data-action="review-post-defense-revision" data-revision-id="${esc(item.id)}" data-decision="changes_requested">طلب استكمال</button></div>` : ''}</article>`).join('');
  const createRevision = data.can_record_revision ? `<form id="post-defense-revision-form" class="form-grid"><div class="field full"><label>ملاحظة لجنة المناقشة *</label><textarea name="description" maxlength="3000" required></textarea></div><div class="field"><label>الطالب المسؤول *</label><select name="assigned_to" required><option value="">اختر الطالب</option>${data.students.map(student => `<option value="${esc(student.id)}">${esc(student.name)}</option>`).join('')}</select></div><div class="field"><label>الموعد المحدد *</label><input type="date" name="due_at" required /></div><div class="field full"><button class="btn btn-teal" type="submit">إضافة تعديل بعد المناقشة</button></div></form>` : '';
  const latestFinal = data.final_submissions[0];
  const allRevisionsApproved = data.revisions.every(item => item.status === 'approved');
  const finalSubmissionForm = data.is_group_leader && data.evaluations_closed && allRevisionsApproved && (!latestFinal || latestFinal.status === 'changes_requested') ? `<form id="post-defense-final-form" class="form-grid"><div class="field full"><label>النسخة النهائية المنقحة *</label><select name="deliverable_id" required><option value="">اختر ملفًا رفعته للمشروع</option>${options}</select></div><div class="field full"><button class="btn btn-teal" type="submit">إرسال النسخة النهائية للمشرف</button></div></form>` : '';
  const finalRows = data.final_submissions.map(item => `<article class="review-member"><strong>النسخة النهائية · الإصدار ${item.version}</strong><div class="request-meta">${esc(item.filename)} · الحالة: ${esc({ submitted: 'بانتظار الاعتماد الفني', changes_requested: 'تحتاج استكمالًا', approved: 'معتمدة فنيًا' }[item.status] || item.status)}</div><a href="${API_BASE}/deliverables/${encodeURIComponent(item.deliverable_id)}/download/" data-download-id="${esc(item.deliverable_id)}">تنزيل النسخة</a>${item.supervisor_note ? `<p><b>ملاحظة المشرف:</b> ${esc(item.supervisor_note)}</p>` : ''}${state.role === 'supervisor' && data.is_assigned_supervisor && item.status === 'submitted' ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="review-post-defense-final" data-submission-id="${esc(item.id)}" data-decision="approved">اعتماد النسخة فنيًا</button><button class="btn btn-outline btn-sm" data-action="review-post-defense-final" data-submission-id="${esc(item.id)}" data-decision="changes_requested">إعادة للاستكمال</button></div>` : ''}</article>`).join('');
  return `<section class="panel" style="margin-top:18px"><h2 class="panel-title">تعديلات ما بعد المناقشة</h2><p class="panel-sub">تسجل اللجنة الملاحظات وتكلف الطلاب، ويراجع المشرف أدلة التنفيذ. لا تقبل النسخة النهائية قبل إغلاق التقييمات واعتماد جميع الملاحظات.</p>${revisionRows || '<div class="empty-state">لم تسجل اللجنة تعديلات.</div>'}${createRevision}<h3 style="margin-top:18px">اعتماد النسخة النهائية فنيًا</h3>${finalRows || '<div class="empty-state">لم تُرسل نسخة نهائية منقحة.</div>'}${finalSubmissionForm}</section>`;
}

function connectionNotice() {
  return state.apiError ? `<div class="notice warn" role="alert">${esc(state.apiError)}</div>` : '';
}

function apiStatusName(value) {
  return value === 'pending_approval' ? 'pending' : value;
}

const originalLogin = login;
login = function connectedLogin() {
  if (state.activationToken) {
    document.querySelector('#app').innerHTML = `<div class="login-page"><section class="login-art"><div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div><div class="brand-sub">تفعيل حساب الطالب</div></div></div><div class="art-copy"><div class="eyebrow">خطوة أخيرة</div><h1>أنشئ كلمة مرورك<br>وابدأ مشروعك</h1><p>الرابط صالح لمرة واحدة ولمدة ساعة من إصداره.</p></div></section><section class="login-panel"><form class="login-box" id="activate-account-form"><div class="eyebrow">تفعيل آمن</div><h2>تعيين كلمة المرور</h2><div class="field"><label for="activation-password">كلمة مرور جديدة</label><input id="activation-password" type="password" autocomplete="new-password" minlength="12" required /><span class="help">استخدم 12 خانة على الأقل.</span></div><div class="field"><label for="activation-password-confirm">تأكيد كلمة المرور</label><input id="activation-password-confirm" type="password" autocomplete="new-password" minlength="12" required /></div>${connectionNotice()}<button type="submit" class="btn btn-primary btn-block">تفعيل الحساب</button></form></section></div>`;
    return;
  }
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
  const topActions = document.querySelector('.topbar .top-actions');
  if (topActions) {
    topActions.querySelector('[data-notification-bell]')?.remove();
    topActions.insertAdjacentHTML('afterbegin', `<button type="button" class="btn btn-outline btn-sm" data-page="notifications" data-notification-bell aria-label="الإشعارات، ${state.unreadNotifications} غير مقروءة">♧${state.unreadNotifications ? ` <span class="status pending">${state.unreadNotifications}</span>` : ''}</button>`);
  }
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
  const title = isSubmit ? 'إرسال الطلب إلى رئيس القسم؟' : modal.title;
  const message = isSubmit ? 'سيُحفظ الطلب ويرسل لرئيس القسم للمراجعة. لن تنشأ المجموعة أو حسابات الطلاب قبل الاعتماد.' : isDecision ? 'سيُحفظ القرار وملاحظاته في النظام ويظهر أثره للمستخدمين المخولين.' : modal.message;
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
    chair: '<button class="btn btn-outline" data-page="requests">مراجعة طلبات القسم ←</button>',
    supervisor: '<button class="btn btn-outline" data-page="projects">مشاهدة المشاريع المسندة ←</button>',
    student: '<button class="btn btn-teal" data-page="requests">＋ طلب مجموعة</button>',
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
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">مساحة العمل · ${esc(state.apiUser?.department?.name || 'نظام إدارة مشاريع التخرج')}</div><h1>مرحبًا، ${esc(lead)} 👋</h1><p>${state.role === 'dean' ? 'تابع طلبات الكلية وفعّل حسابات الطلاب.' : state.role === 'chair' ? 'راجع طلبات المجموعات وأدر مشاريع قسمك.' : state.role === 'supervisor' ? 'تابع المشاريع المسندة وملاحظات الفرق.' : 'قدّم طلب مجموعتك وتابع مشروعك وملفات التسليم.'}</p></div>${roleAction}</div><div class="stats-grid">${metrics}</div><section class="panel"><div class="panel-head"><div><h2 class="panel-title">${sectionTitle}</h2><div class="panel-sub">الحالة محفوظة على الخادم</div></div>${sectionAction}</div><div class="request-list">${sectionRows}</div></section>`;
};

requestRows = function connectedRequestRows(rows) {
  return rows.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.code)} · ${esc(item.department)}</div></div><div><span class="request-status-extra">${item.members} طلاب</span><div class="request-meta">${esc(item.date)}</div></div><div>${statusPill(item.status)}</div><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${serverRequests.indexOf(item)}">التفاصيل</button></div>`).join('');
};

tablePage = function connectedTablePage() {
  const rows = serverRequests.filter(item => (state.requestFilter === 'all' || item.status === state.requestFilter) && `${item.code} ${item.title} ${item.department}`.toLocaleLowerCase().includes(state.search.toLocaleLowerCase()));
  const canCreate = state.role === 'student' ? '<button class="btn btn-teal" data-action="new-group">＋ طلب مجموعة جديدة</button>' : '';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">${state.role === 'dean' ? 'متابعة على مستوى الكلية' : state.role === 'chair' ? 'مراجعة طلبات القسم' : 'طلباتك للمجموعات'}</div><h1>${currentTitle()}</h1><p>الطلبات المعروضة من قاعدة البيانات وبحسب صلاحية حسابك.</p></div>${canCreate}</div><section class="table-panel" style="padding:19px"><div class="panel-head"><div><h2 class="panel-title">${state.role === 'student' ? 'طلباتي' : 'كل الطلبات'}</h2><div class="panel-sub">${rows.length} طلبات</div></div><button class="btn btn-outline btn-sm" data-action="refresh-data">تحديث</button></div><form id="request-filter-form" class="filters"><input type="search" id="request-search" value="${esc(state.search)}" placeholder="ابحث باسم المشروع أو الرقم..." aria-label="بحث الطلبات" /><select id="request-filter" aria-label="تصفية الحالة"><option value="all">كل الحالات</option>${Object.entries(statuses).filter(([key]) => !['active', 'draft'].includes(key)).map(([key, value]) => `<option value="${key}" ${state.requestFilter === key ? 'selected' : ''}>${value}</option>`).join('')}</select><button class="btn btn-outline btn-sm" type="submit">بحث</button></form><div class="table-scroll"><table class="data-table"><thead><tr><th>رقم الطلب / المشروع</th><th>القسم</th><th>الأعضاء</th><th>المشرف</th><th>تاريخ الإرسال</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>${rows.length ? rows.map(item => `<tr><td><div class="table-strong">${esc(item.title)}</div><small>${esc(item.code)}</small></td><td>${esc(item.department)}</td><td>${item.members}</td><td>${esc(item.supervisor)}</td><td>${esc(item.date)}</td><td>${statusPill(item.status)}</td><td><button class="btn btn-outline btn-sm" data-action="open-request" data-index="${serverRequests.indexOf(item)}">عرض الطلب</button></td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">لا توجد طلبات تطابق البحث أو التصفية.</div></td></tr>'}</tbody></table></div>${connectionNotice()}</section>`;
};

detailPage = function connectedDetailPage() {
  const item = serverRequests[state.activeRequest];
  if (!item) return `${connectionNotice()}<div class="empty-state">تعذر العثور على الطلب. <button class="btn btn-outline" data-page="requests">العودة للطلبات</button></div>`;
  const revision = item.revision || {};
  const supervisor = item.supervisorDetail || {};
  const decisions = item.decisions.map(entry => `<div class="review-member">${esc(entry.decision)} · ${esc(entry.actor_name || '')}<div class="request-meta">${esc(entry.note || '')} · ${esc(safeDate(entry.created_at))}</div></div>`).join('');
  const members = item.memberDetails.map((member, index) => `<div class="review-member">${index + 1}. ${esc(member.full_name)} <span style="color:var(--muted)">· ${esc(member.username_proposed)} · ${esc(member.phone_proposed)}</span></div>`).join('');
  const actions = state.role === 'chair' && item.status === 'pending' && item.createdBy !== state.apiUser?.username ? `<div style="display:grid;gap:8px;margin-top:16px"><button class="btn btn-teal" data-action="decision" data-decision="approved">✓ اعتماد المجموعة كاملة</button><button class="btn btn-soft" data-action="decision" data-decision="returned">↶ إعادة للتعديل</button><button class="btn btn-danger" data-action="decision" data-decision="rejected">× رفض الطلب</button></div>` : state.role === 'chair' && item.status === 'pending' ? '<div class="notice warn">لا يمكنك اتخاذ قرار على طلب أنشأه حسابك.</div>' : state.role === 'student' && ['draft', 'returned'].includes(item.status) ? '<div style="margin-top:16px"><button class="btn btn-outline" data-action="resume-draft" data-request-id="' + esc(item.id) + '">تعديل الطلب وإعادة إرساله</button></div>' : '';
  return `${connectionNotice()}<div class="welcome-row"><div><div class="eyebrow">${esc(item.code)} · تفاصيل الطلب</div><h1>${esc(item.title)}</h1><p>مقدم من ${esc(item.department)} · ${esc(item.date)}</p></div>${statusPill(item.status)}</div><div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2 class="panel-title">بيانات المشروع</h2><div class="panel-sub">العام الدراسي ${esc(item.year)}</div></div></div><div class="review-grid"><div class="review-item"><span>القسم</span><strong>${esc(item.department)}</strong></div><div class="review-item"><span>المجموعة</span><strong>${esc(item.code)}</strong></div><div class="review-item"><span>عدد الطلاب</span><strong>${item.members}</strong></div><div class="review-item"><span>المشرف المقترح</span><strong>${esc(supervisor.full_name || item.supervisor)}</strong></div><div class="review-item full"><span>وصف المشروع</span><strong>${esc(item.desc)}</strong></div></div><div class="review-section"><strong style="font-size:12px">أعضاء المجموعة</strong>${members}</div></section><section class="panel"><div class="panel-head"><div><h2 class="panel-title">سجل الطلب والقرارات</h2><div class="panel-sub">المراجعة الحالية رقم ${revision.revision_number || '—'}</div></div></div><div class="review-member">● &nbsp;${statusPill(item.status)}<div class="request-meta">${esc(item.date)}</div></div>${decisions || '<div class="request-meta">لا توجد قرارات سابقة.</div>'}${actions}</section></div><button class="btn btn-outline" data-page="requests">→ رجوع إلى الطلبات</button>`;
};

wizardStepContent = function connectedWizardContent() {
  if (state.step === 0) return `<h2>بيانات المجموعة والمشروع</h2><p class="lead">أدخل المعلومات الأساسية للطلب.</p><div class="form-grid"><div class="field"><label for="group-name">رمز المجموعة *</label><input id="group-name" placeholder="مثال: CS-2026-01" value="${esc(state.project.group)}" required /></div><div class="field"><label for="academic-year">العام الدراسي *</label><input id="academic-year" value="${esc(state.project.year)}" required /></div><div class="field full"><label for="project-title">عنوان المشروع المقترح *</label><input id="project-title" value="${esc(state.project.title)}" required /></div><div class="field full"><label for="project-desc">وصف المشروع وأهدافه الأولية *</label><textarea id="project-desc" required>${esc(state.project.desc)}</textarea></div><div class="field full department-picker-field"><label id="department-label" for="department-picker">القسم العلمي *</label><button id="department-picker" class="department-picker-trigger" type="button" role="combobox" aria-haspopup="listbox" aria-controls="department-options" aria-expanded="${state.departmentMenuOpen ? 'true' : 'false'}" aria-labelledby="department-label" data-action="toggle-department-menu"><span>${esc(state.departments.find(item => item.id === state.project.departmentId)?.name || 'اختر القسم العلمي')}</span><span aria-hidden="true">▾</span></button><input type="hidden" id="department" value="${esc(state.project.departmentId || '')}" /><div class="department-picker-menu ${state.departmentMenuOpen ? 'is-open' : ''}" id="department-options" role="listbox" aria-labelledby="department-label">${state.departments.length ? state.departments.map(department => `<button type="button" class="department-picker-option ${state.project.departmentId === department.id ? 'is-selected' : ''}" role="option" aria-selected="${state.project.departmentId === department.id}" data-action="select-department" data-department-id="${esc(department.id)}">${esc(department.name)}</button>`).join('') : '<div class="department-picker-empty">لا توجد أقسام متاحة للاختيار.</div>'}</div></div></div>`;
  if (state.step === 1) return `<div class="panel-head"><div><h2>أعضاء المجموعة</h2><p class="lead">أضف بيانات الطلاب؛ يجب أن يكون حسابك ضمن الأعضاء. ينشأ حساب الطالب الجديد بعد اعتماد رئيس القسم، ثم يفعّله العميد.</p></div><button class="btn btn-soft btn-sm" data-action="add-student">＋ إضافة طالب</button></div><div id="students-list">${state.students.map((student, index) => `<div class="member-card"><div class="member-head"><div class="member-title"><span class="member-index">${index + 1}</span>بيانات الطالب ${index + 1}</div>${state.students.length > 1 && !(state.role === 'student' && student.username.toLocaleLowerCase() === state.apiUser?.username?.toLocaleLowerCase()) ? `<button class="btn btn-danger btn-sm" data-action="remove-student" data-index="${index}">حذف</button>` : ''}</div><div class="form-grid"><div class="field"><label>الاسم الكامل *</label><input data-student="name" data-index="${index}" value="${esc(student.name)}" /></div><div class="field"><label>اسم المستخدم *</label><input data-student="username" data-index="${index}" value="${esc(student.username)}" /></div><div class="field"><label>رقم الجوال *</label><input data-student="phone" data-index="${index}" value="${esc(student.phone)}" inputmode="tel" /></div></div></div>`).join('')}</div>`;
  if (state.step === 2) return `<h2>المشرف الأكاديمي</h2><p class="lead">اختر مشرفًا مسجلًا أو أدخل بيانات مشرف جديد.</p><div class="choice-row"><label class="choice-card"><input type="radio" name="supervisor-type" value="existing" ${state.supervisorType === 'existing' ? 'checked' : ''} /><span><span class="choice-title">حساب مشرف موجود</span></span></label><label class="choice-card"><input type="radio" name="supervisor-type" value="new" ${state.supervisorType === 'new' ? 'checked' : ''} /><span><span class="choice-title">إضافة مشرف جديد</span></span></label></div>${state.supervisorType === 'existing' ? `<div class="form-grid"><div class="field full"><label for="supervisor-existing">اختر المشرف *</label><select id="supervisor-existing">${state.supervisors.map(supervisor => `<option value="${esc(supervisor.id)}" ${state.selectedSupervisor === supervisor.id ? 'selected' : ''}>${esc(supervisor.full_name)}${supervisor.department ? ` — ${esc(supervisor.department)}` : ''}</option>`).join('')}</select>${!state.supervisors.length ? '<span class="help">لا يوجد مشرفون نشطون متاحون لهذا القسم.</span>' : ''}</div></div>` : `<div class="form-grid"><div class="field"><label for="supervisor-name">اسم المشرف *</label><input id="supervisor-name" value="${esc(state.supervisor.name)}" /></div><div class="field"><label for="supervisor-username">اسم المستخدم *</label><input id="supervisor-username" value="${esc(state.supervisor.username)}" /></div><div class="field"><label for="supervisor-phone">رقم الجوال *</label><input id="supervisor-phone" value="${esc(state.supervisor.phone)}" /></div><div class="field"><label for="supervisor-email">البريد الإلكتروني</label><input id="supervisor-email" type="email" value="${esc(state.supervisor.email)}" /></div><div class="field full"><label for="supervisor-specialty">التخصص</label><input id="supervisor-specialty" value="${esc(state.supervisor.specialty)}" /></div></div>`}`;
  return `<h2>مراجعة الطلب</h2><p class="lead">راجع المعلومات قبل حفظ الطلب وإرساله لرئيس القسم.</p><div class="review-section"><div class="review-grid"><div class="review-item"><span>رمز المجموعة</span><strong>${esc(state.project.group)}</strong></div><div class="review-item"><span>العام الدراسي</span><strong>${esc(state.project.year)}</strong></div><div class="review-item"><span>عنوان المشروع</span><strong>${esc(state.project.title)}</strong></div><div class="review-item"><span>القسم</span><strong>${esc(state.departments.find(item => item.id === state.project.departmentId)?.name || '')}</strong></div><div class="review-item full"><span>الوصف</span><strong>${esc(state.project.desc)}</strong></div></div></div><div class="review-section"><strong>الأعضاء (${state.students.length})</strong>${state.students.map(student => `<div class="review-member">${esc(student.name)} · ${esc(student.username)} · ${esc(student.phone)}</div>`).join('')}</div><div class="review-section"><strong>المشرف الأكاديمي</strong><div class="review-member">${state.supervisorType === 'existing' ? esc(state.supervisors.find(item => item.id === state.selectedSupervisor)?.full_name || '') : esc(state.supervisor.name)}</div></div><div class="notice warn">سيُحفظ الطلب كمسودة على الخادم ثم يرسل لرئيس القسم عند التأكيد.</div>`;
};

function localDateTimeInput(value) {
  if (!value) return '';
  const date = new Date(value);
  const pad = part => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function calendarContent() {
  const canManage = ['dean', 'chair'].includes(state.role);
  const editing = state.appointments.find(item => item.id === state.editingAppointmentId);
  const projectOptions = state.projects.map(project => `<option value="${esc(project.id)}" ${editing?.project === project.id ? 'selected' : ''}>${esc(project.title)} · ${esc(project.group.group_code)}</option>`).join('');
  const departmentOptions = state.departments.map(department => `<option value="${esc(department.id)}" ${editing?.department?.id === department.id ? 'selected' : ''}>${esc(department.name)}</option>`).join('');
  const form = canManage ? `<form id="appointment-form" class="form-grid" style="margin-bottom:20px"><div class="field"><label for="appointment-title">عنوان الموعد *</label><input id="appointment-title" maxlength="180" value="${esc(editing?.title || '')}" required placeholder="مثال: تسليم خطة المشروع" /></div><div class="field"><label for="appointment-start">التاريخ والوقت *</label><input id="appointment-start" type="datetime-local" value="${esc(localDateTimeInput(editing?.starts_at))}" required /></div>${state.role === 'dean' ? `<div class="field"><label for="appointment-department">القسم *</label><select id="appointment-department" ${editing?.project ? 'disabled' : ''} required><option value="">اختر القسم</option>${departmentOptions}</select></div>` : ''}<div class="field"><label for="appointment-project">مشروع محدد (اختياري)</label><select id="appointment-project"><option value="">موعد عام للقسم</option>${projectOptions}</select></div><div class="field full"><label for="appointment-description">التفاصيل</label><textarea id="appointment-description" maxlength="2000">${esc(editing?.description || '')}</textarea></div><div class="field full" style="display:flex;gap:8px;align-items:center"><button class="btn btn-teal" type="submit">${editing ? 'حفظ التعديلات' : 'إضافة الموعد'}</button>${editing ? '<button class="btn btn-outline" type="button" data-action="cancel-appointment-edit">إلغاء التعديل</button>' : ''}</div></form>` : '';
  const items = state.appointments.length ? `<div class="request-list">${state.appointments.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.department?.name || '')}${item.project_title ? ` · ${esc(item.project_title)}` : ' · موعد للقسم'}</div>${item.description ? `<div class="request-meta">${esc(item.description)}</div>` : ''}</div><div>${esc(new Date(item.starts_at).toLocaleString('ar-SA', { dateStyle: 'medium', timeStyle: 'short' }))}</div>${canManage ? `<div class="action-group"><button class="btn btn-outline btn-sm" data-action="edit-appointment" data-appointment-id="${esc(item.id)}">تعديل</button><button class="btn btn-danger btn-sm" data-action="delete-appointment" data-appointment-id="${esc(item.id)}">حذف</button></div>` : ''}</div>`).join('')}</div>` : '<div class="empty-state">لا توجد مواعيد قادمة. ستظهر هنا مراحل المشروع والاجتماعات التي يحددها القسم.</div>';
  return `${form}${items}`;
}

function reportsContent() {
  const reportTypes = [['projects', 'المشاريع'], ['groups', 'المجموعات'], ['supervisors', 'المشرفون'], ['progress', 'تقدم المراحل'], ['defenses', 'المناقشات']];
  if (state.role === 'dean') reportTypes.push(['audit', 'سجل العمليات']);
  const departments = state.role === 'dean' ? `<div class="field"><label for="report-department">القسم</label><select id="report-department"><option value="">كل الأقسام المسموح بها</option>${state.departments.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('')}</select></div>` : '';
  const scope = state.role === 'dean' ? 'بيانات الكلية؛ اختر قسمًا اختياريًا.' : state.role === 'chair' ? `بيانات قسم ${esc(state.apiUser?.department?.name || '')}.` : state.role === 'supervisor' ? 'المشاريع المسندة إليك فقط.' : 'بيانات مشروع مجموعتك فقط.';
  return `<section class="panel"><h2 class="panel-title">إنشاء تقرير</h2><p class="panel-sub">${scope} تستخدم صلاحيات الخادم لتحديد البيانات الظاهرة في الملف.</p><div class="form-grid"><div class="field"><label for="report-type">نوع التقرير</label><select id="report-type">${reportTypes.map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></div>${departments}<div class="field"><label for="report-date-from">من تاريخ</label><input id="report-date-from" type="date" /></div><div class="field"><label for="report-date-to">إلى تاريخ</label><input id="report-date-to" type="date" /></div><div class="field full action-group"><button class="btn btn-teal" type="button" data-action="export-report" data-format="xlsx">تنزيل ملف Excel</button><button class="btn btn-outline" type="button" data-action="export-report" data-format="print">طباعة / حفظ PDF</button></div></div><p class="help">يتضمن التصدير تاريخ الإنشاء والجهة. نسخة الطباعة تفتح صفحة قابلة للحفظ بصيغة PDF من نافذة الطباعة.</p></section>`;
}

genericPage = function connectedGenericPage() {
  const titles = { drafts: 'المسودات المحفوظة', projects: 'المشاريع المسندة إليك', deliverables: 'التقارير والتسليمات', notes: 'الملاحظات', project: 'تفاصيل مشروعي', calendar: 'المواعيد القادمة', groups: 'المجموعات', users: 'المستخدمون', committees: 'لجان مشاريع التخرج', reports: 'التقارير والتصدير', audit: 'سجل العمليات' };
  let content = '<div class="empty-state">لا توجد بيانات متاحة لهذا الحساب.</div>';
  if (state.page === 'reports') content = reportsContent();
  if (state.page === 'drafts') {
    const drafts = serverRequests.filter(item => ['draft', 'returned'].includes(item.status));
    content = drafts.length ? `<div class="request-list">${drafts.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)}</div><div class="request-meta">${esc(item.code)} · ${esc(item.department)} · ${item.members} طلاب</div></div>${statusPill(item.status)}<button class="btn btn-outline btn-sm" data-action="resume-draft" data-request-id="${esc(item.id)}">استكمال الطلب</button></div>`).join('')}</div>` : '<div class="empty-state">لا توجد مسودات أو طلبات معادة للتعديل. يمكنك إنشاء طلب جديد والاحتفاظ به كمسودة من خطوة المراجعة.</div>';
  }
  if (state.page === 'groups' && state.groups.length) content = `<div class="request-list">${state.groups.map(group => `<div class="request-row"><div><div class="request-name">${esc(group.project_title || 'مجموعة مشاريع')}</div><div class="request-meta">${esc(group.group_code)} · ${esc(group.department.name)}</div></div><div>${group.members.filter(member => !member.left_at).length} طلاب نشطون</div><span class="status active">${esc(group.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project" data-project-id="${esc(group.project_id)}">فتح مساحة المشروع</button></div>`).join('')}</div>`;
  if (['projects', 'project'].includes(state.page) && state.projects.length) content = `<div class="request-list">${state.projects.map(project => `<div class="request-row"><div><div class="request-name">${esc(project.title)}</div><div class="request-meta">${esc(project.group.group_code)} · ${esc(project.group.department.name)}</div></div><div>${esc(project.group.academic_year)}</div><span class="status active">${esc(project.status)}</span><button class="btn btn-outline btn-sm" data-action="open-project" data-project-id="${esc(project.id)}">فتح مساحة المشروع</button></div>`).join('')}</div>`;
  if (state.page === 'audit' && state.auditEvents.length) content = `<div class="request-list">${state.auditEvents.map(event => `<div class="request-row"><div><div class="request-name">${esc(event.action)}</div><div class="request-meta">${esc(event.actor || 'النظام')} · ${esc(event.entity_type)}</div></div><div>${esc(safeDate(event.occurred_at))}</div></div>`).join('')}</div>`;
  if (state.page === 'notifications') content = state.notifications.length ? `<div class="request-list">${state.notifications.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.title)} ${item.read_at ? '' : '<span class="status pending">جديد</span>'}</div><div class="request-meta">${esc(item.body || '')} · ${esc(item.actor_name || 'النظام')} · ${esc(safeDate(item.created_at))}</div></div><button class="btn btn-outline btn-sm" data-action="open-notification" data-notification-id="${esc(item.id)}">${item.target_url ? 'فتح' : 'وضع كمقروء'}</button></div>`).join('')}</div>` : '<div class="empty-state">لا توجد إشعارات محفوظة.</div>';
  if (state.page === 'project' && state.projectDetail) {
    const project = state.projectDetail;
    const repoEditor = state.role === 'student' ? `<form id="project-repository-form" class="field" style="margin:18px 0"><label for="project-repository-url">مستودع GitHub للفريق</label><input id="project-repository-url" type="url" value="${esc(project.repository_url || '')}" placeholder="https://github.com/owner/repository" /><span class="help">ضع رابط مستودع الفريق. اجعل المستودع خاصًا عند احتواء الشفرة على بيانات أو أسرار.</span><button class="btn btn-teal" type="submit" style="margin-top:10px">حفظ رابط المستودع</button></form>` : project.repository_url ? `<div class="review-item full"><span>مستودع GitHub</span><a href="${esc(project.repository_url)}" target="_blank" rel="noopener noreferrer">فتح المستودع ↗</a></div>` : '<div class="review-item full"><span>مستودع GitHub</span><strong>لم يضف الفريق رابطًا بعد.</strong></div>';
    const repoLink = state.role === 'student' && project.repository_url ? `<p><a href="${esc(project.repository_url)}" target="_blank" rel="noopener noreferrer">فتح مستودع الفريق ↗</a></p>` : '';
    const statusLabels = { not_started: 'لم تبدأ', in_progress: 'قيد التنفيذ', submitted: 'بانتظار المراجعة', changes_requested: 'تحتاج تعديلات', approved: 'معتمدة' };
    const memberIsLeader = project.group.members?.some(member => !member.left_at && member.username === state.apiUser?.username && member.is_leader);
    const activeMembers = (project.group.members || []).filter(member => !member.left_at);
    const teamPresenceSection = `<section class="panel" style="margin-top:16px"><h2 class="panel-title">أعضاء الفريق وحالة الاتصال</h2><p class="panel-sub">مؤشر تقني فقط، لا يدل على العمل ولا يستخدم أساسًا للتقييم. يعتبر العضو نشط الاتصال إذا استخدم النظام خلال آخر 5 دقائق؛ تُحدث القائمة تلقائيًا كل دقيقة.</p><div class="request-list" id="team-presence-list">${renderTeamPresence(activeMembers)}</div></section>`;
    const membershipData = state.groupMemberships;
    const membershipSection = state.role === 'chair' && membershipData ? `<section class="panel" style="margin-top:16px"><h2 class="panel-title">أعضاء المجموعة وسجل العضوية</h2><div class="request-list">${membershipData.members.map(member => {
      const active = !member.left_at;
      const newLeaders = membershipData.members.filter(entry => !entry.left_at && entry.student_id !== member.student_id);
      return `<article class="request-row"><div><div class="request-name">${esc(member.full_name)} · ${esc(member.username)}</div><div class="request-meta">${active ? member.is_leader ? 'قائد المجموعة · نشط' : 'عضو نشط' : `انتهت العضوية في ${esc(safeDate(member.left_at))}${member.left_reason ? ` · السبب: ${esc(member.left_reason)}` : ''}`}</div></div>${active ? `<div class="action-group">${!member.is_leader ? `<button class="btn btn-outline btn-sm" data-action="promote-group-leader" data-student-id="${esc(member.student_id)}">تعيين قائدًا</button>` : ''}<select aria-label="القائد البديل" data-replacement-leader="${esc(member.student_id)}"><option value="">اختر قائدًا بديلًا</option>${newLeaders.map(entry => `<option value="${esc(entry.student_id)}">${esc(entry.full_name)}</option>`).join('')}</select><button class="btn btn-danger btn-sm" data-action="remove-group-member" data-group-id="${esc(project.group.id)}" data-student-id="${esc(member.student_id)}" data-is-leader="${member.is_leader}">إنهاء العضوية</button></div>` : ''}</article>`;
    }).join('')}</div><form id="group-member-add-form" class="form-grid"><div class="field"><label>إضافة طالب نشط غير مرتبط بمجموعة</label><select name="student_id" required><option value="">اختر الطالب</option>${membershipData.eligible_students.map(student => `<option value="${esc(student.id)}">${esc(student.name)} · ${esc(student.username)}</option>`).join('')}</select></div><div class="field"><button class="btn btn-teal" type="submit" ${membershipData.eligible_students.length ? '' : 'disabled'}>إضافة للمجموعة</button></div></form></section>` : '';
    const supervisorAssignments = project.group.supervisors || [];
    const currentAssignment = supervisorAssignments.find(assignment => !assignment.ended_at);
    const supervisorSection = state.role === 'chair' ? `<section class="panel" style="margin-top:16px"><h2 class="panel-title">الإشراف الأكاديمي وسجل التكليف</h2><div class="request-list">${supervisorAssignments.map(assignment => `<div class="request-row"><div><strong>${esc(assignment.full_name)}</strong><div class="request-meta">بدأ ${esc(safeDate(assignment.started_at))}${assignment.ended_at ? ` · انتهى ${esc(safeDate(assignment.ended_at))} · ${esc(assignment.end_type === 'declined' ? 'اعتذار' : 'إعادة إسناد')}: ${esc(assignment.end_reason || '')}` : ' · مسند حاليًا'}</div></div></div>`).join('') || '<div class="empty-state">لا يوجد مشرف مسند حاليًا.</div>'}</div><form id="supervisor-assignment-form" class="form-grid"><div class="field"><label>المشرف الجديد *</label><select name="supervisor_id" required><option value="">اختر مشرفًا</option>${state.supervisors.map(user => `<option value="${esc(user.id)}" ${user.id === currentAssignment?.supervisor_id ? 'disabled' : ''}>${esc(user.full_name)} · ${esc(user.username)}</option>`).join('')}</select></div>${currentAssignment ? '<div class="field"><label>سبب إعادة الإسناد *</label><input name="reason" maxlength="2000" required /></div>' : ''}<div class="field"><button class="btn btn-teal" type="submit">${currentAssignment ? 'إعادة إسناد المشروع' : 'إسناد مشرف'}</button></div></form></section>` : state.role === 'supervisor' && currentAssignment?.supervisor_id === state.apiUser?.id ? `<section class="panel" style="margin-top:16px"><h2 class="panel-title">الإشراف الأكاديمي</h2><p class="panel-sub">يمكنك الاعتذار عن هذا التكليف مع توضيح السبب؛ سيُخطر رئيس القسم لإعادة إسناد المشروع.</p><button class="btn btn-outline" data-action="decline-project-supervision" data-project-id="${esc(project.id)}">اعتذار عن الإشراف</button></section>` : '';
    const ideaStatusLabels = { supervisor_review: 'مراجعة المشرف', committee_review: 'مراجعة اللجنة', chair_review: 'قرار رئيس القسم', changes_requested: 'تحتاج تعديلات', approved: 'معتمدة', rejected: 'مرفوضة' };
    const latestIdea = state.projectIdeas[0];
    const isCommitteeMember = state.projectCommittee?.member_ids?.some(id => String(id) === String(state.apiUser?.id));
    const ideaHistory = state.projectIdeas.map(idea => `<article class="review-member"><strong>الفكرة · النسخة ${idea.version}</strong><span class="status ${idea.status === 'approved' ? 'active' : ['supervisor_review','committee_review','chair_review'].includes(idea.status) ? 'pending' : 'returned'}">${esc(ideaStatusLabels[idea.status] || idea.status)}</span><h3>${esc(idea.title)}</h3><p><b>المشكلة:</b> ${esc(idea.problem)}</p><p><b>الأهداف:</b> ${esc(idea.objectives)}</p><p><b>الحل المقترح:</b> ${esc(idea.proposed_solution)}</p><p><b>وجه الجدة:</b> ${esc(idea.novelty)}</p>${idea.supervisor_note ? `<p><b>ملاحظة المشرف:</b> ${esc(idea.supervisor_note)}</p>` : ''}${idea.committee_reviews?.length ? `<div class="request-list">${idea.committee_reviews.map(review => `<div class="request-meta">توصية ${esc(review.reviewer_name)}: ${esc({ recommend: 'يوصي بالاعتماد', changes: 'يوصي بالتعديل', not_suitable: 'لا يوصي بالاعتماد' }[review.recommendation] || review.recommendation)}${review.note ? ` — ${esc(review.note)}` : ''}</div>`).join('')}</div>` : ''}${idea.chair_note ? `<p><b>قرار رئيس القسم:</b> ${esc(idea.chair_note)}</p>` : ''}${state.role === 'supervisor' && idea.status === 'supervisor_review' ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="idea-supervisor-review" data-idea-id="${esc(idea.id)}" data-decision="forward">إحالة إلى اللجنة</button><button class="btn btn-danger btn-sm" data-action="idea-supervisor-review" data-idea-id="${esc(idea.id)}" data-decision="changes_requested">إعادة للفريق</button></div>` : ''}${state.role === 'supervisor' && isCommitteeMember && idea.status === 'committee_review' ? `<form class="idea-committee-review-form" data-idea-id="${esc(idea.id)}"><label>توصية اللجنة</label><select name="recommendation"><option value="recommend">يوصي بالاعتماد</option><option value="changes">يوصي بالتعديل</option><option value="not_suitable">لا يوصي بالاعتماد</option></select><textarea name="note" maxlength="3000" placeholder="ملاحظات، وإلزامية عند طلب التعديل أو عدم التوصية"></textarea><button class="btn btn-outline btn-sm" type="submit">حفظ التوصية</button></form>` : ''}${state.role === 'chair' && idea.status === 'chair_review' ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="idea-chair-review" data-idea-id="${esc(idea.id)}" data-decision="approved">اعتماد الفكرة</button><button class="btn btn-outline btn-sm" data-action="idea-chair-review" data-idea-id="${esc(idea.id)}" data-decision="changes_requested">إعادة للفريق</button><button class="btn btn-danger btn-sm" data-action="idea-chair-review" data-idea-id="${esc(idea.id)}" data-decision="rejected">رفض</button></div>` : ''}</article>`).join('');
    const ideaForm = state.role === 'student' && memberIsLeader && !['supervisor_review','committee_review','chair_review','approved'].includes(latestIdea?.status) ? `<form id="project-idea-form" class="form-grid"><p class="field full">تقدم فكرة المشروع للمشرف ثم اللجنة، ويصدر رئيس القسم القرار النهائي.</p><div class="field full"><label>عنوان الفكرة *</label><input name="title" maxlength="240" required value="${esc(latestIdea?.title || project.title)}"/></div><div class="field full"><label>المشكلة التي يعالجها المشروع *</label><textarea name="problem" maxlength="5000" required>${esc(latestIdea?.problem || project.description)}</textarea></div><div class="field full"><label>أهداف المشروع *</label><textarea name="objectives" maxlength="5000" required>${esc(latestIdea?.objectives || '')}</textarea></div><div class="field full"><label>الحل المقترح *</label><textarea name="proposed_solution" maxlength="5000" required>${esc(latestIdea?.proposed_solution || '')}</textarea></div><div class="field full"><label>وجه الجدة والاختلاف *</label><textarea name="novelty" maxlength="5000" required>${esc(latestIdea?.novelty || '')}</textarea></div><div id="idea-similarity-results" class="field full" aria-live="polite"></div><div class="field full action-group"><button class="btn btn-outline" type="button" data-action="check-idea-similarity">مقارنة مع الأفكار المعتمدة</button><button class="btn btn-teal" type="submit">إرسال الفكرة للمشرف</button></div></form>` : '';
    const ideaSection = `<section class="panel" style="margin-top:16px"><h2 class="panel-title">فكرة المشروع ومراجعتها</h2><p class="panel-sub">يتطلب إرسال الفكرة لجنة معتمدة للقسم. اعتماد رئيس القسم شرط لتقديم الخطة وبدء التنفيذ.</p>${ideaHistory || '<div class="empty-state">لم تقدم فكرة مفصلة بعد.</div>'}${ideaForm}</section>`;
    const readinessLabels = { supervisor_review: 'مراجعة المشرف', changes_requested: 'تحتاج تعديلات', chair_review: 'مراجعة رئيس القسم', referred: 'محال لتشكيل لجنة المناقشة', rejected: 'مرفوض' };
    const latestReadiness = state.readinessRequests[0];
    const readinessHistory = state.readinessRequests.map(item => `<article class="review-member"><strong>طلب الجاهزية · النسخة ${item.version}</strong><span class="status ${item.status === 'referred' ? 'active' : ['supervisor_review','chair_review'].includes(item.status) ? 'pending' : 'returned'}">${esc(readinessLabels[item.status] || item.status)}</span><p>النسخة النهائية: ${esc(item.final_filename)} · التقرير: ${esc(item.report_filename)}</p>${item.supervisor_note ? `<p><b>ملاحظة المشرف:</b> ${esc(item.supervisor_note)}</p>` : ''}${item.chair_note ? `<p><b>ملاحظة رئيس القسم:</b> ${esc(item.chair_note)}</p>` : ''}${state.role === 'supervisor' && item.status === 'supervisor_review' ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="review-readiness" data-request-id="${esc(item.id)}" data-stage="supervisor-review" data-decision="approved">موافقة المشرف</button><button class="btn btn-danger btn-sm" data-action="review-readiness" data-request-id="${esc(item.id)}" data-stage="supervisor-review" data-decision="changes_requested">إعادة للتعديل</button></div>` : ''}${state.role === 'chair' && item.status === 'chair_review' ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="review-readiness" data-request-id="${esc(item.id)}" data-stage="chair-review" data-decision="refer">إحالة لتشكيل اللجنة</button><button class="btn btn-outline btn-sm" data-action="review-readiness" data-request-id="${esc(item.id)}" data-stage="chair-review" data-decision="changes_requested">إعادة للفريق</button><button class="btn btn-danger btn-sm" data-action="review-readiness" data-request-id="${esc(item.id)}" data-stage="chair-review" data-decision="rejected">رفض</button></div>` : ''}</article>`).join('');
    const deliverableOptions = state.projectDeliverables.map(file => `<option value="${esc(file.id)}">${esc(file.original_filename)} · ${esc(safeDate(file.created_at))}</option>`).join('');
    const readinessForm = state.role === 'student' && memberIsLeader && !['supervisor_review','chair_review','referred'].includes(latestReadiness?.status) ? `<form id="discussion-readiness-form" class="form-grid"><p class="field full">إرفق الملفين أولًا من صفحة التسليمات. لا يقبل الطلب قبل اعتماد جميع المراحل الإلزامية.</p><div class="field"><label>النسخة النهائية *</label><select name="final_deliverable" required><option value="">اختر ملفًا</option>${deliverableOptions}</select></div><div class="field"><label>التقرير النهائي *</label><select name="report_deliverable" required><option value="">اختر ملفًا</option>${deliverableOptions}</select></div><div class="field full"><button class="btn btn-teal" type="submit">طلب جاهزية المناقشة</button></div></form>` : '';
    const readinessSection = `<section class="panel" style="margin-top:16px"><h2 class="panel-title">جاهزية المناقشة</h2><p class="panel-sub">يقدم القائد النسخة النهائية والتقرير؛ يعتمد المشرف الجاهزية ثم يحيل رئيس القسم الطلب لتشكيل لجنة المناقشة.</p>${readinessHistory || '<div class="empty-state">لم يقدم طلب جاهزية للمناقشة.</div>'}${readinessForm}</section>`;
    const planStatusLabels = { submitted: 'بانتظار مراجعة المشرف', changes_requested: 'تحتاج تعديلات', approved: 'معتمدة' };
    const latestPlan = state.projectPlans[0];
    const planHistory = state.projectPlans.map(plan => `<article class="review-member"><strong>الخطة · النسخة ${plan.version}</strong><span class="status ${plan.status === 'approved' ? 'active' : plan.status === 'submitted' ? 'pending' : 'returned'}">${esc(planStatusLabels[plan.status] || plan.status)}</span><p><b>${esc(plan.title)}</b></p><p><b>الأهداف:</b> ${esc(plan.objectives)}</p><p><b>النطاق:</b> ${esc(plan.scope)}</p><p><b>المنهجية:</b> ${esc(plan.methodology)}</p><p><b>الأدوات:</b> ${esc(plan.tools)}</p><p><b>توزيع المهام:</b> ${esc(plan.task_assignments)}</p><p><b>الجدول الزمني:</b> ${esc(plan.timeline)}</p><p><b>المخاطر:</b> ${esc(plan.risks)}</p><p><b>المخرجات المتوقعة:</b> ${esc(plan.expected_outputs)}</p>${plan.review_note ? `<p><b>ملاحظة المشرف:</b> ${esc(plan.review_note)}</p>` : ''}${state.role === 'supervisor' && plan.status === 'submitted' && plan.id === latestPlan?.id ? `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="review-project-plan" data-plan-id="${esc(plan.id)}" data-decision="approved">اعتماد الخطة</button><button class="btn btn-danger btn-sm" data-action="review-project-plan" data-plan-id="${esc(plan.id)}" data-decision="changes_requested">طلب تعديلات</button></div>` : ''}</article>`).join('');
    const planForm = state.role === 'student' && memberIsLeader && latestPlan?.status !== 'submitted' ? `<form id="project-plan-form" class="form-grid"><p class="field full">تقديم خطة جديدة أو نسخة معدلة. لا يبدأ تنفيذ المراحل قبل اعتماد أحدث نسخة من المشرف.</p><div class="field full"><label>عنوان الخطة *</label><input name="title" maxlength="240" required value="${esc(latestPlan?.title || project.title)}"/></div><div class="field full"><label>الأهداف *</label><textarea name="objectives" maxlength="5000" required>${esc(latestPlan?.objectives || '')}</textarea></div><div class="field full"><label>النطاق والحدود *</label><textarea name="scope" maxlength="5000" required>${esc(latestPlan?.scope || '')}</textarea></div><div class="field full"><label>المنهجية *</label><textarea name="methodology" maxlength="5000" required>${esc(latestPlan?.methodology || '')}</textarea></div><div class="field full"><label>الأدوات والتقنيات *</label><textarea name="tools" maxlength="3000" required>${esc(latestPlan?.tools || '')}</textarea></div><div class="field full"><label>توزيع المهام بين الطلاب *</label><textarea name="task_assignments" maxlength="5000" required>${esc(latestPlan?.task_assignments || '')}</textarea></div><div class="field full"><label>الجدول الزمني والمراحل *</label><textarea name="timeline" maxlength="5000" required>${esc(latestPlan?.timeline || '')}</textarea></div><div class="field full"><label>المخاطر وخطة التعامل معها *</label><textarea name="risks" maxlength="5000" required>${esc(latestPlan?.risks || '')}</textarea></div><div class="field full"><label>المخرجات المتوقعة *</label><textarea name="expected_outputs" maxlength="5000" required>${esc(latestPlan?.expected_outputs || '')}</textarea></div><div class="field full"><button class="btn btn-teal" type="submit">إرسال الخطة للمشرف</button></div></form>` : '';
    const planSection = `${ideaSection}<section class="panel" style="margin-top:16px"><h2 class="panel-title">خطة المشروع</h2><p class="panel-sub">توثق الأهداف والنطاق والمنهجية والأدوات والجدول الزمني، ويعتمدها المشرف قبل بدء المراحل.</p>${planHistory || '<div class="empty-state">لم تقدم خطة للمشروع بعد.</div>'}${planForm}</section>${readinessSection}`;
    const stages = state.projectStages.map(stage => {
      const files = (stage.deliverables || []).map(file => `<div class="request-meta">📎 ${esc(file.original_filename)} · ${esc(safeDate(file.created_at))}</div>`).join('');
      const reviews = (stage.reviews || []).map(review => `<div class="request-meta">${esc(review.actor_name)} · ${esc(statusLabels[review.action] || review.action)} · ${esc(safeDate(review.created_at))}${review.note ? ` — ${esc(review.note)}` : ''}</div>`).join('');
      const stageTasks = state.projectTasks.filter(task => task.stage === stage.id);
      const taskRows = stageTasks.map(task => `<div class="request-row"><div><strong>${esc(task.title)}</strong><div class="request-meta">${esc(task.assigned_to_name || 'غير مسندة')} · ${task.due_at ? esc(safeDate(task.due_at)) : 'بلا موعد'}</div>${task.description ? `<div class="request-meta">${esc(task.description)}</div>` : ''}</div><select data-task-status="${esc(task.id)}"><option value="todo" ${task.status === 'todo' ? 'selected' : ''}>لم تبدأ</option><option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>قيد التنفيذ</option><option value="completed" ${task.status === 'completed' ? 'selected' : ''}>مكتملة</option></select><button class="btn btn-outline btn-sm" data-action="save-task-status" data-task-id="${esc(task.id)}">حفظ الحالة</button></div>`).join('');
      let actions = '';
      if (state.role === 'supervisor' && !['submitted', 'approved'].includes(stage.status)) actions += `<form class="stage-edit-form" data-stage-id="${esc(stage.id)}"><input name="title" maxlength="180" required value="${esc(stage.title)}" aria-label="اسم المرحلة"/><textarea name="description" maxlength="2000" aria-label="وصف المرحلة">${esc(stage.description || '')}</textarea><label>تبدأ <input type="date" name="starts_at" value="${esc(stage.starts_at || '')}"/></label><label>موعد التسليم <input type="date" name="due_at" value="${esc(stage.due_at || '')}"/></label><button class="btn btn-outline btn-sm" type="submit">حفظ خطة المرحلة</button></form>`;
      if (state.role === 'supervisor' && !stage.is_required && !stage.reviews?.length && !stageTasks.length && !stage.deliverables?.length && !['submitted', 'approved'].includes(stage.status)) actions += `<button class="btn btn-danger btn-sm" data-action="delete-stage" data-stage-id="${esc(stage.id)}">حذف المرحلة</button>`;
      if (state.role === 'student' && ['not_started', 'changes_requested'].includes(stage.status)) actions += `<button class="btn btn-outline btn-sm" data-action="start-stage" data-stage-id="${esc(stage.id)}">بدء المرحلة</button>`;
      if (state.role === 'student' && stage.status === 'in_progress') actions += `<form class="stage-progress-form" data-stage-id="${esc(stage.id)}"><label>التقدم: ${stage.progress}%</label><input type="range" min="0" max="99" value="${stage.progress}" name="progress"/><button class="btn btn-outline btn-sm" type="submit">حفظ التقدم</button>${memberIsLeader ? `<button class="btn btn-teal btn-sm" type="button" data-action="submit-stage" data-stage-id="${esc(stage.id)}">إرسال للمراجعة</button>` : ''}</form>`;
      if (state.role === 'supervisor' && stage.status === 'submitted') actions += `<div class="action-group"><button class="btn btn-teal btn-sm" data-action="review-stage" data-decision="approved" data-stage-id="${esc(stage.id)}">اعتماد</button><button class="btn btn-danger btn-sm" data-action="review-stage" data-decision="changes_requested" data-stage-id="${esc(stage.id)}">طلب تعديلات</button></div>`;
      return `<article class="panel" style="margin-top:12px"><div class="panel-head"><div><strong>${stage.order}. ${esc(stage.title)}</strong><div class="panel-sub">${esc(statusLabels[stage.status] || stage.status)} · ${stage.progress}%${stage.due_at ? ` · الموعد ${esc(safeDate(stage.due_at))}` : ''}</div></div></div>${stage.description ? `<p>${esc(stage.description)}</p>` : ''}${taskRows ? `<div class="request-list">${taskRows}</div>` : ''}<progress max="100" value="${stage.progress}" style="width:100%"></progress>${files}${reviews}${actions}</article>`;
    }).join('');
    content = `<div class="review-grid"><div class="review-item"><span>عنوان المشروع</span><strong>${esc(project.title)}</strong></div><div class="review-item"><span>رمز المجموعة</span><strong>${esc(project.group.group_code)}</strong></div><div class="review-item"><span>القسم</span><strong>${esc(project.group.department.name)}</strong></div><div class="review-item"><span>العام الدراسي</span><strong>${esc(project.group.academic_year)}</strong></div><div class="review-item full"><span>الوصف</span><strong>${esc(project.description)}</strong></div>${repoEditor}</div>${repoLink}<div style="display:flex;gap:8px;margin:16px 0"><button class="btn btn-teal" data-action="open-project-notes" data-project-id="${esc(project.id)}">ملاحظات المشروع</button><button class="btn btn-outline" data-page="deliverables">ملفات وتسليمات المشروع</button></div>${teamPresenceSection}${membershipSection}${supervisorSection}${planSection}<section class="panel" style="margin-top:16px"><h2 class="panel-title">مراحل المشروع والمهام</h2><p class="panel-sub">ارفع الدليل من صفحة الملفات واربطه بالمرحلة قبل إرسالها للمراجعة.</p>${state.role === 'supervisor' ? `<form id="project-stage-form" class="form-grid"><div class="field"><label>إضافة مرحلة مخصصة</label><input name="title" maxlength="180" required placeholder="مرحلة إضافية"/></div><div class="field"><label>الوصف</label><input name="description" maxlength="2000"/></div><button class="btn btn-outline" type="submit">إضافة مرحلة</button></form><form id="project-task-form" class="form-grid"><div class="field"><label>المرحلة</label><select name="stage_id" required>${state.projectStages.map(stage => `<option value="${esc(stage.id)}">${stage.order}. ${esc(stage.title)}</option>`).join('')}</select></div><div class="field"><label>اسم المهمة</label><input name="title" maxlength="180" required/></div><div class="field"><label>الطالب المكلف</label><select name="assigned_to"><option value="">غير مسندة</option>${project.group.members.filter(member => !member.left_at).map(member => `<option value="${esc(member.student_id)}">${esc(member.full_name)} · ${esc(member.username)}</option>`).join('')}</select></div><div class="field"><label>موعد التسليم</label><input name="due_at" type="date"/></div><div class="field full"><label>التفاصيل</label><textarea name="description" maxlength="2000"></textarea><button class="btn btn-teal" type="submit">إضافة مهمة</button></div></form>` : ''}${stages || '<div class="empty-state">لم تُنشأ مراحل لهذا المشروع.</div>'}</section>${renderPostDefense()}`;
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
      const items = state.deliverables.length ? `<div class="request-list">${state.deliverables.map(item => `<div class="request-row"><div><div class="request-name">${esc(item.original_filename)}</div><div class="request-meta">${esc(item.uploaded_by_name)} · ${item.visibility === 'personal' ? 'ملف شخصي' : 'ملف مشترك'} · ${esc(safeDate(item.created_at))} · ${Math.ceil(item.size_bytes / 1024)} كيلوبايت</div></div><a class="btn btn-outline btn-sm" href="${API_BASE}/deliverables/${encodeURIComponent(item.id)}/download/" data-download-id="${esc(item.id)}">تنزيل الملف</a></div>`).join('')}</div>` : '<div class="empty-state">لا توجد ملفات مرفوعة لهذا المشروع.</div>';
      const stageOptions = state.projectStages.map(stage => `<option value="${esc(stage.id)}">${stage.order}. ${esc(stage.title)}</option>`).join('');
      const upload = state.role === 'student' ? `<form id="deliverable-upload-form" class="field" style="margin:16px 0" enctype="multipart/form-data"><label for="deliverable-file">إرفاق ملف للمشروع</label><input id="deliverable-file" name="file" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.png,.jpg,.jpeg,.gif,.zip,.py,.js,.ts,.html,.css,.json,.md" required /><label for="deliverable-stage">المرحلة المرتبطة (اختياري)</label><select id="deliverable-stage"><option value="">ملف عام للمشروع</option>${stageOptions}</select><label for="deliverable-visibility">من يمكنه رؤية الملف؟</label><select id="deliverable-visibility"><option value="shared">مشترك مع أعضاء الفريق والمشرف</option><option value="personal">شخصي: أنا والمشرف وإدارة القسم/الكلية</option></select><span class="help">الحد الأقصى 10 ميغابايت. تبقى ملفات التسليم المحددة للمناقشة متاحة للجنة حسب صلاحياتها.</span><button class="btn btn-teal" type="submit" style="margin-top:10px">رفع الملف</button></form>` : '';
      content = `<div class="panel-head"><div><strong>${esc(project?.title || 'ملفات المشروع')}</strong><div class="panel-sub">${esc(project?.group?.group_code || '')}</div></div><button class="btn btn-outline btn-sm" data-action="refresh-data">تحديث</button></div>${upload}${items}`;
    }
  }
  if (state.page === 'calendar') content = calendarContent();
  if (state.page === 'users') {
    const search = state.userSearch.trim().toLocaleLowerCase();
    const filtered = state.users.filter(user => (state.userRoleFilter === 'all' || user.role === state.userRoleFilter) && `${user.username} ${user.display_name} ${user.department?.name || ''}`.toLocaleLowerCase().includes(search));
    const roleOptions = [...new Map(state.users.map(user => [user.role, user.role_label])).entries()];
    const statusLabels = { active: 'نشط', activation_pending: 'بانتظار تفعيل الحساب', pending_approval: 'بانتظار اعتماد المجموعة', disabled: 'موقوف' };
    const activationNotice = state.activationLink ? `<div class="notice warn"><strong>رابط التفعيل (يظهر مرة واحدة، صالح لساعة):</strong><p>انسخه وسلّمه للطالب يدويًا عبر القناة المعتمدة.</p><input readonly value="${esc(state.activationLink)}" aria-label="رابط تفعيل الحساب" onclick="this.select()" /><button class="btn btn-outline btn-sm" type="button" data-action="copy-activation-link">نسخ الرابط</button></div>` : '';
    content = `${activationNotice}<form id="users-filter-form" class="filters"><input type="search" id="users-search" value="${esc(state.userSearchInput)}" placeholder="ابحث بالاسم أو اسم المستخدم أو القسم" aria-label="بحث المستخدمين" /><select id="users-role-filter" aria-label="تصفية الدور"><option value="all">كل الأدوار</option>${roleOptions.map(([role, label]) => `<option value="${esc(role)}" ${state.userRoleFilter === role ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><button class="btn btn-outline btn-sm" type="submit">بحث</button><button class="btn btn-outline btn-sm" type="button" data-action="refresh-data">تحديث</button></form><div class="table-scroll"><table class="data-table"><thead><tr><th>الاسم</th><th>اسم المستخدم</th><th>الدور</th><th>القسم</th><th>حالة الحساب</th><th>الإجراء</th></tr></thead><tbody>${filtered.length ? filtered.map(user => `<tr><td>${esc(user.display_name)}</td><td>${esc(user.username)}</td><td>${esc(user.role_label)}</td><td>${esc(user.department?.name || '—')}</td><td>${esc(statusLabels[user.account_status] || user.account_status)}</td><td>${state.role === 'dean' && user.role === 'student' && user.account_status === 'activation_pending' ? `<button class="btn btn-teal btn-sm" data-action="issue-activation" data-user-id="${esc(user.id)}">تفعيل الحساب</button>` : '—'}</td></tr>`).join('') : '<tr><td colspan="6"><div class="empty-state">لا يوجد مستخدمون يطابقون البحث.</div></td></tr>'}</tbody></table></div>`;
  }
  if (state.page === 'committees') {
    if (state.role === 'supervisor') {
      const queueRows = state.ideaQueue.map(idea => `<article class="review-member"><div class="request-name">${esc(idea.title)} · النسخة ${idea.version}</div><div class="request-meta">${esc(idea.project_title)} · ${esc(idea.department_name)}</div><p><b>المشكلة:</b> ${esc(idea.problem)}</p><p><b>الأهداف:</b> ${esc(idea.objectives)}</p><p><b>الحل المقترح:</b> ${esc(idea.proposed_solution)}</p><p><b>وجه الجدة:</b> ${esc(idea.novelty)}</p><form class="idea-committee-review-form" data-idea-id="${esc(idea.id)}"><label>توصيتك</label><select name="recommendation"><option value="recommend">يوصي بالاعتماد</option><option value="changes">يوصي بالتعديل</option><option value="not_suitable">لا يوصي بالاعتماد</option></select><textarea name="note" maxlength="3000" placeholder="ملاحظات، وإلزامية عند طلب التعديل أو عدم التوصية"></textarea><button class="btn btn-outline btn-sm" type="submit">حفظ التوصية</button></form></article>`).join('');
      const defenseCards = state.defenseData.committees.map(item => `<article class="review-member"><strong>${esc(item.project_title)}</strong><div class="request-meta">${esc(item.department_name)} · لجنة المناقشة معتمدة</div><p>رئيس اللجنة: ${esc(item.members.find(member => member.is_chair)?.name || '—')}</p><div class="action-group"><a class="btn btn-outline btn-sm" href="${API_BASE}/deliverables/${encodeURIComponent(item.final_deliverable)}/download/" data-download-id="${esc(item.final_deliverable)}">تنزيل النسخة النهائية</a><a class="btn btn-outline btn-sm" href="${API_BASE}/deliverables/${encodeURIComponent(item.report_deliverable)}/download/" data-download-id="${esc(item.report_deliverable)}">تنزيل التقرير</a><button class="btn btn-teal btn-sm" data-action="open-defense-evaluation" data-committee-id="${esc(item.id)}">${item.members.find(member => member.id === state.apiUser?.id)?.submitted ? 'عرض التقييمات' : 'تقييم المناقشة'}</button></div></article>`).join('');
      content = `<section><h2 class="panel-title">توصيات لجان الأفكار</h2>${queueRows || '<div class="empty-state">لا توجد أفكار بانتظار توصية اللجنة.</div>'}</section><section style="margin-top:22px"><h2 class="panel-title">لجان المناقشة المسندة إليك</h2>${defenseCards || '<div class="empty-state">لا توجد لجان مناقشة معتمدة مسندة إليك.</div>'}</section>${renderDefenseEvaluation()}${renderPostDefense()}`;
    } else {
    const departmentId = state.committeeDepartmentId;
    const department = state.departments.find(item => item.id === departmentId);
    const eligible = state.users.filter(user => user.role === 'supervisor' && user.account_status === 'active' && user.department?.id === departmentId);
    const committee = state.projectCommittee;
    const departmentPicker = state.role === 'dean' ? `<div class="field"><label for="committee-department-select">القسم</label><select id="committee-department-select"><option value="">اختر قسمًا</option>${state.departments.map(item => `<option value="${esc(item.id)}" ${item.id === departmentId ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></div>` : '';
    const memberForm = state.role === 'chair' && departmentId && committee?.status !== 'approved' ? `<form id="committee-nomination-form" class="form-grid"><div class="field full"><label>المشرفون المرشحون للجنة *</label><select name="member_ids" multiple size="6" required>${eligible.map(user => `<option value="${esc(user.id)}" ${committee?.member_ids?.includes(user.id) ? 'selected' : ''}>${esc(user.display_name)} · ${esc(user.username)}</option>`).join('')}</select><span class="help">اعتماد التشكيل النهائي من العميد. استخدم Ctrl أو Command لاختيار أكثر من مشرف.</span></div><div class="field full"><button class="btn btn-teal" type="submit">إرسال الترشيح للعميد</button></div></form>` : '';
    const statusText = committee ? committee.status === 'approved' ? 'معتمدة' : 'بانتظار اعتماد العميد' : 'لم يرشح رئيس القسم لجنة بعد';
    const defenseForms = state.role === 'chair' ? state.defenseData.referred_requests.map(item => {
      const possible = state.users.filter(user => user.role === 'supervisor' && user.account_status === 'active' && user.department?.id === item.department_id);
      const opts = possible.map(user => `<option value="${esc(user.id)}">${esc(user.display_name)} · ${esc(user.username)}</option>`).join('');
      return `<article class="review-member"><strong>${esc(item.project_title)}</strong><div class="request-meta">${esc(item.department_name)} · نسخة جاهزة: ${esc(item.final_filename)} · التقرير: ${esc(item.report_filename)}</div><form class="defense-nomination-form form-grid" data-readiness-id="${esc(item.id)}"><div class="field full"><label>أعضاء لجنة المناقشة (عضوان على الأقل) *</label><select name="member_ids" multiple size="5" required>${opts}</select></div><div class="field full"><label>رئيس اللجنة *</label><select name="chair_id" required><option value="">اختر رئيس اللجنة</option>${opts}</select></div><div class="field full"><button class="btn btn-teal" type="submit">إرسال التشكيل للعميد</button></div></form></article>`;
    }).join('') : '';
    const defenseCards = state.defenseData.committees.map(item => `<article class="review-member"><strong>${esc(item.project_title)}</strong><div class="request-meta">${esc(item.department_name)} · ${item.status === 'approved' ? 'معتمدة' : 'بانتظار اعتماد العميد'}</div><p>رئيس اللجنة: ${esc(item.members.find(member => member.is_chair)?.name || '—')}</p><p>الأعضاء: ${esc(item.members.map(member => member.name).join('، '))}</p>${item.status === 'approved' ? `<div class="action-group"><a class="btn btn-outline btn-sm" href="${API_BASE}/deliverables/${encodeURIComponent(item.final_deliverable)}/download/" data-download-id="${esc(item.final_deliverable)}">تنزيل النسخة النهائية</a><a class="btn btn-outline btn-sm" href="${API_BASE}/deliverables/${encodeURIComponent(item.report_deliverable)}/download/" data-download-id="${esc(item.report_deliverable)}">تنزيل التقرير</a>${state.role === 'dean' ? `<button class="btn btn-outline btn-sm" data-action="open-defense-evaluation" data-committee-id="${esc(item.id)}">عرض التقييمات</button>` : ''}</div>${['dean', 'chair'].includes(state.role) ? `<p class="request-meta">${item.defense_at ? `موعد الجلسة: ${esc(safeDate(item.defense_at))} · ${esc(item.defense_location || '')}` : 'لم يحدد موعد الجلسة.'}</p><form class="defense-meeting-schedule-form form-grid" data-committee-id="${esc(item.id)}"><div class="field"><label>موعد المناقشة</label><input name="defense_at" type="datetime-local" value="${esc(localDateTimeInput(item.defense_at))}" required /></div><div class="field"><label>المكان</label><input name="location" maxlength="240" value="${esc(item.defense_location || '')}" required /></div><button class="btn btn-outline btn-sm" type="submit">حفظ الموعد</button></form>` : ''}${state.role === 'dean' ? '<div class="request-meta">تفتح درجات الأعضاء بعد إرسالها. لا تصدر نتيجة نهائية قبل اعتماد آلية احتساب درجات اللجنة.</div>' : ''}` : state.role === 'dean' ? `<button class="btn btn-teal" data-action="approve-defense-committee" data-committee-id="${esc(item.id)}">اعتماد لجنة المناقشة</button>` : ''}</article>`).join('');
    const defenseSection = `<section class="panel" style="margin-top:18px"><h2 class="panel-title">لجان المناقشة</h2><p class="panel-sub">يرشح رئيس القسم أعضاء اللجنة ورئيسها بعد إحالة الجاهزية، ثم يعتمد العميد التشكيل. الملفات متاحة للأعضاء بعد الاعتماد.</p>${defenseForms || ''}${defenseCards || '<div class="empty-state">لا توجد لجان مناقشة أو طلبات محالة لهذا القسم.</div>'}</section>`;
    const rubricTotals = Object.fromEntries(['project', 'student'].map(scope => [scope, state.defenseRubric.filter(item => item.is_active && item.scope === scope).reduce((total, item) => total + Number(item.weight), 0)]));
    const rubricSection = state.role === 'dean' ? `<section class="panel" style="margin-top:18px"><h2 class="panel-title">معايير وأوزان تقييم المناقشة</h2><p class="panel-sub">اضبط معيارًا جماعيًا وآخر فرديًا على الأقل؛ يجب أن يبلغ مجموع أوزان كل نوع 100%. تحفظ اللجنة المعايير الحالية عند اعتماد تشكيلها.</p><p class="request-meta">المجموع الجماعي: ${rubricTotals.project}% · المجموع الفردي: ${rubricTotals.student}%</p>${state.defenseRubric.map(item => `<form class="defense-rubric-form form-grid" data-criterion-id="${esc(item.id)}"><div class="field"><label>المعيار</label><input name="title" maxlength="180" required value="${esc(item.title)}" /></div><div class="field"><label>النوع</label><select name="scope"><option value="project" ${item.scope === 'project' ? 'selected' : ''}>جماعي للمشروع</option><option value="student" ${item.scope === 'student' ? 'selected' : ''}>فردي للطالب</option></select></div><div class="field"><label>الوزن %</label><input name="weight" type="number" min="0.01" max="100" step="0.01" required value="${esc(item.weight)}" /></div><div class="field"><label>الترتيب</label><input name="position" type="number" min="0" value="${esc(item.position)}" /></div><div class="field full"><label>الوصف</label><input name="description" maxlength="2000" value="${esc(item.description)}" /></div><div class="field"><label>الحالة</label><select name="is_active"><option value="true" ${item.is_active ? 'selected' : ''}>مفعّل للتشكيلات الجديدة</option><option value="false" ${!item.is_active ? 'selected' : ''}>موقوف</option></select></div><div class="field"><button class="btn btn-outline btn-sm" type="submit">حفظ المعيار</button></div></form>`).join('')}<form id="defense-rubric-create-form" class="form-grid"><div class="field"><label>معيار جديد *</label><input name="title" maxlength="180" required /></div><div class="field"><label>النوع</label><select name="scope"><option value="project">جماعي للمشروع</option><option value="student">فردي للطالب</option></select></div><div class="field"><label>الوزن %</label><input name="weight" type="number" min="0.01" max="100" step="0.01" required /></div><div class="field"><label>الترتيب</label><input name="position" type="number" min="0" value="${state.defenseRubric.length}" /></div><div class="field full"><label>الوصف</label><input name="description" maxlength="2000" /></div><div class="field full"><button class="btn btn-teal" type="submit">إضافة معيار تقييم</button></div></form></section>` : '';
    content = `${departmentPicker}${departmentId ? `<section class="panel"><h2 class="panel-title">لجنة ${esc(department?.name || '')}</h2><p class="panel-sub">الحالة: ${statusText}</p>${committee?.member_names?.length ? `<div class="request-list">${committee.member_names.map(name => `<div class="request-row"><strong>${esc(name)}</strong></div>`).join('')}</div>` : ''}${state.role === 'dean' && committee?.status === 'pending_approval' ? `<button class="btn btn-teal" data-action="approve-committee" data-committee-id="${esc(committee.id)}">اعتماد تشكيل اللجنة</button>` : ''}${memberForm}</section>${defenseSection}${rubricSection}${renderDefenseEvaluation()}` : '<div class="empty-state">اختر القسم لعرض اللجنة.</div>'}`;
    }
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
      members: state.students.map(student => ({
        full_name: student.name.trim(), username: student.username.trim(), phone: student.phone.trim(),
        ...(student.existing_user_id ? { existing_user_id: student.existing_user_id } : {}),
        ...(state.role === 'student' && student.username.trim().toLocaleLowerCase() === state.apiUser?.username?.toLocaleLowerCase() ? { existing_user_id: state.apiUser.id } : {}),
      })),
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
    state.page = state.role === 'student' ? 'requests' : 'drafts'; state.modal = null; render();
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
    toast('تم حفظ الطلب وإرساله لرئيس القسم.');
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
    state.students = item.memberDetails.map(member => ({ name: member.full_name, username: member.username_proposed, phone: member.phone_proposed, existing_user_id: member.existing_user_id || '' }));
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
    document.querySelector('#sidebar')?.classList.remove('open');
    document.querySelector('#mobile-overlay')?.classList.remove('show');
    document.querySelector('.mobile-toggle')?.setAttribute('aria-expanded', 'false');
    state.page = pageButton.dataset.page; state.modal = null;
    if (state.page === 'detail') return render();
    await loadPageData(); render(); return;
  }
  const actionButton = event.target.closest('[data-action]');
  if (!actionButton) return;
  const action = actionButton.dataset.action;
  if (action === 'export-report') {
    event.preventDefault(); event.stopImmediatePropagation();
    const params = new URLSearchParams({ type: document.querySelector('#report-type')?.value || 'projects', output: actionButton.dataset.format || 'xlsx' });
    const dateFrom = document.querySelector('#report-date-from')?.value;
    const dateTo = document.querySelector('#report-date-to')?.value;
    const department = document.querySelector('#report-department')?.value;
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    if (department) params.set('department', department);
    const printWindow = actionButton.dataset.format === 'print' ? window.open('about:blank', '_blank') : null;
    if (actionButton.dataset.format === 'print' && !printWindow) { toast('اسمح بفتح النافذة لإعداد نسخة PDF.', 'error'); return; }
    try {
      const response = await fetch(`${API_BASE}/reports/?${params}`, { headers: { Authorization: `Token ${state.apiToken}` }, credentials: 'omit' });
      if (!response.ok) {
        if (printWindow) printWindow.close();
        let detail = 'تعذر إنشاء التقرير.';
        try { detail = (await response.json()).detail || detail; } catch (_) { /* استجابة غير JSON */ }
        throw new Error(detail);
      }
      if (actionButton.dataset.format === 'print') {
        printWindow.document.open(); printWindow.document.write(await response.text()); printWindow.document.close();
      } else {
        const blobUrl = URL.createObjectURL(await response.blob());
        const filename = response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/i)?.[1] || 'gpms-report.xlsx';
        const anchor = document.createElement('a'); anchor.href = blobUrl; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      }
      toast('أُعد التقرير وفق نطاق صلاحيات حسابك.');
    } catch (error) { toast(error.message, 'error'); }
    return;
  }
  if (action === 'check-idea-similarity') {
    event.preventDefault(); event.stopImmediatePropagation();
    const form = document.querySelector('#project-idea-form');
    const resultsBox = document.querySelector('#idea-similarity-results');
    if (!form || !resultsBox) return;
    if (!form.reportValidity()) return;
    resultsBox.innerHTML = '<p>جارٍ مقارنة الفكرة بالأفكار المعتمدة…</p>';
    try {
      const payload = Object.fromEntries(new FormData(form).entries());
      const result = await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/idea-similarity/`, { method: 'POST', body: JSON.stringify(payload) });
      const fieldLabels = { title: 'العنوان', problem: 'المشكلة', objectives: 'الأهداف', proposed_solution: 'الحل المقترح', novelty: 'وجه الجدة' };
      const matches = result.matches || [];
      resultsBox.innerHTML = `<p>${esc(result.notice || '')}</p>${matches.length ? `<div class="request-list">${matches.map(match => `<article class="request-row"><div><strong>${esc(match.project_title)}</strong><div class="request-meta">${esc(match.department)} · ${match.score}% تشابه لفظي · مجالات التقارب: ${match.similar_fields.map(field => esc(fieldLabels[field] || field)).join('، ') || 'غير محدد'}</div><div class="request-meta">${esc(match.title)}</div></div></article>`).join('')}</div>` : '<p class="request-meta">لم تظهر أفكار معتمدة متقاربة وفق المقارنة اللفظية.</p>'}`;
    } catch (error) { resultsBox.innerHTML = `<p role="alert">${esc(error.message)}</p>`; }
    return;
  }
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
      state.students = state.role === 'student'
        ? [{ name: state.apiUser?.display_name || '', username: state.apiUser?.username || '', phone: state.apiUser?.phone || '' }]
        : [emptyStudent()];
      state.supervisorType = supervisors.length ? 'existing' : 'new'; state.selectedSupervisor = supervisors[0]?.id || '';
      state.supervisor = { name: '', username: '', phone: '', email: '', specialty: '' };
      state.draftRequestId = null; state.step = 0; state.page = 'wizard'; state.modal = null; render();
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'cancel-wizard') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.page = state.draftRequestId ? (state.role === 'student' ? 'requests' : 'drafts') : 'requests'; state.modal = null; await loadPageData(); render(); return;
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
  if (action === 'issue-activation') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const result = await apiRequest(`/users/${encodeURIComponent(actionButton.dataset.userId)}/activation/`, { method: 'POST', body: '{}' });
      state.activationLink = `${window.location.origin}/?activation=${encodeURIComponent(result.activation_token)}`;
      render(); toast('أُصدر رابط تفعيل صالح لساعة ولمرة واحدة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'copy-activation-link') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      await navigator.clipboard.writeText(state.activationLink);
      toast('تم نسخ رابط التفعيل.');
    } catch (_) {
      const field = document.querySelector('[aria-label="رابط تفعيل الحساب"]');
      field?.select();
      toast('حدد الرابط وانسخه يدويًا.');
    }
    return;
  }
  if (action === 'edit-appointment') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.editingAppointmentId = actionButton.dataset.appointmentId; render(); return;
  }
  if (action === 'cancel-appointment-edit') {
    event.preventDefault(); event.stopImmediatePropagation(); state.editingAppointmentId = null; render(); return;
  }
  if (action === 'delete-appointment') {
    event.preventDefault(); event.stopImmediatePropagation();
    const appointment = state.appointments.find(item => item.id === actionButton.dataset.appointmentId);
    if (appointment && window.confirm(`هل تريد حذف الموعد «${appointment.title}»؟`)) {
      try {
        await apiRequest(`/appointments/${encodeURIComponent(appointment.id)}/`, { method: 'DELETE' });
        state.editingAppointmentId = null; await loadPageData(); render(); toast('تم حذف الموعد.');
      } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    }
    return;
  }
  if (action === 'open-project-notes') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.currentProjectId = actionButton.dataset.projectId; state.page = 'notes';
    await loadPageData(); render(); return;
  }
  if (action === 'delete-stage') {
    event.preventDefault(); event.stopImmediatePropagation();
    if (!window.confirm('حذف هذه المرحلة المخصصة ومهامها؟')) return;
    try {
      await apiRequest(`/project-stages/${encodeURIComponent(actionButton.dataset.stageId)}/`, { method: 'DELETE' });
      await loadPageData(); render(); toast('تم حذف المرحلة المخصصة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'save-task-status') {
    event.preventDefault(); event.stopImmediatePropagation();
    const taskId = actionButton.dataset.taskId;
    const statusValue = document.querySelector(`[data-task-status=\"${CSS.escape(taskId)}\"]`)?.value;
    try {
      await apiRequest(`/project-tasks/${encodeURIComponent(taskId)}/`, { method: 'PATCH', body: JSON.stringify({ status: statusValue }) });
      await loadPageData(); render(); toast('تم تحديث حالة المهمة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'open-project') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.currentProjectId = actionButton.dataset.projectId; state.page = 'project';
    await loadPageData(); render(); return;
  }
  if (action === 'promote-group-leader') {
    event.preventDefault(); event.stopImmediatePropagation();
    const project = state.projectDetail;
    if (!project || !window.confirm('تعيين هذا الطالب قائدًا للمجموعة؟')) return;
    try { await apiRequest(`/groups/${encodeURIComponent(project.group.id)}/leader/`, { method: 'PATCH', body: JSON.stringify({ student_id: actionButton.dataset.studentId }) }); await loadPageData(); render(); toast('تم تغيير قائد المجموعة مع حفظ سجل العضوية.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'remove-group-member') {
    event.preventDefault(); event.stopImmediatePropagation();
    const reason = window.prompt('اكتب سبب إنهاء عضوية الطالب:')?.trim() || '';
    if (!reason) { toast('سبب إنهاء العضوية مطلوب.', 'error'); return; }
    const payload = { reason };
    if (actionButton.dataset.isLeader === 'true') {
      payload.new_leader_id = document.querySelector(`[data-replacement-leader="${CSS.escape(actionButton.dataset.studentId)}"]`)?.value || '';
      if (!payload.new_leader_id) { toast('اختر قائدًا بديلًا أولًا.', 'error'); return; }
    }
    try { await apiRequest(`/groups/${encodeURIComponent(actionButton.dataset.groupId)}/members/${encodeURIComponent(actionButton.dataset.studentId)}/`, { method: 'DELETE', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('انتهت العضوية وسُجل سببها.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'decline-project-supervision') {
    event.preventDefault(); event.stopImmediatePropagation();
    const reason = window.prompt('اكتب سبب الاعتذار عن الإشراف:')?.trim() || '';
    if (!reason) { toast('سبب الاعتذار مطلوب.', 'error'); return; }
    try { await apiRequest(`/projects/${encodeURIComponent(actionButton.dataset.projectId)}/supervisor/decline/`, { method: 'POST', body: JSON.stringify({ reason }) }); await loadPageData(); render(); toast('سُجل اعتذارك وأُخطر رئيس القسم لإعادة الإسناد.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'open-notification') {
    event.preventDefault(); event.stopImmediatePropagation();
    const notification = state.notifications.find(item => item.id === actionButton.dataset.notificationId);
    if (!notification) return;
    try {
      await apiRequest(`/notifications/${encodeURIComponent(notification.id)}/read/`, { method: 'POST', body: '{}' });
      if (notification.target_url) {
        const target = new URL(notification.target_url, window.location.origin);
        if (target.origin === window.location.origin) {
          const destination = target.searchParams.get('page');
          const allowed = ['overview', 'requests', 'groups', 'project', 'notes', 'deliverables', 'calendar', 'committees', 'notifications'];
          if (allowed.includes(destination)) state.page = destination;
          const projectId = target.searchParams.get('project');
          if (projectId && UUID_PATTERN.test(projectId)) state.currentProjectId = projectId;
        }
      }
      await loadPageData(); render();
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'review-project-plan') {
    event.preventDefault(); event.stopImmediatePropagation();
    const decision = actionButton.dataset.decision;
    const payload = { decision };
    if (decision === 'changes_requested') {
      payload.note = window.prompt('اكتب ملاحظات التعديلات المطلوبة:')?.trim() || '';
      if (!payload.note) { toast('ملاحظات التعديل مطلوبة.', 'error'); return; }
    }
    try {
      await apiRequest(`/project-plans/${encodeURIComponent(actionButton.dataset.planId)}/review/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast(decision === 'approved' ? 'تم اعتماد خطة المشروع.' : 'أعيدت الخطة للتعديل.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (['review-post-defense-revision', 'review-post-defense-final'].includes(action)) {
    event.preventDefault(); event.stopImmediatePropagation();
    const decision = actionButton.dataset.decision;
    const payload = { decision };
    if (decision === 'changes_requested') {
      payload.note = window.prompt('اكتب المطلوب استكماله:')?.trim() || '';
      if (!payload.note) { toast('ملاحظة الاستكمال مطلوبة.', 'error'); return; }
    }
    const endpoint = action === 'review-post-defense-revision'
      ? `/post-defense-revisions/${encodeURIComponent(actionButton.dataset.revisionId)}/review/`
      : `/post-defense-final-submissions/${encodeURIComponent(actionButton.dataset.submissionId)}/review/`;
    try { await apiRequest(endpoint, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast(decision === 'approved' ? 'تم الاعتماد الفني.' : 'أُعيدت للمراجعة بعد الاستكمال.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'approve-committee') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      await apiRequest(`/project-committees/${encodeURIComponent(actionButton.dataset.committeeId)}/approve/`, { method: 'POST', body: '{}' });
      await loadPageData(); render(); toast('تم اعتماد تشكيل لجنة مشاريع التخرج.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'approve-defense-committee') {
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      await apiRequest(`/defense-committees/${encodeURIComponent(actionButton.dataset.committeeId)}/approve/`, { method: 'POST', body: '{}' });
      await loadPageData(); render(); toast('تم اعتماد لجنة المناقشة وإتاحة ملفي المشروع لأعضائها.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'open-defense-evaluation') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.defenseEvaluationId = actionButton.dataset.committeeId;
    try { await loadPageData(); render(); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'close-defense-evaluation') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.defenseEvaluationId = ''; state.defenseEvaluation = null; render();
    return;
  }
  if (action === 'open-post-defense') {
    event.preventDefault(); event.stopImmediatePropagation();
    state.postDefenseProjectId = actionButton.dataset.projectId;
    try { await loadPageData(); render(); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (['idea-supervisor-review', 'idea-chair-review'].includes(action)) {
    event.preventDefault(); event.stopImmediatePropagation();
    const decision = actionButton.dataset.decision;
    const payload = { decision };
    if (action === 'idea-chair-review' && decision === 'approved') {
      const idea = state.projectIdeas.find(item => item.id === actionButton.dataset.ideaId);
      if (idea?.committee_reviews?.some(review => review.recommendation !== 'recommend')) {
        payload.note = window.prompt('اكتب مبرر اعتماد الفكرة خلافًا لتوصية اللجنة:')?.trim() || '';
        if (!payload.note) { toast('مبرر تجاوز توصية اللجنة مطلوب.', 'error'); return; }
      }
    }
    if (decision !== 'forward' && decision !== 'approved') {
      payload.note = window.prompt(decision === 'rejected' ? 'اكتب سبب الرفض:' : 'اكتب ملاحظات التعديل:')?.trim() || '';
      if (!payload.note) { toast('الملاحظة مطلوبة لهذا القرار.', 'error'); return; }
    }
    const path = action === 'idea-supervisor-review' ? 'supervisor-review' : 'chair-review';
    try {
      await apiRequest(`/project-ideas/${encodeURIComponent(actionButton.dataset.ideaId)}/${path}/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم حفظ قرار مراجعة الفكرة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (action === 'review-readiness') {
    event.preventDefault(); event.stopImmediatePropagation();
    const decision = actionButton.dataset.decision;
    const payload = { decision };
    if (decision === 'changes_requested' || decision === 'rejected') {
      payload.note = window.prompt(decision === 'rejected' ? 'اكتب سبب الرفض:' : 'اكتب ملاحظات التعديل:')?.trim() || '';
      if (!payload.note) { toast('الملاحظة مطلوبة لهذا القرار.', 'error'); return; }
    }
    try {
      await apiRequest(`/discussion-readiness/${encodeURIComponent(actionButton.dataset.requestId)}/${actionButton.dataset.stage}/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم حفظ قرار طلب الجاهزية.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (['start-stage', 'submit-stage', 'review-stage'].includes(action)) {
    event.preventDefault(); event.stopImmediatePropagation();
    const stageId = actionButton.dataset.stageId;
    let endpointAction = action === 'start-stage' ? 'start' : action === 'submit-stage' ? 'submit' : 'review';
    const payload = {};
    if (action === 'review-stage') {
      payload.decision = actionButton.dataset.decision;
      if (payload.decision === 'changes_requested') {
        payload.note = window.prompt('اكتب ملاحظات التعديلات المطلوبة:')?.trim() || '';
        if (!payload.note) { toast('ملاحظات التعديل مطلوبة.', 'error'); return; }
      }
    }
    try {
      await apiRequest(`/project-stages/${encodeURIComponent(stageId)}/${endpointAction}/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم حفظ الإجراء على الخادم.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
}, true);

document.addEventListener('change', event => {
  if (event.target.id === 'committee-department-select') {
    state.committeeDepartmentId = event.target.value;
    loadPageData().finally(render);
  }
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
  if (event.target.id === 'activate-account-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const password = document.querySelector('#activation-password')?.value || '';
    const confirmation = document.querySelector('#activation-password-confirm')?.value || '';
    if (password !== confirmation) { toast('كلمتا المرور غير متطابقتين.', 'error'); return; }
    try {
      await apiRequest('/auth/one-time-password/activate/', { method: 'POST', body: JSON.stringify({ token: state.activationToken, password }) });
      state.activationToken = ''; state.apiError = '';
      window.history.replaceState({}, document.title, window.location.pathname);
      login(); toast('تم تفعيل الحساب. يمكنك تسجيل الدخول الآن.');
    } catch (error) { state.apiError = error.message; login(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'appointment-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const localStart = document.querySelector('#appointment-start')?.value || '';
    const startsAt = new Date(localStart);
    if (!localStart || Number.isNaN(startsAt.getTime())) { toast('اختر تاريخًا ووقتًا صالحين.', 'error'); return; }
    const payload = {
      title: document.querySelector('#appointment-title')?.value.trim() || '',
      description: document.querySelector('#appointment-description')?.value.trim() || '',
      starts_at: startsAt.toISOString(),
    };
    const projectId = document.querySelector('#appointment-project')?.value;
    const departmentId = document.querySelector('#appointment-department')?.value;
    if (projectId) payload.project = projectId;
    else if (state.role === 'dean') payload.department_id = departmentId;
    try {
      const editingId = state.editingAppointmentId;
      await apiRequest(editingId ? `/appointments/${encodeURIComponent(editingId)}/` : '/appointments/', {
        method: editingId ? 'PATCH' : 'POST', body: JSON.stringify(payload),
      });
      state.editingAppointmentId = null; await loadPageData(); render(); toast(editingId ? 'تم تحديث الموعد.' : 'تمت إضافة الموعد.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'project-repository-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const repositoryUrl = document.querySelector('#project-repository-url')?.value.trim() || '';
    try {
      state.projectDetail = await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/repository/`, {
        method: 'PATCH', body: JSON.stringify({ repository_url: repositoryUrl }),
      });
      state.projects = state.projects.map(project => project.id === state.projectDetail.id ? state.projectDetail : project);
      render(); toast('تم حفظ رابط مستودع GitHub.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
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
  if (event.target.matches('.stage-edit-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const formData = new FormData(event.target);
    const payload = Object.fromEntries(formData.entries());
    for (const key of ['starts_at', 'due_at']) if (!payload[key]) payload[key] = null;
    try {
      await apiRequest(`/project-stages/${encodeURIComponent(event.target.dataset.stageId)}/`, { method: 'PATCH', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم حفظ خطة المرحلة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'project-stage-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const formData = new FormData(event.target);
    try {
      await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/stages/`, { method: 'POST', body: JSON.stringify(Object.fromEntries(formData.entries())) });
      await loadPageData(); render(); toast('تمت إضافة المرحلة المخصصة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'committee-nomination-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const memberIds = [...event.target.elements.member_ids.selectedOptions].map(option => option.value);
    try {
      await apiRequest(`/departments/${encodeURIComponent(state.committeeDepartmentId)}/project-committee/`, { method: 'POST', body: JSON.stringify({ member_ids: memberIds }) });
      await loadPageData(); render(); toast('أُرسل ترشيح اللجنة إلى العميد للاعتماد.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.matches('.defense-nomination-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const memberIds = [...event.target.elements.member_ids.selectedOptions].map(option => option.value);
    const chairId = event.target.elements.chair_id.value;
    try {
      await apiRequest('/defense-committees/', { method: 'POST', body: JSON.stringify({ readiness_request_id: event.target.dataset.readinessId, member_ids: memberIds, chair_id: chairId }) });
      await loadPageData(); render(); toast('أُرسل تشكيل لجنة المناقشة إلى العميد للاعتماد.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'defense-rubric-create-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    payload.position = Number(payload.position || 0); payload.is_active = true;
    try { await apiRequest('/defense-rubric/', { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('أضيف معيار التقييم.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.matches('.defense-rubric-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    payload.position = Number(payload.position || 0); payload.is_active = payload.is_active === 'true';
    try { await apiRequest(`/defense-rubric/${encodeURIComponent(event.target.dataset.criterionId)}/`, { method: 'PATCH', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('حُفظ معيار التقييم.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'defense-evaluation-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const scores = [...event.target.querySelectorAll('[data-eval-score]')].map(input => {
      const studentId = input.dataset.studentId || null;
      const key = `${input.dataset.criterionId}:${studentId || 'project'}`;
      const note = [...event.target.querySelectorAll('[data-eval-note]')].find(field => field.dataset.noteKey === key)?.value || '';
      return { criterion_id: input.dataset.criterionId, student_id: studentId, score: input.value, note };
    });
    try { await apiRequest(`/defense-committees/${encodeURIComponent(state.defenseEvaluationId)}/evaluation/`, { method: 'POST', body: JSON.stringify({ scores }) }); await loadPageData(); render(); toast('أُرسل تقييمك سرًا. لا يمكن تعديله بعد الإرسال.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'defense-minutes-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try { await apiRequest(`/defense-committees/${encodeURIComponent(state.defenseEvaluationId)}/meeting/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('حُفظ محضر المناقشة.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.matches('.defense-meeting-schedule-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const formData = new FormData(event.target);
    const local = formData.get('defense_at');
    const payload = { defense_at: local ? new Date(local).toISOString() : null, location: formData.get('location') || '' };
    try { await apiRequest(`/defense-committees/${encodeURIComponent(event.target.dataset.committeeId)}/meeting/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('تم حفظ موعد جلسة المناقشة.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'post-defense-revision-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try { await apiRequest(`/projects/${encodeURIComponent(state.postDefenseProjectId)}/post-defense/revisions/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('سُجلت ملاحظة اللجنة وكُلّف الطالب.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.matches('.post-defense-revision-submit-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try { await apiRequest(`/post-defense-revisions/${encodeURIComponent(event.target.dataset.revisionId)}/submit/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('أُرسل دليل تنفيذ التعديل إلى المشرف.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'post-defense-final-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try { await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/post-defense/final-submissions/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('أُرسلت النسخة النهائية إلى المشرف للاعتماد الفني.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'project-idea-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try {
      await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/ideas/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم إرسال الفكرة إلى المشرف.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'discussion-readiness-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try {
      await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/discussion-readiness/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم تقديم طلب جاهزية المناقشة للمشرف.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.matches('.idea-committee-review-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try {
      await apiRequest(`/project-ideas/${encodeURIComponent(event.target.dataset.ideaId)}/committee-review/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم حفظ توصية عضو اللجنة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'project-plan-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try {
      await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/plans/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تم إرسال خطة المشروع للمشرف.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'group-member-add-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try { await apiRequest(`/groups/${encodeURIComponent(state.projectDetail.group.id)}/members/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('أضيف الطالب للمجموعة.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'supervisor-assignment-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const payload = Object.fromEntries(new FormData(event.target).entries());
    try { await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/supervisor/`, { method: 'POST', body: JSON.stringify(payload) }); await loadPageData(); render(); toast('تم تحديث تكليف المشرف مع الاحتفاظ بالسجل السابق.'); }
    catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'project-task-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const formData = new FormData(event.target);
    const payload = Object.fromEntries(formData.entries());
    for (const key of ['assigned_to', 'due_at', 'description']) if (!payload[key]) delete payload[key];
    try {
      await apiRequest(`/projects/${encodeURIComponent(state.currentProjectId)}/tasks/`, { method: 'POST', body: JSON.stringify(payload) });
      await loadPageData(); render(); toast('تمت إضافة المهمة وتوزيعها.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.id === 'deliverable-upload-form') {
    event.preventDefault(); event.stopImmediatePropagation();
    const file = document.querySelector('#deliverable-file')?.files?.[0];
    if (!file) { toast('اختر ملفًا قبل الرفع.', 'error'); return; }
    const submitButton = event.target.querySelector('[type="submit"]');
    submitButton.disabled = true; submitButton.textContent = 'جارٍ رفع الملف…';
    try {
      const formData = new FormData(); formData.append('file', file);
      const stageId = document.querySelector('#deliverable-stage')?.value;
      if (stageId) formData.append('stage_id', stageId);
      formData.append('visibility', document.querySelector('#deliverable-visibility')?.value || 'shared');
      await apiRequest(`/projects/${state.currentProjectId}/deliverables/`, { method: 'POST', body: formData });
      await loadPageData(); render(); toast('تم رفع الملف بصلاحيات الرؤية المختارة.');
    } catch (error) { state.apiError = error.message; render(); toast(error.message, 'error'); }
    return;
  }
  if (event.target.matches('.stage-progress-form')) {
    event.preventDefault(); event.stopImmediatePropagation();
    const progress = Number(new FormData(event.target).get('progress'));
    try {
      await apiRequest(`/project-stages/${encodeURIComponent(event.target.dataset.stageId)}/progress/`, { method: 'POST', body: JSON.stringify({ progress }) });
      await loadPageData(); render(); toast('تم تحديث نسبة إنجاز المرحلة.');
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

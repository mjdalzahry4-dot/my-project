from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .models import AuditLog, Department, GroupMember, GroupRequest, Notification, Project, ProjectGroup, ProjectStage, ProjectSupervisor, RequestDecision, RequestMember, RequestRevision, RequestSupervisor, StudentProfile, SupervisorProfile, User


class Conflict(APIException):
    status_code = 409
    default_detail = "تعارضت العملية مع حالة أو بيانات حالية. حدّث الصفحة ثم أعد المحاولة."
    default_code = "conflict"


def audit(actor, action, entity_type, entity_id=None, request=None, metadata=None):
    AuditLog.objects.create(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, request=request, safe_metadata=metadata or {})


def notify_users(actor, recipients, event_type, title, body="", target_url=""):
    unique = {user.id: user for user in recipients if user and (not actor or user.id != actor.id)}
    Notification.objects.bulk_create([
        Notification(recipient=user, actor=actor, event_type=event_type, title=title[:180], body=body[:500], target_url=target_url[:500])
        for user in unique.values()
    ])


def check_department_scope(actor, department):
    if actor.role == User.Role.DEAN:
        return
    if actor.role == User.Role.STUDENT and actor.department_id == department.id:
        return
    if actor.role != User.Role.DEPARTMENT_CHAIR or not actor.department_id or actor.department_id != department.id:
        raise PermissionDenied("لا تملك صلاحية إدارة هذا القسم.")


def _check_account_collisions(data):
    names = [m["username"].casefold() for m in data["members"] if not m.get("existing_user_id")]
    supervisor = data["supervisor"]
    if supervisor["kind"] == "new":
        names.append(supervisor["username"].casefold())
    if len(names) != len(set(names)):
        raise ValidationError({"members": "توجد أسماء مستخدمين مكررة في الطلب."})
    collisions = User.objects.filter(username_normalized__in=names).exists()
    if collisions:
        raise ValidationError({"members": "تعذر استخدام بعض بيانات الحسابات. راجع القسم للتحقق منها."})


def _validate_existing_members(data):
    for member in data["members"]:
        user_id = member.get("existing_user_id")
        if not user_id:
            continue
        user = User.objects.select_for_update().filter(id=user_id, role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE).first()
        profile = StudentProfile.objects.filter(user_id=user_id).first()
        if not user or not profile or user.username_normalized != member["username"].casefold() or user.phone != member["phone"] or profile.full_name.strip().casefold() != member["full_name"].strip().casefold():
            raise ValidationError({"members": "تعذر التحقق من بيانات أحد الحسابات الموجودة."})
        if GroupMember.objects.filter(student=user, left_at__isnull=True).exists():
            raise ValidationError({"members": "أحد الطلاب مرتبط بمجموعة نشطة بالفعل."})


def create_revision(request, data, actor):
    department = Department.objects.get(id=data["department_id"], is_active=True)
    check_department_scope(actor, department)
    _check_account_collisions(data)
    _validate_existing_members(data)
    latest = request.revisions.order_by("-revision_number").first()
    number = (latest.revision_number + 1) if latest else 1
    revision = RequestRevision.objects.create(
        request=request,
        revision_number=number,
        group_code_proposed=data["group_code"].strip(),
        project_title=data["project_title"].strip(),
        project_description=data["project_description"].strip(),
        academic_year=data["academic_year"].strip(),
        department=department,
        created_by=actor,
    )
    for order, member in enumerate(data["members"], start=1):
        RequestMember.objects.create(
            revision=revision,
            full_name=member["full_name"].strip(),
            username_proposed=member["username"].strip(),
            username_normalized=member["username"].casefold(),
            phone_proposed=member["phone"].strip(),
            existing_user_id=member.get("existing_user_id"),
            member_order=order,
        )
    supervisor_data = data["supervisor"]
    if supervisor_data["kind"] == "existing":
        RequestSupervisor.objects.create(revision=revision, supervisor_type=RequestSupervisor.Type.EXISTING, existing_user_id=supervisor_data["existing_user_id"])
    else:
        RequestSupervisor.objects.create(
            revision=revision,
            supervisor_type=RequestSupervisor.Type.NEW,
            full_name=supervisor_data["full_name"].strip(),
            username_proposed=supervisor_data["username"].strip(),
            username_normalized=supervisor_data["username"].casefold(),
            phone_proposed=supervisor_data["phone"].strip(),
            email=supervisor_data.get("email", "").strip(),
            specialty=supervisor_data.get("specialty", "").strip(),
        )
    request.current_revision = revision
    request.version += 1
    request.save(update_fields=["current_revision", "version", "updated_at"])
    return revision


@transaction.atomic
def create_request(actor, data):
    if actor.role != User.Role.STUDENT:
        raise PermissionDenied("إنشاء طلب مجموعة متاح للطالب.")
    if not actor.department_id:
        raise ValidationError("يجب ربط حساب الطالب بقسم قبل إنشاء الطلب.")
    if str(data["department_id"]) != str(actor.department_id):
        raise PermissionDenied("يمكن للطالب إنشاء طلب ضمن قسمه فقط.")
    request = GroupRequest.objects.create(created_by=actor)
    try:
        revision = create_revision(request, data, actor)
    except Exception:
        raise
    audit(actor, "group_request.created", "group_request", request.id, request, {"revision": revision.revision_number})
    return request


@transaction.atomic
def update_request(actor, request_id, data):
    request = GroupRequest.objects.select_for_update().select_related("current_revision").get(id=request_id)
    if request.status not in {GroupRequest.Status.DRAFT, GroupRequest.Status.RETURNED}:
        raise Conflict("لا يمكن تعديل الطلب في حالته الحالية.")
    if request.created_by_id != actor.id:
        raise PermissionDenied("يمكن لمنشئ الطلب المخول تعديله فقط.")
    revision = create_revision(request, data, actor)
    audit(actor, "group_request.updated", "group_request", request.id, request, {"revision": revision.revision_number})
    return request


def validate_revision_for_submission(revision, actor=None):
    members = list(revision.members.select_related("existing_user").order_by("member_order"))
    if not members:
        raise ValidationError({"members": "أضف طالبًا واحدًا على الأقل."})
    names = [member.username_normalized for member in members]
    if len(names) != len(set(names)):
        raise ValidationError({"members": "أسماء المستخدمين مكررة داخل الطلب."})
    for member in members:
        if not member.full_name.strip() or not member.username_proposed.strip() or not member.phone_proposed.strip():
            raise ValidationError({"members": "بيانات أحد الطلاب غير مكتملة."})
        user = member.existing_user
        if user:
            if user.account_status != User.AccountStatus.ACTIVE or user.role != User.Role.STUDENT or user.username_normalized != member.username_normalized or user.phone != member.phone_proposed:
                raise ValidationError({"members": "تعذر التحقق من أحد الحسابات الموجودة."})
            if GroupMember.objects.filter(student=user, left_at__isnull=True).exists():
                raise Conflict("أحد الطلاب مرتبط بمجموعة نشطة بالفعل.")
        elif User.objects.filter(username_normalized=member.username_normalized).exists():
            raise ValidationError({"members": "تعذر استخدام بعض بيانات الحسابات. راجع القسم للتحقق منها."})
    if actor and actor.role == User.Role.STUDENT and not any(member.existing_user_id == actor.id for member in members):
        raise ValidationError({"members": "يجب إضافة حسابك كعضو في المجموعة قبل إرسال الطلب."})
    supervisor = revision.supervisor
    if supervisor.supervisor_type == RequestSupervisor.Type.EXISTING:
        if not supervisor.existing_user or supervisor.existing_user.role != User.Role.SUPERVISOR or supervisor.existing_user.account_status != User.AccountStatus.ACTIVE:
            raise ValidationError({"supervisor": "حساب المشرف المختار غير صالح."})
    elif User.objects.filter(username_normalized=supervisor.username_normalized).exists():
        raise ValidationError({"supervisor": "تعذر استخدام بعض بيانات الحسابات. راجع القسم للتحقق منها."})
    if not revision.project_title.strip() or not revision.project_description.strip() or not revision.academic_year.strip():
        raise ValidationError("بيانات المشروع غير مكتملة.")


@transaction.atomic
def submit_request(actor, request_id, expected_version=None):
    request = GroupRequest.objects.select_for_update().select_related("current_revision", "current_revision__department").get(id=request_id)
    if request.created_by_id != actor.id or actor.role != User.Role.STUDENT:
        raise PermissionDenied("يمكن لمنشئ الطلب من الطلاب إرساله فقط.")
    if request.status not in {GroupRequest.Status.DRAFT, GroupRequest.Status.RETURNED}:
        raise Conflict("الطلب ليس مسودة أو معادًا للتعديل.")
    if expected_version is not None and int(expected_version) != request.version:
        raise Conflict("تغير الطلب منذ آخر قراءة. حدّث الصفحة ثم أعد المحاولة.")
    if not request.current_revision_id:
        raise ValidationError("أضف بيانات الطلب قبل إرساله.")
    check_department_scope(actor, request.current_revision.department)
    validate_revision_for_submission(request.current_revision, actor)
    now = timezone.now()
    request.current_revision.submitted_at = now
    request.current_revision.save(update_fields=["submitted_at"])
    request.status = GroupRequest.Status.PENDING
    request.submitted_at = now
    request.closed_at = None
    request.version += 1
    request.save(update_fields=["status", "submitted_at", "closed_at", "version", "updated_at"])
    audit(actor, "group_request.submitted", "group_request", request.id, request, {"revision": request.current_revision.revision_number})
    notify_users(actor, User.objects.filter(role=User.Role.DEPARTMENT_CHAIR, department=request.current_revision.department, account_status=User.AccountStatus.ACTIVE), "group_request.submitted", "طلب مجموعة جديد", request.current_revision.project_title, "/?page=requests")
    return request


def _create_pending_account(role, username, phone, full_name, department):
    user = User(username=username.strip(), role=role, phone=phone.strip(), department=department, account_status=User.AccountStatus.ACTIVATION_PENDING)
    user.set_unusable_password()
    user.save()
    if role == User.Role.STUDENT:
        StudentProfile.objects.create(user=user, full_name=full_name.strip())
    else:
        SupervisorProfile.objects.create(user=user, full_name=full_name.strip())
    return user


@transaction.atomic
def decide_request(actor, request_id, decision, note=""):
    if actor.role != User.Role.DEPARTMENT_CHAIR or not actor.department_id:
        raise PermissionDenied("اعتماد المجموعة متاح لرئيس القسم المرتبط بها فقط.")
    if decision not in {RequestDecision.Decision.APPROVED, RequestDecision.Decision.RETURNED, RequestDecision.Decision.REJECTED}:
        raise ValidationError("القرار غير صالح.")
    if decision in {RequestDecision.Decision.RETURNED, RequestDecision.Decision.REJECTED} and not note.strip():
        raise ValidationError({"note": "ملاحظات الإعادة أو سبب الرفض مطلوب."})
    request = GroupRequest.objects.select_for_update().select_related("current_revision", "current_revision__department").get(id=request_id)
    if request.created_by_id == actor.id:
        raise PermissionDenied("لا يجوز لصاحب الطلب اتخاذ قرار الاعتماد عليه.")
    if request.status != GroupRequest.Status.PENDING or not request.current_revision_id:
        raise Conflict("لا يمكن اتخاذ قرار على طلب غير معلق.")
    revision = RequestRevision.objects.select_for_update().select_related("department").get(id=request.current_revision_id)
    check_department_scope(actor, revision.department)
    validate_revision_for_submission(revision)
    now = timezone.now()
    if decision == RequestDecision.Decision.APPROVED:
        try:
            group = ProjectGroup.objects.create(
                group_code=revision.group_code_proposed,
                department=revision.department,
                academic_year=revision.academic_year,
                source_request=request,
                status=ProjectGroup.Status.ACTIVE,
            )
            project = Project.objects.create(group=group, title=revision.project_title, description=revision.project_description, status=Project.Status.ACTIVE)
            default_stages = [
                "التحليل والمتطلبات", "التصميم", "إعداد المكونات الأساسية", "التنفيذ والتطوير",
                "الاختبار", "التوثيق", "التجهيز للتسليم والمناقشة",
            ]
            ProjectStage.objects.bulk_create([
                ProjectStage(project=project, order=order, title=title)
                for order, title in enumerate(default_stages, start=1)
            ])
            for snapshot in revision.members.select_related("existing_user").order_by("member_order"):
                student = snapshot.existing_user or _create_pending_account(User.Role.STUDENT, snapshot.username_proposed, snapshot.phone_proposed, snapshot.full_name, revision.department)
                if snapshot.existing_user_id is None:
                    snapshot.existing_user = student
                    snapshot.save(update_fields=["existing_user"])
                GroupMember.objects.create(group=group, student=student, is_leader=(student.id == request.created_by_id), changed_by=actor)
            supervisor_snapshot = revision.supervisor
            supervisor = supervisor_snapshot.existing_user
            if supervisor_snapshot.supervisor_type == RequestSupervisor.Type.NEW:
                supervisor = _create_pending_account(User.Role.SUPERVISOR, supervisor_snapshot.username_proposed, supervisor_snapshot.phone_proposed, supervisor_snapshot.full_name, revision.department)
            ProjectSupervisor.objects.create(project=project, supervisor=supervisor)
            decision_record = RequestDecision.objects.create(request=request, revision=revision, actor=actor, decision=decision, note=note.strip())
            request.status = GroupRequest.Status.APPROVED
            request.closed_at = now
            request.version += 1
            request.save(update_fields=["status", "closed_at", "version", "updated_at"])
            audit(actor, "group_request.approved", "group_request", request.id, request, {"revision": revision.revision_number, "decision_id": str(decision_record.id), "project_id": str(project.id)})
            notify_users(actor, [request.created_by, *[member.student for member in group.members.select_related("student")], supervisor], "group_request.approved", "تم اعتماد طلب المجموعة", revision.project_title, f"/?page=project&project={project.id}")
            return request
        except IntegrityError as exc:
            raise Conflict("تعذر اعتماد الطلب بسبب تعارض بيانات. لم تُفعّل المجموعة جزئيًا.") from exc
    decision_record = RequestDecision.objects.create(request=request, revision=revision, actor=actor, decision=decision, note=note.strip())
    request.status = GroupRequest.Status.RETURNED if decision == RequestDecision.Decision.RETURNED else GroupRequest.Status.REJECTED
    request.closed_at = now if decision == RequestDecision.Decision.REJECTED else None
    request.version += 1
    request.save(update_fields=["status", "closed_at", "version", "updated_at"])
    action = "group_request.returned" if decision == RequestDecision.Decision.RETURNED else "group_request.rejected"
    audit(actor, action, "group_request", request.id, request, {"revision": revision.revision_number, "decision_id": str(decision_record.id)})
    notify_users(actor, [request.created_by], f"group_request.{request.status}", "تحديث على طلب المجموعة", note.strip(), "/?page=requests")
    return request

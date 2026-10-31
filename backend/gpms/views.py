import os
import re
import unicodedata
from html import escape
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token

from .models import AuditLog, DefenseCommittee, DefenseCommitteeCriterion, DefenseCommitteeMember, DefenseEvaluation, DefenseEvaluationScore, DefenseRubricCriterion, Department, Deliverable, DiscussionReadinessRequest, GroupMember, GroupRequest, Notification, OneTimeToken, PostDefenseFinalSubmission, PostDefenseRevision, Project, ProjectAppointment, ProjectCommittee, ProjectCommitteeMember, ProjectGroup, ProjectIdeaCommitteeReview, ProjectIdeaRevision, ProjectNote, ProjectPlan, ProjectStage, ProjectStageReview, ProjectSupervisor, ProjectTask, RequestDecision, RequestRevision, RequestSupervisor, User
from .permissions import IsAuthenticatedActive, can_view_group, can_view_project, request_queryset_for
from .serializers import DefenseCommitteeSerializer, DefenseRubricCriterionSerializer, DepartmentSerializer, DeliverableReadSerializer, DiscussionReadinessSerializer, GroupDetailReadSerializer, GroupMemberReadSerializer, GroupRequestReadSerializer, NotificationSerializer, ProjectAppointmentSerializer, ProjectCommitteeSerializer, ProjectIdeaRevisionSerializer, ProjectNoteReadSerializer, ProjectPlanSerializer, ProjectReadSerializer, ProjectRepositorySerializer, ProjectStageSerializer, ProjectTaskReadSerializer, RevisionInputSerializer
from .services import Conflict, audit, create_request, decide_request, notify_users, submit_request, update_request
from .tokens import consume_token, get_valid_token, issue_token
from .reporting import make_xlsx

DUMMY_PASSWORD_HASH = make_password("invalid-dummy-password-for-timing")


class LoginThrottle(SimpleRateThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        return self.get_rate_limit_key(request)

    def get_rate_limit_key(self, request):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordResetThrottle(SimpleRateThrottle):
    scope = "password_reset"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        identifier = str(request.data.get("identifier", "")).strip()
        password = str(request.data.get("password", ""))
        user = User.objects.filter(username_normalized=identifier.casefold()).first() if identifier else None
        encoded = user.password if user else DUMMY_PASSWORD_HASH
        password_ok = check_password(password, encoded)
        if not user:
            return Response({"detail": "بيانات الدخول غير صحيحة."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            now = timezone.now()
            if user.locked_until and user.locked_until > now:
                return Response({"detail": "بيانات الدخول غير صحيحة."}, status=status.HTTP_400_BAD_REQUEST)
            if not password_ok or not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
                if user.account_status == User.AccountStatus.ACTIVE and user.is_active:
                    user.failed_login_attempts += 1
                    update_fields = ["failed_login_attempts", "updated_at"]
                    if user.failed_login_attempts >= 5:
                        user.locked_until = now + timedelta(minutes=5)
                        update_fields.append("locked_until")
                    user.save(update_fields=update_fields)
                    audit(user, "auth.login_failed", "user", user.id, metadata={"failed_attempts": user.failed_login_attempts, "locked": bool(user.locked_until and user.locked_until > now)})
                return Response({"detail": "بيانات الدخول غير صحيحة."}, status=status.HTTP_400_BAD_REQUEST)
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_activity_at = now
            user.save(update_fields=["failed_login_attempts", "locked_until", "last_activity_at", "updated_at"])
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
            audit(user, "auth.login", "user", user.id)
        return Response({"token": token.key, "user": user_payload(user)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def post(self, request):
        audit(request.user, "auth.logout", "user", request.user.id)
        if request.auth is not None:
            request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        return Response({"user": user_payload(request.user)})


def user_payload(user):
    display_name = user.username
    if user.role == User.Role.STUDENT:
        profile = getattr(user, "student_profile", None)
    elif user.role == User.Role.SUPERVISOR:
        profile = getattr(user, "supervisor_profile", None)
    else:
        profile = None
    if profile and profile.full_name:
        display_name = profile.full_name
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": display_name,
        "role": user.role,
        "role_label": user.get_role_display(),
        "account_status": user.account_status,
        "phone": user.phone,
        "department": DepartmentSerializer(user.department).data if user.department_id else None,
    }


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        # Password recovery is handled by an authorized department administrator;
        # the application does not send verification codes or reset instructions.
        return Response({"detail": "لإعادة تعيين كلمة المرور، يرجى مراجعة رئيس القسم."})


@method_decorator(transaction.atomic, name="dispatch")
class OneTimePasswordView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, purpose):
        if purpose not in {OneTimeToken.Purpose.ACTIVATE, OneTimeToken.Purpose.RESET_PASSWORD}:
            raise NotFound()
        raw = str(request.data.get("token", ""))
        password = str(request.data.get("password", ""))
        if not raw or not password:
            raise ValidationError("الرمز وكلمة المرور مطلوبان.")
        token = get_valid_token(raw, purpose)
        if token is None:
            raise Conflict("الرمز غير صالح أو منتهي الصلاحية.")
        user = token.user
        if purpose == OneTimeToken.Purpose.ACTIVATE and user.account_status != User.AccountStatus.ACTIVATION_PENDING:
            raise Conflict("لا يمكن تفعيل هذا الحساب بهذه الطريقة.")
        if purpose == OneTimeToken.Purpose.RESET_PASSWORD and user.account_status != User.AccountStatus.ACTIVE:
            raise Conflict("لا يمكن إعادة تعيين كلمة مرور هذا الحساب.")
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc
        consume_token(token)
        user.set_password(password)
        if purpose == OneTimeToken.Purpose.ACTIVATE:
            user.account_status = User.AccountStatus.ACTIVE
            user.is_active = True
            user.save(update_fields=["password", "account_status", "is_active", "updated_at"])
        else:
            user.save(update_fields=["password", "updated_at"])
        Token.objects.filter(user=user).delete()
        audit(user, "account.activated" if purpose == OneTimeToken.Purpose.ACTIVATE else "auth.password_reset", "user", user.id)
        return Response({"detail": "تم تحديث بيانات الحساب."})


class DepartmentListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR, User.Role.STUDENT}:
            raise PermissionDenied("لا تملك صلاحية عرض الأقسام.")
        qs = Department.objects.filter(is_active=True)
        if request.user.role in {User.Role.DEPARTMENT_CHAIR, User.Role.STUDENT}:
            qs = qs.filter(id=request.user.department_id)
        return Response(DepartmentSerializer(qs, many=True).data)


class SupervisorListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR, User.Role.STUDENT}:
            raise PermissionDenied("لا تملك صلاحية عرض المشرفين.")
        qs = User.objects.filter(role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE).select_related("department", "supervisor_profile").order_by("supervisor_profile__full_name")
        if request.user.role in {User.Role.DEPARTMENT_CHAIR, User.Role.STUDENT}:
            qs = qs.filter(department_id=request.user.department_id)
        return Response([{
            "id": str(user.id),
            "full_name": getattr(user, "supervisor_profile", None).full_name if hasattr(user, "supervisor_profile") else user.username,
            "username": user.username,
            "department": user.department.name if user.department_id else None,
        } for user in qs[:200]])


class UserListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
            raise PermissionDenied("عرض دليل المستخدمين متاح لعميد الكلية ورئيس القسم.")
        users = User.objects.select_related("department", "student_profile", "supervisor_profile")
        if request.user.role == User.Role.DEPARTMENT_CHAIR:
            if not request.user.department_id:
                return Response([])
            users = users.filter(department_id=request.user.department_id)
        users = users.order_by("role", "username")[:500]
        return Response([{
            **{key: value for key, value in user_payload(user).items() if key != "phone"},
            "role_label": user.get_role_display(),
        } for user in users])


@method_decorator(transaction.atomic, name="dispatch")
class StudentActivationView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def post(self, request, user_id):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("تفعيل حسابات الطلاب متاح لعميد الكلية.")
        user = get_object_or_404(User.objects.select_for_update(), id=user_id, role=User.Role.STUDENT)
        if user.account_status != User.AccountStatus.ACTIVATION_PENDING:
            raise ValidationError({"detail": "هذا الحساب ليس بانتظار التفعيل."})
        user.one_time_tokens.filter(purpose=OneTimeToken.Purpose.ACTIVATE, used_at__isnull=True).update(used_at=timezone.now())
        raw_token = issue_token(user, OneTimeToken.Purpose.ACTIVATE)
        audit(request.user, "account.activation_issued", "user", user.id)
        return Response({"activation_token": raw_token, "username": user.username, "expires_in_seconds": 3600})


def input_data(request):
    serializer = RevisionInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class GroupRequestListCreateView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR, User.Role.STUDENT}:
            raise PermissionDenied("لا تملك صلاحية عرض طلبات المجموعات.")
        qs = request_queryset_for(request.user)
        chosen_status = request.query_params.get("status")
        if chosen_status:
            if chosen_status not in GroupRequest.Status.values:
                raise ValidationError({"status": "حالة الطلب غير صالحة."})
            qs = qs.filter(status=chosen_status)
        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(current_revision__project_title__icontains=search) | qs.filter(current_revision__group_code_proposed__icontains=search)
        return Response(GroupRequestReadSerializer(qs.distinct()[:100], many=True).data)

    def post(self, request):
        data = input_data(request)
        obj = create_request(request.user, data)
        obj = request_queryset_for(request.user).get(id=obj.id)
        return Response(GroupRequestReadSerializer(obj).data, status=status.HTTP_201_CREATED)


class GroupRequestDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_queryset(self, user):
        if user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR, User.Role.STUDENT}:
            raise NotFound()
        return request_queryset_for(user)

    def get(self, request, request_id):
        obj = get_object_or_404(self.get_queryset(request.user), id=request_id)
        return Response(GroupRequestReadSerializer(obj).data)

    def patch(self, request, request_id):
        serializer = RevisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = update_request(request.user, request_id, serializer.validated_data)
        obj = request_queryset_for(request.user).get(id=obj.id)
        return Response(GroupRequestReadSerializer(obj).data)


class GroupRequestSubmitView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def post(self, request, request_id):
        expected = request.data.get("version") or request.headers.get("If-Match")
        obj = submit_request(request.user, request_id, expected)
        obj = request_queryset_for(request.user).get(id=obj.id)
        return Response(GroupRequestReadSerializer(obj).data)


class GroupRequestDecisionView(APIView):
    permission_classes = [IsAuthenticatedActive]
    actions = {"approve": RequestDecision.Decision.APPROVED, "return": RequestDecision.Decision.RETURNED, "reject": RequestDecision.Decision.REJECTED}

    def post(self, request, request_id, action):
        decision = self.actions.get(action)
        if not decision:
            raise NotFound()
        obj = decide_request(request.user, request_id, decision, str(request.data.get("note", "")))
        obj = GroupRequest.objects.select_related("created_by", "current_revision", "current_revision__department").prefetch_related("decisions").get(id=obj.id)
        return Response(GroupRequestReadSerializer(obj).data)


def project_queryset_for(user):
    qs = Project.objects.select_related("group", "group__department").prefetch_related("supervisor_assignments", "group__members__student__student_profile")
    if user.role == User.Role.DEAN:
        return qs
    if user.role == User.Role.DEPARTMENT_CHAIR and user.department_id:
        return qs.filter(group__department_id=user.department_id)
    if user.role == User.Role.SUPERVISOR:
        return qs.filter(supervisor_assignments__supervisor=user, supervisor_assignments__ended_at__isnull=True).distinct()
    if user.role == User.Role.STUDENT:
        return qs.filter(group__members__student=user, group__members__left_at__isnull=True).distinct()
    return qs.none()


class ProjectListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        qs = project_queryset_for(request.user).filter(group__status=ProjectGroup.Status.ACTIVE)
        return Response(ProjectReadSerializer(qs.order_by("-created_at")[:100], many=True).data)


def group_queryset_for(user):
    qs = ProjectGroup.objects.select_related("department", "project").prefetch_related(
        "members__student__student_profile",
        "project__supervisor_assignments__supervisor__supervisor_profile",
    )
    if user.role == User.Role.DEAN:
        return qs
    if user.role == User.Role.DEPARTMENT_CHAIR and user.department_id:
        return qs.filter(department_id=user.department_id)
    if user.role == User.Role.SUPERVISOR:
        return qs.filter(project__supervisor_assignments__supervisor=user, project__supervisor_assignments__ended_at__isnull=True).distinct()
    if user.role == User.Role.STUDENT:
        return qs.filter(members__student=user, members__left_at__isnull=True).distinct()
    return qs.none()


class GroupListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        groups = group_queryset_for(request.user).filter(status=ProjectGroup.Status.ACTIVE)
        return Response(GroupDetailReadSerializer(groups.order_by("group_code")[:100], many=True).data)


class GroupDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, group_id):
        group = get_object_or_404(group_queryset_for(request.user), id=group_id)
        if not can_view_group(request.user, group):
            raise NotFound()
        return Response(GroupDetailReadSerializer(group).data)


class GroupMembersView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_group(self, request, group_id, lock=False):
        queryset = ProjectGroup.objects.select_related("department")
        if lock:
            queryset = queryset.select_for_update()
        group = get_object_or_404(queryset, id=group_id)
        if not can_view_group(request.user, group):
            raise NotFound()
        return group

    def get(self, request, group_id):
        group = self.get_group(request, group_id)
        members = group.members.select_related("student__student_profile", "changed_by").order_by("joined_at")
        data = {"members": GroupMemberReadSerializer(members, many=True).data, "eligible_students": []}
        if request.user.role == User.Role.DEPARTMENT_CHAIR and request.user.department_id == group.department_id:
            active_member_ids = GroupMember.objects.filter(left_at__isnull=True).values("student_id")
            eligible = User.objects.filter(role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE, department_id=group.department_id).exclude(id__in=active_member_ids).select_related("student_profile").order_by("student_profile__full_name", "username")
            data["eligible_students"] = [{"id": str(user.id), "name": user.student_profile.full_name if hasattr(user, "student_profile") else user.username, "username": user.username} for user in eligible]
        return Response(data)

    @transaction.atomic
    def post(self, request, group_id):
        if request.user.role != User.Role.DEPARTMENT_CHAIR:
            raise PermissionDenied("إضافة أعضاء المجموعة متاحة لرئيس القسم فقط.")
        group = self.get_group(request, group_id, lock=True)
        if group.department_id != request.user.department_id:
            raise NotFound()
        if group.status != ProjectGroup.Status.ACTIVE:
            raise Conflict("لا يمكن تعديل أعضاء مجموعة مكتملة.")
        student = get_object_or_404(User.objects.select_for_update(), id=request.data.get("student_id"), role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE, department_id=group.department_id)
        if GroupMember.objects.filter(student=student, left_at__isnull=True).exists():
            raise Conflict("الطالب عضو حاليًا في مجموعة نشطة.")
        membership = GroupMember.objects.create(group=group, student=student, changed_by=request.user)
        audit(request.user, "group_member.added", "group_member", membership.id, metadata={"group_id": str(group.id), "student_id": str(student.id)})
        notify_users(request.user, [student], "group_member.added", "أُضيفت إلى مجموعة مشروع تخرج", group.group_code, "/?page=groups")
        return Response(GroupMemberReadSerializer(membership).data, status=status.HTTP_201_CREATED)


class GroupMemberDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def delete(self, request, group_id, student_id):
        if request.user.role != User.Role.DEPARTMENT_CHAIR:
            raise PermissionDenied("إنهاء عضوية الطالب متاح لرئيس القسم فقط.")
        group = get_object_or_404(ProjectGroup.objects.select_for_update().select_related("department"), id=group_id, department_id=request.user.department_id, status=ProjectGroup.Status.ACTIVE)
        member = get_object_or_404(GroupMember.objects.select_for_update(), group=group, student_id=student_id, left_at__isnull=True)
        reason = str(request.data.get("reason", "")).strip()
        if not reason or len(reason) > 2000:
            raise ValidationError({"reason": "سبب إنهاء العضوية مطلوب وبحد أقصى 2000 حرف."})
        active = group.members.filter(left_at__isnull=True)
        if active.count() <= 1:
            raise Conflict("لا يمكن إنهاء عضوية آخر طالب في المجموعة.")
        new_leader_id = request.data.get("new_leader_id")
        if member.is_leader:
            if not new_leader_id:
                raise ValidationError({"new_leader_id": "اختر قائدًا بديلًا قبل إنهاء عضوية القائد الحالي."})
            new_leader = get_object_or_404(active.exclude(id=member.id), student_id=new_leader_id)
            active.update(is_leader=False)
            new_leader.is_leader = True
            new_leader.save(update_fields=["is_leader"])
        elif new_leader_id:
            raise ValidationError({"new_leader_id": "لا حاجة لتغيير القائد عند إنهاء عضوية عضو غير قائد."})
        member.left_at = timezone.now()
        member.left_reason = reason
        member.is_leader = False
        member.changed_by = request.user
        member.save(update_fields=["left_at", "left_reason", "is_leader", "changed_by"])
        audit(request.user, "group_member.removed", "group_member", member.id, metadata={"group_id": str(group.id), "student_id": str(member.student_id), "reason": reason, "new_leader_id": str(new_leader_id) if new_leader_id else None})
        project = getattr(group, "project", None)
        if project:
            notify_users(request.user, [member.student], "group_member.removed", "انتهت عضويتك في مجموعة المشروع", reason, f"/?page=groups")
        return Response(GroupMemberReadSerializer(member).data)


class GroupLeaderView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def patch(self, request, group_id):
        if request.user.role != User.Role.DEPARTMENT_CHAIR:
            raise PermissionDenied("تغيير قائد المجموعة متاح لرئيس القسم فقط.")
        group = get_object_or_404(ProjectGroup.objects.select_for_update(), id=group_id, department_id=request.user.department_id, status=ProjectGroup.Status.ACTIVE)
        new_leader = get_object_or_404(GroupMember.objects.select_for_update(), group=group, student_id=request.data.get("student_id"), left_at__isnull=True)
        group.members.filter(left_at__isnull=True).update(is_leader=False)
        new_leader.is_leader = True
        new_leader.changed_by = request.user
        new_leader.save(update_fields=["is_leader", "changed_by"])
        audit(request.user, "group_leader.changed", "group_member", new_leader.id, metadata={"group_id": str(group.id), "student_id": str(new_leader.student_id)})
        return Response(GroupMemberReadSerializer(new_leader).data)


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return Response(ProjectReadSerializer(project).data)


class ProjectSupervisorAssignmentView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, project_id):
        if request.user.role != User.Role.DEPARTMENT_CHAIR:
            raise PermissionDenied("إعادة إسناد المشرف متاحة لرئيس القسم فقط.")
        project = get_object_or_404(Project.objects.select_for_update().select_related("group__department"), id=project_id, group__department_id=request.user.department_id, status=Project.Status.ACTIVE)
        supervisor = get_object_or_404(User.objects.select_for_update(), id=request.data.get("supervisor_id"), role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE, department_id=project.group.department_id)
        current = ProjectSupervisor.objects.select_for_update().filter(project=project, ended_at__isnull=True).first()
        if current and current.supervisor_id == supervisor.id:
            raise Conflict("هذا المشرف مسند للمشروع بالفعل.")
        reason = str(request.data.get("reason", "")).strip()
        if current and not reason:
            raise ValidationError({"reason": "سبب إعادة الإسناد مطلوب."})
        if current:
            current.ended_at = timezone.now()
            current.ended_by = request.user
            current.end_type = ProjectSupervisor.EndType.REASSIGNED
            current.end_reason = reason[:2000]
            current.save(update_fields=["ended_at", "ended_by", "end_type", "end_reason"])
        assignment = ProjectSupervisor.objects.create(project=project, supervisor=supervisor)
        audit(request.user, "project_supervisor.assigned", "project_supervisor", assignment.id, metadata={"project_id": str(project.id), "new_supervisor_id": str(supervisor.id), "previous_supervisor_id": str(current.supervisor_id) if current else None, "reason": reason})
        recipients = list(User.objects.filter(group_memberships__group=project.group, group_memberships__left_at__isnull=True, account_status=User.AccountStatus.ACTIVE))
        notify_users(request.user, [*recipients, supervisor], "project_supervisor.assigned", "تم تحديث المشرف الأكاديمي للمشروع", project.title, f"/?page=project&project={project.id}")
        return Response(ProjectReadSerializer(project).data)


class ProjectSupervisorDeclineView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, project_id):
        project = get_object_or_404(Project.objects.select_for_update().select_related("group__department"), id=project_id)
        if request.user.role != User.Role.SUPERVISOR:
            raise PermissionDenied("الاعتذار عن الإشراف متاح للمشرف المسند فقط.")
        assignment = get_object_or_404(ProjectSupervisor.objects.select_for_update(), project=project, supervisor=request.user, ended_at__isnull=True)
        reason = str(request.data.get("reason", "")).strip()
        if not reason or len(reason) > 2000:
            raise ValidationError({"reason": "سبب الاعتذار مطلوب وبحد أقصى 2000 حرف."})
        assignment.ended_at = timezone.now()
        assignment.ended_by = request.user
        assignment.end_type = ProjectSupervisor.EndType.DECLINED
        assignment.end_reason = reason
        assignment.save(update_fields=["ended_at", "ended_by", "end_type", "end_reason"])
        audit(request.user, "project_supervisor.declined", "project_supervisor", assignment.id, metadata={"project_id": str(project.id), "reason": reason})
        chairs = User.objects.filter(role=User.Role.DEPARTMENT_CHAIR, department_id=project.group.department_id, account_status=User.AccountStatus.ACTIVE)
        notify_users(request.user, chairs, "project_supervisor.declined", "اعتذر المشرف عن مشروع ويحتاج إعادة إسناد", f"{project.title}: {reason}", f"/?page=project&project={project.id}")
        return Response(ProjectReadSerializer(project).data)


class ProjectRepositoryView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def patch(self, request, project_id):
        if request.user.role != User.Role.STUDENT:
            raise PermissionDenied("تعديل رابط مستودع GitHub متاح لأعضاء المشروع من حساب الطالب.")
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        serializer = ProjectRepositorySerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit(request.user, "project.repository_updated", "project", project.id)
        notify_users(request.user, User.objects.filter(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True), "project.repository_updated", "تحديث رابط مستودع المشروع", project.title, f"/?page=project&project={project.id}")
        return Response(ProjectReadSerializer(project).data)


class ProjectPlansView(APIView):
    permission_classes = [IsAuthenticatedActive]
    fields = ("title", "objectives", "scope", "methodology", "tools", "task_assignments", "timeline", "risks", "expected_outputs")

    def get_project(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return project

    def get(self, request, project_id):
        project = self.get_project(request, project_id)
        return Response(ProjectPlanSerializer(project.plans.select_related("submitted_by", "reviewed_by"), many=True).data)

    @transaction.atomic
    def post(self, request, project_id):
        project = self.get_project(request, project_id)
        if request.user.role != User.Role.STUDENT or not project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists():
            raise PermissionDenied("قائد مجموعة المشروع وحده يستطيع تقديم الخطة.")
        if project.idea_revisions.order_by("-version").values_list("status", flat=True).first() != ProjectIdeaRevision.Status.APPROVED:
            raise Conflict("يجب اعتماد فكرة المشروع من رئيس القسم قبل تقديم الخطة.")
        latest = project.plans.order_by("-version").first()
        if latest and latest.status == ProjectPlan.Status.SUBMITTED:
            raise Conflict("توجد نسخة من الخطة بانتظار مراجعة المشرف.")
        payload = {field: str(request.data.get(field, "")).strip() for field in self.fields}
        required = ("title", "objectives", "scope", "methodology", "task_assignments", "timeline", "risks", "expected_outputs")
        errors = {field: "هذا الحقل مطلوب." for field in required if not payload[field]}
        if errors:
            raise ValidationError(errors)
        limits = {"title": 240, "objectives": 5000, "scope": 5000, "methodology": 5000, "tools": 3000, "task_assignments": 5000, "timeline": 5000, "risks": 5000, "expected_outputs": 5000}
        errors = {field: f"الحد الأقصى {limit} حرفًا." for field, limit in limits.items() if len(payload[field]) > limit}
        if errors:
            raise ValidationError(errors)
        plan = ProjectPlan.objects.create(project=project, version=(latest.version if latest else 0) + 1, submitted_by=request.user, **payload)
        notify_users(request.user, User.objects.filter(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True), "project_plan.submitted", "خطة مشروع بانتظار المراجعة", f"{project.title} · النسخة {plan.version}", f"/?page=project&project={project.id}")
        audit(request.user, "project_plan.submitted", "project_plan", plan.id, metadata={"project_id": str(project.id), "version": plan.version})
        return Response(ProjectPlanSerializer(plan).data, status=status.HTTP_201_CREATED)


class ProjectPlanReviewView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, plan_id):
        plan = get_object_or_404(ProjectPlan.objects.select_for_update().select_related("project"), id=plan_id)
        project = get_object_or_404(project_queryset_for(request.user), id=plan.project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists():
            raise PermissionDenied("مراجعة الخطة متاحة للمشرف المسند للمشروع فقط.")
        if plan.status != ProjectPlan.Status.SUBMITTED or plan.project.plans.order_by("-version").values_list("id", flat=True).first() != plan.id:
            raise Conflict("هذه النسخة ليست خطة معلقة هي الأحدث للمراجعة.")
        decision = request.data.get("decision")
        note = str(request.data.get("note", "")).strip()
        if decision not in {"approved", "changes_requested"}:
            raise ValidationError({"decision": "القرار يجب أن يكون approved أو changes_requested."})
        if decision == "changes_requested" and not note:
            raise ValidationError({"note": "اكتب ملاحظات التعديلات المطلوبة."})
        plan.status = ProjectPlan.Status(decision)
        plan.review_note = note
        plan.reviewed_by = request.user
        plan.reviewed_at = timezone.now()
        plan.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at"])
        notify_users(request.user, User.objects.filter(group_memberships__group=project.group, group_memberships__left_at__isnull=True), f"project_plan.{decision}", "مراجعة خطة المشروع", note or "اعتمد المشرف الخطة.", f"/?page=project&project={project.id}")
        audit(request.user, f"project_plan.{decision}", "project_plan", plan.id, metadata={"project_id": str(project.id)})
        return Response(ProjectPlanSerializer(plan).data)


class DepartmentProjectCommitteeView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, department_id):
        department = get_object_or_404(Department, id=department_id)
        supervisor_in_department = request.user.role == User.Role.SUPERVISOR and request.user.department_id == department.id
        supervisor_committee_member = request.user.role == User.Role.SUPERVISOR and ProjectCommitteeMember.objects.filter(committee__department=department, supervisor=request.user).exists()
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR} and not supervisor_in_department and not supervisor_committee_member or (request.user.role == User.Role.DEPARTMENT_CHAIR and request.user.department_id != department.id):
            raise PermissionDenied("عرض تشكيل لجنة مشاريع التخرج متاح للعميد ورئيس القسم المعني.")
        committee = ProjectCommittee.objects.filter(department=department).first()
        return Response(ProjectCommitteeSerializer(committee).data if committee else None)

    @transaction.atomic
    def post(self, request, department_id):
        department = get_object_or_404(Department, id=department_id)
        if request.user.role != User.Role.DEPARTMENT_CHAIR or request.user.department_id != department.id:
            raise PermissionDenied("ترشيح أعضاء اللجنة متاح لرئيس القسم المعني فقط.")
        ids = request.data.get("member_ids")
        if not isinstance(ids, list) or not ids or len(ids) != len(set(str(item) for item in ids)):
            raise ValidationError({"member_ids": "أرسل قائمة غير فارغة وفريدة بمعرفات المشرفين."})
        members = list(User.objects.filter(id__in=ids, role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE, department=department))
        if len(members) != len(ids):
            raise ValidationError({"member_ids": "يجب أن يكون كل مرشح مشرفًا نشطًا من القسم نفسه."})
        committee = ProjectCommittee.objects.select_for_update().filter(department=department).first()
        if committee and committee.status == ProjectCommittee.Status.APPROVED:
            raise Conflict("اللجنة الحالية معتمدة ولا يمكن استبدال تشكيلها من هذا المسار.")
        if committee:
            committee.proposed_by = request.user
            committee.save(update_fields=["proposed_by", "updated_at"])
            committee.members.all().delete()
        else:
            committee = ProjectCommittee.objects.create(department=department, proposed_by=request.user)
        ProjectCommitteeMember.objects.bulk_create([ProjectCommitteeMember(committee=committee, supervisor=member) for member in members])
        audit(request.user, "project_committee.proposed", "project_committee", committee.id, metadata={"department_id": str(department.id), "member_count": len(members)})
        notify_users(request.user, User.objects.filter(role=User.Role.DEAN, account_status=User.AccountStatus.ACTIVE), "project_committee.proposed", "تشكيل لجنة بانتظار الاعتماد", department.name, "/?page=committees")
        return Response(ProjectCommitteeSerializer(committee).data, status=status.HTTP_201_CREATED)


class ProjectCommitteeApprovalView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, committee_id):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("اعتماد تشكيل اللجنة متاح للعميد فقط.")
        committee = get_object_or_404(ProjectCommittee.objects.select_for_update().select_related("department"), id=committee_id)
        if committee.status != ProjectCommittee.Status.PENDING_APPROVAL or not committee.members.filter(supervisor__role=User.Role.SUPERVISOR, supervisor__account_status=User.AccountStatus.ACTIVE, supervisor__department=committee.department).exists() or committee.members.exclude(supervisor__role=User.Role.SUPERVISOR, supervisor__account_status=User.AccountStatus.ACTIVE, supervisor__department=committee.department).exists():
            raise Conflict("لا يوجد تشكيل لجنة معلق صالح للاعتماد.")
        committee.status = ProjectCommittee.Status.APPROVED
        committee.approved_by = request.user
        committee.approved_at = timezone.now()
        committee.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        audit(request.user, "project_committee.approved", "project_committee", committee.id)
        notify_users(request.user, [committee.proposed_by, *User.objects.filter(project_committee_memberships__committee=committee)], "project_committee.approved", "تم اعتماد لجنة مشاريع التخرج", committee.department.name, "/?page=committees")
        return Response(ProjectCommitteeSerializer(committee).data)


class ProjectIdeaQueueView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role != User.Role.SUPERVISOR:
            raise PermissionDenied("قائمة مراجعة الأفكار متاحة لأعضاء هيئة التدريس فقط.")
        committee = ProjectCommittee.objects.filter(status=ProjectCommittee.Status.APPROVED, members__supervisor=request.user).first()
        if not committee:
            return Response([])
        ideas = ProjectIdeaRevision.objects.filter(project__group__department=committee.department, status=ProjectIdeaRevision.Status.COMMITTEE_REVIEW).select_related("project__group__department", "submitted_by").prefetch_related("committee_reviews__reviewer__supervisor_profile")
        return Response(ProjectIdeaRevisionSerializer(ideas, many=True).data)


class ProjectIdeasView(APIView):
    permission_classes = [IsAuthenticatedActive]
    fields = ("title", "problem", "objectives", "proposed_solution", "novelty")

    def get_project(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return project

    def get(self, request, project_id):
        project = self.get_project(request, project_id)
        ideas = project.idea_revisions.prefetch_related("committee_reviews__reviewer__supervisor_profile")
        return Response(ProjectIdeaRevisionSerializer(ideas, many=True).data)

    @transaction.atomic
    def post(self, request, project_id):
        project = self.get_project(request, project_id)
        if request.user.role != User.Role.STUDENT or not project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists():
            raise PermissionDenied("قائد مجموعة المشروع وحده يستطيع تقديم الفكرة.")
        committee = ProjectCommittee.objects.filter(department=project.group.department, status=ProjectCommittee.Status.APPROVED).first()
        if not committee:
            raise Conflict("لم يعتمد العميد لجنة مشاريع للقسم بعد؛ لا يمكن إحالة الفكرة للمراجعة.")
        latest = project.idea_revisions.order_by("-version").first()
        if latest and latest.status in {ProjectIdeaRevision.Status.SUPERVISOR_REVIEW, ProjectIdeaRevision.Status.COMMITTEE_REVIEW, ProjectIdeaRevision.Status.CHAIR_REVIEW}:
            raise Conflict("توجد نسخة فكرة قيد المراجعة بالفعل.")
        payload = {field: str(request.data.get(field, "")).strip() for field in self.fields}
        required = self.fields
        errors = {field: "هذا الحقل مطلوب." for field in required if not payload[field]}
        if errors:
            raise ValidationError(errors)
        limits = {"title": 240, "problem": 5000, "objectives": 5000, "proposed_solution": 5000, "novelty": 5000}
        errors = {field: f"الحد الأقصى {limit} حرفًا." for field, limit in limits.items() if len(payload[field]) > limit}
        if errors:
            raise ValidationError(errors)
        idea = ProjectIdeaRevision.objects.create(project=project, version=(latest.version if latest else 0) + 1, submitted_by=request.user, **payload)
        notify_users(request.user, User.objects.filter(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True), "project_idea.submitted", "فكرة مشروع بانتظار المراجعة الفنية", idea.title, f"/?page=project&project={project.id}")
        audit(request.user, "project_idea.submitted", "project_idea", idea.id, metadata={"project_id": str(project.id), "version": idea.version})
        return Response(ProjectIdeaRevisionSerializer(idea).data, status=status.HTTP_201_CREATED)


class ProjectIdeaSimilarityView(APIView):
    permission_classes = [IsAuthenticatedActive]
    fields = ("title", "problem", "objectives", "proposed_solution", "novelty")
    stop_words = {"من", "في", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "التي", "الذي", "هو", "هي", "و", "أو", "ثم", "كما", "منها", "نظام", "تطبيق", "مشروع"}

    @staticmethod
    def tokens(value):
        value = unicodedata.normalize("NFKC", value).lower()
        value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
        value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))
        return {token for token in re.findall(r"[a-z0-9\u0621-\u064A]+", value) if len(token) > 1 and token not in ProjectIdeaSimilarityView.stop_words}

    @classmethod
    def jaccard(cls, left, right):
        a, b = cls.tokens(left), cls.tokens(right)
        return len(a & b) / len(a | b) if a and b else 0.0

    def post(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if request.user.role != User.Role.STUDENT or not project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists():
            raise PermissionDenied("فحص تشابه الفكرة متاح لقائد المجموعة فقط.")
        payload = {field: str(request.data.get(field, "")).strip() for field in self.fields}
        errors = {field: "أكمل هذا الحقل قبل فحص التشابه." for field in self.fields if not payload[field]}
        if errors:
            raise ValidationError(errors)
        errors = {field: "النص أطول من الحد المسموح." for field, limit in {"title": 240, "problem": 5000, "objectives": 5000, "proposed_solution": 5000, "novelty": 5000}.items() if len(payload[field]) > limit}
        if errors:
            raise ValidationError(errors)
        weights = {"title": 0.10, "problem": 0.30, "objectives": 0.20, "proposed_solution": 0.25, "novelty": 0.15}
        candidates = ProjectIdeaRevision.objects.filter(status=ProjectIdeaRevision.Status.APPROVED, project__status=Project.Status.COMPLETED).exclude(project=project).select_related("project__group__department").order_by("-created_at")
        results = []
        for prior in candidates.iterator(chunk_size=500):
            field_scores = {field: self.jaccard(payload[field], getattr(prior, field)) for field in weights}
            title_ratio = SequenceMatcher(None, " ".join(sorted(self.tokens(payload["title"]))), " ".join(sorted(self.tokens(prior.title)))).ratio()
            field_scores["title"] = max(field_scores["title"], title_ratio)
            score = round(sum(field_scores[field] * weight for field, weight in weights.items()) * 100)
            if score:
                results.append({"idea_id": str(prior.id), "project_title": prior.project.title, "department": prior.project.group.department.name, "score": score, "similar_fields": [field for field, value in field_scores.items() if value >= 0.2], "title": prior.title})
        results.sort(key=lambda row: (-row["score"], row["project_title"]))
        return Response({"method": "lexical_overlap", "notice": "هذه مقارنة لفظية أولية للمساعدة في المراجعة؛ لا تثبت الانتحال ولا تسبب رفضًا تلقائيًا.", "matches": results[:10]})


class ProjectIdeaReviewView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_idea(self, request, idea_id, stage):
        idea = get_object_or_404(ProjectIdeaRevision.objects.select_related("project__group__department"), id=idea_id)
        committee_reviewer = stage == "committee-review" and ProjectCommitteeMember.objects.filter(committee__department=idea.project.group.department, committee__status=ProjectCommittee.Status.APPROVED, supervisor=request.user).exists()
        if not committee_reviewer:
            get_object_or_404(project_queryset_for(request.user), id=idea.project_id)
            if not can_view_project(request.user, idea.project):
                raise NotFound()
        if idea.project.idea_revisions.order_by("-version").values_list("id", flat=True).first() != idea.id:
            raise Conflict("لا يمكن اتخاذ قرار على نسخة قديمة من الفكرة.")
        return idea

    @transaction.atomic
    def post(self, request, idea_id, stage):
        idea = self.get_idea(request, idea_id, stage)
        note = str(request.data.get("note", "")).strip()
        if stage == "supervisor-review":
            if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project=idea.project, supervisor=request.user, ended_at__isnull=True).exists():
                raise PermissionDenied("المراجعة الفنية متاحة للمشرف المسند فقط.")
            if idea.status != ProjectIdeaRevision.Status.SUPERVISOR_REVIEW or request.data.get("decision") not in {"forward", "changes_requested"}:
                raise Conflict("الفكرة ليست بانتظار المراجعة الفنية أو القرار غير صالح.")
            decision = request.data["decision"]
            if decision == "changes_requested" and not note:
                raise ValidationError({"note": "ملاحظات الإعادة مطلوبة."})
            idea.status = ProjectIdeaRevision.Status.COMMITTEE_REVIEW if decision == "forward" else ProjectIdeaRevision.Status.CHANGES_REQUESTED
            idea.supervisor_note = note
            idea.supervisor_reviewed_at = timezone.now()
            idea.save(update_fields=["status", "supervisor_note", "supervisor_reviewed_at"])
            if decision == "forward":
                committee = ProjectCommittee.objects.get(department=idea.project.group.department, status=ProjectCommittee.Status.APPROVED)
                notify_users(request.user, User.objects.filter(project_committee_memberships__committee=committee), "project_idea.committee_review", "فكرة مشروع بانتظار رأي اللجنة", idea.title, "/?page=committees")
            else:
                notify_users(request.user, User.objects.filter(group_memberships__group=idea.project.group, group_memberships__left_at__isnull=True), "project_idea.changes_requested", "أعيدت فكرة المشروع للتعديل", note, f"/?page=project&project={idea.project_id}")
        elif stage == "committee-review":
            committee_member = ProjectCommitteeMember.objects.filter(committee__department=idea.project.group.department, committee__status=ProjectCommittee.Status.APPROVED, supervisor=request.user).first()
            if request.user.role != User.Role.SUPERVISOR or not committee_member:
                raise PermissionDenied("توصية الفكرة متاحة للأعضاء المعتمدين في اللجنة فقط.")
            if idea.status != ProjectIdeaRevision.Status.COMMITTEE_REVIEW:
                raise Conflict("الفكرة ليست بانتظار مراجعة اللجنة.")
            recommendation = request.data.get("recommendation")
            valid = {choice for choice, _ in ProjectIdeaCommitteeReview.Recommendation.choices}
            if recommendation not in valid:
                raise ValidationError({"recommendation": "حدد توصية صالحة."})
            if recommendation != ProjectIdeaCommitteeReview.Recommendation.RECOMMEND and not note:
                raise ValidationError({"note": "الملاحظات مطلوبة عند طلب تعديل الفكرة أو عدم التوصية بها."})
            review, _ = ProjectIdeaCommitteeReview.objects.update_or_create(idea=idea, reviewer=request.user, defaults={"recommendation": recommendation, "note": note})
            member_count = committee_member.committee.members.count()
            review_count = idea.committee_reviews.filter(reviewer__in=committee_member.committee.members.values("supervisor_id")).count()
            if review_count == member_count:
                idea.status = ProjectIdeaRevision.Status.CHAIR_REVIEW
                idea.save(update_fields=["status"])
                chairs = User.objects.filter(role=User.Role.DEPARTMENT_CHAIR, department=idea.project.group.department, account_status=User.AccountStatus.ACTIVE)
                notify_users(request.user, chairs, "project_idea.chair_review", "فكرة جاهزة لقرار رئيس القسم", idea.title, f"/?page=project&project={idea.project_id}")
        elif stage == "chair-review":
            if request.user.role != User.Role.DEPARTMENT_CHAIR or request.user.department_id != idea.project.group.department_id:
                raise PermissionDenied("القرار النهائي للفكرة متاح لرئيس القسم المعني فقط.")
            if idea.status != ProjectIdeaRevision.Status.CHAIR_REVIEW:
                raise Conflict("الفكرة لم تستكمل مراجعة المشرف واللجنة بعد.")
            decision = request.data.get("decision")
            if decision not in {"approved", "changes_requested", "rejected"}:
                raise ValidationError({"decision": "القرار غير صالح."})
            if decision != "approved" and not note:
                raise ValidationError({"note": "اكتب سبب الإعادة أو الرفض."})
            if decision == "approved" and idea.committee_reviews.exclude(recommendation=ProjectIdeaCommitteeReview.Recommendation.RECOMMEND).exists() and not note:
                raise ValidationError({"note": "اكتب مبرر القرار عند اعتماد الفكرة خلافًا لتوصية أحد أعضاء اللجنة."})
            idea.status = decision
            idea.chair_note = note
            idea.chair_reviewed_at = timezone.now()
            idea.save(update_fields=["status", "chair_note", "chair_reviewed_at"])
            if decision == "approved":
                Project.objects.filter(id=idea.project_id).update(title=idea.title, description=idea.problem)
            notify_users(request.user, User.objects.filter(group_memberships__group=idea.project.group, group_memberships__left_at__isnull=True), f"project_idea.{decision}", "قرار رئيس القسم بشأن الفكرة", note or "تم اعتماد فكرة المشروع.", f"/?page=project&project={idea.project_id}")
        else:
            raise NotFound()
        audit(request.user, f"project_idea.{stage}", "project_idea", idea.id, metadata={"status": idea.status})
        idea = ProjectIdeaRevision.objects.prefetch_related("committee_reviews__reviewer__supervisor_profile").get(id=idea.id)
        return Response(ProjectIdeaRevisionSerializer(idea).data)


class DiscussionReadinessView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_project(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return project

    def get(self, request, project_id):
        project = self.get_project(request, project_id)
        records = project.discussion_readiness_requests.select_related("final_deliverable", "report_deliverable", "submitted_by")
        return Response(DiscussionReadinessSerializer(records, many=True).data)

    @transaction.atomic
    def post(self, request, project_id):
        project = self.get_project(request, project_id)
        if request.user.role != User.Role.STUDENT or not project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists():
            raise PermissionDenied("قائد المجموعة وحده يستطيع تقديم طلب جاهزية المناقشة.")
        if project.idea_revisions.order_by("-version").values_list("status", flat=True).first() != ProjectIdeaRevision.Status.APPROVED:
            raise Conflict("يجب اعتماد فكرة المشروع أولًا.")
        if project.plans.order_by("-version").values_list("status", flat=True).first() != ProjectPlan.Status.APPROVED:
            raise Conflict("يجب اعتماد خطة المشروع أولًا.")
        if project.stages.filter(is_required=True).exclude(status=ProjectStage.Status.APPROVED).exists():
            raise Conflict("يجب اعتماد كل المراحل الإلزامية قبل طلب المناقشة.")
        latest = project.discussion_readiness_requests.order_by("-version").first()
        if latest and latest.status in {DiscussionReadinessRequest.Status.SUPERVISOR_REVIEW, DiscussionReadinessRequest.Status.CHAIR_REVIEW, DiscussionReadinessRequest.Status.REFERRED}:
            raise Conflict("يوجد طلب جاهزية مفتوح أو محال للمناقشة بالفعل.")
        final_id = request.data.get("final_deliverable")
        report_id = request.data.get("report_deliverable")
        if not final_id or not report_id or str(final_id) == str(report_id):
            raise ValidationError({"deliverables": "اختر ملف النسخة النهائية وملف التقرير، ويجب أن يكونا ملفين مختلفين."})
        final_file = get_object_or_404(Deliverable, id=final_id, project=project)
        report_file = get_object_or_404(Deliverable, id=report_id, project=project)
        record = DiscussionReadinessRequest.objects.create(project=project, version=(latest.version if latest else 0) + 1, final_deliverable=final_file, report_deliverable=report_file, submitted_by=request.user)
        supervisors = User.objects.filter(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True)
        notify_users(request.user, supervisors, "discussion_readiness.submitted", "طلب جاهزية مناقشة بانتظار المشرف", project.title, f"/?page=project&project={project.id}")
        audit(request.user, "discussion_readiness.submitted", "discussion_readiness", record.id, metadata={"project_id": str(project.id), "version": record.version})
        return Response(DiscussionReadinessSerializer(record).data, status=status.HTTP_201_CREATED)


class DiscussionReadinessReviewView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, request_id, stage):
        record = get_object_or_404(DiscussionReadinessRequest.objects.select_for_update().select_related("project__group"), id=request_id)
        project = get_object_or_404(project_queryset_for(request.user), id=record.project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        if project.discussion_readiness_requests.order_by("-version").values_list("id", flat=True).first() != record.id:
            raise Conflict("لا يمكن مراجعة نسخة قديمة من طلب الجاهزية.")
        decision = request.data.get("decision")
        note = str(request.data.get("note", "")).strip()
        if stage == "supervisor-review":
            if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists():
                raise PermissionDenied("مراجعة جاهزية المناقشة متاحة للمشرف المسند فقط.")
            if record.status != DiscussionReadinessRequest.Status.SUPERVISOR_REVIEW or decision not in {"approved", "changes_requested"}:
                raise Conflict("طلب الجاهزية ليس بانتظار المشرف أو القرار غير صالح.")
            if decision == "changes_requested" and not note:
                raise ValidationError({"note": "ملاحظات التعديل مطلوبة."})
            record.status = DiscussionReadinessRequest.Status.CHAIR_REVIEW if decision == "approved" else DiscussionReadinessRequest.Status.CHANGES_REQUESTED
            record.supervisor_note = note
            record.supervisor_reviewed_at = timezone.now()
            record.save(update_fields=["status", "supervisor_note", "supervisor_reviewed_at"])
            if decision == "approved":
                chairs = User.objects.filter(role=User.Role.DEPARTMENT_CHAIR, department=project.group.department, account_status=User.AccountStatus.ACTIVE)
                notify_users(request.user, chairs, "discussion_readiness.chair_review", "طلب جاهزية بانتظار رئيس القسم", project.title, f"/?page=project&project={project.id}")
            else:
                notify_users(request.user, User.objects.filter(group_memberships__group=project.group, group_memberships__left_at__isnull=True), "discussion_readiness.changes_requested", "أعيد طلب الجاهزية للتعديل", note, f"/?page=project&project={project.id}")
        elif stage == "chair-review":
            if request.user.role != User.Role.DEPARTMENT_CHAIR or request.user.department_id != project.group.department_id:
                raise PermissionDenied("قرار الإحالة للمناقشة متاح لرئيس القسم المعني فقط.")
            if record.status != DiscussionReadinessRequest.Status.CHAIR_REVIEW or decision not in {"refer", "changes_requested", "rejected"}:
                raise Conflict("طلب الجاهزية ليس بانتظار رئيس القسم أو القرار غير صالح.")
            if decision != "refer" and not note:
                raise ValidationError({"note": "سبب الإعادة أو الرفض مطلوب."})
            record.status = DiscussionReadinessRequest.Status.REFERRED if decision == "refer" else DiscussionReadinessRequest.Status(decision)
            record.chair_note = note
            record.chair_reviewed_at = timezone.now()
            record.save(update_fields=["status", "chair_note", "chair_reviewed_at"])
            notify_users(request.user, User.objects.filter(group_memberships__group=project.group, group_memberships__left_at__isnull=True), f"discussion_readiness.{decision}", "قرار طلب جاهزية المناقشة", note or "أحيل المشروع لتشكيل لجنة المناقشة.", f"/?page=project&project={project.id}")
        else:
            raise NotFound()
        audit(request.user, f"discussion_readiness.{stage}.{decision}", "discussion_readiness", record.id)
        record = DiscussionReadinessRequest.objects.select_related("final_deliverable", "report_deliverable", "submitted_by").get(id=record.id)
        return Response(DiscussionReadinessSerializer(record).data)


class DefenseCommitteeListCreateView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        user = request.user
        if user.role == User.Role.DEAN:
            committees = DefenseCommittee.objects.all()
            referred = DiscussionReadinessRequest.objects.filter(status=DiscussionReadinessRequest.Status.REFERRED)
        elif user.role == User.Role.DEPARTMENT_CHAIR:
            committees = DefenseCommittee.objects.filter(readiness_request__project__group__department=user.department)
            referred = DiscussionReadinessRequest.objects.filter(status=DiscussionReadinessRequest.Status.REFERRED, project__group__department=user.department)
        elif user.role == User.Role.SUPERVISOR:
            committees = DefenseCommittee.objects.filter(status=DefenseCommittee.Status.APPROVED, members__supervisor=user)
            referred = DiscussionReadinessRequest.objects.none()
        else:
            raise PermissionDenied("إدارة لجان المناقشة متاحة للعميد ورئيس القسم وأعضاء اللجنة.")
        committees = committees.select_related("readiness_request__project__group__department", "readiness_request__final_deliverable", "readiness_request__report_deliverable").prefetch_related("members__supervisor__supervisor_profile").distinct()
        referred = referred.select_related("project__group__department", "final_deliverable", "report_deliverable").order_by("created_at")
        requests_data = [{
            "id": str(record.id), "project_id": str(record.project_id), "project_title": record.project.title,
            "department_id": str(record.project.group.department_id), "department_name": record.project.group.department.name,
            "final_deliverable": str(record.final_deliverable_id), "final_filename": record.final_deliverable.original_filename,
            "report_deliverable": str(record.report_deliverable_id), "report_filename": record.report_deliverable.original_filename,
        } for record in referred if not hasattr(record, "defense_committee") or record.defense_committee.status == DefenseCommittee.Status.PENDING_APPROVAL]
        return Response({"referred_requests": requests_data, "committees": DefenseCommitteeSerializer(committees, many=True).data})

    @transaction.atomic
    def post(self, request):
        if request.user.role != User.Role.DEPARTMENT_CHAIR:
            raise PermissionDenied("ترشيح لجنة المناقشة متاح لرئيس القسم فقط.")
        record = get_object_or_404(DiscussionReadinessRequest.objects.select_for_update().select_related("project__group__department"), id=request.data.get("readiness_request_id"))
        if record.project.group.department_id != request.user.department_id:
            raise NotFound()
        if record.status != DiscussionReadinessRequest.Status.REFERRED:
            raise Conflict("طلب الجاهزية غير محال لتشكيل لجنة المناقشة.")
        ids = request.data.get("member_ids")
        chair_id = request.data.get("chair_id")
        if not isinstance(ids, list) or len(ids) < 2 or len(ids) != len(set(str(item) for item in ids)) or not chair_id or str(chair_id) not in {str(item) for item in ids}:
            raise ValidationError({"member_ids": "اختر عضوين على الأقل وحدد رئيس اللجنة من بينهم."})
        members = list(User.objects.filter(id__in=ids, role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE, department_id=request.user.department_id))
        if len(members) != len(ids):
            raise ValidationError({"member_ids": "يجب أن يكون المرشحون مشرفين نشطين من القسم نفسه."})
        committee = DefenseCommittee.objects.select_for_update().filter(readiness_request=record).first()
        if committee and committee.status == DefenseCommittee.Status.APPROVED:
            raise Conflict("لجنة المناقشة معتمدة ولا يمكن استبدالها من هذا المسار.")
        created = committee is None
        if committee:
            committee.proposed_by = request.user
            committee.save(update_fields=["proposed_by", "updated_at"])
            committee.members.all().delete()
        else:
            committee = DefenseCommittee.objects.create(readiness_request=record, proposed_by=request.user)
        DefenseCommitteeMember.objects.bulk_create([DefenseCommitteeMember(committee=committee, supervisor=member, is_chair=str(member.id) == str(chair_id)) for member in members])
        audit(request.user, "defense_committee.proposed", "defense_committee", committee.id, metadata={"readiness_request_id": str(record.id), "member_count": len(members)})
        notify_users(request.user, User.objects.filter(role=User.Role.DEAN, account_status=User.AccountStatus.ACTIVE), "defense_committee.proposed", "لجنة مناقشة بانتظار الاعتماد", record.project.title, "/?page=committees")
        return Response(DefenseCommitteeSerializer(committee).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class DefenseCommitteeApprovalView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, committee_id):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("اعتماد لجنة المناقشة متاح للعميد فقط.")
        committee = get_object_or_404(DefenseCommittee.objects.select_for_update().select_related("readiness_request__project__group"), id=committee_id)
        valid_members = committee.members.filter(supervisor__role=User.Role.SUPERVISOR, supervisor__account_status=User.AccountStatus.ACTIVE, supervisor__department_id=committee.readiness_request.project.group.department_id)
        if committee.status != DefenseCommittee.Status.PENDING_APPROVAL or valid_members.count() < 2 or valid_members.count() != committee.members.count() or valid_members.filter(is_chair=True).count() != 1:
            raise Conflict("تشكيل لجنة المناقشة المعلق غير صالح للاعتماد.")
        criteria = list(DefenseRubricCriterion.objects.filter(is_active=True).order_by("scope", "position", "id"))
        for scope in DefenseRubricCriterion.Scope.values:
            scoped = [criterion for criterion in criteria if criterion.scope == scope]
            if not scoped or sum((criterion.weight for criterion in scoped), Decimal("0")) != Decimal("100.00"):
                raise Conflict("على العميد ضبط أوزان معايير التقييم الجماعي والفردي لتساوي 100% لكل نوع قبل اعتماد لجنة المناقشة.")
        DefenseCommitteeCriterion.objects.bulk_create([
            DefenseCommitteeCriterion(committee=committee, source_criterion_id=criterion.id, title=criterion.title, description=criterion.description, scope=criterion.scope, weight=criterion.weight, position=criterion.position)
            for criterion in criteria
        ])
        committee.status = DefenseCommittee.Status.APPROVED
        committee.approved_by = request.user
        committee.approved_at = timezone.now()
        committee.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        audit(request.user, "defense_committee.approved", "defense_committee", committee.id)
        notify_users(request.user, [committee.proposed_by, *User.objects.filter(defense_committee_memberships__committee=committee)], "defense_committee.approved", "تم اعتماد لجنة المناقشة", committee.readiness_request.project.title, "/?page=committees")
        return Response(DefenseCommitteeSerializer(committee).data)


class DefenseMeetingView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_committee(self, request, committee_id):
        committee = get_object_or_404(DefenseCommittee.objects.select_related("readiness_request__project__group__department"), id=committee_id, status=DefenseCommittee.Status.APPROVED)
        project = committee.readiness_request.project
        panel_member = request.user.role == User.Role.SUPERVISOR and committee.members.filter(supervisor=request.user).exists()
        chair = request.user.role == User.Role.DEPARTMENT_CHAIR and request.user.department_id == project.group.department_id
        if request.user.role != User.Role.DEAN and not panel_member and not chair:
            raise NotFound()
        return committee, panel_member

    def get(self, request, committee_id):
        committee, panel_member = self.get_committee(request, committee_id)
        is_panel_chair = panel_member and committee.members.filter(supervisor=request.user, is_chair=True).exists()
        return Response({"committee_id": str(committee.id), "project_id": str(committee.readiness_request.project_id), "defense_at": committee.defense_at, "location": committee.defense_location, "minutes": committee.minutes, "minutes_recorded_at": committee.minutes_recorded_at, "can_record_minutes": bool(is_panel_chair)})

    @transaction.atomic
    def post(self, request, committee_id):
        committee, panel_member = self.get_committee(request, committee_id)
        project = committee.readiness_request.project
        changed = []
        if "defense_at" in request.data or "location" in request.data:
            can_schedule = request.user.role == User.Role.DEAN or (request.user.role == User.Role.DEPARTMENT_CHAIR and request.user.department_id == project.group.department_id)
            if not can_schedule:
                raise PermissionDenied("جدولة جلسة المناقشة متاحة للعميد أو رئيس القسم فقط.")
            raw_at = request.data.get("defense_at")
            defense_at = parse_datetime(str(raw_at)) if raw_at else None
            if raw_at and defense_at is None:
                raise ValidationError({"defense_at": "أدخل تاريخًا ووقتًا صالحين."})
            location = str(request.data.get("location", "")).strip()
            if defense_at and (not location or len(location) > 240):
                raise ValidationError({"location": "مكان المناقشة مطلوب وبحد أقصى 240 حرفًا."})
            committee.defense_at = defense_at
            committee.defense_location = location if defense_at else ""
            changed += ["defense_at", "defense_location"]
            audit(request.user, "defense_meeting.scheduled" if defense_at else "defense_meeting.cleared", "defense_committee", committee.id, metadata={"project_id": str(project.id), "defense_at": defense_at.isoformat() if defense_at else None, "location": committee.defense_location})
            if defense_at:
                recipients = list(User.objects.filter(Q(group_memberships__group=project.group, group_memberships__left_at__isnull=True) | Q(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True) | Q(defense_committee_memberships__committee=committee), account_status=User.AccountStatus.ACTIVE).distinct())
                notify_users(request.user, recipients, "defense_meeting.scheduled", "تم تحديد موعد المناقشة", f"{project.title} · {defense_at:%Y-%m-%d %H:%M} · {location}", f"/?page=committees")
        if "minutes" in request.data:
            is_panel_chair = panel_member and committee.members.filter(supervisor=request.user, is_chair=True).exists()
            minutes = str(request.data.get("minutes", "")).strip()
            if not is_panel_chair:
                raise PermissionDenied("تسجيل محضر المناقشة متاح لرئيس اللجنة فقط.")
            if not committee.defense_at or committee.defense_at > timezone.now():
                raise Conflict("لا يمكن تسجيل المحضر قبل حلول موعد جلسة المناقشة.")
            if not minutes or len(minutes) > 12000:
                raise ValidationError({"minutes": "أدخل محضرًا لا يتجاوز 12000 حرفًا."})
            committee.minutes = minutes
            committee.minutes_recorded_by = request.user
            committee.minutes_recorded_at = timezone.now()
            changed += ["minutes", "minutes_recorded_by", "minutes_recorded_at"]
            audit(request.user, "defense_meeting.minutes_recorded", "defense_committee", committee.id, metadata={"project_id": str(project.id), "minutes_recorded_at": committee.minutes_recorded_at.isoformat()})
        if not changed:
            raise ValidationError("أرسل بيانات الموعد أو محضر اللجنة.")
        committee.save(update_fields=list(dict.fromkeys(changed + ["updated_at"])))
        return self.get(request, committee_id)


class DefenseRubricView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("إعداد معايير وأوزان التقييم متاح للعميد فقط.")
        return Response(DefenseRubricCriterionSerializer(DefenseRubricCriterion.objects.all(), many=True).data)

    def post(self, request):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("إعداد معايير وأوزان التقييم متاح للعميد فقط.")
        payload = {key: request.data.get(key) for key in ("title", "description", "scope", "weight", "position", "is_active") if key in request.data}
        serializer = DefenseRubricCriterionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["weight"] <= 0 or serializer.validated_data["weight"] > 100:
            raise ValidationError({"weight": "يجب أن يكون وزن المعيار أكبر من صفر ولا يتجاوز 100%."})
        criterion = serializer.save(updated_by=request.user)
        audit(request.user, "defense_rubric.created", "defense_rubric_criterion", criterion.id, metadata={"scope": criterion.scope})
        return Response(DefenseRubricCriterionSerializer(criterion).data, status=status.HTTP_201_CREATED)

    def patch(self, request, criterion_id):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("إعداد معايير وأوزان التقييم متاح للعميد فقط.")
        criterion = get_object_or_404(DefenseRubricCriterion, id=criterion_id)
        payload = {key: request.data[key] for key in ("title", "description", "scope", "weight", "position", "is_active") if key in request.data}
        serializer = DefenseRubricCriterionSerializer(criterion, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("weight", criterion.weight) <= 0 or serializer.validated_data.get("weight", criterion.weight) > 100:
            raise ValidationError({"weight": "يجب أن يكون وزن المعيار أكبر من صفر ولا يتجاوز 100%."})
        criterion = serializer.save(updated_by=request.user)
        audit(request.user, "defense_rubric.updated", "defense_rubric_criterion", criterion.id, metadata={"scope": criterion.scope, "is_active": criterion.is_active})
        return Response(DefenseRubricCriterionSerializer(criterion).data)


class DefenseEvaluationView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_committee(self, request, committee_id):
        committee = get_object_or_404(DefenseCommittee.objects.select_related("readiness_request__project__group"), id=committee_id, status=DefenseCommittee.Status.APPROVED)
        is_dean = request.user.role == User.Role.DEAN
        is_member = request.user.role == User.Role.SUPERVISOR and committee.members.filter(supervisor=request.user).exists()
        if not is_dean and not is_member:
            raise NotFound()
        return committee, is_dean

    def get(self, request, committee_id):
        committee, is_dean = self.get_committee(request, committee_id)
        members = list(committee.members.select_related("supervisor__supervisor_profile").order_by("-is_chair", "supervisor_id"))
        submitted = DefenseEvaluation.objects.filter(committee=committee).count()
        closed = submitted == len(members)
        students = list(committee.readiness_request.project.group.members.filter(left_at__isnull=True).select_related("student__student_profile").order_by("joined_at"))
        criteria = list(committee.rubric.all())
        own = DefenseEvaluation.objects.filter(committee=committee, reviewer=request.user).prefetch_related("scores").first()
        is_committee_chair = not is_dean and committee.members.filter(supervisor=request.user, is_chair=True).exists()

        def serialize_evaluation(evaluation):
            return {
                "reviewer_id": str(evaluation.reviewer_id),
                "reviewer_name": evaluation.reviewer.supervisor_profile.full_name if hasattr(evaluation.reviewer, "supervisor_profile") else evaluation.reviewer.username,
                "submitted_at": evaluation.submitted_at,
                "scores": [{"criterion_id": str(row.criterion_id), "student_id": str(row.student_id) if row.student_id else None, "score": str(row.score), "note": row.note} for row in evaluation.scores.all()],
            }

        evaluations = []
        if is_dean or closed:
            evaluations = [serialize_evaluation(item) for item in DefenseEvaluation.objects.filter(committee=committee).select_related("reviewer__supervisor_profile").prefetch_related("scores")]
        return Response({
            "committee_id": str(committee.id), "project_id": str(committee.readiness_request.project_id), "project_title": committee.readiness_request.project.title,
            "criteria": [{"id": str(item.id), "title": item.title, "description": item.description, "scope": item.scope, "weight": str(item.weight)} for item in criteria],
            "students": [{"id": str(row.student_id), "name": row.student.student_profile.full_name if hasattr(row.student, "student_profile") else row.student.username} for row in students],
            "members": [{"id": str(row.supervisor_id), "name": row.supervisor.supervisor_profile.full_name if hasattr(row.supervisor, "supervisor_profile") else row.supervisor.username, "submitted": DefenseEvaluation.objects.filter(committee=committee, reviewer=row.supervisor).exists()} for row in members],
            "submitted_count": submitted, "total_count": len(members), "closed": closed,
            "meeting": {"defense_at": committee.defense_at, "location": committee.defense_location, "minutes": committee.minutes, "minutes_recorded_at": committee.minutes_recorded_at},
            "can_record_minutes": bool(is_committee_chair),
            "my_evaluation": serialize_evaluation(own) if own else None,
            "evaluations": evaluations,
        })

    @transaction.atomic
    def post(self, request, committee_id):
        committee, is_dean = self.get_committee(request, committee_id)
        if is_dean or request.user.role != User.Role.SUPERVISOR:
            raise PermissionDenied("تقديم التقييم السري متاح لعضو لجنة المناقشة فقط.")
        if DefenseEvaluation.objects.filter(committee=committee, reviewer=request.user).exists():
            raise Conflict("سبق إرسال تقييمك النهائي لهذه المناقشة ولا يمكن تعديله.")
        criteria = list(committee.rubric.all())
        students = list(committee.readiness_request.project.group.members.filter(left_at__isnull=True).values_list("student_id", flat=True))
        raw_scores = request.data.get("scores")
        if not isinstance(raw_scores, list):
            raise ValidationError({"scores": "أرسل درجات معايير التقييم."})
        expected = set()
        for criterion in criteria:
            if criterion.scope == DefenseRubricCriterion.Scope.PROJECT:
                expected.add((str(criterion.id), None))
            else:
                expected.update((str(criterion.id), str(student_id)) for student_id in students)
        supplied = {}
        errors = {}
        for index, row in enumerate(raw_scores):
            if not isinstance(row, dict):
                errors[str(index)] = "صيغة الدرجة غير صحيحة."
                continue
            criterion_id = str(row.get("criterion_id", ""))
            student_id = str(row["student_id"]) if row.get("student_id") else None
            key = (criterion_id, student_id)
            if key not in expected or key in supplied:
                errors[str(index)] = "المعيار أو الطالب غير صالح أو مكرر."
                continue
            try:
                score = Decimal(str(row.get("score", "")))
            except (InvalidOperation, ValueError):
                errors[str(index)] = "أدخل درجة رقمية بين 0 و100."
                continue
            if not score.is_finite() or score < 0 or score > 100 or score.as_tuple().exponent < -2:
                errors[str(index)] = "الدرجة يجب أن تكون بين 0 و100 وبحد أقصى منزلتين عشريتين."
                continue
            note = str(row.get("note", "")).strip()
            if len(note) > 2000:
                errors[str(index)] = "الحد الأقصى لملاحظة الدرجة 2000 حرف."
                continue
            supplied[key] = (score, note)
        if errors:
            raise ValidationError({"scores": errors})
        if set(supplied) != expected:
            raise ValidationError({"scores": "أكمل كل المعايير الجماعية والفردية قبل الإرسال النهائي."})
        evaluation = DefenseEvaluation.objects.create(committee=committee, reviewer=request.user)
        criterion_by_id = {str(item.id): item for item in criteria}
        DefenseEvaluationScore.objects.bulk_create([
            DefenseEvaluationScore(evaluation=evaluation, criterion=criterion_by_id[criterion_id], student_id=student_id, score=score, note=note)
            for (criterion_id, student_id), (score, note) in supplied.items()
        ])
        audit(request.user, "defense_evaluation.submitted", "defense_evaluation", evaluation.id, metadata={"committee_id": str(committee.id), "score_count": len(supplied)})
        total = committee.members.count()
        all_submitted = DefenseEvaluation.objects.filter(committee=committee).count() == total
        if all_submitted:
            notify_users(request.user, [*User.objects.filter(defense_committee_memberships__committee=committee), committee.proposed_by], "defense_evaluation.closed", "أغلقت التقييمات السرية للمناقشة", committee.readiness_request.project.title, "/?page=committees")
        return Response({"submitted": True, "closed": all_submitted, "submitted_count": DefenseEvaluation.objects.filter(committee=committee).count(), "total_count": total}, status=status.HTTP_201_CREATED)


def approved_defense_committee_for_project(project):
    return DefenseCommittee.objects.filter(readiness_request__project=project, status=DefenseCommittee.Status.APPROVED).select_related("readiness_request__project__group").order_by("-readiness_request__version").first()


def post_defense_item_payload(item):
    return {
        "id": str(item.id), "description": item.description, "assigned_to": str(item.assigned_to_id),
        "assigned_to_name": item.assigned_to.student_profile.full_name if hasattr(item.assigned_to, "student_profile") else item.assigned_to.username,
        "due_at": item.due_at, "status": item.status, "evidence_id": str(item.evidence_id) if item.evidence_id else None,
        "evidence_filename": item.evidence.original_filename if item.evidence_id else None,
        "created_by_name": item.created_by.supervisor_profile.full_name if hasattr(item.created_by, "supervisor_profile") else item.created_by.username,
        "supervisor_note": item.supervisor_note, "reviewed_at": item.reviewed_at, "created_at": item.created_at,
    }


class ProjectPostDefenseView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, project_id):
        project = get_object_or_404(Project.objects.select_related("group__department"), id=project_id)
        committee = approved_defense_committee_for_project(project)
        project_access = can_view_project(request.user, project)
        panel_access = bool(committee and request.user.role == User.Role.SUPERVISOR and committee.members.filter(supervisor=request.user).exists())
        if not project_access and not panel_access:
            raise NotFound()
        if not committee:
            return Response({"committee_id": None, "revisions": [], "final_submissions": [], "students": [], "can_record_revision": False, "is_assigned_supervisor": False, "is_group_leader": False})
        revisions = committee.post_defense_revisions.select_related("assigned_to__student_profile", "evidence", "created_by__supervisor_profile").order_by("due_at", "created_at")
        submissions = committee.final_submissions.select_related("deliverable", "submitted_by", "reviewed_by").all()
        return Response({
            "committee_id": str(committee.id), "evaluations_closed": committee.evaluations.count() == committee.members.count(),
            "can_record_revision": panel_access,
            "is_assigned_supervisor": request.user.role == User.Role.SUPERVISOR and ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists(),
            "is_group_leader": request.user.role == User.Role.STUDENT and project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists(),
            "students": [{"id": str(member.student_id), "name": member.student.student_profile.full_name if hasattr(member.student, "student_profile") else member.student.username} for member in project.group.members.filter(left_at__isnull=True).select_related("student__student_profile").order_by("joined_at")],
            "revisions": [post_defense_item_payload(item) for item in revisions],
            "final_submissions": [{"id": str(item.id), "version": item.version, "deliverable_id": str(item.deliverable_id), "filename": item.deliverable.original_filename, "status": item.status, "supervisor_note": item.supervisor_note, "submitted_at": item.created_at, "reviewed_at": item.reviewed_at} for item in submissions],
        })


class PostDefenseRevisionCreateView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, project_id):
        project = get_object_or_404(Project.objects.select_related("group"), id=project_id)
        committee = approved_defense_committee_for_project(project)
        if request.user.role != User.Role.SUPERVISOR or not committee or not committee.members.filter(supervisor=request.user).exists():
            raise PermissionDenied("تسجيل ملاحظات لجنة المناقشة متاح لأعضائها بعد اعتمادها فقط.")
        latest_final = committee.final_submissions.order_by("-version").first()
        if latest_final and latest_final.status == PostDefenseFinalSubmission.Status.APPROVED:
            raise Conflict("اعتمد المشرف النسخة النهائية؛ لا يمكن إضافة ملاحظة جديدة إلى هذه المناقشة.")
        description = str(request.data.get("description", "")).strip()
        due_at = parse_date(str(request.data.get("due_at", "")))
        assigned_id = request.data.get("assigned_to")
        assigned = get_object_or_404(User, id=assigned_id, role=User.Role.STUDENT) if assigned_id else None
        if not description or len(description) > 3000:
            raise ValidationError({"description": "نص الملاحظة مطلوب وبحد أقصى 3000 حرف."})
        if due_at is None:
            raise ValidationError({"due_at": "حدد موعدًا صحيحًا للتنفيذ."})
        if not assigned or not project.group.members.filter(student=assigned, left_at__isnull=True).exists():
            raise ValidationError({"assigned_to": "اختر طالبًا عضوًا حاليًا في المجموعة."})
        item = PostDefenseRevision.objects.create(committee=committee, description=description, due_at=due_at, assigned_to=assigned, created_by=request.user)
        notify_users(request.user, [assigned], "post_defense_revision.assigned", "أُسند إليك تعديل بعد المناقشة", project.title, f"/?page=project&project={project.id}")
        audit(request.user, "post_defense_revision.created", "post_defense_revision", item.id, metadata={"project_id": str(project.id), "assigned_to": str(assigned.id)})
        return Response(post_defense_item_payload(item), status=status.HTTP_201_CREATED)


class PostDefenseRevisionActionView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, revision_id, action):
        item = get_object_or_404(PostDefenseRevision.objects.select_for_update().select_related("committee__readiness_request__project__group", "assigned_to", "evidence"), id=revision_id)
        project = item.committee.readiness_request.project
        note = str(request.data.get("note", "")).strip()
        if action == "submit":
            if request.user.role != User.Role.STUDENT or item.assigned_to_id != request.user.id:
                raise PermissionDenied("تنفيذ الملاحظة متاح للطالب المكلف فقط.")
            if item.status not in {PostDefenseRevision.Status.OPEN, PostDefenseRevision.Status.CHANGES_REQUESTED}:
                raise Conflict("هذه الملاحظة ليست بانتظار التنفيذ.")
            evidence = get_object_or_404(Deliverable, id=request.data.get("evidence_id"), project=project)
            item.evidence = evidence
            item.status = PostDefenseRevision.Status.SUBMITTED
            item.save(update_fields=["evidence", "status", "updated_at"])
            supervisors = User.objects.filter(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True)
            notify_users(request.user, supervisors, "post_defense_revision.submitted", "تعديل بعد المناقشة بانتظار مراجعتك", project.title, f"/?page=project&project={project.id}")
            audit(request.user, "post_defense_revision.submitted", "post_defense_revision", item.id)
        elif action == "review":
            if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists():
                raise PermissionDenied("اعتماد التعديل متاح للمشرف المسند فقط.")
            decision = request.data.get("decision")
            if item.status != PostDefenseRevision.Status.SUBMITTED or decision not in {"approved", "changes_requested"}:
                raise Conflict("التعديل ليس بانتظار المراجعة أو القرار غير صالح.")
            if decision == "changes_requested" and not note:
                raise ValidationError({"note": "اكتب ما يلزم استكماله."})
            item.status = PostDefenseRevision.Status(decision)
            item.supervisor_note = note
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save(update_fields=["status", "supervisor_note", "reviewed_by", "reviewed_at", "updated_at"])
            notify_users(request.user, [item.assigned_to], f"post_defense_revision.{decision}", "مراجعة تعديل ما بعد المناقشة", note or "اعتمد المشرف تنفيذ الملاحظة.", f"/?page=project&project={project.id}")
            audit(request.user, f"post_defense_revision.{decision}", "post_defense_revision", item.id)
        else:
            raise NotFound()
        return Response(post_defense_item_payload(item))


class PostDefenseFinalSubmissionView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, project_id):
        project = get_object_or_404(Project.objects.select_related("group"), id=project_id)
        committee = approved_defense_committee_for_project(project)
        if request.user.role != User.Role.STUDENT or not project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists():
            raise PermissionDenied("تسليم النسخة النهائية بعد التعديلات متاح لقائد المجموعة فقط.")
        if not committee:
            raise Conflict("لا توجد لجنة مناقشة معتمدة لهذا المشروع.")
        if committee.evaluations.count() != committee.members.count():
            raise Conflict("يجب إغلاق تقييمات لجنة المناقشة أولًا.")
        if committee.post_defense_revisions.exclude(status=PostDefenseRevision.Status.APPROVED).exists():
            raise Conflict("يجب اعتماد جميع تعديلات لجنة المناقشة من المشرف قبل تسليم النسخة النهائية.")
        deliverable = get_object_or_404(Deliverable, id=request.data.get("deliverable_id"), project=project)
        latest = committee.final_submissions.order_by("-version").first()
        if latest and latest.status != PostDefenseFinalSubmission.Status.CHANGES_REQUESTED:
            raise Conflict("لا تقبل نسخة أخرى إلا إذا أعاد المشرف النسخة الحالية للاستكمال.")
        item = PostDefenseFinalSubmission.objects.create(committee=committee, version=(latest.version if latest else 0) + 1, deliverable=deliverable, submitted_by=request.user)
        supervisors = User.objects.filter(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True)
        notify_users(request.user, supervisors, "post_defense_final.submitted", "نسخة نهائية بعد المناقشة بانتظار اعتمادك الفني", project.title, f"/?page=project&project={project.id}")
        audit(request.user, "post_defense_final.submitted", "post_defense_final_submission", item.id, metadata={"version": item.version, "project_id": str(project.id)})
        return Response({"id": str(item.id), "version": item.version, "deliverable_id": str(deliverable.id), "filename": deliverable.original_filename, "status": item.status}, status=status.HTTP_201_CREATED)


class PostDefenseFinalReviewView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def post(self, request, submission_id):
        item = get_object_or_404(PostDefenseFinalSubmission.objects.select_for_update().select_related("committee__readiness_request__project", "deliverable"), id=submission_id)
        project = item.committee.readiness_request.project
        if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists():
            raise PermissionDenied("الاعتماد الفني للنسخة النهائية متاح للمشرف المسند فقط.")
        decision = request.data.get("decision")
        note = str(request.data.get("note", "")).strip()
        if item.status != PostDefenseFinalSubmission.Status.SUBMITTED or decision not in {"approved", "changes_requested"}:
            raise Conflict("النسخة النهائية ليست بانتظار المراجعة أو القرار غير صالح.")
        if decision == "changes_requested" and not note:
            raise ValidationError({"note": "اكتب ملاحظات الاستكمال المطلوبة."})
        item.status = PostDefenseFinalSubmission.Status(decision)
        item.supervisor_note = note
        item.reviewed_by = request.user
        item.reviewed_at = timezone.now()
        item.save(update_fields=["status", "supervisor_note", "reviewed_by", "reviewed_at"])
        notify_users(request.user, User.objects.filter(group_memberships__group=project.group, group_memberships__left_at__isnull=True), f"post_defense_final.{decision}", "مراجعة النسخة النهائية", note or "اعتمد المشرف النسخة النهائية فنيًا.", f"/?page=project&project={project.id}")
        audit(request.user, f"post_defense_final.{decision}", "post_defense_final_submission", item.id)
        return Response({"id": str(item.id), "version": item.version, "status": item.status, "supervisor_note": item.supervisor_note})


def stage_project_for(request, stage_id):
    stage = get_object_or_404(ProjectStage.objects.select_for_update().select_related("project", "project__group"), id=stage_id)
    project = get_object_or_404(project_queryset_for(request.user), id=stage.project_id)
    if not can_view_project(request.user, project):
        raise NotFound()
    return stage


def previous_required_stages_approved(stage):
    return not ProjectStage.objects.filter(
        project_id=stage.project_id, is_required=True, order__lt=stage.order,
    ).exclude(status=ProjectStage.Status.APPROVED).exists()


class ProjectStagesView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        stages = ProjectStage.objects.filter(project=project).prefetch_related("reviews__actor", "deliverables")
        data = ProjectStageSerializer(stages, many=True).data
        for entry, stage in zip(data, stages):
            entry["deliverables"] = DeliverableReadSerializer(stage.deliverables.select_related("uploaded_by"), many=True).data
        return Response(data)

    def post(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists():
            raise PermissionDenied("إضافة مراحل مخصصة متاحة للمشرف المسند فقط.")
        title = str(request.data.get("title", "")).strip()
        if not title or len(title) > 180:
            raise ValidationError({"title": "اسم المرحلة مطلوب وبحد أقصى 180 حرفًا."})
        stage = ProjectStage.objects.create(
            project=project,
            order=(project.stages.order_by("-order").values_list("order", flat=True).first() or 0) + 1,
            title=title,
            description=str(request.data.get("description", "")).strip()[:2000],
            is_required=False,
        )
        audit(request.user, "project_stage.created", "project_stage", stage.id)
        return Response(ProjectStageSerializer(stage).data, status=status.HTTP_201_CREATED)


class ProjectStageActionView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def patch(self, request, stage_id):
        stage = stage_project_for(request, stage_id)
        if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(
            project_id=stage.project_id, supervisor=request.user, ended_at__isnull=True,
        ).exists():
            raise PermissionDenied("تعديل خطة المرحلة متاح للمشرف المسند فقط.")
        if stage.status in {ProjectStage.Status.SUBMITTED, ProjectStage.Status.APPROVED}:
            raise Conflict("لا يمكن تعديل بيانات مرحلة بانتظار المراجعة أو معتمدة.")
        serializer = ProjectStageSerializer(stage, data={key: request.data[key] for key in ("title", "description", "starts_at", "due_at") if key in request.data}, partial=True)
        serializer.is_valid(raise_exception=True)
        stage = serializer.save()
        audit(request.user, "project_stage.updated", "project_stage", stage.id)
        return Response(ProjectStageSerializer(stage).data)

    @transaction.atomic
    def delete(self, request, stage_id):
        stage = stage_project_for(request, stage_id)
        if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(project_id=stage.project_id, supervisor=request.user, ended_at__isnull=True).exists():
            raise PermissionDenied("حذف المرحلة متاح للمشرف المسند فقط.")
        if stage.is_required or stage.status in {ProjectStage.Status.SUBMITTED, ProjectStage.Status.APPROVED} or stage.reviews.exists() or stage.tasks.exists() or stage.deliverables.exists():
            raise Conflict("لا يمكن حذف مرحلة إلزامية أو لها مراجعات أو مهام أو ملفات محفوظة.")
        audit(request.user, "project_stage.deleted", "project_stage", stage.id)
        stage.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def post(self, request, stage_id, action):
        stage = stage_project_for(request, stage_id)
        note = str(request.data.get("note", "")).strip()
        if action in {"start", "progress", "submit"}:
            if request.user.role != User.Role.STUDENT or not stage.project.group.members.filter(student=request.user, left_at__isnull=True).exists():
                raise PermissionDenied("العملية متاحة لأعضاء مجموعة المشروع فقط.")
            if action == "submit" and not stage.project.group.members.filter(student=request.user, left_at__isnull=True, is_leader=True).exists():
                raise PermissionDenied("قائد المجموعة هو المخول بإرسال المرحلة للمراجعة.")
            if not previous_required_stages_approved(stage):
                raise Conflict("يجب اعتماد المرحلة السابقة أولًا.")
            if action == "start":
                if stage.project.idea_revisions.order_by("-version").values_list("status", flat=True).first() != ProjectIdeaRevision.Status.APPROVED:
                    raise Conflict("يجب اعتماد فكرة المشروع من رئيس القسم قبل بدء التنفيذ.")
                if not stage.project.plans.filter(status=ProjectPlan.Status.APPROVED).order_by("-version").first() or stage.project.plans.order_by("-version").values_list("status", flat=True).first() != ProjectPlan.Status.APPROVED:
                    raise Conflict("يجب تقديم خطة المشروع واعتماد أحدث نسخة من المشرف قبل بدء المراحل.")
                if stage.status not in {ProjectStage.Status.NOT_STARTED, ProjectStage.Status.CHANGES_REQUESTED}:
                    raise Conflict("لا يمكن بدء المرحلة في حالتها الحالية.")
                stage.status = ProjectStage.Status.IN_PROGRESS
                stage.progress = max(stage.progress, 1)
                stage.save(update_fields=["status", "progress", "updated_at"])
                action_name = "started"
            elif action == "progress":
                try:
                    progress = int(request.data.get("progress"))
                except (TypeError, ValueError):
                    raise ValidationError({"progress": "أدخل نسبة صحيحة من 0 إلى 99."})
                if not 0 <= progress <= 99 or stage.status != ProjectStage.Status.IN_PROGRESS:
                    raise ValidationError({"progress": "تحديث التقدم متاح للمرحلة قيد التنفيذ وبنسبة من 0 إلى 99."})
                stage.progress = progress
                stage.save(update_fields=["progress", "updated_at"])
                action_name = "progress_updated"
            else:
                if stage.status != ProjectStage.Status.IN_PROGRESS:
                    raise Conflict("ابدأ المرحلة قبل إرسالها للمراجعة.")
                if not stage.deliverables.exists():
                    raise ValidationError({"evidence": "ارفع ملفًا مرتبطًا بهذه المرحلة قبل طلب مراجعتها."})
                stage.status = ProjectStage.Status.SUBMITTED
                stage.progress = 100
                stage.save(update_fields=["status", "progress", "updated_at"])
                ProjectStageReview.objects.create(stage=stage, actor=request.user, action=ProjectStageReview.Action.SUBMITTED, note=note)
                notify_users(request.user, User.objects.filter(supervisor_assignments__project=stage.project, supervisor_assignments__ended_at__isnull=True), "project_stage.submitted", "مرحلة تنتظر المراجعة", stage.title, f"/?page=project&project={stage.project_id}")
                action_name = "submitted"
        elif action == "review":
            if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(
                project_id=stage.project_id, supervisor=request.user, ended_at__isnull=True,
            ).exists():
                raise PermissionDenied("مراجعة المراحل متاحة للمشرف المسند فقط.")
            decision = request.data.get("decision")
            if stage.status != ProjectStage.Status.SUBMITTED or decision not in {"approved", "changes_requested"}:
                raise Conflict("لا توجد مرحلة معلقة للمراجعة أو القرار غير صالح.")
            if decision == "changes_requested" and not note:
                raise ValidationError({"note": "اكتب ملاحظات التعديلات المطلوبة."})
            stage.status = decision
            if decision == "changes_requested":
                stage.progress = min(stage.progress, 99)
            ProjectStageReview.objects.create(
                stage=stage, actor=request.user,
                action=ProjectStageReview.Action.APPROVED if decision == "approved" else ProjectStageReview.Action.CHANGES_REQUESTED,
                note=note,
            )
            stage.save(update_fields=["status", "progress", "updated_at"])
            notify_users(request.user, User.objects.filter(group_memberships__group=stage.project.group, group_memberships__left_at__isnull=True), f"project_stage.{decision}", "تحديث مراجعة المرحلة", f"{stage.title}: {note or 'تم اعتماد المرحلة'}", f"/?page=project&project={stage.project_id}")
            action_name = decision
        else:
            raise NotFound()
        audit(request.user, f"project_stage.{action_name}", "project_stage", stage.id, metadata={"progress": stage.progress})
        stage = ProjectStage.objects.prefetch_related("reviews__actor", "deliverables").get(id=stage.id)
        result = ProjectStageSerializer(stage).data
        result["deliverables"] = DeliverableReadSerializer(stage.deliverables.select_related("uploaded_by"), many=True).data
        return Response(result)


class ProjectTasksView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_project(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return project

    def get(self, request, project_id):
        project = self.get_project(request, project_id)
        tasks = ProjectTask.objects.filter(stage__project=project).select_related("stage", "assigned_to", "created_by")
        return Response(ProjectTaskReadSerializer(tasks, many=True).data)

    def post(self, request, project_id):
        project = self.get_project(request, project_id)
        if request.user.role != User.Role.SUPERVISOR or not ProjectSupervisor.objects.filter(
            project=project, supervisor=request.user, ended_at__isnull=True,
        ).exists():
            raise PermissionDenied("إنشاء المهام وتوزيعها متاح للمشرف المسند فقط.")
        stage = get_object_or_404(ProjectStage, id=request.data.get("stage_id"), project=project)
        title = str(request.data.get("title", "")).strip()
        description = str(request.data.get("description", "")).strip()
        if not title or len(title) > 180:
            raise ValidationError({"title": "اسم المهمة مطلوب وبحد أقصى 180 حرفًا."})
        if len(description) > 2000:
            raise ValidationError({"description": "تجاوز وصف المهمة الحد المسموح."})
        assigned_to = None
        assigned_id = request.data.get("assigned_to") or None
        if assigned_id:
            assigned_to = get_object_or_404(User, id=assigned_id, role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE)
            if not project.group.members.filter(student=assigned_to, left_at__isnull=True).exists():
                raise ValidationError({"assigned_to": "يجب أن يكون المكلف عضوًا نشطًا في هذه المجموعة."})
        due_text = request.data.get("due_at") or None
        due_at = parse_date(str(due_text)) if due_text else None
        if due_text and due_at is None:
            raise ValidationError({"due_at": "أدخل تاريخًا بصيغة صحيحة."})
        task = ProjectTask.objects.create(stage=stage, title=title, description=description, assigned_to=assigned_to, created_by=request.user, due_at=due_at)
        audit(request.user, "project_task.created", "project_task", task.id, metadata={"project_id": str(project.id), "stage_id": str(stage.id)})
        if assigned_to:
            notify_users(request.user, [assigned_to], "project_task.assigned", "أُسندت إليك مهمة", title, f"/?page=project&project={project.id}")
        return Response(ProjectTaskReadSerializer(task).data, status=status.HTTP_201_CREATED)


class ProjectTaskDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @transaction.atomic
    def patch(self, request, task_id):
        task = get_object_or_404(ProjectTask.objects.select_related("stage__project", "assigned_to"), id=task_id)
        project = get_object_or_404(project_queryset_for(request.user), id=task.stage.project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        if request.user.role == User.Role.SUPERVISOR:
            if not ProjectSupervisor.objects.filter(project=project, supervisor=request.user, ended_at__isnull=True).exists():
                raise NotFound()
        elif request.user.role == User.Role.STUDENT:
            if not project.group.members.filter(student=request.user, left_at__isnull=True).exists():
                raise NotFound()
            if task.assigned_to_id and task.assigned_to_id != request.user.id:
                raise PermissionDenied("لا يمكنك تحديث مهمة مسندة إلى طالب آخر.")
        else:
            raise PermissionDenied("تحديث المهام متاح لأعضاء المشروع ومشرفه المسند.")
        new_status = request.data.get("status")
        if new_status not in ProjectTask.Status.values:
            raise ValidationError({"status": "اختر حالة مهمة صالحة."})
        task.status = new_status
        task.save(update_fields=["status", "updated_at"])
        audit(request.user, "project_task.status_updated", "project_task", task.id, metadata={"status": new_status})
        return Response(ProjectTaskReadSerializer(task).data)


class NotificationListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        items = Notification.objects.filter(recipient=request.user)[:200]
        unread_count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
        return Response({"unread_count": unread_count, "items": NotificationSerializer(items, many=True).data})


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def post(self, request, notification_id):
        notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


class ProjectAppointmentListCreateView(APIView):
    permission_classes = [IsAuthenticatedActive]

    @staticmethod
    def recipients_for(appointment):
        if appointment.project_id:
            project = appointment.project
            return User.objects.filter(
                Q(group_memberships__group=project.group, group_memberships__left_at__isnull=True)
                | Q(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True),
                account_status=User.AccountStatus.ACTIVE,
            ).distinct()
        return User.objects.filter(
            department=appointment.department,
            account_status=User.AccountStatus.ACTIVE,
            role__in=[User.Role.STUDENT, User.Role.SUPERVISOR, User.Role.DEPARTMENT_CHAIR],
        )

    def get_queryset(self, user):
        qs = ProjectAppointment.objects.select_related("department", "project", "created_by")
        if user.role == User.Role.DEAN:
            return qs
        if user.role == User.Role.DEPARTMENT_CHAIR:
            return qs.filter(department_id=user.department_id) if user.department_id else qs.none()
        if user.role == User.Role.SUPERVISOR:
            project_ids = Project.objects.filter(supervisor_assignments__supervisor=user, supervisor_assignments__ended_at__isnull=True).values("id")
            if user.department_id:
                return qs.filter(Q(department_id=user.department_id) | Q(project_id__in=project_ids)).distinct()
            return qs.filter(project_id__in=project_ids).distinct()
        if user.role == User.Role.STUDENT:
            project_ids = Project.objects.filter(group__members__student=user, group__members__left_at__isnull=True).values("id")
            department_ids = ProjectGroup.objects.filter(members__student=user, members__left_at__isnull=True).values("department_id")
            return qs.filter(department_id__in=department_ids).filter(Q(project__isnull=True) | Q(project_id__in=project_ids)).distinct()
        return qs.none()

    def get(self, request):
        qs = self.get_queryset(request.user)
        return Response(ProjectAppointmentSerializer(qs.filter(starts_at__gte=timezone.now()).order_by("starts_at")[:200], many=True).data)

    def post(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
            raise PermissionDenied("إنشاء المواعيد متاح للعميد ورئيس القسم.")
        project_id = request.data.get("project") or None
        project = None
        if project_id:
            project = get_object_or_404(project_queryset_for(request.user), id=project_id)
            department = project.group.department
        elif request.user.role == User.Role.DEPARTMENT_CHAIR:
            if not request.user.department_id:
                raise ValidationError({"department": "حساب رئيس القسم غير مرتبط بقسم."})
            department = request.user.department
        else:
            department = get_object_or_404(Department, id=request.data.get("department_id"), is_active=True)
        serializer = ProjectAppointmentSerializer(data={key: request.data.get(key) for key in ("title", "description", "starts_at")})
        serializer.is_valid(raise_exception=True)
        appointment = serializer.save(department=department, project=project, created_by=request.user)
        audit(request.user, "appointment.created", "appointment", appointment.id)
        notify_users(request.user, self.recipients_for(appointment), "appointment.created", "موعد أكاديمي جديد", appointment.title, "/?page=calendar")
        return Response(ProjectAppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED)


class ProjectAppointmentDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_object(self, request, appointment_id):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
            raise PermissionDenied("إدارة المواعيد متاحة للعميد ورئيس القسم.")
        qs = ProjectAppointment.objects.select_related("department", "project", "created_by")
        if request.user.role == User.Role.DEPARTMENT_CHAIR:
            qs = qs.filter(department_id=request.user.department_id)
        return get_object_or_404(qs, id=appointment_id)

    def patch(self, request, appointment_id):
        appointment = self.get_object(request, appointment_id)
        serializer = ProjectAppointmentSerializer(appointment, data={key: request.data[key] for key in ("title", "description", "starts_at") if key in request.data}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit(request.user, "appointment.updated", "appointment", appointment.id)
        notify_users(request.user, ProjectAppointmentListCreateView.recipients_for(appointment), "appointment.updated", "تم تعديل موعد أكاديمي", appointment.title, "/?page=calendar")
        return Response(ProjectAppointmentSerializer(appointment).data)

    def delete(self, request, appointment_id):
        appointment = self.get_object(request, appointment_id)
        appointment_id = appointment.id
        notify_users(request.user, ProjectAppointmentListCreateView.recipients_for(appointment), "appointment.cancelled", "تم إلغاء موعد أكاديمي", appointment.title, "/?page=calendar")
        audit(request.user, "appointment.deleted", "appointment", appointment_id, metadata={"title": appointment.title, "department_id": str(appointment.department_id), "project_id": str(appointment.project_id) if appointment.project_id else None})
        appointment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectNotesView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get_project(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return project

    def get(self, request, project_id):
        project = self.get_project(request, project_id)
        notes = project.notes.select_related("author")
        if request.user.role in {User.Role.STUDENT, User.Role.SUPERVISOR}:
            notes = notes.filter(visibility=ProjectNote.Visibility.TEAM)
        return Response(ProjectNoteReadSerializer(notes.order_by("created_at"), many=True).data)

    def post(self, request, project_id):
        project = self.get_project(request, project_id)
        if request.user.role not in {User.Role.STUDENT, User.Role.SUPERVISOR, User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
            raise PermissionDenied("لا تملك صلاحية إضافة ملاحظة.")
        body = str(request.data.get("body", "")).strip()
        if not body:
            raise ValidationError({"body": "نص الملاحظة مطلوب."})
        if len(body) > 5000:
            raise ValidationError({"body": "تجاوزت الملاحظة الحد المسموح."})
        visibility = str(request.data.get("visibility", ProjectNote.Visibility.TEAM))
        if visibility not in ProjectNote.Visibility.values:
            raise ValidationError({"visibility": "مستوى الرؤية غير صالح."})
        if request.user.role in {User.Role.STUDENT, User.Role.SUPERVISOR}:
            visibility = ProjectNote.Visibility.TEAM
        note = ProjectNote.objects.create(project=project, author=request.user, body=body, visibility=visibility)
        audit(request.user, "project_note.created", "project_note", note.id)
        if visibility == ProjectNote.Visibility.TEAM:
            recipients = User.objects.filter(
                Q(group_memberships__group=project.group, group_memberships__left_at__isnull=True)
                | Q(supervisor_assignments__project=project, supervisor_assignments__ended_at__isnull=True),
                account_status=User.AccountStatus.ACTIVE,
            ).distinct()
            notify_users(request.user, recipients, "project_note.created", "ملاحظة جديدة في المشروع", body, f"/?page=notes&project={project.id}")
        return Response(ProjectNoteReadSerializer(note).data, status=status.HTTP_201_CREATED)


class ProjectDeliverablesView(APIView):
    permission_classes = [IsAuthenticatedActive]
    parser_classes = [MultiPartParser, FormParser]
    max_file_size = getattr(settings, "GPMS_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
    allowed_extensions = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".py", ".js", ".ts", ".html", ".css", ".json", ".md"}

    def get_project(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return project

    def get(self, request, project_id):
        project = self.get_project(request, project_id)
        items = project.deliverables.select_related("uploaded_by").order_by("-created_at")
        if request.user.role == User.Role.STUDENT:
            items = items.filter(Q(visibility=Deliverable.Visibility.SHARED) | Q(uploaded_by=request.user))
        return Response(DeliverableReadSerializer(items, many=True).data)

    def post(self, request, project_id):
        if request.user.role != User.Role.STUDENT:
            raise PermissionDenied("رفع ملفات المشروع متاح لأعضاء المجموعة من حساب الطالب.")
        project = self.get_project(request, project_id)
        uploaded = request.FILES.get("file")
        if not uploaded:
            raise ValidationError({"file": "اختر ملفًا لإرفاقه."})
        if uploaded.size <= 0:
            raise ValidationError({"file": "الملف فارغ."})
        if uploaded.size > self.max_file_size:
            raise ValidationError({"file": "الحد الأقصى لحجم الملف 10 ميغابايت."})

        stage_id = request.data.get("stage_id") or None
        stage = None
        if stage_id:
            stage = get_object_or_404(ProjectStage, id=stage_id, project=project)
        visibility = str(request.data.get("visibility", Deliverable.Visibility.SHARED))
        if visibility not in Deliverable.Visibility.values:
            raise ValidationError({"visibility": "اختر ملفًا مشتركًا أو شخصيًا."})

        filename = os.path.basename(uploaded.name.replace("\\", "/")).strip()[:255] or "attachment"
        extension = os.path.splitext(filename)[1].casefold()
        if extension not in self.allowed_extensions:
            raise ValidationError({"file": "نوع الملف غير مسموح. ارفع مستندًا أو صورة أو ملفًا نصيًا/برمجيًا مدعومًا."})
        storage_name = f"deliverables/{project.id}/{uuid4().hex}_{filename}"
        storage_key = default_storage.save(storage_name, uploaded)
        try:
            item = Deliverable.objects.create(
                project=project,
                stage=stage,
                uploaded_by=request.user,
                storage_key=storage_key,
                original_filename=filename,
                media_type=(uploaded.content_type or "application/octet-stream")[:120],
                size_bytes=uploaded.size,
                visibility=visibility,
            )
        except Exception:
            default_storage.delete(storage_key)
            raise
        audit(request.user, "deliverable.uploaded", "deliverable", item.id, metadata={"project_id": str(project.id), "visibility": visibility})
        return Response(DeliverableReadSerializer(item).data, status=status.HTTP_201_CREATED)


class DeliverableDownloadView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, deliverable_id):
        item = get_object_or_404(Deliverable.objects.select_related("project", "uploaded_by"), id=deliverable_id)
        project_access = project_queryset_for(request.user).filter(id=item.project_id).exists() and can_view_project(request.user, item.project)
        defense_access = DefenseCommittee.objects.filter(
            status=DefenseCommittee.Status.APPROVED,
            members__supervisor=request.user,
        ).filter(
            Q(readiness_request__final_deliverable=item)
            | Q(readiness_request__report_deliverable=item)
            | Q(post_defense_revisions__evidence=item)
            | Q(final_submissions__deliverable=item),
        ).exists()
        personal_access = item.visibility == Deliverable.Visibility.PERSONAL and request.user.role == User.Role.STUDENT and item.uploaded_by_id != request.user.id
        if (not project_access and not defense_access) or (personal_access and not defense_access):
            raise NotFound()
        try:
            uploaded = default_storage.open(item.storage_key, "rb")
        except FileNotFoundError:
            raise NotFound("الملف غير موجود في التخزين.")
        response = FileResponse(uploaded, content_type="application/octet-stream")
        response["Content-Disposition"] = content_disposition_header(True, item.original_filename)
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ReportsView(APIView):
    permission_classes = [IsAuthenticatedActive]
    report_names = {
        "projects": "تقرير المشاريع",
        "groups": "تقرير المجموعات",
        "supervisors": "تقرير المشرفين",
        "progress": "تقرير التقدم",
        "defenses": "تقرير المناقشات",
        "audit": "تقرير العمليات",
    }

    @staticmethod
    def _date_filter(queryset, field, date_from, date_to):
        if date_from:
            queryset = queryset.filter(**{f"{field}__date__gte": date_from})
        if date_to:
            queryset = queryset.filter(**{f"{field}__date__lte": date_to})
        return queryset

    def _report_data(self, request, kind, date_from, date_to, department_id):
        user = request.user
        if kind == "audit":
            if user.role != User.Role.DEAN:
                raise PermissionDenied("تقرير سجل العمليات متاح لعميد الكلية فقط.")
            events = AuditLog.objects.select_related("actor").all()
            events = self._date_filter(events, "occurred_at", date_from, date_to).order_by("-occurred_at")[:5000]
            return ["المستخدم", "العملية", "نوع السجل", "التاريخ والوقت"], [
                [event.actor.username if event.actor else "النظام", event.action, event.entity_type, timezone.localtime(event.occurred_at).isoformat(timespec="minutes")]
                for event in events
            ]

        projects = project_queryset_for(user)
        if department_id:
            projects = projects.filter(group__department_id=department_id)
        projects = self._date_filter(projects, "created_at", date_from, date_to).distinct()
        project_ids = projects.values_list("id", flat=True)

        if kind in {"projects", "groups"}:
            columns = ["رمز المجموعة", "عنوان المشروع", "القسم", "العام الدراسي", "الحالة", "عدد الأعضاء", "تاريخ الإنشاء"]
            result = []
            for project in projects.select_related("group__department").order_by("group__department__name", "group__group_code")[:5000]:
                active_members = project.group.members.filter(left_at__isnull=True).count()
                result.append([project.group.group_code, project.title, project.group.department.name, project.group.academic_year,
                               project.get_status_display() if kind == "projects" else project.group.get_status_display(), active_members,
                               timezone.localtime(project.created_at).date().isoformat()])
            return columns, result

        if kind == "supervisors":
            assignments = ProjectSupervisor.objects.filter(project_id__in=project_ids, ended_at__isnull=True).select_related("project__group__department", "supervisor__supervisor_profile").order_by("project__group__department__name", "project__title")
            assignments = self._date_filter(assignments, "started_at", date_from, date_to)[:5000]
            return ["المشروع", "رمز المجموعة", "القسم", "المشرف", "بداية التكليف"], [
                [item.project.title, item.project.group.group_code, item.project.group.department.name,
                 getattr(getattr(item.supervisor, "supervisor_profile", None), "full_name", "") or item.supervisor.username,
                 timezone.localtime(item.started_at).date().isoformat()]
                for item in assignments
            ]

        if kind == "progress":
            stages = ProjectStage.objects.filter(project_id__in=project_ids).select_related("project__group__department").order_by("project__group__department__name", "project__title", "order")
            stages = self._date_filter(stages, "created_at", date_from, date_to)[:5000]
            return ["المشروع", "رمز المجموعة", "القسم", "المرحلة", "الإنجاز %", "الحالة", "تاريخ الاستحقاق"], [
                [stage.project.title, stage.project.group.group_code, stage.project.group.department.name, stage.title,
                 stage.progress, stage.get_status_display(), stage.due_at.isoformat() if stage.due_at else ""]
                for stage in stages
            ]

        committees = DefenseCommittee.objects.filter(status=DefenseCommittee.Status.APPROVED, readiness_request__project_id__in=project_ids).select_related("readiness_request__project__group__department").order_by("readiness_request__project__group__department__name", "readiness_request__project__title")
        committees = self._date_filter(committees, "created_at", date_from, date_to)[:5000]
        return ["المشروع", "رمز المجموعة", "القسم", "موعد المناقشة", "المكان", "حالة المحضر"], [
            [item.readiness_request.project.title, item.readiness_request.project.group.group_code,
             item.readiness_request.project.group.department.name,
             timezone.localtime(item.defense_at).isoformat(timespec="minutes") if item.defense_at else "غير محدد",
             item.defense_location, "سجل" if item.minutes_recorded_at else "لم يسجل"]
            for item in committees
        ]

    def get(self, request):
        kind = str(request.query_params.get("type", "projects"))
        if kind not in self.report_names:
            raise ValidationError({"type": "نوع التقرير غير صالح."})
        if kind == "audit" and request.user.role != User.Role.DEAN:
            raise PermissionDenied("تقرير سجل العمليات متاح لعميد الكلية فقط.")
        raw_department = str(request.query_params.get("department", "")).strip()
        if raw_department and request.user.role != User.Role.DEAN:
            raise PermissionDenied("تصفية التقارير حسب القسم متاحة لعميد الكلية فقط.")
        try:
            department_id = UUID(raw_department) if raw_department else None
        except ValueError:
            raise ValidationError({"department": "معرف القسم غير صالح."})
        if department_id and not Department.objects.filter(id=department_id).exists():
            raise ValidationError({"department": "القسم غير موجود."})
        try:
            date_from = parse_date(str(request.query_params.get("date_from", ""))) if request.query_params.get("date_from") else None
            date_to = parse_date(str(request.query_params.get("date_to", ""))) if request.query_params.get("date_to") else None
        except ValueError:
            raise ValidationError({"date": "استخدم تاريخًا صالحًا بصيغة YYYY-MM-DD."})
        if request.query_params.get("date_from") and not date_from or request.query_params.get("date_to") and not date_to:
            raise ValidationError({"date": "استخدم صيغة التاريخ YYYY-MM-DD."})
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "يجب أن يكون تاريخ النهاية بعد تاريخ البداية."})

        columns, rows = self._report_data(request, kind, date_from, date_to, department_id)
        now = timezone.localtime()
        if department_id:
            department_label = Department.objects.filter(id=department_id).values_list("name", flat=True).first()
        elif request.user.role == User.Role.DEAN:
            department_label = "الكلية"
        elif request.user.role == User.Role.DEPARTMENT_CHAIR:
            department_label = request.user.department.name if request.user.department_id else "القسم غير محدد"
        elif request.user.role == User.Role.SUPERVISOR:
            department_label = f"مشاريع المشرف {request.user.username}"
        else:
            department_label = f"مشروع الطالب {request.user.username}"
        period = f"{date_from.isoformat() if date_from else 'من البداية'} إلى {date_to.isoformat() if date_to else 'اليوم'}"
        metadata = f"تاريخ التصدير: {now.isoformat(timespec='minutes')} · الجهة: {department_label} · أعده: {request.user.get_role_display()} ({request.user.username}) · الفترة: {period} · السجلات المعروضة: {len(rows)} · الحد الأقصى: 5000 سجل"
        output_format = request.query_params.get("output", "xlsx")
        if output_format not in {"xlsx", "print"}:
            raise ValidationError({"output": "صيغة التقرير غير مدعومة."})
        audit(request.user, "reports.export_requested", "report", metadata={"type": kind, "format": output_format, "department_id": str(department_id) if department_id else None, "date_from": date_from.isoformat() if date_from else None, "date_to": date_to.isoformat() if date_to else None, "row_count": len(rows)})
        if output_format == "xlsx":
            filename = f"gpms-{kind}-{now.date().isoformat()}.xlsx"
            response = HttpResponse(make_xlsx(self.report_names[kind], metadata, columns, rows), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = content_disposition_header(True, filename)
            return response
        if output_format == "print":
            head = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
            body = "".join("<tr>" + "".join(f"<td>{escape(str(value if value is not None else ''))}</td>" for value in row) + "</tr>" for row in rows)
            page = f"<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'><title>{escape(self.report_names[kind])}</title><style>body{{font:14px Arial,sans-serif;margin:24px;color:#182b2a}}h1{{font-size:22px}}.meta{{color:#456;font-size:12px;margin:12px 0 20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd7d5;padding:7px;text-align:right;vertical-align:top}}th{{background:#e9f4f1}}button{{padding:8px 16px;margin-bottom:16px}}@media print{{button{{display:none}}body{{margin:10mm}}thead{{display:table-header-group}}}}</style><body><button onclick='window.print()'>طباعة / حفظ PDF</button><h1>{escape(self.report_names[kind])}</h1><p class='meta'>{escape(metadata)}</p><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"
            return HttpResponse(page, content_type="text/html; charset=utf-8")
        raise AssertionError("validated report format was not handled")


class AuditListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role != User.Role.DEAN:
            raise PermissionDenied("سجل التدقيق متاح لعميد الكلية فقط.")
        qs = AuditLog.objects.select_related("actor").all()[:100]
        return Response([{"id": str(x.id), "actor": x.actor.username if x.actor else None, "action": x.action, "entity_type": x.entity_type, "entity_id": str(x.entity_id) if x.entity_id else None, "request_id": str(x.request_id) if x.request_id else None, "metadata": x.safe_metadata, "occurred_at": x.occurred_at} for x in qs])


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "database": "not-probed"})

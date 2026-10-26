from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token

from .models import AuditLog, Department, GroupMember, GroupRequest, OneTimeToken, OutboxEvent, Project, ProjectGroup, ProjectNote, ProjectSupervisor, RequestDecision, RequestRevision, RequestSupervisor, User
from .permissions import IsAuthenticatedActive, can_view_project, request_queryset_for
from .serializers import DepartmentSerializer, GroupDetailReadSerializer, GroupRequestReadSerializer, ProjectNoteReadSerializer, ProjectReadSerializer, RevisionInputSerializer
from .services import Conflict, audit, create_request, decide_request, submit_request, update_request
from .tokens import consume_token, get_valid_token

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
        if not user or not password_ok or not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
            return Response({"detail": "بيانات الدخول غير صحيحة."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            if not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
                return Response({"detail": "بيانات الدخول غير صحيحة."}, status=status.HTTP_400_BAD_REQUEST)
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
        "department": DepartmentSerializer(user.department).data if user.department_id else None,
    }


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        identifier = str(request.data.get("identifier", "")).strip()
        user = User.objects.filter(username_normalized=identifier.casefold(), is_active=True, account_status=User.AccountStatus.ACTIVE).first()
        if not user and identifier:
            user = User.objects.filter(phone=identifier, is_active=True, account_status=User.AccountStatus.ACTIVE).first()
        if user:
            OutboxEvent.objects.create(event_type="password_reset_requested", aggregate_id=user.id, safe_payload={"user_id": str(user.id)})
        return Response({"detail": "إذا كانت البيانات مرتبطة بحساب نشط فستصلك تعليمات الاستعادة عبر قناة الجامعة المعتمدة."})


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
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
            raise PermissionDenied("لا تملك صلاحية عرض الأقسام.")
        qs = Department.objects.filter(is_active=True)
        if request.user.role == User.Role.DEPARTMENT_CHAIR:
            qs = qs.filter(id=request.user.department_id)
        return Response(DepartmentSerializer(qs, many=True).data)


class SupervisorListView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
            raise PermissionDenied("لا تملك صلاحية عرض المشرفين.")
        qs = User.objects.filter(role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE).select_related("department", "supervisor_profile").order_by("supervisor_profile__full_name")
        if request.user.role == User.Role.DEPARTMENT_CHAIR:
            qs = qs.filter(department_id=request.user.department_id)
        return Response([{
            "id": str(user.id),
            "full_name": getattr(user, "supervisor_profile", None).full_name if hasattr(user, "supervisor_profile") else user.username,
            "username": user.username,
            "department": user.department.name if user.department_id else None,
        } for user in qs[:200]])


def input_data(request):
    serializer = RevisionInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class GroupRequestListCreateView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        if request.user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
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
        if user.role not in {User.Role.DEAN, User.Role.DEPARTMENT_CHAIR}:
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
    qs = Project.objects.select_related("group", "group__department").prefetch_related("supervisor_assignments", "group__members")
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


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, project_id):
        project = get_object_or_404(project_queryset_for(request.user), id=project_id)
        if not can_view_project(request.user, project):
            raise NotFound()
        return Response(ProjectReadSerializer(project).data)


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
        return Response(ProjectNoteReadSerializer(note).data, status=status.HTTP_201_CREATED)


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

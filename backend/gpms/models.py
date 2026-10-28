import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Department(UUIDModel):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "dean")
        extra_fields.setdefault("account_status", "active")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        DEAN = "dean", "عميد الكلية"
        DEPARTMENT_CHAIR = "department_chair", "رئيس القسم"
        SUPERVISOR = "supervisor", "المشرف الأكاديمي"
        STUDENT = "student", "الطالب"

    class AccountStatus(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "بانتظار اعتماد المجموعة"
        ACTIVATION_PENDING = "activation_pending", "بانتظار تفعيل الحساب"
        ACTIVE = "active", "نشط"
        DISABLED = "disabled", "موقوف"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username_normalized = models.CharField(max_length=150, unique=True, editable=False)
    role = models.CharField(max_length=24, choices=Role.choices)
    account_status = models.CharField(max_length=24, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    phone = models.CharField(max_length=32, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="users")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    def save(self, *args, **kwargs):
        self.username = self.username.strip()
        self.username_normalized = self.username.casefold()
        self.is_active = self.account_status == self.AccountStatus.ACTIVE
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"username", "username_normalized", "is_active"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE, related_name="student_profile")
    full_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SupervisorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE, related_name="supervisor_profile")
    full_name = models.CharField(max_length=200)
    specialty = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class GroupRequest(UUIDModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        PENDING = "pending_approval", "بانتظار اعتماد العميد"
        RETURNED = "returned", "معاد للتعديل"
        REJECTED = "rejected", "مرفوض"
        APPROVED = "approved", "معتمد"

    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_group_requests")
    current_revision = models.ForeignKey("RequestRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="current_for_requests")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["status", "created_at"])]


class RequestRevision(UUIDModel):
    request = models.ForeignKey(GroupRequest, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    group_code_proposed = models.CharField(max_length=48)
    project_title = models.CharField(max_length=240)
    project_description = models.TextField()
    academic_year = models.CharField(max_length=16)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="request_revisions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="request_revisions")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["request_id", "revision_number"]
        constraints = [models.UniqueConstraint(fields=["request", "revision_number"], name="gpms_request_revision_number_uniq")]


class RequestMember(UUIDModel):
    revision = models.ForeignKey(RequestRevision, on_delete=models.CASCADE, related_name="members")
    full_name = models.CharField(max_length=200)
    username_proposed = models.CharField(max_length=150)
    username_normalized = models.CharField(max_length=150)
    phone_proposed = models.CharField(max_length=32)
    existing_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="request_member_snapshots")
    member_order = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["member_order"]
        constraints = [
            models.UniqueConstraint(fields=["revision", "member_order"], name="gpms_request_member_order_uniq"),
            models.UniqueConstraint(fields=["revision", "username_normalized"], name="gpms_request_member_username_uniq"),
        ]


class RequestSupervisor(UUIDModel):
    class Type(models.TextChoices):
        EXISTING = "existing", "حساب موجود"
        NEW = "new", "مشرف جديد"

    revision = models.OneToOneField(RequestRevision, on_delete=models.CASCADE, related_name="supervisor")
    supervisor_type = models.CharField(max_length=12, choices=Type.choices)
    existing_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="request_supervisor_snapshots")
    full_name = models.CharField(max_length=200, blank=True)
    username_proposed = models.CharField(max_length=150, blank=True)
    username_normalized = models.CharField(max_length=150, blank=True)
    phone_proposed = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    specialty = models.CharField(max_length=200, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.supervisor_type == self.Type.EXISTING and (not self.existing_user_id or self.full_name or self.username_proposed):
            raise ValidationError("يرتبط المشرف الموجود بحساب واحد فقط.")
        if self.supervisor_type == self.Type.NEW and (self.existing_user_id or not self.full_name or not self.username_proposed or not self.phone_proposed):
            raise ValidationError("بيانات المشرف الجديد غير مكتملة أو تحتوي حسابًا موجودًا.")


class RequestDecision(UUIDModel):
    class Decision(models.TextChoices):
        APPROVED = "approved", "اعتماد"
        RETURNED = "returned", "إعادة للتعديل"
        REJECTED = "rejected", "رفض"

    request = models.ForeignKey(GroupRequest, on_delete=models.PROTECT, related_name="decisions")
    revision = models.ForeignKey(RequestRevision, on_delete=models.PROTECT, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="group_request_decisions")
    decision = models.CharField(max_length=12, choices=Decision.choices)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ProjectGroup(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "نشط"
        COMPLETED = "completed", "مكتمل"

    group_code = models.CharField(max_length=48, db_index=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="project_groups")
    academic_year = models.CharField(max_length=16)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    source_request = models.OneToOneField(GroupRequest, on_delete=models.PROTECT, related_name="project_group")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["department", "academic_year", "status"])]


class Project(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "نشط"
        COMPLETED = "completed", "مكتمل"

    group = models.OneToOneField(ProjectGroup, on_delete=models.PROTECT, related_name="project")
    title = models.CharField(max_length=240)
    description = models.TextField()
    repository_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class ProjectAppointment(UUIDModel):
    """A department milestone or a project-specific meeting/deadline."""

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="project_appointments")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name="appointments")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_project_appointments")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, max_length=2000)
    starts_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "title"]


class GroupMember(UUIDModel):
    group = models.ForeignKey(ProjectGroup, on_delete=models.PROTECT, related_name="members")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="group_memberships")
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "student"], condition=Q(left_at__isnull=True), name="gpms_group_member_current_uniq"),
            models.UniqueConstraint(fields=["student"], condition=Q(left_at__isnull=True), name="gpms_student_one_active_group_uniq"),
        ]
        indexes = [models.Index(fields=["group", "left_at"])]


class ProjectSupervisor(UUIDModel):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="supervisor_assignments")
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="supervisor_assignments")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project"], condition=Q(ended_at__isnull=True), name="gpms_project_current_supervisor_uniq")]


class Deliverable(UUIDModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "مقدم"
        REVIEWED = "reviewed", "تمت مراجعته"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="deliverables")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deliverables")
    storage_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    media_type = models.CharField(max_length=120)
    size_bytes = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUBMITTED)
    created_at = models.DateTimeField(auto_now_add=True)


class ProjectNote(UUIDModel):
    class Visibility(models.TextChoices):
        TEAM = "team", "الفريق والمشرف"
        STAFF = "staff", "الإدارة والمشرف"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_notes")
    body = models.TextField()
    visibility = models.CharField(max_length=12, choices=Visibility.choices, default=Visibility.TEAM)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditLog(UUIDModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    action = models.CharField(max_length=80, db_index=True)
    entity_type = models.CharField(max_length=80)
    entity_id = models.UUIDField(null=True, blank=True, db_index=True)
    request = models.ForeignKey(GroupRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    safe_metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]


class OneTimeToken(UUIDModel):
    class Purpose(models.TextChoices):
        ACTIVATE = "activate", "تفعيل حساب"
        RESET_PASSWORD = "reset_password", "إعادة تعيين كلمة المرور"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="one_time_tokens")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class OutboxEvent(UUIDModel):
    event_type = models.CharField(max_length=80, db_index=True)
    aggregate_id = models.UUIDField()
    safe_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

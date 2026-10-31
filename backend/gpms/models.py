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
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
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
        PENDING = "pending_approval", "بانتظار اعتماد رئيس القسم"
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
    left_reason = models.TextField(blank=True, max_length=2000)
    is_leader = models.BooleanField(default=False)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="group_membership_changes")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "student"], condition=Q(left_at__isnull=True), name="gpms_group_member_current_uniq"),
            models.UniqueConstraint(fields=["student"], condition=Q(left_at__isnull=True), name="gpms_student_one_active_group_uniq"),
            models.UniqueConstraint(fields=["group"], condition=Q(left_at__isnull=True, is_leader=True), name="gpms_group_one_active_leader_uniq"),
        ]
        indexes = [models.Index(fields=["group", "left_at"])]


class ProjectSupervisor(UUIDModel):
    class EndType(models.TextChoices):
        REASSIGNED = "reassigned", "إعادة إسناد"
        DECLINED = "declined", "اعتذار المشرف"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="supervisor_assignments")
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="supervisor_assignments")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="ended_supervisor_assignments")
    end_type = models.CharField(max_length=16, choices=EndType.choices, blank=True)
    end_reason = models.TextField(blank=True, max_length=2000)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project"], condition=Q(ended_at__isnull=True), name="gpms_project_current_supervisor_uniq")]


class ProjectPlan(UUIDModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "بانتظار مراجعة المشرف"
        CHANGES_REQUESTED = "changes_requested", "تحتاج تعديلات"
        APPROVED = "approved", "معتمدة"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="plans")
    version = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=240)
    objectives = models.TextField(max_length=5000)
    scope = models.TextField(max_length=5000)
    methodology = models.TextField(max_length=5000)
    tools = models.TextField(max_length=3000, blank=True)
    task_assignments = models.TextField(max_length=5000)
    timeline = models.TextField(max_length=5000)
    risks = models.TextField(max_length=5000)
    expected_outputs = models.TextField(max_length=5000)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_project_plans")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    review_note = models.TextField(blank=True, max_length=3000)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_project_plans")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="gpms_project_plan_version_uniq")]


class ProjectCommittee(UUIDModel):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "بانتظار اعتماد العميد"
        APPROVED = "approved", "معتمدة"

    department = models.OneToOneField(Department, on_delete=models.CASCADE, related_name="project_committee")
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="proposed_project_committees")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING_APPROVAL, db_index=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_project_committees")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectCommitteeMember(UUIDModel):
    committee = models.ForeignKey(ProjectCommittee, on_delete=models.CASCADE, related_name="members")
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_committee_memberships")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["committee", "supervisor"], name="gpms_project_committee_member_uniq")]


class ProjectIdeaRevision(UUIDModel):
    class Status(models.TextChoices):
        SUPERVISOR_REVIEW = "supervisor_review", "مراجعة المشرف"
        COMMITTEE_REVIEW = "committee_review", "مراجعة اللجنة"
        CHAIR_REVIEW = "chair_review", "قرار رئيس القسم"
        CHANGES_REQUESTED = "changes_requested", "تحتاج تعديلات"
        APPROVED = "approved", "معتمدة"
        REJECTED = "rejected", "مرفوضة"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="idea_revisions")
    version = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=240)
    problem = models.TextField(max_length=5000)
    objectives = models.TextField(max_length=5000)
    proposed_solution = models.TextField(max_length=5000)
    novelty = models.TextField(max_length=5000)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_ideas")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUPERVISOR_REVIEW, db_index=True)
    supervisor_note = models.TextField(blank=True, max_length=3000)
    supervisor_reviewed_at = models.DateTimeField(null=True, blank=True)
    chair_note = models.TextField(blank=True, max_length=3000)
    chair_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="gpms_project_idea_version_uniq")]


class ProjectIdeaCommitteeReview(UUIDModel):
    class Recommendation(models.TextChoices):
        RECOMMEND = "recommend", "يوصي بالاعتماد"
        CHANGES = "changes", "يوصي بالتعديل"
        NOT_SUITABLE = "not_suitable", "لا يوصي بالاعتماد"

    idea = models.ForeignKey(ProjectIdeaRevision, on_delete=models.CASCADE, related_name="committee_reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_idea_reviews")
    recommendation = models.CharField(max_length=24, choices=Recommendation.choices)
    note = models.TextField(blank=True, max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["idea", "reviewer"], name="gpms_project_idea_reviewer_uniq")]


class DiscussionReadinessRequest(UUIDModel):
    class Status(models.TextChoices):
        SUPERVISOR_REVIEW = "supervisor_review", "مراجعة المشرف"
        CHANGES_REQUESTED = "changes_requested", "تحتاج تعديلات"
        CHAIR_REVIEW = "chair_review", "مراجعة رئيس القسم"
        REFERRED = "referred", "محالة لتشكيل لجنة المناقشة"
        REJECTED = "rejected", "مرفوضة"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="discussion_readiness_requests")
    version = models.PositiveSmallIntegerField()
    final_deliverable = models.ForeignKey("Deliverable", on_delete=models.PROTECT, related_name="readiness_final_requests")
    report_deliverable = models.ForeignKey("Deliverable", on_delete=models.PROTECT, related_name="readiness_report_requests")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="discussion_readiness_submissions")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUPERVISOR_REVIEW, db_index=True)
    supervisor_note = models.TextField(blank=True, max_length=3000)
    supervisor_reviewed_at = models.DateTimeField(null=True, blank=True)
    chair_note = models.TextField(blank=True, max_length=3000)
    chair_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="gpms_readiness_project_version_uniq")]


class DefenseCommittee(UUIDModel):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "بانتظار اعتماد العميد"
        APPROVED = "approved", "معتمدة"

    readiness_request = models.OneToOneField(DiscussionReadinessRequest, on_delete=models.CASCADE, related_name="defense_committee")
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="proposed_defense_committees")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_defense_committees")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING_APPROVAL, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    defense_at = models.DateTimeField(null=True, blank=True)
    defense_location = models.CharField(max_length=240, blank=True)
    minutes = models.TextField(blank=True, max_length=12000)
    minutes_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="recorded_defense_minutes")
    minutes_recorded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DefenseCommitteeMember(UUIDModel):
    committee = models.ForeignKey(DefenseCommittee, on_delete=models.CASCADE, related_name="members")
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="defense_committee_memberships")
    is_chair = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["committee", "supervisor"], name="gpms_defense_committee_member_uniq"),
            models.UniqueConstraint(fields=["committee"], condition=Q(is_chair=True), name="gpms_defense_committee_one_chair"),
        ]


class DefenseRubricCriterion(UUIDModel):
    class Scope(models.TextChoices):
        PROJECT = "project", "تقييم جماعي للمشروع"
        STUDENT = "student", "تقييم فردي للطالب"

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, max_length=2000)
    scope = models.CharField(max_length=12, choices=Scope.choices)
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="updated_defense_rubric_criteria")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "position", "id"]


class DefenseCommitteeCriterion(UUIDModel):
    """Immutable criterion snapshot attached when the dean approves a panel."""
    committee = models.ForeignKey(DefenseCommittee, on_delete=models.CASCADE, related_name="rubric")
    source_criterion_id = models.UUIDField()
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, max_length=2000)
    scope = models.CharField(max_length=12, choices=DefenseRubricCriterion.Scope.choices)
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["scope", "position", "id"]
        constraints = [models.UniqueConstraint(fields=["committee", "source_criterion_id"], name="gpms_defense_snapshot_source_uniq")]


class DefenseEvaluation(UUIDModel):
    committee = models.ForeignKey(DefenseCommittee, on_delete=models.PROTECT, related_name="evaluations")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="defense_evaluations")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["committee", "reviewer"], name="gpms_defense_evaluation_reviewer_uniq")]


class DefenseEvaluationScore(UUIDModel):
    evaluation = models.ForeignKey(DefenseEvaluation, on_delete=models.CASCADE, related_name="scores")
    criterion = models.ForeignKey(DefenseCommitteeCriterion, on_delete=models.PROTECT, related_name="scores")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="defense_score_rows")
    score = models.DecimalField(max_digits=5, decimal_places=2)
    note = models.TextField(blank=True, max_length=2000)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "criterion"], condition=Q(student__isnull=True), name="gpms_defense_group_score_uniq"),
            models.UniqueConstraint(fields=["evaluation", "criterion", "student"], condition=Q(student__isnull=False), name="gpms_defense_student_score_uniq"),
            models.CheckConstraint(condition=Q(score__gte=0) & Q(score__lte=100), name="gpms_defense_score_0_100"),
        ]


class PostDefenseRevision(UUIDModel):
    class Status(models.TextChoices):
        OPEN = "open", "مطلوب تنفيذها"
        SUBMITTED = "submitted", "بانتظار مراجعة المشرف"
        CHANGES_REQUESTED = "changes_requested", "تحتاج استكمالًا"
        APPROVED = "approved", "معتمدة"

    committee = models.ForeignKey(DefenseCommittee, on_delete=models.PROTECT, related_name="post_defense_revisions")
    description = models.TextField(max_length=3000)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_post_defense_revisions")
    due_at = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    evidence = models.ForeignKey("Deliverable", null=True, blank=True, on_delete=models.PROTECT, related_name="post_defense_revision_evidence")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_post_defense_revisions")
    supervisor_note = models.TextField(blank=True, max_length=3000)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_post_defense_revisions")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PostDefenseFinalSubmission(UUIDModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "بانتظار الاعتماد الفني"
        CHANGES_REQUESTED = "changes_requested", "تحتاج استكمالًا"
        APPROVED = "approved", "معتمدة فنيًا"

    committee = models.ForeignKey(DefenseCommittee, on_delete=models.PROTECT, related_name="final_submissions")
    version = models.PositiveSmallIntegerField()
    deliverable = models.ForeignKey("Deliverable", on_delete=models.PROTECT, related_name="post_defense_final_submissions")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="post_defense_final_submissions")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    supervisor_note = models.TextField(blank=True, max_length=3000)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_post_defense_final_submissions")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["committee", "version"], name="gpms_post_defense_final_version_uniq")]


class ProjectStage(UUIDModel):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "لم تبدأ"
        IN_PROGRESS = "in_progress", "قيد التنفيذ"
        SUBMITTED = "submitted", "بانتظار المراجعة"
        CHANGES_REQUESTED = "changes_requested", "تحتاج تعديلات"
        APPROVED = "approved", "معتمدة"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, max_length=2000)
    starts_at = models.DateField(null=True, blank=True)
    due_at = models.DateField(null=True, blank=True)
    is_required = models.BooleanField(default=True)
    progress = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NOT_STARTED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["project", "order"], name="gpms_project_stage_order_uniq")]


class ProjectStageReview(UUIDModel):
    class Action(models.TextChoices):
        SUBMITTED = "submitted", "إرسال للمراجعة"
        APPROVED = "approved", "اعتماد المرحلة"
        CHANGES_REQUESTED = "changes_requested", "طلب تعديلات"

    stage = models.ForeignKey(ProjectStage, on_delete=models.CASCADE, related_name="reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stage_reviews")
    action = models.CharField(max_length=24, choices=Action.choices)
    note = models.TextField(blank=True, max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ProjectTask(UUIDModel):
    class Status(models.TextChoices):
        TODO = "todo", "لم تبدأ"
        IN_PROGRESS = "in_progress", "قيد التنفيذ"
        COMPLETED = "completed", "مكتملة"

    stage = models.ForeignKey(ProjectStage, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, max_length=2000)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="project_tasks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_project_tasks")
    due_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TODO, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at", "created_at"]


class Notification(UUIDModel):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="issued_notifications")
    event_type = models.CharField(max_length=80, db_index=True)
    title = models.CharField(max_length=180)
    body = models.CharField(max_length=500, blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Deliverable(UUIDModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "مقدم"
        REVIEWED = "reviewed", "تمت مراجعته"

    class Visibility(models.TextChoices):
        SHARED = "shared", "مشترك مع الفريق"
        PERSONAL = "personal", "شخصي"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="deliverables")
    stage = models.ForeignKey(ProjectStage, null=True, blank=True, on_delete=models.SET_NULL, related_name="deliverables")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deliverables")
    storage_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    media_type = models.CharField(max_length=120)
    size_bytes = models.PositiveBigIntegerField()
    visibility = models.CharField(max_length=12, choices=Visibility.choices, default=Visibility.SHARED, db_index=True)
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

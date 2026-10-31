from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .models import DefenseCommittee, DefenseRubricCriterion, Department, Deliverable, DiscussionReadinessRequest, GroupMember, GroupRequest, Notification, Project, ProjectAppointment, ProjectCommittee, ProjectCommitteeMember, ProjectGroup, ProjectIdeaCommitteeReview, ProjectIdeaRevision, ProjectNote, ProjectPlan, ProjectStage, ProjectStageReview, ProjectSupervisor, ProjectTask, RequestDecision, RequestMember, RequestRevision, RequestSupervisor, StudentProfile, SupervisorProfile, User


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "code", "name"]


class StudentInputSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200, trim_whitespace=True)
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    phone = serializers.CharField(max_length=32, trim_whitespace=True)
    existing_user_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs["full_name"] or not attrs["username"] or not attrs["phone"]:
            raise serializers.ValidationError("الاسم واسم المستخدم ورقم الجوال مطلوبة لكل طالب.")
        account_id = attrs.get("existing_user_id")
        if account_id:
            account = User.objects.filter(id=account_id, role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE).first()
            profile = StudentProfile.objects.filter(user_id=account_id).first()
            is_match = bool(account and profile and account.username_normalized == attrs["username"].casefold() and account.phone == attrs["phone"] and profile.full_name.strip().casefold() == attrs["full_name"].strip().casefold())
            if not is_match:
                raise serializers.ValidationError("تعذر التحقق من بيانات الطالب للحساب الموجود.")
        return attrs


class SupervisorInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["existing", "new"])
    existing_user_id = serializers.UUIDField(required=False, allow_null=True)
    full_name = serializers.CharField(max_length=200, required=False, allow_blank=True, trim_whitespace=True)
    username = serializers.CharField(max_length=150, required=False, allow_blank=True, trim_whitespace=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, trim_whitespace=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    specialty = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["kind"] == "existing":
            account_id = attrs.get("existing_user_id")
            account = User.objects.filter(id=account_id, role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE).first() if account_id else None
            if not account:
                raise serializers.ValidationError("تعذر التحقق من حساب المشرف المختار.")
            profile = getattr(account, "supervisor_profile", None)
            attrs["full_name"] = profile.full_name if profile and profile.full_name.strip() else account.username
            attrs["username"] = account.username
        else:
            if attrs.get("existing_user_id") or not all(attrs.get(key) for key in ("full_name", "username", "phone")):
                raise serializers.ValidationError("اسم المشرف واسم المستخدم ورقم الجوال مطلوبة للمشرف الجديد.")
        return attrs


class RevisionInputSerializer(serializers.Serializer):
    group_code = serializers.CharField(max_length=48, trim_whitespace=True)
    project_title = serializers.CharField(max_length=240, trim_whitespace=True)
    project_description = serializers.CharField(trim_whitespace=True)
    academic_year = serializers.CharField(max_length=16, trim_whitespace=True)
    department_id = serializers.UUIDField()
    members = StudentInputSerializer(many=True, allow_empty=False)
    supervisor = SupervisorInputSerializer()

    def validate(self, attrs):
        code = attrs["group_code"].strip()
        title = attrs["project_title"].strip()
        description = attrs["project_description"].strip()
        year = attrs["academic_year"].strip()
        if not code or not title or not description or not year:
            raise serializers.ValidationError("رمز المجموعة والعنوان والوصف والعام الدراسي مطلوبة.")
        if not Department.objects.filter(id=attrs["department_id"], is_active=True).exists():
            raise serializers.ValidationError({"department_id": "القسم غير متاح أو غير موجود."})
        usernames = [member["username"].casefold() for member in attrs["members"]]
        if len(usernames) != len(set(usernames)):
            raise serializers.ValidationError({"members": "أسماء المستخدمين مكررة داخل الطلب."})
        supervisor = attrs["supervisor"]
        if supervisor["kind"] == "new" and supervisor["username"].casefold() in usernames:
            raise serializers.ValidationError({"supervisor": "اسم مستخدم المشرف مكرر بين أعضاء الطلب."})
        return attrs


class RequestMemberReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestMember
        fields = ["id", "full_name", "username_proposed", "phone_proposed", "member_order", "existing_user_id"]


class RequestSupervisorReadSerializer(serializers.ModelSerializer):
    existing_user_id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        if obj.supervisor_type == RequestSupervisor.Type.EXISTING and obj.existing_user_id:
            profile = getattr(obj.existing_user, "supervisor_profile", None)
            return profile.full_name if profile else obj.existing_user.username
        return obj.full_name

    class Meta:
        model = RequestSupervisor
        fields = ["supervisor_type", "existing_user_id", "full_name", "username_proposed", "phone_proposed", "email", "specialty"]


class RequestRevisionReadSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    members = RequestMemberReadSerializer(many=True, read_only=True)
    supervisor = RequestSupervisorReadSerializer(read_only=True)

    class Meta:
        model = RequestRevision
        fields = ["id", "revision_number", "group_code_proposed", "project_title", "project_description", "academic_year", "department", "members", "supervisor", "created_at", "submitted_at"]


class RequestDecisionReadSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = RequestDecision
        fields = ["id", "revision_id", "actor_name", "decision", "note", "created_at"]


class GroupRequestReadSerializer(serializers.ModelSerializer):
    current_revision = RequestRevisionReadSerializer(read_only=True)
    decisions = RequestDecisionReadSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = GroupRequest
        fields = ["id", "status", "created_by_name", "current_revision", "decisions", "created_at", "updated_at", "submitted_at", "closed_at", "version"]


class ProjectGroupReadSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)

    class Meta:
        model = ProjectGroup
        fields = ["id", "group_code", "department", "academic_year", "status", "created_at", "completed_at"]


class GroupMemberReadSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="student.student_profile.full_name", read_only=True)
    username = serializers.CharField(source="student.username", read_only=True)
    student_id = serializers.UUIDField(source="student.id", read_only=True)
    last_activity_at = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()

    def get_last_activity_at(self, obj):
        return obj.student.last_activity_at if obj.left_at is None else None

    def get_is_online(self, obj):
        last_activity = self.get_last_activity_at(obj)
        return bool(last_activity and last_activity >= timezone.now() - timedelta(minutes=5))

    class Meta:
        model = GroupMember
        fields = ["id", "student_id", "full_name", "username", "is_leader", "joined_at", "left_at", "left_reason", "changed_by", "is_online", "last_activity_at"]


class ProjectSupervisorReadSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="supervisor.supervisor_profile.full_name", read_only=True)
    supervisor_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ProjectSupervisor
        fields = ["id", "supervisor_id", "full_name", "started_at", "ended_at", "ended_by", "end_type", "end_reason"]


class GroupDetailReadSerializer(ProjectGroupReadSerializer):
    members = GroupMemberReadSerializer(many=True, read_only=True)
    project_id = serializers.UUIDField(source="project.id", read_only=True)
    project_title = serializers.CharField(source="project.title", read_only=True)
    project_status = serializers.CharField(source="project.status", read_only=True)
    supervisors = ProjectSupervisorReadSerializer(source="project.supervisor_assignments", many=True, read_only=True)

    class Meta(ProjectGroupReadSerializer.Meta):
        fields = ProjectGroupReadSerializer.Meta.fields + ["members", "project_id", "project_title", "project_status", "supervisors"]


class ProjectReadSerializer(serializers.ModelSerializer):
    group = GroupDetailReadSerializer(read_only=True)

    class Meta:
        model = Project
        fields = ["id", "group", "title", "description", "repository_url", "status", "created_at", "completed_at"]


class ProjectRepositorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["repository_url"]

    def validate_repository_url(self, value):
        from urllib.parse import urlparse

        value = value.strip()
        if not value:
            return ""
        parsed = urlparse(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise serializers.ValidationError("رابط المنفذ غير صالح.") from exc
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"} or parsed.username or parsed.password or port:
            raise serializers.ValidationError("أدخل رابط مستودع GitHub يبدأ بـ https://github.com/.")
        parts = [part for part in parsed.path.split("/") if part]
        import re

        if len(parts) != 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."} for part in parts) or parsed.query or parsed.fragment:
            raise serializers.ValidationError("يجب أن يشير الرابط إلى مستودع واحد بصيغة github.com/owner/repository.")
        return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}"


class ProjectPlanSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source="submitted_by.username", read_only=True)
    reviewed_by_name = serializers.CharField(source="reviewed_by.username", read_only=True, allow_null=True)

    class Meta:
        model = ProjectPlan
        fields = ["id", "version", "title", "objectives", "scope", "methodology", "tools", "task_assignments", "timeline", "risks", "expected_outputs", "submitted_by_name", "status", "review_note", "reviewed_by_name", "reviewed_at", "created_at"]
        read_only_fields = fields


class ProjectCommitteeSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    member_ids = serializers.SerializerMethodField()
    member_names = serializers.SerializerMethodField()

    def get_member_ids(self, obj):
        return list(obj.members.order_by("supervisor_id").values_list("supervisor_id", flat=True))

    def get_member_names(self, obj):
        return [member.supervisor.supervisor_profile.full_name if hasattr(member.supervisor, "supervisor_profile") else member.supervisor.username for member in obj.members.select_related("supervisor__supervisor_profile").order_by("supervisor_id")]

    class Meta:
        model = ProjectCommittee
        fields = ["id", "department", "department_name", "status", "member_ids", "member_names", "approved_at", "created_at", "updated_at"]
        read_only_fields = fields


class ProjectIdeaCommitteeReviewSerializer(serializers.ModelSerializer):
    reviewer_id = serializers.UUIDField(read_only=True)
    reviewer_name = serializers.CharField(source="reviewer.supervisor_profile.full_name", read_only=True)

    class Meta:
        model = ProjectIdeaCommitteeReview
        fields = ["id", "reviewer_id", "reviewer_name", "recommendation", "note", "created_at", "updated_at"]
        read_only_fields = fields


class ProjectIdeaRevisionSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source="submitted_by.username", read_only=True)
    project_id = serializers.UUIDField(read_only=True)
    project_title = serializers.CharField(source="project.title", read_only=True)
    department_name = serializers.CharField(source="project.group.department.name", read_only=True)
    committee_reviews = ProjectIdeaCommitteeReviewSerializer(many=True, read_only=True)

    class Meta:
        model = ProjectIdeaRevision
        fields = ["id", "project_id", "project_title", "department_name", "version", "title", "problem", "objectives", "proposed_solution", "novelty", "submitted_by_name", "status", "supervisor_note", "supervisor_reviewed_at", "committee_reviews", "chair_note", "chair_reviewed_at", "created_at"]
        read_only_fields = fields


class DiscussionReadinessSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source="submitted_by.username", read_only=True)
    final_filename = serializers.CharField(source="final_deliverable.original_filename", read_only=True)
    report_filename = serializers.CharField(source="report_deliverable.original_filename", read_only=True)

    class Meta:
        model = DiscussionReadinessRequest
        fields = ["id", "version", "final_deliverable", "final_filename", "report_deliverable", "report_filename", "submitted_by_name", "status", "supervisor_note", "supervisor_reviewed_at", "chair_note", "chair_reviewed_at", "created_at"]
        read_only_fields = fields


class DefenseCommitteeSerializer(serializers.ModelSerializer):
    readiness_request_id = serializers.UUIDField(read_only=True)
    project_id = serializers.UUIDField(source="readiness_request.project_id", read_only=True)
    project_title = serializers.CharField(source="readiness_request.project.title", read_only=True)
    department_name = serializers.CharField(source="readiness_request.project.group.department.name", read_only=True)
    final_deliverable = serializers.UUIDField(source="readiness_request.final_deliverable_id", read_only=True)
    final_filename = serializers.CharField(source="readiness_request.final_deliverable.original_filename", read_only=True)
    report_deliverable = serializers.UUIDField(source="readiness_request.report_deliverable_id", read_only=True)
    report_filename = serializers.CharField(source="readiness_request.report_deliverable.original_filename", read_only=True)
    members = serializers.SerializerMethodField()

    def get_members(self, obj):
        return [{
            "id": str(member.supervisor_id),
            "name": member.supervisor.supervisor_profile.full_name if hasattr(member.supervisor, "supervisor_profile") else member.supervisor.username,
            "is_chair": member.is_chair,
        } for member in obj.members.select_related("supervisor__supervisor_profile").order_by("-is_chair", "supervisor_id")]

    class Meta:
        model = DefenseCommittee
        fields = ["id", "readiness_request_id", "project_id", "project_title", "department_name", "final_deliverable", "final_filename", "report_deliverable", "report_filename", "status", "members", "approved_at", "defense_at", "defense_location", "minutes", "minutes_recorded_by", "minutes_recorded_at", "created_at"]
        read_only_fields = fields


class DefenseRubricCriterionSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source="updated_by.username", read_only=True)

    class Meta:
        model = DefenseRubricCriterion
        fields = ["id", "title", "description", "scope", "weight", "position", "is_active", "updated_by_name", "updated_at"]
        read_only_fields = ["id", "updated_by_name", "updated_at"]


class ProjectAppointmentSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    project_title = serializers.CharField(source="project.title", read_only=True, allow_null=True)

    class Meta:
        model = ProjectAppointment
        fields = ["id", "department", "project", "project_title", "title", "description", "starts_at", "created_at", "updated_at"]
        read_only_fields = ["id", "department", "project_title", "created_at", "updated_at"]


class ProjectNoteReadSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = ProjectNote
        fields = ["id", "author_name", "body", "visibility", "created_at", "updated_at"]


class DeliverableReadSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.username", read_only=True)
    stage_title = serializers.CharField(source="stage.title", read_only=True, allow_null=True)

    class Meta:
        model = Deliverable
        fields = ["id", "uploaded_by_name", "stage", "stage_title", "original_filename", "media_type", "size_bytes", "visibility", "status", "created_at"]


class ProjectStageReviewSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = ProjectStageReview
        fields = ["id", "actor_name", "action", "note", "created_at"]


class ProjectStageSerializer(serializers.ModelSerializer):
    reviews = ProjectStageReviewSerializer(many=True, read_only=True)

    class Meta:
        model = ProjectStage
        fields = ["id", "order", "title", "description", "starts_at", "due_at", "is_required", "progress", "status", "reviews"]
        read_only_fields = ["id", "order", "is_required", "progress", "status", "reviews"]

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        due_at = attrs.get("due_at", getattr(self.instance, "due_at", None))
        if starts_at and due_at and due_at < starts_at:
            raise serializers.ValidationError({"due_at": "يجب أن يكون موعد النهاية بعد البداية أو مساويًا لها."})
        return attrs


class ProjectTaskReadSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source="assigned_to.username", read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    stage_title = serializers.CharField(source="stage.title", read_only=True)

    class Meta:
        model = ProjectTask
        fields = ["id", "stage", "stage_title", "title", "description", "assigned_to", "assigned_to_name", "created_by_name", "due_at", "status", "created_at", "updated_at"]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True, allow_null=True)

    class Meta:
        model = Notification
        fields = ["id", "event_type", "title", "body", "target_url", "actor_name", "read_at", "created_at"]
        read_only_fields = fields

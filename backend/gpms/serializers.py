from rest_framework import serializers

from .models import Department, GroupMember, GroupRequest, Project, ProjectGroup, ProjectNote, ProjectSupervisor, RequestDecision, RequestMember, RequestRevision, RequestSupervisor, StudentProfile, SupervisorProfile, User


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
            attrs["full_name"] = account.supervisor_profile.full_name
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

    class Meta:
        model = GroupMember
        fields = ["id", "full_name", "joined_at"]


class ProjectSupervisorReadSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="supervisor.supervisor_profile.full_name", read_only=True)

    class Meta:
        model = ProjectSupervisor
        fields = ["id", "full_name", "started_at", "ended_at"]


class GroupDetailReadSerializer(ProjectGroupReadSerializer):
    members = GroupMemberReadSerializer(many=True, read_only=True)
    project_id = serializers.UUIDField(source="project.id", read_only=True)
    project_title = serializers.CharField(source="project.title", read_only=True)
    project_status = serializers.CharField(source="project.status", read_only=True)
    supervisors = ProjectSupervisorReadSerializer(source="project.supervisor_assignments", many=True, read_only=True)

    class Meta(ProjectGroupReadSerializer.Meta):
        fields = ProjectGroupReadSerializer.Meta.fields + ["members", "project_id", "project_title", "project_status", "supervisors"]


class ProjectReadSerializer(serializers.ModelSerializer):
    group = ProjectGroupReadSerializer(read_only=True)

    class Meta:
        model = Project
        fields = ["id", "group", "title", "description", "status", "created_at", "completed_at"]


class ProjectNoteReadSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = ProjectNote
        fields = ["id", "author_name", "body", "visibility", "created_at", "updated_at"]

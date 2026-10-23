from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import AuditLog, Department, GroupMember, GroupRequest, OneTimeToken, OutboxEvent, Project, ProjectGroup, ProjectNote, ProjectSupervisor, RequestDecision, RequestSupervisor, StudentProfile, SupervisorProfile, User
from .tokens import issue_token


class GpmsApiTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="CS", name="علوم الحاسب")
        self.other_department = Department.objects.create(code="IS", name="نظم المعلومات")
        self.chair = User.objects.create_user(username="chair.demo", password="ChairPassword-Long-97!", role=User.Role.DEPARTMENT_CHAIR, department=self.department)
        self.other_chair = User.objects.create_user(username="other.chair", password="OtherPassword-Long-97!", role=User.Role.DEPARTMENT_CHAIR, department=self.other_department)
        self.dean = User.objects.create_user(username="dean.demo", password="DeanPassword-Long-97!", role=User.Role.DEAN)
        self.supervisor = User.objects.create_user(username="supervisor.demo", password="SupervisorPassword-97!", role=User.Role.SUPERVISOR)
        SupervisorProfile.objects.create(user=self.supervisor, full_name="د. مشرف تجريبي")
        self.student = User.objects.create_user(username="student.existing", password="StudentPassword-97!", role=User.Role.STUDENT, phone="0501000000")
        StudentProfile.objects.create(user=self.student, full_name="طالب موجود")
        self.client = APIClient()

    def payload(self, code="GP-T-1", student_username="student.new"):
        return {
            "group_code": code,
            "project_title": "مشروع اختبار",
            "project_description": "وصف مشروع اختباري للتحقق من الخدمات.",
            "academic_year": "2026–2027",
            "department_id": str(self.department.id),
            "members": [{"full_name": "طالب جديد", "username": student_username, "phone": "0502000000"}],
            "supervisor": {"kind": "existing", "existing_user_id": str(self.supervisor.id)},
        }

    def make_pending(self, code="GP-T-1", student_username="student.new"):
        self.client.force_authenticate(self.chair)
        response = self.client.post("/api/v1/group-requests/", self.payload(code, student_username), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        request_id = response.data["id"]
        submit = self.client.post(f"/api/v1/group-requests/{request_id}/submit/", {"version": response.data["version"]}, format="json")
        self.assertEqual(submit.status_code, 200, submit.data)
        self.assertEqual(submit.data["status"], GroupRequest.Status.PENDING)
        return request_id

    def test_anonymous_request_is_rejected(self):
        response = self.client.get("/api/v1/group-requests/")
        self.assertEqual(response.status_code, 403)

    def test_login_is_case_insensitive_and_inactive_accounts_cannot_login(self):
        response = self.client.post("/api/v1/auth/login/", {"identifier": "CHAIR.DEMO", "password": "ChairPassword-Long-97!"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["user"]["role"], User.Role.DEPARTMENT_CHAIR)
        pending = User(username="pending.demo", role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVATION_PENDING)
        pending.set_unusable_password()
        pending.save()
        response = self.client.post("/api/v1/auth/login/", {"identifier": "pending.demo", "password": "anything"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "بيانات الدخول غير صحيحة.")

    def test_chair_can_create_and_submit_one_complete_request(self):
        self.client.force_authenticate(self.chair)
        response = self.client.post("/api/v1/group-requests/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], GroupRequest.Status.DRAFT)
        self.assertEqual(len(response.data["current_revision"]["members"]), 1)
        self.assertFalse(ProjectGroup.objects.exists())
        submit = self.client.post(f"/api/v1/group-requests/{response.data['id']}/submit/", {"version": response.data["version"]}, format="json")
        self.assertEqual(submit.status_code, 200, submit.data)
        self.assertEqual(submit.data["status"], GroupRequest.Status.PENDING)
        self.assertFalse(GroupMember.objects.exists())

    def test_duplicate_usernames_in_request_are_rejected(self):
        self.client.force_authenticate(self.chair)
        payload = self.payload()
        payload["members"].append({"full_name": "عضو ثان", "username": "STUDENT.NEW", "phone": "0502000001"})
        response = self.client.post("/api/v1/group-requests/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_chair_cannot_create_request_for_another_department(self):
        self.client.force_authenticate(self.chair)
        payload = self.payload()
        payload["department_id"] = str(self.other_department.id)
        response = self.client.post("/api/v1/group-requests/", payload, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(GroupRequest.objects.exists())

    def test_request_visibility_is_scoped_to_department_chair(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.other_chair)
        self.assertEqual(self.client.get("/api/v1/group-requests/").data, [])
        self.assertEqual(self.client.get(f"/api/v1/group-requests/{request_id}/").status_code, 404)

    def test_returned_request_can_be_edited_and_resubmitted_but_not_submitted_twice(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        returned = self.client.post(f"/api/v1/group-requests/{request_id}/return/", {"note": "يرجى توضيح أهداف المشروع."}, format="json")
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(returned.data["status"], GroupRequest.Status.RETURNED)

        self.client.force_authenticate(self.chair)
        changed = self.payload(code="GP-T-1", student_username="student.new")
        changed["project_title"] = "عنوان بعد التعديل"
        revised = self.client.patch(f"/api/v1/group-requests/{request_id}/", changed, format="json")
        self.assertEqual(revised.status_code, 200, revised.data)
        self.assertEqual(revised.data["current_revision"]["revision_number"], 2)
        self.assertEqual(revised.data["decisions"][0]["note"], "يرجى توضيح أهداف المشروع.")

        resubmitted = self.client.post(f"/api/v1/group-requests/{request_id}/submit/", {"version": revised.data["version"]}, format="json")
        self.assertEqual(resubmitted.status_code, 200, resubmitted.data)
        self.assertEqual(resubmitted.data["status"], GroupRequest.Status.PENDING)
        duplicate = self.client.post(f"/api/v1/group-requests/{request_id}/submit/", {"version": resubmitted.data["version"]}, format="json")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(GroupRequest.objects.get(id=request_id).revisions.count(), 2)

    def test_rejected_request_is_preserved_and_cannot_be_resubmitted_or_changed(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        rejected = self.client.post(f"/api/v1/group-requests/{request_id}/reject/", {"note": "الموضوع خارج خطة القسم."}, format="json")
        self.assertEqual(rejected.status_code, 200, rejected.data)
        self.assertEqual(rejected.data["status"], GroupRequest.Status.REJECTED)

        self.client.force_authenticate(self.chair)
        duplicate = self.client.post(f"/api/v1/group-requests/{request_id}/submit/", {"version": rejected.data["version"]}, format="json")
        self.assertEqual(duplicate.status_code, 409)
        changed = self.client.patch(f"/api/v1/group-requests/{request_id}/", self.payload(), format="json")
        self.assertEqual(changed.status_code, 409)
        stored = GroupRequest.objects.get(id=request_id)
        self.assertEqual(stored.status, GroupRequest.Status.REJECTED)
        self.assertEqual(stored.decisions.get().note, "الموضوع خارج خطة القسم.")

    def test_all_four_roles_only_see_projects_and_groups_in_their_scope(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        approved = self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        group = ProjectGroup.objects.get(source_request_id=request_id)
        project = Project.objects.get(group=group)
        pending_student = User.objects.get(username="student.new")
        self.client.force_authenticate(pending_student)
        self.assertEqual(self.client.get("/api/v1/projects/").status_code, 403)
        pending_student.account_status = User.AccountStatus.ACTIVE
        pending_student.save(update_fields=["account_status"])
        outsider = User.objects.create_user(username="student.outside", password="StudentPassword-97!", role=User.Role.STUDENT)
        StudentProfile.objects.create(user=outsider, full_name="طالب خارج المشروع")
        other_supervisor = User.objects.create_user(username="supervisor.outside", password="SupervisorPassword-97!", role=User.Role.SUPERVISOR)
        SupervisorProfile.objects.create(user=other_supervisor, full_name="مشرف خارج المشروع")

        expected = {
            self.dean: True,
            self.chair: True,
            self.supervisor: True,
            User.objects.get(username="student.new"): True,
            outsider: False,
            other_supervisor: False,
            self.other_chair: False,
        }
        for user, can_access in expected.items():
            with self.subTest(role=user.role, username=user.username):
                self.client.force_authenticate(user)
                projects = self.client.get("/api/v1/projects/")
                groups = self.client.get("/api/v1/groups/")
                self.assertEqual(projects.status_code, 200, projects.data)
                self.assertEqual(groups.status_code, 200, groups.data)
                self.assertEqual(any(item["id"] == str(project.id) for item in projects.data), can_access)
                self.assertEqual(any(item["id"] == str(group.id) for item in groups.data), can_access)
                detail = self.client.get(f"/api/v1/projects/{project.id}/")
                self.assertEqual(detail.status_code, 200 if can_access else 404)

        for user in (self.supervisor, User.objects.get(username="student.new")):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get("/api/v1/group-requests/").status_code, 403)

    def test_team_notes_are_visible_to_assigned_roles_and_staff_notes_are_hidden(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        ProjectNote.objects.create(project=project, author=self.dean, body="ملاحظة إدارية", visibility=ProjectNote.Visibility.STAFF)

        self.client.force_authenticate(self.supervisor)
        team_note = self.client.post(f"/api/v1/projects/{project.id}/notes/", {"body": "ملاحظة للفريق", "visibility": "team"}, format="json")
        self.assertEqual(team_note.status_code, 201, team_note.data)
        notes = self.client.get(f"/api/v1/projects/{project.id}/notes/")
        self.assertEqual(notes.status_code, 200)
        self.assertEqual([note["body"] for note in notes.data], ["ملاحظة للفريق"])

        student = User.objects.get(username="student.new")
        student.account_status = User.AccountStatus.ACTIVE
        student.save(update_fields=["account_status"])
        self.client.force_authenticate(student)
        self.assertEqual([note["body"] for note in self.client.get(f"/api/v1/projects/{project.id}/notes/").data], ["ملاحظة للفريق"])
        coerced = self.client.post(f"/api/v1/projects/{project.id}/notes/", {"body": "طلب إخفاء غير مسموح", "visibility": "staff"}, format="json")
        self.assertEqual(coerced.status_code, 201, coerced.data)
        self.assertEqual(coerced.data["visibility"], ProjectNote.Visibility.TEAM)

        self.client.force_authenticate(self.dean)
        self.assertEqual(len(self.client.get(f"/api/v1/projects/{project.id}/notes/").data), 3)

        outsider = User.objects.create_user(username="student.unassigned", password="StudentPassword-97!", role=User.Role.STUDENT)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(f"/api/v1/projects/{project.id}/notes/").status_code, 404)

    def test_failure_while_creating_new_supervisor_rolls_back_all_approval_records(self):
        request_id = self.make_pending()
        request = GroupRequest.objects.get(id=request_id)
        revision = request.current_revision
        revision.supervisor.delete()
        RequestSupervisor.objects.create(
            revision=revision,
            supervisor_type=RequestSupervisor.Type.NEW,
            full_name="مشرف جديد",
            username_proposed="supervisor.new",
            username_normalized="supervisor.new",
            phone_proposed="0503000000",
        )
        self.client.force_authenticate(self.dean)
        with patch("gpms.services.SupervisorProfile.objects.create", side_effect=IntegrityError("forced profile failure")):
            response = self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(ProjectGroup.objects.exists())
        self.assertFalse(Project.objects.exists())
        self.assertFalse(GroupMember.objects.exists())
        self.assertFalse(User.objects.filter(username_normalized__in=["student.new", "supervisor.new"]).exists())
        self.assertFalse(OutboxEvent.objects.filter(event_type="account_activation_required").exists())
        request.refresh_from_db()
        self.assertEqual(request.status, GroupRequest.Status.PENDING)
        self.assertFalse(RequestDecision.objects.filter(request=request).exists())

    def test_only_dean_can_make_decisions_and_notes_are_required(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json").status_code, 403)
        self.client.force_authenticate(self.dean)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/return/", {"note": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/reject/", {"note": "سبب اختبار الرفض"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], GroupRequest.Status.REJECTED)
        self.assertEqual(response.data["decisions"][0]["note"], "سبب اختبار الرفض")

    def test_approval_creates_group_project_members_and_inactive_account_atomically(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], GroupRequest.Status.APPROVED)
        group = ProjectGroup.objects.get(source_request_id=request_id)
        project = Project.objects.get(group=group)
        member = GroupMember.objects.get(group=group)
        self.assertEqual(project.title, "مشروع اختبار")
        self.assertEqual(member.student.account_status, User.AccountStatus.ACTIVATION_PENDING)
        self.assertFalse(member.student.is_active)
        self.assertTrue(ProjectSupervisor.objects.filter(project=project, supervisor=self.supervisor).exists())
        self.assertEqual(AuditLog.objects.filter(action="group_request.approved").count(), 1)
        self.assertTrue(OutboxEvent.objects.filter(event_type="account_activation_required").exists())
        self.assertFalse(OneTimeToken.objects.exists())

    def test_approval_integrity_failure_rolls_back_every_created_record(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        with patch("gpms.services.ProjectSupervisor.objects.create", side_effect=IntegrityError("forced test failure")):
            response = self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(ProjectGroup.objects.exists())
        self.assertFalse(Project.objects.exists())
        self.assertFalse(GroupMember.objects.exists())
        self.assertFalse(User.objects.filter(username_normalized="student.new").exists())
        request = GroupRequest.objects.get(id=request_id)
        self.assertEqual(request.status, GroupRequest.Status.PENDING)

    def test_student_cannot_join_two_active_groups(self):
        group_one = ProjectGroup.objects.create(group_code="GP-A", department=self.department, academic_year="2026–2027", source_request=self._bare_approved_request("one"))
        group_two = ProjectGroup.objects.create(group_code="GP-B", department=self.department, academic_year="2026–2027", source_request=self._bare_approved_request("two"))
        GroupMember.objects.create(group=group_one, student=self.student)
        with self.assertRaises(IntegrityError):
            with self.atomic_block():
                GroupMember.objects.create(group=group_two, student=self.student)

    def _bare_approved_request(self, suffix):
        return GroupRequest.objects.create(created_by=self.chair, status=GroupRequest.Status.APPROVED)

    @staticmethod
    def atomic_block():
        from django.db import transaction
        return transaction.atomic()

    def test_activation_token_is_single_use_and_sets_password(self):
        user = User(username="activation.demo", role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVATION_PENDING)
        user.set_unusable_password()
        user.save()
        raw = issue_token(user, OneTimeToken.Purpose.ACTIVATE)
        response = self.client.post("/api/v1/auth/one-time-password/activate/", {"token": raw, "password": "A-new-secure-pass-2026!"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("A-new-secure-pass-2026!"))
        replay = self.client.post("/api/v1/auth/one-time-password/activate/", {"token": raw, "password": "Another-new-secure-pass-2026!"}, format="json")
        self.assertEqual(replay.status_code, 409)

    def test_failed_activation_keeps_account_pending_and_token_available_for_retry(self):
        user = User(username="activation.retry", role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVATION_PENDING)
        user.set_unusable_password()
        user.save()
        raw = issue_token(user, OneTimeToken.Purpose.ACTIVATE)
        invalid = self.client.post("/api/v1/auth/one-time-password/activate/", {"token": raw, "password": "short"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        user.refresh_from_db()
        token = OneTimeToken.objects.get(user=user)
        self.assertFalse(user.is_active)
        self.assertEqual(user.account_status, User.AccountStatus.ACTIVATION_PENDING)
        self.assertIsNone(token.used_at)

        retried = self.client.post("/api/v1/auth/one-time-password/activate/", {"token": raw, "password": "A-secure-activation-pass-2026!"}, format="json")
        self.assertEqual(retried.status_code, 200, retried.data)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_password_reset_request_has_same_public_message_and_queues_no_secret(self):
        existing = self.client.post("/api/v1/auth/password-reset-requests/", {"identifier": "student.existing"}, format="json")
        missing = self.client.post("/api/v1/auth/password-reset-requests/", {"identifier": "nobody.unknown"}, format="json")
        self.assertEqual(existing.data, missing.data)
        event = OutboxEvent.objects.get(event_type="password_reset_requested")
        self.assertEqual(event.safe_payload, {"user_id": str(self.student.id)})

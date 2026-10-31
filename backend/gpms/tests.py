from unittest.mock import patch
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token

from .models import AuditLog, DefenseCommittee, DefenseCommitteeMember, DefenseRubricCriterion, Deliverable, Department, DiscussionReadinessRequest, GroupMember, GroupRequest, Notification, OneTimeToken, OutboxEvent, PostDefenseFinalSubmission, PostDefenseRevision, Project, ProjectAppointment, ProjectCommittee, ProjectGroup, ProjectIdeaRevision, ProjectNote, ProjectPlan, ProjectStage, ProjectStageReview, ProjectSupervisor, ProjectTask, RequestDecision, RequestSupervisor, StudentProfile, SupervisorProfile, User
from .tokens import issue_token


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class GpmsApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.department = Department.objects.create(code="CS", name="علوم الحاسب")
        self.other_department = Department.objects.create(code="IS", name="نظم المعلومات")
        self.chair = User.objects.create_user(username="chair.demo", password="ChairPassword-Long-97!", role=User.Role.DEPARTMENT_CHAIR, department=self.department)
        self.other_chair = User.objects.create_user(username="other.chair", password="OtherPassword-Long-97!", role=User.Role.DEPARTMENT_CHAIR, department=self.other_department)
        self.dean = User.objects.create_user(username="dean.demo", password="DeanPassword-Long-97!", role=User.Role.DEAN)
        self.supervisor = User.objects.create_user(username="supervisor.demo", password="SupervisorPassword-97!", role=User.Role.SUPERVISOR)
        SupervisorProfile.objects.create(user=self.supervisor, full_name="د. مشرف تجريبي")
        self.student = User.objects.create_user(username="student.existing", password="StudentPassword-97!", role=User.Role.STUDENT, phone="0501000000", department=self.department)
        StudentProfile.objects.create(user=self.student, full_name="طالب موجود")
        self.client = APIClient()

    def payload(self, code="GP-T-1", student_username="student.new"):
        return {
            "group_code": code,
            "project_title": "مشروع اختبار",
            "project_description": "وصف مشروع اختباري للتحقق من الخدمات.",
            "academic_year": "2026–2027",
            "department_id": str(self.department.id),
            "members": [
                {"full_name": "طالب موجود", "username": self.student.username, "phone": self.student.phone, "existing_user_id": str(self.student.id)},
                {"full_name": "طالب جديد", "username": student_username, "phone": "0502000000"},
            ],
            "supervisor": {"kind": "existing", "existing_user_id": str(self.supervisor.id)},
        }

    def make_pending(self, code="GP-T-1", student_username="student.new"):
        self.client.force_authenticate(self.student)
        response = self.client.post("/api/v1/group-requests/", self.payload(code, student_username), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        request_id = response.data["id"]
        submit = self.client.post(f"/api/v1/group-requests/{request_id}/submit/", {"version": response.data["version"]}, format="json")
        self.assertEqual(submit.status_code, 200, submit.data)
        self.assertEqual(submit.data["status"], GroupRequest.Status.PENDING)
        return request_id

    def test_anonymous_request_is_rejected(self):
        response = self.client.get("/api/v1/group-requests/")
        self.assertEqual(response.status_code, 401)

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

    @patch("gpms.views.LoginThrottle.get_rate_limit_key", return_value=None)
    def test_five_bad_passwords_lock_account_for_five_minutes_and_success_resets_counter(self, _get_rate_limit_key):
        for _ in range(5):
            response = self.client.post("/api/v1/auth/login/", {"identifier": self.chair.username, "password": "incorrect"}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["detail"], "بيانات الدخول غير صحيحة.")
        self.chair.refresh_from_db()
        self.assertEqual(self.chair.failed_login_attempts, 5)
        self.assertGreater(self.chair.locked_until, timezone.now())
        locked_login = self.client.post("/api/v1/auth/login/", {"identifier": self.chair.username, "password": "ChairPassword-Long-97!"}, format="json")
        self.assertEqual(locked_login.status_code, 400)
        self.chair.locked_until = timezone.now() - timedelta(seconds=1)
        self.chair.save(update_fields=["locked_until"])
        success = self.client.post("/api/v1/auth/login/", {"identifier": self.chair.username, "password": "ChairPassword-Long-97!"}, format="json")
        self.assertEqual(success.status_code, 200, success.data)
        self.chair.refresh_from_db()
        self.assertEqual(self.chair.failed_login_attempts, 0)
        self.assertIsNone(self.chair.locked_until)
        self.assertEqual(AuditLog.objects.filter(actor=self.chair, action="auth.login_failed").count(), 5)

    def test_auth_token_expires_after_fifteen_minutes_idle(self):
        login = self.client.post("/api/v1/auth/login/", {"identifier": self.chair.username, "password": "ChairPassword-Long-97!"}, format="json")
        self.assertEqual(login.status_code, 200, login.data)
        token = Token.objects.get(user=self.chair)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)
        self.chair.refresh_from_db()
        self.chair.last_activity_at = timezone.now() - timedelta(minutes=16)
        self.chair.save(update_fields=["last_activity_at"])
        expired = self.client.get("/api/v1/auth/me/")
        self.assertEqual(expired.status_code, 401)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())
        self.chair.refresh_from_db()
        self.assertIsNone(self.chair.last_activity_at)

    def test_user_directory_is_scoped_to_dean_or_chair_and_omits_phone_numbers(self):
        self.client.force_authenticate(self.dean)
        response = self.client.get("/api/v1/users/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({user["username"] for user in response.data}, {
            "chair.demo", "other.chair", "dean.demo", "supervisor.demo", "student.existing",
        })
        self.assertTrue(all("phone" not in user for user in response.data))

        self.student.department = self.department
        self.student.save(update_fields=["department"])
        self.client.force_authenticate(self.chair)
        scoped = self.client.get("/api/v1/users/")
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual({user["username"] for user in scoped.data}, {"chair.demo", "student.existing"})

    def test_dean_issues_single_use_student_activation_link_without_message_delivery(self):
        pending = User(username="student.awaiting", role=User.Role.STUDENT, department=self.department, account_status=User.AccountStatus.ACTIVATION_PENDING)
        pending.set_unusable_password()
        pending.save()
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.post(f"/api/v1/users/{pending.id}/activation/", {}, format="json").status_code, 403)
        self.client.force_authenticate(self.dean)
        issued = self.client.post(f"/api/v1/users/{pending.id}/activation/", {}, format="json")
        self.assertEqual(issued.status_code, 200, issued.data)
        self.assertEqual(issued.data["username"], pending.username)
        token = issued.data["activation_token"]
        self.assertNotIn(token, OneTimeToken.objects.get(user=pending).token_hash)
        self.assertEqual(issued.data["expires_in_seconds"], 3600)
        activated = self.client.post("/api/v1/auth/one-time-password/activate/", {"token": token, "password": "A-long-unique-student-password-2026!"}, format="json")
        self.assertEqual(activated.status_code, 200, activated.data)
        pending.refresh_from_db()
        self.assertEqual(pending.account_status, User.AccountStatus.ACTIVE)
        self.assertTrue(pending.check_password("A-long-unique-student-password-2026!"))
        self.assertEqual(self.client.post(f"/api/v1/users/{pending.id}/activation/", {}, format="json").status_code, 400)

    def test_student_can_set_only_their_project_github_repository(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        student = User.objects.get(username="student.new")
        student.account_status = User.AccountStatus.ACTIVE
        student.save(update_fields=["account_status"])
        self.client.force_authenticate(student)
        saved = self.client.patch(f"/api/v1/projects/{project.id}/repository/", {"repository_url": "https://github.com/example-team/graduation-app.git"}, format="json")
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data["repository_url"], "https://github.com/example-team/graduation-app")
        self.assertEqual(Project.objects.get(id=project.id).repository_url, saved.data["repository_url"])
        rejected = self.client.patch(f"/api/v1/projects/{project.id}/repository/", {"repository_url": "https://example.com/repo"}, format="json")
        self.assertEqual(rejected.status_code, 400)
        outsider = User.objects.create_user(username="student.outside", password="StudentPassword-97!", role=User.Role.STUDENT)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.patch(f"/api/v1/projects/{project.id}/repository/", {"repository_url": "https://github.com/example-team/other"}, format="json").status_code, 404)

    def test_department_appointments_are_scoped_and_manageable(self):
        self.client.force_authenticate(self.chair)
        created = self.client.post("/api/v1/appointments/", {
            "title": "موعد تسليم الخطة", "description": "رفع الخطة الأولية", "starts_at": "2027-01-15T09:00:00Z",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["department"]["id"], str(self.department.id))
        self.assertEqual(self.client.get("/api/v1/appointments/").data[0]["title"], "موعد تسليم الخطة")
        appointment_id = created.data["id"]
        self.assertTrue(Notification.objects.filter(recipient=self.student, event_type="appointment.created", body="موعد تسليم الخطة").exists())
        updated = self.client.patch(f"/api/v1/appointments/{appointment_id}/", {"title": "موعد تسليم الخطة المعدل"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertTrue(Notification.objects.filter(recipient=self.student, event_type="appointment.updated", body="موعد تسليم الخطة المعدل").exists())
        self.client.force_authenticate(self.other_chair)
        self.assertEqual(self.client.get("/api/v1/appointments/").data, [])
        self.assertEqual(self.client.patch(f"/api/v1/appointments/{appointment_id}/", {"title": "تعديل غير مخول"}, format="json").status_code, 404)
        self.client.force_authenticate(self.chair)
        deleted = self.client.delete(f"/api/v1/appointments/{appointment_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertTrue(Notification.objects.filter(recipient=self.student, event_type="appointment.cancelled", body="موعد تسليم الخطة المعدل").exists())
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post("/api/v1/appointments/", {"title": "موعد طالب", "starts_at": "2027-01-16T09:00:00Z"}, format="json").status_code, 403)

    def test_student_can_create_and_submit_one_complete_request_for_chair_review(self):
        self.client.force_authenticate(self.student)
        response = self.client.post("/api/v1/group-requests/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], GroupRequest.Status.DRAFT)
        self.assertEqual(len(response.data["current_revision"]["members"]), 2)
        self.assertFalse(ProjectGroup.objects.exists())
        submit = self.client.post(f"/api/v1/group-requests/{response.data['id']}/submit/", {"version": response.data["version"]}, format="json")
        self.assertEqual(submit.status_code, 200, submit.data)
        self.assertEqual(submit.data["status"], GroupRequest.Status.PENDING)
        self.assertFalse(GroupMember.objects.exists())

    def test_existing_supervisor_without_profile_does_not_crash_request_creation(self):
        supervisor = User.objects.create_user(
            username="supervisor.no-profile",
            password="SupervisorPassword-Without-Profile-97!",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        payload = self.payload(code="GP-T-NO-PROFILE")
        payload["supervisor"] = {"kind": "existing", "existing_user_id": str(supervisor.id)}

        self.client.force_authenticate(self.student)
        response = self.client.post("/api/v1/group-requests/", payload, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["current_revision"]["supervisor"]["full_name"], supervisor.username)
        submitted = self.client.post(
            f"/api/v1/group-requests/{response.data['id']}/submit/",
            {"version": response.data["version"]},
            format="json",
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], GroupRequest.Status.PENDING)

    def test_duplicate_usernames_in_request_are_rejected(self):
        self.client.force_authenticate(self.student)
        payload = self.payload()
        payload["members"].append({"full_name": "عضو ثان", "username": "STUDENT.NEW", "phone": "0502000001"})
        response = self.client.post("/api/v1/group-requests/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_student_can_only_create_requests_for_their_department(self):
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.post("/api/v1/group-requests/", self.payload(), format="json").status_code, 403)

        self.client.force_authenticate(self.student)
        payload = self.payload()
        payload["department_id"] = str(self.other_department.id)
        response = self.client.post("/api/v1/group-requests/", payload, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(GroupRequest.objects.exists())

    def test_student_must_be_an_existing_member_of_the_group_request(self):
        self.client.force_authenticate(self.student)
        payload = self.payload()
        payload["members"] = payload["members"][1:]
        created = self.client.post("/api/v1/group-requests/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        submitted = self.client.post(f"/api/v1/group-requests/{created.data['id']}/submit/", {"version": created.data["version"]}, format="json")
        self.assertEqual(submitted.status_code, 400)
        self.assertEqual(submitted.data["members"], "يجب إضافة حسابك كعضو في المجموعة قبل إرسال الطلب.")

    def test_request_visibility_is_scoped_to_department_chair(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.other_chair)
        self.assertEqual(self.client.get("/api/v1/group-requests/").data, [])
        self.assertEqual(self.client.get(f"/api/v1/group-requests/{request_id}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json").status_code, 403)

    def test_request_creator_cannot_approve_their_own_request(self):
        request_id = self.make_pending()
        request = GroupRequest.objects.get(id=request_id)
        request.created_by = self.chair
        request.save(update_fields=["created_by"])
        self.client.force_authenticate(self.chair)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_student_sees_only_requests_they_created(self):
        request_id = self.make_pending()
        outsider = User.objects.create_user(username="student.outside", password="StudentPassword-97!", role=User.Role.STUDENT, department=self.department)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get("/api/v1/group-requests/").data, [])
        self.assertEqual(self.client.get(f"/api/v1/group-requests/{request_id}/").status_code, 404)

    def test_returned_request_can_be_edited_and_resubmitted_but_not_submitted_twice(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        returned = self.client.post(f"/api/v1/group-requests/{request_id}/return/", {"note": "يرجى توضيح أهداف المشروع."}, format="json")
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(returned.data["status"], GroupRequest.Status.RETURNED)

        self.client.force_authenticate(self.student)
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
        self.client.force_authenticate(self.chair)
        rejected = self.client.post(f"/api/v1/group-requests/{request_id}/reject/", {"note": "الموضوع خارج خطة القسم."}, format="json")
        self.assertEqual(rejected.status_code, 200, rejected.data)
        self.assertEqual(rejected.data["status"], GroupRequest.Status.REJECTED)

        self.client.force_authenticate(self.student)
        duplicate = self.client.post(f"/api/v1/group-requests/{request_id}/submit/", {"version": rejected.data["version"]}, format="json")
        self.assertEqual(duplicate.status_code, 409)
        changed = self.client.patch(f"/api/v1/group-requests/{request_id}/", self.payload(), format="json")
        self.assertEqual(changed.status_code, 409)
        stored = GroupRequest.objects.get(id=request_id)
        self.assertEqual(stored.status, GroupRequest.Status.REJECTED)
        self.assertEqual(stored.decisions.get().note, "الموضوع خارج خطة القسم.")

    def test_all_four_roles_only_see_projects_and_groups_in_their_scope(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
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

        self.client.force_authenticate(self.supervisor)
        self.assertEqual(self.client.get("/api/v1/group-requests/").status_code, 403)
        self.client.force_authenticate(User.objects.get(username="student.new"))
        self.assertEqual(self.client.get("/api/v1/group-requests/").data, [])

    def test_team_notes_are_visible_to_assigned_roles_and_staff_notes_are_hidden(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
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

    def test_student_can_upload_and_download_project_deliverable_but_outsider_cannot(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        student = User.objects.get(username="student.new")
        student.account_status = User.AccountStatus.ACTIVE
        student.save(update_fields=["account_status"])

        self.client.force_authenticate(student)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            rejected = self.client.post(
                f"/api/v1/projects/{project.id}/deliverables/",
                {"file": SimpleUploadedFile("payload.exe", b"MZ\x00unsafe", content_type="application/octet-stream")},
                format="multipart",
            )
            self.assertEqual(rejected.status_code, 400, rejected.data)
            invalid_visibility = self.client.post(
                f"/api/v1/projects/{project.id}/deliverables/",
                {"file": SimpleUploadedFile("invalid.txt", b"invalid", content_type="text/plain"), "visibility": "public"},
                format="multipart",
            )
            self.assertEqual(invalid_visibility.status_code, 400, invalid_visibility.data)
            upload = self.client.post(
                f"/api/v1/projects/{project.id}/deliverables/",
                {"file": SimpleUploadedFile("sample.txt", b"sample attachment", content_type="text/plain")},
                format="multipart",
            )
            self.assertEqual(upload.status_code, 201, upload.data)
            self.assertEqual(upload.data["original_filename"], "sample.txt")
            self.assertEqual(upload.data["size_bytes"], len(b"sample attachment"))
            self.assertEqual(upload.data["visibility"], Deliverable.Visibility.SHARED)
            self.assertEqual(Deliverable.objects.filter(project=project, uploaded_by=student).count(), 1)

            personal_upload = self.client.post(
                f"/api/v1/projects/{project.id}/deliverables/",
                {"file": SimpleUploadedFile("personal.txt", b"private attachment", content_type="text/plain"), "visibility": Deliverable.Visibility.PERSONAL},
                format="multipart",
            )
            self.assertEqual(personal_upload.status_code, 201, personal_upload.data)
            self.assertEqual(personal_upload.data["visibility"], Deliverable.Visibility.PERSONAL)

            listing = self.client.get(f"/api/v1/projects/{project.id}/deliverables/")
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual({item["id"] for item in listing.data}, {upload.data["id"], personal_upload.data["id"]})
            download = self.client.get(f"/api/v1/deliverables/{upload.data['id']}/download/")
            self.assertEqual(download.status_code, 200)
            self.assertEqual(b"".join(download.streaming_content), b"sample attachment")
            personal_download = self.client.get(f"/api/v1/deliverables/{personal_upload.data['id']}/download/")
            self.assertEqual(personal_download.status_code, 200)
            self.assertEqual(b"".join(personal_download.streaming_content), b"private attachment")
            personal_download.close()

            self.client.force_authenticate(self.student)
            teammate_files = self.client.get(f"/api/v1/projects/{project.id}/deliverables/")
            self.assertEqual(teammate_files.status_code, 200, teammate_files.data)
            self.assertEqual([item["id"] for item in teammate_files.data], [upload.data["id"]])
            self.assertEqual(self.client.get(f"/api/v1/deliverables/{personal_upload.data['id']}/download/").status_code, 404)
            self.client.force_authenticate(self.supervisor)
            staff_download = self.client.get(f"/api/v1/deliverables/{personal_upload.data['id']}/download/")
            self.assertEqual(staff_download.status_code, 200)
            self.assertEqual(b"".join(staff_download.streaming_content), b"private attachment")
            staff_download.close()

            outsider = User.objects.create_user(username="student.unassigned", password="StudentPassword-97!", role=User.Role.STUDENT)
            self.client.force_authenticate(outsider)
            self.assertEqual(self.client.get(f"/api/v1/projects/{project.id}/deliverables/").status_code, 404)
            self.assertEqual(self.client.get(f"/api/v1/deliverables/{upload.data['id']}/download/").status_code, 404)

    def test_discussion_readiness_requires_approved_stages_and_final_report_then_supervisor_and_chair(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        ProjectIdeaRevision.objects.create(project=project, version=1, title=project.title, problem=project.description, objectives="أهداف", proposed_solution="حل", novelty="جدة", submitted_by=self.student, status=ProjectIdeaRevision.Status.APPROVED, chair_reviewed_at=timezone.now())
        ProjectPlan.objects.create(project=project, version=1, title=project.title, objectives="أهداف", scope="نطاق", methodology="منهجية", task_assignments="توزيع", timeline="فصل دراسي", risks="مخاطر", expected_outputs="مخرجات", submitted_by=self.student, status=ProjectPlan.Status.APPROVED, reviewed_by=self.supervisor, reviewed_at=timezone.now())
        final_file = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="final.pdf", original_filename="final.pdf", media_type="application/pdf", size_bytes=10)
        report_file = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="report.pdf", original_filename="report.pdf", media_type="application/pdf", size_bytes=10)
        self.client.force_authenticate(self.student)
        payload = {"final_deliverable": str(final_file.id), "report_deliverable": str(report_file.id)}
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/discussion-readiness/", payload, format="json").status_code, 409)
        for stage in project.stages.filter(is_required=True):
            stage.status = ProjectStage.Status.APPROVED
            stage.progress = 100
            stage.save(update_fields=["status", "progress", "updated_at"])
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/discussion-readiness/", {"final_deliverable": str(final_file.id), "report_deliverable": str(final_file.id)}, format="json").status_code, 400)
        submitted = self.client.post(f"/api/v1/projects/{project.id}/discussion-readiness/", payload, format="json")
        self.assertEqual(submitted.status_code, 201, submitted.data)
        self.client.force_authenticate(self.supervisor)
        self.assertEqual(self.client.post(f"/api/v1/discussion-readiness/{submitted.data['id']}/supervisor-review/", {"decision": "changes_requested"}, format="json").status_code, 400)
        returned = self.client.post(f"/api/v1/discussion-readiness/{submitted.data['id']}/supervisor-review/", {"decision": "changes_requested", "note": "أعد رفع نسخة موقعة"}, format="json")
        self.assertEqual(returned.status_code, 200, returned.data)
        self.client.force_authenticate(self.student)
        resubmitted = self.client.post(f"/api/v1/projects/{project.id}/discussion-readiness/", payload, format="json")
        self.assertEqual(resubmitted.status_code, 201, resubmitted.data)
        self.client.force_authenticate(self.supervisor)
        approved = self.client.post(f"/api/v1/discussion-readiness/{resubmitted.data['id']}/supervisor-review/", {"decision": "approved"}, format="json")
        self.assertEqual(approved.data["status"], DiscussionReadinessRequest.Status.CHAIR_REVIEW)
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.post(f"/api/v1/discussion-readiness/{resubmitted.data['id']}/chair-review/", {"decision": "refer"}, format="json").data["status"], DiscussionReadinessRequest.Status.REFERRED)

    def test_defense_committee_requires_chair_nomination_dean_approval_and_limits_member_files(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        self.supervisor.department = self.department
        self.supervisor.save(update_fields=["department"])
        second = User.objects.create_user(username="defense.second", password="DefensePassword-97!", role=User.Role.SUPERVISOR, department=self.department)
        SupervisorProfile.objects.create(user=second, full_name="عضو لجنة المناقشة")
        final_file = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="final.txt", original_filename="final.txt", media_type="text/plain", size_bytes=5, visibility=Deliverable.Visibility.PERSONAL)
        report_file = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="report.txt", original_filename="report.txt", media_type="text/plain", size_bytes=6, visibility=Deliverable.Visibility.PERSONAL)
        unrelated_file = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="extra.txt", original_filename="extra.txt", media_type="text/plain", size_bytes=5)
        readiness = DiscussionReadinessRequest.objects.create(project=project, version=1, final_deliverable=final_file, report_deliverable=report_file, submitted_by=self.student, status=DiscussionReadinessRequest.Status.REFERRED)

        self.client.force_authenticate(self.chair)
        invalid = self.client.post("/api/v1/defense-committees/", {"readiness_request_id": str(readiness.id), "member_ids": [str(self.supervisor.id)], "chair_id": str(self.supervisor.id)}, format="json")
        self.assertEqual(invalid.status_code, 400)
        payload = {"readiness_request_id": str(readiness.id), "member_ids": [str(self.supervisor.id), str(second.id)], "chair_id": str(self.supervisor.id)}
        nominated = self.client.post("/api/v1/defense-committees/", payload, format="json")
        self.assertEqual(nominated.status_code, 201, nominated.data)
        self.assertEqual(nominated.data["status"], DefenseCommittee.Status.PENDING_APPROVAL)
        self.assertEqual(sum(member["is_chair"] for member in nominated.data["members"]), 1)
        corrected = self.client.post("/api/v1/defense-committees/", {**payload, "chair_id": str(second.id)}, format="json")
        self.assertEqual(corrected.status_code, 200, corrected.data)
        self.assertEqual(corrected.data["id"], nominated.data["id"])
        self.assertTrue(next(member for member in corrected.data["members"] if member["id"] == str(second.id))["is_chair"])
        self.assertEqual(self.client.post(f"/api/v1/defense-committees/{nominated.data['id']}/approve/", {}, format="json").status_code, 403)

        outsider = User.objects.create_user(username="defense.outsider", password="DefensePassword-out-97!", role=User.Role.SUPERVISOR, department=self.department)
        group_criterion = DefenseRubricCriterion.objects.create(title="جودة المشروع", description="تقييم جماعي", scope=DefenseRubricCriterion.Scope.PROJECT, weight="100.00", updated_by=self.dean)
        student_criterion = DefenseRubricCriterion.objects.create(title="فهم الطالب", description="تقييم فردي", scope=DefenseRubricCriterion.Scope.STUDENT, weight="100.00", updated_by=self.dean)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get("/api/v1/defense-committees/").data["committees"], [])
        self.assertEqual(self.client.get("/api/v1/defense-rubric/").status_code, 403)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            for item in (final_file, report_file, unrelated_file):
                from django.core.files.storage import default_storage
                with default_storage.open(item.storage_key, "wb") as stream:
                    stream.write(item.original_filename.encode())
            self.assertEqual(self.client.get(f"/api/v1/deliverables/{final_file.id}/download/").status_code, 404)
            self.client.force_authenticate(self.dean)
            approved = self.client.post(f"/api/v1/defense-committees/{nominated.data['id']}/approve/", {}, format="json")
            self.assertEqual(approved.status_code, 200, approved.data)
            self.assertEqual(DefenseCommittee.objects.get(id=nominated.data["id"]).rubric.count(), 2)
            meeting_url = f"/api/v1/defense-committees/{nominated.data['id']}/meeting/"
            self.client.force_authenticate(second)
            self.assertEqual(self.client.post(meeting_url, {"minutes": "محضر مبكر"}, format="json").status_code, 409)
            self.client.force_authenticate(self.chair)
            scheduled = self.client.post(meeting_url, {"defense_at": (timezone.now() - timedelta(days=1)).isoformat(), "location": "قاعة المناقشة"}, format="json")
            self.assertEqual(scheduled.status_code, 200, scheduled.data)
            self.client.force_authenticate(self.supervisor)
            self.assertEqual(self.client.post(meeting_url, {"minutes": "محضر تجريبي"}, format="json").status_code, 403)
            self.client.force_authenticate(second)
            minutes = self.client.post(meeting_url, {"minutes": "ناقشت اللجنة المشروع وطلبت التعديلات المسجلة."}, format="json")
            self.assertEqual(minutes.status_code, 200, minutes.data)
            self.assertTrue(minutes.data["minutes_recorded_at"])
            self.client.force_authenticate(self.dean)
            changed = self.client.patch(f"/api/v1/defense-rubric/{group_criterion.id}/", {"weight": "90.00"}, format="json")
            self.assertEqual(changed.status_code, 200, changed.data)
            self.assertEqual(DefenseCommittee.objects.get(id=nominated.data["id"]).rubric.get(source_criterion_id=group_criterion.id).weight, Decimal("100.00"))
            students = list(project.group.members.filter(left_at__isnull=True).values_list("student_id", flat=True))
            committee = DefenseCommittee.objects.get(id=nominated.data["id"])
            group_snapshot = committee.rubric.get(source_criterion_id=group_criterion.id)
            student_snapshot = committee.rubric.get(source_criterion_id=student_criterion.id)
            scores = [{"criterion_id": str(group_snapshot.id), "score": "88.50"}] + [{"criterion_id": str(student_snapshot.id), "student_id": str(student_id), "score": "91"} for student_id in students]
            self.client.force_authenticate(second)
            self.assertEqual(self.client.get("/api/v1/defense-committees/").data["committees"][0]["status"], DefenseCommittee.Status.APPROVED)
            evaluation_url = f"/api/v1/defense-committees/{nominated.data['id']}/evaluation/"
            self.assertEqual(self.client.get(evaluation_url).data["evaluations"], [])
            self.assertEqual(self.client.post(evaluation_url, {"scores": scores[:-1]}, format="json").status_code, 400)
            first_submission = self.client.post(evaluation_url, {"scores": scores}, format="json")
            self.assertEqual(first_submission.status_code, 201, first_submission.data)
            self.assertFalse(first_submission.data["closed"])
            self.client.force_authenticate(self.supervisor)
            before_close = self.client.get(evaluation_url)
            self.assertEqual(before_close.data["evaluations"], [])
            self.assertEqual(before_close.data["submitted_count"], 1)
            second_submission = self.client.post(evaluation_url, {"scores": scores}, format="json")
            self.assertTrue(second_submission.data["closed"])
            self.assertEqual(self.client.post(evaluation_url, {"scores": scores}, format="json").status_code, 409)
            self.client.force_authenticate(second)
            self.assertEqual(len(self.client.get(evaluation_url).data["evaluations"]), 2)
            post_defense_url = f"/api/v1/projects/{project.id}/post-defense/"
            observation = self.client.post(f"/api/v1/projects/{project.id}/post-defense/revisions/", {"description": "أضف توثيق صلاحيات المستخدمين", "assigned_to": str(self.student.id), "due_at": (timezone.now().date() + timedelta(days=7)).isoformat()}, format="json")
            self.assertEqual(observation.status_code, 201, observation.data)
            self.assertEqual(self.client.get(post_defense_url).data["revisions"][0]["status"], PostDefenseRevision.Status.OPEN)
            evidence = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="revision-evidence.txt", original_filename="revision-evidence.txt", media_type="text/plain", size_bytes=15)
            from django.core.files.storage import default_storage
            with default_storage.open(evidence.storage_key, "wb") as stream:
                stream.write(b"revision evidence")
            self.client.force_authenticate(self.student)
            self.assertEqual(self.client.post(f"/api/v1/post-defense-revisions/{observation.data['id']}/submit/", {"evidence_id": str(evidence.id)}, format="json").data["status"], PostDefenseRevision.Status.SUBMITTED)
            self.client.force_authenticate(second)
            evidence_download = self.client.get(f"/api/v1/deliverables/{evidence.id}/download/")
            self.assertEqual(evidence_download.status_code, 200)
            self.assertEqual(b"".join(evidence_download.streaming_content), b"revision evidence")
            self.client.force_authenticate(outsider)
            self.assertEqual(self.client.get(f"/api/v1/deliverables/{evidence.id}/download/").status_code, 404)
            self.client.force_authenticate(self.student)
            self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/post-defense/final-submissions/", {"deliverable_id": str(final_file.id)}, format="json").status_code, 409)
            self.client.force_authenticate(self.supervisor)
            revision_review = self.client.post(f"/api/v1/post-defense-revisions/{observation.data['id']}/review/", {"decision": "approved"}, format="json")
            self.assertEqual(revision_review.data["status"], PostDefenseRevision.Status.APPROVED)
            post_defense_final = Deliverable.objects.create(project=project, uploaded_by=self.student, storage_key="post-defense-final.pdf", original_filename="post-defense-final.pdf", media_type="application/pdf", size_bytes=30)
            self.client.force_authenticate(self.student)
            final_submission = self.client.post(f"/api/v1/projects/{project.id}/post-defense/final-submissions/", {"deliverable_id": str(post_defense_final.id)}, format="json")
            self.assertEqual(final_submission.status_code, 201, final_submission.data)
            self.client.force_authenticate(self.supervisor)
            final_review = self.client.post(f"/api/v1/post-defense-final-submissions/{final_submission.data['id']}/review/", {"decision": "approved"}, format="json")
            self.assertEqual(final_review.data["status"], PostDefenseFinalSubmission.Status.APPROVED)
            self.client.force_authenticate(self.chair)
            self.assertEqual(self.client.get(post_defense_url).data["final_submissions"][0]["status"], PostDefenseFinalSubmission.Status.APPROVED)
            self.client.force_authenticate(outsider)
            self.assertEqual(self.client.get(evaluation_url).status_code, 404)
            self.client.force_authenticate(second)
            for item in (final_file, report_file):
                download = self.client.get(f"/api/v1/deliverables/{item.id}/download/")
                self.assertEqual(download.status_code, 200)
                self.assertTrue(b"".join(download.streaming_content))
            self.assertEqual(self.client.get(f"/api/v1/deliverables/{unrelated_file.id}/download/").status_code, 404)

    def test_chair_can_add_remove_and_reassign_group_leader_without_erasing_membership_history(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        candidate = User.objects.create_user(username="replacement.student", password="ReplacementPassword-97!", role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE, department=self.department)
        StudentProfile.objects.create(user=candidate, full_name="طالب بديل")
        members_url = f"/api/v1/groups/{project.group_id}/members/"
        listing = self.client.get(members_url)
        self.assertEqual(listing.status_code, 200)
        self.assertIn(str(candidate.id), [row["id"] for row in listing.data["eligible_students"]])
        added = self.client.post(members_url, {"student_id": str(candidate.id)}, format="json")
        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(self.client.post(members_url, {"student_id": str(candidate.id)}, format="json").status_code, 409)
        leader = self.client.patch(f"/api/v1/groups/{project.group_id}/leader/", {"student_id": str(candidate.id)}, format="json")
        self.assertEqual(leader.status_code, 200, leader.data)
        ended = self.client.delete(f"/api/v1/groups/{project.group_id}/members/{candidate.id}/", {"reason": "انسحاب بطلب الطالب", "new_leader_id": str(self.student.id)}, format="json")
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertEqual(ended.data["left_reason"], "انسحاب بطلب الطالب")
        self.assertIsNotNone(ended.data["left_at"])
        self.assertFalse(ended.data["is_leader"])
        self.assertFalse(ended.data["is_online"])
        self.assertIsNone(ended.data["last_activity_at"])
        self.assertEqual(project.group.members.filter(student=candidate).count(), 1)
        self.assertEqual(project.group.members.filter(left_at__isnull=True, is_leader=True).count(), 1)
        self.assertEqual(project.group.members.get(student=candidate).changed_by_id, self.chair.id)
        self.assertTrue(project.group.members.get(student=self.student, left_at__isnull=True).is_leader)
        self.client.force_authenticate(self.other_chair)
        self.assertEqual(self.client.get(members_url).status_code, 404)

    def test_project_roster_reports_recent_activity_only_to_authorized_project_viewers(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        self.student.last_activity_at = timezone.now() - timedelta(minutes=2)
        self.student.save(update_fields=["last_activity_at"])

        self.client.force_authenticate(self.student)
        roster = self.client.get(f"/api/v1/projects/{project.id}/")
        self.assertEqual(roster.status_code, 200, roster.data)
        leader = next(member for member in roster.data["group"]["members"] if member["student_id"] == str(self.student.id))
        self.assertTrue(leader["is_online"])
        self.assertIsNotNone(leader["last_activity_at"])

        self.student.last_activity_at = timezone.now() - timedelta(minutes=10)
        self.student.save(update_fields=["last_activity_at"])
        roster = self.client.get(f"/api/v1/projects/{project.id}/")
        leader = next(member for member in roster.data["group"]["members"] if member["student_id"] == str(self.student.id))
        self.assertFalse(leader["is_online"])
        self.assertIsNotNone(leader["last_activity_at"])

        outsider = User.objects.create_user(username="activity.outsider", password="ActivityPassword-97!", role=User.Role.STUDENT, account_status=User.AccountStatus.ACTIVE, department=self.department)
        StudentProfile.objects.create(user=outsider, full_name="طالب خارج المجموعة")
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(f"/api/v1/projects/{project.id}/").status_code, 404)

    def test_chair_reassigns_supervisor_and_declining_supervisor_is_audited(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        replacement = User.objects.create_user(username="supervisor.replacement", password="ReplacementPassword-97!", role=User.Role.SUPERVISOR, account_status=User.AccountStatus.ACTIVE, department=self.department)
        SupervisorProfile.objects.create(user=replacement, full_name="مشرف بديل")
        url = f"/api/v1/projects/{project.id}/supervisor/"
        self.assertEqual(self.client.post(url, {"supervisor_id": str(replacement.id)}, format="json").status_code, 400)
        reassigned = self.client.post(url, {"supervisor_id": str(replacement.id), "reason": "توزيع العبء الإشرافي"}, format="json")
        self.assertEqual(reassigned.status_code, 200, reassigned.data)
        previous = ProjectSupervisor.objects.get(project=project, supervisor=self.supervisor)
        self.assertEqual(previous.end_type, ProjectSupervisor.EndType.REASSIGNED)
        self.assertEqual(previous.end_reason, "توزيع العبء الإشرافي")
        self.client.force_authenticate(replacement)
        declined = self.client.post(f"/api/v1/projects/{project.id}/supervisor/decline/", {"reason": "تعارض في العبء الدراسي"}, format="json")
        self.assertEqual(declined.status_code, 200, declined.data)
        latest = ProjectSupervisor.objects.get(project=project, supervisor=replacement)
        self.assertEqual(latest.end_type, ProjectSupervisor.EndType.DECLINED)
        self.assertEqual(latest.end_reason, "تعارض في العبء الدراسي")
        self.assertTrue(Notification.objects.filter(recipient=self.chair, event_type="project_supervisor.declined").exists())

    def test_approved_project_gets_required_stages_and_enforces_order_evidence_and_supervisor_review(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        stages = list(ProjectStage.objects.filter(project=project))
        self.assertEqual(len(stages), 7)
        self.assertEqual(stages[0].title, "التحليل والمتطلبات")
        self.assertTrue(project.group.members.get(student=self.student).is_leader)

        self.client.force_authenticate(self.student)
        listing = self.client.get(f"/api/v1/projects/{project.id}/stages/")
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(len(listing.data), 7)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stages[1].id}/start/", {}, format="json").status_code, 409)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stages[0].id}/start/", {}, format="json").status_code, 409)
        idea_payload = {"title": "مكتبة رقمية", "problem": "صعوبة متابعة الإعارة", "objectives": "ضبط عمليات الإعارة", "proposed_solution": "نظام لإدارة المكتبة", "novelty": "إشعارات الاستحقاق"}
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/ideas/", idea_payload, format="json").status_code, 409)
        self.supervisor.department = self.department
        self.supervisor.save(update_fields=["department"])
        second_committee_supervisor = User.objects.create_user(username="committee.second", password="CommitteePassword-97!", role=User.Role.SUPERVISOR, department=self.department)
        SupervisorProfile.objects.create(user=second_committee_supervisor, full_name="عضو لجنة ثانٍ")
        self.client.force_authenticate(self.chair)
        committee = self.client.post(f"/api/v1/departments/{self.department.id}/project-committee/", {"member_ids": [str(self.supervisor.id), str(second_committee_supervisor.id)]}, format="json")
        self.assertEqual(committee.status_code, 201, committee.data)
        self.assertEqual(committee.data["status"], ProjectCommittee.Status.PENDING_APPROVAL)
        self.assertEqual(self.client.post(f"/api/v1/project-committees/{committee.data['id']}/approve/", {}, format="json").status_code, 403)
        self.client.force_authenticate(self.dean)
        committee_approved = self.client.post(f"/api/v1/project-committees/{committee.data['id']}/approve/", {}, format="json")
        self.assertEqual(committee_approved.status_code, 200, committee_approved.data)
        self.client.force_authenticate(self.student)
        missing_idea = dict(idea_payload); missing_idea.pop("novelty")
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/ideas/", missing_idea, format="json").status_code, 400)
        idea = self.client.post(f"/api/v1/projects/{project.id}/ideas/", idea_payload, format="json")
        self.assertEqual(idea.status_code, 201, idea.data)
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/plans/", {"title": "x"}, format="json").status_code, 409)
        self.client.force_authenticate(self.supervisor)
        self.assertEqual(self.client.post(f"/api/v1/project-ideas/{idea.data['id']}/supervisor-review/", {"decision": "forward"}, format="json").status_code, 200)
        queue = self.client.get("/api/v1/project-idea-reviews/")
        self.assertEqual(queue.status_code, 200, queue.data)
        self.assertEqual([entry["id"] for entry in queue.data], [idea.data["id"]])
        first_recommendation = self.client.post(f"/api/v1/project-ideas/{idea.data['id']}/committee-review/", {"recommendation": "recommend"}, format="json")
        self.assertEqual(first_recommendation.data["status"], ProjectIdeaRevision.Status.COMMITTEE_REVIEW)
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.post(f"/api/v1/project-ideas/{idea.data['id']}/chair-review/", {"decision": "approved"}, format="json").status_code, 409)
        self.client.force_authenticate(second_committee_supervisor)
        second_recommendation = self.client.post(f"/api/v1/project-ideas/{idea.data['id']}/committee-review/", {"recommendation": "recommend"}, format="json")
        self.assertEqual(second_recommendation.data["status"], ProjectIdeaRevision.Status.CHAIR_REVIEW)
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.post(f"/api/v1/project-ideas/{idea.data['id']}/chair-review/", {"decision": "approved"}, format="json").status_code, 200)
        self.client.force_authenticate(self.student)
        plan_payload = {"title": "خطة مكتبة", "objectives": "تنظيم الإعارة", "scope": "إعارة الكتب", "methodology": "تحليل وتصميم", "tools": "Django وSQLite", "task_assignments": "الطالب الأول للواجهة والثاني لقاعدة البيانات", "timeline": "فصلان دراسيان", "risks": "تأخر تسليم البيانات؛ معالجة ذلك باجتماع أسبوعي", "expected_outputs": "نظام مكتبة موثق"}
        missing = dict(plan_payload); missing.pop("objectives")
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/plans/", missing, format="json").status_code, 400)
        non_leader = User.objects.get(username="student.new")
        non_leader.account_status = User.AccountStatus.ACTIVE
        non_leader.save(update_fields=["account_status"])
        self.client.force_authenticate(non_leader)
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/plans/", plan_payload, format="json").status_code, 403)
        self.client.force_authenticate(self.student)
        plan = self.client.post(f"/api/v1/projects/{project.id}/plans/", plan_payload, format="json")
        self.assertEqual(plan.status_code, 201, plan.data)
        self.assertEqual(plan.data["version"], 1)
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/plans/", plan_payload, format="json").status_code, 409)
        outsider_supervisor = User.objects.create_user(username="supervisor.plan.outsider", password="SupervisorPassword-Outsider-97!", role=User.Role.SUPERVISOR)
        self.client.force_authenticate(outsider_supervisor)
        self.assertIn(self.client.post(f"/api/v1/project-plans/{plan.data['id']}/review/", {"decision": "approved"}, format="json").status_code, {403, 404})
        self.client.force_authenticate(self.supervisor)
        self.assertEqual(self.client.post(f"/api/v1/project-plans/{plan.data['id']}/review/", {"decision": "changes_requested"}, format="json").status_code, 400)
        requested = self.client.post(f"/api/v1/project-plans/{plan.data['id']}/review/", {"decision": "changes_requested", "note": "أضف نطاق العمل"}, format="json")
        self.assertEqual(requested.status_code, 200, requested.data)
        self.client.force_authenticate(self.student)
        revised = self.client.post(f"/api/v1/projects/{project.id}/plans/", plan_payload, format="json")
        self.assertEqual(revised.status_code, 201, revised.data)
        self.assertEqual(revised.data["version"], 2)
        self.client.force_authenticate(self.supervisor)
        approved_plan = self.client.post(f"/api/v1/project-plans/{revised.data['id']}/review/", {"decision": "approved", "note": "مكتملة"}, format="json")
        self.assertEqual(approved_plan.status_code, 200, approved_plan.data)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stages[0].id}/start/", {}, format="json").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stages[0].id}/submit/", {}, format="json").status_code, 400)

        evidence = SimpleUploadedFile("analysis.txt", b"requirements", content_type="text/plain")
        upload = self.client.post(f"/api/v1/projects/{project.id}/deliverables/", {"file": evidence, "stage_id": str(stages[0].id)}, format="multipart")
        self.assertEqual(upload.status_code, 201, upload.data)
        self.assertEqual(str(upload.data["stage"]), str(stages[0].id))
        submitted = self.client.post(f"/api/v1/project-stages/{stages[0].id}/submit/", {"note": "نسخة التحليل"}, format="json")
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], ProjectStage.Status.SUBMITTED)

        outsider_supervisor = User.objects.create_user(username="supervisor.other", password="SupervisorPassword-Other-97!", role=User.Role.SUPERVISOR)
        self.client.force_authenticate(outsider_supervisor)
        self.assertIn(self.client.post(f"/api/v1/project-stages/{stages[0].id}/review/", {"decision": "approved"}, format="json").status_code, {403, 404})

        self.client.force_authenticate(self.supervisor)
        approved = self.client.post(f"/api/v1/project-stages/{stages[0].id}/review/", {"decision": "approved", "note": "مقبولة"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], ProjectStage.Status.APPROVED)
        self.assertEqual(ProjectStageReview.objects.filter(stage=stages[0]).count(), 2)
        configured = self.client.patch(f"/api/v1/project-stages/{stages[1].id}/", {"starts_at": "2027-01-01", "due_at": "2027-02-01", "title": "التصميم التفصيلي"}, format="json")
        self.assertEqual(configured.status_code, 200, configured.data)
        self.assertEqual(configured.data["title"], "التصميم التفصيلي")
        self.assertEqual(self.client.patch(f"/api/v1/project-stages/{stages[1].id}/", {"starts_at": "2027-03-01", "due_at": "2027-02-01"}, format="json").status_code, 400)
        custom = self.client.post(f"/api/v1/projects/{project.id}/stages/", {"title": "مراجعة إضافية"}, format="json")
        self.assertEqual(custom.status_code, 201, custom.data)
        self.assertFalse(custom.data["is_required"])
        self.assertEqual(self.client.delete(f"/api/v1/project-stages/{stages[1].id}/", format="json").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/v1/project-stages/{custom.data['id']}/", format="json").status_code, 204)
        self.client.force_authenticate(self.student)
        second = self.client.post(f"/api/v1/project-stages/{stages[1].id}/start/", {}, format="json")
        self.assertEqual(second.status_code, 200, second.data)

    def test_only_requesting_student_leader_can_submit_stage_and_supervisor_can_return_with_note(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        stage = project.stages.first()
        ProjectIdeaRevision.objects.create(project=project, version=1, title=project.title, problem=project.description, objectives="أهداف", proposed_solution="حل", novelty="جدة", submitted_by=self.student, status=ProjectIdeaRevision.Status.APPROVED, chair_reviewed_at=timezone.now())
        ProjectPlan.objects.create(project=project, version=1, title=project.title, objectives="أهداف", scope="نطاق", methodology="منهجية", task_assignments="توزيع", timeline="فصل دراسي", risks="مخاطر", expected_outputs="مخرجات", submitted_by=self.student, status=ProjectPlan.Status.APPROVED, reviewed_by=self.supervisor, reviewed_at=timezone.now())
        additional_student = User.objects.get(username="student.new")
        additional_student.account_status = User.AccountStatus.ACTIVE
        additional_student.save(update_fields=["account_status"])
        self.client.force_authenticate(self.student)
        self.client.post(f"/api/v1/project-stages/{stage.id}/start/", {}, format="json")
        self.client.force_authenticate(additional_student)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stage.id}/submit/", {}, format="json").status_code, 403)
        self.client.force_authenticate(self.student)
        evidence = SimpleUploadedFile("design.txt", b"design", content_type="text/plain")
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/deliverables/", {"file": evidence, "stage_id": str(stage.id)}, format="multipart").status_code, 201)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stage.id}/submit/", {}, format="json").status_code, 200)
        self.client.force_authenticate(self.supervisor)
        self.assertEqual(self.client.post(f"/api/v1/project-stages/{stage.id}/review/", {"decision": "changes_requested"}, format="json").status_code, 400)
        returned = self.client.post(f"/api/v1/project-stages/{stage.id}/review/", {"decision": "changes_requested", "note": "أضف مخطط قاعدة البيانات"}, format="json")
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(returned.data["status"], ProjectStage.Status.CHANGES_REQUESTED)
        review = next(entry for entry in returned.data["reviews"] if entry["action"] == "changes_requested")
        self.assertEqual(review["note"], "أضف مخطط قاعدة البيانات")

    def test_supervisor_assigns_project_tasks_and_only_assignee_or_supervisor_can_update(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        project = Project.objects.get(group__source_request_id=request_id)
        stage = project.stages.first()
        student = User.objects.get(username="student.new")
        student.account_status = User.AccountStatus.ACTIVE
        student.save(update_fields=["account_status"])

        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post(f"/api/v1/projects/{project.id}/tasks/", {"stage_id": str(stage.id), "title": "مهمة الطالب"}, format="json").status_code, 403)
        self.client.force_authenticate(self.supervisor)
        created = self.client.post(f"/api/v1/projects/{project.id}/tasks/", {
            "stage_id": str(stage.id), "title": "إنشاء مخطط البيانات", "description": "تسليم ERD", "assigned_to": str(student.id), "due_at": "2027-01-20",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task = ProjectTask.objects.get(id=created.data["id"])
        self.assertEqual(task.status, ProjectTask.Status.TODO)

        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.patch(f"/api/v1/project-tasks/{task.id}/", {"status": "completed"}, format="json").status_code, 403)
        self.client.force_authenticate(student)
        updated = self.client.patch(f"/api/v1/project-tasks/{task.id}/", {"status": "in_progress"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["status"], ProjectTask.Status.IN_PROGRESS)
        self.client.force_authenticate(self.chair)
        self.assertEqual(self.client.patch(f"/api/v1/project-tasks/{task.id}/", {"status": "completed"}, format="json").status_code, 403)

    def test_in_app_notifications_are_scoped_persistent_and_readable_by_recipient_only(self):
        request_id = self.make_pending()
        notification = Notification.objects.get(recipient=self.chair, event_type="group_request.submitted")
        self.assertEqual(Notification.objects.filter(recipient=self.other_chair).count(), 0)
        self.client.force_authenticate(self.chair)
        listing = self.client.get("/api/v1/notifications/")
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["unread_count"], 1)
        marked = self.client.post(f"/api/v1/notifications/{notification.id}/read/", {}, format="json")
        self.assertEqual(marked.status_code, 200, marked.data)
        self.assertIsNotNone(marked.data["read_at"])
        self.assertEqual(self.client.get("/api/v1/notifications/").data["unread_count"], 0)
        self.client.force_authenticate(self.other_chair)
        self.assertEqual(self.client.post(f"/api/v1/notifications/{notification.id}/read/", {}, format="json").status_code, 404)
        self.client.force_authenticate(self.chair)
        self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertTrue(Notification.objects.filter(recipient=self.student, event_type="group_request.approved").exists())

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
        self.client.force_authenticate(self.chair)
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

    def test_only_department_chair_can_make_decisions_and_notes_are_required(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.dean)
        self.assertEqual(self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json").status_code, 403)
        self.client.force_authenticate(self.chair)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/return/", {"note": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/reject/", {"note": "سبب اختبار الرفض"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], GroupRequest.Status.REJECTED)
        self.assertEqual(response.data["decisions"][0]["note"], "سبب اختبار الرفض")

    def test_approval_creates_group_project_members_and_inactive_account_atomically(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
        response = self.client.post(f"/api/v1/group-requests/{request_id}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], GroupRequest.Status.APPROVED)
        group = ProjectGroup.objects.get(source_request_id=request_id)
        project = Project.objects.get(group=group)
        member = GroupMember.objects.get(group=group, student__username="student.new")
        self.assertEqual(project.title, "مشروع اختبار")
        self.assertEqual(member.student.account_status, User.AccountStatus.ACTIVATION_PENDING)
        self.assertFalse(member.student.is_active)
        self.assertTrue(ProjectSupervisor.objects.filter(project=project, supervisor=self.supervisor).exists())
        self.assertEqual(AuditLog.objects.filter(action="group_request.approved").count(), 1)
        self.assertFalse(OutboxEvent.objects.filter(event_type="account_activation_required").exists())
        self.assertFalse(OneTimeToken.objects.exists())

    def test_approval_integrity_failure_rolls_back_every_created_record(self):
        request_id = self.make_pending()
        self.client.force_authenticate(self.chair)
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

    def test_project_idea_similarity_compares_approved_ideas_and_requires_leader(self):
        current_group = ProjectGroup.objects.create(group_code="GP-SIM-CURRENT", department=self.department, academic_year="2026–2027", source_request=self._bare_approved_request("sim-current"))
        current_project = Project.objects.create(group=current_group, title="المكتبة الذكية", description="إدارة إعارة الكتب")
        GroupMember.objects.create(group=current_group, student=self.student, is_leader=True)
        prior_group = ProjectGroup.objects.create(group_code="GP-SIM-PRIOR", department=self.department, academic_year="2025–2026", source_request=self._bare_approved_request("sim-prior"))
        prior_project = Project.objects.create(group=prior_group, title="منصة مكتبة رقمية", description="تنظيم الإعارة والفهرسة", status=Project.Status.COMPLETED)
        ProjectIdeaRevision.objects.create(
            project=prior_project, version=1, submitted_by=self.student,
            title="نظام إدارة المكتبة الرقمية", problem="صعوبة متابعة إعارة الكتب واسترجاعها",
            objectives="تنظيم إعارة الكتب وتتبع الاسترجاع", proposed_solution="منصة لإدارة إعارة الكتب والفهرسة",
            novelty="تنبيهات ذكية لمواعيد استحقاق الكتب", status=ProjectIdeaRevision.Status.APPROVED,
        )
        active_group = ProjectGroup.objects.create(group_code="GP-SIM-ACTIVE", department=self.department, academic_year="2026–2027", source_request=self._bare_approved_request("sim-active"))
        active_project = Project.objects.create(group=active_group, title="مشروع غير مؤرشف", description="وصف داخلي")
        ProjectIdeaRevision.objects.create(
            project=active_project, version=1, submitted_by=self.student,
            title="نظام إدارة المكتبة الرقمية", problem="صعوبة متابعة إعارة الكتب واسترجاعها",
            objectives="تنظيم إعارة الكتب وتتبع الاسترجاع", proposed_solution="منصة لإدارة إعارة الكتب والفهرسة",
            novelty="تنبيهات ذكية لمواعيد استحقاق الكتب", status=ProjectIdeaRevision.Status.APPROVED,
        )
        self.client.force_authenticate(self.student)
        payload = {
            "title": "نظام إدارة المكتبة الرقمية", "problem": "صعوبة متابعة إعارة الكتب واسترجاعها",
            "objectives": "تنظيم إعارة الكتب وتتبع الاسترجاع", "proposed_solution": "منصة لإدارة إعارة الكتب والفهرسة",
            "novelty": "تنبيهات ذكية لمواعيد استحقاق الكتب",
        }
        response = self.client.post(f"/api/v1/projects/{current_project.id}/idea-similarity/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["method"], "lexical_overlap")
        self.assertIn("لا تثبت الانتحال", response.data["notice"])
        self.assertEqual(response.data["matches"][0]["project_title"], prior_project.title)
        self.assertEqual(len(response.data["matches"]), 1, "يجب ألا يكشف الفحص أفكار مشاريع ما زالت نشطة.")
        self.assertGreaterEqual(response.data["matches"][0]["score"], 90)
        incomplete = dict(payload); incomplete.pop("novelty")
        self.assertEqual(self.client.post(f"/api/v1/projects/{current_project.id}/idea-similarity/", incomplete, format="json").status_code, 400)
        non_leader = User.objects.create_user(username="student.similarity.member", password="StudentPassword-97!", role=User.Role.STUDENT, department=self.department)
        GroupMember.objects.create(group=current_group, student=non_leader)
        self.client.force_authenticate(non_leader)
        self.assertEqual(self.client.post(f"/api/v1/projects/{current_project.id}/idea-similarity/", payload, format="json").status_code, 403)

    def test_reports_export_scoped_xlsx_print_and_restrict_audit(self):
        own_group = ProjectGroup.objects.create(group_code="GP-REPORT-OWN", department=self.department, academic_year="2026–2027", source_request=self._bare_approved_request("report-own"))
        own_project = Project.objects.create(group=own_group, title="مشروع ضمن النطاق", description="وصف")
        GroupMember.objects.create(group=own_group, student=self.student, is_leader=True)
        other_group = ProjectGroup.objects.create(group_code="GP-REPORT-OTHER", department=self.department, academic_year="2026–2027", source_request=self._bare_approved_request("report-other"))
        Project.objects.create(group=other_group, title="مشروع خارج نطاق الطالب", description="وصف")

        self.client.force_authenticate(self.student)
        student_print = self.client.get("/api/v1/reports/?type=projects&output=print")
        self.assertEqual(student_print.status_code, 200, student_print.content[:1000])
        self.assertContains(student_print, "مشروع ضمن النطاق")
        self.assertNotContains(student_print, "مشروع خارج نطاق الطالب")
        self.assertEqual(self.client.get(f"/api/v1/reports/?type=projects&output=xlsx&department={self.department.id}").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/reports/?type=audit&output=xlsx").status_code, 403)

        ProjectSupervisor.objects.create(project=own_project, supervisor=self.supervisor)
        self.client.force_authenticate(self.supervisor)
        supervisor_print = self.client.get("/api/v1/reports/?type=projects&output=print")
        self.assertContains(supervisor_print, "مشروع ضمن النطاق")
        self.assertNotContains(supervisor_print, "مشروع خارج نطاق الطالب")
        self.assertEqual(self.client.get("/api/v1/reports/?type=projects&output=xlsx&date_from=invalid").status_code, 400)

        self.client.force_authenticate(self.chair)
        chair_xlsx = self.client.get("/api/v1/reports/?type=projects&output=xlsx")
        self.assertEqual(chair_xlsx.status_code, 200, getattr(chair_xlsx, "data", None))
        self.assertEqual(chair_xlsx["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with ZipFile(BytesIO(chair_xlsx.content)) as workbook:
            sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
            self.assertIn("مشروع ضمن النطاق", sheet)
            self.assertIn("مشروع خارج نطاق الطالب", sheet)
        for kind in ("groups", "supervisors", "progress", "defenses"):
            self.assertEqual(self.client.get(f"/api/v1/reports/?type={kind}&output=xlsx").status_code, 200, kind)
        self.assertEqual(self.client.get("/api/v1/reports/?type=projects&output=csv").status_code, 400)
        self.assertEqual(self.client.get(f"/api/v1/reports/?type=projects&output=xlsx&department={self.other_department.id}").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/reports/?type=audit&output=xlsx").status_code, 403)

        self.client.force_authenticate(self.dean)
        self.assertTrue(AuditLog.objects.filter(actor=self.chair, action="reports.export_requested").exists())
        dean_audit = self.client.get("/api/v1/reports/?type=audit&output=xlsx")
        self.assertEqual(dean_audit.status_code, 200, getattr(dean_audit, "data", None))
        self.assertIn("تقرير العمليات", ZipFile(BytesIO(dean_audit.content)).read("xl/worksheets/sheet1.xml").decode("utf-8"))

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

    def test_password_reset_request_does_not_queue_a_message(self):
        existing = self.client.post("/api/v1/auth/password-reset-requests/", {"identifier": "student.existing"}, format="json")
        missing = self.client.post("/api/v1/auth/password-reset-requests/", {"identifier": "nobody.unknown"}, format="json")
        self.assertEqual(existing.data, missing.data)
        self.assertEqual(existing.data["detail"], "لإعادة تعيين كلمة المرور، يرجى مراجعة رئيس القسم.")
        self.assertFalse(OutboxEvent.objects.filter(event_type="password_reset_requested").exists())

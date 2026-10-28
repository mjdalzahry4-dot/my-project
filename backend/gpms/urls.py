from django.urls import path

from .views import AuditListView, DepartmentListView, DeliverableDownloadView, GroupDetailView, GroupListView, GroupRequestDecisionView, GroupRequestDetailView, GroupRequestListCreateView, GroupRequestSubmitView, HealthView, LoginView, LogoutView, MeView, OneTimePasswordView, PasswordResetRequestView, ProjectAppointmentDetailView, ProjectAppointmentListCreateView, ProjectDeliverablesView, ProjectDetailView, ProjectListView, ProjectNotesView, ProjectRepositoryView, StudentActivationView, SupervisorListView, UserListView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/password-reset-requests/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("auth/one-time-password/<str:purpose>/", OneTimePasswordView.as_view(), name="one-time-password"),
    path("departments/", DepartmentListView.as_view(), name="departments"),
    path("supervisors/", SupervisorListView.as_view(), name="supervisors"),
    path("users/", UserListView.as_view(), name="user-list"),
    path("users/<uuid:user_id>/activation/", StudentActivationView.as_view(), name="student-activation"),
    path("group-requests/", GroupRequestListCreateView.as_view(), name="group-request-list-create"),
    path("group-requests/<uuid:request_id>/", GroupRequestDetailView.as_view(), name="group-request-detail"),
    path("group-requests/<uuid:request_id>/submit/", GroupRequestSubmitView.as_view(), name="group-request-submit"),
    path("group-requests/<uuid:request_id>/<str:action>/", GroupRequestDecisionView.as_view(), name="group-request-decision"),
    path("groups/", GroupListView.as_view(), name="group-list"),
    path("groups/<uuid:group_id>/", GroupDetailView.as_view(), name="group-detail"),
    path("projects/", ProjectListView.as_view(), name="project-list"),
    path("projects/<uuid:project_id>/", ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<uuid:project_id>/repository/", ProjectRepositoryView.as_view(), name="project-repository"),
    path("projects/<uuid:project_id>/notes/", ProjectNotesView.as_view(), name="project-notes"),
    path("projects/<uuid:project_id>/deliverables/", ProjectDeliverablesView.as_view(), name="project-deliverables"),
    path("appointments/", ProjectAppointmentListCreateView.as_view(), name="appointment-list-create"),
    path("appointments/<uuid:appointment_id>/", ProjectAppointmentDetailView.as_view(), name="appointment-detail"),
    path("deliverables/<uuid:deliverable_id>/download/", DeliverableDownloadView.as_view(), name="deliverable-download"),
    path("audit-log/", AuditListView.as_view(), name="audit-log"),
]

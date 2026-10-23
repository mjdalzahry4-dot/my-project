from rest_framework.permissions import BasePermission

from .models import GroupRequest, Project, ProjectGroup, ProjectSupervisor, User


class IsAuthenticatedActive(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.account_status == User.AccountStatus.ACTIVE)


def request_queryset_for(user):
    qs = GroupRequest.objects.select_related("created_by", "current_revision", "current_revision__department").prefetch_related("decisions")
    if user.role == User.Role.DEAN:
        return qs
    if user.role == User.Role.DEPARTMENT_CHAIR and user.department_id:
        return qs.filter(created_by=user, current_revision__department_id=user.department_id)
    return qs.none()


def can_view_project(user, project):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.role == User.Role.DEAN:
        return True
    if user.role == User.Role.DEPARTMENT_CHAIR:
        return bool(user.department_id and project.group.department_id == user.department_id)
    if user.role == User.Role.SUPERVISOR:
        return ProjectSupervisor.objects.filter(project=project, supervisor=user, ended_at__isnull=True).exists()
    if user.role == User.Role.STUDENT:
        return project.group.members.filter(student=user, left_at__isnull=True).exists()
    return False


def can_view_group(user, group):
    project = getattr(group, "project", None)
    return bool(project and can_view_project(user, project))

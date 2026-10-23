from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuditLog, Department, Deliverable, GroupMember, GroupRequest, OneTimeToken, OutboxEvent, Project, ProjectGroup, ProjectNote, ProjectSupervisor, RequestDecision, RequestMember, RequestRevision, RequestSupervisor, StudentProfile, SupervisorProfile, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("GPMS", {"fields": ("role", "account_status", "phone", "department", "username_normalized")}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (("GPMS", {"fields": ("role", "account_status", "phone", "department")}),)
    list_display = ("username", "role", "account_status", "department", "is_active", "is_staff")
    list_filter = ("role", "account_status", "department", "is_active", "is_staff")
    readonly_fields = ("username_normalized",)


admin.site.register([Department, StudentProfile, SupervisorProfile, GroupRequest, RequestRevision, RequestMember, RequestSupervisor, RequestDecision, ProjectGroup, Project, GroupMember, ProjectSupervisor, ProjectNote, Deliverable, AuditLog, OneTimeToken, OutboxEvent])

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Announcement, CustomUser, Manual, ManualSection


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'system_role', 'is_approved', 'is_staff')
    list_filter = ('is_approved', 'system_role')
    list_editable = ('is_approved',)
    fieldsets = UserAdmin.fieldsets + (
        ('DocuRoute Fields', {'fields': ('role', 'system_role', 'full_name', 'is_approved')}),
    )


@admin.register(Manual)
class ManualAdmin(admin.ModelAdmin):
    list_display = ('title', 'series', 'uploaded_by', 'uploaded_at')


@admin.register(ManualSection)
class ManualSectionAdmin(admin.ModelAdmin):
    list_display = ('subtitle', 'manual', 'tag', 'page_number', 'order')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    """Announcements are information, always a banner. Deadlines are a
    separate kind with their own screen; deleting is not offered here
    either - deactivate instead."""

    list_display = ('title', 'audience', 'expires_on', 'active', 'created_at')
    list_filter = ('active', 'audience')
    search_fields = ('title', 'body')
    fields = ('title', 'body', 'audience', 'expires_on', 'active')

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

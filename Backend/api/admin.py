from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Announcement, CustomUser, Department, Manual, ManualSection, ManualRevision,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'department', 'role', 'is_approved', 'is_staff')
    list_filter = ('is_approved', 'role', 'department')
    list_editable = ('is_approved',)
    fieldsets = UserAdmin.fieldsets + (
        ('DocuRoute Fields', {'fields': ('role', 'is_approved', 'department')}),
    )


@admin.register(Manual)
class ManualAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'uploaded_by', 'uploaded_at')


@admin.register(ManualSection)
class ManualSectionAdmin(admin.ModelAdmin):
    list_display = ('subtitle', 'manual', 'tag', 'page_number', 'order')


@admin.register(ManualRevision)
class ManualRevisionAdmin(admin.ModelAdmin):
    list_display = ('section', 'submitted_by', 'status', 'submitted_at')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    """The admin-side form for announcements and upcoming items.

    One model covers both widgets: give it a date and it appears under
    Upcoming, leave the date empty and it is the dashboard banner. The list
    says which, so nobody has to remember the rule.
    """

    list_display = ('title', 'shows_as', 'date', 'department', 'active', 'created_at')
    list_filter = ('active', 'department')
    search_fields = ('title', 'body')
    fieldsets = (
        (None, {
            'fields': ('title', 'body', 'active'),
            'description': 'Leave the date empty for a banner; set one to '
                           'put it under Upcoming.',
        }),
        ('Where and when', {'fields': ('date', 'department')}),
    )

    @admin.display(description='Shows as')
    def shows_as(self, obj):
        return 'Upcoming' if obj.date else 'Banner'

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

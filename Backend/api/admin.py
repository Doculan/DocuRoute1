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
    """The admin-side form for announcements and upcoming items.

    One model covers both widgets: give it a date and it appears under
    Upcoming, leave the date empty and it is the dashboard banner. The list
    says which, so nobody has to remember the rule.
    """

    list_display = ('title', 'shows_as', 'date', 'office', 'active', 'created_at')
    list_filter = ('active', 'office')
    search_fields = ('title', 'body')
    fieldsets = (
        (None, {
            'fields': ('title', 'body', 'active'),
            'description': 'Leave the date empty for a banner; set one to '
                           'put it under Upcoming.',
        }),
        ('Where and when', {'fields': ('date', 'office')}),
    )

    @admin.display(description='Shows as')
    def shows_as(self, obj):
        return 'Upcoming' if obj.date else 'Banner'

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Department, Manual, ManualSection, ManualRevision


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

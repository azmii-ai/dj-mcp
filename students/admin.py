from django.contrib import admin
from .models import Student, StudentNote


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant_id", "email", "plan", "mrr", "health_score", "is_active")
    list_filter = ("tenant_id", "plan", "is_active", "is_deleted")
    search_fields = ("name", "email")
    list_editable = ("plan", "mrr", "health_score", "is_active")


@admin.register(StudentNote)
class StudentNoteAdmin(admin.ModelAdmin):
    list_display = ("student", "tenant_id", "note_type", "created_at", "created_by_agent")
    list_filter = ("note_type", "created_by_agent", "tenant_id")
    search_fields = ("content", "student__name")
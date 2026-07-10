from django.contrib import admin
from .models import UsageMetric


@admin.register(UsageMetric)
class UsageMetricAdmin(admin.ModelAdmin):
    list_display = ("student", "recorded_at", "api_calls", "daily_active_users", "feature_slug")
    list_filter = ("feature_slug",)
    search_fields = ("student__name", "feature_slug")
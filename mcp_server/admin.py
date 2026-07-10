from django import forms
from django.contrib import admin
from .models import MCPApiKey, MCPApiKeyUsage, MCPCapability


class MCPApiKeyAdminForm(forms.ModelForm):
    capabilities = forms.MultipleChoiceField(
        choices=[(c.value, c.label) for c in MCPCapability],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )


@admin.register(MCPApiKey)
class MCPApiKeyAdmin(admin.ModelAdmin):
    form = MCPApiKeyAdminForm
    list_display = ("name", "tenant_id", "key_prefix", "is_active", "requests_per_minute", "created_at", "last_used_at")
    list_filter = ("is_active", "tenant_id")
    search_fields = ("name", "key_prefix")
    readonly_fields = ("key_hash", "key_prefix", "created_at", "last_used_at")


@admin.register(MCPApiKeyUsage)
class MCPApiKeyUsageAdmin(admin.ModelAdmin):
    list_display = ("api_key", "tool_name", "status", "tenant_id", "duration_ms", "invoked_at")
    list_filter = ("status", "tool_name", "tenant_id")
    search_fields = ("tool_name", "request_id", "error_message")
    readonly_fields = ("api_key", "tool_name", "status", "arguments", "tenant_id", "result_rows", "error_message", "duration_ms", "invoked_at", "request_id", "agent_version", "request_count")
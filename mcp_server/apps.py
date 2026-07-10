from django.apps import AppConfig


class McpServerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mcp_server'

    def ready(self):
        # Importing the modules triggers @ToolRegistry.register decorators,
        # so the tools are discoverable when the app starts.
        from mcp_server import student_tools  # noqa: F401
        from mcp_server import write_tools  # noqa: F401

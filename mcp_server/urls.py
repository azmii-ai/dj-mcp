from django.urls import path

from mcp_server.views import HealthCheckView, MCPMessageView, MCPSSEView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("message/", MCPMessageView.as_view(), name="mcp-message"),
    path("sse/", MCPSSEView.as_view(), name="mcp-sse"),
]
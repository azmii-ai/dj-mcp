from django.urls import path, include

urlpatterns = [
    path("api/", include("mcp_server.urls")),
]
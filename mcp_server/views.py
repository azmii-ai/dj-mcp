import json
import uuid
import logging
from asgiref.sync import sync_to_async
from django.http import JsonResponse, StreamingHttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import MCPApiKey
from .protocol import MCPProtocolHandler


logger = logging.getLogger(__name__)
_handler = MCPProtocolHandler()


class HealthCheckView(APIView):
    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


async def _authenticate(request) -> MCPApiKey | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return await sync_to_async(MCPApiKey.authenticate)(auth[len("Bearer ") :])


def _check_rate_limit(api_key: MCPApiKey) -> bool:
    minute_key = f"mcp:rate:min:{api_key.pk}"
    day_key = f"mcp:rate:day:{api_key.pk}"

    if hasattr(cache, "client") and hasattr(cache.client, "pipeline"):
        # Atomic Redis pipeline (preferred)
        pipe = cache.client.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, 60)
        pipe.incr(day_key)
        pipe.expire(day_key, 86400)
        results = pipe.execute()
        return (
            results[0] <= api_key.requests_per_minute
            and results[2] <= api_key.requests_per_day
        )

    # Fallback for non-Redis backends (e.g. LocMemCache in dev)
    minute_count = (cache.get(minute_key) or 0) + 1
    day_count = (cache.get(day_key) or 0) + 1
    cache.set(minute_key, minute_count, 60)
    cache.set(day_key, day_count, 86400)
    return (
        minute_count <= api_key.requests_per_minute
        and day_count <= api_key.requests_per_day
    )


@method_decorator(csrf_exempt, name="dispatch")
class MCPMessageView(View):
    """POST /mcp/message/ — simple HTTP request/response transport."""

    async def post(self, request):
        api_key = await _authenticate(request)
        if not api_key:
            return JsonResponse({"error": "Invalid or missing API key"}, status=401)
        if not _check_rate_limit(api_key):
            return JsonResponse(
                {"error": "Rate limit exceeded"},
                status=429,
                headers={"Retry-After": "60"},
            )
        try:
            message = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await _handler.handle_message(message, api_key, request_id)
        return JsonResponse(response)


@method_decorator(csrf_exempt, name="dispatch")
class MCPSSEView(View):
    """
    GET  /mcp/sse/           — opens SSE stream
    POST /mcp/sse/?session=X — sends message to session

    SSE transport: agent opens a persistent connection (GET), then
    POSTs messages with the session ID. Responses stream back over SSE.
    Preferred for long-running agent sessions.
    """

    async def get(self, request):
        api_key = await _authenticate(request)
        if not api_key:
            return JsonResponse({"error": "Unauthorized"}, status=401)
        session_id = str(uuid.uuid4())
        cache.set(f"mcp:session:{session_id}", str(api_key.pk), timeout=3600)

        async def stream():
            import asyncio

            yield (
                f"event: endpoint\n"
                f"data: {json.dumps({'uri': f'/mcp/sse/?session={session_id}'})}\n\n"
            )
            count = 0
            while True:
                await asyncio.sleep(15)
                count += 1
                yield f"event: heartbeat\ndata: {count}\n\n"
                if not cache.get(f"mcp:session:{session_id}"):
                    break

        resp = StreamingHttpResponse(stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        resp["X-Session-ID"] = session_id
        return resp

    async def post(self, request):
        session_id = request.GET.get("session")
        if not session_id:
            return JsonResponse({"error": "Missing session"}, status=400)
        key_id = cache.get(f"mcp:session:{session_id}")
        if not key_id:
            return JsonResponse({"error": "Session expired"}, status=404)
        api_key = await sync_to_async(MCPApiKey.objects.get)(pk=key_id, is_active=True)
        if not _check_rate_limit(api_key):
            return JsonResponse({"error": "Rate limit exceeded"}, status=429)
        try:
            message = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await _handler.handle_message(message, api_key, request_id)
        return JsonResponse(response)
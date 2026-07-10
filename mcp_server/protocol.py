import json
import time
import logging
from typing import Any
from mcp_server.models import MCPApiKey, MCPCapability

logger = logging.getLogger(__name__)


class MCPProtocolHandler:
    """
    Stateless JSON-RPC handler. One instance per process.
    All per-request state (session, tenant) passed in from views.
    """

    PROTOCOL_VERSION = "2026-07-07"
    SERVER_INFO = {"name": "django-mcp-server", "version": "1.0.0"}

    async def handle_message(
        self,
        message: dict,
        api_key: "MCPApiKey",
        request_id: str,
    ) -> dict:
        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")
        try:
            if method == "initialize":
                result = await self._initialize(api_key)
            elif method == "tools/list":
                result = await self._tools_list(api_key)
            elif method == "tools/call":
                result = await self._tools_call(params, api_key, request_id)
            elif method == "resources/list":
                result = await self._resources_list(api_key)
            elif method == "ping":
                result = {}
            else:
                return self._err(msg_id, -32601, f"Method not found: {method}")
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except PermissionError as e:
            return self._err(msg_id, -32603, str(e))
        except Exception as e:
            logger.error("MCP error: %s", e, exc_info=True)
            return self._err(msg_id, -32603, "Internal error")

    async def _initialize(self, api_key) -> dict:
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": self.SERVER_INFO,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
            },
        }

    async def _tools_list(self, api_key) -> dict:
        from mcp_server.tools import ToolRegistry

        return {"tools": ToolRegistry.all_schemas_for_key(api_key)}

    async def _tools_call(self, params: dict, api_key, request_id: str) -> dict:
        from mcp_server.tools import ToolRegistry
        from mcp_server.models import MCPApiKeyUsage

        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        tenant_id = api_key.tenant_id
        tool = ToolRegistry.get(tool_name)
        if not tool:
            raise PermissionError(f"Tool '{tool_name}' not found")
        # Capability check
        if not api_key.has_capability(tool.required_capability):
            await MCPApiKeyUsage.objects.acreate(
                api_key=api_key,
                tenant_id=tenant_id,
                tool_name=tool_name,
                arguments=arguments,
                status="denied",
                request_id=request_id,
                error_message=f"Missing capability: {tool.required_capability}",
            )
            raise PermissionError(
                f"API key lacks '{tool.required_capability}' to call '{tool_name}'."
            )
        # Allowlist check
        if not api_key.can_use_tool(tool_name):
            await MCPApiKeyUsage.objects.acreate(
                api_key=api_key,
                tenant_id=tenant_id,
                tool_name=tool_name,
                arguments=arguments,
                status="denied",
                request_id=request_id,
                error_message="Tool not in key's allowlist",
            )
            raise PermissionError(f"'{tool_name}' not in this key's tool allowlist.")
        # Execute with timing
        start = time.perf_counter_ns()
        try:
            result = await tool.execute(arguments, tenant_id, api_key)
        except Exception as e:
            duration_ms = (time.perf_counter_ns() - start) // 1_000_000
            await MCPApiKeyUsage.objects.acreate(
                api_key=api_key,
                tenant_id=tenant_id,
                tool_name=tool_name,
                arguments=arguments,
                status="error",
                error_message=str(e),
                duration_ms=duration_ms,
                request_id=request_id,
            )
            raise
        duration_ms = (time.perf_counter_ns() - start) // 1_000_000
        # Audit every successful call
        await MCPApiKeyUsage.objects.acreate(
            api_key=api_key,
            tenant_id=tenant_id,
            tool_name=tool_name,
            arguments=arguments,
            status="success",
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return {"content": result.content, "isError": result.is_error}

    async def _resources_list(self, api_key) -> dict:
        resources = []
        if api_key.has_capability(MCPCapability.READ_STUDENTS):
            resources.append(
                {
                    "uri": f"django://students/{api_key.tenant_id}",
                    "name": "Student Database",
                    "description": "All students in your account",
                    "mimeType": "application/json",
                }
            )
        return {"resources": resources}

    @staticmethod
    def _err(msg_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

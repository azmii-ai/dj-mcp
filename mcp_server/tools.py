# mcp_server/tools/base.py
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolResult:
    """Standardized tool result — maps to MCP content blocks."""

    def __init__(
        self, content: list[dict], is_error: bool = False, row_count: int | None = None
    ):
        self.content = content
        self.is_error = is_error
        self.row_count = row_count

    @classmethod
    def text(cls, text: str, row_count: int | None = None) -> "ToolResult":
        return cls(content=[{"type": "text", "text": text}], row_count=row_count)

    @classmethod
    def json(cls, data: Any, row_count: int | None = None) -> "ToolResult":
        import json

        return cls(
            content=[{"type": "text", "text": json.dumps(data, default=str)}],
            row_count=row_count,
        )

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(
            content=[{"type": "text", "text": f"Error: {message}"}],
            is_error=True,
        )


class BaseTool(ABC):
    """
    Base class for all MCP tools.
    Subclass, define InputSchema + required_capability, implement execute().
    ToolRegistry discovers all subclasses automatically via @register.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    required_capability: ClassVar[str]
    InputSchema: ClassVar[Type[BaseModel]]
    is_read_only: ClassVar[bool] = True
    requires_confirmation: ClassVar[bool] = False
    max_result_rows: ClassVar[int] = 100

    @abstractmethod
    async def execute(
        self,
        arguments: dict,
        tenant_id: int,
        api_key: "MCPApiKey",
    ) -> ToolResult:
        """tenant_id is always enforced — cannot be overridden by arguments."""
        ...

    def to_mcp_schema(self) -> dict:
        schema = self.InputSchema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        }


class ToolRegistry:
    """
    Auto-discovers BaseTool subclasses via @ToolRegistry.register decorator.
    Provides capability-filtered tool listing per API key.
    """

    _tools: dict[str, "BaseTool"] = {}

    @classmethod
    def register(cls, tool_class: Type[BaseTool]) -> Type[BaseTool]:
        instance = tool_class()
        cls._tools[tool_class.name] = instance
        logger.debug("Registered MCP tool: %s", tool_class.name)
        return tool_class

    @classmethod
    def get(cls, name: str) -> "BaseTool | None":
        return cls._tools.get(name)

    @classmethod
    def list_for_key(cls, api_key: "MCPApiKey") -> list["BaseTool"]:
        return [
            tool
            for tool in cls._tools.values()
            if api_key.has_capability(tool.required_capability)
            and api_key.can_use_tool(tool.name)
        ]

    @classmethod
    def all_schemas_for_key(cls, api_key: "MCPApiKey") -> list[dict]:
        return [tool.to_mcp_schema() for tool in cls.list_for_key(api_key)]

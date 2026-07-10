import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from .tools import BaseTool, ToolResult, ToolRegistry
from mcp_server.models import MCPCapability


@ToolRegistry.register
class AddStudentNoteTool(BaseTool):
    name = "add_student_note"
    description = (
        "Add a note to a student's record. Use to log context from "
        "a conversation, flag a risk, or record an action taken. "
    )
    required_capability = MCPCapability.CREATE_NOTES
    is_read_only = False
    requires_confirmation = False  # Low-stakes write — no confirmation needed

    class InputSchema(BaseModel):
        student_id: int = Field(..., gt=0)
        note: str = Field(..., min_length=5, max_length=2000)
        note_type: Literal[
            "observation", "action_taken", "risk_flag", "opportunity", "general"
        ] = "general"

    async def execute(self, arguments: dict, tenant_id: int, api_key) -> ToolResult:
        from students.models import Student, StudentNote

        try:
            args = self.InputSchema(**arguments)
        except Exception as e:
            return ToolResult.error(f"Invalid arguments: {e}")
        try:
            student = await Student.objects.aget(
                id=args.student_id, tenant_id=tenant_id
            )
        except Student.DoesNotExist:
            return ToolResult.error("Student not found in your account.")
        note = await StudentNote.objects.acreate(
            student=student,
            tenant_id=tenant_id,
            content=args.note,
            note_type=args.note_type,
            created_by_agent=True,
        )
        return ToolResult.json(
            {
                "note_id": note.pk,
                "student": student.name,
                "note_type": args.note_type,
                "created": True,
            }
        )

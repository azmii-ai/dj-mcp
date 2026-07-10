from typing import Literal
from pydantic import BaseModel, Field, field_validator
from django.db.models import Q
from .tools import BaseTool, ToolResult, ToolRegistry
from mcp_server.models import MCPCapability


@ToolRegistry.register
class LookupStudentTool(BaseTool):
    name = "lookup_student"
    description = (
        "Look up a student by name or email. "
        "Returns student info, enrollment date, and academic status. "
        "Call this before making decisions about a student."
    )
    required_capability = MCPCapability.READ_STUDENTS
    is_read_only = True

    class InputSchema(BaseModel):
        query: str = Field(
            ...,
            min_length=2,
            max_length=200,
            description="Student email address or name.",
        )
        match_type: Literal["exact", "partial"] = Field(
            default="partial",
            description="'exact' for precise matching, 'partial' for fuzzy.",
        )
        limit: int = Field(default=5, ge=1, le=20)

        @field_validator("query")
        @classmethod
        def sanitize_query(cls, v: str) -> str:
            return v.strip().replace("%", "").replace("_", " ")

    async def execute(self, arguments: dict, tenant_id: int, api_key) -> ToolResult:
        from students.models import Student

        try:
            args = self.InputSchema(**arguments)
        except Exception as e:
            return ToolResult.error(f"Invalid arguments: {e}")
        # tenant_id is ALWAYS appended — the agent cannot bypass this
        qs = Student.objects.filter(tenant_id=tenant_id, is_deleted=False)
        if args.match_type == "exact":
            qs = qs.filter(Q(email__iexact=args.query) | Q(name__iexact=args.query))
        else:
            qs = qs.filter(
                Q(email__icontains=args.query) | Q(name__icontains=args.query)
            )
        results = []
        async for c in qs.order_by("-mrr")[: args.limit]:
            results.append(
                {
                    "id": c.pk,
                    "name": c.name,
                    "email": c.email,
                    "plan": c.plan or "unknown",
                    "mrr": float(c.mrr or 0),
                    "health_score": c.health_score,
                    "status": "active" if c.is_active else "churned",
                    "enrollment_date": c.enrollment_date.isoformat(),
                }
            )
        if not results:
            return ToolResult.text(f"No students found matching '{args.query}'.")
        return ToolResult.json({"students": results}, row_count=len(results))


@ToolRegistry.register
class GetStudentUsageTool(BaseTool):
    name = "get_student_usage"
    description = (
        "Retrieve usage metrics for a specific student over a date range. "
        "Returns API calls, feature adoption, active users, and trend. "
        "Use for health assessments and renewal conversations."
    )
    required_capability = MCPCapability.READ_ANALYTICS
    is_read_only = True

    class InputSchema(BaseModel):
        student_id: int = Field(..., gt=0)
        days: int = Field(default=30, ge=1, le=365, description="Days to look back.")

    async def execute(self, arguments: dict, tenant_id: int, api_key) -> ToolResult:
        from students.models import Student
        from analytics.models import UsageMetric
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum, Avg, Count

        try:
            args = self.InputSchema(**arguments)
        except Exception as e:
            return ToolResult.error(f"Invalid arguments: {e}")
        # Verify student belongs to THIS tenant
        try:
            student = await Student.objects.aget(
                id=args.student_id, tenant_id=tenant_id
            )
        except Student.DoesNotExist:
            return ToolResult.error(
                "Student not found in your account."
            )
        since = timezone.now() - timedelta(days=args.days)
        metrics = await UsageMetric.objects.filter(
            student_id=student.pk,
            recorded_at__gte=since,
        ).aaggregate(
            total_api_calls=Sum("api_calls"),
            avg_dau=Avg("daily_active_users"),
            active_features=Count("feature_slug", distinct=True),
        )
        return ToolResult.json(
            {
                "student": {"id": student.pk, "name": student.name},
                "period_days": args.days,
                "metrics": {
                    "api_calls": int(metrics["total_api_calls"] or 0),
                    "avg_dau": round(float(metrics["avg_dau"] or 0), 1),
                    "active_features": int(metrics["active_features"] or 0),
                },
            }
        )


@ToolRegistry.register
class ListAtRiskStudentsTool(BaseTool):
    name = "list_at_risk_students"
    description = (
        "Returns students with low health scores or declining usage. "
        "Results sorted by risk severity — highest risk first. "
        "Use to identify accounts needing proactive outreach."
    )
    required_capability = MCPCapability.READ_ANALYTICS
    is_read_only = True
    max_result_rows = 50

    class InputSchema(BaseModel):
        health_score_below: int = Field(default=60, ge=0, le=100)
        limit: int = Field(default=20, ge=1, le=50)
        include_churned: bool = Field(default=False)

    async def execute(self, arguments: dict, tenant_id: int, api_key) -> ToolResult:
        from students.models import Student

        try:
            args = self.InputSchema(**arguments)
        except Exception as e:
            return ToolResult.error(f"Invalid arguments: {e}")
        qs = Student.objects.filter(
            tenant_id=tenant_id,
            health_score__lt=args.health_score_below,
        )
        if not args.include_churned:
            qs = qs.filter(is_active=True)
        students = []
        async for s in qs.order_by("health_score")[: args.limit]:
            students.append(
                {
                    "id": s.pk,
                    "name": s.name,
                    "health_score": s.health_score,
                    "mrr": float(s.mrr or 0),
                    "last_active": (
                        s.last_active_at.isoformat() if s.last_active_at else None
                    ),
                }
            )
        return ToolResult.json(
            {
                "at_risk_count": len(students),
                "threshold": args.health_score_below,
                "students": students,
            },
            row_count=len(students),
        )

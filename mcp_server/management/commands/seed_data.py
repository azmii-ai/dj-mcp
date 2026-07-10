from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import random

from students.models import Student, StudentNote
from analytics.models import UsageMetric
from mcp_server.models import MCPApiKey, MCPCapability


class Command(BaseCommand):
    help = "Seed demo students, usage metrics, notes, and a sample MCP API key"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=1)
        parser.add_argument("--reset", action="store_true", help="Delete existing seed data first")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        if options["reset"]:
            StudentNote.objects.filter(tenant_id=tenant_id).delete()
            Student.objects.filter(tenant_id=tenant_id).delete()
            self.stdout.write("Cleared existing data for tenant %d." % tenant_id)

        if Student.objects.filter(tenant_id=tenant_id).exists():
            self.stdout.write(self.style.WARNING("Tenant %d already has students; skipping seed." % tenant_id))
            return

        names = [
            ("Ada Lovelace", "ada@example.com", "pro", 499, 92),
            ("Alan Turing", "alan@example.com", "enterprise", 2500, 78),
            ("Grace Hopper", "grace@example.com", "pro", 499, 88),
            ("Linus Torvalds", "linus@example.com", "free", 0, 35),
            ("Margaret Hamilton", "margaret@example.com", "enterprise", 2500, 95),
            ("Dennis Ritchie", "dennis@example.com", "pro", 499, 64),
            ("Barbara Liskov", "barbara@example.com", "free", 0, 22),
            ("Tim Berners-Lee", "tim@example.com", "enterprise", 2500, 81),
            ("Katherine Johnson", "katherine@example.com", "pro", 499, 48),
            ("Donald Knuth", "donald@example.com", "free", 0, 12),
        ]
        created_students = []
        now = timezone.now()
        for name, email, plan, mrr, score in names:
            is_active = score >= 30
            last_active = now - timedelta(days=random.randint(1, 60)) if is_active else None
            student = Student.objects.create(
                tenant_id=tenant_id,
                name=name,
                age=random.randint(18, 65),
                email=email,
                plan=plan,
                mrr=mrr,
                health_score=score,
                is_active=is_active,
                last_active_at=last_active,
            )
            created_students.append(student)

            # Usage metrics across the last 30 days
            for day in range(30):
                UsageMetric.objects.create(
                    student=student,
                    api_calls=random.randint(0, 500),
                    daily_active_users=random.randint(0, 50),
                    feature_slug=random.choice(["chat", "search", "analytics", "export"]),
                    recorded_at=now - timedelta(days=day),
                )

        # Sample note
        StudentNote.objects.create(
            student=created_students[0],
            tenant_id=tenant_id,
            content="Renewal discussion scheduled for next week. Customer open to upgrade.",
            note_type="opportunity",
            created_by_agent=False,
        )
        StudentNote.objects.create(
            student=created_students[8],
            tenant_id=tenant_id,
            content="Usage dropped sharply after onboarding. At risk of churn.",
            note_type="risk_flag",
            created_by_agent=True,
        )

        # Create an API key for this tenant if none exists
        if not MCPApiKey.objects.filter(tenant_id=tenant_id).exists():
            raw_key, instance = MCPApiKey.create_key(
                name="Demo Agent Key",
                tenant_id=tenant_id,
                capabilities=[c.value for c in MCPCapability if c != MCPCapability.ADMIN],
                agent_description="Full read/write agent for demos",
                requests_per_minute=120,
            )
            self.stdout.write(self.style.WARNING("\n  Created MCP API Key (save it — shown once):\n  %s\n" % raw_key))
        else:
            self.stdout.write("MCP API key for tenant %d already exists; skipping key creation." % tenant_id)

        self.stdout.write(self.style.SUCCESS(
            "\n[OK] Seed complete: %d students, %d usage metrics, sample notes.\n"
            % (len(created_students), 30 * len(created_students))
        ))
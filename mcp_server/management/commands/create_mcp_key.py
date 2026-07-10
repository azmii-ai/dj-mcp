from django.core.management.base import BaseCommand
from mcp_server.models import MCPApiKey, MCPCapability


class Command(BaseCommand):
    help = "Create an MCP API key for an AI agent"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--name", type=str, required=True)
        parser.add_argument("--capabilities", nargs="+", default=[])
        parser.add_argument(
            "--tools",
            nargs="+",
            default=[],
            help="Explicit allowlist (empty = all matching caps)",
        )
        parser.add_argument("--rate-limit", type=int, default=60)
        parser.add_argument("--description", type=str, default="")

    def handle(self, *args, **options):
        valid = {c.value for c in MCPCapability}
        for cap in options["capabilities"]:
            if cap not in valid:
                self.stderr.write(
                    f"Unknown capability '{cap}'. Valid: {', '.join(sorted(valid))}"
                )
                return
        raw_key, instance = MCPApiKey.create_key(
            tenant_id=options["tenant_id"],
            name=options["name"],
            capabilities=options["capabilities"],
            allowed_tools=options["tools"],
            requests_per_minute=options["rate_limit"],
            agent_description=options["description"],
        )
        self.stdout.write(self.style.SUCCESS("\n[OK] MCP API key created\n"))
        self.stdout.write(f"  Key ID:       {instance.id}")
        self.stdout.write(f"  Tenant:       {instance.tenant_id}")
        self.stdout.write(f"  Name:         {instance.name}")
        self.stdout.write(f"  Capabilities: {', '.join(instance.capabilities)}")
        self.stdout.write(f"  Rate limit:   {instance.requests_per_minute}/min")
        self.stdout.write(
            self.style.WARNING(f"\n  API Key (save this — shown once):\n  {raw_key}\n")
        )

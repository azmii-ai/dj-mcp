import hashlib
import secrets
import uuid
from django.db import models
from django.utils import timezone


class MCPCapability(models.TextChoices):
    # READ: The capability to read data from the MCP.
    READ_STUDENT = "read:students", "Read student data"
    READ_ANALYTICS = "read:analytics", "Read analytics and metrics"

    # WRITE: The capability to write data to the MCP.
    UPDATE_STUDENT = "update:students", "Update student data"
    CREATE_NOTES = "create:notes", "Add notes to student records"

    # ADMIN: The capability to manage the MCP and its users.
    DELETE_DATA = "delete:data", "Delete records"
    ADMIN = "admin", "Full administrative access"


class MCPApiKey(models.Model):
    """
    Represents an API key for accessing the MCP (My Custom Platform) with specific capabilities.
    Each key is scoped to a tenant and a specific set of capabilities.
    The raw key is shown once at creation and never stored — only the hash is persisted.
    """

    # Fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=200)
    tenant_id = models.IntegerField(db_index=True)
    key_prefix = models.CharField(max_length=8, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    capabilities = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    # Rate limiting
    requests_per_minute = models.IntegerField(default=60)
    requests_per_day = models.IntegerField(default=10_000)

    # Agent metadata
    agent_description = models.TextField(blank=True)
    allowed_tools = models.JSONField(default=list)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True)
    last_used_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "key_prefix"]),
        ]
        ordering = ["-created_at"]
        db_table = "mcp_api_key"

    def has_capability(self, capability: str) -> bool:
        if MCPCapability.ADMIN in self.capabilities:
            return True
        return capability in self.capabilities

    def can_use_tool(self, tool_name: str) -> bool:
        if self.allowed_tools:
            return tool_name in self.allowed_tools
        return True  # All tools matching capabilities

    @classmethod
    def create_key(
        cls,
        name: str,
        tenant_id: int,
        capabilities: list[str],
        **kwargs,
    ) -> tuple[str, "MCPApiKey"]:
        """
        Creates a new API key for the MCP with the specified parameters.
        Returns a tuple of (raw_key, MCPApiKey instance).
        The raw key is only shown once and is not stored in the database.
        """
        allowed_tools = kwargs.pop("allowed_tools", [])

        # Generate a secure random key
        raw_key = f"mcp_{secrets.token_urlsafe(32)}"
        key_prefix = raw_key[:8]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # Create the MCPApiKey instance
        api_key = cls.objects.create(
            name=name,
            tenant_id=tenant_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            capabilities=capabilities,
            allowed_tools=allowed_tools,
            **kwargs,
        )

        return raw_key, api_key

    @classmethod
    def authenticate(cls, raw_key: str, tenant_id: int) -> "MCPApiKey | None":
        """
        Authenticates an API key against the stored hash and tenant ID.
        Returns the MCPApiKey instance if valid, otherwise None.
        """
        if not raw_key.startswith("mcp_"):
            return None

        key_prefix = raw_key[:8]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        try:
            api_key = cls.objects.get(
                tenant_id=tenant_id,
                key_prefix=key_prefix,
                key_hash=key_hash,
                is_active=True,
            )
            if api_key.expires_at is not None and api_key.expires_at <= timezone.now():
                return None
            # Update last used timestamp
            api_key.last_used_at = timezone.now()
            api_key.save(update_fields=["last_used_at"])
            return api_key
        except cls.DoesNotExist:
            return None


class MCPApiKeyUsage(models.Model):
    """
    Tracks the usage of an MCP API key for rate limiting purposes.
    Each record corresponds to a specific API key and a time window.
    """

    STATUS = [
        ("success", "Success"),
        ("error", "Error"),
        ("denied", "Permission Denied"),
        ("rate_limit", "Rate Limited"),
        ("timeout", "Timeout"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    api_key = models.ForeignKey(
        MCPApiKey, on_delete=models.CASCADE, related_name="usage_records"
    )
    status = models.CharField(max_length=20, choices=STATUS)
    tenant_id = models.IntegerField(db_index=True)
    tool_name = models.CharField(max_length=100, db_index=True)
    arguments = models.JSONField()
    result_rows = models.IntegerField(null=True)
    error_message = models.TextField(blank=True)
    duration_ms = models.IntegerField(null=True)
    invoked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    request_id = models.CharField(max_length=100, blank=True)
    agent_version = models.CharField(max_length=50, blank=True)
    request_count = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["api_key", "invoked_at"]),
            models.Index(fields=["tenant_id", "invoked_at"]),
        ]
        ordering = ["-invoked_at"]
        db_table = "mcp_api_key_usage"

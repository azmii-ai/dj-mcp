import anthropic
import os

PORT = os.environ.get("DJANGO_PORT", "8000")
HOST = os.environ.get("DJANGO_HOST", "localhost")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-20250514")
MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)

response = client.beta.messages.create(
    model=ANTHROPIC_MODEL,
    max_tokens=2048,
    mcp_servers=[
        {
            "type": "url",
            "url": f"https://{HOST}:{PORT}/mcp/sse/",
            "name": "django-crm",
            "api_key": MCP_API_KEY,
        }
    ],
    messages=[
        {
            "role": "user",
            "content": (
                "You are an AI agent that can call tools on a Django CRM server. "
                "The server is running at https://{HOST}:{PORT}/mcp/sse/ and "
                "you have been given an API key to access it. "
                "Your task is to list students with health scores below 50 "
            ),
        }
    ],
    betas=["mcp-client-2025-04-04"],
)
print(response.content)

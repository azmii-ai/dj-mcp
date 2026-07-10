# dj-mcp — Implementing MCP in Django

> Implementing MCP (Model Context Protocol) in Django: giving AI agents secure, type-safe access to your ORM.

`dj-mcp` exposes your Django data to AI agents (Claude, custom MCP clients, etc.) over the
**Model Context Protocol** with tenant isolation, capability-based API keys, per-tool
auditing, and rate limiting.

---

## Table of contents
1. [Architecture](#architecture)
2. [Quickstart](#quickstart)
3. [Demo data + first API key](#demo-data--first-api-key)
4. [MCP endpoints](#mcp-endpoints)
5. [Available tools](#available-tools)
6. [Calling the server](#calling-the-server)
7. [Connecting an AI agent](#connecting-an-ai-agent)
8. [Management commands](#management-commands)
9. [Admin UI](#admin-ui)
10. [Project layout](#project-layout)
11. [Configuration reference](#configuration-reference)
12. [Production notes](#production-notes)

---

## Architecture

```
                 ┌────────────────────────────┐
   AI agent      │  Anthropic SDK / MCP client │
                 └─────────────┬──────────────┘
                               │ JSON-RPC over HTTP or SSE
                               ▼
                 ┌─────────────────────────────────────┐
                 │ Django (ASGI/WSGI)                  │
                 │   mcp_server/views.py               │
                 │     - Bearer auth (sync_to_async)   │
                 │     - rate limit (Redis/LocMem)     │
                 ├─────────────────────────────────────┤
                 │ mcp_server/protocol.py             │
                 │   JSON-RPC: initialize / list / call│
                 ├─────────────────────────────────────┤
                 │ mcp_server/tools.py (ToolRegistry)  │
                 │   BaseTool + capability filter      │
                 ├─────────────────────────────────────┤
                 │ student_tools.py / write_tools.py   │
                 │   lookup_student, get_student_usage,│
                 │   list_at_risk_students, add_note   │
                 ├─────────────────────────────────────┤
                 │ students/models + analytics/models │
                 │   Django ORM (PostgreSQL)           │
                 └─────────────────────────────────────┘
```

Key properties:

- **Tenant isolation is enforced by the framework, not the agent.** Every tool query
  is automatically scoped with `tenant_id=tenant_id`. The agent cannot override it.
- **Capability-scoped keys.** Each `MCPApiKey` carries a list of capabilities
  (`read:students`, `read:analytics`, `update:students`, `create:notes`,
  `delete:data`, `admin`). Tools are only visible to a key that has the matching capability.
- **Per-call audit.** Every `tools/call` writes an `MCPApiKeyUsage` row with status,
  duration, arguments, request id, and error message (if any).
- **Rate limited.** Per-minute and per-day limits enforced by the key's
  `requests_per_minute` / `requests_per_day` fields.
- **Raw key never stored.** Only the SHA-256 hash is persisted; the raw key is shown
  once at creation time.

---

## Quickstart

### Prerequisites
- Python 3.13+
- Docker (for PostgreSQL and, optionally, Redis)
- Or a local PostgreSQL + Redis if you prefer not to use Docker

### 1. Clone and install

```bash
git clone <your-repo-url> dj-mcp
cd dj-mcp
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -e .
```

### 2. Configure environment

`.env` is already provided with sensible defaults for local development:

```env
DJANGO_SECRET_KEY=django-insecure-...
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=dj_mcp
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost     # use "db" when running web inside docker-compose
POSTGRES_PORT=5432

DJANGO_PORT=8000

CORS_ALLOW_ALL_ORIGINS=True
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Optional Redis for rate limiting (defaults to LocMemCache if unset)
# DJANGO_CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
# REDIS_URL=redis://127.0.0.1:6379/1
```

### 3. Start PostgreSQL

```bash
docker compose up -d db
```

### 4. Apply migrations and start the server

```bash
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 5. (Optional) Run everything in Docker

```bash
docker compose up --build
```

This starts `db` (Postgres 17) and `web` (Django), applies migrations, and serves
on `http://localhost:8000`.

---

## Demo data + first API key

A single command seeds 10 students, 30 days of usage metrics per student, sample
notes, and a demo MCP API key with all non-admin capabilities:

```bash
python manage.py seed_data --tenant-id 1 --reset
```

Sample output:

```
Cleared existing data for tenant 1.

  Created MCP API Key (save it - shown once):
  mcp_gWPgNzYtnmNavE5m6eo6a4tq2ejZxywt1-Na_JdU0Jw

[OK] Seed complete: 10 students, 300 usage metrics, sample notes.
```

**Save the raw key** — it is never shown again. You'll pass it as
`Authorization: Bearer <your-key>` on every MCP request.

> If you lose the key, re-run `seed_data --reset` (it will clear and re-seed) or
> create a new key with `python manage.py create_mcp_key` (see below).

---

## MCP endpoints

All endpoints are mounted under `/mcp/`.

| Method | URL                        | Purpose                                              |
|-------:|----------------------------|------------------------------------------------------|
| GET    | `/mcp/health/`             | Unauthenticated health check.                        |
| POST   | `/mcp/message/`            | HTTP transport — one JSON-RPC request per request.  |
| GET    | `/mcp/sse/`                | SSE transport — opens a stream, returns session id. |
| POST   | `/mcp/sse/?session=<id>`   | SSE transport — send JSON-RPC over a session.        |

### Auth
Every MCP request must include:

```
Authorization: Bearer mcp_<your-token>
```

Missing/invalid tokens return `401`. Rate-limit violations return `429` with
`Retry-After: 60`.

### JSON-RPC methods supported

| Method          | Params                         | Description                                |
|------------------|--------------------------------|--------------------------------------------|
| `initialize`     | none                           | Returns protocol version + server info.   |
| `tools/list`     | none                           | Lists tools the API key can call.         |
| `tools/call`     | `name`, `arguments`            | Invokes a tool; returns content blocks.   |
| `resources/list` | none                           | Lists accessible resources.                |
| `ping`           | none                           | Health probe.                              |

---

## Available tools

Each tool is a subclass of `BaseTool` in `mcp_server/tools.py`. They are
auto-registered via the `@ToolRegistry.register` decorator.

### `lookup_student` — `read:students`
Look up a student by name or email.

```json
{
  "query": "ada",
  "match_type": "partial",   // or "exact"
  "limit": 5                  // 1..20
}
```

Returns: `id`, `name`, `email`, `plan`, `mrr`, `health_score`, `status`
(`active` / `churned`), `enrollment_date`.

### `get_student_usage` — `read:analytics`
Aggregate API call / DAU / feature-adoption metrics for a student over N days.

```json
{ "student_id": 1, "days": 30 }
```

Returns: `api_calls`, `avg_dau`, `active_features`.

### `list_at_risk_students` — `read:analytics`
List students whose `health_score` is below a threshold, sorted by severity.

```json
{
  "health_score_below": 60,
  "limit": 20,
  "include_churned": false
}
```

Returns: `id`, `name`, `health_score`, `mrr`, `last_active`.

### `add_student_note` — `create:notes`
Append a typed note to a student's record. The note is automatically flagged
`created_by_agent=True` and tenant-scoped.

```json
{
  "student_id": 1,
  "note": "Renewal conversation went well; customer open to upgrade.",
  "note_type": "opportunity"     // observation | action_taken | risk_flag | opportunity | general
}
```

Returns: `note_id`, `student`, `note_type`, `created: true`.

### Capability matrix

| Tool                  | Required capability  | Read-only? |
|-----------------------|----------------------|------------|
| `lookup_student`      | `read:students`      | yes        |
| `get_student_usage`   | `read:analytics`     | yes        |
| `list_at_risk_students`| `read:analytics`    | yes        |
| `add_student_note`    | `create:notes`       | no         |

The `admin` capability implicitly grants all of the above plus `update:students`
and `delete:data`.

---

## Calling the server

### HTTP transport (simplest)

```bash
KEY="mcp_gWPgNzYtnmNavE5m6eo6a4tq2ejZxywt1-Na_JdU0Jw"

# initialize
curl -s http://127.0.0.1:8000/mcp/message/ \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}'

# list tools
curl -s http://127.0.0.1:8000/mcp/message/ \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# call a tool
curl -s http://127.0.0.1:8000/mcp/message/ \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"lookup_student",
                 "arguments":{"query":"ada","match_type":"partial"}}}'
```

Sample response (`tools/call`):

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{"type": "text", "text": "{\"students\": [...]}"}],
    "isError": false
  }
}
```

### SSE transport

```bash
# 1. Open stream in one terminal — note the session id in the X-Session-ID header
curl -N -H "Authorization: Bearer $KEY" http://127.0.0.1:8000/mcp/sse/

# 2. Send messages using the session id returned in step 1
curl -s "http://127.0.0.1:8000/mcp/sse/?session=<SESSION_ID>" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## Connecting an AI agent

`agent_example.py` shows the canonical pattern using the Anthropic Python SDK
with the MCP client beta:

```python
import os, anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

response = client.beta.messages.create(
    model="claude-opus-4-20250514",
    max_tokens=2048,
    mcp_servers=[
        {
            "type": "url",
            "url": "http://127.0.0.1:8000/mcp/sse/",
            "name": "django-crm",
            "api_key": os.environ["MCP_API_KEY"],   # the mcp_... key from seed_data
        }
    ],
    messages=[
        {"role": "user",
         "content": "List students with health scores below 50 and suggest an outreach plan."}
    ],
    betas=["mcp-client-2025-04-04"],
)
print(response.content)
```

Run it with:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export MCP_API_KEY=mcp_gWPgNzYtnmNavE5m6eo6a4tq2ejZxywt1-Na_JdU0Jw
python agent_example.py
```

The agent will:
1. `initialize` against your Django server,
2. `tools/list` to see what's available,
3. call `list_at_risk_students` (and possibly `lookup_student` / `get_student_usage`)
   to ground its answer,
4. produce a final response that your app can render.

---

## Management commands

### `seed_data`
```
python manage.py seed_data [--tenant-id N] [--reset]
```
Creates demo data and a demo API key for the given tenant. `--reset` clears
existing data for that tenant first.

### `create_mcp_key`
```
python manage.py create_mcp_key \
  --tenant-id 1 \
  --name "Production Agent" \
  --capabilities read:students read:analytics create:notes \
  --tools lookup_student get_student_usage   # optional explicit allowlist
  --rate-limit 120 \
  --description "Agent used in production support bot"
```

Prints the raw key once. Valid capability values are listed in
`mcp_server/models.py::MCPCapability`.

### Standard commands
`migrate`, `makemigrations`, `createsuperuser`, `runserver`, `shell`,
`dumpdata`, `loaddata` all work as normal.

---

## Admin UI

The Django admin is enabled at `/admin/`. Create a superuser:

```bash
python manage.py createsuperuser
```

Then log in at `http://localhost:8000/admin/`. Available admin pages:

- **Students** (`students.Student`, `students.StudentNote`)
- **Analytics** (`analytics.UsageMetric`)
- **MCP / Api keys** (`mcp_server.MCPApiKey`)
- **MCP / Api key usage** (`mcp_server.MCPApiKeyUsage`) — fully read-only audit log
  of every tool call.

From the API key admin you can:
- toggle `is_active`
- edit capabilities (checkbox widget)
- adjust `requests_per_minute` / `requests_per_day`
- set `expires_at`
- inspect `last_used_at` (read-only)

---

## Project layout

```
dj-mcp/
├── agent_example.py            # Anthropic SDK demo
├── docker-compose.yml          # Postgres + Django
├── Dockerfile
├── pyproject.toml
├── manage.py
├── project/
│   ├── settings.py             # INSTALLED_APPS, CACHES, REST_FRAMEWORK
│   ├── urls.py                 # /admin/ + /mcp/ includes
│   ├── asgi.py / wsgi.py
├── mcp_server/                 # the MCP server itself
│   ├── models.py               # MCPApiKey, MCPApiKeyUsage, MCPCapability
│   ├── tools.py                # BaseTool, ToolRegistry, ToolResult
│   ├── protocol.py             # JSON-RPC handler
│   ├── views.py                # HTTP + SSE views (auth, rate limit)
│   ├── urls.py                 # /mcp/health/ /mcp/message/ /mcp/sse/
│   ├── admin.py
│   ├── student_tools.py        # read tools
│   ├── write_tools.py          # write tools
│   └── management/commands/
│       ├── create_mcp_key.py
│       └── seed_data.py
├── students/                   # multi-tenant Student + StudentNote models
│   ├── models.py
│   ├── admin.py
│   └── migrations/0001_initial.py
├── analytics/                  # UsageMetric model
│   ├── models.py
│   ├── admin.py
│   └── migrations/0001_initial.py
└── .env
```

---

## Configuration reference

All settings are env-driven (read in `project/settings.py`).

| Variable                 | Default                              | Notes                                    |
|--------------------------|--------------------------------------|------------------------------------------|
| `DJANGO_SECRET_KEY`      | insecure fallback                    | Set a real key in production.            |
| `DJANGO_DEBUG`           | `True`                               | Set `False` in production.               |
| `DJANGO_ALLOWED_HOSTS`   | `localhost,127.0.0.1`               | Comma-separated.                         |
| `POSTGRES_DB`            | `dj_mcp`                             |                                          |
| `POSTGRES_USER`          | `postgres`                           |                                          |
| `POSTGRES_PASSWORD`      | `postgres`                           |                                          |
| `POSTGRES_HOST`          | `localhost` (or `db` in compose)      |                                          |
| `POSTGRES_PORT`          | `5432`                               |                                          |
| `DJANGO_PORT`            | `8000`                               | Used by `agent_example.py`.              |
| `CORS_ALLOW_ALL_ORIGINS` | `True`                               | Lock down in production.                 |
| `CORS_ALLOWED_ORIGINS`   | `http://localhost:3000,127.0.0.1:3000`|                                          |
| `DJANGO_CACHE_BACKEND`   | `LocMemCache`                        | Set to `django.core.cache.backends.redis.RedisCache` for production.      |
| `REDIS_URL`              | `mcp-cache-default`                  | Redis connection string (location).       |
| `ANTHROPIC_API_KEY`      | —                                    | Only needed by `agent_example.py`.       |
| `MCP_API_KEY`            | —                                    | Only needed by `agent_example.py`.       |

---

## Production notes

1. **Use ASGI.** Run behind an ASGI server (e.g. `daphne`, `uvicorn` with `--workers`,
   or `gunicorn -k uvicorn.workers.UvicornWorker`) so async views and the SSE
   streaming endpoint perform well:
   ```bash
   pip install daphne
   daphne -b 0.0.0.0 -p 8000 project.asgi:application
   ```
2. **Use Redis for caching** so rate limiting is atomic and shared across workers:
   ```env
   DJANGO_CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
   REDIS_URL=redis://redis:6379/1
   ```
   Add a `redis` service to `docker-compose.yml` accordingly.
3. **Rotate keys** by setting `is_active=False` on old keys and minting new ones
   via `create_mcp_key`. Old raw keys are unrecoverable — agents must be updated.
4. **Audit.** Periodically inspect `MCPApiKeyUsage` (admin or DB) to find
   unusual call patterns, denied calls, or slow tools.
5. **Per-tool allowlists.** Use `--tools ...` on `create_mcp_key` to grant a key
   the principle of least privilege even within broader capability tags.
6. **Secrets.** Never commit a real `.env` with production secrets. Use a
   secrets manager (Azure Key Vault, AWS Secrets Manager, Doppler, etc.).

---

## License

See [LICENSE](LICENSE).
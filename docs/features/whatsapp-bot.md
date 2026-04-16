# Feature: WhatsApp Bot

## Summary

Add a WhatsApp chatbot to the existing FastAPI backend. The bot receives incoming text messages from Twilio, maintains per-user multi-turn conversation history in Postgres, fetches a knowledge base document from a URL at startup and caches it in memory, and uses the Anthropic Claude API (via `AsyncAnthropic`) to generate replies. Special intents (order status, appointment booking, human handoff) are handled inline via stub responses. The bot is exposed through a new router mounted on the existing FastAPI application via the `create_app()` factory.

## Scope

- IN: Twilio WhatsApp webhook receiver with signature validation
- IN: LLM-powered replies using Anthropic Claude via `AsyncAnthropic` (native async, first-class `await`)
- IN: Knowledge base fetched from `KNOWLEDGE_BASE_URL` at startup and cached in memory; HTML responses are tag-stripped before caching
- IN: Multi-turn conversation history stored in Postgres, keyed by Twilio `From` number, truncated to `MAX_HISTORY_TURNS`
- IN: Intent detection for ORDER_STATUS, APPOINTMENT, HUMAN_HANDOFF — stub/mock responses
- IN: Graceful handling of unknown questions (LLM replies "I don't know" rather than hallucinating)
- IN: `GET /whatsapp/health` health endpoint for the WhatsApp router
- IN: Alembic migration for new `conversations` and `messages` tables
- OUT: Real order management or appointment scheduling system integration
- OUT: Media/image message handling (text only)
- OUT: Twilio Studio flows or any other Twilio product beyond the Messaging API
- OUT: Frontend changes

## Acceptance Criteria

- [ ] `POST /whatsapp/webhook` returns HTTP 200 with a valid TwiML `<Response><Message>` body for any inbound text message
- [ ] Requests with an invalid or missing Twilio signature return HTTP 403
- [ ] `GET /whatsapp/health` returns `{"status": "ok", "knowledge_base_loaded": true|false}`
- [ ] Each unique `From` number gets its own `Conversation` row; subsequent messages are appended as `Message` rows with roles `user` and `assistant`
- [ ] Conversation history passed to the LLM is limited to the last `MAX_HISTORY_TURNS` turns (one turn = one user message + one assistant message)
- [ ] A message containing the word "order" (case-insensitive) triggers an ORDER_STATUS stub response without an LLM call
- [ ] A message containing the word "appointment" or "book" (case-insensitive) triggers an APPOINTMENT stub response without an LLM call
- [ ] A message containing "human", "agent", or "representative" (case-insensitive) triggers a HUMAN_HANDOFF response without an LLM call
- [ ] Knowledge base content is injected as the system prompt for every LLM call
- [ ] If `KNOWLEDGE_BASE_URL` is not set or fetch fails at startup, the bot still starts and uses a fallback system prompt; `knowledge_base_loaded` is `false` in the health response
- [ ] All eight new env vars are documented in `.env.example` and passed through in `docker-compose.yml`
- [ ] Alembic migration `0002_create_whatsapp_tables.py` creates and drops the two new tables cleanly

## Design

### New Files

- `src/api/routers/whatsapp.py` — FastAPI router: `POST /whatsapp/webhook` and `GET /whatsapp/health`
- `src/api/services/whatsapp_service.py` — all business logic: signature validation, knowledge base fetch/cache, conversation CRUD, LLM call, intent detection, TwiML response building
- `src/api/db_models_whatsapp.py` — SQLAlchemy ORM models: `Conversation` and `Message`
- `alembic/versions/0002_create_whatsapp_tables.py` — Alembic migration

### Modified Files

- `src/api/main.py` — add lifespan context manager inside `create_app()`, include the whatsapp router
- `src/api/db_models.py` — no changes to existing models; the new ORM file `db_models_whatsapp.py` imports `Base` from here to share the same `DeclarativeBase`
- `alembic/env.py` — add `import src.api.db_models_whatsapp  # noqa: F401` so Alembic autogenerate sees the new tables (import only; no functional change)
- `pyproject.toml` — add `anthropic>=0.40` and `twilio>=9.0` to `dependencies`; `httpx>=0.27` is already in `dev` extras — move it to main `dependencies`
- `docker-compose.yml` — add eight new env vars to the `backend` service's `environment` block
- `.env.example` — append eight new vars with placeholder values
- `tests/unit/conftest.py` — add `import src.api.db_models_whatsapp  # noqa: F401` so `Base.metadata.create_all` sees the new tables

### Data Structures

#### ORM Models (`src/api/db_models_whatsapp.py`)

```python
from src.api.db_models import Base  # shared DeclarativeBase

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), nullable=False
    )
    from_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
```

#### Pydantic Schemas (defined inline in `whatsapp_service.py`, not exposed as API models)

```python
class WhatsAppHealthResponse(BaseModel):
    status: str
    knowledge_base_loaded: bool
```

Twilio form fields (`From`, `Body`, `AccountSid`) are declared as `Form(...)` parameters in the router, not as a Pydantic model, because Twilio POSTs `application/x-www-form-urlencoded`.

### Key Functions / Interfaces

#### `src/api/services/whatsapp_service.py`

```python
# Module-level cache
_knowledge_base_content: str | None = None

async def fetch_and_cache_knowledge_base(url: str) -> None:
    """Fetch text from url using httpx.AsyncClient and store in _knowledge_base_content.
    Called once at application startup via FastAPI lifespan. If the response
    Content-Type is 'text/html', strip HTML tags using stdlib html.parser
    (HTMLParser + html.unescape) before caching. If 'text/plain' or
    'text/markdown', use the body as-is. Logs and silently continues if the
    fetch fails; _knowledge_base_content remains None."""

def is_knowledge_base_loaded() -> bool:
    """Return True if the knowledge base was fetched successfully."""

def validate_twilio_signature(
    auth_token: str,
    signature: str,
    url: str,
    params: dict[str, str],
) -> bool:
    """Return True if the X-Twilio-Signature header matches the expected HMAC.
    Uses twilio.request_validator.RequestValidator."""

def detect_intent(text: str) -> str | None:
    """Return intent string or None.
    Returns 'ORDER_STATUS', 'APPOINTMENT', 'HUMAN_HANDOFF', or None.
    HUMAN_HANDOFF is checked first."""

def build_stub_response(intent: str) -> str:
    """Return a canned reply string for a detected intent.
    ORDER_STATUS: 'Your order #MOCK-001 is on its way and will arrive in 2-3 days.'
    APPOINTMENT: 'Your appointment has been booked for next Monday at 10 AM. Ref: APT-MOCK-001.'
    HUMAN_HANDOFF: 'Connecting you with our support team. Call us at +1-800-SUPPORT or email help@example.com.'"""

async def get_or_create_conversation(
    db: AsyncSession,
    from_number: str,
) -> Conversation:
    """Fetch existing Conversation by from_number or insert a new one."""

async def append_message(
    db: AsyncSession,
    conversation_id: str,
    role: str,
    content: str,
) -> Message:
    """Insert a Message row and return it."""

async def get_recent_history(
    db: AsyncSession,
    conversation_id: str,
    max_turns: int,
) -> list[dict[str, str]]:
    """Return the last max_turns*2 Message rows ordered by created_at ASC,
    formatted as [{"role": "user"|"assistant", "content": "..."}].
    max_turns=10 means up to 20 rows (10 user + 10 assistant)."""

async def call_llm(
    user_message: str,
    history: list[dict[str, str]],
    system_prompt: str,
    model: str,
    api_key: str,
) -> str:
    """Call Anthropic Claude using AsyncAnthropic (native async, first-class await).
    Instantiate AsyncAnthropic(api_key=api_key), then await client.messages.create(...).
    No asyncio.to_thread needed.
    Raises anthropic.APIError on failure; caller should catch and return a
    fallback message."""

async def handle_incoming_message(
    db: AsyncSession,
    from_number: str,
    body: str,
    anthropic_api_key: str,
    claude_model: str,
    max_history_turns: int,
) -> str:
    """Orchestrate the full pipeline:
    1. detect_intent → if match, store both sides and return stub
    2. get_or_create_conversation
    3. append user message
    4. get_recent_history
    5. call_llm
    6. append assistant message
    7. return reply text"""
```

#### `src/api/routers/whatsapp.py`

```python
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

@router.get("/health", response_model=WhatsAppHealthResponse)
async def whatsapp_health() -> WhatsAppHealthResponse:
    """Return health status and whether the knowledge base is loaded."""

@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    AccountSid: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Validate Twilio signature, process message, return TwiML Response.

    Signature validation steps:
    1. Read X-Twilio-Signature header from request.
    2. Read TWILIO_AUTH_TOKEN from env. If unset, skip validation and log warning.
    3. Read TWILIO_WEBHOOK_URL from env. If TWILIO_AUTH_TOKEN is set but
       TWILIO_WEBHOOK_URL is unset, raise HTTP 500 — do NOT fall back to
       str(request.url).
    4. Pass dict(await request.form()) — the complete Twilio field set — to
       validate_twilio_signature. Passing only the three declared Form params
       will produce wrong HMACs for real Twilio requests.
    5. If validation returns False, raise HTTPException(status_code=403).

    Returns Response(content=twiml, media_type="text/xml").
    """
```

### Startup Integration

The `lifespan` context manager is created inside `create_app()` and passed to `FastAPI(...)` within that same factory function. The existing `main.py` uses `create_app()` — the change is confined to that function body:

```python
# src/api/main.py (modified)
from contextlib import asynccontextmanager
import os

from src.api.routers import health, items, whatsapp
from src.api.services.whatsapp_service import fetch_and_cache_knowledge_base

def create_app() -> FastAPI:
    """Construct and return the configured FastAPI application instance."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        kb_url = os.getenv("KNOWLEDGE_BASE_URL")
        if kb_url:
            await fetch_and_cache_knowledge_base(kb_url)
        yield

    application = FastAPI(title="fuzzy-umbrella API", lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router)
    application.include_router(items.router)
    application.include_router(whatsapp.router)

    return application

app = create_app()
```

If a lifespan context manager is added to the existing app in future, the knowledge base fetch should be merged into it.

### Intent Detection Rules

`detect_intent` applies these checks in order (first match wins, case-insensitive against the full message text):

| Intent | Trigger keywords (any word match) |
|---|---|
| `HUMAN_HANDOFF` | `human`, `agent`, `representative`, `speak to someone` |
| `ORDER_STATUS` | `order`, `shipment`, `tracking`, `delivery` |
| `APPOINTMENT` | `appointment`, `book`, `schedule`, `reschedule` |

HUMAN_HANDOFF is checked first to prevent it being swallowed by ORDER_STATUS on a message like "I want to order an agent".

### LLM Prompt Structure

```
system: {knowledge_base_content or fallback_system_prompt}
        + "\n\nIf you do not know the answer, say so clearly and offer to connect the user with a human agent."
messages: [...history (oldest first)..., {"role": "user", "content": body}]
```

`fallback_system_prompt` = `"You are a helpful customer support assistant. Answer questions clearly and concisely."`

### Knowledge Base HTML Stripping

When `fetch_and_cache_knowledge_base` fetches the URL:

- If the response `Content-Type` starts with `text/html`: strip HTML tags using Python stdlib `html.parser`. Implement a small `MLStripper(HTMLParser)` subclass that accumulates `handle_data` text, then call `html.unescape` on the result. No third-party library is needed.
- If `text/plain` or `text/markdown`: use the response body as-is.
- Any other content type: log a warning and treat as plain text.

### TwiML Response Format

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>{reply_text}</Message>
</Response>
```

Built as a plain string (no XML library needed). Return `Response(content=twiml, media_type="text/xml")`.

### Twilio Signature Validation Detail

Validation is performed in the router (not the service) before calling `handle_incoming_message`:

1. Read `X-Twilio-Signature` header from `request`.
2. Read `TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")`. If `None`, log `WARNING: TWILIO_AUTH_TOKEN not set, skipping signature validation` and continue.
3. Read `TWILIO_WEBHOOK_URL = os.getenv("TWILIO_WEBHOOK_URL")`. If `TWILIO_AUTH_TOKEN` is set but `TWILIO_WEBHOOK_URL` is unset, raise `HTTPException(status_code=500, detail="TWILIO_WEBHOOK_URL must be set when TWILIO_AUTH_TOKEN is configured")`. Do **not** use `str(request.url)` as a fallback.
4. Collect the complete form payload: `params = dict(await request.form())`.
5. Call `validate_twilio_signature(auth_token, signature, webhook_url, params)`.
6. If `False`, raise `HTTPException(status_code=403)`.

The `validate_twilio_signature` service function receives `auth_token`, `signature`, `url`, and `params` as pure arguments — it has no direct access to the request object.

### Environment Variables

There are eight new env vars:

| Var | Required | Default | Description |
|---|---|---|---|
| `TWILIO_ACCOUNT_SID` | No | — | Twilio account SID (informational; Twilio sends it in payload) |
| `TWILIO_AUTH_TOKEN` | No* | — | Used to validate X-Twilio-Signature; if unset, validation is skipped |
| `TWILIO_WHATSAPP_FROM` | No | — | The Twilio WhatsApp sender number (e.g. `whatsapp:+14155238886`) |
| `TWILIO_WEBHOOK_URL` | Yes (prod) | — | Full URL Twilio posts to, used for signature validation; must be set if `TWILIO_AUTH_TOKEN` is set |
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `CLAUDE_MODEL` | No | `claude-haiku-4-5-20251001` | Anthropic model ID |
| `KNOWLEDGE_BASE_URL` | No | — | URL of text/HTML document to use as knowledge base |
| `MAX_HISTORY_TURNS` | No | `10` | Max conversation turns to pass to LLM |

*If `TWILIO_AUTH_TOKEN` is absent, the webhook still functions but logs a warning. In production it must be set.

Exact lines to append to `.env.example`:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WEBHOOK_URL=https://your-domain.example.com/whatsapp/webhook
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5-20251001
KNOWLEDGE_BASE_URL=https://your-domain.example.com/knowledge-base.txt
MAX_HISTORY_TURNS=10
```

Exact lines to add under the `backend` service `environment` block in `docker-compose.yml`:

```yaml
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID:-}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN:-}
      - TWILIO_WHATSAPP_FROM=${TWILIO_WHATSAPP_FROM:-}
      - TWILIO_WEBHOOK_URL=${TWILIO_WEBHOOK_URL:-}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - CLAUDE_MODEL=${CLAUDE_MODEL:-claude-haiku-4-5-20251001}
      - KNOWLEDGE_BASE_URL=${KNOWLEDGE_BASE_URL:-}
      - MAX_HISTORY_TURNS=${MAX_HISTORY_TURNS:-10}
```

### Alembic Migration (`0002_create_whatsapp_tables.py`)

```
revision = "0002"
down_revision = "0001"
```

`upgrade()` creates `conversations` then `messages` (FK order matters).
`downgrade()` drops `messages` then `conversations`.

Column spec mirrors the ORM: `String(36)` PKs with `server_default=sa.text("gen_random_uuid()")`, `String(50)` for `from_number` with a unique constraint and index, `String(20)` for `role`, `Text` for `content`, `DateTime` with `server_default=sa.func.now()` for timestamps. `messages.conversation_id` has `ForeignKey("conversations.id", ondelete="CASCADE")` and an index.

### Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| Anthropic API call fails | Catch `anthropic.APIError`; return `"I'm sorry, I'm having trouble responding right now. Please try again shortly."` |
| Knowledge base fetch fails at startup | Log warning, set `_knowledge_base_content = None`, use fallback prompt |
| Empty `Body` field from Twilio | Return TwiML with `"I didn't receive any message. Please try again."` without touching DB |
| `TWILIO_AUTH_TOKEN` not set | Log `WARNING: TWILIO_AUTH_TOKEN not set, skipping signature validation` and continue |
| `TWILIO_AUTH_TOKEN` set but `TWILIO_WEBHOOK_URL` unset | Raise HTTP 500 — misconfiguration must be explicit, not silently wrong |
| DB error during message storage | Let the exception propagate to FastAPI's default 500 handler; Twilio will retry |
| Message body exceeds reasonable length | Truncate to 1600 chars before sending to LLM (WhatsApp max is ~1600 chars) |
| Knowledge base URL returns HTML | Strip tags using stdlib `html.parser` before caching |

## Test Plan

### Unit Tests (`tests/unit/test_whatsapp_service.py`)

All external calls are mocked.

- `test_detect_intent_order`: body `"where is my order"` → `"ORDER_STATUS"`
- `test_detect_intent_appointment`: body `"I want to book an appointment"` → `"APPOINTMENT"`
- `test_detect_intent_human_handoff`: body `"let me speak to a human agent"` → `"HUMAN_HANDOFF"`
- `test_detect_intent_human_takes_priority`: body `"order human agent"` → `"HUMAN_HANDOFF"` (not ORDER_STATUS)
- `test_detect_intent_none`: body `"what are your hours?"` → `None`
- `test_build_stub_response_all_intents`: verify each intent returns a non-empty string
- `test_validate_twilio_signature_valid`: mock `RequestValidator.validate` returning `True` → returns `True`
- `test_validate_twilio_signature_invalid`: mock returning `False` → returns `False`
- `test_fetch_and_cache_knowledge_base_success`: mock `httpx.AsyncClient.get` returning 200 with `Content-Type: text/plain` and body `"KB content"` → `is_knowledge_base_loaded()` is `True`
- `test_fetch_and_cache_knowledge_base_html_stripping`: mock returning 200 with `Content-Type: text/html` and body `"<p>Hello <b>world</b></p>"` → cached content is `"Hello world"` (tags stripped)
- `test_fetch_and_cache_knowledge_base_failure`: mock raising `httpx.HTTPError` → `is_knowledge_base_loaded()` is `False`
- `test_get_recent_history_truncation`: seed 15 messages with explicit `created_at = datetime.utcnow() + timedelta(seconds=i)` (to avoid non-deterministic ordering under SQLite's 1-second timestamp resolution); call with `max_turns=5` → returns 10 messages (last 5 turns)
- `test_history_oldest_first`: verify returned messages are in ascending `created_at` order

### Unit Tests (`tests/unit/test_whatsapp_router.py`)

Uses `httpx.AsyncClient` with `ASGITransport` against the FastAPI app (same pattern as existing item tests). Mock target for the Anthropic client is `patch("src.api.services.whatsapp_service.AsyncAnthropic")`.

- `test_health_endpoint`: GET `/whatsapp/health` → 200, `{"status": "ok", "knowledge_base_loaded": false}`
- `test_webhook_missing_signature_no_auth_token_set`: when `TWILIO_AUTH_TOKEN` env var is unset, POST to webhook with valid form data → 200 (validation skipped)
- `test_webhook_invalid_signature`: when `TWILIO_AUTH_TOKEN` and `TWILIO_WEBHOOK_URL` are set, POST with wrong signature header → 403
- `test_webhook_missing_webhook_url_with_auth_token`: when `TWILIO_AUTH_TOKEN` is set but `TWILIO_WEBHOOK_URL` is unset → 500
- `test_webhook_intent_order_no_llm_call`: POST with body `"track my order"`, validation skipped → 200, response XML contains order stub text, `AsyncAnthropic` not instantiated
- `test_webhook_intent_appointment`: POST with body `"book appointment"` → response contains appointment stub
- `test_webhook_intent_human_handoff`: POST with body `"talk to human"` → response contains support contact info
- `test_webhook_llm_reply`: POST with body `"what are your hours?"`, `patch("src.api.services.whatsapp_service.AsyncAnthropic")` configured to return `"We are open 9-5"` → response XML contains that text
- `test_webhook_llm_error_graceful`: `AsyncAnthropic` mock raises `anthropic.APIError` → 200 with error message TwiML (not 500)

### conftest.py Update (`tests/unit/conftest.py`)

Add the following import **before** `Base.metadata.create_all` is called so that the new ORM tables are registered with the shared `Base`:

```python
import src.api.db_models_whatsapp  # noqa: F401
```

This ensures the `conversations` and `messages` tables are created in the in-memory SQLite DB used by all unit tests.

### Integration Tests (`tests/integration/test_whatsapp_integration.py`)

Skipped unless `TWILIO_AUTH_TOKEN` and `ANTHROPIC_API_KEY` are set in environment.

- End-to-end: POST real-form-encoded payload with a correctly computed Twilio signature (using `dict(await request.form())` field set), verify 200 + valid TwiML
- Verify `Conversation` and `Message` rows are created in the test DB

## Dependencies

| Package | Version | Justification |
|---|---|---|
| `anthropic` | `>=0.40` | Official Anthropic Python SDK; provides `AsyncAnthropic` client with native async support |
| `twilio` | `>=9.0` | Provides `twilio.request_validator.RequestValidator` for webhook signature verification; avoids hand-rolling HMAC |
| `httpx` | `>=0.27` | Already in dev deps; move to main deps for async knowledge base fetch at runtime |

No other new packages required. `xmltodict` / `lxml` not needed since TwiML output is a simple hand-built string. HTML stripping uses stdlib `html.parser` — no additional package.

## Open Questions

None. All prior open questions have been resolved:

- **Webhook URL**: Always use `TWILIO_WEBHOOK_URL` env var. If `TWILIO_AUTH_TOKEN` is set but `TWILIO_WEBHOOK_URL` is not, raise HTTP 500. `str(request.url)` fallback is removed entirely.
- **Knowledge base content type**: HTML responses are stripped via stdlib `html.parser`; plain text and markdown are used as-is.
- **Async LLM client**: Use `AsyncAnthropic` (native async). `asyncio.to_thread` and the sync `anthropic.Anthropic` client are not used.

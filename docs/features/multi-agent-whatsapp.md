# Feature: Multi-Agent WhatsApp Bot

## Summary

Extend the existing WhatsApp bot so that each conversation is handled by one of three
specialised agents — `pre_sale`, `refund_period`, or `active` — matched to the student's
lifecycle stage. On the first message of a new conversation the bot calls an external
Student Info REST API (keyed by the sender's phone number) to resolve the stage, stores
the resulting `agent_type` on the `Conversation` row, and keeps it locked for the entire
conversation lifetime. Each agent has a distinct system prompt, persona, and knowledge
base URL. All three KBs are fetched and cached in parallel at application startup.

## Scope

- IN: `AgentType` enum and `AgentConfig` dataclass in a new `agent_config.py` module
- IN: `get_student_lifecycle` async function that calls the Student Info API via `httpx`
- IN: `agent_type` VARCHAR(20) column on the `conversations` table (Alembic migration `0003`)
- IN: `get_or_resolve_agent_type` function — reads locked value or calls API and persists it
- IN: Per-agent KB fetch/cache (`PRE_SALE_KB_URL`, `POST_SALE_KB_URL`, `DURING_COURSE_KB_URL`)
- IN: Updated `handle_incoming_message` signature accepting `student_info_api_url`; selects
  system prompt + KB for the resolved agent type before calling `call_llm`
- IN: Updated `/whatsapp/health` to report per-agent KB status (breaking change — see Modified Files)
- IN: New env vars documented in `.env.example` and `docker-compose.yml`; `KNOWLEDGE_BASE_URL`
  removed from both files
- IN: Dead-code removal: `_knowledge_base_cache`, `is_knowledge_base_loaded()`, and the
  `fetch_and_cache_knowledge_base` import in `main.py` are all deleted from `whatsapp_service.py`
- OUT: Model-per-agent differentiation (same Claude model throughout)
- OUT: Mid-conversation agent switching (locked at first message)
- OUT: Any local `students` table — lifecycle is always resolved via the external API
- OUT: Changes to intent detection, stub responses, or Twilio signature validation

## Acceptance Criteria

- [ ] `AgentType` enum has exactly three values: `pre_sale`, `refund_period`, `active`
- [ ] On the first message of a conversation, the Student Info API is called once; the
  returned `agent_type` is persisted to `conversations.agent_type` and used for that call
- [ ] On every subsequent message in the same conversation, the Student Info API is NOT
  called; the stored `agent_type` is used directly (locked for conversation lifetime)
- [ ] If the Student Info API is unreachable OR returns an unknown/missing lifecycle stage,
  `AgentType.pre_sale` is used as the fallback
- [ ] Each agent type uses its own distinct system prompt (verified by substring assertions
  in tests)
- [ ] Each agent type uses its own KB, loaded at startup from the corresponding env var URL;
  if a URL is empty/unset the agent falls back to a hardcoded fallback prompt
- [ ] All three KBs are loaded in parallel at startup via `asyncio.gather`
- [ ] `GET /whatsapp/health` returns per-agent KB status:
  `{"status": "ok", "knowledge_base_loaded": {"pre_sale": bool, "refund_period": bool, "active": bool}}`
- [ ] Alembic migration `0003` adds `agent_type VARCHAR(20) NULL` to `conversations` and
  rolls back cleanly
- [ ] All four new env vars are present in `.env.example` and `docker-compose.yml`
- [ ] `KNOWLEDGE_BASE_URL` is absent from `docker-compose.yml` and `.env.example` after
  this change

## Design

### New Files

- `src/api/services/agent_config.py` — `AgentType` enum, `AgentConfig` dataclass,
  `AGENT_CONFIGS` dict, `get_agent_config()`, per-agent KB cache (`_kb_cache`), KB
  load/get helpers
- `src/api/services/student_service.py` — `get_student_lifecycle()` async function
- `alembic/versions/0003_add_agent_type_to_conversations.py` — migration

### Modified Files

- `src/api/db_models_whatsapp.py` — add `agent_type` column to `Conversation`
- `src/api/services/whatsapp_service.py` — add `get_or_resolve_agent_type`; update
  `handle_incoming_message` to accept `student_info_api_url` and use agent config;
  **remove** `_knowledge_base_cache` module-level dict, `is_knowledge_base_loaded()`,
  and the (now-unused) single-KB path entirely — these are dead code after the migration
- `src/api/routers/whatsapp.py` — update health response schema from `knowledge_base_loaded: bool`
  to `knowledge_base_loaded: KbStatusResponse` — **this is a breaking API change** for
  any existing caller polling `/whatsapp/health`; pass `STUDENT_INFO_API_URL` to
  `handle_incoming_message`
- `src/api/main.py` — replace `fetch_and_cache_knowledge_base` call in lifespan with
  `load_all_knowledge_bases()`; remove the `fetch_and_cache_knowledge_base` import
- `docker-compose.yml` — remove `KNOWLEDGE_BASE_URL`; add four new env vars to
  `backend.environment`
- `.env.example` — remove `KNOWLEDGE_BASE_URL`; append four new vars with placeholder
  values

### Data Structures

#### `src/api/services/agent_config.py`

```python
import enum
from dataclasses import dataclass

class AgentType(str, enum.Enum):
    pre_sale = "pre_sale"
    refund_period = "refund_period"
    active = "active"

@dataclass(frozen=True)
class AgentConfig:
    agent_type: AgentType
    system_prompt: str          # base persona prompt (KB content is prepended at call time)
    kb_url_env_var: str         # name of the env var holding the KB URL

AGENT_CONFIGS: dict[AgentType, AgentConfig] = {
    AgentType.pre_sale: AgentConfig(
        agent_type=AgentType.pre_sale,
        system_prompt=(
            "You are a helpful and enthusiastic sales assistant for Scaler Academy. "
            "Highlight product benefits, answer pricing and feature queries clearly, "
            "and guide prospective students towards enrollment."
        ),
        kb_url_env_var="PRE_SALE_KB_URL",
    ),
    AgentType.refund_period: AgentConfig(
        agent_type=AgentType.refund_period,
        system_prompt=(
            "You are an empathetic, calm, and patient counselor for students in their "
            "refund period. Acknowledge concerns with understanding, provide clear "
            "clarifications about the course and placement support, and help reduce anxiety."
        ),
        kb_url_env_var="POST_SALE_KB_URL",
    ),
    AgentType.active: AgentConfig(
        agent_type=AgentType.active,
        system_prompt=(
            "You are an efficient platform support specialist for active Scaler students. "
            "Help with platform usage, troubleshoot technical issues concisely, and "
            "escalate to human support when appropriate."
        ),
        kb_url_env_var="DURING_COURSE_KB_URL",
    ),
}

# Module-level per-agent KB cache — populated at startup
_kb_cache: dict[AgentType, str | None] = {t: None for t in AgentType}

_FALLBACK_KB_PROMPT = (
    "You are a helpful assistant. Answer questions clearly and concisely."
)
```

#### `Conversation` ORM change (`src/api/db_models_whatsapp.py`)

```python
# Add to existing Conversation class:
agent_type: Mapped[str | None] = mapped_column(
    String(20),
    nullable=True,
    default=None,
)
```

### Key Functions / Interfaces

#### `src/api/services/agent_config.py`

```python
def get_agent_config(agent_type: AgentType) -> AgentConfig:
    """Return the AgentConfig for the given AgentType. Always succeeds."""

async def load_kb_for_agent(agent_type: AgentType) -> None:
    """Fetch and cache the KB for one agent.

    Reads the URL from os.getenv(config.kb_url_env_var). If the env var is
    unset or empty, sets _kb_cache[agent_type] = None and returns immediately
    without making any HTTP call.

    To avoid a circular import (agent_config is imported by whatsapp_service,
    which would create a cycle if agent_config also imported from whatsapp_service
    at module level), use a LOCAL import inside the function body:

        from src.api.services.whatsapp_service import fetch_and_cache_knowledge_base

    Call fetch_and_cache_knowledge_base(url) and assign its RETURN VALUE directly
    to _kb_cache[agent_type]. Do NOT rely on the side-effect that
    fetch_and_cache_knowledge_base also writes to _knowledge_base_cache in
    whatsapp_service — that global is being removed as dead code.

    Logs a warning on fetch failure; leaves _kb_cache[agent_type] as None.
    """

async def load_all_knowledge_bases() -> None:
    """Load all three agent KBs in parallel.

    Calls asyncio.gather(
        load_kb_for_agent(AgentType.pre_sale),
        load_kb_for_agent(AgentType.refund_period),
        load_kb_for_agent(AgentType.active),
    )

    Repeated calls are idempotent (the gather will simply overwrite _kb_cache
    entries with fresh values or None). No guard against concurrent calls is
    needed because asyncio is single-threaded; in tests, the autouse fixture
    resets _kb_cache between tests so in-flight coroutines from a prior test
    cannot pollute a subsequent one.
    """

def get_kb_for_agent(agent_type: AgentType) -> str | None:
    """Return the cached KB string for agent_type, or None if not loaded."""

def is_kb_loaded_for_agent(agent_type: AgentType) -> bool:
    """Return True if the KB for agent_type was fetched successfully."""
```

#### `src/api/services/student_service.py`

```python
import logging
import httpx
from src.api.services.agent_config import AgentType

logger = logging.getLogger(__name__)

async def get_student_lifecycle(phone_number: str, api_url: str) -> AgentType:
    """Call the Student Info API and return the matching AgentType.

    Makes a GET request to:
        {api_url}?phone={phone_number}
    with timeout=30 (seconds), using params={"phone": phone_number} so that
    special characters in the phone number are URL-encoded by httpx.

    Expects JSON: {"lifecycle_stage": "pre_sale" | "refund_period" | "active"}

    Returns AgentType.pre_sale on ANY of these conditions:
    - httpx connection error or timeout (any subclass of httpx.HTTPError)
    - httpx.InvalidURL (e.g. api_url is empty string) — NOTE: httpx.InvalidURL
      is NOT a subclass of httpx.HTTPError; it must be caught separately as
      except (httpx.HTTPError, httpx.InvalidURL)
    - HTTP response status >= 400 (httpx.HTTPStatusError, subclass of httpx.HTTPError)
    - Response body is not valid JSON (ValueError / json.JSONDecodeError)
    - "lifecycle_stage" key is absent from the JSON (KeyError)
    - "lifecycle_stage" value does not match any AgentType member (ValueError)

    Logs a WARNING in every fallback case with the reason.
    Never raises.
    """
```

The httpx call must use the pattern:

```python
async with httpx.AsyncClient() as client:
    response = await client.get(api_url, params={"phone": phone_number}, timeout=30)
    response.raise_for_status()
    data = response.json()
    return AgentType(data["lifecycle_stage"])
```

Wrap in `try/except (httpx.HTTPError, httpx.InvalidURL)` as two distinct types in a
single tuple — matching the pattern already used in `fetch_and_cache_knowledge_base` in
`whatsapp_service.py`. Inner `KeyError` and `ValueError` are caught in a separate
`except (KeyError, ValueError)` block.

**Import style lock-in:** `whatsapp_service.py` must use a top-level import:

```python
from src.api.services.student_service import get_student_lifecycle
```

This ensures the correct mock target in tests is:
`patch("src.api.services.whatsapp_service.get_student_lifecycle")`

#### `src/api/services/whatsapp_service.py` additions

```python
async def get_or_resolve_agent_type(
    db: AsyncSession,
    conversation: Conversation,
    from_number: str,
    student_info_api_url: str,
) -> AgentType:
    """Return the agent type for this conversation, resolving it if not yet set.

    If conversation.agent_type is already set (non-None), convert it to AgentType
    and return immediately — no API call is made.

    Otherwise:
    1. Call get_student_lifecycle(from_number, student_info_api_url).
    2. Set conversation.agent_type = agent_type.value  (the string "pre_sale" etc.)
    3. await db.flush()  — persists within the current transaction.
    4. Return the AgentType.

    The caller (handle_incoming_message) already calls db.commit() at the end of
    the pipeline, so no separate commit is needed here.
    """
```

**Updated `handle_incoming_message` signature:**

```python
async def handle_incoming_message(
    db: AsyncSession,
    from_number: str,
    body: str,
    anthropic_api_key: str,
    claude_model: str,
    max_history_turns: int,
    student_info_api_url: str,          # NEW — added as last keyword argument
) -> str:
    """Orchestrate the full inbound-message pipeline (multi-agent version).

    Steps (explicit ordering):
    1. Guard against empty body.
    2. Truncate body to _MAX_BODY_LENGTH characters.
    3. detect_intent — if matched:
         3a. get_or_create_conversation (Conversation row must exist first)
         3b. get_or_resolve_agent_type(db, conversation, from_number, student_info_api_url)
             (agent_type is resolved even for intent messages so the DB row is always
             populated after the first call)
         3c. store both turns (user + stub)
         3d. await db.commit(); return stub
    4. get_or_create_conversation (for non-intent messages).
    5. get_or_resolve_agent_type(db, conversation, from_number, student_info_api_url).
       NOTE: step 4 must complete before step 5 — get_or_resolve_agent_type requires the
       Conversation object to already exist in the DB.
    6. get_recent_history.
    7. Build system_prompt from agent config:
         kb = get_kb_for_agent(agent_type) or agent_config.system_prompt
         system_prompt = kb + "\\n\\n" + agent_config.system_prompt + _LLM_SUFFIX
       (KB content provides domain facts; system_prompt provides persona.)
       If kb is None (not loaded), use agent_config.system_prompt alone + _LLM_SUFFIX.
    8. call_llm with the resolved system_prompt.
    9. store user and assistant messages.
    10. return reply text.
    """
```

**System prompt assembly (step 7 detail):**

| KB loaded? | System prompt passed to `call_llm` |
|---|---|
| Yes | `{kb_content}\n\n{agent_config.system_prompt}{_LLM_SUFFIX}` |
| No  | `{agent_config.system_prompt}{_LLM_SUFFIX}` |

`_LLM_SUFFIX` is the existing constant already defined in the module:
`"\n\nIf you do not know the answer, say so clearly and offer to connect the user with a human agent."`

#### `src/api/routers/whatsapp.py` changes

Update `WhatsAppHealthResponse` (breaking change: `knowledge_base_loaded` type changes
from `bool` to `KbStatusResponse` — existing callers polling `/whatsapp/health` must
be updated to handle the new nested dict shape):

```python
class KbStatusResponse(BaseModel):
    pre_sale: bool
    refund_period: bool
    active: bool

class WhatsAppHealthResponse(BaseModel):
    status: str
    knowledge_base_loaded: KbStatusResponse   # was: bool — breaking API change
```

Update `whatsapp_health`:

```python
@router.get("/health", response_model=WhatsAppHealthResponse)
async def whatsapp_health() -> WhatsAppHealthResponse:
    return WhatsAppHealthResponse(
        status="ok",
        knowledge_base_loaded=KbStatusResponse(
            pre_sale=is_kb_loaded_for_agent(AgentType.pre_sale),
            refund_period=is_kb_loaded_for_agent(AgentType.refund_period),
            active=is_kb_loaded_for_agent(AgentType.active),
        ),
    )
```

Update `whatsapp_webhook` — add one line before calling `handle_incoming_message`:

```python
student_info_api_url = os.getenv("STUDENT_INFO_API_URL", "")
reply = await handle_incoming_message(
    db=db,
    from_number=From,
    body=Body,
    anthropic_api_key=anthropic_api_key,
    claude_model=claude_model,
    max_history_turns=max_history_turns,
    student_info_api_url=student_info_api_url,
)
```

#### `src/api/main.py` lifespan update

```python
# Replace the single fetch_and_cache_knowledge_base call with:
from src.api.services.agent_config import load_all_knowledge_bases

@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_all_knowledge_bases()   # fetches all 3 KBs in parallel; no-ops for unset URLs
    yield
```

Remove the import of `fetch_and_cache_knowledge_base` from `main.py`. The old
`KNOWLEDGE_BASE_URL` / `fetch_and_cache_knowledge_base` single-KB logic is **removed**
from `main.py` entirely.

### ORM Column DDL (`src/api/db_models_whatsapp.py`)

```python
agent_type: Mapped[str | None] = mapped_column(
    String(20),
    nullable=True,
    default=None,
)
```

Note: `default=None` sets the Python-side default. No `server_default` — NULL is the
intentional initial state for existing rows.

### Alembic Migration `0003`

```
filename : alembic/versions/0003_add_agent_type_to_conversations.py
revision : "0003"
down_revision : "0002"
```

```python
def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("agent_type", sa.String(20), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("conversations", "agent_type")
```

No index is needed — `agent_type` is read only after the row is already loaded by primary
key or `from_number` lookup.

### Environment Variables

Four new env vars (in addition to all existing ones from the whatsapp-bot feature).
`KNOWLEDGE_BASE_URL` is removed from both files:

| Var | Required | Default | Description |
|---|---|---|---|
| `STUDENT_INFO_API_URL` | Yes (prod) | `""` | Base URL of the Student Info API; queried as `GET {url}?phone={number}` |
| `PRE_SALE_KB_URL` | No | `""` | Knowledge base URL for the `pre_sale` agent |
| `POST_SALE_KB_URL` | No | `""` | Knowledge base URL for the `refund_period` agent |
| `DURING_COURSE_KB_URL` | No | `""` | Knowledge base URL for the `active` agent |

If `STUDENT_INFO_API_URL` is empty, `get_student_lifecycle` will receive `""` as `api_url`
and the `httpx.get` call will raise `httpx.InvalidURL` — caught by
`except (httpx.HTTPError, httpx.InvalidURL)` — falling back to `AgentType.pre_sale`.

Lines to append to `.env.example` (remove the `KNOWLEDGE_BASE_URL` line):

```
# Multi-agent routing
STUDENT_INFO_API_URL=https://your-student-api.example.com/student
PRE_SALE_KB_URL=https://your-domain.example.com/kb-pre-sale.txt
POST_SALE_KB_URL=https://your-domain.example.com/kb-post-sale.txt
DURING_COURSE_KB_URL=https://your-domain.example.com/kb-during-course.txt
```

Lines to add under `backend.environment` in `docker-compose.yml` (remove the
`KNOWLEDGE_BASE_URL` line):

```yaml
      - STUDENT_INFO_API_URL=${STUDENT_INFO_API_URL:-}
      - PRE_SALE_KB_URL=${PRE_SALE_KB_URL:-}
      - POST_SALE_KB_URL=${POST_SALE_KB_URL:-}
      - DURING_COURSE_KB_URL=${DURING_COURSE_KB_URL:-}
```

### Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| Student Info API unreachable / timeout | `httpx.HTTPError` caught in `get_student_lifecycle` via `except (httpx.HTTPError, httpx.InvalidURL)`; log WARNING; return `AgentType.pre_sale` |
| Student Info API returns HTTP 4xx/5xx | `response.raise_for_status()` raises `httpx.HTTPStatusError` (subclass of `httpx.HTTPError`); same handler; fallback |
| Response JSON missing `lifecycle_stage` key | `KeyError` caught separately; log WARNING; return `AgentType.pre_sale` |
| `lifecycle_stage` value not a valid `AgentType` | `ValueError` from `AgentType(value)` caught separately; log WARNING; return `AgentType.pre_sale` |
| `STUDENT_INFO_API_URL` env var not set / empty | Empty string passed as `api_url`; `httpx.InvalidURL` raised (NOT a subclass of `httpx.HTTPError` — caught separately in the same tuple); fallback to `AgentType.pre_sale` |
| KB URL not set for an agent | `load_kb_for_agent` detects empty env var, sets `_kb_cache[agent_type] = None`, no HTTP call |
| KB fetch fails for one agent | Log WARNING; `_kb_cache[agent_type]` stays `None`; agent uses its system_prompt fallback |
| `conversation.agent_type` already set | `get_or_resolve_agent_type` returns immediately; no API call; effectively locked |
| Existing conversations (pre-migration, NULL `agent_type`) | Treated as new: API called on next message, value persisted |

## Test Plan

### New unit test file: `tests/unit/test_agent_config.py`

**Mock target for httpx in `load_kb_for_agent` tests:**
`load_kb_for_agent` calls `fetch_and_cache_knowledge_base` via a local import from
`whatsapp_service`. The httpx client is used inside that function, so the patch target is
`patch("src.api.services.whatsapp_service.httpx.AsyncClient")`.

- `test_get_agent_config_returns_valid_config_for_all_types`: parametrize over all three
  `AgentType` values; assert `get_agent_config(t)` returns an `AgentConfig` with
  `.agent_type == t` and non-empty `.system_prompt`
- `test_agent_config_system_prompt_pre_sale_contains_sales_keyword`: assert `"sales"` or
  `"enrollment"` (case-insensitive) in `pre_sale` system prompt
- `test_agent_config_system_prompt_refund_period_contains_empathy_keyword`: assert
  `"empathetic"` or `"calm"` in `refund_period` system prompt
- `test_agent_config_system_prompt_active_contains_support_keyword`: assert `"support"` or
  `"platform"` in `active` system prompt
- `test_is_kb_loaded_for_agent_initially_false`: all three `AgentType` values return `False`
  before any load
- `test_get_kb_for_agent_returns_none_initially`: all three return `None`
- `test_load_kb_for_agent_success`: mock httpx returning `text/plain` body `"Sales KB"` for
  env var `PRE_SALE_KB_URL=http://example.com/kb.txt`; assert
  `get_kb_for_agent(AgentType.pre_sale) == "Sales KB"` and
  `is_kb_loaded_for_agent(AgentType.pre_sale) is True`
- `test_load_kb_for_agent_unset_url`: env var unset; assert `is_kb_loaded_for_agent` is
  `False` and no httpx call is made
- `test_load_all_knowledge_bases_parallel`: mock all three env vars and httpx; call
  `await load_all_knowledge_bases()`; assert all three `is_kb_loaded_for_agent` return
  `True`

Add an `autouse` fixture to reset `_kb_cache` before/after each test:

```python
@pytest.fixture(autouse=True)
def reset_kb_cache():
    import src.api.services.agent_config as ac
    for t in ac.AgentType:
        ac._kb_cache[t] = None
    yield
    for t in ac.AgentType:
        ac._kb_cache[t] = None
```

### New unit test file: `tests/unit/test_student_service.py`

Mock target: `patch("src.api.services.student_service.httpx.AsyncClient")`

All tests follow the same mock pattern already used in `test_whatsapp_service.py` for
httpx (mock `AsyncClient.__aenter__`, `__aexit__`, and `get`).

- `test_get_student_lifecycle_pre_sale`: mock returns `{"lifecycle_stage": "pre_sale"}`;
  assert result is `AgentType.pre_sale`
- `test_get_student_lifecycle_refund_period`: mock returns
  `{"lifecycle_stage": "refund_period"}`; assert `AgentType.refund_period`
- `test_get_student_lifecycle_active`: mock returns `{"lifecycle_stage": "active"}`;
  assert `AgentType.active`
- `test_get_student_lifecycle_unknown_stage_fallback`: mock returns
  `{"lifecycle_stage": "vip"}`; assert `AgentType.pre_sale`
- `test_get_student_lifecycle_missing_key_fallback`: mock returns `{"user_id": 42}`;
  assert `AgentType.pre_sale`
- `test_get_student_lifecycle_http_error_fallback`: mock raises `httpx.HTTPError`;
  assert `AgentType.pre_sale`
- `test_get_student_lifecycle_http_status_error_fallback`: mock response has
  `raise_for_status` raising `httpx.HTTPStatusError`; assert `AgentType.pre_sale`
- `test_get_student_lifecycle_uses_phone_as_query_param`: capture the call to
  `mock_client.get`; assert it was called with `params={"phone": "+911234567890"}`
- `test_get_student_lifecycle_invalid_json_fallback`: mock `response.json()` raising
  `ValueError`; assert `AgentType.pre_sale`
- `test_get_student_lifecycle_invalid_url_fallback`: pass `api_url=""` (no mock needed);
  assert result is `AgentType.pre_sale` (exercises the `httpx.InvalidURL` branch)

### Existing Tests to Update

#### `tests/unit/test_whatsapp_service.py`

**Existing `handle_incoming_message` call sites (5 total):** every existing call omits
`student_info_api_url`. After the signature change this produces `TypeError`. Add
`student_info_api_url="http://mock-student-api"` as a keyword argument to all 5 existing
call sites.

**Mock for `get_student_lifecycle` in existing tests that call
`handle_incoming_message`:** add `patch("src.api.services.whatsapp_service.get_student_lifecycle")`
returning `AgentType.pre_sale` as a default in any existing test that does not specifically
test agent routing (so the test does not attempt a real HTTP call).

**Autouse fixture — add** a fixture to also reset `_kb_cache` in `agent_config` between
tests (in addition to any existing cache-reset fixture already present):

```python
@pytest.fixture(autouse=True)
def reset_agent_kb_cache():
    import src.api.services.agent_config as ac
    for t in ac.AgentType:
        ac._kb_cache[t] = None
    yield
    for t in ac.AgentType:
        ac._kb_cache[t] = None
```

**New tests (append to file):**

- `test_get_or_resolve_agent_type_locked_conversation`: create a `Conversation` with
  `agent_type="active"` already set; call `get_or_resolve_agent_type` with a mock for
  `get_student_lifecycle`; assert mock is NOT called and result is `AgentType.active`

- `test_get_or_resolve_agent_type_new_conversation_calls_api`: create a `Conversation`
  with `agent_type=None`; mock `get_student_lifecycle` to return
  `AgentType.refund_period`; call `get_or_resolve_agent_type`; assert
  `conversation.agent_type == "refund_period"` after the call

- `test_handle_incoming_message_uses_pre_sale_system_prompt`: set
  `_kb_cache[AgentType.pre_sale] = None`; mock `get_student_lifecycle` to return
  `AgentType.pre_sale`; capture the `system` argument passed to
  `AsyncAnthropic.messages.create`; assert it contains `"sales"` or `"enrollment"`

- `test_handle_incoming_message_uses_refund_period_system_prompt`: same pattern, mock
  returns `AgentType.refund_period`; assert captured system prompt contains
  `"empathetic"` or `"calm"`

- `test_handle_incoming_message_uses_active_system_prompt`: mock returns `AgentType.active`;
  assert system prompt contains `"platform"` or `"support specialist"`

- `test_handle_incoming_message_prepends_kb_to_system_prompt`: set
  `_kb_cache[AgentType.active] = "Active KB content"`; mock `get_student_lifecycle`
  returning `AgentType.active`; assert captured `system` argument starts with
  `"Active KB content"`

All new `handle_incoming_message` calls must include
`student_info_api_url="http://mock-student-api"`.

Mock target for `get_student_lifecycle` in all `test_whatsapp_service.py` tests:
`patch("src.api.services.whatsapp_service.get_student_lifecycle")`
(valid because `whatsapp_service.py` uses a top-level
`from src.api.services.student_service import get_student_lifecycle` import).

#### `tests/unit/test_whatsapp_router.py`

**Delete these two tests** (superseded by the new nested-dict health test below):
- `test_health_endpoint_no_knowledge_base`
- `test_health_endpoint_knowledge_base_loaded`

**Replace the `reset_knowledge_base_cache` autouse fixture.** The existing fixture resets
`svc._knowledge_base_cache` — that global is being removed. Replace with a fixture that
resets `agent_config._kb_cache` instead:

```python
@pytest.fixture(autouse=True)
def reset_kb_cache():
    import src.api.services.agent_config as ac
    for t in ac.AgentType:
        ac._kb_cache[t] = None
    yield
    for t in ac.AgentType:
        ac._kb_cache[t] = None
```

Remove any remaining references to `svc._knowledge_base_cache` in the file (manual
set calls in existing tests that tried to simulate "KB loaded" state).

**New test (add to file):**

- `test_health_endpoint_returns_per_agent_kb_status`: GET `/whatsapp/health`; assert
  response JSON matches exactly:
  `{"status": "ok", "knowledge_base_loaded": {"pre_sale": false, "refund_period": false, "active": false}}`
  (all false because `_kb_cache` is reset to `None` by the autouse fixture)

### conftest.py

No changes required — `db_models_whatsapp` is already imported and `Base.metadata` will
pick up the new `agent_type` column automatically.

## Dependencies

No new packages. `httpx` (already in main deps) is used for the Student Info API call.
`asyncio` (stdlib) is used for `asyncio.gather` in `load_all_knowledge_bases`.

## Open Questions

None. All design decisions have been resolved by the product owner:

- Lifecycle resolved via external API only (no local table)
- Same Claude model for all agents
- Separate KB URL per agent
- Agent locked at first message for the lifetime of the conversation

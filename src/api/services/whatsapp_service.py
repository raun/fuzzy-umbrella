"""WhatsApp bot business logic.

Handles Twilio signature validation, knowledge base fetch/cache, conversation
CRUD, intent detection, LLM calls via AsyncAnthropic, and TwiML response
building.
"""

import html
import logging
from html.parser import HTMLParser

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from src.api.db_models_whatsapp import Conversation, Message
from src.api.services.agent_config import AgentType, get_agent_config, get_kb_for_agent
from src.api.services.student_service import get_student_lifecycle

logger = logging.getLogger(__name__)

_LLM_SUFFIX = (
    "\n\nIf you do not know the answer, say so clearly and offer to connect the user"
    " with a human agent."
)


# ---------------------------------------------------------------------------
# HTML stripping helper
# ---------------------------------------------------------------------------


class _MLStripper(HTMLParser):
    """Minimal HTMLParser subclass that accumulates visible text."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        """Accumulate visible text nodes."""
        self._parts.append(data)

    def get_text(self) -> str:
        """Return all accumulated text joined together."""
        return html.unescape("".join(self._parts))


def _strip_html(raw: str) -> str:
    """Return plain text stripped of all HTML tags."""
    stripper = _MLStripper()
    stripper.feed(raw)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


async def fetch_and_cache_knowledge_base(url: str) -> str:
    """Fetch text from url and return the plain-text content.

    If the response Content-Type is 'text/html', strips tags using stdlib
    html.parser before returning. On fetch failure, logs a warning and returns
    an empty string.

    Returns the fetched text on success, or "" on failure.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        body = response.text

        if content_type.startswith("text/html"):
            body = _strip_html(body)
            logger.info("Knowledge base fetched from %s (HTML stripped, %d chars)", url, len(body))
        elif content_type.startswith("text/plain") or content_type.startswith("text/markdown"):
            logger.info("Knowledge base fetched from %s (%d chars)", url, len(body))
        else:
            logger.warning(
                "Knowledge base URL %s returned unexpected Content-Type %r; treating as plain text",
                url,
                content_type,
            )

        return body

    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning("Failed to fetch knowledge base from %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# Twilio signature validation
# ---------------------------------------------------------------------------


def validate_twilio_signature(
    auth_token: str,
    signature: str,
    url: str,
    params: dict[str, str],
) -> bool:
    """Return True if the X-Twilio-Signature header matches the expected HMAC.

    Uses twilio.request_validator.RequestValidator. Returns False if the
    signature does not match.
    """
    validator = RequestValidator(auth_token)
    return validator.validate(url, params, signature)


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

_INTENT_RULES: list[tuple[str, list[str]]] = [
    ("HUMAN_HANDOFF", ["human", "agent", "representative", "speak to someone"]),
    ("ORDER_STATUS", ["order", "shipment", "tracking", "delivery"]),
    ("APPOINTMENT", ["appointment", "book", "schedule", "reschedule"]),
]


def detect_intent(text: str) -> str | None:
    """Return an intent string or None based on keyword matching.

    Checks HUMAN_HANDOFF first so it is not shadowed by ORDER_STATUS on messages
    like 'I want to order an agent'. Returns 'ORDER_STATUS', 'APPOINTMENT',
    'HUMAN_HANDOFF', or None.
    """
    lowered = text.lower()
    for intent, keywords in _INTENT_RULES:
        if any(kw in lowered for kw in keywords):
            return intent
    return None


def build_stub_response(intent: str) -> str:
    """Return a canned reply string for a detected intent.

    ORDER_STATUS: shipping ETA stub.
    APPOINTMENT: booking confirmation stub.
    HUMAN_HANDOFF: contact details stub.
    """
    stubs: dict[str, str] = {
        "ORDER_STATUS": (
            "Your order #MOCK-001 is on its way and will arrive in 2-3 days."
        ),
        "APPOINTMENT": (
            "Your appointment has been booked for next Monday at 10 AM. Ref: APT-MOCK-001."
        ),
        "HUMAN_HANDOFF": (
            "Connecting you with our support team."
            " Call us at +1-800-SUPPORT or email help@example.com."
        ),
    }
    return stubs.get(intent, "I'm not sure how to help with that.")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


async def get_or_create_conversation(
    db: AsyncSession,
    from_number: str,
) -> Conversation:
    """Fetch existing Conversation by from_number or insert a new one.

    Returns the Conversation ORM instance (either pre-existing or freshly
    created and flushed).
    """
    result = await db.execute(
        select(Conversation).where(Conversation.from_number == from_number)
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        conversation = Conversation(from_number=from_number)
        db.add(conversation)
        await db.flush()
        logger.info("Created new conversation id=%s for from_number=%r", conversation.id, from_number)

    return conversation


async def append_message(
    db: AsyncSession,
    conversation_id: str,
    role: str,
    content: str,
) -> Message:
    """Insert a Message row and return it.

    Role must be 'user' or 'assistant'.
    """
    message = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(message)
    await db.flush()
    return message


async def get_recent_history(
    db: AsyncSession,
    conversation_id: str,
    max_turns: int,
) -> list[dict[str, str]]:
    """Return the last max_turns*2 Message rows ordered by created_at ASC.

    Formatted as [{"role": "user"|"assistant", "content": "..."}].
    max_turns=10 means up to 20 rows (10 user + 10 assistant messages).
    """
    limit = max_turns * 2

    # Fetch the last `limit` rows ordered descending, then reverse for ASC output.
    subq_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(reversed(subq_result.scalars().all()))

    return [{"role": m.role, "content": m.content} for m in messages]


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


async def call_llm(
    user_message: str,
    history: list[dict[str, str]],
    system_prompt: str,
    model: str,
    api_key: str,
) -> str:
    """Call Anthropic Claude using AsyncAnthropic (native async, first-class await).

    Instantiates AsyncAnthropic(api_key=api_key), then awaits client.messages.create.
    Raises anthropic.APIError on failure; the caller should catch and return a
    fallback message.
    """
    client = AsyncAnthropic(api_key=api_key)
    messages = history + [{"role": "user", "content": user_message}]

    response = await client.messages.create(
        model=model,
        max_tokens=500,
        system=system_prompt,
        messages=messages,  # type: ignore[arg-type]
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Agent type resolution
# ---------------------------------------------------------------------------


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
    if conversation.agent_type is not None:
        return AgentType(conversation.agent_type)

    agent_type = await get_student_lifecycle(from_number, student_info_api_url)
    conversation.agent_type = agent_type.value
    await db.flush()
    return agent_type


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

_MAX_BODY_LENGTH = 1600  # WhatsApp maximum message length


async def handle_incoming_message(
    db: AsyncSession,
    from_number: str,
    body: str,
    anthropic_api_key: str,
    claude_model: str,
    max_history_turns: int,
    student_info_api_url: str,
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
    import anthropic  # local import to keep top-level imports clean

    if not body.strip():
        return "I didn't receive any message. Please try again."

    body = body[:_MAX_BODY_LENGTH]

    intent = detect_intent(body)
    if intent:
        stub = build_stub_response(intent)
        conversation = await get_or_create_conversation(db, from_number)
        await get_or_resolve_agent_type(db, conversation, from_number, student_info_api_url)
        await append_message(db, conversation.id, "user", body)
        await append_message(db, conversation.id, "assistant", stub)
        await db.commit()
        logger.info(
            "Intent %r matched for conversation %s; returning stub", intent, conversation.id
        )
        return stub

    conversation = await get_or_create_conversation(db, from_number)
    agent_type = await get_or_resolve_agent_type(db, conversation, from_number, student_info_api_url)

    history = await get_recent_history(db, conversation.id, max_history_turns)

    agent_cfg = get_agent_config(agent_type)
    kb = get_kb_for_agent(agent_type)
    if kb:
        system_prompt = kb + "\n\n" + agent_cfg.system_prompt + _LLM_SUFFIX
    else:
        system_prompt = agent_cfg.system_prompt + _LLM_SUFFIX

    try:
        reply = await call_llm(
            user_message=body,
            history=history,
            system_prompt=system_prompt,
            model=claude_model,
            api_key=anthropic_api_key,
        )
    except anthropic.APIError as exc:
        logger.error("Anthropic API error for conversation %s: %s", conversation.id, exc)
        reply = (
            "I'm sorry, I'm having trouble responding right now."
            " Please try again shortly."
        )

    await append_message(db, conversation.id, "user", body)
    await append_message(db, conversation.id, "assistant", reply)
    await db.commit()

    logger.info("Handled message for conversation %s (reply %d chars)", conversation.id, len(reply))
    return reply

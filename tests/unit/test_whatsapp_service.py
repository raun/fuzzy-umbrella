"""Unit tests for src/api/services/whatsapp_service.py.

All external I/O (httpx, Twilio RequestValidator, AsyncAnthropic) is mocked.
The in-memory SQLite database provided by the conftest fixtures is used for
tests that exercise database helper functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.api.services.whatsapp_service as svc
from src.api.services.whatsapp_service import (
    _strip_html,
    build_stub_response,
    detect_intent,
    fetch_and_cache_knowledge_base,
    get_or_create_conversation,
    append_message,
    get_recent_history,
    validate_twilio_signature,
)
from src.api.services.agent_config import AgentType


# ---------------------------------------------------------------------------
# Helpers: reset module-level cache between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_agent_kb_cache():
    """Reset agent_config._kb_cache to None before and after each test."""
    import src.api.services.agent_config as ac
    for t in ac.AgentType:
        ac._kb_cache[t] = None
    yield
    for t in ac.AgentType:
        ac._kb_cache[t] = None


# ---------------------------------------------------------------------------
# detect_intent — keyword matching
# ---------------------------------------------------------------------------


def test_detect_intent_human_handoff():
    """'speak to someone' should trigger HUMAN_HANDOFF intent."""
    assert detect_intent("I want to speak to someone now") == "HUMAN_HANDOFF"


def test_detect_intent_human_handoff_agent_keyword():
    """'agent' keyword alone triggers HUMAN_HANDOFF."""
    assert detect_intent("Can I talk to an agent?") == "HUMAN_HANDOFF"


def test_detect_intent_human_handoff_representative():
    """'representative' keyword triggers HUMAN_HANDOFF."""
    assert detect_intent("I need a representative please") == "HUMAN_HANDOFF"


def test_detect_intent_order_status():
    """'where is my order' triggers ORDER_STATUS."""
    assert detect_intent("where is my order") == "ORDER_STATUS"


def test_detect_intent_order_status_tracking():
    """'tracking' keyword triggers ORDER_STATUS."""
    assert detect_intent("can you give me the tracking info") == "ORDER_STATUS"


def test_detect_intent_order_status_delivery():
    """'delivery' keyword triggers ORDER_STATUS."""
    assert detect_intent("when is my delivery arriving?") == "ORDER_STATUS"


def test_detect_intent_appointment():
    """'book appointment' triggers APPOINTMENT."""
    assert detect_intent("I would like to book appointment") == "APPOINTMENT"


def test_detect_intent_appointment_schedule():
    """'schedule' keyword triggers APPOINTMENT."""
    assert detect_intent("I need to schedule a call") == "APPOINTMENT"


def test_detect_intent_appointment_reschedule():
    """'reschedule' keyword triggers APPOINTMENT."""
    assert detect_intent("Can I reschedule my booking?") == "APPOINTMENT"


def test_detect_intent_none():
    """'hello' has no matching intent keywords — returns None."""
    assert detect_intent("hello") is None


def test_detect_intent_none_generic_question():
    """A generic question with no intent keywords returns None."""
    assert detect_intent("what are your business hours?") is None


def test_detect_intent_human_handoff_priority_over_order():
    """When text contains both HUMAN_HANDOFF and ORDER_STATUS keywords,
    HUMAN_HANDOFF must win because it is checked first in _INTENT_RULES."""
    assert detect_intent("I want to order something but need to talk to an agent") == "HUMAN_HANDOFF"


def test_detect_intent_case_insensitive():
    """Intent detection is case-insensitive."""
    assert detect_intent("WHERE IS MY ORDER") == "ORDER_STATUS"
    assert detect_intent("Talk To An AGENT") == "HUMAN_HANDOFF"
    assert detect_intent("BOOK an APPOINTMENT") == "APPOINTMENT"


# ---------------------------------------------------------------------------
# build_stub_response — canned replies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent",
    ["ORDER_STATUS", "APPOINTMENT", "HUMAN_HANDOFF"],
    ids=["order-status", "appointment", "human-handoff"],
)
def test_build_stub_response_all_intents(intent: str):
    """build_stub_response returns a non-empty string for every recognised intent."""
    response = build_stub_response(intent)
    assert isinstance(response, str)
    assert len(response) > 0


def test_build_stub_response_order_status_content():
    """ORDER_STATUS stub mentions the mock order reference."""
    response = build_stub_response("ORDER_STATUS")
    assert "MOCK-001" in response


def test_build_stub_response_appointment_content():
    """APPOINTMENT stub mentions the mock appointment reference."""
    response = build_stub_response("APPOINTMENT")
    assert "APT-MOCK-001" in response


def test_build_stub_response_human_handoff_content():
    """HUMAN_HANDOFF stub contains contact information."""
    response = build_stub_response("HUMAN_HANDOFF")
    # The brief specifies +1-800-SUPPORT and help@example.com
    assert "SUPPORT" in response or "help@example.com" in response


def test_build_stub_response_unknown_intent():
    """build_stub_response with an unrecognised intent returns a fallback string."""
    response = build_stub_response("UNKNOWN_INTENT")
    assert isinstance(response, str)
    assert len(response) > 0


# ---------------------------------------------------------------------------
# HTML stripping — _strip_html and fetch_and_cache_knowledge_base
# ---------------------------------------------------------------------------


def test_strip_html_basic():
    """_strip_html removes tags and returns the visible text."""
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_preserves_plain_text():
    """_strip_html on text with no tags returns the text unchanged."""
    assert _strip_html("Plain text content") == "Plain text content"


def test_strip_html_html_entities_unescaped():
    """_strip_html unescapes HTML entities such as &amp;."""
    result = _strip_html("<p>Tom &amp; Jerry</p>")
    assert result == "Tom & Jerry"


@pytest.mark.asyncio
async def test_html_stripping_via_fetch():
    """fetch_and_cache_knowledge_base strips HTML tags when Content-Type is text/html.

    Verifies the cached content equals the tag-stripped version of the mock body.
    """
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/html; charset=utf-8"}
    mock_response.text = "<p>Hello <b>world</b></p>"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.api.services.whatsapp_service.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_and_cache_knowledge_base("http://example.com/kb.html")

    assert result == "Hello world"


@pytest.mark.asyncio
async def test_plain_text_not_stripped():
    """fetch_and_cache_knowledge_base does not strip text/plain content."""
    raw_text = "This is plain text content without any HTML tags."

    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/plain; charset=utf-8"}
    mock_response.text = raw_text
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.api.services.whatsapp_service.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_and_cache_knowledge_base("http://example.com/kb.txt")

    assert result == raw_text


@pytest.mark.asyncio
async def test_fetch_knowledge_base_success_returns_content():
    """A successful fetch returns the fetched KB content."""
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.text = "KB content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.api.services.whatsapp_service.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_and_cache_knowledge_base("http://example.com/kb.txt")

    assert result == "KB content"


@pytest.mark.asyncio
async def test_fetch_knowledge_base_http_error_returns_empty_string():
    """An httpx.HTTPError during fetch returns an empty string."""
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))

    with patch("src.api.services.whatsapp_service.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_and_cache_knowledge_base("http://example.com/kb.txt")

    assert result == ""


# ---------------------------------------------------------------------------
# validate_twilio_signature
# ---------------------------------------------------------------------------


def test_validate_twilio_signature_valid():
    """validate_twilio_signature returns True when RequestValidator.validate returns True."""
    with patch(
        "src.api.services.whatsapp_service.RequestValidator"
    ) as mock_validator_cls:
        mock_instance = MagicMock()
        mock_instance.validate.return_value = True
        mock_validator_cls.return_value = mock_instance

        result = validate_twilio_signature(
            auth_token="test_token",
            signature="valid_signature",
            url="https://example.com/whatsapp/webhook",
            params={"From": "whatsapp:+1234567890", "Body": "Hello"},
        )

    assert result is True
    mock_instance.validate.assert_called_once_with(
        "https://example.com/whatsapp/webhook",
        {"From": "whatsapp:+1234567890", "Body": "Hello"},
        "valid_signature",
    )


def test_validate_twilio_signature_invalid():
    """validate_twilio_signature returns False when RequestValidator.validate returns False."""
    with patch(
        "src.api.services.whatsapp_service.RequestValidator"
    ) as mock_validator_cls:
        mock_instance = MagicMock()
        mock_instance.validate.return_value = False
        mock_validator_cls.return_value = mock_instance

        result = validate_twilio_signature(
            auth_token="test_token",
            signature="bad_signature",
            url="https://example.com/whatsapp/webhook",
            params={"From": "whatsapp:+1234567890", "Body": "Hello"},
        )

    assert result is False


def test_validate_twilio_signature_instantiates_with_auth_token():
    """validate_twilio_signature passes auth_token to RequestValidator constructor."""
    with patch(
        "src.api.services.whatsapp_service.RequestValidator"
    ) as mock_validator_cls:
        mock_instance = MagicMock()
        mock_instance.validate.return_value = True
        mock_validator_cls.return_value = mock_instance

        validate_twilio_signature(
            auth_token="my_secret_token",
            signature="sig",
            url="https://example.com/webhook",
            params={},
        )

    mock_validator_cls.assert_called_once_with("my_secret_token")


# ---------------------------------------------------------------------------
# Database helpers — get_or_create_conversation, append_message, get_recent_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_conversation_creates_new(db_session: AsyncSession):
    """get_or_create_conversation creates a new Conversation for an unseen number."""
    conversation = await get_or_create_conversation(db_session, "whatsapp:+1111111111")
    assert conversation is not None
    assert conversation.from_number == "whatsapp:+1111111111"
    assert conversation.id is not None


@pytest.mark.asyncio
async def test_get_or_create_conversation_deduplication(db_session: AsyncSession):
    """Calling get_or_create_conversation twice with the same number returns the same row."""
    conv1 = await get_or_create_conversation(db_session, "whatsapp:+2222222222")
    conv2 = await get_or_create_conversation(db_session, "whatsapp:+2222222222")
    assert conv1.id == conv2.id


@pytest.mark.asyncio
async def test_get_or_create_conversation_different_numbers(db_session: AsyncSession):
    """Different phone numbers get different Conversation rows."""
    conv1 = await get_or_create_conversation(db_session, "whatsapp:+3333333333")
    conv2 = await get_or_create_conversation(db_session, "whatsapp:+4444444444")
    assert conv1.id != conv2.id


@pytest.mark.asyncio
async def test_append_message_returns_message(db_session: AsyncSession):
    """append_message inserts a Message row and returns it with the correct fields."""
    conversation = await get_or_create_conversation(db_session, "whatsapp:+5555555555")
    msg = await append_message(db_session, conversation.id, "user", "Hello there")
    assert msg is not None
    assert msg.conversation_id == conversation.id
    assert msg.role == "user"
    assert msg.content == "Hello there"
    assert msg.id is not None


@pytest.mark.asyncio
async def test_append_message_assistant_role(db_session: AsyncSession):
    """append_message correctly stores the assistant role."""
    conversation = await get_or_create_conversation(db_session, "whatsapp:+6666666666")
    msg = await append_message(db_session, conversation.id, "assistant", "Hi, how can I help?")
    assert msg.role == "assistant"
    assert msg.content == "Hi, how can I help?"


@pytest.mark.asyncio
async def test_get_recent_history_empty(db_session: AsyncSession):
    """get_recent_history returns an empty list when no messages exist."""
    conversation = await get_or_create_conversation(db_session, "whatsapp:+7777777777")
    history = await get_recent_history(db_session, conversation.id, max_turns=10)
    assert history == []


@pytest.mark.asyncio
async def test_get_recent_history_returns_correct_format(db_session: AsyncSession):
    """get_recent_history returns list of dicts with 'role' and 'content' keys."""
    conversation = await get_or_create_conversation(db_session, "whatsapp:+8888888888")
    await append_message(db_session, conversation.id, "user", "Question one")
    await append_message(db_session, conversation.id, "assistant", "Answer one")

    history = await get_recent_history(db_session, conversation.id, max_turns=10)
    assert len(history) == 2
    assert all("role" in h and "content" in h for h in history)


@pytest.mark.asyncio
async def test_get_recent_history_truncation(db_session: AsyncSession):
    """get_recent_history with max_turns=5 returns at most 10 messages (5 turns * 2).

    Seeds 15 messages with explicit created_at using timedelta to ensure
    deterministic ordering under SQLite's 1-second timestamp resolution.
    """
    from src.api.db_models_whatsapp import Message

    conversation = await get_or_create_conversation(db_session, "whatsapp:+9999999999")
    base_time = datetime.utcnow()

    for i in range(15):
        role = "user" if i % 2 == 0 else "assistant"
        msg = Message(
            conversation_id=conversation.id,
            role=role,
            content=f"Message {i}",
            created_at=base_time + timedelta(seconds=i),
        )
        db_session.add(msg)

    await db_session.flush()

    history = await get_recent_history(db_session, conversation.id, max_turns=5)
    assert len(history) == 10


@pytest.mark.asyncio
async def test_get_recent_history_oldest_first(db_session: AsyncSession):
    """get_recent_history returns messages in ascending created_at order.

    Uses explicit created_at timestamps to guarantee ordering regardless of
    SQLite's timestamp resolution.
    """
    from src.api.db_models_whatsapp import Message

    conversation = await get_or_create_conversation(db_session, "whatsapp:+1010101010")
    base_time = datetime.utcnow()

    expected_contents = ["First", "Second", "Third", "Fourth"]
    for i, content in enumerate(expected_contents):
        role = "user" if i % 2 == 0 else "assistant"
        msg = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            created_at=base_time + timedelta(seconds=i),
        )
        db_session.add(msg)

    await db_session.flush()

    history = await get_recent_history(db_session, conversation.id, max_turns=10)
    actual_contents = [h["content"] for h in history]
    assert actual_contents == expected_contents


# ---------------------------------------------------------------------------
# handle_incoming_message — orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_incoming_message_empty_body_no_db(db_session: AsyncSession):
    """Empty body returns the 'no message received' string without touching the DB."""
    from src.api.services.whatsapp_service import handle_incoming_message

    result = await handle_incoming_message(
        db=db_session,
        from_number="whatsapp:+1234567890",
        body="   ",
        anthropic_api_key="key",
        claude_model="claude-test",
        max_history_turns=10,
        student_info_api_url="http://mock-student-api",
    )
    assert "didn't receive" in result.lower() or "please try again" in result.lower()


@pytest.mark.asyncio
async def test_handle_incoming_message_intent_returns_stub_no_llm(db_session: AsyncSession):
    """An intent match returns the stub without calling AsyncAnthropic."""
    from src.api.services.whatsapp_service import handle_incoming_message

    with patch("src.api.services.whatsapp_service.AsyncAnthropic") as mock_anthropic_cls, \
         patch(
             "src.api.services.whatsapp_service.get_student_lifecycle",
             new=AsyncMock(return_value=AgentType.pre_sale),
         ):
        result = await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+1234567890",
            body="where is my order",
            anthropic_api_key="key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    mock_anthropic_cls.assert_not_called()
    assert "MOCK-001" in result


@pytest.mark.asyncio
async def test_handle_incoming_message_llm_called_for_no_intent(db_session: AsyncSession):
    """When no intent is matched, AsyncAnthropic is instantiated and called."""
    from src.api.services.whatsapp_service import handle_incoming_message

    mock_content = MagicMock()
    mock_content.text = "We are open 9 to 5."
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_messages = AsyncMock()
    mock_messages.create = AsyncMock(return_value=mock_llm_response)

    mock_client_instance = AsyncMock()
    mock_client_instance.messages = mock_messages

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ) as mock_anthropic_cls, patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        result = await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+1234567890",
            body="what are your business hours?",
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    mock_anthropic_cls.assert_called_once_with(api_key="test_key")
    assert result == "We are open 9 to 5."


@pytest.mark.asyncio
async def test_handle_incoming_message_anthropic_error_returns_fallback(db_session: AsyncSession):
    """An anthropic.APIError is caught and a friendly fallback string is returned.

    Patches call_llm directly to raise the error so we don't need to know the
    exact constructor signature of anthropic.APIError (which varies across SDK
    minor versions).
    """
    import anthropic
    from src.api.services.whatsapp_service import handle_incoming_message

    async def _raise_api_error(*args, **kwargs):
        raise anthropic.APIConnectionError(request=MagicMock())

    with patch(
        "src.api.services.whatsapp_service.call_llm",
        new=_raise_api_error,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        result = await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+1234567890",
            body="what are your hours?",
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    assert "trouble" in result.lower() or "sorry" in result.lower()


@pytest.mark.asyncio
async def test_handle_incoming_message_body_truncation(db_session: AsyncSession):
    """Messages longer than 1600 chars are truncated before being sent to the LLM."""
    from src.api.services.whatsapp_service import handle_incoming_message

    long_body = "x" * 2000  # exceeds _MAX_BODY_LENGTH of 1600

    mock_content = MagicMock()
    mock_content.text = "Truncated reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    captured_calls = []

    async def capture_create(**kwargs):
        captured_calls.append(kwargs)
        return mock_llm_response

    mock_client_instance.messages.create = capture_create

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        result = await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+1234567890",
            body=long_body,
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    # The user_message passed to call_llm (which becomes the last message) must be <= 1600
    assert len(captured_calls) == 1
    messages_arg = captured_calls[0]["messages"]
    last_user_msg = messages_arg[-1]
    assert last_user_msg["role"] == "user"
    assert len(last_user_msg["content"]) == 1600


# ---------------------------------------------------------------------------
# get_or_resolve_agent_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_resolve_agent_type_locked_conversation(db_session: AsyncSession):
    """If conversation.agent_type is already set, no API call is made."""
    from src.api.services.whatsapp_service import get_or_resolve_agent_type

    conversation = await get_or_create_conversation(db_session, "whatsapp:+1000000001")
    conversation.agent_type = "active"

    with patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ) as mock_lifecycle:
        result = await get_or_resolve_agent_type(
            db_session, conversation, "whatsapp:+1000000001", "http://mock-student-api"
        )

    mock_lifecycle.assert_not_called()
    assert result is AgentType.active


@pytest.mark.asyncio
async def test_get_or_resolve_agent_type_new_conversation_calls_api(db_session: AsyncSession):
    """If conversation.agent_type is None, the API is called and the value is persisted."""
    from src.api.services.whatsapp_service import get_or_resolve_agent_type

    conversation = await get_or_create_conversation(db_session, "whatsapp:+1000000002")
    assert conversation.agent_type is None

    with patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.refund_period),
    ):
        result = await get_or_resolve_agent_type(
            db_session, conversation, "whatsapp:+1000000002", "http://mock-student-api"
        )

    assert result is AgentType.refund_period
    assert conversation.agent_type == "refund_period"


# ---------------------------------------------------------------------------
# handle_incoming_message — multi-agent system prompt selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_incoming_message_uses_pre_sale_system_prompt(db_session: AsyncSession):
    """handle_incoming_message passes pre_sale system prompt to LLM for pre_sale agent."""
    import src.api.services.agent_config as ac
    from src.api.services.whatsapp_service import handle_incoming_message

    ac._kb_cache[AgentType.pre_sale] = None

    mock_content = MagicMock()
    mock_content.text = "pre_sale reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    captured_calls: list[dict] = []

    async def capture_create(**kwargs):
        captured_calls.append(kwargs)
        return mock_llm_response

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = capture_create

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+2000000001",
            body="Tell me about the course",
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    assert len(captured_calls) == 1
    system_arg = captured_calls[0]["system"]
    assert "sales" in system_arg.lower() or "enrollment" in system_arg.lower()


@pytest.mark.asyncio
async def test_handle_incoming_message_uses_refund_period_system_prompt(db_session: AsyncSession):
    """handle_incoming_message passes refund_period system prompt to LLM."""
    import src.api.services.agent_config as ac
    from src.api.services.whatsapp_service import handle_incoming_message

    ac._kb_cache[AgentType.refund_period] = None

    mock_content = MagicMock()
    mock_content.text = "refund reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    captured_calls: list[dict] = []

    async def capture_create(**kwargs):
        captured_calls.append(kwargs)
        return mock_llm_response

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = capture_create

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.refund_period),
    ):
        await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+2000000002",
            body="I have concerns about my course",
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    assert len(captured_calls) == 1
    system_arg = captured_calls[0]["system"]
    assert "empathetic" in system_arg.lower() or "calm" in system_arg.lower()


@pytest.mark.asyncio
async def test_handle_incoming_message_uses_active_system_prompt(db_session: AsyncSession):
    """handle_incoming_message passes active system prompt to LLM."""
    import src.api.services.agent_config as ac
    from src.api.services.whatsapp_service import handle_incoming_message

    ac._kb_cache[AgentType.active] = None

    mock_content = MagicMock()
    mock_content.text = "active reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    captured_calls: list[dict] = []

    async def capture_create(**kwargs):
        captured_calls.append(kwargs)
        return mock_llm_response

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = capture_create

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.active),
    ):
        await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+2000000003",
            body="How do I access the platform?",
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    assert len(captured_calls) == 1
    system_arg = captured_calls[0]["system"]
    assert "platform" in system_arg.lower() or "support specialist" in system_arg.lower()


@pytest.mark.asyncio
async def test_handle_incoming_message_prepends_kb_to_system_prompt(db_session: AsyncSession):
    """When KB is loaded for an agent, it is prepended to the system prompt."""
    import src.api.services.agent_config as ac
    from src.api.services.whatsapp_service import handle_incoming_message

    ac._kb_cache[AgentType.active] = "Active KB content"

    mock_content = MagicMock()
    mock_content.text = "active reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    captured_calls: list[dict] = []

    async def capture_create(**kwargs):
        captured_calls.append(kwargs)
        return mock_llm_response

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = capture_create

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.active),
    ):
        await handle_incoming_message(
            db=db_session,
            from_number="whatsapp:+2000000004",
            body="How do I access the platform?",
            anthropic_api_key="test_key",
            claude_model="claude-test",
            max_history_turns=10,
            student_info_api_url="http://mock-student-api",
        )

    assert len(captured_calls) == 1
    system_arg = captured_calls[0]["system"]
    assert system_arg.startswith("Active KB content")

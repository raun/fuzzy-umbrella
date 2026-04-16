"""Unit tests for src/api/routers/whatsapp.py.

Uses the `client` fixture from tests/unit/conftest.py, which provides an
httpx.AsyncClient backed by the FastAPI ASGI app with an in-memory SQLite DB.

Twilio signature validation is bypassed in most tests by leaving TWILIO_AUTH_TOKEN
unset (the router skips validation when the env var is absent).

Form payloads are sent as URL-encoded bodies to match real Twilio POST requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import src.api.services.whatsapp_service as svc
from src.api.services.agent_config import AgentType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _form_body(
    from_number: str = "whatsapp:+1234567890",
    body: str = "Hello",
    account_sid: str = "ACtest1234567890",
    signature: str = "test-sig",
) -> str:
    """Build a URL-encoded form body mimicking a Twilio webhook POST."""
    from urllib.parse import urlencode

    return urlencode(
        {
            "From": from_number,
            "Body": body,
            "AccountSid": account_sid,
            "X-Twilio-Signature": signature,
        }
    )


def _form_headers(content_type: str = "application/x-www-form-urlencoded") -> dict:
    return {"Content-Type": content_type}


@pytest.fixture(autouse=True)
def reset_kb_cache():
    """Ensure the per-agent KB cache is clear before and after each test."""
    import src.api.services.agent_config as ac
    for t in ac.AgentType:
        ac._kb_cache[t] = None
    yield
    for t in ac.AgentType:
        ac._kb_cache[t] = None


# ---------------------------------------------------------------------------
# GET /whatsapp/health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client: AsyncClient) -> None:
    """GET /whatsapp/health returns HTTP 200."""
    response = await client.get("/whatsapp/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_endpoint_returns_per_agent_kb_status(client: AsyncClient) -> None:
    """GET /whatsapp/health returns per-agent KB status dict (all false when cache is empty)."""
    response = await client.get("/whatsapp/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["knowledge_base_loaded"] == {
        "pre_sale": False,
        "refund_period": False,
        "active": False,
    }


@pytest.mark.asyncio
async def test_health_endpoint_content_type_is_json(client: AsyncClient) -> None:
    """GET /whatsapp/health response content-type is application/json."""
    response = await client.get("/whatsapp/health")
    assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — auth token not set (validation skipped)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_no_auth_token_skips_validation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When TWILIO_AUTH_TOKEN is not set, validation is skipped and returns 200 with TwiML."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_content = MagicMock()
    mock_content.text = "We are open 9-5."
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="what are your hours?"),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    assert "text/xml" in response.headers["content-type"]
    assert "<Response>" in response.text
    assert "<Message>" in response.text


@pytest.mark.asyncio
async def test_webhook_response_is_valid_twiml(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Webhook response wraps reply text in a valid TwiML Response/Message structure."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_content = MagicMock()
    mock_content.text = "Hello from LLM"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="generic question"),
            headers=_form_headers(),
        )

    xml = response.text
    assert '<?xml version="1.0"' in xml
    assert "<Response>" in xml and "</Response>" in xml
    assert "<Message>" in xml and "</Message>" in xml
    assert "Hello from LLM" in xml


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — misconfiguration errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_missing_webhook_url_when_auth_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns 500 when TWILIO_AUTH_TOKEN is set but TWILIO_WEBHOOK_URL is missing."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "some_token")
    monkeypatch.delenv("TWILIO_WEBHOOK_URL", raising=False)

    response = await client.post(
        "/whatsapp/webhook",
        content=_form_body(),
        headers=_form_headers(),
    )

    assert response.status_code == 500
    assert "TWILIO_WEBHOOK_URL" in response.text


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — signature validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When RequestValidator returns False, the endpoint returns HTTP 403."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "real_token")
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", "https://example.com/whatsapp/webhook")

    with patch(
        "src.api.services.whatsapp_service.RequestValidator"
    ) as mock_validator_cls:
        mock_instance = MagicMock()
        mock_instance.validate.return_value = False
        mock_validator_cls.return_value = mock_instance

        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(signature="bad-sig"),
            headers={
                **_form_headers(),
                "X-Twilio-Signature": "bad-sig",
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webhook_valid_signature_returns_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When RequestValidator returns True, the endpoint continues and returns 200."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "real_token")
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", "https://example.com/whatsapp/webhook")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_content = MagicMock()
    mock_content.text = "Valid response"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.RequestValidator"
    ) as mock_validator_cls, patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        mock_instance = MagicMock()
        mock_instance.validate.return_value = True
        mock_validator_cls.return_value = mock_instance

        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="generic question"),
            headers={
                **_form_headers(),
                "X-Twilio-Signature": "good-sig",
            },
        )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — intent handling (no LLM call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_intent_order_no_llm_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order status intent returns stub text without calling AsyncAnthropic."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic"
    ) as mock_anthropic_cls, patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="where is my order"),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    mock_anthropic_cls.assert_not_called()
    assert "MOCK-001" in response.text


@pytest.mark.asyncio
async def test_webhook_intent_human_handoff(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Human handoff intent returns support contact info without calling LLM."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic"
    ) as mock_anthropic_cls, patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="speak to agent please"),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    mock_anthropic_cls.assert_not_called()
    # Support contact info from the HUMAN_HANDOFF stub
    xml = response.text
    assert "SUPPORT" in xml or "help@example.com" in xml


@pytest.mark.asyncio
async def test_webhook_intent_appointment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appointment intent returns booking stub without calling LLM."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic"
    ) as mock_anthropic_cls, patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="book appointment"),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    mock_anthropic_cls.assert_not_called()
    assert "APT-MOCK-001" in response.text


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — LLM path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_llm_response(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no intent matches, the LLM reply text appears in the TwiML response."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_content = MagicMock()
    mock_content.text = "We are open Monday to Friday 9am-5pm."
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="what are your hours?"),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    assert "We are open Monday to Friday 9am-5pm." in response.text


@pytest.mark.asyncio
async def test_webhook_llm_response_anthropic_api_key_passed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ANTHROPIC_API_KEY env var is forwarded to AsyncAnthropic constructor."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "my-secret-api-key")

    mock_content = MagicMock()
    mock_content.text = "reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ) as mock_anthropic_cls, patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="what are your hours?"),
            headers=_form_headers(),
        )

    mock_anthropic_cls.assert_called_once_with(api_key="my-secret-api-key")


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — empty body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_empty_body(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty Body field returns 200 with a 'no message received' prompt in TwiML."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch("src.api.services.whatsapp_service.AsyncAnthropic") as mock_anthropic_cls:
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="   "),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    mock_anthropic_cls.assert_not_called()
    xml_lower = response.text.lower()
    assert "didn't receive" in xml_lower or "please try again" in xml_lower


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — LLM error graceful handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_llm_error_returns_200_with_fallback(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An anthropic.APIError does not cause a 500; the endpoint returns 200 with a fallback.

    Patches call_llm directly to raise anthropic.APIConnectionError (a concrete
    subclass of APIError) so we avoid relying on a specific constructor
    signature that may vary across anthropic SDK minor versions.
    """
    import anthropic

    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def _raise_api_error(*args, **kwargs):
        raise anthropic.APIConnectionError(request=MagicMock())

    with patch(
        "src.api.services.whatsapp_service.call_llm",
        new=_raise_api_error,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(body="what are your hours?"),
            headers=_form_headers(),
        )

    assert response.status_code == 200
    assert "text/xml" in response.headers["content-type"]
    xml_lower = response.text.lower()
    assert "trouble" in xml_lower or "sorry" in xml_lower


# ---------------------------------------------------------------------------
# POST /whatsapp/webhook — conversation persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_creates_conversation_and_messages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session
) -> None:
    """A successful webhook call creates Conversation and Message rows in the DB."""
    from sqlalchemy import select
    from src.api.db_models_whatsapp import Conversation, Message

    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_content = MagicMock()
    mock_content.text = "LLM reply text"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(from_number="whatsapp:+5550001234", body="tell me about yourself"),
            headers=_form_headers(),
        )

    assert response.status_code == 200

    conv_result = await db_session.execute(
        select(Conversation).where(Conversation.from_number == "whatsapp:+5550001234")
    )
    conversation = conv_result.scalar_one_or_none()
    assert conversation is not None

    msg_result = await db_session.execute(
        select(Message).where(Message.conversation_id == conversation.id)
    )
    messages = msg_result.scalars().all()
    roles = {m.role for m in messages}
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_webhook_same_number_reuses_conversation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session
) -> None:
    """Two requests from the same number share one Conversation row."""
    from sqlalchemy import select
    from src.api.db_models_whatsapp import Conversation

    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_content = MagicMock()
    mock_content.text = "reply"
    mock_llm_response = MagicMock()
    mock_llm_response.content = [mock_content]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "src.api.services.whatsapp_service.AsyncAnthropic",
        return_value=mock_client_instance,
    ), patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.pre_sale),
    ):
        await client.post(
            "/whatsapp/webhook",
            content=_form_body(from_number="whatsapp:+5559998888", body="first message"),
            headers=_form_headers(),
        )
        await client.post(
            "/whatsapp/webhook",
            content=_form_body(from_number="whatsapp:+5559998888", body="second message"),
            headers=_form_headers(),
        )

    conv_result = await db_session.execute(
        select(Conversation).where(Conversation.from_number == "whatsapp:+5559998888")
    )
    conversations = conv_result.scalars().all()
    assert len(conversations) == 1


@pytest.mark.asyncio
async def test_webhook_intent_persists_agent_type(
    client: AsyncClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intent-matched request must persist agent_type on the Conversation row.

    The intent branch calls get_or_resolve_agent_type before committing, so the
    DB row must have agent_type set even when no LLM call is made.
    """
    from sqlalchemy import select

    from src.api.db_models_whatsapp import Conversation

    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch(
        "src.api.services.whatsapp_service.get_student_lifecycle",
        new=AsyncMock(return_value=AgentType.refund_period),
    ):
        response = await client.post(
            "/whatsapp/webhook",
            content=_form_body(from_number="whatsapp:+9990001111", body="where is my order"),
            headers=_form_headers(),
        )

    assert response.status_code == 200

    db_session.expire_all()
    conv_result = await db_session.execute(
        select(Conversation).where(Conversation.from_number == "whatsapp:+9990001111")
    )
    conversation = conv_result.scalar_one()
    assert conversation.agent_type == AgentType.refund_period.value

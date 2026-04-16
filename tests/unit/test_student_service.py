"""Unit tests for src/api/services/student_service.py.

Covers:
- Happy path: valid JSON with each lifecycle_stage value
- HTTP connection errors (httpx.HTTPError subclasses) → AgentType.pre_sale
- httpx.InvalidURL (NOT a subclass of httpx.HTTPError) → AgentType.pre_sale
- HTTP 4xx/5xx status errors → AgentType.pre_sale
- JSON response missing 'lifecycle_stage' key (KeyError) → AgentType.pre_sale
- JSON response with invalid lifecycle_stage value (ValueError) → AgentType.pre_sale
- Non-JSON response body (ValueError from json decode) → AgentType.pre_sale
- Correct query-param encoding: phone number sent as params={'phone': ...}
- Timeout of 30 seconds is passed to httpx
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api.services.agent_config import AgentType
from src.api.services.student_service import get_student_lifecycle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(response: MagicMock) -> AsyncMock:
    """Return an async-context-manager mock that yields a client whose .get() returns response."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


def _make_json_response(payload: dict) -> MagicMock:
    """Return a mock HTTP response with raise_for_status as no-op and .json() returning payload."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=payload)
    return response


# ---------------------------------------------------------------------------
# Happy path — all valid lifecycle_stage values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lifecycle_stage, expected_type",
    [
        ("pre_sale", AgentType.pre_sale),
        ("refund_period", AgentType.refund_period),
        ("active", AgentType.active),
    ],
    ids=["pre_sale", "refund_period", "active"],
)
async def test_get_student_lifecycle_happy_path(lifecycle_stage: str, expected_type: AgentType):
    """get_student_lifecycle maps a valid lifecycle_stage string to the correct AgentType."""
    response = _make_json_response({"lifecycle_stage": lifecycle_stage})
    mock_client = _make_mock_client(response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is expected_type


@pytest.mark.asyncio
async def test_get_student_lifecycle_passes_phone_as_query_param():
    """get_student_lifecycle sends the phone number as params={'phone': ...}."""
    response = _make_json_response({"lifecycle_stage": "active"})
    mock_client = _make_mock_client(response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        await get_student_lifecycle("+44 7911 123456", "http://api.example.com/student")

    mock_client.get.assert_called_once_with(
        "http://api.example.com/student",
        params={"phone": "+44 7911 123456"},
        timeout=30,
    )


@pytest.mark.asyncio
async def test_get_student_lifecycle_uses_timeout_30():
    """get_student_lifecycle passes timeout=30 to httpx.AsyncClient.get."""
    response = _make_json_response({"lifecycle_stage": "pre_sale"})
    mock_client = _make_mock_client(response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        await get_student_lifecycle("+1000000000", "http://api.example.com/student")

    _, kwargs = mock_client.get.call_args
    assert kwargs.get("timeout") == 30


# ---------------------------------------------------------------------------
# HTTP error fallbacks (httpx.HTTPError subclasses)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_student_lifecycle_connection_error_returns_pre_sale():
    """httpx.ConnectError (subclass of HTTPError) → fallback AgentType.pre_sale."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


@pytest.mark.asyncio
async def test_get_student_lifecycle_timeout_error_returns_pre_sale():
    """httpx.TimeoutException (subclass of HTTPError) → fallback AgentType.pre_sale."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=httpx.TimeoutException("timed out")
    )

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


@pytest.mark.asyncio
async def test_get_student_lifecycle_generic_http_error_returns_pre_sale():
    """Any httpx.HTTPError → fallback AgentType.pre_sale."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPError("generic http error")
    )

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


# ---------------------------------------------------------------------------
# httpx.InvalidURL — NOT a subclass of httpx.HTTPError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_student_lifecycle_invalid_url_returns_pre_sale():
    """httpx.InvalidURL (empty api_url) → fallback AgentType.pre_sale without raising."""
    # Passing an empty string triggers httpx.InvalidURL without needing a live server.
    # We rely on the real httpx raising the error when we attempt a request with "".
    # To keep the test deterministic and not require network, mock the client to raise it.
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.InvalidURL("No host"))

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "")

    assert result is AgentType.pre_sale


@pytest.mark.asyncio
async def test_get_student_lifecycle_invalid_url_is_not_http_error():
    """Confirm httpx.InvalidURL is NOT a subclass of httpx.HTTPError (separate catch branch)."""
    assert not issubclass(httpx.InvalidURL, httpx.HTTPError)


# ---------------------------------------------------------------------------
# HTTP status error (4xx / 5xx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_student_lifecycle_http_status_error_returns_pre_sale():
    """raise_for_status raising HTTPStatusError → fallback AgentType.pre_sale."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=MagicMock(),
        )
    )
    mock_client = _make_mock_client(mock_response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


@pytest.mark.asyncio
async def test_get_student_lifecycle_server_error_returns_pre_sale():
    """HTTP 500 → raise_for_status raises HTTPStatusError → fallback AgentType.pre_sale."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(),
        )
    )
    mock_client = _make_mock_client(mock_response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+9999999999", "http://api.example.com/student")

    assert result is AgentType.pre_sale


# ---------------------------------------------------------------------------
# Missing key / invalid value in JSON response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_student_lifecycle_missing_lifecycle_stage_key_returns_pre_sale():
    """JSON response without 'lifecycle_stage' key (KeyError) → fallback AgentType.pre_sale."""
    response = _make_json_response({"other_key": "some_value"})
    mock_client = _make_mock_client(response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


@pytest.mark.asyncio
async def test_get_student_lifecycle_invalid_lifecycle_value_returns_pre_sale():
    """Unknown lifecycle_stage value (ValueError from AgentType()) → fallback AgentType.pre_sale."""
    response = _make_json_response({"lifecycle_stage": "enrolled"})  # not a valid AgentType
    mock_client = _make_mock_client(response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


@pytest.mark.asyncio
async def test_get_student_lifecycle_empty_json_object_returns_pre_sale():
    """Empty JSON object {} (missing key) → fallback AgentType.pre_sale."""
    response = _make_json_response({})
    mock_client = _make_mock_client(response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


# ---------------------------------------------------------------------------
# Non-JSON response body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_student_lifecycle_non_json_response_returns_pre_sale():
    """Non-JSON response body (ValueError from .json()) → fallback AgentType.pre_sale."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(side_effect=ValueError("not valid JSON"))
    mock_client = _make_mock_client(mock_response)

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale


# ---------------------------------------------------------------------------
# Return type guarantee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_student_lifecycle_happy_path_returns_agent_type_instance():
    """get_student_lifecycle returns an AgentType instance on a clean successful call."""
    response = _make_json_response({"lifecycle_stage": "active"})
    good_client = _make_mock_client(response)
    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=good_client):
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert isinstance(result, AgentType)


@pytest.mark.asyncio
async def test_get_student_lifecycle_never_raises_on_connection_failure():
    """get_student_lifecycle never raises; returns AgentType.pre_sale on any covered error."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("unreachable"))

    with patch("src.api.services.student_service.httpx.AsyncClient", return_value=mock_client):
        # Must not raise; must return a value
        result = await get_student_lifecycle("+1234567890", "http://api.example.com/student")

    assert result is AgentType.pre_sale

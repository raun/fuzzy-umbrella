"""Unit tests for src/api/services/agent_config.py.

Covers:
- AgentType enum membership and string values
- AgentConfig dataclass immutability
- AGENT_CONFIGS dict completeness and correct env-var names
- get_agent_config: happy path, all three types
- _kb_cache initialisation and isolation between tests
- get_kb_for_agent: returns None when empty, returns text when loaded
- is_kb_loaded_for_agent: False when None, True when non-empty string
- load_kb_for_agent: env var unset → no HTTP call, cache set to None
- load_kb_for_agent: URL set → delegates to fetch_and_cache_knowledge_base
- load_kb_for_agent: fetch returns "" → cache stores None (not "")
- load_all_knowledge_bases: runs all three agents in parallel
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import src.api.services.agent_config as ac
from src.api.services.agent_config import (
    AGENT_CONFIGS,
    AgentConfig,
    AgentType,
    get_agent_config,
    get_kb_for_agent,
    is_kb_loaded_for_agent,
    load_all_knowledge_bases,
    load_kb_for_agent,
)


# ---------------------------------------------------------------------------
# Autouse fixture: reset _kb_cache before and after every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_kb_cache():
    """Restore _kb_cache to all-None state around each test."""
    for t in AgentType:
        ac._kb_cache[t] = None
    yield
    for t in AgentType:
        ac._kb_cache[t] = None


# ---------------------------------------------------------------------------
# AgentType enum
# ---------------------------------------------------------------------------


def test_agent_type_members():
    """AgentType has exactly the three expected members."""
    members = {t.value for t in AgentType}
    assert members == {"pre_sale", "refund_period", "active"}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("pre_sale", AgentType.pre_sale),
        ("refund_period", AgentType.refund_period),
        ("active", AgentType.active),
    ],
    ids=["pre_sale", "refund_period", "active"],
)
def test_agent_type_from_string(value: str, expected: AgentType):
    """AgentType can be constructed from its string value (str enum)."""
    assert AgentType(value) is expected


def test_agent_type_is_str_subclass():
    """AgentType members behave as plain strings (str enum)."""
    assert isinstance(AgentType.pre_sale, str)
    assert AgentType.pre_sale == "pre_sale"


def test_agent_type_invalid_value_raises():
    """Constructing AgentType from an unknown string raises ValueError."""
    with pytest.raises(ValueError):
        AgentType("unknown_stage")


# ---------------------------------------------------------------------------
# AgentConfig dataclass
# ---------------------------------------------------------------------------


def test_agent_config_is_frozen():
    """AgentConfig is frozen; attribute assignment raises FrozenInstanceError."""
    cfg = AgentConfig(
        agent_type=AgentType.pre_sale,
        system_prompt="test prompt",
        kb_url_env_var="SOME_ENV_VAR",
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        cfg.system_prompt = "new prompt"  # type: ignore[misc]


def test_agent_config_stores_fields():
    """AgentConfig stores the fields passed to the constructor."""
    cfg = AgentConfig(
        agent_type=AgentType.active,
        system_prompt="Active prompt",
        kb_url_env_var="DURING_COURSE_KB_URL",
    )
    assert cfg.agent_type is AgentType.active
    assert cfg.system_prompt == "Active prompt"
    assert cfg.kb_url_env_var == "DURING_COURSE_KB_URL"


# ---------------------------------------------------------------------------
# AGENT_CONFIGS dict
# ---------------------------------------------------------------------------


def test_agent_configs_has_all_types():
    """AGENT_CONFIGS contains an entry for every AgentType."""
    for agent_type in AgentType:
        assert agent_type in AGENT_CONFIGS


def test_agent_configs_kb_url_env_vars():
    """Each AgentConfig in AGENT_CONFIGS references the expected KB URL env var."""
    assert AGENT_CONFIGS[AgentType.pre_sale].kb_url_env_var == "PRE_SALE_KB_URL"
    assert AGENT_CONFIGS[AgentType.refund_period].kb_url_env_var == "POST_SALE_KB_URL"
    assert AGENT_CONFIGS[AgentType.active].kb_url_env_var == "DURING_COURSE_KB_URL"


def test_agent_configs_system_prompts_non_empty():
    """Every AgentConfig has a non-empty system_prompt."""
    for agent_type, cfg in AGENT_CONFIGS.items():
        assert cfg.system_prompt, f"system_prompt is empty for {agent_type}"


@pytest.mark.parametrize(
    "agent_type, keyword",
    [
        (AgentType.pre_sale, "sales"),
        (AgentType.refund_period, "empathetic"),
        (AgentType.active, "platform"),
    ],
    ids=["pre_sale", "refund_period", "active"],
)
def test_agent_configs_system_prompt_keywords(agent_type: AgentType, keyword: str):
    """Each agent's system prompt contains the persona keyword from the brief."""
    assert keyword in AGENT_CONFIGS[agent_type].system_prompt.lower()


# ---------------------------------------------------------------------------
# get_agent_config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_type",
    list(AgentType),
    ids=[t.value for t in AgentType],
)
def test_get_agent_config_returns_correct_config(agent_type: AgentType):
    """get_agent_config returns the matching AgentConfig for each AgentType."""
    cfg = get_agent_config(agent_type)
    assert cfg is AGENT_CONFIGS[agent_type]
    assert cfg.agent_type is agent_type


# ---------------------------------------------------------------------------
# _kb_cache initial state
# ---------------------------------------------------------------------------


def test_kb_cache_initialised_to_none():
    """_kb_cache starts with None for every AgentType (enforced by fixture)."""
    for agent_type in AgentType:
        assert ac._kb_cache[agent_type] is None


# ---------------------------------------------------------------------------
# get_kb_for_agent
# ---------------------------------------------------------------------------


def test_get_kb_for_agent_returns_none_when_unloaded():
    """get_kb_for_agent returns None when the cache is empty (default state)."""
    assert get_kb_for_agent(AgentType.pre_sale) is None


def test_get_kb_for_agent_returns_cached_text():
    """get_kb_for_agent returns the string stored in _kb_cache."""
    ac._kb_cache[AgentType.active] = "Active KB text"
    assert get_kb_for_agent(AgentType.active) == "Active KB text"


def test_get_kb_for_agent_returns_correct_entry_per_type():
    """get_kb_for_agent returns the cache entry specific to the requested AgentType."""
    ac._kb_cache[AgentType.pre_sale] = "Pre-sale content"
    ac._kb_cache[AgentType.refund_period] = None
    ac._kb_cache[AgentType.active] = "Active content"

    assert get_kb_for_agent(AgentType.pre_sale) == "Pre-sale content"
    assert get_kb_for_agent(AgentType.refund_period) is None
    assert get_kb_for_agent(AgentType.active) == "Active content"


# ---------------------------------------------------------------------------
# is_kb_loaded_for_agent
# ---------------------------------------------------------------------------


def test_is_kb_loaded_returns_false_when_cache_is_none():
    """is_kb_loaded_for_agent returns False when the cache entry is None."""
    assert is_kb_loaded_for_agent(AgentType.pre_sale) is False


def test_is_kb_loaded_returns_false_when_cache_is_empty_string():
    """is_kb_loaded_for_agent returns False for an empty string (falsy)."""
    ac._kb_cache[AgentType.pre_sale] = ""
    assert is_kb_loaded_for_agent(AgentType.pre_sale) is False


def test_is_kb_loaded_returns_true_when_cache_has_text():
    """is_kb_loaded_for_agent returns True when the cache holds a non-empty string."""
    ac._kb_cache[AgentType.refund_period] = "Some KB text"
    assert is_kb_loaded_for_agent(AgentType.refund_period) is True


@pytest.mark.parametrize(
    "agent_type",
    list(AgentType),
    ids=[t.value for t in AgentType],
)
def test_is_kb_loaded_false_for_all_types_initially(agent_type: AgentType):
    """All agents report KB not loaded in the default (all-None) state."""
    assert is_kb_loaded_for_agent(agent_type) is False


# ---------------------------------------------------------------------------
# load_kb_for_agent — env var unset or empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_kb_for_agent_no_env_var_returns_empty_string(monkeypatch):
    """load_kb_for_agent returns '' when the KB URL env var is not set."""
    monkeypatch.delenv("PRE_SALE_KB_URL", raising=False)

    # No HTTP call is made when env var is absent — no mock needed.
    result = await load_kb_for_agent(AgentType.pre_sale)

    assert result == ""


@pytest.mark.asyncio
async def test_load_kb_for_agent_no_env_var_sets_cache_to_none(monkeypatch):
    """load_kb_for_agent sets _kb_cache[agent_type] to None when env var is absent."""
    monkeypatch.delenv("PRE_SALE_KB_URL", raising=False)
    # Ensure any stale value is cleared first
    ac._kb_cache[AgentType.pre_sale] = "stale value"

    await load_kb_for_agent(AgentType.pre_sale)

    assert ac._kb_cache[AgentType.pre_sale] is None


@pytest.mark.asyncio
async def test_load_kb_for_agent_empty_env_var_returns_empty_string(monkeypatch):
    """load_kb_for_agent returns '' when the KB URL env var is set to empty string."""
    monkeypatch.setenv("PRE_SALE_KB_URL", "")

    result = await load_kb_for_agent(AgentType.pre_sale)

    assert result == ""
    assert ac._kb_cache[AgentType.pre_sale] is None


@pytest.mark.asyncio
async def test_load_kb_for_agent_no_http_call_when_env_var_unset(monkeypatch):
    """No HTTP call is made when the KB URL env var is unset."""
    monkeypatch.delenv("DURING_COURSE_KB_URL", raising=False)

    mock_fetch = AsyncMock(return_value="should not be called")
    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        await load_kb_for_agent(AgentType.active)

    mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# load_kb_for_agent — URL set, successful fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_kb_for_agent_fetches_and_caches_text(monkeypatch):
    """When the KB URL env var is set, load_kb_for_agent fetches and caches the text."""
    monkeypatch.setenv("PRE_SALE_KB_URL", "http://example.com/pre-sale-kb.txt")

    mock_fetch = AsyncMock(return_value="Pre-sale knowledge base content")
    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        result = await load_kb_for_agent(AgentType.pre_sale)

    assert result == "Pre-sale knowledge base content"
    assert ac._kb_cache[AgentType.pre_sale] == "Pre-sale knowledge base content"
    mock_fetch.assert_called_once_with("http://example.com/pre-sale-kb.txt")


@pytest.mark.asyncio
async def test_load_kb_for_agent_returns_fetched_text(monkeypatch):
    """load_kb_for_agent return value equals the text returned by fetch_and_cache_knowledge_base."""
    monkeypatch.setenv("POST_SALE_KB_URL", "http://example.com/post-sale-kb.txt")

    expected_text = "Refund period KB text here"
    mock_fetch = AsyncMock(return_value=expected_text)
    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        result = await load_kb_for_agent(AgentType.refund_period)

    assert result == expected_text


# ---------------------------------------------------------------------------
# load_kb_for_agent — fetch failure stores None (not "")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_kb_for_agent_failed_fetch_stores_none_not_empty_string(monkeypatch):
    """When fetch returns '' (failure), _kb_cache stores None so is_kb_loaded stays False."""
    monkeypatch.setenv("DURING_COURSE_KB_URL", "http://example.com/active-kb.txt")
    ac._kb_cache[AgentType.active] = "old value"

    mock_fetch = AsyncMock(return_value="")  # simulate fetch failure
    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        result = await load_kb_for_agent(AgentType.active)

    assert result == ""
    assert ac._kb_cache[AgentType.active] is None  # NOT ""
    assert is_kb_loaded_for_agent(AgentType.active) is False


@pytest.mark.asyncio
async def test_load_kb_for_agent_failed_fetch_returns_empty_string(monkeypatch):
    """load_kb_for_agent passes through the empty string on fetch failure."""
    monkeypatch.setenv("PRE_SALE_KB_URL", "http://example.com/pre-sale-kb.txt")

    mock_fetch = AsyncMock(return_value="")
    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        result = await load_kb_for_agent(AgentType.pre_sale)

    assert result == ""


# ---------------------------------------------------------------------------
# load_all_knowledge_bases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_all_knowledge_bases_loads_all_three(monkeypatch):
    """load_all_knowledge_bases populates the cache for all three AgentTypes."""
    monkeypatch.setenv("PRE_SALE_KB_URL", "http://example.com/pre")
    monkeypatch.setenv("POST_SALE_KB_URL", "http://example.com/post")
    monkeypatch.setenv("DURING_COURSE_KB_URL", "http://example.com/during")

    async def mock_fetch(url: str) -> str:
        return f"KB content for {url}"

    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        await load_all_knowledge_bases()

    assert ac._kb_cache[AgentType.pre_sale] == "KB content for http://example.com/pre"
    assert ac._kb_cache[AgentType.refund_period] == "KB content for http://example.com/post"
    assert ac._kb_cache[AgentType.active] == "KB content for http://example.com/during"


@pytest.mark.asyncio
async def test_load_all_knowledge_bases_when_all_env_vars_unset(monkeypatch):
    """load_all_knowledge_bases is safe when all KB URL env vars are unset."""
    monkeypatch.delenv("PRE_SALE_KB_URL", raising=False)
    monkeypatch.delenv("POST_SALE_KB_URL", raising=False)
    monkeypatch.delenv("DURING_COURSE_KB_URL", raising=False)

    await load_all_knowledge_bases()

    for agent_type in AgentType:
        assert ac._kb_cache[agent_type] is None
        assert is_kb_loaded_for_agent(agent_type) is False


@pytest.mark.asyncio
async def test_load_all_knowledge_bases_is_idempotent(monkeypatch):
    """Calling load_all_knowledge_bases twice overwrites the cache cleanly."""
    monkeypatch.setenv("PRE_SALE_KB_URL", "http://example.com/pre")
    monkeypatch.delenv("POST_SALE_KB_URL", raising=False)
    monkeypatch.delenv("DURING_COURSE_KB_URL", raising=False)

    call_count = 0

    async def mock_fetch(url: str) -> str:
        nonlocal call_count
        call_count += 1
        return "fresh content"

    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        await load_all_knowledge_bases()
        await load_all_knowledge_bases()

    # Called once per pre_sale URL per load_all invocation = 2 total
    assert call_count == 2
    assert ac._kb_cache[AgentType.pre_sale] == "fresh content"


@pytest.mark.asyncio
async def test_load_all_knowledge_bases_partial_env_vars(monkeypatch):
    """Only agents with a set URL fetch content; others remain None."""
    monkeypatch.setenv("PRE_SALE_KB_URL", "http://example.com/pre")
    monkeypatch.delenv("POST_SALE_KB_URL", raising=False)
    monkeypatch.delenv("DURING_COURSE_KB_URL", raising=False)

    mock_fetch = AsyncMock(return_value="Pre-sale text")
    with patch(
        "src.api.services.whatsapp_service.fetch_and_cache_knowledge_base",
        new=mock_fetch,
    ):
        await load_all_knowledge_bases()

    assert ac._kb_cache[AgentType.pre_sale] == "Pre-sale text"
    assert ac._kb_cache[AgentType.refund_period] is None
    assert ac._kb_cache[AgentType.active] is None

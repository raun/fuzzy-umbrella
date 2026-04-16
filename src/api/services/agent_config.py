"""Agent configuration module for multi-agent WhatsApp bot.

Defines the AgentType enum, AgentConfig dataclass, per-agent AGENT_CONFIGS dict,
module-level KB cache, and helpers for loading and retrieving cached knowledge bases.
"""

import asyncio
import enum
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class AgentType(str, enum.Enum):
    """Lifecycle stage of a student, mapped to a specialised agent."""

    pre_sale = "pre_sale"
    refund_period = "refund_period"
    active = "active"


@dataclass(frozen=True)
class AgentConfig:
    """Immutable configuration for one agent type."""

    agent_type: AgentType
    system_prompt: str  # base persona prompt (KB content is prepended at call time)
    kb_url_env_var: str  # name of the env var holding the KB URL


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


def get_agent_config(agent_type: AgentType) -> AgentConfig:
    """Return the AgentConfig for the given AgentType. Always succeeds."""
    return AGENT_CONFIGS[agent_type]


async def load_kb_for_agent(agent_type: AgentType) -> str:
    """Fetch and cache the KB for one agent.

    Reads the URL from os.getenv(config.kb_url_env_var). If the env var is
    unset or empty, sets _kb_cache[agent_type] = None and returns immediately
    without making any HTTP call.

    Uses a local import inside the function body to avoid a circular import
    (agent_config is imported by whatsapp_service, which would create a cycle
    if agent_config also imported from whatsapp_service at module level):

        from src.api.services.whatsapp_service import fetch_and_cache_knowledge_base

    Calls fetch_and_cache_knowledge_base(url) and assigns its return value
    directly to _kb_cache[agent_type].

    Logs a warning on fetch failure; leaves _kb_cache[agent_type] as None.
    Returns the fetched text (or empty string on failure).
    """
    config = AGENT_CONFIGS[agent_type]
    url = os.getenv(config.kb_url_env_var, "")

    if not url:
        logger.info(
            "KB URL env var %r is unset or empty for agent %r; skipping fetch",
            config.kb_url_env_var,
            agent_type.value,
        )
        _kb_cache[agent_type] = None
        return ""

    # Local import to avoid circular dependency at module level
    from src.api.services.whatsapp_service import fetch_and_cache_knowledge_base  # noqa: PLC0415

    result = await fetch_and_cache_knowledge_base(url)
    _kb_cache[agent_type] = result if result else None
    return result


async def load_all_knowledge_bases() -> None:
    """Load all three agent KBs in parallel.

    Calls asyncio.gather over all three AgentType values. Repeated calls are
    idempotent (the gather simply overwrites _kb_cache entries with fresh values
    or None). No guard against concurrent calls is needed because asyncio is
    single-threaded; in tests the autouse fixture resets _kb_cache between tests
    so in-flight coroutines from a prior test cannot pollute a subsequent one.
    """
    await asyncio.gather(
        load_kb_for_agent(AgentType.pre_sale),
        load_kb_for_agent(AgentType.refund_period),
        load_kb_for_agent(AgentType.active),
    )


def get_kb_for_agent(agent_type: AgentType) -> str | None:
    """Return the cached KB string for agent_type, or None if not loaded."""
    return _kb_cache.get(agent_type)


def is_kb_loaded_for_agent(agent_type: AgentType) -> bool:
    """Return True if the KB for agent_type was fetched successfully."""
    return bool(_kb_cache.get(agent_type))

"""Student Info API client for resolving lifecycle stage to AgentType.

Provides get_student_lifecycle, which calls an external REST API keyed by phone
number and maps the response to an AgentType enum value.
"""

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
      is NOT a subclass of httpx.HTTPError; it must be caught separately
    - HTTP response status >= 400 (httpx.HTTPStatusError, subclass of httpx.HTTPError)
    - Response body is not valid JSON (ValueError / json.JSONDecodeError)
    - "lifecycle_stage" key is absent from the JSON (KeyError)
    - "lifecycle_stage" value does not match any AgentType member (ValueError)

    Logs a WARNING in every fallback case with the reason. Never raises.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, params={"phone": phone_number}, timeout=30)
            response.raise_for_status()
            data = response.json()
            return AgentType(data["lifecycle_stage"])
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning(
            "Student Info API request failed for phone ***%s (url=%r): %s",
            phone_number[-4:] if len(phone_number) >= 4 else "****",
            api_url,
            exc,
        )
        return AgentType.pre_sale
    except (KeyError, ValueError) as exc:
        logger.warning(
            "Student Info API returned unexpected payload for phone ***%s: %s",
            phone_number[-4:] if len(phone_number) >= 4 else "****",
            exc,
        )
        return AgentType.pre_sale

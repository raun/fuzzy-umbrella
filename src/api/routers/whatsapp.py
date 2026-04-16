"""WhatsApp webhook and health router."""

import html
import logging
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.database import get_db
from src.api.services.agent_config import AgentType, is_kb_loaded_for_agent
from src.api.services.whatsapp_service import (
    handle_incoming_message,
    validate_twilio_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class KbStatusResponse(BaseModel):
    """Per-agent knowledge-base load status."""

    pre_sale: bool
    refund_period: bool
    active: bool


class WhatsAppHealthResponse(BaseModel):
    """Response schema for the WhatsApp health endpoint."""

    status: str
    knowledge_base_loaded: KbStatusResponse  # was: bool — breaking API change


def _build_twiml(reply_text: str) -> str:
    """Return a TwiML Response string wrapping reply_text in a <Message> element."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{html.escape(reply_text)}</Message>"
        "</Response>"
    )


@router.get("/health", response_model=WhatsAppHealthResponse)
async def whatsapp_health() -> WhatsAppHealthResponse:
    """Return health status and per-agent knowledge-base load status."""
    return WhatsAppHealthResponse(
        status="ok",
        knowledge_base_loaded=KbStatusResponse(
            pre_sale=is_kb_loaded_for_agent(AgentType.pre_sale),
            refund_period=is_kb_loaded_for_agent(AgentType.refund_period),
            active=is_kb_loaded_for_agent(AgentType.active),
        ),
    )


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),  # noqa: N803
    Body: str = Form(...),  # noqa: N803
    AccountSid: str = Form(...),  # noqa: N803
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Validate Twilio signature, process message, and return TwiML Response.

    Signature validation steps:
    1. Read X-Twilio-Signature header from request.
    2. Read TWILIO_AUTH_TOKEN from env. If unset, skip validation and log warning.
    3. Read TWILIO_WEBHOOK_URL from env. If TWILIO_AUTH_TOKEN is set but
       TWILIO_WEBHOOK_URL is unset, raise HTTP 500.
    4. Collect the complete form payload via dict(await request.form()) to
       ensure the HMAC covers all Twilio fields, not just the three declared params.
    5. If validate_twilio_signature returns False, raise HTTP 403.
    """
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if auth_token:
        webhook_url = os.getenv("TWILIO_WEBHOOK_URL")
        if not webhook_url:
            raise HTTPException(
                status_code=500,
                detail="TWILIO_WEBHOOK_URL must be set when TWILIO_AUTH_TOKEN is configured",
            )

        signature = request.headers.get("X-Twilio-Signature", "")
        params = dict(await request.form())

        if not validate_twilio_signature(auth_token, signature, webhook_url, params):
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    else:
        logger.warning("TWILIO_AUTH_TOKEN not set, skipping signature validation")

    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    max_history_turns = int(os.getenv("MAX_HISTORY_TURNS", "10"))
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

    twiml = _build_twiml(reply)
    return Response(content=twiml, media_type="text/xml")

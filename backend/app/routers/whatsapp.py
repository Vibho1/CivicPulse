"""WhatsApp Cloud API webhook (PRD: "PWA or WhatsApp webhook", OQ-1; optional).

GET  /api/whatsapp/webhook   Meta's subscription handshake (echoes ``hub.challenge``).
POST /api/whatsapp/webhook   Incoming messages: checked against ``X-Hub-Signature-256``,
                             acknowledged at once and handled in a background task.

Both answer 404 unless WHATSAPP_VERIFY_TOKEN is set. The conversation logic lives in
services/whatsapp.py; setup is described in docs/WHATSAPP.md.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..config import Settings
from ..services import whatsapp

router = APIRouter(tags=["whatsapp"])

# A delivery is a few KB of JSON; photos and voice notes are fetched separately.
MAX_BODY_BYTES = 1024 * 1024


def _enabled_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    if not settings.whatsapp_verify_token:
        raise HTTPException(status_code=404, detail="Not Found")
    return settings


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large")
    return bytes(body)


@router.get("/whatsapp/webhook", response_class=PlainTextResponse)
def verify_webhook(
    request: Request,
    mode: str = Query("", alias="hub.mode"),
    verify_token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Meta calls this when the webhook is registered: echo ``hub.challenge`` if the verify token matches."""
    settings = _enabled_settings(request)
    if mode == "subscribe" and whatsapp.tokens_match(verify_token, settings.whatsapp_verify_token):
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks):
    """Incoming messages. Answer 200 right away (Meta retries slow webhooks); the work happens in the background."""
    settings = _enabled_settings(request)
    body = await _read_body(request)
    if settings.whatsapp_app_secret:
        if not whatsapp.verify_signature(settings.whatsapp_app_secret, body, request.headers.get("x-hub-signature-256")):
            raise HTTPException(status_code=401, detail="Invalid X-Hub-Signature-256")
    else:
        whatsapp.warn_unsigned()
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected a JSON body") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    state = request.app.state
    background.add_task(
        whatsapp.process_payload,
        payload,
        settings=settings,
        store=state.store,
        ai=state.ai,
        client=whatsapp.client_for(request.app),
    )
    return {"status": "received"}

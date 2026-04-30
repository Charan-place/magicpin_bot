"""Vera Bot — magicpin AI Challenge submission."""
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Load .env for local development (no-op if python-dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from composer import Composer
from conversation import ConversationManager
from state import ContextStore

app = FastAPI(title="Vera Bot", version="1.0.0")
START = time.time()

store = ContextStore()
conv = ConversationManager()
composer = Composer()


# ─── healthz + metadata ───────────────────────────────────────────────────────

@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START),
        "contexts_loaded": store.counts(),
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Satya Sai Charan Narra",
        "team_members": ["Satya Sai Charan Narra"],
        "model": "deepseek/deepseek-chat:free via OpenRouter",
        "approach": (
            "3-layer prompt stack (system+mode+context). Trigger-kind dispatch to "
            "operator-mode (contrarian insight) or assistant-mode (artifact draft). "
            "Derived features: CTR vs peer, lapsed revenue estimate. "
            "State machine for auto-reply detection (3-strike), intent transition, "
            "hostile exit. Suppression dedup. Anti-repetition guard."
        ),
        "contact_email": "nsatyasaicharan@gmail.com",
        "version": "1.0.0",
        "submitted_at": "2026-04-30T00:00:00Z",
    }


# ─── /v1/context ─────────────────────────────────────────────────────────────

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: Optional[str] = None


@app.post("/v1/context")
async def push_context(body: ContextBody):
    valid_scopes = {"category", "merchant", "customer", "trigger"}
    if body.scope not in valid_scopes:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": f"scope must be one of {valid_scopes}"},
        )

    result = store.upsert(body.scope, body.context_id, body.version, body.payload)

    if result == "stale":
        return JSONResponse(
            status_code=409,
            content={
                "accepted": False,
                "reason": "stale_version",
                "current_version": store.get_version(body.scope, body.context_id),
            },
        )

    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z",
    }


# ─── /v1/tick ─────────────────────────────────────────────────────────────────

class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []

    for trigger_id in body.available_triggers:
        if len(actions) >= 5:
            break

        trigger = store.get("trigger", trigger_id)
        if not trigger:
            continue

        # Suppression check
        suppression_key = trigger.get("suppression_key", "")
        if conv.is_suppressed(suppression_key):
            continue

        # Get merchant
        merchant_id = (
            trigger.get("merchant_id")
            or trigger.get("payload", {}).get("merchant_id")
        )
        if not merchant_id:
            continue

        # Merchant-level suppression
        if conv.is_merchant_suppressed(merchant_id):
            continue

        merchant = store.get("merchant", merchant_id)
        if not merchant:
            continue

        # Get category
        category_slug = merchant.get("category_slug", "")
        category = store.get("category", category_slug) or {}

        # Get customer (for customer-scoped triggers)
        customer_id = (
            trigger.get("customer_id")
            or trigger.get("payload", {}).get("customer_id")
        )
        customer = store.get("customer", customer_id) if customer_id else None

        # Build conversation_id
        trigger_kind = trigger.get("kind", "unknown")
        week = datetime.utcnow().strftime("%Y_W%U")
        conv_id = f"conv_{merchant_id}_{trigger_kind}_{week}"

        if conv.is_ended(conv_id):
            continue

        # Compose
        action = await composer.compose_tick(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conv_id=conv_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            trigger_id=trigger_id,
        )

        if action and action.get("body"):
            # Anti-repetition guard
            if conv.is_repeat_body(conv_id, action["body"]):
                continue
            conv.record_sent_body(conv_id, action["body"])
            conv.suppress(suppression_key)
            conv.add_turn(conv_id, "vera", action["body"])
            actions.append(action)

    return {"actions": actions}


# ─── /v1/reply ────────────────────────────────────────────────────────────────

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: Optional[str] = None
    turn_number: int = 2


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv_id = body.conversation_id
    merchant_id = body.merchant_id or ""
    message = body.message.strip()

    # Already ended
    if conv.is_ended(conv_id):
        return {"action": "end", "rationale": "Conversation previously closed."}

    # Load context for reply composition
    merchant = store.get("merchant", merchant_id) or {}
    category_slug = merchant.get("category_slug", "")
    category = store.get("category", category_slug) or {}

    # ── auto-reply detection ──────────────────────────────────────────────────
    if conv.is_auto_reply(message):
        count = conv.increment_auto_reply(conv_id)

        if count == 1:
            probe = (
                "Looks like an auto-reply 😊 "
                "Jab owner dekhe, bas reply karein YES — 2 min ka kaam hai."
            )
            conv.record_sent_body(conv_id, probe)
            return {
                "action": "send",
                "body": probe,
                "cta": "binary_yes_no",
                "rationale": "Detected auto-reply (canned phrasing). One probe to surface to owner.",
            }
        elif count == 2:
            return {
                "action": "wait",
                "wait_seconds": 14400,
                "rationale": "Second consecutive auto-reply. Owner not at phone. Backing off 4h.",
            }
        else:
            conv.end_conversation(conv_id)
            return {
                "action": "end",
                "rationale": f"Auto-reply {count}x in a row. No real engagement. Conversation closed.",
            }

    # Real reply — reset auto-reply counter, note owner hour
    hour = datetime.utcnow().hour
    conv.reset_auto_reply(conv_id, hour)

    # ── hostile / opt-out ────────────────────────────────────────────────────
    if conv.is_hostile(message):
        conv.end_conversation(conv_id)
        if merchant_id:
            conv.suppress_merchant(merchant_id, days=30)
        # Brief apology then close
        apology = "Maafi — aage message nahi karunga. Kabhi zaroorat ho toh 'Hi Vera' likhein. 🙏"
        conv.record_sent_body(conv_id, apology)
        return {
            "action": "send",
            "body": apology,
            "cta": "none",
            "rationale": "Merchant hostile/opt-out. One-line apology + graceful exit. Suppressing merchant 30d.",
        }

    # ── commitment / intent transition ───────────────────────────────────────
    if conv.is_commitment(message):
        conv.add_turn(conv_id, "merchant", message)
        result = await composer.compose_commitment_reply(
            merchant=merchant,
            category=category,
            merchant_message=message,
        )
        if result.get("body"):
            conv.record_sent_body(conv_id, result["body"])
            conv.add_turn(conv_id, "vera", result["body"])
        return result

    # ── general reply ────────────────────────────────────────────────────────
    history = conv.get_history(conv_id)
    conv.add_turn(conv_id, "merchant", message)

    result = await composer.compose_reply(
        merchant=merchant,
        category=category,
        merchant_message=message,
        history=history,
    )

    action = result.get("action", "send")

    if action == "end":
        conv.end_conversation(conv_id)
    elif action == "send" and result.get("body"):
        body_text = result["body"]
        # Anti-repetition
        if conv.is_repeat_body(conv_id, body_text):
            # Rephrase fallback
            body_text = body_text + " (aur kuch poochna ho toh batayein)"
        conv.record_sent_body(conv_id, body_text)
        conv.add_turn(conv_id, "vera", body_text)
        result["body"] = body_text

    return result


# ─── /v1/teardown (optional — wipe state) ─────────────────────────────────────

@app.post("/v1/teardown")
async def teardown():
    store.clear()
    conv.clear()
    return {"status": "wiped"}


# ─── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

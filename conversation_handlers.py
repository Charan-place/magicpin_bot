"""
Multi-turn conversation handler — tiebreaker submission.

Implements respond() for handling merchant replies within an active conversation.
State is maintained externally (ConversationState passed in each call).
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from conversation import ConversationManager
from composer import Composer
from state import ContextStore


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    category_slug: str
    turn_number: int = 1
    history: list = field(default_factory=list)
    status: str = "active"  # active | ended | waiting
    from_role: str = "merchant"  # merchant | customer — set per turn before calling respond()


# Module-level singletons (shared with main.py state if imported together)
_store = ContextStore()
_conv = ConversationManager()
_composer = Composer()


def respond(state: ConversationState, merchant_message: str) -> dict:
    """
    Given the conversation so far + the merchant's latest message, produce the reply.

    Returns dict with keys: action, body (if action=send), cta, rationale
    Possible actions: "send" | "wait" | "end"
    """
    return asyncio.get_event_loop().run_until_complete(
        _respond_async(state, merchant_message)
    )


async def _respond_async(state: ConversationState, merchant_message: str) -> dict:
    conv_id = state.conversation_id
    merchant_id = state.merchant_id

    # Already ended — don't respond
    if state.status == "ended" or _conv.is_ended(conv_id):
        state.status = "ended"
        return {"action": "end", "rationale": "Conversation previously closed."}

    msg = merchant_message.strip()

    # ── auto-reply detection ────────────────────────────────────────────────
    if _conv.is_auto_reply(msg):
        count = _conv.increment_auto_reply(conv_id)
        state.history.append({"role": "merchant", "message": msg})

        if count == 1:
            body = "Looks like an auto-reply 😊 Jab owner dekhe, bas reply karein YES — 2 min ka kaam hai."
            state.history.append({"role": "vera", "message": body})
            return {
                "action": "send",
                "body": body,
                "cta": "binary_yes_no",
                "rationale": "Detected auto-reply (canned phrasing). One probe to flag for owner.",
            }
        elif count == 2:
            return {
                "action": "wait",
                "wait_seconds": 14400,
                "rationale": "Second consecutive auto-reply. Backing off 4h for owner availability.",
            }
        else:
            state.status = "ended"
            _conv.end_conversation(conv_id)
            return {
                "action": "end",
                "rationale": f"Auto-reply {count}x consecutively. No real engagement signal. Closing.",
            }

    # Real reply — reset auto-reply streak
    import datetime
    _conv.reset_auto_reply(conv_id, hour=datetime.datetime.utcnow().hour)

    # ── hostile / opt-out ───────────────────────────────────────────────────
    if _conv.is_hostile(msg):
        state.status = "ended"
        _conv.end_conversation(conv_id)
        _conv.suppress_merchant(merchant_id, days=30)
        return {
            "action": "end",
            "rationale": "Merchant opted out / expressed hostility. Closing conversation. Suppressing 30d.",
        }

    # ── commitment / intent transition ─────────────────────────────────────
    merchant = _store.get("merchant", merchant_id) or {}
    category = _store.get("category", state.category_slug) or {}

    if _conv.is_commitment(msg):
        state.history.append({"role": "merchant", "message": msg})
        result = await _composer.compose_commitment_reply(
            merchant=merchant,
            category=category,
            merchant_message=msg,
        )
        if result.get("body"):
            state.history.append({"role": "vera", "message": result["body"]})
            _conv.record_sent_body(conv_id, result["body"])
        state.turn_number += 1
        return result

    # ── general reply — branch on role ──────────────────────────────────────
    history = _conv.get_history(conv_id)

    # Detect customer vs merchant role from conversation state
    is_customer_reply = getattr(state, "from_role", "merchant") == "customer"

    if is_customer_reply:
        customer_id = state.customer_id
        customer = _store.get("customer", customer_id) if customer_id else None
        state.history.append({"role": "customer", "message": msg})
        _conv.add_turn(conv_id, "customer", msg)
        result = await _composer.compose_customer_reply(
            merchant=merchant,
            category=category,
            customer=customer,
            customer_message=msg,
            history=history,
        )
    else:
        state.history.append({"role": "merchant", "message": msg})
        _conv.add_turn(conv_id, "merchant", msg)
        result = await _composer.compose_reply(
            merchant=merchant,
            category=category,
            merchant_message=msg,
            history=history,
        )

    action = result.get("action", "send")
    if action == "end":
        state.status = "ended"
        _conv.end_conversation(conv_id)
    elif action == "send" and result.get("body"):
        body = result["body"]
        if _conv.is_repeat_body(conv_id, body):
            body += " — kuch aur poochna ho toh batayein."
        _conv.record_sent_body(conv_id, body)
        _conv.add_turn(conv_id, "vera", body)
        state.history.append({"role": "vera", "message": body})
        result["body"] = body

    state.turn_number += 1
    return result

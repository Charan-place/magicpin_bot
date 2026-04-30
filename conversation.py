"""Conversation state machine: auto-reply detection, intent transitions, history."""
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"thanks for contacting",
    r"our team will (respond|get back|be in touch)",
    r"we will respond shortly",
    r"will get back to you",
    r"automated (message|reply|response|assistant)",
    r"this is an auto",
    r"main ek automated",
    r"yeh ek automated",
    r"aapki jaankari ke liye.*shukriya",
    r"currently (unavailable|away|out of office)",
    r"away from (my|the) phone",
    r"we are currently closed",
    r"business hours are",
    r"for urgent (matters|queries), (please |kindly )?call",
]

HOSTILE_PATTERNS = [
    r"stop (messaging|sending|contacting|calling|bothering)",
    r"don'?t (message|contact|send|call|bother)",
    r"not interested",
    r"leave me alone",
    r"this is (spam|useless|annoying|irritating)",
    r"remove (me|my number|my contact)",
    r"unsubscribe",
    r"band karo",
    r"mat bhejo",
    r"nahi chahiye",
    r"mujhe pareshan mat karo",
    r"block (kar|karunga|karungi)",
]

COMMITMENT_PATTERNS = [
    r"^yes\b",
    r"^haan\b",
    r"^ha\b",
    r"let'?s (do it|go|start|proceed)",
    r"ok(ay)? (let'?s|go|karo|proceed|chalte|kar)",
    r"\bgo ahead\b",
    r"\bproceed\b",
    r"\bconfirm\b",
    r"karo (yeh|it|ye|na|do)",
    r"kar do",
    r"shuru karo",
    r"start (kar|karo|it)",
    r"what'?s next",
    r"aage (badho|karo|chalo)",
    r"done[.!]?\s*(what|now|next)",
    r"sounds good[.!]?$",
    r"let'?s do this",
]


class ConversationManager:
    def __init__(self):
        # conv_id -> state dict
        self._states: Dict[str, dict] = {}
        # suppression_key -> expiry datetime
        self._suppressed: Dict[str, datetime] = {}
        # conv_id -> set of sent bodies (anti-repetition)
        self._sent_bodies: Dict[str, set] = {}

    # ─── suppression ──────────────────────────────────────────────────────────

    def is_suppressed(self, key: str) -> bool:
        if not key:
            return False
        exp = self._suppressed.get(key)
        return bool(exp and datetime.utcnow() < exp)

    def suppress(self, key: str, days: int = 7):
        if key:
            self._suppressed[key] = datetime.utcnow() + timedelta(days=days)

    def suppress_merchant(self, merchant_id: str, days: int = 30):
        self._suppressed[f"merchant:{merchant_id}"] = datetime.utcnow() + timedelta(days=days)

    def is_merchant_suppressed(self, merchant_id: str) -> bool:
        return self.is_suppressed(f"merchant:{merchant_id}")

    # ─── conversation state ───────────────────────────────────────────────────

    def _state(self, conv_id: str) -> dict:
        if conv_id not in self._states:
            self._states[conv_id] = {
                "status": "active",
                "auto_reply_count": 0,
                "history": [],
                "owner_hour": None,
            }
        return self._states[conv_id]

    def is_ended(self, conv_id: str) -> bool:
        s = self._states.get(conv_id)
        return bool(s and s["status"] == "ended")

    def end_conversation(self, conv_id: str):
        self._state(conv_id)["status"] = "ended"

    # ─── auto-reply detection ─────────────────────────────────────────────────

    def is_auto_reply(self, message: str) -> bool:
        msg = message.lower().strip()
        for pattern in AUTO_REPLY_PATTERNS:
            if re.search(pattern, msg):
                return True
        return False

    def increment_auto_reply(self, conv_id: str) -> int:
        s = self._state(conv_id)
        s["auto_reply_count"] += 1
        return s["auto_reply_count"]

    def reset_auto_reply(self, conv_id: str, hour: Optional[int] = None):
        s = self._state(conv_id)
        s["auto_reply_count"] = 0
        if hour is not None:
            s["owner_hour"] = hour

    # ─── intent detection ─────────────────────────────────────────────────────

    def is_hostile(self, message: str) -> bool:
        msg = message.lower().strip()
        for pattern in HOSTILE_PATTERNS:
            if re.search(pattern, msg):
                return True
        return False

    def is_commitment(self, message: str) -> bool:
        msg = message.lower().strip()
        for pattern in COMMITMENT_PATTERNS:
            if re.search(pattern, msg):
                return True
        return False

    # ─── history + anti-repetition ───────────────────────────────────────────

    def add_turn(self, conv_id: str, role: str, message: str):
        s = self._state(conv_id)
        s["history"].append({
            "role": role,
            "message": message,
            "at": datetime.utcnow().isoformat(),
        })
        if len(s["history"]) > 10:
            s["history"] = s["history"][-10:]

    def get_history(self, conv_id: str) -> List[dict]:
        return self._state(conv_id).get("history", [])

    def is_repeat_body(self, conv_id: str, body: str) -> bool:
        sent = self._sent_bodies.get(conv_id, set())
        return body.strip() in sent

    def record_sent_body(self, conv_id: str, body: str):
        self._sent_bodies.setdefault(conv_id, set()).add(body.strip())

    def clear(self):
        self._states.clear()
        self._suppressed.clear()
        self._sent_bodies.clear()

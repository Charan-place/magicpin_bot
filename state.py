"""In-memory context store — persists across requests as long as process is alive."""
from datetime import datetime
from typing import Optional, Tuple, Dict


class ContextStore:
    def __init__(self):
        # (scope, context_id) -> {version, payload, stored_at}
        self._data: Dict[Tuple[str, str], dict] = {}

    def upsert(self, scope: str, context_id: str, version: int, payload: dict) -> str:
        """Returns 'accepted' or 'stale'."""
        key = (scope, context_id)
        existing = self._data.get(key)
        if existing and existing["version"] >= version:
            return "stale"
        self._data[key] = {
            "version": version,
            "payload": payload,
            "stored_at": datetime.utcnow().isoformat() + "Z",
        }
        return "accepted"

    def get(self, scope: str, context_id: Optional[str]) -> Optional[dict]:
        if not context_id:
            return None
        return self._data.get((scope, context_id), {}).get("payload")

    def get_version(self, scope: str, context_id: str) -> int:
        entry = self._data.get((scope, context_id))
        return entry["version"] if entry else 0

    def counts(self) -> dict:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for scope, _ in self._data:
            if scope in counts:
                counts[scope] += 1
        return counts

    def clear(self):
        self._data.clear()

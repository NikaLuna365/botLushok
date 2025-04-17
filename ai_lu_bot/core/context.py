"""In‑memory + optional Redis chat‑history store."""
from __future__ import annotations

import os
import json
import time
import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional

try:
    import redis
except ImportError:
    redis = None  # Redis optional

logger = logging.getLogger(__name__)

MAX_CONTEXT_MESSAGES = 10

class ChatContextStore:
    """Simple store: RAM fallback, optional Redis."""

    def __init__(self) -> None:
        self._ram: Dict[int, Deque[dict[str, Any]]] = {}
        self._redis: Optional["redis.Redis"] = None
        if os.getenv("REDIS_URL") and redis is not None:
            try:
                self._redis = redis.from_url(os.getenv("REDIS_URL"))
                logger.info("Redis backend for context enabled")
            except Exception as e:  # pragma: no cover
                logger.warning("Redis init failed: %s — fallback to RAM", e)

    # ──────────────────────────────────────────────────────
    def _get_deque(self, chat_id: int) -> Deque[dict[str, Any]]:
        if self._redis:
            raw = self._redis.get(f"ctx:{chat_id}")
            if raw:
                # type: ignore[arg-type]
                return deque(json.loads(raw), MAX_CONTEXT_MESSAGES)
            return deque(maxlen=MAX_CONTEXT_MESSAGES)
        return self._ram.setdefault(chat_id, deque(maxlen=MAX_CONTEXT_MESSAGES))

    def _commit(self, chat_id: int, dq: Deque[dict[str, Any]]) -> None:
        if self._redis:
            self._redis.set(f"ctx:{chat_id}", json.dumps(list(dq)), ex=60 * 60 * 24)
        else:
            self._ram[chat_id] = dq

    # Public API
    # ───────────
    def append(self, chat_id: int, item: dict[str, Any]) -> None:
        dq = self._get_deque(chat_id)
        dq.append(item)
        self._commit(chat_id, dq)

    def trim(self, chat_id: int) -> None:
        dq = self._get_deque(chat_id)
        while len(dq) > MAX_CONTEXT_MESSAGES:
            dq.popleft()
        self._commit(chat_id, dq)

    def history(self, chat_id: int) -> List[dict[str, Any]]:
        return list(self._get_deque(chat_id))

context_store = ChatContextStore()

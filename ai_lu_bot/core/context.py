# ai_lu_bot/core/context.py
from typing import Any, Dict, List

class ChatContextManager:
    """
    Хранит историю переписки в памяти (до max_messages на чат).
    """
    def __init__(self, max_messages: int = 10):
        self._storage: Dict[int, List[Dict[str, Any]]] = {}
        self._max = max_messages

    def add(self, chat_id: int, entry: Dict[str, Any]) -> None:
        lst = self._storage.setdefault(chat_id, [])
        lst.append(entry)
        if len(lst) > self._max:
            lst.pop(0)

    def get(self, chat_id: int) -> List[Dict[str, Any]]:
        return self._storage.get(chat_id, [])

    def remove_last(self, chat_id: int) -> None:
        lst = self._storage.get(chat_id, [])
        if lst:
            lst.pop()

# Глобальный менеджер
chat_context_manager = ChatContextManager()

# ai_lu_bot/core/context.py
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# --- Константа для максимального количества сообщений в контексте ---
# Увеличено до 30 согласно плану Фазы 2, Задача 3.
MAX_CONTEXT_MESSAGES = 30

class ChatContextManager:
    """
    Управляет историей переписки для каждого чата в памяти.
    Хранит до MAX_CONTEXT_MESSAGES последних записей для каждого chat_id.
    История теряется при перезапуске приложения.
    """
    def __init__(self, max_messages: int = MAX_CONTEXT_MESSAGES):
        """
        Инициализирует менеджер контекста.

        Args:
            max_messages: Максимальное количество сообщений для хранения в истории.
        """
        self._storage: Dict[int, List[Dict[str, Any]]] = {}
        self._max = max_messages
        logger.info(f"ChatContextManager initialized with max_messages = {self._max}")


    def add(self, chat_id: int, entry: Dict[str, Any]) -> None:
        """
        Добавляет новую запись в историю контекста для указанного чата.
        Если история превышает максимальный размер, удаляет самую старую запись.

        Args:
            chat_id: ID чата.
            entry: Словарь, представляющий сообщение или событие для добавления.
                   Обычно содержит ключи 'user', 'text', 'from_bot', 'message_id'.
        """
        lst = self._storage.setdefault(chat_id, [])
        lst.append(entry)
        # Обрезаем историю, если она превышает максимальный размер
        if len(lst) > self._max:
            removed_entry = lst.pop(0) # Удаляем самый старый элемент
            # logger.debug(f"Context for chat {chat_id} exceeded max size. Removed oldest entry: {removed_entry.get('text', '...')[:30]}")
        # logger.debug(f"Added entry to context for chat {chat_id}. Current size: {len(lst)}")


    def get(self, chat_id: int) -> List[Dict[str, Any]]:
        """
        Возвращает текущую историю контекста для указанного чата.

        Args:
            chat_id: ID чата.

        Returns:
            Список словарей, представляющих историю сообщений. Возвращает пустой список,
            если история для данного чата отсутствует.
        """
        # logger.debug(f"Retrieving context for chat {chat_id}. Size: {len(self._storage.get(chat_id, []))}")
        return self._storage.get(chat_id, [])


    def remove_last(self, chat_id: int) -> None:
        """
        Удаляет самую последнюю добавленную запись из истории контекста для указанного чата.
        Полезно, если на сообщение не был дан ответ и оно не должно влиять на будущий контекст.

        Args:
            chat_id: ID чата.
        """
        lst = self._storage.get(chat_id, [])
        if lst:
            removed_entry = lst.pop()
            # logger.debug(f"Removed last entry from context for chat {chat_id}: {removed_entry.get('text', '...')[:30]}")
        # else:
             # logger.debug(f"Attempted to remove last entry from empty context for chat {chat_id}")

# Глобальный менеджер контекста, используемый во всем приложении
# (В будущем может быть заменен на реализацию с постоянным хранилищем)
chat_context_manager = ChatContextManager()

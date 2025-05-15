# ai_lu_bot/core/context.py
import logging
import json
from typing import Any, Dict, List, Optional
import redis # Импортируем библиотеку redis

logger = logging.getLogger(__name__)

# --- Константа для максимального количества сообщений в контексте ---
MAX_CONTEXT_MESSAGES = 30 # Теперь используется обеими реализациями менеджера

# --- Вспомогательные функции для сериализации/десериализации ---
def _serialize_entry(entry: Dict[str, Any]) -> str:
    """Сериализует запись контекста (словарь) в JSON строку."""
    # В будущем можно добавить обработку нестандартных типов, если они появятся
    return json.dumps(entry)

def _deserialize_data(data: Optional[bytes]) -> Optional[Dict[str, Any]]:
    """Десериализует JSON строку (bytes) в запись контекста (словарь)."""
    if data is None:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        logger.error(f"Failed to deserialize JSON data: {data!r}")
        return None # Возвращаем None или пустой словарь при ошибке


# --- Реализация менеджера контекста в памяти (старый) ---
class InMemoryChatContextManager:
    """
    Хранит историю переписки в памяти (до max_messages на чат).
    История теряется при перезапуске приложения.
    """
    def __init__(self, max_messages: int = MAX_CONTEXT_MESSAGES):
        """
        Инициализирует in-memory менеджер контекста.
        """
        self._storage: Dict[int, List[Dict[str, Any]]] = {}
        self._max = max_messages
        logger.info(f"InMemoryChatContextManager initialized with max_messages = {self._max}")

    def add(self, chat_id: int, entry: Dict[str, Any]) -> None:
        lst = self._storage.setdefault(chat_id, [])
        lst.append(entry)
        if len(lst) > self._max:
            lst.pop(0)
        # logger.debug(f"InMemory: Added entry to context for chat {chat_id}. Size: {len(lst)}")


    def get(self, chat_id: int) -> List[Dict[str, Any]]:
        """Возвращает историю контекста из памяти."""
        # logger.debug(f"InMemory: Retrieving context for chat {chat_id}. Size: {len(self._storage.get(chat_id, []))}")
        return self._storage.get(chat_id, [])


    def remove_last(self, chat_id: int) -> None:
        """Удаляет последнюю запись из истории в памяти."""
        lst = self._storage.get(chat_id, [])
        if lst:
            lst.pop()
            # logger.debug(f"InMemory: Removed last entry from context for chat {chat_id}.")
        # else:
             # logger.debug(f"InMemory: Attempted to remove last entry from empty context for chat {chat_id}")


# --- Реализация менеджера контекста с использованием Redis ---
class RedisChatContextManager:
    """
    Хранит историю переписки в Redis List (до max_messages на чат).
    Сохраняет контекст между перезапусками бота.
    """
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0, max_messages: int = MAX_CONTEXT_MESSAGES):
        """
        Инициализирует Redis менеджер контекста и устанавливает соединение.

        Args:
            host, port, db: Параметры подключения к Redis.
            max_messages: Максимальное количество сообщений для хранения.
        """
        self._max = max_messages
        self._redis_client: Optional[redis.Redis] = None # Тип Optional, т.к. подключение может не удаться

        try:
            # Создаем клиента Redis. pool_connections=True используется по умолчанию для пула соединений.
            self._redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=False) # decode_responses=False, т.к. json.loads ожидает bytes/str
            # Проверяем соединение (необязательно, но полезно при старте)
            self._redis_client.ping()
            logger.info(f"RedisChatContextManager initialized and connected to redis://{host}:{port}/{db} with max_messages = {self._max}")
        except redis.exceptions.ConnectionError as e:
            self._redis_client = None # Сбрасываем клиента, если подключение не удалось
            logger.critical(f"RedisChatContextManager: Failed to connect to Redis at {host}:{port}/{db}: {e}")
            # В этой реализации мы просто логируем ошибку и не можем использовать Redis.
            # При вызове add/get/remove_last нужно будет это обработать.
        except Exception as e:
            self._redis_client = None
            logger.critical(f"RedisChatContextManager: An unexpected error occurred during Redis initialization: {e}", exc_info=True)


    def _redis_key(self, chat_id: int) -> str:
        """Генерирует ключ Redis для истории чата."""
        return f"context:{chat_id}"

    def add(self, chat_id: int, entry: Dict[str, Any]) -> None:
        """
        Добавляет новую запись в историю контекста в Redis для указанного чата.
        Использует Redis List (RPUSH и LTRIM).
        """
        if not self._redis_client:
            logger.error(f"Redis not connected. Cannot add context for chat {chat_id}.")
            return

        key = self._redis_key(chat_id)
        try:
            # Сериализуем запись в JSON строку
            serialized_entry = _serialize_entry(entry).encode('utf-8') # Кодируем в bytes для Redis
            # Добавляем в конец списка (RPUSH)
            self._redis_client.rpush(key, serialized_entry)
            # Обрезаем список, чтобы оставить только последние max_messages элементов
            # LTRIM key start stop (0 - первый элемент, -1 - последний)
            # LTRIM key -max -1 оставляет max последних элементов
            self._redis_client.ltrim(key, -self._max, -1)
            # logger.debug(f"Redis: Added entry to context for chat {chat_id}. Key: {key}. Current length (approx): {self._redis_client.llen(key)}")
        except Exception as e:
            logger.error(f"Redis: Error adding context entry for chat {chat_id} (Key: {key}): {e}", exc_info=True)


    def get(self, chat_id: int) -> List[Dict[str, Any]]:
        """
        Возвращает текущую историю контекста из Redis для указанного чата.
        Возвращает последние MAX_CONTEXT_MESSAGES записей.
        """
        if not self._redis_client:
            logger.error(f"Redis not connected. Cannot get context for chat {chat_id}.")
            return [] # Возвращаем пустой список при отсутствии подключения

        key = self._redis_key(chat_id)
        try:
            # Получаем последние max_messages элементов из списка (LRANGE key start stop)
            # LRANGE key -max -1
            raw_entries = self._redis_client.lrange(key, -self._max, -1)
            # Десериализуем каждую запись
            entries = [_deserialize_data(raw_entry) for raw_entry in raw_entries if raw_entry is not None]
            # Фильтруем None, если десериализация не удалась для каких-то элементов
            valid_entries = [entry for entry in entries if entry is not None]
            # logger.debug(f"Redis: Retrieved context for chat {chat_id}. Key: {key}. Items: {len(valid_entries)}")
            return valid_entries
        except Exception as e:
            logger.error(f"Redis: Error getting context entries for chat {chat_id} (Key: {key}): {e}", exc_info=True)
            return [] # Возвращаем пустой список при ошибке


    def remove_last(self, chat_id: int) -> None:
        """
        Удаляет самую последнюю добавленную запись из истории контекста в Redis.
        Использует Redis List (RPOP).
        """
        if not self._redis_client:
            logger.error(f"Redis not connected. Cannot remove last context entry for chat {chat_id}.")
            return

        key = self._redis_key(chat_id)
        try:
            # Удаляем и получаем последний элемент списка (RPOP)
            removed_data = self._redis_client.rpop(key)
            # logger.debug(f"Redis: Removed last context entry for chat {chat_id}. Key: {key}. Data: {removed_data!r}")
            # Примечание: RPOP возвращает None, если список пуст, что корректно обрабатывается Redis.
        except Exception as e:
            logger.error(f"Redis: Error removing last context entry for chat {chat_id} (Key: {key}): {e}", exc_info=True)

# Удаляем глобальный инстанс менеджера контекста
# chat_context_manager = ChatContextManager() # УДАЛИТЬ или закомментировать

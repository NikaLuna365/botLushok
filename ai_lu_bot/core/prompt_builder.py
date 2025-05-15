# ai_lu_bot/core/prompt_builder.py
import logging
from typing import Any, Dict, List, Optional
from telegram import Message, ChatType # Импортируем для тайп-хинтинга

# Импортируем шаблон промпта из нового места
from ai_lu_bot.prompt.base_prompt import BASE_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def build_prompt(
    chat_id: int, # Сохраняем для потенциального логирования
    messages: List[Dict[str, Any]], # Теперь принимаем список сообщений как аргумент
    target_message: Message, # Используем Message для тайп-хинтинга
    response_trigger_type: str,
    media_type: str | None,
    media_data_bytes: bytes | None # Пока сохраняем, хотя данные bytes не нужны для сборки текстового промпта
) -> str:
    """
    Собирает полный промпт для Gemini API на основе шаблона, переданного контекста
    чата и целевого сообщения.
    """
    # Используем переданный список сообщений
    # messages = chat_context.get(chat_id, []) # Эту строку удаляем/комментируем

    # Определение имени пользователя или канала (логика остается прежней)
    target_username = "Неизвестный"
    # Идентификаторы создателя - лучше вынести в конфиг, но пока оставим тут для переноса
    creator_nicknames = ["Nik_Ly", "GroupAnonymousBot"] # Добавьте сюда реальные username/first_name создателя
    is_creator = False

    if target_message.from_user:
        is_creator = target_message.from_user.username in creator_nicknames or \
                     (target_message.from_user.username is None and target_message.from_user.first_name in creator_nicknames)

        if is_creator:
            target_username = "Создатель" # Используем специальный маркер для создателя
        else:
            target_username = target_message.from_user.username or target_message.from_user.first_name or "Неизвестный"

    elif target_message.forward_from_chat and target_message.forward_from_chat.title:
        target_username = f"Канал '{target_message.forward_from_chat.title}'"
    elif target_message.sender_chat and target_message.sender_chat.title:
         target_username = f"Канал '{target_message.sender_chat.title}'"

    # Определение текста целевого сообщения (текст или подпись)
    target_text = (target_message.text or target_message.caption or "").strip()

    # Описание типа сообщения для хедера истории
    msg_type_simple = "сообщение"
    num_photos = 0
    if media_type == "image" and target_message.photo:
         msg_type_simple = "изображение"
         num_photos = len(target_message.photo) # Считаем количество PhotoSize (косвенный признак кол-ва фото)
         if num_photos > 1:
             msg_type_simple = "изображения" # Множественное число
    elif media_type == "audio": msg_type_simple = "голосовое"
    elif media_type == "video": msg_type_simple = "видео кружок"
    elif target_message.forward_from_chat or target_message.sender_chat: msg_type_simple = "пост"


    # --- Строим строку истории переписки ---
    conversation_history_string = "История переписки (самые новые внизу):\n"
    # Фильтруем целевое сообщение из истории, если оно там оказалось (хотя по логике менеджера контекста его там не должно быть)
    context_messages_for_history = [msg for msg in messages if msg.get('message_id') != target_message.message_id]

    if not context_messages_for_history:
         conversation_history_string += "[Начало диалога]\n"

    for msg in context_messages_for_history:
        # Используем маркер "Создатель" или "Бот" или имя пользователя
        # Убедимся, что поля существуют, прежде чем их использовать
        label = "[Бот]" if msg.get("from_bot", False) else f"[{msg.get('user', 'Неизвестный')}]"
        context_text = msg.get('text', '[Сообщение без текста или только с медиа]')
        conversation_history_string += f"{label}: {context_text}\n"

    conversation_history_string += "---\n" # Разделитель

    # Добавляем целевое сообщение как последнюю реплику
    target_message_header = f"[{target_username}] ({msg_type_simple}):"
    target_message_content = target_text if target_text else ""

    # Явно указываем наличие медиа ТОЛЬКО если оно есть
    # Обратите внимание: логика в bot_4_02.py передавала media_type только если bytes_data были скачаны
    # Но для build_prompt нам достаточно знать тип медиа, bytes_data не нужны для *сборки строки промпта*
    # Переменная media_data_bytes здесь не используется, но сохранена в сигнатуре для совместимости с вызовом из gemini.py
    if media_type == "image": # Предполагаем, что тип медиа корректно определен
        img_tag = "[Изображение]" if num_photos <= 1 else "[Изображения]"
        target_message_content = f"{img_tag}{(': ' + target_text) if target_text else ''}"
        target_message_content += " (медиа прикреплено для анализа)" # Это добавляется в текст промпта!
    elif media_type == "audio":
        target_message_content = "[Голосовое сообщение] (медиа прикреплено для анализа)"
    elif media_type == "video":
         target_message_content = "[Видео кружок] (медиа прикреплено для анализа)"
    elif not target_text and media_type == "text": # Если текст пуст и нет медиа
         target_message_content = "[Пустое сообщение]"
    # Если есть только текст (или пост без медиа), target_message_content уже содержит его

    conversation_history_string += f"{target_message_header} {target_message_content}\n"

    # --- Формируем краткую финальную задачу (логика остается прежней) ---
    final_task_string = "ЗАДАНИЕ: Напиши ответ в стиле Лу на ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    if response_trigger_type == "channel_post":
        final_task_string = "ЗАДАНИЕ: Напиши комментарий в стиле Лу на ПОСЛЕДНИЙ пост в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    elif response_trigger_type == "dm":
         final_task_string = "ЗАДАНИЕ: Ответь пользователю в личных сообщениях на его ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности (Лу), стилю формулирования и всем инструкциям из Блоков 1-5."
    # Добавляем специальное указание, если отвечает создателю
    if target_username == "Создатель":
        final_task_string += " ПОМНИ ОСОБЫЕ ПРАВИЛА ОБЩЕНИЯ С СОЗДАТЕЛЕМ (см. Блок 1.3 и 3.1.2.15)."


    # --- Собираем итоговый промпт из шаблона ---
    final_prompt = BASE_PROMPT_TEMPLATE.replace(
        "{{CONVERSATION_HISTORY_PLACEHOLDER}}",
        conversation_history_string
    ).replace(
        "{{FINAL_TASK_PLACEHOLDER}}",
        final_task_string
    )

    # logger.debug("Итоговый промпт для Gemini:\n%s", final_prompt) # Можно раскомментировать для отладки
    return final_prompt

# ai_lu_bot/core/prompt_builder.py
import logging
from typing import Any, Dict, List, Optional
# Импортируем Message из telegram
from telegram import Message
# Импортируем ChatType из telegram.constants (исправление Import Error)
from telegram.constants import ChatType

# Импортируем шаблон промпта из нового места внутри пакета
from ai_lu_bot.prompt.base_prompt import BASE_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def build_prompt(
    chat_id: int, # Сохраняем chat_id для потенциального использования (например, в логировании)
    messages: List[Dict[str, Any]], # Список сообщений для контекста, переданный из менеджера
    target_message: Message, # Целевое сообщение, на которое бот отвечает
    response_trigger_type: str, # Тип триггера ответа (dm, reply, creator, random, channel_post)
    media_type: str | None, # Тип медиа в целевом сообщении (image, audio, video, text)
    media_data_bytes: bytes | None # Байты медиа (не используются в сборке текста, но передаются из GeminiService)
) -> str:
    """
    Собирает полный промпт для Gemini API на основе шаблона, переданного контекста
    чата и целевого сообщения.

    Args:
        chat_id: ID чата.
        messages: Список словарей, представляющих сообщения в истории диалога,
                  включая целевое сообщение (должно быть последним).
        target_message: Объект telegram.Message целевого сообщения.
        response_trigger_type: Строка, описывающая, почему бот отвечает.
        media_type: Тип медиа в целевом сообщении ('image', 'audio', 'video') или None/text.
                    Должен быть установлен, только если медиа успешно скачано для анализа ИИ.
        media_data_bytes: Байты медиафайла (не используются в этой функции, но часть сигнатуры).

    Returns:
        Строка, содержащая полный промпт для Gemini API.
    """
    # Определение имени пользователя или канала, отправившего целевое сообщение
    target_username = "Неизвестный"
    # Идентификаторы создателя - временно здесь, для переноса. Лучше вынести в конфиг/переменные окружения.
    creator_nicknames = ["Nik_Ly", "GroupAnonymousBot"]

    is_creator = False
    if target_message.from_user:
        # Проверяем отправителя-пользователя
        nick = target_message.from_user.username or target_message.from_user.first_name or ""
        if nick in creator_nicknames:
            target_username = "Создатель"
            is_creator = True
        else:
            target_username = nick # Используем ник или имя пользователя
    elif target_message.forward_from_chat and target_message.forward_from_chat.title:
        # Проверяем, если сообщение переслано из чата (например, канала)
        target_username = f"Канал '{target_message.forward_from_chat.title}'"
    elif target_message.sender_chat and target_message.sender_chat.title:
        # Проверяем, если сообщение отправлено от имени чата (например, канала или группы)
        target_username = f"Чат '{target_message.sender_chat.title}'"
        # Можно добавить проверку, является ли sender_chat "создателем", если посты от имени канала тоже могут быть от него.
        # is_creator = target_message.sender_chat.username in creator_nicknames # у sender_chat может не быть username

    # Определение текста целевого сообщения (текст или подпись)
    target_text = (target_message.text or target_message.caption or "").strip()

    # Описание типа сообщения для хедера истории и промпта
    msg_type_simple = "сообщение"
    num_photos = 0
    if media_type == "image" and target_message.photo:
         msg_type_simple = "изображение"
         # Count PhotoSize objects as a proxy for number of images in an album
         num_photos = len(target_message.photo)
         if num_photos > 1:
             msg_type_simple = "изображения" # Plural form for albums
    elif media_type == "audio":
        msg_type_simple = "голосовое"
    elif media_type == "video":
        msg_type_simple = "видео кружок"
    # If it's a forwarded/sent-as-chat message without other specific media types
    elif target_message.forward_from_chat or target_message.sender_chat:
        msg_type_simple = "пост"


    # --- Строим строку истории переписки ---
    conversation_history_string = "История переписки (самые новые внизу):\n"

    # Подготавливаем сообщения для истории, исключая целевое сообщение, т.к. оно будет добавлено отдельно последним
    # Filter out the target message from the history list if it's present
    context_messages_for_history = [msg for msg in messages if msg.get('message_id') != target_message.message_id]

    if not context_messages_for_history:
         conversation_history_string += "[Начало диалога]\n"

    # Добавляем сообщения из контекста в строку истории
    for msg in context_messages_for_history:
        # Убедимся, что поля 'user' и 'text' существуют в словаре, прежде чем их использовать
        label = "[Бот]" if msg.get("from_bot", False) else f"[{msg.get('user', 'Неизвестный')}]"
        context_text = msg.get('text', '[Сообщение без текста или только с медиа]') # Default text if 'text' key is missing
        conversation_history_string += f"{label}: {context_text}\n"

    conversation_history_string += "---\n" # Разделитель между историей и целевым сообщением

    # Добавляем целевое сообщение как последнюю реплику, формат зависит от типа контента
    target_message_header = f"[{target_username}] ({msg_type_simple}):"
    target_message_content = target_text if target_text else ""

    # Явно указываем наличие медиа ТОЛЬКО если оно было успешно скачано и передано
    # media_data_bytes наличие не проверяем здесь, т.к. для сборки строки достаточно media_type
    # Предполагается, что media_type == 'image'/'audio'/'video' только если bytes были скачаны
    if media_type == "image":
        img_tag = "[Изображение]" if num_photos <= 1 else "[Изображения]"
        target_message_content = f"{img_tag}{(': ' + target_text) if target_text else ''}"
        target_message_content += " (медиа прикреплено для анализа)" # Добавляем эту фразу в промпт
    elif media_type == "audio":
        target_message_content = "[Голосовое сообщение] (медиа прикреплено для анализа)"
    elif media_type == "video":
         target_message_content = "[Видео кружок] (медиа прикреплено для анализа)"
    elif not target_text and media_type == "text":
         # Если текст пуст, это текстовое сообщение, но без содержимого (редкий случай, уже должен быть отфильтрован)
         target_message_content = "[Пустое сообщение]"
    # В остальных случаях (текст есть, или это пост без специфического медиа), target_message_content уже содержит target_text

    conversation_history_string += f"{target_message_header} {target_message_content}\n"

    # --- Формируем краткую финальную задачу для ИИ ---
    # Логика формирования задачи остается прежней на основе типа триггера
    final_task_string = "ЗАДАНИЕ: Напиши ответ в стиле Лу на ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    # Уточнения задачи в зависимости от триггера (для ИИ)
    if response_trigger_type == "channel_post_forwarded_or_sent_as":
        final_task_string = "ЗАДАНИЕ: Напиши комментарий в стиле Лу на ПОСЛЕДНИЙ пост (пересланный или отправленный от имени канала) в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    elif response_trigger_type == "dm":
         final_task_string = "ЗАДАНИЕ: Ответь пользователю в личных сообщениях на его ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности (Лу), стилю формулирования и всем инструкциям из Блоков 1-5."
    elif response_trigger_type in ["reply_to_bot", "creator_message", "random_group_message"]:
         # Для ответов в группе (на бота, от создателя, случайные) задача остается общей "Напиши ответ"
         pass # Задача по умолчанию уже подходит
    # Добавляем специальное указание, если отвечает создателю
    if is_creator:
        final_task_string += " ПОМНИ ОСОБЫЕ ПРАВИЛА ОБЩЕНИЯ С СОЗДАТЕЛЕМ (см. Блок 1.3 и 3.1.2.15)."


    # --- Собираем итоговый промпт из шаблона ---
    final_prompt = BASE_PROMPT_TEMPLATE.replace(
        "{{CONVERSATION_HISTORY_PLACEHOLDER}}",
        conversation_history_string
    ).replace(
        "{{FINAL_TASK_PLACEHOLDER}}",
        final_task_string
    )

    # logger.debug("Built prompt for chat %d:\n%s", chat_id, final_prompt) # Раскомментировать для отладки промпта
    return final_prompt

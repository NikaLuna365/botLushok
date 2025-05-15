# ai_lu_bot/core/prompt_builder.py
import logging
from typing import Any, Dict, List, Optional
from telegram import Message
from telegram.constants import ChatType

from ai_lu_bot.prompt.base_prompt import BASE_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def build_prompt(
    chat_id: int, # Required: ID чата.
    messages: List[Dict[str, Any]], # Required: Список сообщений для контекста.
    target_message: Message, # Required: Целевое сообщение, на которое бот отвечает.
    trigger: str, # Required: Тип триггера ответа.
    replied_to_message: Optional[Message] = None, # Optional: Объект сообщения, на которое отвечает target_message.
    media_type: Optional[str] = None, # Optional: Тип медиа в целевом сообщении.
    media_data_bytes: Optional[bytes] = None # Optional: Байты медиа (не используются для сборки текста).
) -> str:
    """
    Собирает полный промпт для Gemini API на основе шаблона, переданного контекста
    чата, целевого сообщения и информации о комментируемом посте (если применимо).

    Args:
        chat_id: ID чата.
        messages: Список словарей, представляющих сообщения в истории диалога.
        target_message: Объект telegram.Message целевого сообщения.
        trigger: Строка, описывающая, почему бот отвечает.
        replied_to_message: Объект telegram.Message, на который отвечает target_message (если есть).
        media_type: Тип медиа в целевом сообщении ('image', 'audio', 'video') или None/text.
                    Должен быть установлен, только если медиа успешно скачано для анализа ИИ.
        media_data_bytes: Байты медиафайла (не используются в этой функции).

    Returns:
        Строка, содержащая полный промпт для Gemini API.
    """
    # Определение имени отправителя целевого сообщения
    target_username = "Неизвестный"
    creator_nicknames = ["Nik_Ly", "GroupAnonymousBot"]
    is_creator = False

    if target_message.from_user:
        nick = target_message.from_user.username or target_message.from_user.first_name or ""
        if nick in creator_nicknames:
            target_username = "Создатель"
            is_creator = True
        else:
            target_username = nick
    elif target_message.forward_from_chat and target_message.forward_from_chat.title:
        target_username = f"Канал '{target_message.forward_from_chat.title}'"
    elif target_message.sender_chat and target_message.sender_chat.title:
         target_username = f"Чат '{target_message.sender_chat.title}'"

    # Определение текста и типа медиа целевого сообщения
    target_text = (target_message.text or target_message.caption or "").strip()
    msg_type_simple = "сообщение"
    num_photos = 0
    if media_type == "image" and target_message.photo:
         msg_type_simple = "изображение"
         num_photos = len(target_message.photo)
         if num_photos > 1: msg_type_simple = "изображения"
    elif media_type == "audio": msg_type_simple = "голосовое"
    elif media_type == "video": msg_type_simple = "видео кружок"
    elif target_message.forward_from_chat or target_message.sender_chat: msg_type_simple = "пост"


    # --- Строим строку истории переписки ---
    conversation_history_parts = ["История переписки (самые новые внизу):"]

    # Подготавливаем сообщения из истории, исключая целевое сообщение
    context_messages_for_history = [msg for msg in messages if msg.get('message_id') != target_message.message_id]

    if not context_messages_for_history:
         conversation_history_parts.append("[Начало диалога]")

    for msg in context_messages_for_history:
        label = "[Бот]" if msg.get("from_bot", False) else f"[{msg.get('user', 'Неизвестный')}]"
        context_text = msg.get('text', '[Сообщение без текста или только с медиа]')
        conversation_history_parts.append(f"{label}: {context_text}")

    conversation_history_parts.append("---") # Разделитель

    # --- Добавляем информацию о комментируемом посте, если она доступна ---
    if replied_to_message:
        replied_text = (replied_to_message.text or replied_to_message.caption or "").strip()
        if replied_text:
            # Определяем, откуда был переслан комментируемый пост (если доступно)
            forward_info = ""
            if replied_to_message.forward_from_chat:
                 forward_info = f" (из Канала '{replied_to_message.forward_from_chat.title}')"
            elif replied_to_message.sender_chat:
                 forward_info = f" (из Чата '{replied_to_message.sender_chat.title}')"

            # Добавляем текст комментируемого поста в промпт
            conversation_history_parts.append(f"[Комментируемый пост{forward_info}]: {replied_text}")
            # logger.debug(f"Added replied-to message text to prompt: '{replied_text[:50]}...'")
        # else:
             # logger.debug("replied_to_message exists but has no text/caption to add to prompt.")


    # --- Добавляем целевое сообщение как последнюю реплику ---
    target_message_header = f"[{target_username}] ({msg_type_simple}):"
    target_message_content = target_text if target_text else ""

    if media_type == "image":
        img_tag = "[Изображение]" if num_photos <= 1 else "[Изображения]"
        target_message_content = f"{img_tag}{(': ' + target_text) if target_text else ''}"
        target_message_content += " (медиа прикреплено для анализа)"
    elif media_type == "audio":
        target_message_content = "[Голосовое сообщение] (медиа прикреплено для анализа)"
    elif media_type == "video":
         target_message_content = "[Видео кружок] (медиа прикреплено для анализа)"
    elif not target_text and media_type == "text":
         target_message_content = "[Пустое сообщение]"

    conversation_history_parts.append(f"{target_message_header} {target_message_content}")


    # --- Формируем краткую финальную задачу ---
    final_task_string = "ЗАДАНИЕ: Напиши ответ в стиле Лу на ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    if response_trigger_type == "channel_post_forwarded_or_sent_as":
        final_task_string = "ЗАДАНИЕ: Напиши комментарий в стиле Лу на ПОСЛЕДНИЙ пост (пересланный или отправленный от имени канала) в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    elif response_trigger_type == "dm":
         final_task_string = "ЗАДАНИЕ: Ответь пользователю в личных сообщениях на его ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности (Лу), стилю формулирования и всем инструкциям из Блоков 1-5."
    elif is_creator: # Признак Создателя ставится только на отправителя целевого сообщения
        final_task_string += " ПОМНИ ОСОБЫЕ ПРАВИЛА ОБЩЕНИЯ С СОЗДАТЕЛЕМ (см. Блок 1.3 и 3.1.2.15)."


    # --- Собираем итоговый промпт из всех частей ---
    conversation_history_string = "\n".join(conversation_history_parts)

    final_prompt = BASE_PROMPT_TEMPLATE.replace(
        "{{CONVERSATION_HISTORY_PLACEHOLDER}}",
        conversation_history_string
    ).replace(
        "{{FINAL_TASK_PLACEHOLDER}}",
        final_task_string
    )

    # logger.debug("Built prompt for chat %d:\n%s", chat_id, final_prompt)
    return final_prompt

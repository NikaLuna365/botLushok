# ai_lu_bot/core/prompt_builder.py
import logging
# Импортируем необходимые типы для тайп-хинтинга
from typing import Any, Dict, List, Optional
# Импортируем Message из telegram
from telegram import Message
# Импортируем ChatType из telegram.constants (исправление Import Error)
from telegram.constants import ChatType

# Импортируем шаблон промпта из нового места внутри пакета
from ai_lu_bot.prompt.base_prompt import BASE_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def build_prompt(
    chat_id: int, # Required: ID чата.
    messages: List[Dict[str, Any]], # Required: Список сообщений для контекста.
    target_message: Message, # Required: Целевое сообщение, на которое бот отвечает.
    trigger: str, # Required: Тип триггера ответа.
    replied_to_message: Optional[Message] = None, # Optional: Объект сообщения, на которое отвечает target_message. (Со значением по умолчанию)
    media_type: Optional[str] = None, # Optional: Тип медиа в целевом сообщении. (Со значением по умолчанию)
    media_data_bytes: Optional[bytes] = None # Optional: Байты медиа (не используются для сборки текста). (Со значением по умолчанию)
) -> str:
    """
    Собирает полный промпт для Gemini API на основе шаблона, переданного контекста
    чата, целевого сообщения и информации о комментируемом посте (если применимо).

    Args:
        chat_id: ID чата.
        messages: Список словарей, представляющих сообщения в истории диалога.
        target_message: Объект telegram.Message целевого сообщения.
        trigger: Строка, описывающая, почему бот отвечает.
        replied_to_message: Объект telegram.Message, на который отвечает target_message, или None.
        media_type: Тип медиа в целевом сообщении ('image', 'audio', 'video') или None/text.
                    Указывается, только если медиа *пытались* скачать (даже при ошибке скачивания).
                    В промпте добавляется "(медиа прикреплено)", только если media_bytes не None.
        media_data_bytes: Байты медиафайла. Передается, только если медиа успешно скачано.
                          Используется здесь только для проверки, успешно ли скачано медиа,
                          чтобы добавить "(медиа прикреплено для анализа)" в промпт.

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
    # Определяем простой тип сообщения для отображения в промпте
    if media_type == "image" and target_message.photo:
         msg_type_simple = "изображение"
         # Count PhotoSize objects as a proxy for number of images in an album
         num_photos = len(target_message.photo)
         if num_photos > 1: msg_type_simple = "изображения" # Plural form for albums
    elif media_type == "audio":
        msg_type_simple = "голосовое"
    elif media_type == "video":
        msg_type_simple = "видео кружок"
    # Если это пересланное сообщение или сообщение от имени чата без специфического медиа
    elif target_message.forward_from_chat or target_message.sender_chat:
        msg_type_simple = "пост"


    # --- Строим строку истории переписки ---
    conversation_history_parts = ["История переписки (самые новые внизу):"]

    # Подготавливаем сообщения из истории, исключая целевое сообщение (оно всегда последнее)
    context_messages_for_history = [msg for msg in messages if msg.get('message_id') != target_message.message_id]

    if not context_messages_for_history:
         conversation_history_parts.append("[Начало диалога]")

    # Добавляем сообщения из контекста в строку истории
    for msg in context_messages_for_history:
        label = "[Бот]" if msg.get("from_bot", False) else f"[{msg.get('user', 'Неизвестный')}]"
        # Убедимся, что поле 'text' существует в словаре сообщения контекста
        context_text = msg.get('text', '[Сообщение без текста или только с медиа]')
        conversation_history_parts.append(f"{label}: {context_text}")

    conversation_history_parts.append("---") # Разделитель между историей и текущими элементами


    # --- Добавляем информацию о комментируемом посте, если она доступна и является объектом Message ---
    # !!! ИСПРАВЛЕНИЕ: Добавлена проверка isinstance(replied_to_message, Message) !!!
    if replied_to_message and isinstance(replied_to_message, Message):
        # Извлекаем текст или подпись из объекта Message, на который ответили
        replied_text = (replied_to_message.text or replied_to_message.caption or "").strip()
        if replied_text:
            # Определяем, откуда был переслан комментируемый пост (если доступно из Message объекта)
            forward_info = ""
            # Используем getattr для безопасного доступа к атрибутам, которые могут отсутствовать
            if getattr(replied_to_message, 'forward_from_chat', None):
                 # Проверяем, что forward_from_chat это объект ChatType/Chat и у него есть title
                 if hasattr(replied_to_message.forward_from_chat, 'title'):
                    forward_info = f" (из Канала '{replied_to_message.forward_from_chat.title}')"
                 elif hasattr(replied_to_message.forward_from_chat, 'username'): # Если title нет, возможно, есть username
                    forward_info = f" (из Канала '@{replied_to_message.forward_from_chat.username}')"

            elif getattr(replied_to_message, 'sender_chat', None):
                 # Проверяем, что sender_chat это объект ChatType/Chat и у него есть title
                 if hasattr(replied_to_message.sender_chat, 'title'):
                    forward_info = f" (из Чата '{replied_to_message.sender_chat.title}')"
                 elif hasattr(replied_to_message.sender_chat, 'username'):
                    forward_info = f" (из Чата '@{replied_to_message.sender_chat.username}')"


            # Добавляем текст комментируемого поста в промпт с пометкой
            conversation_history_parts.append(f"[Комментируемый пост{forward_info}]: {replied_text}")
            logger.debug(f"Added replied-to message text to prompt: '{replied_text[:50]}...'")
        # else:
             # logger.debug("replied_to_message exists and is Message, but has no text/caption to add to prompt.")
    # else:
        # logger.debug("replied_to_message is None or not a Message object. Not adding context.")


    # --- Добавляем целевое сообщение как последнюю реплику ---
    target_message_header = f"[{target_username}] ({msg_type_simple}):"
    target_message_content = target_text if target_text else ""

    # Явно указываем наличие медиа ТОЛЬКО если оно было успешно скачано (media_data_bytes не None)
    # media_type используется здесь build_prompt только для определения img_tag/метки типа
    if media_data_bytes is not None and media_type in ("image", "audio", "video"):
        if media_type == "image":
            img_tag = "[Изображение]" if num_photos <= 1 else "[Изображения]"
            target_message_content = f"{img_tag}{(': ' + target_text) if target_text else ''}"
        elif media_type == "audio":
            target_message_content = "[Голосовое сообщение]"
            if target_text: target_message_content += f": {target_text}"
        elif media_type == "video":
             target_message_content = "[Видео кружок]"
             if target_text: target_message_content += f": {target_text}"
        # Добавляем фразу про анализ медиа только если байты есть
        target_message_content += " (медиа прикреплено для анализа)"
    elif not target_text and media_type == "text":
         # Если текст пуст, это текстовое сообщение, но без содержимого (редкий случай)
         target_message_content = "[Пустое сообщение]"
    # В остальных случаях (текст есть, или это пост без специфического медиа), target_message_content уже содержит target_text

    conversation_history_parts.append(f"{target_message_header} {target_message_content}")


    # --- Формируем краткую финальную задачу для ИИ ---
    final_task_string = "ЗАДАНИЕ: Напиши ответ в стиле Лу на ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    # Уточнения задачи в зависимости от триггера (для ИИ)
    if trigger == "channel_post_forwarded_or_sent_as":
        final_task_string = "ЗАДАНИЕ: Напиши комментарий в стиле Лу на ПОСЛЕДНИЙ пост (пересланный или отправленный от имени канала) в истории выше, полностью следуя своей личности, стилю формулирования и всем инструкциям из Блоков 1-5."
    elif trigger == "dm":
         final_task_string = "ЗАДАНИЕ: Ответь пользователю в личных сообщениях на его ПОСЛЕДНЕЕ сообщение в истории выше, полностью следуя своей личности (Лу), стилю формулирования и всем инструкциям из Блоков 1-5."
    # Добавляем специальное указание, если отвечает создателю, который отправил целевое сообщение
    if is_creator:
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

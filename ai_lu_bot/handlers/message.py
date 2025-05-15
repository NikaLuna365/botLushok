# ai_lu_bot/handlers/message.py

import logging
import random
# Убираем импорт из bot_4_02
# from bot_4_02 import filter_technical_info, build_prompt # Удалить или закомментировать

from telegram import Update, ReplyKeyboardMarkup, Voice, VideoNote, PhotoSize, ChatType # Добавили ChatType
from telegram.ext import ContextTypes

from ai_lu_bot.services.gemini import GeminiService
from ai_lu_bot.utils.media import download_media, MediaDownloadError
from ai_lu_bot.core.context import chat_context_manager
# Импортируем перенесенные функции
from ai_lu_bot.utils.text_utils import filter_technical_info
from ai_lu_bot.core.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


# --- Перенесенная функция start из bot_4_02.py ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение и кнопки."""
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        # Текст из bot_4_02.py
        "Привет! Я AI LU – цифровая копия Николая Лу. Могу поболтать о всяком, высказать свое 'ценное' мнение или просто поиронизировать над бытием. Спрашивай или предлагай тему.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# --- Основной Обработчик Сообщений (handle_message) ---
# Здесь будет реализована логика игнорирования комментариев от имени канала (Задача 2 Фазы 1)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает входящие сообщения (текст, голос, видео, фото), скачивает медиа, решает, отвечать ли (включая игнор комментариев от имени канала), и вызывает Gemini."""
    try:
        message = update.message
        if not message:
            logger.warning("Received update without message object.")
            return

        chat_id = update.effective_chat.id
        message_id = message.message_id
        chat_type = update.effective_chat.type # Получаем тип чата

        # --- Определяем отправителя (немного подробнее для логики игнора) ---
        username = "Неизвестный"
        is_creator = False
        # Идентификаторы создателя (лучше брать из конфига)
        creator_nicknames = ["Nik_Ly", "GroupAnonymousBot"]

        sender_is_user = message.from_user is not None
        sender_is_chat = message.sender_chat is not None

        if sender_is_user:
            nick = message.from_user.username or message.from_user.first_name or ""
            if nick in creator_nicknames:
                username = "Создатель"
                is_creator = True
            else:
                username = nick
        elif sender_is_chat:
             # Сообщение отправлено от имени чата (канал, группа)
             username = f"Чат '{message.sender_chat.title}'"
             # Проверяем, является ли sender_chat создателем (если создатель постит от имени канала)
             # Это может быть нужно, если хотим отвечать на посты от имени канала, если это "посты создателя"
             # Пока оставим простую проверку ника, но это место для улучшения
             # is_creator = message.sender_chat.username in creator_nicknames # У sender_chat может не быть username

        # Если переслано из канала (Message.forward_from_chat)
        elif message.forward_from_chat:
            username = f"Переслано из канала '{message.forward_from_chat.title}'"


        media_type = None
        media_obj = None
        text = ""

        # --- Определяем тип контента и исходный текст ---
        if message.photo:
            media_type = "image"
            media_obj = message.photo[-1] # Берем самую большую версию
            text = (message.caption or "").strip()
        elif message.video_note:
            media_type = "video"
            media_obj = message.video_note
        elif message.voice:
            media_type = "audio"
            media_obj = message.voice
        else:
            text = (message.text or message.caption or "").strip()

        log_text_preview = text[:50] + "..." if len(text) > 50 else text
        log_media_info = f", media_type: {media_type}" if media_type else ""
        logger.info("Received from %s (user_id: %s, chat_id: %s%s): '%s'",
                    username, message.from_user.id if message.from_user else 'N/A', chat_id, log_media_info, log_text_preview)


        # --- Записываем в контекст (перед принятием решения об ответе, чтобы история была полной) ---
        # Текст для контекста должен включать информацию о медиа, если текста нет
        context_entry_text = text
        if not context_entry_text and media_type:
            context_entry_text = f"[{media_type.capitalize()}]"
            if media_type == "image" and message.photo and len(message.photo) > 1:
                context_entry_text = "[Изображения]"
        elif message.forward_from_chat or message.sender_chat:
             if not context_entry_text:
                  context_entry_text = "[Пост без текста]" # Уточняем для постов без текста

        chat_context_manager.add(
            chat_id,
            {
                "user": username, # Сохраняем определенное имя пользователя/чата
                "text": context_entry_text,
                "from_bot": False,
                "message_id": message_id,
            },
        )
        # Пока не меняем MAX_CONTEXT_MESSAGES здесь, это часть Фазы 2.
        # chat_context_manager.add() сама обрезает до MAX_CONTEXT_MESSAGES


        # --- Решаем, отвечать ли (Задача 2 Фазы 1: Игнорирование комментариев от имени канала) ---
        should_respond = False
        trigger = None

        is_reply_to_message = message.reply_to_message is not None
        is_reply_to_bot = is_reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id

        # *** НОВАЯ ЛОГИКА ИГНОРИРОВАНИЯ КОММЕНТАРИЕВ ОТ ИМЕНИ КАНАЛА ***
        # Если это ответ на сообщение (т.е. потенциально комментарий в группе обсуждения)
        # И отправлен от имени чата (sender_chat), а НЕ пользователя (from_user),
        # То это, скорее всего, комментарий от лица канала. Игнорируем.
        if is_reply_to_message and sender_is_chat and not sender_is_user:
             logger.info("Ignoring message %d from '%s': Identified as a comment sent as channel.", message_id, username)
             should_respond = False # Явно не отвечаем
             # Удаляем только что добавленное сообщение из контекста, т.к. на него не отвечаем
             chat_context_manager.remove_last(chat_id)
             return # Выходим из функции
        # *******************************************************************

        # Логика для принятия решения об ответе на сообщения, которые НЕ являются комментариями от имени канала:

        # 1. Личное сообщение → всегда отвечаем
        if chat_type == ChatType.PRIVATE:
            should_respond, trigger = True, "dm"
            logger.info("Trigger: Private message from %s.", username)

        # 2. Ответ боту в группе или сообщение от Создателя в группе
        elif chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if is_reply_to_bot:
                should_respond, trigger = True, "reply_to_bot"
                logger.info("Trigger: Reply to bot in group from %s.", username)
            elif is_creator: # Проверка is_creator уже учитывает, отправлено от user или sender_chat (если ник совпал)
                 should_respond, trigger = True, "creator_message"
                 logger.info("Trigger: Message from Creator (%s) in group.", username)
            # 3. Посты из каналов (пересланные в группу обсуждения)
            # Определяем, является ли сообщение пересланным из канала
            is_forwarded_channel_post = message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL
            # Или отправленным от имени канала в группе (sender_chat), если это не комментарий от имени канала (уже отсеяли выше)
            is_sent_as_channel_post_in_group = sender_is_chat and chat_type != ChatType.PRIVATE and not is_reply_to_message

            if (is_forwarded_channel_post or is_sent_as_channel_post_in_group):
                 # Отвечаем на посты с медиа или текстом >= 5 слов, если это не комментарий от имени канала (уже проверено)
                 if media_type is not None or (text and len(text.split()) >= 5):
                     should_respond, trigger = True, "channel_post_forwarded_or_sent_as"
                     logger.info("Trigger: Channel post (forwarded or sent as channel) from %s (with media or text >= 5 words).", username)
                 else:
                     logger.info("Skipping response: Short text-only channel post (forwarded or sent as channel) from %s.", username)
            # 4. Случайный ответ в группе (на обычное сообщение, не ответ боту, не создатель, не пост)
            # Применяется только если ни один из предыдущих триггеров в группе не сработал
            elif not is_reply_to_message and not is_creator and not is_forwarded_channel_post and not is_sent_as_channel_post_in_group:
                is_short_text_only = media_type == "text" and (not text or len(text.split()) < 3)
                if not is_short_text_only and random.random() < 0.05: # 5% шанс ответа
                    should_respond = True
                    trigger = "random_group_message"
                    logger.info("Trigger: Random response (5%% chance) for message (type: %s) from %s in group.", media_type or 'text', username)
                elif is_short_text_only:
                     logger.info("Skipping response: Short text-only message from %s in group.", username)
                else:
                     logger.info("Skipping response: Random chance (5%%) not met for message from %s in group.", username)
            else:
                 # Пропускаем сообщения в группе, которые не подпадают ни под один триггер (например, ответы пользователей друг другу)
                 logger.info("Skipping response: Message from %s in group does not match any trigger.", username)


        if not should_respond:
            logger.info("Final decision: Not responding to message ID %d from %s.", message_id, username)
            # Сообщение уже удалено из контекста, если был игнор комментария от имени канала.
            # Если не отвечаем по другим причинам (например, не выпал шанс, короткий текст),
            # то сообщение все равно остается в контексте на случай, если бот ответит на что-то следующее.
            # Удалять его только при should_respond == False может нарушить последовательность контекста.
            # Поэтому оставляем его в контексте, менеджер сам обрезает до MAX_CONTEXT_MESSAGES.
            return # Выходим, если решили не отвечать


        # --- Скачивание Медиа (если есть и релевантно) ---
        media_bytes = None
        mime_type = None
        if media_obj and media_type in ("image", "video", "audio"):
            logger.info("Attempting to download media (Type: %s, ID: %s) from %s...", media_type, getattr(media_obj, 'file_id', 'N/A'), username)
            try:
                media_bytes, mime_type = await download_media(media_obj, media_type)
                logger.info("Media file (ID: %s) downloaded successfully (%d bytes).", getattr(media_obj, 'file_id', 'N/A'), len(media_bytes))
            except MediaDownloadError as e:
                logger.error("Error downloading media (ID: %s) from %s: %s", getattr(media_obj, 'file_id', 'N/A'), username, e, exc_info=True)
                # Уведомляем пользователя, кроме случая случайного ответа
                if trigger not in ["random_group_message"]:
                    try:
                        await context.bot.send_message(
                            chat_id,
                            f"(Извини, не смог скачать твой медиафайл ({media_type}). Попробую ответить только на текст, если он был.)",
                            reply_to_message_id=message_id
                        )
                    except Exception as send_err:
                         logger.error("Failed to send media download error message: %s", send_err)
                media_bytes, mime_type = None, None # Сбрасываем, чтобы не передавать в API


        # --- Генерируем ответ с помощью Gemini API ---
        logger.info("Generating response for message ID %d from %s (Trigger: %s, Media: %s)...",
                    message_id, username, trigger, media_type or 'none')

        # Получаем актуальный контекст диалога из менеджера
        context_messages_list = chat_context_manager.get(chat_id)
        # Важно: Теперь передаем список сообщений в build_prompt
        text_prompt_part_str = build_prompt(
            chat_id,
            context_messages_list, # Передаем список сообщений
            message, # Передаем целевое сообщение
            trigger,
            media_type if media_bytes else None, # Передаем тип медиа только если оно скачано (как было в bot_4_02)
            media_bytes # Передаем bytes (не используются в сборке строки, но сигнатура build_prompt ожидает)
        )

        # Используем GeminiService из context.bot_data
        gemini_service: GeminiService = context.bot_data["gemini"]
        # Передаем список сообщений в generate_response
        response_text = await gemini_service.generate_response(
            chat_id=chat_id,
            messages=context_messages_list, # Передаем список сообщений в сервис
            target_message=message,
            trigger=trigger,
            media_type=media_type if media_bytes else None, # Передаем тип медиа только если оно скачано
            media_bytes=media_bytes,
            mime_type=mime_type,
        )

        # --- Отправляем текстовой ответ ---
        final_text = filter_technical_info(response_text.strip()) or "..." # Фильтруем и проверяем на пустоту
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=final_text,
            reply_to_message_id=message_id, # Отвечаем на исходное сообщение
        )
        logger.info("Response sent successfully (New message ID: %d) to chat %d.", sent.message_id, chat_id)

        # --- Сохраняем ответ бота в контекст ---
        chat_context_manager.add(
            chat_id,
            {
                "user": "Бот",
                "text": final_text,
                "from_bot": True,
                "message_id": sent.message_id,
            },
        )
        # Менеджер сам обрежет контекст до MAX_CONTEXT_MESSAGES

    except Exception:
        logger.exception("Unhandled exception in handle_message for update %s", update)
        # Общий обработчик ошибок на уровне Application должен поймать это и уведомить пользователя


# --- В будущем здесь могут быть другие хэндлеры ---

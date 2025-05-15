# ai_lu_bot/handlers/message.py

import logging
import random

from telegram import Update, ReplyKeyboardMarkup, Voice, VideoNote, PhotoSize, Message # Импортируем Message
from telegram.constants import ChatType # Импортируем ChatType из constants
from telegram.ext import ContextTypes

from ai_lu_bot.services.gemini import GeminiService
from ai_lu_bot.utils.media import download_media, MediaDownloadError
from ai_lu_bot.core.context import chat_context_manager # MAX_CONTEXT_MESSAGES уже 30 здесь
from ai_lu_bot.utils.text_utils import filter_technical_info
from ai_lu_bot.core.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


# --- Перенесенная функция start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение и кнопки."""
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU – цифровая копия Николая Лу. Могу поболтать о всяком, высказать свое 'ценное' мнение или просто поиронизировать над бытием. Спрашивай или предлагай тему.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# --- Основной Обработчик Сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает входящие сообщения, решает, отвечать ли, и генерирует ответ."""
    try:
        message = update.message
        if not message:
            logger.warning("Received update without message object.")
            return

        chat_id = update.effective_chat.id
        message_id = message.message_id
        chat_type = update.effective_chat.type

        # --- Определяем отправителя ---
        username = "Неизвестный"
        is_creator = False
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
             username = f"Чат '{message.sender_chat.title}'"
        elif message.forward_from_chat:
            username = f"Переслано из канала '{message.forward_from_chat.title}'"


        media_type = None
        media_obj = None
        text = ""

        # --- Определяем тип контента и исходный текст ---
        if message.photo:
            media_type = "image"
            media_obj = message.photo[-1]
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

        # --- Записываем в контекст ---
        context_entry_text = text
        if not context_entry_text and media_type:
            context_entry_text = f"[{media_type.capitalize()}]"
            if media_type == "image" and message.photo and len(message.photo) > 1:
                context_entry_text = "[Изображения]"
        elif message.forward_from_chat or message.sender_chat:
             if not context_entry_text:
                  context_entry_text = "[Пост без текста]"

        chat_context_manager.add(
            chat_id,
            {
                "user": username,
                "text": context_entry_text,
                "from_bot": False,
                "message_id": message_id,
            },
        )

        # --- Решаем, отвечать ли (включая игнор комментариев от имени канала) ---
        should_respond = False
        trigger = None

        is_reply_to_message = message.reply_to_message is not None
        is_reply_to_bot = is_reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id

        # *** ЛОГИКА ИГНОРИРОВАНИЯ КОММЕНТАРИЕВ ОТ ИМЕНИ КАНАЛА ***
        if is_reply_to_message and sender_is_chat and not sender_is_user:
             logger.info("Ignoring message %d from '%s': Identified as a comment sent as channel.", message_id, username)
             should_respond = False
             chat_context_manager.remove_last(chat_id) # Удаляем из контекста, т.к. не отвечаем
             return
        # ******************************************************

        # Логика принятия решения об ответе на НЕ игнорируемые сообщения:

        if chat_type == ChatType.PRIVATE:
            should_respond, trigger = True, "dm"
            logger.info("Trigger: Private message from %s.", username)

        elif chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if is_reply_to_bot:
                should_respond, trigger = True, "reply_to_bot"
                logger.info("Trigger: Reply to bot in group from %s.", username)
            elif is_creator:
                 should_respond, trigger = True, "creator_message"
                 logger.info("Trigger: Message from Creator (%s) in group.", username)

            is_forwarded_channel_post = message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL
            is_sent_as_channel_post_in_group = sender_is_chat and chat_type != ChatType.PRIVATE and not is_reply_to_message

            if (is_forwarded_channel_post or is_sent_as_channel_post_in_group):
                 if media_type is not None or (text and len(text.split()) >= 5):
                     should_respond, trigger = True, "channel_post_forwarded_or_sent_as"
                     logger.info("Trigger: Channel post (forwarded or sent as channel) from %s (with media or text >= 5 words).", username)
                 else:
                     logger.info("Skipping response: Short text-only channel post (forwarded or sent as channel) from %s.", username)

            elif not is_reply_to_message and not is_creator and not is_forwarded_channel_post and not is_sent_as_channel_post_in_group:
                is_short_text_only = media_type == "text" and (not text or len(text.split()) < 3)
                if not is_short_text_only and random.random() < 0.05:
                    should_respond = True
                    trigger = "random_group_message"
                    logger.info("Trigger: Random response (5%% chance) for message (type: %s) from %s in group.", media_type or 'text', username)
                elif is_short_text_only:
                     logger.info("Skipping response: Short text-only message from %s in group.", username)
                else:
                     logger.info("Skipping response: Random chance (5%%) not met for message from %s in group.", username)
            else:
                 logger.info("Skipping response: Message from %s in group does not match any trigger.", username)


        if not should_respond:
            logger.info("Final decision: Not responding to message ID %d from %s.", message_id, username)
            # Сообщение уже удалено из контекста, если был игнор комментария от имени канала.
            # Иначе оно остается в контексте.
            return

        logger.info("Responding to message ID %d (trigger: %s, media: %s)", message_id, trigger, media_type or 'none')


        # --- Скачивание Медиа (если есть и релевантно) ---
        media_bytes = None
        mime_type = None
        if media_obj and media_type in ("image", "video", "audio"):
            logger.info("Attempting to download media (Type: %s, ID: %s)...", media_type, getattr(media_obj, 'file_id', 'N/A'))
            try:
                media_bytes, mime_type = await download_media(media_obj, media_type)
                logger.info("Media file (ID: %s) downloaded (%d bytes).", getattr(media_obj, 'file_id', 'N/A'), len(media_bytes))
            except MediaDownloadError as e:
                logger.error("Error downloading media (ID: %s): %s", getattr(media_obj, 'file_id', 'N/A'), e, exc_info=True)
                if trigger not in ["random_group_message"]:
                    try:
                        await context.bot.send_message(
                            chat_id,
                            f"(Извини, не смог скачать твой медиафайл ({media_type}). Попробую ответить только на текст, если он был.)",
                            reply_to_message_id=message_id
                        )
                    except Exception as send_err:
                         logger.error("Failed to send media download error message: %s", send_err)
                media_bytes, mime_type = None, None


        # --- Генерируем ответ с помощью Gemini API ---
        gemini_service: GeminiService = context.bot_data["gemini"]
        context_messages_list = chat_context_manager.get(chat_id)

        # !!! ПЕРЕДАЕМ reply_to_message В generate_response !!!
        response_text = await gemini_service.generate_response(
            chat_id=chat_id,
            messages=context_messages_list,
            target_message=message,
            replied_to_message=message.reply_to_message if is_reply_to_message else None, # <-- Передаем сюда
            trigger=trigger,
            media_type=media_type if media_bytes else None,
            media_bytes=media_bytes,
            mime_type=mime_type,
        )

        # --- Отправляем текстовой ответ ---
        final_text = filter_technical_info(response_text.strip()) or "..."
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=final_text,
            reply_to_message_id=message_id,
        )
        logger.info("Response sent successfully (New message ID: %d).", sent.message_id)

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

    except Exception:
        logger.exception("Unhandled exception in handle_message for update %s", update)
        # Глобальный error handler должен поймать и уведомить пользователя.

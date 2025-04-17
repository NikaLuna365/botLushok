# ai_lu_bot/handlers/message.py

import logging
import random

from telegram import Update, ReplyKeyboardMarkup, Voice, VideoNote, PhotoSize
from telegram.ext import ContextTypes

from ai_lu_bot.services.gemini import GeminiService
from ai_lu_bot.utils.media import download_media, MediaDownloadError
from ai_lu_bot.core.context import chat_context_manager
from bot_4_02 import filter_technical_info, build_prompt  # промпт и фильтр без изменений

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start."""
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU – цифровая копия Николая Лу. Спрашивай или предлагай тему.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает входящие сообщения (текст, голос, видео, фото), скачивает медиа и вызывает Gemini."""
    try:
        message = update.message
        if not message:
            return

        chat_id = update.effective_chat.id
        message_id = message.message_id

        # --- Определяем отправителя ---
        username = "Неизвестный"
        is_creator = False
        if message.from_user:
            nick = message.from_user.username or message.from_user.first_name or ""
            if nick in ["Nik_Ly", "GroupAnonymousBot"]:
                username = "Создатель"
                is_creator = True
            else:
                username = nick

        # --- Определяем тип контента и исходный текст ---
        media_type = None
        media_obj = None
        text = ""

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

        logger.info("Получено от %s (%s): %s", username, media_type or "text", text[:50])

        # --- Записываем в контекст ---
        entry_text = text or (f"[{media_type}]" if media_type else "")
        chat_context_manager.add(
            chat_id,
            {
                "user": username,
                "text": entry_text,
                "from_bot": False,
                "message_id": message_id,
            },
        )

        # --- Решаем, отвечать ли ---
        should_respond = False
        trigger = None

        # Личное сообщение → всегда отвечаем
        if update.effective_chat.type == "private":
            should_respond, trigger = True, "dm"
        else:
            # Ответ боту или сообщение от создателя
            if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id:
                should_respond, trigger = True, "reply"
            elif is_creator:
                should_respond, trigger = True, "creator"
            else:
                # Посты из каналов
                is_channel_post = (message.forward_from_chat or message.sender_chat) is not None
                if is_channel_post and (media_type is not None or len(text.split()) >= 5):
                    should_respond, trigger = True, "channel_post"
                else:
                    # Слишком короткое текстовое сообщение
                    if text and len(text.split()) < 3:
                        should_respond = False
                    # Случайный 5% ответ в группах
                    elif random.random() < 0.05:
                        should_respond, trigger = True, "random_group"

        if not should_respond:
            logger.info("Пропускаем сообщение %d от %s", message_id, username)
            chat_context_manager.remove_last(chat_id)
            return

        logger.info("Отвечаем на %d (триггер: %s)", message_id, trigger)

        # --- Скачиваем медиа (для image, video, audio) ---
        media_bytes = None
        mime_type = None
        if media_obj and media_type in ("image", "video", "audio"):
            try:
                media_bytes, mime_type = await download_media(media_obj, media_type)
            except MediaDownloadError as e:
                logger.error("Ошибка скачивания медиа %s: %s", media_type, e)
                if trigger != "random_group":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"({username}, извини, не смог скачать твой {media_type}).",
                        reply_to_message_id=message_id,
                    )
                media_bytes, mime_type = None, None

        # --- Генерируем ответ через GeminiService, передавая аудио bytes напрямую ---
        gemini: GeminiService = context.bot_data["gemini"]
        response_text = await gemini.generate_response(
            chat_id=chat_id,
            target_message=message,
            trigger=trigger,
            media_type=media_type,
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
        logger.info("Ответ отправлен (ID %d)", sent.message_id)

        # --- Сохраняем ответ в контекст ---
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
        logger.exception("Unhandled exception in handle_message")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Извини, произошла ошибка при обработке твоего сообщения.",
            )
        except Exception:
            pass

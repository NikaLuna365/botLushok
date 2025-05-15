# ai_lu_bot/handlers/message.py

import logging
import random

from telegram import Update, ReplyKeyboardMarkup, Voice, VideoNote, PhotoSize, Message
from telegram.constants import ChatType
from telegram.ext import ContextTypes

# Импортируем сервисы и утилиты
from ai_lu_bot.services.gemini import GeminiService
from ai_lu_bot.utils.media import download_media, MediaDownloadError
# Удаляем импорт глобального менеджера контекста
# from ai_lu_bot.core.context import chat_context_manager, MAX_CONTEXT_MESSAGES # УДАЛИТЬ или закомментировать
# Импортируем только классы менеджеров и константу MAX_CONTEXT_MESSAGES для тайп-хинтинга и использования константы
from ai_lu_bot.core.context import InMemoryChatContextManager, RedisChatContextManager, MAX_CONTEXT_MESSAGES

from ai_lu_bot.utils.text_utils import filter_technical_info
from ai_lu_bot.core.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


# --- Функция start для команды /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение и кнопки при команде /start."""
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU – цифровая копия Николая Лу. Могу поболтать о всяком, высказать свое 'ценное' мнение или просто поиронизировать над бытием. Спрашивай или предлагай тему.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    logger.info("Sent /start message to chat %s", update.effective_chat.id)


# --- Основной Обработчик Сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает входящие сообщения (текст, голос, видео, фото).
    Получает менеджер контекста и GeminiService из context.bot_data.
    """
    message = update.message
    if not message:
        logger.warning("Received an update without a message object. Skipping.")
        return

    # --- Получаем инстансы сервисов и менеджера из bot_data ---
    # Убедимся, что ключи существуют перед доступом
    gemini_service: GeminiService = context.bot_data.get("gemini_service")
    chat_context_manager_instance: Union[InMemoryChatContextManager, RedisChatContextManager, None] = context.bot_data.get("chat_context_manager")

    if not gemini_service:
         logger.critical("GeminiService not found in context.bot_data!")
         # Можно попытаться уведомить пользователя или просто залогировать и выйти
         if update.effective_chat:
             try: await update.effective_chat.send_message("Произошла внутренняя ошибка сервиса (Gemini недоступен).")
             except Exception: pass
         return

    if not chat_context_manager_instance:
         logger.critical("ChatContextManager not found in context.bot_data!")
         if update.effective_chat:
             try: await update.effective_chat.send_message("Произошла внутренняя ошибка сервиса (контекст недоступен).")
             except Exception: pass
         return
    # ----------------------------------------------------------


    chat_id = update.effective_chat.id
    message_id = message.message_id
    chat_type = update.effective_chat.type


    # --- Определяем отправителя сообщения ---
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

    # --- Определяем тип контента и извлекаем текст/подпись ---
    if message.photo:
        media_type = "image"
        media_obj = message.photo[-1]
        text = (message.caption or "").strip()
    elif message.video_note:
        media_type = "video"
        media_obj = message.video_note
        text = (message.caption or "").strip()
    elif message.voice:
        media_type = "audio"
        media_obj = message.voice
        text = (message.caption or "").strip()
    else:
        text = (message.text or message.caption or "").strip()

    log_text_preview = text[:50] + "..." if len(text) > 50 else text
    log_media_info = f", media_type: {media_type}" if media_type else ""
    logger.info("Received message %d from %s (user_id: %s, chat_id: %s%s): '%s'",
                message_id, username, message.from_user.id if message.from_user else 'N/A', chat_id, log_media_info, log_text_preview)


    # --- Записываем в контекст диалога (используем полученный менеджер) ---
    context_entry_text = text
    if not context_entry_text and media_type:
        context_entry_text = f"[{media_type.capitalize()}]"
        if media_type == "image" and message.photo and len(message.photo) > 1:
            context_entry_text = "[Изображения]"
    elif message.forward_from_chat or message.sender_chat:
         if not context_entry_text:
              context_entry_text = "[Post without text]" # Use English consistently? Or stick to Russian
              # Let's stick to Russian as in prompt builder
              context_entry_text = "[Пост без текста]"


    chat_context_manager_instance.add( # <-- Используем инстанс из bot_data
        chat_id,
        {
            "user": username,
            "text": context_entry_text,
            "from_bot": False,
            "message_id": message_id,
        },
    )
    # Менеджер сам следит за MAX_CONTEXT_MESSAGES (сейчас 30)


    # --- Логика принятия решения об ответе ---
    should_respond = False
    trigger = None

    is_reply_to_message = message.reply_to_message is not None
    is_reply_to_bot = is_reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id

    # *** ЛОГИКА ИГНОРИРОВАНИЯ КОММЕНТАРИЕВ ОТ ИМЕНИ КАНАЛА ***
    if is_reply_to_message and sender_is_chat and not sender_is_user:
         logger.info("Ignoring message %d from '%s': Identified as a comment sent as channel in group.", message_id, username)
         should_respond = False
         chat_context_manager_instance.remove_last(chat_id) # <-- Используем инстанс из bot_data
         return
    # ******************************************************

    # Логика для принятия решения об ответе на НЕ игнорируемые сообщения:

    if chat_type == ChatType.PRIVATE:
        should_respond, trigger = True, "dm"
        logger.info("Trigger: Private message from %s.", username)

    elif chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if is_reply_to_bot:
            should_respond, trigger = True, "reply_to_bot"
            logger.info("Trigger: Reply to bot in group from %s.", username)
        elif is_creator and sender_is_user: # Проверка is_creator для USER
             should_respond, trigger = True, "creator_message_user"
             logger.info("Trigger: Message from Creator (%s) (as User) in group.", username)

        is_forwarded_channel_post = message.forward_from_chat is not None and message.forward_from_chat.type == ChatType.CHANNEL
        is_sent_as_channel_post_in_group = sender_is_chat and chat_type != ChatType.PRIVATE # Отправлено от имени чата в группе/супергруппе

        if (is_forwarded_channel_post or is_sent_as_channel_post_in_group):
             if media_type is not None or (text and len(text.split()) >= 5):
                 should_respond, trigger = True, "channel_post_forwarded_or_sent_as"
                 logger.info("Trigger: Channel post (forwarded or sent as channel) from %s (with media or text >= 5 words) in group.", username)
             else:
                 logger.info("Skipping response: Short text-only channel post (forwarded or sent as channel) from %s.", username)

        elif not is_reply_to_message and not is_creator and not is_forwarded_channel_post and not is_sent_as_channel_post_in_group:
            is_short_text_only = media_type == "text" and (not text or len(text.split()) < 3)
            if not is_short_text_only:
                 if random.random() < 0.05:
                     should_respond = True
                     trigger = "random_group_message"
                     logger.info("Trigger: Random response (5%% chance) for message (type: %s) from %s in group.", media_type or 'text', username)
                 else:
                     logger.info("Skipping response: Random chance (5%%) not met for message from %s in group.", username)
            else:
                 logger.info("Skipping response: Too short text-only message from %s in group.", username)
        else:
             logger.info("Skipping response: Message from %s in group does not match any specific trigger.", username)


    if not should_respond:
        logger.info("Final decision: Not responding to message ID %d from %s.", message_id, username)
        return

    logger.info("Proceeding to generate response for message ID %d (trigger: %s, media: %s)", message_id, trigger, media_type or 'none')


    # --- Скачивание Медиа ---
    media_bytes = None
    mime_type = None
    if media_obj and media_type in ("image", "video", "audio"):
        logger.info("Attempting to download media (Type: %s, ID: %s)...", media_type, getattr(media_obj, 'file_id', 'N/A'))
        try:
            media_bytes, mime_type = await download_media(media_obj, media_type)
            logger.info("Media file (ID: %s) downloaded successfully (%d bytes).", getattr(media_obj, 'file_id', 'N/A'), len(media_bytes))
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
    # Получаем актуальный контекст диалога из менеджера (используем полученный инстанс)
    context_messages_list = chat_context_manager_instance.get(chat_id) # <-- Используем инстанс из bot_data

    logger.debug("Calling GeminiService.generate_response...")
    response_text = await gemini_service.generate_response( # <-- Используем инстанс из bot_data
        chat_id=chat_id,
        messages=context_messages_list,
        target_message=message,
        trigger=trigger,
        replied_to_message=message.reply_to_message if is_reply_to_message else None,
        media_type=media_type if media_bytes else None, # Передаем тип медиа ТОЛЬКО если скачано
        media_bytes=media_bytes,
        mime_type=mime_type,
    )
    logger.debug("Received response_text from GeminiService.")


    # --- Отправляем текстовой ответ в Telegram ---
    final_text = filter_technical_info(response_text.strip()) or "..."
    logger.info("Sending response to chat %d (replying to msg ID %d)...", chat_id, message_id)
    try:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=final_text,
            reply_to_message_id=message_id,
        )
        logger.info("Response sent successfully. New message ID: %d.", sent.message_id)

        # --- Сохраняем ответ бота в контекст диалога (используем полученный менеджер) ---
        chat_context_manager_instance.add( # <-- Используем инстанс из bot_data
            chat_id,
            {
                "user": "Бот",
                "text": final_text,
                "from_bot": True,
                "message_id": sent.message_id,
            },
        )

    except Exception as send_err:
        logger.error("Error sending response message to chat %d: %s", chat_id, str(send_err), exc_info=True)


    except Exception:
        logger.exception("An unexpected error occurred in handle_message for update %s", update)
        # Глобальный error handler в app.py должен поймать это и уведомить пользователя.

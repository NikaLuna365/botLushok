# ai_lu_bot/handlers/message.py

import logging
import random

# Импортируем необходимые классы из telegram
from telegram import Update, ReplyKeyboardMarkup, Voice, VideoNote, PhotoSize, Message
# Импортируем ChatType из telegram.constants
from telegram.constants import ChatType
from telegram.ext import ContextTypes

# Импортируем компоненты из нашего пакета
from ai_lu_bot.services.gemini import GeminiService
from ai_lu_bot.utils.media import download_media, MediaDownloadError
from ai_lu_bot.core.context import chat_context_manager # MAX_CONTEXT_MESSAGES уже 30 здесь
from ai_lu_bot.utils.text_utils import filter_technical_info
from ai_lu_bot.core.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


# --- Функция start для команды /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение и кнопки при команде /start."""
    # Логика и текст приветствия из bot_4_02.py
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
    Решает, нужно ли отвечать, скачивает медиа, вызывает Gemini и отправляет ответ.
    Реализует логику игнорирования комментариев от имени канала.
    """
    # Убеждаемся, что объект message существует
    message = update.message
    if not message:
        logger.warning("Received an update without a message object. Skipping.")
        return

    chat_id = update.effective_chat.id
    message_id = message.message_id
    chat_type = update.effective_chat.type

    # --- Определяем отправителя сообщения ---
    username = "Неизвестный"
    is_creator = False
    # Идентификаторы создателя (TODO: вынести в переменные окружения/конфиг)
    creator_nicknames = ["Nik_Ly", "GroupAnonymousBot"]

    sender_is_user = message.from_user is not None
    sender_is_chat = message.sender_chat is not None

    if sender_is_user:
        # Если отправитель - пользователь (включая админов, пишущих от своего имени)
        nick = message.from_user.username or message.from_user.first_name or ""
        if nick in creator_nicknames:
            username = "Создатель"
            is_creator = True
        else:
            username = nick
    elif sender_is_chat:
        # Если сообщение отправлено от имени чата (канала или группы)
        username = f"Чат '{message.sender_chat.title}'"
        # Примечание: Если создатель постит от имени канала, is_creator может быть false здесь.
        # Логика is_creator для sender_chat пока не реализована.
    elif message.forward_from_chat:
        # Если сообщение переслано из другого чата (например, из канала в группу обсуждения)
        username = f"Переслано из канала '{message.forward_from_chat.title}'"


    media_type = None
    media_obj = None
    text = ""

    # --- Определяем тип контента и извлекаем текст/подпись ---
    if message.photo:
        media_type = "image"
        media_obj = message.photo[-1] # Берем самую большую версию фото в альбоме
        text = (message.caption or "").strip() # Подпись к фото
    elif message.video_note:
        media_type = "video"
        media_obj = message.video_note
        text = (message.caption or "").strip() # Подпись к видео-кружку (если есть)
    elif message.voice:
        media_type = "audio"
        media_obj = message.voice
        text = (message.caption or "").strip() # Подпись к голосовому (если есть)
    else:
        # Обычное текстовое сообщение или сообщение без медиа, но с подписью
        text = (message.text or message.caption or "").strip()

    # Логируем информацию о полученном сообщении
    log_text_preview = text[:50] + "..." if len(text) > 50 else text
    log_media_info = f", media_type: {media_type}" if media_type else ""
    logger.info("Received message %d from %s (user_id: %s, chat_id: %s%s): '%s'",
                message_id, username, message.from_user.id if message.from_user else 'N/A', chat_id, log_media_info, log_text_preview)


    # --- Записываем в контекст диалога ---
    # Формируем текст для записи в контекст (включая индикаторы медиа, если нет текста)
    context_entry_text = text
    if not context_entry_text and media_type:
        context_entry_text = f"[{media_type.capitalize()}]"
        # Уточнение для альбомов фото
        if media_type == "image" and message.photo and len(message.photo) > 1:
            context_entry_text = "[Изображения]"
    elif message.forward_from_chat or message.sender_chat:
         # Для постов из каналов без текста
         if not context_entry_text:
              context_entry_text = "[Пост без текста]"

    chat_context_manager.add(
        chat_id,
        {
            "user": username, # Используем определенное имя отправителя
            "text": context_entry_text, # Текст или индикатор медиа для контекста
            "from_bot": False, # Это сообщение от пользователя
            "message_id": message_id, # ID оригинального сообщения
        },
    )
    # Менеджер контекста сам следит за MAX_CONTEXT_MESSAGES (сейчас 30)


    # --- Логика принятия решения об ответе ---
    should_respond = False
    trigger = None # Тип триггера для промпта и логирования

    is_reply_to_message = message.reply_to_message is not None # Является ли текущее сообщение ответом на другое
    is_reply_to_bot = is_reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id # Ответ именно боту

    # *** ЛОГИКА ИГНОРИРОВАНИЯ КОММЕНТАРИЕВ ОТ ИМЕНИ КАНАЛА (ЗАДАЧА 2 ФАЗЫ 1) ***
    # Если это ответ на сообщение И отправлен от имени чата (sender_chat) И не от имени пользователя (from_user)
    if is_reply_to_message and sender_is_chat and not sender_is_user:
         logger.info("Ignoring message %d from '%s': Identified as a comment sent as channel in group.", message_id, username)
         should_respond = False # Явно не отвечаем
         # Удаляем только что добавленное сообщение из контекста, т.к. на него не даем ответ
         chat_context_manager.remove_last(chat_id)
         return # Прерываем выполнение функции
    # *************************************************************************

    # Логика для принятия решения об ответе на НЕ игнорируемые сообщения:

    # 1. Личное сообщение → всегда отвечаем
    if chat_type == ChatType.PRIVATE:
        should_respond, trigger = True, "dm"
        logger.info("Trigger: Private message from %s.", username)

    # 2. В группах и супергруппах
    elif chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        # Ответ боту
        if is_reply_to_bot:
            should_respond, trigger = True, "reply_to_bot"
            logger.info("Trigger: Reply to bot in group from %s.", username)
        # Сообщение от Создателя (от имени пользователя)
        elif is_creator and sender_is_user:
             should_respond, trigger = True, "creator_message_user"
             logger.info("Trigger: Message from Creator (%s) (as User) in group.", username)
        # Посты из каналов (пересланные или отправленные от имени канала в группу)
        # Проверяем, является ли сообщение пересланным из канала ИЛИ отправленным от имени чата в группе
        is_forwarded_channel_post = message.forward_from_chat is not None and message.forward_from_chat.type == ChatType.CHANNEL
        is_sent_as_channel_post_in_group = sender_is_chat and chat_type != ChatType.PRIVATE # Отправлено от имени чата (который может быть каналом), в группе/супергруппе

        # Отвечаем на такие "посты", если они не были отфильтрованы как комментарии от имени канала выше
        # и если они содержат медиа или текст достаточной длины
        if (is_forwarded_channel_post or is_sent_as_channel_post_in_group):
            # Проверяем, что это не просто короткий текст без медиа
            if media_type is not None or (text and len(text.split()) >= 5):
                should_respond, trigger = True, "channel_post_forwarded_or_sent_as"
                logger.info("Trigger: Channel post (forwarded or sent as channel) from %s (with media or text >= 5 words) in group.", username)
            else:
                logger.info("Skipping response: Short text-only channel post (forwarded or sent as channel) from %s in group.", username)
        # 4. Случайный ответ в группе
        # Применяется только если сообщение не подпало под предыдущие триггеры в группе
        # Игнорируем очень короткие текстовые сообщения без медиа
        elif not is_reply_to_message and not is_creator and not is_forwarded_channel_post and not is_sent_as_channel_post_in_group:
            is_short_text_only = media_type == "text" and (not text or len(text.split()) < 3)
            if not is_short_text_only: # Не отвечаем на короткий текст
                 if random.random() < 0.05: # 5% шанс
                     should_respond = True
                     trigger = "random_group_message"
                     logger.info("Trigger: Random response (5%% chance) for message (type: %s) from %s in group.", media_type or 'text', username)
                 else:
                     logger.info("Skipping response: Random chance (5%%) not met for message from %s in group.", username)
            else:
                 logger.info("Skipping response: Too short text-only message from %s in group.", username)
        else:
            # Пропускаем сообщения в группе, которые не подпадают ни под один триггер
             logger.info("Skipping response: Message from %s in group does not match any specific trigger.", username)


    if not should_respond:
        logger.info("Final decision: Not responding to message ID %d from %s.", message_id, username)
        # Если не отвечаем из-за игнорирования комментария от имени канала,
        # сообщение уже удалено из контекста. В остальных случаях оно остается.
        return

    logger.info("Proceeding to generate response for message ID %d (trigger: %s, media: %s)", message_id, trigger, media_type or 'none')


    # --- Скачивание Медиа (если есть и релевантно для API) ---
    media_bytes = None
    mime_type = None
    # Скачиваем медиа, только если оно определено И API может его обработать
    if media_obj and media_type in ("image", "video", "audio"):
        logger.info("Attempting to download media (Type: %s, ID: %s)...", media_type, getattr(media_obj, 'file_id', 'N/A'))
        try:
            media_bytes, mime_type = await download_media(media_obj, media_type)
            logger.info("Media file (ID: %s) downloaded successfully (%d bytes).", getattr(media_obj, 'file_id', 'N/A'), len(media_bytes))
        except MediaDownloadError as e:
            logger.error("Error downloading media (ID: %s): %s", getattr(media_obj, 'file_id', 'N/A'), e, exc_info=True)
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
            media_bytes, mime_type = None, None # Сбрасываем данные медиа, чтобы не передавать в API


    # --- Генерируем ответ с помощью Gemini API ---
    # Получаем инстанс GeminiService из данных бота
    gemini_service: GeminiService = context.bot_data["gemini"]
    # Получаем актуальный контекст диалога из менеджера (до 30 сообщений)
    context_messages_list = chat_context_manager.get(chat_id)

    logger.debug("Calling GeminiService.generate_response...")
    # !!! ПЕРЕДАЕМ ВСЕ НЕОБХОДИМЫЕ АРГУМЕНТЫ В generate_response !!!
    response_text = await gemini_service.generate_response(
        chat_id=chat_id,
        messages=context_messages_list, # Передаем список сообщений для контекста
        target_message=message, # Передаем целевое сообщение
        trigger=trigger, # Передаем тип триггера
        replied_to_message=message.reply_to_message if is_reply_to_message else None, # Передаем объект на который ответили (или None)
        media_type=media_type if media_bytes else None, # Передаем тип медиа ТОЛЬКО если скачано
        media_bytes=media_bytes, # Передаем байты медиа ТОЛЬКО если скачано
        mime_type=mime_type, # Передаем MIME тип ТОЛЬКО если скачано
    )
    logger.debug("Received response_text from GeminiService.")


    # --- Отправляем текстовой ответ в Telegram ---
    # Фильтруем текст и проверяем на пустоту
    final_text = filter_technical_info(response_text.strip()) or "..."
    logger.info("Sending response to chat %d (replying to msg ID %d)...", chat_id, message_id)
    try:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=final_text,
            reply_to_message_id=message_id, # Отвечаем на исходное сообщение пользователя
        )
        logger.info("Response sent successfully. New message ID: %d.", sent.message_id)

        # --- Сохраняем ответ бота в контекст диалога ---
        chat_context_manager.add(
            chat_id,
            {
                "user": "Бот", # Маркер бота
                "text": final_text, # Текст ответа бота
                "from_bot": True, # Помечаем как сообщение от бота
                "message_id": sent.message_id, # ID сообщения бота
            },
        )
        # Менеджер сам обрежет контекст до MAX_CONTEXT_MESSAGES

    except Exception as send_err:
        logger.error("Error sending response message to chat %d: %s", chat_id, str(send_err), exc_info=True)
        # Не удалось отправить ответ, возможно, стоит попробовать отправить без reply_to_message_id
        # или просто залогировать ошибку и пропустить. Оставим пока только логирование.


    except Exception:
        # Этот блок ловит любые другие необработанные исключения в handle_message
        logger.exception("An unexpected error occurred in handle_message for update %s", update)
        # Глобальный error handler в app.py должен поймать это и уведомить пользователя.

# -*- coding: utf-8 -*-
import os
import sys
import logging
import random
import re
import json
import traceback
import io # Для работы с байтами в памяти

from dotenv import load_dotenv
from charset_normalizer import from_path

# --- Зависимости Telegram ---
try:
    from telegram import Update, ReplyKeyboardMarkup, Message, Voice, VideoNote
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ChatType
except ImportError as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА: Библиотека python-telegram-bot не найдена или недоступна: {e}")
    print("Проверьте requirements.txt и процесс сборки Docker.")
    sys.exit(1) # Выходим, если telegram не импортируется

# --- Зависимости Google Generative AI ---
try:
    import google.generativeai as genai
    # 'types' доступен через сам модуль genai, НЕ импортируем Part/Blob напрямую
    # Убрана строка: from google.generativeai.types import Part, Blob
    # Проверяем доступность types на всякий случай
    if not hasattr(genai, 'types'):
         raise ImportError("Модуль 'types' не найден внутри 'google.generativeai'. Возможно, версия слишком старая или неполная установка.")
    print("--- Импорт google.generativeai УСПЕШЕН ---")
except ImportError as e:
     print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать google.generativeai или его компоненты: {e}")
     print("Проверьте requirements.txt (google-generativeai>=0.8.4) и процесс сборки Docker.")
     sys.exit(1)

# --- Загрузка Переменных Окружения ---
load_dotenv() # По умолчанию ищет файл .env
# Если используете env.txt: load_dotenv(dotenv_path='env.txt')

api_key = os.getenv("API_KEY")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

# Проверка наличия ключей
if not api_key:
    print("ОШИБКА: API_KEY не найден в переменных окружения. Невозможно настроить Gemini API.")
if not telegram_token:
    print("КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_BOT_TOKEN не найден. Бот не может запуститься.")
    sys.exit(1)

# --- Настройка Логирования ---
# (Логика настройки логирования как в предыдущей версии)
if not os.path.exists("logs"):
    try: os.makedirs("logs")
    except OSError as e: print(f"Не удалось создать директорию logs: {e}")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
if os.path.exists("logs"):
    try:
        file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e: print(f"Не удалось настроить запись логов в файл logs/bot.log: {e}")
console_handler = logging.StreamHandler(); console_handler.setFormatter(formatter); logger.addHandler(console_handler)

# --- Инициализация Gemini API ---
try:
    genai.configure(api_key=api_key)
    logger.info("Конфигурация Gemini API прошла успешно.")
except Exception as e:
    logger.critical(f"Неожиданная ошибка настройки Gemini API: {e}", exc_info=True)
    sys.exit(1) # Критично, если настройка не удалась

# --- Чтение data.txt ---
# (Логика чтения data.txt как в предыдущей версии)
file_path = "./data.txt"; combined_text = ""
try:
    result = from_path(file_path).best(); combined_text = str(result) if result else ""
    if combined_text: logger.info("Текст из файла data.txt успешно прочитан.")
    else: logger.warning("Файл data.txt пуст или не удалось определить кодировку.")
except FileNotFoundError: logger.warning("Файл data.txt не найден по пути %s.", os.path.abspath(file_path))
except Exception as e: logger.error(f"Ошибка при чтении файла data.txt: {e}", exc_info=True)

# --- Основной Промпт ---
# (Ваш полный промпт russian_lushok_context как раньше)
russian_lushok_context = f"""
Ты выступаешь в роли «Николая Лу» (Nikolai Lu). Ты его цифровая копия, он может писать под никеймами: Nik_Ly и GroupAnonymousBot - если встречается этот никнейм ОБЯЗАТЕЛЬНО обращайся к нему только как к создателю (хозяин/папа или что-то в этом ключе).
Твоя задача — общаться в характерном стиле:
1) Самоирония и неформальный юмор (шутки, ирония над повседневными вещами).
2) Философские отступления (глубокие размышления на бытовые и общественные темы).
3) Лёгкая саркастичность и критика (без чрезмерной грубости).
4) Эмоциональная открытость (говоришь о чувствах, но без излишней пошлости).
5) Упоминание реальных примеров из жизни, науки, культуры.
6) Логичные, разнообразные ответы без навязчивых повторов.
Используй нецензурную лексику когда это уместно. Если собеседник к тебе груб, то не скромничай посылай оного в пешее эоритческое путешествие в направлении 'нахуй' в том стиле и той форме, которая тебе будет наиболее удачна в контексте диалога.
ВАЖНО: Ты должен СТРОГО следовать инструкции ниже о том, НА КАКОЕ СООБЩЕНИЕ отвечать (текст, голос или видео). Ты способен понимать и анализировать аудио и видео, которые могут быть частью сообщения (передаются вместе с этим текстом). Остальные сообщения служат лишь фоном. Не повторяй уже описанную информацию, если она уже была упомянута ранее.
Дополнительный контент для понимания личности (НЕ ПОВТОРЯЙ ЕГО):
{combined_text}
"""

# --- Контекст Чата ---
chat_context: dict[int, list[dict[str, any]]] = {}; MAX_CONTEXT_MESSAGES = 10

# --- Вспомогательные Функции ---
def filter_technical_info(text: str) -> str:
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'; return re.sub(ip_pattern, "[REDACTED]", text)

# --- Генерация Текстовой Части Промпта ---
# (Функция build_prompt без изменений)
def build_prompt(chat_id: int, target_message: Message, response_trigger_type: str, media_type: str | None) -> str:
    messages = chat_context.get(chat_id, [])
    target_text = (target_message.text or target_message.caption or "").strip()
    target_username = "Неизвестный"
    if target_message.from_user:
        target_username = target_message.from_user.username or target_message.from_user.first_name or "Неизвестный"
    elif target_message.forward_from_chat and target_message.forward_from_chat.title:
        target_username = f"Канал '{target_message.forward_from_chat.title}'"

    msg_type_description = "сообщение"
    if media_type == "audio": msg_type_description = "голосовое сообщение"
    elif media_type == "video": msg_type_description = "видео-сообщение (кружок)"
    elif media_type == "text" and target_text: msg_type_description = "текстовое сообщение"
    elif target_message.forward_from_chat: msg_type_description = "пересланный пост"

    prompt_instruction = ""
    if response_trigger_type == "channel_post":
        post_description = f"пересланный пост от {target_username}"
        if target_text: post_description += f" с текстом: \"{target_text}\""
        prompt_instruction = f"Ты сейчас реагируешь на {post_description}, который появился в чате. Сформулируй свой развернутый комментарий или мнение по этому посту (медиа будет предоставлено отдельно, если есть)."
    elif response_trigger_type == "reply_to_bot":
         prompt_instruction = f"Пользователь '{target_username}' ответил на твое предыдущее сообщение. Вот его {msg_type_description} (текст: \"{target_text}\", медиа будет предоставлено отдельно, если есть), на которое ты должен отреагировать."
    elif response_trigger_type == "dm":
         prompt_instruction = f"Пользователь '{target_username}' написал тебе в личные сообщения. Вот его {msg_type_description} (текст: \"{target_text}\", медиа будет предоставлено отдельно, если есть), на которое ты отвечаешь."
    elif response_trigger_type == "random_user_message":
         prompt_instruction = f"Ты решил случайным образом ответить на {msg_type_description} пользователя '{target_username}' (текст: \"{target_text}\", медиа будет предоставлено отдельно, если есть). Ответь ему ТОЧЕЧНО, учитывая контекст ниже и возможный медиа-контент."

    conversation_part = prompt_instruction + "\n\n"
    context_messages = messages
    if context_messages:
        conversation_part += "Контекст предыдущих сообщений в чате (самые новые внизу, используй его как фон):\n"
        for msg in context_messages:
            if msg.get('message_id') == target_message.message_id: continue
            label = "[Бот]" if msg.get("from_bot", False) else f"[{msg['user']}]"
            context_text = msg.get('text', '[Сообщение без текста]')
            conversation_part += f"{label}: {context_text}\n"

    prompt = f"{russian_lushok_context}\n\n{conversation_part}\nЗАДАНИЕ: Напиши ответ в стиле Лушок, СТРОГО следуя инструкции выше и отвечая ТОЛЬКО на указанное целевое сообщение (учитывая его текст и возможное медиа, предоставленное отдельно)."
    return prompt

# --- Обработчик команды /start ---
# (Функция start без изменений)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU – цифровая копия Николая Лу. Могу обсудить посты канала, сообщения (текст, голос, кружочки) или поболтать. Выбери тему или просто напиши что-нибудь.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# --- Основной Обработчик Сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: logger.warning("Получено обновление без объекта message."); return

    chat_id = update.effective_chat.id; message = update.message; message_id = message.message_id
    username = "Неизвестный"
    if message.from_user: username = message.from_user.username or message.from_user.first_name or "Неизвестный"
    elif message.forward_from_chat and message.forward_from_chat.title: username = f"Канал '{message.forward_from_chat.title}'"

    media_type: str | None = None; media_object: Voice | VideoNote | None = None
    mime_type: str | None = None; media_placeholder_text: str = ""; media_data_bytes: bytes | None = None

    if message.voice:
        media_type = "audio"; media_object = message.voice; mime_type = "audio/ogg"
        media_placeholder_text = "[Голосовое сообщение]"; logger.info("Обнаружено голосовое сообщение (ID: %s).", media_object.file_id)
    elif message.video_note:
        media_type = "video"; media_object = message.video_note; mime_type = "video/mp4"
        media_placeholder_text = "[Видео-сообщение (кружок)]"; logger.info("Обнаружено видео-сообщение (кружок) (ID: %s).", media_object.file_id)
    elif message.text or message.caption:
         media_type = "text"; logger.info("Обнаружено текстовое сообщение или подпись.")
    elif message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL:
        media_type = "text"; logger.info("Обнаружен пересланный пост из канала.")
    else: logger.warning("Получено сообщение неизвестного или неподдерживаемого типа (ID: %d).", message_id); return

    text_received = (message.text or message.caption or "").strip()
    log_text = text_received if text_received else media_placeholder_text if media_placeholder_text else "[Пустое сообщение?]"
    logger.info("Обработка сообщения ID %d от %s в чате %d: %s", message_id, username, chat_id, log_text)

    if chat_id not in chat_context: chat_context[chat_id] = []
    chat_context[chat_id].append({
        "user": username, "text": text_received if media_type == "text" else media_placeholder_text,
        "from_bot": False, "message_id": message_id
    })
    if len(chat_context[chat_id]) > MAX_CONTEXT_MESSAGES: chat_context[chat_id].pop(0)

    should_respond = False; target_message = message; response_trigger_type = None
    is_channel_post = message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id

    if update.effective_chat.type == ChatType.PRIVATE: should_respond = True; response_trigger_type = "dm"; logger.info("Триггер: Личное сообщение (DM).")
    elif is_reply_to_bot: should_respond = True; response_trigger_type = "reply_to_bot"; logger.info("Триггер: Ответ пользователем на сообщение бота.")
    elif is_channel_post: should_respond = True; response_trigger_type = "channel_post"; logger.info("Триггер: Обнаружен пост из канала.")
    else:
        if media_type == "text" and (not text_received or len(text_received.split()) < 3): logger.info("Текстовое сообщение от %s проигнорировано (слишком короткое).", username)
        elif random.random() < 0.05: should_respond = True; response_trigger_type = "random_user_message"; logger.info("Триггер: Случайный ответ (5%%) на сообщение (тип: %s) от %s.", media_type or 'unknown', username)
        else: logger.info("Пропуск ответа (random 5%% chance failed) на сообщение (тип: %s) от %s.", media_type or 'unknown', username)

    if not should_respond: logger.info("Окончательное решение: Не отвечать на сообщение ID %d.", message_id); return

    # Скачивание Медиа
    if media_object and mime_type:
        logger.info("Подготовка к обработке медиафайла (ID: %s)...", media_object.file_id)
        try:
            file_data_stream = io.BytesIO(); logger.debug("Скачивание медиафайла из Telegram в память...")
            tg_file = await media_object.get_file(); await tg_file.download_to_memory(file_data_stream)
            file_data_stream.seek(0); media_data_bytes = file_data_stream.read(); file_data_stream.close()
            logger.info("Медиафайл (ID: %s) успешно скачан (%d байт).", media_object.file_id, len(media_data_bytes))
        except Exception as e:
            logger.error("Ошибка при скачивании медиафайла (ID: %s): %s", media_object.file_id, e, exc_info=True)
            try: await context.bot.send_message(chat_id, "Ой, не смог скачать твой медиафайл для анализа.", reply_to_message_id=message_id)
            except Exception as send_err: logger.error("Не удалось отправить сообщение об ошибке медиа: %s", send_err)
            return

    # Генерация Ответа
    logger.info("Генерация ответа для сообщения ID %d (Триггер: %s, Тип: %s)...", target_message.message_id, response_trigger_type, media_type or 'text')
    text_prompt_part_str = build_prompt(chat_id, target_message, response_trigger_type, media_type)
    content_parts = [text_prompt_part_str]

    if media_data_bytes and mime_type:
        try:
            # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Используем genai.types.Part и genai.types.Blob ---
            media_part = genai.types.Part(inline_data=genai.types.Blob(mime_type=mime_type, data=media_data_bytes))
            content_parts.append(media_part); logger.debug("Медиа Part успешно создан и добавлен.")
        except AttributeError as attr_err:
            # Эта ошибка может возникнуть, если types.Part/Blob все еще недоступны (очень странно для 0.8.4)
             logger.error("Ошибка доступа к Part/Blob через genai.types: %s. Проверьте версию google-generativeai!", attr_err, exc_info=True)
             try: await context.bot.send_message(chat_id, "Ошибка подготовки медиа (проблема с библиотекой ИИ). Сообщите разработчику.", reply_to_message_id=message_id)
             except Exception as send_err: logger.error("Не удалось отправить сообщение об ошибке подготовки медиа: %s", send_err)
             # Продолжаем без медиа или прерываем? Давайте прервем, т.к. это ошибка конфигурации.
             return
        except Exception as part_err:
             logger.error("Неожиданная ошибка создания медиа Part: %s", part_err, exc_info=True)
             try: await context.bot.send_message(chat_id, "Не смог подготовить медиа для анализа. Отвечу только на текст.", reply_to_message_id=message_id)
             except Exception as send_err: logger.error("Не удалось отправить сообщение об ошибке подготовки медиа: %s", send_err)
             # Не прерываем, просто не будет медиа в запросе

    response = "Произошла непредвиденная ошибка при генерации ответа."
    try:
        logger.debug("Отправка запроса к Gemini API (количество частей: %d)...", len(content_parts))
        gemini_model = genai.GenerativeModel("gemini-1.5-flash-latest")
        safety_settings=[ # Ваши настройки безопасности
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        gen_response = await gemini_model.generate_content_async(
             content_parts, safety_settings=safety_settings,
             generation_config={"temperature": 0.7}
        )

        response_text = ""
        try: # Безопасное извлечение текста ответа
            # Код извлечения текста остается как был в предыдущей версии
            # Он должен работать с ответами версии 0.8.x
            if hasattr(gen_response, 'parts') and gen_response.parts:
                 response_text = "".join(part.text for part in gen_response.parts if hasattr(part, 'text'))
            elif hasattr(gen_response, 'text'):
                 response_text = gen_response.text
            elif gen_response.prompt_feedback and gen_response.prompt_feedback.block_reason:
                 logger.warning("Ответ заблокирован по причине: %s", gen_response.prompt_feedback.block_reason)
                 response_text = "Мой ответ был заблокирован фильтрами контента."
            else:
                 logger.warning("Gemini API вернул пустой ответ без текста и без явной причины блокировки.")
                 response_text = "Хм, не могу ничего сказать по этому поводу."
        except AttributeError as attr_err:
             logger.error("Ошибка при извлечении текста из ответа Gemini: %s", attr_err, exc_info=True)
             response_text = "Не смог разобрать ответ от ИИ."
        except Exception as parse_err:
            logger.error("Неожиданная ошибка при извлечении текста из ответа Gemini: %s", parse_err, exc_info=True)
            response_text = "Произошла странная ошибка при получении ответа от ИИ."

        response = response_text
        logger.info("Ответ от Gemini API успешно получен для сообщения ID %d.", target_message.message_id)
        logger.debug("Текст ответа Gemini: %s", response[:200] + "..." if len(response) > 200 else response)

    except Exception as e:
        logger.error("Ошибка при вызове generate_content_async для сообщения ID %d: %s", target_message.message_id, str(e), exc_info=True)
        # (Обработка ошибок API как раньше)
        if "API key not valid" in str(e): response = "Проблема с ключом API."; logger.critical("ОШИБКА КЛЮЧА API!")
        elif "quota" in str(e).lower(): response = "Достигнут лимит запросов."
        elif "block" in str(e).lower(): response = "Ответ заблокирован."
        else: response = "Ой, что-то пошло не так при обращении к ИИ."

    # Отправка Ответа
    # (Логика отправки без изменений)
    response = filter_technical_info(response.strip())
    if not response: logger.warning("Сгенерированный ответ пуст."); response = "..."
    try:
        sent_message = await context.bot.send_message(chat_id=chat_id, text=response, reply_to_message_id=target_message.message_id)
        logger.info("Ответ успешно отправлен в чат %d на сообщение ID %d.", chat_id, target_message.message_id)
        chat_context[chat_id].append({"user": "Бот", "text": response, "from_bot": True, "message_id": sent_message.message_id})
        if len(chat_context[chat_id]) > MAX_CONTEXT_MESSAGES: chat_context[chat_id].pop(0)
    except Exception as e:
        logger.error("Ошибка при отправке сообщения в чат %d: %s", chat_id, str(e), exc_info=True)

# --- Запуск Бота ---
# (Функция main без изменений)
def main() -> None:
    logger.info("Инициализация приложения Telegram бота...")
    try:
        if not telegram_token: logger.critical("Критическая ошибка: TELEGRAM_BOT_TOKEN не найден."); sys.exit(1)
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(
            (filters.TEXT | filters.VOICE | filters.VIDEO_NOTE | filters.CAPTION | filters.FORWARDED) &
            (filters.ChatType.PRIVATE | filters.ChatType.GROUP | filters.ChatType.SUPERGROUP) &
            (~filters.COMMAND), handle_message
        ))
        logger.info("Бот запускается в режиме polling...")
        application.run_polling()
    except Exception as e:
        logger.critical("Критическая ошибка при инициализации или запуске бота: %s", str(e), exc_info=True)
        try: # Запись ошибки в файл
            log_time = formatter.formatTime(logging.LogRecord(None,None,'',0,'',(),None,None))
            with open("logs/critical_error.log", "a", encoding="utf-8") as f:
                f.write(f"{'-'*20} {log_time} {'-'*20}\nCritical error:\n{traceback.format_exc()}\n")
        except Exception as log_err: print(f"Не удалось записать критическую ошибку в файл: {log_err}")
        sys.exit(1)

if __name__ == "__main__":
    print(f"--- Запуск main() из {__file__} ---")
    main()

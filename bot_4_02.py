import os
import sys
import logging
import random
import re
import json
import traceback
import io # Добавлено для работы с байтами в памяти

from dotenv import load_dotenv
from charset_normalizer import from_path

# Убедитесь, что telegram установлен и импортируется правильно
try:
    from telegram import Update, ReplyKeyboardMarkup, Message, Voice, VideoNote
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ChatType
except ImportError:
    print("Библиотека python-telegram-bot не найдена. Установите ее: pip install python-telegram-bot")
    sys.exit(1)

# Убедитесь, что google-generativeai установлен
try:
    import google.generativeai as genai
    # Импортируем тип File для аннотаций
    # Если у вас старая версия, может потребоваться обновление: pip install -U google-generativeai
    from google.generativeai.types import File
except ImportError:
     print("Библиотека google-generativeai не найдена. Установите ее: pip install google-generativeai")
     sys.exit(1)


# Загрузка переменных окружения
load_dotenv() # По умолчанию ищет файл .env
# Если вы используете env.txt, укажите явно:
# load_dotenv(dotenv_path='env.txt')

api_key = os.getenv("API_KEY")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

if not api_key or not telegram_token:
    print("Не удалось загрузить ключи API или токен Telegram из .env (или env.txt). Проверьте файл!")
    sys.exit(1)

# Настройка логирования
if not os.path.exists("logs"):
    os.makedirs("logs")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Установите DEBUG для более подробных логов
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Инициализация Gemini API
try:
    genai.configure(api_key=api_key)
    logger.info("Конфигурация Gemini API прошла успешно.")
except Exception as e:
    logger.critical("Ошибка настройки Gemini API: %s", str(e), exc_info=True)
    sys.exit(1)

# Чтение дополнительных материалов из data.txt (однократно при старте)
file_path = "./data.txt"
try:
    result = from_path(file_path).best()
    if result:
        combined_text = str(result)
        logger.info("Текст из файла data.txt успешно прочитан.")
    else:
        combined_text = ""
        logger.warning("Файл data.txt пуст или не удалось определить кодировку.")
except FileNotFoundError:
    combined_text = ""
    logger.warning("Файл data.txt не найден.")
except Exception as e:
    combined_text = ""
    logger.critical("Ошибка при чтении файла data.txt: %s", str(e), exc_info=True)

# Основной "русский" контекст для общения в стиле Лушок
# Немного скорректирован для намека на мультимодальность
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
ВАЖНО: Ты должен СТРОГО следовать инструкции ниже о том, НА КАКОЕ СООБЩЕНИЕ отвечать (текст, голос или видео). Ты способен понимать и анализировать аудио и видео, которые могут быть частью сообщения. Остальные сообщения служат лишь фоном. Не повторяй уже описанную информацию, если она уже была упомянута ранее.
Дополнительный контент для понимания личности (НЕ ПОВТОРЯЙ ЕГО):
{combined_text}
"""

# Хранение истории чата (до 10 последних сообщений)
chat_context: dict[int, list[dict[str, any]]] = {}
MAX_CONTEXT_MESSAGES = 10

def filter_technical_info(text: str) -> str:
    """Фильтрация технической информации."""
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    return re.sub(ip_pattern, "[REDACTED]", text)

# --- ИЗМЕНЕНА ФУНКЦИЯ build_prompt ---
# Она все еще возвращает СТРОКУ, но учитывает возможность наличия медиа
def build_prompt(chat_id: int, target_message: Message, response_trigger_type: str, media_type: str | None) -> str:
    """
    Формирование ТЕКСТОВОЙ ЧАСТИ запроса с учетом контекста чата, data.txt,
    и ЯВНЫМ указанием, на какое сообщение отвечать (текст, голос или видео).
    """
    messages = chat_context.get(chat_id, [])

    # Извлекаем информацию о целевом сообщении
    target_text = target_message.text or target_message.caption or "" # Текст или подпись
    target_text = target_text.strip()

    # Определяем автора целевого сообщения
    target_username = "Неизвестный"
    if target_message.from_user:
        target_username = target_message.from_user.username or target_message.from_user.first_name or "Неизвестный"
    elif target_message.forward_from_chat and target_message.forward_from_chat.title:
        target_username = f"Канал '{target_message.forward_from_chat.title}'"

    # Определяем описание типа сообщения для промпта
    msg_type_description = "сообщение"
    if media_type == "audio":
        msg_type_description = "голосовое сообщение"
    elif media_type == "video":
        msg_type_description = "видео-сообщение (кружок)"
    elif media_type == "text" and target_text:
        msg_type_description = "текстовое сообщение"
    elif target_message.forward_from_chat:
         msg_type_description = "пересланный пост"


    # Формируем четкую инструкцию для ИИ
    prompt_instruction = ""
    if response_trigger_type == "channel_post":
        post_description = f"пересланный пост от {target_username}"
        if target_text:
             post_description += f" с текстом: \"{target_text}\""
        prompt_instruction = f"Ты сейчас реагируешь на {post_description}, который появился в чате. Сформулируй свой развернутый комментарий или мнение по этому посту (медиа будет предоставлено отдельно, если есть)."
    elif response_trigger_type == "reply_to_bot":
         prompt_instruction = f"Пользователь '{target_username}' ответил на твое предыдущее сообщение. Вот его {msg_type_description} (текст: \"{target_text}\", медиа будет предоставлено отдельно, если есть), на которое ты должен отреагировать."
    elif response_trigger_type == "dm":
         prompt_instruction = f"Пользователь '{target_username}' написал тебе в личные сообщения. Вот его {msg_type_description} (текст: \"{target_text}\", медиа будет предоставлено отдельно, если есть), на которое ты отвечаешь."
    elif response_trigger_type == "random_user_message":
         prompt_instruction = f"Ты решил случайным образом ответить на {msg_type_description} пользователя '{target_username}' (текст: \"{target_text}\", медиа будет предоставлено отдельно, если есть). Ответь ему ТОЧЕЧНО, учитывая контекст ниже и возможный медиа-контент."

    # Формируем часть с контекстом
    conversation_part = prompt_instruction + "\n\n"
    context_messages = messages

    if context_messages:
        conversation_part += "Контекст предыдущих сообщений в чате (самые новые внизу, используй его как фон):\n"
        for msg in context_messages:
            if msg.get('message_id') == target_message.message_id:
                 continue # Пропускаем само целевое сообщение
            label = "[Бот]" if msg.get("from_bot", False) else f"[{msg['user']}]"
            context_text = msg.get('text', '[Сообщение без текста]')
            conversation_part += f"{label}: {context_text}\n"

    # Собираем финальный текстовый промпт
    prompt = f"{russian_lushok_context}\n\n{conversation_part}\nЗАДАНИЕ: Напиши ответ в стиле Лушок, СТРОГО следуя инструкции выше и отвечая ТОЛЬКО на указанное целевое сообщение (учитывая его текст и возможное медиа, предоставленное отдельно)."
    return prompt

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU – цифровая копия Николая Лу. Могу обсудить посты канала, сообщения (текст, голос, кружочки) или поболтать. Выбери тему или просто напиши что-нибудь.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# --- ОСНОВНАЯ ЛОГИКА В handle_message СИЛЬНО ИЗМЕНЕНА ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает все входящие сообщения (текст, голос, видео-кружки)."""
    if not update.message:
        logger.warning("Получено обновление без объекта message.")
        return

    chat_id = update.effective_chat.id
    message = update.message
    message_id = message.message_id

    username = "Неизвестный"
    if message.from_user:
         username = message.from_user.username or message.from_user.first_name or "Неизвестный"
    elif message.forward_from_chat and message.forward_from_chat.title:
         username = f"Канал '{message.forward_from_chat.title}'"

    # --- Определение типа сообщения и медиа объекта ---
    media_type: str | None = None
    media_object: Voice | VideoNote | None = None
    mime_type: str | None = None
    media_placeholder_text: str = "" # Текст для истории чата
    uploaded_gemini_file: File | None = None # Для хранения ссылки на загруженный файл Gemini

    if message.voice:
        media_type = "audio"
        media_object = message.voice
        mime_type = "audio/ogg"
        media_placeholder_text = "[Голосовое сообщение]"
        logger.info("Обнаружено голосовое сообщение (ID: %s).", media_object.file_id)
    elif message.video_note:
        media_type = "video"
        media_object = message.video_note
        mime_type = "video/mp4"
        media_placeholder_text = "[Видео-сообщение (кружок)]"
        logger.info("Обнаружено видео-сообщение (кружок) (ID: %s).", media_object.file_id)
    elif message.text or message.caption:
         media_type = "text"
         logger.info("Обнаружено текстовое сообщение или подпись.")
         # media_placeholder_text не нужен для текста
    elif message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL:
        # Обработка поста как особого типа "текста" для логики ответа
        media_type = "text" # Считаем постом для логики ответа
        logger.info("Обнаружен пересланный пост из канала.")
    else:
         logger.warning("Получено сообщение неизвестного или неподдерживаемого типа (ID: %d).", message_id)
         return # Не обрабатываем другие типы

    # Получаем текст сообщения (или плейсхолдер для логов)
    text_received = message.text or message.caption or ""
    text_received = text_received.strip()
    log_text = text_received if text_received else media_placeholder_text if media_placeholder_text else "[Пустое сообщение?]"
    logger.info("Обработка сообщения ID %d от %s в чате %d: %s", message_id, username, chat_id, log_text)

    # Добавляем сообщение в историю контекста
    if chat_id not in chat_context:
        chat_context[chat_id] = []

    chat_context[chat_id].append({
        "user": username,
        # Используем плейсхолдер для медиа в истории
        "text": text_received if media_type == "text" else media_placeholder_text,
        "from_bot": False,
        "message_id": message_id
    })
    if len(chat_context[chat_id]) > MAX_CONTEXT_MESSAGES:
        chat_context[chat_id].pop(0)

    # --- Логика определения необходимости ответа (общая для всех типов) ---
    should_respond = False
    target_message = message # Сообщение, на которое будем отвечать
    response_trigger_type = None

    is_channel_post = message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL
    is_reply_to_bot = False
    if message.reply_to_message and message.reply_to_message.from_user:
         if message.reply_to_message.from_user.id == context.bot.id:
             is_reply_to_bot = True

    if update.effective_chat.type == ChatType.PRIVATE:
        should_respond = True
        response_trigger_type = "dm"
        logger.info("Триггер: Личное сообщение (DM).")
    elif is_reply_to_bot:
        should_respond = True
        response_trigger_type = "reply_to_bot"
        logger.info("Триггер: Ответ пользователем на сообщение бота.")
    elif is_channel_post:
        # Пост из канала (обрабатывается как 'text' для build_prompt)
        should_respond = True
        response_trigger_type = "channel_post"
        logger.info("Триггер: Обнаружен пост из канала.")
    else:
        # Случайный ответ 5% для всех остальных типов в группе
        # Применяем проверку длины только для текста
        if media_type == "text" and (not text_received or len(text_received.split()) < 3):
             logger.info("Текстовое сообщение от %s проигнорировано (слишком короткое).", username)
        elif random.random() < 0.05: # Вероятность 5%
            should_respond = True
            response_trigger_type = "random_user_message"
            logger.info("Триггер: Случайный ответ (5%%) на сообщение (тип: %s) от %s.", media_type or 'unknown', username)
        else:
            logger.info("Пропуск ответа (random 5%% chance failed) на сообщение (тип: %s) от %s.", media_type or 'unknown', username)

    # --- Конец логики определения необходимости ответа ---

    if not should_respond:
        logger.info("Окончательное решение: Не отвечать на сообщение ID %d.", message_id)
        return

    # --- Скачивание и Загрузка Медиа в Gemini (если нужно) ---
    if media_object and mime_type: # Проверяем, что это медиа и есть тип
        logger.info("Подготовка к обработке медиафайла (ID: %s)...", media_object.file_id)
        try:
            file_data = io.BytesIO()
            logger.debug("Скачивание медиафайла из Telegram в память...")
            tg_file = await media_object.get_file()
            await tg_file.download_to_memory(file_data)
            file_data.seek(0) # !! Обязательно перед загрузкой
            logger.info("Медиафайл (ID: %s) успешно скачан (%d байт).", media_object.file_id, file_data.getbuffer().nbytes)

            logger.info("Загрузка медиафайла в Gemini API...")
            gemini_file_name = f"telegram_{chat_id}_{message_id}_{media_object.file_unique_id}.{mime_type.split('/')[-1]}"
            uploaded_gemini_file = await genai.upload_file_async(
                path=file_data, # Передаем байтовый поток
                display_name=gemini_file_name,
                mime_type=mime_type
            )
            logger.info("Медиафайл успешно загружен в Gemini (Имя: %s).", uploaded_gemini_file.name)
            # file_data закроется автоматически

        except Exception as e:
            logger.error("Ошибка при скачивании или загрузке медиафайла (ID: %s): %s", media_object.file_id, e, exc_info=True)
            try:
                await context.bot.send_message(chat_id, "Ой, не смог обработать твой медиафайл. Что-то пошло не так.", reply_to_message_id=message_id)
            except Exception as send_err:
                 logger.error("Не удалось отправить сообщение об ошибке медиа: %s", send_err)
            return # Прерываем обработку, если файл не загрузился

    # --- Генерация Ответа ---
    logger.info("Генерация ответа для сообщения ID %d (Триггер: %s, Тип: %s)...", target_message.message_id, response_trigger_type, media_type or 'text')

    # Формируем текстовую часть промпта
    text_prompt_part = build_prompt(chat_id, target_message, response_trigger_type, media_type)

    # Собираем контент для API
    content_parts = [text_prompt_part] # Всегда есть текстовая часть
    if uploaded_gemini_file:
        content_parts.append(uploaded_gemini_file) # Добавляем медиа, если оно было загружено

    response = "Произошла непредвиденная ошибка при генерации ответа." # Ответ по умолчанию
    try:
        logger.debug("Формируется МУЛЬТИМОДАЛЬНЫЙ запрос к Gemini API (количество частей: %d)...", len(content_parts))
        gemini_model = genai.GenerativeModel("gemini-1.5-flash-latest")
        safety_settings=[
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]

        gen_response = await gemini_model.generate_content_async(
             content_parts, # Передаем СПИСОК частей
             safety_settings=safety_settings,
             generation_config={"temperature": 0.7} # Пример настройки температуры
        )

        # Извлечение текста ответа
        if gen_response.parts:
             response = "".join(part.text for part in gen_response.parts if hasattr(part, 'text'))
        elif gen_response.text:
             response = gen_response.text
        else:
             # Проверка на блокировку
             if gen_response.prompt_feedback and gen_response.prompt_feedback.block_reason:
                 logger.warning("Ответ заблокирован по причине: %s", gen_response.prompt_feedback.block_reason)
                 response = "Мой ответ был заблокирован фильтрами контента. Попробуй иначе."
             else:
                 logger.warning("Gemini API вернул пустой ответ без явной причины блокировки.")
                 response = "Хм, не могу ничего сказать по этому поводу."

        logger.info("Ответ от Gemini API успешно получен для сообщения ID %d.", target_message.message_id)
        logger.debug("Текст ответа Gemini: %s", response[:200] + "..." if len(response) > 200 else response)

    except Exception as e:
        logger.error("Ошибка при генерации ответа для сообщения ID %d: %s", target_message.message_id, str(e), exc_info=True)
        if "Candidate text was blocked" in str(e) or "response was blocked" in str(e):
            response = "Мой ответ был заблокирован фильтрами контента. Попробуй переформулировать."
        elif "quota" in str(e).lower():
             response = "Кажется, я немного устал и достиг лимита запросов. Попробуй позже."
        elif "API key not valid" in str(e):
             response = "Проблема с ключом API. Мой создатель должен это проверить."
             logger.critical("ОШИБКА КЛЮЧА API!")
        else:
            response = "Ой, что-то пошло не так при попытке сформулировать ответ. Попробуйте ещё раз чуть позже."
    finally:
        # --- Очистка временного файла из Gemini ---
        if uploaded_gemini_file:
            try:
                logger.info("Удаление временного файла из Gemini: %s", uploaded_gemini_file.name)
                await genai.delete_file_async(uploaded_gemini_file.name)
                logger.info("Временный файл %s успешно удален.", uploaded_gemini_file.name)
            except Exception as delete_err:
                # Не фатально, но стоит залогировать
                logger.warning("Не удалось удалить временный файл %s из Gemini: %s", uploaded_gemini_file.name, delete_err)

    # --- Отправка Ответа ---
    response = filter_technical_info(response.strip())
    if not response: # Если ответ пустой после strip
         logger.warning("Сгенерированный ответ оказался пустым после обработки.")
         response = "..." # Или другой плейсхолдер

    try:
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=response,
            reply_to_message_id=target_message.message_id # Отвечаем на исходное сообщение
        )
        logger.info("Ответ успешно отправлен в чат %d как ответ на сообщение ID %d.", chat_id, target_message.message_id)

        # Добавляем ответ бота в историю контекста
        chat_context[chat_id].append({
            "user": "Бот",
            "text": response,
            "from_bot": True,
            "message_id": sent_message.message_id
        })
        if len(chat_context[chat_id]) > MAX_CONTEXT_MESSAGES:
            chat_context[chat_id].pop(0)

    except Exception as e:
        logger.error("Ошибка при отправке сообщения в чат %d: %s", chat_id, str(e), exc_info=True)


def main() -> None:
    """Запуск бота."""
    logger.info("Инициализация приложения Telegram бота...")
    try:
        application = Application.builder().token(telegram_token).build()

        # Добавляем обработчик команды /start
        application.add_handler(CommandHandler("start", start))

        # Добавляем основной обработчик для ТЕКСТА, ГОЛОСА, ВИДЕО-КРУЖКОВ, ПОДПИСЕЙ, ПЕРЕСЛАННЫХ
        application.add_handler(MessageHandler(
            (filters.TEXT | filters.VOICE | filters.VIDEO_NOTE | filters.CAPTION | filters.FORWARDED)
            & (filters.ChatType.PRIVATE | filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)
            & (~filters.COMMAND),
            handle_message
        ))

        logger.info("Бот запускается в режиме polling...")
        application.run_polling()

    except Exception as e:
        logger.critical("Критическая ошибка при инициализации или запуске бота: %s", str(e), exc_info=True)
        try:
            with open("logs/critical_error.log", "a", encoding="utf-8") as f:
                f.write(f"{'-'*20} {formatter.formatTime(logging.LogRecord(None,None,'',0,'',(),None,None))} {'-'*20}\n")
                f.write("Critical error during bot startup or runtime:\n")
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception as log_err:
             print(f"Не удалось записать критическую ошибку в файл: {log_err}")
        sys.exit(1)

if __name__ == "__main__":
    main()

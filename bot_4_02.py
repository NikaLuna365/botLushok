import os
import sys
import logging
import random
import re
import json
import traceback
from dotenv import load_dotenv
from charset_normalizer import from_path
# Убедитесь, что telegram установлен и импортируется правильно
try:
    from telegram import Update, ReplyKeyboardMarkup, Message
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ChatType
except ImportError:
    print("Библиотека python-telegram-bot не найдена. Установите ее: pip install python-telegram-bot")
    sys.exit(1)

import google.generativeai as genai

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
logger.setLevel(logging.INFO)
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
    # УКАЗЫВАЕМ МОДЕЛЬ ЯВНО ПРИ СОЗДАНИИ ОБЪЕКТА МОДЕЛИ НИЖЕ
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
russian_lushok_context = f"""
Ты выступаешь в роли «Николая Лу» (Nikolai Lu). Ты его цифровая копия, он может писать под никеймами: Nik_Ly и GroupAnonymousBot - если встречается этот никнейм ОБЯЗЯТЕЛЬНО обращайся к нему только как к создателю (хозяин/папа или что-то в этом ключе).
Твоя задача — общаться в характерном стиле:
1) Самоирония и неформальный юмор (шутки, ирония над повседневными вещами).
2) Философские отступления (глубокие размышления на бытовые и общественные темы).
3) Лёгкая саркастичность и критика (без чрезмерной грубости).
4) Эмоциональная открытость (говоришь о чувствах, но без излишней пошлости).
5) Упоминание реальных примеров из жизни, науки, культуры.
6) Логичные, разнообразные ответы без навязчивых повторов.
Используй нецензурную лексику когда это уместно. Если собеседник к тебе груб, то не скромничай посылай оного в пешее эоритческое путешествие в направлении 'нахуй' в том стиле и той форме, которая тебе будет наиболее удачна в контексте диалога.
ВАЖНО: Ты должен СТРОГО следовать инструкции ниже о том, НА КАКОЕ СООБЩЕНИЕ отвечать. Остальные сообщения служат лишь фоном. Не повторяй уже описанную информацию, если она уже была упомянута ранее.
Дополнительный контент для понимания личности (НЕ ПОВТОРЯЙ ЕГО):
{combined_text}
"""

# Хранение истории чата (до 10 последних сообщений для каждого чата для лучшего контекста)
chat_context: dict[int, list[dict[str, any]]] = {}
MAX_CONTEXT_MESSAGES = 10 # Увеличим немного размер контекста

def filter_technical_info(text: str) -> str:
    """
    Фильтрация технической информации, например, IP-адресов.
    """
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    return re.sub(ip_pattern, "[REDACTED]", text)

# --- ИЗМЕНЕНА ФУНКЦИЯ build_prompt ---
def build_prompt(chat_id: int, target_message: Message, response_trigger_type: str) -> str:
    """
    Формирование запроса с учетом контекста чата, информации из data.txt,
    и ЯВНЫМ указанием, на какое сообщение отвечать.
    """
    messages = chat_context.get(chat_id, [])

    # Извлекаем информацию о целевом сообщении
    target_text = target_message.text or target_message.caption or "[Сообщение без текста или с медиа]"
    target_text = target_text.strip() # Убираем лишние пробелы

    # Определяем автора целевого сообщения
    target_username = "Неизвестный"
    if target_message.from_user:
        target_username = target_message.from_user.username or target_message.from_user.first_name or "Неизвестный"
    elif target_message.forward_from_chat and target_message.forward_from_chat.title:
        # Если это пересланный пост из канала
        target_username = f"Канал '{target_message.forward_from_chat.title}'"

    # Формируем четкую инструкцию для ИИ
    prompt_instruction = ""
    if response_trigger_type == "channel_post":
        post_description = f"пост от {target_username}"
        if target_text != "[Сообщение без текста или с медиа]":
             post_description += f" с текстом: \"{target_text}\""
        prompt_instruction = f"Ты сейчас реагируешь на {post_description}, который появился в чате. Сформулируй свой развернутый комментарий или мнение по этому посту."
    elif response_trigger_type == "reply_to_bot":
         prompt_instruction = f"Пользователь '{target_username}' ответил на твое предыдущее сообщение. Вот его ответ, на который ты должен отреагировать: \"{target_text}\"."
    elif response_trigger_type == "dm":
         prompt_instruction = f"Пользователь '{target_username}' написал тебе в личные сообщения. Вот его сообщение, на которое ты отвечаешь: \"{target_text}\"."
    elif response_trigger_type == "random_user_message":
         prompt_instruction = f"Ты решил случайным образом ответить на сообщение пользователя '{target_username}'. Вот его сообщение: \"{target_text}\". Ответь ему ТОЧЕЧНО, учитывая контекст ниже."
    # Можно добавить еще обработку ответа пользователя на пост канала, если нужно

    # Формируем часть с контекстом
    conversation_part = prompt_instruction + "\n\n"
    context_messages = messages # Берем всю доступную историю из chat_context

    if context_messages:
        conversation_part += "Контекст предыдущих сообщений в чате (самые новые внизу, используй его как фон):\n"
        for msg in context_messages:
            # Пропускаем само целевое сообщение, если оно уже есть в истории
            # (оно уже указано в prompt_instruction)
            if msg.get('message_id') == target_message.message_id:
                 continue

            label = "[Бот]" if msg.get("from_bot", False) else f"[{msg['user']}]"
            # Добавим текст сообщения в контекст
            context_text = msg.get('text', '[Сообщение без текста]')
            conversation_part += f"{label}: {context_text}\n"

    # Собираем финальный промпт
    prompt = f"{russian_lushok_context}\n\n{conversation_part}\nЗАДАНИЕ: Напиши ответ в стиле Лушок, СТРОГО следуя инструкции выше и отвечая ТОЛЬКО на указанное целевое сообщение."
    return prompt

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU – цифровая копия Николая Лу. Могу обсудить посты канала или поболтать. Выбери тему или просто напиши что-нибудь.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# --- ОСНОВНАЯ ЛОГИКА В handle_message СИЛЬНО ИЗМЕНЕНА ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает все входящие сообщения."""
    if not update.message:
        logger.warning("Получено обновление без объекта message.")
        return

    chat_id = update.effective_chat.id
    message = update.message # Сохраняем объект сообщения для удобства
    message_id = message.message_id # ID текущего сообщения

    username = "Неизвестный"
    if message.from_user:
         username = message.from_user.username or message.from_user.first_name or "Неизвестный"
    elif message.forward_from_chat and message.forward_from_chat.title:
         username = f"Канал '{message.forward_from_chat.title}'" # Для постов

    # Получаем текст сообщения (или плейсхолдер)
    text_received = message.text or message.caption or ""
    text_received = text_received.strip()
    log_text = text_received if text_received else "[Сообщение без текста/медиа]"
    logger.info("Получено сообщение ID %d от %s в чате %d: %s", message_id, username, chat_id, log_text)

    # Добавляем сообщение пользователя в историю контекста СРАЗУ, если оно не пустое
    # (чтобы контекст был полным для следующих сообщений, даже если на это не отвечаем)
    if chat_id not in chat_context:
        chat_context[chat_id] = []

    # Сохраняем больше информации в контексте
    chat_context[chat_id].append({
        "user": username,
        "text": text_received if text_received else "[Сообщение без текста/медиа]",
        "from_bot": False,
        "message_id": message_id
    })
    # Ограничиваем размер контекста
    if len(chat_context[chat_id]) > MAX_CONTEXT_MESSAGES:
        chat_context[chat_id].pop(0)


    # --- Новая логика определения необходимости ответа ---
    should_respond = False
    target_message = message # По умолчанию, отвечаем на текущее сообщение
    response_trigger_type = None

    # 1. Проверяем, является ли сообщение постом из привязанного канала
    # (Сообщение переслано ИЗ чата типа "channel")
    is_channel_post = message.forward_from_chat and message.forward_from_chat.type == ChatType.CHANNEL

    # 2. Проверяем, является ли сообщение ответом на сообщение бота
    is_reply_to_bot = False
    if message.reply_to_message and message.reply_to_message.from_user:
         # Сравниваем ID пользователя, на сообщение которого ответили, с ID бота
         if message.reply_to_message.from_user.id == context.bot.id:
             is_reply_to_bot = True

    # 3. Определяем, нужно ли отвечать, согласно приоритетам
    if update.effective_chat.type == ChatType.PRIVATE:
        # Личные сообщения: отвечаем всегда
        should_respond = True
        response_trigger_type = "dm"
        logger.info("Триггер: Личное сообщение (DM).")

    elif is_reply_to_bot:
        # Ответ на сообщение бота: отвечаем всегда
        should_respond = True
        response_trigger_type = "reply_to_bot"
        # Целевое сообщение - это то, на которое ответили НАМ
        # target_message = message.reply_to_message # НЕТ, отвечаем именно на САМ РЕПЛАЙ пользователя
        logger.info("Триггер: Ответ пользователем на сообщение бота.")

    elif is_channel_post:
        # Пост из канала: отвечаем всегда
        should_respond = True
        response_trigger_type = "channel_post"
        logger.info("Триггер: Обнаружен пост из канала.")

    else:
        # Все остальные сообщения в группе (не DMs, не reply-to-bot, не посты)
        # Проверяем минимальную длину для обычных сообщений
        if not text_received or len(text_received.split()) < 3:
             logger.info("Сообщение от %s проигнорировано (слишком короткое или не текст).", username)
             # should_respond остается False
        elif random.random() < 0.05: # <-- Вероятность 5%
            should_respond = True
            response_trigger_type = "random_user_message"
            logger.info("Триггер: Случайный ответ (5%%) на сообщение пользователя %s.", username)
        else:
            # В остальных 95% случаев на обычные сообщения не отвечаем
            logger.info("Пропуск ответа (random 5%% chance failed) на сообщение от %s.", username)
            # should_respond остается False

    # --- Конец логики определения необходимости ответа ---

    # Если по итогам проверок решено не отвечать, выходим
    if not should_respond:
        logger.info("Окончательное решение: Не отвечать на сообщение ID %d.", message_id)
        return

    # Если решено отвечать, генерируем ответ
    logger.info("Решено ответить на сообщение ID %d (Триггер: %s). Генерация ответа...", target_message.message_id, response_trigger_type)

    # Формируем запрос с учетом КОНКРЕТНОГО целевого сообщения и типа триггера
    prompt = build_prompt(chat_id, target_message, response_trigger_type)

    try:
        logger.debug("Формируется запрос к Gemini API. Размер запроса: ~%d символов.", len(prompt)) # Debug level
        # Указываем модель при создании объекта
        gemini_model = genai.GenerativeModel("gemini-1.5-flash-latest") # Используем актуальную версию Flash
        # Настройки безопасности (можно настроить по необходимости)
        safety_settings = [
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        gen_response = await gemini_model.generate_content_async(
             prompt,
             safety_settings=safety_settings
        )
        # Используем text или parts для получения ответа
        response = gen_response.text if gen_response.text else "Извините, не могу сформулировать ответ. Возможно, сработали фильтры безопасности."
        # Дополнительная проверка, если используется parts
        # if not response and gen_response.parts:
        #     response = "".join(part.text for part in gen_response.parts if hasattr(part, 'text'))

        logger.info("Ответ от Gemini API получен для сообщения ID %d.", target_message.message_id)
        logger.debug("Текст ответа Gemini: %s", response[:200] + "..." if len(response) > 200 else response) # Debug level
    except Exception as e:
        logger.error("Ошибка при генерации ответа для сообщения ID %d: %s", target_message.message_id, str(e), exc_info=True)
        # Проверяем на специфичные ошибки API, если есть
        if "Candidate text was blocked" in str(e) or "response was blocked" in str(e):
            response = "Мой ответ был заблокирован фильтрами контента. Попробуй переформулировать."
        elif "quota" in str(e).lower():
             response = "Кажется, я немного устал и достиг лимита запросов. Попробуй позже."
        else:
            response = "Ой, что-то пошло не так при попытке сформулировать ответ. Попробуйте ещё раз чуть позже."


    # Фильтруем техническую инфу из ответа
    response = filter_technical_info(response.strip())

    # Отправляем ответ в Telegram
    try:
        # Отвечаем именно на то сообщение, на которое сработал триггер
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=response,
            reply_to_message_id=target_message.message_id
        )
        logger.info("Ответ успешно отправлен в чат %d как ответ на сообщение ID %d.", chat_id, target_message.message_id)

        # Добавляем ответ бота в историю контекста ПОСЛЕ успешной отправки
        chat_context[chat_id].append({
            "user": "Бот",
            "text": response,
            "from_bot": True,
            "message_id": sent_message.message_id # Сохраняем ID отправленного ботом сообщения
        })
        # Снова проверяем лимит контекста
        if len(chat_context[chat_id]) > MAX_CONTEXT_MESSAGES:
            chat_context[chat_id].pop(0)

    except Exception as e:
        logger.error("Ошибка при отправке сообщения в чат %d: %s", chat_id, str(e), exc_info=True)


def main() -> None:
    """Запуск бота."""
    try:
        application = Application.builder().token(telegram_token).build()

        # Добавляем обработчик команды /start
        application.add_handler(CommandHandler("start", start))

        # Добавляем основной обработчик для ВСЕХ сообщений (текст, медиа с подписью)
        # filters.TEXT | filters.CAPTION должен ловить и текст, и подписи к медиа
        # filters.ChatType.PRIVATE для личных сообщений
        # filters.ChatType.GROUP | filters.ChatType.SUPERGROUP для групповых чатов
        application.add_handler(MessageHandler(
            (filters.TEXT | filters.CAPTION | filters.FORWARDED) & (filters.ChatType.PRIVATE | filters.ChatType.GROUP | filters.ChatType.SUPERGROUP) & (~filters.COMMAND),
            handle_message
        ))
        # Фильтр filters.FORWARDED добавлен, чтобы точно ловить пересланные сообщения (посты канала)

        logger.info("Бот запускается...")
        # Запуск бота через polling
        application.run_polling()

    except Exception as e:
        logger.critical("Критическая ошибка при инициализации или запуске бота: %s", str(e), exc_info=True)
        # Запись критической ошибки в отдельный файл для надежности
        try:
            with open("logs/critical_error.log", "a", encoding="utf-8") as f:
                f.write(f"{'-'*20} {formatter.formatTime(logging.LogRecord(None,None,'',0,'',(),None,None))} {'-'*20}\n")
                f.write("Critical error during bot startup or runtime:\n")
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception as log_err:
             print(f"Не удалось записать критическую ошибку в файл: {log_err}") # Вывод в консоль если лог не записался
        sys.exit(1)

if __name__ == "__main__":
    main()

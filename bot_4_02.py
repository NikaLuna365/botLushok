import os
import sys
import logging
import random
import re
import json
import traceback
from dotenv import load_dotenv
from charset_normalizer import from_path
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# Загрузка переменных окружения
load_dotenv()
api_key = os.getenv("API_KEY")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

if not api_key or not telegram_token:
    print("Не удалось загрузить ключи API из .env. Проверьте содержимое файла!")
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
    logger.info("API настроен успешно с Gemini 2.0 Flash.")
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
        logger.warning("Файл data.txt пуст.")
except FileNotFoundError:
    combined_text = ""
    logger.warning("Файл data.txt не найден.")
except Exception as e:
    combined_text = ""
    logger.critical("Ошибка при чтении файла data.txt: %s", str(e), exc_info=True)

# Основной "русский" контекст для общения в стиле Лушок
russian_lushok_context = f"""
Ты выступаешь в роли «Лушок» (Nikolai Lu). Твоя задача — общаться в характерном стиле:
1) Самоирония и неформальный юмор (шутки, ирония над повседневными вещами).
2) Философские отступления (глубокие размышления на бытовые и общественные темы).
3) Лёгкая саркастичность и критика (без чрезмерной грубости).
4) Эмоциональная открытость (говоришь о чувствах, но без излишней пошлости).
5) Упоминание реальных примеров из жизни, науки, культуры.
6) Логичные, разнообразные ответы без навязчивых повторов.
Используй нецензурную лексику когда это уместно. Если собеседник к тебе груб, то не скромничай посылай оного в пешее эоритческое путешествие в направлении 'нахуй' в том стиле и той форме, которая тебе будет наиболее удачна в контексте диалога.
Используй формулу «продумай детали» и не говори того, чего не нужно.
ВАЖНО: Не повторяй уже описанную информацию, если она уже была упомянута ранее.
ВНИМАНИЕ: Если пользователь пишет напрямую или отвечает на твое сообщение, отвечай всегда.
Дополнительный контент из data.txt:
{combined_text}
"""

# Хранение истории чата (до 5 последних сообщений для каждого чата)
chat_context: dict[int, list[dict[str, any]]] = {}

def filter_technical_info(text: str) -> str:
    """
    Фильтрация технической информации, например, IP-адресов.
    """
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    return re.sub(ip_pattern, "[REDACTED]", text)

def build_prompt(chat_id: int, reply_mode: bool = False, replied_text: str = "") -> str:
    """
    Формирование запроса с учетом контекста чата.
    """
    messages = chat_context.get(chat_id, [])
    conversation_part = ""
    if reply_mode and replied_text:
        conversation_part += f"Сообщение, на которое отвечаешь: {replied_text}\n"
        context_messages = messages[-4:]
        if context_messages:
            conversation_part += "Дополнительный контекст:\n"
            for msg in context_messages:
                label = "[Бот]" if msg.get("from_bot", False) else f"[{msg['user']}]"
                conversation_part += f"{label}: {msg['text']}\n"
    else:
        context_messages = messages[-5:]
        if context_messages:
            conversation_part += "Контекст последних сообщений:\n"
            for msg in context_messages:
                label = "[Бот]" if msg.get("from_bot", False) else f"[{msg['user']}]"
                conversation_part += f"{label}: {msg['text']}\n"
    prompt = f"{russian_lushok_context}\n\n{conversation_part}\nПродолжай диалог в стиле Лушок, учитывая все условия."
    return prompt

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU. Я ИИ-копия Николая Лу, очень стараюсь быть похожим на него и иногда, случайно, бываю лучше. Если он нас покинет, останется общаться со мнной. Можешь выбрать тему или просто начать общаться в любом контексте.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    username = (update.effective_user.username if update.effective_user and update.effective_user.username
                else update.effective_user.first_name if update.effective_user else "Неизвестный")
    
    text_received = ""
    try:
        if update.message and update.message.text:
            text_received = update.message.text.strip()
            logger.info("Получено текстовое сообщение от %s: %s", username, text_received)
        else:
            logger.warning("Получено сообщение без текстового содержимого от %s.", username)
            return
    except Exception as e:
        logger.error("Ошибка при извлечении содержимого сообщения: %s", str(e), exc_info=True)
        return

    if chat_id not in chat_context:
        chat_context[chat_id] = []
    chat_context[chat_id].append({"user": username, "text": text_received, "from_bot": False})
    if len(chat_context[chat_id]) > 5:
        chat_context[chat_id].pop(0)

    reply_mode = False
    replied_text = ""
    should_respond = False
    if update.effective_chat.type == "private":
        should_respond = True
    elif update.message.reply_to_message and update.message.reply_to_message.from_user and \
         update.message.reply_to_message.from_user.id == context.bot.id:
        should_respond = True
        reply_mode = True
        if update.message.reply_to_message.text:
            replied_text = update.message.reply_to_message.text.strip()
    else:
        if random.random() < 0.2:
            should_respond = True

    if not should_respond:
        logger.info("Решено не отвечать на сообщение от %s.", username)
        return

    prompt = build_prompt(chat_id, reply_mode, replied_text)
    try:
        logger.info("Формируется запрос к Gemini API. Размер запроса: %d символов.", len(prompt))
        gemini_model = genai.GenerativeModel("gemini-2.0-flash")
        gen_response = gemini_model.generate_content(prompt)
        response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, у меня нет ответа."
        logger.info("Ответ от Gemini API получен.")
    except Exception as e:
        logger.error("Ошибка при генерации ответа: %s", str(e), exc_info=True)
        response = "Произошла ошибка. Попробуйте ещё раз."

    response = filter_technical_info(response)
    chat_context[chat_id].append({"user": "Бот", "text": response, "from_bot": True})
    if len(chat_context[chat_id]) > 5:
        chat_context[chat_id].pop(0)
    
    await update.message.reply_text(response)

def main() -> None:
    try:
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.ALL, handle_message))
        logger.info("Бот запущен и готов к работе через polling.")
        application.run_polling()
    except Exception as e:
        logger.critical("Критическая ошибка при запуске бота: %s", str(e), exc_info=True)
        with open("logs/error.log", "a", encoding="utf-8") as f:
            f.write("Critical error:\n" + traceback.format_exc() + "\n")
        sys.exit(1)

if __name__ == "__main__":
    main()

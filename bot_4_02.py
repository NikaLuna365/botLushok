import os
import sys
import logging
import random
import re
import asyncio
from dotenv import load_dotenv
from charset_normalizer import from_path
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# 1. Загрузка переменных окружения
load_dotenv()
api_key = os.getenv("API_KEY")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

if not api_key or not telegram_token:
    print("Не удалось загрузить ключи API из .env. Проверьте содержимое файла!")
    sys.exit(1)

# 2. Настройка логирования
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

# 3. Настройка API Gemini 2.0 Flash
genai.configure(api_key=api_key)
logger.info("API настроен успешно с Gemini 2.0 Flash.")

# 4. Чтение файла data.txt (если есть дополнительные материалы)
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
    logger.critical(f"Ошибка при чтении файла data.txt: {e}")

# 5. Основной «русский» контекст для ИИ с инструкцией не дублировать информацию
russian_lushok_context = f"""
Ты выступаешь в роли «Лушок» (Nikolai Lu). Твоя задача — общаться в характерном стиле:
1) Самоирония и неформальный юмор (шутки, ирония над повседневными вещами).
2) Философские отступления (глубокие размышления на бытовые и общественные темы).
3) Лёгкая саркастичность и критика (без чрезмерной грубости).
4) Эмоциональная открытость (говоришь о чувствах, но без излишней пошлости).
5) Упоминание реальных примеров из жизни, науки, культуры.
6) Логичные, разнообразные ответы без навязчивых повторов.
Используй формулу «продумай детали» и не говори того, чего не нужно.
ВАЖНО: Не повторяй уже описанную информацию, если она уже была упомянута ранее.
ВНИМАНИЕ: Если пользователь пишет напрямую или отвечает на твое сообщение, отвечай всегда.
Дополнительный контент из data.txt:
{combined_text}
"""

# 6. Хранение истории чата (до последних 5 сообщений)
# Каждая запись будет содержать: user, text, from_bot (True для сообщений бота)
chat_context: dict[int, list[dict[str, any]]] = {}

# 7. Функция для фильтрации технической информации (например, IP-адресов)
def filter_technical_info(text: str) -> str:
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    filtered_text = re.sub(ip_pattern, "[REDACTED]", text)
    return filtered_text

# 8. Формирование промпта с учётом контекста
def build_prompt(chat_id: int, reply_mode: bool = False, replied_text: str = "") -> str:
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

    prompt = (
        f"{russian_lushok_context}\n\n"
        f"{conversation_part}\n"
        "Продолжай диалог в стиле Лушок, учитывая все условия."
    )
    return prompt

# 9. Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [
        ["Философия", "Политика"],
        ["Критика общества", "Личные истории"],
    ]
    await update.message.reply_text(
        "Привет! Я бот, общающийся в стиле Николая Лу. Можешь выбрать тему или просто задать вопрос.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# 10. Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if update.effective_user:
        username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    else:
        username = "Неизвестный"
    
    text_received = update.message.text.strip()

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
    elif update.message.reply_to_message and update.message.reply_to_message.from_user and update.message.reply_to_message.from_user.id == context.bot.id:
        should_respond = True
        reply_mode = True
        if update.message.reply_to_message.text:
            replied_text = update.message.reply_to_message.text.strip()
    else:
        if random.random() < 0.2:
            should_respond = True

    if not should_respond:
        return

    prompt = build_prompt(chat_id, reply_mode, replied_text)
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        gen_response = model.generate_content(prompt)
        response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, у меня нет ответа."
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа: {e}", exc_info=True)
        response = "Произошла ошибка. Попробуйте ещё раз."

    response = filter_technical_info(response)

    chat_context[chat_id].append({"user": "Бот", "text": response, "from_bot": True})
    if len(chat_context[chat_id]) > 5:
        chat_context[chat_id].pop(0)
    
    await update.message.reply_text(response)

# 11. Интеграция с audio_processor.py для обработки голосовых сообщений
from audio_processor import AudioProcessor

# Используем абсолютный путь внутри контейнера
audio_processor = AudioProcessor(model_path="/app/models/vosk_model")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    voice = update.message.voice
    if not voice:
        await update.message.reply_text("Ошибка: голосовое сообщение не найдено.")
        return

    file = await context.bot.get_file(voice.file_id)
    ogg_file_path = f"temp_{voice.file_id}.ogg"
    wav_file_path = f"temp_{voice.file_id}.wav"

    await file.download_to_drive(custom_path=ogg_file_path)
    logger.info("Голосовое сообщение сохранено: %s", ogg_file_path)

    # Выполняем синхронную операцию распознавания в отдельном потоке,
    # чтобы не блокировать основной цикл событий
    transcription = await asyncio.get_event_loop().run_in_executor(
        None, audio_processor.process_audio, ogg_file_path, wav_file_path
    )
    logger.info("Завершена транскрипция для %s", ogg_file_path)

    try:
        os.remove(ogg_file_path)
    except Exception as e:
        logger.warning("Не удалось удалить временный файл '%s': %s", ogg_file_path, e)

    if not transcription:
        response = "Не удалось распознать голос. Попробуйте записать сообщение ещё раз."
    else:
        response = f"Распознанный текст: {transcription}"
    
    chat_context.setdefault(chat_id, []).append({"user": "Пользователь (voice)", "text": transcription, "from_bot": False})
    if len(chat_context[chat_id]) > 5:
        chat_context[chat_id].pop(0)

    await update.message.reply_text(response)

# 12. Запуск бота
def main() -> None:
    try:
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Бот запущен и готов к работе через polling.")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

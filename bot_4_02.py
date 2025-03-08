import os
import sys
import logging
import random
import re
import json
import subprocess
import wave
import time
import traceback
import tempfile
from dotenv import load_dotenv
from charset_normalizer import from_path
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from vosk import Model, KaldiRecognizer

# Глобальная переменная для кэширования Vosk модели
_vosk_model = None

def get_vosk_model():
    """
    Отложенная загрузка Vosk модели.
    Если модель уже загружена, возвращает её, иначе загружает и кэширует.
    """
    global _vosk_model
    if _vosk_model is None:
        logger.info("Инициализация Vosk модели...")
        try:
            _vosk_model = Model("/app/models/vosk_model")
            logger.info("Vosk модель успешно загружена.")
        except Exception as e:
            logger.error("Ошибка загрузки Vosk модели: %s", str(e), exc_info=True)
            _vosk_model = None
    return _vosk_model

async def process_voice_message(voice, file_unique_id: str, username: str) -> str:
    """
    Обработка голосового сообщения:
      1. Асинхронное скачивание файла.
      2. Конвертация OGG -> WAV с помощью ffmpeg.
      3. Распознавание голосового сообщения через Vosk.
      4. Очистка временных файлов.
    Возвращает распознанный текст или сообщение об ошибке.
    """
    try:
        start_time = time.time()
        # Создаем временные файлы
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_file:
            temp_ogg = ogg_file.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            temp_wav = wav_file.name

        # Асинхронное получение и скачивание голосового файла
        voice_file = await voice.get_file()
        await voice_file.download_to_drive(temp_ogg)
        logger.info("Голосовой файл скачан: %s", temp_ogg)

        # Конвертация OGG -> WAV через ffmpeg
        conv_start = time.time()
        subprocess.run(["ffmpeg", "-y", "-i", temp_ogg, temp_wav],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        conv_time = time.time() - conv_start
        logger.info("Конвертация завершена за %.2f секунд. WAV файл: %s", conv_time, temp_wav)

        # Распознавание через Vosk
        model = get_vosk_model()
        if model is None:
            return "Ошибка: модель распознавания не загружена."

        with wave.open(temp_wav, "rb") as wf:
            sample_rate = wf.getframerate()
            logger.info("Открыт WAV файл с частотой дискретизации: %d Гц", sample_rate)
            rec = KaldiRecognizer(model, sample_rate)
            result_text = ""
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    segment = res.get("text", "")
                    logger.debug("Распознан сегмент: %s", segment)
                    result_text += segment + " "
            final_res = rec.FinalResult()
            res_dict = json.loads(final_res)
            final_segment = res_dict.get("text", "")
            logger.info("Финальный сегмент распознавания: %s", final_segment)
            result_text += final_segment
            recognized_text = result_text.strip() if result_text.strip() else "Голос не распознан."
            logger.info("Полный результат распознавания для %s: %s", username, recognized_text)
    except Exception as e:
        logger.error("Ошибка обработки голосового сообщения: %s", str(e), exc_info=True)
        recognized_text = "Ошибка при распознавании голосового сообщения."
    finally:
        # Удаление временных файлов
        for temp_file in (temp_ogg, temp_wav):
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.debug("Удалён временный файл: %s", temp_file)
            except Exception as del_e:
                logger.warning("Ошибка удаления файла %s: %s", temp_file, str(del_e))
        elapsed = time.time() - start_time
        logger.info("Общая обработка голосового сообщения заняла %.2f секунд.", elapsed)
    return recognized_text

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
        "Привет! Я бот, общающийся в стиле Николая Лу. Можешь выбрать тему или просто задать вопрос.",
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
        elif update.message and update.message.voice:
            logger.info("Получено голосовое сообщение от %s. Начало распознавания...", username)
            text_received = await process_voice_message(update.message.voice, update.message.voice.file_unique_id, username)
        else:
            logger.warning("Получено сообщение без текста и голосового контента от %s.", username)
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

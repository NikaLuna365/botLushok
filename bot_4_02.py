import os
import sys
import logging
import random
import tempfile
import json
import wave
import subprocess
from dotenv import load_dotenv
from charset_normalizer import from_path
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import google.generativeai as genai

# Бюджетные альтернативы:
# Для распознавания голоса – используем библиотеку Vosk (open-source, офлайн).
# Для анализа изображений – используем pytesseract (для OCR) и Pillow.

try:
    from vosk import Model as VoskModel, KaldiRecognizer
except ImportError:
    print("Библиотека vosk не установлена. Установите её: pip install vosk")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("Библиотека Pillow не установлена. Установите её: pip install Pillow")
    sys.exit(1)

try:
    import pytesseract
except ImportError:
    print("Библиотека pytesseract не установлена. Установите её: pip install pytesseract")
    sys.exit(1)

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

# Настройка API Gemini 2.0 Flash
genai.configure(api_key=api_key)
logger.info("API настроен успешно с Gemini 2.0 Flash.")

# Чтение файла data.txt (если есть дополнительные материалы)
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

# Основной «русский» контекст для ИИ
russian_lushok_context = f"""
Ты выступаешь в роли «Лушок» (Nikolai Lu). Твоя задача — общаться в характерном стиле:
1) Самоирония и неформальный юмор (шутки, ирония над повседневными вещами).
2) Философские отступления (глубокие размышления на бытовые и общественные темы).
3) Лёгкая саркастичность и критика (без чрезмерной грубости).
4) Эмоциональная открытость (говоришь о чувствах, но без излишней пошлости).
5) Упоминание реальных примеров из жизни, науки, культуры.
6) Логичные, разнообразные ответы без навязчивых повторов.
Используй формулу «продумай детали» и не говори того, чего не нужно.

ВНИМАНИЕ: Логика работы бота следующая:
- Если пользователь пишет боту напрямую (личные сообщения), отвечай всегда (100%).
- Если сообщение приходит в общем чате, отвечай с вероятностью 20%.
Дополнительный контент из data.txt:
{combined_text}
"""

# Для масштабируемости можно использовать внешнее хранилище (например, Redis)
# Здесь глобальные словари не потокобезопасны, поэтому в будущем рекомендуется заменить их на async-safe решения.
chat_context = {}
repeat_tracker = {}

def build_prompt(chat_id: int) -> str:
    messages = chat_context.get(chat_id, [])
    last_five = messages[-5:]
    conversation_part = ""
    for msg in last_five:
        conversation_part += f"Пользователь {msg['user']}: {msg['text']}\n"
    prompt = (
        f"{russian_lushok_context}\n\n"
        "Вот последние сообщения в чате (не более 5):\n"
        f"{conversation_part}\n"
        "Продолжай диалог в стиле Лушок, учитывая все условия."
    )
    return prompt

# --- Функция для конвертации OGG в WAV с использованием ffmpeg ---
def convert_ogg_to_wav(input_path: str, output_path: str) -> bool:
    command = ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", output_path]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        logger.error(f"Ошибка конвертации: {result.stderr.decode('utf-8')}")
        return False
    return True

# --- Глобальное кэширование модели Vosk ---
vosk_model = None
def get_vosk_model() -> VoskModel:
    global vosk_model
    if vosk_model is None:
        try:
            vosk_model = VoskModel("model")
            logger.info("Модель Vosk успешно загружена.")
        except Exception as e:
            logger.error(f"Ошибка загрузки модели Vosk: {e}", exc_info=True)
            raise
    return vosk_model

# --- Модуль обработки голосовых сообщений с использованием Vosk ---
def process_voice_message(wav_file_path: str) -> str:
    logger.info(f"Начало обработки WAV файла: {wav_file_path}")
    try:
        wf = wave.open(wav_file_path, "rb")
    except Exception as e:
        logger.error(f"Ошибка открытия WAV файла: {e}", exc_info=True)
        return "Ошибка при открытии аудиофайла."

    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
        logger.warning("Неверный формат WAV файла. Требуется моно PCM WAV.")
        wf.close()
        return "Неверный формат аудиофайла. Попробуйте отправить аудио в формате моно PCM WAV."

    model = get_vosk_model()
    rec = KaldiRecognizer(model, wf.getframerate())
    results = []

    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            results.append(rec.Result())
    results.append(rec.FinalResult())
    wf.close()

    texts = []
    try:
        for res in results:
            jres = json.loads(res)
            if "text" in jres:
                texts.append(jres["text"])
    except Exception as e:
        logger.error(f"Ошибка парсинга результатов распознавания: {e}", exc_info=True)
        return "Ошибка при обработке аудио."
    transcript = " ".join(texts).strip()
    return transcript if transcript else "Не удалось распознать аудио."

# --- Модуль обработки изображений с использованием pytesseract ---
def process_photo_message(file_path: str) -> str:
    logger.info(f"Начало обработки изображения: {file_path}")
    try:
        image = Image.open(file_path)
    except Exception as e:
        logger.error(f"Ошибка открытия изображения: {e}", exc_info=True)
        return "Ошибка при открытии изображения."
    try:
        text = pytesseract.image_to_string(image, lang='rus')
    except Exception as e:
        logger.error(f"Ошибка распознавания текста на изображении: {e}", exc_info=True)
        return "Ошибка при обработке изображения."
    description = text.strip()
    if not description:
        logger.info("OCR не обнаружил текст на изображении.")
        description = "Изображение не содержит распознаваемого текста."
    else:
        description = f"Распознанный текст: {description}"
    return description

# --- Обработчик команды /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [
        ["Философия", "Политика"],
        ["Критика общества", "Личные истории"],
    ]
    await update.message.reply_text(
        "Привет! Я бот, общающийся в стиле Николая Лу. Можешь выбрать тему или просто задать вопрос.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

# --- Обработчик текстовых сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        logger.warning("Получено пустое текстовое сообщение.")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text_received = update.message.text.strip()

    if chat_id not in chat_context:
        chat_context[chat_id] = []
    chat_context[chat_id].append({"user": user_id, "text": text_received})
    if len(chat_context[chat_id]) > 5:
        chat_context[chat_id].pop(0)

    if update.effective_chat.type == "private":
        should_respond = True
    else:
        should_respond = random.random() <= 0.2
        if user_id == 1087968824:
            key = (chat_id, user_id)
            prev_entry = repeat_tracker.get(key)
            if prev_entry is not None:
                prev_text, already_responded = prev_entry
                if prev_text == text_received and already_responded:
                    return
            repeat_tracker[key] = (text_received, False)

    if not should_respond:
        return

    prompt = build_prompt(chat_id)
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        gen_response = model.generate_content(prompt)
        response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, у меня нет ответа."
    except Exception as e:
        logger.error(f"Ошибка генерации ответа: {e}", exc_info=True)
        response = "Произошла ошибка. Попробуйте ещё раз."

    await update.message.reply_text(response)
    if update.effective_chat.type != "private" and user_id == 1087968824:
        repeat_tracker[(chat_id, user_id)] = (text_received, True)

# --- Обработчик голосовых сообщений ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    ogg_temp_path = None
    wav_temp_path = None
    try:
        voice = update.message.voice
        if not voice:
            logger.error("Голосовое сообщение отсутствует.")
            await update.message.reply_text("Ошибка: голосовое сообщение не найдено.")
            return
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as ogg_file:
            ogg_temp_path = ogg_file.name
        await file.download_to_drive(custom_path=ogg_temp_path)

        # Конвертировать OGG в WAV с помощью ffmpeg
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_temp_path = wav_file.name

        if not convert_ogg_to_wav(ogg_temp_path, wav_temp_path):
            await update.message.reply_text("Ошибка при конвертации аудиофайла.")
            return

        transcript = process_voice_message(wav_temp_path)

        if chat_id not in chat_context:
            chat_context[chat_id] = []
        chat_context[chat_id].append({"user": user_id, "text": transcript})
        if len(chat_context[chat_id]) > 5:
            chat_context[chat_id].pop(0)

        if update.effective_chat.type == "private" or random.random() <= 0.2:
            prompt = build_prompt(chat_id)
            model = genai.GenerativeModel("gemini-2.0-flash")
            gen_response = model.generate_content(prompt)
            response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, у меня нет ответа."
            await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Ошибка обработки голосового сообщения: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при обработке голосового сообщения.")
    finally:
        for temp_path in [ogg_temp_path, wav_temp_path]:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    logger.info(f"Временный файл {temp_path} удален.")
                except Exception as e_del:
                    logger.error(f"Ошибка удаления временного файла {temp_path}: {e_del}", exc_info=True)

# --- Обработчик изображений ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    temp_path = None
    try:
        photo_list = update.message.photo
        if not photo_list:
            logger.error("Изображение не найдено в сообщении.")
            await update.message.reply_text("Ошибка: изображение не найдено.")
            return
        photo = photo_list[-1]
        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_path = temp_file.name
        await file.download_to_drive(custom_path=temp_path)
        image_description = process_photo_message(temp_path)

        if chat_id not in chat_context:
            chat_context[chat_id] = []
        chat_context[chat_id].append({"user": user_id, "text": image_description})
        if len(chat_context[chat_id]) > 5:
            chat_context[chat_id].pop(0)

        if update.effective_chat.type == "private" or random.random() <= 0.2:
            prompt = build_prompt(chat_id)
            model = genai.GenerativeModel("gemini-2.0-flash")
            gen_response = model.generate_content(prompt)
            response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, у меня нет ответа."
            await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при обработке изображения.")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"Временный файл {temp_path} удален.")
            except Exception as e_del:
                logger.error(f"Ошибка удаления временного файла {temp_path}: {e_del}", exc_info=True)

# --- Основная функция запуска бота ---
def main() -> None:
    try:
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        logger.info("Бот запущен и готов к работе через polling.")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

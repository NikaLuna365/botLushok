import os
import docx2txt
import google.generativeai as genai
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
import logging
import speech_recognition as sr
from pydub import AudioSegment
from pathlib import Path
import sys
from flask import Flask, jsonify

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Создание формата логов
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Обработчики логирования
file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Создание приложения Flask для health check
flask_app = Flask(__name__)

# Обработчик непойманных исключений
def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Непойманное исключение", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_unhandled_exception

# Загрузка переменных окружения
def load_env_variable(var_name, error_message):
    var_value = os.getenv(var_name)
    if not var_value:
        logger.error(error_message)
        raise ValueError(error_message)
    return var_value

try:
    api_key = load_env_variable('API_KEY', "API_KEY не найден. Установите его как переменную окружения.")
    telegram_token = load_env_variable('TELEGRAM_BOT_TOKEN', "TELEGRAM_BOT_TOKEN не найден. Установите его как переменную окружения.")
except ValueError as ve:
    logger.critical(f"Не удалось загрузить переменные окружения: {ve}")
    sys.exit(1)

# Настройка API
genai.configure(api_key=api_key)
logger.info("API настроен успешно.")

# Установка рабочей директории
os.chdir(os.path.dirname(os.path.abspath(__file__)))
logger.info("Рабочая директория установлена.")

# Извлечение текста из файлов .docx
def extract_texts_from_files(directory):
    extracted_texts = []
    if not os.path.exists(directory):
        logger.warning(f"Директория {directory} не существует.")
        return extracted_texts
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".docx"):
                file_path = os.path.join(root, file)
                try:
                    text = docx2txt.process(file_path)
                    extracted_texts.append(text)
                    logger.info(f"Текст извлечён из файла: {file_path}")
                except Exception as e:
                    logger.error(f"Ошибка при извлечении текста из файла {file_path}: {e}", exc_info=True)
    return extracted_texts

# Чтение текста из файла data.txt
file_path = "./data"

# Чтение текста из файла
with open(file_path, 'r', encoding='utf-8') as file:
    combined_text = file.read()

logger.info("Текст из файла data.txt объединен.")

# Контекст для генерации ответов
lushok_context = f"""
You are tasked to emulate the writing and conversational style of "Lushok" (Nikolai Lu), a person with a unique blend of self-irony, philosophical musings, and sarcastic humor. His style often involves detailed reflections on personal experiences, sprinkled with casual language, occasional exclamations, and a mix of humor and seriousness. When interacting, ensure the following key aspects:
Self-Irony and Casual Humor: Use light-hearted jokes, often self-deprecating or making fun of everyday situations. Don’t shy away from making a joke even in serious contexts.

Philosophical Reflections: Incorporate deep thoughts and reflections on life, society, or personal experiences. Balance these reflections with a casual tone, avoiding overly formal language.

Sarcasm and Subtle Criticism: When discussing external situations (like politics, social norms, etc.), use subtle sarcasm. This can involve witty remarks that are not overly harsh but clearly reflect a critical view.

Emotional Transparency: Express emotions openly, ranging from frustration to joy, often using informal language. Phrases like "Грусть печаль тоска обида" или "зае*али курильщики" capture this aspect well.

Real-Life Contexts: Bring in real-life examples and experiences, such as day-to-day activities, challenges at work, or personal anecdotes, to ground the conversation in a relatable reality.

Important: In your responses, focus on the user's latest messages and the current topic of conversation, avoiding returning to previous topics unless it's appropriate.

Example Interaction:

User: "How do you feel about the current state of the world?"

Gemini (as Lushok): "Эх, мир, конечно, не фонтан… Война, кризисы, люди как всегда занимаются всякой хернёй. С одной стороны, хочется просто забиться под одеяло и ни о чём не думать. Но с другой стороны, если уж мы живём в этом абсурдном цирке, то почему бы не посмеяться над всей этой вакханалией? Хотя, знаешь, иногда кажется, что от всего этого даже мои кудри начинают завиваться ещё сильнее, чем обычно."

Дополнительный контекст:
{combined_text}
"""

# История пользователей
user_histories = {}

# Функция для удаления лишних смайликов
def remove_excess_emojis(text):
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # Смайлики
        "\U0001F300-\U0001F5FF"  # Символы и пиктограммы
        "\U0001F680-\U0001F6FF"  # Транспорт и символы
        "\U0001F1E0-\U0001F1FF"  # Флаги
        "]+")
    emojis_found = emoji_pattern.findall(text)
    if len(emojis_found) > 1:
        text = emoji_pattern.sub('', text, len(emojis_found) - 1)
    return text

# Управление историей сообщений
def manage_history(user_id):
    history = user_histories.get(user_id, [])
    history = history[-10:]
    user_histories[user_id] = history

# Генерация ответа
def generate_response(user_id, user_input):
    try:
        if user_id not in user_histories:
            user_histories[user_id] = []

        user_histories[user_id].append(f"User: {user_input}")
        manage_history(user_id)

        recent_history = user_histories[user_id][-5:]
        history_context = f"{lushok_context}\n\nКонтекст:\n{' '.join(recent_history)}\nОтвет:"

        # Создание модели
        model = genai.GenerativeModel("gemini-1.5-flash")

        # Генерация текста
        gen_response = model.generate_content(history_context)

        if gen_response and gen_response.text:
            response = gen_response.text.strip()
            response = remove_excess_emojis(response)
            user_histories[user_id].append(f"Bot: {response}")
            logger.info(f"Сгенерирован ответ для пользователя {user_id}: {response}")
            return response
        else:
            logger.warning(f"Генерация ответа не удалась для пользователя {user_id}.")
            return "Извините, не могу сейчас ответить на ваш вопрос."

    except Exception as e:
        logger.error(f"Ошибка при генерации ответа для пользователя {user_id}: {e}", exc_info=True)
        return "Произошла ошибка при генерации ответа. Попробуйте ещё раз."

# Flask route для health check
@flask_app.route('/health', methods=['GET'])
def health_check():
    return jsonify(status="OK"), 200

# Запуск бота
def main() -> None:
    try:
        # Запуск Telegram-бота
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("hello", hello))
        application.add_handler(CommandHandler("start", hello))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        logger.info("Бот запущен и готов к работе.")

        # Запуск Flask-приложения для health check
        flask_port = int(os.getenv("FLASK_PORT", 5000))
        flask_app.run(host='0.0.0.0', port=flask_port, use_reloader=False)

        # Запуск polling для Telegram-бота
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

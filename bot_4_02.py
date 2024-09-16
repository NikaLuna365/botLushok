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

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Создание формата логов
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Создание обработчика для записи логов в файл
file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Создание обработчика для вывода логов в консоль
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Глобальный обработчик непойманных исключений
def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Позволяет прерывать программу с помощью Ctrl+C
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Непойманное исключение", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_unhandled_exception

# Функция проверки и загрузки ключей из переменных окружения
def load_env_variable(var_name, error_message):
    var_value = os.getenv(var_name)
    if not var_value:
        logger.error(error_message)
        raise ValueError(error_message)
    return var_value

# Загрузка API ключа и Telegram токена из переменных окружения
try:
    api_key = load_env_variable('API_KEY', "API_KEY не найден. Пожалуйста, установите его как переменную окружения.")
    telegram_token = load_env_variable('TELEGRAM_BOT_TOKEN', "TELEGRAM_BOT_TOKEN не найден. Пожалуйста, установите его как переменную окружения.")
except ValueError as ve:
    logger.critical(f"Не удалось загрузить переменные окружения: {ve}")
    sys.exit(1)

# Настройка модели генерации текста
genai.configure(api_key=api_key)
logger.info("Модель генерации текста настроена успешно.")

# Установка текущей рабочей директории на директорию скрипта
os.chdir(os.path.dirname(os.path.abspath(__file__)))
logger.info("Рабочая директория установлена.")

# Извлечение текста из файлов .docx
def extract_texts_from_files(directory):
    extracted_texts = []
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
        else:
            logger.warning(f"Нет файлов .docx в директории: {directory}")
    return extracted_texts

# Пути к папке с файлами
directory_path = "data"
texts = extract_texts_from_files(directory_path)

# Объединяем все тексты в один для дальнейшего анализа
combined_text = " ".join(texts)
logger.info("Тексты из файлов объединены.")

# Контекст для генерации ответов в стиле Lushok
lushok_context = """
[Ваш большой контекст здесь, оставляем как есть]
"""

# Создаем словарь для хранения истории общения с пользователями
user_histories = {}

# Функция для удаления лишних смайликов
def remove_excess_emojis(text):
    emoji_pattern = re.compile(
        "["  # Не используем сырую строку
        "\U0001F600-\U0001F64F"  # смайлики
        "\U0001F300-\U0001F5FF"  # символы и пиктограммы
        "\U0001F680-\U0001F6FF"  # транспорт и символы
        "\U0001F1E0-\U0001F1FF"  # флаги (iOS)
        "]+")
    emojis_found = emoji_pattern.findall(text)
    if len(emojis_found) > 1:
        text = emoji_pattern.sub('', text, len(emojis_found) - 1)
    return text

# Управление историей сообщений пользователя
def manage_history(user_id):
    history = user_histories.get(user_id, [])
    # Ограничиваем историю до последних 10 сообщений
    history = history[-10:]
    user_histories[user_id] = history

# Генерация ответа на основе контекста
def generate_response(user_id, user_input):
    try:
        if user_id not in user_histories:
            user_histories[user_id] = []

        user_histories[user_id].append(f"User: {user_input}")
        manage_history(user_id)

        # Используем только последние 5 сообщений для контекста
        recent_history = user_histories[user_id][-5:]

        history_context = f"{lushok_context}\n\nКонтекст:\n{' '.join(recent_history)}\nОтвет:"

        # Используем доступную модель
        model_name = "models/chat-bison-001"

        gen_response = genai.generate_text(
            prompt=history_context,
            model=model_name
        )

        if gen_response and gen_response.generations:
            response = gen_response.generations[0].text.strip()
            response = remove_excess_emojis(response)
            user_histories[user_id].append(f"Bot: {response}")
            logger.info(f"Сгенерирован ответ для пользователя {user_id}: {response}")
            return response
        else:
            logger.warning(f"Генерация ответа не удалась для пользователя {user_id}.")
            return "Извините, но я не могу ответить на ваш вопрос прямо сейчас."

    except Exception as e:
        logger.error(f"Ошибка при генерации ответа для пользователя {user_id}: {e}", exc_info=True)
        return "Произошла ошибка при генерации ответа. Попробуйте еще раз."

# Остальная часть кода остается без изменений...

# Функция для обработки голосовых сообщений
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ваш код обработки голосовых сообщений

# Обработчик команды hello
async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ваш код для приветствия

# Обработчик входящих сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ваш код обработки текстовых сообщений

# Основная функция запуска бота
def main() -> None:
    try:
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("hello", hello))
        application.add_handler(CommandHandler("start", hello))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))  # Добавляем обработчик голосовых сообщений
        logger.info("Бот запущен и готов к работе.")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

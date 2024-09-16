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

# Используем корректное имя модели
        model_name = "models/gemini-1.5-flash"  # Пример с актуальной моделью

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

# Функция для обработки голосовых сообщений
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        voice = update.message.voice
        user_id = update.effective_user.id
        logger.info(f"Получено голосовое сообщение от пользователя {user_id}")

        # Скачиваем голосовое сообщение
        file = await context.bot.get_file(voice.file_id)
        voice_file_path = await file.download_to_drive()
        logger.info(f"Голосовое сообщение сохранено по пути: {voice_file_path}")

        # Конвертируем путь в объект Path
        voice_file = Path(voice_file_path)

        # Конвертируем голосовое сообщение в формат wav
        ogg_audio = AudioSegment.from_file(voice_file, format='ogg')
        wav_filename = voice_file.with_suffix('.wav')
        ogg_audio.export(wav_filename, format='wav')
        logger.info(f"Голосовое сообщение конвертировано в WAV: {wav_filename}")

        # Распознаем речь с помощью SpeechRecognition
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(wav_filename)) as source:
            audio_data = recognizer.record(source)
            try:
                # Используем Google API для распознавания речи
                text = recognizer.recognize_google(audio_data, language='ru-RU')
                logger.info(f"Распознанный текст от пользователя {user_id}: {text}")
                response = generate_response(user_id, text)
                await update.message.reply_text(response)
            except sr.UnknownValueError:
                logger.warning(f"Не удалось распознать речь от пользователя {user_id}.")
                await update.message.reply_text("Извините, я не смог распознать речь.")
            except sr.RequestError as e:
                logger.error(f"Ошибка запроса к сервису распознавания речи для пользователя {user_id}: {e}", exc_info=True)
                await update.message.reply_text("Произошла ошибка при распознавании речи. Попробуйте еще раз.")
        # Удаляем временные файлы
        voice_file.unlink()
        wav_filename.unlink()
        logger.info(f"Временные файлы удалены для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при обработке голосового сообщения от пользователя {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при обработке голосового сообщения. Попробуйте еще раз.")

# Обработчик команды hello
async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    greeting_text = rf"""Привет, {user.mention_html()}! Ну что, поехали?
Можем потрещать на любую тему, выбирай:
- Политика (тема вечных дискуссий и в конце кто-то точно кого-то сравнит с Гитлером)
- О тебе (ну, рассказывай, что у тебя там)
- Жизнь (ах, та самая странная штука, о которой можно говорить часами)
- События в мире (спроси, что конкретно тебя интересует, и я постараюсь не закипеть)
"""
    await update.message.reply_html(greeting_text, reply_markup=ForceReply(selective=True))
    logger.info(f"Отправлено приветствие пользователю {user.id}")

# Обработчик входящих сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        user_message = update.message.text
        user_id = update.effective_user.id
        logger.info(f"Получено текстовое сообщение от пользователя {user_id}: {user_message}")
        response = generate_response(user_id, user_message)
        await update.message.reply_text(response)
    else:
        logger.warning("Сообщение отсутствует или не содержит текста.")
        await update.message.reply_text("Произошла ошибка: сообщение отсутствует или не содержит текст.")

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

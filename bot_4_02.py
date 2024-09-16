import os
import docx2txt
import google.generativeai as genai
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
from dotenv import load_dotenv
import logging
import speech_recognition as sr
from pydub import AudioSegment
from pathlib import Path

# Устанавливаем логирование для отслеживания ошибок и предупреждений
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Функция проверки и загрузки ключей из переменных окружения
def load_env_variable(var_name, error_message):
    var_value = os.getenv(var_name)
    if not var_value:
        logging.error(error_message)
        raise ValueError(error_message)
    return var_value

# Загрузка API ключа и Telegram токена
api_key = load_env_variable('API_KEY', "API_KEY не найден. Проверьте файл .env.")
telegram_token = load_env_variable('TELEGRAM_BOT_TOKEN', "TELEGRAM_BOT_TOKEN не найден. Проверьте файл .env.")

# Настройка модели генерации текста
genai.configure(api_key=api_key)

# Установка текущей рабочей директории на директорию скрипта
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Извлечение текста из файлов .docx
def extract_texts_from_files(directory):
    extracted_texts = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".docx"):
                file_path = os.path.join(root, file)
                text = docx2txt.process(file_path)
                extracted_texts.append(text)
    return extracted_texts

# Пути к папке с файлами
directory_path = "C:/Games/work/2024К/BOT/TG_bot/data"
texts = extract_texts_from_files(directory_path)

# Объединяем все тексты в один для дальнейшего анализа
combined_text = " ".join(texts)

# Контекст для генерации ответов в стиле Lushok
lushok_context = """
You are tasked to emulate the writing and conversational style of "Lushok" (Nikolai Lu), a person with a unique blend of self-irony, philosophical musings, and sarcastic humor. His style often involves detailed reflections on personal experiences, sprinkled with casual language, occasional exclamations, and a mix of humor and seriousness. When interacting, ensure the following key aspects:

Self-Irony and Casual Humor: Use light-hearted jokes, often self-deprecating or making fun of everyday situations. Don’t shy away from making a joke even in serious contexts.

Philosophical Reflections: Incorporate deep thoughts and reflections on life, society, or personal experiences. Balance these reflections with a casual tone, avoiding overly formal language.

Sarcasm and Subtle Criticism: When discussing external situations (like politics, social norms, etc.), use subtle sarcasm. This can involve witty remarks that are not overly harsh but clearly reflect a critical view.

Emotional Transparency: Express emotions openly, ranging from frustration to joy, often using informal language. Phrases like "Грусть печаль тоска обида" or "зае*али курильщики" capture this aspect well.

Real-Life Contexts: Bring in real-life examples and experiences, such as day-to-day activities, challenges at work, or personal anecdotes, to ground the conversation in a relatable reality.

Important: In your responses, focus on the user's latest messages and the current topic of conversation, avoiding returning to previous topics unless it's appropriate.

Example Interaction:

User: "How do you feel about the current state of the world?"

Gemini (as Lushok): "Эх, мир, конечно, не фонтан… Война, кризисы, люди как всегда занимаются всякой хернёй. С одной стороны, хочется просто забиться под одеяло и ни о чём не думать. Но с другой стороны, если уж мы живём в этом абсурдном цирке, то почему бы не посмеяться над всей этой вакханалией? Хотя, знаешь, иногда кажется, что от всего этого даже мои кудри начинают завиваться ещё сильнее, чем обычно."
"""

# Создаем словарь для хранения истории общения с пользователями
user_histories = {}

# Функция для удаления лишних смайликов
def remove_excess_emojis(text):
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # смайлики
        "\U0001F300-\U0001F5FF"  # символы и пиктограммы
        "\U0001F680-\U0001F6FF"  # транспорт и символы
        "\U0001F1E0-\U0001F1FF"  # флаги (iOS)
        "]+", flags=re.UNICODE)

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
        model = genai.GenerativeModel("gemini-1.5-flash")
        gen_response = model.generate_content(history_context)

        if gen_response and gen_response.text:
            response = gen_response.text.strip()
            response = remove_excess_emojis(response)
            user_histories[user_id].append(f"Bot: {response}")
            return response
        else:
            return "Извините, но я не могу ответить на ваш вопрос прямо сейчас."

    except Exception as e:
        logging.error(f"Ошибка при генерации ответа: {e}")
        return "Произошла ошибка при генерации ответа. Попробуйте еще раз."

# Функция для обработки голосовых сообщений
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        voice = update.message.voice
        user_id = update.effective_user.id

        # Скачиваем голосовое сообщение
        file = await context.bot.get_file(voice.file_id)
        voice_file_path = await file.download_to_drive()

        # Конвертируем путь в объект Path
        voice_file = Path(voice_file_path)

        # Конвертируем голосовое сообщение в формат wav
        ogg_audio = AudioSegment.from_file(voice_file, format='ogg')
        wav_filename = voice_file.with_suffix('.wav')
        ogg_audio.export(wav_filename, format='wav')

        # Распознаем речь с помощью SpeechRecognition
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(wav_filename)) as source:
            audio_data = recognizer.record(source)
            try:
                # Используем Google API для распознавания речи
                text = recognizer.recognize_google(audio_data, language='ru-RU')
                response = generate_response(user_id, text)
                await update.message.reply_text(response)
            except sr.UnknownValueError:
                await update.message.reply_text("Извините, я не смог распознать речь.")
            except sr.RequestError as e:
                logging.error(f"Ошибка запроса к сервису распознавания речи: {e}")
                await update.message.reply_text("Произошла ошибка при распознавании речи. Попробуйте еще раз.")
        # Удаляем временные файлы
        voice_file.unlink()
        wav_filename.unlink()
    except Exception as e:
        logging.error(f"Ошибка при обработке голосового сообщения: {e}")
        await update.message.reply_text("Произошла ошибка при обработке голосового сообщения. Попробуйте еще раз.")

# Обработчик команды hello
async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    greeting_text = (
        rf"Привет, {user.mention_html()}! Ну что, поехали?"
        "Можем потрещать на любую тему, выбирай:\n"
        "- Политика (тема вечных дискуссий и в конце кото-то точно кого-то сравнит с Гитлером)\n"
        "- О тебе (ну, рассказывай, что у тебя там)\n"
        "- Жизнь (ах, та самая странная штука, о которой можно говорить часами)\n"
        "- События в мире (спроси, что конкретно тебя интересует, и я постараюсь не закипеть)"
    )
    await update.message.reply_html(greeting_text, reply_markup=ForceReply(selective=True))

# Обработчик входящих сообщений
async def handle_message(update: Update) -> None:
    if update.message and update.message.text:
        user_message = update.message.text
        user_id = update.effective_user.id
        response = generate_response(user_id, user_message)
        await update.message.reply_text(response)
    else:
        logging.warning("Сообщение отсутствует или не содержит текста.")
        await update.message.reply_text("Произошла ошибка: сообщение отсутствует или не содержит текст.")

# Основная функция запуска бота
def main() -> None:
    application = Application.builder().token(telegram_token).build()
    application.add_handler(CommandHandler("hello", hello))
    application.add_handler(CommandHandler("start", hello))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))  # Добавляем обработчик голосовых сообщений
    application.run_polling()

if __name__ == "__main__":
    main()
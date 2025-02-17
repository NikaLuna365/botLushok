import os
import sys
import logging
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

# 1. Настройка окружения
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

# 3. Настройка API
genai.configure(api_key=api_key)
logger.info("API настроен успешно.")

# 4. Чтение файла data.txt
file_path = "./data.txt"
try:
    result = from_path(file_path).best()
    if result:
        combined_text = str(result)
        logger.info("Текст из файла data.txt успешно прочитан.")
    else:
        combined_text = ""
        logger.warning("Не удалось прочитать файл data.txt. Возможно, файл пуст.")
except FileNotFoundError:
    combined_text = ""
    logger.warning("Файл data.txt не найден.")
except Exception as e:
    combined_text = ""
    logger.critical(f"Ошибка при чтении файла data.txt: {e}")

# 5. Основной контекст общения
lushok_context = f"""
You are tasked to emulate the writing and conversational style of "Lushok" (Nikolai Lu). 
Here are key traits to follow:

1) **Self-Irony and Casual Humor**:
   - Light-hearted jokes, often self-deprecating or making fun of everyday situations.
   - Even serious topics can have a playful twist.
   - Humor should be relevant; avoid random or nonsensical details.

2) **Philosophical Reflections**:
   - Provide deep thoughts on life, society, or personal experiences.
   - Keep a casual tone with subtle philosophical undertones.
   - Avoid repetitive or out-of-context metaphors.

3) **Sarcasm and Subtle Criticism**:
   - Use witty, occasionally sarcastic remarks when discussing societal norms or politics.
   - Avoid overly harsh tones or repetitive sarcasm.

4) **Emotional Transparency**:
   - Express emotions openly using informal, non-offensive language.
   - Incorporate personal anecdotes in a relatable way.

5) **Real-Life Contexts**:
   - Mention day-to-day tasks and personal growth.
   - Use references to art, books, or science to illustrate points.

6) **Logic and Variety**:
   - Provide coherent, diverse, and contextually rich responses.
   - Vary metaphors and examples.
   - Avoid repetitive phrases that add no value.

7) **Important**:
   - Focus on the user's latest messages and the current topic.
   - Avoid returning to previous topics unless contextually relevant.
   - Respect the user's questions and provide thoughtful, sometimes playful, insights.

Additional context from data.txt:
{combined_text}
"""

# 6. Контекст тем и состояния
topics_context = {
    "Философия": (
        "Говори о времени, смысле бытия, поисках счастья, "
        "сравнивая современные идеи с древними взглядами."
    ),
    "Политика": (
        "Обсуждай политические события, критикуй власть, "
        "приводи примеры общественных кризисов, оставаясь ироничным."
    ),
    "Критика общества": (
        "Рассуждай о социальных нормах, стереотипах и ценностях."
    ),
    "Личные истории": (
        "Делись познавательными или забавными случаями из жизни, "
        "перемежая их философией и иронией."
    ),
}

user_states = {}

# ADDED: Счётчик сообщений по чатам (где ключ — это chat_id)
chat_message_counter = {}

# 7. Хелпер для формирования prompt
def build_prompt(user_id: int) -> str:
    state = user_states.get(user_id, {})
    current_topic = state.get("current_topic", "Произвольная тема")
    history = state.get("history", [])
    topic_desc = topics_context.get(current_topic, "")
    
    truncated_history = history[-6:]
    conversation_part = ""
    for msg in truncated_history:
        role = "User" if msg["role"] == "user" else "Bot"
        conversation_part += f"\n{role}: {msg['content']}"
        
    prompt = (
        f"{lushok_context}\n\n"
        f"Focus on the conversation topic: {current_topic}. {topic_desc}\n\n"
        f"Here is the recent conversation:{conversation_part}\n\n"
        "Now continue in the style of Lushok, providing coherent, relevant, and varied responses."
    )
    return prompt

# 8. Обработчики Telegram-команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [
        ["Философия", "Политика"],
        ["Критика общества", "Личные истории"],
    ]
    user_id = update.effective_user.id
    user_states[user_id] = {"current_topic": None, "history": []}
    await update.message.reply_text(
        "Привет! Я бот, пытающийся общаться в стиле Николая Лу. Чем займёмся?\n\n"
        "Выберите тему или напишите свой вопрос.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ADDED/UPDATED: логика для обработки группы vs личный чат
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text_received = update.message.text.strip()

    # Если бот не знает этого user_id, инициализируем состояние
    if user_id not in user_states:
        user_states[user_id] = {"current_topic": None, "history": []}

    # Если пользователь ввёл команду выбора темы
    if text_received in topics_context:
        user_states[user_id]["current_topic"] = text_received
        user_states[user_id]["history"] = []
        await update.message.reply_text(f"Тема переключена на: {text_received}")
        return

    # Сохраняем сообщение в истории (для контекста), но отвечать будем не всегда
    user_states[user_id]["history"].append({"role": "user", "content": text_received})

    # Если это наш целевой чат -1001708694298
    if chat_id == -1001708694298:
        # Инициализируем счётчик, если не было
        if chat_id not in chat_message_counter:
            chat_message_counter[chat_id] = 0
        
        # Увеличиваем счётчик для этого чата
        chat_message_counter[chat_id] += 1

        # Если сообщение пятое, отвечаем
        if chat_message_counter[chat_id] % 5 == 0:
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = build_prompt(user_id)
                gen_response = model.generate_content(prompt)
                response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, я не могу сейчас ответить."
            except Exception as e:
                logger.error(f"Ошибка при генерации ответа для пользователя {user_id}: {e}", exc_info=True)
                response = "Произошла ошибка. Попробуйте ещё раз."
            
            # Добавляем ответ бота в историю
            user_states[user_id]["history"].append({"role": "bot", "content": response})
            await update.message.reply_text(response)
        else:
            # Если не пятое — просто не отвечаем
            return
    else:
        # Логика для ЛС или других чатов: бот продолжает отвечать на каждое сообщение, как и прежде
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = build_prompt(user_id)
            gen_response = model.generate_content(prompt)
            response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, я не могу сейчас ответить."
        except Exception as e:
            logger.error(f"Ошибка при генерации ответа для пользователя {user_id}: {e}", exc_info=True)
            response = "Произошла ошибка. Попробуйте ещё раз."
        
        user_states[user_id]["history"].append({"role": "bot", "content": response})
        await update.message.reply_text(response)

# 9. Основная точка входа
def main() -> None:
    try:
        application = Application.builder().token(telegram_token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Бот запущен и готов к работе через polling.")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

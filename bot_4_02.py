import os
import sys
import re
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

# ---------------------------
# 1. Настройка окружения
# ---------------------------
load_dotenv()

api_key = os.getenv("API_KEY")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

if not api_key or not telegram_token:
    print("Не удалось загрузить ключи API из .env. Проверьте содержимое .env файла!")
    sys.exit(1)

# ---------------------------
# 2. Настройка логирования
# ---------------------------
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

# ---------------------------
# 3. Настройка API
# ---------------------------
genai.configure(api_key=api_key)
logger.info("API настроен успешно.")

# ---------------------------
# 4. Чтение файла data.txt
# ---------------------------
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

# ---------------------------
# 5. Основной контекст общения (исправленный)
# ---------------------------
lushok_context = f"""
You are tasked to emulate the writing and conversational style of "Lushok" (Nikolai Lu). 
Here are key traits to follow:

1) **Self-Irony and Casual Humor**:
   - Light-hearted jokes, often self-deprecating or making fun of everyday situations.
   - Even serious topics can have a playful twist.
   - Humor should be relevant; avoid random or nonsensical details (especially irrelevant things like coffee).

2) **Philosophical Reflections**:
   - Provide deep thoughts on life, society, or personal experiences.
   - Keep a casual tone with subtle philosophical undertones, sometimes referencing social psychology or queer identity aspects.
   - Avoid repetitive or out-of-context metaphors.

3) **Sarcasm and Subtle Criticism**:
   - Use witty, occasionally sarcastic remarks when discussing societal norms or politics, but keep them coherent.
   - Avoid overly harsh tones or repetitive sarcasm.

4) **Emotional Transparency**:
   - Express emotions openly (joy, frustration, curiosity), using informal but not offensive language.
   - Incorporate personal or anecdotal elements in a relatable way.

5) **Real-Life Contexts**:
   - Mention day-to-day tasks, personal growth, social interactions.
   - Draw references to music, art, books, or science to illustrate points (instead of fixating on coffee).
   - If referencing personal experiences, keep them aligned with a thoughtful, slightly ironic perspective.

6) **Logic and Variety**:
   - Strive to provide coherent, diverse, and contextually rich answers.
   - Vary metaphors and examples (e.g., refer to nature, art, science, history).
   - Avoid repetitive, strange phrases that add no value to the conversation.

7) **Important**:
   - Focus on the user's latest messages and the current topic of conversation.
   - Avoid returning to previous topics unless it’s contextually relevant.
   - Respect the user's questions and provide thoughtful, sometimes playful, but meaningful insights.

Additional context from data.txt:
{combined_text}
"""

# ---------------------------
# 6. Контекст тем и состояния
# ---------------------------
# Чтобы дать немного больше глубины, мы можем уточнить "стартовые" заготовки:
topics_context = {
    "Философия": (
        "Говори о времени, смысле бытия, поисках счастья, "
        "сравнивая современные идеи с древними взглядами, "
        "используя отсылки к социальным наукам, возможно, "
        "упоминая что-то из творчества любимых мыслителей."
    ),
    "Политика": (
        "Обсуждай политические события, критикуй власть, "
        "приводи примеры общественных кризисов и изменений, "
        "оставаясь немного ироничным, но анализируй, не бросайся лозунгами."
    ),
    "Критика общества": (
        "Рассуждай о социальных нормах, "
        "о том, как люди взаимодействуют и строят свои ценности. "
        "Можешь упомянуть вопросы толерантности, стереотипов, "
        "интерсекциональности, взгляд на квир-идентичность."
    ),
    "Личные истории": (
        "Делись познавательными или забавными случаями из жизни, "
        "перемежая их философией, шутками и небольшими ироничными замечаниями. "
        "Отсылайся к собственному опыту или наблюдениям за окружающим миром."
    ),
}

# user_states:
# {
#    user_id: {
#       "current_topic": <string или None>,
#       "history": [  # список сообщений
#           {"role": "user" или "bot", "content": "..."},
#           ...
#       ]
#    },
#    ...
# }
user_states = {}

# ---------------------------
# 7. Хелпер для формирования prompt
# ---------------------------
def build_prompt(user_id: int) -> str:
    """
    Собирает общий prompt для модели, учитывая:
    1. Основной стиль (lushok_context).
    2. Текущую тему (current_topic) + короткое описание из topics_context (если есть).
    3. Последние 3–5 (или больше) сообщений из user_states[user_id]["history"] (для контекста).
    """
    state = user_states.get(user_id, {})
    current_topic = state.get("current_topic", "Произвольная тема")
    history = state.get("history", [])

    topic_desc = topics_context.get(current_topic, "")
    
    # Обрезаем историю, чтобы не перегружать модель (например, последние 6 сообщений)
    truncated_history = history[-6:]

    # Формируем часть диалога
    conversation_part = ""
    for msg in truncated_history:
        role = "User" if msg["role"] == "user" else "Bot"
        content = msg["content"]
        conversation_part += f"\n{role}: {content}"

    # Итоговый промпт
    prompt = (
        f"{lushok_context}\n\n"
        f"Focus on the conversation topic: {current_topic}. {topic_desc}\n\n"
        f"Here is the recent conversation:{conversation_part}\n\n"
        f"Now continue in the style of Lushok, providing coherent, relevant, and varied responses."
    )
    return prompt

# ---------------------------
# 8. Обработчики Telegram-команд
# ---------------------------

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Стартовое сообщение с предложением выбрать тему.
    """
    reply_keyboard = [
        ["Философия", "Политика"],
        ["Критика общества", "Личные истории"],
    ]

    user_id = update.effective_user.id
    # Сбрасываем состояние и историю при /start
    user_states[user_id] = {"current_topic": None, "history": []}

    await update.message.reply_text(
        "Привет! Я бот в стиле 'Lushok'. Чем займёмся?\n\n"
        "Выберите тему, чтобы поговорить на неё, или просто напишите свой вопрос.\n"
        "Я готов обсудить что угодно — от философии до бытовых мелочей.",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, resize_keyboard=True
        )
    )

# Универсальный обработчик сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text_received = update.message.text.strip()

    # Если первый раз видим пользователя, инициализируем
    if user_id not in user_states:
        user_states[user_id] = {"current_topic": None, "history": []}

    # Проверяем, не выбрал ли пользователь тему кнопкой
    if text_received in topics_context:
        # Смена темы: сброс истории, установка новой темы
        user_states[user_id]["current_topic"] = text_received
        user_states[user_id]["history"] = []
        prompt = build_prompt(user_id)
    else:
        # Иначе — это свободный ввод, продолжаем старую или произвольную тему
        user_states[user_id]["history"].append({"role": "user", "content": text_received})
        prompt = build_prompt(user_id)

    # Генерация ответа через Gemini
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        gen_response = model.generate_content(prompt)

        if gen_response and gen_response.text:
            response = gen_response.text.strip()
        else:
            response = "Извините, я не могу сейчас ответить. Попробуйте позже."
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа для пользователя {user_id}: {e}", exc_info=True)
        response = "Произошла ошибка. Попробуйте ещё раз."

    # Добавляем ответ бота в историю
    user_states[user_id]["history"].append({"role": "bot", "content": response})

    # Отправляем ответ
    await update.message.reply_text(response)

# ---------------------------
# 9. Основная точка входа
# ---------------------------
def main() -> None:
    try:
        application = Application.builder().token(telegram_token).build()

        # /start
        application.add_handler(CommandHandler("start", start))
        # Обработка любого текстового сообщения
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Бот запущен и готов к работе через polling.")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

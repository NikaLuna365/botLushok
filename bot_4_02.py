import os
import sys
import logging
import base64
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

# -- Встроенные ключи (для тестового бота) --
TELEGRAM_BOT_TOKEN = "7211227866:AAGXvLKse9pd8Jq9NllbdPlrmSUD9lCYHOU"
GEMINI_API_KEY = "AIzaSyBxh0v7z4VO2T3wTbs788XRL1tHOBHXgBg"

api_key = GEMINI_API_KEY
telegram_token = TELEGRAM_BOT_TOKEN

if not api_key or not telegram_token:
    print("Не удалось загрузить ключи API. Проверьте наличие!")
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

# Настройка Gemini API
genai.configure(api_key=api_key)
logger.info("Gemini API настроен успешно.")

# Попытка прочитать дополнительный текстовый контекст
file_path = "./data.txt"
try:
    result = from_path(file_path).best()
    if result:
        combined_text = str(result)
        logger.info("Текст из файла data.txt успешно прочитан.")
    else:
        combined_text = ""
        logger.warning("Файл data.txt пуст или не читается.")
except FileNotFoundError:
    combined_text = ""
    logger.warning("Файл data.txt не найден.")
except Exception as e:
    combined_text = ""
    logger.critical(f"Ошибка при чтении data.txt: {e}")

# Базовый контекст стиля Lushok
lushok_context = f"""
You are tasked to emulate the writing style of "Lushok" (Nikolai Lu). 
Key traits:
- Self-irony and casual humor
- Philosophical reflections
- Sarcasm and subtle criticism
- Emotional transparency
- Real-life contexts
- Logic and variety

Additional context from data.txt:
{combined_text}
"""

topics_context = {
    "Философия": "Говори о времени, смысле бытия, поисках счастья и сравнивай с древними взглядами.",
    "Политика": "Обсуждай политические события, критикуй власть, приводи примеры общественных кризисов.",
    "Критика общества": "Рассуждай о социальных нормах, стереотипах и ценностях.",
    "Личные истории": "Делись забавными случаями из жизни, перемежая их философией и иронией.",
}

# Хранилище состояний пользователей (тема и история диалога)
user_states = {}

def build_prompt(user_id: int) -> str:
    """Собираем итоговый prompt для генерации текста."""
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
        f"Recent conversation:{conversation_part}\n\n"
        "You must respond in **Russian** language, continuing in the style of Lushok.\n"
        "Do not switch to English.\n"
        "Now continue in the style of Lushok, providing coherent, relevant, and varied responses."
    )
    return prompt

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
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
    """Обработка текстовых сообщений."""
    user_id = update.effective_user.id
    text_received = update.message.text.strip()
    
    # Гарантируем, что у пользователя есть запись в user_states
    if user_id not in user_states:
        user_states[user_id] = {"current_topic": None, "history": []}
    
    if text_received in topics_context:
        # Если пользователь выбрал одну из тем
        user_states[user_id]["current_topic"] = text_received
        user_states[user_id]["history"] = []
    else:
        # Иначе это обычное сообщение
        user_states[user_id]["history"].append({"role": "user", "content": text_received})
    
    prompt = build_prompt(user_id)
    
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        gen_response = model.generate_content(prompt)
        response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, я не могу сейчас ответить."
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа для пользователя {user_id}: {e}", exc_info=True)
        response = "Произошла ошибка. Попробуйте ещё раз."
    
    user_states[user_id]["history"].append({"role": "bot", "content": response})
    await update.message.reply_text(response)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка фотографий, отправляемых пользователем."""
    user_id = update.effective_user.id
    
    # Важно: инициализируем запись в user_states, чтобы избежать KeyError
    if user_id not in user_states:
        user_states[user_id] = {"current_topic": None, "history": []}
    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # Сохраняем фото во временный файл
    temp_file_path = f"temp_{photo.file_id}.jpg"
    await file.download_to_drive(custom_path=temp_file_path)
    
    # Проверяем, есть ли в caption упоминание "подпись" (режим extended)
    caption = update.message.caption.lower() if update.message.caption else ""
    mode = "extended" if "подпись" in caption else "short"
    
    try:
        # Читаем файл и кодируем в base64
        with open(temp_file_path, "rb") as f:
            img_data = f.read()
        img_base64 = base64.b64encode(img_data).decode("utf-8")
        
        # Собираем текстовый контекст так же, как при текстовых сообщениях
        prompt_text = build_prompt(user_id)
        
        # Добавляем инструкцию для изображения
        image_instructions = (
            f"{prompt_text}\n\n"
            "Вложения: изображение. "
            "Опиши или интерпретируй его на русском языке, сохраняя стиль Lushok. "
            f"Режим ответа: {mode}."
        )
        
        # Формируем мультимодальный запрос
        multimodal_request = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": image_instructions
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": img_base64
                            }
                        }
                    ]
                }
            ]
        }
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        gen_response = model.generate_content(**multimodal_request)
        
        if gen_response and gen_response.text:
            response_text = gen_response.text.strip()
        else:
            response_text = "Извините, не удалось получить ответ по изображению."
        
        # Добавляем в историю
        user_states[user_id]["history"].append({"role": "user", "content": "[Изображение]"})
        user_states[user_id]["history"].append({"role": "bot", "content": response_text})
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения для пользователя {user_id}: {e}", exc_info=True)
        response_text = "Произошла ошибка при обработке изображения. Попробуйте позже."
    finally:
        # Удаляем временный файл
        try:
            os.remove(temp_file_path)
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {temp_file_path}: {e}")
    
    await update.message.reply_text(response_text)

def main() -> None:
    """Запуск бота."""
    try:
        application = Application.builder().token(telegram_token).build()
        
        # Регистрируем хендлеры
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        logger.info("Бот запущен и готов к работе через polling.")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

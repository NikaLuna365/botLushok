import os
import sys
import logging
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

# 5. Основной «русский» контекст для ИИ
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
- Если пользователь пишет боту напрямую (личные сообщения) или обращается к нему в групповом чате (например, через reply на сообщение бота), отвечай всегда (100%).
Дополнительный контент из data.txt:
{combined_text}
"""

# 6. Хранение последних 5 сообщений в каждом чате
chat_context: dict[int, list[dict[str, any]]] = {}

# 7. Формирование промпта с учётом последних 5 сообщений чата
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

# 8. Обработчики команд и сообщений
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_keyboard = [
        ["Философия", "Политика"],
        ["Критика общества", "Личные истории"],
    ]
    await update.message.reply_text(
        "Привет! Я бот, общающийся в стиле Николая Лу. Можешь выбрать тему или просто задать вопрос.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text_received = update.message.text.strip()

    # Сохраняем сообщение в истории чата (до 5 последних)
    if chat_id not in chat_context:
        chat_context[chat_id] = []
    chat_context[chat_id].append({"user": user_id, "text": text_received})
    if len(chat_context[chat_id]) > 5:
        chat_context[chat_id].pop(0)

    # Определяем необходимость ответа:
    # - В личном чате всегда отвечаем.
    # - В групповом чате отвечаем, если сообщение является ответом на сообщение бота.
    if update.effective_chat.type == "private":
        should_respond = True
    elif (update.message.reply_to_message and 
          update.message.reply_to_message.from_user and 
          update.message.reply_to_message.from_user.id == context.bot.id):
        should_respond = True
    else:
        should_respond = False

    if not should_respond:
        return

    # Формирование промпта и генерация ответа
    prompt = build_prompt(chat_id)
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        gen_response = model.generate_content(prompt)
        response = gen_response.text.strip() if gen_response and gen_response.text else "Извините, у меня нет ответа."
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа: {e}", exc_info=True)
        response = "Произошла ошибка. Попробуйте ещё раз."

    await update.message.reply_text(response)

# 9. Запуск бота
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

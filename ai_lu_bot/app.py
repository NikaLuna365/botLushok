# ai_lu_bot/app.py
import logging
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatType # Добавили ChatType

# Удаляем импорт из bot_4_02
# from bot_4_02 import start # Удалить или закомментировать

# Импортируем перенесенную функцию start из message.py
from ai_lu_bot.handlers.message import handle_message, start # Импортируем обе функции
from ai_lu_bot.services.gemini import GeminiService

# -----------------------------------------------------------------------------
# Загрузка .env и настройка логов
# -----------------------------------------------------------------------------
# load_dotenv() # Убедитесь, что load_dotenv вызывается только один раз, например, в этом файле.

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("API_KEY") # Также нужен здесь для проверки инициализации сервиса

if not BOT_TOKEN:
    print("CRITICAL: TELEGRAM_BOT_TOKEN не найден в окружении", file=sys.stderr)
    sys.exit(1)
if not API_KEY:
    print("CRITICAL: API_KEY не найден в окружении", file=sys.stderr)
    sys.exit(1)


LOG_DIR = Path("logs")
# Проверяем существование папки перед созданием, чтобы избежать ошибки
if not LOG_DIR.exists():
    try:
        LOG_DIR.mkdir(exist_ok=True) # Используем exist_ok=True для безопасности
    except OSError as e:
        print(f"CRITICAL: Не удалось создать директорию logs: {e}", file=sys.stderr)
        # Возможно, стоит выйти или работать без файловых логов
        # sys.exit(1) # Можно добавить выход, если логирование критично
        pass # Иначе продолжаем без файловых логов

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Уровень логов по умолчанию

# Очищаем существующие хэндлеры, если они были добавлены где-то еще (маловероятно, но для чистоты)
if not logger.handlers:
    _formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_formatter)
    logger.addHandler(_sh)
    # Добавляем файловый хэндлер только если директория logs существует
    if LOG_DIR.exists():
        try:
            _fh = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
            _fh.setFormatter(_formatter)
            logger.addHandler(_fh)
        except Exception as e:
            print(f"WARNING: Не удалось настроить файловый логгер: {e}", file=sys.stderr)


# -----------------------------------------------------------------------------
# Критическая обёртка (логика остается прежней)
# -----------------------------------------------------------------------------
def write_critical_log(exc: Exception) -> None:
    """Записывает полную трассировку в logs/critical_startup_error.log."""
    log_file = LOG_DIR / "critical_startup_error.log"
    try:
        # Проверяем, что директория logs существует, прежде чем писать файл
        if not LOG_DIR.exists():
             print(f"WARNING: Директория logs не существует, не могу записать критический лог в {log_file}", file=sys.stderr)
             traceback.print_exception(exc, file=sys.stderr) # Выводим в stderr как запасной вариант
             return

        with open(log_file, "a", encoding="utf-8") as f:
            log_time = logging.Formatter('%(asctime)s').format(logging.LogRecord(None, None, '', 0, '', (), None, None))
            f.write(f"\n{'-'*20} {log_time} {'-'*20}\n")
            f.write("Critical error during bot startup:\n")
            traceback.print_exception(exc, file=f)
            f.write(f"{'-'*40}\n")
        print(f"Critical startup error logged to {log_file}", file=sys.stderr)
    except Exception as e:
        print(f"CRITICAL: Failed to write critical startup log to {log_file}: {e}", file=sys.stderr)
        traceback.print_exception(exc, file=sys.stderr) # Выводим исходную ошибку в stderr


# -----------------------------------------------------------------------------
# Глобальный error handler (логика остается прежней)
# -----------------------------------------------------------------------------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик необработанных исключений."""
    logger.error("Unhandled exception in update", exc_info=context.error)
    # Опционально: уведомить пользователя, если есть чат
    try:
        # Проверяем, что effective_chat существует и имеет id
        if hasattr(update, 'effective_chat') and update.effective_chat and hasattr(update.effective_chat, 'id'):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Извини, произошла непредвиденная ошибка. Попробуй позже."
            )
        else:
             logger.warning("Error handler triggered but no effective_chat to send message.")
    except Exception as e:
        logger.error("Failed to send error message to user: %s", e)


# -----------------------------------------------------------------------------
# Сборка приложения
# -----------------------------------------------------------------------------
def build_application() -> Application:
    """Создаёт Application, регистрирует хэндлеры и сервисы."""
    logger.info("Building Telegram Application...")
    # Проверяем токен еще раз, хотя он уже проверялся выше
    if not BOT_TOKEN:
         logger.critical("BOT_TOKEN is not set during application build.")
         sys.exit(1) # Или raise

    app = Application.builder().token(BOT_TOKEN).build()

    # Инициализация GeminiService и сохранение в bot_data
    # Здесь может возникнуть исключение, если API_KEY невалиден
    try:
        gemini_service = GeminiService()
        app.bot_data["gemini"] = gemini_service
        logger.info("GeminiService initialized and added to bot_data.")
    except Exception as e:
         logger.critical(f"Failed to initialize GeminiService: {e}")
         # Re-raise the exception so the main() block can catch and log it critically
         raise e


    # Регистрация глобального error handler
    app.add_error_handler(global_error_handler)
    logger.info("Global error handler registered.")


    # Команда /start (импортируем из message.py)
    app.add_handler(CommandHandler("start", start))
    logger.info("Command handler for /start registered.")

    # Основной обработчик сообщений (handle_message уже импортирован)
    # Фильтры: текст, голос, видео-кружок, фото, подписи к медиа, пересланные сообщения
    # Работает в личных чатах, группах и супергруппах
    # Исключает команды
    message_filters = (
        filters.TEXT
        | filters.VOICE
        | filters.VIDEO_NOTE
        | filters.PHOTO
        | filters.CAPTION
        # Фильтр FORWARDED устарел в пользу Message.forward_from_chat, Message.forward_from_message_id и т.п.
        # Удалим filters.FORWARDED, логика обработки пересланных сообщений есть в handle_message
        # filters.FORWARDED
        | filters.ChatType.PRIVATE
        | filters.ChatType.GROUP
        | filters.ChatType.SUPERGROUP
    ) & (~filters.COMMAND)

    app.add_handler(
        MessageHandler(
            message_filters,
            handle_message,
        )
    )
    logger.info("Message handler for text, media, etc., registered.")

    return app


# -----------------------------------------------------------------------------
# Entry‑point
# -----------------------------------------------------------------------------
def main() -> None:
    logger.info("=== AI LU Bot Bootstrap Start ===")
    try:
        # Загрузка .env перед сборкой приложения, чтобы переменные были доступны
        load_dotenv()
        logger.info(".env file loaded.")

        application = build_application()
        logger.info("Telegram Application built successfully.")
        logger.info("Bot starting in polling mode...")
        # close_loop=False, чтобы PTB не пытался закрывать внешний loop
        # В большинстве случаев run_polling() блокирующий, close_loop=False нужен для async/await в handlers
        application.run_polling(close_loop=False, stop_signals=None) # stop_signals=None чтобы PTB обрабатывал сигналы завершения
        logger.info("Bot polling stopped.")

    except Exception as exc:
        # Эта ветка ловит ошибки при инициализации (например, API KEY) или критические ошибки до запуска polling
        logger.critical("CRITICAL: Startup failure: %s", exc, exc_info=True)
        write_critical_log(exc) # Записываем в отдельный файл
        sys.exit(1) # Завершаем работу с ошибкой


if __name__ == "__main__":
    logger.info(f"--- Script {__file__} started ---")
    main()
    logger.info(f"--- Script {__file__} finished ---")

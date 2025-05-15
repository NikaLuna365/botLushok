# ai_lu_bot/app.py
import logging
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import (
    Application, # Импортируем Application
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatType

# Импортируем хэндлер сообщений и команду start
from ai_lu_bot.handlers.message import handle_message, start
# Импортируем GeminiService
from ai_lu_bot.services.gemini import GeminiService
# Импортируем обе реализации менеджера контекста и константу
from ai_lu_bot.core.context import InMemoryChatContextManager, RedisChatContextManager, MAX_CONTEXT_MESSAGES


# -----------------------------------------------------------------------------
# Загрузка .env и Настройка логов
# -----------------------------------------------------------------------------
load_dotenv()
# Переменные окружения для Telegram и Gemini
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
# Переменные окружения для выбора хранилища контекста и его настроек Redis
CONTEXT_STORAGE_TYPE = os.getenv("CONTEXT_STORAGE_TYPE", "memory").lower()
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

# Проверка критически важных переменных
if not BOT_TOKEN:
    print("CRITICAL: TELEGRAM_BOT_TOKEN не найден в окружении", file=sys.stderr)
    sys.exit(1)
if not API_KEY:
    print("CRITICAL: API_KEY не найден в окружении", file=sys.stderr)
    sys.exit(1)
# Проверка типа хранилища контекста
if CONTEXT_STORAGE_TYPE not in ["memory", "redis"]:
    print(f"CRITICAL: Неизвестный тип хранилища контекста: {CONTEXT_STORAGE_TYPE}. Используйте 'memory' или 'redis'.", file=sys.stderr)
    sys.exit(1)


# Настройка директории логов
LOG_DIR = Path("logs")
if not LOG_DIR.exists():
    try:
        LOG_DIR.mkdir(exist_ok=True)
    except OSError as e:
        print(f"CRITICAL: Не удалось создать директорию logs: {e}", file=sys.stderr)
        pass # Продолжаем без файловых логов, если не удалось создать директорию

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Настройка логгеров (консольный и файловый)
if not logger.handlers: # Добавляем хэндлеры только если их еще нет
    _formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_formatter)
    logger.addHandler(_sh)
    if LOG_DIR.exists(): # Добавляем файловый хэндлер только если директория логов существует
        try:
            _fh = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
            _fh.setFormatter(_formatter)
            logger.addHandler(_fh)
        except Exception as e:
            print(f"WARNING: Не удалось настроить файловый логгер: {e}", file=sys.stderr)


# -----------------------------------------------------------------------------
# Критическая обёртка для логирования ошибок запуска
# -----------------------------------------------------------------------------
def write_critical_log(exc: Exception) -> None:
    """Записывает полную трассировку критических ошибок запуска в logs/critical_startup_error.log."""
    log_file = LOG_DIR / "critical_startup_error.log"
    try:
        if not LOG_DIR.exists():
             print(f"WARNING: Директория logs не существует, не могу записать критический лог в {log_file}", file=sys.stderr)
             traceback.print_exception(exc, file=sys.stderr)
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
        traceback.print_exception(exc, file=sys.stderr)


# -----------------------------------------------------------------------------
# Глобальный error handler
# -----------------------------------------------------------------------------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик необработанных исключений в хэндлерах."""
    logger.error("Unhandled exception in update", exc_info=context.error)
    try:
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
# Сборка приложения Telegram Application
# -----------------------------------------------------------------------------
def build_application() -> Application:
    """
    Создаёт и конфигурирует Application.
    Инициализирует и сохраняет сервисы (GeminiService, ChatContextManager) в bot_data.
    Регистрирует хэндлеры.
    """
    logger.info("Building Telegram Application...")

    # --- Создание Application ---
    # Используем BOT_TOKEN, который уже проверен
    app = Application.builder().token(BOT_TOKEN).build()
    logger.info("Telegram Application instance created.")

    # --- Инициализация сервисов ---
    # Инициализация GeminiService
    # Проверка API_KEY уже была выше, но сервис может упасть и при конфигурации
    try:
        gemini_service = GeminiService()
        # Сохраняем инстанс сервиса в bot_data, чтобы он был доступен в хэндлерах
        app.bot_data["gemini_service"] = gemini_service
        logger.info("GeminiService initialized and added to app.bot_data.")
    except Exception as e:
         logger.critical(f"Failed to initialize GeminiService: {e}")
         # Перебрасываем исключение, чтобы его поймал главный блок main()
         raise e # Критическая ошибка, останавливаемся

    # Инициализация Менеджера Контекста на основе переменной окружения
    chat_context_manager_instance = None
    if CONTEXT_STORAGE_TYPE == "memory":
        logger.info("Using InMemoryChatContextManager for context storage.")
        chat_context_manager_instance = InMemoryChatContextManager(max_messages=MAX_CONTEXT_MESSAGES)
    elif CONTEXT_STORAGE_TYPE == "redis":
        logger.info(f"Using RedisChatContextManager for context storage (redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}).")
        try:
            chat_context_manager_instance = RedisChatContextManager(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                max_messages=MAX_CONTEXT_MESSAGES
            )
            # Проверяем, успешно ли подключились к Redis внутри менеджера
            # Если Redis выбран, но менеджер не смог подключиться, это критическая ошибка
            if chat_context_manager_instance._redis_client is None:
                 raise RuntimeError(f"RedisChatContextManager failed to connect to Redis at {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}.")
        except Exception as e:
            logger.critical(f"Failed to initialize RedisChatContextManager: {e}")
            # Если Redis выбран, но менеджер не смог инициализироваться/подключиться, это критическая ошибка запуска
            raise e # Критическая ошибка, останавливаемся

    # Сохраняем инстанс менеджера контекста в bot_data
    app.bot_data["chat_context_manager"] = chat_context_manager_instance
    logger.info(f"{type(chat_context_manager_instance).__name__} initialized and added to app.bot_data.")


    # --- Регистрация хэндлеров ---
    # Глобальный error handler
    app.add_error_handler(global_error_handler)
    logger.info("Global error handler registered.")

    # Команда /start
    app.add_handler(CommandHandler("start", start))
    logger.info("Command handler for /start registered.")

    # Основной обработчик сообщений
    message_filters = (
        filters.TEXT
        | filters.VOICE
        | filters.VIDEO_NOTE
        | filters.PHOTO
        | filters.CAPTION
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

    # Возвращаем сконфигурированный объект Application
    return app


# -----------------------------------------------------------------------------
# Entry‑point
# -----------------------------------------------------------------------------
def main() -> None:
    """Главная точка входа приложения. Инициализирует и запускает бота."""
    logger.info(f"--- Script {__file__} started ---")
    logger.info("=== AI LU Bot Bootstrap Start ===")

    application = None # Объявляем переменную application здесь

    try:
        # Вызываем build_application для создания и полной настройки объекта Application
        # build_application теперь возвращает объект Application
        application = build_application()

        logger.info("Telegram Application built successfully.")
        logger.info("Bot starting in polling mode...")

        # Запускаем бота в режиме polling.
        # application уже определен благодаря build_application
        application.run_polling(close_loop=False, stop_signals=None)
        logger.info("Bot polling stopped gracefully.")

    except Exception as exc:
        # Ловим любые исключения, произошедшие во время bootstrap (до запуска polling)
        logger.critical("CRITICAL: Startup failure: %s", exc, exc_info=True)
        write_critical_log(exc) # Записываем в отдельный лог
        sys.exit(1) # Завершаем работу с ошибкой

    logger.info(f"--- Script {__file__} finished ---")


if __name__ == "__main__":
    main()

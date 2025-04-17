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

# Импортируем /start из старого монолита (там промпт и старт остались без изменений)
from bot_4_02 import start  
from ai_lu_bot.handlers.message import handle_message
from ai_lu_bot.services.gemini import GeminiService

# -----------------------------------------------------------------------------
# Загрузка .env и настройка логов
# -----------------------------------------------------------------------------
load_dotenv()  # .env на сервере/ПК, в репо его нет

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("CRITICAL: TELEGRAM_BOT_TOKEN не найден в окружении", file=sys.stderr)
    sys.exit(1)

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
_sh = logging.StreamHandler()
_sh.setFormatter(_formatter)
logger.addHandler(_sh)
_fh = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
_fh.setFormatter(_formatter)
logger.addHandler(_fh)


# -----------------------------------------------------------------------------
# Критическая обёртка
# -----------------------------------------------------------------------------
def write_critical_log(exc: Exception) -> None:
    """Записывает полную трассировку в logs/critical_startup_error.log."""
    try:
        with open(LOG_DIR / "critical_startup_error.log", "a", encoding="utf-8") as f:
            f.write(f"\n{'-'*40}\n")
            traceback.print_exception(exc, file=f)
            f.write(f"{'-'*40}\n")
    except Exception as e:
        print("Failed to write critical startup log:", e, file=sys.stderr)


# -----------------------------------------------------------------------------
# Глобальный error handler
# -----------------------------------------------------------------------------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception in update", exc_info=context.error)
    # Опционально: уведомить пользователя
    try:
        if getattr(update, "effective_chat", None):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Извини, произошла непредвиденная ошибка. Попробуй позже."
            )
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Сборка приложения
# -----------------------------------------------------------------------------
def build_application() -> Application:
    """Создаёт Application, регистрирует хэндлеры и сервисы."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Инициализация GeminiService и сохранение в bot_data
    gemini_service = GeminiService()
    app.bot_data["gemini"] = gemini_service

    # Регистрация глобального error handler
    app.add_error_handler(global_error_handler)

    # Команда /start
    app.add_handler(CommandHandler("start", start))

    # Основной обработчик сообщений
    app.add_handler(
        MessageHandler(
            (
                filters.TEXT
                | filters.VOICE
                | filters.VIDEO_NOTE
                | filters.PHOTO
                | filters.CAPTION
                | filters.FORWARDED
                | filters.ChatType.PRIVATE
                | filters.ChatType.GROUP
                | filters.ChatType.SUPERGROUP
            )
            & (~filters.COMMAND),
            handle_message,
        )
    )

    return app


# -----------------------------------------------------------------------------
# Entry‑point
# -----------------------------------------------------------------------------
def main() -> None:
    logger.info("=== AI LU Bot bootstrap ===")
    try:
        application = build_application()
        logger.info("Бот запускается в режиме polling…")
        # close_loop=False, чтобы PTB не пытался закрывать внешний loop
        application.run_polling(close_loop=False)
    except Exception as exc:
        logger.critical("Startup failure: %s", exc, exc_info=True)
        write_critical_log(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

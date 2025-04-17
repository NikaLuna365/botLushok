# ai_lu_bot/app.py
# Точка входа в приложение AI LU Bot — polling‑режим.
# Убедитесь, что файл лежит внутри пакета ai_lu_bot/:
# ai_lu_bot/
# ├─ __init__.py
# ├─ app.py            ← этот файл
# ├─ handlers/
# │   └─ message.py    (содержит handle_message)
# └─ ...

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
)

# Поправка: start ещё не перенесён в handlers/message.py,
# поэтому импортируем его из корневого bot_4_02.py
from bot_4_02 import start        # <-- здесь теперь берём start
from ai_lu_bot.handlers.message import handle_message  # handle_message в handlers

# -----------------------------------------------------------------------------
# ЛОГИРОВАНИЕ И ОКРУЖЕНИЕ
# -----------------------------------------------------------------------------
load_dotenv()  # .env в репо нет — будет на сервере или локально

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
# Консоль
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)
# Файл
fh = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
fh.setFormatter(fmt)
logger.addHandler(fh)


def write_critical_log(exc: Exception) -> None:
    """Записывает стек в logs/critical_startup_error.log при падении на старте."""
    try:
        with (LOG_DIR / "critical_startup_error.log").open("a", encoding="utf-8") as f:
            f.write(f"{'-'*40}\n")
            traceback.print_exception(exc, file=f)
            f.write(f"{'-'*40}\n\n")
    except Exception as e:
        print("Не удалось записать critical_startup_error.log:", e, file=sys.stderr)


def build_application() -> Application:
    """Создаёт и настраивает telegram.ext.Application."""
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в окружении")
    app = Application.builder().token(BOT_TOKEN).build()

    # Команда /start
    app.add_handler(CommandHandler("start", start))

    # Основной поток сообщений
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


def main() -> None:
    """Инициализация и запуск бота (polling)."""
    logger.info("=== AI LU Bot bootstrap ===")
    try:
        application = build_application()
        logger.info("Бот запускается в режиме polling…")
        # run_polling — синхронно блокирует текущий поток, сам управляет event loop
        application.run_polling(close_loop=False)
    except Exception as exc:
        logger.critical("Startup failure: %s", exc, exc_info=True)
        write_critical_log(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

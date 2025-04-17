# ai_lu_bot/app.py
# Точка входа в приложение AI LU Bot (polling‑режим).
# ВНИМАНИЕ: файл должен лежать внутри пакета ai_lu_bot/
# ├─ ai_lu_bot/
# │  ├─ __init__.py
# │  ├─ app.py          ← ЭТОТ ФАЙЛ
# │  ├─ handlers/
# │  ├─ core/
# │  ├─ services/
# │  └─ ...

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

# --- ЛОКАЛЬНЫЕ ИМПОРТЫ ---
from ai_lu_bot.handlers.message import start, handle_message  # noqa: E402

# -----------------------------------------------------------------------------
# НАСТРОЙКА ОКРУЖЕНИЯ И ЛОГИРОВАНИЕ
# -----------------------------------------------------------------------------
load_dotenv()  # .env может отсутствовать в репо — он на сервере/ПК

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Создаём папку logs, если нет
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

fmt = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
# Консоль
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)
# Файл
fh = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
fh.setFormatter(fmt)
logger.addHandler(fh)


# -----------------------------------------------------------------------------
# ФУНКЦИИ
# -----------------------------------------------------------------------------
def write_critical_log(exc: Exception) -> None:
    """
    Записывает критическую ошибку запуска в отдельный файл
    logs/critical_startup_error.log
    """
    try:
        with (LOG_DIR / "critical_startup_error.log").open("a", encoding="utf-8") as f:
            f.write(f"{'-'*40}\n")
            traceback.print_exception(exc, file=f)
            f.write(f"{'-'*40}\n\n")
    except Exception as log_err:  # noqa: BLE001
        # Если даже это не удалось — выводим в консоль
        print("Не удалось записать critical_startup_error.log:", log_err, file=sys.stderr)


def build_application() -> Application:
    """
    Создаёт экземпляр telegram.ext.Application, регистрирует хэндлеры.
    THROWS: любые исключения наружу (обработаются в main()).
    """
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в переменных окружения")

    app = Application.builder().token(BOT_TOKEN).build()

    # /start
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


def main() -> None:  # noqa: D401
    """Инициализирует и запускает бота Telegram."""
    logger.info("=== AI LU Bot bootstrap ===")

    try:
        application = build_application()

        logger.info("Бот запускается в режиме polling…")
        # ВАЖНО: run_polling() — синхронная блокирующая функция,
        # сама управляет event‑loop‑ом, поэтому её НЕ нужно оборачивать
        # в asyncio.run / await.
        application.run_polling(close_loop=False)  # close_loop=False — PTB‑реком.
    except Exception as exc:  # noqa: BLE001
        logger.critical("Startup failure: %s", exc, exc_info=True)
        write_critical_log(exc)
        sys.exit(1)


# -----------------------------------------------------------------------------
# CLI entry‑point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # При прямом запуске `python -m ai_lu_bot.app`
    main()

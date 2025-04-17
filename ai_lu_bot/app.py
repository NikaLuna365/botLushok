"""Entry point: sets up PTB application and runs polling or webhook."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from contextlib import suppress

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .handlers.message import handle_message, start_cmd
from .services.gemini import GeminiService

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

load_dotenv()

API_KEY = os.getenv("API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    print("TELEGRAM_BOT_TOKEN missing!")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
async def _run() -> None:
    gemini = GeminiService(API_KEY) if API_KEY else None  # type: ignore[arg-type]
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.VOICE | filters.VIDEO_NOTE | filters.PHOTO | filters.CAPTION | filters.FORWARDED)
            & (~filters.COMMAND),
            handle_message,
        )
    )
    app.bot_data["gemini"] = gemini
    await app.run_polling()

# ── critical wrapper (from original) ──────────────────────

def main() -> None:  # noqa: D401
    try:
        asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        logger.critical("Startup failure: %s", e, exc_info=True)
        try:
            os.makedirs("logs", exist_ok=True)
            with open("logs/critical_startup_error.log", "a", encoding="utf-8") as f:
                f.write("-" * 40 + "\n")
                traceback.print_exc(file=f)
        except Exception as log_err:  # pragma: no cover
            print("Failed to write critical_startup_error.log:", log_err)
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

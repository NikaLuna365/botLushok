# ai_lu_bot/services/gemini.py
import logging
import os
import traceback
from typing import Any, List, Optional, Union

import google.generativeai as genai
from dotenv import load_dotenv

from bot_4_02 import build_prompt  # Промпт из монолита

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Обёртка над google.generativeai с детальной обработкой ошибок.
    Один инстанс на всё приложение.
    """

    def __init__(self):
        load_dotenv()
        api_key = os.getenv("API_KEY")
        if not api_key:
            raise RuntimeError("API_KEY не найден в окружении")
        genai.configure(api_key=api_key)
        logger.info("GeminiService: Gemini API configured")

    async def generate_response(
        self,
        chat_id: int,
        target_message: Any,
        trigger: str,
        media_type: Optional[str],
        media_bytes: Optional[bytes],
        mime_type: Optional[str],
    ) -> str:
        """
        Генерирует ответ, обрабатывая:
         - блокировки prompt_feedback.block_reason
         - ошибки API key, quota, model not found, 5xx, timeout
        """
        content = [build_prompt(chat_id, target_message, trigger, media_type, media_bytes)]
        if media_bytes and mime_type:
            content.append({"mime_type": mime_type, "data": media_bytes})

        try:
            model = genai.GenerativeModel("gemini-1.5-flash-latest")
            response = await model.generate_content_async(
                content,
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                ],
                generation_config={"temperature": 0.75},
            )

            # Если текст пришёл
            if response.text:
                return response.text

            # Блокировка по safety
            if getattr(response, "prompt_feedback", None) and getattr(response.prompt_feedback, "block_reason", None):
                reason = response.prompt_feedback.block_reason
                logger.warning("Blocked by Gemini safety: %s", reason)
                return f"(Стоп. Ответ заблокирован: {reason}.)"

            # Собираем из частей
            parts = getattr(response, "parts", [])
            text = "".join(p.text for p in parts if getattr(p, "text", None))
            if text:
                return text

            logger.error("Empty response from Gemini")
            return "(ИИ промолчал. Попробуй переформулировать.)"

        except Exception as e:
            # Логируем стектрейс
            logger.error("Gemini API error", exc_info=True)
            err = str(e).lower()
            if "api key not valid" in err:
                return "(Бляха, ключ API неверен или истёк.)"
            if any(k in err for k in ("quota", "limit", "rate limit")):
                return "(Лимит запросов к ИИ исчерпан. Попробуй позже.)"
            if any(k in err for k in ("503", "internal server", "service unavailable")):
                return "(Серверы ИИ недоступны. Попробуй чуть позже.)"
            if any(k in err for k in ("timeout", "deadline")):
                return "(ИИ долго думает, но время вышло. Попробуй позже.)"
            if "model not found" in err:
                return "(Модель ИИ не найдена. Проверь конфиг.)"
            # По умолчанию
            return "(Произошла ошибка при генерации ответа. Попробуй позже.)"

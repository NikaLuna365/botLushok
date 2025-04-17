from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Any, List

import google.generativeai as genai

logger = logging.getLogger(__name__)

class GeminiAPIError(Enum):
    INVALID_KEY = auto()
    QUOTA = auto()
    SAFETY = auto()
    MODEL_NOT_FOUND = auto()
    SERVER = auto()
    TIMEOUT = auto()
    UNKNOWN = auto()

_ERROR_REPLIES = {
    GeminiAPIError.INVALID_KEY: "(Бляха, ключ API не тот или просрочен. Создатель, ау, разберись с этим!)",
    GeminiAPIError.QUOTA: "(Всё, приехали. Лимит запросов к ИИ исчерпан. Видимо, слишком много умных мыслей на сегодня.)",
    GeminiAPIError.SAFETY: "(Опять цензура! Мой гениальный запрос заблокировали. Неженки.)",
    GeminiAPIError.MODEL_NOT_FOUND: "(Модель, которой я должен думать, сейчас недоступна. Может, на техобслуживании?)",
    GeminiAPIError.SERVER: "(Серверы ИИ, похоже, легли отдохнуть. Позже попробуй.)",
    GeminiAPIError.TIMEOUT: "(Что-то ИИ долго думает, аж время вышло. Видимо, вопрос слишком сложный.)",
    GeminiAPIError.UNKNOWN: "(Какая-то техническая засада с ИИ. Попробуй позже.)",
}

class GeminiService:
    """Wrapper around google‑generativeai."""

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-1.5-flash-latest")

    async def generate(self, content_parts: List[Any]):
        try:
            resp = await self._model.generate_content_async(
                content_parts,
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                ],
                generation_config={"temperature": 0.75},
            )
            # Block‑reason check
            if hasattr(resp, "prompt_feedback") and resp.prompt_feedback and resp.prompt_feedback.block_reason:
                reason = resp.prompt_feedback.block_reason
                logger.warning("Gemini blocked response: %s", reason)
                return f"(Так, стоп. Мой ответ завернули из-за цензуры – причина '{reason}'. Ну и хрен с ними.)"
            return resp.text or "(ИИ выдал пустоту. Странно.)"
        except Exception as e:  # noqa: BLE001
            logger.error("Gemini error: %s", e, exc_info=True)
            return self._map_exception_to_reply(e)

    # ──────────────────────────────────────────────────────
    def _map_exception_to_reply(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "api key" in msg and "invalid" in msg:
            err = GeminiAPIError.INVALID_KEY
        elif "quota" in msg or "rate limit" in msg or "limit" in msg:
            err = GeminiAPIError.QUOTA
        elif "safety" in msg or "block" in msg:
            err = GeminiAPIError.SAFETY
        elif "model" in msg and "not found" in msg:
            err = GeminiAPIError.MODEL_NOT_FOUND
        elif "temporarily unavailable" in msg or "503" in msg or "internal server error" in msg or "500" in msg:
            err = GeminiAPIError.SERVER
        elif "deadline" in msg or "timeout" in msg:
            err = GeminiAPIError.TIMEOUT
        else:
            err = GeminiAPIError.UNKNOWN
        return _ERROR_REPLIES[err]


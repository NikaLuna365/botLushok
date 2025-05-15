# ai_lu_bot/services/gemini.py
import logging
import os
import traceback
from typing import Any, List, Optional, Union, Dict
from telegram import Message

import google.generativeai as genai
from dotenv import load_dotenv

from ai_lu_bot.core.prompt_builder import build_prompt # build_prompt уже импортирован корректно

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
            logger.critical("API_KEY не найден в окружении!")
            raise RuntimeError("API_KEY not found in environment")

        try:
            genai.configure(api_key=api_key)
            logger.info("GeminiService: Gemini API configured successfully.")
        except Exception as e:
            logger.critical(f"GeminiService: Failed to configure Gemini API: {e}", exc_info=True)
            raise RuntimeError(f"Failed to configure Gemini API: {e}")


    async def generate_response(
        self,
        chat_id: int,
        messages: List[Dict[str, Any]],
        target_message: Message,
        replied_to_message: Optional[Message] = None, # !!! ДОБАВЛЕН АРГУМЕНТ !!!
        trigger: str,
        media_type: Optional[str],
        media_bytes: Optional[bytes],
        mime_type: Optional[str],
    ) -> str:
        """
        Генерирует ответ, обрабатывая ошибки.
        Принимает список сообщений для контекста и опционально replied_to_message
        для контекста комментируемого поста.
        """
        # Формируем текстовую часть промпта с использованием перенесенной функции
        # !!! ПЕРЕДАЕМ replied_to_message В build_prompt !!!
        text_prompt_part_str = build_prompt(
            chat_id,
            messages,
            target_message,
            replied_to_message, # <-- Передаем сюда
            trigger,
            media_type,
            media_bytes
        )

        # Формируем полный контент для запроса к API
        content: List[Union[str, Dict[str, Any]]] = [text_prompt_part_str]
        if media_bytes and mime_type:
            try:
                media_part_dict = {
                    "mime_type": mime_type,
                    "data": media_bytes
                }
                content.append(media_part_dict)
                logger.debug("Added media part (%s, %d bytes) to Gemini request content.", mime_type, len(media_bytes))
            except Exception as part_err:
                 logger.error("Critical error creating dict for media part: %s", part_err, exc_info=True)


        try:
            model = genai.GenerativeModel("gemini-1.5-flash-latest")
            logger.debug("Calling Gemini API with %d parts...", len(content))

            safety_settings=[
                 {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                 {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                 {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ]
            generation_config={"temperature": 0.75}

            response = await model.generate_content_async(
                 content,
                 safety_settings=safety_settings,
                 generation_config=generation_config,
            )

            logger.debug("Received response from Gemini API.")

            extracted_text = ""
            try:
                if response.text:
                     extracted_text = response.text
                     logger.debug("Successfully extracted text from Gemini response.")
                elif getattr(response, 'prompt_feedback', None) and getattr(response.prompt_feedback, 'block_reason', None):
                    reason = response.prompt_feedback.block_reason
                    logger.warning("Gemini API response blocked. Reason: %s", reason)
                    extracted_text = f"(Так, стоп. Мой ответ завернули из-за цензуры – причина '{reason}'. Видимо, слишком честно или резко получилось для их нежных алгоритмов. Ну и хрен с ними.)"
                else:
                    logger.warning("Gemini API returned response without text and no explicit block reason. Response: %s", response)
                    parts = getattr(response, 'parts', [])
                    extracted_text = "".join(getattr(part, 'text', '') for part in parts)
                    if not extracted_text:
                         logger.error("Failed to extract text from Gemini response parts, response structure is undefined.")
                         extracted_text = "(Хм, что-то пошло не так с генерацией. Даже сказать нечего. ИИ молчит как партизан.)"
                    else:
                         logger.debug("Extracted text from Gemini response parts.")

            except AttributeError as attr_err:
                logger.error("AttributeError extracting text from Gemini response: %s. Response: %s", attr_err, response, exc_info=True)
                extracted_text = "(Черт, не могу разобрать, что там ИИ нагенерил. Техника барахлит, или ответ какой-то кривой пришел.)"
            except Exception as parse_err:
                logger.error("Unexpected error extracting text from Gemini response: %s. Response: %s", parse_err, response, exc_info=True)
                extracted_text = "(Какая-то хуйня с обработкой ответа ИИ. Забей, видимо, не судьба.)"

            return extracted_text

        except Exception as e:
            logger.error("Error calling generate_content_async for chat %d: %s", chat_id, str(e), exc_info=True)
            err_str = str(e).lower()
            if "api key not valid" in err_str:
                return "(Бляха, ключ API неверен или истёк.)"
            if any(k in err_str for k in ("quota", "limit", "rate limit")):
                return "(Лимит запросов к ИИ исчерпан. Попробуй позже.)"
            if any(k in err_str for k in ("503", "internal server", "service unavailable")):
                return "(Серверы ИИ недоступны. Попробуй чуть позже.)"
            if any(k in err_str for k in ("timeout", "deadline")):
                return "(ИИ долго думает, но время вышло. Видимо, вопрос слишком сложный... или серваки тупят.)"
            if "model not found" in err_str:
                return "(Модель ИИ не найдена. Проверь конфиг.)"
            if "block" in err_str or "safety" in err_str or "filtered" in err_str:
                 return "(Опять цензура! Мой гениальный запрос заблокировали еще на подлете из-за каких-то их правил безопасности. Неженки.)"
            return "(Произошла ошибка при генерации ответа. Попробуй позже.)"

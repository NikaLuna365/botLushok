# ai_lu_bot/services/gemini.py
import logging
import os
import traceback
from typing import Any, List, Optional, Union, Dict # Добавляем Dict сюда
from telegram import Message # Импортируем для тайп-хинтинга

import google.generativeai as genai
from dotenv import load_dotenv

# Удаляем импорт из bot_4_02
# from bot_4_02 import build_prompt # Удалить или закомментировать

# Импортируем перенесенную функцию build_prompt
from ai_lu_bot.core.prompt_builder import build_prompt

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
            # Это критическая ошибка, приложение не может работать без API KEY
            logger.critical("API_KEY не найден в окружении!")
            # Вместо raise RuntimeError, можно sys.exit(1) или обрабатывать на уровне app.py
            # Пока оставим raise, так как build_application в app.py ловит исключения.
            raise RuntimeError("API_KEY not found in environment")

        try:
            genai.configure(api_key=api_key)
            logger.info("GeminiService: Gemini API configured successfully.")
        except Exception as e:
            # Обработка ошибок конфигурации API (например, неверный ключ сразу)
            logger.critical(f"GeminiService: Failed to configure Gemini API: {e}", exc_info=True)
            raise RuntimeError(f"Failed to configure Gemini API: {e}") # Перебрасываем исключение


    async def generate_response(
        self,
        chat_id: int,
        messages: List[Dict[str, Any]], # !!! Теперь принимаем список сообщений для контекста !!!
        target_message: Message, # Используем Message для тайп-хинтинга
        trigger: str,
        media_type: Optional[str], # Тип медиа, если скачано и передается в API
        media_bytes: Optional[bytes], # Байты медиа, если скачано и передается в API
        mime_type: Optional[str], # MIME тип медиа, если скачано и передается в API
    ) -> str:
        """
        Генерирует ответ, обрабатывая:
         - блокировки prompt_feedback.block_reason
         - ошибки API key, quota, model not found, 5xx, timeout
        Принимает список сообщений для формирования контекста промпта.
        """
        # Формируем текстовую часть промпта с использованием перенесенной функции
        # Передаем chat_id, список сообщений, целевое сообщение и т.д.
        text_prompt_part_str = build_prompt(
            chat_id,
            messages, # Передаем список сообщений
            target_message,
            trigger,
            media_type, # build_prompt использует media_type для текста, media_bytes не нужны для строки
            media_bytes # Пробрасываем media_bytes на всякий случай, хотя build_prompt их не использует для текста
        )

        # Формируем полный контент для запроса к API
        content: List[Union[str, Dict[str, Any]]] = [text_prompt_part_str]
        if media_bytes and mime_type: # Добавляем медиа только если оно успешно скачано и MIME тип известен
            try:
                media_part_dict = {
                    "mime_type": mime_type,
                    "data": media_bytes
                }
                content.append(media_part_dict)
                logger.debug("Added media part (%s, %d bytes) to Gemini request content.", mime_type, len(media_bytes))
            except Exception as part_err:
                 # Это маловероятная ошибка на этапе создания словаря, но лучше перестраховаться
                 logger.error("Critical error creating dict for media part: %s", part_err, exc_info=True)
                 # Не добавляем медиа часть, если ошибка, продолжаем с текстовым промптом


        try:
            model = genai.GenerativeModel("gemini-1.5-flash-latest")
            logger.debug("Calling Gemini API with %d parts...", len(content))

            # Настройки безопасности и генерации остаются прежними
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
                 # Добавим таймаут на всякий случай, если API зависнет
                 # request_options={'timeout': 120} # Пример настройки таймаута (зависит от версии библиотеки)
            )

            logger.debug("Received response from Gemini API.")

            # Извлечение текста ответа с проверкой на блокировку (логика остается прежней)
            extracted_text = ""
            try:
                # Проверка наличия текста
                if response.text:
                     extracted_text = response.text
                     logger.debug("Successfully extracted text from Gemini response.")
                # Проверка на блокировку из-за безопасности или других причин
                elif getattr(response, 'prompt_feedback', None) and getattr(response.prompt_feedback, 'block_reason', None):
                    reason = response.prompt_feedback.block_reason
                    logger.warning("Gemini API response blocked. Reason: %s", reason)
                    # Формируем ответ в стиле Лу об ошибке
                    extracted_text = f"(Так, стоп. Мой ответ завернули из-за цензуры – причина '{reason}'. Видимо, слишком честно или резко получилось для их нежных алгоритмов. Ну и хрен с ними.)"
                # Если нет текста и нет явной блокировки (странный случай)
                else:
                    logger.warning("Gemini API returned response without text and no explicit block reason. Response: %s", response)
                    # Попытка извлечь текст из 'parts' как запасной вариант
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

            return extracted_text # Возвращаем извлеченный текст или сообщение об ошибке

        # Обработка ошибок самого вызова API (логика остается прежней)
        except Exception as e:
            logger.error("Error calling generate_content_async for chat %d: %s", chat_id, str(e), exc_info=True)
            err_str = str(e).lower()
            # Формируем ответы в стиле Лу для разных ошибок API
            if "api key not valid" in err_str:
                # Эта ошибка уже должна быть поймана при инициализации GeminiService,
                # но оставляем на всякий случай, если ключ стал невалидным позже
                return "(Бляха, ключ API неверен или истёк.)"
            if any(k in err_str for k in ("quota", "limit", "rate limit")):
                return "(Лимит запросов к ИИ исчерпан. Попробуй позже.)"
            if any(k in err_str for k in ("503", "internal server", "service unavailable")):
                return "(Серверы ИИ недоступны. Попробуй чуть позже.)"
            if any(k in err_str for k in ("timeout", "deadline")):
                return "(ИИ долго думает, но время вышло. Попробуй позже.)"
            if "model not found" in err_str:
                return "(Модель ИИ не найдена. Проверь конфиг.)"
            if "block" in err_str or "safety" in err_str or "filtered" in err_str:
                 # Эта ошибка может возникнуть и на этапе ЗАПРОСА (не только ответа)
                return "(Опять цензура! Мой гениальный запрос заблокировали еще на подлете из-за каких-то их правил безопасности. Неженки.)"
            # По умолчанию
            return "(Произошла ошибка при генерации ответа. Попробуй позже.)"

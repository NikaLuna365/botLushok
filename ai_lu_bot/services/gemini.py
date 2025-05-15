# ai_lu_bot/services/gemini.py
import logging
import os
import traceback
# Импортируем необходимые типы для тайп-хинтинга
from typing import Any, List, Optional, Union, Dict
# Импортируем Message из telegram для тайп-хинтинга
from telegram import Message

import google.generativeai as genai
from dotenv import load_dotenv # Используется здесь для загрузки API_KEY

# Импортируем функцию сборки промпта из нашего пакета
from ai_lu_bot.core.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Обёртка над google.generativeai API.
    Обрабатывает вызовы генерации контента и ошибки API.
    Используется как синглтон (один инстанс на всё приложение).
    """

    def __init__(self):
        """
        Инициализирует сервис Gemini, загружает API ключ и конфигурирует SDK.
        Вызывает RuntimeError при отсутствии API ключа или ошибке конфигурации.
        """
        # Убедимся, что переменные окружения загружены (хотя load_dotenv вызывается и в app.py)
        load_dotenv()
        api_key = os.getenv("API_KEY")
        if not api_key:
            # Это критическая ошибка, без ключа API сервис не работает
            logger.critical("GeminiService: API_KEY не найден в переменных окружения!")
            raise RuntimeError("API_KEY not found in environment")

        try:
            # Конфигурируем Google Generative AI SDK с помощью ключа
            genai.configure(api_key=api_key)
            logger.info("GeminiService: Google Generative AI SDK configured successfully.")
        except Exception as e:
            # Логируем и перебрасываем исключение, если конфигурация не удалась
            logger.critical(f"GeminiService: Failed to configure Google Generative AI SDK: {e}", exc_info=True)
            raise RuntimeError(f"Failed to configure Google Generative AI SDK: {e}")


    async def generate_response(
        self,
        chat_id: int, # ID чата для логирования/контекста
        messages: List[Dict[str, Any]], # Список сообщений для контекста диалога
        target_message: Message, # Объект целевого сообщения
        trigger: str, # Тип триггера ответа
        replied_to_message: Optional[Message] = None, # Объект сообщения, на которое ответили (опционально)
        media_type: Optional[str] = None, # Тип медиа в целевом сообщении (если скачано)
        media_bytes: Optional[bytes] = None, # Байты медиа (если скачано)
        mime_type: Optional[str] = None, # MIME тип медиа (если скачано)
    ) -> str:
        """
        Генерирует текстовый ответ с помощью Google Gemini API.
        Формирует промпт из контекста диалога и информации о комментируемом посте (если есть).
        Включает медиафайл в запрос, если он был успешно скачан.
        Обрабатывает ошибки API и блокировки контента.

        Args:
            chat_id: ID чата.
            messages: Список словарей с историей диалога.
            target_message: Объект telegram.Message целевого сообщения.
            trigger: Строка, описывающая триггер ответа.
            replied_to_message: Объект telegram.Message, на который отвечает target_message, или None.
            media_type: Тип медиа в target_message ('image', 'audio', 'video') или None.
                        Передается, только если медиа успешно скачано.
            media_bytes: Байты медиафайла. Передается, только если медиа успешно скачано.
            mime_type: MIME тип медиа. Передается, только если медиа успешно скачано.

        Returns:
            Строка с сгенерированным ответом или сообщением об ошибке/блокировке.
        """
        # Формируем текстовую часть промпта с использованием build_prompt
        # build_prompt принимает все данные, необходимые для создания текстового промпта
        text_prompt_part_str = build_prompt(
            chat_id=chat_id,
            messages=messages, # Передаем список сообщений
            target_message=target_message, # Передаем целевое сообщение
            trigger=trigger, # Передаем триггер
            replied_to_message=replied_to_message, # Передаем сообщение, на которое ответили
            media_type=media_type, # Передаем тип медиа (нужен build_prompt для текстового маркера)
            # media_bytes здесь не нужен build_prompt, но в сигнатуре он есть, пробрасываем None
            # Если сигнатура build_prompt будет изменена, можно убрать media_bytes
            media_data_bytes=None # У build_prompt есть этот аргумент, но он не используется для текста промпта
        )

        # Собираем список "частей" для запроса к Gemini API
        # Первая часть - всегда текстовый промпт
        content: List[Union[str, Dict[str, Any]]] = [text_prompt_part_str]

        # Вторая часть (опционально) - медиафайл, если он есть и был скачан
        if media_bytes and mime_type:
            try:
                media_part_dict = {
                    "mime_type": mime_type,
                    "data": media_bytes
                }
                content.append(media_part_dict)
                logger.debug("Added media part (%s, %d bytes) to Gemini request content.", mime_type, len(media_bytes))
            except Exception as part_err:
                 # Это крайне маловероятная ошибка, но лучше залогировать
                 logger.error("Critical error creating dict for media part: %s", part_err, exc_info=True)
                 # Не добавляем медиа часть в контент, если ошибка


        # --- Вызов Gemini API ---
        try:
            # Используем модель gemini-1.5-flash-latest
            model = genai.GenerativeModel("gemini-1.5-flash-latest")
            logger.debug("Calling Gemini API with %d parts...", len(content))

            # Настройки безопасности (можно настроить по желанию)
            safety_settings=[
                 {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}, # Менее строгие для стиля Лу
                 {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                 {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ]
            # Настройки генерации (температура влияет на креативность)
            generation_config={"temperature": 0.75}

            # Отправляем запрос на генерацию контента
            response = await model.generate_content_async(
                 content,
                 safety_settings=safety_settings,
                 generation_config=generation_config,
                 # request_options={'timeout': 120} # Пример настройки таймаута (зависит от версии библиотеки)
            )

            logger.debug("Received raw response from Gemini API.")

            # --- Извлечение текста ответа и обработка блокировок ---
            extracted_text = ""
            try:
                # Попытка получить текст ответа напрямую
                if response.text:
                     extracted_text = response.text.strip() # Удаляем лишние пробелы по краям
                     logger.debug("Successfully extracted text from Gemini response.")
                # Проверка на блокировку API по причинам безопасности (prompt_feedback)
                elif getattr(response, 'prompt_feedback', None) and getattr(response.prompt_feedback, 'block_reason', None):
                    reason = response.prompt_feedback.block_reason
                    logger.warning("Gemini API response blocked by safety settings. Reason: %s", reason)
                    # Формируем сообщение об ошибке в стиле Лу
                    extracted_text = f"(Так, стоп. Мой ответ завернули из-за цензуры – причина '{reason}'. Видимо, слишком честно или резко получилось для их нежных алгоритмов. Ну и хрен с ними.)"
                # Если текст отсутствует и нет явной блокировки (неожиданное состояние)
                else:
                    logger.warning("Gemini API returned response without text and no explicit block reason. Response: %s", response)
                    # Попытка собрать текст из частей ответа, если они есть
                    parts = getattr(response, 'parts', [])
                    extracted_text = "".join(getattr(part, 'text', '') for part in parts).strip()
                    if not extracted_text:
                         logger.error("Failed to extract text from Gemini response parts, response structure is undefined.")
                         extracted_text = "(Хм, что-то пошло не так с генерацией. Даже сказать нечего. ИИ молчит как партизан.)"
                    else:
                         logger.debug("Extracted text from Gemini response parts.")

            except AttributeError as attr_err:
                # Ошибка доступа к атрибутам объекта response
                logger.error("AttributeError extracting text from Gemini response: %s. Response: %s", attr_err, response, exc_info=True)
                extracted_text = "(Черт, не могу разобрать, что там ИИ нагенерил. Техника барахлит, или ответ какой-то кривой пришел.)"
            except Exception as parse_err:
                # Любая другая неожиданная ошибка при обработке ответа
                logger.error("Unexpected error extracting text from Gemini response: %s. Response: %s", parse_err, response, exc_info=True)
                extracted_text = "(Какая-то хуйня с обработкой ответа ИИ. Забей, видимо, не судьба.)"

            return extracted_text # Возвращаем извлеченный текст или сообщение об ошибке

        # --- Обработка исключений при вызове API ---
        except Exception as e:
            # Ловим ошибки, возникающие непосредственно при вызове generate_content_async
            logger.error("Error during generate_content_async call for chat %d: %s", chat_id, str(e), exc_info=True)
            err_str = str(e).lower()
            # Формируем специфичные сообщения об ошибках API в стиле Лу
            if "api key not valid" in err_str:
                # Эта ошибка должна по идее ловиться при инициализации, но дублируем на всякий случай
                return "(Бляха, ключ API неверен или истёк.)"
            if any(k in err_str for k in ("quota", "limit", "rate limit")):
                return "(Всё, приехали. Лимит запросов к ИИ исчерпан. Видимо, слишком много умных мыслей на сегодня. Попробуй позже.)"
            if any(k in err_str for k in ("503", "internal server", "service unavailable")):
                return "(Серверы ИИ, похоже, легли отдохнуть. Или от моего сарказма перегрелись. Позже попробуй.)"
            if any(k in err_str for k in ("timeout", "deadline")):
                return "(Что-то ИИ долго думает, аж время вышло. Видимо, вопрос слишком сложный... или серваки тупят.)"
            if "model not found" in err_str:
                return "(Модель, которой я должен думать, сейчас недоступна. Может, на техобслуживании? Попробуй позже, если не лень.)"
            if "block" in err_str or "safety" in err_str or "filtered" in err_str:
                 # Эта ошибка может возникнуть и на этапе отправки промпта, а не только в ответе
                 return "(Опять цензура! Мой гениальный запрос заблокировали еще на подлете из-за каких-то их правил безопасности. Неженки.)"
            # Общее сообщение для всех остальных ошибок API
            return "(Какая-то техническая засада с ИИ. Не сегодня, видимо. Попробуй позже.)"

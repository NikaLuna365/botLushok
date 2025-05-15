# ai_lu_bot/utils/text_utils.py
import re
import logging

logger = logging.getLogger(__name__)

def filter_technical_info(text: str) -> str:
    """Удаляет потенциально чувствительную техническую информацию (например, IP-адреса) из текста."""
    # Логика остается такой же, как была в bot_4_02.py
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    # Возможно, стоит добавить логирование, если что-то было отфильтровано, но пока оставим как есть
    # if re.search(ip_pattern, text):
    #    logger.debug("Filtered IP addresses from text")
    return re.sub(ip_pattern, "[REDACTED_IP]", text)

# В будущем здесь могут появиться другие полезные утилиты для обработки текста

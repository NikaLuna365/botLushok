# ai_lu_bot/utils/media.py
import io
import logging
from telegram import Voice, VideoNote, PhotoSize

logger = logging.getLogger(__name__)


class MediaDownloadError(Exception):
    """Ошибка при скачивании медиа из Telegram."""


async def download_media(media_obj: Voice | VideoNote | PhotoSize, media_type: str) -> tuple[bytes, str]:
    """
    Скачивает media_obj в память, возвращает (bytes, mime_type).
    Бросает MediaDownloadError при любых проблемах.
    """
    try:
        tg_file = await media_obj.get_file()
        buffer = io.BytesIO()
        await tg_file.download_to_memory(buffer)
        data = buffer.getvalue()
        buffer.close()
        if not data:
            raise MediaDownloadError("Пустые данные после скачивания")

        mime_map = {"image": "image/jpeg", "audio": "audio/ogg", "video": "video/mp4"}
        mime = mime_map.get(media_type)
        if not mime:
            raise MediaDownloadError(f"Неизвестный media_type: {media_type}")
        return data, mime

    except Exception as e:
        logger.error("download_media error", exc_info=True)
        raise MediaDownloadError(str(e))

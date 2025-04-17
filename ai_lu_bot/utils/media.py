"""Media helpers: download, resize, transcription."""
from __future__ import annotations

import io
import logging
from typing import Optional, Tuple

from telegram import Voice, VideoNote, PhotoSize

logger = logging.getLogger(__name__)

class MediaDownloadError(Exception):
    """Raised when Telegram media cannot be downloaded."""

# Size limit (bytes) to avoid sending 20‑MB+ originals to Vision.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

async def download_media(obj: PhotoSize | Voice | VideoNote):
    """Return tuple: (bytes, mime_type). Raise MediaDownloadError on failure."""
    try:
        file = await obj.get_file()
        buffer = io.BytesIO()
        await file.download_to_memory(buffer)
        data = buffer.getvalue()
        if not data:
            raise RuntimeError("downloaded empty")
        mime: str = "application/octet-stream"
        if isinstance(obj, PhotoSize):
            mime = "image/jpeg"
            if len(data) > _MAX_IMAGE_BYTES:  # rudimentary resize stub
                logger.info("Image >%d B; sending original (resize TODO)", _MAX_IMAGE_BYTES)
        elif isinstance(obj, Voice):
            mime = "audio/ogg"
        elif isinstance(obj, VideoNote):
            mime = "video/mp4"
        return data, mime
    except Exception as e:
        logger.error("download_media failed: %s", e, exc_info=True)
        raise MediaDownloadError(str(e)) from e

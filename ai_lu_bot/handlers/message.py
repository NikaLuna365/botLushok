from __future__ import annotations

import logging
import random
import re
from typing import Any, List

from telegram import (
    Message,
    Update,
    ReplyKeyboardMarkup,
    Voice,
    VideoNote,
    PhotoSize,
)
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from ..core.context import context_store
from ..prompt.base_prompt import BASE_PROMPT_TEMPLATE
from ..services.gemini import GeminiService
from ..utils.media import download_media, MediaDownloadError

logger = logging.getLogger(__name__)

# Helper regex for IP hiding
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _filter_technical_info(text: str) -> str:  # noqa: D401
    """Remove public IP addresses before sending message."""
    return _IP_PATTERN.sub("[REDACTED_IP]", text)


def _build_prompt(
    chat_id: int,
    target_msg: Message,
    conv_history: List[dict[str, Any]],
    final_task: str,
    media_type: str | None,
) -> str:
    history_str = "История переписки (самые новые внизу):\n"
    if not conv_history:
        history_str += "[Начало диалога]\n"
    for msg in conv_history:
        label = "[Бот]" if msg.get("from_bot") else f"[{msg.get('user')}]"
        history_str += f"{label}: {msg.get('text')}\n"
    history_str += "---\n"

    user_label = (
        "Создатель" if (target_msg.from_user and target_msg.from_user.username in ["Nik_Ly", "GroupAnonymousBot"]) else target_msg.from_user.first_name
    )
    header = f"[{user_label}] ({media_type or 'сообщение'}):"
    content = target_msg.text or target_msg.caption or "[Пустое сообщение]"

    history_str += f"{header} {content}\n"
    return (
        BASE_PROMPT_TEMPLATE.replace("{{CONVERSATION_HISTORY_PLACEHOLDER}}", history_str)
        .replace("{{FINAL_TASK_PLACEHOLDER}}", final_task)
    )

# ──────────────────────────────────────────────────────────

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Философия", "Политика"], ["Критика общества", "Личные истории"]]
    await update.message.reply_text(
        "Привет! Я AI LU — цифровая копия Николая Лу. Спрашивай!",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    gemini: GeminiService = context.bot_data["gemini"]

    msg = update.message
    chat_id = update.effective_chat.id

    # ── Determine reply‑need first (cheap) ─────────────────
    is_creator = msg.from_user and msg.from_user.username in ["Nik_Ly", "GroupAnonymousBot"]
    is_reply_to_bot = msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == context.bot.id
    is_channel_post = (
        (msg.forward_from_chat and msg.forward_from_chat.type == ChatType.CHANNEL)
        or (msg.sender_chat and msg.sender_chat.type == ChatType.CHANNEL)
    )

    should_respond = False
    trigger: str | None = None
    if update.effective_chat.type == ChatType.PRIVATE:
        should_respond = True
        trigger = "dm"
    elif is_reply_to_bot or is_creator:
        should_respond = True
        trigger = "reply_or_creator"
    elif is_channel_post:
        text_len = len((msg.text or msg.caption or "").split())
        if msg.photo or msg.voice or msg.video_note or text_len >= 5:
            should_respond = True
            trigger = "channel_post"
    else:  # group random
        is_short = not msg.photo and not msg.voice and not msg.video_note and len((msg.text or "").split()) < 3
        if not is_short and random.random() < 0.05:
            should_respond = True
            trigger = "random_group_message"
    if not should_respond:
        return

    # ── After decision → download media if any ─────────────
    media_type: str | None = None
    media_part: Any | None = None
    if msg.photo:
        media_type = "image"
        try:
            media_part = await download_media(msg.photo[-1])  # (bytes, mime)
        except MediaDownloadError:
            if trigger != "random_group_message":
                await context.bot.send_message(chat_id, "(Извини, не смог скачать твой медиафайл. Попробую ответить только на текст.)", reply_to_message_id=msg.message_id)
    elif msg.voice:
        media_type = "audio"
        try:
            media_part = await download_media(msg.voice)
        except MediaDownloadError:
            if trigger != "random_group_message":
                await context.bot.send_message(chat_id, "(Извини, не смог скачать твой голос. Попробую ответить текстом.)", reply_to_message_id=msg.message_id)
    elif msg.video_note:
        media_type = "video"
        try:
            media_part = await download_media(msg.video_note)
        except MediaDownloadError:
            if trigger != "random_group_message":
                await context.bot.send_message(chat_id, "(Извини, не смог скачать видео‑кружок.)", reply_to_message_id=msg.message_id)

    # ── Build prompt & ask LLM ─────────────────────────────
    final_task = (
        "ЗАДАНИЕ: Напиши ответ в стиле Лу на ПОСЛЕДНЕЕ сообщение в истории выше…"
        if trigger != "channel_post"
        else "ЗАДАНИЕ: Напиши комментарий в стиле Лу на ПОСЛЕДНИЙ пост…"
    )
    if is_creator:
        final_task += " ПОМНИ ОСОБЫЕ ПРАВИЛА ОБЩЕНИЯ С СОЗДАТЕЛЕМ."

    history = context_store.history(chat_id)
    prompt = _build_prompt(chat_id, msg, history, final_task, media_type)

    parts: List[Any] = [prompt]
    if media_part:
        data, mime = media_part
        parts.append({"data": data, "mime_type": mime})

    reply_text = await gemini.generate(parts)
    reply_text = _filter_technical_info(reply_text.strip()) or "…"

    sent = await context.bot.send_message(chat_id, reply_text, reply_to_message_id=msg.message_id)

    context_store.append(chat_id, {"user": "Бот", "text": reply_text, "from_bot": True, "message_id": sent.message_id})
    context_store.trim(chat_id)


from __future__ import annotations

import asyncio
import logging

from telegram import Audio, Document, Message, Update, Voice
from telegram.error import NetworkError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .agent import LocalAgentGateway, build_agent_input
from .config import Settings


LOGGER = logging.getLogger(__name__)


class TelegramIntakeService:
    """Receives Telegram messages and forwards them to the agent gateway."""

    def __init__(self, settings: Settings, agent_gateway: LocalAgentGateway) -> None:
        self._settings = settings
        self._agent_gateway = agent_gateway
        self._application = Application.builder().token(settings.telegram_bot_token).build()
        self._application.add_handler(CommandHandler("start", self._handle_start))
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_message)
        )
        self._application.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self._handle_audio_message)
        )
        self._application.add_handler(
            MessageHandler(filters.PHOTO | filters.Document.ALL, self._handle_attachment_message)
        )

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.effective_message:
            return
        await update.effective_message.reply_text(
            "Telegram intake is active. Send a text, voice note, audio file, image, PDF, PPTX, or CSV to talk to the agent pipeline."
        )

    async def _handle_text_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        text = update.effective_message.text or ""
        LOGGER.info(
            "Incoming Telegram message chat_id=%s user_id=%s username=%s text=%r",
            chat_id,
            update.effective_user.id if update.effective_user else None,
            update.effective_user.username if update.effective_user else None,
            text[:80],
        )

        if self._settings.allowed_chat_ids and chat_id not in self._settings.allowed_chat_ids:
            LOGGER.warning("Rejected message from unauthorized chat_id=%s", chat_id)
            return

        agent_input = build_agent_input(
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            username=update.effective_user.username if update.effective_user else None,
            text=text,
        )
        reply = await self._agent_gateway.handle_message(agent_input)

        await update.effective_message.reply_text(reply)

    async def _handle_audio_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        if self._settings.allowed_chat_ids and chat_id not in self._settings.allowed_chat_ids:
            LOGGER.warning("Rejected audio from unauthorized chat_id=%s", chat_id)
            return

        message = update.effective_message
        media: Voice | Audio | None = message.voice or message.audio
        if media is None:
            return

        filename, mime_type = self._resolve_audio_metadata(media)
        LOGGER.info(
            "Incoming Telegram audio chat_id=%s user_id=%s filename=%s mime_type=%s",
            chat_id,
            update.effective_user.id if update.effective_user else None,
            filename,
            mime_type,
        )

        telegram_file = await media.get_file()
        audio_buffer = await telegram_file.download_as_bytearray()
        transcript = await self._agent_gateway.transcribe_audio(
            audio_bytes=bytes(audio_buffer),
            filename=filename,
            mime_type=mime_type,
        )
        if transcript is None:
            await message.reply_text(
                "I could not transcribe the audio message because the transcription backend failed. Please try again."
            )
            return

        if not transcript:
            await message.reply_text(
                "I could not detect clear speech in the audio message. Try a slightly longer or louder voice note."
            )
            return

        LOGGER.info("Audio transcript chat_id=%s text=%r", chat_id, transcript[:120])
        await message.reply_text(f"Transcription: {transcript}")
        agent_input = build_agent_input(
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            username=update.effective_user.username if update.effective_user else None,
            text=transcript,
            source="telegram_audio",
            filename=filename,
            mime_type=mime_type,
        )
        reply = await self._agent_gateway.handle_message(agent_input)
        await message.reply_text(reply)

    async def _handle_attachment_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        if self._settings.allowed_chat_ids and chat_id not in self._settings.allowed_chat_ids:
            LOGGER.warning("Rejected attachment from unauthorized chat_id=%s", chat_id)
            return

        message = update.effective_message
        attachment = self._resolve_attachment(message)
        if attachment is None:
            return

        if not attachment["supported"]:
            await message.reply_text(
                "I can currently read images, PDF documents, PPTX slide decks, and CSV files from Telegram attachments."
            )
            return

        LOGGER.info(
            "Incoming Telegram attachment chat_id=%s user_id=%s filename=%s mime_type=%s source=%s",
            chat_id,
            update.effective_user.id if update.effective_user else None,
            attachment["filename"],
            attachment["mime_type"],
            attachment["source"],
        )

        telegram_file = await attachment["media"].get_file()
        file_buffer = await telegram_file.download_as_bytearray()
        extracted_text = await self._agent_gateway.extract_attachment_text(
            file_bytes=bytes(file_buffer),
            filename=attachment["filename"],
            mime_type=attachment["mime_type"],
            caption=message.caption,
        )
        if not extracted_text:
            await message.reply_text(
                "I could not read that attachment right now. Please try again with a clearer file."
            )
            return

        agent_input = build_agent_input(
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            username=update.effective_user.username if update.effective_user else None,
            text=self._build_attachment_prompt(
                filename=attachment["filename"],
                mime_type=attachment["mime_type"],
                caption=message.caption,
                extracted_text=extracted_text,
            ),
            source=attachment["source"],
            filename=str(attachment["filename"]),
            mime_type=attachment["mime_type"] if isinstance(attachment["mime_type"], str) else None,
        )
        reply = await self._agent_gateway.handle_message(agent_input)
        await message.reply_text(reply)

    @staticmethod
    def _resolve_audio_metadata(media: Voice | Audio) -> tuple[str, str | None]:
        if isinstance(media, Voice):
            return "telegram_voice.ogg", getattr(media, "mime_type", None) or "audio/ogg"

        file_name = media.file_name or "telegram_audio"
        mime_type = media.mime_type
        return file_name, mime_type

    @staticmethod
    def _resolve_attachment(message: Message) -> dict[str, object] | None:
        if message.photo:
            photo = message.photo[-1]
            return {
                "media": photo,
                "filename": "telegram_photo.jpg",
                "mime_type": "image/jpeg",
                "source": "telegram_image",
                "supported": True,
            }

        document: Document | None = message.document
        if document is None:
            return None

        filename = document.file_name or "telegram_document"
        mime_type = document.mime_type
        normalized_name = filename.lower()
        normalized_mime = (mime_type or "").lower()
        is_supported = (
            normalized_mime.startswith("image/")
            or normalized_mime == "application/pdf"
            or normalized_mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            or normalized_mime in {"text/csv", "application/csv"}
            or (normalized_mime == "text/plain" and normalized_name.endswith(".csv"))
            or normalized_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".pptx", ".csv"))
        )
        source = "telegram_image" if normalized_mime.startswith("image/") or normalized_name.endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".gif")
        ) else "telegram_document"
        return {
            "media": document,
            "filename": filename,
            "mime_type": mime_type,
            "source": source,
            "supported": is_supported,
        }

    @staticmethod
    def _build_attachment_prompt(
        *,
        filename: str,
        mime_type: str | None,
        caption: str | None,
        extracted_text: str,
    ) -> str:
        lines = [
            "A Telegram attachment was received.",
            f"Filename: {filename}",
            f"MIME type: {mime_type or 'unknown'}",
        ]
        if caption:
            lines.append(f"User caption: {caption}")
        lines.extend(
            [
                "",
                "Extracted attachment content:",
                extracted_text,
            ]
        )
        return "\n".join(lines)

    def run(self) -> None:
        LOGGER.info("Starting Telegram intake service in polling mode.")
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            self._application.run_polling(allowed_updates=Update.ALL_TYPES)
        except NetworkError as exc:
            raise RuntimeError(
                "Telegram bootstrap failed due to a network error. "
                "Check internet connectivity, DNS resolution, and bot token validity."
            ) from exc

"""
Handler Telegram adattato da agents-ai per il sistema multi-agente.

Riceve messaggi Telegram (testo, audio, allegati) e li inoltra al
Chief Orchestrator via ChiefOrchestratorGateway.

Rispetto a agents-ai:
- non dipende da agent.py (rimosso)
- importa AgentInput e build_agent_input da agno_service
- usa ChiefOrchestratorGateway invece di LocalAgentGateway
- la trascrizione audio è opzionale (richiede OPENAI_API_KEY)
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Audio, Document, Message, Update, Voice
from telegram.error import NetworkError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agno_service import AgentInput, ChiefOrchestratorGateway, build_agent_input
from config import Settings


LOGGER = logging.getLogger(__name__)


class TelegramIntakeService:
    """Riceve messaggi Telegram e li inoltra al Chief Orchestrator."""

    def __init__(self, settings: Settings, gateway: ChiefOrchestratorGateway) -> None:
        self._settings = settings
        self._gateway = gateway
        self._application = Application.builder().token(settings.telegram_bot_token).build()
        self._application.add_handler(CommandHandler("start", self._handle_start))
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )
        self._application.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self._handle_audio)
        )
        self._application.add_handler(
            MessageHandler(filters.PHOTO | filters.Document.ALL, self._handle_attachment)
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.effective_message:
            return
        await update.effective_message.reply_text(
            "Engineering Copilot attivo. "
            "Invia testo, nota vocale, audio, immagine, PDF, PPTX o CSV per interagire."
        )

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        text = update.effective_message.text or ""
        LOGGER.info(
            "Messaggio Telegram chat_id=%s user_id=%s username=%s text=%r",
            chat_id,
            update.effective_user.id if update.effective_user else None,
            update.effective_user.username if update.effective_user else None,
            text[:80],
        )

        if not self._is_allowed(chat_id):
            return

        agent_input = build_agent_input(
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            username=update.effective_user.username if update.effective_user else None,
            text=text,
        )
        reply = await self._gateway.handle_message(agent_input)
        await update.effective_message.reply_text(reply)

    async def _handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return

        message = update.effective_message
        media: Voice | Audio | None = message.voice or message.audio
        if media is None:
            return

        filename, mime_type = self._resolve_audio_metadata(media)
        LOGGER.info(
            "Audio Telegram chat_id=%s user_id=%s filename=%s mime_type=%s",
            chat_id,
            update.effective_user.id if update.effective_user else None,
            filename, mime_type,
        )

        telegram_file = await media.get_file()
        audio_bytes = bytes(await telegram_file.download_as_bytearray())
        transcript = await self._gateway.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        if transcript is None:
            await message.reply_text(
                "Trascrizione audio non disponibile. "
                "Configura OPENAI_API_KEY per abilitarla, oppure invia un messaggio di testo."
            )
            return
        if not transcript:
            await message.reply_text(
                "Nessun parlato rilevato nell'audio. Prova con una nota vocale più lunga o più chiara."
            )
            return

        LOGGER.info("Trascrizione audio chat_id=%s text=%r", chat_id, transcript[:120])
        await message.reply_text(f"Trascrizione: {transcript}")

        agent_input = build_agent_input(
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            username=update.effective_user.username if update.effective_user else None,
            text=transcript,
            source="telegram_audio",
            filename=filename,
            mime_type=mime_type,
        )
        reply = await self._gateway.handle_message(agent_input)
        await message.reply_text(reply)

    async def _handle_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return

        message = update.effective_message
        attachment = self._resolve_attachment(message)
        if attachment is None:
            return

        if not attachment["supported"]:
            await message.reply_text(
                "Posso leggere immagini, PDF, PPTX e file CSV dagli allegati Telegram."
            )
            return

        LOGGER.info(
            "Allegato Telegram chat_id=%s user_id=%s filename=%s mime_type=%s source=%s",
            chat_id,
            update.effective_user.id if update.effective_user else None,
            attachment["filename"], attachment["mime_type"], attachment["source"],
        )

        telegram_file = await attachment["media"].get_file()
        file_bytes = bytes(await telegram_file.download_as_bytearray())
        extracted_text = await self._gateway.extract_attachment_text(
            file_bytes=file_bytes,
            filename=attachment["filename"],
            mime_type=attachment["mime_type"],
            caption=message.caption,
        )
        if not extracted_text:
            await message.reply_text(
                "Non riesco a leggere questo allegato. Riprova con un file più chiaro."
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
        reply = await self._gateway.handle_message(agent_input)
        await message.reply_text(reply)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _is_allowed(self, chat_id: int) -> bool:
        if self._settings.allowed_chat_ids and chat_id not in self._settings.allowed_chat_ids:
            LOGGER.warning("Messaggio rifiutato da chat_id=%s non autorizzato", chat_id)
            return False
        return True

    @staticmethod
    def _resolve_audio_metadata(media: Voice | Audio) -> tuple[str, str | None]:
        if isinstance(media, Voice):
            return "telegram_voice.ogg", getattr(media, "mime_type", None) or "audio/ogg"
        return media.file_name or "telegram_audio", media.mime_type

    @staticmethod
    def _resolve_attachment(message: Message) -> dict[str, object] | None:
        if message.photo:
            return {
                "media": message.photo[-1],
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
        name = filename.lower()
        mime = (mime_type or "").lower()
        is_supported = (
            mime.startswith("image/")
            or mime == "application/pdf"
            or mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            or mime in {"text/csv", "application/csv"}
            or (mime == "text/plain" and name.endswith(".csv"))
            or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".pptx", ".csv"))
        )
        source = (
            "telegram_image"
            if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
            else "telegram_document"
        )
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
            "È stato ricevuto un allegato Telegram.",
            f"Filename: {filename}",
            f"MIME type: {mime_type or 'unknown'}",
        ]
        if caption:
            lines.append(f"Didascalia utente: {caption}")
        lines += ["", "Contenuto estratto:", extracted_text]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        LOGGER.info("Telegram intake service avviato in modalità polling.")
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            self._application.run_polling(allowed_updates=Update.ALL_TYPES)
        except NetworkError as exc:
            raise RuntimeError(
                "Avvio Telegram fallito per errore di rete. "
                "Verifica connessione, DNS e validità del bot token."
            ) from exc

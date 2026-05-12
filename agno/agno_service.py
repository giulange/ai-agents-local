"""
Setup del sistema multi-agente Agno con Chief Orchestrator come entry point.

Architettura attuale (Step 0 → Step 1):
  - ChiefOrchestratorGateway: agente singolo (qwen2.5:7b via Ollama)
    con memoria SQLite e tools locali.
  - Step 1: il Chief diventerà il leader di un agno.team.Team con
    agenti specializzati (MeteoAgent, CodeAgent, DataAgent, …).

Non dipende da agent.py di agents-ai — AgentInput e build_agent_input
sono definiti qui.
"""
from __future__ import annotations

import base64
import csv
import logging
import mimetypes
import sqlite3
import zipfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import httpx

from config import Settings

LOGGER = logging.getLogger(__name__)
CURRENT_TOOL_CHAT_ID: ContextVar[int | None] = ContextVar("current_tool_chat_id", default=None)


# ---------------------------------------------------------------------------
# AgentInput  (era in agents-ai/agent.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentInput:
    chat_id: int
    user_id: int | None
    username: str | None
    text: str
    received_at: datetime
    source: str = "telegram"
    filename: str | None = None
    mime_type: str | None = None


def build_agent_input(
    *,
    chat_id: int,
    user_id: int | None,
    username: str | None,
    text: str,
    source: str = "telegram",
    filename: str | None = None,
    mime_type: str | None = None,
) -> AgentInput:
    return AgentInput(
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        text=text,
        received_at=datetime.now(timezone.utc),
        source=source,
        filename=filename,
        mime_type=mime_type,
    )


# ---------------------------------------------------------------------------
# Chief Orchestrator Gateway
# ---------------------------------------------------------------------------

class ChiefOrchestratorGateway:
    """
    Gateway conversazionale basato su Agno con Chief Orchestrator.

    Il Chief usa qwen2.5:7b via Ollama locale con persistenza SQLite.

    Step 1: sostituire self._chief con un agno.team.Team dove il Chief
    è il leader e i membri sono agenti specializzati.
    """

    REQUIRED_SESSION_COLUMNS = {
        "session_id", "user_id", "created_at", "updated_at", "summary",
        "runs", "session_type", "metadata", "workflow_id", "workflow_data",
        "team_id", "team_data",
    }
    REQUIRED_MEMORY_COLUMNS = {
        "id", "user_id", "memory", "created_at", "updated_at", "agent_id",
        "team_id", "feedback", "topics", "input", "memory_id",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._transcription_client = self._build_transcription_client()
        self._chief = self._build_chief()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_chief(self) -> Any:
        try:
            from agno.agent import Agent
            from agno.db.sqlite import SqliteDb
            from agno.models.ollama import Ollama
        except ImportError as exc:
            raise RuntimeError(
                "Agno o una delle sue dipendenze non è installata. "
                "Esegui: pip install -r requirements.txt"
            ) from exc

        db_path = Path(self._settings.agno_db_file)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._archive_incompatible_db(db_path)

        db = SqliteDb(
            db_file=str(db_path),
            session_table="agent_sessions",
            memory_table="agent_memories",
        )
        self._initialize_required_tables(db)

        # Step 1: wrappare questo Agent in un agno.team.Team come leader,
        # aggiungendo agenti specializzati come membri.
        return Agent(
            name="Chief Orchestrator",
            model=Ollama(
                id=self._settings.ollama_model,
                host=self._settings.ollama_host,
            ),
            db=db,
            tools=self._build_tools(db_path),
            instructions=[
                "Il tuo nome è ChiefOrchestrator.",
                "Sei l'agente principale di un sistema multi-agente Engineering Copilot.",
                "Ricevi messaggi dall'utente tramite Telegram e coordini la risposta.",
                "Rispondi in modo chiaro, diretto e conciso.",
                "Usa la storia della sessione e le memorie utente quando rilevanti.",
                "Non salvare dettagli temporanei come preferenze stabili.",
            ],
            enable_agentic_memory=True,
            add_history_to_context=True,
            num_history_runs=8,
            markdown=False,
            debug_mode=self._settings.agno_debug_mode,
            debug_level=self._settings.agno_debug_level,
        )

    def _build_transcription_client(self) -> Any | None:
        if not self._settings.openai_api_key:
            return None
        try:
            from openai import AsyncOpenAI
            return AsyncOpenAI(api_key=self._settings.openai_api_key)
        except ImportError:
            LOGGER.warning("openai non installato — trascrizione audio non disponibile.")
            return None

    # ------------------------------------------------------------------
    # Handle message
    # ------------------------------------------------------------------

    async def handle_message(self, message: AgentInput) -> str:
        session_id = f"telegram-chat-{message.chat_id}"
        user_id = (
            f"telegram-user-{message.user_id}"
            if message.user_id is not None
            else f"telegram-chat-{message.chat_id}"
        )
        LOGGER.info(
            "Chief Orchestrator user_id=%s session_id=%s source=%s",
            user_id, session_id, message.source,
        )
        token = CURRENT_TOOL_CHAT_ID.set(message.chat_id)
        try:
            response = await self._chief.arun(
                input=message.text,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception:
            LOGGER.exception("Chief Orchestrator request failed session_id=%s", session_id)
            return "L'assistente è temporaneamente non disponibile. Riprova."
        finally:
            CURRENT_TOOL_CHAT_ID.reset(token)

        reply = self._coerce_output(response)
        if not reply:
            LOGGER.warning("Risposta vuota da Chief Orchestrator session_id=%s", session_id)
            return "L'assistente ha restituito una risposta vuota. Riprova."
        return reply

    # ------------------------------------------------------------------
    # Audio transcription (opzionale, richiede openai_api_key)
    # ------------------------------------------------------------------

    async def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        mime_type: str | None,
    ) -> str | None:
        if self._transcription_client is None:
            LOGGER.warning("Trascrizione audio non disponibile (OPENAI_API_KEY non configurato).")
            return None

        audio_file = BytesIO(audio_bytes)
        audio_file.name = filename
        try:
            transcript = await self._transcription_client.audio.transcriptions.create(
                file=audio_file,
                model=self._settings.openai_transcription_model,
                response_format="text",
            )
        except Exception:
            LOGGER.exception("Trascrizione audio fallita filename=%s", filename)
            return None

        if not isinstance(transcript, str):
            transcript = getattr(transcript, "text", "") or ""
        return transcript.strip() or None

    # ------------------------------------------------------------------
    # Attachment extraction
    # ------------------------------------------------------------------

    async def extract_attachment_text(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        mime_type: str | None,
        caption: str | None = None,
    ) -> str:
        name = filename.lower()
        mime = (mime_type or "").lower()

        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return await self._extract_image_text(file_bytes, filename, mime_type)
        if mime == "application/pdf" or name.endswith(".pdf"):
            return await self._extract_pdf_text(file_bytes, filename)
        if (
            mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            or name.endswith(".pptx")
        ):
            return self._extract_pptx_text(file_bytes, filename)
        if mime in {"text/csv", "application/csv"} or name.endswith(".csv"):
            return self._extract_csv_text(file_bytes, filename)
        return ""

    async def _extract_image_text(
        self, image_bytes: bytes, filename: str, mime_type: str | None
    ) -> str:
        if self._transcription_client is None:
            return "[Estrazione immagine non disponibile: OPENAI_API_KEY non configurato]"

        media_type = mime_type or self._guess_image_mime(filename)
        image_url = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"
        prompt = (
            "Leggi questa immagine. Estrai il testo visibile fedelmente. "
            "Se contiene grafici o UI, descrivi brevemente le parti utili per il ragionamento."
        )
        try:
            response = await self._transcription_client.responses.create(
                model="gpt-4o-mini",
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_url, "detail": "high"},
                    ],
                }],
            )
            return self._truncate(self._extract_response_text(response))
        except Exception:
            LOGGER.exception("Estrazione immagine fallita filename=%s", filename)
            return ""

    async def _extract_pdf_text(self, pdf_bytes: bytes, filename: str) -> str:
        if self._transcription_client is None:
            return "[Estrazione PDF non disponibile: OPENAI_API_KEY non configurato]"

        prompt = (
            "Estrai il contenuto testuale utile da questo PDF come testo piano. "
            "Preserva intestazioni, bullet e struttura tabelle."
        )
        try:
            response = await self._transcription_client.responses.create(
                model="gpt-4o-mini",
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_file",
                            "filename": filename,
                            "file_data": base64.b64encode(pdf_bytes).decode(),
                        },
                    ],
                }],
            )
            return self._truncate(self._extract_response_text(response))
        except Exception:
            LOGGER.exception("Estrazione PDF fallita filename=%s", filename)
            return ""

    def _extract_pptx_text(self, pptx_bytes: bytes, filename: str) -> str:
        try:
            import zipfile as zf
            from xml.etree import ElementTree as ET
            slides: list[str] = []
            with zf.ZipFile(BytesIO(pptx_bytes)) as z:
                slide_names = sorted(
                    n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
                )
                for name in slide_names:
                    tree = ET.fromstring(z.read(name))
                    texts = [el.text for el in tree.iter() if el.text and el.text.strip()]
                    if texts:
                        slides.append(" ".join(texts))
            return self._truncate("\n\n".join(slides))
        except zipfile.BadZipFile:
            LOGGER.exception("PPTX non valido filename=%s", filename)
            return ""
        except Exception:
            LOGGER.exception("Estrazione PPTX fallita filename=%s", filename)
            return ""

    def _extract_csv_text(self, csv_bytes: bytes, filename: str) -> str:
        raw = self._decode_bytes(csv_bytes)
        if not raw.strip():
            return ""
        line_count = raw.count("\n") + 1
        try:
            reader = csv.reader(StringIO(raw))
            rows = [",".join(row) for i, row in enumerate(reader) if i < 20]
            preview = "\n".join(rows)
        except Exception:
            preview = raw
        return (
            f"File CSV `{filename}`. Righe totali: ~{line_count}.\nAnteprima:\n"
            + self._truncate(preview)
        )

    # ------------------------------------------------------------------
    # Telegram file sender (tool callable dall'agente)
    # ------------------------------------------------------------------

    def send_file_to_telegram(self, file_path: str, caption: str | None = None) -> str:
        """Invia un file locale alla chat Telegram corrente."""
        target_chat_id = CURRENT_TOOL_CHAT_ID.get() or (
            self._settings.allowed_chat_ids[0] if self._settings.allowed_chat_ids else None
        )
        if target_chat_id is None:
            return "Errore: nessuna chat Telegram disponibile per l'invio del file."

        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = (Path(self._settings.tools_base_dir) / path).resolve()
        if not path.exists() or not path.is_file():
            return f"Errore: file non trovato: {path}"

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        url = f"https://api.telegram.org/bot{self._settings.telegram_bot_token}/sendDocument"
        try:
            with path.open("rb") as fh:
                response = httpx.post(
                    url,
                    data={"chat_id": str(target_chat_id), "caption": caption or ""},
                    files={"document": (path.name, fh, mime_type)},
                    timeout=60.0,
                )
            response.raise_for_status()
        except Exception as exc:
            LOGGER.exception("Invio file Telegram fallito path=%s chat_id=%s", path, target_chat_id)
            return f"Errore invio file Telegram: {exc}"
        return f"File `{path.name}` inviato alla chat Telegram `{target_chat_id}`."

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _build_tools(self, db_path: Path) -> list[Any]:
        tools: list[Any] = []
        tools.extend(self._build_local_tools())
        tools.extend(self._build_data_tools(db_path))
        tools.extend(self._build_search_tools())
        tools.append(self.send_file_to_telegram)
        return tools

    def _build_local_tools(self) -> list[Any]:
        base_dir = Path(self._settings.tools_base_dir).resolve()
        output_dir = Path(self._settings.tools_output_dir).resolve()
        return self._load_toolkits(
            ("agno.tools.file", "FileTools",
             {"base_dir": base_dir, "enable_delete_file": False}, "file_tools"),
            ("agno.tools.python", "PythonTools",
             {"base_dir": base_dir, "restrict_to_base_dir": True}, "python_tools"),
            ("agno.tools.shell", "ShellTools",
             {"base_dir": str(base_dir)}, "shell_tools"),
            ("agno.tools.local_file_system", "LocalFileSystemTools",
             {"target_directory": str(output_dir)}, "local_file_system_tools"),
        )

    def _build_data_tools(self, db_path: Path) -> list[Any]:
        tools = self._load_toolkits(
            ("agno.tools.sql", "SQLTools",
             {"db_url": f"sqlite:///{db_path.resolve()}"}, "sql_tools"),
        )
        if self._has_postgres_config():
            tools.extend(self._load_toolkits(
                ("agno.tools.postgres", "PostgresTools", {
                    "db_name": self._settings.postgres_db_name,
                    "user": self._settings.postgres_user,
                    "password": self._settings.postgres_password,
                    "host": self._settings.postgres_host,
                    "port": self._settings.postgres_port,
                    "table_schema": self._settings.postgres_schema,
                }, "postgres_tools"),
            ))
        return tools

    def _build_search_tools(self) -> list[Any]:
        return self._load_toolkits(
            ("agno.tools.websearch", "WebSearchTools",
             {"fixed_max_results": 5, "backend": "duckduckgo"}, "websearch_tools"),
        )

    def _load_toolkits(self, *defs: tuple[str, str, dict[str, Any], str]) -> list[Any]:
        loaded: list[Any] = []
        for module_name, class_name, kwargs, label in defs:
            try:
                module = __import__(module_name, fromlist=[class_name])
                loaded.append(getattr(module, class_name)(**kwargs))
                LOGGER.info("Toolkit abilitato: %s", label)
            except Exception as exc:
                LOGGER.warning("Toolkit %s saltato: %s", label, exc)
        return loaded

    def _has_postgres_config(self) -> bool:
        s = self._settings
        return all([s.postgres_db_name, s.postgres_user, s.postgres_password,
                    s.postgres_host, s.postgres_port is not None])

    # ------------------------------------------------------------------
    # SQLite schema migration (da agents-ai/agno_service.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _initialize_required_tables(db: Any) -> None:
        try:
            db._get_table(table_type="sessions", create_table_if_not_found=True)
            db._get_table(table_type="memories", create_table_if_not_found=True)
        except Exception as exc:
            raise RuntimeError("Inizializzazione tabelle SQLite Agno fallita.") from exc

    @classmethod
    def _archive_incompatible_db(cls, db_path: Path) -> None:
        if not db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            tables = {r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "agent_sessions" in tables:
                cols = cls._read_columns(cur, "agent_sessions")
                if not cls.REQUIRED_SESSION_COLUMNS.issubset(cols):
                    cls._archive_db(db_path, reason="schema agent_sessions incompatibile")
                    return
            if "agent_memories" in tables:
                cols = cls._read_columns(cur, "agent_memories")
                if not cls.REQUIRED_MEMORY_COLUMNS.issubset(cols):
                    cls._archive_db(db_path, reason="schema agent_memories incompatibile")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _read_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
        return {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}

    @staticmethod
    def _archive_db(db_path: Path, *, reason: str) -> None:
        archive = db_path.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archived = archive / f"{db_path.stem}-{ts}{db_path.suffix}"
        db_path.replace(archived)
        LOGGER.warning("DB archiviato %s → %s (%s)", db_path, archived, reason)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _truncate(self, text: str) -> str:
        text = text.strip()
        limit = self._settings.attachment_text_char_limit
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}\n\n[Contenuto troncato]"

    @staticmethod
    def _coerce_output(run_output: Any) -> str:
        content = getattr(run_output, "content", run_output)
        if content is None:
            return ""
        return str(content).strip() if not isinstance(content, str) else content.strip()

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        if response is None:
            return ""
        out = getattr(response, "output_text", None)
        if isinstance(out, str):
            return out.strip()
        chunks = []
        for item in getattr(response, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    chunks.append(str(t).strip())
        return "\n\n".join(c for c in chunks if c).strip()

    @staticmethod
    def _guess_image_mime(filename: str) -> str:
        name = filename.lower()
        if name.endswith(".png"):
            return "image/png"
        if name.endswith(".webp"):
            return "image/webp"
        if name.endswith(".gif"):
            return "image/gif"
        return "image/jpeg"

    @staticmethod
    def _decode_bytes(data: bytes) -> str:
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

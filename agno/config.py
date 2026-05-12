"""
Configurazione unificata per il sistema multi-agente Agno.

Carica da variabili d'ambiente (e da un file .env nella cwd).
Rispetto a agents-ai, OpenAI non è più il backend primario:
  - LLM locale: Ollama (qwen2.5:7b)
  - LLM cloud:  Anthropic Claude (opzionale)
  - OpenAI:     conservato opzionalmente per la sola trascrizione audio
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers (stessa logica di agents-ai/config.py)
# ---------------------------------------------------------------------------

def _parse_chat_ids(raw: str) -> tuple[int, ...]:
    return tuple(int(v.strip()) for v in raw.split(",") if v.strip())


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if not raw or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw!r}")


def _parse_int(raw: str | None, *, default: int) -> int:
    if not raw or not raw.strip():
        return default
    return int(raw.strip())


def _parse_debug_level(raw: str | None, *, default: int = 1) -> int:
    level = _parse_int(raw, default=default)
    if level not in (1, 2):
        raise ValueError("AGNO_DEBUG_LEVEL must be 1 or 2.")
    return level


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    # --- Telegram ---
    telegram_bot_token: str
    allowed_chat_ids: tuple[int, ...]

    # --- Ollama (LLM locale, primario) ---
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_embed_model: str = "nomic-embed-text"

    # --- Anthropic (cloud, opzionale — fallback o agenti specializzati) ---
    anthropic_api_key: str | None = None

    # --- OpenAI (opzionale — solo trascrizione audio via Whisper) ---
    openai_api_key: str | None = None
    openai_transcription_model: str = "gpt-4o-mini-transcribe"

    # --- Persistenza ---
    agno_db_file: str = "state/agents.db"

    # --- Paths ---
    repos_base_dir: str = "~/git"           # radice di tutti i repo clonati
    tools_base_dir: str = "."
    tools_output_dir: str = "logs/generated"

    # --- Logging e debug ---
    log_level: str = "INFO"
    agno_debug_mode: bool = False
    agno_debug_level: int = 1
    httpx_log_level: str = "WARNING"

    # --- Limiti ---
    attachment_text_char_limit: int = 24_000

    # --- PostgreSQL (opzionale) ---
    postgres_db_name: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_host: str | None = None
    postgres_port: int | None = None
    postgres_schema: str = "public"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    _load_dotenv(Path(".env"))

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable.")

    return Settings(
        # Telegram
        telegram_bot_token=telegram_token,
        allowed_chat_ids=_parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),

        # Ollama
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip() or "http://localhost:11434",
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b",
        ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").strip() or "nomic-embed-text",

        # Anthropic
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip() or None,

        # OpenAI (opzionale)
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        openai_transcription_model=(
            os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe").strip()
            or "gpt-4o-mini-transcribe"
        ),

        # Persistenza
        agno_db_file=os.getenv("AGNO_DB_FILE", "state/agents.db").strip() or "state/agents.db",

        # Paths
        repos_base_dir=os.getenv("REPOS_BASE_DIR", "~/git").strip() or "~/git",
        tools_base_dir=os.getenv("TOOLS_BASE_DIR", ".").strip() or ".",
        tools_output_dir=os.getenv("TOOLS_OUTPUT_DIR", "logs/generated").strip() or "logs/generated",

        # Logging
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        agno_debug_mode=_parse_bool(os.getenv("AGNO_DEBUG_MODE"), default=False),
        agno_debug_level=_parse_debug_level(os.getenv("AGNO_DEBUG_LEVEL"), default=1),
        httpx_log_level=os.getenv("HTTPX_LOG_LEVEL", "WARNING").strip().upper() or "WARNING",

        # Limiti
        attachment_text_char_limit=_parse_int(
            os.getenv("ATTACHMENT_TEXT_CHAR_LIMIT"), default=24_000
        ),

        # PostgreSQL
        postgres_db_name=os.getenv("POSTGRES_DB_NAME", "").strip() or None,
        postgres_user=os.getenv("POSTGRES_USER", "").strip() or None,
        postgres_password=os.getenv("POSTGRES_PASSWORD", "").strip() or None,
        postgres_host=os.getenv("POSTGRES_HOST", "").strip() or None,
        postgres_port=(
            _parse_int(os.getenv("POSTGRES_PORT"), default=5432)
            if os.getenv("POSTGRES_PORT", "").strip()
            else None
        ),
        postgres_schema=os.getenv("POSTGRES_SCHEMA", "public").strip() or "public",
    )

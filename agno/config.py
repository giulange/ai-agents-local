from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_chat_ids(raw_value: str) -> tuple[int, ...]:
    if not raw_value.strip():
        return ()
    values = []
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        values.append(int(item))
    return tuple(values)


def _parse_bool(raw_value: str | None, *, default: bool = False) -> bool:
    if raw_value is None or not raw_value.strip():
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw_value!r}")


def _parse_debug_level(raw_value: str | None, *, default: int = 1) -> int:
    if raw_value is None or not raw_value.strip():
        return default

    debug_level = int(raw_value.strip())
    if debug_level not in (1, 2):
        raise ValueError("AGNO_DEBUG_LEVEL must be 1 or 2.")
    return debug_level


def _parse_int(raw_value: str | None, *, default: int) -> int:
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value.strip())


def _parse_csv_strings(raw_value: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw_value is None or not raw_value.strip():
        return default
    values = []
    for item in raw_value.split(","):
        normalized = item.strip()
        if normalized:
            values.append(normalized)
    return tuple(values)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    allowed_chat_ids: tuple[int, ...]
    openai_api_key: str
    openai_model: str
    openai_transcription_model: str
    agno_db_file: str
    log_level: str = "INFO"
    agno_debug_mode: bool = False
    agno_debug_level: int = 1
    httpx_log_level: str = "WARNING"
    attachment_text_char_limit: int = 24000
    tools_base_dir: str = "."
    tools_output_dir: str = "data/generated"
    csv_tool_glob: str = "**/*.csv"
    runtime_skills_dir: str = "skills/runtime"
    enabled_runtime_skills: tuple[str, ...] = ("pdf", "pptx", "brainstorming")
    postgres_db_name: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_host: str | None = None
    postgres_port: int | None = None
    postgres_schema: str = "public"
    # --- Multi-agent extensions ---
    anthropic_api_key: str = ""
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"
    git_repos_base_dir: str = "~/git"
    knowledge_store_path: str = "knowledge/lancedb"


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
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
        telegram_bot_token=telegram_token,
        allowed_chat_ids=_parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini",
        openai_transcription_model=(
            os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe").strip()
            or "gpt-4o-mini-transcribe"
        ),
        agno_db_file=os.getenv("AGNO_DB_FILE", "data/agents.db").strip() or "data/agents.db",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        agno_debug_mode=_parse_bool(os.getenv("AGNO_DEBUG_MODE"), default=False),
        agno_debug_level=_parse_debug_level(os.getenv("AGNO_DEBUG_LEVEL"), default=1),
        httpx_log_level=os.getenv("HTTPX_LOG_LEVEL", "WARNING").strip().upper() or "WARNING",
        attachment_text_char_limit=_parse_int(
            os.getenv("ATTACHMENT_TEXT_CHAR_LIMIT"),
            default=24000,
        ),
        tools_base_dir=os.getenv("TOOLS_BASE_DIR", ".").strip() or ".",
        tools_output_dir=os.getenv("TOOLS_OUTPUT_DIR", "data/generated").strip() or "data/generated",
        csv_tool_glob=os.getenv("CSV_TOOL_GLOB", "**/*.csv").strip() or "**/*.csv",
        runtime_skills_dir=os.getenv("RUNTIME_SKILLS_DIR", "skills/runtime").strip() or "skills/runtime",
        enabled_runtime_skills=_parse_csv_strings(
            os.getenv("ENABLED_RUNTIME_SKILLS"),
            default=("pdf", "pptx", "brainstorming"),
        ),
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
        # --- Multi-agent extensions ---
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip(),
        ollama_embedding_model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text").strip(),
        git_repos_base_dir=os.getenv("GIT_REPOS_BASE_DIR", "~/git").strip(),
        knowledge_store_path=os.getenv("KNOWLEDGE_STORE_PATH", "knowledge/lancedb").strip(),
    )

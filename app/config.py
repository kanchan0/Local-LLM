from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip().casefold() in {"", "auto", "automatic"}:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer or auto") from exc


@dataclass(frozen=True)
class Settings:
    app_secret_key: str
    data_dir: Path
    ollama_host: str
    ollama_model: str
    app_host: str
    app_port: int
    max_upload_bytes: int
    max_pdf_pages: int
    max_docx_chars: int
    retention_seconds: int
    max_concurrent_jobs: int
    active_user_window_seconds: int = 300
    ollama_num_ctx: int | None = None
    ollama_thinking: bool = True
    admin_username: str | None = None
    admin_password: str | None = field(default=None, repr=False)
    user_username: str | None = None
    user_password: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        data_dir = Path(os.getenv("LOCAL_LLM_DATA_DIR", ".data")).expanduser()
        retention_minutes = _int_env("FILE_RETENTION_MINUTES", 30)
        if retention_minutes <= 0:
            raise ValueError("FILE_RETENTION_MINUTES must be positive")

        settings = cls(
            app_secret_key=os.getenv("APP_SECRET_KEY", "development-only-change-me"),
            data_dir=data_dir,
            ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.3"),
            ollama_thinking=_bool_env("OLLAMA_THINKING", True),
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=_int_env("APP_PORT", 8080),
            max_upload_bytes=_int_env("MAX_UPLOAD_MB", 25) * 1024 * 1024,
            max_pdf_pages=_int_env("MAX_PDF_PAGES", 50),
            max_docx_chars=_int_env("MAX_DOCX_CHARS", 200_000),
            retention_seconds=retention_minutes * 60,
            max_concurrent_jobs=_int_env("MAX_CONCURRENT_JOBS", 2),
            active_user_window_seconds=_int_env("ACTIVE_USER_WINDOW_SECONDS", 300),
            ollama_num_ctx=_optional_int_env("OLLAMA_NUM_CTX"),
            admin_username=os.getenv("ADMIN_USERNAME") or None,
            admin_password=os.getenv("ADMIN_PASSWORD") or None,
            user_username=os.getenv("USER_USERNAME") or None,
            user_password=os.getenv("USER_PASSWORD") or None,
        )
        if settings.max_upload_bytes <= 0:
            raise ValueError("MAX_UPLOAD_MB must be positive")
        if settings.max_pdf_pages <= 0 or settings.max_docx_chars <= 0:
            raise ValueError("document limits must be positive")
        if settings.max_concurrent_jobs <= 0:
            raise ValueError("MAX_CONCURRENT_JOBS must be positive")
        if settings.active_user_window_seconds <= 0:
            raise ValueError("ACTIVE_USER_WINDOW_SECONDS must be positive")
        if settings.ollama_num_ctx is not None and settings.ollama_num_ctx <= 0:
            raise ValueError("OLLAMA_NUM_CTX must be positive")
        for label, username, password in (
            ("ADMIN", settings.admin_username, settings.admin_password),
            ("USER", settings.user_username, settings.user_password),
        ):
            if bool(username) != bool(password):
                raise ValueError(f"{label}_USERNAME and {label}_PASSWORD must be supplied together")
            if password is not None and len(password) < 10:
                raise ValueError(f"{label}_PASSWORD must be at least 10 characters")
        return settings

    @property
    def database_path(self) -> Path:
        return self.data_dir / "users.sqlite3"

    @property
    def temporary_dir(self) -> Path:
        return self.data_dir / "temporary"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.temporary_dir.mkdir(parents=True, exist_ok=True)

from __future__ import annotations

import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileRecord:
    file_id: str
    owner_id: int
    original_name: str
    extension: str
    path: Path
    created_at: float
    expires_at: float
    output_path: Path | None = None
    output_name: str | None = None
    download_token: str | None = None


class TemporaryFileStore:
    def __init__(self, root: Path, retention_seconds: int):
        self.root = root
        self.retention_seconds = retention_seconds
        self.records: dict[str, FileRecord] = {}
        self.downloads: dict[str, str] = {}
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, owner_id: int, original_name: str, extension: str, content: bytes) -> FileRecord:
        file_id = secrets.token_urlsafe(18)
        directory = self.root / file_id
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / f"source{extension}"
        path.write_bytes(content)
        now = time.time()
        record = FileRecord(
            file_id=file_id,
            owner_id=owner_id,
            original_name=original_name,
            extension=extension,
            path=path,
            created_at=now,
            expires_at=now + self.retention_seconds,
        )
        with self.lock:
            self.records[file_id] = record
        return record

    def get_owned(self, file_id: str, owner_id: int) -> FileRecord | None:
        with self.lock:
            record = self.records.get(file_id)
            if not record or record.owner_id != owner_id or record.expires_at <= time.time():
                return None
            return record

    def attach_output(self, record: FileRecord, output_name: str, content: bytes) -> str:
        output_path = record.path.parent / "corrected.docx"
        output_path.write_bytes(content)
        token = secrets.token_urlsafe(32)
        with self.lock:
            record.output_path = output_path
            record.output_name = output_name
            record.download_token = token
            self.downloads[token] = record.file_id
        return token

    def get_download(self, token: str, owner_id: int) -> FileRecord | None:
        with self.lock:
            file_id = self.downloads.get(token)
            record = self.records.get(file_id) if file_id else None
            if (
                not record
                or record.owner_id != owner_id
                or record.expires_at <= time.time()
                or record.output_path is None
                or not record.output_path.exists()
            ):
                return None
            return record

    def delete(self, file_id: str, owner_id: int) -> bool:
        with self.lock:
            record = self.records.get(file_id)
            if not record or record.owner_id != owner_id:
                return False
            self._remove_locked(record)
            return True

    def cleanup(self) -> int:
        removed = 0
        now = time.time()
        with self.lock:
            for record in list(self.records.values()):
                if record.expires_at <= now:
                    self._remove_locked(record)
                    removed += 1
        return removed

    def _remove_locked(self, record: FileRecord) -> None:
        self.records.pop(record.file_id, None)
        if record.download_token:
            self.downloads.pop(record.download_token, None)
        shutil.rmtree(record.path.parent, ignore_errors=True)

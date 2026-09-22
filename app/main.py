from __future__ import annotations

import asyncio
import json
import logging
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from .config import Settings
from .correction import correct_document
from .database import UserDatabase
from .documents import DOCUMENT_EXTENSIONS, DocumentError, extension_for, parse_document, select_context
from .ollama_service import OllamaService, build_chat_messages
from .security import current_user, hash_password, require_admin, require_csrf, require_user, verify_password
from .storage import FileRecord, TemporaryFileStore


LOGGER = logging.getLogger(__name__)


class JobTracker:
    """Bound model work while exposing useful queue information to administrators."""

    def __init__(self, limit: int):
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._lock = asyncio.Lock()
        self.running = 0
        self.queued = 0

    @asynccontextmanager
    async def slot(self):
        async with self._lock:
            self.queued += 1
        acquired = False
        registered = False
        try:
            await self._semaphore.acquire()
            acquired = True
            async with self._lock:
                self.queued -= 1
                self.running += 1
                registered = True
            yield
        finally:
            if registered:
                async with self._lock:
                    self.running -= 1
            elif not registered:
                async with self._lock:
                    self.queued -= 1
            if acquired:
                self._semaphore.release()

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return {"limit": self.limit, "running": self.running, "queued": self.queued}


def _bootstrap_configured_users(database: UserDatabase, settings: Settings) -> None:
    configured_users = (
        (settings.admin_username, settings.admin_password, "admin"),
        (settings.user_username, settings.user_password, "user"),
    )
    for username, password, role in configured_users:
        if not username or not password or database.get_by_username(username):
            continue
        database.create_user(username, hash_password(password), role)
        LOGGER.info("bootstrapped %s account", role)


class ChatMessage(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=40_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    file_id: str | None = None


CORRECTION_TERMS = {
    "correct",
    "correction",
    "grammar",
    "grammatical",
    "proofread",
    "proofreading",
    "spelling",
    "punctuation",
    "edit",
    "editing",
    "fix errors",
    "व्याकरण",
    "सुधार",
    "गलतियाँ",
    "गलतियां",
    "वर्तनी",
}


def _is_correction_request(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in CORRECTION_TERMS)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    database = UserDatabase(settings.database_path)
    database.initialize()
    _bootstrap_configured_users(database, settings)
    store = TemporaryFileStore(settings.temporary_dir, settings.retention_seconds)
    ollama = OllamaService(
        settings.ollama_host,
        settings.ollama_model,
        settings.ollama_thinking,
        settings.ollama_num_ctx,
    )
    job_tracker = JobTracker(settings.max_concurrent_jobs)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    async def cleanup_loop() -> None:
        while True:
            await asyncio.sleep(60)
            store.cleanup()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        cleanup_task = asyncio.create_task(cleanup_loop())
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="SenaSaarthi AI", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key,
        max_age=8 * 60 * 60,
        same_site="lax",
        https_only=False,
    )
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    async def authenticated_user(request: Request) -> dict[str, Any]:
        return require_user(request, database)

    async def administrator(request: Request) -> dict[str, Any]:
        return require_admin(request, database)

    def render_admin_page(
        request: Request,
        user: dict[str, Any],
        *,
        error: str | None = None,
        notice: str | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        users = database.list_users(settings.active_user_window_seconds)
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "user": user,
                "csrf_token": request.session.get("csrf_token", ""),
                "users": users,
                "active_count": sum(1 for item in users if item["active"]),
                "error": error,
                "notice": notice,
            },
            status_code=status_code,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "model": settings.ollama_model}

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        user = current_user(request, database)
        csrf_token = request.session.get("csrf_token", "") if user else ""
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"user": user, "csrf_token": csrf_token, "model": settings.ollama_model},
        )

    @app.post("/login")
    async def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]):
        user = database.get_by_username(username)
        if not user or not user["enabled"] or not verify_password(password, user["password_hash"]):
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={"user": None, "csrf_token": "", "model": settings.ollama_model, "login_error": "Invalid login."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        request.session.clear()
        request.session["user_id"] = int(user["id"])
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        request.session["session_version"] = int(user["session_version"])
        database.record_login(int(user["id"]))
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/logout")
    async def logout(request: Request, user: dict[str, Any] = Depends(authenticated_user), csrf_token: Annotated[str, Form()] = ""):
        require_csrf(request, csrf_token)
        request.session.clear()
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_home(request: Request, user: dict[str, Any] = Depends(administrator)) -> HTMLResponse:
        return render_admin_page(request, user, notice=request.query_params.get("notice"))

    @app.post("/admin/users")
    async def admin_create_user(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
        role: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()] = "",
        user: dict[str, Any] = Depends(administrator),
    ):
        require_csrf(request, csrf_token)
        try:
            database.create_user(username, hash_password(password), role)
        except sqlite3.IntegrityError:
            return render_admin_page(request, user, error="That username already exists.", status_code=400)
        except ValueError as exc:
            return render_admin_page(request, user, error=str(exc), status_code=400)
        return RedirectResponse("/admin?notice=User+created", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/admin/users/{user_id}/toggle")
    async def admin_toggle_user(
        user_id: int,
        request: Request,
        csrf_token: Annotated[str, Form()] = "",
        user: dict[str, Any] = Depends(administrator),
    ):
        require_csrf(request, csrf_token)
        target = database.get_by_id(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        if target["id"] == user["id"]:
            return render_admin_page(request, user, error="You cannot disable your own account.", status_code=400)
        if target["role"] == "admin" and target["enabled"]:
            enabled_admins = [item for item in database.list_users() if item["role"] == "admin" and item["enabled"]]
            if len(enabled_admins) <= 1:
                return render_admin_page(request, user, error="At least one administrator must remain enabled.", status_code=400)
        database.set_enabled_by_id(user_id, not bool(target["enabled"]))
        return RedirectResponse("/admin?notice=Account+status+updated", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/admin/users/{user_id}/reset-password")
    async def admin_reset_password(
        user_id: int,
        request: Request,
        password: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()] = "",
        user: dict[str, Any] = Depends(administrator),
    ):
        require_csrf(request, csrf_token)
        if not database.get_by_id(user_id):
            raise HTTPException(status_code=404, detail="user not found")
        try:
            database.set_password(user_id, hash_password(password))
        except ValueError as exc:
            return render_admin_page(request, user, error=str(exc), status_code=400)
        return RedirectResponse("/admin?notice=Password+reset", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/admin/users/{user_id}/revoke-sessions")
    async def admin_revoke_sessions(
        user_id: int,
        request: Request,
        csrf_token: Annotated[str, Form()] = "",
        user: dict[str, Any] = Depends(administrator),
    ):
        require_csrf(request, csrf_token)
        target = database.get_by_id(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        if target["id"] == user["id"]:
            return render_admin_page(request, user, error="You cannot revoke your own current session.", status_code=400)
        database.revoke_sessions(user_id)
        return RedirectResponse("/admin?notice=Sessions+revoked", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/api/heartbeat")
    async def heartbeat(request: Request, user: dict[str, Any] = Depends(authenticated_user)):
        require_csrf(request)
        return {"ok": True}

    @app.get("/api/admin/status")
    async def admin_status(request: Request, user: dict[str, Any] = Depends(administrator)):
        del request, user
        return {
            "jobs": await job_tracker.snapshot(),
            "ollama": await ollama.status(),
            "active_users": sum(
                1 for item in database.list_users(settings.active_user_window_seconds) if item["active"]
            ),
        }

    @app.post("/api/uploads")
    async def upload_file(request: Request, user: dict[str, Any] = Depends(authenticated_user), upload: UploadFile = File(...)):
        require_csrf(request)
        filename = Path(upload.filename or "upload").name
        try:
            extension = extension_for(filename)
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        content = await upload.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="file exceeds the 25 MB limit")
        record = store.create(user["id"], filename, extension, content)
        if extension in DOCUMENT_EXTENSIONS:
            try:
                await asyncio.to_thread(
                    parse_document,
                    record.path,
                    max_pdf_pages=settings.max_pdf_pages,
                    max_docx_chars=settings.max_docx_chars,
                )
            except DocumentError as exc:
                store.delete(record.file_id, user["id"])
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "file_id": record.file_id,
            "name": record.original_name,
            "extension": record.extension,
            "expires_at": record.expires_at,
        }

    @app.post("/api/chat")
    async def chat(request: Request, body: ChatRequest, user: dict[str, Any] = Depends(authenticated_user)):
        require_csrf(request)
        if body.messages[-1].role != "user":
            raise HTTPException(status_code=400, detail="the final message must be from the user")
        file_record: FileRecord | None = None
        if body.file_id:
            file_record = store.get_owned(body.file_id, user["id"])
            if not file_record:
                raise HTTPException(status_code=404, detail="file not found or expired")

        async def event_stream():
            async with job_tracker.slot():
                try:
                    prompt = body.messages[-1].content
                    if file_record and file_record.extension in DOCUMENT_EXTENSIONS and _is_correction_request(prompt):
                        yield _sse("status", {"message": "Reading the document..."})
                        progress_queue: asyncio.Queue[str] = asyncio.Queue()

                        async def correction_progress(stage: str, current: int, total: int) -> None:
                            progress_queue.put_nowait(
                                _sse(
                                    "status",
                                    {"message": f"{stage.title()} section {current} of {total}..."},
                                )
                            )

                        correction_task = asyncio.create_task(
                            correct_document(
                                file_record.path,
                                file_record.path.parent / "corrected.docx",
                                file_record.original_name,
                                ollama,
                                max_pdf_pages=settings.max_pdf_pages,
                                max_docx_chars=settings.max_docx_chars,
                                progress=correction_progress,
                            )
                        )
                        while not correction_task.done():
                            try:
                                yield await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                            except asyncio.TimeoutError:
                                pass
                        while not progress_queue.empty():
                            yield progress_queue.get_nowait()
                        result = await correction_task
                        token = store.attach_output(file_record, result.output_name, result.output_path.read_bytes())
                        summary = "Correction complete.\n\n" + "\n".join(f"- {note}" for note in result.notes)
                        yield _sse("message", {"content": summary})
                        yield _sse(
                            "file",
                            {
                                "name": result.output_name,
                                "download_url": f"/api/files/{token}",
                                "expires_at": file_record.expires_at,
                            },
                        )
                        yield _sse("done", {})
                        return

                    file_context = None
                    if file_record:
                        if file_record.extension in DOCUMENT_EXTENSIONS:
                            parsed = await asyncio.to_thread(
                                parse_document,
                                file_record.path,
                                max_pdf_pages=settings.max_pdf_pages,
                                max_docx_chars=settings.max_docx_chars,
                            )
                            file_context = select_context(parsed, prompt)
                        else:
                            file_context = file_record.path.read_text(encoding="utf-8", errors="replace")[:30_000]
                    messages = build_chat_messages(
                        [message.model_dump() for message in body.messages],
                        file_context,
                    )
                    yield _sse("start", {"model": settings.ollama_model})
                    saw_content = False
                    async for chunk in ollama.stream_chat(messages):
                        if chunk.thinking:
                            yield _sse("status", {"message": "Reasoning…"})
                        if chunk.content:
                            saw_content = True
                            yield _sse("token", {"content": chunk.content})
                    if not saw_content:
                        yield _sse(
                            "error",
                            {
                                "message": (
                                    "The model finished reasoning without producing an answer. "
                                    "Try again or shorten the document."
                                )
                            },
                        )
                        return
                    yield _sse("done", {})
                except DocumentError as exc:
                    yield _sse("error", {"message": str(exc)})
                except Exception:
                    LOGGER.exception("chat request failed")
                    yield _sse("error", {"message": "The request could not be completed."})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/files/{download_token}")
    async def download_file(download_token: str, user: dict[str, Any] = Depends(authenticated_user)):
        record = store.get_download(download_token, user["id"])
        if not record or not record.output_path or not record.output_name:
            raise HTTPException(status_code=404, detail="download not found or expired")
        return FileResponse(
            record.output_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=record.output_name,
        )

    @app.delete("/api/files/{file_id}")
    async def delete_file(file_id: str, request: Request, user: dict[str, Any] = Depends(authenticated_user)):
        require_csrf(request)
        if not store.delete(file_id, user["id"]):
            raise HTTPException(status_code=404, detail="file not found")
        return JSONResponse({"deleted": True})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()

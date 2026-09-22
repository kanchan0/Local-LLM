import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import UserDatabase
from app.main import create_app
from app.security import hash_password


def _app(tmp_path: Path):
    settings = Settings(
        app_secret_key="test-secret-key-which-is-long",
        data_dir=tmp_path,
        ollama_host="http://127.0.0.1:11434",
        ollama_model="test-model",
        app_host="127.0.0.1",
        app_port=8080,
        max_upload_bytes=1024 * 1024,
        max_pdf_pages=50,
        max_docx_chars=200_000,
        retention_seconds=1800,
        max_concurrent_jobs=2,
    )
    settings.ensure_directories()
    database = UserDatabase(settings.database_path)
    database.initialize()
    database.create_user("alice", hash_password("a-strong-password"))
    return create_app(settings)


def _login(client: TestClient) -> str:
    return _login_as(client, "alice", "a-strong-password")


def _login_as(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/")
    return re.search(r'csrf_token":\s*"([^"]+)', page.text).group(1)


def test_authenticated_upload_requires_csrf_and_owner(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        token = _login(client)
        rejected = client.post(
            "/api/uploads",
            files={"upload": ("note.txt", b"hello", "text/plain")},
        )
        assert rejected.status_code == 403

        uploaded = client.post(
            "/api/uploads",
            files={"upload": ("note.txt", b"hello", "text/plain")},
            headers={"X-CSRF-Token": token},
        )
        assert uploaded.status_code == 200
        file_id = uploaded.json()["file_id"]

        deleted = client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": token})
        assert deleted.status_code == 200


def test_home_and_health_are_reachable(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "/static/styles.css?v=20260921-7" in home.text
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "model": "test-model"}


def test_env_configured_users_are_bootstrapped_without_overwriting(tmp_path: Path):
    settings = Settings(
        app_secret_key="test-secret-key-which-is-long",
        data_dir=tmp_path,
        ollama_host="http://127.0.0.1:11434",
        ollama_model="test-model",
        app_host="127.0.0.1",
        app_port=8080,
        max_upload_bytes=1024 * 1024,
        max_pdf_pages=50,
        max_docx_chars=200_000,
        retention_seconds=1800,
        max_concurrent_jobs=2,
        admin_username="configured-admin",
        admin_password="configured-admin-password",
        user_username="configured-user",
        user_password="configured-user-password",
    )
    create_app(settings)
    database = UserDatabase(settings.database_path)
    assert database.get_by_username("configured-admin")["role"] == "admin"
    assert database.get_by_username("configured-user")["role"] == "user"

    database.set_enabled("configured-user", False)
    create_app(settings)
    assert database.get_by_username("configured-user")["enabled"] == 0


def test_normal_user_cannot_access_admin_page(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        _login(client)
        response = client.get("/admin")
        assert response.status_code == 403


def test_admin_can_create_disable_and_reset_users(tmp_path: Path):
    settings = Settings(
        app_secret_key="test-secret-key-which-is-long",
        data_dir=tmp_path,
        ollama_host="http://127.0.0.1:11434",
        ollama_model="test-model",
        app_host="127.0.0.1",
        app_port=8080,
        max_upload_bytes=1024 * 1024,
        max_pdf_pages=50,
        max_docx_chars=200_000,
        retention_seconds=1800,
        max_concurrent_jobs=2,
    )
    settings.ensure_directories()
    database = UserDatabase(settings.database_path)
    database.initialize()
    database.create_user("admin", hash_password("admin-password"), "admin")

    with TestClient(create_app(settings)) as client:
        csrf = _login_as(client, "admin", "admin-password")
        admin_page = client.get("/admin")
        assert admin_page.status_code == 200
        assert "User management" in admin_page.text
        assert "active now" in admin_page.text

        created = client.post(
            "/admin/users",
            data={
                "username": "bravo",
                "password": "bravo-password",
                "role": "user",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        bravo = database.get_by_username("bravo")
        assert bravo and bravo["role"] == "user"

        with TestClient(create_app(settings)) as bravo_client:
            _login_as(bravo_client, "bravo", "bravo-password")
            revoked = client.post(
                f"/admin/users/{bravo['id']}/revoke-sessions",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert revoked.status_code == 303
            assert "Sign in" in bravo_client.get("/").text

        toggled = client.post(
            f"/admin/users/{bravo['id']}/toggle",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert toggled.status_code == 303
        assert database.get_by_id(bravo["id"])["enabled"] == 0

        reset = client.post(
            f"/admin/users/{bravo['id']}/reset-password",
            data={"password": "bravo-new-password", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert reset.status_code == 303

        heartbeat = client.post("/api/heartbeat", headers={"X-CSRF-Token": csrf})
        assert heartbeat.status_code == 200
        assert database.get_by_username("admin")["last_seen_at"] is not None

        live_status = client.get("/api/admin/status")
        assert live_status.status_code == 200
        assert set(live_status.json()) == {"jobs", "ollama", "active_users"}
        assert live_status.json()["jobs"]["limit"] == 2

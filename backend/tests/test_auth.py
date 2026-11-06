from contextlib import closing

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db.database import connect_database
from backend.app.main import create_app


PASSWORD = "correct horse battery staple"


def make_client(tmp_path):
    settings = Settings(
        database_path=tmp_path / "app.db",
        storage_path=tmp_path / "cases",
        session_cookie_name="test_session",
        session_ttl_seconds=3600,
    )
    return TestClient(create_app(settings)), settings


def register(client: TestClient, username="Sample_User", password=PASSWORD):
    return client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )


def test_registration_creates_argon2_user_and_http_only_session(tmp_path):
    client, settings = make_client(tmp_path)
    with client:
        response = register(client)

        assert response.status_code == 201
        body = response.json()
        assert body["username"] == "sample_user"
        assert body["csrf_token"]
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie

        with closing(connect_database(settings.database_path)) as connection:
            row = connection.execute(
                "SELECT username, password_hash FROM users WHERE id = ?",
                (body["id"],),
            ).fetchone()
            sessions = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (body["id"],)
            ).fetchone()[0]

        assert row[0] == "sample_user"
        assert row[1] != PASSWORD
        assert PasswordHasher().verify(row[1], PASSWORD)
        assert sessions == 1

        current = client.get("/auth/me")
        assert current.status_code == 200
        assert current.json()["id"] == body["id"]
        assert current.json()["csrf_token"] == body["csrf_token"]


def test_login_is_case_normalized_and_logout_revokes_session(tmp_path):
    client, settings = make_client(tmp_path)
    with client:
        assert register(client).status_code == 201
        logout = client.post(
            "/auth/logout",
            headers={"X-CSRF-Token": "invalid"},
        )
        assert logout.status_code == 403
        assert client.get("/auth/me").status_code == 200

        logout = client.post(
            "/auth/logout",
            headers={"X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]},
        )
        assert logout.status_code == 200
        assert client.get("/auth/me").status_code == 401

        login = client.post(
            "/auth/login",
            json={"username": "SAMPLE_USER", "password": PASSWORD},
        )
        assert login.status_code == 200
        assert login.json()["username"] == "sample_user"
        assert client.get("/auth/me").status_code == 200

        with closing(connect_database(settings.database_path)) as connection:
            sessions = connection.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0]
        assert sessions == 1


def test_registration_rejects_duplicate_username_and_weak_password(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        assert register(client).status_code == 201
        duplicate = register(client, username="SAMPLE_USER")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "username_taken"

        weak_password = register(client, username="another", password="short")
        assert weak_password.status_code == 422


def test_login_uses_generic_failure_and_locks_after_repeated_attempts(tmp_path):
    client, settings = make_client(tmp_path)
    with client:
        assert register(client).status_code == 201
        client.post("/auth/logout", headers={"X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]})

        for _ in range(5):
            response = client.post(
                "/auth/login",
                json={"username": "sample_user", "password": "incorrect password"},
            )
            assert response.status_code == 401
            assert response.json()["error"]["message"] == "Invalid username or password."

        correct_password = client.post(
            "/auth/login",
            json={"username": "sample_user", "password": PASSWORD},
        )
        assert correct_password.status_code == 401
        assert correct_password.json()["error"]["message"] == "Invalid username or password."

    with closing(connect_database(settings.database_path)) as connection:
        attempts, locked_until = connection.execute(
            "SELECT failed_attempts, locked_until FROM users WHERE username = ?",
            ("sample_user",),
        ).fetchone()
    assert attempts == 5
    assert locked_until is not None


def test_registration_rejects_unexpected_browser_origin(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        response = client.post(
            "/auth/register",
            headers={"Origin": "https://attacker.example"},
            json={"username": "sample_user", "password": PASSWORD},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"

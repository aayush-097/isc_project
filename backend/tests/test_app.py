from contextlib import closing
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db.database import SCHEMA, connect_database, initialize_database
from backend.app.main import create_app


def make_test_app(tmp_path):
    settings = Settings(
        database_path=tmp_path / "app.db",
        storage_path=tmp_path / "cases",
    )
    return create_app(settings)


def test_health_and_database_initialization(tmp_path):
    app = make_test_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert (tmp_path / "cases").is_dir()

    with closing(sqlite3.connect(tmp_path / "app.db")) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert {"users", "cases", "jobs", "sessions"} <= tables
    assert journal_mode.lower() == "wal"


def test_database_initialization_preserves_existing_rows(tmp_path):
    app = make_test_app(tmp_path)
    with TestClient(app):
        pass

    with closing(connect_database(tmp_path / "app.db")) as connection:
        connection.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            ("user-1", "sample", "already-hashed"),
        )
        connection.commit()

    with TestClient(app):
        pass

    with closing(connect_database(tmp_path / "app.db")) as connection:
        row = connection.execute(
            "SELECT username, password_hash FROM users WHERE id = ?",
            ("user-1",),
        ).fetchone()

    assert row == ("sample", "already-hashed")


def test_additive_metrics_migration_preserves_existing_jobs(tmp_path):
    database_path = tmp_path / "legacy.db"
    legacy_schema = SCHEMA.replace("    metrics_json TEXT,\n", "")
    assert legacy_schema != SCHEMA
    with closing(sqlite3.connect(database_path)) as connection:
        connection.executescript(legacy_schema)
        connection.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            ("user-1", "sample", "already-hashed"),
        )
        connection.execute(
            "INSERT INTO cases (id, title, owner_id, folder_path) VALUES (?, ?, ?, ?)",
            ("case-1", "Existing case", "user-1", "existing/path"),
        )
        connection.execute(
            "INSERT INTO jobs (id, case_id, status, progress) VALUES (?, ?, ?, ?)",
            ("job-1", "case-1", "processing", 42),
        )
        connection.commit()

    initialize_database(database_path)

    with closing(connect_database(database_path)) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)")
        }
        row = connection.execute(
            "SELECT case_id, status, progress, metrics_json FROM jobs WHERE id = ?",
            ("job-1",),
        ).fetchone()

    assert "metrics_json" in columns
    assert row == ("case-1", "processing", 42, None)


def test_additive_video_metadata_migration_preserves_legacy_cases(tmp_path):
    database_path = tmp_path / "legacy-cases.db"
    case_columns = (
        "    original_filename TEXT,\n"
        "    original_relative_path TEXT,\n"
        "    blurred_relative_path TEXT,\n"
        "    processing_completed_at TEXT,\n"
        "    duration_seconds REAL,\n"
        "    video_width INTEGER,\n"
        "    video_height INTEGER,\n"
    )
    legacy_schema = SCHEMA.replace(case_columns, "")
    assert legacy_schema != SCHEMA
    with closing(sqlite3.connect(database_path)) as connection:
        connection.executescript(legacy_schema)
        connection.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            ("development-upload-identity", "__development_uploads__", "disabled"),
        )
        connection.execute(
            "INSERT INTO cases (id, title, owner_id, folder_path) VALUES (?, ?, ?, ?)",
            (
                "case_legacy",
                "Unclaimed legacy case",
                "development-upload-identity",
                "storage/cases/case_legacy",
            ),
        )
        connection.execute(
            "INSERT INTO jobs (id, case_id, status, progress) VALUES (?, ?, ?, ?)",
            ("case_legacy", "case_legacy", "completed", 100),
        )
        connection.commit()

    initialize_database(database_path)

    with closing(connect_database(database_path)) as connection:
        case_columns_after = {
            row[1] for row in connection.execute("PRAGMA table_info(cases)")
        }
        case_row = connection.execute(
            "SELECT title, owner_id, folder_path, original_relative_path, blurred_relative_path "
            "FROM cases WHERE id = ?",
            ("case_legacy",),
        ).fetchone()

    assert {
        "original_filename",
        "original_relative_path",
        "blurred_relative_path",
        "processing_completed_at",
        "duration_seconds",
        "video_width",
        "video_height",
    } <= case_columns_after
    assert case_row == (
        "Unclaimed legacy case",
        "development-upload-identity",
        "storage/cases/case_legacy",
        None,
        None,
    )


def test_database_connections_enforce_foreign_keys(tmp_path):
    with TestClient(make_test_app(tmp_path)):
        pass

    with closing(connect_database(tmp_path / "app.db")) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO cases (id, title, owner_id, folder_path) VALUES (?, ?, ?, ?)",
                ("case-1", "Case", "missing-user", "not-exposed"),
            )


def test_openapi_exposes_contract_and_marks_stubs(tmp_path):
    with TestClient(make_test_app(tmp_path)) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert paths["/health"]["get"]["responses"]["200"]
    assert paths["/health/face-model"]["get"]["responses"]["200"]
    assert paths["/auth/register"]["post"]["responses"]["201"]
    assert paths["/auth/login"]["post"]["responses"]["200"]
    assert paths["/auth/me"]["get"]["responses"]["200"]
    assert paths["/cases"]["post"]["requestBody"]
    assert paths["/cases/{case_id}/restore/start"]["post"]["responses"]["501"]
    assert paths["/restore/stream/{token}"]["get"]["responses"]["501"]
    assert paths["/auth/logout"]["post"]["responses"]["200"]


def test_unimplemented_endpoint_returns_consistent_error(tmp_path):
    with TestClient(make_test_app(tmp_path)) as client:
        response = client.get("/cases")

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"

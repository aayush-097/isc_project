from contextlib import closing
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    public_key BLOB,
    encrypted_private_key BLOB,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    original_filename TEXT,
    original_relative_path TEXT,
    blurred_relative_path TEXT,
    processing_completed_at TEXT,
    duration_seconds REAL,
    video_width INTEGER,
    video_height INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    error TEXT,
    metrics_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cases_owner_id ON cases (owner_id);
CREATE INDEX IF NOT EXISTS idx_jobs_case_id ON jobs (case_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
"""


def connect_database(database_path: Path) -> sqlite3.Connection:
    """Open a configured connection with foreign-key checks enabled."""
    connection = sqlite3.connect(database_path, timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path) -> None:
    """Create missing tables and indexes without removing existing data."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(connect_database(database_path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        job_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)")
        }
        if "metrics_json" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN metrics_json TEXT")
        case_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(cases)")
        }
        case_migrations = {
            "original_filename": "TEXT",
            "original_relative_path": "TEXT",
            "blurred_relative_path": "TEXT",
            "processing_completed_at": "TEXT",
            "duration_seconds": "REAL",
            "video_width": "INTEGER",
            "video_height": "INTEGER",
        }
        for column, column_type in case_migrations.items():
            if column not in case_columns:
                connection.execute(f"ALTER TABLE cases ADD COLUMN {column} {column_type}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_owner_created ON cases (owner_id, created_at DESC)"
        )

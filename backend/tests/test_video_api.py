import tempfile
from contextlib import closing

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db.database import connect_database
from backend.app.main import create_app
from backend.app.services.video_jobs import get_video_record


class FakeDetector:
    gpu_acceleration_used = False

    def __init__(self, fail: bool = False, on_detect=None):
        self.fail = fail
        self.on_detect = on_detect

    def detect(self, frame):
        if self.on_detect is not None:
            self.on_detect()
        if self.fail:
            raise RuntimeError("test-only injected detector failure")
        return [(20, 12, 50, 42)]


def create_upload_video() -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = f"{directory}/sample.avi"
        writer = cv2.VideoWriter(
            path,
            cv2.VideoWriter_fourcc(*"MJPG"),
            10.0,
            (96, 64),
        )
        assert writer.isOpened(), "The installed OpenCV MJPG codec is required for tests."
        try:
            for index in range(3):
                frame = np.full((64, 96, 3), 80 + index * 30, dtype=np.uint8)
                writer.write(frame)
        finally:
            writer.release()
        with open(path, "rb") as generated:
            return generated.read()


@pytest.fixture
def api_environment(tmp_path):
    settings = Settings(
        database_path=tmp_path / "app.db",
        storage_path=tmp_path / "cases",
        face_blur_strength=31,
        face_box_padding=0,
        max_video_upload_bytes=1024 * 1024,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app, settings


def upload(client, *, filename="sample.avi", content=None, title="Test case"):
    return client.post(
        "/videos/upload",
        data={"title": title},
        files={
            "video": (
                filename,
                create_upload_video() if content is None else content,
                "application/octet-stream",
            )
        },
    )


def test_upload_runs_processing_and_exposes_only_blurred_video(api_environment):
    client, app, settings = api_environment
    processing_states = []

    def capture_processing_state():
        with closing(connect_database(settings.database_path)) as connection:
            processing_states.append(
                connection.execute(
                    "SELECT status, progress FROM jobs ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
            )

    app.state.video_detector_factory = lambda: FakeDetector(
        on_detect=capture_processing_state
    )

    response = upload(client, filename="../../face.avi", title="  Test case  ")

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["title"] == "Test case"
    assert accepted["status"] == "queued"
    case_id = accepted["case_id"]
    case_directory = settings.storage_path / case_id
    assert case_directory.is_dir()
    assert (case_directory / "original.avi").is_file()
    assert not (settings.storage_path / "face.avi").exists()

    status = client.get(f"/videos/{case_id}/status")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["metrics"]["processed_frames"] == 3
    assert body["metrics"]["output_frame_count"] == 3
    assert body["metrics"]["detected_face_instances"] == 3
    assert body["metrics"]["gpu_acceleration_used"] is False
    assert len(processing_states) == 3
    assert all(state[0] == "processing" for state in processing_states)
    assert [state[1] for state in processing_states] == sorted(
        state[1] for state in processing_states
    )
    assert "folder_path" not in body
    assert "original" not in body

    public = client.get(f"/videos/{case_id}/public")
    assert public.status_code == 200
    assert public.headers["content-type"].startswith("video/mp4")
    assert public.content.startswith(b"\x00\x00\x00")
    assert b"test-only" not in public.content

    partial = client.get(
        f"/videos/{case_id}/public",
        headers={"Range": "bytes=0-63"},
    )
    assert partial.status_code == 206
    assert len(partial.content) == 64
    assert partial.headers["content-range"].startswith("bytes 0-63/")

    library = client.get("/videos")
    assert library.status_code == 200
    assert len(library.json()["videos"]) == 1
    assert library.json()["videos"][0]["case_id"] == case_id


def test_missing_file_unsupported_extension_and_invalid_title(api_environment):
    client, _, _ = api_environment

    missing = client.post("/videos/upload", data={"title": "Missing file"})
    assert missing.status_code == 422

    unsupported = upload(client, filename="document.txt")
    assert unsupported.status_code == 415

    invalid_title = upload(client, title="   ")
    assert invalid_title.status_code == 422


def test_oversized_and_unreadable_uploads_are_rejected_and_cleaned(api_environment):
    client, _, settings = api_environment
    oversized = upload(client, content=b"x" * (settings.max_video_upload_bytes + 1))
    assert oversized.status_code == 413
    assert not list(settings.storage_path.iterdir())

    corrupt = upload(client, content=b"not a video")
    assert corrupt.status_code == 400
    assert not list(settings.storage_path.iterdir())


def test_processing_failure_is_reported_and_never_serves_output(api_environment):
    client, app, settings = api_environment
    app.state.video_detector_factory = lambda: FakeDetector(fail=True)

    response = upload(client)
    assert response.status_code == 202
    case_id = response.json()["case_id"]

    status = client.get(f"/videos/{case_id}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert status.json()["error"] == "Video processing failed. Check the backend log for details."
    assert status.json()["metrics"] is None
    assert not (settings.storage_path / case_id / "public.mp4").exists()
    assert client.get(f"/videos/{case_id}/public").status_code == 409


def test_missing_face_checkpoint_is_a_clear_failure(api_environment):
    client, app, settings = api_environment
    settings.face_model_path = settings.storage_path / "missing-face-model.pt"
    app.state.video_detector_factory = None

    response = upload(client)
    assert response.status_code == 202
    case_id = response.json()["case_id"]
    status = client.get(f"/videos/{case_id}/status").json()

    assert status["status"] == "failed"
    assert "Configure FACE_MODEL_PATH" in status["error"]
    assert "missing-face-model" not in status["error"]
    assert not (settings.storage_path / case_id / "public.mp4").exists()


def test_unknown_cases_and_path_traversal_are_rejected(api_environment):
    client, _, _ = api_environment

    assert client.get("/videos/case_unknown/status").status_code == 404
    assert client.get("/videos/../../outside/public").status_code in {404, 422}
    assert client.get("/videos/case_" + "a" * 32 + "/public").status_code == 404


def test_database_records_use_only_reserved_unusable_development_identity(api_environment):
    client, app, settings = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    response = upload(client)
    case_id = response.json()["case_id"]

    record = get_video_record(settings.database_path, case_id)
    assert record is not None
    assert record["case_status"] == "ready"
    assert record["job_status"] == "completed"

    with closing(connect_database(settings.database_path)) as connection:
        row = connection.execute(
            "SELECT username, password_hash FROM users WHERE id = ?",
            ("development-upload-identity",),
        ).fetchone()
    assert row == ("__development_uploads__", "!disabled-development-only!")


def test_range_request_rejects_unsatisfiable_range(api_environment):
    client, app, _ = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    response = upload(client)
    case_id = response.json()["case_id"]

    invalid_range = client.get(
        f"/videos/{case_id}/public",
        headers={"Range": "bytes=999999999-"},
    )
    assert invalid_range.status_code == 416
    assert invalid_range.headers["content-range"].startswith("bytes */")


def test_openapi_and_health_remain_available(api_environment):
    client, _, _ = api_environment
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/videos/upload" in schema["paths"]
    assert "/videos/{case_id}/status" in schema["paths"]
    assert "/videos/{case_id}/public" in schema["paths"]

import tempfile
from contextlib import closing

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db.database import connect_database
from backend.app.main import create_app
from backend.app.services.video_crypto import encrypt_video_file
from backend.app.services.video_jobs import create_video_record, get_video_record

TEST_PASSWORD = "correct horse battery staple"
VIDEO_PASSKEY = "unique-video-passkey-123"


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


def csrf_headers(client: TestClient) -> dict[str, str]:
    current_user = client.get("/auth/me")
    assert current_user.status_code == 200
    return {"X-CSRF-Token": current_user.json()["csrf_token"]}


def unlock(client: TestClient, case_id: str, passkey: str = VIDEO_PASSKEY):
    return client.post(
        f"/videos/{case_id}/unlock",
        headers=csrf_headers(client),
        json={"passkey": passkey},
    )


def grant_cookie(response) -> str:
    return response.cookies.get("video_unlock_grant", "")


def store_grant_cookie(client: TestClient, response) -> None:
    client.cookies.set("video_unlock_grant", grant_cookie(response), path="/")


def make_crypto_metadata(video_id: str, directory, source=b"test-original"):
    directory.mkdir(parents=True, exist_ok=True)
    source_path = directory / ".test-source"
    encrypted_path = directory / "encrypted" / "original.enc"
    source_path.write_bytes(source)
    _, metadata = encrypt_video_file(
        source_path,
        encrypted_path,
        video_id=video_id,
        passkey=VIDEO_PASSKEY,
    )
    source_path.unlink()
    return metadata


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
        app.state.test_owner = register(client, "video_owner")
        yield client, app, settings


def upload(
    client,
    *,
    filename="sample.avi",
    content=None,
    title="Test case",
    passkey=VIDEO_PASSKEY,
    confirm_passkey=None,
):
    original = create_upload_video() if content is None else content
    return client.post(
        "/videos/upload",
        headers=csrf_headers(client),
        data={
            "title": title,
            "passkey": passkey,
            "confirm_passkey": passkey if confirm_passkey is None else confirm_passkey,
        },
        files={
            "video": (
                filename,
                original,
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
    encrypted_original = case_directory / "encrypted" / "original.enc"
    assert encrypted_original.is_file()
    assert not (case_directory / "original.avi").exists()
    assert not (case_directory / ".upload.avi.tmp").exists()
    assert (case_directory / "processed" / "public.mp4").is_file()
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
    assert body["original_filename"] == "face.avi"
    assert body["video_width"] == 96
    assert body["video_height"] == 64
    assert body["duration_seconds"] == pytest.approx(0.3)
    assert body["processing_completed_at"]
    assert len(processing_states) == 3
    assert all(state[0] == "processing" for state in processing_states)
    assert [state[1] for state in processing_states] == sorted(
        state[1] for state in processing_states
    )
    assert "folder_path" not in body
    assert "original" not in body
    with closing(connect_database(settings.database_path)) as connection:
        key_metadata = connection.execute(
            "SELECT passkey_salt, wrapped_video_key, key_wrap_nonce, "
            "crypto_algorithm, original_relative_path FROM cases WHERE id = ?",
            (case_id,),
        ).fetchone()
    assert VIDEO_PASSKEY.encode() not in b"".join(
        value if isinstance(value, bytes) else b"" for value in key_metadata[:3]
    )
    assert key_metadata[3] == "AES-256-GCM-CHUNKED"
    assert key_metadata[4] == "encrypted/original.enc"

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
    unlocked = unlock(client, case_id)
    assert unlocked.status_code == 200
    store_grant_cookie(client, unlocked)
    original = client.get(f"/videos/{case_id}/original")
    assert original.status_code == 200
    assert original.content == create_upload_video()


def test_missing_file_unsupported_extension_and_invalid_title(api_environment):
    client, _, _ = api_environment

    missing = client.post("/videos/upload", data={"title": "Missing file"})
    assert missing.status_code == 422

    unsupported = upload(client, filename="document.txt")
    assert unsupported.status_code == 415

    mismatched_passkey = upload(
        client,
        confirm_passkey="another-video-passkey-456",
    )
    assert mismatched_passkey.status_code == 422

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
    assert not (settings.storage_path / case_id / "processed" / "public.mp4").exists()
    assert client.get(f"/videos/{case_id}/public").status_code == 409


def test_missing_face_checkpoint_is_reported_before_upload(api_environment):
    client, app, settings = api_environment
    settings.face_model_path = settings.storage_path / "missing-face-model.pt"
    app.state.video_detector_factory = None

    model_status = client.get("/health/face-model")
    assert model_status.status_code == 200
    assert model_status.json()["checkpoint_available"] is False
    assert model_status.json()["checkpoint_name"] == "missing-face-model.pt"
    assert model_status.json()["detection_class"] == "person"
    assert "FACE_DETECTION_CLASS" in model_status.json()["message"]

    response = upload(client)
    assert response.status_code == 503
    assert "FACE_DETECTION_CLASS" in response.json()["error"]["message"]
    assert len(list(settings.storage_path.iterdir())) == 0


def test_failed_case_can_be_retried_after_model_is_available(api_environment):
    client, app, settings = api_environment
    settings.face_model_path = settings.storage_path / "face-model.pt"
    app.state.video_detector_factory = lambda: FakeDetector(fail=True)
    upload_response = upload(client)
    case_id = upload_response.json()["case_id"]
    assert client.get(f"/videos/{case_id}/status").json()["status"] == "failed"

    app.state.video_detector_factory = None
    unavailable_retry = client.post(
        f"/videos/{case_id}/retry",
        headers=csrf_headers(client),
        json={"passkey": VIDEO_PASSKEY},
    )
    assert unavailable_retry.status_code == 503
    assert client.get(f"/videos/{case_id}/status").json()["status"] == "failed"

    settings.face_model_path.write_bytes(b"test checkpoint placeholder")
    app.state.video_detector_factory = lambda: FakeDetector()
    retry = client.post(
        f"/videos/{case_id}/retry",
        headers=csrf_headers(client),
        json={"passkey": VIDEO_PASSKEY},
    )

    assert retry.status_code == 202
    assert retry.json()["case_id"] == case_id
    assert retry.json()["status"] == "queued"
    assert client.get(f"/videos/{case_id}/status").json()["status"] == "completed"


def test_unknown_cases_and_path_traversal_are_rejected(api_environment):
    client, _, _ = api_environment

    assert client.get("/videos/case_unknown/status").status_code == 404
    assert client.get("/videos/../../outside/public").status_code in {404, 422}
    assert client.get("/videos/case_" + "a" * 32 + "/public").status_code == 404


def test_database_records_use_authenticated_owner_identity(api_environment):
    client, app, settings = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    response = upload(client)
    case_id = response.json()["case_id"]

    record = get_video_record(settings.database_path, case_id)
    assert record is not None
    assert record["case_status"] == "ready"
    assert record["job_status"] == "completed"
    assert record["owner_id"] == app.state.test_owner["id"]

    with closing(connect_database(settings.database_path)) as connection:
        rows = connection.execute("SELECT id, username FROM users").fetchall()
    assert rows == [(app.state.test_owner["id"], "video_owner")]


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


def test_any_logged_in_user_with_video_passkey_can_unlock_only_that_original(api_environment):
    owner_client, app, _ = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    upload_response = upload(owner_client)
    case_id = upload_response.json()["case_id"]
    second_response = upload(
        owner_client,
        title="Second case",
        passkey="another-video-passkey-456",
    )
    second_case_id = second_response.json()["case_id"]

    with TestClient(app) as viewer_client:
        register(viewer_client, "video_viewer")
        owner_unlock = unlock(owner_client, case_id)
        assert owner_unlock.status_code == 200
        store_grant_cookie(viewer_client, owner_unlock)
        assert viewer_client.get(f"/videos/{case_id}/original").status_code == 403
        details = viewer_client.get(f"/videos/{case_id}")
        assert details.status_code == 200
        assert details.json()["is_owner"] is False
        assert len(viewer_client.get("/videos").json()["videos"]) == 2
        assert viewer_client.get(f"/videos/{case_id}/original").status_code == 403
        assert viewer_client.get(
            f"/videos/{case_id}/original",
            headers={"Range": "bytes=0-5"},
        ).status_code == 403
        assert viewer_client.post(
            f"/videos/{case_id}/retry",
            headers=csrf_headers(viewer_client),
            json={"passkey": VIDEO_PASSKEY},
        ).status_code == 404
        assert viewer_client.delete(
            f"/videos/{case_id}",
            headers=csrf_headers(viewer_client),
        ).status_code == 404

        blurred = viewer_client.get(f"/videos/{case_id}/blurred")
        assert blurred.status_code == 200
        blurred_partial = viewer_client.get(
            f"/videos/{case_id}/public",
            headers={"Range": "bytes=0-31"},
        )
        assert blurred_partial.status_code == 206
        assert len(blurred_partial.content) == 32
        wrong_key = unlock(viewer_client, case_id, "incorrect-video-passkey-555")
        assert wrong_key.status_code == 401
        correct_key = unlock(viewer_client, case_id)
        assert correct_key.status_code == 200
        store_grant_cookie(viewer_client, correct_key)
        original_partial = viewer_client.get(
            f"/videos/{case_id}/original",
            headers={"Range": "bytes=0-31"},
        )
        assert original_partial.status_code == 206
        assert len(original_partial.content) == 32
        assert original_partial.headers["cache-control"] == "private, no-store"
        assert viewer_client.get(
            f"/videos/{second_case_id}/original",
        ).status_code == 403
        assert unlock(
            viewer_client,
            second_case_id,
            "incorrect-video-passkey-555",
        ).status_code == 401
        second_unlock = unlock(viewer_client, second_case_id, "another-video-passkey-456")
        assert second_unlock.status_code == 200
        store_grant_cookie(viewer_client, second_unlock)
        second_original = viewer_client.get(f"/videos/{second_case_id}/original")
        assert second_original.status_code == 200

        assert viewer_client.post(
            "/auth/logout",
            headers=csrf_headers(viewer_client),
        ).status_code == 200
        assert viewer_client.get(
            f"/videos/{second_case_id}/original",
        ).status_code == 401


def test_unauthenticated_private_video_requests_and_logout_revocation(api_environment):
    owner_client, app, _ = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    case_id = upload(owner_client).json()["case_id"]
    with TestClient(app) as anonymous:
        unauthenticated_upload = anonymous.post(
            "/videos/upload",
            data={
                "title": "Anonymous",
                "passkey": VIDEO_PASSKEY,
                "confirm_passkey": VIDEO_PASSKEY,
            },
            files={"video": ("sample.avi", b"video", "video/avi")},
        )
        assert unauthenticated_upload.status_code == 401
        assert anonymous.get("/videos").status_code == 401
        assert anonymous.get(f"/videos/{case_id}/status").status_code == 401
        assert anonymous.post(
            f"/videos/{case_id}/unlock",
            json={"passkey": VIDEO_PASSKEY},
        ).status_code == 401
        assert anonymous.get(f"/videos/{case_id}/original").status_code == 401
        assert anonymous.delete(f"/videos/{case_id}").status_code == 401
        assert anonymous.get(f"/videos/{case_id}/public").status_code == 401

        missing_unlock_csrf = owner_client.post(
            f"/videos/{case_id}/unlock",
            json={"passkey": VIDEO_PASSKEY},
            headers={"X-CSRF-Token": "invalid"},
        )
        assert missing_unlock_csrf.status_code == 403

    missing_csrf = owner_client.post(
        "/videos/upload",
        data={
            "title": "Missing CSRF",
            "passkey": VIDEO_PASSKEY,
            "confirm_passkey": VIDEO_PASSKEY,
        },
        files={"video": ("sample.avi", b"video", "video/avi")},
        headers={"X-CSRF-Token": "invalid"},
    )
    assert missing_csrf.status_code == 403

    token = csrf_headers(owner_client)
    assert owner_client.post("/auth/logout", headers=token).status_code == 200
    assert owner_client.get(f"/videos/{case_id}/original").status_code == 401
    assert owner_client.get(f"/videos/{case_id}/status").status_code == 401
    assert owner_client.get(f"/videos/{case_id}/public").status_code == 401


def test_original_is_not_served_during_processing_and_blurred_has_no_source_fallback(api_environment):
    client, _, settings = api_environment
    owner_id = client.get("/auth/me").json()["id"]
    case_id = "case_" + "b" * 32
    case_directory = settings.storage_path / case_id
    crypto_metadata = make_crypto_metadata(case_id, case_directory)
    create_video_record(
        settings.database_path,
        case_id=case_id,
        title="Pending source",
        owner_id=owner_id,
        folder_path=case_directory,
        original_filename="private.avi",
        original_relative_path="encrypted/original.enc",
        crypto_metadata=crypto_metadata,
    )

    assert client.get(f"/videos/{case_id}/original").status_code == 409
    assert client.get(f"/videos/{case_id}/public").status_code == 409
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'failed' WHERE case_id = ?",
            (case_id,),
        )
        connection.execute(
            "UPDATE cases SET status = 'failed' WHERE id = ?",
            (case_id,),
        )
        connection.commit()
    (case_directory / "processed").mkdir(exist_ok=True)
    (case_directory / "processed" / "public.mp4").write_bytes(b"private-source")

    unavailable = client.get(f"/videos/{case_id}/public")
    assert unavailable.status_code == 409
    assert unavailable.content != b"private-source"
    unlocked = unlock(client, case_id)
    assert unlocked.status_code == 200
    store_grant_cookie(client, unlocked)
    original = client.get(f"/videos/{case_id}/original")
    assert original.status_code == 200
    assert original.content == b"test-original"


def test_passkey_rate_limit_and_expired_grant(api_environment):
    client, app, settings = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    case_id = upload(client).json()["case_id"]

    for _ in range(5):
        response = unlock(client, case_id, "incorrect-video-passkey-555")
        assert response.status_code == 401
    locked = unlock(client, case_id)
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "900"

    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "DELETE FROM video_passkey_attempts WHERE video_id = ?",
            (case_id,),
        )
        connection.commit()
    unlocked = unlock(client, case_id)
    assert unlocked.status_code == 200
    store_grant_cookie(client, unlocked)
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "UPDATE video_unlock_grants SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE video_id = ?",
            (case_id,),
        )
        connection.commit()
    assert client.get(f"/videos/{case_id}/original").status_code == 403


def test_missing_original_is_not_replaced_by_blurred_or_source_file(api_environment):
    client, app, _ = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    case_id = upload(client).json()["case_id"]
    response = unlock(client, case_id)
    assert response.status_code == 200
    store_grant_cookie(client, response)
    original = client.get(f"/videos/{case_id}/original")
    assert original.status_code == 200
    (app.state.settings.storage_path / case_id / "encrypted" / "original.enc").unlink()

    missing = client.get(f"/videos/{case_id}/original")
    assert missing.status_code == 404
    blurred = client.get(f"/videos/{case_id}/public")
    assert blurred.status_code == 200
    assert blurred.content != original.content


def test_legacy_case_owner_is_not_guessed_and_only_validated_blur_is_public(api_environment):
    client, _, settings = api_environment
    case_id = "case_" + "d" * 32
    case_directory = settings.storage_path / case_id
    case_directory.mkdir()
    (case_directory / "original.avi").write_bytes(b"legacy-original")
    (case_directory / "public.mp4").write_bytes(b"legacy-blurred")
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            ("development-upload-identity", "__development_uploads__", "disabled"),
        )
        connection.execute(
            """
            INSERT INTO cases (id, title, owner_id, folder_path, status)
            VALUES (?, ?, ?, ?, 'ready')
            """,
            (
                case_id,
                "Unclaimed legacy video",
                "development-upload-identity",
                str(case_directory),
            ),
        )
        connection.execute(
            """
            INSERT INTO jobs (id, case_id, status, progress, metrics_json)
            VALUES (?, ?, 'completed', 100, ?)
            """,
            (
                case_id,
                case_id,
                """{
                    "input_width": 96,
                    "input_height": 64,
                    "input_fps": 10.0,
                    "input_frame_count": 3,
                    "processed_frames": 3,
                    "detected_face_instances": 0,
                    "frames_with_detections": 0,
                    "elapsed_seconds": 0.1,
                    "processing_fps": 30.0,
                    "output_frame_count": 3,
                    "output_validation_status": "passed",
                    "gpu_acceleration_used": false,
                    "output_fps": 10.0
                }""",
            ),
        )
        connection.commit()

    listed_legacy = next(
        video
        for video in client.get("/videos").json()["videos"]
        if video["case_id"] == case_id
    )
    assert listed_legacy["is_owner"] is False
    assert client.get(f"/videos/{case_id}/status").status_code == 200
    assert client.get(f"/videos/{case_id}/original").status_code == 403
    assert client.get(f"/videos/{case_id}/public").content == b"legacy-blurred"


def test_owner_can_delete_case_and_cannot_delete_while_processing(api_environment):
    client, app, settings = api_environment
    app.state.video_detector_factory = lambda: FakeDetector()
    case_id = upload(client).json()["case_id"]

    pending_id = "case_" + "c" * 32
    pending_directory = settings.storage_path / pending_id
    pending_crypto_metadata = make_crypto_metadata(pending_id, pending_directory)
    create_video_record(
        settings.database_path,
        case_id=pending_id,
        title="Pending case",
        owner_id=client.get("/auth/me").json()["id"],
        folder_path=pending_directory,
        original_filename="pending.avi",
        original_relative_path="encrypted/original.enc",
        crypto_metadata=pending_crypto_metadata,
    )
    assert client.delete(
        f"/videos/{pending_id}",
        headers=csrf_headers(client),
    ).status_code == 409

    deleted = client.delete(
        f"/videos/{case_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204
    assert not (settings.storage_path / case_id).exists()
    assert client.get(f"/videos/{case_id}/status").status_code == 404
    assert client.get(f"/videos/{case_id}/public").status_code == 404


def test_openapi_and_health_remain_available(api_environment):
    client, _, _ = api_environment
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/videos/upload" in schema["paths"]
    assert "/videos/{case_id}/status" in schema["paths"]
    assert "/videos/{case_id}/public" in schema["paths"]
    assert "/videos/{case_id}/original" in schema["paths"]
    assert "/videos/{case_id}" in schema["paths"]

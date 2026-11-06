import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.app.ai.face_detector import FaceDetectionError
from backend.app.config import Settings
from backend.app.services.video_processing import process_case_video
from backend.app.video.processor import VideoProcessingError, process_video


class FakeDetector:
    gpu_acceleration_used = False

    def __init__(self, boxes_by_frame=None, fail_at=None):
        self.boxes_by_frame = boxes_by_frame or {}
        self.fail_at = fail_at
        self.calls = 0
        self.frame_shapes = []

    def detect(self, frame):
        self.calls += 1
        self.frame_shapes.append(frame.shape)
        if self.calls == self.fail_at:
            raise FaceDetectionError("injected detector failure")
        return self.boxes_by_frame.get(self.calls, [])


def make_test_settings(tmp_path, **overrides):
    return Settings(
        database_path=tmp_path / "db.sqlite",
        storage_path=tmp_path / "cases",
        face_blur_strength=31,
        face_box_padding=0,
        **overrides,
    )


def create_video(path, frames, fps=10.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (96, 64),
    )
    assert writer.isOpened(), "The installed OpenCV MJPG codec is required for tests."
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def make_frames():
    frames = []
    for index, color in enumerate(((40, 80, 120), (60, 100, 140), (80, 120, 160))):
        frame = np.full((64, 96, 3), color, dtype=np.uint8)
        if index == 1:
            pattern = (np.indices((34, 34)).sum(axis=0) % 2 * 255).astype(np.uint8)
            frame[15:49, 31:65] = pattern[:, :, None]
        frames.append(frame)
    return frames


def read_all(path):
    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
        frames = []
        while True:
            success, frame = capture.read()
            if not success:
                break
            frames.append(frame)
        return frames
    finally:
        capture.release()


def probe_streams(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["streams"]


def create_video_with_audio(tmp_path, audio_duration):
    silent = tmp_path / "silent.avi"
    source = tmp_path / "with-audio.mkv"
    create_video(silent, make_frames() * 4)
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(silent),
            "-f", "lavfi", "-i",
            f"sine=frequency=440:sample_rate=48000:duration={audio_duration}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "pcm_s16le", str(source),
        ],
        check=True,
        capture_output=True,
    )
    return source


def assert_faststart(path):
    data = path.read_bytes()
    atom_types = []
    offset = 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        atom_types.append(data[offset + 4:offset + 8])
        if size == 0:
            break
        assert size >= 8
        offset += size
    assert atom_types.index(b"moov") < atom_types.index(b"mdat")


@pytest.mark.parametrize("suffix", [".mp4", ".m4v", ".mov", ".avi"])
@pytest.mark.parametrize("audio_duration", [0.4, 1.8])
def test_preserves_audio_and_all_blurred_video_frames(tmp_path, suffix, audio_duration):
    source = create_video_with_audio(tmp_path, audio_duration)
    destination = tmp_path / f"public{suffix}"
    stats = process_video(
        source,
        destination,
        FakeDetector({2: [(31, 15, 65, 49)]}),
        settings=make_test_settings(tmp_path),
    )

    streams = probe_streams(destination)
    video_streams = [stream for stream in streams if stream["codec_type"] == "video"]
    audio_streams = [stream for stream in streams if stream["codec_type"] == "audio"]
    assert len(video_streams) == len(audio_streams) == 1
    if suffix == ".avi":
        assert video_streams[0]["codec_name"] == "mjpeg"
        assert audio_streams[0]["codec_name"] == "pcm_s16le"
    else:
        assert video_streams[0]["codec_name"] == "h264"
        assert video_streams[0]["pix_fmt"] == "yuv420p"
        assert audio_streams[0]["codec_name"] == "aac"
        assert_faststart(destination)
    frames = read_all(destination)
    assert len(frames) == stats.processed_frames == stats.output_frame_count == 12
    assert stats.output_validation_status == "passed"
    assert frames[1][20:44, 36:60].std() < 30
    assert frames[0].mean() < frames[1].mean() < frames[2].mean()

    decoded = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(destination), "-map", "0:a:0",
            "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    samples = np.frombuffer(decoded.stdout, dtype="<f4")
    assert abs(len(samples) / 48000 - audio_duration) < 0.1
    assert np.sqrt(np.mean(samples ** 2)) > 0.02
    frequencies = np.fft.rfftfreq(len(samples), 1 / 48000)
    dominant_frequency = frequencies[np.argmax(abs(np.fft.rfft(samples)))]
    assert dominant_frequency == pytest.approx(440, abs=10)
    assert list(tmp_path.glob(".public.*")) == []


@pytest.mark.parametrize("suffix", [".mp4", ".m4v", ".mov", ".avi"])
def test_silent_input_encodes_without_fabricated_audio(tmp_path, suffix):
    source = tmp_path / "silent.avi"
    destination = tmp_path / f"public{suffix}"
    create_video(source, make_frames())

    stats = process_video(
        source, destination, FakeDetector(), settings=make_test_settings(tmp_path)
    )

    streams = probe_streams(destination)
    assert len(streams) == 1
    assert streams[0]["codec_type"] == "video"
    assert streams[0]["codec_name"] == ("mjpeg" if suffix == ".avi" else "h264")
    if suffix != ".avi":
        assert streams[0]["pix_fmt"] == "yuv420p"
        assert_faststart(destination)
    assert len(read_all(destination)) == stats.output_frame_count == 3
    assert list(tmp_path.glob(".public.*")) == []


@pytest.mark.parametrize("missing_binary", [False, True])
@pytest.mark.parametrize("existing_output", [False, True])
def test_final_encoding_failure_never_publishes_or_leaves_temporary_files(
    tmp_path, monkeypatch, missing_binary, existing_output
):
    source = tmp_path / "source.avi"
    destination = tmp_path / "published.mp4"
    create_video(source, make_frames())
    if existing_output:
        destination.write_bytes(b"previous published output")

    def fail_encoding(command, **kwargs):
        if missing_binary:
            raise FileNotFoundError("ffmpeg")
        Path(command[-1]).write_bytes(b"partial encoded output")
        raise subprocess.CalledProcessError(
            1, command, stderr="injected encoder failure"
        )

    monkeypatch.setattr("backend.app.video.processor.subprocess.run", fail_encoding)
    message = "FFmpeg is required" if missing_binary else "injected encoder failure"
    with pytest.raises(VideoProcessingError, match=message):
        process_video(
            source, destination, FakeDetector(), settings=make_test_settings(tmp_path)
        )

    if existing_output:
        assert destination.read_bytes() == b"previous published output"
    else:
        assert not destination.exists()
    assert list(tmp_path.glob(".published.*")) == []


def test_processes_video_blurs_faces_and_verifies_output(tmp_path):
    input_video = tmp_path / "input.avi"
    output_video = tmp_path / "output" / "public.avi"
    create_video(input_video, make_frames())
    detector = FakeDetector({2: [(31, 15, 65, 49)]})

    stats = process_video(
        input_video,
        output_video,
        detector,
        settings=make_test_settings(tmp_path),
    )

    output_frames = read_all(output_video)
    assert len(output_frames) == 3
    assert output_frames[0].shape == (64, 96, 3)
    assert stats.input_width == 96
    assert stats.input_height == 64
    assert stats.input_frame_count == stats.processed_frames == stats.output_frame_count == 3
    assert stats.detected_face_instances == 1
    assert stats.frames_with_detections == 1
    assert stats.output_validation_status == "passed"
    assert stats.gpu_acceleration_used is False
    assert stats.processing_fps > 0
    assert output_frames[1][20:44, 36:60].std() < 30
    frame_means = [frame.mean() for frame in output_frames]
    assert frame_means[0] < frame_means[1] < frame_means[2]


def test_no_detections_are_reported_without_claiming_safety(tmp_path):
    source = tmp_path / "no-faces.avi"
    destination = tmp_path / "no-faces-output.avi"
    frames = [np.full((64, 96, 3), (30, 90, 150), dtype=np.uint8) for _ in range(2)]
    create_video(source, frames)

    stats = process_video(
        source,
        destination,
        FakeDetector(),
        settings=make_test_settings(tmp_path),
    )

    assert stats.detected_face_instances == 0
    assert stats.frames_with_detections == 0
    assert len(read_all(destination)) == 2


def test_missing_input_metadata_uses_documented_fps_fallback(tmp_path, monkeypatch):
    source = tmp_path / "missing-metadata.avi"
    destination = tmp_path / "fallback-output.avi"
    create_video(source, make_frames()[:2])
    real_capture = cv2.VideoCapture

    class MissingMetadataCapture:
        def __init__(self, path, *args, **kwargs):
            self.path = str(path)
            self.wrapped = real_capture(path, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def get(self, prop):
            if self.path == str(source) and prop in {
                cv2.CAP_PROP_FPS,
                cv2.CAP_PROP_FRAME_COUNT,
            }:
                return 0
            return self.wrapped.get(prop)

        def release(self):
            self.wrapped.release()

    monkeypatch.setattr(
        "backend.app.video.processor.cv2.VideoCapture", MissingMetadataCapture
    )
    stats = process_video(
        source,
        destination,
        FakeDetector(),
        settings=make_test_settings(tmp_path),
    )

    assert stats.input_fps is None
    assert stats.input_frame_count is None
    assert stats.output_fps == 25.0
    assert stats.output_frame_count == 2


@pytest.mark.parametrize("reported_count", [1, 5])
def test_inaccurate_input_frame_metadata_preserves_all_decoded_frames(
    tmp_path, monkeypatch, reported_count
):
    source = tmp_path / "estimated-count.avi"
    destination = tmp_path / "estimated-count-output.avi"
    create_video(source, make_frames())
    real_capture = cv2.VideoCapture

    class EstimatedCountCapture:
        def __init__(self, path, *args, **kwargs):
            self.is_source = str(path) == str(source)
            self.wrapped = real_capture(path, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def get(self, prop):
            if self.is_source and prop == cv2.CAP_PROP_FRAME_COUNT:
                return reported_count
            return self.wrapped.get(prop)

    monkeypatch.setattr(
        "backend.app.video.processor.cv2.VideoCapture", EstimatedCountCapture
    )
    detector = FakeDetector({2: [(31, 15, 65, 49)]})
    stats = process_video(
        source, destination, detector, settings=make_test_settings(tmp_path)
    )

    output_frames = read_all(destination)
    assert stats.input_frame_count == reported_count
    assert stats.processed_frames == stats.output_frame_count == len(output_frames) == 3
    assert detector.calls == 3
    assert output_frames[1][20:44, 36:60].std() < 30
    frame_means = [frame.mean() for frame in output_frames]
    assert frame_means[0] < frame_means[1] < frame_means[2]


def test_dropped_output_frame_is_rejected_without_replacing_published_video(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.avi"
    destination = tmp_path / "published.avi"
    create_video(source, make_frames())
    destination.write_bytes(b"previous published output")
    real_writer = cv2.VideoWriter

    class DroppingWriter:
        def __init__(self, *args, **kwargs):
            self.wrapped = real_writer(*args, **kwargs)
            self.frames = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def write(self, frame):
            self.frames += 1
            if self.frames != 3:
                self.wrapped.write(frame)

    monkeypatch.setattr("backend.app.video.processor.cv2.VideoWriter", DroppingWriter)
    with pytest.raises(
        VideoProcessingError,
        match=r"Output frame count validation failed \(expected 3, got 2\)",
    ):
        process_video(
            source, destination, FakeDetector(), settings=make_test_settings(tmp_path)
        )

    assert destination.read_bytes() == b"previous published output"
    assert list(tmp_path.glob(".published.*.avi")) == []


def test_invalid_boxes_do_not_fail_processing(tmp_path):
    source = tmp_path / "invalid-boxes.avi"
    destination = tmp_path / "invalid-boxes-output.avi"
    create_video(source, [np.full((64, 96, 3), 100, dtype=np.uint8)])
    detector = FakeDetector(
        {1: [(10, 10, 5, 20), (float("nan"), 1, 5, 8), (1, 1, 1, 1)]}
    )

    stats = process_video(
        source,
        destination,
        detector,
        settings=make_test_settings(tmp_path),
    )

    assert stats.detected_face_instances == 0
    assert stats.processed_frames == 1


def test_detector_failure_does_not_publish_partial_output_and_releases_capture(
    tmp_path, monkeypatch
):
    source = tmp_path / "failure.avi"
    destination = tmp_path / "published.avi"
    create_video(source, make_frames())

    real_capture = cv2.VideoCapture
    real_writer = cv2.VideoWriter
    captures = []
    writers = []

    class TrackedCapture:
        def __init__(self, *args, **kwargs):
            self.wrapped = real_capture(*args, **kwargs)
            self.released = False
            captures.append(self)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def release(self):
            self.released = True
            self.wrapped.release()

    class TrackedWriter:
        def __init__(self, *args, **kwargs):
            self.wrapped = real_writer(*args, **kwargs)
            self.released = False
            writers.append(self)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def release(self):
            self.released = True
            self.wrapped.release()

    monkeypatch.setattr("backend.app.video.processor.cv2.VideoCapture", TrackedCapture)
    monkeypatch.setattr("backend.app.video.processor.cv2.VideoWriter", TrackedWriter)
    with pytest.raises(VideoProcessingError, match="Face detection failed on input frame 2"):
        process_video(
            source,
            destination,
            FakeDetector(fail_at=2),
            settings=make_test_settings(tmp_path),
        )

    assert not destination.exists()
    assert captures and all(capture.released for capture in captures)
    assert writers and all(writer.released for writer in writers)
    assert list(tmp_path.glob(".published.*.avi")) == []


def test_successful_processing_releases_capture_and_writer(tmp_path, monkeypatch):
    source = tmp_path / "success.avi"
    destination = tmp_path / "success-output.avi"
    create_video(source, make_frames())

    real_capture = cv2.VideoCapture
    real_writer = cv2.VideoWriter
    captures = []
    writers = []

    class TrackedCapture:
        def __init__(self, *args, **kwargs):
            self.wrapped = real_capture(*args, **kwargs)
            self.released = False
            captures.append(self)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def release(self):
            self.released = True
            self.wrapped.release()

    class TrackedWriter:
        def __init__(self, *args, **kwargs):
            self.wrapped = real_writer(*args, **kwargs)
            self.released = False
            writers.append(self)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def release(self):
            self.released = True
            self.wrapped.release()

    monkeypatch.setattr("backend.app.video.processor.cv2.VideoCapture", TrackedCapture)
    monkeypatch.setattr("backend.app.video.processor.cv2.VideoWriter", TrackedWriter)
    stats = process_video(
        source,
        destination,
        FakeDetector(),
        settings=make_test_settings(tmp_path),
    )

    assert stats.output_validation_status == "passed"
    assert captures and all(capture.released for capture in captures)
    assert writers and all(writer.released for writer in writers)


def test_unreadable_or_empty_video_fails_clearly(tmp_path):
    missing = tmp_path / "missing.avi"
    with pytest.raises(VideoProcessingError, match="missing or empty"):
        process_video(missing, tmp_path / "out.avi", FakeDetector())

    empty = tmp_path / "empty.avi"
    empty.touch()
    with pytest.raises(VideoProcessingError, match="missing or empty"):
        process_video(empty, tmp_path / "out.avi", FakeDetector())

    unreadable = tmp_path / "unreadable.avi"
    unreadable.write_bytes(b"not a video")
    with pytest.raises(VideoProcessingError, match="not a readable video|no readable video frames"):
        process_video(unreadable, tmp_path / "out.avi", FakeDetector())


def test_case_service_keeps_output_under_storage_and_rejects_path_traversal(tmp_path):
    source = tmp_path / "source.avi"
    create_video(source, [np.full((64, 96, 3), 90, dtype=np.uint8)])
    settings = make_test_settings(tmp_path)

    stats = process_case_video(source, "case_123", FakeDetector(), settings=settings)

    assert stats.output_validation_status == "passed"
    assert (settings.storage_path / "case_123" / "processed" / "public.mp4").is_file()
    with pytest.raises(ValueError, match="case_id"):
        process_case_video(source, "../outside", FakeDetector(), settings=settings)


def test_input_path_cannot_be_overwritten(tmp_path):
    source = tmp_path / "same.avi"
    create_video(source, make_frames())

    with pytest.raises(VideoProcessingError, match="must be different"):
        process_video(source, source, FakeDetector())


def test_real_model_mode_fails_clearly_when_checkpoint_is_missing(tmp_path):
    source = tmp_path / "no-checkpoint.avi"
    create_video(source, [np.full((64, 96, 3), 90, dtype=np.uint8)])
    settings = make_test_settings(
        tmp_path,
        face_model_path=tmp_path / "missing-face-model.pt",
    )

    with pytest.raises(VideoProcessingError, match="FACE_MODEL_PATH|checkpoint"):
        process_video(source, tmp_path / "no-model-output.avi", settings=settings)

    assert not (tmp_path / "no-model-output.avi").exists()

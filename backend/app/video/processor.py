from __future__ import annotations

import math
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2

from backend.app.ai.face_detector import Detector, FaceDetectionError
from backend.app.config import Settings, get_settings
from backend.app.video.blur import blur_face_regions


class VideoProcessingError(RuntimeError):
    """Raised when a video cannot be processed or its output cannot be verified."""


@dataclass(frozen=True)
class ProcessingStats:
    input_width: int
    input_height: int
    input_fps: float | None
    input_frame_count: int | None
    processed_frames: int
    detected_face_instances: int
    frames_with_detections: int
    elapsed_seconds: float
    processing_fps: float
    output_frame_count: int
    output_validation_status: str
    gpu_acceleration_used: bool
    output_fps: float

    def to_dict(self) -> dict[str, int | float | str | bool | None]:
        return asdict(self)


ProgressCallback = Callable[[int, int | None], None]
SUPPORTED_OUTPUT_SUFFIXES = {".mp4", ".m4v", ".mov", ".avi"}
DEFAULT_OUTPUT_FPS = 25.0


def _metadata_number(value: float) -> float | None:
    return value if math.isfinite(value) and value > 0 else None


def _writer_fourcc(path: Path) -> int:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_OUTPUT_SUFFIXES:
        raise VideoProcessingError(
            f"Unsupported output video extension '{path.suffix}'. "
            f"Use one of: {', '.join(sorted(SUPPORTED_OUTPUT_SUFFIXES))}."
        )
    return cv2.VideoWriter_fourcc(*("MJPG" if suffix == ".avi" else "mp4v"))


def _verify_output(
    path: Path,
    *,
    width: int,
    height: int,
    expected_frames: int,
    expected_fps: float,
) -> int:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise VideoProcessingError("Processed output cannot be reopened.")

        output_fps = _metadata_number(capture.get(cv2.CAP_PROP_FPS))
        if output_fps is None or abs(output_fps - expected_fps) > max(0.1, expected_fps * 0.02):
            raise VideoProcessingError(
                f"Output frame rate validation failed (expected {expected_fps:g}, "
                f"got {output_fps})."
            )

        output_frames = 0
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame is None or frame.shape[:2] != (height, width):
                raise VideoProcessingError(
                    f"Output frame {output_frames + 1} has unexpected dimensions."
                )
            output_frames += 1
        if output_frames != expected_frames:
            raise VideoProcessingError(
                f"Output frame count validation failed (expected {expected_frames}, "
                f"got {output_frames})."
            )
        return output_frames
    finally:
        capture.release()


def process_video(
    input_path: Path,
    output_path: Path,
    detector: Detector | None = None,
    *,
    settings: Settings | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProcessingStats:
    """Process a video sequentially and publish only a verified blurred output."""
    app_settings = settings or get_settings()
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if source == destination:
        raise VideoProcessingError("Input and output paths must be different.")
    if not source.is_file() or source.stat().st_size == 0:
        raise VideoProcessingError(f"Input video is missing or empty: {source}")

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VideoProcessingError(
            f"Could not create output directory {destination.parent}: {exc}"
        ) from exc
    if destination.suffix.lower() not in SUPPORTED_OUTPUT_SUFFIXES:
        _writer_fourcc(destination)

    if detector is None:
        from backend.app.ai.face_detector import YoloFaceDetector

        try:
            detector = YoloFaceDetector(
                app_settings.face_model_path,
                confidence=app_settings.face_confidence_threshold,
                image_size=app_settings.face_image_size,
                device=app_settings.face_device,
            )
        except FaceDetectionError as exc:
            raise VideoProcessingError(str(exc)) from exc

    capture = cv2.VideoCapture(str(source))
    writer: cv2.VideoWriter | None = None
    temporary_path: Path | None = None
    started_at = time.perf_counter()
    try:
        if not capture.isOpened():
            raise VideoProcessingError(f"Input is not a readable video: {source}")
        success, frame = capture.read()
        if not success or frame is None or frame.size == 0:
            raise VideoProcessingError(f"Input contains no readable video frames: {source}")
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise VideoProcessingError("Input video frames must be three-channel BGR images.")

        height, width = frame.shape[:2]
        metadata_fps = _metadata_number(capture.get(cv2.CAP_PROP_FPS))
        output_fps = metadata_fps or DEFAULT_OUTPUT_FPS
        metadata_count = _metadata_number(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        input_frame_count = int(round(metadata_count)) if metadata_count else None

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.", suffix=destination.suffix, dir=destination.parent
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        temporary_path.unlink()
        writer = cv2.VideoWriter(
            str(temporary_path),
            _writer_fourcc(destination),
            output_fps,
            (width, height),
        )
        if not writer.isOpened():
            raise VideoProcessingError(
                f"Could not initialize an output writer for {destination.suffix}."
            )

        processed_frames = 0
        detected_faces = 0
        frames_with_detections = 0
        while success and frame is not None:
            if frame.shape[:2] != (height, width):
                raise VideoProcessingError(
                    f"Input frame {processed_frames + 1} dimensions changed during processing."
                )
            try:
                boxes = detector.detect(frame)
            except Exception as exc:
                raise VideoProcessingError(
                    f"Face detection failed on input frame {processed_frames + 1}: {exc}"
                ) from exc
            if boxes is None:
                raise VideoProcessingError(
                    f"Detector returned no result on input frame {processed_frames + 1}."
                )
            blurred_frame, frame_face_count = blur_face_regions(
                frame,
                boxes,
                padding=app_settings.face_box_padding,
                strength=app_settings.face_blur_strength,
            )
            writer.write(blurred_frame)
            processed_frames += 1
            detected_faces += frame_face_count
            if frame_face_count:
                frames_with_detections += 1
            if progress_callback is not None:
                progress_callback(processed_frames, input_frame_count)
            success, frame = capture.read()

        if processed_frames == 0:
            raise VideoProcessingError("No input frames were processed.")
        if input_frame_count is not None and processed_frames != input_frame_count:
            raise VideoProcessingError(
                f"Input frame count did not match metadata (expected "
                f"{input_frame_count}, processed {processed_frames})."
            )
        writer.release()
        writer = None
        capture.release()

        if temporary_path is None or not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise VideoProcessingError("Video writer did not produce an output file.")
        output_frame_count = _verify_output(
            temporary_path,
            width=width,
            height=height,
            expected_frames=processed_frames,
            expected_fps=output_fps,
        )
        os.replace(temporary_path, destination)
        temporary_path = None

        elapsed = time.perf_counter() - started_at
        processing_fps = processed_frames / elapsed if elapsed > 0 else 0.0
        return ProcessingStats(
            input_width=width,
            input_height=height,
            input_fps=metadata_fps,
            input_frame_count=input_frame_count,
            processed_frames=processed_frames,
            detected_face_instances=detected_faces,
            frames_with_detections=frames_with_detections,
            elapsed_seconds=elapsed,
            processing_fps=processing_fps,
            output_frame_count=output_frame_count,
            output_validation_status="passed",
            gpu_acceleration_used=bool(getattr(detector, "gpu_acceleration_used", False)),
            output_fps=output_fps,
        )
    except VideoProcessingError:
        raise
    except Exception as exc:
        raise VideoProcessingError(f"Video processing failed: {exc}") from exc
    finally:
        if writer is not None:
            writer.release()
        capture.release()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

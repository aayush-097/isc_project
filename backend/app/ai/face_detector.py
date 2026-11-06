from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, TypeAlias

import numpy as np
from numpy.typing import NDArray


Frame: TypeAlias = NDArray[np.uint8]
BoundingBox: TypeAlias = tuple[float, float, float, float]
IntegerBoundingBox: TypeAlias = tuple[int, int, int, int]


class FaceDetectionError(RuntimeError):
    """Raised when a configured face detector cannot be used."""


FACE_MODEL_SETUP_MESSAGE = (
    "Detector checkpoint is missing or empty. Set FACE_MODEL_PATH to a local "
    "YOLO checkpoint that contains the configured FACE_DETECTION_CLASS."
)


class Detector(Protocol):
    @property
    def gpu_acceleration_used(self) -> bool: ...

    def detect(self, frame: Frame) -> Sequence[Sequence[float]]: ...


def validate_frame(frame: Frame) -> None:
    if (
        not isinstance(frame, np.ndarray)
        or frame.dtype != np.uint8
        or frame.ndim != 3
        or frame.shape[2] != 3
        or frame.shape[0] == 0
        or frame.shape[1] == 0
    ):
        raise ValueError("frame must be a non-empty uint8 BGR image with 3 channels")


def checkpoint_is_available(checkpoint_path: Path) -> bool:
    checkpoint = Path(checkpoint_path).expanduser()
    return checkpoint.is_file() and checkpoint.stat().st_size > 0


class YoloFaceDetector:
    """Reusable Ultralytics detector that accepts face-specific checkpoints only."""

    def __init__(
        self,
        checkpoint_path: Path,
        *,
        confidence: float = 0.25,
        image_size: int = 960,
        device: str = "auto",
        target_class: str = "face",
        model_loader: Callable[[Path], object] | None = None,
    ) -> None:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if image_size < 32:
            raise ValueError("image_size must be at least 32 pixels")
        normalized_target = target_class.strip().lower()
        if normalized_target not in {"face", "person"}:
            raise ValueError("target_class must be face or person")

        checkpoint = Path(checkpoint_path).expanduser()
        if not checkpoint_is_available(checkpoint):
            raise FaceDetectionError(
                f"{FACE_MODEL_SETUP_MESSAGE} No weights are downloaded automatically."
            )

        self.checkpoint_path = checkpoint.resolve()
        self.confidence = confidence
        self.image_size = image_size
        self.device, self.gpu_acceleration_used = self._resolve_device(device)

        try:
            if model_loader is None:
                from ultralytics import YOLO

                self._model = YOLO(str(self.checkpoint_path))
            else:
                self._model = model_loader(self.checkpoint_path)
        except Exception as exc:
            raise FaceDetectionError(
                f"Could not load the configured face model checkpoint: {exc}"
            ) from exc

        names = getattr(self._model, "names", None)
        if isinstance(names, dict):
            name_items = list(names.items())
        elif isinstance(names, (list, tuple)):
            name_items = list(enumerate(names))
        else:
            name_items = []

        target_indices = {
            int(index)
            for index, name in name_items
            if str(name).strip().lower()
            in ({"face", "faces"} if normalized_target == "face" else {"person", "people"})
        }
        if not target_indices:
            labels = ", ".join(str(name) for _, name in name_items) or "unavailable"
            raise FaceDetectionError(
                f"The configured checkpoint does not identify the requested "
                f"{normalized_target} class "
                f"(reported classes: {labels}). Configure a face-specific "
                "or person-capable YOLO checkpoint as appropriate."
            )
        self._target_class_indices = target_indices

    @staticmethod
    def _resolve_device(device: str) -> tuple[str, bool]:
        normalized = device.strip().lower()
        if normalized == "cpu":
            return "cpu", False

        try:
            import torch
        except Exception as exc:
            if normalized == "auto":
                return "cpu", False
            raise FaceDetectionError(
                f"CUDA device '{device}' was requested but PyTorch is unavailable: {exc}"
            ) from exc

        available = torch.cuda.is_available()
        if normalized == "auto":
            return ("0", True) if available else ("cpu", False)
        if normalized == "cuda":
            if not available:
                raise FaceDetectionError(
                    "CUDA inference was requested, but torch.cuda.is_available() "
                    "is false. Check the installed PyTorch build, NVIDIA driver, "
                    "and GPU availability, or configure FACE_DEVICE=cpu."
                )
            return "0", True
        if normalized.isdigit():
            index = int(normalized)
            if not available or index >= torch.cuda.device_count():
                raise FaceDetectionError(
                    f"CUDA device index {index} was requested but is unavailable. "
                    "Check the installed PyTorch build, driver, and GPU availability."
                )
            return normalized, True
        raise ValueError("device must be auto, cpu, cuda, or a CUDA device index")

    def detect(self, frame: Frame) -> list[BoundingBox]:
        validate_frame(frame)
        try:
            results = self._model.predict(
                source=frame,
                conf=self.confidence,
                imgsz=self.image_size,
                device=self.device,
                verbose=False,
            )
            if not results:
                raise FaceDetectionError("Face model returned no prediction result.")
            result = results[0]
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                return []

            coordinates = boxes.xyxy
            if hasattr(coordinates, "detach"):
                coordinates = coordinates.detach()
            if hasattr(coordinates, "cpu"):
                coordinates = coordinates.cpu()
            if hasattr(coordinates, "numpy"):
                coordinates = coordinates.numpy()
            coordinates = np.asarray(coordinates)
            if coordinates.size == 0:
                return []
            if coordinates.ndim != 2 or coordinates.shape[1] != 4:
                raise FaceDetectionError(
                    "Face model returned bounding boxes that are not Nx4 xyxy coordinates."
                )

            classes = getattr(boxes, "cls", None)
            if classes is not None:
                if hasattr(classes, "detach"):
                    classes = classes.detach()
                if hasattr(classes, "cpu"):
                    classes = classes.cpu()
                if hasattr(classes, "numpy"):
                    classes = classes.numpy()
                class_ids = np.asarray(classes).reshape(-1)
            else:
                if len(self._target_class_indices) != 1:
                    raise FaceDetectionError(
                        "Detector omitted class IDs for a multi-class checkpoint."
                    )
                class_ids = np.full(
                    len(coordinates), next(iter(self._target_class_indices)), dtype=np.int64
                )
            if len(class_ids) != len(coordinates):
                raise FaceDetectionError(
                    "Face model returned different numbers of boxes and class IDs."
                )

            detections: list[BoundingBox] = []
            for coordinates_row, class_id in zip(coordinates, class_ids):
                try:
                    class_index = int(class_id)
                except (TypeError, ValueError, OverflowError):
                    continue
                if class_index not in self._target_class_indices:
                    continue
                detections.append(tuple(float(value) for value in coordinates_row))
            return detections
        except FaceDetectionError:
            raise
        except Exception as exc:
            raise FaceDetectionError(f"Face-model inference failed: {exc}") from exc

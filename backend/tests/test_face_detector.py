import numpy as np
import pytest

from backend.app.ai.face_detector import FaceDetectionError, YoloFaceDetector, validate_frame


def test_valid_and_invalid_frames():
    validate_frame(np.zeros((12, 16, 3), dtype=np.uint8))

    with pytest.raises(ValueError, match="uint8 BGR"):
        validate_frame(np.zeros((12, 16), dtype=np.uint8))
    with pytest.raises(ValueError, match="uint8 BGR"):
        validate_frame(np.zeros((12, 16, 3), dtype=np.float32))


def test_missing_checkpoint_is_reported_without_model_download(tmp_path):
    with pytest.raises(FaceDetectionError, match="No weights are downloaded automatically"):
        YoloFaceDetector(tmp_path / "missing-face-model.pt", device="cpu")


def test_yolo_detector_uses_injected_model_and_filters_non_face_classes(tmp_path):
    checkpoint = tmp_path / "face-model.pt"
    checkpoint.write_bytes(b"test checkpoint placeholder")

    class TensorLike:
        def __init__(self, value):
            self.value = np.asarray(value)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.value

    class Boxes:
        xyxy = TensorLike([[1, 2, 10, 12], [20, 22, 30, 32]])
        cls = TensorLike([0, 1])

    class Result:
        boxes = Boxes()

    class Model:
        names = {0: "face", 1: "person"}

        def predict(self, **kwargs):
            assert kwargs["device"] == "cpu"
            assert kwargs["conf"] == 0.4
            assert kwargs["imgsz"] == 640
            return [Result()]

    detector = YoloFaceDetector(
        checkpoint,
        confidence=0.4,
        image_size=640,
        device="cpu",
        model_loader=lambda _: Model(),
    )
    boxes = detector.detect(np.zeros((40, 50, 3), dtype=np.uint8))

    assert boxes == [(1.0, 2.0, 10.0, 12.0)]
    assert detector.gpu_acceleration_used is False


def test_injected_yolo_model_rejects_non_face_checkpoint(tmp_path):
    checkpoint = tmp_path / "object-model.pt"
    checkpoint.write_bytes(b"test checkpoint placeholder")

    class Model:
        names = {0: "person"}

    with pytest.raises(FaceDetectionError, match="does not identify the requested face class"):
        YoloFaceDetector(checkpoint, device="cpu", model_loader=lambda _: Model())


def test_person_mode_uses_person_boxes_from_general_yolo_checkpoint(tmp_path):
    checkpoint = tmp_path / "yolo26n.pt"
    checkpoint.write_bytes(b"test checkpoint placeholder")

    class TensorLike:
        def __init__(self, value):
            self.value = np.asarray(value)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.value

    class Boxes:
        xyxy = TensorLike([[1, 2, 10, 12], [20, 22, 30, 32]])
        cls = TensorLike([0, 1])

    class Result:
        boxes = Boxes()

    class Model:
        names = {0: "person", 1: "car"}

        def predict(self, **kwargs):
            assert kwargs["device"] == "cpu"
            return [Result()]

    detector = YoloFaceDetector(
        checkpoint,
        device="cpu",
        target_class="person",
        model_loader=lambda _: Model(),
    )

    assert detector.detect(np.zeros((40, 50, 3), dtype=np.uint8)) == [
        (1.0, 2.0, 10.0, 12.0)
    ]


def test_explicit_cuda_request_fails_when_cuda_is_unavailable(tmp_path, monkeypatch):
    import torch

    checkpoint = tmp_path / "face-model.pt"
    checkpoint.write_bytes(b"test checkpoint placeholder")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    with pytest.raises(FaceDetectionError, match="CUDA inference was requested"):
        YoloFaceDetector(
            checkpoint,
            device="cuda",
            model_loader=lambda _: object(),
        )

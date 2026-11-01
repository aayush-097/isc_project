import math
from collections.abc import Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from backend.app.ai.face_detector import IntegerBoundingBox, validate_frame


def prepare_face_boxes(
    frame: NDArray[np.uint8],
    boxes: Sequence[Sequence[float]],
    *,
    padding: float = 0.18,
) -> list[IntegerBoundingBox]:
    validate_frame(frame)
    if not 0 <= padding <= 1:
        raise ValueError("padding must be between 0 and 1")

    height, width = frame.shape[:2]
    prepared: list[IntegerBoundingBox] = []
    for box in boxes:
        if isinstance(box, (str, bytes)):
            continue
        try:
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = (float(value) for value in box)
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            continue
        if x2 <= x1 or y2 <= y1:
            continue

        pad_x = (x2 - x1) * padding
        pad_y = (y2 - y1) * padding
        left = max(0, math.floor(x1 - pad_x))
        top = max(0, math.floor(y1 - pad_y))
        right = min(width, math.ceil(x2 + pad_x))
        bottom = min(height, math.ceil(y2 + pad_y))
        if right <= left or bottom <= top:
            continue
        prepared.append((left, top, right, bottom))
    return prepared


def blur_face_regions(
    frame: NDArray[np.uint8],
    boxes: Sequence[Sequence[float]],
    *,
    padding: float = 0.18,
    strength: int = 51,
) -> tuple[NDArray[np.uint8], int]:
    """Return a blurred copy and the number of valid regions processed."""
    validate_frame(frame)
    if strength < 3 or strength > 99 or strength % 2 == 0:
        raise ValueError("strength must be an odd integer between 3 and 99")

    output = frame.copy()
    prepared = prepare_face_boxes(frame, boxes, padding=padding)
    for left, top, right, bottom in prepared:
        region = output[top:bottom, left:right]
        output[top:bottom, left:right] = cv2.GaussianBlur(
            region, (strength, strength), sigmaX=0
        )
    return output, len(prepared)


def blur_faces(
    frame: NDArray[np.uint8],
    boxes: Sequence[Sequence[float]],
    *,
    padding: float = 0.18,
    strength: int = 51,
) -> NDArray[np.uint8]:
    """Blur detected face regions on a copy, leaving the input frame unchanged."""
    output, _ = blur_face_regions(frame, boxes, padding=padding, strength=strength)
    return output

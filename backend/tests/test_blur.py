import numpy as np

from backend.app.video.blur import blur_face_regions, blur_faces, prepare_face_boxes


def test_blur_changes_face_region_without_mutating_input():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    pattern = (np.indices((50, 50)).sum(axis=0) % 2 * 255).astype(np.uint8)
    frame[25:75, 35:85] = pattern[:, :, None]
    original = frame.copy()

    blurred, count = blur_face_regions(frame, [(35, 25, 85, 75)], padding=0, strength=31)

    assert count == 1
    assert np.array_equal(frame, original)
    assert not np.array_equal(blurred[35:65, 45:75], original[35:65, 45:75])
    assert np.array_equal(blurred[:20], original[:20])


def test_boxes_are_padded_clamped_and_invalid_boxes_are_rejected():
    frame = np.zeros((80, 100, 3), dtype=np.uint8)
    prepared = prepare_face_boxes(
        frame,
        [
            (-10, 5, 20, 35),
            (30, 30, 20, 40),
            (1, 1, 1, 5),
            (float("nan"), 1, 5, 5),
            (1, 1, 4),
            7,
            None,
        ],
        padding=0.2,
    )

    assert prepared == [(0, 0, 26, 41)]


def test_no_face_frame_is_visually_unchanged():
    frame = np.full((32, 48, 3), 127, dtype=np.uint8)
    blurred = blur_faces(frame, [], strength=31)

    assert np.array_equal(blurred, frame)
    assert blurred is not frame

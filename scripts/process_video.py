import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import Settings, get_settings
from backend.app.video.processor import VideoProcessingError, process_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Blur detected faces in a video using a configured face-specific model."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input video path")
    parser.add_argument("--output", required=True, type=Path, help="Output video path")
    parser.add_argument("--model", type=Path, help="Local face-specific YOLO26n checkpoint")
    parser.add_argument("--confidence", type=float, help="Detection confidence threshold (0..1)")
    parser.add_argument("--image-size", type=int, help="Model inference image size")
    parser.add_argument("--device", help="Inference device: auto, cpu, cuda, or CUDA index")
    parser.add_argument("--blur-strength", type=int, help="Odd Gaussian blur kernel size (3..99)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        base = get_settings()
        values = base.model_dump()
        if args.model is not None:
            values["face_model_path"] = args.model
        if args.confidence is not None:
            values["face_confidence_threshold"] = args.confidence
        if args.image_size is not None:
            values["face_image_size"] = args.image_size
        if args.device is not None:
            values["face_device"] = args.device
        if args.blur_strength is not None:
            values["face_blur_strength"] = args.blur_strength
        settings = Settings(**values)

        def report_progress(processed: int, total: int | None) -> None:
            total_label = str(total) if total is not None else "unknown"
            print(f"Processed {processed}/{total_label} frames", file=sys.stderr)

        stats = process_video(
            args.input,
            args.output,
            settings=settings,
            progress_callback=report_progress,
        )
    except (VideoProcessingError, ValueError, OSError) as exc:
        print(f"Video processing failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(stats.to_dict(), indent=2))
    print(
        "Note: frame-by-frame detection can miss faces. Zero detections do not "
        "prove a video contains no faces or is privacy-safe."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

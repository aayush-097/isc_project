import type { VideoProcessingMetrics, VideoStatus } from "../lib/api";

export function StatusBadge({ status }: { status: VideoStatus }) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}

export function ProcessingMetrics({
  metrics,
}: {
  metrics: VideoProcessingMetrics;
}) {
  return (
    <dl className="metrics-grid">
      <div><dt>Frames processed</dt><dd>{metrics.processed_frames}</dd></div>
      <div><dt>Face detections</dt><dd>{metrics.detected_face_instances}</dd></div>
      <div><dt>Frames with detections</dt><dd>{metrics.frames_with_detections}</dd></div>
      <div><dt>Processing speed</dt><dd>{metrics.processing_fps.toFixed(1)} fps</dd></div>
      <div><dt>Input dimensions</dt><dd>{metrics.input_width} × {metrics.input_height}</dd></div>
      <div><dt>GPU acceleration</dt><dd>{metrics.gpu_acceleration_used ? "Used" : "Not used"}</dd></div>
      <div><dt>Output validation</dt><dd>{metrics.output_validation_status}</dd></div>
    </dl>
  );
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

import { useCallback, useEffect, useState } from "react";

import { StatusBadge, ProcessingMetrics } from "../components/VideoComponents";
import { listVideos, type VideoListItem } from "../lib/api";

export default function CaseLibrary() {
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const result = await listVideos(signal);
      setVideos(result.videos);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason.message : "Could not load the video library.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const update = () => void refresh(controller.signal);
    update();
    window.addEventListener("videos-updated", update);
    return () => {
      controller.abort();
      window.removeEventListener("videos-updated", update);
    };
  }, [refresh]);

  const hasActiveJobs = videos.some(
    (video) => video.status === "queued" || video.status === "processing",
  );
  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, refresh]);

  return (
    <section className="content">
      <div className="page-intro">
        <p className="eyebrow">Your workspace</p>
        <h1>Case library</h1>
        <p className="intro-copy">Development cases and their face-blurring processing status.</p>
      </div>
      <div className="toolbar">
        <div className="filter-tabs"><span className="filter-active">All cases <span>{videos.length}</span></span></div>
        <a className="button" href="/upload"><span aria-hidden="true">＋</span> Upload a video</a>
      </div>
      {loading && <div className="empty-card"><p>Loading video cases…</p></div>}
      {!loading && error && <div className="message message-error" role="alert">{error}</div>}
      {!loading && !error && videos.length === 0 && (
        <div className="empty-card">
          <div className="empty-icon" aria-hidden="true">▧</div>
          <h2>Your library is ready</h2>
          <p>Upload a video to create a development case and begin processing.</p>
          <a className="text-link" href="/upload">Upload a video →</a>
        </div>
      )}
      {!loading && !error && videos.length > 0 && (
        <div className="video-list">
          {videos.map((video) => (
            <article className="video-card" key={video.case_id}>
              <div className="video-card-heading">
                <div>
                  <p className="eyebrow">Video case</p>
                  <h2>{video.title}</h2>
                  <p className="microcopy">
                    Added {new Date(video.created_at).toLocaleString()}
                  </p>
                </div>
                <StatusBadge status={video.status} />
              </div>
              {video.metrics && (
                <p className="panel-copy">
                  {video.metrics.processed_frames} frames · {video.metrics.detected_face_instances} detected face instances
                </p>
              )}
              {video.metrics && <ProcessingMetrics metrics={video.metrics} />}
              {video.status === "completed" ? (
                <a className="button button-small" href={`/cases/${encodeURIComponent(video.case_id)}`}>View blurred video</a>
              ) : video.status === "failed" ? (
                <p className="message message-error">{video.error ?? "Video processing failed."}</p>
              ) : (
                <a className="text-link" href={`/cases/${encodeURIComponent(video.case_id)}`}>View processing status →</a>
              )}
            </article>
          ))}
        </div>
      )}
      <p className="status-note">Unauthenticated development endpoint; do not expose this service to an untrusted network.</p>
    </section>
  );
}

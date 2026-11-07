import { useCallback, useEffect, useState } from "react";

import { StatusBadge, ProcessingMetrics } from "../components/VideoComponents";
import {
  ApiRequestError,
  deleteVideo,
  listVideos,
  retryVideoProcessing,
  type VideoListItem,
} from "../lib/api";

export default function CaseLibrary({ authenticated }: { authenticated: boolean }) {
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authRequired, setAuthRequired] = useState(false);
  const [retryingCaseId, setRetryingCaseId] = useState<string | null>(null);
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});
  const [retryPasskeys, setRetryPasskeys] = useState<Record<string, string>>({});
  const [deletingCaseId, setDeletingCaseId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState("");

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    setAuthRequired(false);
    try {
      const result = await listVideos(signal);
      setVideos(result.videos);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setAuthRequired(reason instanceof ApiRequestError && reason.status === 401);
        setError(reason instanceof Error ? reason.message : "Could not load the video library.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authenticated) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const update = () => void refresh(controller.signal);
    update();
    window.addEventListener("videos-updated", update);
    return () => {
      controller.abort();
      window.removeEventListener("videos-updated", update);
    };
  }, [authenticated, refresh]);

  const hasActiveJobs = videos.some(
    (video) => video.status === "queued" || video.status === "processing",
  );

  async function retry(caseId: string) {
    const passkey = retryPasskeys[caseId] ?? "";
    if (passkey.length < 16 || passkey.length > 1024) {
      setRetryErrors((current) => ({
        ...current,
        [caseId]: "Enter this video's passkey (16–1024 characters) to retry processing.",
      }));
      return;
    }
    setRetryingCaseId(caseId);
    setRetryErrors((current) => {
      const next = { ...current };
      delete next[caseId];
      return next;
    });
    try {
      await retryVideoProcessing(caseId, passkey);
      await refresh();
    } catch (reason) {
      setRetryErrors((current) => ({
        ...current,
        [caseId]: reason instanceof Error ? reason.message : "Could not retry video processing.",
      }));
    } finally {
      setRetryingCaseId(null);
      setRetryPasskeys((current) => {
        const next = { ...current };
        delete next[caseId];
        return next;
      });
    }
  }

  async function remove(caseId: string) {
    if (!window.confirm("Delete this video case and its stored files? This cannot be undone.")) return;
    setDeletingCaseId(caseId);
    setDeleteError("");
    try {
      await deleteVideo(caseId);
      await refresh();
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : "Could not delete the video case.");
    } finally {
      setDeletingCaseId(null);
    }
  }

  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, refresh]);

  return (
    <section className="content">
      <div className="page-intro">
        <p className="eyebrow">Video workspace</p>
        <h1>Video library</h1>
        <p className="intro-copy">Browse blurred videos and unlock originals with their video-specific passkeys.</p>
      </div>
      {!authenticated && (
        <div className="empty-card">
          <h2>Sign in to view your private library</h2>
          <p>Shared video links expose only validated blurred output.</p>
          <a className="button" href="/login">Log in</a>
        </div>
      )}
      {authenticated && (
        <>
      <div className="toolbar">
        <div className="filter-tabs"><span className="filter-active">All cases <span>{videos.length}</span></span></div>
        <a className="button" href="/upload"><span aria-hidden="true">＋</span> Upload a video</a>
      </div>
      {loading && <div className="empty-card"><p>Loading video cases…</p></div>}
      {!loading && error && <div className="message message-error" role="alert">{error}</div>}
      {!loading && authRequired && (
        <p className="panel-copy">
          <a href="/login">Log in</a> to access your private video library.
        </p>
      )}
      {!loading && deleteError && <p className="message message-error" role="alert">{deleteError}</p>}
      {!loading && !error && videos.length === 0 && (
        <div className="empty-card">
          <div className="empty-icon" aria-hidden="true">▧</div>
          <h2>Your library is ready</h2>
          <p>Upload a video to create a private case and begin processing.</p>
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
                <div className="case-actions">
                  <a className="button button-small" href={`/cases/${encodeURIComponent(video.case_id)}`}>View videos</a>
                  {video.is_owner && (
                    <button
                      className="button button-small button-danger"
                      disabled={deletingCaseId !== null}
                      onClick={() => void remove(video.case_id)}
                      type="button"
                    >
                      {deletingCaseId === video.case_id ? "Deleting…" : "Delete case"}
                    </button>
                  )}
                </div>
              ) : video.status === "failed" ? (
                <>
                  <p className="message message-error">{video.error ?? "Video processing failed."}</p>
                  {retryErrors[video.case_id] && (
                    <p className="message message-error" role="alert">{retryErrors[video.case_id]}</p>
                  )}
                  <div className="case-actions">
                    <a className="text-link" href={`/cases/${encodeURIComponent(video.case_id)}`}>View details →</a>
                    {video.is_owner && (
                      <>
                        <form
                          className="upload-form retry-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void retry(video.case_id);
                          }}
                        >
                          <label className="field-label" htmlFor={`retry-passkey-${video.case_id}`}>
                            Video passkey required to retry
                          </label>
                          <input
                            id={`retry-passkey-${video.case_id}`}
                            className="text-input"
                            autoComplete="off"
                            maxLength={1024}
                            minLength={16}
                            onChange={(event) => setRetryPasskeys((current) => ({
                              ...current,
                              [video.case_id]: event.target.value,
                            }))}
                            required
                            type="password"
                            value={retryPasskeys[video.case_id] ?? ""}
                          />
                          <div className="case-actions">
                            <button
                              className="button button-small"
                              disabled={retryingCaseId !== null || (retryPasskeys[video.case_id] ?? "").length < 16}
                              type="submit"
                            >
                              {retryingCaseId === video.case_id ? "Retrying…" : "Retry processing"}
                            </button>
                            <button
                              className="button button-small button-danger"
                              disabled={deletingCaseId !== null}
                              onClick={() => void remove(video.case_id)}
                              type="button"
                            >
                              {deletingCaseId === video.case_id ? "Deleting…" : "Delete case"}
                            </button>
                          </div>
                        </form>
                      </>
                    )}
                  </div>
                </>
              ) : (
                <div className="case-actions">
                  <a className="text-link" href={`/cases/${encodeURIComponent(video.case_id)}`}>View processing status →</a>
                  {video.is_owner && (
                    <button
                      className="button button-small button-danger"
                      disabled={deletingCaseId !== null}
                      onClick={() => void remove(video.case_id)}
                      type="button"
                    >
                      {deletingCaseId === video.case_id ? "Deleting…" : "Delete case"}
                    </button>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      <p className="status-note">Blurred videos are available to signed-in users. Originals require the video-specific passkey and a signed-in account.</p>
        </>
      )}
    </section>
  );
}

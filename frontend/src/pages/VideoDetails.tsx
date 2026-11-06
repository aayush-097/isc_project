import { useEffect, useState } from "react";

import { ProcessingMetrics, StatusBadge } from "../components/VideoComponents";
import {
  ApiRequestError,
  getOriginalVideoUrl,
  getPublicVideoStatus,
  getPublicVideoUrl,
  getVideoStatus,
  type VideoPublicStatusResponse,
  type VideoStatusResponse,
} from "../lib/api";

function wait(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Polling cancelled.", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export default function VideoDetails({ caseId }: { caseId: string }) {
  const [status, setStatus] = useState<VideoStatusResponse | null>(null);
  const [publicStatus, setPublicStatus] = useState<VideoPublicStatusResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const loadStatus = async () => {
      let isOwner = true;
      try {
        while (active) {
          if (isOwner) {
            try {
              const result = await getVideoStatus(caseId, controller.signal);
              if (!active) return;
              setStatus(result);
              if (result.status === "completed" || result.status === "failed") return;
            } catch (reason) {
              if (
                reason instanceof ApiRequestError
                && (reason.status === 401 || reason.status === 404)
              ) {
                isOwner = false;
              } else {
                throw reason;
              }
            }
          }
          if (!isOwner) {
            const result = await getPublicVideoStatus(caseId, controller.signal);
            if (!active) return;
            setPublicStatus(result);
            if (result.status === "completed" || result.status === "failed") return;
          }
          await wait(1500, controller.signal);
        }
      } catch (reason) {
        if (active && !(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason.message : "Could not load this video case.");
        }
      }
    };
    void loadStatus();
    return () => {
      active = false;
      controller.abort();
    };
  }, [caseId]);

  const visibleStatus = status ?? publicStatus;

  return (
    <section className="content">
      <a className="text-link back-link" href="/cases">← All cases</a>
      {error && <p className="message message-error" role="alert">{error}</p>}
      {!visibleStatus && !error && <div className="empty-card"><p>Loading video case…</p></div>}
      {status && (
        <>
          <div className="page-intro">
            <p className="eyebrow">Your video case</p>
            <h1>{status.title}</h1>
            <p className="intro-copy">Processing status <StatusBadge status={status.status} /></p>
          </div>
          {status.status === "completed" && (
            <>
              <div className="video-player-card">
                <h2>Blurred video</h2>
                <video controls playsInline preload="metadata" src={getPublicVideoUrl(caseId)}>
                  Your browser does not support HTML video.
                </video>
                <a className="text-link" download="blurred.mp4" href={getPublicVideoUrl(caseId)}>
                  Download blurred video
                </a>
              </div>
              <div className="video-player-card">
                <h2>Original video</h2>
                <video controls playsInline preload="none" src={getOriginalVideoUrl(caseId)}>
                  Your browser does not support HTML video.
                </video>
                <a className="text-link" download href={getOriginalVideoUrl(caseId)}>
                  Download original video
                </a>
              </div>
            </>
          )}
          {status.status === "processing" && (
            <div className="processing-card">
              <p>Processing video frames… {status.progress ?? 0}%</p>
              <progress className="progress-bar" max={100} value={status.progress ?? 0} />
              <p className="microcopy">Original video is unavailable while processing.</p>
            </div>
          )}
          {status.status === "queued" && (
            <div className="processing-card">
              <p>Upload accepted; processing is queued.</p>
              <p className="microcopy">Original video is unavailable while processing.</p>
            </div>
          )}
          {status.status === "failed" && (
            <>
              <p className="message message-error" role="alert">
                {status.error ?? "Video processing failed. No blurred video is available."}
              </p>
              <div className="video-player-card">
                <h2>Original video</h2>
                <video controls playsInline preload="none" src={getOriginalVideoUrl(caseId)}>
                  Your browser does not support HTML video.
                </video>
                <a className="text-link" download href={getOriginalVideoUrl(caseId)}>
                  Download original video
                </a>
              </div>
            </>
          )}
          {status.original_filename && (
            <dl className="case-metadata">
              <div><dt>Original filename</dt><dd>{status.original_filename}</dd></div>
              {status.processing_completed_at && (
                <div><dt>Processed</dt><dd>{new Date(status.processing_completed_at).toLocaleString()}</dd></div>
              )}
              {status.duration_seconds !== null && (
                <div><dt>Duration</dt><dd>{status.duration_seconds.toFixed(2)} seconds</dd></div>
              )}
              {status.video_width && status.video_height && (
                <div><dt>Resolution</dt><dd>{status.video_width} × {status.video_height}</dd></div>
              )}
            </dl>
          )}
          {status.metrics && <ProcessingMetrics metrics={status.metrics} />}
          <p className="status-note">
            Person detection can miss people. This mode blurs detected whole-person boxes, not only faces; a
            zero-detection result is not a privacy guarantee.
          </p>
        </>
      )}
      {!status && publicStatus && (
        <>
          <div className="page-intro">
            <p className="eyebrow">Shared video</p>
            <h1>Blurred video</h1>
            <p className="intro-copy">Only the validated blurred output is available to other viewers.</p>
          </div>
          {publicStatus.status === "completed" && (
            <div className="video-player-card">
              <video controls playsInline preload="metadata" src={getPublicVideoUrl(caseId)}>
                Your browser does not support HTML video.
              </video>
              <a className="text-link" download="blurred.mp4" href={getPublicVideoUrl(caseId)}>
                Download blurred video
              </a>
            </div>
          )}
          {(publicStatus.status === "queued" || publicStatus.status === "processing") && (
            <div className="processing-card"><p>Blurred video is not available until processing completes.</p></div>
          )}
          {publicStatus.status === "failed" && (
            <p className="message message-error" role="alert">No validated blurred video is available.</p>
          )}
        </>
      )}
    </section>
  );
}

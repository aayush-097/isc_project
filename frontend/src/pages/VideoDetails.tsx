import { useEffect, useState } from "react";

import { ProcessingMetrics, StatusBadge } from "../components/VideoComponents";
import {
  getPublicVideoUrl,
  getVideoStatus,
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
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const loadStatus = async () => {
      try {
        while (active) {
          const result = await getVideoStatus(caseId, controller.signal);
          if (!active) return;
          setStatus(result);
          if (result.status === "completed" || result.status === "failed") return;
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

  return (
    <section className="content">
      <a className="text-link back-link" href="/cases">← All cases</a>
      {error && <p className="message message-error" role="alert">{error}</p>}
      {!status && !error && <div className="empty-card"><p>Loading video case…</p></div>}
      {status && (
        <>
          <div className="page-intro">
            <p className="eyebrow">Video case</p>
            <h1>{status.title}</h1>
            <p className="intro-copy">Processing status <StatusBadge status={status.status} /></p>
          </div>
          {status.status === "completed" && (
            <div className="video-player-card">
              <video controls playsInline preload="metadata" src={getPublicVideoUrl(caseId)}>
                Your browser does not support HTML video.
              </video>
              <a className="text-link" download="public.mp4" href={getPublicVideoUrl(caseId)}>
                Download blurred video
              </a>
            </div>
          )}
          {status.status === "processing" && (
            <div className="processing-card">
              <p>Processing video frames… {status.progress ?? 0}%</p>
              <progress className="progress-bar" max={100} value={status.progress ?? 0} />
            </div>
          )}
          {status.status === "queued" && (
            <div className="processing-card"><p>Upload accepted; processing is queued.</p></div>
          )}
          {status.status === "failed" && (
            <p className="message message-error" role="alert">
              {status.error ?? "Video processing failed. No public video is available."}
            </p>
          )}
          {status.metrics && <ProcessingMetrics metrics={status.metrics} />}
          <p className="status-note">
            Person detection can miss people. This mode blurs detected whole-person boxes, not only faces; a
            zero-detection result is not a privacy guarantee.
          </p>
        </>
      )}
    </section>
  );
}

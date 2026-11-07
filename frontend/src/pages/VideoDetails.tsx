import { useEffect, useRef, useState } from "react";

import { ProcessingMetrics, StatusBadge } from "../components/VideoComponents";
import {
  getOriginalVideoUrl,
  getPublicVideoUrl,
  getVideoStatus,
  unlockVideoOriginal,
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
  const [passkey, setPasskey] = useState("");
  const [unlockError, setUnlockError] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [grantExpiresAt, setGrantExpiresAt] = useState<number | null>(null);
  const expiryTimer = useRef<number | null>(null);
  const originalPlayer = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    originalPlayer.current?.pause();
    setStatus(null);
    setError("");
    setPasskey("");
    setUnlockError("");
    setUnlocked(false);
    setGrantExpiresAt(null);
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
      if (expiryTimer.current !== null) window.clearTimeout(expiryTimer.current);
    };
  }, [caseId]);

  async function unlockOriginal(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUnlockError("");
    setUnlocking(true);
    try {
      const grant = await unlockVideoOriginal(caseId, passkey);
      const expiresAt = Date.now() + grant.expires_in_seconds * 1000;
      if (expiryTimer.current !== null) window.clearTimeout(expiryTimer.current);
      setUnlocked(true);
      setGrantExpiresAt(expiresAt);
      expiryTimer.current = window.setTimeout(() => {
        originalPlayer.current?.pause();
        setUnlocked(false);
        setGrantExpiresAt(null);
      }, grant.expires_in_seconds * 1000);
    } catch (reason) {
      setUnlockError(reason instanceof Error ? reason.message : "Could not unlock this original video.");
    } finally {
      setPasskey("");
      setUnlocking(false);
    }
  }

  return (
    <section className="content">
      <a className="text-link back-link" href="/cases">← Video library</a>
      {error && <p className="message message-error" role="alert">{error}</p>}
      {!status && !error && <div className="empty-card"><p>Loading video case…</p></div>}
      {status && (
        <>
          <div className="page-intro">
            <p className="eyebrow">Video details</p>
            <h1>{status.title}</h1>
            <p className="intro-copy">Processing status <StatusBadge status={status.status} /></p>
          </div>
          {status.status === "completed" && (
            <div className="video-player-card">
              <h2>Blurred Video</h2>
              <video controls playsInline preload="metadata" src={getPublicVideoUrl(caseId)}>
                Your browser does not support HTML video.
              </video>
              <a className="text-link" download="blurred.mp4" href={getPublicVideoUrl(caseId)}>
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
            <div className="processing-card"><p>Video processing is queued.</p></div>
          )}
          {status.status === "failed" && (
            <p className="message message-error" role="alert">
              {status.error ?? "Video processing failed. The blurred video is unavailable."}
            </p>
          )}
          {(status.status === "completed" || status.status === "failed") && (
            <section className="video-player-card" aria-labelledby="original-video-heading">
              <h2 id="original-video-heading">Original Video</h2>
              {!status.original_protected && (
                <p className="message message-error" role="status">
                  This legacy video has no passkey protection. Re-upload it to protect and unlock its original.
                </p>
              )}
              {status.original_protected && !unlocked && (
                <>
                  <p>🔒 Original video is locked. Enter its video-specific passkey to unlock it.</p>
                  {unlockError && <p className="message message-error" role="alert">{unlockError}</p>}
                  <form className="upload-form" onSubmit={(event) => void unlockOriginal(event)}>
                    <label className="field-label" htmlFor="original-passkey">Video passkey</label>
                    <input
                      id="original-passkey"
                      className="text-input"
                      autoComplete="off"
                      maxLength={1024}
                      onChange={(event) => setPasskey(event.target.value)}
                      required
                      type="password"
                      value={passkey}
                    />
                    <button className="button" disabled={unlocking || passkey.length < 16} type="submit">
                      {unlocking ? "Unlocking…" : "Unlock Original Video"}
                    </button>
                  </form>
                </>
              )}
              {status.original_protected && unlocked && (
                <>
                  <p className="message message-success" role="status">
                    Original unlocked. Access expires in five minutes
                    {grantExpiresAt ? ` (at ${new Date(grantExpiresAt).toLocaleTimeString()})` : ""}.
                  </p>
                  <video
                    ref={originalPlayer}
                    controls
                    playsInline
                    preload="metadata"
                    src={getOriginalVideoUrl(caseId)}
                  >
                    Your browser does not support HTML video.
                  </video>
                  <a className="text-link" download href={getOriginalVideoUrl(caseId)}>
                    Download original video
                  </a>
                </>
              )}
            </section>
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
    </section>
  );
}

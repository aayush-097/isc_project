import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  getVideoStatus,
  uploadVideo,
  type VideoStatusResponse,
} from "../lib/api";
import { formatFileSize, ProcessingMetrics, StatusBadge } from "../components/VideoComponents";

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = new Set([".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm"]);

function extensionOf(name: string): string {
  return name.slice(name.lastIndexOf(".")).toLowerCase();
}

function pause(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Polling cancelled.", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    signal.addEventListener(
      "abort",
      abort,
      { once: true },
    );
  });
}

export default function UploadPage() {
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [pollError, setPollError] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [caseId, setCaseId] = useState("");
  const [videoStatus, setVideoStatus] = useState<VideoStatusResponse | null>(null);
  const uploadController = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!caseId) return;
    const controller = new AbortController();
    let active = true;

    const poll = async () => {
      try {
        while (active) {
          const result = await getVideoStatus(caseId, controller.signal);
          if (!active) return;
          setVideoStatus(result);
          window.dispatchEvent(new Event("videos-updated"));
          if (result.status === "completed" || result.status === "failed") return;
          await pause(1500, controller.signal);
        }
      } catch (error) {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) {
          setPollError(error instanceof Error ? error.message : "Could not read processing status.");
        }
      }
    };

    void poll();
    return () => {
      active = false;
      controller.abort();
    };
  }, [caseId]);

  useEffect(() => () => uploadController.current?.abort(), []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError("");
    setUploadError("");
    setPollError("");

    const cleanedTitle = title.trim();
    if (!cleanedTitle) {
      setValidationError("Enter a title for this case.");
      return;
    }
    if (!file) {
      setValidationError("Choose a video file to upload.");
      return;
    }
    if (!ACCEPTED_EXTENSIONS.has(extensionOf(file.name))) {
      setValidationError("Choose an MP4, M4V, MOV, AVI, MKV, or WEBM video.");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setValidationError("The maximum video upload size is 100 MB.");
      return;
    }

    const controller = new AbortController();
    uploadController.current = controller;
    setIsUploading(true);
    setUploadProgress(0);
    setVideoStatus(null);
    setCaseId("");
    try {
      const accepted = await uploadVideo(
        cleanedTitle,
        file,
        setUploadProgress,
        controller.signal,
      );
      setCaseId(accepted.case_id);
      setVideoStatus({
        case_id: accepted.case_id,
        title: accepted.title,
        status: accepted.status,
        progress: 0,
        error: null,
        metrics: null,
      });
      window.dispatchEvent(new Event("videos-updated"));
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setUploadError(error instanceof Error ? error.message : "Video upload failed.");
      }
    } finally {
      setIsUploading(false);
      uploadController.current = null;
    }
  }

  return (
    <section className="content content-narrow">
      <PageIntro
        eyebrow="New case"
        title="Upload a video"
        description="A local development workflow for creating and reviewing a face-blurred video."
      />
      <form className="upload-card upload-form" onSubmit={handleSubmit}>
        <label className="field-label" htmlFor="case-title">Case title</label>
        <input
          id="case-title"
          className="text-input"
          maxLength={200}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. Studio interview"
          value={title}
        />
        <label className="field-label" htmlFor="video-file">Video file</label>
        <input
          id="video-file"
          className="file-input"
          accept="video/mp4,video/quicktime,video/x-msvideo,video/webm,.m4v,.mkv"
          disabled={isUploading || Boolean(caseId)}
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setValidationError("");
          }}
          type="file"
        />
        {file && (
          <p className="selected-file">
            {file.name} <span>· {formatFileSize(file.size)}</span>
          </p>
        )}
        {validationError && <p className="message message-error" role="alert">{validationError}</p>}
        {uploadError && <p className="message message-error" role="alert">{uploadError}</p>}
        {!caseId && (
          <button className="button button-full upload-submit" disabled={isUploading} type="submit">
            {isUploading ? `Uploading${uploadProgress === null ? "" : ` · ${uploadProgress}%`}` : "Upload and process video"}
          </button>
        )}
        {isUploading && (
          <progress aria-label="Upload progress" className="progress-bar" max={100} value={uploadProgress ?? 0} />
        )}
        <p className="form-note">
          Maximum 100 MB. Accepted formats depend on installed OpenCV codecs.
          Upload and case endpoints are unauthenticated and for local development only.
        </p>
      </form>

      {videoStatus && (
        <section className="processing-card" aria-live="polite">
          <div className="processing-heading">
            <div>
              <p className="eyebrow">Processing status</p>
              <h2>{videoStatus.title}</h2>
            </div>
            <StatusBadge status={videoStatus.status} />
          </div>
          {videoStatus.status === "queued" && <p className="panel-copy">Upload accepted; waiting for processing to start.</p>}
          {videoStatus.status === "processing" && (
            <>
              <p className="panel-copy">Processing frames. Keep this page open or return to the library later.</p>
              <progress
                aria-label="Video processing progress"
                className="progress-bar"
                max={100}
                value={videoStatus.progress ?? 0}
              />
              <p className="microcopy">{videoStatus.progress ?? 0}% reported</p>
            </>
          )}
          {videoStatus.status === "failed" && (
            <p className="message message-error" role="alert">
              {videoStatus.error ?? "Video processing failed."}
            </p>
          )}
          {pollError && <p className="message message-error" role="alert">{pollError}</p>}
          {videoStatus.status === "completed" && videoStatus.metrics && (
            <>
              <p className="message message-success">Processing completed and output validation passed.</p>
              <ProcessingMetrics metrics={videoStatus.metrics} />
              <p className="form-note">
                Detected-face counts are observations, not a guarantee that every face was covered.
              </p>
              <a className="button" href={`/cases/${encodeURIComponent(videoStatus.case_id)}`}>
                View blurred video
              </a>
            </>
          )}
          <a className="text-link library-link" href="/cases">Open case library →</a>
        </section>
      )}
      <a className="text-link back-link" href="/cases">← Back to library</a>
    </section>
  );
}

function PageIntro({ eyebrow, title, description }: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="intro-copy">{description}</p>
    </div>
  );
}

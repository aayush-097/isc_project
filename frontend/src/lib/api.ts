export type HealthResponse = {
  status: "ok";
};

export type FaceModelStatusResponse = {
  checkpoint_available: boolean;
  checkpoint_name: string;
  detection_class: "face" | "person";
  message: string;
};

export type ApiError = {
  error?: {
    code?: string;
    message?: string;
    details?: Array<Record<string, string>> | null;
  };
};

export type CredentialsRequest = {
  username: string;
  password: string;
};

export type UserResponse = {
  id: string;
  username: string;
};

export type CaseSummary = {
  id: string;
  title: string;
  is_owner: boolean;
  status: "pending" | "processing" | "ready" | "failed";
  created_at: string;
};

export type CaseListResponse = {
  cases: CaseSummary[];
};

export type CaseCreatedResponse = {
  id: string;
  job_id: string;
  status: "pending" | "processing";
};

export type VerificationResponse = {
  valid: boolean;
  message: string;
};

export type JobResponse = {
  id: string;
  case_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;
  error: string | null;
};

export type RestoreStartRequest = {
  password: string;
};

export type RestoreStartResponse = {
  token: string;
  expires_in_seconds: number;
};

export type VideoStatus = "queued" | "processing" | "completed" | "failed";

export type VideoProcessingMetrics = {
  input_width: number;
  input_height: number;
  input_fps: number | null;
  input_frame_count: number | null;
  processed_frames: number;
  detected_face_instances: number;
  frames_with_detections: number;
  elapsed_seconds: number;
  processing_fps: number;
  output_frame_count: number;
  output_validation_status: string;
  gpu_acceleration_used: boolean;
  output_fps: number;
};

export type VideoUploadResponse = {
  case_id: string;
  title: string;
  status: VideoStatus;
  message: string;
};

export type VideoStatusResponse = {
  case_id: string;
  title: string;
  status: VideoStatus;
  progress: number | null;
  error: string | null;
  metrics: VideoProcessingMetrics | null;
};

export type VideoListItem = {
  case_id: string;
  title: string;
  status: VideoStatus;
  created_at: string;
  error: string | null;
  metrics: VideoProcessingMetrics | null;
};

export type VideoListResponse = {
  videos: VideoListItem[];
};

const API_BASE = "/api";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiError;
    throw new Error(body.error?.message ?? `Request failed (${response.status}).`);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export function getFaceModelStatus(): Promise<FaceModelStatusResponse> {
  return requestJson<FaceModelStatusResponse>("/health/face-model");
}

export function listVideos(signal?: AbortSignal): Promise<VideoListResponse> {
  return requestJson<VideoListResponse>("/videos", { signal });
}

export function getVideoStatus(
  caseId: string,
  signal?: AbortSignal,
): Promise<VideoStatusResponse> {
  return requestJson<VideoStatusResponse>(
    `/videos/${encodeURIComponent(caseId)}/status`,
    { signal },
  );
}

export function retryVideoProcessing(caseId: string): Promise<VideoUploadResponse> {
  return requestJson<VideoUploadResponse>(
    `/videos/${encodeURIComponent(caseId)}/retry`,
    { method: "POST" },
  );
}

export function getPublicVideoUrl(caseId: string): string {
  return `${API_BASE}/videos/${encodeURIComponent(caseId)}/public`;
}

export function uploadVideo(
  title: string,
  file: File,
  onProgress?: (percentage: number) => void,
  signal?: AbortSignal,
): Promise<VideoUploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("title", title);
    form.append("video", file);

    const abort = () => xhr.abort();
    if (signal?.aborted) {
      reject(new DOMException("Upload cancelled.", "AbortError"));
      return;
    }
    signal?.addEventListener("abort", abort, { once: true });

    xhr.open("POST", `${API_BASE}/videos/upload`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onerror = () => reject(new Error("Could not reach the video API."));
    xhr.onabort = () => reject(new DOMException("Upload cancelled.", "AbortError"));
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = {};
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const apiError = body as ApiError & { detail?: string };
        reject(
          new Error(
            apiError.error?.message ??
              apiError.detail ??
              `Video upload failed (${xhr.status}).`,
          ),
        );
        return;
      }
      resolve(body as VideoUploadResponse);
    };
    xhr.onloadend = () => signal?.removeEventListener("abort", abort);
    xhr.send(form);
  });
}

export const apiContract = {
  faceModelStatus: `${API_BASE}/health/face-model`,
  register: `${API_BASE}/auth/register`,
  login: `${API_BASE}/auth/login`,
  logout: `${API_BASE}/auth/logout`,
  currentUser: `${API_BASE}/auth/me`,
  cases: `${API_BASE}/cases`,
  publicVideo: (id: string) => `${API_BASE}/cases/${encodeURIComponent(id)}/public`,
  verifyCase: (id: string) => `${API_BASE}/cases/${encodeURIComponent(id)}/verify`,
  job: (id: string) => `${API_BASE}/jobs/${encodeURIComponent(id)}`,
  startRestore: (id: string) =>
    `${API_BASE}/cases/${encodeURIComponent(id)}/restore/start`,
  restoreStream: (token: string) =>
    `${API_BASE}/restore/stream/${encodeURIComponent(token)}`,
  uploadVideo: `${API_BASE}/videos/upload`,
  videos: `${API_BASE}/videos`,
  videoStatus: (id: string) =>
    `${API_BASE}/videos/${encodeURIComponent(id)}/status`,
  retryVideo: (id: string) =>
    `${API_BASE}/videos/${encodeURIComponent(id)}/retry`,
  videoPublic: getPublicVideoUrl,
} as const;

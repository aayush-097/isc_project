export type HealthResponse = {
  status: "ok";
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

export const apiContract = {
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
} as const;

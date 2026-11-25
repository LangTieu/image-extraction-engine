// API client + shared types for the Image Extraction Engine web UI.
//
// Every fetch hits the backend's real /v1 prefix (settings.api_prefix): the
// built UI is served by FastAPI at "/" and the API lives at "/v1" on the same
// origin. tests/test_ui_contract.py asserts each template below matches a real
// backend route (method + path).

export type JobStatus = "queued" | "processing" | "needs_review" | "completed" | "failed";

export interface JobField {
  field_id?: string;
  field_name: string;
  value: unknown;
  needs_review?: boolean;
  confidence?: number;
}

export interface JobFile {
  id: string;
  file_name: string;
  status: JobStatus;
  mime_type: string | null;
  size_bytes: number;
  confidence: number | null;
  error: string | null;
  result: {
    fields?: JobField[];
    tables?: unknown[];
    document_type?: string;
  } | null;
  exports: Record<string, { path: string; mime: string; checksum: string; size: number }>;
}

export interface Job {
  id: string;
  status: JobStatus;
  profile: string | null;
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  files: JobFile[];
}

const BASE = "/v1";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function createJob(files: File[]): Promise<{ job_id: string }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${BASE}/jobs`, { method: "POST", body: form });
  return json(res);
}

export const getJob = (id: string) => fetch(`${BASE}/jobs/${id}`).then(json<Job>);

export const listJobs = () => fetch(`${BASE}/jobs`).then(json<Job[]>);

// Review one FIELD (not the file): PATCH /v1/jobs/{job_id}/fields/{field_id}.
// The backend finds the field by field_id, falling back to field_name.
export async function review(
  jobId: string,
  fieldId: string,
  action: "accept" | "correct" | "reject",
  value?: string
): Promise<{ job_id: string; field_id: string; action: string; status: string }> {
  const res = await fetch(`${BASE}/jobs/${jobId}/fields/${encodeURIComponent(fieldId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, value }),
  });
  return json(res);
}

// Exports are per JOB: GET /v1/jobs/{job_id}/exports/{fmt} streams the first
// file's artifact for that format. Same origin, so plain links work.
export const exportUrl = (jobId: string, fmt: string) =>
  `${BASE}/jobs/${jobId}/exports/${fmt}`;

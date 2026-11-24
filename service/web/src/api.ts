// API client + shared types for the Image Extraction Engine web UI.

export type JobStatus = "queued" | "processing" | "needs_review" | "completed" | "failed";

export interface JobFile {
  id: string;
  file_name: string;
  status: JobStatus;
  mime_type: string | null;
  size_bytes: number;
  confidence: number | null;
  error: string | null;
  result: {
    fields?: { field_name: string; value: unknown; needs_review?: boolean; confidence?: number }[];
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

const BASE = "/api/v1";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function createJob(files: File[], profile?: string): Promise<{ job_id: string }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const q = profile ? `?profile=${encodeURIComponent(profile)}` : "";
  const res = await fetch(`${BASE}/jobs${q}`, { method: "POST", body: form });
  return json(res);
}

export const getJob = (id: string) => fetch(`${BASE}/jobs/${id}`).then(json<Job>);

export const listJobs = () => fetch(`${BASE}/jobs`).then(json<Job[]>);

export async function review(
  jobId: string,
  fileId: string,
  action: "accept" | "correct" | "reject",
  value?: string
): Promise<Job> {
  const params = new URLSearchParams({ action });
  if (value !== undefined) params.set("value", value);
  const res = await fetch(`${BASE}/jobs/${jobId}/review/${fileId}?${params}`, { method: "POST" });
  return json(res);
}

export const exportUrl = (jobId: string, fileId: string, fmt: string) =>
  `${BASE}/jobs/${jobId}/files/${fileId}/export/${fmt}`;

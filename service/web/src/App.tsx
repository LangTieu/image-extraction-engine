import { useCallback, useEffect, useRef, useState } from "react";
import { createJob, getJob, listJobs, review, exportUrl, Job, JobFile, JobField, JobStatus } from "./api";
import "./styles.css";

// Poll intervals (ms). One tab + one upload must stay under the API's
// rate limit (60 req/min): 6 + 12 = 18 req/min per open tab.
const LIST_POLL_MS = 10_000;
const JOB_POLL_MS = 5_000;

const STATUS_CLASS: Record<JobStatus, string> = {
  queued: "st-queued",
  processing: "st-processing",
  needs_review: "st-review",
  completed: "st-completed",
  failed: "st-failed",
};

function Badge({ status }: { status: JobStatus }) {
  return <span className={`badge ${STATUS_CLASS[status]}`}>{status.replace("_", " ")}</span>;
}

function FieldRow({
  job,
  field,
  onReviewed,
}: {
  job: Job;
  field: JobField;
  onReviewed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doReview = async (action: "accept" | "reject") => {
    setBusy(true);
    setErr(null);
    try {
      await review(job.id, field.field_id ?? field.field_name, action);
      onReviewed();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className={field.needs_review ? "needs-review" : ""}>
      <td>{field.field_name}</td>
      <td>{String(field.value ?? "")}</td>
      {field.needs_review && (
        <td className="field-actions">
          <button className="btn btn-accept" disabled={busy} onClick={() => doReview("accept")}>
            Accept
          </button>
          <button className="btn btn-reject" disabled={busy} onClick={() => doReview("reject")}>
            Reject
          </button>
          {err && <span className="file-error">{err}</span>}
        </td>
      )}
    </tr>
  );
}

function FileCard({ job, file, onReviewed }: { job: Job; file: JobFile; onReviewed: () => void }) {
  return (
    <div className="file-card">
      <div className="file-head">
        <strong>{file.file_name}</strong>
        <Badge status={file.status} />
        {file.confidence != null && (
          <span className="conf">conf {(file.confidence * 100).toFixed(0)}%</span>
        )}
      </div>
      {file.error && <div className="file-error">{file.error}</div>}
      {file.result && (
        <table className="fields">
          <thead>
            <tr>
              <th>Field</th>
              <th>Value</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(file.result.fields ?? []).map((f) => (
              <FieldRow key={f.field_id ?? f.field_name} job={job} field={f} onReviewed={onReviewed} />
            ))}
            {(file.result.fields ?? []).length === 0 && (
              <tr>
                <td colSpan={3}>No fields extracted</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshList = useCallback(() => {
    listJobs().then(setJobs).catch(() => {});
  }, []);

  useEffect(() => {
    refreshList();
    const t = setInterval(refreshList, LIST_POLL_MS);
    return () => clearInterval(t);
  }, [refreshList]);

  useEffect(() => {
    if (!selected) return;
    let stop = false;
    const tick = () =>
      getJob(selected)
        .then((j) => !stop && setJob(j))
        .catch(() => {});
    tick();
    const t = setInterval(tick, JOB_POLL_MS);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [selected]);

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      const created = await createJob(Array.from(files));
      refreshList();
      setSelected(created.job_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  // Export formats available anywhere in the job (exports are per job).
  const formats = job ? [...new Set(job.files.flatMap((f) => Object.keys(f.exports)))] : [];

  return (
    <div className="app">
      <header>
        <h1>Image Extraction Engine</h1>
        <div className="upload">
          <input
            ref={inputRef}
            id="file-input"
            type="file"
            multiple
            accept="image/*,.pdf"
            disabled={uploading}
            onChange={(e) => upload(e.target.files)}
          />
          <label htmlFor="file-input" className="btn btn-primary">
            {uploading ? "Uploading…" : "Upload images / PDFs"}
          </label>
        </div>
      </header>
      {error && <div className="file-error">{error}</div>}
      <main>
        <aside>
          <h2>Jobs</h2>
          <ul className="job-list">
            {jobs.map((j) => (
              <li
                key={j.id}
                className={j.id === selected ? "active" : ""}
                onClick={() => setSelected(j.id)}
              >
                <span className="job-id">{j.id}</span>
                <Badge status={j.status} />
              </li>
            ))}
            {jobs.length === 0 && <li className="empty">No jobs yet</li>}
          </ul>
        </aside>
        <section>
          {job ? (
            <>
              <div className="job-head">
                <h2>
                  {job.id} <Badge status={job.status} />
                </h2>
                {job.status === "processing" || job.status === "queued" ? (
                  <progress value={job.progress} max={100} />
                ) : null}
              </div>
              {formats.length > 0 && (
                <div className="job-exports">
                  {formats.map((fmt) => (
                    <a key={fmt} className="btn btn-export" href={exportUrl(job.id, fmt)} download>
                      ⬇ {fmt}
                    </a>
                  ))}
                </div>
              )}
              {job.files.map((f) => (
                <FileCard key={f.id} job={job} file={f} onReviewed={() => getJob(job.id).then(setJob)} />
              ))}
            </>
          ) : (
            <p className="empty">Upload images or PDFs to start an extraction job.</p>
          )}
        </section>
      </main>
    </div>
  );
}

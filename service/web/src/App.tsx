import { useCallback, useEffect, useRef, useState } from "react";
import { createJob, getJob, listJobs, review, exportUrl, Job, JobFile, JobStatus } from "./api";
import "./styles.css";

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

function FileCard({
  job,
  file,
  onReviewed,
}: {
  job: Job;
  file: JobFile;
  onReviewed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doReview = async (action: "accept" | "reject", value?: string) => {
    setBusy(true);
    setErr(null);
    try {
      await review(job.id, file.id, action, value);
      onReviewed();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

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
            </tr>
          </thead>
          <tbody>
            {(file.result.fields ?? []).map((f) => (
              <tr key={f.field_name} className={f.needs_review ? "needs-review" : ""}>
                <td>{f.field_name}</td>
                <td>{String(f.value ?? "")}</td>
              </tr>
            ))}
            {(file.result.fields ?? []).length === 0 && (
              <tr>
                <td colSpan={2}>No fields extracted</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <div className="file-actions">
        {Object.keys(file.exports).map((fmt) => (
          <a
            key={fmt}
            className="btn btn-export"
            href={exportUrl(job.id, file.id, fmt)}
            download
          >
            ⬇ {fmt}
          </a>
        ))}
        {file.status === "needs_review" && (
          <>
            <button className="btn btn-accept" disabled={busy} onClick={() => doReview("accept")}>
              Accept
            </button>
            <button className="btn btn-reject" disabled={busy} onClick={() => doReview("reject")}>
              Reject
            </button>
          </>
        )}
        {err && <span className="file-error">{err}</span>}
      </div>
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
    const t = setInterval(refreshList, 3000);
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
    const t = setInterval(tick, 1500);
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

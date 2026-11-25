import { useEffect, useRef, useState } from 'react'
import { cancelJob, errorMessage, getJob, isActiveStatus, type Job } from '../api'
import { Badge, EmptyState, Icon, JobBadge, Notice, ProgressBar } from '../components/ui'
import { routeHref, usePolling, type PollState } from '../hooks'
import { describeFile, fileCountLabel, formatDateTime, jobTitle, shortId, timeAgo } from '../util'

const JOB_POLL_MS = 3_000

const FILTERS = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'active', label: 'In progress', match: (job: Job) => isActiveStatus(job.status) },
  { id: 'needs_review', label: 'Needs review', match: (job: Job) => job.status === 'needs_review' },
  { id: 'completed', label: 'Completed', match: (job: Job) => job.status === 'completed' },
  { id: 'failed', label: 'Failed', match: (job: Job) => job.status === 'failed' || job.failedFileCount > 0 },
] as const

type FilterId = (typeof FILTERS)[number]['id']

export function JobsView({ jobs, jobId }: { jobs: PollState<Job[]>; jobId: string | null }) {
  const [filter, setFilter] = useState<FilterId>('all')
  const all = jobs.data ?? []
  const match = FILTERS.find((f) => f.id === filter)?.match ?? (() => true)
  const visible = all.filter(match)
  const listJob = jobId === null ? null : (all.find((job) => job.id === jobId) ?? null)

  return (
    <div className={`split${jobId ? ' split-has-selection' : ''}`}>
      <section className="split-list" aria-label="Jobs">
        <header className="split-list-header">
          <h1>Jobs</h1>
          <label className="sr-only" htmlFor="jobs-filter">
            Filter jobs
          </label>
          <select id="jobs-filter" value={filter} onChange={(e) => setFilter(e.target.value as FilterId)}>
            {FILTERS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label} ({all.filter(f.match).length})
              </option>
            ))}
          </select>
        </header>

        {jobs.loading && <p className="muted pad">Loading jobs…</p>}
        {jobs.error && !jobs.data && <p className="error-text pad">{jobs.error.message}</p>}
        {jobs.data && visible.length === 0 && (
          <EmptyState title={all.length === 0 ? 'No jobs yet' : 'No jobs match this filter'}>
            {all.length === 0 ? 'Upload images to create the first job.' : undefined}
          </EmptyState>
        )}

        <ul className="job-list">
          {visible.map((job) => (
            <li key={job.id}>
              <a
                className={`job-row${job.id === jobId ? ' selected' : ''}`}
                href={routeHref({ view: 'jobs', jobId: job.id })}
                aria-current={job.id === jobId ? 'true' : undefined}
              >
                <span className="job-row-top">
                  <span className="job-row-title">{jobTitle(job)}</span>
                  <span className="muted small">{timeAgo(job.createdAt)}</span>
                </span>
                <span className="job-row-bottom">
                  <JobBadge job={job} />
                  <span className="muted small">
                    {shortId(job.id)} · {fileCountLabel(job.fileCount)}
                  </span>
                </span>
                {isActiveStatus(job.status) && <ProgressBar value={job.progress} label={`Progress of job ${shortId(job.id)}`} />}
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className="split-detail" aria-label="Job details">
        {jobId === null ? (
          <EmptyState title="Select a job">Status, progress and per-file errors appear here.</EmptyState>
        ) : (
          <JobDetail key={jobId} jobId={jobId} listJob={listJob} onChanged={jobs.refresh} />
        )}
      </section>
    </div>
  )
}

function JobDetail({ jobId, listJob, onChanged }: { jobId: string; listJob: Job | null; onChanged: () => void }) {
  const detail = usePolling(
    `job:${jobId}`,
    (signal) => getJob(jobId, signal),
    (job) => (isActiveStatus(job.status) ? JOB_POLL_MS : null),
  )
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)

  // The detail is only polled while the job is running. If the 5 s list poll later reports a
  // different status (for example after review), fetch the detail once more.
  const detailStatus = useRef<string | null>(null)
  const { refresh } = detail
  useEffect(() => {
    detailStatus.current = detail.data?.status ?? null
  }, [detail.data])
  useEffect(() => {
    if (listJob && detailStatus.current !== null && listJob.status !== detailStatus.current) refresh()
  }, [listJob, refresh])

  const job = detail.data ?? listJob

  async function cancel() {
    setCancelling(true)
    setCancelError(null)
    try {
      const updated = await cancelJob(jobId)
      if (updated) detail.setData(updated)
      else detail.refresh()
      onChanged()
      setConfirmingCancel(false)
    } catch (error) {
      setCancelError(errorMessage(error))
    } finally {
      setCancelling(false)
    }
  }

  if (!job) {
    return detail.error ? (
      <Notice
        tone="bad"
        title="Could not load this job"
        action={
          <button type="button" className="btn btn-small" onClick={detail.refresh}>
            Retry
          </button>
        }
      >
        {detail.error.message}
      </Notice>
    ) : (
      <p className="muted">Loading job…</p>
    )
  }

  const active = isActiveStatus(job.status)
  const failedFiles = job.files.filter((f) => describeFile(f.status, f.error).tone === 'bad')

  return (
    <div className="stack">
      <a className="back-link" href={routeHref({ view: 'jobs', jobId: null })}>
        <Icon name="back" />
        All jobs
      </a>

      <header className="detail-header">
        <div>
          <h2 className="detail-title">{jobTitle(job)}</h2>
          <p className="muted small mono">Job {job.id}</p>
        </div>
        <JobBadge job={job} />
      </header>

      {active && (
        <div className="stack-tight">
          <ProgressBar value={job.progress} label="Job progress" />
          <p className="muted small">
            {job.progress === null ? 'Working…' : `${Math.round(job.progress * 100)}% done`} · updates every 3 seconds
          </p>
        </div>
      )}

      {detail.error && <p className="error-text">Status update failed: {detail.error.message}</p>}
      {job.error && (
        <Notice tone="bad" title="Job error">
          {job.error}
        </Notice>
      )}
      {job.failedFileCount > 0 && (
        <Notice tone="bad" title={`${job.failedFileCount} of ${job.fileCount ?? job.failedFileCount} files failed`}>
          {job.status === 'completed' || job.status === 'needs_review'
            ? 'This job finished, but the failed files are missing from the results and exports.'
            : 'The failed files will be missing from the results and exports.'}
          {failedFiles.length === 0 && ' The API did not report which files failed.'}
        </Notice>
      )}

      <dl className="meta">
        <div>
          <dt>Profile</dt>
          <dd>{job.profile ?? 'Not reported'}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatDateTime(job.createdAt)}</dd>
        </div>
        <div>
          <dt>Last update</dt>
          <dd>{formatDateTime(job.updatedAt)}</dd>
        </div>
        <div>
          <dt>Files</dt>
          <dd>{fileCountLabel(job.fileCount)}</dd>
        </div>
      </dl>

      <div className="actions">
        {job.status === 'needs_review' && (
          <a className="btn btn-primary" href={routeHref({ view: 'review', jobId: job.id })}>
            Review flagged fields
          </a>
        )}
        {(job.status === 'completed' || job.status === 'needs_review') && (
          <a className="btn" href={routeHref({ view: 'results', jobId: job.id })}>
            Results and downloads
          </a>
        )}
        {job.status === 'completed' && (
          <a className="btn" href={routeHref({ view: 'review', jobId: job.id })}>
            Open in review
          </a>
        )}
        {active && !confirmingCancel && (
          <button type="button" className="btn btn-danger" onClick={() => setConfirmingCancel(true)}>
            Cancel job
          </button>
        )}
      </div>

      {active && confirmingCancel && (
        <Notice
          tone="warn"
          title="Cancel this job?"
          action={
            <div className="actions">
              <button type="button" className="btn btn-danger" disabled={cancelling} onClick={() => void cancel()}>
                {cancelling ? 'Cancelling…' : 'Yes, cancel job'}
              </button>
              <button type="button" className="btn" disabled={cancelling} onClick={() => setConfirmingCancel(false)}>
                Keep running
              </button>
            </div>
          }
        >
          Processing stops and files that are not finished yet will not be extracted.
        </Notice>
      )}
      {cancelError && (
        <Notice tone="bad" title="Could not cancel the job">
          {cancelError}
        </Notice>
      )}

      <section aria-label="Files in this job">
        <h3 className="section-title">Files</h3>
        {job.files.length === 0 ? (
          <p className="muted">The API did not list individual files for this job.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Status</th>
                  <th scope="col">Error</th>
                </tr>
              </thead>
              <tbody>
                {job.files.map((file) => {
                  const described = describeFile(file.status, file.error)
                  return (
                    <tr key={file.id} className={described.tone === 'bad' ? 'row-bad' : undefined}>
                      <td className="cell-break">{file.name}</td>
                      <td>
                        <Badge tone={described.tone}>{described.label}</Badge>
                      </td>
                      <td className="cell-break">
                        {file.error ?? (described.tone === 'bad' ? 'No error message was provided.' : '')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

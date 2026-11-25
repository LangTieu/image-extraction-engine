import { useEffect, useRef, type ReactNode } from 'react'
import type { Job } from '../api'
import { routeHref, type PollState, type Route } from '../hooks'
import { describeJob, fileCountLabel, jobTitle, shortId, timeAgo, type Tone } from '../util'

const ICON_PATHS = {
  upload: 'M12 16V4m0 0L8 8m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3',
  jobs: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  review: 'M9 11l3 3 8-8M20 12v6a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h9',
  download: 'M12 4v12m0 0l-4-4m4 4l4-4M4 20h16',
  back: 'M15 6l-6 6 6 6',
} as const

export type IconName = keyof typeof ICON_PATHS

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  )
}

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span className="badge-dot" aria-hidden="true" />
      {children}
    </span>
  )
}

export function JobBadge({ job }: { job: Job }) {
  const { label, tone } = describeJob(job)
  return <Badge tone={tone}>{label}</Badge>
}

export function ProgressBar({ value, label, tone = 'info' }: { value: number | null; label: string; tone?: Tone }) {
  const pct = value === null ? null : Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <div
      className={`progress progress-${tone}${pct === null ? ' progress-indeterminate' : ''}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct ?? undefined}
    >
      <div className="progress-fill" style={pct === null ? undefined : { width: `${pct}%` }} />
    </div>
  )
}

export function Notice({
  tone,
  title,
  children,
  action,
}: {
  tone: Tone
  title?: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={`notice notice-${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <div className="notice-body">
        {title && <strong className="notice-title">{title}</strong>}
        {children && <div>{children}</div>}
      </div>
      {action && <div className="notice-action">{action}</div>}
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children && <p className="empty-text">{children}</p>}
    </div>
  )
}

export function EditInput({
  label,
  value,
  disabled,
  onChange,
  onCommit,
  onCancel,
}: {
  label: string
  value: string
  disabled: boolean
  onChange: (value: string) => void
  onCommit: () => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])

  return (
    <input
      ref={ref}
      className="edit-input"
      type="text"
      aria-label={label}
      value={value}
      disabled={disabled}
      autoComplete="off"
      spellCheck={false}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing && e.keyCode !== 229) {
          e.preventDefault()
          onCommit()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
    />
  )
}

/** Job list used by Review and Results when no job is open yet. */
export function JobPicker({
  title,
  intro,
  emptyTitle,
  emptyText,
  jobs,
  include,
  view,
}: {
  title: string
  intro: string
  emptyTitle: string
  emptyText: string
  jobs: PollState<Job[]>
  include: (job: Job) => boolean
  view: Exclude<Route['view'], 'upload'>
}) {
  const matching = (jobs.data ?? []).filter(include)
  return (
    <div className="view">
      <div className="view-narrow">
        <header className="view-header">
          <h1>{title}</h1>
          <p className="muted">{intro}</p>
        </header>
        {jobs.loading && <p className="muted">Loading jobs…</p>}
        {jobs.error && !jobs.data && (
          <Notice tone="bad" title="Could not load jobs">
            {jobs.error.message}
          </Notice>
        )}
        {jobs.data && matching.length === 0 && <EmptyState title={emptyTitle}>{emptyText}</EmptyState>}
        {matching.length > 0 && (
          <ul className="card-list">
            {matching.map((job) => (
              <li key={job.id}>
                <a className="card-link" href={routeHref({ view, jobId: job.id })}>
                  <span className="card-link-main">
                    <span className="card-link-title">{jobTitle(job)}</span>
                    <span className="muted small">
                      Job {shortId(job.id)} · {fileCountLabel(job.fileCount)}
                      {job.createdAt ? ` · ${timeAgo(job.createdAt)}` : ''}
                    </span>
                  </span>
                  <JobBadge job={job} />
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

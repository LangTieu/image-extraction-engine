import { getHealth, getVersion, isActiveStatus, listJobs } from './api'
import { Icon, Notice, type IconName } from './components/ui'
import { routeHref, usePolling, useRoute, type Route } from './hooks'
import { JobsView } from './views/JobsView'
import { ResultsView } from './views/ResultsView'
import { ReviewView } from './views/ReviewView'
import { UploadView } from './views/UploadView'

const JOBS_POLL_MS = 5_000
const HEALTH_POLL_MS = 60_000

function NavLink({
  route,
  current,
  icon,
  label,
  count,
  countLabel,
}: {
  route: Route
  current: Route['view']
  icon: IconName
  label: string
  count?: number
  countLabel?: string
}) {
  const active = route.view === current
  return (
    <li>
      <a className={`nav-link${active ? ' active' : ''}`} href={routeHref(route)} aria-current={active ? 'page' : undefined}>
        <Icon name={icon} />
        <span className="nav-label">{label}</span>
        {count !== undefined && count > 0 && (
          <span className="nav-count">
            {count}
            <span className="sr-only"> {countLabel}</span>
          </span>
        )}
      </a>
    </li>
  )
}

export default function App() {
  const route = useRoute()

  // While a job is open in the review screen the request budget belongs to review actions.
  const reviewing = route.view === 'review' && route.jobId !== null
  const jobs = usePolling('jobs', listJobs, JOBS_POLL_MS, reviewing)
  const health = usePolling('health', getHealth, HEALTH_POLL_MS)
  const version = usePolling('version', getVersion, null)

  const list = jobs.data ?? []
  const activeCount = list.filter((job) => isActiveStatus(job.status)).length
  const reviewCount = list.filter((job) => job.status === 'needs_review').length
  const apiDown = health.error !== null || (health.data !== null && !health.data.ok)

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Image Extraction Engine</span>
        </div>
        <nav aria-label="Main">
          <ul className="nav">
            <NavLink route={{ view: 'upload' }} current={route.view} icon="upload" label="Upload" />
            <NavLink
              route={{ view: 'jobs', jobId: null }}
              current={route.view}
              icon="jobs"
              label="Jobs"
              count={activeCount}
              countLabel="in progress"
            />
            <NavLink
              route={{ view: 'review', jobId: null }}
              current={route.view}
              icon="review"
              label="Review"
              count={reviewCount}
              countLabel="waiting for review"
            />
            <NavLink route={{ view: 'results', jobId: null }} current={route.view} icon="download" label="Results" />
          </ul>
        </nav>
        <div className="api-status">
          <span className={`status-dot ${apiDown ? 'status-dot-bad' : health.data ? 'status-dot-ok' : ''}`} aria-hidden="true" />
          <span>
            {apiDown ? 'API unavailable' : health.data ? 'API online' : 'Checking API…'}
            {version.data && <span className="muted"> · v{version.data.replace(/^v/i, '')}</span>}
          </span>
        </div>
      </aside>

      <main className="main">
        {jobs.error && (
          <div className="main-notice">
            <Notice tone="bad" title="Job list is not updating">
              {jobs.error.message} Retrying automatically.
            </Notice>
          </div>
        )}
        {/* Kept mounted so a running upload survives switching views. */}
        <div className="view-host" hidden={route.view !== 'upload'}>
          <UploadView active={route.view === 'upload'} onJobCreated={jobs.refresh} />
        </div>
        {route.view === 'jobs' && <JobsView jobs={jobs} jobId={route.jobId} />}
        {route.view === 'review' && <ReviewView jobs={jobs} jobId={route.jobId} />}
        {route.view === 'results' && <ResultsView jobs={jobs} jobId={route.jobId} />}
      </main>
    </div>
  )
}

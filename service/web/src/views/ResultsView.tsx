import { useState } from 'react'
import {
  ApiError,
  EXPORT_FORMATS,
  downloadExport,
  errorMessage,
  getJob,
  getResult,
  isActiveStatus,
  isPending,
  requestExports,
  saveBlob,
  type ExportFormat,
  type Field,
  type Job,
  type ResultFile,
} from '../api'
import { Badge, Icon, JobBadge, JobPicker, Notice } from '../components/ui'
import { routeHref, usePolling, type PollState } from '../hooks'
import { confidenceTone, describeFile, jobTitle, percent, type Tone } from '../util'

const JOB_POLL_MS = 3_000

const FORMAT_INFO: Record<ExportFormat, { title: string; description: string }> = {
  xlsx: { title: 'XLSX', description: 'Excel workbook' },
  json: { title: 'JSON', description: 'Unified extraction result' },
  csv: { title: 'CSV', description: 'Comma-separated values' },
  pdf: { title: 'PDF', description: 'Printable report' },
}

export function ResultsView({ jobs, jobId }: { jobs: PollState<Job[]>; jobId: string | null }) {
  if (jobId === null) {
    return (
      <JobPicker
        title="Results"
        intro="Open a finished job to download its exports. Each export file covers the whole job."
        emptyTitle="No finished jobs yet"
        emptyText="Jobs appear here once processing has finished."
        jobs={jobs}
        include={(job) => !isActiveStatus(job.status)}
        view="results"
      />
    )
  }
  const listJob = jobs.data?.find((job) => job.id === jobId) ?? null
  return <ResultsDetail key={jobId} jobId={jobId} listJob={listJob} />
}

interface RowMessage {
  tone: Tone
  text: string
}

function ResultsDetail({ jobId, listJob }: { jobId: string; listJob: Job | null }) {
  const detail = usePolling(
    `job:${jobId}`,
    (signal) => getJob(jobId, signal),
    (job) => (isActiveStatus(job.status) ? JOB_POLL_MS : null),
  )
  const job = detail.data ?? listJob
  const finished = job !== null && !isActiveStatus(job.status)
  const result = usePolling(finished ? `result:${jobId}` : null, (signal) => getResult(jobId, signal), null)

  const [busy, setBusy] = useState<string | null>(null)
  const [messages, setMessages] = useState<Partial<Record<ExportFormat, RowMessage>>>({})

  const setMessage = (fmt: ExportFormat, message: RowMessage) => setMessages((current) => ({ ...current, [fmt]: message }))

  async function download(fmt: ExportFormat) {
    setBusy(`download:${fmt}`)
    try {
      const { blob, filename } = await downloadExport(jobId, fmt)
      saveBlob(blob, filename)
      setMessage(fmt, { tone: 'ok', text: `Downloaded ${filename}` })
    } catch (error) {
      const notReady = error instanceof ApiError && [404, 409, 425].includes(error.status)
      setMessage(fmt, {
        tone: 'bad',
        text: notReady
          ? `${errorMessage(error)} Choose Generate, wait a moment, then download again.`
          : errorMessage(error),
      })
    } finally {
      setBusy(null)
    }
  }

  async function generate(formats: ExportFormat[]) {
    setBusy(`generate:${formats.join(',')}`)
    try {
      await requestExports(jobId, formats)
      for (const fmt of formats) setMessage(fmt, { tone: 'info', text: 'Generation requested. Download in a moment.' })
    } catch (error) {
      for (const fmt of formats) setMessage(fmt, { tone: 'bad', text: errorMessage(error) })
    } finally {
      setBusy(null)
    }
  }

  const pendingCount = (result.data?.files ?? []).reduce(
    (sum, file) => sum + [...file.fields, ...file.tables.flatMap((t) => t.cells)].filter(isPending).length,
    0,
  )

  return (
    <div className="view">
      <div className="view-narrow stack">
        <a className="back-link back-link-always" href={routeHref({ view: 'results', jobId: null })}>
          <Icon name="back" />
          All results
        </a>

        {!job && detail.loading && <p className="muted">Loading job…</p>}
        {!job && detail.error && (
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
        )}

        {job && (
          <>
            <header className="detail-header">
              <div>
                <h1 className="detail-title">{jobTitle(job)}</h1>
                <p className="muted small mono">Job {job.id}</p>
              </div>
              <JobBadge job={job} />
            </header>

            {!finished && (
              <Notice tone="info" title="This job is still processing">
                Exports become available when processing has finished. This page updates automatically.
              </Notice>
            )}
            {job.error && (
              <Notice tone="bad" title="Job error">
                {job.error}
              </Notice>
            )}
            {job.failedFileCount > 0 && (
              <Notice tone="bad" title={`${job.failedFileCount} of ${job.fileCount ?? job.failedFileCount} files failed`}>
                <p>The exports do not contain data for these files:</p>
                <ul className="plain-list">
                  {job.files
                    .filter((f) => describeFile(f.status, f.error).tone === 'bad')
                    .map((f) => (
                      <li key={f.id}>
                        <strong>{f.name}</strong>: {f.error ?? 'No error message was provided.'}
                      </li>
                    ))}
                </ul>
              </Notice>
            )}
            {job.status === 'needs_review' && (
              <Notice
                tone="warn"
                title={pendingCount > 0 ? `${pendingCount} flagged items are not reviewed yet` : 'This job still needs review'}
                action={
                  <a className="btn btn-small" href={routeHref({ view: 'review', jobId })}>
                    Review now
                  </a>
                }
              >
                Exports created now contain the unreviewed values.
              </Notice>
            )}

            <section className="panel" aria-label="Downloads">
              <div className="panel-header">
                <h2>Downloads</h2>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={!finished || busy !== null}
                  onClick={() => void generate([...EXPORT_FORMATS])}
                >
                  Generate all formats
                </button>
              </div>
              <ul className="export-list">
                {EXPORT_FORMATS.map((fmt) => {
                  const message = messages[fmt]
                  return (
                    <li key={fmt} className="export-row">
                      <div className="export-info">
                        <span className="export-title">{FORMAT_INFO[fmt].title}</span>
                        <span className="muted small">{FORMAT_INFO[fmt].description}</span>
                      </div>
                      <div className="actions">
                        <button
                          type="button"
                          className="btn btn-small"
                          disabled={!finished || busy !== null}
                          onClick={() => void generate([fmt])}
                        >
                          {busy === `generate:${fmt}` ? 'Requesting…' : 'Generate'}
                          <span className="sr-only"> {FORMAT_INFO[fmt].title} export</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn-primary btn-small"
                          disabled={!finished || busy !== null}
                          onClick={() => void download(fmt)}
                        >
                          <Icon name="download" />
                          {busy === `download:${fmt}` ? 'Downloading…' : 'Download'}
                          <span className="sr-only"> {FORMAT_INFO[fmt].title} export</span>
                        </button>
                      </div>
                      {message && (
                        <p className={`export-message tone-${message.tone}`} role="status">
                          {message.text}
                        </p>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>

            {finished && (
              <section aria-label="Extracted data">
                <h2 className="section-title">Extracted data</h2>
                {result.loading && <p className="muted">Loading result…</p>}
                {result.error && (
                  <Notice
                    tone="bad"
                    title="Could not load the extraction result"
                    action={
                      <button type="button" className="btn btn-small" onClick={result.refresh}>
                        Retry
                      </button>
                    }
                  >
                    {result.error.message}
                  </Notice>
                )}
                {result.data && result.data.files.length === 0 && <p className="muted">The result contains no files.</p>}
                <div className="stack">
                  {result.data?.files.map((file) => (
                    <ResultFileCard key={file.id} file={file} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function fieldState(field: Field): { label: string; tone: Tone } | null {
  if (isPending(field)) return { label: 'Needs review', tone: 'warn' }
  if (field.reviewState === 'accepted') return { label: 'Accepted', tone: 'ok' }
  if (field.reviewState === 'corrected') return { label: 'Corrected', tone: 'ok' }
  if (field.reviewState === 'rejected') return { label: 'Rejected', tone: 'bad' }
  return null
}

function ResultFileCard({ file }: { file: ResultFile }) {
  const described = describeFile(file.status, file.error)
  return (
    <details className="panel file-card" open={described.tone !== 'bad' || file.fields.length > 0}>
      <summary className="panel-header">
        <span className="file-card-title">
          <span className="file-name">{file.name}</span>
          {file.category && <span className="muted small">{file.category}</span>}
        </span>
        {file.status !== '' || file.error ? <Badge tone={described.tone}>{described.label}</Badge> : null}
      </summary>
      <div className="panel-body stack">
        {described.tone === 'bad' && (
          <Notice tone="bad" title="This file failed">
            {file.error ?? 'No error message was provided.'}
          </Notice>
        )}
        {file.fields.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Value</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Review</th>
                </tr>
              </thead>
              <tbody>
                {file.fields.map((field) => {
                  const state = fieldState(field)
                  return (
                    <tr key={field.key}>
                      <td>{field.name}</td>
                      <td className={`mono cell-break${field.reviewState === 'rejected' ? ' struck' : ''}`}>{field.value}</td>
                      <td className={`tone-${confidenceTone(field.confidence)}`}>{percent(field.confidence)}</td>
                      <td>{state && <Badge tone={state.tone}>{state.label}</Badge>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {file.tables.map((table) => (
          <div key={table.id} className="table-wrap">
            <table className="data-table">
              <caption>{table.name}</caption>
              {table.headers.length > 0 && (
                <thead>
                  <tr>
                    {Array.from({ length: table.colCount }, (_, col) => (
                      <th key={col} scope="col">
                        {table.headers[col] ?? ''}
                      </th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {Array.from({ length: table.rowCount }, (_, row) => (
                  <tr key={row}>
                    {Array.from({ length: table.colCount }, (_, col) => {
                      const cell = table.cells.find((c) => c.cell?.row === row && c.cell?.col === col)
                      return (
                        <td
                          key={col}
                          className={`mono${cell && isPending(cell) ? ' cell-pending' : ''}${cell?.reviewState === 'rejected' ? ' struck' : ''}`}
                        >
                          {cell?.value ?? ''}
                          {cell && isPending(cell) && <span className="sr-only"> (needs review)</span>}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {file.textBlocks.length > 0 && (
          <div>
            <p className="label">Extracted text</p>
            <ol className="text-blocks">
              {file.textBlocks.map((block) => (
                <li key={block.key}>
                  <span className="mono text-block-text">{block.text === '' ? <span className="muted">(empty)</span> : block.text}</span>
                  <span className="muted small">
                    {' '}
                    {percent(block.confidence)}
                    {block.language !== null && ` · ${block.language}`}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {described.tone !== 'bad' && file.fields.length === 0 && file.tables.length === 0 && file.textBlocks.length === 0 && (
          <p className="muted">No fields were extracted from this file.</p>
        )}
      </div>
    </details>
  )
}

import { useRef, useState, type DragEvent } from 'react'
import {
  EXPORT_FORMATS,
  createJob,
  errorMessage,
  getJob,
  isActiveStatus,
  listProfiles,
  type ExportFormat,
  type Job,
  type JobFile,
} from '../api'
import { Badge, JobBadge, Notice, ProgressBar } from '../components/ui'
import { routeHref, usePolling } from '../hooks'
import { rememberSourceImage } from '../imageStore'
import { describeFile, describeJob, formatBytes, shortId, type Described } from '../util'

const JOB_POLL_MS = 3_000
const IMAGE_EXTENSION = /\.(png|jpe?g|gif|bmp|webp|tiff?|heic|heif)$/i

type UploadState =
  | { phase: 'idle' }
  | { phase: 'uploading'; fraction: number }
  | { phase: 'failed'; message: string }
  | { phase: 'created'; job: Job }

interface RowState extends Described {
  progress: number | null
  detail: string | null
}

const isImage = (file: File) => file.type.startsWith('image/') || IMAGE_EXTENSION.test(file.name)
const identity = (file: File) => `${file.name}:${file.size}:${file.lastModified}`

function matchJobFile(job: Job, file: File, index: number, all: File[]): JobFile | null {
  const sameName = job.files.filter((f) => f.name === file.name)
  if (sameName.length === 1) return sameName[0]
  if (sameName.length > 1) {
    const occurrence = all.slice(0, index).filter((f) => f.name === file.name).length
    return sameName[occurrence] ?? sameName[0]
  }
  return job.files.length === all.length ? job.files[index] : null
}

export function UploadView({ active, onJobCreated }: { active: boolean; onJobCreated: () => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [skipped, setSkipped] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [profile, setProfile] = useState('')
  const [category, setCategory] = useState('')
  const [languages, setLanguages] = useState('')
  const [formats, setFormats] = useState<ExportFormat[]>([])
  const [upload, setUpload] = useState<UploadState>({ phase: 'idle' })
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const profiles = usePolling('profiles', listProfiles, null)
  const createdId = upload.phase === 'created' ? upload.job.id : null
  const tracked = usePolling(
    createdId === null ? null : `job:${createdId}`,
    (signal) => getJob(createdId ?? '', signal),
    (job) => (isActiveStatus(job.status) ? JOB_POLL_MS : null),
    !active,
  )
  const job = upload.phase === 'created' ? (tracked.data ?? upload.job) : null

  const locked = upload.phase === 'uploading' || upload.phase === 'created'
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0)
  const selectedProfile = profiles.data?.find((p) => p.id === profile) ?? null
  const categories = selectedProfile?.categories ?? [...new Set((profiles.data ?? []).flatMap((p) => p.categories))]

  function addFiles(incoming: File[]) {
    if (locked) return
    const images = incoming.filter(isImage)
    setSkipped(incoming.filter((f) => !isImage(f)).map((f) => f.name))
    setFiles((current) => {
      const known = new Set(current.map(identity))
      return [...current, ...images.filter((f) => !known.has(identity(f)))]
    })
    if (upload.phase === 'failed') setUpload({ phase: 'idle' })
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    addFiles(Array.from(event.dataTransfer.files))
  }

  async function start() {
    if (files.length === 0 || locked) return
    const controller = new AbortController()
    abortRef.current = controller
    setUpload({ phase: 'uploading', fraction: 0 })
    try {
      const created = await createJob(
        files,
        {
          profile: profile || null,
          forcedCategory: category.trim() || null,
          languages: languages.split(/[,\s]+/).filter(Boolean),
          exportFormats: formats,
        },
        (loaded, total) => setUpload({ phase: 'uploading', fraction: total > 0 ? loaded / total : 0 }),
        controller.signal,
      )
      for (const file of files) void rememberSourceImage(created.id, file.name, file)
      setUpload({ phase: 'created', job: created })
      onJobCreated()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setUpload({ phase: 'idle' })
      } else {
        setUpload({ phase: 'failed', message: errorMessage(error) })
      }
    }
  }

  function reset() {
    setFiles([])
    setSkipped([])
    setUpload({ phase: 'idle' })
  }

  // One multipart request carries the whole batch, so per-file upload progress is derived from
  // the bytes sent so far (files are streamed in list order).
  function uploadFraction(index: number, fraction: number): number {
    const before = files.slice(0, index).reduce((sum, f) => sum + f.size, 0)
    const size = files[index].size
    if (size === 0) return fraction >= 1 ? 1 : 0
    return Math.min(1, Math.max(0, (fraction * totalBytes - before) / size))
  }

  function rowState(file: File, index: number): RowState {
    switch (upload.phase) {
      case 'idle':
        return { label: 'Ready', tone: 'neutral', progress: null, detail: null }
      case 'failed':
        return { label: 'Not uploaded', tone: 'bad', progress: null, detail: null }
      case 'uploading': {
        const p = uploadFraction(index, upload.fraction)
        const label = p >= 1 ? 'Uploaded' : p > 0 ? `Uploading ${Math.round(p * 100)}%` : 'Waiting'
        return { label, tone: p >= 1 ? 'ok' : 'info', progress: p, detail: null }
      }
      case 'created': {
        const current = job ?? upload.job
        const jobFile = matchJobFile(current, file, index, files)
        if (jobFile && (jobFile.status !== '' || jobFile.error !== null)) {
          return { ...describeFile(jobFile.status, jobFile.error), progress: null, detail: jobFile.error }
        }
        return { ...describeJob(current), progress: null, detail: null }
      }
    }
  }

  return (
    <div className="view">
      <div className="view-narrow">
        <header className="view-header">
          <h1>Upload</h1>
          <p className="muted">Add one or more images. The whole batch is submitted as a single extraction job.</p>
        </header>

        <div
          className={`dropzone${dragging ? ' dropzone-active' : ''}${locked ? ' dropzone-locked' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            if (!locked) setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <p className="dropzone-title">Drag and drop images here</p>
          <p className="muted small">PNG, JPEG, TIFF, BMP, WebP and other image formats</p>
          <button type="button" className="btn" disabled={locked} onClick={() => inputRef.current?.click()}>
            Choose files
          </button>
          <input
            ref={inputRef}
            className="sr-only"
            type="file"
            accept="image/*"
            multiple
            tabIndex={-1}
            aria-label="Choose image files"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
        </div>

        {skipped.length > 0 && (
          <Notice tone="warn" title="Some files were skipped">
            Only images can be uploaded. Skipped: {skipped.join(', ')}
          </Notice>
        )}

        {files.length > 0 && (
          <section className="panel" aria-label="Selected files">
            <div className="panel-header">
              <h2>
                {files.length === 1 ? '1 file' : `${files.length} files`} · {formatBytes(totalBytes)}
              </h2>
              {!locked && (
                <button type="button" className="btn btn-quiet" onClick={reset}>
                  Clear all
                </button>
              )}
            </div>
            <ul className="file-list">
              {files.map((file, index) => {
                const row = rowState(file, index)
                return (
                  <li key={identity(file)} className="file-row">
                    <div className="file-row-main">
                      <span className="file-name">{file.name}</span>
                      <span className="muted small">{formatBytes(file.size)}</span>
                    </div>
                    <div className="file-row-status">
                      <Badge tone={row.tone}>{row.label}</Badge>
                      {!locked && (
                        <button
                          type="button"
                          className="btn btn-quiet btn-small"
                          onClick={() => setFiles((current) => current.filter((f) => f !== file))}
                        >
                          Remove<span className="sr-only"> {file.name}</span>
                        </button>
                      )}
                    </div>
                    {row.progress !== null && (
                      <div className="file-row-wide">
                        <ProgressBar
                          value={row.progress}
                          label={`Upload progress for ${file.name}`}
                          tone={row.progress >= 1 ? 'ok' : 'info'}
                        />
                      </div>
                    )}
                    {row.detail && <p className="file-row-wide error-text">{row.detail}</p>}
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        {upload.phase !== 'created' && (
          <section className="panel" aria-label="Extraction options">
            <div className="panel-header">
              <h2>Options</h2>
            </div>
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="upload-profile">Extraction profile</label>
                <select id="upload-profile" value={profile} disabled={locked} onChange={(e) => setProfile(e.target.value)}>
                  <option value="">Server default</option>
                  {(profiles.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.isDefault ? ' (default)' : ''}
                    </option>
                  ))}
                </select>
                {profiles.loading && <p className="hint">Loading profiles…</p>}
                {profiles.error && (
                  <p className="hint error-text">
                    Could not load profiles: {profiles.error.message}{' '}
                    <button type="button" className="link-button" onClick={profiles.refresh}>
                      Retry
                    </button>
                  </p>
                )}
                {selectedProfile?.description && <p className="hint">{selectedProfile.description}</p>}
              </div>

              <div className="form-field">
                <label htmlFor="upload-category">Forced category</label>
                <input
                  id="upload-category"
                  type="text"
                  list="upload-categories"
                  placeholder="Auto-detect"
                  value={category}
                  disabled={locked}
                  onChange={(e) => setCategory(e.target.value)}
                />
                <datalist id="upload-categories">
                  {categories.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
                <p className="hint">Leave empty to let the engine classify each image.</p>
              </div>

              <div className="form-field">
                <label htmlFor="upload-languages">Languages</label>
                <input
                  id="upload-languages"
                  type="text"
                  placeholder={selectedProfile?.languages.join(', ') || 'Profile default'}
                  value={languages}
                  disabled={locked}
                  onChange={(e) => setLanguages(e.target.value)}
                />
                <p className="hint">Language codes separated by commas, for example: en, de</p>
              </div>

              <fieldset className="form-field">
                <legend>Export formats</legend>
                <div className="check-row">
                  {EXPORT_FORMATS.map((fmt) => (
                    <label key={fmt} className="check">
                      <input
                        type="checkbox"
                        checked={formats.includes(fmt)}
                        disabled={locked}
                        onChange={(e) =>
                          setFormats((current) => (e.target.checked ? [...current, fmt] : current.filter((f) => f !== fmt)))
                        }
                      />
                      {fmt.toUpperCase()}
                    </label>
                  ))}
                </div>
                <p className="hint">Optional. Any format can also be generated later from Results.</p>
              </fieldset>
            </div>
          </section>
        )}

        {upload.phase === 'failed' && (
          <Notice tone="bad" title="Upload failed">
            {upload.message} No job was created. Your files are still listed, so you can try again.
          </Notice>
        )}

        {upload.phase !== 'created' && (
          <div className="actions">
            <button type="button" className="btn btn-primary" disabled={files.length === 0 || locked} onClick={() => void start()}>
              {upload.phase === 'uploading'
                ? `Uploading ${Math.round(upload.fraction * 100)}%`
                : files.length > 1
                  ? `Upload ${files.length} files`
                  : 'Upload'}
            </button>
            {upload.phase === 'uploading' && (
              <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
                Cancel upload
              </button>
            )}
          </div>
        )}

        {job && (
          <section className="panel" aria-label="Created job" aria-live="polite">
            <div className="panel-header">
              <h2>Job {shortId(job.id)}</h2>
              <JobBadge job={job} />
            </div>
            <div className="panel-body stack">
              {isActiveStatus(job.status) && <ProgressBar value={job.progress} label="Job progress" />}
              {job.failedFileCount > 0 && (
                <Notice tone="bad" title={`${job.failedFileCount} of ${job.fileCount ?? files.length} files failed`}>
                  Failed files are missing from the results and exports. See the per-file errors above.
                </Notice>
              )}
              {job.error && <Notice tone="bad">{job.error}</Notice>}
              {tracked.error && <p className="error-text">Status update failed: {tracked.error.message}</p>}
              <div className="actions">
                <a className="btn" href={routeHref({ view: 'jobs', jobId: job.id })}>
                  Open job
                </a>
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
                <button type="button" className="btn btn-quiet" onClick={reset}>
                  New upload
                </button>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

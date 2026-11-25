import { useEffect, useMemo, useRef, useState } from 'react'
import {
  allItems,
  errorMessage,
  getReviewData,
  isPending,
  reviewField,
  type ExtractionResult,
  type Field,
  type Job,
  type ReviewAction,
  type TextBlock,
} from '../api'
import { FieldList, type EditControls } from '../components/FieldList'
import { ImageViewer, type OverlayBox, type Size } from '../components/ImageViewer'
import { Inspector } from '../components/Inspector'
import { TableGrid } from '../components/TableGrid'
import { EmptyState, Icon, JobPicker, Notice } from '../components/ui'
import { routeHref, usePolling, useSourceImage, type PollState } from '../hooks'
import { describeFile, isTypingTarget, percent, shortId } from '../util'

export function ReviewView({ jobs, jobId }: { jobs: PollState<Job[]>; jobId: string | null }) {
  if (jobId === null) {
    return (
      <JobPicker
        title="Review"
        intro="Jobs with fields the engine was not sure about. Open one to check the flagged values against the image."
        emptyTitle="Nothing to review"
        emptyText="Jobs appear here when their status is “needs review”."
        jobs={jobs}
        include={(job) => job.status === 'needs_review'}
        view="review"
      />
    )
  }
  const job = jobs.data?.find((j) => j.id === jobId) ?? null
  return <ReviewWorkspace key={jobId} jobId={jobId} job={job} />
}

interface Entry {
  fileIndex: number
  item: Field
}

function updateField(result: ExtractionResult, key: string, change: (field: Field) => Field): ExtractionResult {
  const apply = (field: Field) => (field.key === key ? change(field) : field)
  return {
    ...result,
    files: result.files.map((file) => ({
      ...file,
      fields: file.fields.map(apply),
      tables: file.tables.map((table) => ({ ...table, cells: table.cells.map(apply) })),
    })),
  }
}

function boxTone(field: Field): OverlayBox['tone'] {
  if (isPending(field)) return 'pending'
  if (field.reviewState === 'rejected') return 'rejected'
  if (field.reviewState !== null) return 'ok'
  return 'plain'
}

function ReviewWorkspace({ jobId, job }: { jobId: string; job: Job | null }) {
  const loaded = usePolling(`review:${jobId}`, (signal) => getReviewData(jobId, signal), null)

  const [synced, setSynced] = useState<ExtractionResult | null>(null)
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [fileIndex, setFileIndex] = useState(0)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [space, setSpace] = useState<Size | null>(null)

  // Copy each freshly loaded result into local state so review actions can update it in place.
  if (loaded.data !== synced) {
    setSynced(loaded.data)
    setResult(loaded.data)
    if (loaded.data && selectedKey === null) {
      const entries = loaded.data.files.flatMap((f, fi) => allItems(f).map((item) => ({ fileIndex: fi, item })))
      const first = entries.find((e) => isPending(e.item)) ?? entries[0]
      if (first) {
        setFileIndex(first.fileIndex)
        setSelectedKey(first.item.key)
      } else {
        // No reviewable fields: fall back to the first extracted text block, if any.
        const blockFile = loaded.data.files.find((f) => f.textBlocks.length > 0)
        if (blockFile) {
          setFileIndex(loaded.data.files.indexOf(blockFile))
          setSelectedKey(blockFile.textBlocks[0].key)
        }
      }
    }
  }

  const order = useMemo<Entry[]>(
    () => (result ? result.files.flatMap((f, fi) => allItems(f).map((item) => ({ fileIndex: fi, item }))) : []),
    [result],
  )
  const pendingCount = order.filter((e) => isPending(e.item)).length
  const file = result?.files[fileIndex] ?? null
  const selectedEntry = order.find((e) => e.item.key === selectedKey) ?? null
  const selected = selectedEntry?.item ?? null
  const selectedBlock = file?.textBlocks.find((b) => b.key === selectedKey) ?? null
  const image = useSourceImage(jobId, file)

  // Blocks of the current file in reading order (missing reading_order keeps the API order).
  const blockOrder = useMemo<TextBlock[]>(
    () =>
      file
        ? file.textBlocks
            .map((block, index) => ({ block, index }))
            .sort((a, b) => (a.block.readingOrder ?? a.index) - (b.block.readingOrder ?? b.index))
            .map(({ block }) => block)
        : [],
    [file],
  )

  const boxes = useMemo<OverlayBox[]>(
    () =>
      file
        ? [
            // Draw text blocks first so reviewable field boxes render on top of them.
            ...file.textBlocks.flatMap((block) =>
              block.bbox
                ? [{ key: block.key, bbox: block.bbox, tone: 'block' as const, label: `Text block: ${block.text}` }]
                : [],
            ),
            ...allItems(file).flatMap((item) =>
              item.bbox ? [{ key: item.key, bbox: item.bbox, tone: boxTone(item), label: `${item.name}: ${item.value}` }] : [],
            ),
          ]
        : [],
    [file],
  )

  function select(key: string) {
    const entry = order.find((e) => e.item.key === key)
    if (entry) {
      setFileIndex(entry.fileIndex)
      setSelectedKey(key)
      setEditing(false)
      setActionError(null)
      return
    }
    // Text blocks are not review items; still let the image and list select them.
    const blockFileIndex = result?.files.findIndex((f) => f.textBlocks.some((b) => b.key === key)) ?? -1
    if (blockFileIndex === -1) return
    setFileIndex(blockFileIndex)
    setSelectedKey(key)
    setEditing(false)
    setActionError(null)
  }

  function findPending(direction: 1 | -1, skipKey?: string): Entry | null {
    const count = order.length
    if (count === 0) return null
    const current = order.findIndex((e) => e.item.key === selectedKey)
    const start = current === -1 ? (direction === 1 ? -1 : 0) : current
    for (let stepCount = 1; stepCount <= count; stepCount++) {
      const entry = order[(((start + direction * stepCount) % count) + count) % count]
      if (entry.item.key !== skipKey && isPending(entry.item)) return entry
    }
    return null
  }

  function goPending(direction: 1 | -1) {
    const entry = findPending(direction)
    if (entry) select(entry.item.key)
  }

  function startEdit(key?: string) {
    const target = key ? order.find((e) => e.item.key === key)?.item : selected
    if (!target || saving) return
    if (key) select(key)
    setDraft(target.value)
    setEditing(true)
  }

  async function act(action: ReviewAction, value?: string) {
    if (!selected || saving) return
    if (selected.id === null) {
      setActionError('The API result has no field id for this item, so it cannot be reviewed.')
      return
    }
    const key = selected.key
    setSaving(true)
    setActionError(null)
    try {
      await reviewField(jobId, selected.id, action, value)
      setResult(
        (current) =>
          current &&
          updateField(current, key, (field) => ({
            ...field,
            value: action === 'correct' ? (value ?? '') : field.value,
            originalValue: action === 'correct' ? (field.originalValue ?? field.value) : field.originalValue,
            reviewState: action === 'accept' ? 'accepted' : action === 'reject' ? 'rejected' : 'corrected',
          })),
      )
      setEditing(false)
      const next = findPending(1, key)
      if (next) {
        setFileIndex(next.fileIndex)
        setSelectedKey(next.item.key)
      }
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  function commitEdit() {
    if (!selected) return
    if (draft === selected.value) {
      if (isPending(selected)) void act('accept')
      else setEditing(false)
      return
    }
    void act('correct', draft)
  }

  const onKey = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return
    const onControl = event.target instanceof HTMLElement && event.target.closest('button, a, summary, label') !== null
    switch (event.key) {
      case 'n':
      case 'j':
        goPending(1)
        break
      case 'p':
      case 'k':
        goPending(-1)
        break
      case 'a':
        if (selected?.reviewState === 'accepted') return
        void act('accept')
        break
      case 'r':
        if (selected?.reviewState === 'rejected') return
        void act('reject')
        break
      case 'e':
      case 'F2':
        startEdit()
        break
      case 'Enter':
        if (onControl) return
        startEdit()
        break
      default: {
        const alternative = /^[1-9]$/.test(event.key) ? selected?.alternatives[Number(event.key) - 1] : undefined
        if (!alternative) return
        void act('correct', alternative.value)
      }
    }
    event.preventDefault()
  }
  const onKeyRef = useRef(onKey)
  useEffect(() => {
    onKeyRef.current = onKey
  })
  useEffect(() => {
    const listener = (event: KeyboardEvent) => onKeyRef.current(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  const edit: EditControls = {
    editing,
    draft,
    saving,
    onDraft: setDraft,
    onStart: startEdit,
    onCommit: commitEdit,
    onCancel: () => setEditing(false),
  }

  const header = (
    <header className="review-bar">
      <a className="back-link back-link-always" href={routeHref({ view: 'review', jobId: null })}>
        <Icon name="back" />
        Review list
      </a>
      <h1 className="review-title">Job {shortId(jobId)}</h1>
      {result && (
        <span className={`review-count ${pendingCount > 0 ? 'tone-warn' : 'tone-ok'}`} role="status">
          {pendingCount > 0 ? `${pendingCount} flagged ${pendingCount === 1 ? 'item' : 'items'} left` : 'All flagged items reviewed'}
        </span>
      )}
      <div className="review-bar-actions">
        <button type="button" className="btn btn-small" disabled={pendingCount === 0} onClick={() => goPending(-1)}>
          Previous flagged <kbd>P</kbd>
        </button>
        <button type="button" className="btn btn-small" disabled={pendingCount === 0} onClick={() => goPending(1)}>
          Next flagged <kbd>N</kbd>
        </button>
        <a className="btn btn-small" href={routeHref({ view: 'results', jobId })}>
          Results
        </a>
      </div>
    </header>
  )

  if (!result) {
    return (
      <div className="review">
        {header}
        <div className="view">
          {loaded.error ? (
            <Notice
              tone="bad"
              title="Could not load the review data"
              action={
                <button type="button" className="btn btn-small" onClick={loaded.refresh}>
                  Retry
                </button>
              }
            >
              {loaded.error.message}
            </Notice>
          ) : (
            <p className="muted">Loading result and flagged fields…</p>
          )}
        </div>
      </div>
    )
  }

  if (!file) {
    return (
      <div className="review">
        {header}
        <div className="view">
          <EmptyState title="This result contains no files">There is nothing to review for this job.</EmptyState>
        </div>
      </div>
    )
  }

  const fileFailed = describeFile(file.status, file.error).tone === 'bad'
  const failedInJob = job?.failedFileCount ?? 0

  return (
    <div className="review">
      {header}

      {(failedInJob > 0 || (pendingCount === 0 && order.length > 0)) && (
        <div className="review-notices">
          {failedInJob > 0 && (
            <Notice
              tone="bad"
              title={`${failedInJob} ${failedInJob === 1 ? 'file' : 'files'} in this job failed`}
              action={
                <a className="btn btn-small" href={routeHref({ view: 'jobs', jobId })}>
                  See errors
                </a>
              }
            >
              Failed files have no extracted data to review.
            </Notice>
          )}
          {pendingCount === 0 && order.length > 0 && (
            <Notice
              tone="ok"
              title="All flagged items are reviewed"
              action={
                <a className="btn btn-small btn-primary" href={routeHref({ view: 'results', jobId })}>
                  Go to downloads
                </a>
              }
            />
          )}
        </div>
      )}

      {result.files.length > 1 && (
        <div className="file-tabs" role="tablist" aria-label="Files in this job">
          {result.files.map((f, index) => {
            const flagged = allItems(f).filter(isPending).length
            const failed = describeFile(f.status, f.error).tone === 'bad'
            return (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={index === fileIndex}
                className={`file-tab${index === fileIndex ? ' active' : ''}`}
                onClick={() => {
                  setFileIndex(index)
                  setEditing(false)
                  setSelectedKey(allItems(f).find(isPending)?.key ?? allItems(f)[0]?.key ?? f.textBlocks[0]?.key ?? null)
                }}
              >
                <span className="file-tab-name">{f.name}</span>
                {failed ? (
                  <span className="pill pill-bad">Failed</span>
                ) : flagged > 0 ? (
                  <span className="pill pill-warn">
                    {flagged}
                    <span className="sr-only"> flagged</span>
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>
      )}

      <div className="review-body">
        <div className="review-stage">
          {fileFailed && (
            <div className="review-notices">
              <Notice tone="bad" title={`${file.name} failed`}>
                {file.error ?? 'No error message was provided.'}
              </Notice>
            </div>
          )}
          <ImageViewer
            src={image.src}
            searching={image.searching}
            fileName={file.name}
            declaredSize={file.width !== null && file.height !== null ? { w: file.width, h: file.height } : null}
            boxes={boxes}
            selectedKey={selectedKey}
            onSelect={select}
            onSpace={setSpace}
            onAttach={image.attach}
          />
          {file.tables.length > 0 && <TableGrid tables={file.tables} selectedKey={selectedKey} onSelect={select} edit={edit} />}
        </div>

        <aside className="review-side" aria-label="Review panel">
          <Inspector
            field={selectedEntry?.fileIndex === fileIndex ? selected : null}
            block={selectedBlock}
            src={image.src}
            space={space}
            saving={saving}
            error={actionError}
            onAccept={() => void act('accept')}
            onReject={() => void act('reject')}
            onEdit={() => startEdit()}
            onUseAlternative={(value) => void act('correct', value)}
          />
          <FieldList fields={file.fields} selectedKey={selectedKey} onSelect={select} edit={edit} />
          {file.textBlocks.length > 0 && (
            <section className="panel" aria-label="Extracted text">
              <div className="field-panel-head">
                <h2 className="section-title">
                  Extracted text <span className="pill pill-neutral">{file.textBlocks.length}</span>
                </h2>
              </div>
              <ol className="text-blocks">
                {blockOrder.map((block) => (
                  <li key={block.key}>
                    <button
                      type="button"
                      className={`text-block${block.key === selectedKey ? ' selected' : ''}`}
                      onClick={() => select(block.key)}
                    >
                      <span className="mono text-block-text">{block.text === '' ? <span className="muted">(empty)</span> : block.text}</span>
                      <span className="muted small">
                        {block.readingOrder !== null && <span>#{block.readingOrder} </span>}
                        {percent(block.confidence)}
                        {block.language !== null && ` · ${block.language}`}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            </section>
          )}
          <p className="shortcuts">
            <kbd>N</kbd>/<kbd>P</kbd> next / previous flagged · <kbd>A</kbd> accept · <kbd>E</kbd> edit · <kbd>R</kbd> reject ·{' '}
            <kbd>1</kbd>–<kbd>9</kbd> use alternative · <kbd>+</kbd>/<kbd>−</kbd>/<kbd>0</kbd> zoom
          </p>
        </aside>
      </div>
    </div>
  )
}

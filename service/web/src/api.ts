// The ONLY module that talks to the backend. Every request in the app goes through here.
//
// Endpoints used (Image Extraction Engine API v7.0.0, same origin; X-API-Key header is only
// required when the server sets IMAGE_ENGINE_API_KEY):
//   POST  /v1/jobs (multipart files; profile / category / languages / export_formats are
//          FastAPI Query parameters, so they ride the query string)   GET  /v1/jobs
//   GET   /v1/jobs/{job_id}                     GET  /v1/jobs/{job_id}/result
//   POST  /v1/jobs/{job_id}/cancel              GET  /v1/jobs/{job_id}/review
//   PATCH /v1/jobs/{job_id}/fields/{field_id}   POST /v1/jobs/{job_id}/exports
//   GET   /v1/jobs/{job_id}/exports/{fmt}       GET  /v1/profiles
//   GET   /v1/health                            GET  /v1/version

export const BASE = "/v1"

// Request/response key names that the endpoint list does not spell out. Traced against the
// real backend (service/api/app.py, engine/schema/models.py); if the contract changes, this
// is the one place to update.
const WIRE = {
  uploadFiles: 'files',
  uploadProfile: 'profile',
  uploadForcedCategory: 'category',
  uploadLanguages: 'languages',
  uploadExportFormats: 'export_formats',
  reviewCorrectedValue: 'value',
  exportFormats: 'formats',
  // How a 4-number bounding box array is read: [x0, y0, x1, y1] or [x, y, width, height].
  bboxArray: 'xyxy' as 'xyxy' | 'xywh',
}

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

export const EXPORT_FORMATS = ['xlsx', 'json', 'csv', 'pdf'] as const
export type ExportFormat = (typeof EXPORT_FORMATS)[number]

export type ReviewAction = 'accept' | 'correct' | 'reject'
export type ReviewState = 'accepted' | 'corrected' | 'rejected' | null

export interface JobFile {
  id: string
  name: string
  status: string
  error: string | null
}

export interface Job {
  id: string
  /** queued | processing | needs_review | completed | failed */
  status: string
  profile: string | null
  createdAt: string | null
  updatedAt: string | null
  /** 0..1, or null when the API does not report it */
  progress: number | null
  files: JobFile[]
  fileCount: number | null
  failedFileCount: number
  error: string | null
}

export interface BBox {
  x: number
  y: number
  w: number
  h: number
  /** true when coordinates are fractions of the image size (0..1) rather than pixels */
  normalized: boolean
}

export interface Alternative {
  value: string
  confidence: number | null
}

export interface Field {
  /** Unique within a result; used for selection in the UI. */
  key: string
  /** FIELD id used by PATCH /jobs/{job_id}/fields/{field_id}; null when the API gave none. */
  id: string | null
  fileId: string
  name: string
  value: string
  originalValue: string | null
  confidence: number | null
  needsReview: boolean
  reviewState: ReviewState
  bbox: BBox | null
  alternatives: Alternative[]
  reasons: string[]
  cell: { tableId: string; row: number; col: number } | null
}

export interface Table {
  id: string
  name: string
  headers: string[]
  rowCount: number
  colCount: number
  cells: Field[]
}

export interface ResultFile {
  id: string
  name: string
  status: string
  error: string | null
  category: string | null
  imageUrl: string | null
  width: number | null
  height: number | null
  fields: Field[]
  tables: Table[]
}

export interface ExtractionResult {
  jobId: string
  files: ResultFile[]
}

export interface Profile {
  id: string
  name: string
  description: string | null
  isDefault: boolean
  categories: string[]
  languages: string[]
}

export interface UploadOptions {
  profile: string | null
  forcedCategory: string | null
  languages: string[]
  exportFormats: ExportFormat[]
}

export class ApiError extends Error {
  readonly status: number
  readonly retryAfterMs: number | null

  constructor(status: number, message: string, retryAfterMs: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfterMs = retryAfterMs
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

/* ------------------------------------------------------------------ */
/* Rate limiting: the API allows 60 requests/minute. Every request     */
/* (polls, uploads, review actions, downloads) takes a slot here, so   */
/* one tab stays below the limit no matter how the views combine.      */
/* ------------------------------------------------------------------ */

const WINDOW_MS = 60_000
const MAX_REQUESTS_PER_WINDOW = 50
const sentAt: number[] = []
let gate: Promise<void> = Promise.resolve()

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

function acquireSlot(): Promise<void> {
  const turn = gate.then(async () => {
    for (;;) {
      const now = Date.now()
      while (sentAt.length > 0 && now - sentAt[0] >= WINDOW_MS) sentAt.shift()
      if (sentAt.length < MAX_REQUESTS_PER_WINDOW) {
        sentAt.push(now)
        return
      }
      await sleep(sentAt[0] + WINDOW_MS - now + 50)
    }
  })
  gate = turn
  return turn
}

/* ------------------------------------------------------------------ */
/* Transport                                                           */
/* ------------------------------------------------------------------ */

function detailToMessage(body: unknown): string | null {
  if (typeof body === 'string') return body.trim() || null
  if (!isRecord(body)) return null
  const detail = body.detail ?? body.message ?? body.error
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === 'string') return d
      if (isRecord(d)) {
        const where = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join('.') : ''
        const msg = typeof d.msg === 'string' ? d.msg : JSON.stringify(d)
        return where ? `${where}: ${msg}` : msg
      }
      return String(d)
    })
    return parts.join('; ') || null
  }
  if (isRecord(detail)) return text(detail, 'message', 'msg', 'detail') ?? JSON.stringify(detail)
  return null
}

function buildError(status: number, statusText: string, body: unknown, retryAfter: string | null): ApiError {
  const seconds = retryAfter ? Number(retryAfter) : NaN
  const retryAfterMs = Number.isFinite(seconds) ? seconds * 1000 : null
  const detail = detailToMessage(body)
  let message = detail ?? `Request failed (${status}${statusText ? ` ${statusText}` : ''}).`
  if (status === 429) message = 'Rate limit reached. Requests will resume automatically in a moment.'
  return new ApiError(status, message, retryAfterMs)
}

function parseBody(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return raw.trimStart().startsWith('<') ? null : raw
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  await acquireSlot()
  let res: Response
  try {
    res = await fetch(BASE + path, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'Cannot reach the API. Check that the server is running.')
  }
  if (!res.ok) {
    const raw = await res.text().catch(() => '')
    throw buildError(res.status, res.statusText, parseBody(raw), res.headers.get('Retry-After'))
  }
  return res
}

async function requestJson(path: string, init: RequestInit = {}): Promise<unknown> {
  const res = await request(path, { ...init, headers: { Accept: 'application/json', ...init.headers } })
  if (res.status === 204) return null
  const raw = await res.text()
  if (raw === '') return null
  const type = res.headers.get('Content-Type') ?? ''
  if (!type.includes('json')) {
    throw new ApiError(res.status, `${BASE}${path} did not return JSON (got "${type || 'no content type'}").`)
  }
  return JSON.parse(raw)
}

function jsonBody(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

const seg = encodeURIComponent

/* ------------------------------------------------------------------ */
/* Tolerant readers for response JSON                                  */
/* ------------------------------------------------------------------ */

type Rec = Record<string, unknown>

function isRecord(value: unknown): value is Rec {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function text(obj: Rec, ...keys: string[]): string | null {
  for (const key of keys) {
    const v = obj[key]
    if (typeof v === 'string' && v !== '') return v
    if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  }
  return null
}

function number(obj: Rec, ...keys: string[]): number | null {
  for (const key of keys) {
    const v = obj[key]
    if (typeof v === 'number' && Number.isFinite(v)) return v
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
  }
  return null
}

function flag(obj: Rec, ...keys: string[]): boolean {
  return keys.some((key) => obj[key] === true)
}

function list(obj: unknown, ...keys: string[]): unknown[] {
  if (Array.isArray(obj)) return obj
  if (!isRecord(obj)) return []
  for (const key of keys) {
    const v = obj[key]
    if (Array.isArray(v)) return v
  }
  return []
}

function strings(values: unknown[]): string[] {
  return values.filter((v): v is string => typeof v === 'string' && v !== '')
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function errorText(obj: Rec): string | null {
  for (const key of ['error', 'error_message', 'failure_reason', 'error_detail']) {
    const v = obj[key]
    if (typeof v === 'string' && v !== '') return v
    if (isRecord(v)) return text(v, 'message', 'detail', 'msg', 'code') ?? JSON.stringify(v)
  }
  return null
}

function unitInterval(value: number | null): number | null {
  if (value === null) return null
  const scaled = value > 1 ? value / 100 : value
  return Math.min(1, Math.max(0, scaled))
}

/* ------------------------------------------------------------------ */
/* Normalizers                                                         */
/* ------------------------------------------------------------------ */

export function isFailedStatus(status: string): boolean {
  return /fail|error/i.test(status)
}

export function isActiveStatus(status: string): boolean {
  return status === 'queued' || status === 'processing'
}

function normalizeJobFile(raw: unknown, index: number): JobFile {
  if (typeof raw === 'string') return { id: String(index), name: raw, status: '', error: null }
  const obj = isRecord(raw) ? raw : {}
  const name = text(obj, 'filename', 'file_name', 'original_filename', 'name') ?? `File ${index + 1}`
  return {
    id: text(obj, 'file_id', 'id') ?? String(index),
    name,
    status: text(obj, 'status', 'state') ?? '',
    error: errorText(obj),
  }
}

function normalizeProgress(obj: Rec): number | null {
  const raw = obj.progress
  if (isRecord(raw)) {
    const direct = number(raw, 'percent', 'percentage', 'fraction', 'value')
    if (direct !== null) return unitInterval(direct)
    const done = number(raw, 'processed', 'completed', 'done', 'current', 'processed_files')
    const total = number(raw, 'total', 'total_files')
    if (done !== null && total !== null && total > 0) return Math.min(1, done / total)
    return null
  }
  const direct = number(obj, 'progress', 'progress_percent', 'percent')
  if (direct !== null) return unitInterval(direct)
  const done = number(obj, 'processed_files', 'files_processed', 'completed_files')
  const total = number(obj, 'total_files', 'file_count', 'files_total')
  if (done !== null && total !== null && total > 0) return Math.min(1, done / total)
  return null
}

function looksLikeJob(raw: unknown): raw is Rec {
  return isRecord(raw) && text(raw, 'job_id', 'id') !== null && text(raw, 'status', 'state') !== null
}

function normalizeJob(raw: unknown): Job {
  const obj = isRecord(raw) && isRecord(raw.job) ? raw.job : isRecord(raw) ? raw : {}
  const id = text(obj, 'job_id', 'id')
  if (id === null) throw new ApiError(0, 'The API returned a job without an id.')
  const files = list(obj.files ?? obj.documents ?? [], 'items').map(normalizeJobFile)
  const failedInFiles = files.filter((f) => isFailedStatus(f.status) || f.error !== null).length
  const failedCount = number(obj, 'failed_files', 'failed_count', 'files_failed') ?? 0
  return {
    id,
    status: text(obj, 'status', 'state') ?? 'queued',
    profile: text(obj, 'profile', 'profile_id', 'profile_name'),
    createdAt: text(obj, 'created_at', 'created', 'submitted_at'),
    updatedAt: text(obj, 'updated_at', 'finished_at', 'completed_at', 'updated'),
    progress: normalizeProgress(obj),
    files,
    fileCount: files.length > 0 ? files.length : number(obj, 'file_count', 'total_files', 'files_total'),
    failedFileCount: Math.max(failedInFiles, failedCount),
    error: errorText(obj),
  }
}

function normalizeBBox(raw: unknown): BBox | null {
  let x: number, y: number, w: number, h: number

  if (Array.isArray(raw) && raw.length > 0 && raw.every((p) => Array.isArray(p) || isRecord(p))) {
    const points = raw
      .map((p) => (Array.isArray(p) ? [p[0], p[1]] : [(p as Rec).x, (p as Rec).y]))
      .filter((p): p is [number, number] => typeof p[0] === 'number' && typeof p[1] === 'number')
    if (points.length < 2) return null
    const xs = points.map((p) => p[0])
    const ys = points.map((p) => p[1])
    x = Math.min(...xs)
    y = Math.min(...ys)
    w = Math.max(...xs) - x
    h = Math.max(...ys) - y
  } else if (Array.isArray(raw) && raw.length === 4 && raw.every((n) => typeof n === 'number')) {
    const [a, b, c, d] = raw as number[]
    x = a
    y = b
    w = WIRE.bboxArray === 'xyxy' ? c - a : c
    h = WIRE.bboxArray === 'xyxy' ? d - b : d
  } else if (isRecord(raw)) {
    const left = number(raw, 'x', 'left', 'x0', 'x1', 'x_min', 'xmin')
    const top = number(raw, 'y', 'top', 'y0', 'y1', 'y_min', 'ymin')
    if (left === null || top === null) return null
    const width = number(raw, 'width', 'w')
    const height = number(raw, 'height', 'h')
    const right = raw.x0 !== undefined ? number(raw, 'x1') : number(raw, 'x2', 'right', 'x_max', 'xmax')
    const bottom = raw.y0 !== undefined ? number(raw, 'y1') : number(raw, 'y2', 'bottom', 'y_max', 'ymax')
    x = left
    y = top
    if (width !== null && height !== null) {
      w = width
      h = height
    } else if (right !== null && bottom !== null) {
      w = right - left
      h = bottom - top
    } else {
      return null
    }
  } else {
    return null
  }

  if (!(w > 0) || !(h > 0)) return null
  const normalized = x >= 0 && y >= 0 && x + w <= 1.0001 && y + h <= 1.0001
  return { x, y, w, h, normalized }
}

function normalizeReviewState(obj: Rec): ReviewState {
  const raw = (text(obj, 'review_status', 'review_state', 'review_action', 'reviewed_action') ?? '').toLowerCase()
  if (raw.startsWith('accept')) return 'accepted'
  if (raw.startsWith('correct')) return 'corrected'
  if (raw.startsWith('reject')) return 'rejected'
  return null
}

function normalizeAlternatives(obj: Rec): Alternative[] {
  // engine/schema FieldValue calls them "proposals" (plain strings); accept richer
  // {value|text|candidate, confidence} shapes too.
  return list(obj, 'proposals', 'alternatives', 'ocr_alternatives', 'candidates')
    .map((alt): Alternative | null => {
      if (typeof alt === 'string' || typeof alt === 'number') return { value: String(alt), confidence: null }
      if (!isRecord(alt)) return null
      const value = alt.value ?? alt.text ?? alt.candidate
      if (value === undefined || value === null) return null
      return { value: displayValue(value), confidence: unitInterval(number(alt, 'confidence', 'score', 'conf')) }
    })
    .filter((alt): alt is Alternative => alt !== null)
}

function normalizeReasons(obj: Rec): string[] {
  const many = list(obj, 'reasons', 'review_reasons', 'flags').map((r) =>
    typeof r === 'string' ? r : isRecord(r) ? (text(r, 'message', 'reason', 'code') ?? '') : '',
  )
  const single = text(obj, 'reason', 'review_reason')
  return [...strings(many), ...(single ? [single] : [])]
}

function normalizeField(raw: unknown, fileId: string, key: string, fallbackName: string): Field {
  const obj = isRecord(raw) ? raw : { value: raw }
  const reviewState = normalizeReviewState(obj)
  return {
    key,
    id: text(obj, 'field_id', 'id'),
    fileId: text(obj, 'file_id') ?? fileId,
    name: text(obj, 'label', 'name', 'key', 'field_name') ?? fallbackName,
    value: displayValue(obj.value ?? obj.text),
    originalValue: obj.original_value !== undefined ? displayValue(obj.original_value) : text(obj, 'raw_text', 'raw_value', 'ocr_value'),
    confidence: unitInterval(number(obj, 'confidence', 'score', 'conf')),
    needsReview: flag(obj, 'needs_review', 'flagged', 'requires_review') && reviewState === null,
    reviewState,
    bbox: normalizeBBox(obj.bbox ?? obj.bounding_box ?? obj.box ?? obj.polygon),
    alternatives: normalizeAlternatives(obj),
    reasons: normalizeReasons(obj),
    cell: null,
  }
}

function normalizeTable(raw: unknown, fileId: string, index: number): Table {
  const obj = isRecord(raw) ? raw : {}
  // engine/schema Table: table_name, columns, rows, cells[] with row_index / col_index.
  const tableId = text(obj, 'table_id', 'id') ?? `table-${index}`
  const name = text(obj, 'table_name', 'name', 'label', 'title') ?? `Table ${index + 1}`
  const headers = list(obj, 'columns', 'headers').map((h) =>
    typeof h === 'string' ? h : isRecord(h) ? (text(h, 'label', 'name', 'key') ?? '') : displayValue(h),
  )
  const cells: Field[] = []
  const push = (cellRaw: unknown, row: number, col: number) => {
    const key = `${fileId}/${tableId}/r${row}c${col}`
    const cell = normalizeField(cellRaw, fileId, key, `${headers[col] || `Column ${col + 1}`}, row ${row + 1}`)
    cell.cell = { tableId, row, col }
    cells.push(cell)
  }

  const flat = list(obj, 'cells')
  if (flat.length > 0) {
    for (const cellRaw of flat) {
      const c = isRecord(cellRaw) ? cellRaw : {}
      push(cellRaw, number(c, 'row_index', 'row') ?? 0, number(c, 'col_index', 'col', 'column', 'column_index') ?? 0)
    }
  } else {
    list(obj, 'rows').forEach((rowRaw, row) => {
      list(rowRaw, 'cells').forEach((cellRaw, col) => push(cellRaw, row, col))
    })
  }

  return {
    id: tableId,
    name,
    headers,
    rowCount: cells.reduce((max, c) => Math.max(max, (c.cell?.row ?? 0) + 1), 0),
    colCount: Math.max(headers.length, cells.reduce((max, c) => Math.max(max, (c.cell?.col ?? 0) + 1), 0)),
    cells,
  }
}

function fieldEntries(raw: unknown): { raw: unknown; name: string }[] {
  if (Array.isArray(raw)) return raw.map((item, i) => ({ raw: item, name: `Field ${i + 1}` }))
  if (isRecord(raw)) return Object.entries(raw).map(([name, item]) => ({ raw: item, name }))
  return []
}

function imageReference(obj: Rec): string | null {
  const ref = text(obj, 'image_url', 'preview_url', 'source_url', 'image')
  if (ref === null) return null
  return /^(data:image\/|https?:\/\/|\/)/.test(ref) ? ref : null
}

function normalizeResultFile(raw: unknown, index: number): ResultFile {
  const obj = isRecord(raw) ? raw : {}
  // GET /v1/jobs/{id}/result wraps each file: {file_id, file_name, status, result: {...}} —
  // the extraction payload (fields / tables / document_type / page sizes) sits one level down.
  const inner = isRecord(obj.result) ? obj.result : {}
  const id = text(obj, 'file_id', 'id') ?? String(index)
  const pageRaw = list(inner, 'pages')[0]
  const pageRec = isRecord(pageRaw) ? pageRaw : {}
  const tablesRaw = list(obj, 'tables').length > 0 ? list(obj, 'tables') : list(inner, 'tables')
  return {
    id,
    name: text(obj, 'filename', 'file_name', 'original_filename', 'name') ?? `File ${index + 1}`,
    status: text(obj, 'status', 'state') ?? '',
    error: errorText(obj),
    category: text(obj, 'category', 'document_type', 'detected_category') ?? text(inner, 'document_type'),
    imageUrl: imageReference(obj) ?? imageReference(inner),
    width: number(obj, 'width', 'image_width', 'page_width') ?? number(pageRec, 'width_px', 'width'),
    height: number(obj, 'height', 'image_height', 'page_height') ?? number(pageRec, 'height_px', 'height'),
    fields: fieldEntries(obj.fields ?? inner.fields).map((entry, i) =>
      normalizeField(entry.raw, id, `${id}/f${i}`, entry.name),
    ),
    tables: tablesRaw.map((t, i) => normalizeTable(t, id, i)),
  }
}

function normalizeResult(raw: unknown, jobId: string): ExtractionResult {
  const root = isRecord(raw) && isRecord(raw.result) ? raw.result : raw
  let fileRaws = list(root, 'files', 'documents', 'results', 'items')
  const rootHasFields = isRecord(root) && (root.fields !== undefined || root.tables !== undefined)
  if (fileRaws.length === 0 && rootHasFields) fileRaws = [root]
  const files = fileRaws.map(normalizeResultFile)

  // Some APIs return a flat top-level field list where each field names its file.
  if (fileRaws.length > 0 && fileRaws[0] !== root && isRecord(root) && Array.isArray(root.fields)) {
    root.fields.forEach((fieldRaw, i) => {
      const field = normalizeField(fieldRaw, files[0].id, `root/f${i}`, `Field ${i + 1}`)
      const owner = files.find((f) => f.id === field.fileId) ?? files[0]
      owner.fields.push({ ...field, fileId: owner.id })
    })
  }
  return { jobId, files }
}

export function allItems(file: ResultFile): Field[] {
  return [...file.fields, ...file.tables.flatMap((t) => t.cells)]
}

export function isPending(field: Field): boolean {
  return field.needsReview && field.reviewState === null
}

/**
 * Folds GET /jobs/{id}/review into the result: every pending item is marked as flagged on the
 * matching field (by FIELD id) and contributes alternatives / reasons / boxes the result lacks.
 */
function mergeReview(result: ExtractionResult, reviewRaw: unknown): ExtractionResult {
  const items = list(reviewRaw, 'items', 'fields', 'pending', 'review_items')
  if (items.length === 0) return result

  const byId = new Map<string, Field>()
  for (const file of result.files) for (const item of allItems(file)) if (item.id) byId.set(item.id, item)

  items.forEach((itemRaw, i) => {
    const wrapper = isRecord(itemRaw) ? itemRaw : {}
    const fieldRaw = isRecord(wrapper.field) ? { ...wrapper, ...wrapper.field } : wrapper
    const incoming = normalizeField(fieldRaw, text(wrapper, 'file_id') ?? '', `review/${i}`, `Flagged item ${i + 1}`)
    const existing = incoming.id ? byId.get(incoming.id) : undefined
    if (existing) {
      existing.needsReview = true
      existing.reviewState = null
      if (existing.alternatives.length === 0) existing.alternatives = incoming.alternatives
      if (existing.reasons.length === 0) existing.reasons = incoming.reasons
      if (existing.bbox === null) existing.bbox = incoming.bbox
      if (existing.confidence === null) existing.confidence = incoming.confidence
      return
    }
    if (result.files.length === 0) {
      result.files.push({
        id: incoming.fileId || 'file',
        name: 'File 1',
        status: '',
        error: null,
        category: null,
        imageUrl: null,
        width: null,
        height: null,
        fields: [],
        tables: [],
      })
    }
    const owner = result.files.find((f) => f.id === incoming.fileId) ?? result.files[0]
    owner.fields.push({ ...incoming, fileId: owner.id, needsReview: true, reviewState: null })
  })
  return result
}

function normalizeProfile(raw: unknown): Profile | null {
  if (typeof raw === 'string') {
    return { id: raw, name: raw, description: null, isDefault: false, categories: [], languages: [] }
  }
  if (!isRecord(raw)) return null
  const id = text(raw, 'id', 'profile_id', 'key', 'name')
  if (id === null) return null
  return {
    id,
    name: text(raw, 'display_name', 'label', 'title', 'name') ?? id,
    description: text(raw, 'description', 'summary'),
    isDefault: flag(raw, 'default', 'is_default'),
    categories: strings(list(raw, 'categories')),
    languages: strings(list(raw, 'languages', 'default_languages')),
  }
}

/* ------------------------------------------------------------------ */
/* Endpoints                                                           */
/* ------------------------------------------------------------------ */

/** GET /v1/jobs — newest first (order preserved from the API). */
export async function listJobs(signal?: AbortSignal): Promise<Job[]> {
  const raw = await requestJson('/jobs', { signal })
  return list(raw, 'jobs', 'items', 'results').filter(looksLikeJob).map(normalizeJob)
}

/** GET /v1/jobs/{job_id} */
export async function getJob(jobId: string, signal?: AbortSignal): Promise<Job> {
  return normalizeJob(await requestJson(`/jobs/${seg(jobId)}`, { signal }))
}

/** POST /v1/jobs/{job_id}/cancel */
export async function cancelJob(jobId: string): Promise<Job | null> {
  const raw = await requestJson(`/jobs/${seg(jobId)}/cancel`, { method: 'POST' })
  const candidate = isRecord(raw) && isRecord(raw.job) ? raw.job : raw
  return looksLikeJob(candidate) ? normalizeJob(candidate) : null
}

/** GET /v1/jobs/{job_id}/result */
export async function getResult(jobId: string, signal?: AbortSignal): Promise<ExtractionResult> {
  return normalizeResult(await requestJson(`/jobs/${seg(jobId)}/result`, { signal }), jobId)
}

/** GET /v1/jobs/{job_id}/result + GET /v1/jobs/{job_id}/review, merged for the review screen. */
export async function getReviewData(jobId: string, signal?: AbortSignal): Promise<ExtractionResult> {
  const [resultRaw, reviewRaw] = await Promise.all([
    requestJson(`/jobs/${seg(jobId)}/result`, { signal }),
    requestJson(`/jobs/${seg(jobId)}/review`, { signal }),
  ])
  return mergeReview(normalizeResult(resultRaw, jobId), reviewRaw)
}

/** PATCH /v1/jobs/{job_id}/fields/{field_id} — field_id is the FIELD id, never a file id. */
export async function reviewField(
  jobId: string,
  fieldId: string,
  action: ReviewAction,
  correctedValue?: string,
): Promise<void> {
  const body: Rec = { action }
  if (action === 'correct') body[WIRE.reviewCorrectedValue] = correctedValue ?? ''
  await requestJson(`/jobs/${seg(jobId)}/fields/${seg(fieldId)}`, jsonBody('PATCH', body))
}

/** POST /v1/jobs/{job_id}/exports — asks the backend to generate export files (202). */
export async function requestExports(jobId: string, formats: ExportFormat[]): Promise<void> {
  await requestJson(`/jobs/${seg(jobId)}/exports`, jsonBody('POST', { [WIRE.exportFormats]: formats }))
}

/** GET /v1/jobs/{job_id}/exports/{fmt} — one file for the whole job. */
export async function downloadExport(jobId: string, fmt: ExportFormat): Promise<{ blob: Blob; filename: string }> {
  const res = await request(`/jobs/${seg(jobId)}/exports/${seg(fmt)}`)
  const type = res.headers.get('Content-Type') ?? ''
  if (type.includes('text/html')) {
    throw new ApiError(res.status, 'The server returned a web page instead of the export file.')
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const encoded = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(disposition)?.[1]
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition)?.[1]
  let filename = plain?.trim() ?? `job-${jobId}.${fmt}`
  if (encoded) {
    try {
      filename = decodeURIComponent(encoded.trim().replace(/^"|"$/g, ''))
    } catch {
      /* keep the plain filename */
    }
  }
  return { blob: await res.blob(), filename }
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** GET /v1/profiles — {profiles: [{name, category}], default: "<name>"} (service/api/app.py). */
export async function listProfiles(signal?: AbortSignal): Promise<Profile[]> {
  const raw = await requestJson('/profiles', { signal })
  const defaultName = isRecord(raw) ? (text(raw, 'default', 'default_profile') ?? '') : ''
  return list(raw, 'profiles', 'items', 'results')
    .map((p) => {
      const profile = normalizeProfile(p)
      if (profile && defaultName && profile.id === defaultName) profile.isDefault = true
      return profile
    })
    .filter((p): p is Profile => p !== null)
}

/** GET /v1/health */
export async function getHealth(signal?: AbortSignal): Promise<{ ok: boolean; status: string }> {
  const raw = await requestJson('/health', { signal })
  const status = (isRecord(raw) ? text(raw, 'status', 'state') : typeof raw === 'string' ? raw : null) ?? 'ok'
  return { ok: /^(ok|healthy|up|pass|alive|ready)$/i.test(status), status }
}

/** GET /v1/version — {engine: "7.0.0", ...} (service/api/app.py). */
export async function getVersion(signal?: AbortSignal): Promise<string> {
  const raw = await requestJson('/version', { signal })
  if (typeof raw === 'string') return raw
  return (isRecord(raw) ? text(raw, 'engine', 'version', 'api_version', 'app_version') : null) ?? 'unknown'
}

/**
 * POST /v1/jobs — multipart/form-data with one or more image files. One request
 * creates ONE job for the whole batch. Uses XMLHttpRequest because fetch cannot report upload
 * progress. The options (profile, category, languages, export_formats) are FastAPI Query
 * parameters on the backend, so they ride the query string, not the form body.
 */
export function createJob(
  files: File[],
  options: UploadOptions,
  onProgress?: (loadedBytes: number, totalBytes: number) => void,
  signal?: AbortSignal,
): Promise<Job> {
  const form = new FormData()
  for (const file of files) form.append(WIRE.uploadFiles, file, file.name)
  const params = new URLSearchParams()
  if (options.profile) params.set(WIRE.uploadProfile, options.profile)
  if (options.forcedCategory) params.set(WIRE.uploadForcedCategory, options.forcedCategory)
  if (options.languages.length > 0) params.set(WIRE.uploadLanguages, options.languages.join(','))
  if (options.exportFormats.length > 0) params.set(WIRE.uploadExportFormats, options.exportFormats.join(','))
  const qs = params.toString()

  return acquireSlot().then(
    () =>
      new Promise<Job>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${BASE}/jobs${qs ? `?${qs}` : ''}`)
        xhr.setRequestHeader('Accept', 'application/json')
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress?.(event.loaded, event.total)
        }
        xhr.onload = () => {
          const body = parseBody(xhr.responseText)
          if (xhr.status < 200 || xhr.status >= 300) {
            reject(buildError(xhr.status, xhr.statusText, body, xhr.getResponseHeader('Retry-After')))
            return
          }
          try {
            resolve(normalizeJob(body))
          } catch (error) {
            reject(error)
          }
        }
        xhr.onerror = () => reject(new ApiError(0, 'Upload failed: cannot reach the API.'))
        xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
        if (signal) {
          if (signal.aborted) {
            reject(new DOMException('Upload cancelled', 'AbortError'))
            return
          }
          signal.addEventListener('abort', () => xhr.abort(), { once: true })
        }
        xhr.send(form)
      }),
  )
}

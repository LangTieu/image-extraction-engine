import { isFailedStatus, type Job } from './api'

export type Tone = 'neutral' | 'info' | 'warn' | 'ok' | 'bad'

export interface Described {
  label: string
  tone: Tone
}

export function humanize(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ').trim()
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : ''
}

/** A job with failed files is never presented as plainly "Completed". */
export function describeJob(job: Job): Described {
  const hasFailedFiles = job.failedFileCount > 0
  switch (job.status) {
    case 'queued':
      return { label: 'Queued', tone: 'neutral' }
    case 'processing':
      return { label: 'Processing', tone: 'info' }
    case 'needs_review':
      return hasFailedFiles
        ? { label: 'Needs review, with file errors', tone: 'bad' }
        : { label: 'Needs review', tone: 'warn' }
    case 'completed':
      return hasFailedFiles ? { label: 'Completed with errors', tone: 'bad' } : { label: 'Completed', tone: 'ok' }
    case 'failed':
      return { label: 'Failed', tone: 'bad' }
    default:
      return { label: humanize(job.status) || 'Unknown', tone: 'neutral' }
  }
}

export function describeFile(status: string, error: string | null): Described {
  if (error !== null || isFailedStatus(status)) return { label: 'Failed', tone: 'bad' }
  switch (status) {
    case '':
      return { label: 'No status', tone: 'neutral' }
    case 'queued':
    case 'pending':
      return { label: 'Queued', tone: 'neutral' }
    case 'processing':
      return { label: 'Processing', tone: 'info' }
    case 'needs_review':
      return { label: 'Needs review', tone: 'warn' }
    case 'completed':
    case 'done':
    case 'success':
      return { label: 'Completed', tone: 'ok' }
    default:
      return { label: humanize(status), tone: 'neutral' }
  }
}

export function jobTitle(job: Job): string {
  if (job.files.length === 0) return `Job ${shortId(job.id)}`
  const extra = job.files.length - 1
  return extra > 0 ? `${job.files[0].name} +${extra} more` : job.files[0].name
}

export function shortId(id: string): string {
  return id.length > 12 ? id.slice(0, 8) : id
}

export function fileCountLabel(count: number | null): string {
  if (count === null) return 'Files not listed'
  return count === 1 ? '1 file' : `${count} files`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return 'Unknown'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`
  return date.toLocaleDateString(undefined, { dateStyle: 'medium' })
}

export function percent(value: number | null): string {
  return value === null ? 'n/a' : `${Math.round(value * 100)}%`
}

export function confidenceTone(value: number | null): Tone {
  if (value === null) return 'neutral'
  if (value < 0.6) return 'bad'
  if (value < 0.85) return 'warn'
  return 'ok'
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

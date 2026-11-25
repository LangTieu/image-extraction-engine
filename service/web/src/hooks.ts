import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { ApiError, type ResultFile } from './api'
import { loadSourceImage, rememberSourceImage } from './imageStore'

/* ------------------------------------------------------------------ */
/* Polling                                                             */
/* ------------------------------------------------------------------ */

export type Interval<T> = number | null | ((data: T) => number | null)

export interface PollState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  refresh: () => void
  setData: (data: T) => void
}

const RATE_LIMIT_BACKOFF_MS = 15_000
const TRANSIENT_RETRY_MS = 5_000

/**
 * Loads `fetcher` when `key` is set and repeats it every `interval` ms. The next request is
 * only scheduled after the previous one settled, polling stops while the tab is hidden, and a
 * 429 backs off for Retry-After (or 15 s). An interval of null means "load once".
 */
export function usePolling<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
  interval: Interval<T>,
  paused = false,
): PollState<T> {
  const [state, setState] = useState<{ key: string | null; data: T | null; error: Error | null }>({
    key: null,
    data: null,
    error: null,
  })
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)
  const intervalRef = useRef(interval)

  useEffect(() => {
    fetcherRef.current = fetcher
    intervalRef.current = interval
  })

  useEffect(() => {
    if (key === null || paused) return
    const controller = new AbortController()
    let timer: number | undefined
    let stopped = false
    let waitingForVisibility = false

    const tick = async () => {
      if (document.hidden) {
        waitingForVisibility = true
        return
      }
      let delay: number | null
      try {
        const data = await fetcherRef.current(controller.signal)
        if (stopped) return
        setState({ key, data, error: null })
        const iv = intervalRef.current
        delay = typeof iv === 'function' ? iv(data) : iv
      } catch (caught) {
        if (stopped) return
        const error = caught instanceof Error ? caught : new Error(String(caught))
        setState((prev) => ({ key, data: prev.key === key ? prev.data : null, error }))
        const status = error instanceof ApiError ? error.status : 0
        const iv = intervalRef.current
        if (status === 429) {
          delay = Math.max(error instanceof ApiError ? (error.retryAfterMs ?? 0) : 0, RATE_LIMIT_BACKOFF_MS)
        } else if (typeof iv === 'number') {
          delay = iv
        } else if (iv !== null && (status === 0 || status >= 500)) {
          delay = TRANSIENT_RETRY_MS
        } else {
          delay = null
        }
      }
      if (delay !== null) timer = window.setTimeout(tick, delay)
    }

    const onVisibilityChange = () => {
      if (!document.hidden && waitingForVisibility) {
        waitingForVisibility = false
        void tick()
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    void tick()
    return () => {
      stopped = true
      controller.abort()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [key, paused, nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  const setData = useCallback((data: T) => setState({ key, data, error: null }), [key])

  const current = state.key === key
  const data = current ? state.data : null
  const error = current ? state.error : null
  return { data, error, loading: key !== null && data === null && error === null, refresh, setData }
}

/* ------------------------------------------------------------------ */
/* Client-side views (hash based, no routing library)                  */
/* ------------------------------------------------------------------ */

export type Route = { view: 'upload' } | { view: 'jobs' | 'review' | 'results'; jobId: string | null }

function parseRoute(hash: string): Route {
  const [view, rawId] = hash.replace(/^#\/?/, '').split('/')
  let jobId: string | null = null
  if (rawId) {
    try {
      jobId = decodeURIComponent(rawId)
    } catch {
      jobId = rawId
    }
  }
  if (view === 'jobs' || view === 'review' || view === 'results') return { view, jobId }
  return { view: 'upload' }
}

export function routeHref(route: Route): string {
  if (route.view === 'upload') return '#/upload'
  return `#/${route.view}${route.jobId ? `/${encodeURIComponent(route.jobId)}` : ''}`
}

function subscribeToHash(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribeToHash, () => window.location.hash)
  return useMemo(() => parseRoute(hash), [hash])
}

/* ------------------------------------------------------------------ */
/* Source image for the review screen                                  */
/* ------------------------------------------------------------------ */

export interface SourceImage {
  src: string | null
  searching: boolean
  attach: (file: File) => void
}

/**
 * The endpoint list has no route that serves the uploaded image, so the review screen uses, in
 * order: an image reference inside the result JSON, the copy kept in this browser at upload
 * time, or a file the reviewer picks from disk.
 */
export function useSourceImage(jobId: string, file: ResultFile | null): SourceImage {
  const [local, setLocal] = useState<{ id: string; url: string | null } | null>(null)
  const fileName = file?.name ?? null
  const remote = file?.imageUrl ?? null
  const id = fileName === null ? null : `${jobId}::${fileName}`

  useEffect(() => {
    if (id === null || fileName === null || remote !== null) return
    let cancelled = false
    void loadSourceImage(jobId, fileName).then((url) => {
      if (!cancelled) setLocal({ id, url })
    })
    return () => {
      cancelled = true
    }
  }, [id, jobId, fileName, remote])

  const attach = useCallback(
    (picked: File) => {
      if (id === null || fileName === null) return
      void rememberSourceImage(jobId, fileName, picked).then((url) => setLocal({ id, url }))
    },
    [id, jobId, fileName],
  )

  const localCurrent = local !== null && local.id === id
  return {
    src: remote ?? (localCurrent ? local.url : null),
    searching: id !== null && remote === null && !localCurrent,
    attach,
  }
}

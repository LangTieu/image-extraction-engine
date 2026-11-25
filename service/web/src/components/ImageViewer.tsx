import { useEffect, useRef, useState } from 'react'
import type { BBox } from '../api'
import { isTypingTarget } from '../util'

export interface Size {
  w: number
  h: number
}

export interface OverlayBox {
  key: string
  bbox: BBox
  tone: 'plain' | 'pending' | 'ok' | 'rejected' | 'block'
  label: string
}

type Zoom = 'fit' | number

const MIN_SCALE = 0.05
const MAX_SCALE = 8
const STAGE_PADDING = 16
const FALLBACK_SIZE: Size = { w: 1000, h: 1414 }

const clampScale = (scale: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale))

export function toPixels(bbox: BBox, space: Size): { x: number; y: number; w: number; h: number } {
  if (!bbox.normalized) return { x: bbox.x, y: bbox.y, w: bbox.w, h: bbox.h }
  return { x: bbox.x * space.w, y: bbox.y * space.h, w: bbox.w * space.w, h: bbox.h * space.h }
}

export function ImageViewer({
  src,
  searching,
  fileName,
  declaredSize,
  boxes,
  selectedKey,
  onSelect,
  onSpace,
  onAttach,
}: {
  src: string | null
  searching: boolean
  fileName: string
  /** Size of the coordinate space the bounding boxes use, when the API reports it. */
  declaredSize: Size | null
  boxes: OverlayBox[]
  selectedKey: string | null
  onSelect: (key: string) => void
  onSpace: (space: Size | null) => void
  onAttach: (file: File) => void
}) {
  const [loaded, setLoaded] = useState<(Size & { src: string }) | null>(null)
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const [zoom, setZoom] = useState<Zoom>('fit')
  const [viewportWidth, setViewportWidth] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)

  const natural = loaded !== null && loaded.src === src ? loaded : null
  const space = natural ? (declaredSize ?? natural) : null
  const fitScale = natural && viewportWidth > 0 ? clampScale((viewportWidth - STAGE_PADDING * 2) / natural.w) : 1
  const scale = zoom === 'fit' ? fitScale : zoom
  const failed = src !== null && failedSrc === src

  const latest = useRef({ fitScale, scale, space, natural, boxes })
  useEffect(() => {
    latest.current = { fitScale, scale, space, natural, boxes }
  })

  const spaceW = space?.w ?? null
  const spaceH = space?.h ?? null
  useEffect(() => {
    onSpace(spaceW !== null && spaceH !== null ? { w: spaceW, h: spaceH } : null)
  }, [spaceW, spaceH, onSpace])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const observer = new ResizeObserver(() => setViewportWidth(el.clientWidth))
    observer.observe(el)
    setViewportWidth(el.clientWidth)
    return () => observer.disconnect()
  }, [])

  const step = (factor: number) => setZoom((z) => clampScale((z === 'fit' ? latest.current.fitScale : z) * factor))

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      step(event.deltaY < 0 ? 1.1 : 1 / 1.1)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return
      if (event.key === '+' || event.key === '=') step(1.25)
      else if (event.key === '-') step(0.8)
      else if (event.key === '0') setZoom('fit')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Keep the selected field's box in view.
  const ready = natural !== null
  useEffect(() => {
    const el = scrollRef.current
    const canvas = canvasRef.current
    const { scale: s, space: sp, natural: nat, boxes: all } = latest.current
    if (!el || !canvas || !sp || !nat || selectedKey === null) return
    const box = all.find((b) => b.key === selectedKey)
    if (!box) return
    const px = toPixels(box.bbox, sp)
    const centerX = (px.x + px.w / 2) * (nat.w / sp.w) * s
    const centerY = (px.y + px.h / 2) * (nat.h / sp.h) * s
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollTo({
      left: canvas.offsetLeft + centerX - el.clientWidth / 2,
      top: canvas.offsetTop + centerY - el.clientHeight / 2,
      behavior: reduceMotion ? 'auto' : 'smooth',
    })
  }, [selectedKey, ready])

  const ordered = [...boxes].sort((a, b) => b.bbox.w * b.bbox.h - a.bbox.w * a.bbox.h)

  return (
    <div className="viewer">
      <div className="viewer-toolbar" role="toolbar" aria-label="Image zoom">
        <button type="button" className="btn btn-small" onClick={() => step(0.8)} disabled={!natural} aria-label="Zoom out">
          −
        </button>
        <span className="viewer-zoom" aria-live="off">
          {natural ? `${Math.round(scale * 100)}%` : ''}
        </span>
        <button type="button" className="btn btn-small" onClick={() => step(1.25)} disabled={!natural} aria-label="Zoom in">
          +
        </button>
        <button type="button" className="btn btn-small" onClick={() => setZoom('fit')} disabled={!natural} aria-pressed={zoom === 'fit'}>
          Fit width
        </button>
        <button type="button" className="btn btn-small" onClick={() => setZoom(1)} disabled={!natural} aria-pressed={zoom === 1}>
          100%
        </button>
        <span className="viewer-name muted small">{fileName}</span>
      </div>

      <div className="viewer-scroll" ref={scrollRef}>
        {src !== null && !failed ? (
          <div
            className="viewer-canvas"
            ref={canvasRef}
            style={natural ? { width: natural.w * scale, height: natural.h * scale } : { visibility: 'hidden', width: 1, height: 1 }}
          >
            <img
              src={src}
              alt={`Source image ${fileName}`}
              draggable={false}
              onLoad={(event) => {
                const img = event.currentTarget
                const fallback = declaredSize ?? FALLBACK_SIZE
                setLoaded({ src, w: img.naturalWidth || fallback.w, h: img.naturalHeight || fallback.h })
              }}
              onError={() => setFailedSrc(src)}
            />
            {space && (
              <svg className="overlay" viewBox={`0 0 ${space.w} ${space.h}`} preserveAspectRatio="none" aria-hidden="true">
                {ordered.map((box) => {
                  const px = toPixels(box.bbox, space)
                  return (
                    <rect
                      key={box.key}
                      className={`box box-${box.tone}${box.key === selectedKey ? ' selected' : ''}`}
                      x={px.x}
                      y={px.y}
                      width={px.w}
                      height={px.h}
                      onClick={() => onSelect(box.key)}
                    >
                      <title>{box.label}</title>
                    </rect>
                  )
                })}
              </svg>
            )}
          </div>
        ) : (
          <div className="viewer-missing">
            {searching ? (
              <p className="muted">Looking for the source image…</p>
            ) : (
              <>
                <p className="empty-title">{failed ? 'The source image could not be displayed' : 'Source image not available'}</p>
                <p className="empty-text">
                  {failed
                    ? 'The browser could not decode this image (some formats, such as TIFF, are not supported).'
                    : 'The API result does not include the image, and this file was not uploaded from this browser.'}{' '}
                  You can still review every value on the right. To see bounding boxes, choose the original file
                  <strong> {fileName}</strong> from your computer. It stays in this browser and is not uploaded.
                </p>
                <label className="btn">
                  Choose image file
                  <input
                    className="sr-only"
                    type="file"
                    accept="image/*"
                    onChange={(event) => {
                      const picked = event.target.files?.[0]
                      if (picked) {
                        setFailedSrc(null)
                        onAttach(picked)
                      }
                      event.target.value = ''
                    }}
                  />
                </label>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

import { isPending, type BBox, type Field, type TextBlock } from '../api'
import { confidenceTone, humanize, percent, type Tone } from '../util'
import { toPixels, type Size } from './ImageViewer'
import { Badge, ProgressBar } from './ui'

const CROP_MAX_WIDTH = 340
const CROP_MAX_HEIGHT = 120
const CROP_MAX_SCALE = 4

export function reviewBadge(field: Field): { label: string; tone: Tone } | null {
  if (isPending(field)) return { label: 'Flagged', tone: 'warn' }
  if (field.reviewState === 'accepted') return { label: 'Accepted', tone: 'ok' }
  if (field.reviewState === 'corrected') return { label: 'Corrected', tone: 'ok' }
  if (field.reviewState === 'rejected') return { label: 'Rejected', tone: 'bad' }
  return null
}

function Crop({ src, space, bbox, label }: { src: string; space: Size; bbox: BBox; label: string }) {
  const px = toPixels(bbox, space)
  const pad = Math.max(6, px.h * 0.35)
  const x = Math.max(0, px.x - pad)
  const y = Math.max(0, px.y - pad)
  const w = Math.min(space.w - x, px.w + pad * 2)
  const h = Math.min(space.h - y, px.h + pad * 2)
  const scale = Math.min(CROP_MAX_WIDTH / w, CROP_MAX_HEIGHT / h, CROP_MAX_SCALE)
  return (
    <div className="crop" style={{ width: w * scale, height: h * scale }}>
      <img
        src={src}
        alt={`Image crop of ${label}`}
        draggable={false}
        style={{ width: space.w * scale, height: space.h * scale, transform: `translate(${-x * scale}px, ${-y * scale}px)` }}
      />
    </div>
  )
}

export function Inspector({
  field,
  block,
  src,
  space,
  saving,
  error,
  onAccept,
  onReject,
  onEdit,
  onUseAlternative,
}: {
  field: Field | null
  block?: TextBlock | null
  src: string | null
  space: Size | null
  saving: boolean
  error: string | null
  onAccept: () => void
  onReject: () => void
  onEdit: () => void
  onUseAlternative: (value: string) => void
}) {
  if (!field && block) {
    // A text block is read-only OCR output, so there are no review actions here.
    return (
      <section className="inspector" aria-label="Selected item">
        <div className="inspector-head">
          <h2 className="inspector-title">Text block</h2>
          {block.language !== null && <Badge tone="neutral">{block.language}</Badge>}
        </div>

        {src && space && block.bbox ? (
          <Crop src={src} space={space} bbox={block.bbox} label={`text block ${block.readingOrder ?? ''}`.trim()} />
        ) : (
          <p className="muted small">{block.bbox ? 'No image available for a crop.' : 'This text block has no bounding box.'}</p>
        )}

        <div>
          <p className="label">Extracted text</p>
          <p className="inspector-value mono">{block.text === '' ? <span className="muted">(empty)</span> : block.text}</p>
        </div>

        <div>
          <p className="label">
            Confidence <span className={`tone-${confidenceTone(block.confidence)}`}>{percent(block.confidence)}</span>
          </p>
          {block.confidence !== null && (
            <ProgressBar value={block.confidence} label="Confidence" tone={confidenceTone(block.confidence)} />
          )}
        </div>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </section>
    )
  }

  if (!field) {
    return (
      <section className="inspector" aria-label="Selected item">
        <p className="muted">Select a field, a table cell, a text block or a box on the image to see its details.</p>
      </section>
    )
  }

  const badge = reviewBadge(field)
  const reviewable = field.id !== null

  return (
    <section className="inspector" aria-label="Selected item">
      <div className="inspector-head">
        <h2 className="inspector-title">{field.name}</h2>
        {badge && <Badge tone={badge.tone}>{badge.label}</Badge>}
      </div>

      {src && space && field.bbox ? (
        <Crop src={src} space={space} bbox={field.bbox} label={field.name} />
      ) : (
        <p className="muted small">{field.bbox ? 'No image available for a crop.' : 'This item has no bounding box.'}</p>
      )}

      <div>
        <p className="label">Extracted value</p>
        <p className={`inspector-value mono${field.reviewState === 'rejected' ? ' struck' : ''}`}>
          {field.value === '' ? <span className="muted">(empty)</span> : field.value}
        </p>
        {field.reviewState === 'corrected' && field.originalValue !== null && field.originalValue !== field.value && (
          <p className="muted small">
            Originally read as <span className="mono">{field.originalValue}</span>
          </p>
        )}
      </div>

      <div>
        <p className="label">
          Confidence <span className={`tone-${confidenceTone(field.confidence)}`}>{percent(field.confidence)}</span>
        </p>
        {field.confidence !== null && (
          <ProgressBar value={field.confidence} label="Confidence" tone={confidenceTone(field.confidence)} />
        )}
      </div>

      {field.reasons.length > 0 && (
        <div>
          <p className="label">Why it was flagged</p>
          <ul className="reason-list">
            {field.reasons.map((reason, i) => (
              <li key={i}>{/[_-]/.test(reason) && !reason.includes(' ') ? humanize(reason) : reason}</li>
            ))}
          </ul>
        </div>
      )}

      {field.alternatives.length > 0 && (
        <div>
          <p className="label">OCR alternatives</p>
          <ul className="alt-list">
            {field.alternatives.map((alt, i) => (
              <li key={i}>
                <button
                  type="button"
                  className="alt"
                  disabled={saving || !reviewable}
                  onClick={() => onUseAlternative(alt.value)}
                  title="Correct the field to this value"
                >
                  {i < 9 && <kbd>{i + 1}</kbd>}
                  <span className="mono alt-value">{alt.value}</span>
                  <span className="muted small">{percent(alt.confidence)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!reviewable && (
        <p className="error-text small">The API result has no field id for this item, so it cannot be reviewed from here.</p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}

      <div className="actions">
        <button type="button" className="btn btn-primary" disabled={saving || !reviewable} onClick={onAccept}>
          Accept <kbd>A</kbd>
        </button>
        <button type="button" className="btn" disabled={saving || !reviewable} onClick={onEdit}>
          Edit <kbd>E</kbd>
        </button>
        <button type="button" className="btn btn-danger" disabled={saving || !reviewable} onClick={onReject}>
          Reject <kbd>R</kbd>
        </button>
      </div>
    </section>
  )
}

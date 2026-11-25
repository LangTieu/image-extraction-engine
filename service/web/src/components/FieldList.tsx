import { useEffect, useRef, useState } from 'react'
import { isPending, type Field } from '../api'
import { confidenceTone, percent } from '../util'
import { reviewBadge } from './Inspector'
import { Badge, EditInput } from './ui'

export interface EditControls {
  editing: boolean
  draft: string
  saving: boolean
  onDraft: (value: string) => void
  onStart: (key: string) => void
  onCommit: () => void
  onCancel: () => void
}

export function FieldList({
  fields,
  selectedKey,
  onSelect,
  edit,
}: {
  fields: Field[]
  selectedKey: string | null
  onSelect: (key: string) => void
  edit: EditControls
}) {
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const listRef = useRef<HTMLUListElement>(null)
  const flaggedCount = fields.filter(isPending).length
  const visible = flaggedOnly ? fields.filter((f) => isPending(f) || f.key === selectedKey) : fields

  useEffect(() => {
    if (selectedKey === null) return
    const row = listRef.current?.querySelector(`[data-key="${CSS.escape(selectedKey)}"]`)
    row?.scrollIntoView({ block: 'nearest' })
  }, [selectedKey])

  return (
    <section className="field-panel" aria-label="Fields">
      <div className="field-panel-head">
        <h2 className="section-title">Fields</h2>
        <label className="check small">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
          Flagged only ({flaggedCount})
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="muted pad small">
          {fields.length === 0 ? 'This file has no standalone fields.' : 'No flagged fields left in this file.'}
        </p>
      ) : (
        <ul className="field-list" ref={listRef}>
          {visible.map((field) => {
            const selected = field.key === selectedKey
            const badge = reviewBadge(field)
            const className = `field-row${selected ? ' selected' : ''}${isPending(field) ? ' pending' : ''}`
            if (selected && edit.editing) {
              return (
                <li key={field.key} data-key={field.key} className={className}>
                  <div className="field-edit">
                    <span className="field-name">{field.name}</span>
                    <EditInput
                      label={`Corrected value for ${field.name}`}
                      value={edit.draft}
                      disabled={edit.saving}
                      onChange={edit.onDraft}
                      onCommit={edit.onCommit}
                      onCancel={edit.onCancel}
                    />
                    <div className="actions">
                      <button type="button" className="btn btn-primary btn-small" disabled={edit.saving} onClick={edit.onCommit}>
                        {edit.saving ? 'Saving…' : 'Save'} <kbd>Enter</kbd>
                      </button>
                      <button type="button" className="btn btn-small" disabled={edit.saving} onClick={edit.onCancel}>
                        Cancel <kbd>Esc</kbd>
                      </button>
                    </div>
                  </div>
                </li>
              )
            }
            return (
              <li key={field.key} data-key={field.key} className={className}>
                <button
                  type="button"
                  className="field-button"
                  aria-current={selected ? 'true' : undefined}
                  onClick={() => onSelect(field.key)}
                  onDoubleClick={() => edit.onStart(field.key)}
                >
                  <span className="field-text">
                    <span className="field-name">{field.name}</span>
                    <span className={`field-value mono${field.reviewState === 'rejected' ? ' struck' : ''}`}>
                      {field.value === '' ? '(empty)' : field.value}
                    </span>
                  </span>
                  <span className="field-meta">
                    {badge && <Badge tone={badge.tone}>{badge.label}</Badge>}
                    <span className={`small tone-${confidenceTone(field.confidence)}`}>{percent(field.confidence)}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

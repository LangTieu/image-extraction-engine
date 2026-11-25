import { useEffect, useRef, type KeyboardEvent } from 'react'
import { isPending, type Field, type Table } from '../api'
import type { EditControls } from './FieldList'
import { EditInput } from './ui'

const ARROWS: Record<string, [number, number]> = {
  ArrowUp: [-1, 0],
  ArrowDown: [1, 0],
  ArrowLeft: [0, -1],
  ArrowRight: [0, 1],
}

function cellClass(cell: Field, selected: boolean): string {
  let name = 'grid-cell'
  if (selected) name += ' selected'
  if (isPending(cell)) name += ' pending'
  else if (cell.reviewState === 'rejected') name += ' rejected'
  else if (cell.reviewState !== null) name += ' reviewed'
  return name
}

function cellStatus(cell: Field): string {
  if (isPending(cell)) return ', flagged for review'
  if (cell.reviewState !== null) return `, ${cell.reviewState}`
  return ''
}

/** Editable grids for a file's tables. Selection is shared with the image overlay. */
export function TableGrid({
  tables,
  selectedKey,
  onSelect,
  edit,
}: {
  tables: Table[]
  selectedKey: string | null
  onSelect: (key: string) => void
  edit: EditControls
}) {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root || selectedKey === null) return
    const cell = root.querySelector<HTMLElement>(`[data-key="${CSS.escape(selectedKey)}"]`)
    if (!cell) return
    if (root.contains(document.activeElement)) cell.focus()
    cell.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selectedKey])

  function onCellKeyDown(event: KeyboardEvent<HTMLButtonElement>, table: Table, cell: Field) {
    if (event.key === 'Enter' || event.key === 'F2') {
      event.preventDefault()
      edit.onStart(cell.key)
      return
    }
    const move = ARROWS[event.key]
    if (!move || !cell.cell) return
    const row = cell.cell.row + move[0]
    const col = cell.cell.col + move[1]
    const neighbour = table.cells.find((c) => c.cell?.row === row && c.cell?.col === col)
    if (neighbour) {
      event.preventDefault()
      onSelect(neighbour.key)
    }
  }

  return (
    <div className="grid-dock" ref={rootRef}>
      {tables.map((table) => {
        const flagged = table.cells.filter(isPending).length
        return (
          <table key={table.id} className="grid">
            <caption>
              {table.name}
              <span className="muted">
                {' '}
                · {table.rowCount} rows{flagged > 0 ? ` · ${flagged} flagged` : ''} · arrow keys move, Enter edits
              </span>
            </caption>
            <thead>
              <tr>
                <th scope="col" className="grid-rownum">
                  <span className="sr-only">Row</span>
                </th>
                {Array.from({ length: table.colCount }, (_, col) => (
                  <th key={col} scope="col">
                    {table.headers[col] || `Column ${col + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: table.rowCount }, (_, row) => (
                <tr key={row}>
                  <th scope="row" className="grid-rownum">
                    {row + 1}
                  </th>
                  {Array.from({ length: table.colCount }, (_, col) => {
                    const cell = table.cells.find((c) => c.cell?.row === row && c.cell?.col === col)
                    if (!cell) return <td key={col} className="grid-empty" />
                    const selected = cell.key === selectedKey
                    return (
                      <td key={col}>
                        {selected && edit.editing ? (
                          <EditInput
                            label={`Corrected value for ${cell.name}`}
                            value={edit.draft}
                            disabled={edit.saving}
                            onChange={edit.onDraft}
                            onCommit={edit.onCommit}
                            onCancel={edit.onCancel}
                          />
                        ) : (
                          <button
                            type="button"
                            data-key={cell.key}
                            className={cellClass(cell, selected)}
                            aria-label={`${cell.name}: ${cell.value || 'empty'}${cellStatus(cell)}`}
                            aria-current={selected ? 'true' : undefined}
                            onClick={() => onSelect(cell.key)}
                            onDoubleClick={() => edit.onStart(cell.key)}
                            onKeyDown={(event) => onCellKeyDown(event, table, cell)}
                          >
                            {cell.value === '' ? '\u00a0' : cell.value}
                          </button>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )
      })}
    </div>
  )
}

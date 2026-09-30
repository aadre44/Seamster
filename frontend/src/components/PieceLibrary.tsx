import { useMemo } from 'react'
import { useEditor } from '../context/EditorContext'
import { PRESETS, presetDetail } from '../library/presets'
import type { PresetCategory, PresetResult } from '../library/presets'
import { presetContext } from '../library/context'

// Drawer of ready-made pieces and markings: drag one onto the canvas.
export const PRESET_MIME = 'application/x-seamster-preset'

const CATEGORIES: PresetCategory[] = ['Pockets', 'Collars', 'Cuffs & bands', 'Plackets & flaps', 'Buttons']

function Thumb({ result }: { result: PresetResult }) {
  const shapes = result.elements.filter(e => e.type === 'line' || e.type === 'curve')
  const pts = shapes.flatMap(e => ('start' in e ? [e.start, e.end] : []))
  const x0 = Math.min(...pts.map(p => p.x)), x1 = Math.max(...pts.map(p => p.x))
  const y0 = Math.min(...pts.map(p => p.y)), y1 = Math.max(...pts.map(p => p.y))
  const pad = Math.max(x1 - x0, y1 - y0) * 0.08 + 0.3
  const marking = !result.piece
  return (
    <svg viewBox={`${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`} className="w-12 h-12 shrink-0" preserveAspectRatio="xMidYMid meet">
      {shapes.map(e => (
        <path key={e.id}
          d={e.type === 'curve'
            ? `M ${e.start.x} ${e.start.y} C ${e.cp1.x} ${e.cp1.y}, ${e.cp2.x} ${e.cp2.y}, ${e.end.x} ${e.end.y}`
            : `M ${e.start.x} ${e.start.y} L ${e.end.x} ${e.end.y}`}
          fill="none"
          stroke={marking ? '#92400e' : e.type === 'line' && e.isFold ? '#9ca3af' : '#4f46e5'}
          strokeWidth={marking ? 1.5 : 1.2}
          strokeDasharray={e.type === 'line' && e.isFold ? '3 2' : undefined}
          vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  )
}

export default function PieceLibrary({ onClose }: { onClose: () => void }) {
  const { state } = useEditor()
  const ctx = useMemo(() => presetContext(state.pieces, state.elements, state.measurements), [state.pieces, state.elements, state.measurements])
  const items = useMemo(() => PRESETS.map(p => ({ p, result: p.make(ctx), detail: presetDetail(p, ctx) })), [ctx])

  return (
    <div className="absolute left-full top-0 h-full w-64 z-30 bg-white border-r border-gray-200 shadow-lg flex flex-col" data-testid="piece-library">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <div>
          <div className="text-xs font-semibold text-gray-700">Piece library</div>
          <div className="text-[10px] text-gray-400">Drag onto the canvas. Buttons and buttonholes go on a piece.</div>
        </div>
        <button onClick={onClose} aria-label="Close library" className="text-gray-400 hover:text-gray-700 text-sm px-1">✕</button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {CATEGORIES.map(cat => (
          <div key={cat} className="mb-2">
            <div className="px-1 pt-1 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">{cat}</div>
            {items.filter(i => i.p.category === cat).map(({ p, result, detail }) => (
              <div
                key={p.id}
                draggable
                onDragStart={e => {
                  e.dataTransfer.setData(PRESET_MIME, p.id)
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                title={`Drag ${p.name.toLowerCase()} onto the canvas`}
                data-preset={p.id}
                className="flex items-center gap-2 px-1.5 py-1 rounded cursor-grab hover:bg-indigo-50 active:cursor-grabbing"
              >
                <Thumb result={result} />
                <div className="min-w-0">
                  <div className="text-[11px] text-gray-800 truncate">{p.name}</div>
                  <div className="text-[10px] text-gray-500 truncate">{detail}</div>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

import { useState } from 'react'
import { inferAttachments } from '../../api'
import { useEditor } from '../../context/EditorContext'
import type { CanvasElement, PatternPiece, SeamConnection, SeamEnd } from '../../types'
import { edgeName, hasSides, labelColour, seamFit, sewnLength } from './seams'
import type { Fit } from './seams'

const FIT_STYLE: Record<Fit, string> = {
  match: 'bg-emerald-50 text-emerald-700',
  ease: 'bg-amber-50 text-amber-700',
  mismatch: 'bg-red-50 text-red-700',
}

interface Props {
  pieces: PatternPiece[]
  byId: Map<string, CanvasElement>
  selected: number | null
  onSelect: (i: number | null) => void
  onHover: (i: number | null) => void
  pending: SeamEnd | null
}

export default function SeamsPanel({ pieces, byId, selected, onSelect, onHover, pending }: Props) {
  const { state, dispatch } = useEditor()
  const { connections } = state
  const [inferring, setInferring] = useState(false)
  const [inferError, setInferError] = useState('')
  const pieceOf = (id: string) => pieces.find(p => p.id === id)
  const endName = (end: SeamEnd) => `${pieceOf(end.pieceId)?.name ?? '?'} · ${edgeName(pieceOf(end.pieceId), end.edgeId, byId)}`
  const sel = selected !== null ? connections[selected] : undefined
  const update = (c: SeamConnection, tag?: string) => selected !== null && dispatch({ type: 'UPDATE_CONNECTION', index: selected, connection: c, tag })

  const reinfer = async () => {
    if (!window.confirm('Replace the automatic seams and pocket placements with freshly inferred ones? Seams and placements you made yourself are kept.')) return
    setInferring(true)
    setInferError('')
    try {
      const r = await inferAttachments(state.elements, state.pieces)
      onSelect(null)
      dispatch({ type: 'APPLY_INFERRED', connections: r.connections, placements: r.placements, layers: r.layers })
    } catch {
      setInferError('Could not reach the pattern server to infer seams.')
    } finally {
      setInferring(false)
    }
  }

  return (
    <div className="w-72 shrink-0 border-l border-gray-200 bg-white overflow-y-auto flex flex-col" data-testid="seams-panel">
      <div className="px-3 py-2 border-b border-gray-100">
        <div className="flex items-center justify-between">
          <div className="text-xs font-semibold text-gray-700">Seams ({connections.length})</div>
          <button
            onClick={reinfer}
            disabled={inferring}
            title="Work out seams for collars, cuffs, flies, pocket bags and where pockets go"
            className="text-[11px] px-2 py-0.5 rounded border border-teal-300 text-teal-700 hover:bg-teal-50 disabled:opacity-50"
          >
            {inferring ? 'Inferring…' : 'Re-infer'}
          </button>
        </div>
        {inferError && <div className="text-[11px] text-red-600 mt-1">{inferError}</div>}
        <div className="text-[11px] text-gray-400 mt-0.5 leading-snug">
          {pending
            ? <span className="text-teal-700">Now click the edge to sew <b>{endName(pending)}</b> to. Esc cancels.</span>
            : 'Click an edge, then the edge it is sewn to. Click a seam to edit it.'}
        </div>
      </div>

      {sel && selected !== null && (
        <div className="px-3 py-2 border-b border-gray-200 bg-gray-50 space-y-2" data-testid="seam-editor">
          <div className="flex items-center gap-2">
            <input
              aria-label="Seam label"
              className="flex-1 text-xs border border-gray-300 rounded px-1.5 py-0.5"
              value={sel.label}
              onChange={e => update({ ...sel, label: e.target.value }, `label:${selected}`)}
            />
            <button
              className="text-xs px-2 py-0.5 rounded border border-red-200 text-red-600 hover:bg-red-50"
              onClick={() => { dispatch({ type: 'DELETE_CONNECTION', index: selected }); onSelect(null) }}
            >Delete</button>
          </div>
          {(['from', 'to'] as const).map(k => (
            <EndEditor
              key={k}
              end={sel[k]}
              name={endName(sel[k])}
              length={sewnLength(sel[k], byId)}
              sided={hasSides(pieceOf(sel[k].pieceId))}
              onChange={(end, tag) => update({ ...sel, [k]: end }, tag)}
            />
          ))}
          <label className="flex items-center justify-between text-[11px] text-gray-600">
            Direction
            <select
              aria-label="Sewing direction"
              className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white"
              value={sel.reversed === undefined ? 'auto' : sel.reversed ? 'reversed' : 'same'}
              onChange={e => update({ ...sel, reversed: e.target.value === 'auto' ? undefined : e.target.value === 'reversed' })}
            >
              <option value="auto">Automatic</option>
              <option value="same">Start to start</option>
              <option value="reversed">Start to end</option>
            </select>
          </label>
          <FitLine c={sel} byId={byId} />
        </div>
      )}

      <ul className="flex-1 py-1">
        {connections.map((c, i) => (
          <li key={i}>
            <button
              className={`w-full text-left px-3 py-1.5 flex items-start gap-2 hover:bg-gray-50 ${selected === i ? 'bg-teal-50' : ''}`}
              onClick={() => onSelect(selected === i ? null : i)}
              onMouseEnter={() => onHover(i)}
              onMouseLeave={() => onHover(null)}
            >
              <span className="mt-1 shrink-0 w-2.5 h-2.5 rounded-full" style={{ background: labelColour(c.label) }} />
              <span className="flex-1 min-w-0">
                <span className="block text-[11px] text-gray-800 truncate">{endName(c.from)}</span>
                <span className="block text-[11px] text-gray-500 truncate">↔ {endName(c.to)}</span>
              </span>
              <span className="flex flex-col items-end gap-0.5">
                <FitChip c={c} byId={byId} />
                <span className="text-[9px] uppercase tracking-wide text-gray-400">{c.source === 'user' ? 'yours' : 'auto'}</span>
              </span>
            </button>
          </li>
        ))}
        {connections.length === 0 && <li className="px-3 py-2 text-[11px] text-gray-400">No seams yet.</li>}
      </ul>
    </div>
  )
}

function FitChip({ c, byId }: { c: SeamConnection; byId: Map<string, CanvasElement> }) {
  const { delta, fit } = seamFit(c, byId)
  return <span className={`text-[10px] px-1 rounded ${FIT_STYLE[fit]}`}>{fit === 'match' ? '✓' : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}`}</span>
}

function FitLine({ c, byId }: { c: SeamConnection; byId: Map<string, CanvasElement> }) {
  const { delta, fit } = seamFit(c, byId)
  const text = fit === 'match'
    ? 'Lengths match.'
    : fit === 'ease'
      ? `Eased: ${Math.abs(delta).toFixed(1)} cm of fullness worked into the shorter side.`
      : `Lengths differ by ${Math.abs(delta).toFixed(1)} cm: this seam will pucker or fall short.`
  return <div className={`text-[11px] rounded px-1.5 py-1 ${FIT_STYLE[fit]}`}>{text}</div>
}

function EndEditor({ end, name, length, sided, onChange }: {
  end: SeamEnd
  name: string
  length: number
  sided: boolean
  onChange: (end: SeamEnd, tag?: string) => void
}) {
  const [lo, hi] = end.range ?? [0, 1]
  const setRange = (a: number, b: number) => {
    const r: [number, number] = [Math.max(0, Math.min(a, b - 0.02)), Math.min(1, Math.max(b, a + 0.02))]
    const whole = r[0] <= 0 && r[1] >= 1
    const { range: _drop, ...rest } = end
    onChange(whole ? rest : { ...rest, range: r }, `range:${name}`)
  }
  const pct = (v: number) => Math.round(v * 100)
  return (
    <div className="rounded border border-gray-200 bg-white px-2 py-1.5 space-y-1">
      <div className="text-[11px] font-medium text-gray-700 truncate" title={name}>{name}</div>
      <div className="flex items-center gap-1 text-[11px] text-gray-500">
        <span>Sewn</span>
        <input aria-label={`${name} range start`} type="number" min={0} max={100} value={pct(lo)}
          onChange={e => setRange(Number(e.target.value) / 100, hi)}
          className="w-12 border border-gray-300 rounded px-1 py-0.5 text-[11px]" />
        <span>–</span>
        <input aria-label={`${name} range end`} type="number" min={0} max={100} value={pct(hi)}
          onChange={e => setRange(lo, Number(e.target.value) / 100)}
          className="w-12 border border-gray-300 rounded px-1 py-0.5 text-[11px]" />
        <span>% · {length.toFixed(1)} cm</span>
        {end.range && (
          <button className="ml-auto text-[10px] text-teal-700 hover:underline" onClick={() => setRange(0, 1)}>whole</button>
        )}
      </div>
      {end.half && <div className="text-[11px] text-gray-500">On the {end.half} half of the sleeve</div>}
      {sided && (
        <label className="flex items-center justify-between text-[11px] text-gray-500">
          Side (wearer's)
          <select
            aria-label={`${name} side`}
            className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white"
            value={end.side ?? 'both'}
            onChange={e => {
              const { side: _drop, ...rest } = end
              onChange(e.target.value === 'both' ? rest : { ...rest, side: e.target.value as 'left' | 'right' })
            }}
          >
            <option value="both">Both</option>
            <option value="left">Left</option>
            <option value="right">Right</option>
          </select>
        </label>
      )}
    </div>
  )
}


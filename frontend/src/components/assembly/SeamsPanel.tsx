import { useState } from 'react'
import { inferAttachments } from '../../api'
import { useEditor } from '../../context/EditorContext'
import type { CanvasElement, PatternPiece, Placement, SeamConnection, SeamEnd } from '../../types'
import { pieceEdges } from './geometry'
import { flySeams, guessFly, isFlyHost } from './autoFly'
import type { FlyPlan } from './autoFly'
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
  selectedPlacement: string | null
  onSelectPlacement: (id: string | null) => void
}

export default function SeamsPanel({ pieces, byId, selected, onSelect, onHover, pending, selectedPlacement, onSelectPlacement }: Props) {
  const { state, dispatch } = useEditor()
  const { connections, placements } = state
  const placed = placements.find(p => p.id === selectedPlacement)
  const [inferring, setInferring] = useState(false)
  const [fly, setFly] = useState<FlyPlan | null>(null)
  const canFly = pieces.some(p => isFlyHost(p, byId)) && pieces.length > 1
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
          {canFly && (
            <button
              onClick={() => setFly(f => (f ? null : guessFly(pieces, byId)))}
              title="Sew the fly facing and fly shield to the centre front, the way a fly is constructed"
              className={`ml-auto mr-1 text-[11px] px-2 py-0.5 rounded border ${fly ? 'bg-teal-600 text-white border-teal-600' : 'border-teal-300 text-teal-700 hover:bg-teal-50'}`}
            >
              Fly…
            </button>
          )}
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
            : 'Click an edge, then the edge it is sewn to. Click a seam to edit it. Drag a pocket onto the piece it goes on.'}
        </div>
      </div>

      {fly && <FlyForm plan={fly} pieces={pieces} byId={byId} onChange={setFly} onDone={() => setFly(null)} />}

      {placed && (
        <PlacementEditor
          onFly={() => { onSelectPlacement(null); setFly({ ...guessFly(pieces, byId), ...(/shield/i.test(pieceOf(placed.pieceId)?.name ?? '') ? { shield: placed.pieceId } : { facing: placed.pieceId }) }) }}
          placement={placed}
          piece={pieceOf(placed.pieceId)}
          host={pieceOf(placed.hostId)}
          byId={byId}
          onDone={() => onSelectPlacement(null)}
        />
      )}

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

      <div className="px-3 pt-2 pb-1 border-t border-gray-100 text-xs font-semibold text-gray-700">Placed pieces ({placements.length})</div>
      <ul className="pb-2" data-testid="placements">
        {placements.map(pl => (
          <li key={pl.id}>
            <button
              className={`w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-gray-50 ${selectedPlacement === pl.id ? 'bg-teal-50' : ''}`}
              onClick={() => onSelectPlacement(selectedPlacement === pl.id ? null : pl.id)}
            >
              <span className="shrink-0 w-2.5 h-2.5 rounded-sm bg-amber-300" />
              <span className="flex-1 min-w-0 text-[11px] text-gray-800 truncate">
                {pieceOf(pl.pieceId)?.name ?? '?'} <span className="text-gray-400">on</span> {pieceOf(pl.hostId)?.name ?? '?'}
              </span>
              <span className="text-[9px] uppercase tracking-wide text-gray-400">{pl.source === 'user' ? 'yours' : 'auto'}</span>
            </button>
          </li>
        ))}
        {placements.length === 0 && <li className="px-3 py-1 text-[11px] text-gray-400">None — drag a pocket onto its piece.</li>}
      </ul>
    </div>
  )
}

function FlyForm({ plan, pieces, byId, onChange, onDone }: {
  plan: FlyPlan
  pieces: PatternPiece[]
  byId: Map<string, CanvasElement>
  onChange: (p: FlyPlan) => void
  onDone: () => void
}) {
  const { dispatch } = useEditor()
  const [error, setError] = useState('')
  const hosts = pieces.filter(p => isFlyHost(p, byId))
  const others = pieces.filter(p => p.id !== plan.host)
  const pick = (label: string, value: string | null, options: PatternPiece[], set: (id: string | null) => void, none = true) => (
    <label className="flex items-center justify-between gap-2 text-[11px] text-gray-600">
      {label}
      <select aria-label={label} className="max-w-[9rem] text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white"
        value={value ?? ''} onChange={e => set(e.target.value || null)}>
        {none && <option value="">None</option>}
        {options.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
  )
  const attach = () => {
    const seams = flySeams(plan, pieces, byId)
    const ids = [plan.facing, plan.shield].filter((x): x is string => !!x)
    if (!seams.length || !ids.length) { setError('Pick the front piece and at least the fly facing.'); return }
    dispatch({ type: 'REPLACE_ATTACHMENTS', pieceIds: ids, connections: seams, layers: Object.fromEntries(ids.map(id => [id, 'inside' as const])) })
    onDone()
  }
  return (
    <div className="px-3 py-2 border-b border-gray-200 bg-teal-50/60 space-y-1.5" data-testid="fly-form">
      <div className="text-[11px] font-medium text-gray-800">Place the fly</div>
      <div className="text-[11px] text-gray-500 leading-snug">
        Sews the fly facing along the centre front from the waist down, and the shield on the other side, both inside. Replaces any seams or placements they had.
      </div>
      {pick('Front piece', plan.host, hosts, id => onChange({ ...plan, host: id }), false)}
      {pick('Fly facing', plan.facing, others, id => onChange({ ...plan, facing: id }))}
      {pick('Fly shield', plan.shield, others.filter(p => p.id !== plan.facing), id => onChange({ ...plan, shield: id }))}
      <label className="flex items-center justify-between text-[11px] text-gray-600">
        Facing on the wearer's
        <select aria-label="Facing side" className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white"
          value={plan.facingSide} onChange={e => onChange({ ...plan, facingSide: e.target.value as 'left' | 'right' })}>
          <option value="left">Left (menswear)</option>
          <option value="right">Right (womenswear)</option>
        </select>
      </label>
      {error && <div className="text-[11px] text-red-600">{error}</div>}
      <div className="flex gap-2 pt-0.5">
        <button onClick={attach} className="text-[11px] px-2 py-0.5 rounded bg-teal-600 text-white hover:bg-teal-700">Attach fly</button>
        <button onClick={onDone} className="text-[11px] px-2 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50">Cancel</button>
      </div>
    </div>
  )
}

function PlacementEditor({ placement, piece, host, byId, onDone, onFly }: {
  placement: Placement
  piece: PatternPiece | undefined
  host: PatternPiece | undefined
  byId: Map<string, CanvasElement>
  onDone: () => void
  onFly: () => void
}) {
  const { dispatch } = useEditor()
  const update = (p: Placement, tag?: string) => dispatch({ type: 'UPDATE_PLACEMENT', placement: { ...p, source: 'user' }, tag })
  const edges = piece ? pieceEdges(piece, byId) : []
  const layer = piece?.layer ?? 'outer'
  return (
    <div className="px-3 py-2 border-b border-gray-200 bg-amber-50/60 space-y-2" data-testid="placement-editor">
      <div className="flex items-center gap-2">
        <div className="flex-1 min-w-0 text-[11px] font-medium text-gray-800 truncate">
          {piece?.name ?? '?'} <span className="text-gray-500 font-normal">on</span> {host?.name ?? '?'}
        </div>
        <button
          className="text-xs px-2 py-0.5 rounded border border-red-200 text-red-600 hover:bg-red-50"
          onClick={() => { dispatch({ type: 'DELETE_PLACEMENT', id: placement.id }); onDone() }}
        >Remove</button>
      </div>
      {piece && /\b(fly|shield)\b/i.test(piece.name) && (
        <button onClick={onFly} className="w-full text-left text-[11px] px-2 py-1 rounded border border-teal-300 bg-white text-teal-800 hover:bg-teal-50">
          This is a fly piece: a fly is sewn to the centre front, not placed on it. <b>Attach it automatically…</b>
        </button>
      )}
      <div className="text-[11px] text-gray-500">Drag it to move; drag the round handle to turn it.</div>
      <label className="flex items-center justify-between text-[11px] text-gray-600">
        Rotation
        <span className="flex items-center gap-1">
          <input aria-label="Rotation" type="number" step={5} value={placement.transform.rotation}
            onChange={e => update({ ...placement, transform: { ...placement.transform, rotation: Number(e.target.value) || 0 } }, `rot:${placement.id}`)}
            className="w-14 border border-gray-300 rounded px-1 py-0.5 text-[11px]" />°
        </span>
      </label>
      {hasSides(host) && (
        <label className="flex items-center justify-between text-[11px] text-gray-600">
          Side (wearer's)
          <select aria-label="Placement side" className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white"
            value={placement.side ?? 'both'}
            onChange={e => {
              const { side: _drop, ...rest } = placement
              update(e.target.value === 'both' ? rest : { ...rest, side: e.target.value as 'left' | 'right' })
            }}>
            <option value="both">Both</option>
            <option value="left">Left</option>
            <option value="right">Right</option>
          </select>
        </label>
      )}
      {piece && (
        <label className="flex items-center justify-between text-[11px] text-gray-600">
          Sits
          <select aria-label="Layer" className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white"
            value={layer}
            onChange={e => dispatch({ type: 'UPDATE_PIECE', piece: { ...piece, layer: e.target.value as 'outer' | 'inside' } })}>
            <option value="outer">Outside</option>
            <option value="inside">Inside</option>
          </select>
        </label>
      )}
      <div className="text-[11px] text-gray-600">
        Stitched edges <span className="text-gray-400">(the rest stay open)</span>
        <div className="mt-1 flex flex-wrap gap-1">
          {edges.map((el, k) => {
            const on = placement.stitched.includes(el.id)
            return (
              <button key={el.id}
                aria-pressed={on}
                onClick={() => update({ ...placement, stitched: on ? placement.stitched.filter(id => id !== el.id) : [...placement.stitched, el.id] })}
                className={`px-1.5 py-0.5 rounded border text-[10px] ${on ? 'bg-amber-700 text-white border-amber-700' : 'bg-white text-gray-600 border-gray-300'}`}>
                {edgeName(piece, el.id, byId) || `edge ${k + 1}`}
              </button>
            )
          })}
        </div>
      </div>
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


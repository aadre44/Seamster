import { useState } from 'react'
import { inferAttachments } from '../../api'
import { useEditor } from '../../context/EditorContext'
import type { CanvasElement, PatternPiece, Placement, SeamConnection, SeamEnd } from '../../types'
import { pieceEdges, sampleEdge } from './geometry'
import type { Edge } from './geometry'
import { flySeams, guessFly, isFlyHost } from './autoFly'
import { distances, moveTo } from './placementAids'
import { DEFAULT_ROW, buttonRow, canButton } from './closures'
import { bandEdge, bandSeams } from './bands'
import { isTrimName } from '../../three/pieceClassifier'
import type { ButtonRowOptions } from './closures'
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
  const [band, setBand] = useState(false)
  const bandPieces = pieces.filter(p => isTrimName(p.name))
  const [buttons, setButtons] = useState(false)
  const buttonHosts = pieces.filter(p => canButton(p, byId))
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
          {bandPieces.length > 0 && (
            <button
              onClick={() => setBand(b => !b)}
              title="Sew a waistband, collar, cuff or hem band round its opening, across all the pieces it touches"
              className={`ml-auto mr-1 text-[11px] px-2 py-0.5 rounded border ${band ? 'bg-teal-600 text-white border-teal-600' : 'border-teal-300 text-teal-700 hover:bg-teal-50'}`}
            >
              Band…
            </button>
          )}
          {canFly && (
            <button
              onClick={() => setFly(f => (f ? null : guessFly(pieces, byId)))}
              title="Sew the fly facing and fly shield to the centre front, the way a fly is constructed"
              className={`${bandPieces.length ? '' : 'ml-auto '}mr-1 text-[11px] px-2 py-0.5 rounded border ${fly ? 'bg-teal-600 text-white border-teal-600' : 'border-teal-300 text-teal-700 hover:bg-teal-50'}`}
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

      {band && <BandForm bands={bandPieces} pieces={pieces} byId={byId} onDone={() => setBand(false)} />}
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

      <div className="px-3 pt-2 pb-1 border-t border-gray-100 flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">Placed pieces ({placements.length})</span>
        {buttonHosts.length > 0 && (
          <button onClick={() => setButtons(b => !b)}
            title="A row of buttons down a front, with the buttonholes on the other front"
            className={`text-[11px] px-2 py-0.5 rounded border ${buttons ? 'bg-teal-600 text-white border-teal-600' : 'border-teal-300 text-teal-700 hover:bg-teal-50'}`}>
            Buttons…
          </button>
        )}
      </div>
      {buttons && <ButtonRowForm hosts={buttonHosts} byId={byId} onDone={() => setButtons(false)} />}
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
                {hasSides(pieceOf(pl.hostId)) && <span className="text-gray-400"> · {pl.side ? (pl.side === 'left' ? 'L' : 'R') : '🔗 both'}</span>}
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

type Opening = 'waist' | 'neckline' | 'hem' | 'wrist'
const OPENINGS: { key: Opening; label: string }[] = [
  { key: 'waist', label: 'Waist' }, { key: 'neckline', label: 'Neckline' }, { key: 'hem', label: 'Hem' }, { key: 'wrist', label: 'Wrist (cuff)' },
]
const openingFor = (name: string): Opening =>
  /collar|neck|hood/i.test(name) ? 'neckline' : /cuff|wrist|sleeve/i.test(name) ? 'wrist' : /hem|ruffle|frill|flounce/i.test(name) ? 'hem' : 'waist'

function BandForm({ bands, pieces, byId, onDone }: { bands: PatternPiece[]; pieces: PatternPiece[]; byId: Map<string, CanvasElement>; onDone: () => void }) {
  const { dispatch } = useEditor()
  const first = bands.find(p => /band|collar|cuff/i.test(p.name)) ?? bands[0]
  const [bandId, setBandId] = useState(first?.id ?? '')
  const [opening, setOpening] = useState<Opening>(openingFor(first?.name ?? ''))
  const [error, setError] = useState('')
  const trim = bands.find(p => p.id === bandId)
  const edge = trim && bandEdge(trim, byId)
  // Every edge of the garment (not trims) along that opening.
  const hosts = pieces.filter(p => !isTrimName(p.name)).flatMap(p => pieceEdges(p, byId)
    .filter(e => e.seamLabel === opening || (opening === 'waist' && e.seamLabel === 'waist_seam' && !/bodice/i.test(p.name)))
    .map(e => ({ pieceId: p.id, edgeId: e.id })))
  const planned = trim && edge && hosts.length ? bandSeams(trim, edge, hosts, pieces, byId) : null
  // How the band's length compares with the opening it will be sewn round.
  const fit = (() => {
    if (!trim || !edge || !planned?.length) return null
    const L = sampleEdge(edge).length
    const sewn = planned.reduce((s, c) => s + (byId.get(c.to.edgeId) ? sampleEdge(byId.get(c.to.edgeId) as Edge).length : 0), 0)
    const extra = L - sewn
    if (Math.abs(extra) < 0.5) return { text: `Band ${L.toFixed(1)} cm fits the ${sewn.toFixed(1)} cm opening exactly.`, tone: 'bg-emerald-50 text-emerald-700' }
    if (extra < 0) return { text: `Band ${L.toFixed(1)} cm is ${(-extra).toFixed(1)} cm shorter than the ${sewn.toFixed(1)} cm opening: it will be eased (stretched) along it.`, tone: 'bg-amber-50 text-amber-700' }
    const where = opening === 'neckline' ? `split between its two ends (${(extra / 2).toFixed(1)} cm each)` : 'as the overlap at its end'
    const typical = opening === 'waist' && extra > 6 ? ' A waistband overlap is usually 3–4 cm.' : ''
    return { text: `Band ${L.toFixed(1)} cm, opening ${sewn.toFixed(1)} cm: ${extra.toFixed(1)} cm left over, ${where}.${typical}`, tone: extra > 6 && opening === 'waist' ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700' }
  })()
  const attach = () => {
    if (!trim || !edge) return
    const seams = planned
    if (!seams?.length) { setError(`No ${opening} edges to sew it to.`); return }
    dispatch({ type: 'REPLACE_ATTACHMENTS', pieceIds: [trim.id], connections: seams })
    onDone()
  }
  return (
    <div className="px-3 py-2 border-b border-gray-200 bg-teal-50/60 space-y-1.5" data-testid="band-form">
      <div className="text-[11px] font-medium text-gray-800">Sew a band round an opening</div>
      <div className="text-[11px] text-gray-500 leading-snug">
        Its longest edge is sewn along every piece at that opening in turn — right front, right back, left back, left front for a band cut once — each stretch as long as the edge it meets; extra length is left as an overlap at the end.
      </div>
      <label className="flex items-center justify-between gap-2 text-[11px] text-gray-600">
        Band
        <select aria-label="Band piece" value={bandId} onChange={e => { setBandId(e.target.value); setOpening(openingFor(bands.find(p => p.id === e.target.value)?.name ?? '')) }}
          className="max-w-[9rem] text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white">
          {bands.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label className="flex items-center justify-between gap-2 text-[11px] text-gray-600">
        Sewn to the
        <select aria-label="Opening" value={opening} onChange={e => setOpening(e.target.value as Opening)}
          className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white">
          {OPENINGS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
      </label>
      {fit && <div className={`text-[11px] rounded px-1.5 py-1 ${fit.tone}`}>{fit.text}</div>}
      {error && <div className="text-[11px] text-red-600">{error}</div>}
      <div className="flex gap-2 pt-0.5">
        <button onClick={attach} className="text-[11px] px-2 py-0.5 rounded bg-teal-600 text-white hover:bg-teal-700">Attach band</button>
        <button onClick={onDone} className="text-[11px] px-2 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50">Cancel</button>
      </div>
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

function ButtonRowForm({ hosts, byId, onDone }: { hosts: PatternPiece[]; byId: Map<string, CanvasElement>; onDone: () => void }) {
  const { dispatch } = useEditor()
  const [host, setHost] = useState(hosts[0]?.id ?? '')
  const [o, setO] = useState<ButtonRowOptions>(DEFAULT_ROW)
  const num = (label: string, key: 'count' | 'inset' | 'top' | 'bottom', step: number) => (
    <label className="flex items-center justify-between text-[11px] text-gray-600">
      {label}
      <input aria-label={label} type="number" step={step} min={key === 'count' ? 1 : 0} value={o[key]}
        onChange={e => { const v = parseFloat(e.target.value); if (Number.isFinite(v)) setO({ ...o, [key]: key === 'count' ? Math.max(1, Math.round(v)) : v }) }}
        className="w-16 border border-gray-300 rounded px-1 py-0.5 text-[11px]" />
    </label>
  )
  const add = () => {
    const piece = hosts.find(p => p.id === host)
    if (!piece) return
    dispatch({ type: 'INSERT_PRESET', elements: buttonRow(piece, byId, o) })
    onDone()
  }
  return (
    <div className="px-3 py-2 border-b border-gray-200 bg-teal-50/60 space-y-1.5" data-testid="button-row-form">
      <div className="text-[11px] font-medium text-gray-800">Button row</div>
      <label className="flex items-center justify-between gap-2 text-[11px] text-gray-600">
        Front piece
        <select aria-label="Button piece" value={host} onChange={e => setHost(e.target.value)}
          className="max-w-[9rem] text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white">
          {hosts.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      {num('Buttons', 'count', 1)}
      <label className="flex items-center justify-between text-[11px] text-gray-600">
        Size
        <select aria-label="Button size" value={o.diameter} onChange={e => setO({ ...o, diameter: parseFloat(e.target.value) })}
          className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white">
          <option value={1.1}>11 mm (shirt)</option>
          <option value={1.5}>15 mm</option>
          <option value={2.0}>20 mm (coat)</option>
        </select>
      </label>
      {num('In from the front edge (cm)', 'inset', 0.25)}
      {num('First, below the top (cm)', 'top', 0.5)}
      {num('Last, above the bottom (cm)', 'bottom', 0.5)}
      <label className="flex items-center justify-between text-[11px] text-gray-600">
        Buttons on the wearer's
        <select aria-label="Buttons on" value={o.buttonsOn} onChange={e => setO({ ...o, buttonsOn: e.target.value as 'left' | 'right' })}
          className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white">
          <option value="right">Right (menswear)</option>
          <option value="left">Left (womenswear)</option>
        </select>
      </label>
      <label className="flex items-center justify-between text-[11px] text-gray-600">
        Buttonholes on the other front
        <select aria-label="Buttonholes" value={o.holes} onChange={e => setO({ ...o, holes: e.target.value as ButtonRowOptions['holes'] })}
          className="text-[11px] border border-gray-300 rounded px-1 py-0.5 bg-white">
          <option value="vertical">Vertical (placket)</option>
          <option value="horizontal">Horizontal</option>
          <option value="none">None</option>
        </select>
      </label>
      <div className="flex gap-2 pt-0.5">
        <button onClick={add} className="text-[11px] px-2 py-0.5 rounded bg-teal-600 text-white hover:bg-teal-700">Add buttons</button>
        <button onClick={onDone} className="text-[11px] px-2 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50">Cancel</button>
      </div>
    </div>
  )
}

// Exact position: centre from the centre line, top below the waist; and, for a
// one-sided placement with a twin on the other side, align it with the twin.
function PositionFields({ placement, piece, host, byId, onChange }: {
  placement: Placement
  piece: PatternPiece
  host: PatternPiece
  byId: Map<string, CanvasElement>
  onChange: (p: Placement, tag?: string) => void
}) {
  const { state } = useEditor()
  const d = distances(placement, piece, host, byId)
  const twin = state.placements.find(o => o.id !== placement.id && o.pieceId === placement.pieceId && o.hostId === placement.hostId)
  const field = (label: string, value: number | null, set: (v: number) => void) => value !== null && (
    <label className="flex items-center justify-between text-[11px] text-gray-600">
      {label}
      <span className="flex items-center gap-1">
        <input aria-label={label} type="number" step={0.5} value={value}
          onChange={e => Number.isFinite(parseFloat(e.target.value)) && set(parseFloat(e.target.value))}
          className="w-16 border border-gray-300 rounded px-1 py-0.5 text-[11px]" />cm
      </span>
    </label>
  )
  return (
    <div className="space-y-1">
      {field('Centre from centre line', d.fromCentre, v => onChange(moveTo(placement, piece, host, byId, { fromCentre: v, belowTop: d.belowTop ?? undefined }), `pos:${placement.id}`))}
      {field('Top below the waist', d.belowTop, v => onChange(moveTo(placement, piece, host, byId, { belowTop: v }), `pos:${placement.id}`))}
      {d.toSide !== null && (
        <div className="text-[11px] text-gray-500">{d.toSide < 0 ? 'Crosses the side seam onto the next panel.' : `${d.toSide} cm from the side seam.`}</div>
      )}
      {twin && placement.side && (
        <button onClick={() => onChange({ ...placement, transform: { ...twin.transform } })}
          title="Same position and angle as on the other side, mirrored"
          className="w-full text-[11px] px-2 py-0.5 rounded border border-gray-300 bg-white hover:bg-gray-50">
          Align with other side
        </button>
      )}
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
      <div className="text-[11px] text-gray-500">Drag it to move (it snaps to the side seam and the other side; hold Alt to place freely); drag the round handle to turn it.</div>
      {piece && host && <PositionFields placement={placement} piece={piece} host={host} byId={byId} onChange={(p, tag) => update(p, tag)} />}
      <label className="flex items-center justify-between text-[11px] text-gray-600">
        Rotation
        <span className="flex items-center gap-1">
          <input aria-label="Rotation" type="number" step={5} value={placement.transform.rotation}
            onChange={e => update({ ...placement, transform: { ...placement.transform, rotation: Number(e.target.value) || 0 } }, `rot:${placement.id}`)}
            className="w-14 border border-gray-300 rounded px-1 py-0.5 text-[11px]" />°
        </span>
      </label>
      {hasSides(host) && (
        placement.side ? (
          <div className="flex items-center justify-between gap-2 text-[11px] text-gray-600">
            <span>Only on the wearer's <b>{placement.side}</b></span>
            <button onClick={() => dispatch({ type: 'MIRROR_PLACEMENT', id: placement.id })}
              className="px-2 py-0.5 rounded border border-gray-300 bg-white hover:bg-gray-50">Mirror to other side</button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 text-[11px] text-gray-600">
            <span>🔗 On both sides, mirrored</span>
            <button onClick={() => dispatch({ type: 'UNLINK_PLACEMENT', id: placement.id, newId: crypto.randomUUID() })}
              title="Make the left and right placements independent (asymmetric design)"
              className="px-2 py-0.5 rounded border border-gray-300 bg-white hover:bg-gray-50">Unlink sides</button>
          </div>
        )
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


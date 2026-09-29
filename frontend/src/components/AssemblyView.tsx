import { useEffect, useMemo, useRef, useState } from 'react'
import { useEditor } from '../context/EditorContext'
import type { CanvasElement, SeamConnection, SeamEnd } from '../types'
import type { Affine, Edge } from './assembly/geometry'
import {
  apply, arcPath, edgePath, fitToView, flatLayLayout, gridLayout, invert, isEdge, nearestFraction,
  outlinePath, pieceCentroid, pieceEdges, pointAt, polylinePath, sampleEdge, subPolyline,
} from './assembly/geometry'
import { FOLD_COLOUR, labelColour, prettyLabel } from './assembly/seams'
import SeamsPanel from './assembly/SeamsPanel'

// Assembly: how the pieces go together. Every seam is drawn as an arc between
// the two edges it joins and can be edited — click an edge, then the edge it
// is sewn to, to add one; select a seam to change which part of each edge is
// sewn (drag the handles), the side of the body, the direction, or delete it.

type Mode = 'pieces' | 'flat'

interface Drag { index: number; which: 'from' | 'to'; bound: 0 | 1; gesture: number }

const sameEnd = (a: SeamEnd | null, pieceId: string, edgeId: string) => !!a && a.pieceId === pieceId && a.edgeId === edgeId

export default function AssemblyView() {
  const { state, dispatch } = useEditor()
  const { pieces, elements, connections } = state
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [mode, setMode] = useState<Mode>('pieces')
  const [pending, setPending] = useState<SeamEnd | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [hoverEdge, setHoverEdge] = useState<string | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const gestures = useRef(0)

  useEffect(() => {
    if (!svgRef.current) return
    const obs = new ResizeObserver(([e]) => e && setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    obs.observe(svgRef.current)
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      if (e.key === 'Escape') { setPending(null); setSelected(null) }
      if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); dispatch({ type: 'UNDO' }) }
      if (e.ctrlKey && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); dispatch({ type: 'REDO' }) }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selected !== null) {
        dispatch({ type: 'DELETE_CONNECTION', index: selected })
        setSelected(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, dispatch])

  // A selection can outlive its seam (undo, delete elsewhere).
  useEffect(() => { if (selected !== null && selected >= connections.length) setSelected(null) }, [selected, connections.length])

  const byId = useMemo(() => new Map<string, CanvasElement>(elements.map(e => [e.id, e])), [elements])
  const samples = useMemo(() => {
    const m = new Map<string, ReturnType<typeof sampleEdge>>()
    for (const p of pieces) for (const el of pieceEdges(p, byId)) m.set(el.id, sampleEdge(el))
    return m
  }, [pieces, byId])

  // Laid flat moves pieces whenever seams change, so editing defaults to a
  // stable grid; both are drawn at one scale.
  const screen = useMemo<Map<string, Affine>>(() => {
    if (mode === 'flat' && connections.length) {
      return fitToView(pieces, byId, flatLayLayout(pieces, byId, connections), size.w, size.h)
    }
    return gridLayout(pieces, byId, size.w, size.h)
  }, [mode, pieces, byId, connections, size])

  if (pieces.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
        No pattern pieces to assemble yet.
      </div>
    )
  }

  const endPolyline = (end: SeamEnd) => {
    const s = samples.get(end.edgeId)
    if (!s) return null
    const [lo, hi] = end.range ?? [0, 1]
    return subPolyline(s, Math.min(lo, hi), Math.max(lo, hi))
  }
  const endMid = (end: SeamEnd) => {
    const s = samples.get(end.edgeId)
    const t = screen.get(end.pieceId)
    if (!s || !t) return null
    const [lo, hi] = end.range ?? [0, 1]
    return apply(t, pointAt(s, (lo + hi) / 2))
  }

  const clickEdge = (pieceId: string, el: Edge) => {
    setSelected(null)
    if (!pending || pending.pieceId === pieceId) {
      setPending(sameEnd(pending, pieceId, el.id) ? null : { pieceId, edgeId: el.id })
      return
    }
    const first = byId.get(pending.edgeId)
    const label = (isEdge(first) && first.seamLabel) || el.seamLabel || 'seam'
    const connection: SeamConnection = { label, from: pending, to: { pieceId, edgeId: el.id }, source: 'user' }
    dispatch({ type: 'ADD_CONNECTION', connection })
    setPending(null)
    setSelected(connections.length)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || !svgRef.current) return
    const c = connections[drag.index]
    if (!c) return
    const end = c[drag.which]
    const s = samples.get(end.edgeId)
    const t = screen.get(end.pieceId)
    if (!s || !t) return
    const box = svgRef.current.getBoundingClientRect()
    const local = apply(invert(t), { x: e.clientX - box.left, y: e.clientY - box.top })
    const f = nearestFraction(s, local)
    const [lo, hi] = end.range ?? [0, 1]
    const r: [number, number] = drag.bound === 0 ? [Math.min(f, hi - 0.02), hi] : [lo, Math.max(f, lo + 0.02)]
    const { range: _whole, ...rest } = end
    const next: SeamEnd = r[0] <= 0.005 && r[1] >= 0.995 ? rest : { ...rest, range: r }
    dispatch({ type: 'UPDATE_CONNECTION', index: drag.index, connection: { ...c, [drag.which]: next }, tag: `drag:${drag.gesture}` })
  }

  const sel = selected !== null ? connections[selected] : undefined
  const focus = hovered !== null ? connections[hovered] : sel
  const focusEdges = new Set(focus ? [focus.from.edgeId, focus.to.edgeId] : [])

  return (
    <div className="flex-1 flex overflow-hidden bg-gray-50 relative">
      <svg
        ref={svgRef}
        className="flex-1 select-none"
        style={{ background: '#f9fafb', touchAction: 'none' }}
        onPointerMove={onPointerMove}
        onPointerUp={() => setDrag(null)}
        onPointerLeave={() => setDrag(null)}
        onClick={e => { if (e.target === e.currentTarget) { setPending(null); setSelected(null) } }}
        data-testid="assembly-svg"
      >
        {pieces.map(piece => {
          const t = screen.get(piece.id)
          if (!t) return null
          const label = apply(t, pieceCentroid(piece, byId))
          return (
            <g key={piece.id}>
              <path d={outlinePath(piece, byId, t)} fill="#f0f9ff" fillOpacity={0.7} stroke="none" />
              {elements.filter(el => el.type === 'grain-line' && el.pieceId === piece.id).map(el => {
                if (el.type !== 'grain-line') return null
                const a = apply(t, el.start), b = apply(t, el.end)
                return <line key={el.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#9ca3af" strokeWidth={0.8} strokeDasharray="3 3" />
              })}
              {pieceEdges(piece, byId).map(el => {
                const fold = el.type === 'line' && el.isFold
                const isPending = sameEnd(pending, piece.id, el.id)
                const hot = isPending || hoverEdge === el.id || focusEdges.has(el.id)
                const d = edgePath(el, t)
                return (
                  <g key={el.id}>
                    <path d={d} fill="none" stroke={isPending ? '#0f766e' : fold ? FOLD_COLOUR : labelColour(el.seamLabel ?? '')}
                      strokeWidth={isPending ? 4 : hot ? 3 : fold ? 1 : 1.5} strokeDasharray={fold ? '4 3' : undefined} />
                    {/* wide invisible hit area */}
                    <path d={d} fill="none" stroke="transparent" strokeWidth={12} style={{ cursor: 'pointer' }}
                      data-edge={el.id}
                      onClick={e => { e.stopPropagation(); clickEdge(piece.id, el) }}
                      onMouseEnter={() => setHoverEdge(el.id)}
                      onMouseLeave={() => setHoverEdge(null)}>
                      <title>{`${piece.name} · ${el.seamLabel ? prettyLabel(el.seamLabel) : fold ? 'fold' : 'edge'}`}</title>
                    </path>
                  </g>
                )
              })}
              <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fontSize={11} fontWeight={500} fill="#374151"
                style={{ pointerEvents: 'none' }}>
                {piece.name}{piece.cutQty > 1 ? ` ×${piece.cutQty}` : ''}
              </text>
            </g>
          )
        })}

        {/* Seams: the sewn stretch of each edge, and an arc joining them. */}
        {connections.map((c, i) => {
          const a = endMid(c.from), b = endMid(c.to)
          if (!a || !b) return null
          const active = i === selected || i === hovered
          const colour = labelColour(c.label)
          return (
            <g key={i}>
              {active && [c.from, c.to].map((end, k) => {
                const pts = endPolyline(end)
                const t = screen.get(end.pieceId)
                return pts && t ? <path key={k} d={polylinePath(pts, t)} fill="none" stroke={colour} strokeWidth={6} strokeOpacity={0.45} style={{ pointerEvents: 'none' }} /> : null
              })}
              <path d={arcPath(a, b)} fill="none" stroke={colour} strokeWidth={active ? 2.5 : 1.5}
                strokeDasharray={active ? undefined : '4 4'} strokeOpacity={active ? 0.95 : 0.55} style={{ pointerEvents: 'none' }} />
              <path d={arcPath(a, b)} fill="none" stroke="transparent" strokeWidth={10} style={{ cursor: 'pointer' }}
                data-seam={i}
                onClick={e => { e.stopPropagation(); setPending(null); setSelected(i === selected ? null : i) }}
                onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)} />
            </g>
          )
        })}

        {/* Range handles on the selected seam's two edges. */}
        {sel && selected !== null && (['from', 'to'] as const).map(which => {
          const end = sel[which]
          const s = samples.get(end.edgeId)
          const t = screen.get(end.pieceId)
          if (!s || !t) return null
          const [lo, hi] = end.range ?? [0, 1]
          return ([lo, hi] as const).map((f, bound) => {
            const p = apply(t, pointAt(s, f))
            return (
              <circle key={`${which}${bound}`} cx={p.x} cy={p.y} r={6} fill="white" stroke={labelColour(sel.label)} strokeWidth={2}
                style={{ cursor: 'grab' }} data-handle={`${which}-${bound}`}
                onPointerDown={e => {
                  e.stopPropagation()
                  ;(e.target as Element).setPointerCapture?.(e.pointerId)
                  setDrag({ index: selected, which, bound: bound as 0 | 1, gesture: ++gestures.current })
                }} />
            )
          })
        })}
      </svg>

      {connections.length > 0 && (
        <div className="absolute top-2 left-2 flex rounded border border-gray-300 bg-white shadow-sm text-xs overflow-hidden">
          {(['pieces', 'flat'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)}
              className={`px-2 py-1 ${mode === m ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:bg-gray-50'}`}>
              {m === 'pieces' ? 'Pieces' : 'Laid flat'}
            </button>
          ))}
        </div>
      )}

      <SeamsPanel pieces={pieces} byId={byId} selected={selected} onSelect={setSelected} onHover={setHovered} pending={pending} />
    </div>
  )
}

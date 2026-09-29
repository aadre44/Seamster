import { useEffect, useMemo, useRef, useState } from 'react'
import { useEditor } from '../context/EditorContext'
import type { CanvasElement, PatternPiece, Placement, SeamConnection, SeamEnd } from '../types'
import type { Affine, Edge, Pt } from './assembly/geometry'
import {
  apply, arcPath, compose, edgePath, fitToView, flatLayLayout, gridLayout, insidePolygon, invert, isEdge,
  nearestFraction, outlinePath, pieceCentroid, pieceEdges, pointAt, polylinePath, sampleEdge, subPolyline,
} from './assembly/geometry'
import { FOLD_COLOUR, labelColour, prettyLabel } from './assembly/seams'
import SeamsPanel from './assembly/SeamsPanel'
import { pieceCenter, placementMatrix } from '../utils/placement'

// Assembly: how the pieces go together. Every seam is drawn as an arc between
// the two edges it joins and can be edited — click an edge, then the edge it
// is sewn to, to add one; select a seam to change which part of each edge is
// sewn (drag the handles), the side of the body, the direction, or delete it.
// Pieces applied onto another (pockets) are dragged onto their host; placed,
// they move with a drag, rotate with their handle, and their edges toggle
// between stitched and open.

type Mode = 'pieces' | 'flat'

type Drag =
  | { kind: 'range'; index: number; which: 'from' | 'to'; bound: 0 | 1; gesture: number }
  | { kind: 'place'; pieceId: string; at: Pt; moved: boolean }
  | { kind: 'move'; id: string; gesture: number; start: Pt; dx: number; dy: number }
  | { kind: 'rotate'; id: string; gesture: number; center: Pt; startAngle: number; rotation: number }

const sameEnd = (a: SeamEnd | null, pieceId: string, edgeId: string) => !!a && a.pieceId === pieceId && a.edgeId === edgeId
const deg = (r: number) => (r * 180) / Math.PI

// A new placement stitches every edge but the mouth (the top-most edge).
function defaultStitched(piece: PatternPiece, byId: Map<string, CanvasElement>): string[] {
  const edges = pieceEdges(piece, byId)
  if (edges.length < 2) return edges.map(e => e.id)
  const mouth = edges.reduce((m, e) => ((e.start.y + e.end.y) / 2 < (m.start.y + m.end.y) / 2 ? e : m))
  return edges.filter(e => e !== mouth).map(e => e.id)
}

export default function AssemblyView() {
  const { state, dispatch } = useEditor()
  const { pieces, elements, connections, placements } = state
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [mode, setMode] = useState<Mode>('pieces')
  const [pending, setPending] = useState<SeamEnd | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [selPlacement, setSelPlacement] = useState<string | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [hoverEdge, setHoverEdge] = useState<string | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const gestures = useRef(0)

  const selectSeam = (i: number | null) => { setSelected(i); if (i !== null) setSelPlacement(null) }
  const selectPlacement = (id: string | null) => { setSelPlacement(id); if (id !== null) { setSelected(null); setPending(null) } }

  useEffect(() => {
    if (!svgRef.current) return
    const obs = new ResizeObserver(([e]) => e && setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    obs.observe(svgRef.current)
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      if (e.key === 'Escape') { setPending(null); setSelected(null); setSelPlacement(null) }
      if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); dispatch({ type: 'UNDO' }) }
      if (e.ctrlKey && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); dispatch({ type: 'REDO' }) }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selected !== null) { dispatch({ type: 'DELETE_CONNECTION', index: selected }); setSelected(null) }
        if (selPlacement !== null) { dispatch({ type: 'DELETE_PLACEMENT', id: selPlacement }); setSelPlacement(null) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, selPlacement, dispatch])

  // A selection can outlive what it selects (undo, delete elsewhere).
  useEffect(() => { if (selected !== null && selected >= connections.length) setSelected(null) }, [selected, connections.length])
  useEffect(() => { if (selPlacement !== null && !placements.some(p => p.id === selPlacement)) setSelPlacement(null) }, [selPlacement, placements])

  const byId = useMemo(() => new Map<string, CanvasElement>(elements.map(e => [e.id, e])), [elements])
  const pieceById = useMemo(() => new Map(pieces.map(p => [p.id, p])), [pieces])
  const samples = useMemo(() => {
    const m = new Map<string, ReturnType<typeof sampleEdge>>()
    for (const p of pieces) for (const el of pieceEdges(p, byId)) m.set(el.id, sampleEdge(el))
    return m
  }, [pieces, byId])

  // Placed pieces are drawn on their host, not laid out on their own.
  const placedIds = useMemo(() => new Set(placements.filter(p => pieceById.has(p.hostId)).map(p => p.pieceId)), [placements, pieceById])
  const laidOut = useMemo(() => pieces.filter(p => !placedIds.has(p.id)), [pieces, placedIds])

  // Laid flat moves pieces whenever seams change, so editing defaults to a
  // stable grid; both are drawn at one scale.
  const layout = useMemo<Map<string, Affine>>(() => {
    if (mode === 'flat' && connections.length) {
      return fitToView(laidOut, byId, flatLayLayout(laidOut, byId, connections), size.w, size.h)
    }
    return gridLayout(laidOut, byId, size.w, size.h)
  }, [mode, laidOut, byId, connections, size])

  // Screen transform of every piece, placed ones through their host.
  const screen = useMemo(() => {
    const m = new Map(layout)
    for (const pl of placements) {
      const host = layout.get(pl.hostId)
      const piece = pieceById.get(pl.pieceId)
      if (host && piece) m.set(pl.pieceId, compose(host, placementMatrix(pl, pieceCenter(piece, byId))))
    }
    return m
  }, [layout, placements, pieceById, byId])

  if (pieces.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
        No pattern pieces to assemble yet.
      </div>
    )
  }

  const svgPoint = (e: { clientX: number; clientY: number }): Pt => {
    const box = svgRef.current!.getBoundingClientRect()
    return { x: e.clientX - box.left, y: e.clientY - box.top }
  }
  const outlineScreen = (piece: PatternPiece): Pt[] => {
    const t = screen.get(piece.id)
    return t ? pieceEdges(piece, byId).flatMap(el => (samples.get(el.id)?.pts ?? []).map(p => apply(t, p))) : []
  }
  const hostAt = (p: Pt, except: string) => laidOut.find(h => h.id !== except && insidePolygon(outlineScreen(h), p))

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
    const pl = placements.find(p => p.pieceId === pieceId)
    if (pl) {
      // A placed piece's edges are stitched down or left open.
      if (selPlacement !== pl.id) { selectPlacement(pl.id); return }
      const stitched = pl.stitched.includes(el.id) ? pl.stitched.filter(id => id !== el.id) : [...pl.stitched, el.id]
      dispatch({ type: 'UPDATE_PLACEMENT', placement: { ...pl, stitched, source: 'user' } })
      return
    }
    selectSeam(null)
    setSelPlacement(null)
    if (!pending || pending.pieceId === pieceId) {
      setPending(sameEnd(pending, pieceId, el.id) ? null : { pieceId, edgeId: el.id })
      return
    }
    const first = byId.get(pending.edgeId)
    const label = (isEdge(first) && first.seamLabel) || el.seamLabel || 'seam'
    const connection: SeamConnection = { label, from: pending, to: { pieceId, edgeId: el.id }, source: 'user' }
    dispatch({ type: 'ADD_CONNECTION', connection })
    setPending(null)
    selectSeam(connections.length)
  }

  // Where a screen point falls in a host's canvas coordinates.
  const inHost = (hostId: string, p: Pt): Pt | null => {
    const t = layout.get(hostId)
    return t ? apply(invert(t), p) : null
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || !svgRef.current) return
    const p = svgPoint(e)
    if (drag.kind === 'range') {
      const c = connections[drag.index]
      if (!c) return
      const end = c[drag.which]
      const s = samples.get(end.edgeId)
      const t = screen.get(end.pieceId)
      if (!s || !t) return
      const f = nearestFraction(s, apply(invert(t), p))
      const [lo, hi] = end.range ?? [0, 1]
      const r: [number, number] = drag.bound === 0 ? [Math.min(f, hi - 0.02), hi] : [lo, Math.max(f, lo + 0.02)]
      const { range: _whole, ...rest } = end
      const next: SeamEnd = r[0] <= 0.005 && r[1] >= 0.995 ? rest : { ...rest, range: r }
      dispatch({ type: 'UPDATE_CONNECTION', index: drag.index, connection: { ...c, [drag.which]: next }, tag: `drag:${drag.gesture}` })
      return
    }
    if (drag.kind === 'place') {
      setDrag({ ...drag, at: p, moved: drag.moved || Math.hypot(p.x - drag.at.x, p.y - drag.at.y) > 4 })
      return
    }
    const pl = placements.find(x => x.id === drag.id)
    const q = pl && inHost(pl.hostId, p)
    if (!pl || !q) return
    if (drag.kind === 'move') {
      const transform = { ...pl.transform, dx: drag.dx + q.x - drag.start.x, dy: drag.dy + q.y - drag.start.y }
      dispatch({ type: 'UPDATE_PLACEMENT', placement: { ...pl, transform, source: 'user' }, tag: `move:${drag.gesture}` })
    } else {
      const a = deg(Math.atan2(q.y - drag.center.y, q.x - drag.center.x))
      const rotation = Math.round((drag.rotation + a - drag.startAngle) / 5) * 5
      dispatch({ type: 'UPDATE_PLACEMENT', placement: { ...pl, transform: { ...pl.transform, rotation: ((rotation % 360) + 360) % 360 }, source: 'user' }, tag: `rotate:${drag.gesture}` })
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    if (drag?.kind === 'place' && drag.moved) {
      const p = svgPoint(e)
      const piece = pieceById.get(drag.pieceId)
      const host = piece && hostAt(p, piece.id)
      const q = host && inHost(host.id, p)
      if (piece && host && q) {
        const c = pieceCenter(piece, byId)
        const placement: Placement = {
          id: crypto.randomUUID(),
          pieceId: piece.id,
          hostId: host.id,
          transform: { dx: q.x - c.x, dy: q.y - c.y, rotation: 0 },
          stitched: defaultStitched(piece, byId),
          source: 'user',
        }
        dispatch({ type: 'ADD_PLACEMENT', placement })
        selectPlacement(placement.id)
      }
    }
    setDrag(null)
  }

  const sel = selected !== null ? connections[selected] : undefined
  const focus = hovered !== null ? connections[hovered] : sel
  const focusEdges = new Set(focus ? [focus.from.edgeId, focus.to.edgeId] : [])
  const hostTarget = drag?.kind === 'place' && drag.moved ? hostAt(drag.at, drag.pieceId) : undefined

  const drawPiece = (piece: PatternPiece, placed?: Placement) => {
    const t = screen.get(piece.id)
    if (!t) return null
    const label = apply(t, pieceCentroid(piece, byId))
    const inside = piece.layer === 'inside'
    const active = placed && placed.id === selPlacement
    return (
      <g key={piece.id} data-piece={piece.id}>
        <path d={outlinePath(piece, byId, t)}
          fill={placed ? (inside ? '#e5e7eb' : '#fde68a') : hostTarget?.id === piece.id ? '#ccfbf1' : '#f0f9ff'}
          fillOpacity={placed ? 0.75 : 0.7}
          stroke={active ? '#0f766e' : 'none'} strokeWidth={active ? 1 : 0}
          style={{ cursor: placed ? 'move' : 'grab' }}
          onPointerDown={e => {
            if (e.button !== 0) return
            e.stopPropagation()
            ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
            if (placed) {
              const q = inHost(placed.hostId, svgPoint(e))
              selectPlacement(placed.id)
              if (q) setDrag({ kind: 'move', id: placed.id, gesture: ++gestures.current, start: q, dx: placed.transform.dx, dy: placed.transform.dy })
            } else {
              setDrag({ kind: 'place', pieceId: piece.id, at: svgPoint(e), moved: false })
            }
          }}
        />
        {!placed && elements.filter(el => el.type === 'grain-line' && el.pieceId === piece.id).map(el => {
          if (el.type !== 'grain-line') return null
          const a = apply(t, el.start), b = apply(t, el.end)
          return <line key={el.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#9ca3af" strokeWidth={0.8} strokeDasharray="3 3" style={{ pointerEvents: 'none' }} />
        })}
        {pieceEdges(piece, byId).map(el => {
          const fold = el.type === 'line' && el.isFold
          const isPending = sameEnd(pending, piece.id, el.id)
          const hot = isPending || hoverEdge === el.id || focusEdges.has(el.id)
          const stitched = placed?.stitched.includes(el.id)
          const d = edgePath(el, t)
          const stroke = placed ? (stitched ? '#92400e' : '#a8a29e') : isPending ? '#0f766e' : fold ? FOLD_COLOUR : labelColour(el.seamLabel ?? '')
          return (
            <g key={el.id}>
              <path d={d} fill="none" stroke={stroke}
                strokeWidth={isPending ? 4 : hot ? 3 : placed ? (stitched ? 1.8 : 1.2) : fold ? 1 : 1.5}
                strokeDasharray={placed ? (stitched ? '5 2' : '2 3') : fold ? '4 3' : undefined}
                style={{ pointerEvents: 'none' }} />
              {/* wide invisible hit area */}
              <path d={d} fill="none" stroke="transparent" strokeWidth={12} style={{ cursor: 'pointer' }}
                data-edge={el.id}
                onClick={e => { e.stopPropagation(); clickEdge(piece.id, el) }}
                onMouseEnter={() => setHoverEdge(el.id)}
                onMouseLeave={() => setHoverEdge(null)}>
                <title>{placed
                  ? `${piece.name} · ${stitched ? 'stitched' : 'open'}${active ? ' (click to toggle)' : ''}`
                  : `${piece.name} · ${el.seamLabel ? prettyLabel(el.seamLabel) : fold ? 'fold' : 'edge'}`}</title>
              </path>
            </g>
          )
        })}
        <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fontSize={placed ? 9 : 11} fontWeight={500}
          fill={placed ? '#78350f' : '#374151'} style={{ pointerEvents: 'none' }}>
          {piece.name}{!placed && piece.cutQty > 1 ? ` ×${piece.cutQty}` : ''}
        </text>
      </g>
    )
  }

  const placedSel = placements.find(p => p.id === selPlacement)
  const rotateHandle = (() => {
    if (!placedSel) return null
    const piece = pieceById.get(placedSel.pieceId)
    const t = screen.get(placedSel.pieceId)
    if (!piece || !t) return null
    const c = pieceCenter(piece, byId)
    const pts = pieceEdges(piece, byId).flatMap(el => [el.start, el.end])
    const top = Math.min(...pts.map(p => p.y))
    const center = apply(t, c)
    const knob = apply(t, { x: c.x, y: top - 3 })
    return (
      <g>
        <line x1={center.x} y1={center.y} x2={knob.x} y2={knob.y} stroke="#0f766e" strokeWidth={1} strokeDasharray="2 2" style={{ pointerEvents: 'none' }} />
        <circle cx={knob.x} cy={knob.y} r={6} fill="white" stroke="#0f766e" strokeWidth={2} style={{ cursor: 'grab' }} data-handle="rotate"
          onPointerDown={e => {
            e.stopPropagation()
            ;(e.target as Element).setPointerCapture?.(e.pointerId)
            const hc = inHost(placedSel.hostId, center)
            const q = inHost(placedSel.hostId, svgPoint(e))
            if (!hc || !q) return
            setDrag({ kind: 'rotate', id: placedSel.id, gesture: ++gestures.current, center: hc, startAngle: deg(Math.atan2(q.y - hc.y, q.x - hc.x)), rotation: placedSel.transform.rotation })
          }} />
      </g>
    )
  })()

  // While dragging a piece to place it, a ghost follows the pointer.
  const ghost = (() => {
    if (drag?.kind !== 'place' || !drag.moved) return null
    const piece = pieceById.get(drag.pieceId)
    const t = piece && screen.get(piece.id)
    if (!piece || !t) return null
    const c = apply(t, pieceCenter(piece, byId))
    const g = compose({ a: 1, b: 0, c: 0, d: 1, tx: drag.at.x - c.x, ty: drag.at.y - c.y }, t)
    return <path d={outlinePath(piece, byId, g)} fill="#fde68a" fillOpacity={0.5} stroke="#b45309" strokeDasharray="4 3" style={{ pointerEvents: 'none' }} />
  })()

  return (
    <div className="flex-1 flex overflow-hidden bg-gray-50 relative">
      <svg
        ref={svgRef}
        className="flex-1 select-none"
        style={{ background: '#f9fafb', touchAction: 'none' }}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setDrag(null)}
        onClick={e => { if (e.target === e.currentTarget) { setPending(null); setSelected(null); setSelPlacement(null) } }}
        data-testid="assembly-svg"
      >
        {laidOut.map(piece => drawPiece(piece))}
        {placements.map(pl => {
          const piece = pieceById.get(pl.pieceId)
          return piece && layout.has(pl.hostId) ? drawPiece(piece, pl) : null
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
                onClick={e => { e.stopPropagation(); setPending(null); selectSeam(i === selected ? null : i) }}
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
                  setDrag({ kind: 'range', index: selected, which, bound: bound as 0 | 1, gesture: ++gestures.current })
                }} />
            )
          })
        })}
        {rotateHandle}
        {ghost}
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

      <SeamsPanel pieces={pieces} byId={byId} selected={selected} onSelect={selectSeam} onHover={setHovered} pending={pending}
        selectedPlacement={selPlacement} onSelectPlacement={selectPlacement} />
    </div>
  )
}

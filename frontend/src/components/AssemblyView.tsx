import { useEffect, useMemo, useRef, useState } from 'react'
import { useEditor } from '../context/EditorContext'
import type { CanvasElement, PatternPiece, Placement, SeamConnection, SeamEnd } from '../types'
import type { Affine, Edge, Pt } from './assembly/geometry'
import {
  apply, arcPath, compose, edgePath, fitToView, flatLayLayout, gridLayout, insidePolygon, invert, isEdge,
  nearestFraction, outlinePath, pieceCentroid, pieceEdges, pointAt, polylinePath, sampleEdge, subPolyline,
} from './assembly/geometry'
import { garmentLayout } from './assembly/garmentLayout'
import type { CopyRef, Side } from './assembly/garmentLayout'
import { FOLD_COLOUR, labelColour, prettyLabel } from './assembly/seams'
import SeamsPanel from './assembly/SeamsPanel'
import { pieceCenter, placementMatrix } from '../utils/placement'
import { distances, placedBox, snapPlacement } from './assembly/placementAids'
import type { Guide } from './assembly/placementAids'

// Assembly: how the pieces go together.
//
// The Garment view (default) shows every cut copy laid out around the body —
// R back | R front | L front | L back, sleeves above, trims in a tray below —
// each next to what it is sewn to, so pockets can go on one side only or
// straddle a seam. Pieces shows each piece once; Laid flat opens them along
// their seams.
//
// Seams are arcs between the edges they join (none between neighbours that
// visibly touch). Click an edge, then the edge it is sewn to, to add one:
// between two copies on the same side it is sewn on both sides (symmetric);
// across sides it is that pair only. Select a seam to drag its range handles or
// edit it in the panel. Drag a piece onto another to place it (on the copy you
// drop it on); placed pieces move by dragging and turn with their handle.

type Mode = 'garment' | 'pieces' | 'flat'

// One drawn piece: a copy in the Garment view, or the piece itself.
interface Item { key: string; piece: PatternPiece; copy: CopyRef | null }

type Drag =
  | { kind: 'range'; index: number; which: 'from' | 'to'; item: string; bound: 0 | 1; gesture: number }
  | { kind: 'place'; pieceId: string; item: string; at: Pt; moved: boolean }
  | { kind: 'move'; id: string; host: string; gesture: number; start: Pt; dx: number; dy: number }
  | { kind: 'rotate'; id: string; host: string; gesture: number; center: Pt; startAngle: number; rotation: number }

interface Pending { end: SeamEnd; item: string; side: Side | null }

const deg = (r: number) => (r * 180) / Math.PI
const sideLabel = (s: Side | null | undefined) => (s === 'left' ? 'L' : s === 'right' ? 'R' : '')

// A new placement stitches every edge but the mouth (the top-most edge).
function defaultStitched(piece: PatternPiece, byId: Map<string, CanvasElement>): string[] {
  const edges = pieceEdges(piece, byId)
  if (edges.length < 2) return edges.map(e => e.id)
  const mouth = edges.reduce((m, e) => ((e.start.y + e.end.y) / 2 < (m.start.y + m.end.y) / 2 ? e : m))
  return edges.filter(e => e !== mouth).map(e => e.id)
}

// Which drawn copies of a seam end take part: a named side or sleeve half
// narrows it, else every copy (paired by side below).
function endItems(items: Item[], end: SeamEnd, other: Item[]): Item[] {
  return items.filter(i => i.piece.id === end.pieceId
    && (!end.side || !i.copy?.side || i.copy.side === end.side)
    && (!i.copy?.half || (end.half ? i.copy.half === end.half : i.copy.half === (other[0] && /back/i.test(other[0].piece.name) ? 'back' : 'front'))))
}

export default function AssemblyView() {
  const { state, dispatch } = useEditor()
  const { pieces, elements, connections, placements } = state
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [mode, setMode] = useState<Mode>('garment')
  const [centre, setCentre] = useState<'front' | 'back'>('front')
  const [pending, setPending] = useState<Pending | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [selPlacement, setSelPlacement] = useState<{ id: string; host: string } | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [hoverEdge, setHoverEdge] = useState<string | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  // While a placed piece is dragged: snap guides and its distances (host coords).
  const [guides, setGuides] = useState<{ host: string; list: Guide[]; placement: string } | null>(null)
  const gestures = useRef(0)

  const selectSeam = (i: number | null) => { setSelected(i); if (i !== null) setSelPlacement(null) }
  const selectPlacement = (id: string | null, host?: string) => {
    setSelPlacement(id ? { id, host: host ?? selPlacement?.host ?? '' } : null)
    if (id !== null) { setSelected(null); setPending(null) }
  }

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
        if (selPlacement !== null) { dispatch({ type: 'DELETE_PLACEMENT', id: selPlacement.id }); setSelPlacement(null) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, selPlacement, dispatch])

  // A selection can outlive what it selects (undo, delete elsewhere).
  useEffect(() => { if (selected !== null && selected >= connections.length) setSelected(null) }, [selected, connections.length])
  useEffect(() => { if (selPlacement !== null && !placements.some(p => p.id === selPlacement.id)) setSelPlacement(null) }, [selPlacement, placements])

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

  // Items and their screen transforms.
  const { items, screen } = useMemo(() => {
    if (mode === 'garment') {
      const g = garmentLayout(pieces, elements, connections, { centre, exclude: placedIds })
      const items: Item[] = g.copies.map(c => ({ key: c.key, piece: pieceById.get(c.pieceId)!, copy: c }))
      const pts = [...g.outlines.values()].flat()
      const pad = 36
      if (!pts.length) return { items, screen: new Map<string, Affine>() }
      const minX = Math.min(...pts.map(p => p.x)), maxX = Math.max(...pts.map(p => p.x))
      const minY = Math.min(...pts.map(p => p.y)), maxY = Math.max(...pts.map(p => p.y))
      const s = Math.min((size.w - 2 * pad) / Math.max(maxX - minX, 1e-6), (size.h - 2 * pad - 24) / Math.max(maxY - minY, 1e-6))
      const view: Affine = { a: s, b: 0, c: 0, d: s, tx: pad + (size.w - 2 * pad - (maxX - minX) * s) / 2 - minX * s, ty: pad + 24 - minY * s }
      return { items, screen: new Map(items.map(i => [i.key, compose(view, g.transforms.get(i.key)!)])) }
    }
    const items: Item[] = laidOut.map(p => ({ key: p.id, piece: p, copy: null }))
    const layout = mode === 'flat' && connections.length
      ? fitToView(laidOut, byId, flatLayLayout(laidOut, byId, connections), size.w, size.h)
      : gridLayout(laidOut, byId, size.w, size.h)
    return { items, screen: layout }
  }, [mode, centre, pieces, elements, connections, placedIds, laidOut, pieceById, byId, size])

  // Placed pieces: drawn on each host copy they apply to (a pair on both sides).
  const placedItems = useMemo(() => placements.flatMap(pl => {
    const piece = pieceById.get(pl.pieceId)
    if (!piece) return []
    return items
      .filter(h => h.piece.id === pl.hostId && (h.copy?.role !== 'sleeve' || h.copy.half !== 'back')
        && (!pl.side || !h.copy?.side || h.copy.side === pl.side))
      .map(h => ({ pl, piece, host: h, key: `${pl.id}@${h.key}`, t: compose(screen.get(h.key)!, placementMatrix(pl, pieceCenter(piece, byId))) }))
  }), [placements, items, screen, pieceById, byId])
  const placedT = useMemo(() => new Map(placedItems.map(p => [p.key, p.t])), [placedItems])
  const tOf = (key: string) => screen.get(key) ?? placedT.get(key)

  // Seam arcs: each connection between the copies that take part, paired by side.
  const seamPairs = useMemo(() => connections.map(c => {
    const fromAll = items.filter(i => i.piece.id === c.from.pieceId)
    const toAll = items.filter(i => i.piece.id === c.to.pieceId)
    const froms = endItems(items, c.from, toAll)
    const tos = endItems(items, c.to, fromAll)
    const pairs: [Item, Item][] = []
    for (const a of froms) {
      const partner = c.from.side || c.to.side
        ? tos[0]
        : tos.find(b => !a.copy?.side || !b.copy?.side || a.copy.side === b.copy.side)
      if (partner) pairs.push([a, partner])
    }
    return pairs
  }), [connections, items])

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
  const outlineScreen = (item: Item): Pt[] => {
    const t = screen.get(item.key)
    return t ? pieceEdges(item.piece, byId).flatMap(el => (samples.get(el.id)?.pts ?? []).map(p => apply(t, p))) : []
  }
  const hostAt = (p: Pt, exceptPiece: string) => items.find(h => h.piece.id !== exceptPiece && insidePolygon(outlineScreen(h), p))

  const endPolyline = (end: SeamEnd) => {
    const s = samples.get(end.edgeId)
    if (!s) return null
    const [lo, hi] = end.range ?? [0, 1]
    return subPolyline(s, Math.min(lo, hi), Math.max(lo, hi))
  }
  const endMid = (end: SeamEnd, key: string) => {
    const s = samples.get(end.edgeId)
    const t = tOf(key)
    if (!s || !t) return null
    const [lo, hi] = end.range ?? [0, 1]
    return apply(t, pointAt(s, (lo + hi) / 2))
  }

  const clickEdge = (item: Item, el: Edge, placedKey?: string) => {
    const pl = placedKey ? placedItems.find(p => p.key === placedKey)?.pl : undefined
    if (pl && placedKey) {
      // A placed piece's edges are stitched down or left open.
      if (selPlacement?.id !== pl.id) { selectPlacement(pl.id, placedKey.split('@')[1]); return }
      const stitched = pl.stitched.includes(el.id) ? pl.stitched.filter(id => id !== el.id) : [...pl.stitched, el.id]
      dispatch({ type: 'UPDATE_PLACEMENT', placement: { ...pl, stitched, source: 'user' } })
      return
    }
    selectSeam(null)
    setSelPlacement(null)
    const here: Pending = { end: { pieceId: item.piece.id, edgeId: el.id }, item: item.key, side: item.copy?.side ?? null }
    if (!pending || pending.end.pieceId === item.piece.id) {
      setPending(pending && pending.item === item.key && pending.end.edgeId === el.id ? null : here)
      return
    }
    const first = byId.get(pending.end.edgeId)
    const label = (isEdge(first) && first.seamLabel) || el.seamLabel || 'seam'
    // Same side (or a piece shown once): sewn on both sides. Across sides: that pair only.
    const across = pending.side && here.side && pending.side !== here.side
    const connection: SeamConnection = {
      label,
      from: across ? { ...pending.end, side: pending.side! } : pending.end,
      to: across ? { ...here.end, side: here.side! } : here.end,
      source: 'user',
    }
    dispatch({ type: 'ADD_CONNECTION', connection })
    setPending(null)
    selectSeam(connections.length)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || !svgRef.current) return
    const p = svgPoint(e)
    if (drag.kind === 'range') {
      const c = connections[drag.index]
      if (!c) return
      const end = c[drag.which]
      const s = samples.get(end.edgeId)
      const t = tOf(drag.item)
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
    const t = screen.get(drag.host)
    if (!pl || !t) return
    const q = apply(invert(t), p)
    if (drag.kind === 'move') {
      const raw = { ...pl, transform: { ...pl.transform, dx: drag.dx + q.x - drag.start.x, dy: drag.dy + q.y - drag.start.y } }
      const piece = pieceById.get(pl.pieceId), host = pieceById.get(pl.hostId)
      // Snap onto the side seam, midway to it, or level with the twin; show the guides.
      const twins = placements.filter(o => o.id !== pl.id && o.pieceId === pl.pieceId && o.hostId === pl.hostId)
      const snap = piece && host && !e.altKey ? snapPlacement(raw, piece, host, byId, twins) : null
      setGuides(snap ? { host: drag.host, list: snap.guides, placement: pl.id } : { host: drag.host, list: [], placement: pl.id })
      const transform = snap ? { ...raw.transform, dx: snap.dx, dy: snap.dy } : raw.transform
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
      const t = host && screen.get(host.key)
      if (piece && host && t) {
        const q = apply(invert(t), p)
        const c = pieceCenter(piece, byId)
        // On the copy it was dropped on (a piece with two copies), else plain.
        const twoCopies = host.piece.cutQty >= 2 || host.piece.onFold
        const placement: Placement = {
          id: crypto.randomUUID(),
          pieceId: piece.id,
          hostId: host.piece.id,
          transform: { dx: q.x - c.x, dy: q.y - c.y, rotation: 0 },
          stitched: defaultStitched(piece, byId),
          source: 'user',
          ...(twoCopies && host.copy?.side ? { side: host.copy.side } : {}),
        }
        dispatch({ type: 'ADD_PLACEMENT', placement })
        selectPlacement(placement.id, host.key)
      }
    }
    setDrag(null)
    setGuides(null)
  }

  const sel = selected !== null ? connections[selected] : undefined
  const focus = hovered !== null ? connections[hovered] : sel
  const focusEdges = new Set(focus ? [focus.from.edgeId, focus.to.edgeId] : [])
  const hostTarget = drag?.kind === 'place' && drag.moved ? hostAt(drag.at, drag.pieceId) : undefined

  const drawPiece = (item: Item, t: Affine, placed?: { pl: Placement; key: string; host: Item }) => {
    const { piece } = item
    const label = apply(t, pieceCentroid(piece, byId))
    const inside = piece.layer === 'inside'
    const active = placed && placed.pl.id === selPlacement?.id
    const key = placed?.key ?? item.key
    return (
      <g key={key} data-piece={piece.id} data-item={key}>
        <path d={outlinePath(piece, byId, t)}
          fill={placed ? (inside ? '#e5e7eb' : '#fde68a') : hostTarget?.key === item.key ? '#ccfbf1' : item.copy?.role === 'tray' ? '#f5f5f4' : '#f0f9ff'}
          fillOpacity={placed ? 0.75 : 0.7}
          stroke={active ? '#0f766e' : 'none'} strokeWidth={active ? 1 : 0}
          style={{ cursor: placed ? 'move' : 'grab' }}
          onPointerDown={e => {
            if (e.button !== 0) return
            e.stopPropagation()
            ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
            if (placed) {
              const ht = screen.get(placed.host.key)
              selectPlacement(placed.pl.id, placed.host.key)
              if (ht) setDrag({ kind: 'move', id: placed.pl.id, host: placed.host.key, gesture: ++gestures.current, start: apply(invert(ht), svgPoint(e)), dx: placed.pl.transform.dx, dy: placed.pl.transform.dy })
            } else {
              setDrag({ kind: 'place', pieceId: piece.id, item: item.key, at: svgPoint(e), moved: false })
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
          const isPending = pending?.item === item.key && pending.end.edgeId === el.id
          const hot = isPending || hoverEdge === `${key}|${el.id}` || focusEdges.has(el.id)
          const stitched = placed?.pl.stitched.includes(el.id)
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
                onClick={e => { e.stopPropagation(); clickEdge(item, el, placed?.key) }}
                onMouseEnter={() => setHoverEdge(`${key}|${el.id}`)}
                onMouseLeave={() => setHoverEdge(null)}>
                <title>{placed
                  ? `${piece.name} · ${stitched ? 'stitched' : 'open'}${active ? ' (click to toggle)' : ''}`
                  : `${piece.name}${item.copy?.side ? ` (${sideLabel(item.copy.side)})` : ''} · ${el.seamLabel ? prettyLabel(el.seamLabel) : fold ? 'fold' : 'edge'}`}</title>
              </path>
            </g>
          )
        })}
        <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fontSize={placed ? 9 : 10} fontWeight={500}
          fill={placed ? '#78350f' : '#374151'} style={{ pointerEvents: 'none' }}>
          {piece.name}
          {!placed && item.copy?.side ? ` · ${sideLabel(item.copy.side)}` : ''}
          {!placed && item.copy?.half ? ` ${item.copy.half}` : ''}
          {!placed && !item.copy?.side && piece.cutQty > 1 ? ` ×${piece.cutQty}` : ''}
          {placed && !placed.pl.side && (placed.host.copy?.side) ? ' 🔗' : ''}
        </text>
      </g>
    )
  }

  const placedSel = selPlacement && placedItems.find(p => p.pl.id === selPlacement.id && (p.host.key === selPlacement.host || !placedItems.some(q => q.pl.id === selPlacement.id && q.host.key === selPlacement.host)))
  const rotateHandle = (() => {
    if (!placedSel) return null
    const { piece, t, pl, host } = placedSel
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
            const ht = screen.get(host.key)
            if (!ht) return
            const inv = invert(ht)
            const hc = apply(inv, center)
            const q = apply(inv, svgPoint(e))
            setDrag({ kind: 'rotate', id: pl.id, host: host.key, gesture: ++gestures.current, center: hc, startAngle: deg(Math.atan2(q.y - hc.y, q.x - hc.x)), rotation: pl.transform.rotation })
          }} />
      </g>
    )
  })()

  // While dragging a piece to place it, a ghost follows the pointer.
  const ghost = (() => {
    if (drag?.kind !== 'place' || !drag.moved) return null
    const piece = pieceById.get(drag.pieceId)
    const t = screen.get(drag.item)
    if (!piece || !t) return null
    const c = apply(t, pieceCenter(piece, byId))
    const g = compose({ a: 1, b: 0, c: 0, d: 1, tx: drag.at.x - c.x, ty: drag.at.y - c.y }, t)
    return <path d={outlinePath(piece, byId, g)} fill="#fde68a" fillOpacity={0.5} stroke="#b45309" strokeDasharray="4 3" style={{ pointerEvents: 'none' }} />
  })()

  const selPair = selected !== null ? seamPairs[selected]?.[0] : undefined

  // Snap guides and the dragged piece's distances to the centre, waist and side seam.
  const guideOverlay = (() => {
    if (!guides) return null
    const t = screen.get(guides.host)
    const pl = placements.find(p => p.id === guides.placement)
    const piece = pl && pieceById.get(pl.pieceId), host = pl && pieceById.get(pl.hostId)
    if (!t || !pl || !piece || !host) return null
    const d = distances(pl, piece, host, byId)
    const b = placedBox(pl, piece, byId)
    const at = apply(t, { x: b.cx, y: b.maxY })
    const parts = [
      d.fromCentre !== null && `${d.fromCentre} cm from centre`,
      d.belowTop !== null && `${d.belowTop} cm below the top`,
      d.toSide !== null && (d.toSide < 0 ? 'across the side seam' : `${d.toSide} cm to the side seam`),
    ].filter(Boolean) as string[]
    return (
      <g style={{ pointerEvents: 'none' }} data-testid="placement-guides">
        {guides.list.map((g, i) => {
          const a = apply(t, g.a), c = apply(t, g.b)
          return (
            <g key={i}>
              <line x1={a.x} y1={a.y} x2={c.x} y2={c.y} stroke="#0d9488" strokeWidth={1.2} strokeDasharray="5 3" />
              <text x={c.x + 4} y={c.y} fontSize={9} fill="#0f766e">{g.label}</text>
            </g>
          )
        })}
        {parts.length > 0 && (
          <g>
            <rect x={at.x - 90} y={at.y + 6} width={180} height={14 * parts.length + 6} rx={4} fill="white" fillOpacity={0.9} stroke="#99f6e4" />
            {parts.map((s, i) => <text key={i} x={at.x} y={at.y + 18 + 14 * i} textAnchor="middle" fontSize={10} fill="#134e4a">{s}</text>)}
          </g>
        )}
      </g>
    )
  })()

  return (
    <div className="flex-1 flex overflow-hidden bg-gray-50 relative">
      <svg
        ref={svgRef}
        className="flex-1 select-none"
        style={{ background: '#f9fafb', touchAction: 'none' }}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => { setDrag(null); setGuides(null) }}
        onClick={e => { if (e.target === e.currentTarget) { setPending(null); setSelected(null); setSelPlacement(null) } }}
        data-testid="assembly-svg"
      >
        {mode === 'garment' && (
          <text x={size.w / 2} y={18} textAnchor="middle" fontSize={10} fill="#9ca3af" style={{ pointerEvents: 'none' }}>
            {centre === 'front' ? 'Seen from the front · wearer’s right on the left' : 'Seen from the back · wearer’s left on the left'}
          </text>
        )}
        {items.map(item => { const t = screen.get(item.key); return t ? drawPiece(item, t) : null })}
        {placedItems.map(p => drawPiece({ key: p.key, piece: p.piece, copy: null }, p.t, p))}

        {/* Seams: the sewn stretch of each edge, and an arc joining them
            (not between neighbours that visibly touch). */}
        {connections.map((c, i) => (seamPairs[i] ?? []).map(([a, b], k) => {
          const pa = endMid(c.from, a.key), pb = endMid(c.to, b.key)
          if (!pa || !pb) return null
          const active = i === selected || i === hovered
          const colour = labelColour(c.label)
          const near = Math.hypot(pa.x - pb.x, pa.y - pb.y) < 18
          return (
            <g key={`${i}:${k}`}>
              {active && ([[c.from, a], [c.to, b]] as const).map(([end, item], j) => {
                const pts = endPolyline(end)
                const t = tOf(item.key)
                return pts && t ? <path key={j} d={polylinePath(pts, t)} fill="none" stroke={colour} strokeWidth={6} strokeOpacity={0.45} style={{ pointerEvents: 'none' }} /> : null
              })}
              {(!near || active) && (
                <>
                  <path d={arcPath(pa, pb)} fill="none" stroke={colour} strokeWidth={active ? 2.5 : 1.5}
                    strokeDasharray={active ? undefined : '4 4'} strokeOpacity={active ? 0.95 : 0.55} style={{ pointerEvents: 'none' }} />
                  <path d={arcPath(pa, pb)} fill="none" stroke="transparent" strokeWidth={10} style={{ cursor: 'pointer' }}
                    data-seam={i}
                    onClick={e => { e.stopPropagation(); setPending(null); selectSeam(i === selected ? null : i) }}
                    onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)} />
                </>
              )}
            </g>
          )
        }))}

        {/* Range handles on the selected seam's two edges (first pair shown). */}
        {sel && selected !== null && selPair && (['from', 'to'] as const).map((which, w) => {
          const end = sel[which]
          const item = selPair[w]
          const s = samples.get(end.edgeId)
          const t = tOf(item.key)
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
                  setDrag({ kind: 'range', index: selected, which, item: item.key, bound: bound as 0 | 1, gesture: ++gestures.current })
                }} />
            )
          })
        })}
        {rotateHandle}
        {ghost}
        {guideOverlay}
      </svg>

      <div className="absolute top-2 left-2 flex gap-2">
        <div className="flex rounded border border-gray-300 bg-white shadow-sm text-xs overflow-hidden">
          {(['garment', 'pieces', 'flat'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)} disabled={m === 'flat' && !connections.length}
              className={`px-2 py-1 disabled:opacity-40 ${mode === m ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:bg-gray-50'}`}>
              {m === 'garment' ? 'Garment' : m === 'pieces' ? 'Pieces' : 'Laid flat'}
            </button>
          ))}
        </div>
        {mode === 'garment' && (
          <div className="flex rounded border border-gray-300 bg-white shadow-sm text-xs overflow-hidden" title="Which side of the garment is in the middle">
            {(['front', 'back'] as const).map(c => (
              <button key={c} onClick={() => setCentre(c)}
                className={`px-2 py-1 ${centre === c ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:bg-gray-50'}`}>
                {c === 'front' ? 'Front centred' : 'Back centred'}
              </button>
            ))}
          </div>
        )}
      </div>

      <SeamsPanel pieces={pieces} byId={byId} selected={selected} onSelect={selectSeam} onHover={setHovered}
        pending={pending?.end ?? null}
        selectedPlacement={selPlacement?.id ?? null} onSelectPlacement={id => selectPlacement(id)} />
    </div>
  )
}

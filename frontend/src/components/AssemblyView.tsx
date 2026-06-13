import { useMemo, useRef, useState, useEffect } from 'react'
import { useEditor } from '../context/EditorContext'
import type { CanvasElement, LineElement, CurveElement, PatternPiece, SeamConnection } from '../types'

// ── Colour palette for seam labels ──────────────────────────────────────────
const LABEL_COLOURS: Record<string, string> = {
  side_seam:          '#3b82f6', // blue
  shoulder:           '#8b5cf6', // violet
  armhole:            '#ec4899', // pink
  waist:              '#f59e0b', // amber
  waist_seam:         '#f59e0b', // amber (dress bodice-skirt join)
  hem:                '#10b981', // emerald
  inseam:             '#06b6d4', // cyan
  crotch:             '#ef4444', // red
  sleeve_seam:        '#6366f1', // indigo
  neckline:           '#f97316', // orange
  wrist:              '#84cc16', // lime
  yoke_seam:          '#a78bfa', // purple
  back_sleeve_seam:   '#6366f1',
  front_sleeve_seam:  '#818cf8',
  center_front:       '#d1d5db',
  center_back:        '#d1d5db',
  center_sleeve:      '#d1d5db',
}
const DEFAULT_COLOUR = '#9ca3af'
const FOLD_COLOUR = '#d1d5db'

function labelColour(label: string): string {
  return LABEL_COLOURS[label] ?? DEFAULT_COLOUR
}

// ── Geometry helpers ─────────────────────────────────────────────────────────

interface Pt { x: number; y: number }

function midpoint(a: Pt, b: Pt): Pt {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

function curveMid(start: Pt, cp1: Pt, cp2: Pt, end: Pt, t = 0.5): Pt {
  const mt = 1 - t
  return {
    x: mt*mt*mt*start.x + 3*mt*mt*t*cp1.x + 3*mt*t*t*cp2.x + t*t*t*end.x,
    y: mt*mt*mt*start.y + 3*mt*mt*t*cp1.y + 3*mt*t*t*cp2.y + t*t*t*end.y,
  }
}

function edgeMidpoint(el: LineElement | CurveElement): Pt {
  if (el.type === 'curve') return curveMid(el.start, el.cp1, el.cp2, el.end)
  return midpoint(el.start, el.end)
}

// ── Piece bounding box ───────────────────────────────────────────────────────

interface BBox { minX: number; minY: number; maxX: number; maxY: number }

function piecebbox(piece: PatternPiece, elemMap: Map<string, CanvasElement>): BBox {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const id of piece.elementIds) {
    const el = elemMap.get(id)
    if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
    for (const pt of [el.start, el.end]) {
      minX = Math.min(minX, pt.x); minY = Math.min(minY, pt.y)
      maxX = Math.max(maxX, pt.x); maxY = Math.max(maxY, pt.y)
    }
    if (el.type === 'curve') {
      for (const pt of [el.cp1, el.cp2]) {
        minX = Math.min(minX, pt.x); minY = Math.min(minY, pt.y)
        maxX = Math.max(maxX, pt.x); maxY = Math.max(maxY, pt.y)
      }
    }
  }
  if (!isFinite(minX)) return { minX: 0, minY: 0, maxX: 1, maxY: 1 }
  return { minX, minY, maxX, maxY }
}

// ── Grid layout computation ──────────────────────────────────────────────────

const CELL_PAD = 8
const CELL_GAP = 16

interface CellLayout {
  piece: PatternPiece
  bbox: BBox
  scale: number
  dx: number
  dy: number
  cellX: number
  cellY: number
  cellW: number
  cellH: number
}

function computeLayout(
  pieces: PatternPiece[],
  elemMap: Map<string, CanvasElement>,
  containerW: number,
  containerH: number,
): CellLayout[] {
  if (pieces.length === 0) return []
  const cols = Math.max(1, Math.ceil(Math.sqrt(pieces.length)))
  const CELL_TARGET = Math.floor(
    Math.min(
      (containerW - CELL_GAP * (cols + 1)) / cols,
      (containerH - CELL_GAP * (Math.ceil(pieces.length / cols) + 1)) / Math.ceil(pieces.length / cols)
    )
  ) - CELL_PAD * 2

  return pieces.map((piece, i) => {
    const bb = piecebbox(piece, elemMap)
    const w = bb.maxX - bb.minX, h = bb.maxY - bb.minY
    const scale = w > 0 && h > 0 ? Math.min(CELL_TARGET / w, CELL_TARGET / h) : 1
    const col = i % cols, row = Math.floor(i / cols)
    const cellW = CELL_TARGET + CELL_PAD * 2
    const cellH = CELL_TARGET + CELL_PAD * 2
    return {
      piece, bbox: bb, scale,
      dx: -bb.minX, dy: -bb.minY,
      cellX: CELL_GAP + col * (cellW + CELL_GAP),
      cellY: CELL_GAP + row * (cellH + CELL_GAP),
      cellW, cellH,
    }
  })
}

// ── Connection arc SVG path ──────────────────────────────────────────────────

function arcPath(from: Pt, to: Pt): string {
  const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2
  const dx = to.x - from.x, dy = to.y - from.y
  const len = Math.hypot(dx, dy)
  if (len < 1) return `M ${from.x} ${from.y}`
  const bulge = Math.min(len * 0.35, 60)
  const nx = -dy / len * bulge, ny = dx / len * bulge
  return `M ${from.x} ${from.y} Q ${mx + nx} ${my + ny} ${to.x} ${to.y}`
}

// ── Flat-lay types ───────────────────────────────────────────────────────────

interface AffineTransform {
  a: number; b: number   // x' = a*x + b*y + tx
  c: number; d: number   // y' = c*x + d*y + ty
  tx: number; ty: number
}

interface FlatLayPieceLayout {
  piece: PatternPiece
  transform: AffineTransform
}

// ── Flat-lay geometry ────────────────────────────────────────────────────────

function identityTransform(): AffineTransform {
  return { a: 1, b: 0, c: 0, d: 1, tx: 0, ty: 0 }
}

function applyTransform(t: AffineTransform, p: Pt): Pt {
  return { x: t.a * p.x + t.b * p.y + t.tx, y: t.c * p.x + t.d * p.y + t.ty }
}

// Signed cross product: positive if P is left of A→B
function sideOfLine(A: Pt, B: Pt, P: Pt): number {
  return (B.x - A.x) * (P.y - A.y) - (B.y - A.y) * (P.x - A.x)
}

// Mean of all vertex coords of a piece (local space)
function pieceCentroid(piece: PatternPiece, elemMap: Map<string, CanvasElement>): Pt {
  const pts: Pt[] = []
  for (const id of piece.elementIds) {
    const el = elemMap.get(id)
    if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
    pts.push(el.start, el.end)
  }
  if (pts.length === 0) return { x: 0, y: 0 }
  return {
    x: pts.reduce((s, p) => s + p.x, 0) / pts.length,
    y: pts.reduce((s, p) => s + p.y, 0) / pts.length,
  }
}

// Rotation + translation: maps C→tgtC and D→tgtD
function buildAlignment(C: Pt, D: Pt, tgtC: Pt, tgtD: Pt): AffineTransform {
  const dsx = D.x - C.x, dsy = D.y - C.y
  const dtx = tgtD.x - tgtC.x, dty = tgtD.y - tgtC.y
  const lenS = Math.hypot(dsx, dsy), lenT = Math.hypot(dtx, dty)
  if (lenS < 1e-10 || lenT < 1e-10) return identityTransform()
  const sx = dsx / lenS, sy = dsy / lenS
  const tx = dtx / lenT, ty = dty / lenT
  const cosT = sx * tx + sy * ty
  const sinT = sx * ty - sy * tx
  // T(Q) = R*(Q - C) + tgtC
  return {
    a: cosT,  b: -sinT,
    c: sinT,  d:  cosT,
    tx: -cosT * C.x + sinT * C.y + tgtC.x,
    ty: -sinT * C.x - cosT * C.y + tgtC.y,
  }
}

// Place new piece adjacent to placed piece along shared seam, ensuring no overlap
function computeAlignmentTransform(
  C: Pt, D: Pt,                   // new piece's seam edge (local coords)
  targetA: Pt, targetB: Pt,        // placed piece's seam edge (world coords)
  placedWorldCentroid: Pt,          // centroid of placed piece (world)
  newLocalCentroid: Pt,             // centroid of new piece (local)
): AffineTransform {
  const t1 = buildAlignment(C, D, targetA, targetB)
  const newWorldCentroid = applyTransform(t1, newLocalCentroid)
  const sPlaced = sideOfLine(targetA, targetB, placedWorldCentroid)
  const sNew    = sideOfLine(targetA, targetB, newWorldCentroid)
  // If both centroids on same side, pieces would overlap — reverse edge direction
  if (Math.abs(sPlaced) > 1e-10 && Math.abs(sNew) > 1e-10 && Math.sign(sPlaced) === Math.sign(sNew)) {
    return buildAlignment(C, D, targetB, targetA)
  }
  return t1
}

// BFS edge-aligned placement: one transform per piece
function computeFlatLayLayout(
  pieces: PatternPiece[],
  elemMap: Map<string, CanvasElement>,
  connections: SeamConnection[],
): FlatLayPieceLayout[] {
  if (pieces.length === 0) return []

  // Keep only first connection per piece pair
  const connKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`)
  const seenPairs = new Set<string>()
  const deduped: SeamConnection[] = []
  for (const conn of connections) {
    const key = connKey(conn.from.pieceId, conn.to.pieceId)
    if (!seenPairs.has(key)) { seenPairs.add(key); deduped.push(conn) }
  }

  const adj = new Map<string, SeamConnection[]>()
  for (const p of pieces) adj.set(p.id, [])
  for (const conn of deduped) {
    adj.get(conn.from.pieceId)?.push(conn)
    adj.get(conn.to.pieceId)?.push(conn)
  }

  const pieceMap = new Map(pieces.map(p => [p.id, p]))
  const transforms = new Map<string, AffineTransform>()
  const placed = new Set<string>()

  // BFS from first piece
  transforms.set(pieces[0].id, identityTransform())
  placed.add(pieces[0].id)
  const queue: string[] = [pieces[0].id]

  while (queue.length > 0) {
    const currentId = queue.shift()!
    const currentT = transforms.get(currentId)!
    const currentPiece = pieceMap.get(currentId)!

    for (const conn of adj.get(currentId) ?? []) {
      const isFrom = conn.from.pieceId === currentId
      const neighborId = isFrom ? conn.to.pieceId : conn.from.pieceId
      if (placed.has(neighborId)) continue

      const neighborPiece = pieceMap.get(neighborId)
      if (!neighborPiece) continue

      const placedEdgeId   = isFrom ? conn.from.edgeId : conn.to.edgeId
      const neighborEdgeId = isFrom ? conn.to.edgeId   : conn.from.edgeId
      const placedEl   = elemMap.get(placedEdgeId)
      const neighborEl = elemMap.get(neighborEdgeId)
      if (!placedEl   || (placedEl.type   !== 'line' && placedEl.type   !== 'curve')) continue
      if (!neighborEl || (neighborEl.type  !== 'line' && neighborEl.type  !== 'curve')) continue

      const worldA = applyTransform(currentT, (placedEl   as LineElement | CurveElement).start)
      const worldB = applyTransform(currentT, (placedEl   as LineElement | CurveElement).end)
      const localC = (neighborEl as LineElement | CurveElement).start
      const localD = (neighborEl as LineElement | CurveElement).end

      const placedWorldCentroid = applyTransform(currentT, pieceCentroid(currentPiece, elemMap))
      const newLocalCentroid    = pieceCentroid(neighborPiece, elemMap)

      transforms.set(neighborId, computeAlignmentTransform(localC, localD, worldA, worldB, placedWorldCentroid, newLocalCentroid))
      placed.add(neighborId)
      queue.push(neighborId)
    }
  }

  // Orphans: place to the right of the main cluster
  let clusterMaxX = -Infinity
  for (const [id, t] of transforms) {
    const bb = piecebbox(pieceMap.get(id)!, elemMap)
    for (const corner of [
      { x: bb.minX, y: bb.minY }, { x: bb.maxX, y: bb.minY },
      { x: bb.minX, y: bb.maxY }, { x: bb.maxX, y: bb.maxY },
    ]) clusterMaxX = Math.max(clusterMaxX, applyTransform(t, corner).x)
  }
  if (!isFinite(clusterMaxX)) clusterMaxX = 0

  let orphanOffsetY = 0
  for (const piece of pieces) {
    if (placed.has(piece.id)) continue
    const bb = piecebbox(piece, elemMap)
    transforms.set(piece.id, {
      a: 1, b: 0, c: 0, d: 1,
      tx: clusterMaxX + 5 - bb.minX,
      ty: orphanOffsetY - bb.minY,
    })
    orphanOffsetY += (bb.maxY - bb.minY) + 5
  }

  return pieces.map(p => ({ piece: p, transform: transforms.get(p.id) ?? identityTransform() }))
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AssemblyView() {
  const { state } = useEditor()
  const { pieces, elements, connections } = state
  const containerRef = useRef<SVGSVGElement>(null)
  const [containerSize, setContainerSize] = useState({ w: 800, h: 600 })
  const [hoveredLabel, setHoveredLabel] = useState<string | null>(null)
  const [mode, setMode] = useState<'flat' | 'grid'>('flat')

  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver(entries => {
      const e = entries[0]
      if (e) setContainerSize({ w: e.contentRect.width, h: e.contentRect.height })
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  const elemMap = useMemo(() => {
    const m = new Map<string, CanvasElement>()
    for (const el of elements) m.set(el.id, el)
    return m
  }, [elements])

  const layouts = useMemo(
    () => computeLayout(pieces, elemMap, containerSize.w, containerSize.h),
    [pieces, elemMap, containerSize]
  )

  const flatLayouts = useMemo(
    () => connections.length === 0 ? null : computeFlatLayLayout(pieces, elemMap, connections),
    [pieces, elemMap, connections]
  )

  const isFlat = mode === 'flat' && flatLayouts !== null

  // Edge midpoints for grid-mode arc drawing only
  const edgeMids = useMemo(() => {
    if (isFlat) return new Map<string, Pt>()
    const m = new Map<string, Pt>()
    for (const layout of layouts) {
      const { piece, bbox, scale, dx, dy, cellX, cellY, cellW, cellH } = layout
      const offsetX = cellX + CELL_PAD + (cellW - CELL_PAD * 2 - (bbox.maxX - bbox.minX) * scale) / 2
      const offsetY = cellY + CELL_PAD + (cellH - CELL_PAD * 2 - (bbox.maxY - bbox.minY) * scale) / 2
      for (const id of piece.elementIds) {
        const el = elemMap.get(id)
        if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
        const raw = edgeMidpoint(el as LineElement | CurveElement)
        m.set(id, { x: (raw.x + dx) * scale + offsetX, y: (raw.y + dy) * scale + offsetY })
      }
    }
    return m
  }, [isFlat, layouts, elemMap])

  // Global bounding box of all flat-lay pieces (world cm)
  const flatBBox = useMemo((): BBox | null => {
    if (!flatLayouts) return null
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const { piece, transform } of flatLayouts) {
      for (const id of piece.elementIds) {
        const el = elemMap.get(id)
        if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
        const pts: Pt[] = [el.start, el.end]
        if (el.type === 'curve') pts.push(el.cp1, el.cp2)
        for (const p of pts) {
          const w = applyTransform(transform, p)
          minX = Math.min(minX, w.x); minY = Math.min(minY, w.y)
          maxX = Math.max(maxX, w.x); maxY = Math.max(maxY, w.y)
        }
      }
    }
    return isFinite(minX) ? { minX, minY, maxX, maxY } : null
  }, [flatLayouts, elemMap])

  // Flat-lay viewport scale + offset
  const FLAT_PAD = 40
  let flatScale = 1, flatOx = 0, flatOy = 0
  if (isFlat && flatBBox) {
    const worldW = flatBBox.maxX - flatBBox.minX
    const worldH = flatBBox.maxY - flatBBox.minY
    if (worldW > 0 && worldH > 0) {
      const availW = containerSize.w - FLAT_PAD * 2
      const availH = containerSize.h - FLAT_PAD * 2
      flatScale = Math.min(availW / worldW, availH / worldH)
      flatOx = FLAT_PAD + (availW - worldW * flatScale) / 2 - flatBBox.minX * flatScale
      flatOy = FLAT_PAD + (availH - worldH * flatScale) / 2 - flatBBox.minY * flatScale
    }
  }

  const allLabels = useMemo(() => {
    const seen = new Set<string>()
    for (const conn of connections) seen.add(conn.label)
    return Array.from(seen).sort()
  }, [connections])

  if (pieces.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
        No pattern pieces to display. Generate a pattern with AI Assist first.
      </div>
    )
  }

  // Convert local-space point → SVG pixels via a piece's flat-lay transform
  const toSvg = (t: AffineTransform) => (p: Pt): Pt => {
    const w = applyTransform(t, p)
    return { x: w.x * flatScale + flatOx, y: w.y * flatScale + flatOy }
  }

  return (
    <div className="flex-1 flex overflow-hidden bg-gray-50 relative">
      <svg ref={containerRef} className="flex-1" style={{ background: '#f9fafb' }}>

        {/* ── FLAT MODE ── */}
        {isFlat && flatLayouts && flatLayouts.map(({ piece, transform }) => {
          const sv = toSvg(transform)

          let outlinePath = ''
          for (const id of piece.elementIds) {
            const el = elemMap.get(id)
            if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
            const edEl = el as LineElement | CurveElement
            const s = sv(edEl.start), e = sv(edEl.end)
            if (outlinePath === '') outlinePath += `M ${s.x} ${s.y}`
            if (el.type === 'curve') {
              const cp1 = sv(el.cp1), cp2 = sv(el.cp2)
              outlinePath += ` C ${cp1.x} ${cp1.y}, ${cp2.x} ${cp2.y}, ${e.x} ${e.y}`
            } else {
              outlinePath += ` L ${e.x} ${e.y}`
            }
          }
          if (outlinePath) outlinePath += ' Z'

          const labelPt = sv(pieceCentroid(piece, elemMap))

          return (
            <g key={piece.id}>
              {outlinePath && (
                <path d={outlinePath} fill="#f0f9ff" fillOpacity={0.6} stroke="none" />
              )}

              {piece.elementIds.map(id => {
                const el = elemMap.get(id)
                if (!el || (el.type !== 'line' && el.type !== 'curve')) return null
                const edEl = el as LineElement | CurveElement
                const label = edEl.seamLabel ?? ''
                const isFold = el.type === 'line' && (el as LineElement).isFold
                const colour = isFold ? FOLD_COLOUR : labelColour(label)
                const isHov = hoveredLabel !== null && label === hoveredLabel && label !== ''
                const s = sv(edEl.start), e = sv(edEl.end)
                let d: string
                if (el.type === 'curve') {
                  const cp1 = sv(el.cp1), cp2 = sv(el.cp2)
                  d = `M ${s.x} ${s.y} C ${cp1.x} ${cp1.y}, ${cp2.x} ${cp2.y}, ${e.x} ${e.y}`
                } else {
                  d = `M ${s.x} ${s.y} L ${e.x} ${e.y}`
                }
                return (
                  <path
                    key={id} d={d} fill="none"
                    stroke={colour}
                    strokeWidth={isHov ? 3 : isFold ? 1 : 1.5}
                    strokeDasharray={isFold ? '4 3' : undefined}
                    strokeOpacity={isHov ? 1.0 : 0.85}
                    style={{ cursor: label ? 'pointer' : 'default', transition: 'stroke-width 0.1s' }}
                    onMouseEnter={() => label && setHoveredLabel(label)}
                    onMouseLeave={() => setHoveredLabel(null)}
                  >
                    {label && <title>{label.replace(/_/g, ' ')}</title>}
                  </path>
                )
              })}

              {elements
                .filter(el => el.type === 'grain-line' && el.pieceId === piece.id)
                .map(el => {
                  if (el.type !== 'grain-line') return null
                  const s = sv(el.start), e = sv(el.end)
                  return <line key={el.id} x1={s.x} y1={s.y} x2={e.x} y2={e.y} stroke="#9ca3af" strokeWidth={0.8} strokeDasharray="3 3" />
                })
              }

              <text
                x={labelPt.x} y={labelPt.y}
                textAnchor="middle" dominantBaseline="middle"
                fontSize={10} fontWeight={500} fill="#374151"
                style={{ pointerEvents: 'none', userSelect: 'none' }}
              >
                {piece.name}
              </text>
            </g>
          )
        })}

        {/* ── GRID MODE ── */}
        {!isFlat && (
          <>
            {connections.map((conn, i) => {
              const fromPt = edgeMids.get(conn.from.edgeId)
              const toPt = edgeMids.get(conn.to.edgeId)
              if (!fromPt || !toPt) return null
              const colour = labelColour(conn.label)
              const isHovered = hoveredLabel === conn.label
              return (
                <path key={i}
                  d={arcPath(fromPt, toPt)} fill="none"
                  stroke={colour}
                  strokeWidth={isHovered ? 2.5 : 1.5}
                  strokeDasharray={isHovered ? '6 3' : '4 4'}
                  strokeOpacity={isHovered ? 0.9 : 0.5}
                  style={{ transition: 'stroke-opacity 0.15s, stroke-width 0.15s' }}
                />
              )
            })}

            {layouts.map(({ piece, bbox, scale, dx, dy, cellX, cellY, cellW, cellH }) => {
              const offsetX = cellX + CELL_PAD + (cellW - CELL_PAD * 2 - (bbox.maxX - bbox.minX) * scale) / 2
              const offsetY = cellY + CELL_PAD + (cellH - CELL_PAD * 2 - (bbox.maxY - bbox.minY) * scale) / 2
              const gs = (p: Pt): Pt => ({ x: (p.x + dx) * scale + offsetX, y: (p.y + dy) * scale + offsetY })

              let outlinePath = ''
              for (const id of piece.elementIds) {
                const el = elemMap.get(id)
                if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
                const edEl = el as LineElement | CurveElement
                const s = gs(edEl.start), e = gs(edEl.end)
                if (outlinePath === '') outlinePath += `M ${s.x} ${s.y}`
                if (el.type === 'curve') {
                  const cp1 = gs(el.cp1), cp2 = gs(el.cp2)
                  outlinePath += ` C ${cp1.x} ${cp1.y}, ${cp2.x} ${cp2.y}, ${e.x} ${e.y}`
                } else {
                  outlinePath += ` L ${e.x} ${e.y}`
                }
              }
              if (outlinePath) outlinePath += ' Z'

              return (
                <g key={piece.id}>
                  <rect x={cellX} y={cellY} width={cellW} height={cellH} rx={6} fill="white" stroke="#e5e7eb" strokeWidth={1} />
                  {outlinePath && <path d={outlinePath} fill="#f0f9ff" fillOpacity={0.7} stroke="none" />}

                  {piece.elementIds.map(id => {
                    const el = elemMap.get(id)
                    if (!el || (el.type !== 'line' && el.type !== 'curve')) return null
                    const edEl = el as LineElement | CurveElement
                    const label = edEl.seamLabel ?? ''
                    const isFold = el.type === 'line' && (el as LineElement).isFold
                    const colour = isFold ? FOLD_COLOUR : labelColour(label)
                    const isHov = hoveredLabel !== null && label === hoveredLabel && label !== ''
                    const s = gs(edEl.start), e = gs(edEl.end)
                    let d: string
                    if (el.type === 'curve') {
                      const cp1 = gs(el.cp1), cp2 = gs(el.cp2)
                      d = `M ${s.x} ${s.y} C ${cp1.x} ${cp1.y}, ${cp2.x} ${cp2.y}, ${e.x} ${e.y}`
                    } else {
                      d = `M ${s.x} ${s.y} L ${e.x} ${e.y}`
                    }
                    return (
                      <path key={id} d={d} fill="none"
                        stroke={colour}
                        strokeWidth={isHov ? 3 : isFold ? 1 : 1.5}
                        strokeDasharray={isFold ? '4 3' : undefined}
                        strokeOpacity={isHov ? 1.0 : 0.85}
                        style={{ cursor: label ? 'pointer' : 'default', transition: 'stroke-width 0.1s' }}
                        onMouseEnter={() => label && setHoveredLabel(label)}
                        onMouseLeave={() => setHoveredLabel(null)}
                      >
                        {label && <title>{label.replace(/_/g, ' ')}</title>}
                      </path>
                    )
                  })}

                  {elements
                    .filter(el => el.type === 'grain-line' && el.pieceId === piece.id)
                    .map(el => {
                      if (el.type !== 'grain-line') return null
                      const s = gs(el.start), e = gs(el.end)
                      return <line key={el.id} x1={s.x} y1={s.y} x2={e.x} y2={e.y} stroke="#9ca3af" strokeWidth={0.8} strokeDasharray="3 3" />
                    })
                  }

                  <text x={cellX + cellW / 2} y={cellY + cellH - 6}
                    textAnchor="middle" fontSize={10} fontWeight={500} fill="#374151"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >{piece.name}</text>

                  {piece.cutQty > 1 && (
                    <text x={cellX + cellW - 6} y={cellY + 14}
                      textAnchor="end" fontSize={9} fill="#6b7280"
                      style={{ pointerEvents: 'none' }}
                    >×{piece.cutQty}</text>
                  )}
                </g>
              )
            })}
          </>
        )}
      </svg>

      {/* Mode toggle */}
      {flatLayouts !== null && (
        <div style={{ position: 'absolute', top: 8, right: allLabels.length > 0 ? 184 : 8, zIndex: 10 }}>
          <button
            onClick={() => setMode(m => m === 'flat' ? 'grid' : 'flat')}
            className="text-xs px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-50 shadow-sm text-gray-600"
          >
            {isFlat ? 'Grid View' : 'Assembly View'}
          </button>
        </div>
      )}

      {/* Legend */}
      {allLabels.length > 0 && (
        <div className="w-44 shrink-0 border-l border-gray-200 bg-white overflow-y-auto p-3">
          <div className="text-xs font-semibold text-gray-600 mb-2 uppercase tracking-wide">Seam Guide</div>
          {allLabels.map(label => (
            <div
              key={label}
              className="flex items-center gap-2 mb-1.5 cursor-pointer rounded px-1 py-0.5 hover:bg-gray-50"
              onMouseEnter={() => setHoveredLabel(label)}
              onMouseLeave={() => setHoveredLabel(null)}
              style={{ background: hoveredLabel === label ? '#f3f4f6' : undefined }}
            >
              <div className="shrink-0 w-5 h-1.5 rounded-full" style={{ background: labelColour(label) }} />
              <span className="text-xs text-gray-700 truncate capitalize">{label.replace(/_/g, ' ')}</span>
            </div>
          ))}
          <div className="mt-3 pt-3 border-t border-gray-100">
            <div className="text-[10px] text-gray-400 leading-relaxed">
              Hover a seam label or edge to highlight all matching seams.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import type { CanvasElement, PatternPiece, Placement } from '../../types'
import { pieceCenter, placementMatrix, applyMatrix } from '../../utils/placement'
import type { Pt } from './geometry'
import { pieceEdges, sampleEdge } from './geometry'

// Help placing pockets precisely, in the host piece's own pattern coordinates
// (so it works the same on every copy and in every view): where the host's
// centre line, waist and side seam are; how far a placed piece is from them;
// and snapping while it is dragged — onto the side seam (to straddle it), onto
// the middle between centre and side seam, and level with its twin on the other side.

export interface HostRefs {
  centreX: number | null // CF / CB / fold line
  waistY: (x: number) => number | null // top edge (waist / waist seam / neckline) at x
  sideX: (y: number) => number | null // side seam at y
}

const CENTRE = ['center_front', 'center_back', 'overlap_edge', 'underlap_edge']
const TOPS = ['waist', 'waist_seam', 'neckline']

function polylineAt(pts: Pt[], coord: 'x' | 'y', v: number): number | null {
  const other = coord === 'x' ? 'y' : 'x'
  let best: number | null = null
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1]
    if ((v < Math.min(a[coord], b[coord])) || (v > Math.max(a[coord], b[coord]))) continue
    const f = b[coord] === a[coord] ? 0 : (v - a[coord]) / (b[coord] - a[coord])
    const w = a[other] + (b[other] - a[other]) * f
    best = best === null ? w : coord === 'x' ? Math.min(best, w) : best
    if (coord === 'y') return w
  }
  return best
}

export function hostRefs(host: PatternPiece, byId: Map<string, CanvasElement>): HostRefs {
  const edges = pieceEdges(host, byId)
  const centre = edges.filter(e => (e.type === 'line' && e.isFold) || CENTRE.includes(e.seamLabel ?? ''))
  const centreX = centre.length ? centre.flatMap(e => [e.start.x, e.end.x]).reduce((s, x) => s + x, 0) / (centre.length * 2) : null
  const tops = edges.filter(e => TOPS.includes(e.seamLabel ?? '')).flatMap(e => sampleEdge(e, 16).pts)
  const sides = edges.filter(e => e.seamLabel === 'side_seam').flatMap(e => sampleEdge(e, 16).pts).sort((a, b) => a.y - b.y)
  return {
    centreX,
    waistY: x => {
      if (!tops.length) return null
      const sorted = [...tops].sort((a, b) => a.x - b.x)
      return polylineAt(sorted, 'x', Math.min(Math.max(x, sorted[0].x), sorted[sorted.length - 1].x))
    },
    sideX: y => (sides.length ? polylineAt(sides, 'y', Math.min(Math.max(y, sides[0].y), sides[sides.length - 1].y)) : null),
  }
}

// The placed piece's outline box in host coordinates.
export function placedBox(pl: Placement, piece: PatternPiece, byId: Map<string, CanvasElement>) {
  const M = placementMatrix(pl, pieceCenter(piece, byId))
  const pts = pieceEdges(piece, byId).flatMap(e => sampleEdge(e, 12).pts).map(p => applyMatrix(M, p.x, p.y))
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1])
  const box = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) }
  return { ...box, cx: (box.minX + box.maxX) / 2, cy: (box.minY + box.maxY) / 2 }
}

export interface Distances { fromCentre: number | null; belowTop: number | null; toSide: number | null }

// Pocket centre from the centre line; pocket top below the waist; nearest
// pocket edge to the side seam (negative: it crosses the side seam).
export function distances(pl: Placement, piece: PatternPiece, host: PatternPiece, byId: Map<string, CanvasElement>): Distances {
  const r = hostRefs(host, byId)
  const b = placedBox(pl, piece, byId)
  const top = r.waistY(b.cx)
  const side = r.sideX(b.cy)
  const round = (v: number) => Math.round(v * 10) / 10
  return {
    fromCentre: r.centreX === null ? null : round(Math.abs(b.cx - r.centreX)),
    belowTop: top === null ? null : round(b.minY - top),
    toSide: side === null ? null : round(Math.min(Math.abs(side - b.minX), Math.abs(side - b.maxX)) * (b.minX < side && b.maxX > side ? -1 : 1)),
  }
}

export interface Guide { a: Pt; b: Pt; label: string }

// Snaps a dragged placement (its candidate dx, dy) and returns the guides to draw
// (host coordinates).
export function snapPlacement(
  pl: Placement, piece: PatternPiece, host: PatternPiece, byId: Map<string, CanvasElement>, twins: Placement[], tol = 0.8,
): { dx: number; dy: number; guides: Guide[] } {
  const r = hostRefs(host, byId)
  let { dx, dy } = pl.transform
  const guides: Guide[] = []
  const b = placedBox(pl, piece, byId)
  // Horizontal: the side seam through the centre (straddling it), or the
  // middle between the centre line and the side seam.
  const side = r.sideX(b.cy)
  const targetsX: { x: number; label: string }[] = []
  if (side !== null) targetsX.push({ x: side, label: 'on the side seam' })
  if (side !== null && r.centreX !== null) targetsX.push({ x: (side + r.centreX) / 2, label: 'midway to the side seam' })
  for (const twin of twins) targetsX.push({ x: placedBox(twin, piece, byId).cx, label: 'level with the other side' })
  const nx = targetsX.map(t => ({ ...t, d: Math.abs(t.x - b.cx) })).filter(t => t.d < tol).sort((a, c) => a.d - c.d)[0]
  if (nx) {
    dx += nx.x - b.cx
    guides.push({ a: { x: nx.x, y: b.minY - 4 }, b: { x: nx.x, y: b.maxY + 4 }, label: nx.label })
  }
  // Vertical: level with the twin.
  for (const twin of twins) {
    const tb = placedBox(twin, piece, byId)
    if (Math.abs(tb.minY - b.minY) < tol) {
      dy += tb.minY - b.minY
      guides.push({ a: { x: b.minX - 4, y: tb.minY }, b: { x: b.maxX + 4, y: tb.minY }, label: 'level with the other side' })
      break
    }
  }
  return { dx, dy, guides }
}

// Moves a placement so its centre is `fromCentre` from the centre line and its
// top `belowTop` under the waist (either may be left as is).
export function moveTo(
  pl: Placement, piece: PatternPiece, host: PatternPiece, byId: Map<string, CanvasElement>,
  want: { fromCentre?: number; belowTop?: number },
): Placement {
  const r = hostRefs(host, byId)
  let out = pl
  if (want.fromCentre !== undefined && r.centreX !== null) {
    const b = placedBox(out, piece, byId)
    const dir = Math.sign(b.cx - r.centreX) || 1
    out = { ...out, transform: { ...out.transform, dx: out.transform.dx + r.centreX + dir * want.fromCentre - b.cx } }
  }
  // Measured where the pocket now is (the waist may slope).
  if (want.belowTop !== undefined) {
    const b = placedBox(out, piece, byId)
    const top = r.waistY(b.cx)
    if (top !== null) out = { ...out, transform: { ...out.transform, dy: out.transform.dy + top + want.belowTop - b.minY } }
  }
  return out
}

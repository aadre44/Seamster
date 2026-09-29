import type { CanvasElement, CurveElement, LineElement, PatternPiece, SeamConnection } from '../../types'

// Geometry for the Assembly view: piece layouts (a shelf-packed grid at one
// common scale, or laid flat edge to edge along seams) and edge sampling for
// seam ranges. Everything is in canvas cm until a layout maps it to screen.

export interface Pt { x: number; y: number }
export interface BBox { minX: number; minY: number; maxX: number; maxY: number }
export type Edge = LineElement | CurveElement

// x' = a*x + b*y + tx, y' = c*x + d*y + ty
export interface Affine { a: number; b: number; c: number; d: number; tx: number; ty: number }

export const IDENTITY: Affine = { a: 1, b: 0, c: 0, d: 1, tx: 0, ty: 0 }

export function apply(t: Affine, p: Pt): Pt {
  return { x: t.a * p.x + t.b * p.y + t.tx, y: t.c * p.x + t.d * p.y + t.ty }
}

export function invert(t: Affine): Affine {
  const det = t.a * t.d - t.b * t.c || 1e-12
  const a = t.d / det, b = -t.b / det, c = -t.c / det, d = t.a / det
  return { a, b, c, d, tx: -(a * t.tx + b * t.ty), ty: -(c * t.tx + d * t.ty) }
}

// Screen transform after a world transform.
export function compose(outer: Affine, inner: Affine): Affine {
  return {
    a: outer.a * inner.a + outer.b * inner.c,
    b: outer.a * inner.b + outer.b * inner.d,
    c: outer.c * inner.a + outer.d * inner.c,
    d: outer.c * inner.b + outer.d * inner.d,
    tx: outer.a * inner.tx + outer.b * inner.ty + outer.tx,
    ty: outer.c * inner.tx + outer.d * inner.ty + outer.ty,
  }
}

export const isEdge = (el: CanvasElement | undefined): el is Edge => !!el && (el.type === 'line' || el.type === 'curve')

export function pieceEdges(piece: PatternPiece, byId: Map<string, CanvasElement>): Edge[] {
  return piece.elementIds.map(id => byId.get(id)).filter(isEdge)
}

export function pieceBBox(piece: PatternPiece, byId: Map<string, CanvasElement>): BBox {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const el of pieceEdges(piece, byId)) {
    for (const p of el.type === 'curve' ? [el.start, el.end, el.cp1, el.cp2] : [el.start, el.end]) {
      minX = Math.min(minX, p.x); minY = Math.min(minY, p.y)
      maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y)
    }
  }
  return isFinite(minX) ? { minX, minY, maxX, maxY } : { minX: 0, minY: 0, maxX: 1, maxY: 1 }
}

export function pieceCentroid(piece: PatternPiece, byId: Map<string, CanvasElement>): Pt {
  const pts = pieceEdges(piece, byId).flatMap(el => [el.start, el.end])
  if (!pts.length) return { x: 0, y: 0 }
  return { x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length }
}

// ── Edge sampling (for ranges: fractions of an edge's arc length) ────────────

function bezier(el: CurveElement, t: number): Pt {
  const u = 1 - t
  const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t
  return {
    x: a * el.start.x + b * el.cp1.x + c * el.cp2.x + d * el.end.x,
    y: a * el.start.y + b * el.cp1.y + c * el.cp2.y + d * el.end.y,
  }
}

export interface Samples { pts: Pt[]; f: number[]; length: number }

export function sampleEdge(el: Edge, n = 48): Samples {
  const pts = el.type === 'line' ? [el.start, el.end] : Array.from({ length: n + 1 }, (_, i) => bezier(el, i / n))
  const cum = [0]
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y))
  const length = cum[cum.length - 1]
  return { pts, f: cum.map(c => (length > 0 ? c / length : 0)), length }
}

export function pointAt(s: Samples, f: number): Pt {
  let i = 0
  while (i < s.f.length - 2 && s.f[i + 1] < f) i++
  const g = (f - s.f[i]) / Math.max(s.f[i + 1] - s.f[i], 1e-9)
  return { x: s.pts[i].x + (s.pts[i + 1].x - s.pts[i].x) * g, y: s.pts[i].y + (s.pts[i + 1].y - s.pts[i].y) * g }
}

// The stretch of an edge between two fractions, as a polyline.
export function subPolyline(s: Samples, lo: number, hi: number): Pt[] {
  const out = [pointAt(s, lo)]
  s.f.forEach((f, i) => { if (f > lo && f < hi) out.push(s.pts[i]) })
  out.push(pointAt(s, hi))
  return out
}

// Fraction along the edge closest to p.
export function nearestFraction(s: Samples, p: Pt): number {
  let best = 0, bestD = Infinity
  for (let i = 0; i < s.pts.length - 1; i++) {
    const a = s.pts[i], b = s.pts[i + 1]
    const dx = b.x - a.x, dy = b.y - a.y
    const len2 = dx * dx + dy * dy
    const t = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2)) : 0
    const d = Math.hypot(a.x + dx * t - p.x, a.y + dy * t - p.y)
    if (d < bestD) { bestD = d; best = s.f[i] + (s.f[i + 1] - s.f[i]) * t }
  }
  return best
}

// Even-odd point in polygon.
export function insidePolygon(poly: Pt[], p: Pt): boolean {
  let c = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j]
    if ((a.y > p.y) !== (b.y > p.y) && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) c = !c
  }
  return c
}

// ── Layouts ──────────────────────────────────────────────────────────────────

const GAP_PX = 28

// Pieces in reading order, all at one scale (so relative sizes are true),
// wrapped into rows; the largest scale at which everything fits.
export function gridLayout(pieces: PatternPiece[], byId: Map<string, CanvasElement>, W: number, H: number, pad = 24): Map<string, Affine> {
  // Seam arcs bulge up to ~60 px beyond the edges they join; keep room below.
  const bottom = 64
  const boxes = pieces.map(p => pieceBBox(p, byId))
  const place = (scale: number) => {
    const out: { x: number; y: number }[] = []
    let x = pad, y = pad, rowH = 0
    boxes.forEach(b => {
      const w = (b.maxX - b.minX) * scale, h = (b.maxY - b.minY) * scale
      if (x > pad && x + w > W - pad) { x = pad; y += rowH + GAP_PX; rowH = 0 }
      out.push({ x, y })
      x += w + GAP_PX
      rowH = Math.max(rowH, h)
    })
    return { out, height: y + rowH + bottom }
  }
  let lo = 0.01, hi = 40
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2
    const widest = Math.max(...boxes.map(b => (b.maxX - b.minX) * mid))
    if (place(mid).height <= H && widest <= W - 2 * pad) lo = mid
    else hi = mid
  }
  const { out } = place(lo)
  return new Map(pieces.map((p, i) => [p.id, { a: lo, b: 0, c: 0, d: lo, tx: out[i].x - boxes[i].minX * lo, ty: out[i].y - boxes[i].minY * lo }]))
}

// Rotation + translation mapping C→tC and D→tD.
function alignment(C: Pt, D: Pt, tC: Pt, tD: Pt): Affine {
  const sx = D.x - C.x, sy = D.y - C.y, dx = tD.x - tC.x, dy = tD.y - tC.y
  const ls = Math.hypot(sx, sy), lt = Math.hypot(dx, dy)
  if (ls < 1e-10 || lt < 1e-10) return IDENTITY
  const cos = (sx * dx + sy * dy) / (ls * lt), sin = (sx * dy - sy * dx) / (ls * lt)
  return { a: cos, b: -sin, c: sin, d: cos, tx: -cos * C.x + sin * C.y + tC.x, ty: -sin * C.x - cos * C.y + tC.y }
}

const side = (A: Pt, B: Pt, P: Pt) => (B.x - A.x) * (P.y - A.y) - (B.y - A.y) * (P.x - A.x)

// The two ends of a seam that may run over several edges (a side seam drawn
// as a curve then a line): the pair of edge endpoints farthest apart.
function seamSpan(edges: Edge[]): [Pt, Pt] {
  const pts = edges.flatMap(e => [e.start, e.end])
  let best: [Pt, Pt] = [pts[0], pts[1]], d = -1
  for (const p of pts) for (const q of pts) {
    const dd = Math.hypot(p.x - q.x, p.y - q.y)
    if (dd > d) { d = dd; best = [p, q] }
  }
  return best
}

// Pieces laid flat edge to edge along their seams (breadth first from the
// first piece), each joined to its neighbour along the whole seam between
// them; unconnected pieces stack to the right. World cm.
export function flatLayLayout(pieces: PatternPiece[], byId: Map<string, CanvasElement>, connections: SeamConnection[]): Map<string, Affine> {
  const out = new Map<string, Affine>()
  if (!pieces.length) return out
  const byPiece = new Map(pieces.map(p => [p.id, p]))
  const between = new Map<string, SeamConnection[]>()
  for (const c of connections) {
    if (c.from.pieceId === c.to.pieceId) continue
    const key = [c.from.pieceId, c.to.pieceId].sort().join('|')
    between.set(key, [...(between.get(key) ?? []), c])
  }
  out.set(pieces[0].id, IDENTITY)
  const queue = [pieces[0].id]
  while (queue.length) {
    const id = queue.shift()!
    const t = out.get(id)!
    for (const [key, cs] of between) {
      const [p, q] = key.split('|')
      if (p !== id && q !== id) continue
      const otherId = p === id ? q : p
      const next = byPiece.get(otherId)
      if (out.has(otherId) || !next) continue
      const mine = cs.map(c => byId.get(c.from.pieceId === id ? c.from.edgeId : c.to.edgeId)).filter(isEdge)
      const theirs = cs.map(c => byId.get(c.from.pieceId === id ? c.to.edgeId : c.from.edgeId)).filter(isEdge)
      if (!mine.length || !theirs.length) continue
      const [a0, a1] = seamSpan(mine)
      const [b0, b1] = seamSpan(theirs)
      const A = apply(t, a0), B = apply(t, a1)
      const placedC = apply(t, pieceCentroid(byPiece.get(id)!, byId))
      // Sewn pieces lie right sides together, so laid open one is usually a
      // mirror image: try both orientations each way round, and keep the one
      // that lands every seam element on its partner without overlapping.
      const mid = (e: Edge) => ({ x: (e.start.x + e.end.x) / 2, y: (e.start.y + e.end.y) / 2 })
      let best = IDENTITY, bestScore = Infinity
      for (const mirror of [false, true]) {
        const M: Affine = mirror ? { a: -1, b: 0, c: 0, d: 1, tx: 0, ty: 0 } : IDENTITY
        const m0 = apply(M, b0), m1 = apply(M, b1)
        for (const [P, Q] of [[A, B], [B, A]]) {
          const cand = compose(alignment(m0, m1, P, Q), M)
          const overlap = Math.sign(side(A, B, placedC)) === Math.sign(side(A, B, apply(cand, pieceCentroid(next, byId))))
          let score = (overlap ? 1e6 : 0) + (mirror ? 1e-3 : 0) // on a tie, don't mirror
          mine.forEach((e, k) => {
            if (!theirs[k]) return
            const p = apply(t, mid(e)), q = apply(cand, mid(theirs[k]))
            score += Math.hypot(p.x - q.x, p.y - q.y)
          })
          if (score < bestScore) { bestScore = score; best = cand }
        }
      }
      out.set(otherId, best)
      queue.push(otherId)
    }
  }
  let maxX = 0
  for (const [id, t] of out) {
    const b = pieceBBox(byPiece.get(id)!, byId)
    for (const p of [{ x: b.minX, y: b.minY }, { x: b.maxX, y: b.maxY }, { x: b.minX, y: b.maxY }, { x: b.maxX, y: b.minY }]) maxX = Math.max(maxX, apply(t, p).x)
  }
  let y = 0
  for (const p of pieces) {
    if (out.has(p.id)) continue
    const b = pieceBBox(p, byId)
    out.set(p.id, { ...IDENTITY, tx: maxX + 5 - b.minX, ty: y - b.minY })
    y += b.maxY - b.minY + 5
  }
  return out
}

// Fits world-space layouts into the viewport.
export function fitToView(pieces: PatternPiece[], byId: Map<string, CanvasElement>, world: Map<string, Affine>, W: number, H: number, pad = 40): Map<string, Affine> {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const p of pieces) {
    const t = world.get(p.id) ?? IDENTITY
    for (const el of pieceEdges(p, byId)) {
      for (const q of el.type === 'curve' ? [el.start, el.end, el.cp1, el.cp2] : [el.start, el.end]) {
        const w = apply(t, q)
        minX = Math.min(minX, w.x); minY = Math.min(minY, w.y); maxX = Math.max(maxX, w.x); maxY = Math.max(maxY, w.y)
      }
    }
  }
  if (!isFinite(minX)) return world
  const s = Math.min((W - 2 * pad) / Math.max(maxX - minX, 1e-6), (H - 2 * pad) / Math.max(maxY - minY, 1e-6))
  const view: Affine = { a: s, b: 0, c: 0, d: s, tx: pad + ((W - 2 * pad) - (maxX - minX) * s) / 2 - minX * s, ty: pad + ((H - 2 * pad) - (maxY - minY) * s) / 2 - minY * s }
  return new Map(pieces.map(p => [p.id, compose(view, world.get(p.id) ?? IDENTITY)]))
}

// SVG path of an edge (or of a polyline) through a transform.
export function edgePath(el: Edge, t: Affine): string {
  const s = apply(t, el.start), e = apply(t, el.end)
  if (el.type === 'curve') {
    const c1 = apply(t, el.cp1), c2 = apply(t, el.cp2)
    return `M ${s.x} ${s.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${e.x} ${e.y}`
  }
  return `M ${s.x} ${s.y} L ${e.x} ${e.y}`
}

export function polylinePath(pts: Pt[], t: Affine): string {
  return pts.map((p, i) => { const q = apply(t, p); return `${i ? 'L' : 'M'} ${q.x} ${q.y}` }).join(' ')
}

export function outlinePath(piece: PatternPiece, byId: Map<string, CanvasElement>, t: Affine): string {
  let d = ''
  for (const el of pieceEdges(piece, byId)) {
    const s = apply(t, el.start), e = apply(t, el.end)
    if (!d) d = `M ${s.x} ${s.y}`
    if (el.type === 'curve') {
      const c1 = apply(t, el.cp1), c2 = apply(t, el.cp2)
      d += ` C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${e.x} ${e.y}`
    } else d += ` L ${e.x} ${e.y}`
  }
  return d ? `${d} Z` : ''
}

export function arcPath(from: Pt, to: Pt): string {
  const dx = to.x - from.x, dy = to.y - from.y
  const len = Math.hypot(dx, dy)
  if (len < 1) return `M ${from.x} ${from.y}`
  const bulge = Math.min(len * 0.35, 60)
  const mx = (from.x + to.x) / 2 - (dy / len) * bulge, my = (from.y + to.y) / 2 + (dx / len) * bulge
  return `M ${from.x} ${from.y} Q ${mx} ${my} ${to.x} ${to.y}`
}

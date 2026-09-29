import cdt2d from 'cdt2d'
import type { CanvasElement, PatternPiece } from '../types'
import type { Pt } from './bodyQuery'

// A pattern piece's outline as an ordered, closed loop of labelled edges,
// with curves flattened. Coordinates are the editor's (cm, y down).

export interface OutlineEdge {
  id: string
  label: string
  isFold: boolean
  pts: Pt[] // along the loop, both endpoints included
}

export interface PieceShape {
  edges: OutlineEdge[]
  loop: Pt[] // closed polygon without the repeated first point
}

const JOIN_EPS = 0.05

function cubic(p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: number): Pt {
  const u = 1 - t
  const a = u * u * u
  const b = 3 * u * u * t
  const c = 3 * u * t * t
  const d = t * t * t
  return [a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]]
}

function edgePoints(e: CanvasElement): Pt[] | null {
  if (e.type === 'line') return [[e.start.x, e.start.y], [e.end.x, e.end.y]]
  if (e.type === 'curve') {
    const p0: Pt = [e.start.x, e.start.y]
    const p1: Pt = [e.cp1.x, e.cp1.y]
    const p2: Pt = [e.cp2.x, e.cp2.y]
    const p3: Pt = [e.end.x, e.end.y]
    const hull = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) + Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) + Math.hypot(p3[0] - p2[0], p3[1] - p2[1])
    const n = Math.max(4, Math.ceil(hull / 0.8))
    return Array.from({ length: n + 1 }, (_, i) => cubic(p0, p1, p2, p3, i / n))
  }
  return null
}

const near = (p: Pt, q: Pt) => Math.hypot(p[0] - q[0], p[1] - q[1]) < JOIN_EPS

// Chains the piece's outline elements end to end (reversing any that run
// backwards). Null when they don't form one closed loop.
export function extractOutline(piece: PatternPiece, byId: Map<string, CanvasElement>): PieceShape | null {
  const raw: OutlineEdge[] = []
  for (const id of piece.elementIds) {
    const e = byId.get(id)
    if (!e) return null
    const pts = edgePoints(e)
    if (!pts) continue
    raw.push({ id, label: (e as { seamLabel?: string }).seamLabel ?? '', isFold: e.type === 'line' && e.isFold, pts })
  }
  if (raw.length < 2) return null
  const edges: OutlineEdge[] = [raw[0]]
  const rest = raw.slice(1)
  while (rest.length) {
    const end = edges[edges.length - 1].pts[edges[edges.length - 1].pts.length - 1]
    const i = rest.findIndex(e => near(e.pts[0], end) || near(e.pts[e.pts.length - 1], end))
    if (i < 0) return null
    const [next] = rest.splice(i, 1)
    edges.push(near(next.pts[0], end) ? next : { ...next, pts: [...next.pts].reverse() })
  }
  const first = edges[0].pts[0]
  const last = edges[edges.length - 1].pts[edges[edges.length - 1].pts.length - 1]
  if (!near(first, last)) return null
  const loop: Pt[] = []
  for (const e of edges) loop.push(...e.pts.slice(0, -1))
  return { edges, loop }
}

// A dart as two legs, each [base on the outline, apex].
export interface DartLegs { a: [Pt, Pt]; b: [Pt, Pt] }

// Cuts each dart's wedge out of the outline: the edge its bases sit on is split
// and the two legs become their own edges, labelled 'dart' (ids dart:<k>:a /
// dart:<k>:b) so they can be sewn together like a seam. Darts whose bases are
// not on the outline are left alone.
export function cutDarts(shape: PieceShape, darts: DartLegs[]): PieceShape {
  let edges = shape.edges
  const onSegment = (p: Pt, a: Pt, b: Pt) => {
    const len = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (len < 1e-9) return null
    const t = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / (len * len)
    if (t < -1e-6 || t > 1 + 1e-6) return null
    const d = Math.hypot(a[0] + (b[0] - a[0]) * t - p[0], a[1] + (b[1] - a[1]) * t - p[1])
    return d < 0.1 ? t : null
  }
  // Position of p along an edge as (segment index + fraction), or null.
  const locate = (e: OutlineEdge, p: Pt) => {
    for (let i = 0; i < e.pts.length - 1; i++) {
      const t = onSegment(p, e.pts[i], e.pts[i + 1])
      if (t !== null) return i + Math.min(1, Math.max(0, t))
    }
    return null
  }
  darts.forEach((dart, k) => {
    const ei = edges.findIndex(e => locate(e, dart.a[0]) !== null && locate(e, dart.b[0]) !== null)
    if (ei < 0) return
    const e = edges[ei]
    const la = locate(e, dart.a[0])!
    const lb = locate(e, dart.b[0])!
    const [first, second, s1, s2] = la <= lb ? [dart.a, dart.b, la, lb] : [dart.b, dart.a, lb, la]
    const before = [...e.pts.slice(0, Math.floor(s1) + 1), first[0]]
    const after = [second[0], ...e.pts.slice(Math.floor(s2) + 1)]
    const apex = first[1]
    edges = [
      ...edges.slice(0, ei),
      { ...e, pts: before },
      { id: `dart:${k}:a`, label: 'dart', isFold: false, pts: [first[0], apex] },
      { id: `dart:${k}:b`, label: 'dart', isFold: false, pts: [apex, second[0]] },
      { ...e, id: `${e.id}#after-dart-${k}`, pts: after },
      ...edges.slice(ei + 1),
    ]
  })
  const loop: Pt[] = []
  for (const e of edges) loop.push(...e.pts.slice(0, -1))
  return { edges, loop }
}

export function transformShape(shape: PieceShape, fn: (p: Pt) => Pt): PieceShape {
  return {
    edges: shape.edges.map(e => ({ ...e, pts: e.pts.map(fn) })),
    loop: shape.loop.map(fn),
  }
}

export function edgesWith(shape: PieceShape, labels: string[]): OutlineEdge[] {
  return shape.edges.filter(e => labels.includes(e.label) || (labels.includes('fold') && e.isFold))
}

export function allPoints(edges: OutlineEdge[]): Pt[] {
  return edges.flatMap(e => e.pts)
}

export function yRange(edges: OutlineEdge[]): [number, number] {
  const ys = allPoints(edges).map(p => p[1])
  return [Math.min(...ys), Math.max(...ys)]
}

export function xRange(edges: OutlineEdge[]): [number, number] {
  const xs = allPoints(edges).map(p => p[0])
  return [Math.min(...xs), Math.max(...xs)]
}

// x positions where the horizontal line at y crosses the edges.
export function xsAtY(edges: OutlineEdge[], y: number): number[] {
  const out: number[] = []
  for (const e of edges) {
    for (let i = 0; i < e.pts.length - 1; i++) {
      const [x1, y1] = e.pts[i]
      const [x2, y2] = e.pts[i + 1]
      if ((y < Math.min(y1, y2)) || (y > Math.max(y1, y2))) continue
      if (y1 === y2) out.push(x1, x2)
      else out.push(x1 + ((y - y1) / (y2 - y1)) * (x2 - x1))
    }
  }
  return out
}

// y positions where the vertical line at x crosses the edges.
export function ysAtX(edges: OutlineEdge[], x: number): number[] {
  const out: number[] = []
  for (const e of edges) {
    for (let i = 0; i < e.pts.length - 1; i++) {
      const [x1, y1] = e.pts[i]
      const [x2, y2] = e.pts[i + 1]
      if ((x < Math.min(x1, x2)) || (x > Math.max(x1, x2))) continue
      if (x1 === x2) out.push(y1, y2)
      else out.push(y1 + ((x - x1) / (x2 - x1)) * (y2 - y1))
    }
  }
  return out
}

function inside(poly: Pt[], x: number, y: number): boolean {
  let c = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]
    const [xj, yj] = poly[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c
  }
  return c
}

function segmentDistance(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const len2 = dx * dx + dy * dy
  const t = len2 > 0 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) : 0
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
}

export interface PieceMesh {
  pts: Pt[]
  tris: [number, number, number][]
  // Per outline edge (same order as shape.edges): its boundary vertices from
  // start to end (endpoints shared with the neighbouring edges) and each
  // vertex's arc-length fraction along the edge.
  edgeVerts: number[][]
  edgeT: number[][]
}

// Samples a polyline every ~spacing by arc length (or into exactly `count`
// intervals); returns points (without the final endpoint) and their arc-length fractions.
function resample(pts: Pt[], spacing: number, count?: number): { pts: Pt[]; t: number[] } {
  const cum = [0]
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  const total = cum[cum.length - 1]
  if (total < 1e-6) return { pts: [], t: [] }
  const n = count ?? Math.max(1, Math.round(total / spacing))
  const out: Pt[] = []
  const ts: number[] = []
  let seg = 0
  for (let k = 0; k < n; k++) {
    const s = (total * k) / n
    while (seg < pts.length - 2 && cum[seg + 1] < s) seg++
    const f = (s - cum[seg]) / Math.max(cum[seg + 1] - cum[seg], 1e-9)
    out.push([pts[seg][0] + (pts[seg + 1][0] - pts[seg][0]) * f, pts[seg][1] + (pts[seg + 1][1] - pts[seg][1]) * f])
    ts.push(k / n)
  }
  return { pts: out, t: ts }
}

// Triangulates a piece with interior points on a grid (so the flat piece can
// bend on the body), keeping track of which boundary vertices lie on which
// outline edge (so seams can be sewn). `counts` fixes the number of intervals
// on particular edges, so both sides of a seam get matching vertices.
export function triangulateShape(shape: PieceShape, spacing: number, counts?: (number | undefined)[]): PieceMesh {
  const boundary: Pt[] = []
  const edgeVerts: number[][] = []
  const edgeT: number[][] = []
  for (const [ei, e] of shape.edges.entries()) {
    const r = resample(e.pts, spacing, counts?.[ei])
    const verts: number[] = []
    r.pts.forEach(p => {
      verts.push(boundary.length)
      boundary.push(p)
    })
    edgeVerts.push(verts)
    edgeT.push(r.t)
  }
  // Each edge ends where the next begins: append that shared vertex.
  for (let k = 0; k < edgeVerts.length; k++) {
    let next = (k + 1) % edgeVerts.length
    while (edgeVerts[next].length === 0 && next !== k) next = (next + 1) % edgeVerts.length
    edgeVerts[k].push(edgeVerts[next][0] ?? 0)
    edgeT[k].push(1)
  }
  const mesh = triangulateBoundary(boundary, spacing)
  return { ...mesh, edgeVerts, edgeT }
}

function triangulateBoundary(boundary: Pt[], spacing: number): { pts: Pt[]; tris: [number, number, number][] } {
  const xs = boundary.map(p => p[0])
  const ys = boundary.map(p => p[1])
  const interior: Pt[] = []
  for (let y = Math.min(...ys) + spacing / 2; y < Math.max(...ys); y += spacing) {
    for (let x = Math.min(...xs) + spacing / 2; x < Math.max(...xs); x += spacing) {
      if (!inside(boundary, x, y)) continue
      let d = Infinity
      for (let i = 0; i < boundary.length && d > spacing * 0.45; i++) {
        d = Math.min(d, segmentDistance([x, y], boundary[i], boundary[(i + 1) % boundary.length]))
      }
      if (d > spacing * 0.45) interior.push([x, y])
    }
  }
  const pts = [...boundary, ...interior]
  const edges = boundary.map((_, i) => [i, (i + 1) % boundary.length] as [number, number])
  const tris = cdt2d(pts, edges, { exterior: false })
  return { pts, tris }
}

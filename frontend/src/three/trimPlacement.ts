import type { CanvasElement, PatternPiece, Placement, SeamConnection, SeamEnd } from '../types'
import type { BodyQuery, Pt } from './bodyQuery'
import type { CopySpec, PlacedCopy, PlacedPiece, Pin } from './garmentWrap'
import { elementSampler, insideLoop, triangulateShape } from './pieceGeometry'
import type { PieceShape } from './pieceGeometry'
import { applyMatrix, pieceCenter, placementMatrix } from '../utils/placement'
import type { Vec3 } from './types'

// Trims and placed pieces on the body. The garment shell is wrapped onto the
// body region by region (garmentWrap.ts); everything else is positioned from
// what it is attached to:
//
//  - a SEAM-ATTACHED trim (waistband, cuff, collar, facing, fly, pocket bag)
//    starts at the host edge it is sewn to. Each trim vertex is found by its
//    nearest point on the sewn trim edge (which seam stretch, how far along)
//    and its distance from that edge. Outer trims sewn to an opening
//    (waist, wrist, neckline, hem, armhole) *continue* the host surface past
//    the edge — a waistband rises, a cuff hangs over the hand, a collar
//    stands. Everything else *overlays* the host: it lies over (outer) or
//    under (inside: facings, fly, bags) the host fabric, folded back from the
//    seam, one layer away. Its seams are welded like any other.
//  - a PLACED piece (pocket) is mapped through its placement transform onto
//    the host's surface, one layer out (or in), and pinned there: firmly along
//    its stitched edges, lightly elsewhere so it lies on the host.
//
// A trim can hang from another trim (a cuff on a sleeve band), so pieces are
// placed in passes until nothing more attaches.

export const LAYER = 0.3 // cm between a layer and the fabric it lies on
const CONTINUES = new Set(['waist', 'waist_seam', 'wrist', 'neckline', 'hem', 'armhole', 'yoke_seam'])
const PIN_STITCHED = 1
const PIN_LIES = 0.25

export interface TrimInput { piece: PatternPiece; shape: PieceShape }

export interface TrimContext {
  connections: SeamConnection[]
  placements: Placement[]
  byId: Map<string, CanvasElement>
  body: BodyQuery
  pushOut: (q: Vec3) => Vec3
  counts: Map<string, (number | undefined)[]>
  spacing: number
  outlines: Map<string, Pt[]> // every piece's outline loop in canvas coordinates
}

type Side = 'left' | 'right'

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const add = (a: Vec3, b: Vec3, k = 1): Vec3 => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k]
const norm = (a: Vec3): Vec3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1
  return [a[0] / l, a[1] / l, a[2] / l]
}

// The body's outward normal near p (distance-field gradient).
function outward(body: BodyQuery, p: Vec3): Vec3 {
  const e = 0.05
  const [x, y, z] = p
  return norm([
    body.sdf(x + e, y, z) - body.sdf(x - e, y, z),
    body.sdf(x, y + e, z) - body.sdf(x, y - e, z),
    body.sdf(x, y, z + e) - body.sdf(x, y, z - e),
  ])
}

// Which side of the body (the wearer's; left is +x) a placed copy is on.
export function copySide(p: PlacedPiece, copy: number): Side {
  const pos = p.copies[copy].positions
  let sx = 0
  for (let i = 0; i < pos.length; i += 3) sx += pos[i]
  return sx >= 0 ? 'left' : 'right'
}

// The host triangle (flat, local coordinates) containing q, as barycentric
// weights; the nearest vertex when q is outside the host.
export function barycentric(host: PlacedPiece, q: Pt): { tri: [number, number, number]; w: [number, number, number] } {
  const { pts, tris } = host.mesh
  for (const [a, b, c] of tris) {
    const [ax, ay] = pts[a], [bx, by] = pts[b], [cx, cy] = pts[c]
    const det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if (Math.abs(det) < 1e-12) continue
    const w0 = ((by - cy) * (q[0] - cx) + (cx - bx) * (q[1] - cy)) / det
    const w1 = ((cy - ay) * (q[0] - cx) + (ax - cx) * (q[1] - cy)) / det
    const w2 = 1 - w0 - w1
    if (w0 >= -1e-6 && w1 >= -1e-6 && w2 >= -1e-6) return { tri: [a, b, c], w: [w0, w1, w2] }
  }
  let best = 0, bd = Infinity
  pts.forEach((p, i) => { const d = Math.hypot(p[0] - q[0], p[1] - q[1]); if (d < bd) { bd = d; best = i } })
  return { tri: [best, best, best], w: [1, 0, 0] }
}

// Faces wound so their normals point away from the body (consistent shading).
function wound(tris: [number, number, number][], positions: Float32Array, body: BodyQuery): Uint32Array {
  const out = new Uint32Array(tris.length * 3)
  let score = 0
  for (const [a, b, c] of tris.slice(0, 40)) {
    const P = (i: number): Vec3 => [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]]
    const e1 = sub(P(b), P(a)), e2 = sub(P(c), P(a))
    const n: Vec3 = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
    const o = outward(body, P(a))
    score += n[0] * o[0] + n[1] * o[1] + n[2] * o[2]
  }
  tris.forEach(([a, b, c], i) => out.set(score >= 0 ? [a, b, c] : [a, c, b], i * 3))
  return out
}

interface Attach { trimEnd: SeamEnd; hostEnd: SeamEnd; reversed: boolean; host: number }

export function placeTrims(trims: TrimInput[], shell: PlacedPiece[], ctx: TrimContext): { placed: PlacedPiece[]; unattached: TrimInput[] } {
  const all = [...shell]
  const indexOf = (id: string) => all.findIndex(p => p.id === id)
  let pending = [...trims]
  for (let progress = true; progress && pending.length;) {
    progress = false
    for (const t of [...pending]) {
      // A piece may be placed more than once (a left and a right pocket after
      // unlinking a pair): one placed piece carrying the copies of all of them.
      const pls = ctx.placements.filter(p => p.pieceId === t.piece.id && indexOf(p.hostId) >= 0)
      let piece: PlacedPiece | null = null
      if (pls.length) piece = mergePlaced(pls.map(pl => placeOnHost(t, pl, all, indexOf(pl.hostId), ctx)))
      else {
        const attach: Attach[] = []
        for (const c of ctx.connections) {
          const mine = c.from.pieceId === t.piece.id ? c.from : c.to.pieceId === t.piece.id ? c.to : null
          const other = mine === c.from ? c.to : c.from
          if (!mine || other.pieceId === t.piece.id) continue
          const host = indexOf(other.pieceId)
          if (host >= 0) attach.push({ trimEnd: mine, hostEnd: other, reversed: !!c.reversed, host })
        }
        if (attach.length) piece = sewOn(t, attach, all, ctx)
      }
      if (piece) {
        all.push(piece)
        pending = pending.filter(p => p !== t)
        progress = true
      }
    }
  }
  return { placed: all.slice(shell.length), unattached: pending }
}

// ── Placed pieces (pockets) ───────────────────────────────────────────────────

// Several placements of one piece → one placed piece with all their copies.
function mergePlaced(list: PlacedPiece[]): PlacedPiece {
  if (list.length === 1) return list[0]
  const [first] = list
  const owner = list.flatMap(p => p.copies.map((_, i) => ({ p, i })))
  return {
    ...first,
    copies: list.flatMap(p => p.copies),
    copySpecs: list.flatMap(p => p.copySpecs),
    pins: list.flatMap(p => p.pins ?? p.copies.map(() => [])),
    mapPoint: (x, y, copy) => owner[copy].p.mapPoint(x, y, owner[copy].i),
  }
}

// A point on an element (fraction of its length, element direction), its
// distance from q, and the element's inward normal there (into `loop`).
function projectOnElement(el: CanvasElement, q: Pt): { f: number; d: number } {
  const at = elementSampler(el)!
  const N = 48
  let best = { f: 0, d: Infinity }
  let prev = at(0)
  for (let k = 1; k <= N; k++) {
    const cur = at(k / N)
    const dx = cur[0] - prev[0], dy = cur[1] - prev[1]
    const l2 = dx * dx + dy * dy
    const u = l2 > 0 ? Math.max(0, Math.min(1, ((q[0] - prev[0]) * dx + (q[1] - prev[1]) * dy) / l2)) : 0
    const d = Math.hypot(prev[0] + dx * u - q[0], prev[1] + dy * u - q[1])
    if (d < best.d) best = { f: (k - 1 + u) / N, d }
    prev = cur
  }
  return best
}

function inwardAt(el: CanvasElement, f: number, loop: Pt[] | undefined): Pt {
  const at = elementSampler(el)!
  const a = at(Math.max(0, f - 0.01)), b = at(Math.min(1, f + 0.01))
  const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
  let n: Pt = [-(b[1] - a[1]) / l, (b[0] - a[0]) / l]
  const p = at(f)
  if (loop && !insideLoop(loop, p[0] + n[0] * 0.5, p[1] + n[1] * 0.5)) n = [-n[0], -n[1]]
  return n
}

// Where a placed piece's point q (in the host's pattern coordinates) lies on
// the garment. Inside the host: on the host. Past one of the host's sewn edges
// (a cargo pocket straddling the side seam): across that seam, as far in from
// the matching point of the other piece's seam as it is past this one — so the
// pocket continues onto the neighbouring panel exactly as if the seam weren't
// there. Otherwise the host's own surface, extrapolated.
interface Spot { host: number; copy: number; q: Pt }

function spotFor(q: Pt, hostIndex: number, hc: number, all: PlacedPiece[], ctx: TrimContext): Spot {
  const host = all[hostIndex]
  const loop = ctx.outlines.get(host.id)
  if (!loop || insideLoop(loop, q[0], q[1])) return { host: hostIndex, copy: hc, q }
  let best: { spot: Spot; d: number } | null = null
  for (const c of ctx.connections) {
    for (const [mine, theirs] of [[c.from, c.to], [c.to, c.from]] as const) {
      if (mine.pieceId !== host.id || theirs.pieceId === host.id) continue
      const bi = all.findIndex(p => p.id === theirs.pieceId)
      const ea = ctx.byId.get(mine.edgeId), eb = ctx.byId.get(theirs.edgeId)
      if (bi < 0 || !ea || !eb || all[bi].region === 'trim') continue
      const { f, d } = projectOnElement(ea, q)
      const [lo, hi] = mine.range ?? [0, 1]
      if (f < Math.min(lo, hi) - 0.02 || f > Math.max(lo, hi) + 0.02) continue
      if (best && d >= best.d) continue
      const other = all[bi]
      // The other piece's copy on the same side (a sleeve: the matching half).
      const side = copySide(host, hc)
      const bc = other.copySpecs.findIndex((s, i) => copySide(other, i) === side && (other.region !== 'sleeve' || s.frontHalf === !host.back))
      if (bc < 0) continue
      // Which way the two seam edges run, from where they are on the body.
      const sa = elementSampler(ea)!, sb = elementSampler(eb)!
      const A0 = host.mapPoint(...sa(0), hc), B0 = other.mapPoint(...sb(0), bc), B1 = other.mapPoint(...sb(1), bc)
      const reversed = c.reversed ?? Math.hypot(...sub(A0, B1)) < Math.hypot(...sub(A0, B0))
      const u = Math.max(0, Math.min(1, (f - lo) / ((hi - lo) || 1e-9)))
      const [blo, bhi] = theirs.range ?? [0, 1]
      const g = reversed ? bhi - u * (bhi - blo) : blo + u * (bhi - blo)
      const P = sb(g)
      const n = inwardAt(eb, g, ctx.outlines.get(other.id))
      best = { spot: { host: bi, copy: bc, q: [P[0] + n[0] * d, P[1] + n[1] * d] }, d }
    }
  }
  return best && best.d < 40 ? best.spot : { host: hostIndex, copy: hc, q }
}

function placeOnHost(t: TrimInput, pl: Placement, all: PlacedPiece[], hostIndex: number, ctx: TrimContext): PlacedPiece {
  const host = all[hostIndex]
  const M = placementMatrix(pl, pieceCenter(t.piece, ctx.byId))
  const layer = t.piece.layer ?? 'outer'
  const sign = layer === 'inside' ? -1 : 1
  // One copy per host copy it goes on (both sides, or the chosen one; a
  // sleeve's front half only).
  const hostCopies = host.copySpecs.map((_, i) => i).filter(i =>
    (!pl.side || copySide(host, i) === pl.side) && (host.region !== 'sleeve' || host.copySpecs[i].frontHalf))
  const mesh = triangulateShape(t.shape, ctx.spacing, ctx.counts.get(t.piece.id))
  const stitchedEdges = t.shape.edges.map((e, i) => (pl.stitched.includes(e.base) ? i : -1)).filter(i => i >= 0)
  const stitchedVerts = new Set(stitchedEdges.flatMap(i => mesh.edgeVerts[i]))
  const onHost = mesh.pts.map(([x, y]) => applyMatrix(M, x, y) as Pt)

  const at = (s: Spot): Vec3 => {
    const x0 = all[s.host].mapPoint(s.q[0], s.q[1], s.copy)
    return add(x0, outward(ctx.body, x0), sign * LAYER)
  }
  const copies: PlacedCopy[] = []
  const pins: Pin[][] = []
  for (const hc of hostCopies) {
    const spots = onHost.map(q => spotFor(q, hostIndex, hc, all, ctx))
    const positions = new Float32Array(mesh.pts.length * 3)
    spots.forEach((s, i) => positions.set(at(s), i * 3))
    copies.push({ positions, indices: wound(mesh.tris, positions, ctx.body), ease: new Float32Array(mesh.pts.length).fill(1) })
    pins.push(spots.map((s, i) => ({
      vertex: i, host: s.host, hostCopy: s.copy, ...barycentric(all[s.host], all[s.host].toLocal(s.q)),
      stiffness: stitchedVerts.has(i) ? PIN_STITCHED : PIN_LIES, offset: sign * LAYER,
    })))
  }
  return {
    id: t.piece.id, name: t.piece.name, region: 'trim', back: false, onFold: t.piece.onFold, layer,
    copies, copySpecs: hostCopies.map(hc => host.copySpecs[hc]), mesh,
    edges: t.shape.edges.map(({ id, label, isFold, base, span, flipped }) => ({ id, label, isFold, base, span, flipped })),
    mapPoint: (x, y, copy) => at(spotFor(applyMatrix(M, x, y) as Pt, hostIndex, hostCopies[copy] ?? 0, all, ctx)),
    toLocal: p => p,
    pins,
    stitchedEdges,
  }
}

// ── Seam-attached trims ───────────────────────────────────────────────────────

interface TrimCopy { spec: CopySpec; side: Side | 'both' }

function sewOn(t: TrimInput, attach: Attach[], all: PlacedPiece[], ctx: TrimContext): PlacedPiece {
  const layer = t.piece.layer ?? 'outer'
  const sign = layer === 'inside' ? -1 : 1
  const firstEdge = ctx.byId.get(attach[0].hostEnd.edgeId) as { seamLabel?: string } | undefined
  const continues = layer === 'outer' && CONTINUES.has(firstEdge?.seamLabel ?? '')

  // Copies: a trim sewn to both sides of the body (a full collar or waistband)
  // is one piece; one sewn to one named side is one copy there; otherwise one
  // per side the host is on (cut 2 / on the fold) or just the first.
  const sides = new Set(attach.map(a => a.hostEnd.side).filter((s): s is Side => !!s))
  const host0 = all[attach[0].host]
  let copies: TrimCopy[]
  if (sides.size === 2) copies = [{ spec: { mirrorWorld: false, frontHalf: true }, side: 'both' }]
  else if (sides.size === 1) {
    const side = [...sides][0]
    copies = [{ spec: { mirrorWorld: side === 'right' ? false : true, frontHalf: true }, side }]
  } else {
    const mirrors = [...new Set(host0.copySpecs.map(s => s.mirrorWorld))]
    const wanted = t.piece.cutQty >= 2 || t.piece.onFold ? mirrors : mirrors.slice(0, 1)
    copies = wanted.map(m => {
      const hc = host0.copySpecs.findIndex(s => s.mirrorWorld === m)
      return { spec: { mirrorWorld: m, frontHalf: true }, side: copySide(host0, hc) }
    })
  }

  const hostCopyFor = (a: Attach, tc: TrimCopy): number => {
    const host = all[a.host]
    const ok = host.copySpecs.map((_, i) => i).filter(i => {
      const s = host.copySpecs[i]
      if (a.hostEnd.side && copySide(host, i) !== a.hostEnd.side) return false
      if (!a.hostEnd.side && tc.side !== 'both' && s.mirrorWorld !== tc.spec.mirrorWorld) return false
      if (host.region === 'sleeve') return a.hostEnd.half ? s.frontHalf === (a.hostEnd.half === 'front') : s.frontHalf
      return true
    })
    return ok[0] ?? 0
  }

  const mesh = triangulateShape(t.shape, ctx.spacing, ctx.counts.get(t.piece.id))
  const attachedBases = new Set(attach.map(a => a.trimEnd.edgeId))
  const sewnParts = t.shape.edges.map((e, i) => ({ e, i })).filter(({ e }) => attachedBases.has(e.base))

  // Each vertex: nearest point on the sewn trim edge (element, fraction along
  // it in the element's direction) and distance from it.
  const nearest = (p: Pt): { base: string; g: number; d: number } => {
    let best = { base: sewnParts[0].e.base, g: 0, d: Infinity }
    for (const { e } of sewnParts) {
      const pts = e.pts
      let walked = 0
      const total = pts.reduce((s, q, k) => (k ? s + Math.hypot(q[0] - pts[k - 1][0], q[1] - pts[k - 1][1]) : 0), 0) || 1e-9
      for (let k = 0; k < pts.length - 1; k++) {
        const [ax, ay] = pts[k], [bx, by] = pts[k + 1]
        const dx = bx - ax, dy = by - ay
        const len = Math.hypot(dx, dy)
        const u = len > 0 ? Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (len * len))) : 0
        const d = Math.hypot(ax + dx * u - p[0], ay + dy * u - p[1])
        if (d < best.d) {
          const f = (walked + u * len) / total // along this part, in loop order
          const [s0, s1] = e.span
          best = { base: e.base, g: e.flipped ? s1 - f * (s1 - s0) : s0 + f * (s1 - s0), d }
        }
        walked += len
      }
    }
    return best
  }
  const where = mesh.pts.map(nearest)

  const samplers = new Map(attach.map(a => [a.hostEnd.edgeId, elementSampler(ctx.byId.get(a.hostEnd.edgeId)!)]))
  // The host point a trim fraction is sewn to, and the host's inward direction there (canvas).
  const seamAt = (base: string, g: number) => {
    let best = attach[0], bd = Infinity
    for (const a of attach) {
      if (a.trimEnd.edgeId !== base) continue
      const [lo, hi] = a.trimEnd.range ?? [0, 1]
      const d = g < Math.min(lo, hi) ? Math.min(lo, hi) - g : g > Math.max(lo, hi) ? g - Math.max(lo, hi) : 0
      if (d < bd) { bd = d; best = a }
    }
    const [lo, hi] = best.trimEnd.range ?? [0, 1]
    const u = Math.max(0, Math.min(1, (g - lo) / ((hi - lo) || 1e-9)))
    const [hlo, hhi] = best.hostEnd.range ?? [0, 1]
    const hf = best.reversed ? hhi - u * (hhi - hlo) : hlo + u * (hhi - hlo)
    const at = samplers.get(best.hostEnd.edgeId)!
    const P = at(hf)
    const a0 = at(hf - 0.01), a1 = at(hf + 0.01)
    const tl = Math.hypot(a1[0] - a0[0], a1[1] - a0[1]) || 1
    let n: Pt = [-(a1[1] - a0[1]) / tl, (a1[0] - a0[0]) / tl]
    const loop = ctx.outlines.get(best.hostEnd.pieceId)
    if (loop && !insideLoop(loop, P[0] + n[0] * 0.5, P[1] + n[1] * 0.5)) n = [-n[0], -n[1]]
    return { a: best, P, inward: n }
  }

  // A band round the whole body longer than the opening keeps the extra as an
  // overlap at one end. The ring closes there, so the overlap carries on past
  // the end over the band's start and is fastened to it (button/hook), instead
  // of bunching at the end and hanging loose. `lap(g)` is the band fraction the
  // overlap point lies over (undefined off the overlap).
  let lap: (g: number) => number | undefined = () => undefined
  const bandEdgeAt = sewnParts.length ? elementSampler(ctx.byId.get(sewnParts[0].e.base)!) : null
  if (bandEdgeAt && continues && copies.length === 1 && copies[0].side === 'both' && attachedBases.size === 1) {
    const rs = attach.map(a => a.trimEnd.range ?? [0, 1])
    const lo = Math.min(...rs.map(r => Math.min(r[0], r[1]))), hi = Math.max(...rs.map(r => Math.max(r[0], r[1])))
    const E = 0.02
    if (lo < E && hi < 1 - E && 1 - hi < hi - lo) lap = g => (g > hi + 1e-3 ? lo + (g - hi) : undefined)
    else if (hi > 1 - E && lo > E && lo < hi - lo) lap = g => (g < lo - 1e-3 ? hi - (lo - g) : undefined)
  }

  const trimCopies: PlacedCopy[] = []
  const pins: Pin[][] = []
  const position = (i: number, tc: TrimCopy, pinsOut?: Pin[]): Vec3 => {
    const { base, g, d } = where[i]
    const under = lap(g)
    if (under !== undefined) {
      const { a, P, inward } = seamAt(base, under)
      const host = all[a.host], hc = hostCopyFor(a, tc)
      const H = host.mapPoint(P[0], P[1], hc)
      const Hin = host.mapPoint(P[0] + inward[0], P[1] + inward[1], hc)
      const X = ctx.pushOut(add(H, norm(sub(H, Hin)), d))
      // Fastened over the band's own start, one layer out.
      const [ux, uy] = bandEdgeAt!(under), [gx, gy] = bandEdgeAt!(g)
      const q: Pt = [mesh.pts[i][0] + ux - gx, mesh.pts[i][1] + uy - gy]
      pinsOut?.push({ vertex: i, host: -1, hostCopy: 0, ...barycentric({ mesh } as PlacedPiece, q), stiffness: 0.6, offset: LAYER, mutual: true })
      return add(X, outward(ctx.body, X), LAYER)
    }
    const { a, P, inward } = seamAt(base, g)
    const host = all[a.host]
    const hc = hostCopyFor(a, tc)
    if (continues) {
      const H = host.mapPoint(P[0], P[1], hc)
      const Hin = host.mapPoint(P[0] + inward[0], P[1] + inward[1], hc)
      return ctx.pushOut(add(H, norm(sub(H, Hin)), d))
    }
    const Q: Pt = [P[0] + inward[0] * d, P[1] + inward[1] * d]
    const X0 = host.mapPoint(Q[0], Q[1], hc)
    if (pinsOut) pinsOut.push({ vertex: i, host: a.host, hostCopy: hc, ...barycentric(host, host.toLocal(Q)), stiffness: PIN_LIES, offset: sign * LAYER })
    return add(X0, outward(ctx.body, X0), sign * LAYER)
  }
  for (const tc of copies) {
    const positions = new Float32Array(mesh.pts.length * 3)
    const copyPins: Pin[] = []
    mesh.pts.forEach((_, i) => positions.set(position(i, tc, copyPins), i * 3))
    trimCopies.push({ positions, indices: wound(mesh.tris, positions, ctx.body), ease: new Float32Array(mesh.pts.length).fill(1) })
    pins.push(copyPins)
  }
  return {
    id: t.piece.id, name: t.piece.name, region: 'trim', back: false, onFold: t.piece.onFold, layer,
    copies: trimCopies, copySpecs: copies.map(c => c.spec), mesh,
    edges: t.shape.edges.map(({ id, label, isFold, base, span, flipped }) => ({ id, label, isFold, base, span, flipped })),
    mapPoint: (x, y, copy) => {
      // Rarely needed for trims: the nearest mesh vertex's position.
      let best = 0, bd = Infinity
      mesh.pts.forEach((p, i) => { const dd = Math.hypot(p[0] - x, p[1] - y); if (dd < bd) { bd = dd; best = i } })
      const pos = trimCopies[copy].positions
      return [pos[best * 3], pos[best * 3 + 1], pos[best * 3 + 2]]
    },
    toLocal: p => p,
    pins: pins.some(p => p.length) ? pins : undefined,
  }
}

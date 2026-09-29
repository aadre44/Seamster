import type { CanvasElement, PatternPiece, SeamConnection, SeamEnd } from '../types'
import type { BodyQuery, Pt, Section } from './bodyQuery'
import { perimeter } from './bodyQuery'
import { classifyPiece } from './pieceClassifier'
import type { Region } from './pieceClassifier'
import { allPoints, cutDarts, edgesWith, extractOutline, rangeCuts, seamParts, splitAtRanges, transformShape, triangulateShape, xRange, xsAtY, yRange, ysAtX } from './pieceGeometry'
import type { DartLegs, OutlineEdge, PieceMesh, PieceShape } from './pieceGeometry'
import type { Vec3 } from './types'

// Static fit preview: every flat pattern piece is wrapped onto the body.
//
// A row of a piece (a horizontal line in pattern space) is laid around the
// body's cross-section at the matching height, following the tape line
// (convex hull — fabric bridges hollows). The centre edge (fold / CF / CB)
// lands on the body's centre line and the side seam on its side line, so
// front and back side seams meet by construction. The fabric stands off the
// body by however much the garment's loop at that height (front + back) is
// longer than the body's — so ease and flare are visible — and a loop
// *shorter* than the body is reported as tight.
//
// Near the shoulder seam the fabric curves up over the shoulder onto its top
// ridge, so front and back shoulder seams meet. Trouser legs wrap a torso
// quadrant above the crotch and the leg below it. Sleeves follow the arm axis
// with the fold on top of the arm. Any point that would end up inside the
// body is pushed out onto its surface.

export const GAP = 0.35 // cm the fabric sits off the skin at zero ease
// Ease (fabric loop ÷ body tape) below which a band is shown as snug / tight.
// A tape reading and woven fabric both tolerate a couple of percent.
export const EASE_SNUG = 1.0
export const EASE_TIGHT = 0.97
const ROOF = 7 // cm below the shoulder seam over which fabric curves onto the shoulder top
const CROTCH_BLEND = 4
const MESH_SPACING = 2.0
const ARC_SAMPLES = 64

export interface PlacedCopy {
  positions: Float32Array
  indices: Uint32Array
  ease: Float32Array // fabric loop ÷ body loop at each vertex's height (< 1 = tight)
}

export interface CopySpec { mirrorWorld: boolean; frontHalf: boolean }

export interface PlacedPiece {
  id: string
  name: string
  region: Region
  back: boolean
  onFold: boolean
  copies: PlacedCopy[]
  copySpecs: CopySpec[] // mirrorWorld = the body's left side; frontHalf = sleeve half
  mesh: PieceMesh // flat (pattern-space) mesh shared by every copy
  // Same order as mesh.edgeVerts; base/span/flipped as in OutlineEdge (seamParts finds a seam's edges).
  edges: Pick<OutlineEdge, 'id' | 'label' | 'isFold' | 'base' | 'span' | 'flipped'>[]
  // Maps a point in the piece's original pattern coordinates onto the body for one copy.
  mapPoint: (x: number, y: number, copy: number) => Vec3
}

export interface GarmentPlacement {
  placed: PlacedPiece[]
  skipped: { id: string; name: string; reason: string }[]
}

// ── Arcs around a section ────────────────────────────────────────────────────

interface Arc { pts: Pt[]; cum: number[]; center: Pt }

function rayHull(s: Section, theta: number): number {
  const [cx, cz] = s.center
  const dx = Math.cos(theta)
  const dz = Math.sin(theta)
  let best = 0
  for (let i = 0; i < s.hull.length; i++) {
    const [ax, az] = s.hull[i]
    const [bx, bz] = s.hull[(i + 1) % s.hull.length]
    const ex = bx - ax
    const ez = bz - az
    const den = dx * ez - dz * ex
    if (Math.abs(den) < 1e-12) continue
    const t = ((ax - cx) * ez - (az - cz) * ex) / den
    const u = ((ax - cx) * dz - (az - cz) * dx) / den
    if (t > 0 && u >= -1e-9 && u <= 1 + 1e-9) best = Math.max(best, t)
  }
  return best
}

const arcCache = new WeakMap<Section, Map<string, Arc>>()

function sweepArc(s: Section, theta0: number, sweep: number): Arc {
  let bySection = arcCache.get(s)
  if (!bySection) {
    bySection = new Map()
    arcCache.set(s, bySection)
  }
  const key = `${theta0.toFixed(4)}:${sweep.toFixed(4)}`
  const hit = bySection.get(key)
  if (hit) return hit
  const pts: Pt[] = []
  const cum: number[] = []
  for (let i = 0; i <= ARC_SAMPLES; i++) {
    const th = theta0 + (sweep * i) / ARC_SAMPLES
    const r = rayHull(s, th)
    const p: Pt = [s.center[0] + r * Math.cos(th), s.center[1] + r * Math.sin(th)]
    cum.push(i === 0 ? 0 : cum[i - 1] + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]))
    pts.push(p)
  }
  const arc = { pts, cum, center: s.center }
  bySection.set(key, arc)
  return arc
}

// Point at arc length s (extrapolated along the end tangents), offset
// outward from the section centre by `offset`.
function arcPoint(arc: Arc, s: number, offset: number): Pt {
  const { pts, cum } = arc
  const n = pts.length - 1
  let i = 0
  if (s <= 0) i = 0
  else if (s >= cum[n]) i = n - 1
  else while (i < n - 1 && cum[i + 1] < s) i++
  const seg = Math.max(cum[i + 1] - cum[i], 1e-9)
  const f = (s - cum[i]) / seg
  const x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f
  const z = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f
  const rx = x - arc.center[0]
  const rz = z - arc.center[1]
  const r = Math.hypot(rx, rz) || 1
  return [x + (rx / r) * offset, z + (rz / r) * offset]
}

const standOff = (fabricLoop: number, bodyLoop: number) => Math.max(GAP, (fabricLoop - bodyLoop) / (2 * Math.PI) + GAP)

// ── Piece profiles ───────────────────────────────────────────────────────────

interface Profile {
  piece: PatternPiece
  region: Region
  back: boolean
  shape: PieceShape // normalised: centre edge on the left, top up (smaller y)
  toLocal: (p: Pt) => Pt
  x0: number // centre line
  side: OutlineEdge[]
  inner: OutlineEdge[] // inseam (legs)
  shoulder: OutlineEdge[]
  anchorRow: number
  // Row of a waist seam on a piece that also hangs from the shoulder (a dress
  // bodice): the seam is sewn at the body's waist, so it is a second anchor.
  waistRow: number | null
  hps: Pt | null
  darts: Dart[]
  crotchExt: number // legs: how far the crotch curve reaches past the centre line
  partner: Profile | null
}

// A dart: two legs meeting at the apex. Sewing it folds away the fabric
// between the legs, so on the body both legs land on the same point.
type Dart = DartLegs

function legXAt(leg: [Pt, Pt], y: number): number | null {
  const [[x1, y1], [x2, y2]] = leg
  if (y < Math.min(y1, y2) || y > Math.max(y1, y2) || y1 === y2) return null
  return x1 + ((y - y1) / (y2 - y1)) * (x2 - x1)
}

// Dart legs at row y, as [left, right] x pairs (only darts crossing the row).
function dartSpans(darts: Dart[], y: number): [number, number][] {
  const out: [number, number][] = []
  for (const d of darts) {
    const xa = legXAt(d.a, y)
    const xb = legXAt(d.b, y)
    if (xa !== null && xb !== null) out.push(xa < xb ? [xa, xb] : [xb, xa])
  }
  return out
}

// Distance from the centre line after the darts on this row are sewn: fabric
// inside a dart folds away onto its left leg.
function sewnDistance(p: Profile, x: number, y: number): number {
  let d = x - p.x0
  for (const [l, r] of dartSpans(p.darts, y)) {
    if (r <= p.x0) continue
    if (x >= r) d -= r - l
    else if (x > l) d -= x - l
  }
  return d
}

function findDarts(piece: PatternPiece, elements: CanvasElement[], toLocal: (p: Pt) => Pt): Dart[] {
  const outline = new Set(piece.elementIds)
  const legs: [Pt, Pt][] = elements
    .filter(e => e.type === 'line' && e.pieceId === piece.id && !outline.has(e.id) && !e.seamLabel && !e.isFold)
    .map(e => {
      const l = e as Extract<CanvasElement, { type: 'line' }>
      return [toLocal([l.start.x, l.start.y]), toLocal([l.end.x, l.end.y])]
    })
  const darts: Dart[] = []
  const used = new Set<number>()
  const same = (p: Pt, q: Pt) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.05
  for (let i = 0; i < legs.length; i++) {
    if (used.has(i)) continue
    for (let j = i + 1; j < legs.length; j++) {
      if (used.has(j)) continue
      for (const [ai, bi] of [[0, 1], [1, 0]]) {
        for (const [aj, bj] of [[0, 1], [1, 0]]) {
          if (used.has(j) || !same(legs[i][bi], legs[j][bj])) continue
          const apex = legs[i][bi]
          // Only darts that run mostly vertically (waist darts) take width out of a row.
          const tall = (leg: Pt) => Math.abs(apex[1] - leg[1]) > Math.abs(apex[0] - leg[0])
          if (tall(legs[i][ai]) && tall(legs[j][aj])) darts.push({ a: [legs[i][ai], apex], b: [legs[j][aj], apex] })
          used.add(i)
          used.add(j)
        }
      }
    }
  }
  return darts
}

const CENTER = ['center_front', 'center_back', 'center_sleeve', 'fold']
const SIDE = ['side_seam', 'sleeve_seam']
const TOP = ['waist', 'waist_seam', 'shoulder', 'neckline']
const BOTTOM = ['hem', 'wrist']

const meanOf = (edges: OutlineEdge[], k: 0 | 1) => {
  const pts = allPoints(edges)
  return pts.reduce((s, p) => s + p[k], 0) / pts.length
}

function makeProfile(piece: PatternPiece, shape: PieceShape, region: Region, back: boolean, elements: CanvasElement[]): Profile {
  const center = edgesWith(shape, CENTER)
  const side = edgesWith(shape, SIDE)
  const top = edgesWith(shape, region === 'sleeve' ? [...TOP, 'armhole'] : TOP)
  const bottom = edgesWith(shape, BOTTOM)
  // Users may have flipped a piece on the canvas; bring it back to the
  // engine's convention (centre edge left, top up).
  const mirrorX = center.length > 0 && side.length > 0 && meanOf(center, 0) > meanOf(side, 0)
  const flipY = top.length > 0 && bottom.length > 0 && meanOf(top, 1) > meanOf(bottom, 1)
  const toLocal = (p: Pt): Pt => [mirrorX ? -p[0] : p[0], flipY ? -p[1] : p[1]]
  const s = transformShape(shape, toLocal)
  const c = edgesWith(s, CENTER)
  const sd = edgesWith(s, SIDE)
  const x0 = c.length ? meanOf(c, 0) : xRange(s.edges)[0]
  const shoulder = edgesWith(s, ['shoulder'])
  let anchorRow = yRange(s.edges)[0]
  let hps: Pt | null = null
  let waistRow: number | null = null
  if (region === 'torso-upper' && shoulder.length) {
    hps = allPoints(shoulder).reduce((a, p) => (p[0] < a[0] ? p : a))
    anchorRow = hps[1]
    const waistSeam = edgesWith(s, ['waist_seam', 'waist'])
    if (waistSeam.length) {
      // The waist seam's height at the side seam (where the body's waist is measured).
      const sideBottom = sd.length ? yRange(sd)[1] : yRange(waistSeam)[0]
      waistRow = Math.min(Math.max(sideBottom, yRange(waistSeam)[0]), yRange(waistSeam)[1])
    }
  } else if ((region === 'torso-lower' || region === 'leg') && sd.length) {
    anchorRow = yRange(sd)[0]
  }
  return {
    piece, region, back, shape: s, toLocal, x0, side: sd, inner: edgesWith(s, ['inseam']), shoulder,
    anchorRow, waistRow, hps, darts: findDarts(piece, elements, toLocal),
    crotchExt: region === 'leg' ? Math.max(0, x0 - xRange(s.edges)[0]) : 0,
    partner: null,
  }
}

// x of an edge set at row y, clamping y into the edges' vertical extent.
function edgeX(edges: OutlineEdge[], y: number, pick: 'max' | 'min'): number | null {
  if (!edges.length) return null
  const [lo, hi] = yRange(edges)
  const xs = xsAtY(edges, Math.min(Math.max(y, lo), hi))
  if (!xs.length) return null
  return pick === 'max' ? Math.max(...xs) : Math.min(...xs)
}

// Sewn width of a row from the centre line to the side seam (darts closed).
function widthAt(p: Profile, y: number): number {
  const sx = edgeX(p.side, y, 'max') ?? xRange(p.shape.edges)[1]
  return Math.max(1, sewnDistance(p, sx, y))
}

// ── Mapping ──────────────────────────────────────────────────────────────────

interface Mapped { p: Vec3; ease: number }

function sectionNear(get: (k: number) => Section | null, k: number): Section {
  for (let i = 0; i < 400; i++) {
    const s = get(k + i * 0.5) ?? get(k - i * 0.5)
    if (s) return s
  }
  throw new Error('body has no sections')
}

class Wrapper {
  private neck: { section: Section; y: number }
  private neckSide: Pt
  private hpsY: number

  constructor(private body: BodyQuery) {
    this.neck = body.neckSection()
    this.neckSide = this.neck.section.hull.reduce((a, p) => (p[0] > a[0] ? p : a))
    this.hpsY = body.topY(this.neckSide[0] + 1)
  }

  // Vertical scale: 1 cm of pattern per cm of height, except a piece anchored
  // at both the neck and the waist, which is stretched to span the two.
  private scale(p: Profile): number {
    if (p.waistRow === null) return 1
    return (this.hpsY - this.body.waistY) / Math.max(p.waistRow - p.anchorRow, 1)
  }

  bodyY(p: Profile, row: number): number {
    const anchor = p.region === 'torso-upper' ? this.hpsY : this.body.waistY
    return anchor - (row - p.anchorRow) * this.scale(p)
  }

  rowAt(p: Profile, y: number): number {
    const anchor = p.region === 'torso-upper' ? this.hpsY : this.body.waistY
    return p.anchorRow + (anchor - y) / this.scale(p)
  }

  // A row of a torso piece around the body at its height.
  torso(p: Profile, row: number, d: number): Mapped {
    const y = this.bodyY(p, row)
    const sec = sectionNear(k => this.body.wrapSection(k), y)
    const w = widthAt(p, row)
    const wp = p.partner ? widthAt(p.partner, this.rowAt(p.partner, y)) : w
    const fabric = 2 * (w + wp)
    const bodyLoop = perimeter(sec.hull)
    const arc = sweepArc(sec, p.back ? -Math.PI / 2 : Math.PI / 2, p.back ? Math.PI : -Math.PI)
    const sideArc = arc.cum[ARC_SAMPLES / 2]
    const [x, z] = arcPoint(arc, (d * sideArc) / w, standOff(fabric, bodyLoop))
    return { p: [x, y, z], ease: fabric / bodyLoop }
  }

  // Upper torso: curves over the shoulder top near the shoulder seam.
  upper(p: Profile, X: number, Y: number): Mapped {
    const d = sewnDistance(p, X, Y)
    const regular = this.torso(p, Y, d)
    if (!p.shoulder.length || !p.hps) return regular
    const [sx0, sx1] = xRange(p.shoulder)
    const ys = ysAtX(p.shoulder, Math.min(Math.max(X, sx0), sx1))
    const seamY = ys.length ? Math.min(...ys) : p.hps[1]
    const dv = Y - seamY
    if (dv >= ROOF) return regular
    const below = this.torso(p, seamY + ROOF, d)
    const dHps = p.hps[0] - p.x0
    let top: Vec3
    if (d <= dHps) {
      // Between the centre and the neck point: around the base of the neck.
      const arc = sweepArc(this.neck.section, p.back ? -Math.PI / 2 : Math.PI / 2, p.back ? Math.PI / 2 : -Math.PI / 2)
      const [x, z] = arcPoint(arc, (Math.max(d, 0) / Math.max(dHps, 1e-6)) * arc.cum[ARC_SAMPLES], GAP)
      top = [x, this.hpsY + GAP, z]
    } else {
      // Along the shoulder ridge, 1:1 from the neck point.
      const x = this.neckSide[0] + (d - dHps)
      top = [x, this.body.topY(x) + GAP, this.body.ridgeZ]
    }
    const phi = Math.max(0, dv) / ROOF
    const a = (phi * Math.PI) / 2
    return {
      p: [
        top[0] + (below.p[0] - top[0]) * phi,
        top[1] + (below.p[1] - top[1]) * (1 - Math.cos(a)),
        top[2] + (below.p[2] - top[2]) * Math.sin(a),
      ],
      ease: below.ease,
    }
  }

  leg(p: Profile, X: number, Y: number): Mapped {
    const y = this.bodyY(p, Y)
    const yc = this.body.crotchY
    // The crotch extension (left of the centre line) passes UNDER the body:
    // from the centre line it runs down to one crotch point beneath the torso,
    // where the front and back crotch curves (and the inseams) meet.
    // Only the crotch curve itself: rows at or above where the inseam starts
    // (below that, the inseam runs down the inner leg).
    const inseamTop = p.inner.length ? yRange(p.inner)[0] : Infinity
    if (X < p.x0 && p.crotchExt > 0 && Y <= inseamTop) {
      const f = Math.min(1, (p.x0 - X) / p.crotchExt)
      const centre = this.torso(p, Y, 0)
      const under = sectionNear(k => this.body.wrapSection(k), yc)
      const crotchPoint: Vec3 = [0, Math.min(centre.p[1], yc - GAP), under.center[1]]
      return {
        p: [0, 1, 2].map(k => centre.p[k] + (crotchPoint[k] - centre.p[k]) * f) as Vec3,
        ease: centre.ease,
      }
    }
    const t = Math.min(1, Math.max(0, (y - (yc - CROTCH_BLEND)) / (2 * CROTCH_BLEND)))
    const above = t > 0 ? this.torso(p, Y, Math.max(0, sewnDistance(p, X, Y))) : null
    const below = t < 1 ? this.legBelow(p, X, Y, y) : null
    if (!above) return below!
    if (!below) return above
    return {
      p: [0, 1, 2].map(k => below.p[k] + (above.p[k] - below.p[k]) * t) as Vec3,
      ease: below.ease + (above.ease - below.ease) * t,
    }
  }

  private legBelow(p: Profile, X: number, Y: number, y: number): Mapped {
    const sec = sectionNear(k => this.body.legSection(k), y)
    const inner = (q: Profile, row: number) => edgeX(q.inner, row, 'min') ?? q.x0
    const width = (q: Profile, row: number) => Math.max(1, (edgeX(q.side, row, 'max') ?? q.x0) - inner(q, row))
    const w = width(p, Y)
    const wp = p.partner ? width(p.partner, this.rowAt(p.partner, y)) : w
    const bodyLoop = perimeter(sec.hull)
    // Front: inner side → front → outer side; back: inner → back → outer.
    const arc = sweepArc(sec, p.back ? -Math.PI : Math.PI, p.back ? Math.PI : -Math.PI)
    const f = (X - inner(p, Y)) / w
    const [x, z] = arcPoint(arc, f * arc.cum[ARC_SAMPLES], standOff(w + wp, bodyLoop))
    return { p: [x, y, z], ease: (w + wp) / bodyLoop }
  }

  // Sleeves: the fold runs along the top of the arm, the seam underneath.
  sleeve(p: Profile, X: number, Y: number, frontHalf: boolean): Mapped {
    const { arm } = this.body
    const t = Math.min(arm.endT, arm.capTopT + (Y - p.anchorRow))
    const sec = sectionNear(k => this.body.armSection(k), t)
    const w = widthAt(p, Y)
    const bodyLoop = perimeter(sec.hull)
    const arc = sweepArc(sec, 0, frontHalf ? Math.PI : -Math.PI)
    const f = (X - p.x0) / w
    const [pu, pw] = arcPoint(arc, f * arc.cum[ARC_SAMPLES], standOff(2 * w, bodyLoop))
    return {
      p: [0, 1, 2].map(k => arm.joint[k] + arm.dir[k] * t + arm.u[k] * pu + arm.w[k] * pw) as Vec3,
      ease: (2 * w) / bodyLoop,
    }
  }

  // Keeps fabric outside the body: Newton steps along the field gradient.
  // Blended regions (crotch, armpit) have a gradient weaker than 1, so the
  // step is divided by its magnitude or it would stop short of the surface.
  pushOut(q: Vec3): Vec3 {
    const { sdf } = this.body
    let [x, y, z] = q
    for (let i = 0; i < 12; i++) {
      const d = sdf(x, y, z)
      if (d >= GAP) break
      const e = 0.05
      const gx = (sdf(x + e, y, z) - sdf(x - e, y, z)) / (2 * e)
      const gy = (sdf(x, y + e, z) - sdf(x, y - e, z)) / (2 * e)
      const gz = (sdf(x, y, z + e) - sdf(x, y, z - e)) / (2 * e)
      const g = Math.hypot(gx, gy, gz)
      if (g < 1e-6) break
      const step = Math.min((GAP + 0.02 - d) / g, 3)
      x += (gx / g) * step
      y += (gy / g) * step
      z += (gz / g) * step
    }
    return [x, y, z]
  }
}


function copiesFor(p: Profile): CopySpec[] {
  const both = p.piece.onFold || p.piece.cutQty >= 2
  if (p.region === 'sleeve') {
    const halves = p.piece.onFold ? [true, false] : [true]
    const sides = p.piece.cutQty >= 2 ? [false, true] : [false]
    return sides.flatMap(mirrorWorld => halves.map(frontHalf => ({ mirrorWorld, frontHalf })))
  }
  return both ? [{ mirrorWorld: false, frontHalf: true }, { mirrorWorld: true, frontHalf: true }] : [{ mirrorWorld: false, frontHalf: true }]
}

const polylineLength = (pts: Pt[]) => pts.reduce((s, p, i) => (i ? s + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0), 0)

// Sewn edges must have matching vertices so the drape can weld them (share
// particles) — a seam held by constraints alone opens into a visible crack.
// Edges joined by connections (transitively: a sleeve armhole is sewn to both
// bodice armholes) get ONE vertex count, sampled uniformly by arc length; an
// edge split by darts gets that count spread across its segments.
function conformSeamCounts(
  profiles: Profile[],
  shapes: Map<Profile, PieceShape>,
  connections: SeamConnection[],
): Map<Profile, (number | undefined)[]> {
  const byId = new Map(profiles.map(p => [p.piece.id, p]))
  const parent = new Map<string, string>()
  const find = (k: string): string => {
    let r = k
    while (parent.get(r) !== undefined && parent.get(r) !== r) r = parent.get(r)!
    return r
  }
  // One node per seam end (a piece's edge, or the part of it a range covers).
  const ends = new Map<string, SeamEnd>()
  const node = (end: SeamEnd) => {
    const p = byId.get(end.pieceId)
    if (!p || !seamParts(shapes.get(p)!.edges, end).length) return null
    const [lo, hi] = end.range ?? [0, 1]
    const k = `${end.pieceId}|${end.edgeId}|${lo}|${hi}`
    if (!parent.has(k)) {
      parent.set(k, k)
      ends.set(k, end)
    }
    return k
  }
  for (const c of connections) {
    const a = node(c.from)
    const b = node(c.to)
    if (a && b) parent.set(find(b), find(a))
  }
  const groups = new Map<string, string[]>()
  for (const k of parent.keys()) {
    const r = find(k)
    groups.set(r, [...(groups.get(r) ?? []), k])
  }
  const counts = new Map<Profile, (number | undefined)[]>(profiles.map(p => [p, shapes.get(p)!.edges.map(() => undefined)]))
  for (const members of groups.values()) {
    const info = members.map(k => {
      const end = ends.get(k)!
      const p = byId.get(end.pieceId)!
      const edges = shapes.get(p)!.edges
      const parts = seamParts(edges, end)
      const lens = parts.map(i => polylineLength(edges[i].pts))
      return { p, parts, lens, total: lens.reduce((a, b) => a + b, 0) }
    })
    const n = Math.max(...info.map(m => Math.max(m.parts.length, Math.round(m.total / MESH_SPACING), 1)))
    for (const m of info) {
      const out = counts.get(m.p)!
      if (m.parts.length === 1) {
        out[m.parts[0]] = n
        continue
      }
      // Largest-remainder split of n intervals across the segments (each ≥ 1).
      const raw = m.lens.map(l => (n * l) / Math.max(m.total, 1e-9))
      const k = raw.map(r => Math.max(1, Math.floor(r)))
      while (k.reduce((a, b) => a + b, 0) > n) k[k.indexOf(Math.max(...k))]--
      const order = raw.map((r, i) => ({ i, f: r - Math.floor(r) })).sort((a, b) => b.f - a.f)
      for (let j = 0; k.reduce((a, b) => a + b, 0) < n; j++) k[order[j % order.length].i]++
      m.parts.forEach((pi, j) => { out[pi] = k[j] })
    }
  }
  return counts
}

export function placeGarment(
  pieces: PatternPiece[],
  elements: CanvasElement[],
  body: BodyQuery,
  connections: SeamConnection[] = [],
): GarmentPlacement {
  const byId = new Map(elements.map(e => [e.id, e]))
  const skipped: GarmentPlacement['skipped'] = []
  const profiles: Profile[] = []
  for (const piece of pieces) {
    const outline = extractOutline(piece, byId)
    // Seams covering part of an edge split it, so each seam is whole edges.
    const shape = outline && splitAtRanges(outline, rangeCuts(piece.id, connections.flatMap(c => [c.from, c.to])))
    if (!shape) {
      skipped.push({ id: piece.id, name: piece.name, reason: 'outline is not a closed loop' })
      continue
    }
    const labels = new Set(shape.edges.map(e => e.label).filter(Boolean))
    if (shape.edges.some(e => e.isFold)) labels.add('fold')
    const cls = classifyPiece(piece.name, labels)
    if (cls.region === 'skip') {
      skipped.push({ id: piece.id, name: piece.name, reason: cls.reason ?? 'not placed' })
      continue
    }
    profiles.push(makeProfile(piece, shape, cls.region, cls.back, elements))
  }
  for (const p of profiles) {
    p.partner = profiles.find(q => q !== p && q.region === p.region && q.back !== p.back) ?? null
  }

  const wrapper = new Wrapper(body)
  const map = (p: Profile, X: number, Y: number, c: CopySpec): Mapped => {
    const m = p.region === 'sleeve' ? wrapper.sleeve(p, X, Y, c.frontHalf)
      : p.region === 'leg' ? wrapper.leg(p, X, Y)
        : p.region === 'torso-upper' ? wrapper.upper(p, X, Y)
          : wrapper.torso(p, Y, sewnDistance(p, X, Y))
    const q = wrapper.pushOut(m.p)
    return { p: c.mirrorWorld ? [-q[0], q[1], q[2]] : q, ease: m.ease }
  }

  // Darts are cut out of the mesh and sewn shut in the drape (their legs become edges).
  const shapes = new Map(profiles.map(p => [p, cutDarts(p.shape, p.darts)]))
  const seamCounts = conformSeamCounts(profiles, shapes, connections)

  const placed: PlacedPiece[] = profiles.map(p => {
    const specs = copiesFor(p)
    const meshShape = shapes.get(p)!
    const mesh = triangulateShape(meshShape, MESH_SPACING, seamCounts.get(p))
    const copies = specs.map(c => {
      const positions = new Float32Array(mesh.pts.length * 3)
      const ease = new Float32Array(mesh.pts.length)
      mesh.pts.forEach(([X, Y], i) => {
        const m = map(p, X, Y, c)
        positions.set(m.p, i * 3)
        ease[i] = m.ease
      })
      // Mirroring flips handedness; keep faces consistently wound.
      const flip = c.mirrorWorld !== !c.frontHalf
      const indices = new Uint32Array(mesh.tris.length * 3)
      mesh.tris.forEach(([a, b, t], i) => indices.set(flip ? [a, t, b] : [a, b, t], i * 3))
      return { positions, indices, ease }
    })
    return {
      id: p.piece.id,
      name: p.piece.name,
      region: p.region,
      back: p.back,
      onFold: p.piece.onFold,
      copies,
      copySpecs: specs,
      mesh,
      edges: meshShape.edges.map(({ id, label, isFold, base, span, flipped }) => ({ id, label, isFold, base, span, flipped })),
      mapPoint: (x, y, copy) => {
        const [X, Y] = p.toLocal([x, y])
        return map(p, X, Y, specs[copy]).p
      },
    }
  })
  return { placed, skipped }
}

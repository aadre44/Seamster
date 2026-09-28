import type { LoftRing, ResolvedBody, Vec3 } from './types'
import { armFrame, armRings, bodyLevels, legRings, torsoRings } from './bodyRegions'
import { buildBodySdf } from './bodySdf'
import type { Sdf } from './bodySdf'
import { dot, ringInterpolator, ringRadius, sub } from './rings'

// Everything the garment placement needs to know about a body. The garment
// code talks only to this interface, so a different body (e.g. a sculpted
// mesh) can be dropped in by implementing it.

export type Pt = [number, number]

// A convex cross-section outline (the tape line: fabric bridges hollows).
// Torso/leg sections are in world (x, z) at a height; arm sections are in the
// arm's local (u, w) frame around its axis.
export interface Section {
  center: Pt
  hull: Pt[] // counter-clockwise
}

export interface ArmAxis {
  joint: Vec3
  dir: Vec3
  u: Vec3 // outward (away from the body) for the right arm
  w: Vec3 // front
  capTopT: number // axial position of the top of the shoulder cap
  endT: number
}

export interface BodyQuery {
  height: number
  waistY: number
  crotchY: number
  sdf: Sdf
  // Hull of everything a garment wraps at height y: the torso and, below the
  // hips, both legs (a skirt hangs around both legs together).
  wrapSection(y: number): Section | null
  legSection(y: number): Section | null // right leg
  arm: ArmAxis // right arm
  armSection(t: number): Section | null
  neckSection(): { section: Section; y: number }
  ridgeZ: number
  topY(x: number): number // height of the body's upper surface at lateral x (shoulder line)
}

const OUTLINE_ANGLES = 72

function convexHull(points: Pt[]): Pt[] {
  const pts = [...points].sort((p, q) => p[0] - q[0] || p[1] - q[1])
  if (pts.length < 3) return pts
  const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const build = (list: Pt[]) => {
    const out: Pt[] = []
    for (const p of list) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop()
      out.push(p)
    }
    return out
  }
  const lower = build(pts)
  const upper = build([...pts].reverse())
  return [...lower.slice(0, -1), ...upper.slice(0, -1)]
}

export function perimeter(hull: Pt[]): number {
  let total = 0
  for (let i = 0; i < hull.length; i++) {
    const p = hull[i]
    const q = hull[(i + 1) % hull.length]
    total += Math.hypot(q[0] - p[0], q[1] - p[1])
  }
  return total
}

// Densely sampled chain of sections along a body part, keyed by a monotone
// coordinate (height for torso/legs, axial position for arms).
interface Chain {
  keys: number[]
  rings: LoftRing[]
  ascending: boolean
}

function sampleChain(landmarks: LoftRing[], key: (r: LoftRing) => number, step = 0.5): Chain {
  const interp = ringInterpolator(landmarks)
  const n = Math.max(2, Math.ceil(interp.length / step) + 1)
  const rings = Array.from({ length: n }, (_, i) => interp.at((interp.length * i) / (n - 1)))
  const keys = rings.map(key)
  return { keys, rings, ascending: keys[n - 1] > keys[0] }
}

// Section outline points at `k` in the ring's own (u, w) plane, interpolated
// between the two nearest samples; null outside the chain.
function chainOutline(c: Chain, k: number): { pts: Pt[]; center: Vec3 } | null {
  const { keys } = c
  const n = keys.length
  const lo = c.ascending ? keys[0] : keys[n - 1]
  const hi = c.ascending ? keys[n - 1] : keys[0]
  if (k < lo || k > hi) return null
  let i = 0
  for (; i < n - 2; i++) {
    const a = keys[i]
    const b = keys[i + 1]
    if ((k >= Math.min(a, b)) && (k <= Math.max(a, b))) break
  }
  const a = keys[i]
  const b = keys[i + 1]
  const f = b === a ? 0 : (k - a) / (b - a)
  const r1 = c.rings[i]
  const r2 = c.rings[i + 1]
  const pts: Pt[] = []
  for (let j = 0; j < OUTLINE_ANGLES; j++) {
    const th = -Math.PI + (2 * Math.PI * j) / OUTLINE_ANGLES
    const R = ringRadius(r1, th) * (1 - f) + ringRadius(r2, th) * f
    pts.push([R * Math.cos(th), R * Math.sin(th)])
  }
  const center: Vec3 = [
    r1.center[0] + (r2.center[0] - r1.center[0]) * f,
    r1.center[1] + (r2.center[1] - r1.center[1]) * f,
    r1.center[2] + (r2.center[2] - r1.center[2]) * f,
  ]
  return { pts, center }
}

export function proceduralBodyQuery(body: ResolvedBody): BodyQuery {
  const L = bodyLevels(body)
  const { sdf } = buildBodySdf(body)
  const torsoLandmarks = torsoRings(body)
  const torso = sampleChain(torsoLandmarks, r => r.center[1])
  const legR = sampleChain(legRings(body, 1), r => r.center[1])
  const legL = sampleChain(legRings(body, -1), r => r.center[1])
  const frame = armFrame(body, 1)
  const armLandmarks = armRings(body, 1)
  const arm = sampleChain(armLandmarks, r => dot(sub(r.center, frame.joint), frame.dir))
  const armTop = armLandmarks.find(r => r.name === 'armTop')!
  const shoulderRing = torsoLandmarks.find(r => r.name === 'shoulder')!

  // Torso/leg sections are horizontal with u = x and w = z, so local outline
  // points are world (x, z) offsets from the section centre.
  const worldXZ = (o: { pts: Pt[]; center: Vec3 } | null): Pt[] =>
    o ? o.pts.map(([x, z]) => [x + o.center[0], z + o.center[2]] as Pt) : []

  const cache = new Map<number, Section | null>()
  const wrapSection = (y: number): Section | null => {
    const key = Math.round(y * 4)
    if (cache.has(key)) return cache.get(key)!
    const t = chainOutline(torso, y)
    const pts = [...worldXZ(t), ...worldXZ(chainOutline(legR, y)), ...worldXZ(chainOutline(legL, y))]
    let section: Section | null = null
    if (pts.length) {
      const zc = t ? t.center[2] : pts.reduce((s, p) => s + p[1], 0) / pts.length
      section = { center: [0, zc], hull: convexHull(pts) }
    }
    cache.set(key, section)
    return section
  }

  const legSection = (y: number): Section | null => {
    const o = chainOutline(legR, y)
    if (!o) return null
    return { center: [o.center[0], o.center[2]], hull: convexHull(worldXZ(o)) }
  }

  const armSection = (t: number): Section | null => {
    const o = chainOutline(arm, t)
    return o ? { center: [0, 0], hull: convexHull(o.pts) } : null
  }

  // The neck just above where the shoulders slope away from it.
  const neckBase = torsoLandmarks.find(r => r.name === 'neckBase')!
  const neckY = neckBase.center[1] + 1.5
  const neckOutline = chainOutline(torso, neckY)!
  const neckSection = { section: { center: [0, neckOutline.center[2]] as Pt, hull: convexHull(worldXZ(neckOutline)) }, y: neckY }

  const ridgeZ = shoulderRing.center[2]
  const topCache = new Map<number, number>()
  const topY = (x: number): number => {
    const key = Math.round(x * 4)
    const hit = topCache.get(key)
    if (hit !== undefined) return hit
    let hiY = body.height + 1
    let loY = hiY
    let found = false
    for (let y = hiY; y > L.armpit; y -= 0.5) {
      if (sdf(x, y, ridgeZ) < 0) {
        loY = y
        hiY = y + 0.5
        found = true
        break
      }
    }
    let result = L.shoulder
    if (found) {
      for (let i = 0; i < 20; i++) {
        const mid = (loY + hiY) / 2
        if (sdf(x, mid, ridgeZ) < 0) loY = mid
        else hiY = mid
      }
      result = loY
    }
    topCache.set(key, result)
    return result
  }

  return {
    height: body.height,
    waistY: L.waist,
    crotchY: L.crotch,
    sdf,
    wrapSection,
    legSection,
    arm: {
      joint: frame.joint,
      dir: frame.dir,
      u: frame.u,
      w: [0, 0, 1],
      capTopT: -1 - armTop.a,
      endT: frame.length,
    },
    armSection,
    neckSection: () => neckSection,
    ridgeZ,
    topY,
  }
}


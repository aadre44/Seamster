import type { LoftRing, ResolvedBody, Vec3 } from './types'
import { armFrame, armRings, footEllipsoid, headEllipsoids, legRings, torsoRings } from './bodyRegions'
import type { Ellipsoid } from './bodyRegions'
import { dot, ringInterpolator, ringRadius, sub } from './rings'

// The avatar surface is the zero set of a signed distance field (negative
// inside). Body parts are joined with a smooth minimum, which is what makes
// shoulders flow into arms and hips into legs like a real mannequin.

export type Sdf = (x: number, y: number, z: number) => number

export interface Bounds { min: Vec3; max: Vec3 }

// Blend radii (cm). Arm/torso blending stays below ARM_CLEARANCE so measured
// torso sections are never fattened by a nearby arm.
const BLEND = { head: 2.5, leg: 4, foot: 3, arm: 2.5 }
const TABLE_ANGLES = 128
const TUBE_STEP = 0.5
// Beyond this distance from a part's bounding box the part can't influence the
// blend, so its bounding-box distance is used instead of evaluating it.
const CULL_MARGIN = 6

// Polynomial smooth minimum (Quilez): equals min(a, b) once |a − b| ≥ k.
function smin(a: number, b: number, k: number): number {
  const h = Math.max(k - Math.abs(a - b), 0) / k
  return Math.min(a, b) - (h * h * k) / 4
}

function boxDistance(x: number, y: number, z: number, b: Bounds): number {
  const dx = Math.max(b.min[0] - x, 0, x - b.max[0])
  const dy = Math.max(b.min[1] - y, 0, y - b.max[1])
  const dz = Math.max(b.min[2] - z, 0, z - b.max[2])
  return Math.hypot(dx, dy, dz)
}

interface Tube {
  origin: Vec3
  axis: Vec3
  u: Vec3
  w: Vec3
  t: Float64Array // axial coordinate of each sampled section (increasing)
  cx: Float64Array
  cy: Float64Array
  cz: Float64Array
  radius: Float32Array // [section * TABLE_ANGLES + angle]
  bounds: Bounds
}

// A part swept through its landmark sections: sampled densely along the
// monotone-cubic interpolation, with each section's polar outline tabulated.
// All sections of a part share one frame (u, w) and one axis.
function makeTube(landmarks: LoftRing[], axis: Vec3): Tube {
  const interp = ringInterpolator(landmarks)
  const count = Math.max(2, Math.ceil(interp.length / TUBE_STEP) + 1)
  const origin = landmarks[0].center
  const t = new Float64Array(count)
  const cx = new Float64Array(count)
  const cy = new Float64Array(count)
  const cz = new Float64Array(count)
  const radius = new Float32Array(count * TABLE_ANGLES)
  const min: Vec3 = [Infinity, Infinity, Infinity]
  const max: Vec3 = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < count; i++) {
    const ring = interp.at((interp.length * i) / (count - 1))
    t[i] = dot(sub(ring.center, origin), axis)
    cx[i] = ring.center[0]
    cy[i] = ring.center[1]
    cz[i] = ring.center[2]
    let rMax = 0
    for (let j = 0; j < TABLE_ANGLES; j++) {
      const r = ringRadius(ring, -Math.PI + (2 * Math.PI * j) / TABLE_ANGLES)
      radius[i * TABLE_ANGLES + j] = r
      rMax = Math.max(rMax, r)
    }
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], ring.center[k] - rMax)
      max[k] = Math.max(max[k], ring.center[k] + rMax)
    }
  }
  // Keep the axial coordinate strictly increasing for the section search.
  for (let i = 1; i < count; i++) if (t[i] <= t[i - 1]) t[i] = t[i - 1] + 1e-6
  return { origin, axis, u: landmarks[0].u, w: landmarks[0].w, t, cx, cy, cz, radius, bounds: { min, max } }
}

function tubeDistance(tube: Tube, x: number, y: number, z: number): number {
  const box = boxDistance(x, y, z, tube.bounds)
  if (box > CULL_MARGIN) return box
  const { t, axis, origin, u, w } = tube
  const n = t.length
  const s = (x - origin[0]) * axis[0] + (y - origin[1]) * axis[1] + (z - origin[2]) * axis[2]
  const sc = Math.min(Math.max(s, t[0]), t[n - 1])
  let i = 0
  let hi = n - 1
  while (hi - i > 1) {
    const mid = (i + hi) >> 1
    if (t[mid] <= sc) i = mid
    else hi = mid
  }
  const f = (sc - t[i]) / (t[i + 1] - t[i])
  const qx = x - (tube.cx[i] + (tube.cx[i + 1] - tube.cx[i]) * f)
  const qy = y - (tube.cy[i] + (tube.cy[i + 1] - tube.cy[i]) * f)
  const qz = z - (tube.cz[i] + (tube.cz[i + 1] - tube.cz[i]) * f)
  const pu = qx * u[0] + qy * u[1] + qz * u[2]
  const pw = qx * w[0] + qy * w[1] + qz * w[2]
  const r = Math.hypot(pu, pw)
  const fa = ((Math.atan2(pw, pu) + Math.PI) / (2 * Math.PI)) * TABLE_ANGLES
  const j0 = Math.floor(fa) % TABLE_ANGLES
  const j1 = (j0 + 1) % TABLE_ANGLES
  const g = fa - Math.floor(fa)
  const R0 = tube.radius[i * TABLE_ANGLES + j0] * (1 - g) + tube.radius[i * TABLE_ANGLES + j1] * g
  const R1 = tube.radius[(i + 1) * TABLE_ANGLES + j0] * (1 - g) + tube.radius[(i + 1) * TABLE_ANGLES + j1] * g
  const radial = r - (R0 + (R1 - R0) * f)
  const axial = Math.max(t[0] - s, s - t[n - 1])
  if (axial <= 0) return radial
  return radial > 0 ? Math.hypot(radial, axial) : axial
}

// Ellipsoid distance bound (Quilez): exact on the surface, good near it.
function ellipsoidDistance(e: Ellipsoid, x: number, y: number, z: number): number {
  const px = x - e.center[0]
  const py = y - e.center[1]
  const pz = z - e.center[2]
  const [rx, ry, rz] = e.radii
  const k0 = Math.hypot(px / rx, py / ry, pz / rz)
  const k1 = Math.hypot(px / (rx * rx), py / (ry * ry), pz / (rz * rz))
  if (k1 === 0) return -Math.min(rx, ry, rz)
  return (k0 * (k0 - 1)) / k1
}

export interface BodySdf {
  sdf: Sdf
  bounds: Bounds
}

export function buildBodySdf(body: ResolvedBody): BodySdf {
  const DOWN: Vec3 = [0, -1, 0]
  const torso = makeTube(torsoRings(body), DOWN)
  const legs = ([1, -1] as const).map(side => makeTube(legRings(body, side), DOWN))
  const arms = ([1, -1] as const).map(side => makeTube(armRings(body, side), armFrame(body, side).dir))
  const { cranium, jaw } = headEllipsoids(body)
  const feet = ([1, -1] as const).map(side => footEllipsoid(body, side))

  // smin isn't associative, so each left/right pair is blended together first
  // (smin is commutative) — blending one side before the other would make the
  // inner thighs asymmetric.
  const sdf: Sdf = (x, y, z) => {
    let d = tubeDistance(torso, x, y, z)
    const head = smin(ellipsoidDistance(cranium, x, y, z), ellipsoidDistance(jaw, x, y, z), 3)
    d = smin(d, head, BLEND.head)
    d = smin(d, smin(tubeDistance(legs[0], x, y, z), tubeDistance(legs[1], x, y, z), BLEND.leg), BLEND.leg)
    d = smin(d, smin(ellipsoidDistance(feet[0], x, y, z), ellipsoidDistance(feet[1], x, y, z), BLEND.foot), BLEND.foot)
    d = smin(d, smin(tubeDistance(arms[0], x, y, z), tubeDistance(arms[1], x, y, z), BLEND.arm), BLEND.arm)
    return Math.max(d, -y) // flat soles on the floor
  }

  const min: Vec3 = [Infinity, 0, Infinity]
  const max: Vec3 = [-Infinity, body.height, -Infinity]
  for (const b of [torso.bounds, ...legs.map(l => l.bounds), ...arms.map(a => a.bounds)]) {
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], b.min[k])
      max[k] = Math.max(max[k], b.max[k])
    }
  }
  for (const e of [cranium, jaw, ...feet]) {
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], e.center[k] - e.radii[k])
      max[k] = Math.max(max[k], e.center[k] + e.radii[k])
    }
  }
  min[1] = 0
  return { sdf, bounds: { min, max } }
}

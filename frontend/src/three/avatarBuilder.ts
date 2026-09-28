import type { AvatarData, LoftRing, MeshData, ResolvedBody, Vec3 } from './types'
import { armEnd, armRings, armStartCap, bodyLevels, headRings, legEnd, legRings, torsoRings } from './bodyRegions'

const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const scale = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const cross = (p: Vec3, q: Vec3): Vec3 => [
  p[1] * q[2] - p[2] * q[1],
  p[2] * q[0] - p[0] * q[2],
  p[0] * q[1] - p[1] * q[0],
]
const lerp3 = (p: Vec3, q: Vec3, t: number): Vec3 => add(p, scale(sub(q, p), t))
const normalize = (p: Vec3): Vec3 => scale(p, 1 / Math.hypot(p[0], p[1], p[2]))

export function ringPoint(r: LoftRing, theta: number): Vec3 {
  return add(r.center, add(scale(r.u, r.a * Math.cos(theta)), scale(r.w, r.b * Math.sin(theta))))
}

export function ringPoints(r: LoftRing, segments: number): Vec3[] {
  return Array.from({ length: segments }, (_, j) => ringPoint(r, (2 * Math.PI * j) / segments))
}

// Fritsch–Carlson tangents: the Hermite interpolant through (xs, ys) never
// overshoots the data, so a section can't bulge past its landmarks and a
// monotone coordinate (height down the torso) stays monotone — rings can't fold.
function monotoneTangents(xs: number[], ys: number[]): number[] {
  const n = xs.length
  const d = Array.from({ length: n - 1 }, (_, i) => (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]))
  const m = ys.map((_, i) => {
    if (i === 0) return d[0]
    if (i === n - 1) return d[n - 2]
    return d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2
  })
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0
      m[i + 1] = 0
      continue
    }
    const alpha = m[i] / d[i]
    const beta = m[i + 1] / d[i]
    const s = alpha * alpha + beta * beta
    if (s > 9) {
      const tau = 3 / Math.sqrt(s)
      m[i] = tau * alpha * d[i]
      m[i + 1] = tau * beta * d[i]
    }
  }
  return m
}

function hermite(y0: number, y1: number, m0: number, m1: number, h: number, t: number): number {
  const t2 = t * t
  const t3 = t2 * t
  return (2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m0 + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * m1
}

// Insert `subdiv - 1` rings between each landmark pair, interpolating section
// size and centre with monotone cubics over distance along the body.
export function smoothRings(rings: LoftRing[], subdiv: number): LoftRing[] {
  if (subdiv <= 1 || rings.length < 2) return rings
  const s = [0]
  for (let i = 1; i < rings.length; i++) {
    const [dx, dy, dz] = sub(rings[i].center, rings[i - 1].center)
    s.push(s[i - 1] + Math.max(Math.hypot(dx, dy, dz), 1e-6))
  }
  const channels = [
    rings.map(r => r.a),
    rings.map(r => r.b),
    rings.map(r => r.center[0]),
    rings.map(r => r.center[1]),
    rings.map(r => r.center[2]),
  ]
  const tangents = channels.map(ys => monotoneTangents(s, ys))
  const out: LoftRing[] = []
  for (let i = 0; i < rings.length - 1; i++) {
    const r1 = rings[i]
    const r2 = rings[i + 1]
    const h = s[i + 1] - s[i]
    out.push(r1)
    for (let k = 1; k < subdiv; k++) {
      const t = k / subdiv
      const [a, b, x, y, z] = channels.map((ys, c) => hermite(ys[i], ys[i + 1], tangents[c][i], tangents[c][i + 1], h, t))
      out.push({
        name: `${r1.name}~${k}`,
        center: [x, y, z],
        a,
        b,
        u: normalize(lerp3(r1.u, r2.u, t)),
        w: normalize(lerp3(r1.w, r2.w, t)),
      })
    }
  }
  out.push(rings[rings.length - 1])
  return out
}

// Tube through the rings, optionally closed with a fan to a cap point at either
// end. Winding is chosen per ring pair so faces always point outward whatever
// direction the limb runs.
export function loft(name: string, rings: LoftRing[], segments: number, startCap?: Vec3, endCap?: Vec3): MeshData {
  const positions: number[] = []
  const indices: number[] = []
  for (const r of rings) for (const p of ringPoints(r, segments)) positions.push(...p)

  const outward = (i: number) => {
    const next = rings[Math.min(i + 1, rings.length - 1)]
    const prev = rings[Math.max(i - 1, 0)]
    const r = rings[i]
    return dot(cross(r.u, r.w), sub(next.center, prev.center)) >= 0
  }
  const tri = (a: number, b: number, c: number, keep: boolean) =>
    keep ? indices.push(a, b, c) : indices.push(a, c, b)

  for (let i = 0; i < rings.length - 1; i++) {
    const keep = outward(i)
    const u0 = i * segments
    const l0 = (i + 1) * segments
    for (let j = 0; j < segments; j++) {
      const j1 = (j + 1) % segments
      tri(u0 + j, u0 + j1, l0 + j, keep)
      tri(u0 + j1, l0 + j1, l0 + j, keep)
    }
  }
  if (startCap) {
    const c = positions.length / 3
    positions.push(...startCap)
    const keep = outward(0)
    for (let j = 0; j < segments; j++) tri(c, (j + 1) % segments, j, keep)
  }
  if (endCap) {
    const c = positions.length / 3
    positions.push(...endCap)
    const last = rings.length - 1
    const keep = outward(last)
    const base = last * segments
    for (let j = 0; j < segments; j++) tri(base + j, base + ((j + 1) % segments), c, keep)
  }
  return { name, positions: new Float32Array(positions), indices: new Uint32Array(indices) }
}

export function buildAvatar(body: ResolvedBody, segments = 32, subdiv = 4): AvatarData {
  const levels = bodyLevels(body)
  const torso = torsoRings(body)
  const legR = legRings(body, 1)
  const legL = legRings(body, -1)
  const armR = armRings(body, 1)
  const armL = armRings(body, -1)
  const head = headRings(body)

  const crotch = torso[torso.length - 1]

  const parts: MeshData[] = [
    loft('torso', smoothRings(torso, subdiv), segments,
      add(torso[0].center, [0, 0.5, 0]), [0, levels.crotch - 2.5, crotch.center[2]]),
    loft('legRight', smoothRings(legR, subdiv), segments, add(legR[0].center, [0, 1, 0]), legEnd(body, 1)),
    loft('legLeft', smoothRings(legL, subdiv), segments, add(legL[0].center, [0, 1, 0]), legEnd(body, -1)),
    loft('armRight', smoothRings(armR, subdiv), segments, armStartCap(body, 1), armEnd(body, 1)),
    loft('armLeft', smoothRings(armL, subdiv), segments, armStartCap(body, -1), armEnd(body, -1)),
    loft('head', head.rings, segments, head.top, head.bottom),
  ]

  return {
    parts,
    landmarks: { torso, legRight: legR, legLeft: legL, armRight: armR, armLeft: armL, head: head.rings },
    height: body.height,
  }
}

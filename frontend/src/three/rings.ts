import type { LoftRing, Vec3 } from './types'

export const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
export const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
export const scale = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
export const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
export const lerp3 = (p: Vec3, q: Vec3, t: number): Vec3 => add(p, scale(sub(q, p), t))
export const normalize = (p: Vec3): Vec3 => scale(p, 1 / Math.hypot(p[0], p[1], p[2]))

const TAU = 2 * Math.PI

export function angleDiff(a: number, b: number): number {
  let d = (a - b) % TAU
  if (d > Math.PI) d -= TAU
  if (d < -Math.PI) d += TAU
  return d
}

// Polar radius of the cross-section outline at angle θ (from +u towards +w).
export function ringRadius(r: LoftRing, theta: number): number {
  const c = Math.cos(theta)
  const s = Math.sin(theta)
  const depth = s >= 0 ? r.b : (r.back ?? r.b)
  const n = r.n ?? 2
  const base = n === 2
    ? 1 / Math.sqrt((c / r.a) ** 2 + (s / depth) ** 2)
    : 1 / Math.pow(Math.abs(c / r.a) ** n + Math.abs(s / depth) ** n, 1 / n)
  let bump = 0
  if (r.lobes) {
    for (const l of r.lobes) {
      if (l.amp === 0) continue
      const k = angleDiff(theta, l.angle) / l.width
      if (k > -1 && k < 1) bump += l.amp * lobeKernel(k)
    }
  }
  return base + bump
}

// Rounded dome (1 − k²)^1.5 on |k| < 1: a broad, round crown (breasts and
// buttocks are domes, not cones — a Gaussian of the same width comes to a
// point) that meets the section with zero slope, so there is no crease.
function lobeKernel(k: number): number {
  const q = 1 - k * k
  return q * Math.sqrt(q)
}

export function ringPoint(r: LoftRing, theta: number): Vec3 {
  const R = ringRadius(r, theta)
  return add(r.center, add(scale(r.u, R * Math.cos(theta)), scale(r.w, R * Math.sin(theta))))
}

export function ringPoints(r: LoftRing, segments: number): Vec3[] {
  return Array.from({ length: segments }, (_, j) => ringPoint(r, -Math.PI + (TAU * j) / segments))
}

function planarPoints(r: LoftRing, segments: number): [number, number][] {
  return Array.from({ length: segments }, (_, j) => {
    const theta = -Math.PI + (TAU * j) / segments
    const R = ringRadius(r, theta)
    return [R * Math.cos(theta), R * Math.sin(theta)]
  })
}

// What a tape measure reads around the section: the perimeter of its convex
// hull (the tape bridges hollows, e.g. between the breasts).
export function tapeLength(r: LoftRing, segments = 360): number {
  const pts = planarPoints(r, segments).sort((p, q) => p[0] - q[0] || p[1] - q[1])
  const cross = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const lower: [number, number][] = []
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop()
    lower.push(p)
  }
  const upper: [number, number][] = []
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop()
    upper.push(p)
  }
  const hull = [...lower.slice(0, -1), ...upper.slice(0, -1)]
  let total = 0
  for (let i = 0; i < hull.length; i++) {
    const p = hull[i]
    const q = hull[(i + 1) % hull.length]
    total += Math.hypot(q[0] - p[0], q[1] - p[1])
  }
  return total
}

// Largest lateral (u) extent of the section from its centre.
export function ringHalfWidth(r: LoftRing, segments = 360): number {
  return Math.max(...planarPoints(r, segments).map(p => Math.abs(p[0])))
}

export function scaleRing(r: LoftRing, k: number): LoftRing {
  return {
    ...r,
    a: r.a * k,
    b: r.b * k,
    back: (r.back ?? r.b) * k,
    lobes: r.lobes?.map(l => ({ ...l, amp: l.amp * k })),
  }
}

// ── Interpolation between landmark sections ──────────────────────────────────

// Fritsch–Carlson tangents: the Hermite interpolant through (xs, ys) never
// overshoots the data, so a section can't bulge past its landmarks and a
// monotone coordinate (height down the torso) stays monotone — sections can't fold.
function monotoneTangents(xs: number[], ys: number[]): number[] {
  const n = xs.length
  if (n < 2) return ys.map(() => 0)
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

// Continuous section as a function of distance s along the centre line.
// Every scalar (size, depths, exponent, centre, lobe amplitudes) is
// interpolated with its own monotone cubic; lobe angles/widths come from the
// first section (all sections of one body part share the same lobe slots).
export function ringInterpolator(rings: LoftRing[]): { length: number; at: (s: number) => LoftRing } {
  const s = [0]
  for (let i = 1; i < rings.length; i++) {
    const [dx, dy, dz] = sub(rings[i].center, rings[i - 1].center)
    s.push(s[i - 1] + Math.max(Math.hypot(dx, dy, dz), 1e-6))
  }
  const slots = rings[0].lobes ?? []
  const channels: number[][] = [
    rings.map(r => r.a),
    rings.map(r => r.b),
    rings.map(r => r.back ?? r.b),
    rings.map(r => r.n ?? 2),
    rings.map(r => r.center[0]),
    rings.map(r => r.center[1]),
    rings.map(r => r.center[2]),
    ...slots.map((_, k) => rings.map(r => r.lobes?.[k]?.amp ?? 0)),
  ]
  const tangents = channels.map(ys => monotoneTangents(s, ys))
  const length = s[s.length - 1]

  const at = (sv: number): LoftRing => {
    const x = Math.min(Math.max(sv, 0), length)
    let i = 0
    let hi = s.length - 1
    while (hi - i > 1) {
      const mid = (i + hi) >> 1
      if (s[mid] <= x) i = mid
      else hi = mid
    }
    const h = s[i + 1] - s[i]
    const t = h > 0 ? (x - s[i]) / h : 0
    const v = channels.map((ys, c) => hermite(ys[i], ys[i + 1], tangents[c][i], tangents[c][i + 1], h, t))
    const r1 = rings[i]
    const r2 = rings[i + 1]
    return {
      name: t === 0 ? r1.name : `${r1.name}~`,
      a: v[0],
      b: v[1],
      back: v[2],
      n: v[3],
      center: [v[4], v[5], v[6]],
      lobes: slots.map((l, k) => ({ angle: l.angle, width: l.width, amp: Math.max(0, v[7 + k]) })),
      u: normalize(lerp3(r1.u, r2.u, t)),
      w: normalize(lerp3(r1.w, r2.w, t)),
    }
  }
  return { length, at }
}

// Landmarks plus `subdiv - 1` interpolated sections in every span.
export function smoothRings(rings: LoftRing[], subdiv: number): LoftRing[] {
  if (subdiv <= 1 || rings.length < 2) return rings
  const interp = ringInterpolator(rings)
  const s = [0]
  for (let i = 1; i < rings.length; i++) {
    const [dx, dy, dz] = sub(rings[i].center, rings[i - 1].center)
    s.push(s[i - 1] + Math.max(Math.hypot(dx, dy, dz), 1e-6))
  }
  const out: LoftRing[] = []
  for (let i = 0; i < rings.length - 1; i++) {
    out.push(rings[i])
    for (let k = 1; k < subdiv; k++) out.push(interp.at(s[i] + ((s[i + 1] - s[i]) * k) / subdiv))
  }
  out.push(rings[rings.length - 1])
  return out
}

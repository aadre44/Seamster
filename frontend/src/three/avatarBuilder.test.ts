import { describe, expect, it } from 'vitest'
import { FINE_CELL, buildAvatar } from './avatarBuilder'
import {
  ARM_CLEARANCE, BODY_FIELDS, DEFAULT_BODY_PROFILE, armClearanceRings, armFrame, armRadius, bodyLevels,
  ellipseAxes, ellipsePerimeter, legRings, resolveBody, torsoRings,
} from './bodyRegions'
import { buildBodySdf } from './bodySdf'
import { ringHalfWidth, ringRadius, smoothRings, tapeLength } from './rings'
import type { BodyField, BodyShapePreset, LoftRing, MeshData, ResolvedBody } from './types'

function body(overrides: Partial<Record<BodyField, number>> = {}, shape: BodyShapePreset = 'hourglass'): ResolvedBody {
  return resolveBody({ overrides, shape }, {})
}

function landmark(rings: LoftRing[], name: string): LoftRing {
  const r = rings.find(x => x.name === name)
  if (!r) throw new Error(`no ring ${name}`)
  return r
}

function hullPerimeter(points: [number, number][]): number {
  const pts = [...points].sort((p, q) => p[0] - q[0] || p[1] - q[1])
  const cross = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const half = (list: [number, number][]) => {
    const out: [number, number][] = []
    for (const p of list) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop()
      out.push(p)
    }
    return out
  }
  const hull = [...half(pts).slice(0, -1), ...half([...pts].reverse()).slice(0, -1)]
  let total = 0
  for (let i = 0; i < hull.length; i++) {
    const p = hull[i]
    const q = hull[(i + 1) % hull.length]
    total += Math.hypot(q[0] - p[0], q[1] - p[1])
  }
  return total
}

// Tape measure taken on the final blended surface: march outward from the
// section centre to the zero set at many angles, then take the hull perimeter.
function surfaceTape(sdf: (x: number, y: number, z: number) => number, ring: LoftRing): number {
  const [cx, y, cz] = ring.center
  const pts: [number, number][] = []
  for (let j = 0; j < 180; j++) {
    const th = (2 * Math.PI * j) / 180
    const dx = Math.cos(th)
    const dz = Math.sin(th)
    let lo = 0
    let hi = 0.25
    while (sdf(cx + dx * hi, y, cz + dz * hi) < 0 && hi < 100) {
      lo = hi
      hi += 0.25
    }
    for (let k = 0; k < 30; k++) {
      const mid = (lo + hi) / 2
      if (sdf(cx + dx * mid, y, cz + dz * mid) < 0) lo = mid
      else hi = mid
    }
    pts.push([dx * lo, dz * lo])
  }
  return hullPerimeter(pts)
}

function eachVertex(mesh: MeshData, fn: (x: number, y: number, z: number) => void) {
  for (let i = 0; i < mesh.positions.length; i += 3) fn(mesh.positions[i], mesh.positions[i + 1], mesh.positions[i + 2])
}

const allMin = Object.fromEntries(BODY_FIELDS.map(f => [f.key, f.minCm])) as Record<BodyField, number>
const allMax = Object.fromEntries(BODY_FIELDS.map(f => [f.key, f.maxCm])) as Record<BodyField, number>

describe('ellipse sizing', () => {
  it('inverts the perimeter approximation exactly', () => {
    for (const ratio of [0.5, 0.72, 1, 1.5]) {
      const { a, b } = ellipseAxes(96, ratio)
      expect(b / a).toBeCloseTo(ratio, 10)
      expect(ellipsePerimeter(a, b)).toBeCloseTo(96, 8)
    }
  })
})

describe('resolveBody', () => {
  it('prefers overrides, then editor measurements, then defaults, clamped to bounds', () => {
    const r = resolveBody({ overrides: { waist: 70 }, shape: 'pear' }, { waist: 80, hip: 104, bust: 999 })
    expect(r.waist).toBe(70)
    expect(r.hip).toBe(104)
    expect(r.bust).toBe(160)
    expect(r.height).toBe(168)
    expect(r.shape).toBe('pear')
  })

  it('does not treat a garment sleeve length as an arm length', () => {
    expect(resolveBody(DEFAULT_BODY_PROFILE, { sleeveLength: 20 }).armLength).toBe(58)
  })
})

describe('anatomical sections', () => {
  it('each measured section tapes to its measurement', () => {
    const b = body({ bust: 101, underbust: 80, waist: 79, hip: 108, thigh: 60, calf: 38 })
    const torso = torsoRings(b)
    for (const [name, circ] of [['bust', 101], ['underbust', 80], ['waist', 79], ['hip', 108]] as const) {
      expect(Math.abs(tapeLength(landmark(torso, name)) - circ) / circ).toBeLessThan(0.005)
    }
    const leg = legRings(b, 1)
    expect(Math.abs(tapeLength(landmark(leg, 'thigh')) - 60) / 60).toBeLessThan(0.005)
    expect(Math.abs(tapeLength(landmark(leg, 'calf')) - 38) / 38).toBeLessThan(0.005)
  })

  it('turns the bust–underbust difference into breast projection', () => {
    const frontDepth = (b: ResolvedBody) => {
      const bust = landmark(torsoRings(b), 'bust')
      return Math.max(...[0.9, 1.0, 1.1].map(th => ringRadius(bust, th) * Math.sin(th)))
    }
    const flat = body({ bust: 80, underbust: 78 })
    const small = body({ bust: 88, underbust: 76 })
    const full = body({ bust: 104, underbust: 76 })
    const breastLobes = (r: LoftRing) => r.lobes!.filter(l => Math.abs(l.angle - Math.PI / 2) > 0.3 && l.angle > 0)
    expect(breastLobes(landmark(torsoRings(flat), 'bust')).every(l => l.amp === 0)).toBe(true)
    expect(breastLobes(landmark(torsoRings(full), 'bust')).every(l => l.amp > 0)).toBe(true)
    expect(frontDepth(full)).toBeGreaterThan(frontDepth(small) + 2)
    // The tape bridges the cleavage: the surface between the breasts is set back from the apexes.
    const bust = landmark(torsoRings(full), 'bust')
    expect(ringRadius(bust, Math.PI / 2)).toBeLessThan(ringRadius(bust, Math.PI / 2 - 0.56))
  })

  it('shape presets change the silhouette, not the measurements', () => {
    const hg = torsoRings(body({}, 'hourglass'))
    const ap = torsoRings(body({}, 'apple'))
    const pe = torsoRings(body({}, 'pear'))
    expect(landmark(ap, 'waist').b).toBeGreaterThan(landmark(hg, 'waist').b)
    expect(landmark(ap, 'waist').center[2]).toBeGreaterThan(landmark(hg, 'waist').center[2])
    expect(ringHalfWidth(landmark(pe, 'hip'))).toBeGreaterThan(ringHalfWidth(landmark(hg, 'hip')))
    for (const rings of [hg, ap, pe]) expect(tapeLength(landmark(rings, 'hip'))).toBeCloseTo(98, 0)
  })

  it('changing the bust leaves the waist section untouched', () => {
    expect(landmark(torsoRings(body({ bust: 120 })), 'waist')).toEqual(landmark(torsoRings(body({ bust: 88 })), 'waist'))
  })

  it('keeps torso sections strictly ordered with positive size at slider extremes', () => {
    for (const overrides of [allMin, allMax, { ...allMin, height: 210 }, { ...allMax, height: 140 }]) {
      for (const shape of ['hourglass', 'rectangle', 'pear', 'apple'] as const) {
        const rings = torsoRings(body(overrides, shape))
        for (let i = 1; i < rings.length; i++) expect(rings[i].center[1]).toBeLessThan(rings[i - 1].center[1])
        for (const r of rings) {
          expect(r.a).toBeGreaterThan(0)
          expect(r.b).toBeGreaterThan(0)
          expect(r.back ?? r.b).toBeGreaterThan(0)
        }
      }
    }
  })

  it('smoothing never folds the torso or bulges past its landmarks', () => {
    for (const shape of ['hourglass', 'apple'] as const) {
      const landmarks = torsoRings(body({ waist: 120 }, shape))
      const smooth = smoothRings(landmarks, 6)
      for (let i = 1; i < smooth.length; i++) expect(smooth[i].center[1]).toBeLessThan(smooth[i - 1].center[1])
      const lo = Math.min(...landmarks.map(r => r.a))
      const hi = Math.max(...landmarks.map(r => r.a))
      for (const r of smooth) {
        expect(r.a).toBeGreaterThanOrEqual(lo - 1e-9)
        expect(r.a).toBeLessThanOrEqual(hi + 1e-9)
      }
    }
  })

  it('arms clear the torso even with wide hips and narrow shoulders', () => {
    const cases: Partial<Record<BodyField, number>>[] = [
      {},
      { hip: 170, waist: 150, shoulder: 30, upperArm: 50 },
      { bust: 160, underbust: 140, waist: 150, shoulder: 30 },
    ]
    for (const overrides of cases) {
      const b = body(overrides, 'apple')
      const f = armFrame(b, 1)
      for (const r of armClearanceRings(b)) {
        const dy = f.joint[1] - r.center[1]
        if (dy <= 0 || dy > f.length * Math.cos(f.angle)) continue
        const armX = f.joint[0] + dy * Math.tan(f.angle)
        expect(armX - armRadius(b)).toBeGreaterThan(ringHalfWidth(r) + ARM_CLEARANCE * 0.9)
      }
    }
  })
})

describe('blended surface', () => {
  const b = body({ bust: 96, underbust: 78, waist: 76, hip: 102 })
  const { sdf } = buildBodySdf(b)
  const started = performance.now()
  const avatar = buildAvatar(b, FINE_CELL)
  const buildMs = performance.now() - started
  const mesh = avatar.parts[0]

  it('keeps the measured circumferences on the final surface', () => {
    const torso = torsoRings(b)
    for (const [name, circ] of [['bust', 96], ['waist', 76], ['hip', 102]] as const) {
      expect(Math.abs(surfaceTape(sdf, landmark(torso, name)) - circ) / circ).toBeLessThan(0.02)
    }
  })

  // Fingertips are thinner than two grid cells, where surface nets pinches a
  // few edges (shared by 4 triangles). That is harmless; holes are not.
  it('is one closed surface with no holes', () => {
    const edges = new Map<string, number>()
    for (let t = 0; t < mesh.indices.length; t += 3) {
      for (let e = 0; e < 3; e++) {
        const a = mesh.indices[t + e]
        const c = mesh.indices[t + ((e + 1) % 3)]
        const key = a < c ? `${a},${c}` : `${c},${a}`
        edges.set(key, (edges.get(key) ?? 0) + 1)
      }
    }
    const counts = [...edges.values()]
    expect(counts.filter(n => n % 2 === 1)).toHaveLength(0)
    expect(counts.filter(n => n !== 2).length / counts.length).toBeLessThan(0.001)
  })

  it('faces point outward', () => {
    const p = mesh.positions
    let outward = 0
    const tris = mesh.indices.length / 3
    for (let t = 0; t < mesh.indices.length; t += 3) {
      const [i0, i1, i2] = [mesh.indices[t] * 3, mesh.indices[t + 1] * 3, mesh.indices[t + 2] * 3]
      const e1 = [p[i1] - p[i0], p[i1 + 1] - p[i0 + 1], p[i1 + 2] - p[i0 + 2]]
      const e2 = [p[i2] - p[i0], p[i2 + 1] - p[i0 + 1], p[i2 + 2] - p[i0 + 2]]
      const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
      const c = [(p[i0] + p[i1] + p[i2]) / 3, (p[i0 + 1] + p[i1 + 1] + p[i2 + 1]) / 3, (p[i0 + 2] + p[i1 + 2] + p[i2 + 2]) / 3]
      const e = 0.05
      const g = [
        sdf(c[0] + e, c[1], c[2]) - sdf(c[0] - e, c[1], c[2]),
        sdf(c[0], c[1] + e, c[2]) - sdf(c[0], c[1] - e, c[2]),
        sdf(c[0], c[1], c[2] + e) - sdf(c[0], c[1], c[2] - e),
      ]
      if (n[0] * g[0] + n[1] * g[1] + n[2] * g[2] > 0) outward++
    }
    expect(outward / tris).toBeGreaterThan(0.99)
  })

  it('is mirror-symmetric about x = 0', () => {
    const cell = 0.05
    const grid = new Map<string, [number, number, number][]>()
    const key = (x: number, y: number, z: number) => `${Math.round(x / cell)},${Math.round(y / cell)},${Math.round(z / cell)}`
    eachVertex(mesh, (x, y, z) => {
      const k = key(x, y, z)
      if (!grid.has(k)) grid.set(k, [])
      grid.get(k)!.push([x, y, z])
    })
    let missing = 0
    eachVertex(mesh, (x, y, z) => {
      const [kx, ky, kz] = [Math.round(-x / cell), Math.round(y / cell), Math.round(z / cell)]
      let found = false
      for (let dx = -1; dx <= 1 && !found; dx++)
        for (let dy = -1; dy <= 1 && !found; dy++)
          for (let dz = -1; dz <= 1 && !found; dz++)
            for (const q of grid.get(`${kx + dx},${ky + dy},${kz + dz}`) ?? [])
              if (Math.hypot(q[0] + x, q[1] - y, q[2] - z) < 1e-3) found = true
      if (!found) missing++
    })
    expect(missing).toBe(0)
  })

  it('stands on the floor and reaches its height', () => {
    let minY = Infinity
    let maxY = -Infinity
    eachVertex(mesh, (_x, y) => {
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
    })
    expect(minY).toBeGreaterThan(-0.01)
    expect(minY).toBeLessThan(FINE_CELL)
    expect(maxY).toBeGreaterThan(b.height - FINE_CELL)
    expect(maxY).toBeLessThan(b.height + 0.01)
  })

  it('has a smooth crotch and neck (surface continues through the joins)', () => {
    const L = bodyLevels(b)
    expect(sdf(0, L.neckTop - 1, 0)).toBeLessThan(0)
    expect(sdf(0, (L.neckTop + b.height * 0.87) / 2, 0)).toBeLessThan(0)
    expect(sdf(0, L.crotch + 1, 0)).toBeLessThan(0)
  })

  it('builds fast enough for interactive use', () => {
    console.log(`fine avatar: ${mesh.positions.length / 3} vertices, ${mesh.indices.length / 3} triangles, ${buildMs.toFixed(0)} ms`)
    expect(buildMs).toBeLessThan(4000)
  })
})

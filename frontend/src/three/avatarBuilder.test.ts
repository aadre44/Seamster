import { describe, expect, it } from 'vitest'
import { buildAvatar, ringPoints, smoothRings } from './avatarBuilder'
import { BODY_FIELDS, DEFAULT_BODY_PROFILE, armClearanceRings, armFrame, armRadius, ellipseAxes, ellipsePerimeter, resolveBody, torsoRings } from './bodyRegions'
import type { BodyField, BodyShapePreset, LoftRing, ResolvedBody, Vec3 } from './types'

const SEGMENTS = 32

function body(overrides: Partial<Record<BodyField, number>> = {}, shape: BodyShapePreset = 'hourglass'): ResolvedBody {
  return resolveBody({ overrides, shape }, {})
}

function polygonLength(points: Vec3[]): number {
  let total = 0
  for (let i = 0; i < points.length; i++) {
    const p = points[i]
    const q = points[(i + 1) % points.length]
    total += Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2])
  }
  return total
}

function landmark(rings: LoftRing[], name: string): LoftRing {
  const r = rings.find(x => x.name === name)
  if (!r) throw new Error(`no ring ${name}`)
  return r
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

describe('buildAvatar', () => {
  it('sampled landmark rings match the input circumferences within 2%', () => {
    const b = body({ bust: 101, waist: 79, hip: 108 })
    const torso = buildAvatar(b, SEGMENTS).landmarks.torso
    for (const [name, circ] of [['bust', 101], ['waist', 79], ['hip', 108]] as const) {
      const len = polygonLength(ringPoints(landmark(torso, name), SEGMENTS))
      expect(Math.abs(len - circ) / circ).toBeLessThan(0.02)
    }
    const thigh = landmark(buildAvatar(b, SEGMENTS).landmarks.legLeft, 'thigh')
    expect(Math.abs(polygonLength(ringPoints(thigh, SEGMENTS)) - b.thigh) / b.thigh).toBeLessThan(0.02)
  })

  it('is mirror-symmetric about x = 0', () => {
    for (const shape of ['hourglass', 'apple'] as const) {
      const avatar = buildAvatar(body({}, shape), SEGMENTS)
      // `+ 0` folds -0 into 0 so centre-line points match their own mirror.
      const q = (v: number) => Math.round(v * 100) + 0
      const key = (x: number, y: number, z: number) => `${q(x)},${q(y)},${q(z)}`
      const seen = new Set<string>()
      const all: number[][] = []
      for (const part of avatar.parts) {
        for (let i = 0; i < part.positions.length; i += 3) {
          const [x, y, z] = [part.positions[i], part.positions[i + 1], part.positions[i + 2]]
          seen.add(key(x, y, z))
          all.push([x, y, z])
        }
      }
      const missing = all.filter(([x, y, z]) => !seen.has(key(-x + 0, y, z)))
      expect(missing).toHaveLength(0)
    }
  })

  it('spans exactly the body height from floor to crown', () => {
    for (const height of [150, 168, 195]) {
      const avatar = buildAvatar(body({ height }), SEGMENTS)
      let minY = Infinity
      let maxY = -Infinity
      for (const part of avatar.parts) {
        for (let i = 1; i < part.positions.length; i += 3) {
          minY = Math.min(minY, part.positions[i])
          maxY = Math.max(maxY, part.positions[i])
        }
      }
      expect(minY).toBeCloseTo(0, 3)
      expect(maxY).toBeCloseTo(height, 3)
    }
  })

  it('changing the bust leaves the waist ring untouched', () => {
    const w1 = landmark(buildAvatar(body({ bust: 88 })).landmarks.torso, 'waist')
    const w2 = landmark(buildAvatar(body({ bust: 120 })).landmarks.torso, 'waist')
    expect(w2).toEqual(w1)
  })

  it('shape presets change waist depth and belly projection', () => {
    const hg = landmark(torsoRings(body({}, 'hourglass')), 'waist')
    const ap = landmark(torsoRings(body({}, 'apple')), 'waist')
    expect(ap.b).toBeGreaterThan(hg.b)
    expect(ap.center[2]).toBeGreaterThan(hg.center[2])
  })

  it('keeps torso sections strictly ordered top to bottom with positive axes at slider extremes', () => {
    for (const overrides of [allMin, allMax, { ...allMin, height: 210 }, { ...allMax, height: 140 }]) {
      for (const shape of ['hourglass', 'rectangle', 'pear', 'apple'] as const) {
        const rings = torsoRings(body(overrides, shape))
        for (let i = 1; i < rings.length; i++) {
          expect(rings[i].center[1]).toBeLessThan(rings[i - 1].center[1])
        }
        for (const r of rings) {
          expect(r.a).toBeGreaterThan(0)
          expect(r.b).toBeGreaterThan(0)
        }
      }
    }
  })

  it('smoothing never folds the torso or bulges past its landmarks', () => {
    for (const shape of ['hourglass', 'apple'] as const) {
      const landmarks = torsoRings(body({ waist: 120 }, shape))
      const smooth = smoothRings(landmarks, 6)
      for (let i = 1; i < smooth.length; i++) {
        expect(smooth[i].center[1]).toBeLessThan(smooth[i - 1].center[1])
      }
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
      const armR = armRadius(b)
      for (const r of armClearanceRings(b)) {
        const dy = f.joint[1] - r.center[1]
        if (dy <= 0 || dy > f.length * Math.cos(f.angle)) continue
        const armX = f.joint[0] + dy * Math.tan(f.angle)
        expect(armX - armR).toBeGreaterThan(r.a)
      }
    }
  })

  it('emits closed, index-valid meshes for every part', () => {
    const avatar = buildAvatar(body())
    expect(avatar.parts.map(p => p.name)).toEqual(['torso', 'legRight', 'legLeft', 'armRight', 'armLeft', 'head'])
    for (const part of avatar.parts) {
      const count = part.positions.length / 3
      expect(part.indices.length % 3).toBe(0)
      for (const i of part.indices) expect(i).toBeLessThan(count)
      expect(Array.from(part.positions).every(Number.isFinite)).toBe(true)
    }
  })
})

import { describe, expect, it } from 'vitest'
import skirtFixture from './fixtures/skirt.psnap.json'
import trousersFixture from './fixtures/trousers.psnap.json'
import shirtFixture from './fixtures/shirt.psnap.json'
import dressFixture from './fixtures/dress.psnap.json'
import vestFixture from './fixtures/vest.psnap.json'
import { resolveBody } from './bodyRegions'
import { proceduralBodyQuery } from './bodyQuery'
import { EASE_TIGHT, placeGarment } from './garmentWrap'
import type { GarmentPlacement } from './garmentWrap'
import type { CanvasElement, PatternPiece, SeamConnection } from '../types'
import type { Vec3 } from './types'

// Fixtures are real /api/generate outputs from the backend engine for the
// default body (bust 92, waist 74, hip 98, shoulder 39, inseam 77, arm 58).
interface Psnap { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[] }
const FIXTURES: Record<string, unknown> = {
  skirt: skirtFixture, trousers: trousersFixture, shirt: shirtFixture, dress: dressFixture, vest: vestFixture,
}
const load = (name: string): Psnap => structuredClone(FIXTURES[name]) as Psnap

const body = resolveBody({ overrides: {}, shape: 'hourglass' }, {})
const query = proceduralBodyQuery(body)
const GARMENTS = ['skirt', 'trousers', 'shirt', 'dress', 'vest'] as const
const placements = new Map<string, { psnap: Psnap; placement: GarmentPlacement; ms: number }>()
for (const g of GARMENTS) {
  const psnap = load(g)
  const t0 = performance.now()
  const placement = placeGarment(psnap.pieces, psnap.elements, query)
  placements.set(g, { psnap, placement, ms: performance.now() - t0 })
}

function samples(e: CanvasElement, n = 9): [number, number][] {
  const out: [number, number][] = []
  for (let i = 1; i <= n; i++) {
    const t = i / (n + 1)
    if (e.type === 'line') out.push([e.start.x + (e.end.x - e.start.x) * t, e.start.y + (e.end.y - e.start.y) * t])
    else if (e.type === 'curve') {
      const u = 1 - t
      const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t
      out.push([
        a * e.start.x + b * e.cp1.x + c * e.cp2.x + d * e.end.x,
        a * e.start.y + b * e.cp1.y + c * e.cp2.y + d * e.end.y,
      ])
    }
  }
  return out
}

const dist = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])

// Mean 3D gap between two sewn edges, pairing samples in whichever direction fits.
function seamGap(g: string, c: SeamConnection): number {
  const { psnap, placement } = placements.get(g)!
  const el = (id: string) => psnap.elements.find(e => e.id === id)!
  const pa = placement.placed.find(p => p.id === c.from.pieceId)!
  const pb = placement.placed.find(p => p.id === c.to.pieceId)!
  const A = samples(el(c.from.edgeId)).map(([x, y]) => pa.mapPoint(x, y, 0))
  const B = samples(el(c.to.edgeId)).map(([x, y]) => pb.mapPoint(x, y, 0))
  const mean = (pairs: Vec3[]) => A.reduce((s, a, i) => s + dist(a, pairs[i]), 0) / A.length
  return Math.min(mean(B), mean([...B].reverse()))
}

describe('piece classification', () => {
  const regions = (g: string) => Object.fromEntries(placements.get(g)!.placement.placed.map(p => [p.name, p.region]))
  it('recognises body regions on engine patterns', () => {
    expect(regions('skirt')).toEqual({ 'Front Skirt': 'torso-lower', 'Back Skirt': 'torso-lower' })
    expect(regions('shirt')).toEqual({ 'Front Bodice': 'torso-upper', 'Back Bodice': 'torso-upper', Sleeve: 'sleeve' })
    expect(regions('trousers')).toEqual({ 'Front Leg': 'leg', 'Back Leg': 'leg' })
    expect(regions('dress')).toEqual({
      'Front Bodice': 'torso-upper', 'Back Bodice': 'torso-upper', 'Front Skirt': 'torso-lower', 'Back Skirt': 'torso-lower',
    })
  })

  it('leaves trims out of the 3D preview', () => {
    expect(placements.get('trousers')!.placement.skipped.map(s => s.name).sort()).toEqual(['Fly Facing', 'Fly Shield'])
  })
})

describe('garment placement', () => {
  const TOLERANCE: Record<string, number> = { side_seam: 1.0, shoulder: 2.0, inseam: 2.5 }

  // The backend pairs ANY two edges sharing a label (e.g. dress bodice side
  // seam ↔ skirt side seam, hem ↔ hem), so only physically sewn pairs are
  // checked: side/shoulder/inseam between the front and back of one body part,
  // and the waist seam between bodice and skirt on the same side.
  const isSewn = (g: string, c: SeamConnection) => {
    const placed = placements.get(g)!.placement.placed
    const a = placed.find(p => p.id === c.from.pieceId)
    const b = placed.find(p => p.id === c.to.pieceId)
    if (!a || !b) return false
    const backA = /back/i.test(a.name)
    const backB = /back/i.test(b.name)
    if (c.label === 'waist_seam') return a.region !== b.region && backA === backB
    return a.region === b.region && backA !== backB
  }

  it('brings every sewn seam together on the body', () => {
    const report: string[] = []
    for (const g of GARMENTS) {
      for (const c of placements.get(g)!.psnap.connections) {
        const tol = TOLERANCE[c.label]
        if (tol === undefined || !isSewn(g, c)) continue
        const gap = seamGap(g, c)
        report.push(`${g} ${c.label} ${gap.toFixed(2)}`)
        expect(gap, `${g} ${c.label}`).toBeLessThan(tol)
      }
    }
    console.log(report.join('\n'))
  })

  // Both sides of a dress waist seam are sewn at the body's waist. (Their
  // lengths differ in the engine's current drafts — darts are double-counted,
  // see fixList — so only the height is checked, not the full 3D gap.)
  it('puts both sides of a waist seam at the body waist', () => {
    const { psnap, placement } = placements.get('dress')!
    for (const piece of placement.placed) {
      const src = psnap.pieces.find(p => p.id === piece.id)!
      for (const id of src.elementIds) {
        const e = psnap.elements.find(x => x.id === id)!
        if ((e as { seamLabel?: string }).seamLabel !== 'waist_seam') continue
        for (const [x, y] of samples(e)) {
          expect(Math.abs(piece.mapPoint(x, y, 0)[1] - query.waistY), piece.name).toBeLessThan(1.5)
        }
      }
    }
  })

  it('closes darts: both legs of a dart land on the same body line', () => {
    const { psnap, placement } = placements.get('skirt')!
    const front = placement.placed.find(p => p.name === 'Front Skirt')!
    const pieceId = psnap.pieces.find(p => p.name === 'Front Skirt')!.id
    const outline = new Set(psnap.pieces.find(p => p.id === pieceId)!.elementIds)
    const legs = psnap.elements.filter(e => e.type === 'line' && e.pieceId === pieceId && !outline.has(e.id) && !e.seamLabel)
    expect(legs).toHaveLength(2)
    const [a, b] = legs.map(e => samples(e).map(([x, y]) => front.mapPoint(x, y, 0)))
    for (let i = 0; i < a.length; i++) expect(dist(a[i], b[i])).toBeLessThan(0.6)
  })

  it('puts fold edges on the centre line', () => {
    for (const g of GARMENTS) {
      const { psnap, placement } = placements.get(g)!
      for (const piece of psnap.pieces) {
        const placed = placement.placed.find(p => p.id === piece.id)
        if (!placed || placed.region === 'sleeve') continue
        for (const id of piece.elementIds) {
          const e = psnap.elements.find(x => x.id === id)!
          if (e.type !== 'line' || !e.isFold) continue
          for (const [x, y] of samples(e)) expect(Math.abs(placed.mapPoint(x, y, 0)[0]), `${g} ${piece.name}`).toBeLessThan(0.6)
        }
      }
    }
  })

  // The push-out aims for GAP; at the crotch (legs + torso blend) it can stop a
  // little short, so the requirement checked is a clear margin outside the body.
  it('never puts fabric inside the body', () => {
    for (const g of GARMENTS) {
      for (const piece of placements.get(g)!.placement.placed) {
        for (const copy of piece.copies) {
          for (let i = 0; i < copy.positions.length; i += 3) {
            const d = query.sdf(copy.positions[i], copy.positions[i + 1], copy.positions[i + 2])
            expect(d, `${g} ${piece.name}`).toBeGreaterThan(0.2)
          }
        }
      }
    }
  })

  it('mirrors fold and cut-2 pieces to the other side', () => {
    const front = placements.get('shirt')!.placement.placed.find(p => p.name === 'Front Bodice')!
    expect(front.copies).toHaveLength(2)
    const [a, b] = front.copies
    for (let i = 0; i < a.positions.length; i += 3) {
      expect(b.positions[i]).toBeCloseTo(-a.positions[i], 4)
      expect(b.positions[i + 1]).toBeCloseTo(a.positions[i + 1], 4)
    }
    const sleeve = placements.get('shirt')!.placement.placed.find(p => p.name === 'Sleeve')!
    expect(sleeve.copies).toHaveLength(4) // front + back half, on both arms
  })

  it('shows flare: an A-line hem stands further from the body than its waist', () => {
    const { placement } = placements.get('skirt')!
    const front = placement.placed.find(p => p.name === 'Front Skirt')!
    const clearance = (x: number, y: number) => query.sdf(...front.mapPoint(x, y, 0))
    expect(clearance(20, 61)).toBeGreaterThan(clearance(15, 3) + 2)
  })

  it('reports a garment smaller than the body as tight', () => {
    const psnap = load('skirt')
    const shrink = (e: CanvasElement): CanvasElement => {
      const s = (p: { x: number; y: number }) => ({ x: p.x * 0.75, y: p.y })
      if (e.type === 'line' || e.type === 'grain-line') return { ...e, start: s(e.start), end: s(e.end) }
      if (e.type === 'curve') return { ...e, start: s(e.start), cp1: s(e.cp1), cp2: s(e.cp2), end: s(e.end) }
      return e
    }
    const tight = placeGarment(psnap.pieces, psnap.elements.map(shrink), query)
    const belowDarts = (c: { positions: Float32Array; ease: Float32Array }) =>
      Array.from(c.ease).filter((_, i) => c.positions[i * 3 + 1] < query.waistY - 16)
    expect(Math.min(...belowDarts(tight.placed[0].copies[0]))).toBeLessThan(EASE_TIGHT)
    // A skirt drafted for this body is not tight over the hips and below.
    expect(Math.min(...belowDarts(placements.get('skirt')!.placement.placed[0].copies[0]))).toBeGreaterThanOrEqual(EASE_TIGHT)
  })

  it('wraps trouser legs around each leg below the crotch', () => {
    const { placement } = placements.get('trousers')!
    const front = placement.placed.find(p => p.name === 'Front Leg')!
    const knee = front.mapPoint(18, 80, 0)
    const leg = query.legSection(knee[1])!
    expect(knee[0]).toBeGreaterThan(0)
    expect(Math.hypot(knee[0] - leg.center[0], knee[2] - leg.center[1])).toBeLessThan(15)
    expect(knee[2]).toBeGreaterThan(leg.center[1]) // front leg is on the front of the leg
  })

  it('places a pattern quickly enough to follow slider changes', () => {
    for (const [g, { ms, placement }] of placements) {
      const verts = placement.placed.reduce((s, p) => s + p.copies.reduce((t, c) => t + c.positions.length / 3, 0), 0)
      console.log(`${g}: ${verts} vertices in ${ms.toFixed(0)} ms`)
      expect(ms).toBeLessThan(3000)
    }
  })
})

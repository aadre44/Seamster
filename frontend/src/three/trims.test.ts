import { describe, expect, it } from 'vitest'
import trousersFixture from './fixtures/trousers-trims.psnap.json'
import shirtFixture from './fixtures/shirt-trims.psnap.json'
import { resolveBody } from './bodyRegions'
import { proceduralBodyQuery } from './bodyQuery'
import { buildBodySdf } from './bodySdf'
import { SdfGrid } from './sdfGrid'
import { placeGarment } from './garmentWrap'
import { Cloth, DRAPE } from './clothSim'
import type { CanvasElement, PatternPiece, Placement, SeamConnection } from '../types'

// Real /api/generate outputs with trims: trousers (button fly: fly facing +
// shield, side pocket bags, back patch pockets, belt loops) and a button-front
// shirt (collar, cuffs, chest pocket).
interface Psnap { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[]; placements: Placement[] }

const body = resolveBody({ overrides: {}, shape: 'hourglass' }, {})
const query = proceduralBodyQuery(body)
const { sdf, bounds } = buildBodySdf(body)
const grid = new SdfGrid(sdf, bounds)

function drape(fixture: unknown) {
  const psnap = fixture as Psnap
  const t0 = performance.now()
  const placement = placeGarment(psnap.pieces, psnap.elements, query, psnap.connections, psnap.placements)
  const cloth = new Cloth(placement.placed, psnap.connections, grid)
  const energy: number[] = []
  for (let s = 0; s < DRAPE.steps; s++) {
    cloth.step(DRAPE.dt, DRAPE.substeps)
    energy.push(cloth.kineticEnergy())
  }
  return { ...placement, cloth, energy, ms: performance.now() - t0 }
}

const trousers = drape(trousersFixture)
const shirt = drape(shirtFixture)
const copies = (r: typeof shirt, name: string) => r.placed.find(p => p.name === name)?.copies.length ?? 0
const rangesOf = (r: typeof shirt, name: string) => r.cloth.ranges.filter(g => r.placed[g.piece].name === name)
const median = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)]

describe('trims on the body', () => {
  it('places every attached trim; only unattached ones are skipped', () => {
    expect(trousers.skipped.map(s => s.name)).toEqual(['Belt Loop'])
    expect(shirt.skipped).toEqual([])
    // one fly facing on the left, one shield on the right; bags and back pockets on both sides
    expect([copies(trousers, 'Fly Facing'), copies(trousers, 'Fly Shield')]).toEqual([1, 1])
    expect([copies(trousers, 'Front Pocket Bag'), copies(trousers, 'Back Pocket')]).toEqual([2, 2])
    // a full collar is one piece round the neck; a cuff on each sleeve; one chest pocket
    expect([copies(shirt, 'Collar'), copies(shirt, 'Cuff'), copies(shirt, 'Chest Patch Pocket')]).toEqual([1, 2, 1])
  })

  for (const [name, r] of [['trousers', trousers], ['shirt', shirt]] as const) {
    describe(name, () => {
      it('settles', () => {
        const early = r.energy.slice(0, 20).reduce((a, b) => a + b) / 20
        const late = r.energy.slice(-20).reduce((a, b) => a + b) / 20
        console.log(`${name} with trims: ${r.cloth.n} particles, ${r.ms.toFixed(0)} ms, KE ${early.toFixed(0)} -> ${late.toFixed(1)}`)
        expect(Number.isFinite(late)).toBe(true)
        expect(late).toBeLessThan(early / 4)
      })

      it('sews every trim seam shut (welded, no stitch fallback)', () => {
        expect(r.cloth.weldedSeams).toBeGreaterThan(0)
        expect(r.cloth.stitchGaps()).toHaveLength(0)
      })

      it('keeps every trim on its side of the garment (pockets over, facings and bags under)', () => {
        expect(r.cloth.layerParticles).toBeGreaterThan(100)
        expect(r.cloth.layerViolations()).toBeLessThanOrEqual(Math.floor(r.cloth.layerParticles * 0.01))
      })

      it('keeps stitched pocket edges on the garment', () => {
        expect(Math.max(...r.cloth.pinGaps(1))).toBeLessThan(0.5)
      })

      it('drapes quickly enough', () => {
        expect(r.ms).toBeLessThan(20000)
      })
    })
  }

  it('keeps inside pieces under the garment and pockets on top of it', () => {
    for (const g of rangesOf(trousers, 'Fly Facing')) expect(median(trousers.cloth.pinSides(g))).toBeLessThan(0)
    for (const g of rangesOf(trousers, 'Front Pocket Bag')) expect(median(trousers.cloth.pinSides(g))).toBeLessThan(0)
    for (const g of rangesOf(trousers, 'Back Pocket')) expect(median(trousers.cloth.pinSides(g))).toBeGreaterThan(0)
    for (const g of rangesOf(shirt, 'Chest Patch Pocket')) expect(median(shirt.cloth.pinSides(g))).toBeGreaterThan(0)
  })
})

describe('a button front', () => {
  const front = shirt.placed.find(p => p.buttonFront)

  it('laps the fronts: the buttonhole side over the button side, CF on CF', () => {
    expect(front?.name).toBe('Front Bodice')
    const { top, under, line, strip } = front!.buttonFront!
    expect([top, under].sort()).toEqual([0, 1])
    expect(line.length).toBeGreaterThan(5)
    expect(strip.length).toBeGreaterThan(5)
    expect(front!.pins![top]!.every(p => p.mutual && p.hostCopy === under)).toBe(true)
  })

  it('buttons the centre-front lines together on the body', () => {
    const gaps = shirt.cloth.pinGaps(0.5, true)
    expect(gaps.length).toBe(front!.buttonFront!.line.length)
    expect(Math.max(...gaps)).toBeLessThan(0.6)
  })
})

describe('one-sided and unlinked placements', () => {
  const psnap = structuredClone(trousersFixture) as unknown as Psnap
  const pocket = psnap.placements[0]

  it('puts a one-sided pocket on that side only', () => {
    for (const side of ['left', 'right'] as const) {
      const { placed } = placeGarment(psnap.pieces, psnap.elements, query, psnap.connections, [{ ...pocket, side }])
      const p = placed.find(x => x.name === 'Back Pocket')!
      expect(p.copies).toHaveLength(1)
      const xs = p.copies[0].positions.filter((_, i) => i % 3 === 0)
      expect(Math.sign(xs.reduce((a, b) => a + b, 0))).toBe(side === 'left' ? 1 : -1) // the wearer's left is +x
    }
  })

  it('places an unlinked pair independently', () => {
    const right = { ...pocket, side: 'right' as const }
    const left = { ...pocket, id: 'other', side: 'left' as const, transform: { ...pocket.transform, dy: pocket.transform.dy + 8 } }
    const { placed } = placeGarment(psnap.pieces, psnap.elements, query, psnap.connections, [right, left])
    const p = placed.find(x => x.name === 'Back Pocket')!
    expect(p.copies).toHaveLength(2)
    const meanY = (c: { positions: Float32Array }) => c.positions.filter((_, i) => i % 3 === 1).reduce((a, b) => a + b, 0) / (c.positions.length / 3)
    expect(meanY(p.copies[0]) - meanY(p.copies[1])).toBeGreaterThan(5) // the left one moved 8 cm down
  })
})

describe('a pocket straddling a seam', () => {
  const psnap = structuredClone(trousersFixture) as unknown as Psnap
  const byId = new Map(psnap.elements.map(e => [e.id, e]))
  const front = psnap.pieces.find(p => p.name === 'Front Leg')!
  const pocketPiece = psnap.pieces.find(p => p.name === 'Back Pocket')!
  // Centre the pocket on the longest front side-seam element (mid-thigh), right leg only.
  const seam = front.elementIds.map(i => byId.get(i)!).filter(e => e.type === 'line' && e.seamLabel === 'side_seam')
    .reduce((a, e) => (e.type === 'line' && a.type === 'line' && Math.hypot(e.end.x - e.start.x, e.end.y - e.start.y) > Math.hypot(a.end.x - a.start.x, a.end.y - a.start.y) ? e : a))
  if (seam.type !== 'line') throw new Error('expected a straight side seam')
  const mid = { x: (seam.start.x + seam.end.x) / 2, y: (seam.start.y + seam.end.y) / 2 }
  const pts = pocketPiece.elementIds.map(i => byId.get(i)!).flatMap(e => ('start' in e ? [e.start, e.end] : []))
  const c = { x: (Math.min(...pts.map(p => p.x)) + Math.max(...pts.map(p => p.x))) / 2, y: (Math.min(...pts.map(p => p.y)) + Math.max(...pts.map(p => p.y))) / 2 }
  const across: Placement = {
    id: 'cargo', pieceId: pocketPiece.id, hostId: front.id, side: 'right',
    transform: { dx: mid.x - c.x, dy: mid.y - c.y, rotation: 0 }, stitched: psnap.placements[0].stitched, source: 'user',
  }
  const { placed } = placeGarment(psnap.pieces, psnap.elements, query, psnap.connections, [across])
  const cloth = new Cloth(placed, psnap.connections, grid)
  for (let s = 0; s < DRAPE.steps; s++) cloth.step(DRAPE.dt, DRAPE.substeps)
  const pocket = placed.find(p => p.name === 'Back Pocket')!

  it('is pinned to both panels it covers, on that side only', () => {
    const hosts = new Set(pocket.pins![0].map(p => placed[p.host].name))
    expect([...hosts].sort()).toEqual(['Back Leg', 'Front Leg'])
    for (const pin of pocket.pins![0]) {
      const host = placed[pin.host]
      const xs = host.copies[pin.hostCopy].positions.filter((_, i) => i % 3 === 0)
      expect(xs.reduce((a, b) => a + b, 0)).toBeLessThan(0) // the wearer's right is −x
    }
  })

  it('wraps round the side of the leg and stays on the garment', () => {
    const pos = cloth.positionsOf(cloth.ranges.find(r => placed[r.piece] === pocket)!)
    const xs = pos.filter((_, i) => i % 3 === 0), zs = pos.filter((_, i) => i % 3 === 2)
    // from the front of the thigh round to the back of it
    expect(Math.max(...zs) - Math.min(...zs)).toBeGreaterThan(5)
    expect(Math.max(...xs)).toBeLessThan(0)
    expect(Math.max(...cloth.pinGaps(1))).toBeLessThan(0.5)
  })
})

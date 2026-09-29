import { describe, expect, it } from 'vitest'
import skirtFixture from './fixtures/skirt.psnap.json'
import trousersFixture from './fixtures/trousers.psnap.json'
import shirtFixture from './fixtures/shirt.psnap.json'
import dressFixture from './fixtures/dress.psnap.json'
import { resolveBody } from './bodyRegions'
import { proceduralBodyQuery } from './bodyQuery'
import { buildBodySdf } from './bodySdf'
import { SdfGrid } from './sdfGrid'
import { placeGarment } from './garmentWrap'
import { Cloth, DRAPE } from './clothSim'
import { EASE_TIGHT } from './garmentWrap'
import type { CanvasElement, PatternPiece, SeamConnection, SeamEnd } from '../types'
import { seamParts } from './pieceGeometry'

interface Psnap { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[] }

const body = resolveBody({ overrides: {}, shape: 'hourglass' }, {})
const query = proceduralBodyQuery(body)
const { sdf, bounds } = buildBodySdf(body)
const grid = new SdfGrid(sdf, bounds)

function drape(fixture: unknown) {
  const psnap = fixture as Psnap
  const { placed } = placeGarment(psnap.pieces, psnap.elements, query, psnap.connections)
  const t0 = performance.now()
  const cloth = new Cloth(placed, psnap.connections, grid)
  const start = new Float32Array(cloth.x)
  const energy: number[] = []
  for (let s = 0; s < DRAPE.steps; s++) {
    cloth.step(DRAPE.dt, DRAPE.substeps)
    energy.push(cloth.kineticEnergy())
  }
  return { cloth, placed, start, energy, ms: performance.now() - t0 }
}

const FIXTURES: Record<string, unknown> = {
  skirt: skirtFixture, trousers: trousersFixture, shirt: shirtFixture, dress: dressFixture,
}

const results = {
  skirt: drape(skirtFixture),
  trousers: drape(trousersFixture),
  shirt: drape(shirtFixture),
  dress: drape(dressFixture),
}

// Per-particle ease (fit map value) from the placement, indexed like the cloth.
function easeOf(r: ReturnType<typeof drape>): Float32Array {
  const out = new Float32Array(r.cloth.n)
  for (const g of r.cloth.ranges) out.set(r.placed[g.piece].copies[g.copy].ease, g.start)
  return out
}

describe('drape simulation', () => {
  for (const [name, r] of Object.entries(results)) {
    describe(name, () => {
      it('settles: motion dies down instead of oscillating or blowing up', () => {
        const early = r.energy.slice(0, 20).reduce((a, b) => a + b) / 20
        const late = r.energy.slice(-20).reduce((a, b) => a + b) / 20
        console.log(`${name}: ${r.cloth.n} particles, ${r.ms.toFixed(0)} ms, KE ${early.toFixed(0)} -> ${late.toFixed(1)}`)
        expect(Number.isFinite(late)).toBe(true)
        expect(late).toBeLessThan(early / 4)
      })

      // Both sides of every seam are sampled identically and welded (they share
      // particles), so no seam can open: nothing falls back to a stitch, and
      // sewn edges end up at exactly the same place.
      it('keeps every seam closed', () => {
        expect(r.cloth.weldedSeams).toBeGreaterThan(0)
        expect(r.cloth.stitchGaps()).toHaveLength(0)
        const psnap = FIXTURES[name] as Psnap
        let worst = 0
        for (const c of psnap.connections) {
          const pa = r.placed.find(p => p.id === c.from.pieceId)
          const pb = r.placed.find(p => p.id === c.to.pieceId)
          if (!pa || !pb) continue
          const ends = (p: typeof pa, end: SeamEnd, copy: number) => {
            const parts = seamParts(p.edges, end).map(i => ({ e: p.edges[i], i }))
            const range = r.cloth.ranges.find(g => g.piece === r.placed.indexOf(p) && g.copy === copy)!
            const first = p.mesh.edgeVerts[parts[0].i][0]
            const lastPart = p.mesh.edgeVerts[parts[parts.length - 1].i]
            const last = lastPart[lastPart.length - 1]
            return [first, last].map(v => Array.from(r.cloth.x.slice((range.start + v) * 3, (range.start + v) * 3 + 3)))
          }
          const [a0, a1] = ends(pa, c.from, 0)
          const [b0, b1] = ends(pb, c.to, pb.region === 'sleeve' && pa.back ? 1 : 0)
          const d = (p: number[], q: number[]) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
          worst = Math.max(worst, Math.min(Math.max(d(a0, b0), d(a1, b1)), Math.max(d(a0, b1), d(a1, b0))))
        }
        expect(worst).toBeLessThan(0.05)
      })

      it('keeps the fabric outside the body', () => {
        const { x } = r.cloth
        let inside = 0
        let worst = Infinity
        for (let i = 0; i < r.cloth.n; i++) {
          const d = grid.sample(x[i * 3], x[i * 3 + 1], x[i * 3 + 2])
          if (d < 0) inside++
          worst = Math.min(worst, d)
        }
        expect(inside / r.cloth.n).toBeLessThan(0.01)
        expect(worst).toBeGreaterThan(-1)
      })

      // Where the pattern fits the body, woven fabric barely stretches. (Where
      // it is smaller than the body — red on the fit map — it has to.)
      it('barely stretches the fabric wherever the pattern fits', () => {
        const stretch = r.cloth.edgeStretch(easeOf(r), EASE_TIGHT).sort((a, b) => a - b)
        const mean = stretch.reduce((a, b) => a + Math.max(0, b), 0) / stretch.length
        const p98 = stretch[Math.floor(stretch.length * 0.98)]
        console.log(`${name}: stretch where it fits: mean ${(mean * 100).toFixed(2)}%, p98 ${(p98 * 100).toFixed(1)}%`)
        expect(mean).toBeLessThan(0.02)
        expect(p98).toBeLessThan(0.08)
      })
    })
  }

  it('a skirt stays at the waist', () => {
    let top = -Infinity
    for (let i = 0; i < results.skirt.cloth.n; i++) top = Math.max(top, results.skirt.cloth.x[i * 3 + 1])
    expect(top).toBeGreaterThan(query.waistY - 2)
  })

  // Trousers drafted with a crotch drop settle until the waist grips; they
  // must not slide off.
  it('trousers hang from the waist and do not slide off', () => {
    let top = -Infinity
    for (let i = 0; i < results.trousers.cloth.n; i++) top = Math.max(top, results.trousers.cloth.x[i * 3 + 1])
    expect(top).toBeGreaterThan(query.waistY - 5)
  })

  it('a shirt hangs from the shoulders instead of sliding off', () => {
    const r = results.shirt
    let top = -Infinity
    let startTop = -Infinity
    for (let i = 0; i < r.cloth.n; i++) {
      top = Math.max(top, r.cloth.x[i * 3 + 1])
      startTop = Math.max(startTop, r.start[i * 3 + 1])
    }
    expect(startTop - top).toBeLessThan(3)
  })

  it('gravity acts: a flared hem falls and swings below its wrapped shape', () => {
    const r = results.skirt
    let meanStart = 0
    let meanEnd = 0
    for (let i = 0; i < r.cloth.n; i++) {
      meanStart += r.start[i * 3 + 1]
      meanEnd += r.cloth.x[i * 3 + 1]
    }
    expect(meanEnd / r.cloth.n).toBeLessThan(meanStart / r.cloth.n)
  })
})

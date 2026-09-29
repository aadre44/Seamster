import { describe, expect, it } from 'vitest'
import skirtFixture from './fixtures/skirt.psnap.json'
import { resolveBody } from './bodyRegions'
import { proceduralBodyQuery } from './bodyQuery'
import { buildBodySdf } from './bodySdf'
import { SdfGrid } from './sdfGrid'
import { placeGarment } from './garmentWrap'
import { Cloth } from './clothSim'
import { seamParts, splitAtRanges } from './pieceGeometry'
import type { PieceShape } from './pieceGeometry'
import type { CanvasElement, PatternPiece, SeamConnection } from '../types'

// A 10 × 4 rectangle whose bottom edge "b" runs right→left along the loop
// although its element runs left→right (flipped).
function rect(): PieceShape {
  const e = (id: string, pts: [number, number][], flipped = false) => ({ id, label: '', isFold: false, pts, base: id, span: [0, 1] as [number, number], flipped })
  return {
    edges: [
      e('t', [[0, 0], [10, 0]]),
      e('r', [[10, 0], [10, 4]]),
      e('b', [[10, 4], [0, 4]], true),
      e('l', [[0, 4], [0, 0]]),
    ],
    loop: [[0, 0], [10, 0], [10, 4], [0, 4]],
  }
}

describe('seam ranges split outline edges', () => {
  it('cuts an edge at fractions of its own length, in the element direction', () => {
    const s = splitAtRanges(rect(), new Map([['t', [0.25, 0.75]], ['b', [0.3]]]))
    const top = s.edges.filter(e => e.base === 't')
    expect(top.map(e => e.span)).toEqual([[0, 0.25], [0.25, 0.75], [0.75, 1]])
    expect(top[1].pts[0][0]).toBeCloseTo(2.5)
    expect(top[1].pts[top[1].pts.length - 1][0]).toBeCloseTo(7.5)
    // "b" is flipped: 30 % along the element (from x=0) is x = 3, reached last along the loop.
    const bottom = s.edges.filter(e => e.base === 'b')
    expect(bottom.map(e => e.span)).toEqual([[0.3, 1], [0, 0.3]])
    expect(bottom[0].pts[bottom[0].pts.length - 1][0]).toBeCloseTo(3)
    expect(s.loop.length).toBe(rect().loop.length + 3)
  })

  it('finds the parts a seam end covers', () => {
    const s = splitAtRanges(rect(), new Map([['t', [0.25, 0.75]]]))
    expect(seamParts(s.edges, { edgeId: 't', range: [0.25, 0.75] }).map(i => s.edges[i].span)).toEqual([[0.25, 0.75]])
    expect(seamParts(s.edges, { edgeId: 't', range: [0, 0.75] })).toHaveLength(2)
    expect(seamParts(s.edges, { edgeId: 't' })).toHaveLength(3)
  })
})

describe('a seam over part of an edge', () => {
  const psnap = structuredClone(skirtFixture) as unknown as { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[] }
  const body = resolveBody({ overrides: {}, shape: 'hourglass' }, {})
  const { sdf, bounds } = buildBodySdf(body)
  // Only the first side-seam element, sewn over its first half.
  const c0 = psnap.connections[0]
  const half: SeamConnection[] = [{ ...c0, from: { ...c0.from, range: [0, 0.5] }, to: { ...c0.to, range: [0, 0.5] } }]
  const { placed } = placeGarment(psnap.pieces, psnap.elements, proceduralBodyQuery(body), half)
  const cloth = new Cloth(placed, half, new SdfGrid(sdf, bounds))

  it('welds only that part', () => {
    const c = half[0]
    const pa = placed.findIndex(p => p.id === c.from.pieceId)
    const pb = placed.findIndex(p => p.id === c.to.pieceId)
    const range = (pi: number) => cloth.ranges.find(r => r.piece === pi && r.copy === 0)!
    const verts = (pi: number, end: SeamConnection['from']) =>
      seamParts(placed[pi].edges, end).flatMap(i => placed[pi].mesh.edgeVerts[i]).map(v => range(pi).start + v)
    const sewnA = verts(pa, c.from)
    const sewnB = verts(pb, c.to)
    const restA = verts(pa, { ...c.from, range: [0.5, 1] }).filter(v => !sewnA.includes(v))
    const allB = verts(pb, { ...c.to, range: [0, 1] })
    expect(sewnA.length).toBeGreaterThan(2)
    expect(sewnA.every(a => sewnB.some(b => cloth.welded(a, b)))).toBe(true)
    expect(restA.length).toBeGreaterThan(2)
    expect(restA.some(a => allB.some(b => cloth.welded(a, b)))).toBe(false)
  })
})

describe('a seam on one side of the body', () => {
  it('sews only that copy of a cut-2 / on-fold piece', () => {
    const psnap = structuredClone(skirtFixture) as unknown as { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[] }
    const body = resolveBody({ overrides: {}, shape: 'hourglass' }, {})
    const { sdf, bounds } = buildBodySdf(body)
    const grid = new SdfGrid(sdf, bounds)
    const c0 = psnap.connections[0]
    const weldsFor = (c: SeamConnection) => {
      const { placed } = placeGarment(psnap.pieces, psnap.elements, proceduralBodyQuery(body), [c])
      return new Cloth(placed, [c], grid).weldedSeams
    }
    expect(weldsFor(c0)).toBe(2)
    expect(weldsFor({ ...c0, from: { ...c0.from, side: 'left' } })).toBe(1)
    expect(weldsFor({ ...c0, to: { ...c0.to, side: 'right' } })).toBe(1)
  })
})

import { describe, expect, it } from 'vitest'
import userFile from '../../three/fixtures/trousers-waistband.psnap.json'
import { initialState, reducer } from '../../context/EditorContext'
import { loadPsnapAction } from '../../utils/psnap'
import { resolveBody } from '../../three/bodyRegions'
import { proceduralBodyQuery } from '../../three/bodyQuery'
import { buildBodySdf } from '../../three/bodySdf'
import { SdfGrid } from '../../three/sdfGrid'
import { placeGarment } from '../../three/garmentWrap'
import { Cloth, DRAPE } from '../../three/clothSim'
import { bandEdge, bandSeams } from './bands'

// A user's trousers with a hand-drawn "Waist Band" sewn WHOLE to both the
// front and the back waist (two overlapping seams, no sides).
const loaded = reducer(initialState, loadPsnapAction(JSON.stringify(userFile)))
const byId = new Map(loaded.elements.map(e => [e.id, e]))
const piece = (name: string) => loaded.pieces.find(p => p.name === name)!
const band = piece('Waist Band'), front = piece('Front Leg'), back = piece('Back Leg')
const bandSeamsNow = loaded.connections.filter(c => c.from.pieceId === band.id || c.to.pieceId === band.id)

describe('a waistband across several pieces', () => {
  it('is re-made as consecutive stretches round the body: R front, R back, L back, L front', () => {
    expect(bandSeamsNow.map(c => [c.to.pieceId === front.id ? 'front' : 'back', c.to.side])).toEqual([
      ['front', 'right'], ['back', 'right'], ['back', 'left'], ['front', 'left']])
    const ranges = bandSeamsNow.map(c => c.from.range!)
    ranges.slice(1).forEach((r, i) => expect(r[0]).toBeCloseTo(ranges[i][1], 3)) // end to end, no overlap
    // length-true: each stretch is as long as the waist edge it is sewn to
    const L = 102.6
    const waistLen = (pid: string) => (pid === front.id ? 21.1 : 23.0)
    bandSeamsNow.forEach(c => expect((c.from.range![1] - c.from.range![0]) * L).toBeCloseTo(waistLen(c.to.pieceId), 0))
    // the band is longer than the waist: the rest is left as an overlap at its end
    expect(ranges[3][1]).toBeLessThan(0.9)
  })

  it('does the same when sewn by hand in Assembly (any click order)', () => {
    const edge = bandEdge(band, byId)!
    const s0 = { ...loaded, connections: loaded.connections.filter(c => !bandSeamsNow.includes(c)) }
    const waist = (p: typeof front) => p.elementIds.find(id => (byId.get(id) as { seamLabel?: string }).seamLabel === 'waist')!
    const s1 = reducer(s0, { type: 'ADD_CONNECTION', connection: { label: 'waist', from: { pieceId: band.id, edgeId: edge.id }, to: { pieceId: back.id, edgeId: waist(back) }, source: 'user' } })
    const s2 = reducer(s1, { type: 'ADD_CONNECTION', connection: { label: 'waist', from: { pieceId: front.id, edgeId: waist(front) }, to: { pieceId: band.id, edgeId: edge.id }, source: 'user' } })
    expect(s2.connections.filter(c => c.from.pieceId === band.id)).toHaveLength(4)
    expect(bandSeams(band, edge, [{ pieceId: front.id, edgeId: waist(front) }, { pieceId: back.id, edgeId: waist(back) }], loaded.pieces, byId)).toHaveLength(4)
  })

  it('sits round the waist in 3D as one piece, without pulling front and back together', () => {
    const body = resolveBody({ overrides: {}, shape: 'rectangle', sex: 'male' }, {})
    const query = proceduralBodyQuery(body)
    const { sdf, bounds } = buildBodySdf(body)
    const { placed } = placeGarment(loaded.pieces, loaded.elements, query, loaded.connections, loaded.placements)
    const wb = placed.find(p => p.name === 'Waist Band')!
    expect(wb.copies).toHaveLength(1)
    const cloth = new Cloth(placed, loaded.connections, new SdfGrid(sdf, bounds))
    const energy: number[] = []
    for (let s = 0; s < DRAPE.steps; s++) { cloth.step(DRAPE.dt, DRAPE.substeps); energy.push(cloth.kineticEnergy()) }
    expect(energy.slice(-20).reduce((a, b) => a + b) / 20).toBeLessThan(energy.slice(0, 20).reduce((a, b) => a + b) / 20 / 4)
    expect(cloth.stitchGaps()).toHaveLength(0)
    // the overlap is fastened over the band's start, on top of it
    const wbRange = cloth.ranges.find(r => placed[r.piece] === wb)!
    expect(wb.pins?.[0]?.length).toBeGreaterThan(10)
    expect(Math.max(...cloth.pinGaps(0.5, true))).toBeLessThan(0.6)
    const sides = cloth.pinSides(wbRange).sort((a, b) => a - b)
    expect(sides[Math.floor(sides.length / 2)]).toBeGreaterThan(0)
    const pos = cloth.positionsOf(wbRange)
    const ys = pos.filter((_, i) => i % 3 === 1), xs = pos.filter((_, i) => i % 3 === 0), zs = pos.filter((_, i) => i % 3 === 2)
    // round the whole waist (both sides, front and back), at waist height
    expect(Math.min(...xs)).toBeLessThan(-10)
    expect(Math.max(...xs)).toBeGreaterThan(10)
    expect(Math.max(...zs) - Math.min(...zs)).toBeGreaterThan(15)
    const mid = ys.reduce((a, b) => a + b, 0) / ys.length
    expect(Math.abs(mid - query.waistY)).toBeLessThan(8)
    // the trousers' front and back waists are still apart (front forward, back behind)
    const legZ = (name: string) => {
      const r = cloth.ranges.find(g => placed[g.piece].name === name)!
      const p = cloth.positionsOf(r)
      return p.filter((_, i) => i % 3 === 2).reduce((a, b) => a + b, 0) / r.count
    }
    expect(legZ('Front Leg') - legZ('Back Leg')).toBeGreaterThan(5)
  })
})

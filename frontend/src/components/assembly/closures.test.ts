import { describe, expect, it } from 'vitest'
import shirt from '../../three/fixtures/shirt-trims.psnap.json'
import { DEFAULT_ROW, buttonRow, rowPoints } from './closures'
import { insidePolygon, pieceEdges, sampleEdge } from './geometry'
import { resolveBody } from '../../three/bodyRegions'
import { proceduralBodyQuery } from '../../three/bodyQuery'
import { placeGarment } from '../../three/garmentWrap'
import { copySide } from '../../three/trimPlacement'
import type { CanvasElement, PatternPiece, SeamConnection } from '../../types'

const psnap = shirt as unknown as { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[] }
const byId = new Map(psnap.elements.map(e => [e.id, e]))
const front = psnap.pieces.find(p => p.name === 'Front Bodice')!

describe('button row', () => {
  it('spaces the buttons evenly down the front, inside the piece', () => {
    const pts = rowPoints(front, byId, DEFAULT_ROW)
    expect(pts).toHaveLength(6)
    const gaps = pts.slice(1).map((p, i) => p.y - pts[i].y)
    for (const g of gaps) expect(g).toBeCloseTo(gaps[0], 6)
    const outline = pieceEdges(front, byId).flatMap(e => sampleEdge(e, 16).pts)
    for (const p of pts) expect(insidePolygon(outline, p)).toBe(true)
  })

  it('puts the buttons on one front and the holes on the other', () => {
    const els = buttonRow(front, byId, DEFAULT_ROW) as (CanvasElement & { seamLabel?: string; side?: string; pieceId?: string })[]
    expect(els.filter(e => e.seamLabel === 'button').every(e => e.side === 'right')).toBe(true)
    expect(els.filter(e => e.seamLabel === 'buttonhole')).toHaveLength(6)
    expect(els.filter(e => e.seamLabel === 'buttonhole').every(e => e.side === 'left')).toBe(true)
    expect(els.every(e => e.pieceId === front.id)).toBe(true)
  })

  it('shows each marking only on its side in 3D', async () => {
    const { outsideMarks } = await import('../../three/garmentWorker')
    const elements = [...psnap.elements, ...buttonRow(front, byId, DEFAULT_ROW)]
    const body = resolveBody({ overrides: {}, shape: 'rectangle', sex: 'male' }, {})
    const { placed } = placeGarment(psnap.pieces, elements, proceduralBodyQuery(body), psnap.connections, [])
    const p = placed.find(x => x.id === front.id)!
    const marks = outsideMarks(p, { elements, pieces: psnap.pieces, connections: psnap.connections })
    const sides = (kind: string) => new Set(marks.filter(m => m.kind === kind).map(m => copySide(p, m.copy)))
    expect([...sides('button')]).toEqual(['right'])
    expect([...sides('buttonhole')]).toEqual(['left'])
  })
})

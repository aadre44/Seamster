import { describe, expect, it } from 'vitest'
import shirt from '../three/fixtures/shirt-trims.psnap.json'
import trousers from '../three/fixtures/trousers-trims.psnap.json'
import { pieceEdges } from '../components/assembly/geometry'
import { PRESETS } from './presets'
import { presetContext } from './context'
import { extractOutline } from '../three/pieceGeometry'
import { isTrimName } from '../three/pieceClassifier'
import type { CanvasElement, PatternPiece } from '../types'

const empty = { neck: null, waist: null, wrist: null, measurements: {} }
const len = (e: CanvasElement) => (e.type === 'line' ? Math.hypot(e.end.x - e.start.x, e.end.y - e.start.y) : 0)

describe('piece library', () => {
  it('every piece is a closed outline centred on the drop point, named like a trim', () => {
    for (const p of PRESETS) {
      const r = p.make(empty)
      if (!r.piece) continue
      const piece = { ...r.piece, elementIds: r.piece.elementIds! } as PatternPiece
      const shape = extractOutline(piece, new Map(r.elements.map(e => [e.id, e])))
      expect(shape, p.id).not.toBeNull()
      expect(isTrimName(piece.name), p.id).toBe(true)
      const xs = r.elements.flatMap(e => ('start' in e ? [e.start.x, e.end.x] : []))
      expect(Math.abs(Math.min(...xs) + Math.max(...xs)), p.id).toBeLessThan(1e-6)
    }
  })

  it('buttons and buttonholes are markings, not pieces', () => {
    for (const p of PRESETS.filter(p => p.category === 'Buttons')) {
      const r = p.make(empty)
      expect(r.piece).toBeUndefined()
      expect(r.elements.every(e => 'seamLabel' in e && ['button', 'buttonhole'].includes(e.seamLabel!))).toBe(true)
    }
    const hole = PRESETS.find(p => p.id === 'buttonhole-h')!.make(empty).elements[0]
    expect(len(hole)).toBeCloseTo(1.8)
  })

  it('sizes collars, cuffs and waistbands to the pattern', () => {
    const s = shirt as unknown as { pieces: PatternPiece[]; elements: CanvasElement[] }
    const ctx = presetContext(s.pieces, s.elements, {})
    expect(ctx.neck).toBeGreaterThan(50) // button-front shirt: 2 × (front incl. extension + back)
    expect(ctx.wrist).toBeCloseTo(42, 0) // an on-fold sleeve's wrist, both halves
    const collar = PRESETS.find(p => p.id === 'collar-stand')!.make(ctx)
    const neckEdge = collar.elements.find(e => 'seamLabel' in e && e.seamLabel === 'neckline')!
    expect(len(neckEdge)).toBeCloseTo(ctx.neck! + 3, 1)
    const t = trousers as unknown as { pieces: PatternPiece[]; elements: CanvasElement[] }
    const tctx = presetContext(t.pieces, t.elements, {})
    expect(tctx.waist).toBeGreaterThan(70)
    const band = PRESETS.find(p => p.id === 'waistband')!.make(tctx)
    expect(len(band.elements.find(e => 'seamLabel' in e && e.seamLabel === 'waist')!)).toBeCloseTo(tctx.waist! + 4, 1)
  })

  it('falls back to standard sizes with no pattern', () => {
    const collar = PRESETS.find(p => p.id === 'collar-stand')!.make(empty)
    expect(len(collar.elements.find(e => 'seamLabel' in e && e.seamLabel === 'neckline')!)).toBeCloseTo(43)
  })
})

describe('waistbands in the library', async () => {
  const { bandEdge, bandSeams, openingEdges } = await import('../components/assembly/bands')
  const { resolveBody } = await import('../three/bodyRegions')
  const { proceduralBodyQuery } = await import('../three/bodyQuery')
  const { placeGarment } = await import('../three/garmentWrap')
  const t = trousers as unknown as { pieces: PatternPiece[]; elements: CanvasElement[]; connections: import('../types').SeamConnection[] }
  const ctx = { ...presetContext(t.pieces, t.elements, { hip: 98 }) }
  const waistbands = PRESETS.filter(p => p.category === 'Waistbands')
  const edgeLen = (r: ReturnType<typeof waistbands[0]['make']>, label: string) =>
    r.elements.filter(e => 'seamLabel' in e && e.seamLabel === label).reduce((s, e) => s + (e.type === 'line' ? len(e) : 0), 0)

  it('offers straight, contoured, elastic and drawstring bands that attach to the waist', () => {
    expect(waistbands.map(p => p.id)).toEqual(['waistband', 'wb-narrow', 'wb-wide', 'wb-contoured', 'wb-elastic', 'wb-drawstring'])
    expect(waistbands.every(p => p.attach === 'waist')).toBe(true)
  })

  it('sizes them: waist + a 4 cm overlap, casings over the hips; folded bands marked at their fold', () => {
    expect(edgeLen(PRESETS.find(p => p.id === 'waistband')!.make(ctx), 'waist')).toBeCloseTo(ctx.waist! + 4, 1)
    expect(edgeLen(PRESETS.find(p => p.id === 'wb-elastic')!.make(ctx), 'waist')).toBeCloseTo(98 + 4, 1)
    for (const id of ['waistband', 'wb-narrow', 'wb-wide', 'wb-elastic', 'wb-drawstring']) {
      const r = PRESETS.find(p => p.id === id)!.make(ctx)
      const fold = r.elements.find(e => 'seamLabel' in e && e.seamLabel === 'fold_line')
      expect(fold, id).toBeDefined()
      expect(fold!.type === 'line' && fold!.start.y).toBeCloseTo(0, 6) // halfway up the centred band
    }
  })

  it('shapes the contoured band: its sewn edge 6 cm longer than its top', () => {
    const r = PRESETS.find(p => p.id === 'wb-contoured')!.make(ctx)
    const curves = r.elements.filter(e => e.type === 'curve')
    const arcLen = (e: CanvasElement) => {
      if (e.type !== 'curve') return 0
      let l = 0, prev = e.start
      for (let i = 1; i <= 64; i++) {
        const tt = i / 64, u = 1 - tt
        const p = { x: u * u * u * e.start.x + 3 * u * u * tt * e.cp1.x + 3 * u * tt * tt * e.cp2.x + tt * tt * tt * e.end.x,
          y: u * u * u * e.start.y + 3 * u * u * tt * e.cp1.y + 3 * u * tt * tt * e.cp2.y + tt * tt * tt * e.end.y }
        l += Math.hypot(p.x - prev.x, p.y - prev.y); prev = p
      }
      return l
    }
    const sewn = curves.find(e => 'seamLabel' in e && e.seamLabel === 'waist')!
    const top = curves.find(e => e !== sewn)!
    expect(arcLen(sewn)).toBeCloseTo(ctx.waist! + 4, 0)
    expect(arcLen(sewn) - arcLen(top)).toBeCloseTo(6, 0)
  })

  const drop = (id: string) => {
    const r = PRESETS.find(p => p.id === id)!.make(ctx)
    const piece = { ...r.piece!, elementIds: r.piece!.elementIds! } as PatternPiece
    const all = new Map([...t.elements, ...r.elements].map(e => [e.id, e]))
    const edge = pieceEdges(piece, all).find(e => e.seamLabel === 'waist') ?? bandEdge(piece, all)!
    const seams = bandSeams(piece, edge, openingEdges(t.pieces, all, 'waist'), [...t.pieces, piece], all)!
    return { piece, elements: [...t.elements, ...r.elements], seams }
  }

  it('is sewn round the whole waist when dropped; elastic is gathered all along it', () => {
    const straight = drop('waistband')
    expect(straight.seams.map(c => c.to.side)).toEqual(['right', 'right', 'left', 'left'])
    const last = straight.seams[3].from.range![1]
    expect(last).toBeCloseTo(ctx.waist! / (ctx.waist! + 4), 2) // the 4 cm overlap left at the end
    const elastic = drop('wb-elastic')
    expect(elastic.seams[0].from.range![0]).toBeCloseTo(0, 3)
    expect(elastic.seams[3].from.range![1]).toBeCloseTo(1, 3)
  })

  it('stands at its finished height on the body (folded), not twice it', () => {
    const { piece, elements, seams } = drop('waistband')
    const body = resolveBody({ overrides: {}, shape: 'rectangle', sex: 'male' }, {})
    const q = proceduralBodyQuery(body)
    const { placed } = placeGarment([...t.pieces, piece], elements, q, [...t.connections, ...seams], [])
    const wb = placed.find(p => p.id === piece.id)!
    const ys = wb.copies[0].positions.filter((_, i) => i % 3 === 1)
    const legTop = Math.max(...placed.find(p => p.name === 'Front Leg')!.copies[0].positions.filter((_, i) => i % 3 === 1))
    expect(Math.max(...ys) - legTop).toBeLessThan(4 + 1.5) // 4 cm finished (cut 8)
    expect(Math.max(...ys) - legTop).toBeGreaterThan(2.5)
  })
})

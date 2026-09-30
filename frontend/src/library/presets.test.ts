import { describe, expect, it } from 'vitest'
import shirt from '../three/fixtures/shirt-trims.psnap.json'
import trousers from '../three/fixtures/trousers-trims.psnap.json'
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

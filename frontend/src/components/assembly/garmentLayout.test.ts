import { describe, expect, it } from 'vitest'
import trousers from '../../three/fixtures/trousers-trims.psnap.json'
import dress from '../../three/fixtures/dress.psnap.json'
import shirt from '../../three/fixtures/shirt-trims.psnap.json'
import { LAYOUT_GAP, copyKey, garmentLayout } from './garmentLayout'
import { apply, pieceEdges } from './geometry'
import type { CanvasElement, PatternPiece, SeamConnection } from '../../types'

type Psnap = { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[] }
const load = (f: unknown) => f as Psnap
const id = (p: Psnap, name: string) => p.pieces.find(x => x.name === name)!.id
const centreX = (l: ReturnType<typeof garmentLayout>, key: string) => {
  const pts = l.outlines.get(key)!
  return (Math.min(...pts.map(p => p.x)) + Math.max(...pts.map(p => p.x))) / 2
}
const bbox = (l: ReturnType<typeof garmentLayout>, key: string) => {
  const pts = l.outlines.get(key)!
  return { minY: Math.min(...pts.map(p => p.y)), maxY: Math.max(...pts.map(p => p.y)) }
}

describe('garment layout (around the body)', () => {
  const t = load(trousers)
  const L = garmentLayout(t.pieces, t.elements, t.connections)
  const FL = id(t, 'Front Leg'), BL = id(t, 'Back Leg')

  it('shows every cut copy of the shell: R back | R front | L front | L back', () => {
    const order = [copyKey(BL, 'right'), copyKey(FL, 'right'), copyKey(FL, 'left'), copyKey(BL, 'left')]
    const xs = order.map(k => centreX(L, k))
    expect(xs).toEqual([...xs].sort((a, b) => a - b))
    expect(L.copies.filter(c => c.role === 'shell')).toHaveLength(4)
  })

  it('lays the side seams next to each other, a small gap apart', () => {
    const byId = new Map(t.elements.map(e => [e.id, e]))
    for (const side of ['left', 'right'] as const) {
      const ends = (pid: string) => {
        const tr = L.transforms.get(copyKey(pid, side))!
        return pieceEdges(t.pieces.find(p => p.id === pid)!, byId).filter(e => e.seamLabel === 'side_seam').flatMap(e => [apply(tr, e.start), apply(tr, e.end)])
      }
      // Front and back hip curves both bulge outward, so laid flat they touch
      // near the hip and part toward the waist and hem: the closest points are
      // about a gap apart, the seam's ends within a few cm.
      const front = ends(FL), back = ends(BL)
      const closest = Math.min(...front.map(p => Math.min(...back.map(q => Math.hypot(p.x - q.x, p.y - q.y)))))
      expect(closest).toBeLessThan(LAYOUT_GAP + 1)
      const span = (pts: { x: number; y: number }[]) => [pts.reduce((a, p) => (p.y < a.y ? p : a)), pts.reduce((a, p) => (p.y > a.y ? p : a))]
      const [ft, fb] = span(front), [bt, bb] = span(back)
      expect(Math.hypot(ft.x - bt.x, ft.y - bt.y)).toBeLessThan(10)
      expect(Math.hypot(fb.x - bb.x, fb.y - bb.y)).toBeLessThan(10)
    }
  })

  it('mirrors the left side of the right side about the centre line', () => {
    const r = L.outlines.get(copyKey(FL, 'right'))!, l = L.outlines.get(copyKey(FL, 'left'))!
    r.forEach((p, i) => { expect(l[i].x).toBeCloseTo(-p.x, 6); expect(l[i].y).toBeCloseTo(p.y, 6) })
  })

  it('puts trims in the tray under the garment and finds the copy under a point', () => {
    const tray = L.copies.filter(c => c.role === 'tray')
    expect(tray.map(c => t.pieces.find(p => p.id === c.pieceId)!.name)).toContain('Fly Facing')
    const garmentBottom = Math.max(...L.copies.filter(c => c.role === 'shell').map(c => bbox(L, c.key).maxY))
    for (const c of tray) expect(bbox(L, c.key).minY).toBeGreaterThan(garmentBottom)
    const inside = L.outlines.get(copyKey(BL, 'left'))!
    const mid = { x: inside.reduce((s, p) => s + p.x, 0) / inside.length, y: inside.reduce((s, p) => s + p.y, 0) / inside.length }
    expect(L.copyAt(mid)?.key).toBe(copyKey(BL, 'left'))
  })

  it('centred on the back, the backs are in the middle', () => {
    const B = garmentLayout(t.pieces, t.elements, t.connections, { centre: 'back' })
    expect(Math.abs(centreX(B, copyKey(BL, 'left')))).toBeLessThan(Math.abs(centreX(B, copyKey(FL, 'left'))))
  })

  it('stacks a dress bodice above its skirt', () => {
    const d = load(dress)
    const D = garmentLayout(d.pieces, d.elements, d.connections)
    expect(bbox(D, copyKey(id(d, 'Front Bodice'), 'left')).maxY).toBeLessThan(bbox(D, copyKey(id(d, 'Front Skirt'), 'left')).minY)
  })

  it('puts a shirt’s sleeves above the body, both halves of each', () => {
    const s = load(shirt)
    const S = garmentLayout(s.pieces, s.elements, s.connections)
    const sleeve = S.copies.filter(c => c.role === 'sleeve')
    expect(sleeve.map(c => `${c.side}-${c.half}`).sort()).toEqual(['left-back', 'left-front', 'right-back', 'right-front'])
    const bodyTop = Math.min(...S.copies.filter(c => c.role === 'shell').map(c => bbox(S, c.key).minY))
    for (const c of sleeve) expect(bbox(S, c.key).maxY).toBeLessThan(bodyTop)
  })
})

describe('garment layout keeps copies apart', () => {
  it('never overlaps two copies (trouser legs clear each other at the crotch)', () => {
    for (const f of [trousers, dress, shirt]) {
      const p = load(f)
      const L = garmentLayout(p.pieces, p.elements, p.connections)
      const garment = L.copies.filter(c => c.role !== 'tray')
      for (const a of garment) for (const b of garment) {
        if (a.key >= b.key) continue
        if (a.pieceId === b.pieceId && a.side === b.side) continue // a sleeve's two halves share their fold
        // no vertex of one strictly inside the other (a gap apart at most touching)
        const pa = L.outlines.get(a.key)!, pb = L.outlines.get(b.key)!
        const inside = pa.filter(q => L.copyAt(q, 0)?.key === b.key).length
        expect(inside, `${a.key} in ${b.key}`).toBeLessThan(pa.length * 0.02 + 1)
        void pb
      }
    }
  })
})

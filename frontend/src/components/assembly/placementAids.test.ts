import { describe, expect, it } from 'vitest'
import trousers from '../../three/fixtures/trousers-trims.psnap.json'
import { distances, hostRefs, moveTo, placedBox, snapPlacement } from './placementAids'
import type { CanvasElement, PatternPiece, Placement } from '../../types'

const psnap = trousers as unknown as { elements: CanvasElement[]; pieces: PatternPiece[]; placements: Placement[] }
const byId = new Map(psnap.elements.map(e => [e.id, e]))
const piece = (name: string) => psnap.pieces.find(p => p.name === name)!
const back = piece('Back Leg'), pocket = piece('Back Pocket')
const base = psnap.placements[0] // the inferred back pocket, on the back leg

describe('placement aids', () => {
  it('finds the host’s centre line, waist and side seam', () => {
    const r = hostRefs(back, byId)
    expect(r.centreX).not.toBeNull()
    const b = placedBox(base, pocket, byId)
    expect(r.waistY(b.cx)!).toBeLessThan(b.minY) // the pocket is below the waist
    expect(r.sideX(b.cy)!).toBeGreaterThan(b.maxX) // …and inside the side seam
  })

  it('reports distances and moves to exact ones', () => {
    const d = distances(base, pocket, back, byId)
    // The generator puts back pockets 6 cm below the lowest point of the (sloped)
    // back waist; measured straight above the pocket's centre it is a little more.
    expect(d.belowTop!).toBeGreaterThanOrEqual(5.9)
    expect(d.belowTop!).toBeLessThan(8)
    const moved = moveTo(base, pocket, back, byId, { belowTop: 10, fromCentre: 9 })
    const d2 = distances(moved, pocket, back, byId)
    expect(d2.belowTop).toBeCloseTo(10, 1)
    expect(d2.fromCentre).toBeCloseTo(9, 1)
  })

  it('snaps the centre onto the side seam, with a guide', () => {
    const r = hostRefs(back, byId)
    const b = placedBox(base, pocket, byId)
    const onSeam = r.sideX(b.cy)!
    const near = { ...base, transform: { ...base.transform, dx: base.transform.dx + (onSeam - b.cx) + 0.5 } } // 0.5 cm off
    const s = snapPlacement(near, pocket, back, byId, [])
    const after = placedBox({ ...near, transform: { ...near.transform, dx: s.dx, dy: s.dy } }, pocket, byId)
    expect(after.cx).toBeCloseTo(hostRefs(back, byId).sideX(after.cy)!, 1)
    expect(s.guides.map(g => g.label)).toContain('on the side seam')
  })

  it('snaps level with the twin on the other side', () => {
    const twin = { ...base, id: 'twin', side: 'left' as const }
    const off = { ...base, side: 'right' as const, transform: { ...base.transform, dy: base.transform.dy + 0.6 } }
    const s = snapPlacement(off, pocket, back, byId, [twin])
    expect(s.dy).toBeCloseTo(base.transform.dy, 6)
  })
})

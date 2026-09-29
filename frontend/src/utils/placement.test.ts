import { describe, expect, it } from 'vitest'
import { applyMatrix, placementMatrix } from './placement'
import type { Placement } from '../types'

const pl = (transform: Placement['transform']): Placement => ({ id: 'p', pieceId: 'a', hostId: 'b', transform, stitched: [] })
const c = { x: 10, y: 20 }

describe('placement transform', () => {
  it('translates the piece', () => {
    expect(applyMatrix(placementMatrix(pl({ dx: 5, dy: -3, rotation: 0 }), c), 12, 20)).toEqual([17, 17])
  })

  it('rotates about the piece centre (y down: +90° turns right into down)', () => {
    const [x, y] = applyMatrix(placementMatrix(pl({ dx: 0, dy: 0, rotation: 90 }), c), 12, 20)
    expect(x).toBeCloseTo(10)
    expect(y).toBeCloseTo(22)
    const [cx, cy] = applyMatrix(placementMatrix(pl({ dx: 1, dy: 1, rotation: 37 }), c), 10, 20)
    expect(cx).toBeCloseTo(11)
    expect(cy).toBeCloseTo(21)
  })

  it('mirrors before rotating', () => {
    const [x, y] = applyMatrix(placementMatrix(pl({ dx: 0, dy: 0, rotation: 0, flip: true }), c), 12, 21)
    expect(x).toBeCloseTo(8)
    expect(y).toBeCloseTo(21)
  })
})

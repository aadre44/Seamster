import { describe, expect, it } from 'vitest'
import { initialState } from '../context/EditorContext'
import { loadPsnapAction, toPsnap } from './psnap'
import type { Placement, SeamConnection } from '../types'

describe('.psnap round trip', () => {
  it('keeps seams and placements (the 3D view sews from them)', () => {
    const connections: SeamConnection[] = [
      { label: 'side_seam', from: { pieceId: 'A', edgeId: 'a1', range: [0, 0.5] }, to: { pieceId: 'B', edgeId: 'b1', side: 'left' }, source: 'user' },
    ]
    const placements: Placement[] = [{ id: 'p', pieceId: 'C', hostId: 'A', transform: { dx: 1, dy: 2, rotation: 15 }, stitched: ['c1'] }]
    const doc = JSON.stringify(toPsnap({ ...initialState, connections, placements }))
    const action = loadPsnapAction(doc)
    expect(action.connections).toEqual(connections)
    expect(action.placements).toEqual(placements)
  })

  it('loads old files without placements', () => {
    expect(loadPsnapAction(JSON.stringify({ version: 1, elements: [] })).placements).toEqual([])
  })

  it('rejects files without elements', () => {
    expect(() => loadPsnapAction('{"version":1}')).toThrow()
  })
})

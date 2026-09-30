import { describe, expect, it } from 'vitest'
import fixture from '../../three/fixtures/trousers-trims.psnap.json'
import { flySeams, guessFly } from './autoFly'
import { initialState, reducer } from '../../context/EditorContext'
import type { CanvasElement, PatternPiece, Placement, SeamConnection } from '../../types'

const psnap = fixture as unknown as { elements: CanvasElement[]; pieces: PatternPiece[]; connections: SeamConnection[]; placements: Placement[] }
const byId = new Map(psnap.elements.map(e => [e.id, e]))
const id = (name: string) => psnap.pieces.find(p => p.name === name)!.id

describe('auto-placed fly', () => {
  const plan = guessFly(psnap.pieces, byId)

  it('finds the front leg, the facing and the shield by name', () => {
    expect(plan).toEqual({ host: id('Front Leg'), facing: id('Fly Facing'), shield: id('Fly Shield'), facingSide: 'left' })
  })

  it('sews them exactly as the generator does (same edges, ranges, sides, direction)', () => {
    const strip = (c: SeamConnection) => ({ from: c.from, to: c.to, reversed: c.reversed })
    const backend = psnap.connections.filter(c => c.label === 'fly').map(strip)
    expect(flySeams(plan, psnap.pieces, byId).map(strip)).toEqual(backend)
  })

  it('puts the facing on the other side when asked', () => {
    const seams = flySeams({ ...plan, facingSide: 'right' }, psnap.pieces, byId)
    expect(seams.map(c => c.to.side)).toEqual(['right', 'left'])
  })

  it('replaces a fly that was dragged on by hand', () => {
    const manual: Placement = { id: 'm', pieceId: id('Fly Facing'), hostId: id('Front Leg'), transform: { dx: 3, dy: 4, rotation: 20 }, stitched: [], source: 'user' }
    const s0 = { ...initialState, pieces: psnap.pieces, elements: psnap.elements, placements: [manual],
      connections: psnap.connections.filter(c => c.label !== 'fly') }
    const seams = flySeams(plan, psnap.pieces, byId)
    const s1 = reducer(s0, { type: 'REPLACE_ATTACHMENTS', pieceIds: [id('Fly Facing'), id('Fly Shield')], connections: seams,
      layers: { [id('Fly Facing')]: 'inside', [id('Fly Shield')]: 'inside' } })
    expect(s1.placements).toEqual([])
    expect(s1.connections.filter(c => c.label === 'fly')).toHaveLength(2)
    expect(s1.pieces.find(p => p.name === 'Fly Facing')!.layer).toBe('inside')
    expect(reducer(s1, { type: 'UNDO' }).placements).toEqual([manual])
  })
})

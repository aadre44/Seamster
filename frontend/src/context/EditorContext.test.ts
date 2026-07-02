// Reducer tests for the undo/redo model: history entries must version
// elements, pieces AND connections together (T1 — codebase-review-tasks.md).
import { describe, expect, it } from 'vitest'
import { initialState, reducer } from './EditorContext'
import type { EditorState, GrainLineElement, LineElement, PatternPiece, SeamConnection } from '../types'

function line(id: string, x1: number, y1: number, x2: number, y2: number, pieceId?: string): LineElement {
  return { id, type: 'line', start: { x: x1, y: y1 }, end: { x: x2, y: y2 }, isFold: false, ...(pieceId ? { pieceId } : {}) }
}

function grain(id: string, pieceId: string): GrainLineElement {
  return { id, type: 'grain-line', start: { x: 2, y: 2 }, end: { x: 2, y: 8 }, pieceId }
}

function piece(id: string, elementIds: string[]): PatternPiece {
  return { id, name: 'Test Piece', elementIds, cutQty: 2, onFold: false, seamAllowance: 1.5, closed: true }
}

// A triangle piece P1 with an interior grain line, plus one loose element,
// and a connection attached to P1's edge L2.
function baseState(): EditorState {
  const elements = [
    line('L1', 0, 0, 10, 0, 'P1'),
    line('L2', 10, 0, 0, 10, 'P1'),
    line('L3', 0, 10, 0, 0, 'P1'),
    grain('G1', 'P1'),
    line('LOOSE', 20, 20, 30, 30),
  ]
  const connections: SeamConnection[] = [
    { label: 'side_seam', from: { pieceId: 'P1', edgeId: 'L2' }, to: { pieceId: 'P2', edgeId: 'X1' } },
    { label: 'hem', from: { pieceId: 'P2', edgeId: 'X2' }, to: { pieceId: 'P3', edgeId: 'X3' } },
  ]
  return { ...initialState, elements, pieces: [piece('P1', ['L1', 'L2', 'L3'])], connections }
}

describe('DELETE_PIECE', () => {
  it('removes outline elements, interior markings and connections in one step', () => {
    const s1 = reducer(baseState(), { type: 'DELETE_PIECE', id: 'P1' })
    expect(s1.pieces).toHaveLength(0)
    expect(s1.elements.map(e => e.id)).toEqual(['LOOSE'])
    expect(s1.connections).toHaveLength(1)
    expect(s1.connections[0].label).toBe('hem')
  })

  it('is fully undoable and redoable', () => {
    const s0 = baseState()
    const s1 = reducer(s0, { type: 'DELETE_PIECE', id: 'P1' })
    const s2 = reducer(s1, { type: 'UNDO' })
    expect(s2.pieces).toHaveLength(1)
    expect(s2.elements).toHaveLength(5)
    expect(s2.connections).toHaveLength(2)

    const s3 = reducer(s2, { type: 'REDO' })
    expect(s3.pieces).toHaveLength(0)
    expect(s3.elements.map(e => e.id)).toEqual(['LOOSE'])
    expect(s3.connections).toHaveLength(1)
  })
})

describe('MIRROR_PIECE + UNDO', () => {
  it('leaves no dangling piece after undo', () => {
    const s0 = baseState()
    const s1 = reducer(s0, { type: 'MIRROR_PIECE', pieceId: 'P1', op: 'flipH' })
    expect(s1.pieces).toHaveLength(2)
    expect(s1.elements.length).toBeGreaterThan(s0.elements.length)

    const s2 = reducer(s1, { type: 'UNDO' })
    expect(s2.pieces).toHaveLength(1)
    expect(s2.elements).toHaveLength(s0.elements.length)
    // Invariant: every piece's elementIds resolve to live elements
    const ids = new Set(s2.elements.map(e => e.id))
    for (const p of s2.pieces) {
      for (const eid of p.elementIds) expect(ids.has(eid)).toBe(true)
    }
  })
})

describe('ADD_PIECE (close outline) + UNDO/REDO', () => {
  it('round-trips the piece and the element tagging', () => {
    const s0: EditorState = {
      ...initialState,
      elements: [line('A', 0, 0, 10, 0), line('B', 10, 0, 0, 10), line('C', 0, 10, 0, 0)],
    }
    const s1 = reducer(s0, { type: 'ADD_PIECE', piece: piece('NEW', ['A', 'B', 'C']) })
    expect(s1.pieces).toHaveLength(1)
    expect(s1.elements.every(e => 'pieceId' in e && e.pieceId === 'NEW')).toBe(true)

    const s2 = reducer(s1, { type: 'UNDO' })
    expect(s2.pieces).toHaveLength(0)
    expect(s2.elements.every(e => !('pieceId' in e) || e.pieceId === undefined)).toBe(true)

    const s3 = reducer(s2, { type: 'REDO' })
    expect(s3.pieces).toHaveLength(1)
    expect(s3.elements.every(e => 'pieceId' in e && e.pieceId === 'NEW')).toBe(true)
  })
})

describe('UPDATE_PIECE coalescing', () => {
  it('groups consecutive edits to the same piece into one undo entry', () => {
    const s0 = baseState()
    const p0 = s0.pieces[0]
    const s1 = reducer(s0, { type: 'UPDATE_PIECE', piece: { ...p0, name: 'Renamed' } })
    const s2 = reducer(s1, { type: 'UPDATE_PIECE', piece: { ...s1.pieces[0], cutQty: 4 } })
    expect(s2.undoStack.length).toBe(s0.undoStack.length + 1)

    const s3 = reducer(s2, { type: 'UNDO' })
    expect(s3.pieces[0].name).toBe('Test Piece')
    expect(s3.pieces[0].cutQty).toBe(2)
  })

  it('starts a new undo entry after the selection changes', () => {
    const s0 = baseState()
    const s1 = reducer(s0, { type: 'UPDATE_PIECE', piece: { ...s0.pieces[0], name: 'First' } })
    const s2 = reducer(s1, { type: 'SELECT_PIECE', id: 'P1' })
    const s3 = reducer(s2, { type: 'UPDATE_PIECE', piece: { ...s2.pieces[0], name: 'Second' } })
    expect(s3.undoStack.length).toBe(s1.undoStack.length + 1)
  })
})

describe('drag gesture (LIVE_UPDATE_ELEMENTS + PUSH_UNDO)', () => {
  it('collapses a whole drag into a single undo entry restoring pre-drag state', () => {
    let s = baseState()
    const before = s.undoStack.length
    // Simulate 60 mousemove frames (would previously wipe the 50-slot stack)
    for (let i = 1; i <= 60; i++) {
      s = reducer(s, { type: 'LIVE_UPDATE_ELEMENTS', elements: [line('LOOSE', 20 + i, 20, 30 + i, 30)] })
    }
    s = reducer(s, { type: 'PUSH_UNDO' })
    expect(s.undoStack.length).toBe(before + 1)

    const undone = reducer(s, { type: 'UNDO' })
    const loose = undone.elements.find(e => e.id === 'LOOSE') as LineElement
    expect(loose.start.x).toBe(20)
  })

  it('pushes nothing for a click without movement', () => {
    const s0 = baseState()
    const s1 = reducer(s0, { type: 'PUSH_UNDO' })
    expect(s1.undoStack.length).toBe(s0.undoStack.length)
  })
})

describe('DELETE_ELEMENTS', () => {
  it('prunes connections referencing a deleted edge', () => {
    const s1 = reducer(baseState(), { type: 'DELETE_ELEMENTS', ids: ['L2'] })
    expect(s1.connections).toHaveLength(1)
    expect(s1.connections[0].label).toBe('hem')
  })
})

import type { Action } from '../context/EditorContext'
import type { EditorState } from '../types'

// The .psnap file format, written and read in one place so every save path
// (header Save, Ctrl+S) keeps the seams and placements the 3D view sews from.

export function toPsnap(state: Pick<EditorState, 'elements' | 'pieces' | 'measurements' | 'connections' | 'placements' | 'instructions' | 'lastFeatures' | 'lastMeasurements'>) {
  return {
    version: 1,
    elements: state.elements,
    pieces: state.pieces,
    measurements: state.measurements,
    connections: state.connections,
    placements: state.placements,
    ...(state.instructions ? { instructions: state.instructions } : {}),
    ...(state.lastFeatures ? { lastFeatures: state.lastFeatures } : {}),
    ...(state.lastMeasurements ? { lastMeasurements: state.lastMeasurements } : {}),
  }
}

export function downloadPsnap(data: ReturnType<typeof toPsnap>, filename = 'pattern.psnap'): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// Parses a .psnap document into a LOAD_STATE action; throws if it isn't one.
export function loadPsnapAction(json: string): Extract<Action, { type: 'LOAD_STATE' }> {
  const data = JSON.parse(json)
  if (!data.elements || !Array.isArray(data.elements)) throw new Error('Invalid .psnap file')
  return {
    type: 'LOAD_STATE',
    elements: data.elements,
    pieces: data.pieces ?? [],
    measurements: data.measurements ?? {},
    connections: data.connections ?? [],
    placements: data.placements ?? [],
    instructions: data.instructions ?? null,
    lastFeatures: data.lastFeatures ?? null,
    lastMeasurements: data.lastMeasurements ?? null,
  }
}

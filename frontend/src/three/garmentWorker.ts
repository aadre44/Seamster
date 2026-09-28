import { proceduralBodyQuery } from './bodyQuery'
import { placeGarment } from './garmentWrap'
import type { CanvasElement, PatternPiece } from '../types'
import type { ResolvedBody } from './types'

export interface GarmentJob { body: ResolvedBody; pieces: PatternPiece[]; elements: CanvasElement[] }

export interface GarmentCopyData { positions: Float32Array; indices: Uint32Array; ease: Float32Array }
export interface GarmentResult {
  pieces: { id: string; name: string; copies: GarmentCopyData[] }[]
  skipped: { id: string; name: string; reason: string }[]
  error?: string
}

// Wrapping a pattern onto the body takes up to a couple of seconds, so it runs
// off the UI thread (in its own worker, in parallel with body meshing).
self.onmessage = (e: MessageEvent<GarmentJob>) => {
  const worker = self as unknown as Worker
  try {
    const { placed, skipped } = placeGarment(e.data.pieces, e.data.elements, proceduralBodyQuery(e.data.body))
    const result: GarmentResult = {
      pieces: placed.map(p => ({ id: p.id, name: p.name, copies: p.copies })),
      skipped,
    }
    const transfer = placed.flatMap(p => p.copies.flatMap(c => [c.positions.buffer, c.indices.buffer, c.ease.buffer]))
    worker.postMessage(result, transfer)
  } catch (err) {
    const result: GarmentResult = { pieces: [], skipped: [], error: err instanceof Error ? err.message : String(err) }
    worker.postMessage(result)
  }
}

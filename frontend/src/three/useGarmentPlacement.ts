import { useEffect, useRef, useState } from 'react'
import type { CanvasElement, PatternPiece, Placement, SeamConnection } from '../types'
import type { GarmentJob, GarmentMessage, GarmentPieceData } from './garmentWorker'
import type { ResolvedBody } from './types'

export interface GarmentState {
  placementId: number // changes when the topology (pieces/copies) changes
  frame: number // changes whenever positions change
  pieces: GarmentPieceData[]
  skipped: { id: string; name: string; reason: string }[]
  draping: boolean
  error?: string
}

// Places (and drapes) the current pattern in a worker. Placement blocks the
// worker, so a new job is only sent once the previous one has been placed; a
// drape in progress is cancellable, so a newer job simply supersedes it.
export function useGarmentPlacement(
  body: ResolvedBody,
  pieces: PatternPiece[],
  elements: CanvasElement[],
  connections: SeamConnection[],
  placements: Placement[],
  enabled: boolean,
  drape: boolean,
): { result: GarmentState | null; busy: boolean } {
  const [result, setResult] = useState<GarmentState | null>(null)
  const [busy, setBusy] = useState(false)
  const state = useRef({
    worker: null as Worker | null,
    placing: false,
    nextId: 1,
    want: null as Omit<GarmentJob, 'id'> | null,
    sent: null as Omit<GarmentJob, 'id'> | null,
    runningId: 0,
  })

  const pump = () => {
    const s = state.current
    if (!s.worker || s.placing || !s.want || s.want === s.sent) return
    const id = s.nextId++
    s.placing = true
    s.sent = s.want
    s.runningId = id
    setBusy(true)
    s.worker.postMessage({ ...s.want, id } satisfies GarmentJob)
  }

  useEffect(() => {
    if (!enabled) return
    const worker = new Worker(new URL('./garmentWorker.ts', import.meta.url), { type: 'module' })
    const s = state.current
    s.worker = worker
    worker.onmessage = (e: MessageEvent<GarmentMessage>) => {
      const m = e.data
      if (m.kind === 'placed') s.placing = false
      if (m.id !== s.runningId) {
        pump()
        return
      }
      if (m.kind === 'placed') {
        setResult({ placementId: m.id, frame: 0, pieces: m.pieces, skipped: m.skipped, draping: !m.done })
      } else if (m.kind === 'frame') {
        setResult(r => r && r.placementId === m.id
          ? {
              ...r,
              frame: m.step,
              draping: !m.done,
              pieces: r.pieces.map((p, pi) => ({ ...p, copies: p.copies.map((c, ci) => ({ ...c, positions: m.positions[pi][ci] })) })),
            }
          : r)
      } else {
        s.placing = false
        setResult(r => (r ? { ...r, draping: false, error: m.error } : { placementId: m.id, frame: 0, pieces: [], skipped: [], draping: false, error: m.error }))
      }
      if (m.done && s.want === s.sent) setBusy(false)
      pump()
    }
    pump()
    return () => {
      worker.terminate()
      s.worker = null
      s.placing = false
      s.sent = null
      setBusy(false)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    state.current.want = { body, pieces, elements, connections, placements, drape }
    pump()
  }, [enabled, body, pieces, elements, connections, placements, drape])

  return { result: enabled ? result : null, busy }
}

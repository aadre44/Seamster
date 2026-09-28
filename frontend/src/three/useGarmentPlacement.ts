import { useEffect, useRef, useState } from 'react'
import type { CanvasElement, PatternPiece } from '../types'
import type { GarmentJob, GarmentResult } from './garmentWorker'
import type { ResolvedBody } from './types'

// Places the current pattern on the body in a worker. At most one job runs;
// when it finishes, the newest request (if it changed meanwhile) goes next.
export function useGarmentPlacement(
  body: ResolvedBody,
  pieces: PatternPiece[],
  elements: CanvasElement[],
  enabled: boolean,
): { result: GarmentResult | null; busy: boolean } {
  const [result, setResult] = useState<GarmentResult | null>(null)
  const [busy, setBusy] = useState(false)
  const state = useRef({
    worker: null as Worker | null,
    inFlight: false,
    want: null as GarmentJob | null,
    done: null as GarmentJob | null,
  })

  const pump = () => {
    const s = state.current
    if (!s.worker || s.inFlight || !s.want || s.want === s.done) return
    s.inFlight = true
    s.done = s.want
    setBusy(true)
    s.worker.postMessage(s.want)
  }

  useEffect(() => {
    if (!enabled) return
    const worker = new Worker(new URL('./garmentWorker.ts', import.meta.url), { type: 'module' })
    const s = state.current
    s.worker = worker
    worker.onmessage = (e: MessageEvent<GarmentResult>) => {
      s.inFlight = false
      setResult(e.data)
      if (s.want === s.done) setBusy(false)
      pump()
    }
    pump()
    return () => {
      worker.terminate()
      s.worker = null
      s.inFlight = false
      s.done = null
      setBusy(false)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    state.current.want = { body, pieces, elements }
    pump()
  }, [enabled, body, pieces, elements])

  return { result: enabled ? result : null, busy }
}

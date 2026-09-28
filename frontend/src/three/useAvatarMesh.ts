import { useEffect, useRef, useState } from 'react'
import { FINE_CELL, PREVIEW_CELL } from './avatarBuilder'
import type { AvatarJob, AvatarResult } from './avatarWorker'
import type { ResolvedBody } from './types'

// Keeps at most one mesh build in flight. For the newest body it first builds
// a coarse preview (fast feedback while a slider is dragged), then — only if
// the body is still current when that finishes — the full-resolution mesh.
export function useAvatarMesh(body: ResolvedBody): AvatarResult | null {
  const [mesh, setMesh] = useState<AvatarResult | null>(null)
  const state = useRef({
    worker: null as Worker | null,
    busy: false,
    want: body,
    inFlight: null as { body: ResolvedBody; cell: number } | null,
    previewDone: null as ResolvedBody | null,
    fineDone: null as ResolvedBody | null,
  })

  const pump = () => {
    const s = state.current
    if (!s.worker || s.busy || s.fineDone === s.want) return
    const cell = s.previewDone === s.want ? FINE_CELL : PREVIEW_CELL
    s.busy = true
    s.inFlight = { body: s.want, cell }
    const job: AvatarJob = { body: s.want, cell }
    s.worker.postMessage(job)
  }

  useEffect(() => {
    const worker = new Worker(new URL('./avatarWorker.ts', import.meta.url), { type: 'module' })
    const s = state.current
    s.worker = worker
    worker.onmessage = (e: MessageEvent<AvatarResult>) => {
      const done = s.inFlight!
      s.busy = false
      s.inFlight = null
      if (done.cell === PREVIEW_CELL) s.previewDone = done.body
      else s.fineDone = done.body
      setMesh(e.data)
      pump()
    }
    pump()
    return () => {
      worker.terminate()
      s.worker = null
      s.busy = false
      s.inFlight = null
    }
  }, [])

  useEffect(() => {
    state.current.want = body
    pump()
  }, [body])

  return mesh
}

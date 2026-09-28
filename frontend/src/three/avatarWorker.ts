import { buildAvatar } from './avatarBuilder'
import type { ResolvedBody } from './types'

export interface AvatarJob { body: ResolvedBody; cell: number }
export interface AvatarResult { positions: Float32Array; indices: Uint32Array }

// Meshing takes ~1 s at full resolution, so it runs off the UI thread.
self.onmessage = (e: MessageEvent<AvatarJob>) => {
  const mesh = buildAvatar(e.data.body, e.data.cell).parts[0]
  const result: AvatarResult = { positions: mesh.positions, indices: mesh.indices }
  ;(self as unknown as Worker).postMessage(result, [mesh.positions.buffer, mesh.indices.buffer])
}

import type { AvatarData, ResolvedBody } from './types'
import { armRings, legRings, torsoRings } from './bodyRegions'
import { buildBodySdf } from './bodySdf'
import { meshSdf } from './surfaceNets'

// Grid cell size (cm) for the final mesh and for the quick preview shown while
// a slider is being dragged.
export const FINE_CELL = 0.8
export const PREVIEW_CELL = 2.0

export function buildAvatar(body: ResolvedBody, cell = FINE_CELL): AvatarData {
  const { sdf, bounds } = buildBodySdf(body)
  return {
    parts: [meshSdf(sdf, bounds, cell, 'body')],
    landmarks: {
      torso: torsoRings(body),
      legRight: legRings(body, 1),
      legLeft: legRings(body, -1),
      armRight: armRings(body, 1),
      armLeft: armRings(body, -1),
    },
    height: body.height,
  }
}

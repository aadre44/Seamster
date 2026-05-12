import type { Point, CanvasElement } from '../types'

const SNAP_RADIUS_PX = 8

export type SnapResult = {
  point: Point
  kind: 'endpoint' | 'midpoint' | 'grid' | 'angle' | 'none'
}

/** Convert screen pixels to cm given the current scale (px/cm). */
export function screenToCm(screenX: number, screenY: number, pan: { x: number; y: number }, scale: number): Point {
  return {
    x: (screenX - pan.x) / scale,
    y: (screenY - pan.y) / scale,
  }
}

/** Convert cm to screen pixels. */
export function cmToScreen(cmX: number, cmY: number, pan: { x: number; y: number }, scale: number): Point {
  return {
    x: cmX * scale + pan.x,
    y: cmY * scale + pan.y,
  }
}

function dist2(a: Point, b: Point): number {
  return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
}

/** Find the best snap point for a cursor at screen position (sx, sy). */
export function snap(
  sx: number,
  sy: number,
  pan: { x: number; y: number },
  scale: number,
  elements: CanvasElement[],
  snapEnabled: boolean,
  shiftDown: boolean,
  anchorPoint?: Point, // for angle-snap
): SnapResult {
  const cursor = screenToCm(sx, sy, pan, scale)
  const snapRadiusCm = SNAP_RADIUS_PX / scale

  if (!snapEnabled) {
    return { point: cursor, kind: 'none' }
  }

  // Collect candidate snap points from elements
  const candidates: { point: Point; kind: SnapResult['kind'] }[] = []

  for (const el of elements) {
    if (el.type === 'line') {
      candidates.push({ point: el.start, kind: 'endpoint' })
      candidates.push({ point: el.end, kind: 'endpoint' })
      candidates.push({
        point: { x: (el.start.x + el.end.x) / 2, y: (el.start.y + el.end.y) / 2 },
        kind: 'midpoint',
      })
    } else if (el.type === 'curve') {
      candidates.push({ point: el.start, kind: 'endpoint' })
      candidates.push({ point: el.end, kind: 'endpoint' })
    } else if (el.type === 'anchor-point') {
      candidates.push({ point: el.position, kind: 'endpoint' })
    }
  }

  // Find closest endpoint/midpoint within snap radius
  let best: { point: Point; kind: SnapResult['kind'] } | null = null
  let bestDist2 = snapRadiusCm ** 2

  for (const c of candidates) {
    const d2 = dist2(cursor, c.point)
    if (d2 < bestDist2) {
      bestDist2 = d2
      best = c
    }
  }

  if (best) return { point: best.point, kind: best.kind }

  // Angle snap (Shift held + anchor point given)
  if (shiftDown && anchorPoint) {
    const angles = [0, 45, 90, 135, 180, 225, 270, 315]
    const dx = cursor.x - anchorPoint.x
    const dy = cursor.y - anchorPoint.y
    const len = Math.hypot(dx, dy)
    if (len > 0.01) {
      const angleDeg = (Math.atan2(dy, dx) * 180) / Math.PI
      const nearest = angles.reduce((a, b) =>
        Math.abs(((b - angleDeg + 540) % 360) - 180) < Math.abs(((a - angleDeg + 540) % 360) - 180) ? b : a
      )
      const rad = (nearest * Math.PI) / 180
      return {
        point: { x: anchorPoint.x + Math.cos(rad) * len, y: anchorPoint.y + Math.sin(rad) * len },
        kind: 'angle',
      }
    }
  }

  // Grid snap (0.5 cm intervals)
  const GRID_SNAP = 0.5
  return {
    point: {
      x: Math.round(cursor.x / GRID_SNAP) * GRID_SNAP,
      y: Math.round(cursor.y / GRID_SNAP) * GRID_SNAP,
    },
    kind: 'grid',
  }
}

/** Visual indicator colours per snap kind. */
export const SNAP_COLORS: Record<SnapResult['kind'], string> = {
  endpoint: '#ef4444',
  midpoint: '#f59e0b',
  grid: '#3b82f6',
  angle: '#8b5cf6',
  none: 'transparent',
}

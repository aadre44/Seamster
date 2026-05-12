import type { CanvasElement, PatternPiece, Point } from '../types'

export type TransformOp = 'flipH' | 'flipV' | 'rotate'

export function getPieceCentroid(piece: PatternPiece, elements: CanvasElement[]): Point {
  const idSet = new Set(piece.elementIds)
  const pts: Point[] = []
  for (const el of elements) {
    if (!idSet.has(el.id)) continue
    if (el.type === 'line' || el.type === 'curve') {
      pts.push(el.start, el.end)
    } else if (el.type === 'grain-line') {
      pts.push(el.start, el.end)
    } else if (el.type === 'notch') {
      pts.push(el.position)
    }
  }
  if (pts.length === 0) return { x: 0, y: 0 }
  return {
    x: pts.reduce((s, p) => s + p.x, 0) / pts.length,
    y: pts.reduce((s, p) => s + p.y, 0) / pts.length,
  }
}

function applyOp(p: Point, cx: number, cy: number, op: TransformOp, angleDeg: number): Point {
  if (op === 'flipH') return { x: 2 * cx - p.x, y: p.y }
  if (op === 'flipV') return { x: p.x, y: 2 * cy - p.y }
  const rad = (angleDeg * Math.PI) / 180
  const dx = p.x - cx
  const dy = p.y - cy
  return {
    x: cx + dx * Math.cos(rad) - dy * Math.sin(rad),
    y: cy + dx * Math.sin(rad) + dy * Math.cos(rad),
  }
}

function transformElement(
  el: CanvasElement,
  cx: number,
  cy: number,
  op: TransformOp,
  angleDeg: number,
): CanvasElement {
  const t = (p: Point) => applyOp(p, cx, cy, op, angleDeg)
  if (el.type === 'line') return { ...el, start: t(el.start), end: t(el.end) }
  if (el.type === 'curve') return { ...el, start: t(el.start), cp1: t(el.cp1), cp2: t(el.cp2), end: t(el.end) }
  if (el.type === 'grain-line') return { ...el, start: t(el.start), end: t(el.end) }
  if (el.type === 'notch') return { ...el, position: t(el.position) }
  return el
}

/** Returns updated copies of only the elements belonging to the piece. */
export function transformPieceElements(
  piece: PatternPiece,
  elements: CanvasElement[],
  op: TransformOp,
  angleDeg = 0,
): CanvasElement[] {
  const centroid = getPieceCentroid(piece, elements)
  const idSet = new Set(piece.elementIds)
  return elements
    .filter(el => idSet.has(el.id))
    .map(el => transformElement(el, centroid.x, centroid.y, op, angleDeg))
}

/**
 * Creates a mirrored copy of a piece and all its elements.
 * The original piece is unchanged; returns new elements + a new piece.
 */
export function mirrorPiece(
  piece: PatternPiece,
  elements: CanvasElement[],
  op: 'flipH' | 'flipV',
): { newElements: CanvasElement[]; newPiece: PatternPiece } {
  const centroid = getPieceCentroid(piece, elements)
  const idSet = new Set(piece.elementIds)
  const pieceEls = elements.filter(el => idSet.has(el.id))

  const stamp = Date.now()
  const idMap = new Map<string, string>(pieceEls.map((el, i) => [el.id, `${el.id}-m${stamp}-${i}`]))

  const t = (p: Point) => applyOp(p, centroid.x, centroid.y, op, 0)

  const newElements: CanvasElement[] = pieceEls.map(el => {
    const newId = idMap.get(el.id)!
    if (el.type === 'line')
      return { ...el, id: newId, start: t(el.start), end: t(el.end), pieceId: undefined }
    if (el.type === 'curve')
      return { ...el, id: newId, start: t(el.start), cp1: t(el.cp1), cp2: t(el.cp2), end: t(el.end), pieceId: undefined }
    if (el.type === 'grain-line')
      return { ...el, id: newId, start: t(el.start), end: t(el.end), pieceId: undefined }
    if (el.type === 'notch') {
      const mirroredAngle = op === 'flipH' ? -el.angle : 180 - el.angle
      return { ...el, id: newId, position: t(el.position), angle: mirroredAngle, pieceId: undefined }
    }
    // anchor-point (no angle to mirror)
    return { ...el, id: newId, position: t((el as any).position) } as CanvasElement
  })

  const newPieceId = `piece-m${stamp}`
  const newPiece: PatternPiece = {
    ...piece,
    id: newPieceId,
    name: `${piece.name} (mirrored)`,
    elementIds: newElements.map(el => el.id),
  }

  return { newElements, newPiece }
}

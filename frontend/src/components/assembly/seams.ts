import type { CanvasElement, PatternPiece, SeamConnection, SeamEnd } from '../../types'
import { isEdge, pieceEdges, sampleEdge } from './geometry'

// Seam bookkeeping for the Assembly view: readable names, sewn lengths and
// whether the two sides of a seam fit together.

export const LABEL_COLOURS: Record<string, string> = {
  side_seam: '#3b82f6',
  shoulder: '#8b5cf6',
  armhole: '#ec4899',
  waist: '#f59e0b',
  waist_seam: '#f59e0b',
  hem: '#10b981',
  inseam: '#06b6d4',
  crotch: '#ef4444',
  sleeve_seam: '#6366f1',
  neckline: '#f97316',
  wrist: '#84cc16',
  yoke_seam: '#a78bfa',
  back_sleeve_seam: '#6366f1',
  front_sleeve_seam: '#818cf8',
  center_front: '#d1d5db',
  center_back: '#d1d5db',
  center_sleeve: '#d1d5db',
}
export const DEFAULT_COLOUR = '#9ca3af'
export const FOLD_COLOUR = '#d1d5db'
export const labelColour = (label: string) => LABEL_COLOURS[label] ?? DEFAULT_COLOUR
export const prettyLabel = (label: string) => label.replace(/_/g, ' ')

// "side seam 2" when a piece has several edges with the same label.
export function edgeName(piece: PatternPiece | undefined, edgeId: string, byId: Map<string, CanvasElement>): string {
  if (!piece) return 'missing piece'
  const edges = pieceEdges(piece, byId)
  const el = edges.find(e => e.id === edgeId)
  if (!el) return 'missing edge'
  const label = el.seamLabel || (el.type === 'line' && el.isFold ? 'fold' : '')
  if (!label) return positionName(edges, el)
  const same = edges.filter(e => (e.seamLabel || (e.type === 'line' && e.isFold ? 'fold' : '')) === label)
  return same.length > 1 ? `${prettyLabel(label)} ${same.indexOf(el) + 1}` : prettyLabel(label)
}

// An unlabelled edge named by where it lies on the piece ("top edge"); a
// number is added only if two edges face the same way.
function positionName(edges: ReturnType<typeof pieceEdges>, el: ReturnType<typeof pieceEdges>[number]): string {
  const pts = edges.flatMap(e => [e.start, e.end])
  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length
  const facing = (e: typeof el) => {
    const mx = (e.start.x + e.end.x) / 2 - cx, my = (e.start.y + e.end.y) / 2 - cy
    return Math.abs(mx) > Math.abs(my) ? (mx > 0 ? 'right' : 'left') : (my > 0 ? 'bottom' : 'top')
  }
  const dir = facing(el)
  const same = edges.filter(e => !e.seamLabel && facing(e) === dir)
  return same.length > 1 ? `${dir} edge ${same.indexOf(el) + 1}` : `${dir} edge`
}

export function edgeLength(edgeId: string, byId: Map<string, CanvasElement>): number {
  const el = byId.get(edgeId)
  return isEdge(el) ? sampleEdge(el).length : 0
}

export function sewnLength(end: SeamEnd, byId: Map<string, CanvasElement>): number {
  const [lo, hi] = end.range ?? [0, 1]
  return edgeLength(end.edgeId, byId) * Math.abs(hi - lo)
}

// Sewing two lengths together: equal, eased (a little fullness worked in, as
// in a set-in sleeve cap), or a mismatch that will pucker or not reach.
export type Fit = 'match' | 'ease' | 'mismatch'

export function seamFit(c: SeamConnection, byId: Map<string, CanvasElement>): { delta: number; fit: Fit } {
  const a = sewnLength(c.from, byId)
  const b = sewnLength(c.to, byId)
  const delta = a - b
  const d = Math.abs(delta)
  const fit: Fit = d <= 0.3 ? 'match' : d <= Math.max(1, 0.05 * Math.max(a, b)) ? 'ease' : 'mismatch'
  return { delta, fit }
}

// Cut-2 and on-fold pieces are on both sides of the body, so a seam end can
// pick one side.
export const hasSides = (p: PatternPiece | undefined) => !!p && (p.cutQty >= 2 || p.onFold)

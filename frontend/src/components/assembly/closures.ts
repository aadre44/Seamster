import type { CanvasElement, CurveElement, LineElement, PatternPiece } from '../../types'
import { button, buttonhole } from '../../library/presets'
import { pieceEdges, sampleEdge } from './geometry'

// A row of buttons down a front, with the matching buttonholes on the other
// front — markings with a `side`, so the buttons are on one copy of the front
// piece and the holes on the other (menswear: buttons on the wearer's right,
// holes on the left).

export type Side = 'left' | 'right'

export interface ButtonRowOptions {
  count: number
  diameter: number // cm
  inset: number // cm in from the front edge (the button's centre)
  top: number // cm below the top of the front edge to the first button
  bottom: number // cm above the bottom of the front edge to the last
  buttonsOn: Side
  holes: 'vertical' | 'horizontal' | 'none'
}

export const DEFAULT_ROW: ButtonRowOptions = { count: 6, diameter: 1.1, inset: 1.5, top: 1.5, bottom: 12, buttonsOn: 'right', holes: 'vertical' }

const FRONT_EDGE = ['center_front', 'overlap_edge', 'underlap_edge']

// Pieces a button row can go on: a front with its front edge.
export const canButton = (p: PatternPiece, byId: Map<string, CanvasElement>) =>
  pieceEdges(p, byId).some(e => FRONT_EDGE.includes(e.seamLabel ?? ''))

// The button centres down the front edge, evenly spaced.
export function rowPoints(host: PatternPiece, byId: Map<string, CanvasElement>, o: Pick<ButtonRowOptions, 'count' | 'inset' | 'top' | 'bottom'>): { x: number; y: number }[] {
  const edges = pieceEdges(host, byId).filter(e => FRONT_EDGE.includes(e.seamLabel ?? ''))
  const pts = edges.flatMap(e => sampleEdge(e, 16).pts).sort((a, b) => a.y - b.y)
  if (pts.length < 2 || o.count < 1) return []
  const all = pieceEdges(host, byId).flatMap(e => [e.start, e.end])
  const midX = (Math.min(...all.map(p => p.x)) + Math.max(...all.map(p => p.x))) / 2
  const edgeX = (y: number) => {
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1]
      if (y >= a.y && y <= b.y) return b.y === a.y ? a.x : a.x + ((b.x - a.x) * (y - a.y)) / (b.y - a.y)
    }
    return pts[pts.length - 1].x
  }
  const y0 = pts[0].y + o.top, y1 = pts[pts.length - 1].y - o.bottom
  return Array.from({ length: o.count }, (_, i) => {
    const y = o.count === 1 ? y0 : y0 + ((y1 - y0) * i) / (o.count - 1)
    const x = edgeX(y)
    return { x: x + Math.sign(midX - x || 1) * o.inset, y }
  })
}

const moved = (e: CanvasElement, dx: number, dy: number): CanvasElement => {
  const m = (p: { x: number; y: number }) => ({ x: p.x + dx, y: p.y + dy })
  if (e.type === 'curve') return { ...e, start: m(e.start), end: m(e.end), cp1: m(e.cp1), cp2: m(e.cp2) }
  if (e.type === 'line') return { ...e, start: m(e.start), end: m(e.end) }
  return e
}

// The markings: buttons on one side, holes (if any) on the other.
export function buttonRow(host: PatternPiece, byId: Map<string, CanvasElement>, o: ButtonRowOptions): CanvasElement[] {
  const holesOn: Side = o.buttonsOn === 'right' ? 'left' : 'right'
  return rowPoints(host, byId, o).flatMap(p => [
    ...button(o.diameter).elements.map(e => ({ ...moved(e, p.x, p.y), pieceId: host.id, side: o.buttonsOn } as LineElement | CurveElement)),
    ...(o.holes === 'none' ? [] : buttonhole(o.diameter + 0.3, o.holes === 'vertical').elements
      .map(e => ({ ...moved(e, p.x, p.y), pieceId: host.id, side: holesOn } as LineElement | CurveElement))),
  ])
}

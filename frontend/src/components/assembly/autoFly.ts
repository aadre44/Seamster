import type { CanvasElement, PatternPiece, SeamConnection, SeamEnd } from '../../types'
import type { Edge, Pt } from './geometry'
import { pieceEdges, sampleEdge } from './geometry'

// A fly sewn the way it is constructed: the fly facing's straight edge along
// the front's centre front from the waist down (on the wearer's left by
// default), the fly shield the same on the other side, both inside the
// garment. Mirrors the backend rule (app/patterns/attachments.py _fly_rule) so
// it works on any pattern, offline, and on pieces with any name.

export type Side = 'left' | 'right'

export interface FlyPlan {
  host: string | null // front piece with a centre front and a waist
  facing: string | null
  shield: string | null
  facingSide: Side
}

const labelled = (p: PatternPiece, byId: Map<string, CanvasElement>, label: string) =>
  pieceEdges(p, byId).filter(e => e.seamLabel === label)

export function isFlyHost(p: PatternPiece, byId: Map<string, CanvasElement>): boolean {
  return labelled(p, byId, 'center_front').length > 0 && labelled(p, byId, 'waist').length > 0
}

// Prefilled from names: the facing, the shield, and a front leg (or skirt front).
export function guessFly(pieces: PatternPiece[], byId: Map<string, CanvasElement>): FlyPlan {
  const hosts = pieces.filter(p => isFlyHost(p, byId))
  const host = hosts.find(p => labelled(p, byId, 'inseam').length) ?? hosts[0] ?? null
  const facing = pieces.find(p => /\bfly\b/i.test(p.name) && /facing/i.test(p.name))
    ?? pieces.find(p => /\bfly\b/i.test(p.name) && !/shield/i.test(p.name)) ?? null
  const shield = pieces.find(p => /shield/i.test(p.name) && p !== facing) ?? null
  return { host: host?.id ?? null, facing: facing?.id ?? null, shield: shield?.id ?? null, facingSide: 'left' }
}

const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y)

interface Step { edge: Edge; forward: boolean; length: number }

// The front's centre-front edges, walked from the waist down.
function centreFrontPath(host: PatternPiece, byId: Map<string, CanvasElement>): Step[] {
  const cf = labelled(host, byId, 'center_front')
  const anchors = labelled(host, byId, 'waist').flatMap(e => [e.start, e.end])
  const ends = cf.flatMap(e => [e.start, e.end])
  const top = anchors.length
    ? ends.reduce((best, p) => (Math.min(...anchors.map(a => dist(a, p))) < Math.min(...anchors.map(a => dist(a, best))) ? p : best))
    : ends.reduce((best, p) => (p.y < best.y ? p : best))
  return cf
    .map(edge => ({ edge, near: Math.min(dist(edge.start, top), dist(edge.end, top)) }))
    .sort((a, b) => a.near - b.near)
    .map(({ edge }) => ({ edge, forward: dist(edge.start, top) <= dist(edge.end, top), length: sampleEdge(edge).length }))
}

// The trim edge sewn to the CF: its straight edge closest in length to the CF.
function flyEdge(trim: PatternPiece, byId: Map<string, CanvasElement>, cfLength: number): Edge | null {
  const edges = pieceEdges(trim, byId).filter(e => !(e.type === 'line' && e.isFold))
  const lines = edges.filter(e => e.type === 'line')
  const pool = lines.length ? lines : edges
  if (!pool.length) return null
  return pool.reduce((best, e) => (Math.abs(sampleEdge(e).length - cfLength) < Math.abs(sampleEdge(best).length - cfLength) ? e : best))
}

const end = (pieceId: string, edgeId: string, lo: number, hi: number, side?: Side): SeamEnd => {
  const e: SeamEnd = { pieceId, edgeId }
  const [a, b] = [Math.min(lo, hi), Math.max(lo, hi)]
  if (a > 1e-4 || b < 1 - 1e-4) e.range = [Math.round(a * 1e4) / 1e4, Math.round(b * 1e4) / 1e4]
  if (side) e.side = side
  return e
}

// Sews `trim`'s fly edge along the CF path from the waist, on `side`.
function sewFly(trim: PatternPiece, host: PatternPiece, byId: Map<string, CanvasElement>, side: Side): SeamConnection[] {
  const path = centreFrontPath(host, byId)
  const total = path.reduce((s, p) => s + p.length, 0)
  const edge = flyEdge(trim, byId, total)
  if (!edge || total <= 0) return []
  const trimLen = sampleEdge(edge).length
  const length = Math.min(trimLen, total)
  const walkDown = edge.start.y <= edge.end.y // trims are drafted upright: start at the top
  const out: SeamConnection[] = []
  let c0 = 0
  for (const step of path) {
    const c1 = c0 + step.length
    const a = c0, b = Math.min(length, c1)
    if (b - a > 0.05) {
      const u0 = (a - c0) / step.length, u1 = (b - c0) / step.length
      const [h0, h1] = step.forward ? [u0, u1] : [1 - u1, 1 - u0]
      const f0 = a / trimLen, f1 = b / trimLen // the trim edge from its top
      const [g0, g1] = walkDown ? [f0, f1] : [1 - f1, 1 - f0]
      out.push({
        label: 'fly',
        from: end(trim.id, edge.id, g0, g1),
        to: end(host.id, step.edge.id, h0, h1, side),
        reversed: step.forward !== walkDown,
        source: 'user',
      })
    }
    c0 = c1
    if (c0 >= length) break
  }
  return out
}

export function flySeams(plan: FlyPlan, pieces: PatternPiece[], byId: Map<string, CanvasElement>): SeamConnection[] {
  const byPiece = new Map(pieces.map(p => [p.id, p]))
  const host = plan.host ? byPiece.get(plan.host) : undefined
  if (!host) return []
  const other: Side = plan.facingSide === 'left' ? 'right' : 'left'
  const facing = plan.facing ? byPiece.get(plan.facing) : undefined
  const shield = plan.shield ? byPiece.get(plan.shield) : undefined
  return [
    ...(facing ? sewFly(facing, host, byId, plan.facingSide) : []),
    ...(shield ? sewFly(shield, host, byId, other) : []),
  ]
}

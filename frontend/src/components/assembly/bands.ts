import type { CanvasElement, PatternPiece, SeamConnection, SeamEnd } from '../../types'
import { classifyPiece, isTrimName } from '../../three/pieceClassifier'
import type { Edge } from './geometry'
import { pieceEdges, sampleEdge } from './geometry'

// A band sewn along an opening that runs across several pieces — a waistband
// round the front and back waist, a collar round the neckline, a hem band —
// is ONE edge of the band sewn to several edges in turn. So its seams must be
// consecutive stretches of the band edge, each as long as the edge it is sewn
// to, in order around the body:
//
//   one piece going all the way round (cut once):
//     R front (CF → side) → R back (side → CB) → L back (CB → side) → L front (side → CF)
//   a half (cut on the fold / cut 2): CF → side → CB, sewn on each side.
//
// A band longer than the opening keeps its extra length as an overlap at the
// end (not squashed to fit); a shorter one is eased along it. Mirrors the
// backend rule (app/patterns/attachments.py _around_rule).

type Side = 'left' | 'right'
const CENTRE = ['center_front', 'center_back', 'overlap_edge', 'underlap_edge']

interface Step { pieceId: string; edge: Edge; forward: boolean; side?: Side; half?: 'front' | 'back'; length: number }

const len = (e: Edge) => sampleEdge(e).length

function info(p: PatternPiece, byId: Map<string, CanvasElement>) {
  const edges = pieceEdges(p, byId)
  const labels = new Set(edges.map(e => e.seamLabel ?? '').filter(Boolean))
  if (edges.some(e => e.type === 'line' && e.isFold)) labels.add('fold')
  const cls = classifyPiece(p.name, labels)
  const centre = edges.filter(e => (e.type === 'line' && e.isFold) || CENTRE.includes(e.seamLabel ?? ''))
  const xs = edges.flatMap(e => [e.start.x, e.end.x])
  const cx = centre.length ? centre.flatMap(e => [e.start.x, e.end.x]).reduce((s, x) => s + x, 0) / (centre.length * 2) : Math.min(...xs)
  return { region: cls.region, back: cls.back, cx }
}

// A piece's edges from its centre line outward (each walked outward).
function outward(p: PatternPiece, edges: Edge[], byId: Map<string, CanvasElement>): Step[] {
  const { cx } = info(p, byId)
  const d = (x: number) => Math.abs(x - cx)
  return [...edges]
    .sort((a, b) => d((a.start.x + a.end.x) / 2) - d((b.start.x + b.end.x) / 2))
    .map(edge => ({ pieceId: p.id, edge, forward: d(edge.end.x) >= d(edge.start.x), length: len(edge) }))
}

const reverse = (steps: Step[], side?: Side): Step[] =>
  [...steps].reverse().map(s => ({ ...s, forward: !s.forward, side: side ?? s.side }))
const onSide = (steps: Step[], side: Side): Step[] => steps.map(s => ({ ...s, side }))

// The band's sewn edge: the one it is already sewn by, else the longest edge.
export function bandEdge(trim: PatternPiece, byId: Map<string, CanvasElement>, preferred?: string): Edge | null {
  const edges = pieceEdges(trim, byId).filter(e => !(e.type === 'line' && e.isFold))
  return edges.find(e => e.id === preferred) ?? (edges.length ? edges.reduce((a, e) => (len(e) > len(a) ? e : a)) : null)
}

// Seams sewing `trim`'s edge along `hosts` (edges of the garment), in order
// round the body. Null when the hosts don't make a path (e.g. no front or back).
export function bandSeams(
  trim: PatternPiece, trimEdge: Edge, hosts: { pieceId: string; edgeId: string }[],
  pieces: PatternPiece[], byId: Map<string, CanvasElement>,
): SeamConnection[] | null {
  const byPiece = new Map(pieces.map(p => [p.id, p]))
  const edgesOf = (pid: string) => hosts.filter(h => h.pieceId === pid).map(h => byId.get(h.edgeId)).filter((e): e is Edge => !!e && (e.type === 'line' || e.type === 'curve'))
  const hostPieces = [...new Set(hosts.map(h => h.pieceId))].map(id => byPiece.get(id)).filter((p): p is PatternPiece => !!p)
  if (!hostPieces.length) return null
  const L = len(trimEdge)
  const label = hosts.map(h => (byId.get(h.edgeId) as { seamLabel?: string } | undefined)?.seamLabel).find(Boolean) ?? 'band'

  let path: Step[]
  const sleeves = hostPieces.filter(p => info(p, byId).region === 'sleeve')
  if (sleeves.length) {
    // Round a sleeve (a cuff): its front half, then its back half when cut on the fold.
    const steps = sleeves.flatMap(s => edgesOf(s.id).map(edge => ({ pieceId: s.id, edge, forward: true, length: len(edge) })))
    const W = steps.reduce((a, s) => a + s.length, 0)
    path = sleeves.length === 1 && sleeves[0].onFold && L > 1.5 * W
      ? [...steps.map(s => ({ ...s, half: 'front' as const })), ...reverse(steps).map(s => ({ ...s, half: 'back' as const }))]
      : steps
  } else {
    const fronts = hostPieces.filter(p => !info(p, byId).back)
    const backs = hostPieces.filter(p => info(p, byId).back)
    const f = fronts.flatMap(p => outward(p, edgesOf(p.id), byId)) // CF → side
    const b = backs.flatMap(p => outward(p, edgesOf(p.id), byId)) // CB → side
    const half = [...f, ...reverse(b)] // CF → side → CB
    const H = half.reduce((a, s) => a + s.length, 0)
    // All the way round: longer than 1.5 × the half opening (a band cut twice is
    // two layers of one band, not a left and a right).
    const spansBoth = !trim.onFold && L > 1.5 * H && hostPieces.every(p => p.cutQty >= 2 || p.onFold)
    const startsAtBack = pieceEdges(trim, byId).some(e => e.type === 'line' && e.isFold) // a collar cut on the CB fold
    path = spansBoth
      ? [...onSide(f, 'right'), ...reverse(b, 'right'), ...onSide(b, 'left'), ...reverse(f, 'left')]
      : startsAtBack ? [...b, ...reverse(f)] : half
  }
  const P = path.reduce((a, s) => a + s.length, 0)
  if (P <= 0 || L <= 0) return null
  // Length-true when the band is longer (the rest is an overlap at its end);
  // eased along the opening when it is shorter.
  // An elastic or drawstring casing is gathered evenly along the opening.
  const gathered = /elastic|drawstring|gather/i.test(trim.name)
  const scale = L >= P && !gathered ? 1 / L : 1 / P
  const out: SeamConnection[] = []
  // A collar's extra length is its seam allowances, one at each end; a
  // waistband's is the overlap at its end.
  let at = L > P && !gathered && label === 'neckline' ? (L - P) / 2 : 0
  for (const s of path) {
    const lo = at * scale, hi = (at + s.length) * scale
    at += s.length
    const from: SeamEnd = { pieceId: trim.id, edgeId: trimEdge.id }
    if (lo > 1e-4 || hi < 1 - 1e-4) from.range = [Math.round(lo * 1e4) / 1e4, Math.round(Math.min(1, hi) * 1e4) / 1e4]
    const to: SeamEnd = { pieceId: s.pieceId, edgeId: s.edge.id }
    if (s.side) to.side = s.side
    if (s.half) to.half = s.half
    out.push({ label, from, to, reversed: !s.forward, source: 'user' })
  }
  return out
}

export type Opening = 'waist' | 'neckline' | 'hem' | 'wrist'

// Every edge of the garment (not its trims) along an opening; the waist also
// takes a skirt's or trousers' waist seam (not a bodice's).
export function openingEdges(pieces: PatternPiece[], byId: Map<string, CanvasElement>, opening: Opening): { pieceId: string; edgeId: string }[] {
  return pieces.filter(p => !isTrimName(p.name)).flatMap(p => pieceEdges(p, byId)
    .filter(e => e.seamLabel === opening || (opening === 'waist' && e.seamLabel === 'waist_seam' && !/bodice/i.test(p.name)))
    .map(e => ({ pieceId: p.id, edgeId: e.id })))
}

// A trim edge sewn whole to two or more edges of other pieces (e.g. a
// waistband clicked onto the front waist, then the back waist) is re-made as a
// band: consecutive stretches in order round the body. Other seams untouched.
export function normalizeBands(connections: SeamConnection[], pieces: PatternPiece[], elements: CanvasElement[]): SeamConnection[] {
  const byId = new Map(elements.map(e => [e.id, e]))
  const byPiece = new Map(pieces.map(p => [p.id, p]))
  const groups = new Map<string, { trim: PatternPiece; edgeId: string; seams: number[]; hosts: { pieceId: string; edgeId: string }[] }>()
  connections.forEach((c, i) => {
    for (const [mine, other] of [[c.from, c.to], [c.to, c.from]] as const) {
      const trim = byPiece.get(mine.pieceId)
      if (!trim || !isTrimName(trim.name) || mine.range || other.pieceId === mine.pieceId) continue
      if (isTrimName(byPiece.get(other.pieceId)?.name ?? '')) continue
      const key = `${mine.pieceId}|${mine.edgeId}`
      const g = groups.get(key) ?? { trim, edgeId: mine.edgeId, seams: [], hosts: [] }
      g.seams.push(i)
      g.hosts.push({ pieceId: other.pieceId, edgeId: other.edgeId })
      groups.set(key, g)
    }
  })
  let out = connections
  for (const g of groups.values()) {
    if (new Set(g.hosts.map(h => `${h.pieceId}|${h.edgeId}`)).size < 2) continue
    const edge = bandEdge(g.trim, byId, g.edgeId)
    const seams = edge && bandSeams(g.trim, edge, g.hosts, pieces, byId)
    if (!seams) continue
    const drop = new Set(g.seams.map(i => connections[i]))
    out = [...out.filter(c => !drop.has(c)), ...seams]
  }
  return out
}

import type { CanvasElement, PatternPiece, SeamConnection } from '../../types'
import { classifyPiece } from '../../three/pieceClassifier'
import type { Affine, Pt } from './geometry'
import { IDENTITY, alignToNeighbour, apply, compose, insidePolygon, pieceBBox, pieceEdges, sampleEdge } from './geometry'

// The whole garment laid out the way it is worn: every cut copy (a left and a
// right front leg, a left and a right back leg…), unrolled around the body as
// if cut down the centre back — R back | R front | L front | L back — each
// piece next to the one it is sewn to, a small gap apart. Shared by the
// Assembly view and the 3D drape (a pocket placed across two panels is mapped
// onto each through this layout). Pure geometry, no React.
//
//  - Rows: upper torso (bodice, shirt) above lower torso / legs (skirt,
//    trousers); a dress's bodice row sits over its skirt row.
//  - In a row, a chain from the centre piece (CF, or CB when centred on the
//    back) outward, each piece aligned to the previous one along the seam
//    between them (the side seam, not the inseam) and pushed GAP away. That is
//    one side; the other side is its mirror image about the centre line.
//  - Sleeves: unfolded (front and back half) above their side, cap down.
//  - Everything else (trims, unattached pieces) in a tray row underneath.
//
// Sides are the wearer's. Centred on the front, the wearer's right is on the
// left of the layout (as you look at someone); centred on the back, on the right.

export type Side = 'left' | 'right'
export type Half = 'front' | 'back'

export interface CopyRef {
  key: string
  pieceId: string
  side: Side | null // null: a piece shown once (tray)
  half?: Half // sleeves cut on the fold
  role: 'shell' | 'sleeve' | 'tray'
}

export interface GarmentLayout {
  copies: CopyRef[]
  transforms: Map<string, Affine> // copy key → piece canvas coords to layout cm
  outlines: Map<string, Pt[]> // copy key → outline polygon in layout cm
  copyAt: (p: Pt, maxGap?: number) => CopyRef | null
}

export const LAYOUT_GAP = 1.2 // cm between pieces that are sewn together

export const copyKey = (pieceId: string, side: Side | null, half?: Half) =>
  `${pieceId}#${side ?? 'tray'}${half ? `-${half}` : ''}`

const MIRROR_X: Affine = { a: -1, b: 0, c: 0, d: 1, tx: 0, ty: 0 }
const MIRROR_Y: Affine = { a: 1, b: 0, c: 0, d: -1, tx: 0, ty: 0 }
const translate = (tx: number, ty: number): Affine => ({ ...IDENTITY, tx, ty })
const CENTRE_LABELS = ['center_front', 'center_back', 'overlap_edge', 'underlap_edge']

interface Info { piece: PatternPiece; region: string; back: boolean; labels: Set<string> }

// Outline polygon of a piece through a transform.
function polygon(piece: PatternPiece, byId: Map<string, CanvasElement>, t: Affine): Pt[] {
  return pieceEdges(piece, byId).flatMap(e => sampleEdge(e, 16).pts.map(p => apply(t, p)))
}

function bounds(pts: Pt[]) {
  return {
    minX: Math.min(...pts.map(p => p.x)), maxX: Math.max(...pts.map(p => p.x)),
    minY: Math.min(...pts.map(p => p.y)), maxY: Math.max(...pts.map(p => p.y)),
  }
}

// The piece placed with its centre line (CF / CB / fold) on x = 0 and the rest
// of it to the right, top at y = 0.
function atCentre(piece: PatternPiece, byId: Map<string, CanvasElement>): Affine {
  const edges = pieceEdges(piece, byId)
  const centre = edges.filter(e => (e.type === 'line' && e.isFold) || CENTRE_LABELS.includes(e.seamLabel ?? ''))
  const b = pieceBBox(piece, byId)
  const cx = centre.length ? centre.flatMap(e => [e.start.x, e.end.x]).reduce((s, x) => s + x, 0) / (centre.length * 2) : b.minX
  const mirrored = cx > (b.minX + b.maxX) / 2 // drawn with the centre on the right: flip it
  return mirrored ? compose(translate(cx, -b.minY), MIRROR_X) : translate(-cx, -b.minY)
}

// Seams to lay two neighbours open along: their side seam(s), or any
// construction seam except the inseam / crotch (a trouser leg's front and back
// share both the side seam and the inseam; around the body it opens at the side).
function ringSeams(between: SeamConnection[]): SeamConnection[] {
  const side = between.filter(c => c.label === 'side_seam')
  return side.length ? side : between.filter(c => !['inseam', 'crotch', 'center_front', 'center_back'].includes(c.label))
}

export function garmentLayout(
  pieces: PatternPiece[],
  elements: CanvasElement[],
  connections: SeamConnection[],
  opts: { centre?: 'front' | 'back'; exclude?: Set<string> } = {},
): GarmentLayout {
  const centre = opts.centre ?? 'front'
  const byId = new Map(elements.map(e => [e.id, e]))
  const infos: Info[] = pieces.filter(p => !opts.exclude?.has(p.id)).map(piece => {
    const edges = pieceEdges(piece, byId)
    const labels = new Set(edges.map(e => e.seamLabel ?? '').filter(Boolean))
    if (edges.some(e => e.type === 'line' && e.isFold)) labels.add('fold')
    const cls = classifyPiece(piece.name, labels)
    return { piece, region: cls.region, back: cls.back, labels }
  })
  const between = (a: string, b: string) => connections.filter(c =>
    (c.from.pieceId === a && c.to.pieceId === b) || (c.from.pieceId === b && c.to.pieceId === a))

  const copies: CopyRef[] = []
  const transforms = new Map<string, Affine>()
  const add = (piece: PatternPiece, side: Side | null, role: CopyRef['role'], t: Affine, half?: Half) => {
    const key = copyKey(piece.id, side, half)
    copies.push({ key, pieceId: piece.id, side, half, role })
    transforms.set(key, t)
  }
  // One side's chain goes to the right of the centre line; which side that is
  // depends on whether we look at the front or the back.
  const rightOfCentre: Side = centre === 'front' ? 'left' : 'right'
  const leftOfCentre: Side = rightOfCentre === 'left' ? 'right' : 'left'
  const sidesOf = (p: PatternPiece): Side[] => (p.cutQty >= 2 || p.onFold ? [rightOfCentre, leftOfCentre] : [rightOfCentre])

  const placedInRing = new Set<string>()
  let top = 0
  const rows = [infos.filter(i => i.region === 'torso-upper'), infos.filter(i => i.region === 'torso-lower' || i.region === 'leg')]
  let armholeX: number | null = null // where the upper row's side seam starts (for the sleeves)
  let upperTop: number | null = null
  for (const row of rows) {
    if (!row.length) continue
    const wantBack = centre === 'back'
    const hasCentre = (i: Info) => i.labels.has('fold') || CENTRE_LABELS.some(l => i.labels.has(l))
    const start = row.find(i => i.back === wantBack && hasCentre(i)) ?? row.find(i => i.back === wantBack) ?? row[0]
    // Chain outward from the centre piece (one side, drafted orientation).
    const chain = new Map<string, Affine>([[start.piece.id, atCentre(start.piece, byId)]])
    for (let current = start; ;) {
      const next = row.find(i => !chain.has(i.piece.id) && ringSeams(between(current.piece.id, i.piece.id)).length)
      if (!next) break
      let t = alignToNeighbour(chain.get(current.piece.id)!, current.piece, next.piece,
        ringSeams(between(current.piece.id, next.piece.id)), byId, LAYOUT_GAP)
      if (!t) break
      // Seams that curve differently (a back leg's hip curve against the front's)
      // can still cross once their ends meet: ease the new piece away until clear.
      const here = polygon(current.piece, byId, chain.get(current.piece.id)!)
      const c0 = bounds(here)
      for (let k = 0; k < 20; k++) {
        const there = polygon(next.piece, byId, t)
        if (!there.some(q => insidePolygon(here, q)) && !here.some(q => insidePolygon(there, q))) break
        const c1 = bounds(there)
        const dx = (c1.minX + c1.maxX - c0.minX - c0.maxX) / 2, dy = (c1.minY + c1.maxY - c0.minY - c0.maxY) / 2
        const l = Math.hypot(dx, dy) || 1
        t = { ...t, tx: t.tx + (dx / l) * 0.5, ty: t.ty + (dy / l) * 0.5 }
      }
      chain.set(next.piece.id, t)
      current = next
    }
    // Unchained pieces of the row continue to the right.
    for (const i of row) {
      if (chain.has(i.piece.id)) continue
      const right = Math.max(...[...chain].flatMap(([id, t]) => polygon(pieces.find(p => p.id === id)!, byId, t).map(p => p.x)))
      chain.set(i.piece.id, compose(translate(right + 4 * LAYOUT_GAP, 0), atCentre(i.piece, byId)))
    }
    // Row placement: half a gap off the centre line, below the previous row. A
    // piece reaching past the centre line (a trouser front's crotch extension)
    // would overlap its mirror image, so that side moves out just clear of it —
    // the two legs' inseams then meet in the middle.
    const all = [...chain].flatMap(([id, t]) => polygon(pieces.find(p => p.id === id)!, byId, t))
    const b = bounds(all)
    const shift = translate(LAYOUT_GAP / 2 + Math.max(0, -b.minX), top - b.minY)
    if (upperTop === null) upperTop = top
    for (const [id, t] of chain) {
      const piece = pieces.find(p => p.id === id)!
      const placed = compose(shift, t)
      for (const side of sidesOf(piece)) {
        add(piece, side, 'shell', side === rightOfCentre ? placed : compose(MIRROR_X, placed))
      }
      placedInRing.add(id)
    }
    if (armholeX === null) {
      const junction = row.find(i => i.back !== wantBack)
      if (junction) {
        const pts = polygon(junction.piece, byId, compose(shift, chain.get(junction.piece.id)!))
        armholeX = bounds(pts).minX - LAYOUT_GAP / 2
      }
    }
    top = b.maxY - b.minY + top + 6 * LAYOUT_GAP
  }

  // Sleeves: the whole sleeve (both halves of an on-fold piece) above its side,
  // cap down toward the armhole.
  const sleeves = infos.filter(i => i.region === 'sleeve')
  let sleeveTop = upperTop ?? 0
  for (const s of sleeves) {
    const base = compose(MIRROR_Y, atCentre(s.piece, byId)) // fold on x = 0, cap at the bottom
    const pts = polygon(s.piece, byId, base)
    const bb = bounds(pts)
    const x = armholeX ?? 0
    const lift = translate(x, (sleeveTop - 4 * LAYOUT_GAP) - bb.maxY)
    const halves: { half?: Half; t: Affine }[] = s.piece.onFold
      ? [{ half: 'back', t: compose(lift, base) }, { half: 'front', t: compose(lift, compose(MIRROR_X, base)) }]
      : [{ t: compose(lift, base) }]
    for (const side of sidesOf(s.piece)) {
      for (const h of halves) {
        const t = side === rightOfCentre ? h.t : compose(MIRROR_X, h.t)
        add(s.piece, side, 'sleeve', t, h.half)
      }
    }
    placedInRing.add(s.piece.id)
    sleeveTop = sleeveTop - (bb.maxY - bb.minY) - 4 * LAYOUT_GAP
  }

  // Tray: the rest, left to right under the garment, drafted orientation.
  const ringBounds = copies.length ? bounds([...transforms].flatMap(([k, t]) => polygon(pieces.find(p => p.id === k.split('#')[0])!, byId, t))) : null
  let x = ringBounds ? ringBounds.minX : 0
  const trayTop = (ringBounds ? ringBounds.maxY : 0) + 8 * LAYOUT_GAP
  const rightEdge = ringBounds ? Math.max(ringBounds.maxX, ringBounds.minX + 80) : 120
  let y = trayTop, rowH = 0
  for (const i of infos) {
    if (placedInRing.has(i.piece.id)) continue
    const b = pieceBBox(i.piece, byId)
    const w = b.maxX - b.minX, h = b.maxY - b.minY
    if (x > (ringBounds?.minX ?? 0) && x + w > rightEdge) { x = ringBounds?.minX ?? 0; y += rowH + 4 * LAYOUT_GAP; rowH = 0 }
    add(i.piece, null, 'tray', translate(x - b.minX, y - b.minY))
    x += w + 4 * LAYOUT_GAP
    rowH = Math.max(rowH, h)
  }

  const outlines = new Map(copies.map(c => [c.key, polygon(pieces.find(p => p.id === c.pieceId)!, byId, transforms.get(c.key)!)]))
  const garment = copies.filter(c => c.role !== 'tray')
  const copyAt = (p: Pt, maxGap = LAYOUT_GAP * 1.5): CopyRef | null => {
    const hit = garment.find(c => insidePolygon(outlines.get(c.key)!, p))
    if (hit) return hit
    // In the gap between two sewn pieces: the nearer one.
    let best: CopyRef | null = null, bd = maxGap
    for (const c of garment) {
      const poly = outlines.get(c.key)!
      for (let i = 0; i < poly.length; i++) {
        const a = poly[i], b = poly[(i + 1) % poly.length]
        const dx = b.x - a.x, dy = b.y - a.y
        const l2 = dx * dx + dy * dy
        const u = l2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0
        const d = Math.hypot(a.x + dx * u - p.x, a.y + dy * u - p.y)
        if (d < bd) { bd = d; best = c }
      }
    }
    return best
  }
  return { copies, transforms, outlines, copyAt }
}

import type { CanvasElement, CurveElement, LineElement, PatternPiece, Point } from '../types'

// Ready-made pieces and markings the user drags onto the canvas: pockets in
// common shapes and sizes, collars, cuffs, waistbands, plackets, flaps, belt
// loops, ties, buttons and buttonholes. Pieces carry the same names and edge
// labels as generated trims (a collar's sewn edge is "neckline", a cuff's
// "wrist"…), so Assembly's Re-infer and the 3D view attach them like the
// generator's own. Collars, cuffs and waistbands size themselves to the
// pattern's neckline, wrist or waist when it has one.

export type PresetCategory = 'Pockets' | 'Collars' | 'Cuffs & bands' | 'Plackets & flaps' | 'Buttons'

export interface PresetContext {
  neck: number | null // whole neckline length of the current pattern (cm)
  waist: number | null // whole waist edge length
  wrist: number | null // one sleeve's wrist length
  measurements: Record<string, number>
}

export interface PresetResult {
  elements: CanvasElement[]
  piece?: Omit<PatternPiece, 'elementIds'> & { elementIds?: string[] } // absent → a marking, placed on the piece under it
}

export interface Preset {
  id: string
  category: PresetCategory
  name: string
  detail: string // size / what it fits
  make: (ctx: PresetContext) => PresetResult
}

let seq = 0
const uid = (kind: string) => `${kind}-${Date.now().toString(36)}-${(++seq).toString(36)}`
const P = (x: number, y: number): Point => ({ x, y })
const KAPPA = 0.5523

type Seg =
  | { to: Point; label?: string; fold?: boolean }
  | { to: Point; cp1: Point; cp2: Point; label?: string }

// A closed outline from a start point and segments, as canvas elements.
function outline(start: Point, segs: Seg[], pieceId: string): (LineElement | CurveElement)[] {
  let at = start
  return segs.map(s => {
    const base = { id: uid('el'), start: at, end: s.to, pieceId, ...('label' in s && s.label ? { seamLabel: s.label } : {}) }
    at = s.to
    return 'cp1' in s
      ? { ...base, type: 'curve' as const, cp1: s.cp1, cp2: s.cp2 }
      : { ...base, type: 'line' as const, isFold: !!s.fold }
  })
}

function grain(pieceId: string, a: Point, b: Point): CanvasElement {
  return { id: uid('el'), type: 'grain-line', start: a, end: b, pieceId }
}

// Centres the geometry on (0, 0) so the canvas can drop it under the pointer.
function centred(r: PresetResult): PresetResult {
  const pts = r.elements.flatMap(e => ('start' in e ? [e.start, e.end] : []))
  const cx = (Math.min(...pts.map(p => p.x)) + Math.max(...pts.map(p => p.x))) / 2
  const cy = (Math.min(...pts.map(p => p.y)) + Math.max(...pts.map(p => p.y))) / 2
  const m = (p: Point) => P(p.x - cx, p.y - cy)
  return {
    ...r,
    elements: r.elements.map(e => {
      if (e.type === 'curve') return { ...e, start: m(e.start), end: m(e.end), cp1: m(e.cp1), cp2: m(e.cp2) }
      if (e.type === 'line' || e.type === 'grain-line') return { ...e, start: m(e.start), end: m(e.end) }
      return e
    }),
  }
}

function piece(name: string, segs: Seg[], start: Point, opts: { cutQty?: number; onFold?: boolean; grainV?: boolean } = {}): PresetResult {
  const id = uid('piece')
  const edges = outline(start, segs, id)
  const xs = edges.flatMap(e => [e.start.x, e.end.x]), ys = edges.flatMap(e => [e.start.y, e.end.y])
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const g = opts.grainV === false
    ? grain(id, P(x0 + (x1 - x0) * 0.2, (y0 + y1) / 2), P(x0 + (x1 - x0) * 0.8, (y0 + y1) / 2))
    : grain(id, P((x0 + x1) / 2, y0 + (y1 - y0) * 0.2), P((x0 + x1) / 2, y0 + (y1 - y0) * 0.8))
  return centred({
    elements: [...edges, g],
    piece: { id, name, cutQty: opts.cutQty ?? 1, onFold: !!opts.onFold, seamAllowance: 1.5, closed: true, elementIds: edges.map(e => e.id), source: 'library' },
  })
}

// ── Pockets ──────────────────────────────────────────────────────────────────

type PocketShape = 'square' | 'rounded' | 'pointed' | 'angled' | 'curved'

// Top edge (the mouth) first, then clockwise. `c` = corner size.
function pocket(name: string, w: number, h: number, shape: PocketShape, cutQty: number, c = 2.5): PresetResult {
  const top: Seg = { to: P(w, 0), label: 'pocket_opening' }
  const bottom: Seg[] = {
    square: [{ to: P(w, h) }, { to: P(0, h) }],
    rounded: [
      { to: P(w, h - c) },
      { to: P(w - c, h), cp1: P(w, h - c + c * KAPPA), cp2: P(w - c + c * KAPPA, h) },
      { to: P(c, h) },
      { to: P(0, h - c), cp1: P(c - c * KAPPA, h), cp2: P(0, h - c + c * KAPPA) },
    ],
    pointed: [{ to: P(w, h - c) }, { to: P(w / 2, h) }, { to: P(0, h - c) }],
    angled: [{ to: P(w, h - c) }, { to: P(w - c, h) }, { to: P(c, h) }, { to: P(0, h - c) }],
    curved: [{ to: P(w, h - w / 2) }, { to: P(0, h - w / 2), cp1: P(w, h + w * 0.16), cp2: P(0, h + w * 0.16) }],
  }[shape] as Seg[]
  return piece(name, [top, ...bottom, { to: P(0, 0) }], P(0, 0), { cutQty })
}

// ── Collars / bands ──────────────────────────────────────────────────────────

const neckOf = (ctx: PresetContext) => ctx.neck ?? 40
const waistOf = (ctx: PresetContext) => ctx.waist ?? ctx.measurements.waist ?? 74
const wristOf = (ctx: PresetContext) => ctx.wrist ?? 22

function band(name: string, len: number, h: number, label: string, cutQty = 1): PresetResult {
  return piece(name, [{ to: P(len, 0), label }, { to: P(len, h) }, { to: P(0, h) }, { to: P(0, 0) }], P(0, 0), { cutQty, grainV: false })
}

function pointCollar(L: number): PresetResult {
  // Neck edge along the bottom, points flaring out at the collar ends.
  return piece('Shirt Collar', [
    { to: P(L, 0), label: 'neckline' },
    { to: P(L + 1.8, -7.5) },
    { to: P(-1.8, -7.5), cp1: P(L * 0.7, -6.8), cp2: P(L * 0.3, -6.8) },
    { to: P(0, 0) },
  ], P(0, 0), { cutQty: 2, grainV: false })
}

function peterPan(L: number): PresetResult {
  // Half a flat collar cut on the CB fold: the neck edge is a quarter circle
  // of the half-neckline's length, 6 cm wide, rounded at the front.
  const half = L / 2
  const r = half / (Math.PI / 2)
  const R = r + 6
  const k = KAPPA
  return piece('Peter Pan Collar', [
    { to: P(0, -R), fold: true }, // CB fold (from the neck point up to the outer edge)
    { to: P(R * 0.95, 0), cp1: P(R * k, -R), cp2: P(R * 0.95, -R * k) }, // outer edge
    { to: P(r, 0), cp1: P(R * 0.95, 4), cp2: P(r + 1, 4) }, // rounded front
    { to: P(0, -r), cp1: P(r, -r * k), cp2: P(r * k, -r), label: 'neckline' }, // neck edge back to CB
  ], P(0, -r), { onFold: true })
}

// ── Markings ─────────────────────────────────────────────────────────────────

export function button(d: number): PresetResult {
  const r = d / 2, k = r * KAPPA
  const q = (a: Point, c1: Point, c2: Point, b: Point): CurveElement => ({ id: uid('el'), type: 'curve', start: a, cp1: c1, cp2: c2, end: b, seamLabel: 'button' })
  return {
    elements: [
      q(P(r, 0), P(r, k), P(k, r), P(0, r)),
      q(P(0, r), P(-k, r), P(-r, k), P(-r, 0)),
      q(P(-r, 0), P(-r, -k), P(-k, -r), P(0, -r)),
      q(P(0, -r), P(k, -r), P(r, -k), P(r, 0)),
    ],
  }
}

export function buttonhole(len: number, vertical: boolean): PresetResult {
  const a = vertical ? P(0, -len / 2) : P(-len / 2, 0)
  const b = vertical ? P(0, len / 2) : P(len / 2, 0)
  return { elements: [{ id: uid('el'), type: 'line', start: a, end: b, isFold: false, seamLabel: 'buttonhole' }] }
}

const fits = (v: number | null, what: string) => (v ? `fits your ${what}` : `standard ${what}`)

export const PRESETS: Preset[] = [
  { id: 'pocket-chest', category: 'Pockets', name: 'Chest pocket', detail: '11 × 13 cm, square', make: () => pocket('Chest Patch Pocket', 11, 13, 'square', 1) },
  { id: 'pocket-rounded', category: 'Pockets', name: 'Patch pocket', detail: '15 × 16 cm, rounded', make: () => pocket('Patch Pocket', 15, 16, 'rounded', 2) },
  { id: 'pocket-jeans', category: 'Pockets', name: 'Jeans back pocket', detail: '14 × 15 cm, pointed', make: () => pocket('Back Pocket', 14, 15, 'pointed', 2, 2) },
  { id: 'pocket-angled', category: 'Pockets', name: 'Angled pocket', detail: '15 × 16 cm, chamfered', make: () => pocket('Patch Pocket', 15, 16, 'angled', 2) },
  { id: 'pocket-curved', category: 'Pockets', name: 'Curved pocket', detail: '15 × 17 cm, U-shaped', make: () => pocket('Patch Pocket', 15, 17, 'curved', 2) },
  { id: 'pocket-cargo', category: 'Pockets', name: 'Cargo pocket', detail: '18 × 20 cm, square', make: () => pocket('Cargo Pocket', 18, 20, 'square', 2) },
  { id: 'pocket-bag', category: 'Pockets', name: 'In-seam pocket bag', detail: '16 × 20 cm', make: () => pocket('Side Pocket Bag', 16, 20, 'rounded', 2, 4) },

  { id: 'collar-stand', category: 'Collars', name: 'Stand collar', detail: '', make: ctx => band('Collar', neckOf(ctx) + 3, 4, 'neckline', 2) },
  { id: 'collar-shirt', category: 'Collars', name: 'Shirt collar', detail: '', make: ctx => pointCollar(neckOf(ctx) + 3) },
  { id: 'collar-mandarin', category: 'Collars', name: 'Mandarin collar', detail: '', make: ctx => band('Mandarin Collar', neckOf(ctx) + 3, 3.5, 'neckline', 2) },
  { id: 'collar-peterpan', category: 'Collars', name: 'Peter Pan collar', detail: '', make: ctx => peterPan(neckOf(ctx)) },

  { id: 'cuff-shirt', category: 'Cuffs & bands', name: 'Shirt cuff', detail: '', make: ctx => band('Cuff', wristOf(ctx) + 2, 6, 'wrist', 2) },
  { id: 'cuff-band', category: 'Cuffs & bands', name: 'Sleeve band', detail: 'folded, 4 cm', make: ctx => band('Sleeve Band', wristOf(ctx), 8, 'wrist', 2) },
  { id: 'waistband', category: 'Cuffs & bands', name: 'Waistband', detail: 'folded, 4 cm', make: ctx => band('Waistband', waistOf(ctx) + 4, 8, 'waist') },

  { id: 'placket', category: 'Plackets & flaps', name: 'Button placket', detail: '4 × 40 cm', make: () => band('Button Placket', 4, 40, '', 1) },
  { id: 'flap', category: 'Plackets & flaps', name: 'Pocket flap', detail: '15 × 6 cm, pointed', make: () => piece('Pocket Flap', [{ to: P(15, 0), label: 'pocket_opening' }, { to: P(15, 4) }, { to: P(7.5, 6) }, { to: P(0, 4) }, { to: P(0, 0) }], P(0, 0), { cutQty: 2 }) },
  { id: 'welt', category: 'Plackets & flaps', name: 'Welt', detail: '14 × 2 cm', make: () => band('Welt Strip', 14, 2, '', 2) },
  { id: 'belt-loop', category: 'Plackets & flaps', name: 'Belt loop', detail: '1.2 × 8 cm', make: () => band('Belt Loop', 1.2, 8, '', 5) },
  { id: 'tie', category: 'Plackets & flaps', name: 'Tie / sash', detail: '5 × 80 cm', make: () => band('Tie', 80, 5, '', 2) },

  { id: 'button-11', category: 'Buttons', name: 'Shirt button', detail: '11 mm', make: () => button(1.1) },
  { id: 'button-15', category: 'Buttons', name: 'Button', detail: '15 mm', make: () => button(1.5) },
  { id: 'button-20', category: 'Buttons', name: 'Coat button', detail: '20 mm', make: () => button(2.0) },
  { id: 'buttonhole-h', category: 'Buttons', name: 'Buttonhole', detail: '1.8 cm, horizontal', make: () => buttonhole(1.8, false) },
  { id: 'buttonhole-v', category: 'Buttons', name: 'Buttonhole', detail: '1.4 cm, vertical', make: () => buttonhole(1.4, true) },
]

// Detail line for presets that size themselves to the pattern.
export function presetDetail(p: Preset, ctx: PresetContext): string {
  if (p.category === 'Collars') return fits(ctx.neck, 'neckline')
  if (p.id.startsWith('cuff')) return `${fits(ctx.wrist, 'wrist')}${p.detail ? `, ${p.detail}` : ''}`
  if (p.id === 'waistband') return `${fits(ctx.waist, 'waist')}, ${p.detail}`
  return p.detail
}

export const findPreset = (id: string) => PRESETS.find(p => p.id === id)

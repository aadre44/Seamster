import type { BodyField, BodyProfile, BodySex, BodyShapePreset, Lobe, LoftRing, ResolvedBody, Vec3 } from './types'
import { ringHalfWidth, scaleRing, tapeLength } from './rings'

export interface BodyFieldMeta {
  key: BodyField
  label: string
  minCm: number
  maxCm: number
  defaultCm: number
  maleDefaultCm: number // a typical adult man (chest 100, waist 86)
  // Key in EditorState.measurements that already holds this body measurement.
  // Garment-only measurements (e.g. sleeveLength) are deliberately not mapped:
  // a short-sleeve length is not an arm length.
  measurementKey?: string
}

export const BODY_FIELDS: BodyFieldMeta[] = [
  { key: 'height',     label: 'Height',         minCm: 140, maxCm: 210, defaultCm: 168, maleDefaultCm: 178 },
  { key: 'bust',       label: 'Bust',           minCm: 60,  maxCm: 160, defaultCm: 92, maleDefaultCm: 100, measurementKey: 'bust' },
  { key: 'underbust',  label: 'Underbust',      minCm: 55,  maxCm: 140, defaultCm: 76, maleDefaultCm: 94 },
  { key: 'waist',      label: 'Waist',          minCm: 45,  maxCm: 150, defaultCm: 74, maleDefaultCm: 86, measurementKey: 'waist' },
  { key: 'waistToHip', label: 'Waist to Hip',   minCm: 10,  maxCm: 35,  defaultCm: 20, maleDefaultCm: 20, measurementKey: 'waistToHip' },
  { key: 'hip',        label: 'Hip',            minCm: 60,  maxCm: 170, defaultCm: 98, maleDefaultCm: 100, measurementKey: 'hip' },
  { key: 'neck',       label: 'Neck',           minCm: 28,  maxCm: 50,  defaultCm: 36, maleDefaultCm: 39 },
  { key: 'shoulder',   label: 'Shoulder Width', minCm: 30,  maxCm: 55,  defaultCm: 39, maleDefaultCm: 46, measurementKey: 'shoulder' },
  { key: 'armLength',  label: 'Arm Length',     minCm: 45,  maxCm: 75,  defaultCm: 58, maleDefaultCm: 63 },
  { key: 'upperArm',   label: 'Upper Arm',      minCm: 20,  maxCm: 50,  defaultCm: 29, maleDefaultCm: 32 },
  { key: 'wrist',      label: 'Wrist',          minCm: 12,  maxCm: 22,  defaultCm: 16, maleDefaultCm: 17.5 },
  { key: 'inseam',     label: 'Inseam',         minCm: 60,  maxCm: 95,  defaultCm: 77, maleDefaultCm: 81, measurementKey: 'inseam' },
  { key: 'thigh',      label: 'Thigh',          minCm: 40,  maxCm: 85,  defaultCm: 56, maleDefaultCm: 57 },
  { key: 'knee',       label: 'Knee',           minCm: 28,  maxCm: 50,  defaultCm: 37, maleDefaultCm: 39 },
  { key: 'calf',       label: 'Calf',           minCm: 25,  maxCm: 50,  defaultCm: 36, maleDefaultCm: 38 },
  { key: 'ankle',      label: 'Ankle',          minCm: 18,  maxCm: 32,  defaultCm: 23, maleDefaultCm: 24 },
]

export const DEFAULT_BODY_PROFILE: BodyProfile = { overrides: {}, shape: 'hourglass' }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function resolveBody(profile: BodyProfile, measurements: Record<string, number>): ResolvedBody {
  const sex: BodySex = profile.sex ?? 'female'
  const out = { shape: profile.shape, sex } as ResolvedBody
  for (const f of BODY_FIELDS) {
    const fromMeasurements = f.measurementKey ? measurements[f.measurementKey] : undefined
    const fallback = sex === 'male' ? f.maleDefaultCm : f.defaultCm
    const raw = profile.overrides[f.key] ?? fromMeasurements ?? fallback
    out[f.key] = clamp(Number.isFinite(raw) ? raw : fallback, f.minCm, f.maxCm)
  }
  out.underbust = Math.min(out.underbust, out.bust)
  return out
}

// Ramanujan's perimeter approximation, P ≈ π[3(a+b) − √((3a+b)(a+3b))].
export function ellipsePerimeter(a: number, b: number): number {
  return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)))
}

// With b = ratio·a the approximation is linear in a, so it inverts in closed form.
export function ellipseAxes(circumference: number, ratio: number): { a: number; b: number } {
  const k = 3 * (1 + ratio) - Math.sqrt((3 + ratio) * (1 + 3 * ratio))
  const a = circumference / (Math.PI * k)
  return { a, b: a * ratio }
}

const X: Vec3 = [1, 0, 0]
const Z: Vec3 = [0, 0, 1]
const HALF_PI = Math.PI / 2

// ── Cross-section shapes ─────────────────────────────────────────────────────
// A shape is given relative to a half-width of 1: front depth f, back depth,
// superellipse exponent n (2 = ellipse; torso sections are boxier, flat-backed)
// and lobe amplitudes. `shapedRing` scales it so the tape measure (convex-hull
// perimeter) equals the measured circumference.

// Torso lobe slots, in this order on every torso section so they interpolate.
// Pairs are mirror images (θ ↔ π − θ) so the body stays symmetric.
const TORSO_SLOTS = [
  { key: 'breast', angle: HALF_PI - 0.56, width: 0.75 },
  { key: 'breast', angle: HALF_PI + 0.56, width: 0.75 },
  { key: 'blade', angle: -HALF_PI + 0.75, width: 0.8 },
  { key: 'blade', angle: -HALF_PI - 0.75, width: 0.8 },
  { key: 'belly', angle: HALF_PI, width: 1.2 },
  { key: 'glute', angle: -HALF_PI + 0.6, width: 0.95 },
  { key: 'glute', angle: -HALF_PI - 0.6, width: 0.95 },
] as const
type TorsoLobe = (typeof TORSO_SLOTS)[number]['key']

// Leg lobes: quadriceps in front, calf muscle behind.
const LEG_SLOTS = [
  { key: 'quad', angle: HALF_PI, width: 1.2 },
  { key: 'calf', angle: -HALF_PI, width: 1.0 },
] as const
type LegLobe = (typeof LEG_SLOTS)[number]['key']

function lobes<K extends string>(slots: readonly { key: K; angle: number; width: number }[], amps: Partial<Record<K, number>>): Lobe[] {
  return slots.map(s => ({ angle: s.angle, width: s.width, amp: amps[s.key] ?? 0 }))
}

interface Shape { f: number; back: number; n: number; lobes: Lobe[] }

function shapedRing(name: string, center: Vec3, circumference: number, shape: Shape, u: Vec3 = X, w: Vec3 = Z): LoftRing {
  const unit: LoftRing = { name, center, a: 1, b: shape.f, back: shape.back, n: shape.n, lobes: shape.lobes, u, w }
  return scaleRing(unit, circumference / tapeLength(unit))
}

const torsoShape = (f: number, back: number, n: number, amps: Partial<Record<TorsoLobe, number>> = {}): Shape =>
  ({ f, back, n, lobes: lobes(TORSO_SLOTS, amps) })

// Per-preset torso proportions (relative to half-width): waist and hip
// depths, belly and buttock projection, and posture offsets (cm, +z = front).
interface ShapeParams {
  waist: { f: number; back: number }
  hip: { f: number; back: number }
  belly: number
  glute: number
  waistZ: number
  hipZ: number
}

export const SHAPE_PRESETS: Record<BodyShapePreset, ShapeParams> = {
  hourglass: { waist: { f: 0.66, back: 0.70 }, hip: { f: 0.58, back: 0.54 }, belly: 0.03, glute: 0.12, waistZ: 0,   hipZ: -1.0 },
  rectangle: { waist: { f: 0.72, back: 0.74 }, hip: { f: 0.62, back: 0.58 }, belly: 0.05, glute: 0.08, waistZ: 0,   hipZ: -0.5 },
  pear:      { waist: { f: 0.66, back: 0.70 }, hip: { f: 0.54, back: 0.50 }, belly: 0.04, glute: 0.13, waistZ: 0,   hipZ: -1.2 },
  apple:     { waist: { f: 0.92, back: 0.72 }, hip: { f: 0.66, back: 0.58 }, belly: 0.20, glute: 0.06, waistZ: 2.0, hipZ: -0.3 },
}

// Men: a deeper, straighter waist, narrower flatter seat. The same four keys,
// shown as Athletic (V), Rectangle, Triangle and Oval.
export const MALE_SHAPE_PRESETS: Record<BodyShapePreset, ShapeParams> = {
  hourglass: { waist: { f: 0.70, back: 0.70 }, hip: { f: 0.60, back: 0.56 }, belly: 0.02, glute: 0.07, waistZ: 0.3, hipZ: -0.6 },
  rectangle: { waist: { f: 0.76, back: 0.74 }, hip: { f: 0.64, back: 0.60 }, belly: 0.04, glute: 0.05, waistZ: 0.5, hipZ: -0.3 },
  pear:      { waist: { f: 0.72, back: 0.72 }, hip: { f: 0.60, back: 0.56 }, belly: 0.05, glute: 0.08, waistZ: 0.3, hipZ: -0.6 },
  apple:     { waist: { f: 0.95, back: 0.74 }, hip: { f: 0.68, back: 0.60 }, belly: 0.22, glute: 0.04, waistZ: 2.5, hipZ: -0.2 },
}

const presetFor = (b: ResolvedBody): ShapeParams => (b.sex === 'male' ? MALE_SHAPE_PRESETS : SHAPE_PRESETS)[b.shape]

// ── Levels ───────────────────────────────────────────────────────────────────

// Vertical landmarks as fractions of height (adult proportions), except crotch
// (from inseam) and hip (from waist-to-hip), which are measured.
export interface Levels {
  neckUpper: number; neckTop: number; neckBase: number; shoulder: number; armpit: number; upperBust: number
  bust: number; lowerBust: number; underbust: number; waist: number; abdomen: number; hip: number; crotch: number
  knee: number; calf: number; ankle: number
}

export function bodyLevels(b: ResolvedBody): Levels {
  const H = b.height
  const crotch = clamp(b.inseam, 0.40 * H, 0.52 * H)
  // A man's natural waist sits a little lower on the torso.
  const waist = (b.sex === 'male' ? 0.605 : 0.62) * H
  const hip = clamp(waist - b.waistToHip, crotch + 5, waist - 8)
  return {
    neckUpper: 0.9 * H,
    neckTop: 0.872 * H,
    neckBase: 0.835 * H,
    shoulder: 0.812 * H,
    armpit: 0.75 * H,
    upperBust: 0.735 * H,
    bust: 0.72 * H,
    lowerBust: 0.702 * H,
    underbust: 0.68 * H,
    waist,
    abdomen: waist - 0.45 * (waist - hip),
    hip,
    crotch,
    knee: 0.285 * H,
    calf: 0.215 * H,
    ankle: 0.05 * H,
  }
}

// ── Torso ────────────────────────────────────────────────────────────────────

// The bust section is the chest wall (sized from the underbust) plus the two
// breast lobes, whose projection is solved so the tape over the apexes equals
// the bust measurement — the bust–underbust difference becomes the cup.
function bustRing(center: Vec3, wallCirc: number, bustCirc: number, wall: Shape): LoftRing {
  const base = shapedRing('bust', center, Math.min(wallCirc, bustCirc), wall)
  if (bustCirc <= wallCirc) return base
  const withBreasts = (amp: number): LoftRing => ({
    ...base,
    lobes: base.lobes!.map((l, k) => (TORSO_SLOTS[k].key === 'breast' ? { ...l, amp } : l)),
  })
  let lo = 0
  let hi = base.a
  for (let i = 0; i < 20 && tapeLength(withBreasts(hi)) < bustCirc; i++) hi *= 1.5
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2
    if (tapeLength(withBreasts(mid)) < bustCirc) lo = mid
    else hi = mid
  }
  return withBreasts((lo + hi) / 2)
}

const torsoCache = new WeakMap<ResolvedBody, LoftRing[]>()

// Top to bottom. The centre z offsets give the spine its S-curve: upper back
// rounded behind, chest forward, lumbar hollow, seat behind.
export function torsoRings(b: ResolvedBody): LoftRing[] {
  const cached = torsoCache.get(b)
  if (cached) return cached
  const L = bodyLevels(b)
  const P = presetFor(b)

  // The neck leans forward from its base behind the collarbones, and continues
  // up inside the head so the nape blends into the skull instead of ending in a rim.
  const neckBase = shapedRing('neckBase', [0, L.neckBase, -2.0], b.neck * 1.12, torsoShape(0.80, 0.90, 2))
  const shoulderA = (b.shoulder / 2) * 0.9
  const shoulder: LoftRing = {
    name: 'shoulder', center: [0, L.shoulder, -1.5], a: shoulderA, b: b.shoulder * 0.13, back: b.shoulder * 0.17, n: 2.4,
    lobes: lobes(TORSO_SLOTS, { blade: 0.4 }), u: X, w: Z,
  }
  // Sloped trapezius between neck and shoulder point, so the shoulder line
  // falls away from the neck instead of forming a flat shelf.
  const trapezius: LoftRing = {
    name: 'trapezius',
    center: [0, L.shoulder + 0.35 * (L.neckBase - L.shoulder), -1.2],
    a: neckBase.a + 0.55 * (shoulderA - neckBase.a),
    b: Math.max(neckBase.b, shoulder.b),
    back: Math.max(neckBase.back ?? neckBase.b, shoulder.back!) * 1.05,
    n: 2.2,
    lobes: lobes(TORSO_SLOTS, {}),
    u: X,
    w: Z,
  }
  const male = b.sex === 'male'
  const chestWall = torsoShape(0.62, 0.78, 2.4, { blade: 0.03 })
  // A man's chest is the measured girth over broad, flat pectorals: no cup.
  const maleChest = torsoShape(0.58, 0.74, 2.6, { breast: 0.035, blade: 0.05 })
  const bust = male
    ? shapedRing('bust', [0, L.bust, 0.5], b.bust, maleChest)
    : bustRing([0, L.bust, 0.5], b.underbust * 1.06, b.bust, chestWall)
  // Breast profile from the side: a gentle upper slope, the apex at bust level,
  // and a fuller lower curve tucking into the fold at the underbust.
  const breastAmp = bust.lobes![0].amp
  const withBreast = (r: LoftRing, fraction: number): LoftRing => ({
    ...r,
    lobes: r.lobes!.map((l, k) => (TORSO_SLOTS[k].key === 'breast' ? { ...l, amp: breastAmp * fraction } : l)),
  })
  const upperBust = male
    ? shapedRing('upperBust', [0, L.upperBust, 0.3], b.bust * 0.995, maleChest)
    : withBreast(shapedRing('upperBust', [0, L.upperBust, 0.2], b.underbust * 1.07, chestWall), 0.55)
  const lowerBust = male
    ? shapedRing('lowerBust', [0, L.lowerBust, 0.4], b.bust * 0.975, torsoShape(0.6, 0.76, 2.5, { breast: 0.015, blade: 0.03 }))
    : withBreast(shapedRing('lowerBust', [0, L.lowerBust, 0.4], b.underbust * 1.05, chestWall), 0.8)

  const hipShape = torsoShape(P.hip.f, P.hip.back, 2.3, { glute: P.glute })
  const seat = shapedRing('seat', [0, L.crotch + 3, P.hipZ * 0.8], b.hip * 0.95,
    torsoShape(P.hip.f, P.hip.back, 2.2, { glute: P.glute * 1.15 }))
  // Rounds the torso off between the legs (hidden by the inner thighs), so
  // there is no flat shelf at the crotch.
  const crotch: LoftRing = { ...scaleRing(seat, 0.6), name: 'crotch', center: [0, L.crotch - 1.5, P.hipZ * 0.6] }
  const crotchBottom: LoftRing = { ...scaleRing(seat, 0.25), name: 'crotchBottom', center: [0, L.crotch - 3.5, P.hipZ * 0.5] }

  const rings: LoftRing[] = [
    shapedRing('neckUpper', [0, L.neckUpper, 0.4], b.neck * 0.85, torsoShape(0.95, 0.95, 2)),
    shapedRing('neckTop', [0, L.neckTop, -0.6], b.neck * 0.92, torsoShape(0.95, 0.95, 2)),
    neckBase,
    trapezius,
    shoulder,
    shapedRing('armpit', [0, L.armpit, -0.5],
      male ? b.bust * 0.98 : Math.min(b.bust, b.underbust * 1.1 + 0.15 * (b.bust - b.underbust)),
      torsoShape(male ? 0.62 : 0.66, 0.78, 2.4, { blade: 0.05 })),
    upperBust,
    bust,
    lowerBust,
    // For a man, the ribcage below the pectorals tapers toward the waist.
    shapedRing('underbust', [0, L.underbust, 0.3], male ? 0.7 * b.bust + 0.3 * b.waist : b.underbust,
      torsoShape(0.66, 0.80, 2.4)),
    shapedRing('waist', [0, L.waist, P.waistZ], b.waist, torsoShape(P.waist.f, P.waist.back, 2.3)),
    shapedRing('abdomen', [0, L.abdomen, (P.waistZ + P.hipZ) / 2], b.waist + 0.6 * (b.hip - b.waist),
      torsoShape((P.waist.f + P.hip.f) / 2, (P.waist.back + P.hip.back) / 2, 2.3, { belly: P.belly, glute: P.glute * 0.4 })),
    shapedRing('hip', [0, L.hip, P.hipZ], b.hip, hipShape),
    seat,
    crotch,
    crotchBottom,
  ]
  torsoCache.set(b, rings)
  return rings
}

// ── Legs ─────────────────────────────────────────────────────────────────────

const legShape = (ratio: number, amps: Partial<Record<LegLobe, number>> = {}): Shape =>
  ({ f: ratio, back: ratio, n: 2, lobes: lobes(LEG_SLOTS, amps) })

export function legRings(b: ResolvedBody, side: 1 | -1): LoftRing[] {
  const L = bodyLevels(b)
  const P = presetFor(b)
  const hip = torsoRings(b).find(r => r.name === 'hip')!
  const hipHalf = ringHalfWidth(hip)
  const thighA = ellipseAxes(b.thigh, 0.9).a
  const cx = Math.max(hipHalf - thighA * 0.95, thighA * 0.8)
  const midThighY = L.crotch - 0.4 * (L.crotch - L.knee)
  // The leg starts at hip level with its outer side just inside the hip, so
  // the outer thigh continues the hip line (no saddlebag where they join).
  const top = shapedRing('legTop', [0, L.hip, P.hipZ * 0.6], b.thigh, legShape(0.9))
  top.center = [side * Math.max(hipHalf - top.a - 1.5, top.a * 0.5), L.hip, P.hipZ * 0.6]
  return [
    top,
    shapedRing('thigh', [side * cx, L.crotch - 3, 0], b.thigh, legShape(0.88, { quad: 0.04 })),
    shapedRing('midThigh', [side * cx * 0.9, midThighY, 0.3], b.thigh * 0.6 + b.knee * 0.4, legShape(0.88, { quad: 0.06 })),
    shapedRing('knee', [side * cx * 0.8, L.knee, 0.5], b.knee, legShape(0.92)),
    shapedRing('calf', [side * cx * 0.76, L.calf, -0.8], b.calf, legShape(0.82, { calf: 0.14 })),
    shapedRing('ankle', [side * cx * 0.74, L.ankle, -0.5], b.ankle, legShape(0.8)),
  ]
}

// ── Arms ─────────────────────────────────────────────────────────────────────

export interface ArmFrame {
  joint: Vec3
  dir: Vec3
  u: Vec3
  angle: number // radians from vertical
  length: number // shoulder → fingertip
}

export const armRadius = (b: ResolvedBody) => (b.upperArm / (2 * Math.PI)) * 1.1

// Gap kept between a hanging arm and the torso. It exceeds the arm/torso blend
// radius of the surface, so blending never alters a measured torso section.
export const ARM_CLEARANCE = 3.5

// Torso sections the hanging arm must clear. Above the bust the arm is attached
// (shoulder socket / armpit), so overlap there is expected.
export function armClearanceRings(b: ResolvedBody): LoftRing[] {
  const bustY = bodyLevels(b).bust
  return torsoRings(b).filter(r => r.center[1] <= bustY)
}

// Arms hang in a relaxed A-pose; the angle opens just enough that the arm
// clears every torso section it passes (wide hips / apple waist push it out).
export function armFrame(b: ResolvedBody, side: 1 | -1): ArmFrame {
  const L = bodyLevels(b)
  const armR = armRadius(b)
  // A chest broader than the shoulder measurement pushes the arm root out to the ribcage side.
  const armpit = torsoRings(b).find(r => r.name === 'armpit')!
  const jointX = Math.max(b.shoulder / 2 - armR * 0.5, ringHalfWidth(armpit) + armR * 0.3)
  const joint: Vec3 = [side * jointX, L.shoulder - armR * 0.9, -1.5]
  const handLen = 0.105 * b.height
  const reach = b.armLength + handLen
  let tanNeeded = Math.tan((12 * Math.PI) / 180)
  for (const r of armClearanceRings(b)) {
    const dy = joint[1] - r.center[1]
    if (dy <= 0 || dy > reach) continue
    const needX = ringHalfWidth(r) + armR + ARM_CLEARANCE
    tanNeeded = Math.max(tanNeeded, (needX - Math.abs(joint[0])) / dy)
  }
  const angle = Math.min(Math.atan(tanNeeded), (55 * Math.PI) / 180)
  const dir: Vec3 = [side * Math.sin(angle), -Math.cos(angle), 0]
  const u: Vec3 = [-dir[1], dir[0], 0] // Z × dir
  return { joint, dir, u, angle, length: reach }
}

export function armRings(b: ResolvedBody, side: 1 | -1): LoftRing[] {
  const f = armFrame(b, side)
  const at = (t: number): Vec3 => [f.joint[0] + f.dir[0] * t, f.joint[1] + f.dir[1] * t, f.joint[2]]
  const A = b.armLength
  const handLen = f.length - A
  const r = b.wrist / (2 * Math.PI)
  const forearm = ((b.upperArm * 0.82 + b.wrist) / 2) * 1.08
  const armRing = (name: string, t: number, circ: number, ratio: number): LoftRing =>
    ({ ...shapedRing(name, at(t), circ, { f: ratio, back: ratio, n: 2, lobes: [] }, f.u, Z) })
  const top = armRing('armTop', -1, b.upperArm * 1.12, 0.95)
  // Rounded shoulder cap: sections of a hemisphere at 35°, 65° and 85°.
  const R = top.a
  const capRing = (name: string, deg: number): LoftRing => {
    const phi = (deg * Math.PI) / 180
    return { ...scaleRing(top, Math.cos(phi)), name, center: at(-1 - R * Math.sin(phi)) }
  }
  const handRing = (name: string, t: number, a: number, depth: number): LoftRing =>
    ({ name, center: at(t), a, b: depth, back: depth, n: 2, lobes: [], u: f.u, w: Z })
  return [
    capRing('armCap3', 85),
    capRing('armCap2', 65),
    capRing('armCap1', 35),
    top,
    armRing('upperArm', 0.15 * A, b.upperArm, 0.95),
    armRing('elbow', 0.45 * A, b.upperArm * 0.82, 0.9),
    armRing('forearm', 0.62 * A, forearm, 0.85),
    // Palms face the thighs, so from the wrist down the wide axis runs front-to-back (w).
    armRing('wrist', A, b.wrist, 1.5),
    handRing('palm', A + 0.45 * handLen, r * 0.5, r * 1.65),
    handRing('fingers', A + 0.85 * handLen, r * 0.45, r * 1.4),
    handRing('fingertip', A + 0.98 * handLen, r * 0.25, r * 0.7),
  ]
}

// ── Head & feet ──────────────────────────────────────────────────────────────

export interface Ellipsoid { center: Vec3; radii: Vec3 }

// Mannequin head: an egg-shaped cranium plus a narrower jaw ellipsoid, which
// the surface blends together. The crown sits exactly at `height`.
export function headEllipsoids(b: ResolvedBody): { cranium: Ellipsoid; jaw: Ellipsoid } {
  const H = b.height
  const ry = 0.066 * H
  const rz = 0.056 * H
  return {
    cranium: { center: [0, H - ry, 0.8], radii: [0.043 * H, ry, rz] },
    // A man's jaw is broader and squarer.
    jaw: { center: [0, H - ry * 1.5, 0.8 + rz * 0.22], radii: [(b.sex === 'male' ? 0.036 : 0.032) * H, ry * 0.55, rz * (b.sex === 'male' ? 0.72 : 0.68)] },
  }
}

// Foot: an ellipsoid running forward from the heel under the ankle; the floor
// plane cuts it flat.
export function footEllipsoid(b: ResolvedBody, side: 1 | -1): Ellipsoid {
  const ankle = legRings(b, side).find(r => r.name === 'ankle')!
  const H = b.height
  const length = 0.15 * H
  return {
    center: [ankle.center[0], 0.022 * H, ankle.center[2] - 4 + length / 2],
    radii: [0.024 * H, 0.027 * H, length / 2],
  }
}

import type { BodyField, BodyProfile, BodyShapePreset, LoftRing, ResolvedBody, Vec3 } from './types'

export interface BodyFieldMeta {
  key: BodyField
  label: string
  minCm: number
  maxCm: number
  defaultCm: number
  // Key in EditorState.measurements that already holds this body measurement.
  // Garment-only measurements (e.g. sleeveLength) are deliberately not mapped:
  // a short-sleeve length is not an arm length.
  measurementKey?: string
}

export const BODY_FIELDS: BodyFieldMeta[] = [
  { key: 'height',     label: 'Height',         minCm: 140, maxCm: 210, defaultCm: 168 },
  { key: 'bust',       label: 'Bust',           minCm: 60,  maxCm: 160, defaultCm: 92,  measurementKey: 'bust' },
  { key: 'underbust',  label: 'Underbust',      minCm: 55,  maxCm: 140, defaultCm: 76 },
  { key: 'waist',      label: 'Waist',          minCm: 45,  maxCm: 150, defaultCm: 74,  measurementKey: 'waist' },
  { key: 'waistToHip', label: 'Waist to Hip',   minCm: 10,  maxCm: 35,  defaultCm: 20,  measurementKey: 'waistToHip' },
  { key: 'hip',        label: 'Hip',            minCm: 60,  maxCm: 170, defaultCm: 98,  measurementKey: 'hip' },
  { key: 'neck',       label: 'Neck',           minCm: 28,  maxCm: 50,  defaultCm: 36 },
  { key: 'shoulder',   label: 'Shoulder Width', minCm: 30,  maxCm: 55,  defaultCm: 39,  measurementKey: 'shoulder' },
  { key: 'armLength',  label: 'Arm Length',     minCm: 45,  maxCm: 75,  defaultCm: 58 },
  { key: 'upperArm',   label: 'Upper Arm',      minCm: 20,  maxCm: 50,  defaultCm: 29 },
  { key: 'wrist',      label: 'Wrist',          minCm: 12,  maxCm: 22,  defaultCm: 16 },
  { key: 'inseam',     label: 'Inseam',         minCm: 60,  maxCm: 95,  defaultCm: 77,  measurementKey: 'inseam' },
  { key: 'thigh',      label: 'Thigh',          minCm: 40,  maxCm: 85,  defaultCm: 56 },
  { key: 'knee',       label: 'Knee',           minCm: 28,  maxCm: 50,  defaultCm: 37 },
  { key: 'calf',       label: 'Calf',           minCm: 25,  maxCm: 50,  defaultCm: 36 },
  { key: 'ankle',      label: 'Ankle',          minCm: 18,  maxCm: 32,  defaultCm: 23 },
]

export const DEFAULT_BODY_PROFILE: BodyProfile = { overrides: {}, shape: 'hourglass' }

// Depth ratio = front-to-back semi-axis / side-to-side semi-axis of a cross-section.
// Z offsets (cm, +z = front) push the section centre forward (bust, belly) or back (seat).
interface ShapeParams {
  ratio: { bust: number; underbust: number; waist: number; hip: number }
  bustZ: number
  waistZ: number
  hipZ: number
}

export const SHAPE_PRESETS: Record<BodyShapePreset, ShapeParams> = {
  hourglass: { ratio: { bust: 0.80, underbust: 0.74, waist: 0.72, hip: 0.74 }, bustZ: 2.0, waistZ: 0,   hipZ: -1.5 },
  rectangle: { ratio: { bust: 0.74, underbust: 0.72, waist: 0.78, hip: 0.72 }, bustZ: 1.2, waistZ: 0,   hipZ: -0.8 },
  pear:      { ratio: { bust: 0.72, underbust: 0.70, waist: 0.72, hip: 0.66 }, bustZ: 1.0, waistZ: 0,   hipZ: -1.8 },
  apple:     { ratio: { bust: 0.82, underbust: 0.86, waist: 0.95, hip: 0.78 }, bustZ: 1.5, waistZ: 3.5, hipZ: -0.5 },
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function resolveBody(profile: BodyProfile, measurements: Record<string, number>): ResolvedBody {
  const out = { shape: profile.shape } as ResolvedBody
  for (const f of BODY_FIELDS) {
    const fromMeasurements = f.measurementKey ? measurements[f.measurementKey] : undefined
    const raw = profile.overrides[f.key] ?? fromMeasurements ?? f.defaultCm
    out[f.key] = clamp(Number.isFinite(raw) ? raw : f.defaultCm, f.minCm, f.maxCm)
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

function ring(name: string, center: Vec3, circ: number, ratio: number, u: Vec3 = X, w: Vec3 = Z): LoftRing {
  const { a, b } = ellipseAxes(circ, ratio)
  return { name, center, a, b, u, w }
}

// Vertical landmarks as fractions of height (adult mannequin proportions),
// except crotch (from inseam) and hip (from waist-to-hip), which are measured.
export interface Levels {
  neckTop: number; neckBase: number; shoulder: number; armpit: number
  bust: number; underbust: number; waist: number; hip: number; crotch: number
  knee: number; calf: number; ankle: number
}

export function bodyLevels(b: ResolvedBody): Levels {
  const H = b.height
  const crotch = clamp(b.inseam, 0.40 * H, 0.52 * H)
  const waist = 0.62 * H
  const hip = clamp(waist - b.waistToHip, crotch + 5, waist - 8)
  return {
    neckTop: 0.872 * H,
    neckBase: 0.835 * H,
    shoulder: 0.812 * H,
    armpit: 0.75 * H,
    bust: 0.72 * H,
    underbust: 0.68 * H,
    waist,
    hip,
    crotch,
    knee: 0.285 * H,
    calf: 0.215 * H,
    ankle: 0.05 * H,
  }
}

export function torsoRings(b: ResolvedBody): LoftRing[] {
  const L = bodyLevels(b)
  const s = SHAPE_PRESETS[b.shape]
  const neckBase = ring('neckBase', [0, L.neckBase, -1.0], b.neck * 1.12, 0.85)
  const shoulder: LoftRing = {
    name: 'shoulder', center: [0, L.shoulder, -1.5], a: (b.shoulder / 2) * 0.9, b: b.shoulder * 0.16, u: X, w: Z,
  }
  // Sloped trapezius between neck and shoulder point, so the shoulder line
  // falls away from the neck instead of forming a flat shelf.
  const trapezius: LoftRing = {
    name: 'trapezius',
    center: [0, L.shoulder + 0.35 * (L.neckBase - L.shoulder), -1.2],
    a: neckBase.a + 0.55 * (shoulder.a - neckBase.a),
    b: Math.max(neckBase.b, shoulder.b) * 1.05,
    u: X,
    w: Z,
  }
  const seat = ring('seat', [0, L.crotch + 3, s.hipZ * 0.8], b.hip * 0.94, 0.72)
  // Closes the torso between the legs; mostly hidden inside the thighs.
  const crotch: LoftRing = { ...seat, name: 'crotch', center: [0, L.crotch - 1, s.hipZ * 0.6], a: seat.a * 0.8, b: seat.b * 0.8 }
  return [
    ring('neckTop', [0, L.neckTop, -0.5], b.neck * 0.92, 0.95),
    neckBase,
    trapezius,
    shoulder,
    ring('armpit', [0, L.armpit, -0.5], Math.min(b.bust, (b.bust + b.underbust) / 2 + 2), 0.68),
    ring('bust', [0, L.bust, s.bustZ], b.bust, s.ratio.bust),
    ring('underbust', [0, L.underbust, s.bustZ * 0.3], b.underbust, s.ratio.underbust),
    ring('waist', [0, L.waist, s.waistZ], b.waist, s.ratio.waist),
    ring('hip', [0, L.hip, s.hipZ], b.hip, s.ratio.hip),
    seat,
    crotch,
  ]
}

export function legRings(b: ResolvedBody, side: 1 | -1): LoftRing[] {
  const L = bodyLevels(b)
  const s = SHAPE_PRESETS[b.shape]
  const hipA = ellipseAxes(b.hip, s.ratio.hip).a
  const thighA = ellipseAxes(b.thigh, 0.9).a
  const cx = Math.max(hipA - thighA * 0.95, thighA * 0.8)
  const footR = b.ankle / (2 * Math.PI)
  const midThighY = L.crotch - 0.4 * (L.crotch - L.knee)
  return [
    // Starts inside the torso, smaller than the thigh, so hips flow into the legs.
    ring('legTop', [side * cx * 0.85, L.crotch + 7, s.hipZ * 0.5], b.thigh * 0.8, 0.9),
    ring('thigh', [side * cx, L.crotch - 3, 0], b.thigh, 0.9),
    ring('midThigh', [side * cx * 0.9, midThighY, 0.3], b.thigh * 0.6 + b.knee * 0.4, 0.9),
    ring('knee', [side * cx * 0.8, L.knee, 0.5], b.knee, 0.9),
    ring('calf', [side * cx * 0.76, L.calf, -1.2], b.calf, 0.85),
    ring('ankle', [side * cx * 0.74, L.ankle, -0.5], b.ankle, 0.8),
    { name: 'foot', center: [side * cx * 0.74, 0.02 * b.height, 5], a: footR * 1.1, b: footR * 2.4, u: X, w: Z },
  ]
}

export function legEnd(b: ResolvedBody, side: 1 | -1): Vec3 {
  const rings = legRings(b, side)
  const foot = rings[rings.length - 1]
  return [foot.center[0], 0, foot.center[2]]
}

export interface ArmFrame {
  joint: Vec3
  dir: Vec3
  u: Vec3
  angle: number // radians from vertical
  length: number // shoulder → fingertip
}

export const armRadius = (b: ResolvedBody) => (b.upperArm / (2 * Math.PI)) * 1.1

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
  const armpitA = torsoRings(b).find(r => r.name === 'armpit')!.a
  const jointX = Math.max(b.shoulder / 2 - armR * 0.5, armpitA + armR * 0.3)
  const joint: Vec3 = [side * jointX, L.shoulder - armR * 0.9, -1.5]
  const handLen = 0.105 * b.height
  const reach = b.armLength + handLen
  let tanNeeded = Math.tan((12 * Math.PI) / 180)
  for (const r of armClearanceRings(b)) {
    const dy = joint[1] - r.center[1]
    if (dy <= 0 || dy > reach) continue
    const needX = r.a + armR + 1.5
    tanNeeded = Math.max(tanNeeded, (needX - Math.abs(joint[0])) / dy)
  }
  const angle = Math.min(Math.atan(tanNeeded), (45 * Math.PI) / 180)
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
  const armRing = (name: string, t: number, circ: number, ratio: number) =>
    ring(name, at(t), circ, ratio, f.u, Z)
  const top = armRing('armTop', -1, b.upperArm * 1.12, 0.95)
  // Rounded shoulder cap: sections of a hemisphere at 35° and 65°, pole at armStartCap.
  const R = top.a
  const capRing = (name: string, deg: number): LoftRing => {
    const phi = (deg * Math.PI) / 180
    return { ...top, name, center: at(-1 - R * Math.sin(phi)), a: top.a * Math.cos(phi), b: top.b * Math.cos(phi) }
  }
  return [
    capRing('armCap2', 65),
    capRing('armCap1', 35),
    top,
    armRing('upperArm', 0.15 * A, b.upperArm, 0.95),
    armRing('elbow', 0.45 * A, b.upperArm * 0.82, 0.9),
    armRing('forearm', 0.62 * A, forearm, 0.85),
    // Palms face the thighs, so from the wrist down the wide axis runs front-to-back (w).
    armRing('wrist', A, b.wrist, 1.5),
    { name: 'palm', center: at(A + 0.45 * handLen), a: r * 0.5, b: r * 1.65, u: f.u, w: Z },
    { name: 'fingers', center: at(A + 0.85 * handLen), a: r * 0.45, b: r * 1.4, u: f.u, w: Z },
  ]
}

export function armStartCap(b: ResolvedBody, side: 1 | -1): Vec3 {
  const f = armFrame(b, side)
  const R = ellipseAxes(b.upperArm * 1.12, 0.95).a
  const t = -1 - R
  return [f.joint[0] + f.dir[0] * t, f.joint[1] + f.dir[1] * t, f.joint[2]]
}

export function armEnd(b: ResolvedBody, side: 1 | -1): Vec3 {
  const f = armFrame(b, side)
  return [f.joint[0] + f.dir[0] * f.length, f.joint[1] + f.dir[1] * f.length, f.joint[2]]
}

export function headRings(b: ResolvedBody, count = 12): { rings: LoftRing[]; top: Vec3; bottom: Vec3 } {
  const H = b.height
  const rx = 0.045 * H
  const ry = 0.068 * H
  const rz = 0.057 * H
  const cy = H - ry
  const cz = 0.8
  const rings: LoftRing[] = []
  for (let i = 1; i < count; i++) {
    const phi = Math.PI / 2 - (Math.PI * i) / count // top → bottom
    const c = Math.cos(phi)
    rings.push({ name: `head${i}`, center: [0, cy + ry * Math.sin(phi), cz], a: rx * c, b: rz * c, u: X, w: Z })
  }
  return { rings, top: [0, H, cz], bottom: [0, cy - ry, cz] }
}

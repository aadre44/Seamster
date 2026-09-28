export type Vec3 = [number, number, number]

export type BodyShapePreset = 'hourglass' | 'rectangle' | 'pear' | 'apple'

export type BodyField =
  | 'height' | 'bust' | 'underbust' | 'waist' | 'waistToHip' | 'hip'
  | 'neck' | 'shoulder' | 'armLength' | 'upperArm' | 'wrist'
  | 'inseam' | 'thigh' | 'knee' | 'calf' | 'ankle'

// Only the values the user has explicitly set on the body; everything else
// resolves from the editor measurements, then from defaults.
export interface BodyProfile {
  overrides: Partial<Record<BodyField, number>>
  shape: BodyShapePreset
}

export type ResolvedBody = Record<BodyField, number> & { shape: BodyShapePreset }

// A soft radial bump on a cross-section (breast, shoulder blade, buttock, belly).
// `angle` is measured from +u towards +w (front); `width` is the dome's
// half-extent in radians; `amp` its peak height in cm.
export interface Lobe {
  angle: number
  width: number
  amp: number
}

// One cross-section of the body, in the plane spanned by u (lateral) and w
// (front). Its outline is the polar curve
//   R(θ) = superellipse(a, front depth b / back depth `back`, exponent n) + Σ lobes,
// placed at center + R(θ)·(cosθ·u + sinθ·w). With back = b, n = 2 and no lobes
// it is the ellipse (a, b).
export interface LoftRing {
  name: string
  center: Vec3
  a: number
  b: number
  back?: number
  n?: number
  lobes?: Lobe[]
  u: Vec3
  w: Vec3
}

export interface MeshData {
  name: string
  positions: Float32Array
  normals?: Float32Array
  indices: Uint32Array
}

export interface AvatarData {
  parts: MeshData[]
  // Named landmark cross-sections per body part, used by tests and by the
  // garment-wrap / collision phases.
  landmarks: Record<string, LoftRing[]>
  height: number
}

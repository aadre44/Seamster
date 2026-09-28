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

// One cross-section of a loft: an ellipse in the plane spanned by u (lateral)
// and w (depth), p(θ) = center + a·cosθ·u + b·sinθ·w.
export interface LoftRing {
  name: string
  center: Vec3
  a: number
  b: number
  u: Vec3
  w: Vec3
}

export interface MeshData {
  name: string
  positions: Float32Array
  indices: Uint32Array
}

export interface AvatarData {
  parts: MeshData[]
  // Named landmark rings per part (before smoothing subdivision), for tests and
  // for the garment wrap / collision phases.
  landmarks: Record<string, LoftRing[]>
  height: number
}

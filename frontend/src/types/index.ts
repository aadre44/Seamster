import type { BodyProfile } from '../three/types'

// ── Phase 1: Editor types ────────────────────────────────────────────────────

export interface Point {
  x: number // cm
  y: number // cm
}

export interface LineElement {
  id: string
  type: 'line'
  start: Point
  end: Point
  formula?: string
  isFold: boolean
  pieceId?: string
  seamLabel?: string
}

export interface CurveElement {
  id: string
  type: 'curve'
  start: Point
  cp1: Point
  cp2: Point
  end: Point
  formula?: string
  pieceId?: string
  seamLabel?: string
}

export interface GrainLineElement {
  id: string
  type: 'grain-line'
  start: Point
  end: Point
  pieceId?: string
}

export interface NotchElement {
  id: string
  type: 'notch'
  position: Point
  angle: number // degrees
  pieceId?: string
}

export interface AnchorPointElement {
  id: string
  type: 'anchor-point'
  position: Point
}

export type CanvasElement = LineElement | CurveElement | GrainLineElement | NotchElement | AnchorPointElement

export interface SeamConnection {
  label: string
  from: { pieceId: string; edgeId: string }
  to: { pieceId: string; edgeId: string }
}

export interface PatternPiece {
  id: string
  name: string
  elementIds: string[]
  cutQty: number
  onFold: boolean
  seamAllowance: number // cm
  closed: boolean
  notes?: string
  // Provenance of generated pieces: 'engine' (parametric builder), 'template'
  // (learned store), 'llm' (AI-guessed draft), 'vision' (traced from the photo).
  // Non-engine pieces render amber on the canvas and offer "Save as template".
  source?: string
  detail?: string // the detail token that produced a non-engine piece
}

export type ToolType = 'select' | 'line' | 'curve' | 'seam-allowance' | 'grain-line' | 'notch' | 'point' | 'eraser'

export type UnitSystem = 'metric' | 'imperial'

// One undo/redo history entry. Pieces and connections must be versioned together
// with elements — restoring elements alone leaves pieces referencing deleted
// element ids (dangling pieces).
export interface EditorSnapshot {
  elements: CanvasElement[]
  pieces: PatternPiece[]
  connections: SeamConnection[]
}

export interface EditorState {
  elements: CanvasElement[]
  pieces: PatternPiece[]
  measurements: Record<string, number>
  connections: SeamConnection[]
  selectedIds: string[]
  selectedPieceId: string | null
  activeTool: ToolType
  zoom: number // multiplier; 1.0 = BASE_SCALE px/cm
  pan: { x: number; y: number } // px offset in SVG viewport
  showGrid: boolean
  snapEnabled: boolean
  showSeamAllowance: boolean
  unitSystem: UnitSystem // all internal values always in cm; this controls display only
  undoStack: EditorSnapshot[]
  redoStack: EditorSnapshot[]
  // Pre-gesture snapshot captured on the first LIVE_UPDATE_ELEMENTS of a drag;
  // PUSH_UNDO commits it as the undo entry so a whole drag is one undo step.
  liveBase: EditorSnapshot | null
  // Coalescing tag: consecutive UPDATE_PIECE edits on the same piece share one
  // undo entry until the selection or action type changes.
  undoTag: string | null
  instructions: SewingInstructions | null
  instructionsLoading: boolean
  lastFeatures: GarmentFeatures | null
  lastMeasurements: Measurements | null
  // The 3D avatar's body. Belongs to the user, not the pattern, so it survives
  // LOAD_STATE and is outside undo/redo.
  bodyProfile: BodyProfile
}

// ── Phase 2: AI types ────────────────────────────────────────────────────────

export type GarmentType =
  | 'skirt' | 'dress' | 'trousers' | 'pants' | 'shirt'
  | 'blouse' | 'jacket' | 'blazer' | 'vest' | 'bodice' | 'coat' | 'shorts'
  | 'tunic' | 'romper' | 'jumpsuit'

export const GARMENT_TYPES: GarmentType[] = [
  'skirt', 'dress', 'trousers', 'pants', 'shirt',
  'blouse', 'jacket', 'blazer', 'vest', 'bodice', 'coat', 'shorts',
  'tunic', 'romper', 'jumpsuit',
]

// Silhouette-generation strategy for shape-aware garments (vest / bodice).
export type ShapeMode = 'modifiers' | 'warp' | 'fit_params'

export type HemStyle =
  | 'straight' | 'pointed' | 'angled' | 'curved_scoop' | 'high_low' | 'cutaway'

export type FrontCut = 'closed' | 'cutaway' | 'open_drape'

export interface ShapeFeature {
  hem_style: HemStyle
  hem_depth_cm: number
  waist_taper_cm: number
  hem_sweep_cm: number
  high_low_cm: number
  side_vent_cm: number
  front_cut: FrontCut
  front_cut_depth_cm: number
}

export type FrontStyle = 'symmetric' | 'asymmetric_wrap'

export interface AsymmetryFeature {
  front_style: FrontStyle
  wrap_side: 'left' | 'right'
  overlap_cm: number
  closure_drop_frac: number
}

export type WaistbandType = 'straight' | 'contoured' | 'elastic' | 'facing' | 'yoke'
export type ClosureType =
  | 'center_back_zip' | 'side_zip' | 'button_fly' | 'hook_and_eye'
  | 'center_front_zip' | 'button_front' | 'snap_front' | 'double_breasted'
  | 'none'
export type ClosurePosition = 'center_back' | 'left_side' | 'right_side' | 'center_front'

export interface WaistbandFeature {
  type: WaistbandType
  width_cm_estimate: number
}

export interface ClosureFeature {
  type: ClosureType
  position: ClosurePosition
}

export interface DartFeature {
  front: number
  back: number
}

export interface PieceContour {
  detail: string
  name?: string
  points: { x: number; y: number }[]
  width_frac: number
  reference: string
  cut_qty?: number
  attachment_label?: string | null
  attachment_edges?: number[] | null
  confidence?: number
}

export interface GarmentFeatures {
  garment_type: GarmentType
  silhouette: string
  length_category: string
  closure: ClosureFeature
  waistband?: WaistbandFeature
  darts?: DartFeature
  details: string[]
  shape?: ShapeFeature
  asymmetry?: AsymmetryFeature
  piece_contours?: PieceContour[]
  confidence: number
  notes: string
}

// Kept for backward compatibility
export type Silhouette = 'straight' | 'a_line' | 'pencil' | 'circle' | 'gathered' | 'pleated' | 'wrap'
export type LengthCategory = 'mini' | 'above_knee' | 'knee' | 'midi' | 'maxi'
export type SkirtDetail =
  | 'kick_pleat' | 'back_vent' | 'side_slits' | 'patch_pockets'
  | 'welt_pockets' | 'belt_loops' | 'lining_visible' | 'topstitching'
export interface SkirtFeatures {
  silhouette: Silhouette
  length_category: LengthCategory
  waistband: WaistbandFeature
  closure: ClosureFeature
  darts: DartFeature
  details: SkirtDetail[]
  confidence: number
  notes: string
}

export interface Measurements {
  waist_cm: number
  hip_cm: number
  waist_to_hip_cm: number
  length_cm: number
  waistband_width_cm?: number
  seam_allowance_cm?: number
  hem_allowance_cm?: number
  // Shirt / blouse specific
  chest_cm?: number
  shoulder_width_cm?: number
  arm_length_cm?: number
  // Trouser / pants specific
  inseam_cm?: number
  rise_cm?: number
}

export type PaperSize = 'a4' | 'letter'
export type ExportFormat = 'pdf_tiled' | 'pdf_single' | 'svg'

export type WizardStep = 1 | 2 | 3 | 4 | 5

// ── Sewing Instructions ──────────────────────────────────────────────────────

export interface InstructionStep {
  number: number
  instruction: string
  tip?: string
}

export interface InstructionSection {
  title: string
  steps: InstructionStep[]
}

export interface SewingInstructions {
  garment_summary: string
  sections: InstructionSection[]
}

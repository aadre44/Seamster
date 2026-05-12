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

export interface PatternPiece {
  id: string
  name: string
  elementIds: string[]
  cutQty: number
  onFold: boolean
  seamAllowance: number // cm
  closed: boolean
}

export type ToolType = 'select' | 'line' | 'curve' | 'seam-allowance' | 'grain-line' | 'notch' | 'point' | 'eraser'

export interface EditorState {
  elements: CanvasElement[]
  pieces: PatternPiece[]
  measurements: Record<string, number>
  selectedIds: string[]
  selectedPieceId: string | null
  activeTool: ToolType
  zoom: number // multiplier; 1.0 = BASE_SCALE px/cm
  pan: { x: number; y: number } // px offset in SVG viewport
  showGrid: boolean
  snapEnabled: boolean
  showSeamAllowance: boolean
  undoStack: CanvasElement[][]
  redoStack: CanvasElement[][]
}

// ── Phase 2: AI types (used later) ──────────────────────────────────────────

export type Silhouette = 'straight' | 'a_line' | 'pencil' | 'circle' | 'gathered' | 'pleated' | 'wrap'
export type LengthCategory = 'mini' | 'above_knee' | 'knee' | 'midi' | 'maxi'
export type WaistbandType = 'straight' | 'contoured' | 'elastic' | 'facing' | 'yoke'
export type ClosureType = 'center_back_zip' | 'side_zip' | 'button_fly' | 'hook_and_eye' | 'none'
export type ClosurePosition = 'center_back' | 'left_side' | 'right_side' | 'center_front'
export type SkirtDetail =
  | 'kick_pleat' | 'back_vent' | 'side_slits' | 'patch_pockets'
  | 'welt_pockets' | 'belt_loops' | 'lining_visible' | 'topstitching'

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
}

export type PaperSize = 'a4' | 'letter'
export type ExportFormat = 'pdf_tiled' | 'pdf_single' | 'svg'

export type WizardStep = 1 | 2 | 3 | 4 | 5

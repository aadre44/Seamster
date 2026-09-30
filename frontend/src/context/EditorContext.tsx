import { createContext, useContext, useReducer, ReactNode } from 'react'
import type { CanvasElement, EditorSnapshot, EditorState, GarmentFeatures, Measurements, PatternPiece, Placement, SeamConnection, SewingInstructions, ToolType, UnitSystem } from '../types'
import { mirrorPiece } from '../utils/pieceTransforms'
import type { BodyField, BodySex, BodyShapePreset } from '../three/types'
import { DEFAULT_BODY_PROFILE } from '../three/bodyRegions'

type Action =
  | { type: 'SET_ZOOM'; zoom: number }
  | { type: 'SET_PAN'; pan: { x: number; y: number } }
  | { type: 'TOGGLE_GRID' }
  | { type: 'TOGGLE_SNAP' }
  | { type: 'TOGGLE_SEAM_ALLOWANCE' }
  | { type: 'SET_UNIT_SYSTEM'; unit: UnitSystem }
  | { type: 'SET_ACTIVE_TOOL'; tool: ToolType }
  | { type: 'ADD_ELEMENT'; element: CanvasElement }
  | { type: 'UPDATE_ELEMENT'; element: CanvasElement }
  | { type: 'DELETE_ELEMENTS'; ids: string[] }
  | { type: 'SET_SELECTED'; ids: string[] }
  | { type: 'DESELECT_ALL' }
  | { type: 'SET_MEASUREMENT'; name: string; value: number }
  | { type: 'ADD_PIECE'; piece: PatternPiece }
  | { type: 'UPDATE_PIECE'; piece: PatternPiece }
  | { type: 'DELETE_PIECE'; id: string }
  | { type: 'SELECT_PIECE'; id: string }
  | { type: 'BATCH_UPDATE_ELEMENTS'; elements: CanvasElement[] }
  | { type: 'LIVE_UPDATE_ELEMENTS'; elements: CanvasElement[] }
  | { type: 'REMOVE_SIDE_FROM_PIECE'; pieceId: string; elementId: string }
  | { type: 'MIRROR_PIECE'; pieceId: string; op: 'flipH' | 'flipV' }
  | { type: 'LOAD_STATE'; elements: CanvasElement[]; pieces: PatternPiece[]; measurements: Record<string, number>; connections?: SeamConnection[]; placements?: Placement[]; instructions?: SewingInstructions | null; lastFeatures?: GarmentFeatures | null; lastMeasurements?: Measurements | null }
  | { type: 'SET_INSTRUCTIONS'; instructions: SewingInstructions | null; loading: boolean; features?: GarmentFeatures; measurements?: Measurements }
  | { type: 'ADD_CONNECTION'; connection: SeamConnection }
  | { type: 'UPDATE_CONNECTION'; index: number; connection: SeamConnection; tag?: string }
  | { type: 'DELETE_CONNECTION'; index: number }
  | { type: 'SET_CONNECTIONS'; connections: SeamConnection[] }
  | { type: 'APPLY_INFERRED'; connections: SeamConnection[]; placements: Placement[]; layers: Record<string, 'outer' | 'inside'> }
  | { type: 'ADD_PLACEMENT'; placement: Placement }
  | { type: 'UPDATE_PLACEMENT'; placement: Placement; tag?: string }
  | { type: 'DELETE_PLACEMENT'; id: string }
  | { type: 'SET_BODY_PROFILE_FIELD'; field: BodyField; value: number }
  | { type: 'SET_BODY_SHAPE'; shape: BodyShapePreset }
  | { type: 'SET_BODY_SEX'; sex: BodySex }
  | { type: 'RESET_BODY_PROFILE' }
  | { type: 'PUSH_UNDO' }
  | { type: 'UNDO' }
  | { type: 'REDO' }

const MAX_UNDO = 50

const initialState: EditorState = {
  elements: [],
  pieces: [],
  measurements: {},
  connections: [],
  placements: [],
  selectedIds: [],
  selectedPieceId: null,
  activeTool: 'select',
  zoom: 1.0,
  pan: { x: 40, y: 40 }, // initial offset so (0,0) isn't at the very edge
  showGrid: true,
  snapEnabled: true,
  showSeamAllowance: true,
  unitSystem: 'metric',
  undoStack: [],
  redoStack: [],
  liveBase: null,
  undoTag: null,
  instructions: null,
  instructionsLoading: false,
  lastFeatures: null,
  lastMeasurements: null,
  bodyProfile: DEFAULT_BODY_PROFILE,
}

function snapshot(state: EditorState): EditorSnapshot {
  return { elements: state.elements, pieces: state.pieces, connections: state.connections, placements: state.placements }
}

// Seams and placements that involve a piece being removed go with it.
function withoutPiece(state: EditorState, pieceId: string): Pick<EditorState, 'connections' | 'placements'> {
  return {
    connections: state.connections.filter(c => c.from.pieceId !== pieceId && c.to.pieceId !== pieceId),
    placements: state.placements.filter(p => p.pieceId !== pieceId && p.hostId !== pieceId),
  }
}

// Push the current state onto the undo stack (before applying a mutation).
// A non-null `tag` coalesces consecutive edits: while state.undoTag matches,
// no new entry is pushed, so e.g. spinner clicks on cut-quantity form ONE undo step.
function pushUndo(state: EditorState, tag: string | null = null): Pick<EditorState, 'undoStack' | 'redoStack' | 'liveBase' | 'undoTag'> {
  if (tag !== null && state.undoTag === tag) {
    return { undoStack: state.undoStack, redoStack: [], liveBase: null, undoTag: tag }
  }
  return {
    undoStack: [...state.undoStack, snapshot(state)].slice(-MAX_UNDO),
    redoStack: [],
    liveBase: null,
    undoTag: tag,
  }
}

function reducer(state: EditorState, action: Action): EditorState {
  switch (action.type) {
    case 'SET_ZOOM':
      return { ...state, zoom: Math.max(0.25, Math.min(4.0, action.zoom)) }

    case 'SET_PAN':
      return { ...state, pan: action.pan }

    case 'TOGGLE_GRID':
      return { ...state, showGrid: !state.showGrid }

    case 'TOGGLE_SNAP':
      return { ...state, snapEnabled: !state.snapEnabled }

    case 'TOGGLE_SEAM_ALLOWANCE':
      return { ...state, showSeamAllowance: !state.showSeamAllowance }

    case 'SET_UNIT_SYSTEM':
      return { ...state, unitSystem: action.unit }

    case 'SET_ACTIVE_TOOL':
      return { ...state, activeTool: action.tool, selectedIds: [], selectedPieceId: null, undoTag: null }

    case 'ADD_ELEMENT': {
      const newElements = [...state.elements, action.element]
      return { ...state, ...pushUndo(state), elements: newElements }
    }

    case 'UPDATE_ELEMENT': {
      const newElements = state.elements.map(el =>
        el.id === action.element.id ? action.element : el
      )
      return { ...state, ...pushUndo(state), elements: newElements }
    }

    case 'DELETE_ELEMENTS': {
      const ids = new Set(action.ids)
      const newElements = state.elements.filter(el => !ids.has(el.id))
      // Drop connections whose edge no longer exists (and stitching along it)
      const newConnections = state.connections.filter(
        c => !ids.has(c.from.edgeId) && !ids.has(c.to.edgeId)
      )
      const newPlacements = state.placements.map(p =>
        p.stitched.some(id => ids.has(id)) ? { ...p, stitched: p.stitched.filter(id => !ids.has(id)) } : p
      )
      return { ...state, ...pushUndo(state), elements: newElements, connections: newConnections, placements: newPlacements, selectedIds: [] }
    }

    case 'SET_SELECTED':
      return { ...state, selectedIds: action.ids, selectedPieceId: null, undoTag: null }

    case 'DESELECT_ALL':
      return { ...state, selectedIds: [], selectedPieceId: null, undoTag: null }

    case 'ADD_PIECE': {
      const idSet = new Set(action.piece.elementIds)
      const updatedElements = state.elements.map(el =>
        idSet.has(el.id) ? { ...el, pieceId: action.piece.id } : el
      )
      return { ...state, ...pushUndo(state), pieces: [...state.pieces, action.piece], elements: updatedElements }
    }

    case 'UPDATE_PIECE':
      return {
        ...state,
        ...pushUndo(state, `piece:${action.piece.id}`),
        pieces: state.pieces.map(p => p.id === action.piece.id ? action.piece : p),
      }

    case 'DELETE_PIECE': {
      const piece = state.pieces.find(p => p.id === action.id)
      if (!piece) return state
      // Remove the outline elements AND any interior elements tagged with this
      // piece (grain line, dart/pleat markings from generated patterns).
      const outlineIds = new Set(piece.elementIds)
      const newElements = state.elements.filter(
        el => !outlineIds.has(el.id) && !('pieceId' in el && el.pieceId === action.id)
      )
      return {
        ...state,
        ...pushUndo(state),
        elements: newElements,
        pieces: state.pieces.filter(p => p.id !== action.id),
        ...withoutPiece(state, action.id),
        selectedPieceId: state.selectedPieceId === action.id ? null : state.selectedPieceId,
      }
    }

    case 'SELECT_PIECE':
      return { ...state, selectedPieceId: action.id, selectedIds: [], undoTag: null }

    case 'SET_MEASUREMENT':
      return { ...state, measurements: { ...state.measurements, [action.name]: action.value } }

    case 'BATCH_UPDATE_ELEMENTS': {
      const updateMap = new Map(action.elements.map(el => [el.id, el]))
      const newElements = state.elements.map(el => updateMap.has(el.id) ? updateMap.get(el.id)! : el)
      return { ...state, ...pushUndo(state), elements: newElements }
    }

    case 'LIVE_UPDATE_ELEMENTS': {
      // Applied on every mousemove during a drag/rotate. Does NOT push an undo
      // entry per frame — instead the first frame captures the pre-gesture
      // snapshot in liveBase, which PUSH_UNDO commits on mouseup.
      const updateMap = new Map(action.elements.map(el => [el.id, el]))
      const newElements = state.elements.map(el => updateMap.has(el.id) ? updateMap.get(el.id)! : el)
      return { ...state, elements: newElements, liveBase: state.liveBase ?? snapshot(state) }
    }

    case 'REMOVE_SIDE_FROM_PIECE': {
      const piece = state.pieces.find(p => p.id === action.pieceId)
      if (!piece) return state
      // Revert ALL elements of the piece to standalone (clear pieceId), then delete the piece.
      const updatedElements = state.elements.map(el =>
        piece.elementIds.includes(el.id) ? { ...el, pieceId: undefined } : el
      )
      return {
        ...state,
        ...pushUndo(state),
        elements: updatedElements,
        pieces: state.pieces.filter(p => p.id !== action.pieceId),
        ...withoutPiece(state, action.pieceId),
        selectedPieceId: state.selectedPieceId === action.pieceId ? null : state.selectedPieceId,
      }
    }

    case 'MIRROR_PIECE': {
      const srcPiece = state.pieces.find(p => p.id === action.pieceId)
      if (!srcPiece) return state
      const { newElements, newPiece } = mirrorPiece(srcPiece, state.elements, action.op)
      const taggedElements = newElements.map(el => ({ ...el, pieceId: newPiece.id }))
      return {
        ...state,
        ...pushUndo(state),
        elements: [...state.elements, ...taggedElements],
        pieces: [...state.pieces, newPiece],
        selectedPieceId: newPiece.id,
      }
    }

    case 'LOAD_STATE':
      return {
        ...initialState,
        elements: action.elements,
        pieces: action.pieces,
        measurements: action.measurements,
        connections: action.connections ?? [],
        placements: action.placements ?? [],
        instructions: action.instructions ?? null,
        lastFeatures: action.lastFeatures ?? null,
        lastMeasurements: action.lastMeasurements ?? null,
        bodyProfile: state.bodyProfile,
      }

    case 'ADD_CONNECTION': {
      const same = (a: SeamConnection['from'], b: SeamConnection['from']) => a.pieceId === b.pieceId && a.edgeId === b.edgeId
      const c = action.connection
      if (state.connections.some(o => (same(o.from, c.from) && same(o.to, c.to)) || (same(o.from, c.to) && same(o.to, c.from)))) return state
      return { ...state, ...pushUndo(state), connections: [...state.connections, c] }
    }

    case 'UPDATE_CONNECTION':
      // A tag (e.g. while dragging a range handle) makes the whole gesture one undo step.
      return {
        ...state,
        ...pushUndo(state, action.tag ?? null),
        connections: state.connections.map((c, i) => (i === action.index ? action.connection : c)),
      }

    case 'DELETE_CONNECTION':
      return { ...state, ...pushUndo(state), connections: state.connections.filter((_, i) => i !== action.index) }

    case 'SET_CONNECTIONS':
      return { ...state, ...pushUndo(state), connections: action.connections }

    case 'ADD_PLACEMENT':
      // A piece is placed on one host at a time.
      return {
        ...state,
        ...pushUndo(state),
        placements: [...state.placements.filter(p => p.pieceId !== action.placement.pieceId), action.placement],
      }

    case 'UPDATE_PLACEMENT':
      return {
        ...state,
        ...pushUndo(state, action.tag ?? null),
        placements: state.placements.map(p => (p.id === action.placement.id ? action.placement : p)),
      }

    case 'DELETE_PLACEMENT':
      return { ...state, ...pushUndo(state), placements: state.placements.filter(p => p.id !== action.id) }

    case 'APPLY_INFERRED': {
      // Re-infer: the user's own seams and placements stay; everything else is
      // replaced. An inferred seam the user already made is not added twice.
      const endKey = (e: SeamConnection['from']) => `${e.pieceId}|${e.edgeId}|${e.range?.join(',') ?? ''}|${e.side ?? ''}|${e.half ?? ''}`
      const key = (c: SeamConnection) => [endKey(c.from), endKey(c.to)].sort().join('~')
      const userSeams = state.connections.filter(c => c.source === 'user')
      const taken = new Set(userSeams.map(key))
      const userPlaced = state.placements.filter(p => p.source === 'user')
      const placedPieces = new Set(userPlaced.map(p => p.pieceId))
      return {
        ...state,
        ...pushUndo(state),
        connections: [...userSeams, ...action.connections.filter(c => !taken.has(key(c)))],
        placements: [...userPlaced, ...action.placements.filter(p => !placedPieces.has(p.pieceId))],
        // Layers the user never set come from the inference.
        pieces: state.pieces.map(p => (p.layer === undefined && action.layers[p.id] ? { ...p, layer: action.layers[p.id] } : p)),
      }
    }

    case 'SET_BODY_PROFILE_FIELD':
      return {
        ...state,
        bodyProfile: { ...state.bodyProfile, overrides: { ...state.bodyProfile.overrides, [action.field]: action.value } },
      }

    case 'SET_BODY_SEX':
      return { ...state, bodyProfile: { ...state.bodyProfile, sex: action.sex } }

    case 'SET_BODY_SHAPE':
      return { ...state, bodyProfile: { ...state.bodyProfile, shape: action.shape } }

    case 'RESET_BODY_PROFILE':
      return { ...state, bodyProfile: { ...state.bodyProfile, overrides: {} } }

    case 'SET_INSTRUCTIONS':
      return {
        ...state,
        instructions: action.instructions,
        instructionsLoading: action.loading,
        ...(action.features !== undefined ? { lastFeatures: action.features } : {}),
        ...(action.measurements !== undefined ? { lastMeasurements: action.measurements } : {}),
      }

    case 'PUSH_UNDO': {
      // Commit the drag gesture that just ended: the undo entry is the state
      // captured BEFORE the first live update. Without live updates (a plain
      // click, no movement) there is nothing to undo — push nothing.
      if (state.liveBase === null) return state
      return {
        ...state,
        undoStack: [...state.undoStack, state.liveBase].slice(-MAX_UNDO),
        redoStack: [],
        liveBase: null,
        undoTag: null,
      }
    }

    case 'UNDO': {
      if (state.undoStack.length === 0) return state
      const prev = state.undoStack[state.undoStack.length - 1]
      return {
        ...state,
        elements: prev.elements,
        pieces: prev.pieces,
        connections: prev.connections,
        placements: prev.placements,
        undoStack: state.undoStack.slice(0, -1),
        redoStack: [snapshot(state), ...state.redoStack].slice(0, MAX_UNDO),
        selectedIds: [],
        selectedPieceId: null,
        liveBase: null,
        undoTag: null,
      }
    }

    case 'REDO': {
      if (state.redoStack.length === 0) return state
      const next = state.redoStack[0]
      return {
        ...state,
        elements: next.elements,
        pieces: next.pieces,
        connections: next.connections,
        placements: next.placements,
        undoStack: [...state.undoStack, snapshot(state)].slice(-MAX_UNDO),
        redoStack: state.redoStack.slice(1),
        selectedIds: [],
        selectedPieceId: null,
        liveBase: null,
        undoTag: null,
      }
    }

    default:
      return state
  }
}

// Exported for unit tests (the reducer is pure).
export { reducer, initialState }
export type { Action }

const EditorContext = createContext<{
  state: EditorState
  dispatch: React.Dispatch<Action>
} | null>(null)

export function EditorProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  return (
    <EditorContext.Provider value={{ state, dispatch }}>
      {children}
    </EditorContext.Provider>
  )
}

export function useEditor() {
  const ctx = useContext(EditorContext)
  if (!ctx) throw new Error('useEditor must be used within EditorProvider')
  return ctx
}

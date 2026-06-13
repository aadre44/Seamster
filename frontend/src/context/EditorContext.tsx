import { createContext, useContext, useReducer, ReactNode } from 'react'
import type { CanvasElement, EditorState, GarmentFeatures, Measurements, PatternPiece, SeamConnection, SewingInstructions, ToolType, UnitSystem } from '../types'
import { mirrorPiece } from '../utils/pieceTransforms'

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
  | { type: 'LOAD_STATE'; elements: CanvasElement[]; pieces: PatternPiece[]; measurements: Record<string, number>; connections?: SeamConnection[]; instructions?: SewingInstructions | null; lastFeatures?: GarmentFeatures | null; lastMeasurements?: Measurements | null }
  | { type: 'SET_INSTRUCTIONS'; instructions: SewingInstructions | null; loading: boolean; features?: GarmentFeatures; measurements?: Measurements }
  | { type: 'PUSH_UNDO' }
  | { type: 'UNDO' }
  | { type: 'REDO' }

const MAX_UNDO = 50

const initialState: EditorState = {
  elements: [],
  pieces: [],
  measurements: {},
  connections: [],
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
  instructions: null,
  instructionsLoading: false,
  lastFeatures: null,
  lastMeasurements: null,
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
      return { ...state, activeTool: action.tool, selectedIds: [], selectedPieceId: null }

    case 'ADD_ELEMENT': {
      const newElements = [...state.elements, action.element]
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return { ...state, elements: newElements, undoStack: newUndo, redoStack: [] }
    }

    case 'UPDATE_ELEMENT': {
      const newElements = state.elements.map(el =>
        el.id === action.element.id ? action.element : el
      )
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return { ...state, elements: newElements, undoStack: newUndo, redoStack: [] }
    }

    case 'DELETE_ELEMENTS': {
      const ids = new Set(action.ids)
      const newElements = state.elements.filter(el => !ids.has(el.id))
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return { ...state, elements: newElements, selectedIds: [], undoStack: newUndo, redoStack: [] }
    }

    case 'SET_SELECTED':
      return { ...state, selectedIds: action.ids, selectedPieceId: null }

    case 'DESELECT_ALL':
      return { ...state, selectedIds: [], selectedPieceId: null }

    case 'ADD_PIECE': {
      const idSet = new Set(action.piece.elementIds)
      const updatedElements = state.elements.map(el =>
        idSet.has(el.id) ? { ...el, pieceId: action.piece.id } : el
      )
      return { ...state, pieces: [...state.pieces, action.piece], elements: updatedElements }
    }

    case 'UPDATE_PIECE':
      return { ...state, pieces: state.pieces.map(p => p.id === action.piece.id ? action.piece : p) }

    case 'DELETE_PIECE': {
      const keepPieceId = state.selectedPieceId === action.id ? null : state.selectedPieceId
      return { ...state, pieces: state.pieces.filter(p => p.id !== action.id), selectedPieceId: keepPieceId }
    }

    case 'SELECT_PIECE':
      return { ...state, selectedPieceId: action.id, selectedIds: [] }

    case 'SET_MEASUREMENT':
      return { ...state, measurements: { ...state.measurements, [action.name]: action.value } }

    case 'BATCH_UPDATE_ELEMENTS': {
      const updateMap = new Map(action.elements.map(el => [el.id, el]))
      const newElements = state.elements.map(el => updateMap.has(el.id) ? updateMap.get(el.id)! : el)
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return { ...state, elements: newElements, undoStack: newUndo, redoStack: [] }
    }

    case 'LIVE_UPDATE_ELEMENTS': {
      // Like BATCH_UPDATE_ELEMENTS but does NOT push to the undo stack (used during live drag/rotate)
      const updateMap = new Map(action.elements.map(el => [el.id, el]))
      const newElements = state.elements.map(el => updateMap.has(el.id) ? updateMap.get(el.id)! : el)
      return { ...state, elements: newElements }
    }

    case 'REMOVE_SIDE_FROM_PIECE': {
      const piece = state.pieces.find(p => p.id === action.pieceId)
      if (!piece) return state
      // Revert ALL elements of the piece to standalone (clear pieceId), then delete the piece.
      const updatedElements = state.elements.map(el =>
        piece.elementIds.includes(el.id) ? { ...el, pieceId: undefined } : el
      )
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return {
        ...state,
        elements: updatedElements,
        pieces: state.pieces.filter(p => p.id !== action.pieceId),
        selectedPieceId: state.selectedPieceId === action.pieceId ? null : state.selectedPieceId,
        undoStack: newUndo,
        redoStack: [],
      }
    }

    case 'MIRROR_PIECE': {
      const srcPiece = state.pieces.find(p => p.id === action.pieceId)
      if (!srcPiece) return state
      const { newElements, newPiece } = mirrorPiece(srcPiece, state.elements, action.op)
      const taggedElements = newElements.map(el => ({ ...el, pieceId: newPiece.id }))
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return {
        ...state,
        elements: [...state.elements, ...taggedElements],
        pieces: [...state.pieces, newPiece],
        selectedPieceId: newPiece.id,
        undoStack: newUndo,
        redoStack: [],
      }
    }

    case 'LOAD_STATE':
      return {
        ...initialState,
        elements: action.elements,
        pieces: action.pieces,
        measurements: action.measurements,
        connections: action.connections ?? [],
        instructions: action.instructions ?? null,
        lastFeatures: action.lastFeatures ?? null,
        lastMeasurements: action.lastMeasurements ?? null,
        undoStack: [],
        redoStack: [],
      }

    case 'SET_INSTRUCTIONS':
      return {
        ...state,
        instructions: action.instructions,
        instructionsLoading: action.loading,
        ...(action.features !== undefined ? { lastFeatures: action.features } : {}),
        ...(action.measurements !== undefined ? { lastMeasurements: action.measurements } : {}),
      }

    case 'PUSH_UNDO': {
      const newUndo = [...state.undoStack, state.elements].slice(-MAX_UNDO)
      return { ...state, undoStack: newUndo, redoStack: [] }
    }

    case 'UNDO': {
      if (state.undoStack.length === 0) return state
      const prev = state.undoStack[state.undoStack.length - 1]
      return {
        ...state,
        elements: prev,
        undoStack: state.undoStack.slice(0, -1),
        redoStack: [state.elements, ...state.redoStack].slice(0, MAX_UNDO),
        selectedIds: [],
      }
    }

    case 'REDO': {
      if (state.redoStack.length === 0) return state
      const next = state.redoStack[0]
      return {
        ...state,
        elements: next,
        undoStack: [...state.undoStack, state.elements].slice(-MAX_UNDO),
        redoStack: state.redoStack.slice(1),
        selectedIds: [],
      }
    }

    default:
      return state
  }
}

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

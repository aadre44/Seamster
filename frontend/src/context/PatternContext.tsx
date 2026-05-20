import { createContext, useContext, useReducer, ReactNode } from 'react'
import type { GarmentFeatures, Measurements, WizardStep } from '../types'

interface PatternState {
  step: WizardStep
  frontImage: File | null
  backImage: File | null
  detectedFeatures: GarmentFeatures | null
  confirmedFeatures: GarmentFeatures | null
  measurements: Measurements | null
  patternSvg: string | null
  error: string | null
}

type Action =
  | { type: 'SET_STEP'; step: WizardStep }
  | { type: 'SET_IMAGES'; front: File; back?: File }
  | { type: 'SET_DETECTED_FEATURES'; features: GarmentFeatures }
  | { type: 'SET_CONFIRMED_FEATURES'; features: GarmentFeatures }
  | { type: 'SET_MEASUREMENTS'; measurements: Measurements }
  | { type: 'SET_PATTERN_SVG'; svg: string }
  | { type: 'SET_ERROR'; error: string }
  | { type: 'CLEAR_ERROR' }

const initialState: PatternState = {
  step: 1,
  frontImage: null,
  backImage: null,
  detectedFeatures: null,
  confirmedFeatures: null,
  measurements: null,
  patternSvg: null,
  error: null,
}

function reducer(state: PatternState, action: Action): PatternState {
  switch (action.type) {
    case 'SET_STEP':
      return { ...state, step: action.step }
    case 'SET_IMAGES':
      return { ...state, frontImage: action.front, backImage: action.back ?? null }
    case 'SET_DETECTED_FEATURES':
      return { ...state, detectedFeatures: action.features }
    case 'SET_CONFIRMED_FEATURES':
      return { ...state, confirmedFeatures: action.features }
    case 'SET_MEASUREMENTS':
      return { ...state, measurements: action.measurements }
    case 'SET_PATTERN_SVG':
      return { ...state, patternSvg: action.svg }
    case 'SET_ERROR':
      return { ...state, error: action.error }
    case 'CLEAR_ERROR':
      return { ...state, error: null }
    default:
      return state
  }
}

const PatternContext = createContext<{
  state: PatternState
  dispatch: React.Dispatch<Action>
} | null>(null)

export function PatternProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  return (
    <PatternContext.Provider value={{ state, dispatch }}>
      {children}
    </PatternContext.Provider>
  )
}

export function usePattern() {
  const ctx = useContext(PatternContext)
  if (!ctx) throw new Error('usePattern must be used within PatternProvider')
  return ctx
}

/**
 * Single API client for all backend calls.
 *
 * Base URL resolution:
 *  - `VITE_API_URL` env var when set (e.g. `http://192.168.1.20:8000/api` for
 *    LAN/phone testing, or an absolute URL in a split deploy),
 *  - otherwise `/api`, served by the Vite dev proxy (vite.config.ts) in
 *    development and by same-origin routing in production.
 *
 * All wrappers throw `Error` with the FastAPI `detail` message when available,
 * so callers can show `e.message` directly.
 */
import type {
  CanvasElement,
  GarmentFeatures,
  Measurements,
  PatternPiece,
  SeamConnection,
  SewingInstructions,
  ShapeMode,
} from './types'

export const API_BASE: string = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/+$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }))
    throw new Error(body.detail ?? `Server error ${res.status}`)
  }
  return res.json() as Promise<T>
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

// ── /analyze ──────────────────────────────────────────────────────────────────

export function analyzeGarment(
  garmentType: string,
  frontImage: File,
  backImage?: File | null,
): Promise<GarmentFeatures> {
  const fd = new FormData()
  fd.append('garment_type', garmentType)
  fd.append('front_image', frontImage)
  if (backImage) fd.append('back_image', backImage)
  return request<GarmentFeatures>('/analyze', { method: 'POST', body: fd })
}

// ── /generate ─────────────────────────────────────────────────────────────────

/** The .psnap document returned by the parametric engine. */
export interface GeneratedPattern {
  version: number
  elements: CanvasElement[]
  pieces?: PatternPiece[]
  measurements?: Record<string, number>
  connections?: SeamConnection[]
  notice?: string
}

export function generatePattern(
  features: GarmentFeatures,
  measurements: Measurements,
  shapeMode: ShapeMode = 'modifiers',
): Promise<GeneratedPattern> {
  return request<GeneratedPattern>(
    '/generate',
    jsonInit({ features, measurements, shape_mode: shapeMode }),
  )
}

// ── /instructions ─────────────────────────────────────────────────────────────

/** Piece summary the instruction generator expects (snake_case API contract). */
export interface InstructionPieceInfo {
  name: string
  cut_qty: number
  on_fold: boolean
  seam_allowance: number
  notes: string
}

export function generateInstructions(
  features: GarmentFeatures,
  measurements: Measurements,
  pieces: InstructionPieceInfo[],
): Promise<SewingInstructions> {
  return request<SewingInstructions>(
    '/instructions',
    jsonInit({ features, measurements, pieces }),
  )
}

// ── /export/pdf ───────────────────────────────────────────────────────────────

export interface ExportPdfRequest {
  elements: CanvasElement[]
  pieces: PatternPiece[]
  paper_size: string
  single_page: boolean
  instructions?: SewingInstructions
}

export async function exportPdf(payload: ExportPdfRequest): Promise<Blob> {
  const res = await fetch(`${API_BASE}/export/pdf`, jsonInit(payload))
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  return res.blob()
}

// ── /provider ─────────────────────────────────────────────────────────────────

export interface ProviderOption {
  key: string
  label: string
}

export interface ProviderState {
  active: string
  model: string
  providers: ProviderOption[]
}

export function getProvider(): Promise<ProviderState> {
  return request<ProviderState>('/provider')
}

export function setProvider(key: string): Promise<ProviderState> {
  return request<ProviderState>('/provider', jsonInit({ provider: key }))
}

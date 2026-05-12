/**
 * Phase 2 AI Assist workflow — three steps inside a modal:
 *   Step 1: Upload garment photo(s) → POST /api/analyze
 *   Step 2: Review / correct detected features
 *   Step 3: Generate pattern → POST /api/generate → load into editor
 */
import { useState, useRef } from 'react'
import { useEditor } from '../context/EditorContext'
import type { SkirtFeatures, Measurements } from '../types'

const API = 'http://localhost:8000/api'

type Step = 'upload' | 'review' | 'generating'

interface Props {
  onClose: () => void
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-xs font-medium text-gray-700 mb-1">{children}</label>
}

function Select({ value, onChange, options }: {
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
    >
      {options.map(o => (
        <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>
      ))}
    </select>
  )
}

function NumberField({ value, onChange, min, max, step = 0.5 }: {
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  step?: number
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      onChange={e => onChange(parseFloat(e.target.value) || min)}
      className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
    />
  )
}

// ── Step 1: Upload ────────────────────────────────────────────────────────────

function UploadStep({
  onAnalyzed,
  onClose,
}: {
  onAnalyzed: (f: SkirtFeatures) => void
  onClose: () => void
}) {
  const frontRef = useRef<HTMLInputElement>(null)
  const backRef = useRef<HTMLInputElement>(null)
  const [frontFile, setFrontFile] = useState<File | null>(null)
  const [backFile, setBackFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleAnalyze = async () => {
    if (!frontFile) { setError('Please select a front photo.'); return }
    setLoading(true); setError('')
    try {
      const fd = new FormData()
      fd.append('front_image', frontFile)
      if (backFile) fd.append('back_image', backFile)

      const res = await fetch(`${API}/analyze`, { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `Server error ${res.status}`)
      }
      const features: SkirtFeatures = await res.json()
      onAnalyzed(features)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-600">
        Upload a photo of the skirt you want to replicate. The AI will detect its style
        and create a starting pattern for you to refine.
      </p>

      {/* Front photo */}
      <div>
        <Label>Front photo (required)</Label>
        <div
          onClick={() => frontRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors
            ${frontFile ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}`}
        >
          {frontFile ? (
            <span className="text-xs text-blue-700 font-medium">{frontFile.name}</span>
          ) : (
            <span className="text-xs text-gray-500">Click to select JPEG or PNG (max 10 MB)</span>
          )}
        </div>
        <input
          ref={frontRef}
          type="file"
          accept="image/jpeg,image/png"
          className="hidden"
          onChange={e => setFrontFile(e.target.files?.[0] ?? null)}
        />
      </div>

      {/* Back photo */}
      <div>
        <Label>Back photo (optional — improves accuracy)</Label>
        <div
          onClick={() => backRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors
            ${backFile ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}`}
        >
          {backFile ? (
            <span className="text-xs text-blue-700 font-medium">{backFile.name}</span>
          ) : (
            <span className="text-xs text-gray-500">Click to select JPEG or PNG (optional)</span>
          )}
        </div>
        <input
          ref={backRef}
          type="file"
          accept="image/jpeg,image/png"
          className="hidden"
          onChange={e => setBackFile(e.target.files?.[0] ?? null)}
        />
      </div>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>
      )}

      <div className="flex gap-2 justify-end pt-2">
        <button onClick={onClose}
          className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50">
          Cancel
        </button>
        <button
          onClick={handleAnalyze}
          disabled={loading || !frontFile}
          className="px-4 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {loading ? (
            <>
              <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Analysing your skirt…
            </>
          ) : 'Analyse Photo'}
        </button>
      </div>
    </div>
  )
}

// ── Step 2: Review ────────────────────────────────────────────────────────────

const SILHOUETTES = ['straight', 'a_line', 'pencil', 'circle', 'gathered', 'pleated', 'wrap']
const LENGTH_CATS = ['mini', 'above_knee', 'knee', 'midi', 'maxi']
const WAISTBAND_TYPES = ['straight', 'contoured', 'elastic', 'facing', 'yoke']
const CLOSURE_TYPES = ['center_back_zip', 'side_zip', 'button_fly', 'hook_and_eye', 'none']
const CLOSURE_POSITIONS = ['center_back', 'left_side', 'right_side', 'center_front']

function ReviewStep({
  features,
  measurements,
  onGenerate,
  onBack,
}: {
  features: SkirtFeatures
  measurements: Measurements
  onGenerate: (f: SkirtFeatures, m: Measurements) => void
  onBack: () => void
}) {
  const [f, setF] = useState<SkirtFeatures>(features)
  const [m, setM] = useState<Measurements>(measurements)

  const lowConfidence = f.confidence < 0.5

  return (
    <div className="space-y-4 overflow-y-auto max-h-[60vh] pr-1">
      {lowConfidence && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-800">
          <strong>Low confidence ({Math.round(f.confidence * 100)}%)</strong> — the AI wasn't sure
          about some features. Please review each field carefully before generating.
        </div>
      )}

      {f.notes && (
        <p className="text-xs text-gray-500 italic bg-gray-50 rounded px-3 py-2">{f.notes}</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        {/* Silhouette */}
        <div>
          <Label>Silhouette</Label>
          <Select value={f.silhouette} onChange={v => setF(p => ({ ...p, silhouette: v as SkirtFeatures['silhouette'] }))} options={SILHOUETTES} />
        </div>

        {/* Length category */}
        <div>
          <Label>Length</Label>
          <Select value={f.length_category} onChange={v => setF(p => ({ ...p, length_category: v as SkirtFeatures['length_category'] }))} options={LENGTH_CATS} />
        </div>

        {/* Waistband type */}
        <div>
          <Label>Waistband type</Label>
          <Select value={f.waistband.type} onChange={v => setF(p => ({ ...p, waistband: { ...p.waistband, type: v as SkirtFeatures['waistband']['type'] } }))} options={WAISTBAND_TYPES} />
        </div>

        {/* Waistband width */}
        <div>
          <Label>Waistband width (cm)</Label>
          <NumberField value={f.waistband.width_cm_estimate} min={1} max={15}
            onChange={v => setF(p => ({ ...p, waistband: { ...p.waistband, width_cm_estimate: v } }))} />
        </div>

        {/* Closure type */}
        <div>
          <Label>Closure type</Label>
          <Select value={f.closure.type} onChange={v => setF(p => ({ ...p, closure: { ...p.closure, type: v as SkirtFeatures['closure']['type'] } }))} options={CLOSURE_TYPES} />
        </div>

        {/* Closure position */}
        <div>
          <Label>Closure position</Label>
          <Select value={f.closure.position} onChange={v => setF(p => ({ ...p, closure: { ...p.closure, position: v as SkirtFeatures['closure']['position'] } }))} options={CLOSURE_POSITIONS} />
        </div>

        {/* Darts — front */}
        <div>
          <Label>Front darts (0–4)</Label>
          <NumberField value={f.darts.front} min={0} max={4} step={1}
            onChange={v => setF(p => ({ ...p, darts: { ...p.darts, front: Math.round(v) } }))} />
        </div>

        {/* Darts — back */}
        <div>
          <Label>Back darts (0–4)</Label>
          <NumberField value={f.darts.back} min={0} max={4} step={1}
            onChange={v => setF(p => ({ ...p, darts: { ...p.darts, back: Math.round(v) } }))} />
        </div>
      </div>

      {/* Measurements */}
      <div className="border-t border-gray-200 pt-3">
        <p className="text-xs font-semibold text-gray-700 mb-2">Your measurements (cm)</p>
        <div className="grid grid-cols-2 gap-3">
          {[
            { key: 'waist_cm', label: 'Waist', min: 50, max: 160 },
            { key: 'hip_cm', label: 'Hip', min: 60, max: 180 },
            { key: 'waist_to_hip_cm', label: 'Waist to hip', min: 10, max: 35 },
            { key: 'length_cm', label: 'Skirt length', min: 20, max: 150 },
            { key: 'seam_allowance_cm', label: 'Seam allowance', min: 0.5, max: 5 },
          ].map(({ key, label, min, max }) => (
            <div key={key}>
              <Label>{label}</Label>
              <NumberField
                value={(m as unknown as Record<string, number>)[key] ?? 0}
                min={min}
                max={max}
                onChange={v => setM(prev => ({ ...prev, [key]: v }))}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-2 justify-end pt-2 border-t border-gray-200">
        <button onClick={onBack}
          className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50">
          ← Back
        </button>
        <button onClick={() => onGenerate(f, m)}
          className="px-4 py-1.5 text-xs bg-green-600 text-white rounded hover:bg-green-700">
          Generate Pattern
        </button>
      </div>
    </div>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────

export default function AIAssistModal({ onClose }: Props) {
  const { state, dispatch } = useEditor()
  const [step, setStep] = useState<Step>('upload')
  const [features, setFeatures] = useState<SkirtFeatures | null>(null)
  const [genError, setGenError] = useState('')

  // Pre-fill measurements from current editor state
  const currentMeasurements: Measurements = {
    waist_cm: state.measurements['waist'] ?? 76,
    hip_cm: state.measurements['hip'] ?? 94,
    waist_to_hip_cm: state.measurements['waistToHip'] ?? 21,
    length_cm: state.measurements['skirtLength'] ?? 65,
    seam_allowance_cm: 1.5,
    hem_allowance_cm: 3.0,
    waistband_width_cm: 3.0,
  }

  const handleAnalyzed = (f: SkirtFeatures) => {
    setFeatures(f)
    setStep('review')
  }

  const handleGenerate = async (f: SkirtFeatures, m: Measurements) => {
    setStep('generating')
    setGenError('')
    try {
      const res = await fetch(`${API}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ features: f, measurements: m }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `Server error ${res.status}`)
      }
      const psnap = await res.json()
      if (!psnap.elements || !Array.isArray(psnap.elements)) throw new Error('Invalid pattern data')

      const hasContent = state.elements.length > 0 || state.pieces.length > 0
      if (hasContent && !window.confirm('Loading the generated pattern will replace the current canvas. Continue?')) {
        setStep('review')
        return
      }

      dispatch({
        type: 'LOAD_STATE',
        elements: psnap.elements,
        pieces: psnap.pieces ?? [],
        measurements: psnap.measurements ?? {},
      })
      onClose()
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : String(e))
      setStep('review')
    }
  }

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-xl shadow-2xl w-[520px] max-w-[95vw] max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">AI Pattern Assistant</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {step === 'upload' && 'Step 1 of 2 — Upload garment photo'}
              {step === 'review' && 'Step 2 of 2 — Review detected features'}
              {step === 'generating' && 'Generating your pattern…'}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 flex-1 overflow-y-auto">
          {step === 'upload' && (
            <UploadStep onAnalyzed={handleAnalyzed} onClose={onClose} />
          )}
          {(step === 'review') && features && (
            <>
              {genError && (
                <div className="mb-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{genError}</div>
              )}
              <ReviewStep
                features={features}
                measurements={currentMeasurements}
                onGenerate={handleGenerate}
                onBack={() => setStep('upload')}
              />
            </>
          )}
          {step === 'generating' && (
            <div className="flex flex-col items-center justify-center py-12 gap-4">
              <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-sm text-gray-600">Building your pattern…</p>
              <p className="text-xs text-gray-400">This usually takes a few seconds.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

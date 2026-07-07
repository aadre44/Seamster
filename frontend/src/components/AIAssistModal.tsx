/**
 * Phase 2 AI Assist workflow — modal with three steps:
 *   Step 1: Select garment type + upload photo(s) → POST /api/analyze
 *   Step 2: Review / correct detected features
 *   Step 3: Generating pattern → POST /api/generate → load into editor,
 *           then the modal closes so the result can be inspected. When a
 *           photo was used, the refine context is handed up via onGenerated
 *           and the persistent "Refine from Photo" header button takes over
 *           (RefinePhotoModal) — refine stays available at any time.
 */
import { useState, useRef } from 'react'
import { useEditor } from '../context/EditorContext'
import { analyzeGarment, generatePattern } from '../api'
import type { RefineContext } from './RefinePhotoModal'
import type { GarmentFeatures, GarmentType, Measurements, ShapeMode, WaistbandType } from '../types'
import { GARMENT_TYPES } from '../types'

type Step = 'upload' | 'review' | 'generating'

interface Props {
  onClose: () => void
  /** Called after a successful photo-based generate with everything the
   * refine pass needs; the parent keeps it so refine stays available. */
  onGenerated?: (ctx: RefineContext) => void
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

// ── Dev mode: fixture JSON extractor ─────────────────────────────────────────

/**
 * Extract the first complete JSON object from a string.
 * Handles files like example4.txt that concatenate two JSON objects
 * (the analysis response followed by the generated pattern).
 */
function extractFirstJsonObject(text: string): string | null {
  const start = text.indexOf('{')
  if (start === -1) return null
  let depth = 0
  let inString = false
  let escape = false
  for (let i = start; i < text.length; i++) {
    const ch = text[i]
    if (escape) { escape = false; continue }
    if (ch === '\\' && inString) { escape = true; continue }
    if (ch === '"') { inString = !inString; continue }
    if (inString) continue
    if (ch === '{') depth++
    if (ch === '}') { depth--; if (depth === 0) return text.slice(start, i + 1) }
  }
  return null
}

function parseFixtureFeatures(text: string): GarmentFeatures {
  // Try full text first (single-object files), then first-object extraction
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    const first = extractFirstJsonObject(text)
    if (!first) throw new Error('No valid JSON object found in the pasted text.')
    parsed = JSON.parse(first)
  }
  const obj = parsed as Record<string, unknown>
  if (!obj.garment_type)
    throw new Error('This JSON does not look like an analysis response — missing garment_type.')
  if (!obj.silhouette || !obj.closure)
    throw new Error('Missing required fields (silhouette, closure). Paste the analysis JSON, not the pattern JSON.')
  return obj as unknown as GarmentFeatures
}

// ── Step 1: Upload ────────────────────────────────────────────────────────────

type UploadMode = 'photo' | 'fixture'

function UploadStep({
  onAnalyzed,
  onClose,
  frontFile,
  backFile,
  setFrontFile,
  setBackFile,
}: {
  onAnalyzed: (f: GarmentFeatures) => void
  onClose: () => void
  frontFile: File | null
  backFile: File | null
  setFrontFile: (f: File | null) => void
  setBackFile: (f: File | null) => void
}) {
  const frontRef = useRef<HTMLInputElement>(null)
  const backRef = useRef<HTMLInputElement>(null)
  const fixtureFileRef = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<UploadMode>('photo')
  const [garmentType, setGarmentType] = useState<GarmentType>('skirt')
  const [fixtureText, setFixtureText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [forceContours, setForceContours] = useState(false)

  const handleAnalyze = async () => {
    if (!frontFile) { setError('Please select a front photo.'); return }
    setLoading(true); setError('')
    try {
      const features = await analyzeGarment(garmentType, frontFile, backFile, forceContours)
      onAnalyzed(features)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const handleFixtureFile = (file: File) => {
    const reader = new FileReader()
    reader.onload = e => setFixtureText((e.target?.result as string) ?? '')
    reader.readAsText(file)
  }

  const handleLoadFixture = () => {
    setError('')
    try {
      const features = parseFixtureFeatures(fixtureText)
      // Fixture mode has no photo — clear any picked files so the done step
      // doesn't offer a photo refine against an unrelated image.
      setFrontFile(null)
      setBackFile(null)
      onAnalyzed(features)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-4">
      {/* Mode toggle */}
      <div className="flex rounded-lg border border-gray-200 overflow-hidden text-xs">
        <button
          onClick={() => { setMode('photo'); setError('') }}
          className={`flex-1 py-1.5 font-medium transition-colors ${
            mode === 'photo'
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          Photo upload
        </button>
        <button
          onClick={() => { setMode('fixture'); setError('') }}
          className={`flex-1 py-1.5 font-medium transition-colors ${
            mode === 'fixture'
              ? 'bg-amber-500 text-white'
              : 'bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          Dev — load saved analysis
        </button>
      </div>

      {mode === 'photo' && (
        <>
          {/* Garment type selector */}
          <div>
            <Label>Garment type</Label>
            <Select
              value={garmentType}
              onChange={v => setGarmentType(v as GarmentType)}
              options={GARMENT_TYPES}
            />
          </div>

          <p className="text-xs text-gray-600">
            Upload a photo of the {garmentType} you want to replicate. The AI will detect its
            style and create a starting pattern for you to refine.
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

          {/* Dev-only: force the vision model to trace every piece as a contour,
              so the contour-patternizing path can be tested on any photo. */}
          {import.meta.env.DEV && (
            <label className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded px-3 py-2 text-[11px] text-amber-800 cursor-pointer">
              <input
                type="checkbox"
                checked={forceContours}
                onChange={e => setForceContours(e.target.checked)}
                className="w-3.5 h-3.5 accent-amber-600"
              />
              <span>
                <span className="font-semibold">Force vision contours (dev)</span> — trace every
                visible piece as a photo contour so vision drafts can be inspected
              </span>
            </label>
          )}
        </>
      )}

      {mode === 'fixture' && (
        <>
          <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-800">
            Paste or load a saved analysis response to skip the LLM call. Accepts the full
            contents of files like <code>example4.txt</code> — the features JSON is extracted
            automatically even if the file also contains a generated pattern.
          </div>

          {/* File picker */}
          <div>
            <Label>Load from file</Label>
            <div
              onClick={() => fixtureFileRef.current?.click()}
              className="border-2 border-dashed border-amber-300 rounded-lg p-3 text-center cursor-pointer hover:border-amber-400 transition-colors"
            >
              <span className="text-xs text-amber-700">
                {fixtureText ? 'File loaded — or click to replace' : 'Click to select .txt or .json'}
              </span>
            </div>
            <input
              ref={fixtureFileRef}
              type="file"
              accept=".txt,.json"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) handleFixtureFile(f)
              }}
            />
          </div>

          {/* Paste area */}
          <div>
            <Label>Or paste JSON directly</Label>
            <textarea
              value={fixtureText}
              onChange={e => setFixtureText(e.target.value)}
              rows={8}
              placeholder={'{\n  "garment_type": "shirt",\n  "silhouette": "fitted",\n  ...\n}'}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs font-mono resize-y focus:outline-none focus:ring-1 focus:ring-amber-400"
            />
          </div>
        </>
      )}

      {error && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>
      )}

      <div className="flex gap-2 justify-end pt-2">
        <button onClick={onClose}
          className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50">
          Cancel
        </button>

        {mode === 'photo' ? (
          <button
            onClick={handleAnalyze}
            disabled={loading || !frontFile}
            className="px-4 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {loading ? (
              <>
                <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Analysing your {garmentType}…
              </>
            ) : 'Analyse Photo'}
          </button>
        ) : (
          <button
            onClick={handleLoadFixture}
            disabled={!fixtureText.trim()}
            className="px-4 py-1.5 text-xs bg-amber-500 text-white rounded hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Load Analysis
          </button>
        )}
      </div>
    </div>
  )
}

// ── Step 2: Review ────────────────────────────────────────────────────────────

const WAISTBAND_TYPES = ['straight', 'contoured', 'elastic', 'facing', 'yoke']
const CLOSURE_TYPES = [
  'center_back_zip', 'side_zip', 'button_fly', 'hook_and_eye',
  'center_front_zip', 'button_front', 'snap_front', 'double_breasted', 'none',
]
const CLOSURE_POSITIONS = ['center_back', 'left_side', 'right_side', 'center_front']

type MeasurementField = { key: string; label: string; min: number; max: number }

const MEASUREMENT_FIELDS: Record<string, MeasurementField[]> = {
  skirt: [
    { key: 'waist_cm', label: 'Waist', min: 50, max: 160 },
    { key: 'hip_cm', label: 'Hip', min: 60, max: 180 },
    { key: 'waist_to_hip_cm', label: 'Waist to hip', min: 10, max: 35 },
    { key: 'length_cm', label: 'Length', min: 20, max: 150 },
    { key: 'seam_allowance_cm', label: 'Seam allowance', min: 0.5, max: 5 },
  ],
  shirt: [
    { key: 'waist_cm', label: 'Waist', min: 50, max: 160 },
    { key: 'hip_cm', label: 'Hip', min: 60, max: 180 },
    { key: 'chest_cm', label: 'Chest/Bust', min: 60, max: 200 },
    { key: 'shoulder_width_cm', label: 'Shoulder width', min: 25, max: 70 },
    { key: 'arm_length_cm', label: 'Arm length', min: 40, max: 90 },
    { key: 'length_cm', label: 'Body length', min: 20, max: 150 },
    { key: 'seam_allowance_cm', label: 'Seam allowance', min: 0.5, max: 5 },
  ],
  pants: [
    { key: 'waist_cm', label: 'Waist', min: 50, max: 160 },
    { key: 'hip_cm', label: 'Hip', min: 60, max: 180 },
    { key: 'waist_to_hip_cm', label: 'Waist to hip', min: 10, max: 35 },
    { key: 'rise_cm', label: 'Rise', min: 15, max: 45 },
    { key: 'inseam_cm', label: 'Inseam', min: 40, max: 110 },
    { key: 'seam_allowance_cm', label: 'Seam allowance', min: 0.5, max: 5 },
  ],
}
MEASUREMENT_FIELDS['blouse'] = MEASUREMENT_FIELDS['shirt']
MEASUREMENT_FIELDS['vest'] = MEASUREMENT_FIELDS['shirt']
MEASUREMENT_FIELDS['bodice'] = MEASUREMENT_FIELDS['shirt']
MEASUREMENT_FIELDS['trousers'] = MEASUREMENT_FIELDS['pants']
MEASUREMENT_FIELDS['dress'] = [
  { key: 'waist_cm', label: 'Waist', min: 50, max: 160 },
  { key: 'hip_cm', label: 'Hip', min: 60, max: 180 },
  { key: 'waist_to_hip_cm', label: 'Waist to hip', min: 10, max: 35 },
  { key: 'chest_cm', label: 'Chest/Bust', min: 60, max: 200 },
  { key: 'shoulder_width_cm', label: 'Shoulder width', min: 25, max: 70 },
  { key: 'arm_length_cm', label: 'Arm length', min: 40, max: 90 },
  { key: 'length_cm', label: 'Body length', min: 20, max: 160 },
  { key: 'seam_allowance_cm', label: 'Seam allowance', min: 0.5, max: 5 },
]
MEASUREMENT_FIELDS['jacket'] = [
  { key: 'waist_cm', label: 'Waist', min: 50, max: 160 },
  { key: 'hip_cm', label: 'Hip', min: 60, max: 180 },
  { key: 'chest_cm', label: 'Chest/Bust', min: 60, max: 200 },
  { key: 'shoulder_width_cm', label: 'Shoulder width', min: 25, max: 70 },
  { key: 'arm_length_cm', label: 'Arm length', min: 40, max: 90 },
  { key: 'length_cm', label: 'Body length', min: 20, max: 120 },
  { key: 'seam_allowance_cm', label: 'Seam allowance', min: 0.5, max: 5 },
]
MEASUREMENT_FIELDS['blazer'] = MEASUREMENT_FIELDS['jacket']

function ReviewStep({
  features,
  measurements,
  onGenerate,
  onBack,
}: {
  features: GarmentFeatures
  measurements: Measurements
  onGenerate: (f: GarmentFeatures, m: Measurements, shapeMode: ShapeMode) => void
  onBack: () => void
}) {
  const [f, setF] = useState<GarmentFeatures>(features)
  const [m, setM] = useState<Measurements>(measurements)
  const [shapeMode, setShapeMode] = useState<ShapeMode>('modifiers')

  const lowConfidence = f.confidence < 0.5
  const isPatternSupported = ['skirt', 'shirt', 'blouse', 'pants', 'trousers', 'dress', 'jacket', 'blazer', 'vest', 'bodice'].includes(f.garment_type)
  // Shape-aware garments expose the silhouette-generation mode toggle.
  const isShapeAware = ['vest', 'bodice'].includes(f.garment_type)

  return (
    <div className="space-y-4 overflow-y-auto max-h-[60vh] pr-1">
      {/* Garment type badge */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-gray-500">Garment type:</span>
        <span className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded px-2 py-0.5 capitalize">
          {f.garment_type}
        </span>
        {!isPatternSupported && (
          <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
            measurements-only pattern
          </span>
        )}
      </div>

      {lowConfidence && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-800">
          <strong>Low confidence ({Math.round(f.confidence * 100)}%)</strong> — the AI wasn't sure
          about some features. Please review each field carefully before generating.
        </div>
      )}

      {!isPatternSupported && (
        <div className="bg-blue-50 border border-blue-200 rounded px-3 py-2 text-xs text-blue-800">
          Automated pattern blocks for <strong>{f.garment_type}</strong> are coming soon.
          Generating now will load your measurements into an empty canvas for manual drafting.
        </div>
      )}

      {f.notes && (
        <p className="text-xs text-gray-500 italic bg-gray-50 rounded px-3 py-2">{f.notes}</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        {/* Silhouette */}
        <div>
          <Label>Silhouette</Label>
          <input
            type="text"
            value={f.silhouette}
            onChange={e => setF(p => ({ ...p, silhouette: e.target.value }))}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
          />
        </div>

        {/* Length category */}
        <div>
          <Label>Length</Label>
          <input
            type="text"
            value={f.length_category}
            onChange={e => setF(p => ({ ...p, length_category: e.target.value }))}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
          />
        </div>

        {/* Closure type */}
        <div>
          <Label>Closure type</Label>
          <Select
            value={f.closure.type}
            onChange={v => setF(p => ({ ...p, closure: { ...p.closure, type: v as GarmentFeatures['closure']['type'] } }))}
            options={CLOSURE_TYPES}
          />
        </div>

        {/* Closure position */}
        <div>
          <Label>Closure position</Label>
          <Select
            value={f.closure.position}
            onChange={v => setF(p => ({ ...p, closure: { ...p.closure, position: v as GarmentFeatures['closure']['position'] } }))}
            options={CLOSURE_POSITIONS}
          />
        </div>

        {/* Waistband — only if detected */}
        {f.waistband && (
          <>
            <div>
              <Label>Waistband type</Label>
              <Select
                value={f.waistband.type}
                onChange={v => setF(p => ({ ...p, waistband: { ...p.waistband!, type: v as WaistbandType } }))}
                options={WAISTBAND_TYPES}
              />
            </div>
            <div>
              <Label>Waistband width (cm)</Label>
              <NumberField
                value={f.waistband.width_cm_estimate}
                min={1}
                max={15}
                onChange={v => setF(p => ({ ...p, waistband: { ...p.waistband!, width_cm_estimate: v } }))}
              />
            </div>
          </>
        )}

        {/* Darts — only if detected */}
        {f.darts && (
          <>
            <div>
              <Label>Front darts (0–4)</Label>
              <NumberField
                value={f.darts.front}
                min={0}
                max={4}
                step={1}
                onChange={v => setF(p => ({ ...p, darts: { ...p.darts!, front: Math.round(v) } }))}
              />
            </div>
            <div>
              <Label>Back darts (0–4)</Label>
              <NumberField
                value={f.darts.back}
                min={0}
                max={4}
                step={1}
                onChange={v => setF(p => ({ ...p, darts: { ...p.darts!, back: Math.round(v) } }))}
              />
            </div>
          </>
        )}
      </div>

      {/* Measurements */}
      <div className="border-t border-gray-200 pt-3">
        <p className="text-xs font-semibold text-gray-700 mb-2">Your measurements (cm)</p>
        <div className="grid grid-cols-2 gap-3">
          {(MEASUREMENT_FIELDS[f.garment_type] ?? MEASUREMENT_FIELDS['skirt']).map(({ key, label, min, max }) => (
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

      {/* Shape-generation mode (vest / bodice) — toggle + regenerate to compare strategies */}
      {isShapeAware && (
        <div className="pt-2 border-t border-gray-200">
          <Label>Shape mode</Label>
          <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs w-fit mt-1">
            {([
              ['modifiers', 'Modifiers'],
              ['warp', 'Warp'],
              ['fit_params', 'Fit-params'],
            ] as [ShapeMode, string][]).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setShapeMode(key)}
                className={`px-2.5 py-1 font-medium border-r last:border-r-0 border-gray-200 ${
                  shapeMode === key ? 'bg-violet-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            How the silhouette/hem is generated. Regenerate after switching to compare.
          </p>
        </div>
      )}

      <div className="flex gap-2 justify-end pt-2 border-t border-gray-200">
        <button onClick={onBack}
          className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50">
          ← Back
        </button>
        <button onClick={() => onGenerate(f, m, shapeMode)}
          className="px-4 py-1.5 text-xs bg-green-600 text-white rounded hover:bg-green-700">
          {isPatternSupported ? 'Generate Pattern' : 'Load Measurements'}
        </button>
      </div>
    </div>
  )
}

// ── Length category → cm mapping ─────────────────────────────────────────────

const LENGTH_CATEGORY_CM: Record<string, number> = {
  // Skirts / dresses
  micro: 35, mini: 45, above_knee: 52, knee: 58, midi: 80, maxi: 110,
  // Trousers / pants
  full_length: 100, ankle: 95, cropped: 85, capri: 75,
  // Tops
  hip_length: 65, tunic: 75,
  // Shorts
  short: 35, mid_thigh: 42,
  // Coats / jackets
  below_hip: 70,
}

function lengthCategoryToCm(category: string): number {
  return LENGTH_CATEGORY_CM[category] ?? 65
}

// ── Main modal ────────────────────────────────────────────────────────────────

export default function AIAssistModal({ onClose, onGenerated }: Props) {
  const { state, dispatch } = useEditor()
  const [step, setStep] = useState<Step>('upload')
  const [features, setFeatures] = useState<GarmentFeatures | null>(null)
  const [genError, setGenError] = useState('')
  // Photo files live here (not in UploadStep) so they can be handed up for refine.
  const [frontFile, setFrontFile] = useState<File | null>(null)
  const [backFile, setBackFile] = useState<File | null>(null)

  const baseMeasurements: Measurements = {
    waist_cm: state.measurements['waist'] ?? 76,
    hip_cm: state.measurements['hip'] ?? 94,
    waist_to_hip_cm: state.measurements['waistToHip'] ?? 21,
    length_cm: state.measurements['garmentLength'] ?? state.measurements['skirtLength'] ?? 65,
    seam_allowance_cm: 1.5,
    hem_allowance_cm: 3.0,
    waistband_width_cm: 3.0,
    // Shirt-specific (seeded from canvas measurement panel if available)
    chest_cm: state.measurements['bust'] || undefined,
    shoulder_width_cm: state.measurements['shoulder'] || undefined,
    arm_length_cm: state.measurements['sleeveLength'] || undefined,
    // Pants-specific
    inseam_cm: state.measurements['inseam'] || undefined,
    rise_cm: undefined,  // no canvas panel key; backend defaults to H/4
  }

  const handleAnalyzed = (f: GarmentFeatures) => {
    setFeatures(f)
    // If the canvas has no length set yet, seed it from the AI-detected length category
    if (!state.measurements['garmentLength'] && !state.measurements['skirtLength']) {
      baseMeasurements.length_cm = lengthCategoryToCm(f.length_category)
    }
    setStep('review')
  }

  const handleGenerate = async (f: GarmentFeatures, m: Measurements, shapeMode: ShapeMode = 'modifiers') => {
    setStep('generating')
    setGenError('')
    try {
      const psnap = await generatePattern(f, m, shapeMode)
      if (!Array.isArray(psnap.elements)) throw new Error('Invalid pattern data')

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
        connections: psnap.connections ?? [],
      })

      // Cache features/measurements so the Instructions panel can generate on demand
      dispatch({ type: 'SET_INSTRUCTIONS', instructions: null, loading: false, features: f, measurements: m })
      // Hand the refine context up so the persistent "Refine from Photo"
      // header button works after this modal closes.
      if (frontFile) {
        onGenerated?.({
          garmentType: f.garment_type,
          notes: f.notes ?? '',
          measurements: m,
          frontFile,
          backFile,
        })
      }
      onClose()
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : String(e))
      setStep('review')
    }
  }

  return (
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
              {step === 'upload' && 'Step 1 of 2 — Select type & upload photo'}
              {step === 'review' && 'Step 2 of 2 — Review detected features'}
              {step === 'generating' && 'Generating your pattern…'}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 flex-1 overflow-y-auto">
          {step === 'upload' && (
            <UploadStep
              onAnalyzed={handleAnalyzed}
              onClose={onClose}
              frontFile={frontFile}
              backFile={backFile}
              setFrontFile={setFrontFile}
              setBackFile={setBackFile}
            />
          )}
          {step === 'review' && features && (
            <>
              {genError && (
                <div className="mb-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{genError}</div>
              )}
              <ReviewStep
                features={features}
                measurements={baseMeasurements}
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

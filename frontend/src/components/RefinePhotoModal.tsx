/**
 * Photo refine — a compact modal opened from the persistent "Refine from Photo"
 * header button (available any time after an AI generate ran with a photo).
 *
 * Refines the CURRENT canvas state, not a snapshot from generate time, so
 * pieces the user moved or edited while inspecting the draft are respected.
 * POST /api/refine sends the photo + the drafted outlines to the vision LLM,
 * which reshapes only the pieces whose flat shape disagrees with the photo.
 */
import { useState } from 'react'
import { useEditor } from '../context/EditorContext'
import { refinePattern } from '../api'
import type { GeneratedPattern, RefineSummary } from '../api'
import type { Measurements } from '../types'

/** Everything the refine pass needs, captured when the AI generate ran. */
export interface RefineContext {
  garmentType: string
  notes: string
  measurements: Measurements   // backend-unit measurements from the generate step
  frontFile: File
  backFile: File | null
}

export default function RefinePhotoModal({ ctx, onClose }: {
  ctx: RefineContext
  onClose: () => void
}) {
  const { state, dispatch } = useEditor()
  const [refining, setRefining] = useState(false)
  const [summary, setSummary] = useState<RefineSummary | null>(null)
  const [error, setError] = useState('')

  const handleRefine = async () => {
    setRefining(true)
    setError('')
    try {
      const psnap: GeneratedPattern = {
        version: 1,
        elements: state.elements,
        pieces: state.pieces,
        measurements: state.measurements,
        connections: state.connections,
      }
      const r = await refinePattern(
        ctx.garmentType, psnap, ctx.measurements,
        ctx.frontFile, ctx.backFile, ctx.notes,
      )
      dispatch({
        type: 'LOAD_STATE',
        elements: r.psnap.elements,
        pieces: r.psnap.pieces ?? [],
        measurements: r.psnap.measurements ?? {},
        connections: r.psnap.connections ?? [],
        // Preserve state LOAD_STATE would otherwise reset to null.
        instructions: state.instructions,
        lastFeatures: state.lastFeatures,
        lastMeasurements: state.lastMeasurements,
      })
      setSummary(r.summary)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRefining(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-xl shadow-2xl w-[440px] max-w-[95vw] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Refine Shapes from Photo</h2>
            <p className="text-xs text-gray-500 mt-0.5">{ctx.frontFile.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-gray-600">
            The AI compares each piece on the canvas against your photo and reshapes the
            edges that disagree (curved necklines, wrap edges, hems). Reshaped pieces
            appear amber as AI drafts — verify them before cutting. You can run this as
            many times as you like.
          </p>

          {summary && (
            <div className="bg-gray-50 border border-gray-200 rounded px-3 py-2.5 space-y-1.5 text-xs">
              {summary.changed.length > 0 ? (
                <p className="text-violet-800">
                  <span className="font-semibold">Reshaped:</span> {summary.changed.join(', ')}
                </p>
              ) : (
                <p className="text-gray-600">No pieces needed reshaping — the pattern already matches the photo.</p>
              )}
              {summary.unchanged.length > 0 && (
                <p className="text-gray-500">Unchanged: {summary.unchanged.join(', ')}</p>
              )}
              {summary.rejected.length > 0 && (
                <div className="text-amber-700">
                  <p className="font-semibold">Skipped (failed validation):</p>
                  {summary.rejected.map(r => (
                    <p key={r.name} className="text-[11px] ml-2">• {r.name}: {r.reason}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50"
            >
              Close
            </button>
            <button
              onClick={handleRefine}
              disabled={refining || state.pieces.length === 0}
              className="px-4 py-1.5 text-xs bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {refining ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Comparing with photo…
                </>
              ) : summary ? 'Refine Again' : 'Refine Shapes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

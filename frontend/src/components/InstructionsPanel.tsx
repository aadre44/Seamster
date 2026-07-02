import { useState } from 'react'
import { useEditor } from '../context/EditorContext'
import { generateInstructions } from '../api'
import type { InstructionSection } from '../types'

interface Props {
  onClose: () => void
}

function SectionBlock({ section, baseNumber }: { section: InstructionSection; baseNumber: number }) {
  const [expanded, setExpanded] = useState(true)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Section header */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <span className="text-xs font-semibold text-gray-800 uppercase tracking-wide">{section.title}</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] bg-gray-200 text-gray-600 rounded-full px-2 py-0.5">
            {section.steps.length} step{section.steps.length !== 1 ? 's' : ''}
          </span>
          <span className="text-gray-400 text-xs">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Steps */}
      {expanded && (
        <ol className="divide-y divide-gray-100">
          {section.steps.map((step, i) => {
            const num = baseNumber + i
            return (
              <li key={num} className="px-4 py-3">
                <div className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white text-[10px] font-bold flex items-center justify-center mt-0.5">
                    {num}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-800 leading-relaxed">{step.instruction}</p>
                    {step.tip && (
                      <div className="mt-1.5 bg-amber-50 border-l-2 border-amber-400 px-3 py-1.5 rounded-r">
                        <p className="text-[10px] text-amber-700 leading-relaxed">{step.tip}</p>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

export default function InstructionsPanel({ onClose }: Props) {
  const { state, dispatch } = useEditor()
  const { instructions, instructionsLoading, lastFeatures, lastMeasurements } = state
  const [error, setError] = useState<string | null>(null)

  const canGenerate = !!lastFeatures && !!lastMeasurements && !instructionsLoading

  const handleGenerate = () => {
    if (!canGenerate) return
    const pieces = state.pieces
      .filter(p => p.name)
      .map(p => ({ name: p.name, cut_qty: p.cutQty, on_fold: p.onFold, seam_allowance: p.seamAllowance, notes: p.notes ?? "" }))
    if (pieces.length === 0) return

    setError(null)
    dispatch({ type: 'SET_INSTRUCTIONS', instructions: null, loading: true })

    generateInstructions(lastFeatures, lastMeasurements, pieces)
      .then(data => dispatch({ type: 'SET_INSTRUCTIONS', instructions: data, loading: false }))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to generate instructions.')
        dispatch({ type: 'SET_INSTRUCTIONS', instructions: null, loading: false })
      })
  }

  // Count steps across all sections so we can number them consecutively
  const sectionOffsets: number[] = []
  if (instructions) {
    let count = 1
    for (const section of instructions.sections) {
      sectionOffsets.push(count)
      count += section.steps.length
    }
  }

  return (
    <div className="flex flex-col h-full bg-white border-l border-gray-200" style={{ width: 300 }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm">🧵</span>
          <h2 className="text-xs font-semibold text-gray-800">Sewing Instructions</h2>
        </div>
        <div className="flex items-center gap-1">
          {canGenerate && (
            <button
              onClick={handleGenerate}
              className="text-[10px] text-blue-600 hover:text-blue-800 px-2 py-1 rounded hover:bg-blue-50 transition-colors"
            >
              {instructions ? 'Regenerate' : 'Generate'}
            </button>
          )}
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-base leading-none px-1"
          >
            ×
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Loading skeleton */}
        {instructionsLoading && (
          <div className="space-y-3">
            <div className="h-4 bg-gray-200 rounded animate-pulse w-3/4" />
            {[1, 2, 3].map(i => (
              <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="h-10 bg-gray-100 animate-pulse" />
                <div className="px-4 py-3 space-y-2">
                  {[1, 2].map(j => (
                    <div key={j} className="flex gap-3">
                      <div className="w-6 h-6 rounded-full bg-gray-200 animate-pulse flex-shrink-0" />
                      <div className="flex-1 space-y-1">
                        <div className="h-3 bg-gray-200 rounded animate-pulse w-full" />
                        <div className="h-3 bg-gray-200 rounded animate-pulse w-2/3" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!instructionsLoading && !instructions && (
          <div className="flex flex-col items-center justify-center h-48 text-center gap-3 text-gray-400">
            <span className="text-3xl">📋</span>
            {canGenerate ? (
              <>
                <p className="text-xs leading-relaxed">
                  Ready to generate step-by-step sewing instructions for this pattern.
                </p>
                <button
                  onClick={handleGenerate}
                  className="px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Generate Instructions
                </button>
              </>
            ) : (
              <p className="text-xs leading-relaxed">
                Generate a pattern using AI Assist to see step-by-step sewing instructions here.
              </p>
            )}
            {error && (
              <p className="text-[10px] text-red-500 leading-relaxed px-2">{error}</p>
            )}
          </div>
        )}
        {error && instructions && (
          <p className="text-[10px] text-red-500 leading-relaxed px-2 pb-1">{error}</p>
        )}

        {/* Instructions */}
        {!instructionsLoading && instructions && (
          <>
            <p className="text-[11px] text-gray-600 italic leading-relaxed px-1">
              {instructions.garment_summary}
            </p>
            {instructions.sections.map((section, i) => (
              <SectionBlock
                key={section.title}
                section={section}
                baseNumber={sectionOffsets[i]}
              />
            ))}
          </>
        )}
      </div>
    </div>
  )
}

import { lazy, Suspense, useRef, useState } from 'react'
import { EditorProvider, useEditor } from './context/EditorContext'
import Canvas from './components/Canvas'
import Toolbar from './components/Toolbar'
import PropertiesPanel from './components/PropertiesPanel'
import MeasurementPanel from './components/MeasurementPanel'
import AIAssistModal from './components/AIAssistModal'
import RefinePhotoModal from './components/RefinePhotoModal'
import type { RefineContext } from './components/RefinePhotoModal'
import InstructionsPanel from './components/InstructionsPanel'
import AssemblyView from './components/AssemblyView'
import ModelToggle from './components/ModelToggle'
import BodyCustomizationPanel from './components/BodyCustomizationPanel'

// three.js is only fetched when the 3D view is first opened.
const BodyModelView = lazy(() => import('./components/BodyModelView'))

type MainView = 'canvas' | 'assembly' | 'body'
import { downloadSVG } from './export/svgExport'
import { exportPdf } from './api'
import { downloadPsnap, loadPsnapAction, toPsnap } from './utils/psnap'

function StatusBar() {
  const { state } = useEditor()
  const zoomPct = Math.round(state.zoom * 100)
  return (
    <div className="flex items-center gap-4 px-3 py-1 bg-gray-100 border-t border-gray-200 text-xs text-gray-500 shrink-0">
      <span>Zoom: {zoomPct}%</span>
      <span>Pan: ({Math.round(state.pan.x)}, {Math.round(state.pan.y)}) px</span>
      <span>Tool: <strong className="text-gray-700">{state.activeTool}</strong></span>
      <span>Grid: {state.showGrid ? 'on' : 'off'}</span>
      <span>Snap: {state.snapEnabled ? 'on' : 'off'}</span>
      <span className="ml-auto">{state.elements.length} element{state.elements.length !== 1 ? 's' : ''}</span>
    </div>
  )
}

function FileButtons() {
  const { state, dispatch } = useEditor()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const save = () => downloadPsnap(toPsnap(state))

  const exportPDF = async (elements: typeof state.elements, pieces: typeof state.pieces,
                           paperSize: string, singlePage: boolean) => {
    try {
      const blob = await exportPdf({
        elements,
        pieces,
        paper_size: paperSize,
        single_page: singlePage,
        ...(state.instructions ? { instructions: state.instructions } : {}),
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = singlePage ? 'pattern-single.pdf' : `pattern-${paperSize}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(`PDF export failed: ${e}`)
    }
  }

  const open = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const hasContent = state.elements.length > 0 || state.pieces.length > 0
    if (hasContent && !window.confirm('Loading a file will replace the current pattern. Continue?')) return
    file.text().then(json => {
      try {
        dispatch(loadPsnapAction(json))
      } catch { alert('Failed to load pattern file.') }
    })
    e.target.value = ''
  }

  return (
    <>
      <button onClick={save}
        className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600">
        Save (Ctrl+S)
      </button>
      <button onClick={() => fileInputRef.current?.click()}
        className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600">
        Open
      </button>
      <button onClick={() => downloadSVG(state.elements, state.pieces, state.instructions ?? undefined)}
        className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600">
        Export SVG
      </button>
      <button onClick={() => exportPDF(state.elements, state.pieces, 'a4', false)}
        className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600">
        Export PDF (A4)
      </button>
      <button onClick={() => exportPDF(state.elements, state.pieces, 'a4', true)}
        className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600">
        Export PDF (Single)
      </button>
      <input ref={fileInputRef} type="file" accept=".psnap" className="hidden" onChange={open} />
    </>
  )
}

const VIEWS: { id: MainView; label: string; icon: string }[] = [
  { id: 'canvas', label: 'Pattern', icon: '✏️' },
  { id: 'assembly', label: 'Assembly', icon: '🧩' },
  { id: 'body', label: '3D Body', icon: '🧍' },
]

// Which main view is showing. Tabs rather than toggles, so the way back to the
// pattern is always visible.
function ViewTabs({ view, onChange, canAssemble }: { view: MainView; onChange: (v: MainView) => void; canAssemble: boolean }) {
  return (
    <div role="tablist" aria-label="View" className="flex items-center p-0.5 bg-gray-100 rounded-full">
      {VIEWS.map(v => {
        const disabled = v.id === 'assembly' && !canAssemble
        const active = view === v.id && !disabled
        return (
          <button
            key={v.id}
            role="tab"
            aria-selected={active}
            disabled={disabled}
            title={disabled ? 'Add pattern pieces to assemble them' : undefined}
            onClick={() => onChange(v.id)}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-full transition-colors ${
              active
                ? 'bg-white text-gray-900 shadow-sm'
                : disabled
                  ? 'text-gray-300 cursor-not-allowed'
                  : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <span aria-hidden>{v.icon}</span>
            {v.label}
          </button>
        )
      })}
    </div>
  )
}

function Editor() {
  const { state } = useEditor()
  const [showAI, setShowAI] = useState(false)
  const [showInstructions, setShowInstructions] = useState(false)
  const [mainView, setMainView] = useState<MainView>('canvas')
  const [split, setSplit] = useState(false) // Assembly with the 3D body beside it
  // Set after a photo-based AI generate; keeps the photo + measurements so the
  // "Refine from Photo" button stays available until the next generate.
  const [refineCtx, setRefineCtx] = useState<RefineContext | null>(null)
  const [showRefine, setShowRefine] = useState(false)

  const canShowInstructions = state.lastFeatures !== null
  const canShowAssembly = state.pieces.length > 0
  const canRefine = refineCtx !== null && state.pieces.length > 0
  // Assembly needs pieces; with none (e.g. after deleting them) show the pattern.
  const view: MainView = mainView === 'assembly' && !canShowAssembly ? 'canvas' : mainView

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {showAI && (
        <AIAssistModal
          onClose={() => setShowAI(false)}
          onGenerated={ctx => setRefineCtx(ctx)}
        />
      )}
      {showRefine && refineCtx && (
        <RefinePhotoModal ctx={refineCtx} onClose={() => setShowRefine(false)} />
      )}

      {/* Top header */}
      <header className="flex items-center gap-3 px-4 py-2 bg-white border-b border-gray-200 shrink-0">
        <h1 className="text-sm font-semibold text-gray-900 tracking-tight">Seamster</h1>
        <ViewTabs view={view} onChange={setMainView} canAssemble={canShowAssembly} />
        <button
          onClick={() => setShowAI(true)}
          className="ml-3 flex items-center gap-1.5 px-3 py-1 text-xs font-medium bg-violet-600 text-white rounded-full hover:bg-violet-700 transition-colors"
        >
          <span>✦</span> AI Assist
        </button>
        {canRefine && (
          <button
            onClick={() => setShowRefine(true)}
            className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium bg-violet-50 text-violet-700 border border-violet-300 rounded-full hover:bg-violet-100 transition-colors"
          >
            <span>📷</span> Refine from Photo
          </button>
        )}
        {canShowInstructions && (
          <button
            onClick={() => setShowInstructions(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-full transition-colors ${
              showInstructions
                ? 'bg-teal-600 text-white hover:bg-teal-700'
                : 'bg-teal-50 text-teal-700 border border-teal-300 hover:bg-teal-100'
            }`}
          >
            {state.instructionsLoading ? (
              <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
            ) : (
              <span>📋</span>
            )}
            {state.instructions ? 'Instructions' : 'Generate Instructions'}
          </button>
        )}
        <div className="ml-auto flex items-center gap-3">
          <ModelToggle />
          <span className="text-gray-200 text-sm">|</span>
          <FileButtons />
        </div>
      </header>

      {/* Main row */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left toolbar (drawing tools only apply to the pattern) */}
        {view === 'canvas' && <Toolbar />}

        {/* Main view (fills remaining space) */}
        {view === 'body' ? (
          <Suspense fallback={
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">Loading 3D view…</div>
          }>
            <BodyModelView />
          </Suspense>
        ) : view === 'assembly' ? (
          <div className="flex-1 flex min-w-0 overflow-hidden">
            <AssemblyView split={split} onSplit={setSplit} />
            {split && (
              // The live 3D body beside Assembly: placements re-drape as they move.
              <div className="flex w-[42%] min-w-[320px] border-l border-gray-200" data-testid="assembly-3d">
                <Suspense fallback={<div className="flex-1 flex items-center justify-center text-sm text-gray-400">Loading 3D view…</div>}>
                  <BodyModelView />
                </Suspense>
              </div>
            )}
          </div>
        ) : <Canvas />}

        {/* Right sidebar */}
        <aside className="w-52 shrink-0 border-l border-gray-200 bg-white overflow-y-auto flex flex-col">
          {(view === 'body' || (view === 'assembly' && split)) && <BodyCustomizationPanel />}
          <div className="px-3 py-2 text-xs font-semibold text-gray-700 border-b border-gray-100">
            Properties
          </div>
          <PropertiesPanel />
          <MeasurementPanel />
        </aside>

        {/* Instructions drawer */}
        {showInstructions && (
          <InstructionsPanel onClose={() => setShowInstructions(false)} />
        )}
      </div>

      {/* Status bar */}
      <StatusBar />
    </div>
  )
}

export default function App() {
  return (
    <EditorProvider>
      <Editor />
    </EditorProvider>
  )
}

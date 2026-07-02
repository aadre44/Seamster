import { useRef, useState } from 'react'
import { EditorProvider, useEditor } from './context/EditorContext'
import Canvas from './components/Canvas'
import Toolbar from './components/Toolbar'
import PropertiesPanel from './components/PropertiesPanel'
import MeasurementPanel from './components/MeasurementPanel'
import AIAssistModal from './components/AIAssistModal'
import InstructionsPanel from './components/InstructionsPanel'
import AssemblyView from './components/AssemblyView'
import ModelToggle from './components/ModelToggle'
import { downloadSVG } from './export/svgExport'
import { exportPdf } from './api'

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

  const save = () => {
    const data = {
      version: 1,
      elements: state.elements,
      pieces: state.pieces,
      measurements: state.measurements,
      ...(state.instructions ? { instructions: state.instructions } : {}),
      ...(state.lastFeatures ? { lastFeatures: state.lastFeatures } : {}),
      ...(state.lastMeasurements ? { lastMeasurements: state.lastMeasurements } : {}),
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'pattern.psnap'; a.click()
    URL.revokeObjectURL(url)
  }

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
        const data = JSON.parse(json)
        if (!data.elements || !Array.isArray(data.elements)) throw new Error('Invalid file')
        dispatch({
          type: 'LOAD_STATE',
          elements: data.elements,
          pieces: data.pieces ?? [],
          measurements: data.measurements ?? {},
          connections: data.connections ?? [],
          instructions: data.instructions ?? null,
          lastFeatures: data.lastFeatures ?? null,
          lastMeasurements: data.lastMeasurements ?? null,
        })
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

function Editor() {
  const { state } = useEditor()
  const [showAI, setShowAI] = useState(false)
  const [showInstructions, setShowInstructions] = useState(false)
  const [showAssembly, setShowAssembly] = useState(false)

  const canShowInstructions = state.lastFeatures !== null
  const canShowAssembly = state.pieces.length > 0

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {showAI && <AIAssistModal onClose={() => setShowAI(false)} />}

      {/* Top header */}
      <header className="flex items-center gap-3 px-4 py-2 bg-white border-b border-gray-200 shrink-0">
        <h1 className="text-sm font-semibold text-gray-900 tracking-tight">Seamster</h1>
        <span className="text-gray-300 text-sm">|</span>
        <span className="text-xs text-gray-500">Pattern Editor</span>
        <button
          onClick={() => setShowAI(true)}
          className="ml-3 flex items-center gap-1.5 px-3 py-1 text-xs font-medium bg-violet-600 text-white rounded-full hover:bg-violet-700 transition-colors"
        >
          <span>✦</span> AI Assist
        </button>
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
        {canShowAssembly && (
          <button
            onClick={() => setShowAssembly(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-full transition-colors ${
              showAssembly
                ? 'bg-teal-600 text-white hover:bg-teal-700'
                : 'bg-teal-50 text-teal-700 border border-teal-300 hover:bg-teal-100'
            }`}
          >
            <span>🧩</span>
            Assembly View
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
        {/* Left toolbar */}
        <Toolbar />

        {/* Canvas / Assembly View (fills remaining space) */}
        {showAssembly ? <AssemblyView /> : <Canvas />}

        {/* Right sidebar */}
        <aside className="w-52 shrink-0 border-l border-gray-200 bg-white overflow-y-auto flex flex-col">
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

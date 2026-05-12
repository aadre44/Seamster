import { useEditor } from '../context/EditorContext'
import type { ToolType } from '../types'
import HelpPanel from './HelpPanel'

const TOOLS: { id: ToolType; label: string; shortcut: string; icon: string }[] = [
  { id: 'select',         label: 'Select',         shortcut: 'S', icon: '↖' },
  { id: 'line',           label: 'Line',           shortcut: 'L', icon: '╱' },
  { id: 'curve',          label: 'Curve',          shortcut: 'C', icon: '∿' },
  { id: 'point',          label: 'Point',          shortcut: 'P', icon: '·' },
  { id: 'seam-allowance', label: 'Seam Allowance', shortcut: 'A', icon: '⊡' },
  { id: 'grain-line',     label: 'Grain Line',     shortcut: 'G', icon: '↕' },
  { id: 'notch',          label: 'Notch',          shortcut: 'N', icon: '|' },
  { id: 'eraser',         label: 'Eraser',         shortcut: 'E', icon: '✕' },
]

export default function Toolbar() {
  const { state, dispatch } = useEditor()

  return (
    <aside className="flex flex-col items-center gap-1 w-12 bg-gray-100 border-r border-gray-200 py-2 shrink-0">
      {TOOLS.map(t => (
        <button
          key={t.id}
          title={`${t.label} (${t.shortcut})`}
          onClick={() => dispatch({ type: 'SET_ACTIVE_TOOL', tool: t.id })}
          className={`
            w-9 h-9 rounded flex flex-col items-center justify-center text-xs leading-none
            ${state.activeTool === t.id
              ? 'bg-indigo-600 text-white shadow'
              : 'text-gray-600 hover:bg-gray-200'}
          `}
        >
          <span className="text-base">{t.icon}</span>
          <span className="text-[9px] mt-0.5 opacity-70">{t.shortcut}</span>
        </button>
      ))}

      <div className="flex-1" />

      {/* Grid toggle indicator */}
      <button
        title="Toggle Grid (Ctrl+G)"
        onClick={() => dispatch({ type: 'TOGGLE_GRID' })}
        className={`w-9 h-9 rounded flex flex-col items-center justify-center text-xs leading-none
          ${state.showGrid ? 'bg-gray-300 text-gray-700' : 'text-gray-400 hover:bg-gray-200'}`}
      >
        <span className="text-base">#</span>
        <span className="text-[9px] mt-0.5 opacity-70">G</span>
      </button>

      {/* Snap toggle indicator */}
      <button
        title="Toggle Snap (Ctrl+Shift+S)"
        onClick={() => dispatch({ type: 'TOGGLE_SNAP' })}
        className={`w-9 h-9 rounded flex flex-col items-center justify-center text-xs leading-none
          ${state.snapEnabled ? 'bg-gray-300 text-gray-700' : 'text-gray-400 hover:bg-gray-200'}`}
      >
        <span className="text-base">⊕</span>
        <span className="text-[9px] mt-0.5 opacity-70">sn</span>
      </button>

      {/* Seam allowance toggle */}
      <button
        title="Toggle Seam Allowance lines"
        onClick={() => dispatch({ type: 'TOGGLE_SEAM_ALLOWANCE' })}
        className={`w-9 h-9 rounded flex flex-col items-center justify-center text-xs leading-none
          ${state.showSeamAllowance ? 'bg-red-100 text-red-600' : 'text-gray-400 hover:bg-gray-200'}`}
      >
        <span className="text-base">⊡</span>
        <span className="text-[9px] mt-0.5 opacity-70">sa</span>
      </button>

      {/* Help / tool reference */}
      <HelpPanel />
    </aside>
  )
}

import { useState } from 'react'

const TOOLS_REF = [
  {
    icon: '↖', label: 'Select', key: 'S',
    desc: 'Click to select elements. Shift+click for multi-select. Drag to move. Box-drag to bulk-select a region. Delete/Backspace to delete selection.',
  },
  {
    icon: '╱', label: 'Line', key: 'L',
    desc: 'Click to set the start point, click again to set the end. Keeps chaining — each new click extends the outline. Click the start point again (or press Enter) to close the outline into a pattern piece.',
  },
  {
    icon: '∿', label: 'Curve', key: 'C',
    desc: 'Three-click arc control: (1) Click to set the start point. (2) Click to set the end point. (3) Move your mouse — the curve bends to pass through the cursor. Click to commit the shape. Chain curves and lines together; Enter closes the outline into a piece.',
  },
  {
    icon: '·', label: 'Point', key: 'P',
    desc: 'Place an invisible snap anchor at any position. Useful for creating snappable reference points that don\'t show in the final export.',
  },
  {
    icon: '⊡', label: 'Seam Allowance', key: 'A',
    desc: 'Click a closed pattern piece to open a dialog and set its seam allowance amount in cm. The red dashed offset outline updates immediately.',
  },
  {
    icon: '↕', label: 'Grain Line', key: 'G',
    desc: 'Click and drag to draw a grain line arrow on a pattern piece. Shows the fabric grain direction for cutting.',
  },
  {
    icon: '|', label: 'Notch', key: 'N',
    desc: 'Click on any line or curve to place a notch tick mark at that position. The angle is calculated automatically from the element\'s tangent.',
  },
  {
    icon: '✕', label: 'Eraser', key: 'E',
    desc: 'Click on any element to delete it immediately.',
  },
]

const SHORTCUTS = [
  { keys: 'Ctrl+Z / Ctrl+Y', desc: 'Undo / Redo (50-level stack)' },
  { keys: 'Ctrl+S', desc: 'Save pattern as .psnap file' },
  { keys: 'Ctrl+N', desc: 'New piece — resets chain state, switches to Line tool' },
  { keys: 'Enter', desc: 'Close outline into a pattern piece (Line/Curve tool)' },
  { keys: 'Escape', desc: 'Cancel current action and deselect everything' },
  { keys: 'Delete / Backspace', desc: 'Delete selected element or entire selected piece' },
  { keys: 'Ctrl+G', desc: 'Toggle grid' },
  { keys: 'Ctrl+Shift+S', desc: 'Toggle snapping' },
  { keys: 'Ctrl+= / Ctrl+-', desc: 'Zoom in / out' },
  { keys: 'Ctrl+0', desc: 'Fit pattern to screen' },
  { keys: 'Scroll wheel', desc: 'Zoom (centred on cursor)' },
  { keys: 'Space + drag', desc: 'Pan the canvas' },
  { keys: 'Middle-mouse drag', desc: 'Pan the canvas' },
  { keys: 'Shift (while drawing)', desc: 'Constrain to 45° angle increments' },
  { keys: 'S / L / C / P / A / G / N / E', desc: 'Activate the tool matching that letter' },
]

const SNAP_KINDS = [
  { color: 'bg-red-500', label: 'Endpoint', desc: 'Snaps to start or end of any existing element' },
  { color: 'bg-orange-400', label: 'Midpoint', desc: 'Snaps to the geometric midpoint of a segment' },
  { color: 'bg-blue-500', label: 'Grid', desc: 'Snaps to 0.5 cm grid intersections' },
  { color: 'bg-purple-500', label: 'Angle (45°)', desc: 'Hold Shift — constrains direction from anchor to 45° steps' },
]

const WORKFLOW = [
  'Choose the Line or Curve tool. Click on the canvas to begin drawing an outline.',
  'Continue clicking to add segments. Lines and curves can be mixed in the same outline.',
  'Close the outline: click the very first point again (it snaps when close enough), or press Enter.',
  'A pattern piece is created automatically. Click it to select and edit its name, cut quantity, and seam allowance in the Properties panel.',
  'Annotate the piece: use the Grain Line tool to show fabric direction, and the Notch tool to mark matching points.',
  'Use the Select tool to move, rotate, or box-select multiple elements. Right-click a piece for quick Flip / Rotate options.',
  'Save your work as a .psnap file (Ctrl+S). Export to SVG for vector editing, or tiled PDF for printing at 1:1 scale.',
]

export default function HelpPanel() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        title="Tool Reference — keyboard shortcuts and workflow tips"
        onClick={() => setOpen(true)}
        className="w-9 h-9 rounded flex flex-col items-center justify-center text-xs leading-none text-gray-400 hover:bg-gray-200 hover:text-gray-700"
      >
        <span className="text-base font-semibold">?</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onMouseDown={e => { if (e.target === e.currentTarget) setOpen(false) }}
        >
          <div className="bg-white rounded-xl shadow-2xl w-[600px] max-h-[85vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 sticky top-0 bg-white rounded-t-xl">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">Tool Reference</h2>
                <p className="text-[11px] text-gray-400 mt-0.5">Seamster — Phase 1 Pattern Editor</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-xl leading-none w-7 h-7 flex items-center justify-center rounded hover:bg-gray-100"
              >
                ✕
              </button>
            </div>

            <div className="px-6 py-5 space-y-6">
              {/* Tools */}
              <section>
                <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Drawing Tools
                </h3>
                <div className="space-y-3">
                  {TOOLS_REF.map(t => (
                    <div key={t.key} className="flex gap-3 items-start">
                      <span className="w-7 h-7 rounded-md bg-gray-100 flex items-center justify-center text-base shrink-0 mt-0.5 border border-gray-200">
                        {t.icon}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-semibold text-gray-800">{t.label}</span>
                          <kbd className="text-[10px] px-1.5 py-0.5 bg-gray-100 border border-gray-200 rounded font-mono text-gray-600">
                            {t.key}
                          </kbd>
                        </div>
                        <p className="text-[11px] text-gray-500 leading-relaxed">{t.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {/* Workflow */}
              <section>
                <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Piece Workflow
                </h3>
                <ol className="space-y-2">
                  {WORKFLOW.map((step, i) => (
                    <li key={i} className="flex gap-3 items-start">
                      <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold flex items-center justify-center shrink-0 mt-0.5">
                        {i + 1}
                      </span>
                      <span className="text-[11px] text-gray-600 leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ol>
              </section>

              {/* Snap indicators */}
              <section>
                <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Snap Indicators
                </h3>
                <div className="grid grid-cols-2 gap-2">
                  {SNAP_KINDS.map(s => (
                    <div key={s.label} className="flex items-start gap-2 bg-gray-50 rounded-lg p-2">
                      <span className={`w-3 h-3 rounded-full ${s.color} shrink-0 mt-0.5 ring-2 ring-white`} />
                      <div>
                        <div className="text-[11px] font-medium text-gray-700">{s.label}</div>
                        <div className="text-[10px] text-gray-400">{s.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {/* Keyboard shortcuts */}
              <section>
                <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Keyboard Shortcuts
                </h3>
                <div className="space-y-1.5">
                  {SHORTCUTS.map(s => (
                    <div key={s.keys} className="flex items-center gap-3">
                      <kbd className="text-[10px] px-2 py-0.5 bg-gray-100 border border-gray-200 rounded font-mono text-gray-600 shrink-0 whitespace-nowrap min-w-[120px] text-center">
                        {s.keys}
                      </kbd>
                      <span className="text-[11px] text-gray-600">{s.desc}</span>
                    </div>
                  ))}
                </div>
              </section>

              {/* Canvas toggles */}
              <section>
                <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Canvas Toggles (Toolbar Bottom)
                </h3>
                <div className="space-y-1.5">
                  {[
                    { icon: '#', label: 'Grid', desc: 'Show or hide the background grid (major lines every 5 cm)' },
                    { icon: '⊕', label: 'Snap', desc: 'Enable or disable all snapping (endpoint, midpoint, grid, angle)' },
                    { icon: '⊡', label: 'Seam Allowance', desc: 'Show or hide seam allowance offset outlines on all pieces' },
                  ].map(t => (
                    <div key={t.label} className="flex items-center gap-3">
                      <span className="w-7 h-7 rounded-md bg-gray-100 border border-gray-200 flex items-center justify-center text-base text-gray-500 shrink-0">
                        {t.icon}
                      </span>
                      <div>
                        <span className="text-[11px] font-medium text-gray-700">{t.label} — </span>
                        <span className="text-[11px] text-gray-500">{t.desc}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {/* Measurements note */}
              <section className="bg-indigo-50 rounded-lg p-3 border border-indigo-100">
                <h3 className="text-[10px] font-semibold text-indigo-600 uppercase tracking-widest mb-1.5">
                  Parametric Measurements
                </h3>
                <p className="text-[11px] text-indigo-800 leading-relaxed">
                  Body measurements (waist, hip, length, etc.) are entered in the Measurements section of the Properties panel.
                  Select a line element and enter a formula in the <strong>Formula</strong> field to drive its length parametrically —
                  for example <code className="bg-indigo-100 px-1 rounded font-mono">hip / 4 + 1</code>.
                  Changing a measurement value automatically updates all elements that reference it.
                </p>
              </section>
            </div>

            <div className="px-6 py-3 border-t border-gray-100 bg-gray-50 rounded-b-xl">
              <p className="text-[10px] text-gray-400 text-center">
                1 SVG unit = 1 cm · Coordinates shown in cm · Grid major lines every 5 cm
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

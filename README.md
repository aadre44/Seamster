# PatternSnap

Browser-based sewing pattern editor with AI-assisted pattern generation. Draft patterns on a 2D SVG canvas using lines and curves, with dimensions driven by body measurement formulas. Upload a garment photo and let the AI detect its style, then generate a starting pattern for you to refine. Export as SVG or tiled print-ready PDF.

**Phase 1 — 2D editor ✅ complete**
**Phase 2 — AI photo-to-pattern ✅ complete**

---

## How to Use the Editor

### Drawing Tools

| Icon | Tool | Key | How to use |
|------|------|-----|-----------|
| ↖ | **Select** | S | Click to select. Shift+click for multi-select. Drag to move. Box-drag to bulk-select. Delete to remove. |
| ╱ | **Line** | L | Click start → click end. Each new click extends the chain. Click the start point again or press Enter to close into a piece. |
| ∿ | **Curve** | C | **Three-click arc control:** (1) Click start. (2) Click end. (3) Move cursor to shape the arc — the curve passes through wherever your cursor is. Click to commit. Chain with lines/curves; Enter closes the outline. |
| · | **Point** | P | Place an invisible snap anchor. Doesn't appear in exports. |
| ⊡ | **Seam Allow.** | A | Click a closed pattern piece to set its seam allowance (cm). |
| ↕ | **Grain Line** | G | Click and drag to draw a grain line arrow (shows fabric direction). |
| \| | **Notch** | N | Click on any line or curve to place a notch mark. Angle is auto-calculated from the element's tangent. |
| ✕ | **Eraser** | E | Click any element to delete it. |

### Toolbar Toggles (bottom of toolbar)

| Button | Function |
|--------|---------|
| # | Toggle grid (major lines every 5 cm) |
| ⊕ | Toggle snapping (endpoint, midpoint, grid, angle) |
| ⊡ | Toggle seam allowance offset display |
| ? | Open Tool Reference — full help panel |

---

## Piece Workflow

1. **Draw an outline** — use the Line or Curve tool to create a closed shape. Lines and curves can be mixed.
2. **Close it** — click the first point again (snaps when close enough) or press Enter. A pattern piece is created automatically.
3. **Edit the piece** — click to select it. The Properties panel (right sidebar) shows name, cut quantity, on-fold flag, and seam allowance.
4. **Annotate** — add a grain line and notch marks to the piece.
5. **Parametric formulas** — select a line and enter a formula like `hip / 4 + 1` in the Formula field. Changing body measurements automatically resizes the element.
6. **Export** — save as `.psnap` (Ctrl+S), export SVG, or export tiled PDF (requires backend server).

---

## Curve Tool Detail

The curve tool uses a **through-point arc** model. After placing start and end points, you move your cursor to a point the curve should pass through — the Bezier control points are computed automatically so the curve arcs through that position at its midpoint.

After placing a curve, select it to see:
- **Chord** — straight-line distance from start to end
- **Arc length** — actual length along the curve
- **Arc height** — perpendicular offset from the chord midpoint; edit this number to reshape the curve precisely (positive = left of chord direction)

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| S / L / C / P / A / G / N / E | Switch to named tool |
| Ctrl+Z / Ctrl+Y | Undo / Redo (50 levels) |
| Ctrl+S | Save as .psnap |
| Ctrl+N | New piece — resets chain, switches to Line tool |
| Enter | Close current outline into a pattern piece |
| Escape | Cancel / deselect all |
| Delete / Backspace | Delete selected element or piece |
| Ctrl+G | Toggle grid |
| Ctrl+Shift+S | Toggle snap |
| Ctrl+= / Ctrl+- | Zoom in / out |
| Ctrl+0 | Fit to screen |
| Scroll wheel | Zoom (centred on cursor) |
| Space + drag | Pan |
| Shift (while drawing) | Constrain to 45° angle increments |

---

## Snap System

Snap radius is 8 screen pixels, converted to canvas coordinates at the current zoom level.

| Indicator colour | Snap type |
|-----------------|-----------|
| Red | Endpoint |
| Orange | Midpoint |
| Blue | Grid (0.5 cm) |
| Purple | Angle 45° (Shift held) |

Snap priority: endpoint > midpoint > grid > angle.

---

## Documentation

Detailed technical docs live in [Docs/](Docs/):

| File | Contents |
|------|----------|
| [Docs/architecture.md](Docs/architecture.md) | Stack, project structure, coordinate system, state management, API reference, file format |

---

## AI Assist (Phase 2)

The **AI Assist** button in the header opens a two-step workflow:

1. **Upload photo** — select a JPEG/PNG front-view photo of the skirt (back photo optional). The app calls `/api/analyze` which uses Claude's vision API to detect silhouette, waistband, closure, dart count, and details.
2. **Review & generate** — confirm or correct the detected features and enter your measurements, then click "Generate Pattern". The app calls `/api/generate` which runs the Aldrich parametric engine and returns a `.psnap` file that loads directly into the editor.

Supported silhouettes: **straight, pencil, a-line, circle, gathered, pleated, wrap**.

Requires `ANTHROPIC_API_KEY` set in the backend environment.

---

## Architecture

```
Seamster/
├── frontend/               React 18 + TypeScript + Tailwind + Vite
│   └── src/
│       ├── components/
│       │   ├── Canvas.tsx          Main SVG canvas — all drawing tools, snapping, rendering
│       │   ├── Toolbar.tsx         Left tool-button column (8 tools + 3 toggles + help)
│       │   ├── HelpPanel.tsx       Tool reference modal (? button)
│       │   ├── PropertiesPanel.tsx Right sidebar — element and piece editing
│       │   ├── MeasurementPanel.tsx Body measurements with range validation
│       │   └── AIAssistModal.tsx   Phase 2: photo upload + feature review + generate workflow
│       ├── context/
│       │   └── EditorContext.tsx   Redux-style reducer; ~30 action types; 50-level undo stack
│       ├── snapping/
│       │   └── snapEngine.ts       Endpoint / midpoint / grid / angle snap with colour coding
│       ├── export/
│       │   ├── svgExport.ts        Client-side SVG export
│       │   └── pdfExport.ts        Backend-assisted tiled PDF (A4)
│       ├── utils/
│       │   ├── formulaEval.ts      Sandboxed expression parser (no eval) for parametric dims
│       │   └── pieceTransforms.ts  Flip H/V, rotate, mirror-copy geometry
│       └── types/
│           └── index.ts            Element, Piece, Measurement TypeScript interfaces
│
└── backend/                Python 3.12 + FastAPI
    └── app/
        ├── main.py                 FastAPI app, CORS config
        ├── api/export.py           POST /api/export/pdf — returns tiled PDF binary
        ├── api/analyze.py          POST /api/analyze — Claude vision → SkirtFeatures JSON
        ├── api/generate.py         POST /api/generate — parametric engine → .psnap JSON
        ├── patterns/
        │   ├── geometry.py         Point, offset_polygon, cubic/quadratic bezier
        │   ├── skirts.py           Aldrich straight skirt base block (PieceSpec + DartSpec)
        │   ├── modifiers.py        Silhouette modifiers (pencil, a-line, circle, wrap, etc.)
        │   └── engine.py           generate_pattern() → full .psnap JSON dict
        ├── vision/
        │   ├── analyzer.py         Claude API call + JSON parse + retry logic
        │   └── prompts.py          System + user prompt templates
        └── export/pdf_tiler.py     reportlab tiled PDF with registration marks
```

### Canvas coordinate system

- 1 SVG unit = 1 cm
- `BASE_SCALE` = 20 px/cm at zoom 1.0
- All element coordinates stored in cm; display transforms applied via SVG `<g transform>` wrapper
- Seam allowance computed by offsetting each polygon edge perpendicular to its direction

### State management

`EditorContext` holds the full editor state:
- `elements` — array of `CanvasElement` (line, curve, grain-line, notch, anchor-point)
- `pieces` — array of `PatternPiece` (elementIds, name, cutQty, onFold, seamAllowance)
- `measurements` — `Record<string, number>` body measurements
- `selectedIds` / `selectedPieceId` — selection state
- `zoom`, `pan` — viewport state
- `showGrid`, `snapEnabled`, `showSeamAllowance` — toggles
- `undoStack`, `redoStack` — 50-level snapshots

### File format (`.psnap`)

JSON with top-level keys: `version`, `elements`, `pieces`, `measurements`.

---

## Setup

### Prerequisites

- Python 3.12+, Node.js 18+
- Anthropic API key (Phase 2 only)

### Quick start

```bash
bash init.sh
```

Or manually:

```bash
# Frontend
cd frontend
npm install
npm run dev       # http://localhost:5173

# Backend (separate terminal, needed for PDF export)
cd backend
python -m venv venv
venv\Scripts\activate         # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload # http://localhost:8000
```

### Running tests

```bash
# Frontend
cd frontend
npm run test

# Backend
cd backend
pytest
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Phase 2 only | — | Claude API key for vision analysis |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-20250514` | Model identifier |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Allowed frontend origins |
| `DEFAULT_SEAM_ALLOWANCE_CM` | No | `1.5` | Default seam allowance for new pieces |

# PatternSnap — Architecture

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| Backend | Python 3.12, FastAPI |
| Canvas | SVG (no canvas element) |
| State | Custom reducer in `EditorContext` (no external state library) |

---

## Project Structure

```
Seamster/
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── Canvas.tsx            Main SVG canvas — all drawing tools, snapping, rendering
│       │   ├── Toolbar.tsx           Left tool-button column (8 tools + 3 toggles + help)
│       │   ├── HelpPanel.tsx         Tool reference modal
│       │   ├── PropertiesPanel.tsx   Right sidebar — element and piece editing
│       │   └── MeasurementPanel.tsx  Body measurements with range validation
│       ├── context/
│       │   └── EditorContext.tsx     Redux-style reducer; ~30 action types; 50-level undo stack
│       ├── snapping/
│       │   └── snapEngine.ts         Endpoint / midpoint / grid / angle snap
│       ├── export/
│       │   ├── svgExport.ts          Client-side SVG export
│       │   └── pdfExport.ts          Backend-assisted tiled PDF (A4)
│       ├── utils/
│       │   ├── formulaEval.ts        Sandboxed expression parser for parametric dims
│       │   └── pieceTransforms.ts    Flip H/V, rotate, mirror-copy geometry
│       └── types/
│           └── index.ts              Element, Piece, Measurement TypeScript interfaces
│
├── backend/
│   └── app/
│       ├── main.py                   FastAPI app, CORS config
│       ├── api/export.py             POST /api/export/pdf — returns tiled PDF binary
│       ├── api/analyze.py            Phase 2: POST /api/analyze (Claude vision)
│       ├── api/generate.py           Phase 2: POST /api/generate (parametric engine)
│       └── export/pdf_tiler.py       reportlab tiled PDF with registration marks
│
├── Docs/                             Technical documentation
├── harness/                          AI workflow files (gitignored)
└── README.md
```

---

## Coordinate System

- 1 SVG unit = 1 cm
- `BASE_SCALE` = 20 px/cm at zoom 1.0
- All element coordinates stored in cm; display transforms applied via SVG `<g transform>` wrapper
- Pan and zoom are viewport transforms only — stored coordinates never change

---

## State Management

`EditorContext` holds the complete editor state and is the single source of truth:

| Key | Type | Description |
|-----|------|-------------|
| `elements` | `CanvasElement[]` | All lines, curves, grain-lines, notches, anchor-points |
| `pieces` | `PatternPiece[]` | Closed outlines with metadata |
| `measurements` | `Record<string, number>` | Body measurements driving parametric formulas |
| `selectedIds` | `string[]` | Currently selected element IDs |
| `selectedPieceId` | `string \| null` | Currently selected piece ID |
| `zoom` | `number` | Viewport zoom level |
| `pan` | `{x, y}` | Viewport pan offset |
| `showGrid` | `boolean` | Grid visibility toggle |
| `snapEnabled` | `boolean` | Snap-to-point toggle |
| `showSeamAllowance` | `boolean` | Seam allowance overlay toggle |
| `undoStack` / `redoStack` | `EditorState[][]` | 50-level history snapshots |

Actions are dispatched via `useReducer`. The undo stack snapshots the full state on every mutating action.

---

## Snapping

Snap radius is 8 screen pixels, converted to canvas coordinates at the current zoom level.

| Priority | Colour | Type |
|----------|--------|------|
| 1 | Red | Endpoint |
| 2 | Orange | Midpoint |
| 3 | Blue | Grid (0.5 cm) |
| 4 | Purple | Angle 45° (Shift held) |

---

## Seam Allowance

Computed by offsetting each polygon edge perpendicular to its direction by the piece's `seamAllowance` (cm). The offset polygon is rendered as a dashed overlay and not stored in state — it is derived on render.

---

## Curve Model

The curve tool uses a **through-point arc** model. After placing start and end points, the user moves the cursor to a point the curve should pass through. Bezier control points are computed so the curve passes through that point at its parametric midpoint (t=0.5).

Editable properties after placement:
- **Arc height** — perpendicular offset from chord midpoint; positive = left of chord direction
- **Chord** — straight-line distance (read-only display)
- **Arc length** — actual length along the curve (read-only display)

---

## Parametric Formulas

`formulaEval.ts` provides a sandboxed math expression parser (no `eval`). Variables are body measurement keys (e.g., `hip`, `waist`, `bust`). Example: `hip / 4 + 1`.

Formulas are stored on elements and re-evaluated whenever `measurements` changes.

---

## File Format (`.psnap`)

JSON with top-level keys:

```json
{
  "version": 1,
  "elements": [...],
  "pieces": [...],
  "measurements": { "bust": 90, "waist": 70, "hip": 96 }
}
```

---

## Backend API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/export/pdf` | POST | Accepts SVG string + page size, returns tiled PDF binary |
| `/api/analyze` | POST | Phase 2: Claude vision — analyzes a garment photo |
| `/api/generate` | POST | Phase 2: Generates parametric pattern from measurements |

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | Active | 2D canvas editor — draw, annotate, export |
| 2 | Planned | AI photo-to-pattern — Claude vision + parametric engine |

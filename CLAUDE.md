# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PatternSnap** is a browser-based sewing pattern editor. Users draft patterns on a 2D canvas using lines and curves that snap together, with dimensions driven by body measurement formulas. Phase 2 (later) will add AI photo analysis to auto-generate a starting pattern for the user to refine.

**Phase 1 priority: the 2D editor.** AI features come after the editor is solid.

**Key Document:** `patternsnap_full_prd.md` — complete PRD covering both phases, tech stack, feature specs, and acceptance criteria.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Tailwind CSS + Vite |
| Canvas rendering | Inline SVG (React SVG elements; 1 SVG unit = 1 cm) |
| State management | React Context + useReducer |
| Testing | Vitest + React Testing Library |
| Backend | Python 3.12 + FastAPI (PDF export; Phase 2 AI) |
| PDF export | reportlab |

## Project Structure

```
patternsnap/
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Canvas.tsx            # SVG canvas, pan/zoom, grid, rulers
│   │   │   ├── Toolbar.tsx           # Tool buttons and keyboard shortcuts
│   │   │   ├── PropertiesPanel.tsx   # Context-sensitive element properties
│   │   │   ├── MeasurementPanel.tsx  # Body measurements + formula evaluation
│   │   │   └── ExportModal.tsx       # SVG / PDF export options
│   │   ├── tools/
│   │   │   ├── SelectTool.ts         # Select, move, delete
│   │   │   ├── LineTool.ts           # Draw straight line segments
│   │   │   ├── CurveTool.ts          # Draw cubic bezier curves
│   │   │   ├── SeamAllowanceTool.ts  # Offset outline generation
│   │   │   ├── GrainLineTool.ts      # Grain line annotation
│   │   │   └── NotchTool.ts          # Notch tick marks
│   │   ├── snapping/
│   │   │   └── snapEngine.ts         # Endpoint, midpoint, grid, angle snapping
│   │   ├── context/
│   │   │   └── EditorContext.tsx     # Canvas state, elements, measurements, undo stack
│   │   ├── export/
│   │   │   ├── svgExport.ts          # Client-side SVG export
│   │   │   └── pdfExport.ts          # Backend-assisted tiled PDF export
│   │   └── types/
│   │       └── index.ts              # Element, Piece, Measurement TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI app, CORS, routes
│   │   ├── api/
│   │   │   ├── export.py             # /api/export/pdf endpoint
│   │   │   ├── analyze.py            # /api/analyze (Phase 2 — Claude vision)
│   │   │   └── generate.py          # /api/generate (Phase 2 — parametric engine)
│   │   └── export/
│   │       └── pdf_tiler.py          # Tiled PDF with registration marks
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
└── README.md
```

## High-Level Architecture

### Phase 1 Data Flow (Editor)

1. User draws lines/curves on the SVG canvas with snapping active.
2. Lines can reference body measurement formulas (e.g., `hip / 2 + 1`).
3. Closing an outline creates a pattern piece; seam allowance tool adds offset.
4. User saves pattern as `.psnap` JSON file (download) or exports as SVG/PDF.
5. Tiled PDF generated server-side via `/api/export/pdf` (reportlab).

### Phase 2 Data Flow (AI Assist — added later)

1. User uploads garment photo → `/api/analyze` → Claude vision returns `SkirtFeatures`.
2. User confirms/edits detected features.
3. `/api/generate` runs the parametric engine → returns `.psnap` JSON.
4. Frontend loads the `.psnap` into the editor; user refines as needed.

## Development Workflow

### Feature Execution Order

Work through `FEATURES.json` sequentially. The first 17 features are Phase 1 (editor). The last 4 (`ai-*` category) are Phase 2 and should not be started until all Phase 1 features pass.

### Build Commands

#### Frontend
```bash
cd frontend
npm install
npm run dev       # Vite dev server at localhost:5173
npm run test      # Vitest
npm run build     # Production build
```

#### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload  # localhost:8000
pytest
```

## Key Conventions

**Canvas / SVG:**
- All coordinates in **cm**. One SVG user unit = 1 cm. Never mix pixels and cm in element geometry.
- ViewBox origin is (0, 0) at top-left of the pattern workspace; canvas transforms (pan/zoom) are applied via an SVG `<g transform="...">` wrapper, not by modifying element coordinates.
- Hit-testing uses SVG DOM events (`onMouseEnter`, `onMouseDown` on elements), not manual geometry checks.

**Snapping:**
- Snap radius is always expressed in **screen pixels** (8px default), converted to canvas coordinates using the current zoom level before comparison.
- Snap priority order: endpoint > intersection > midpoint > perpendicular > grid.

**Parametric formulas:**
- Formulas are plain strings stored on each element. Evaluated with a sandboxed expression parser (no `eval`). Variables are measurement names, case-insensitive.
- If a measurement is missing, the formula result is `null`; the element retains its last valid length.

**State management:**
- All canvas elements live in `EditorContext`. Undo stack stores snapshots of the full element list (immutable updates).
- Measurements live separately in `EditorContext.measurements`; formula evaluation is a derived computation, not stored state.

**Export:**
- SVG export is client-side only (no server round-trip).
- PDF tiling requires the backend (`/api/export/pdf` accepts SVG string, returns PDF binary).

## Environment Variables

| Variable | Description | Required | Default |
|----------|------------|----------|---------|
| `ANTHROPIC_API_KEY` | Claude vision API key (Phase 2 only) | Phase 2 | — |
| `CLAUDE_MODEL` | Model identifier | No | `claude-sonnet-4-20250514` |
| `CORS_ORIGINS` | Allowed frontend origins | No | `http://localhost:5173` |
| `DEFAULT_SEAM_ALLOWANCE_CM` | Default seam allowance | No | `1.5` |

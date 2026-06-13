# Seamster

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

## Assembly View

After generating a pattern with AI Assist, an **Assembly View** button appears in the header. Click it to replace the canvas with a view showing how the pieces connect.

- **Flat / Assembly mode** — pieces are arranged edge-to-edge using BFS seam alignment. Each piece is rotated and positioned so its shared seam edge sits flush against the neighbouring piece, letting you visualise the 3D construction at a glance. This mode activates automatically when the pattern has `connections` data.
- **Grid mode** — pieces are laid out in a grid. Dashed arcs connect matching seam edges across pieces. Toggle between modes with the button at the top-right of the view.
- **Seam Guide** — a legend on the right side lists every seam label with its colour. Hovering a label or any edge highlights all matching edges across all pieces.

Seam colour coding:

| Label | Colour |
|-------|--------|
| side_seam | Blue |
| shoulder | Violet |
| armhole | Pink |
| waist / waist_seam | Amber |
| hem | Emerald |
| inseam | Cyan |
| crotch | Red |
| sleeve_seam | Indigo |
| neckline | Orange |
| wrist | Lime |
| yoke_seam | Purple |
| fold lines | Light grey (dashed) |

Assembly View is only shown when the canvas has at least one pattern piece. Connections are computed automatically by the backend when generating a pattern and stored in the `.psnap` file.

---

## Sewing Instructions

After generating a pattern with AI Assist, an **Instructions** button appears in the header. If instructions have not yet been generated it reads "Generate Instructions"; once generated it reads "Instructions". Click it to open the step-by-step sewing guide in a slide-out panel.

- Instructions are generated on demand when you click the button — the panel shows a loading skeleton, then populates with sections.
- Sections follow construction order: **Fabric Preparation → Cutting & Marking → Interfacing & Stabilising → Construction → Closures → Waistband / Collar / Sleeves (conditional) → Hem & Finishing → Pressing & Quality Check**.
- Each step references the exact piece names from the canvas.
- Steps include optional **Tip** callouts (common beginner mistakes to avoid).
- The **Regenerate** button in the panel header fires a fresh API call to produce a new set of instructions.
- Instructions are scoped to the specific garment — a trouser pattern produces a completely different guide from a skirt.
- Instructions are saved inside `.psnap` files and restored on open.

Requires a configured LLM provider (Anthropic by default, or local Ollama — see [How to run](#how-to-run)). Instructions call `POST /api/instructions` which uses the same provider/model as pattern analysis.

---

## AI Assist (Phase 2)

The **AI Assist** button in the header opens a two-step workflow:

1. **Upload photo** — select a garment type, then upload a JPEG/PNG front-view photo (back photo optional). The app calls `/api/analyze` which uses the configured LLM's vision API (Claude or a vision-capable Ollama model) to detect silhouette, waistband, closure, dart count, and details.
2. **Review & generate** — confirm or correct the detected features and enter your measurements, then click "Generate Pattern". The app calls `/api/generate` which runs the Aldrich parametric engine and returns a `.psnap` file that loads directly into the editor.

A **Dev — load saved analysis** mode lets you paste or load a saved analysis JSON response to skip the LLM call (useful for testing).

Supported garment types and fit styles:

| Type | Fit styles |
|------|-----------|
| **Skirt** | straight, pencil, a-line, flared, circle, gathered, pleated, wrap, trumpet, mermaid, tulip, tiered |
| **Shirt / Blouse** | slim, fitted, regular, relaxed, boxy, oversized, athletic, longline |
| **Trousers / Pants** | skinny, slim, cigarette, fitted, regular, relaxed, wide_leg, flared, bootcut, palazzo, jogger |
| **Dress** | shift, sheath, a-line, fit-and-flare, wrap, bodycon, empire |
| **Jacket / Blazer** | fitted, slim, regular, relaxed, boxy, oversized, moto, bomber, military, denim, anorak, varsity |

Jacket axes beyond silhouette:

| Axis | Options |
|------|---------|
| **collar_type** | `notch_lapel` (default), `peak_lapel` (taller), `shawl_collar` (wider), `band_collar` (narrow stand), `no_collar` (omit piece) |
| **breast_style** | `single_breasted` (default), `double_breasted` (wider facing + extended front width) |
| **length_category** | `waist_length` (40 cm), `cropped` (45 cm), `hip_length` (60 cm), `below_hip` (72 cm), `knee` |

Jacket detail pieces generated on demand:

| Piece(s) | Triggered by |
|----------|-------------|
| Back Yoke + Back Panel | `back_yoke`, `yoke`, `western_yoke` |
| Collar | `collar` (height/width driven by `collar_type`) |
| Front Facing | `lapels`, `facing`, `lining_visible`, lapel details, or button-front closure (width driven by `breast_style`) |
| Patch Pocket | `patch_pockets` |
| Welt Strip + Pocket Bag | `welt_pockets` |
| Breast Pocket Welt + Bag | `breast_pocket`, `chest_pocket`, `chest_welt` |
| In-Seam Pocket Bag | `in_seam_pockets`, `slash_pockets`, `side_pockets` |
| Woven Cuff | `cuffs`, `button_cuff`, `snap_cuff`, `woven_cuff` |
| Sleeve Placket | `sleeve_placket`, `cuff_vent` |
| Cuff Band (rib knit) | `cuff_band`, `ribbed_cuffs`, `knit_cuffs`, or bomber/varsity silhouette |
| Hem Band (rib knit) | `hem_band`, `ribbed_hem`, `knit_hem`, or bomber/varsity silhouette |
| Hood Panel | `hood` |
| Belt Strap | `belt`, `belt_strap`, `self_belt` |
| Epaulet Tab | `epaulets`, `epaulet_tab`, `shoulder_tab` |
| Back Lining + Front Lining | `lining_visible` |
| Upper Sleeve + Under Sleeve | `two_piece_sleeve`, `tailored_sleeve`, or fitted/slim/moto/military silhouette (auto) |

Optional detail pieces for other garments: side pocket bag, back welt pocket, kick-pleat facing, ruffle/tier strip.

Requires a configured LLM provider (Anthropic or Ollama) in the backend environment.

---

## Architecture

```
Seamster/
├── frontend/               React 18 + TypeScript + Tailwind + Vite
│   └── src/
│       ├── components/
│       │   ├── Canvas.tsx              Main SVG canvas — all drawing tools, snapping, rendering
│       │   ├── Toolbar.tsx             Left tool-button column (8 tools + 3 toggles + help)
│       │   ├── HelpPanel.tsx           Tool reference modal (? button)
│       │   ├── PropertiesPanel.tsx     Right sidebar — element and piece editing
│       │   ├── MeasurementPanel.tsx    Body measurements with range validation
│       │   ├── AIAssistModal.tsx       Phase 2: photo upload + feature review + generate workflow
│       │   ├── InstructionsPanel.tsx   Sewing instructions drawer — sections, steps, tips
│       │   └── AssemblyView.tsx        Assembly view — flat-lay BFS alignment + grid view with seam arc connections
│       ├── context/
│       │   └── EditorContext.tsx       Redux-style reducer; ~30 action types; 50-level undo stack
│       ├── snapping/
│       │   └── snapEngine.ts           Endpoint / midpoint / grid / angle snap with colour coding
│       ├── export/
│       │   ├── svgExport.ts            Client-side SVG export
│       │   └── pdfExport.ts            Backend-assisted tiled PDF (A4)
│       ├── utils/
│       │   ├── formulaEval.ts          Sandboxed expression parser (no eval) for parametric dims
│       │   └── pieceTransforms.ts      Flip H/V, rotate, mirror-copy geometry
│       └── types/
│           └── index.ts                Element, Piece, SeamConnection, Measurement TypeScript interfaces
│
└── backend/                Python 3.12 + FastAPI
    └── app/
        ├── main.py                     FastAPI app, CORS config
        ├── api/export.py               POST /api/export/pdf — returns tiled PDF binary
        ├── api/analyze.py              POST /api/analyze — LLM vision → GarmentFeatures JSON
        ├── api/generate.py             POST /api/generate — parametric engine → .psnap JSON
        ├── api/instructions.py         POST /api/instructions — features+pieces → sewing instructions JSON
        ├── patterns/
        │   ├── geometry.py             Point, offset_polygon, cubic/quadratic bezier
        │   ├── skirts.py               Skirt block: 12 silhouettes, 6 lengths, 4 optional pieces (PieceSpec + DartSpec)
        │   ├── shirts.py               Shirt/blouse block: 8 fit styles, 13 necklines, 9 sleeve types
        │   ├── trousers.py             Trouser/pants block: 11 fit styles, 4 rise styles, 5 lengths, 8 optional pieces
        │   ├── dresses.py              Dress block: 7 silhouettes, 10 necklines, 6 sleeve types, 6 optional pieces
        │   ├── jackets.py              Jacket/blazer block: 12 fit styles, 5 lengths, 5 sleeve types, 2 collar-type axes, 2 breast-style options, 16 conditional pieces
        │   ├── modifiers.py            Legacy silhouette modifiers (used by skirt tests only)
        │   ├── engine.py               generate_pattern() → full .psnap JSON dict; _compute_connections() auto-builds SeamConnection list from edge_labels
        │   ├── instruction_generator.py  LLM call → structured sewing instructions JSON
        │   └── llm_fallback.py         LLM-generated parametric pieces for unsupported details (template-cached)
        ├── llm/                        Provider-agnostic LLM layer (Anthropic + Ollama)
        │   ├── base.py                 LLMProvider ABC, LLMResponse, common error hierarchy
        │   ├── anthropic_provider.py   Anthropic Claude implementation (text + vision)
        │   ├── ollama_provider.py      Local Ollama implementation via httpx /api/chat
        │   └── factory.py              get_provider() + shared retry & JSON-parse helpers
        ├── vision/
        │   ├── analyzer.py             LLM vision call + JSON parse (retry via llm layer)
        │   └── prompts.py              System + user prompt templates
        └── export/pdf_tiler.py         reportlab tiled PDF with registration marks
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
- `connections` — array of `SeamConnection` (label, from/to pieceId+edgeId pairs); auto-populated on generate
- `measurements` — `Record<string, number>` body measurements
- `selectedIds` / `selectedPieceId` — selection state
- `zoom`, `pan` — viewport state
- `showGrid`, `snapEnabled`, `showSeamAllowance` — toggles
- `undoStack`, `redoStack` — 50-level snapshots
- `instructions` / `instructionsLoading` — sewing instructions state (null until generated)
- `lastFeatures` / `lastMeasurements` — the inputs used for the last generate call (used to regenerate instructions)

### File format (`.psnap`)

JSON with top-level keys: `version`, `elements`, `pieces`, `measurements`, `connections`.

- Each `line` element has `isFold: boolean` and `seamLabel: string` fields.
- Each `curve` element has a `seamLabel: string` field.
- `connections` is an array of `{ label, from: { pieceId, edgeId }, to: { pieceId, edgeId } }` objects — generated automatically by the backend engine by matching edges with the same non-empty `seamLabel` across different pieces.

---

## Documentation

Detailed technical docs live in [Docs/](Docs/):

| File | Contents |
|------|----------|
| [Docs/codebase-guide.md](Docs/codebase-guide.md) | **Start here** — the complete guide: what every part does, where it lives, *why* each technology was chosen, domain glossary, end-to-end data flows, and a "how do I find…" task index |
| [Docs/architecture.md](Docs/architecture.md) | Stack, project structure, coordinate system, state management, API reference, file format |
| [Docs/architecture-map.md](Docs/architecture-map.md) | Full architecture map — all modules, edges, data flows, tech stack, key files reference |
| [Docs/architecture-map.html](Docs/architecture-map.html) | Interactive node-graph — hover/click modules, animate data flows, drag to rearrange (open in browser) |
| [Docs/implementation-guide.md](Docs/implementation-guide.md) | **Step-by-step build guide** — every feature broken into small actionable steps with sample code; shows current position in the project |
| [Docs/canvas-decisions.md](Docs/canvas-decisions.md) | **Canvas design decisions** — coordinate system, all tools, snapping, line/curve creation, selection, moving, node/endpoint handles, undo, keyboard shortcuts |
| [Docs/presentation.md](Docs/presentation.md) | **Presentation overview** — project summary, tech-stack rationale, shirt photo→export flow chart, 3 problems faced, future improvements (Mermaid diagrams) |

---

## Setup

### Prerequisites

- Python 3.11+, Node.js 18+
- Anthropic API key (Phase 2 only)

### Quick start

**1. Install uv** (Python package manager — one-time):

```bash
pip install uv
# or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Frontend** (terminal 1):

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
```

**3. Backend** (terminal 2):

```bash
cd backend
uv sync --group dev                                          # create .venv + install all deps
uv run uvicorn app.main:app --reload --port 8000             # http://localhost:8000
```

Set your API key before starting the backend if you want AI features:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # macOS / Linux
$env:ANTHROPIC_API_KEY="sk-ant-..."   # Windows PowerShell
```

#### Using a local open-source model (Ollama)

The backend supports two LLM providers, selected with the `LLM_PROVIDER` env var:
`anthropic` (cloud Claude, default) or `ollama` (local, free, no API key). To run
fully locally:

```bash
# 1. Install Ollama (https://ollama.com) and pull a vision-capable model
ollama pull qwen2.5vl:7b

# 2. Point the backend at Ollama
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=qwen2.5vl:7b           # vision model needed for /analyze
export OLLAMA_BASE_URL=http://localhost:11434
```

The selected provider/model is reported by `GET /api/health`. Photo analysis
(`/analyze`) needs a **vision-capable** model; text-only models still work for
instruction generation and the novel-piece fallback.

**Switching at runtime.** The app header has a **Model** toggle (Claude ↔ Local)
that flips the active provider for every AI action without restarting the server.
It calls `GET`/`POST /api/provider`; the choice is held in the backend process
memory and overrides `LLM_PROVIDER` until changed or the server restarts (it is
not persisted to disk, so `LLM_PROVIDER` still sets the startup default).

**Model choice matters.** Small models (e.g. `llava`) produce unreliable,
self-contradictory garment analysis. `qwen2.5vl:7b` follows the JSON schema well
and loads on all current Ollama builds. Avoid `llama3.2-vision`: it's strong in
principle but its `mllama` architecture fails to load on many Ollama versions
(`unknown model architecture: 'mllama'`). For best quality overall, use the
Anthropic provider.

### Running tests

```bash
# Frontend
cd frontend
npm run test

# Backend
cd backend
uv run pytest
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `anthropic` | LLM backend: `anthropic` (cloud) or `ollama` (local) |
| `ANTHROPIC_API_KEY` | When `LLM_PROVIDER=anthropic` | — | Claude API key for vision analysis, pattern generation, and instructions |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Anthropic model identifier |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL (when `LLM_PROVIDER=ollama`) |
| `OLLAMA_MODEL` | No | `qwen2.5vl:7b` | Ollama model; must be vision-capable for `/analyze` |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Allowed frontend origins |
| `DEFAULT_SEAM_ALLOWANCE_CM` | No | `1.5` | Default seam allowance for new pieces |

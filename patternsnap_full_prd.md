# PatternSnap — Full Project PRD
## Interactive Pattern Editor + AI-Assisted Generation
**v2.0 — May 2026**

> **Covers:** Phase 1 (2D Pattern Editor) → Phase 2 (AI Photo-to-Pattern)

---

## 1. Product Vision

PatternSnap is a browser-based sewing pattern editor where users draft, edit, and export professional-grade patterns on a 2D canvas. Patterns are built from snappable lines and curves, with dimensions driven by the user's body measurements. In a later phase, AI photo analysis can generate a starting pattern that the user then refines in the editor.

### 1.1 Problem Statement

Home sewists and patternmakers currently rely on:

- Paper and pencil drafting (slow, imprecise, hard to iterate)
- Desktop CAD software (Seamly2D, Valentina) that is complex and Windows/Mac-only
- Commercial patterns in standard sizes (not body-custom)

PatternSnap closes this gap with a precise, browser-based parametric drafting tool — accessible to anyone without a software install, and driven by the user's own measurements.

### 1.2 Target Users

- **Primary:** Home sewists who can sew from a pattern and want to draft custom patterns fitted to their measurements.
- **Secondary:** Fashion students learning patternmaking who want a digital drafting board.
- **Tertiary (Phase 2):** Users who have a reference garment and want to reverse-engineer a starting pattern from a photo.

### 1.3 Key Value Propositions

| Value | Description |
|-------|-------------|
| Precision | Snap-based geometry ensures seam lengths match and corners are exact |
| Body-custom | Every dimension can reference a body measurement by formula |
| Browser-based | No install, works on any OS with a modern browser |
| Exportable | Tiled PDF for home printing, SVG for digital use |

---

## 2. Phased Roadmap

| Phase | Scope | Key Milestone |
|-------|-------|---------------|
| Phase 1: Editor | 2D canvas pattern editor — draw, snap, measure, export | First complete skirt pattern drafted and printed to scale |
| Phase 2: AI Assist | Upload garment photo → AI generates initial pattern → user edits in the Phase 1 editor | Full photo-to-edited-pattern workflow |

---

## 3. Phase 1: 2D Pattern Editor

### 3.1 Core Concept

The editor presents a **metric 2D canvas** (like graph paper on-screen). The user creates one or more **pattern pieces** by drawing outlines with lines and curves. Every line length can optionally be **parameterized** — linked to a body measurement formula (e.g., `hip / 2 + 1`). When the user updates a measurement, all linked dimensions update automatically.

### 3.2 Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite |
| Canvas rendering | SVG (inline React SVG elements for precision + easy export) |
| State management | React Context + useReducer |
| Styling | Tailwind CSS |
| Testing | Vitest + React Testing Library |
| Backend | Python 3.12 + FastAPI (PDF tiling, later AI) |
| PDF export | reportlab (backend) |
| Packaging | npm (frontend), pip + venv (backend) |

**Why SVG over Canvas2D?** SVG elements map directly to pattern lines/curves, can be exported at real-world scale (cm viewBox), and allow DOM-level hit-testing for selection. This avoids a separate scene graph.

### 3.3 Canvas & Viewport

- Infinite canvas with **pan** (middle-click drag or Space+drag) and **zoom** (scroll wheel).
- **Grid overlay:** major gridlines every 5 cm, minor every 1 cm. Togglable.
- **Ruler bars** on top and left edges showing cm values.
- All coordinates stored in **centimetres** (one SVG user unit = 1 cm).
- Zoom levels: 25% – 400%. Default: fit-to-window on load.

### 3.4 Drawing Tools

| Tool | Shortcut | Behaviour |
|------|----------|-----------|
| Select | S | Click to select elements; drag to box-select; move by dragging |
| Line | L | Click start → click end; creates a straight line segment |
| Curve | C | Click start → click control point → click end; creates a cubic bezier |
| Point | P | Place an isolated anchor point (used as snap targets) |
| Seam Allowance | A | Click a line or closed piece to add an offset outline |
| Grain Line | G | Draw a straight line annotated as the grain direction |
| Notch | N | Click on a line to add a small perpendicular tick mark |
| Measure | M | Click two points to display the distance |
| Eraser | E | Click an element to delete it |

### 3.5 Snapping

Snapping is active by default and can be toggled per-type:

| Snap Type | Description |
|-----------|-------------|
| Endpoint snap | Snap to the start or end of any existing line/curve |
| Midpoint snap | Snap to the midpoint of a line |
| Grid snap | Snap to the nearest cm or 0.5 cm grid intersection |
| Perpendicular snap | When drawing a line from a point on an existing line, snap to 90° |
| Angle snap | Constrain a line to 0°, 45°, 90°, 135° (hold Shift) |
| Intersection snap | Snap to where two lines cross |

Snap indicators: coloured glyph appears at the snap target when cursor is within 8 screen pixels.

### 3.6 Measurement Panel & Parametric Dimensions

A collapsible panel on the right lists **body measurements**. The user enters their values once:

| Measurement | Default | Range |
|-------------|---------|-------|
| Waist | — | 40–160 cm |
| Hip | — | 50–180 cm |
| Waist-to-Hip | — | 10–35 cm |
| Skirt Length | — | 20–150 cm |
| Bust | — | 60–160 cm |
| Back Length (nape→waist) | — | 30–55 cm |
| Shoulder Width | — | 30–55 cm |
| Inseam | — | 50–90 cm |

**Parametric line lengths:** When a line is selected, its length field in the Properties panel accepts a formula: `hip / 2 + 1`. Variables are the measurement names (case-insensitive). Computed value shown in real-time. If a measurement is undefined, the formula shows `?` and the line retains its last manual length.

### 3.7 Pattern Pieces

- Each closed outline on the canvas is a **pattern piece** (front skirt, back skirt, waistband, etc.).
- Pieces can be named in the Properties panel.
- **Close a piece** by snapping the last point to the first point (or pressing `Enter`).
- Closed pieces get a light fill to signal closure.
- A piece can be **mirrored** horizontally or vertically to generate the opposite half.
- **Cut quantity** annotation (e.g., "Cut 2" or "Cut 1 on fold") displayed inside the piece.

### 3.8 Seam Allowance

- Select a closed piece or individual edges → Apply Seam Allowance (shortcut A or toolbar button).
- User sets the allowance amount (default 1.5 cm).
- The offset outline is drawn as a dashed line in a contrasting colour.
- Fold lines receive no seam allowance (user marks an edge as a fold line in Properties).

### 3.9 Markings & Annotations

| Marking | How to Add |
|---------|-----------|
| Grain line | G tool; drawn as a double-arrow line |
| Notch | N tool; tick mark perpendicular to edge |
| Dart | Select a V-shape; mark as dart in Properties (shows stitching symbol) |
| Label | Double-click empty canvas area to add text |
| Scale square | Auto-generated 5 cm × 5 cm square placed on first PDF page for print verification |

### 3.10 File Format (Save / Load)

Patterns saved as JSON (`.psnap`):

```json
{
  "version": 1,
  "measurements": { "waist": 72, "hip": 96, ... },
  "pieces": [
    {
      "id": "front-skirt",
      "name": "Front Skirt",
      "cutQty": 1,
      "onFold": true,
      "elements": [
        { "type": "line", "from": [0, 0], "to": [0, 60], "formula": "length" },
        { "type": "curve", "from": [0, 0], "cp1": [4, -2], "cp2": [22, -3], "to": [24, 0], "formula": "waist / 2" },
        ...
      ],
      "seamAllowance": 1.5,
      "grainLines": [...],
      "notches": [...]
    }
  ]
}
```

Save: `Ctrl+S` downloads `.psnap`. Load: File → Open or drag `.psnap` onto canvas.

### 3.11 Export

| Format | Description |
|--------|-------------|
| SVG | Single SVG file with all pieces; viewBox in cm for scale-accurate output |
| Single-page PDF | All pieces on one page (may be very large); for plotters |
| Tiled PDF (A4) | Pattern split across A4 pages; 1.5 cm overlap; registration marks (crosshairs); grid coords (A1, A2, …); assembly diagram on first page; 5 cm test square |
| Tiled PDF (US Letter) | Same as above, US Letter page size |

### 3.12 Undo / Redo

Full undo/redo stack (`Ctrl+Z` / `Ctrl+Y`). Every element add, delete, move, and property change is undoable.

### 3.13 Keyboard Shortcuts Summary

| Action | Shortcut |
|--------|----------|
| Select tool | S |
| Line tool | L |
| Curve tool | C |
| Point tool | P |
| Seam Allowance tool | A |
| Grain Line tool | G |
| Notch tool | N |
| Eraser | E |
| Undo | Ctrl+Z |
| Redo | Ctrl+Y |
| Delete selected | Delete |
| Zoom in/out | Ctrl+= / Ctrl+- |
| Fit to screen | Ctrl+0 |
| Toggle grid | Ctrl+G |
| Toggle snap | Ctrl+Shift+S |
| Save | Ctrl+S |
| New piece | Ctrl+N |

### 3.14 Acceptance Criteria for Phase 1

1. User can draw a complete skirt pattern (front, back, waistband pieces) using line and curve tools.
2. Lines snap to endpoints, midpoints, and grid intersections reliably (within 8 screen pixels).
3. Parametric formulas update all linked dimensions when measurements change.
4. Seam allowance offset is geometrically correct on straight and curved edges.
5. Tiled PDF prints at correct scale — 5 cm test square measures exactly 5 cm when printed at 100%.
6. Pattern saves to `.psnap` and reloads correctly with all elements and formulas intact.
7. Undo/redo works for all editing operations.
8. App works on desktop Chrome, Firefox, and Safari.

---

## 4. Phase 2: AI Photo-to-Pattern

Phase 2 adds a photo upload flow that uses AI vision to generate an initial pattern. The result is loaded directly into the Phase 1 editor for refinement.

### 4.1 Flow

1. **Upload** — User uploads 1–2 garment photos (front view required, back optional).
2. **Analyze** — Backend sends images to Claude vision API; returns a `SkirtFeatures` JSON object: silhouette, waistband type, closure, dart count, details, confidence.
3. **Review** — User confirms or corrects detected features in a modal overlay.
4. **Measurements** — User enters body measurements (reuses Phase 1 measurement panel).
5. **Generate** — Backend parametric engine computes pattern pieces from features + measurements.
6. **Load into Editor** — Generated pattern is imported as a `.psnap` file into the Phase 1 editor; user can refine any piece.

### 4.2 AI Integration Details

- **Model:** Claude claude-sonnet-4-20250514 via Anthropic API.
- **Input:** JPEG or PNG, max 10 MB each. Multipart POST to `/api/analyze`.
- **Output:** `SkirtFeatures` Pydantic model (silhouette, length_category, waistband, closure, darts, details, confidence, notes).
- **Error handling:** If no skirt detected, return friendly error. Retry once on API failure. Flag confidence < 0.5 to user.

### 4.3 Parametric Pattern Generator (Phase 2 Backend)

The backend computes an initial pattern from features + measurements using the Aldrich method:

- Straight skirt base block → silhouette modifier (pencil, a-line, gathered, etc.) → feature modifiers (waistband, darts, closure, pockets).
- Output: list of pattern pieces → serialised as `.psnap` JSON → returned to frontend.
- Frontend loads `.psnap` into the editor as if the user had opened a saved file.

### 4.4 Phase 2 Acceptance Criteria

1. User uploads a skirt photo and receives correctly detected features (silhouette, waistband, closure) for straight, pencil, and A-line skirts.
2. Feature review UI shows detected values and allows correction before generation.
3. Generated pattern loads into the Phase 1 editor with all pieces, seam allowances, grain lines, and labels.
4. User can make edits to the generated pattern in the editor and re-export.
5. Backend pattern accuracy: key dimensions within ±2 mm of golden-file reference for 5 test skirts.

---

## 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SVG hit-testing is slow with many elements | Performance degrades on complex patterns | Spatial indexing (R-tree or quadtree) for hit tests; virtualize off-screen elements |
| Snap feels laggy or mis-fires | Poor UX, user loses trust in precision | Tune snap radius; add visual indicator before committing snap; allow snap toggle |
| Bezier curve UX is hard for non-designers | Users can't draw curves accurately | Provide tangent handle previews; add a "smooth corner" option; offer common curve presets for waists/hips |
| Parametric formula errors confuse users | Users give up on formulas | Friendly inline error messages; show computed value in real-time; revert to manual on parse error |
| Print scale accuracy | Printed patterns are wrong size | 5 cm test square on every export; document "print at 100%, no fit-to-page" clearly |

---

## 6. Success Metrics

### Phase 1
- User completes a full skirt pattern draft in under 20 minutes.
- Tiled PDF test square measures within 0.5 mm of 5 cm when printed at 100%.
- Snap success rate: >95% of intended snaps succeed without retry (user study).

### Phase 2
- Feature detection correct without user correction on >70% of test photos.
- Time from photo upload to editable pattern in editor: <30 seconds.

---

## 7. Appendix

### 7.1 Patternmaking Reference Texts

- Winifred Aldrich, *Metric Pattern Cutting for Women's Wear* (6th ed.)
- Helen Joseph-Armstrong, *Patternmaking for Fashion Design*

### 7.2 Comparable Tools for Reference

- **Seamly2D / Valentina** — open-source desktop pattern editor (parametric, Windows/Mac/Linux). Most direct reference for the Phase 1 editor concept.
- **Freesewing.org** — open-source parametric patterns in JavaScript. Reference for measurement-driven geometry.
- **Inkscape** with sewing plugins — what advanced users currently hack together.

### 7.3 Environment Variables

| Variable | Description | Required | Default |
|----------|------------|----------|---------|
| `ANTHROPIC_API_KEY` | API key for Claude vision (Phase 2 only) | Phase 2 | — |
| `CLAUDE_MODEL` | Model identifier | No | `claude-sonnet-4-20250514` |
| `CORS_ORIGINS` | Allowed frontend origins | No | `http://localhost:5173` |
| `MAX_IMAGE_SIZE_MB` | Maximum upload size (Phase 2) | No | `10` |
| `DEFAULT_SEAM_ALLOWANCE_CM` | Default seam allowance | No | `1.5` |

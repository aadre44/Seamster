# PatternSnap — Phase 1 MVP: Product Requirements Document

**For Claude Code Implementation**
**v1.0 — March 2026**

> **Scope:** Skirt-only parametric pattern generator with AI-assisted garment analysis
> **Target Timeline:** 12 weeks

---

## 1. Project Overview

PatternSnap is a web application that allows users to photograph a skirt and receive a downloadable, print-ready sewing pattern for that garment. Phase 1 constrains the problem to skirts only, uses a vision LLM for feature detection (no custom model training), and relies on parametric pattern generation driven by user-provided measurements.

### 1.1 Goals

- Deliver a working MVP that generates accurate, sewable skirt patterns from a photo + measurements.
- Validate the core product hypothesis: users want AI-assisted reverse pattern engineering.
- Build a pattern engine architecture that is extensible to other garment types in Phase 2+.
- Ship within 12 weeks with a single developer using Claude Code.

### 1.2 Non-Goals (Phase 1)

- No 3D garment reconstruction.
- No automatic measurement extraction from photos.
- No custom-trained ML models — use vision LLM APIs only.
- No garment types beyond skirts (trousers, tops, dresses are Phase 2+).
- No user accounts or payment — this is a free tool for validation.

---

## 2. Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend / API | Python 3.12 + FastAPI | Fast async API, great Claude Code support, strong SVG/PDF libraries |
| AI / Vision | Anthropic Claude API (claude-sonnet-4-20250514 vision) | Structured JSON output, strong garment understanding, no GPU needed |
| Pattern Engine | Python (svgwrite + reportlab) | svgwrite for vector pattern pieces, reportlab for tiled PDF export |
| Frontend | React 18 + TypeScript + Tailwind CSS | Component-based UI, fast iteration with Claude Code |
| State Management | React Context + useReducer | Sufficient for single-page wizard flow, no Redux needed |
| Build Tool | Vite | Fast dev server, simple config |
| Hosting | Any static host (Vercel/Netlify) + backend on Railway/Fly.io | Simple deployment, no GPU infra required |
| Testing | pytest (backend) + Vitest (frontend) | Standard, well-supported by Claude Code |

---

## 3. System Architecture

### 3.1 High-Level Data Flow

1. User uploads 1–2 photos of a skirt (front required, back optional).
2. Frontend sends images to the backend `/analyze` endpoint.
3. Backend forwards images to Claude vision API with a structured prompt.
4. Claude returns a JSON object describing detected garment features.
5. Frontend displays detected features for user confirmation/editing.
6. User enters body measurements.
7. Frontend sends confirmed features + measurements to `/generate` endpoint.
8. Backend pattern engine computes parametric pattern pieces.
9. Backend renders pieces as SVG, then converts to tiled PDF.
10. Frontend offers the pattern for download.

### 3.2 Backend API Endpoints

| Endpoint | Method | Input | Output |
|----------|--------|-------|--------|
| `/api/analyze` | POST | Multipart: 1–2 images (JPEG/PNG, max 10MB each) | JSON: detected features object |
| `/api/generate` | POST | JSON: confirmed features + measurements | Binary: PDF file (tiled pattern) or SVG |
| `/api/skirt-types` | GET | None | JSON: list of supported skirt types and feature options |
| `/api/health` | GET | None | JSON: service status |

### 3.3 Directory Structure

```
patternsnap/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, routes
│   │   ├── api/
│   │   │   ├── analyze.py       # /analyze endpoint
│   │   │   └── generate.py      # /generate endpoint
│   │   ├── vision/
│   │   │   ├── analyzer.py      # Claude API integration
│   │   │   └── prompts.py       # Vision prompt templates
│   │   ├── patterns/
│   │   │   ├── engine.py        # Core parametric engine
│   │   │   ├── skirts.py        # Skirt-specific pattern logic
│   │   │   ├── modifiers.py     # Feature modifiers (darts, pleats, etc.)
│   │   │   └── geometry.py      # Point, line, curve math utilities
│   │   ├── export/
│   │   │   ├── svg_renderer.py  # SVG pattern piece rendering
│   │   │   └── pdf_tiler.py     # Tiled PDF export with registration marks
│   │   └── models/
│   │       ├── features.py      # Pydantic models for garment features
│   │       └── measurements.py  # Pydantic models for body measurements
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── PhotoUpload.tsx      # Camera/upload step
│   │   │   ├── FeatureReview.tsx    # Confirm/edit detected features
│   │   │   ├── MeasurementForm.tsx  # Enter body measurements
│   │   │   ├── PatternPreview.tsx   # SVG preview of generated pattern
│   │   │   └── DownloadStep.tsx     # Download PDF/SVG
│   │   ├── context/
│   │   │   └── PatternContext.tsx   # App state management
│   │   └── types/
│   │       └── index.ts             # TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

---

## 4. AI Vision Analysis — Detailed Spec

### 4.1 Vision Prompt

The prompt sent to Claude's vision API should be a system message + user message with the image(s). The system message instructs Claude to analyze a skirt photograph and return structured JSON.

**SYSTEM PROMPT:**

```
You are a garment analysis expert. Analyze the provided skirt photograph(s) and return ONLY a JSON object with no additional text. Identify:

1. silhouette: one of ["straight", "a_line", "pencil", "circle", "gathered", "pleated", "wrap"]
2. length_category: one of ["mini", "above_knee", "knee", "midi", "maxi"]
3. waistband: { type: "straight" | "contoured" | "elastic" | "facing" | "yoke", width_cm_estimate: number }
4. closure: { type: "center_back_zip" | "side_zip" | "button_fly" | "hook_and_eye" | "none", position: "center_back" | "left_side" | "right_side" | "center_front" }
5. darts: { front: number (0-4), back: number (0-4) }
6. details: array of strings from ["kick_pleat", "back_vent", "side_slits", "patch_pockets", "welt_pockets", "belt_loops", "lining_visible", "topstitching"]
7. confidence: number 0-1 representing overall confidence
8. notes: string with any additional observations relevant to pattern making

If you cannot determine a feature, use your best judgment and note uncertainty in the notes field. Respond with valid JSON only.
```

**USER MESSAGE:**

```
Analyze this skirt and return the structured JSON as specified. [IMAGE(S) ATTACHED]
```

### 4.2 Expected Response Schema (Pydantic)

Define these models in `backend/app/models/features.py`. The API response from Claude must be parsed and validated against this schema.

```python
from pydantic import BaseModel, Field
from typing import Literal

class WaistbandFeature(BaseModel):
    type: Literal['straight', 'contoured', 'elastic', 'facing', 'yoke']
    width_cm_estimate: float = 3.0

class ClosureFeature(BaseModel):
    type: Literal['center_back_zip', 'side_zip', 'button_fly', 'hook_and_eye', 'none']
    position: Literal['center_back', 'left_side', 'right_side', 'center_front']

class DartFeature(BaseModel):
    front: int = Field(ge=0, le=4)
    back: int = Field(ge=0, le=4)

class SkirtFeatures(BaseModel):
    silhouette: Literal['straight', 'a_line', 'pencil', 'circle', 'gathered', 'pleated', 'wrap']
    length_category: Literal['mini', 'above_knee', 'knee', 'midi', 'maxi']
    waistband: WaistbandFeature
    closure: ClosureFeature
    darts: DartFeature
    details: list[str]
    confidence: float = Field(ge=0, le=1)
    notes: str = ''
```

### 4.3 Error Handling

- If the image does not contain a skirt, return a clear error message to the user: "We couldn't identify a skirt in this photo. Please upload a clear front-view photo of a skirt."
- If confidence is below 0.5, show a warning banner on the feature review screen.
- If the API call fails (rate limit, network error), retry once after 2 seconds, then show a user-friendly error.
- Log all API responses (redacting image data) for debugging and future training data collection.

---

## 5. Measurement Input — Detailed Spec

### 5.1 Required Measurements

| Measurement | Description | Unit | Typical Range | Validation |
|------------|-------------|------|---------------|------------|
| Waist | Natural waist circumference, measured at narrowest point | cm | 58–120 | Required, 40–160 |
| Hips | Fullest hip circumference | cm | 80–140 | Required, 50–180 |
| Waist-to-Hip | Vertical distance from waist to widest hip point | cm | 17–25 | Required, 10–35 |
| Skirt Length | Desired finished length from waist to hem | cm | 35–120 | Required, 20–150 |

### 5.2 Optional Measurements

| Measurement | Description | Default If Omitted |
|------------|-------------|-------------------|
| Waistband Width | Desired waistband height | 3 cm (or as detected by AI) |
| Seam Allowance | Desired seam allowance | 1.5 cm |
| Hem Allowance | Extra fabric at hem for finishing | 3 cm |

### 5.3 Measurement Guide

The frontend must display a clear measurement guide illustration (a simple SVG diagram showing where each measurement is taken on the body). This is critical for pattern accuracy. Include a toggle for cm/inches with automatic conversion.

---

## 6. Parametric Pattern Engine — Detailed Spec

This is the core of the application. The engine takes confirmed features and measurements as input and outputs a set of 2D pattern pieces with all markings.

### 6.1 Base Pattern: Straight Skirt Block

The straight skirt is the foundation pattern. All other silhouettes are derived from it by applying modifiers. Implement the drafting method from standard patternmaking (Aldrich method). Key construction steps:

1. Start with a rectangle: width = (hip/2 + ease), height = skirt_length.
2. Mark the hip line at waist_to_hip distance from the top.
3. Calculate front and back waist dart intake: total_dart_intake = (hip/2 + ease) - (waist/2 + ease).
4. Distribute dart intake: typically 60% to back darts, 40% to front darts.
5. Position darts: back dart at hip/4 from center back, front dart at hip/6 from center front.
6. Shape the waist curve: slight concave curve from side seam to dart, accounting for body contour.
7. Add seam allowances to all edges.
8. Add grain line (vertical, parallel to center front/back).

### 6.2 Silhouette Modifiers

Each silhouette type modifies the base block. Implement as functions that take the base points and return modified points.

| Silhouette | Modification | Key Parameter |
|-----------|-------------|---------------|
| straight | No modification to base block | N/A |
| pencil | Taper inward 1–2 cm at hem on each side seam | taper_amount: 1.5 cm default |
| a_line | Flare outward at hem; pivot from hip or waist | flare_amount: 3–10 cm per side |
| circle | Concentric circle construction; full circumference pattern | fullness: full, half, or quarter |
| gathered | Extend waist edge by gather ratio, keep hem same as base | gather_ratio: 1.5–3.0 |
| pleated | Add pleat extensions at marked positions | pleat_width: 2–5 cm, pleat_count: 2–6 |
| wrap | Overlap extension at center front, shaped hemline | overlap_cm: 15–20 |

### 6.3 Feature Modifiers

These modify the pattern based on detected or user-selected construction details.

- **Waistband:** Generate a separate rectangular piece. Length = waist + closure_overlap + seam_allowances. Height = waistband_width × 2 + seam_allowances (folds in half). Contoured waistband uses a curved piece instead.
- **Closure:** Affects which edge gets a seam allowance vs. fold line. Center-back zip: back piece is cut as two halves with seam allowance on center back. Side zip: side seam gets extra allowance for zip shield.
- **Darts:** Triangular cutouts at waist edge. Mark with notches at waist and circle at dart point. Back darts are typically longer (12–15 cm) than front darts (8–10 cm).
- **Kick pleat:** Extend the back center seam below the vent opening point. Add a pleat underlap piece.
- **Pockets:** For patch pockets, generate a separate pocket piece (rectangle with rounded bottom corners). For welt pockets, mark the welt position on the main piece.

### 6.4 Pattern Piece Output Specification

Each pattern piece must include these elements:

- **Outline:** closed polyline or path defining the cut edge (including seam allowances).
- **Seam line:** dashed line inside the outline showing the actual stitch line.
- **Grain line:** arrow indicating fabric grain direction (parallel to selvage).
- **Notches:** small triangular marks at key alignment points (dart positions, side seam at hip, etc.).
- **Labels:** piece name (e.g., "Front Skirt"), cut quantity (e.g., "Cut 1 on fold"), and the pattern name.
- **Dart markings:** lines from waist notches to dart point, with dart point marked as a small circle.
- **Fold line indicator:** if the piece should be cut on fold, a bracket marking along the fold edge.

---

## 7. Export — Detailed Spec

### 7.1 SVG Output

Each pattern piece should be rendered as an SVG group within a single SVG document. Use real-world units (cm) so the SVG can be printed at actual size. Set the viewBox in centimeters and include a 5 cm test square on the first page so users can verify print scale.

- Stroke width: 0.3mm for cut lines, 0.2mm for seam lines (dashed), 0.15mm for markings.
- Colors: black for cut lines, gray for seam lines, red for grain lines, blue for notches and labels.
- Font: 8pt sans-serif for labels.

### 7.2 Tiled PDF Output

Most users will print on A4 or US Letter paper. The tiled PDF must:

1. Split the full-size pattern across multiple pages with 1.5 cm overlap margins.
2. Add registration marks (crosshairs) in the overlap zone so users can align pages.
3. Number each page with grid coordinates (e.g., "A1", "A2", "B1").
4. Include an assembly diagram on the first page showing the page grid layout.
5. Include a 5 cm × 5 cm test square on page 1 for scale verification.
6. Default to A4 paper, with option for US Letter.

### 7.3 Single-Page PDF

Also offer a single large-format PDF for print shops. Calculate the bounding box of all pieces and set the page size to fit. Common plotter paper is 91 cm (36 in) wide.

---

## 8. Frontend UI — Detailed Spec

### 8.1 User Flow (Wizard Steps)

The frontend is a single-page wizard with 5 steps. The user progresses linearly but can go back to any previous step.

#### Step 1: Photo Upload

- Drag-and-drop zone + file picker + camera capture button (on mobile).
- Accept JPEG and PNG, max 10MB per image.
- Require 1 front-view photo. Optionally accept 1 back-view photo.
- Show image preview with crop/rotate controls.
- "Analyze" button triggers the `/api/analyze` call. Show a loading spinner with the text "Analyzing your skirt..."

#### Step 2: Feature Review

- Display the uploaded photo alongside the detected features as an editable form.
- Silhouette: visual selector with skirt silhouette icons (not just a dropdown).
- Waistband, closure, darts, details: dropdowns and toggles.
- If confidence < 0.5, show a yellow warning: "We're not fully confident in our analysis. Please review carefully."
- "Confirm Features" button proceeds to Step 3.

#### Step 3: Measurements

- Clean form with labeled input fields and a measurement guide SVG illustration.
- cm/inches toggle (convert on the fly, store internally in cm).
- Real-time validation: highlight out-of-range values in red with helper text.
- Pre-fill optional fields with sensible defaults.
- "Generate Pattern" button triggers `/api/generate`. Show loading with progress indication.

#### Step 4: Pattern Preview

- Render the returned SVG pattern inline in the browser.
- Pan and zoom controls (use a library like panzoom or react-zoom-pan-pinch).
- Show piece names and key measurements as overlays.
- "Download" button proceeds to Step 5.

#### Step 5: Download

- Paper size selector: A4 or US Letter.
- Download buttons for: Tiled PDF, Single-page PDF, SVG file.
- Brief printing instructions: "Print at 100% scale (do not fit to page). Verify using the 5 cm test square on page 1."

---

## 9. Testing Requirements

### 9.1 Backend Tests

- Unit tests for geometry utilities (point calculations, line intersections, curve generation).
- Unit tests for each silhouette modifier (verify output points match expected values for known inputs).
- Unit tests for each feature modifier (darts, waistband, closure effects on pattern).
- Integration test for the full generation pipeline: known measurements + features in → valid SVG out.
- Snapshot tests: compare generated SVG output against golden files for regression detection.
- Test PDF tiling: verify page count, overlap zones, and registration mark placement.

### 9.2 Frontend Tests

- Component tests for each wizard step (render, user interaction, state updates).
- Form validation tests: measurement ranges, required fields, unit conversion.
- API integration tests with mocked responses.

### 9.3 Accuracy Validation

Create a validation suite of 5 test skirts with known measurements and features. For each, manually draft the correct pattern and store as a golden SVG. The pattern engine output must match within 2mm tolerance on all key dimensions (waist, hip, length, dart positions).

---

## 10. Implementation Order for Claude Code

Execute these tasks in order. Each task should be a discrete, testable unit of work.

| Task # | Description | Est. Time | Dependencies |
|--------|------------|-----------|-------------|
| 1 | Scaffold project: directories, package.json, requirements.txt, basic FastAPI app with health endpoint, Vite + React setup | 2–3 hrs | None |
| 2 | Define Pydantic models (features.py, measurements.py) and TypeScript types (types/index.ts) | 1–2 hrs | Task 1 |
| 3 | Implement geometry utilities (geometry.py): point class, line/curve math, seam allowance offset algorithm | 3–4 hrs | Task 1 |
| 4 | Implement straight skirt base block (skirts.py): basic rectangle → darted waist construction | 4–6 hrs | Task 3 |
| 5 | Implement silhouette modifiers (modifiers.py): pencil, a_line, gathered, pleated, circle, wrap | 6–8 hrs | Task 4 |
| 6 | Implement feature modifiers: waistband generation, closure handling, dart placement, kick pleat, pockets | 4–6 hrs | Task 4 |
| 7 | Implement SVG renderer (svg_renderer.py): render pieces with all markings, labels, grain lines, notches | 4–5 hrs | Task 4 |
| 8 | Implement tiled PDF export (pdf_tiler.py): page splitting, overlap, registration marks, test square, assembly diagram | 6–8 hrs | Task 7 |
| 9 | Implement Claude vision integration (analyzer.py, prompts.py): API call, response parsing, error handling | 3–4 hrs | Task 2 |
| 10 | Wire up /api/analyze and /api/generate endpoints (analyze.py, generate.py) | 2–3 hrs | Tasks 8, 9 |
| 11 | Build frontend: PhotoUpload component with drag-drop and camera capture | 3–4 hrs | Task 1 |
| 12 | Build frontend: FeatureReview component with visual selectors and edit controls | 4–5 hrs | Task 11 |
| 13 | Build frontend: MeasurementForm with validation, cm/inches toggle, guide illustration | 3–4 hrs | Task 12 |
| 14 | Build frontend: PatternPreview with inline SVG rendering, pan/zoom | 3–4 hrs | Task 13 |
| 15 | Build frontend: DownloadStep with paper size selection and download buttons | 2–3 hrs | Task 14 |
| 16 | Build PatternContext state management, wire all steps together into wizard flow | 3–4 hrs | Tasks 11–15 |
| 17 | Backend unit tests: geometry, base block, modifiers, export | 4–6 hrs | Tasks 3–8 |
| 18 | Frontend component tests + API integration tests | 3–4 hrs | Tasks 11–16 |
| 19 | Accuracy validation: create 5 golden-file test skirts, verify within 2mm tolerance | 4–6 hrs | Task 10 |
| 20 | Polish: error handling, loading states, responsive design, printing instructions | 4–6 hrs | All tasks |

---

## 11. Acceptance Criteria

Phase 1 is complete when all of the following are true:

1. A user can upload a photo of a straight, pencil, or A-line skirt and receive accurate feature detection.
2. The user can confirm or correct all detected features via the UI.
3. The user can enter waist, hip, waist-to-hip, and length measurements.
4. The app generates a multi-piece sewing pattern (front, back, waistband) as downloadable PDF and SVG.
5. The tiled PDF prints at correct scale (verified by 5 cm test square).
6. All pattern pieces include correct seam allowances, grain lines, notches, and labels.
7. Dart positions and sizes are mathematically correct for the given measurements.
8. The golden-file test suite passes within 2mm tolerance for all 5 test skirts.
9. Backend has >80% test coverage on the pattern engine.
10. The app works on desktop Chrome/Firefox/Safari and mobile Safari/Chrome.

---

## 12. Environment & Configuration

| Variable | Description | Required |
|----------|------------|----------|
| `ANTHROPIC_API_KEY` | API key for Claude vision calls | Yes |
| `CLAUDE_MODEL` | Model identifier (default: `claude-sonnet-4-20250514`) | No |
| `CORS_ORIGINS` | Allowed frontend origins (default: `http://localhost:5173`) | No |
| `LOG_LEVEL` | Logging level (default: `INFO`) | No |
| `MAX_IMAGE_SIZE_MB` | Maximum upload size (default: `10`) | No |
| `DEFAULT_SEAM_ALLOWANCE_CM` | Default seam allowance (default: `1.5`) | No |

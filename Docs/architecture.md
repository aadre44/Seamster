# Seamster — Architecture

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
│       ├── api.ts                    Single API client — typed wrappers; base URL VITE_API_URL ?? '/api' (Vite dev proxy)
│       ├── utils/
│       │   ├── formulaEval.ts        Sandboxed expression parser for parametric dims
│       │   └── pieceTransforms.ts    Flip H/V, rotate, mirror-copy geometry
│       └── types/
│           └── index.ts              Element, Piece, Measurement TypeScript interfaces
│
├── backend/
│   └── app/
│       ├── main.py                   FastAPI app, CORS config, /api/health (reports LLM provider)
│       ├── api/export.py             POST /api/export/pdf — returns tiled PDF binary
│       ├── api/analyze.py            Phase 2: POST /api/analyze (LLM vision)
│       ├── api/generate.py           Phase 2: POST /api/generate (parametric engine)
│       ├── llm/                      Provider-agnostic LLM layer (Anthropic + Ollama)
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
| `undoStack` / `redoStack` | `EditorSnapshot[]` | 50-level history; each entry versions `{elements, pieces, connections}` together |
| `liveBase` | `EditorSnapshot \| null` | Pre-gesture snapshot captured on the first `LIVE_UPDATE_ELEMENTS` of a drag |
| `undoTag` | `string \| null` | Coalescing tag — consecutive `UPDATE_PIECE` edits on the same piece share one undo entry |

Actions are dispatched via `useReducer`. Undo semantics:

- Every discrete mutating action (`ADD_ELEMENT`, `ADD_PIECE`, `DELETE_PIECE`, `BATCH_UPDATE_ELEMENTS`, …) pushes a snapshot of `{elements, pieces, connections}` **before** applying the change — pieces and connections are versioned with elements so an undo can never leave a piece referencing deleted element ids.
- Continuous drags (move, rotate, node/endpoint reshape) dispatch `LIVE_UPDATE_ELEMENTS` per mousemove; the first frame stores the pre-drag snapshot in `liveBase`, and `PUSH_UNDO` on mouseup commits it as **one** undo entry. A click with no movement pushes nothing.
- `DELETE_PIECE` removes the piece, its outline elements, its interior markings (grain line, darts, pleat folds) and any connections that reference it — one undoable step.
- Piece property edits (`UPDATE_PIECE`) coalesce per piece via `undoTag`: spinner clicks on cut-quantity form a single undo step; changing selection starts a new one.

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
| `/api/analyze` | POST | Phase 2: LLM vision — analyzes a garment photo |
| `/api/generate` | POST | Phase 2: Generates parametric pattern from measurements |
| `/api/health` | GET | Reports `{status, llm_provider, llm_model}` for the active config |

---

## Pattern Detail Handling — pockets & pleats

The parametric engine (`backend/app/patterns/`) shapes two commonly-mis-rendered
details from the vision analysis:

- **Patch pocket bottom shape** — `pockets.py::make_patch_pocket()` is the single
  builder used by every garment block. A `shape` argument
  (`square`/`rounded`/`angled`/`pointed`/`curved`) selects the bottom edge, built
  from `Point`/`CurveSegment` primitives. The vision layer reports the shape with a
  `pocket_*` detail token (`prompts.py`) plus a notes-based fallback
  (`analyzer.py::_infer_pockets_from_notes`). `engine.py::_pocket_shape()` maps the
  token to the builder argument.

- **Pleats** — `pleats.py` models the two pattern-making essentials:
  `pleat_unit_allowance()` encodes the fabric each fold consumes (`2×depth` knife /
  accordion / pintuck; `4×depth` box / inverted box); `apply_pleats()` widens the
  panel by that allowance (optionally tapering above `max_y` for released waist
  pleats) and attaches `PleatSpec` markings. `PieceSpec` (in `skirts.py`) carries a
  `pleats: list[PleatSpec]` field, and `engine.py::_serialise_piece()` renders each
  as interior fold (dashed `isFold`) + placement lines with a direction tick — not
  part of the cutting outline, so `_compute_connections()` ignores them. The
  analysis returns a structured `PleatDetail` (`type`/`count`/`placement`/
  `depth_cm`); `engine.py::_resolve_pleats()` normalises it (also honouring the
  legacy `pleated` silhouette and bare `pleats` token) and each `_generate_*`
  applies it to the relevant panels (skirt/dress full-length, trouser front-waist,
  shirt/jacket centre-back).

- **Construction topology (strap / back / front opening)** — the `Construction`
  sub-model (`models/features.py`) captures three orthogonal axes the neckline alone
  can't express, so halter/backless/plunge garments build correctly:
  - `strap_style` — `shoulder_seam` (default) | `halter_neck` | `halter_tie` |
    `spaghetti_straps` | `wide_straps` | `one_shoulder` | `strapless` | `racerback`.
  - `back_coverage` — `full` (default) | `low_back` | `racer` | `backless`.
  - `front_opening` — `closed` (default) | `plunge` | `deep_v_split` | `keyhole` |
    `surplice` | `placket` | `wrap`.
  The vision layer reports the object directly (`prompts.py`, `_CONSTRUCTION_NOTE`)
  with a notes-based fallback (`analyzer.py::_infer_construction_from_notes`).
  `engine.py::_resolve_construction()` defaults it (and maps `neckline=halter/strapless`
  when the object is absent) and passes the three axes into `build_shirt_block` /
  `build_dress_block`.
  - **Shoulderless = sleeveless.** Any `strap_style` ≠ `shoulder_seam` forces
    `sleeve_length=sleeveless` and builds no shoulder seam (guards against a strappy top
    regressing into a sleeved blouse when the analysis is noisy).
  - **Front** (halter): the neckline rises into an integral strap. `closed`/`plunge` keep
    ONE continuous Front **cut on the CF fold** (the deep V is a notch, not a seam);
    `deep_v_split` is still ONE continuous piece but cut on the fold along the **top
    (back-neck) edge** — the strap mirrors over the neck so the two panels are joined only
    by the strap, with the centre front fully open below it (the fold is the top seam, not a
    vertical centre band). A shoulder-seam `deep_v_split` is two off-fold halves;
    a shoulder-seam `plunge` stays one piece on the fold.
  - **Front** (non-halter shoulderless: spaghetti/wide/one_shoulder/strapless): a
    strapless-style band/V front on the fold **plus separate strap pieces** (`_rect_piece`;
    none for strapless).
  - **Back**: `backless` omits the Back Bodice (adding a **Waist Tie**); any other coverage
    on a shoulderless top builds a **band back** (flat top edge, bare shoulders) whose top
    sits at the **underarm for a halter** (low/bare back) but **higher for a tank**
    (spaghetti/wide/one_shoulder/racerback — covers the shoulder blades) so the back side
    seam matches the front. Non-shoulderless `low_back`/`racer` keep a conventional
    shouldered back, scooped/narrowed.
  - **Halter vs tank (anchor point)**: a halter is supported at the NECK (straps meet behind
    the neck, bare shoulders); a tank/cami is supported at the SHOULDERS (straps over the
    shoulders). `analyzer.py::_refine_strap_style` keeps `halter_neck`/`halter_tie` **only when
    the notes give positive neck-support evidence** ("behind the neck", "bare shoulders", …);
    with tank/over-shoulder language or NO neck evidence it downgrades to `spaghetti_straps`
    ("when unsure → tank"). Skipped only when the neckline is explicitly `halter`.
    `_clamp_spaghetti_back` then forbids a `full` back on a `spaghetti_straps` top (clamped to
    `low_back`) — thin straps support at most a half back, or a backless one.
  - **Strap width** (`construction.strap_width`: `thin`/`medium`/`wide` → ≈2/4/7 cm via
    `shirts.py::_strap_cm`) sizes the integral halter strap and the separate spaghetti/wide
    strap pieces so each matches its photo (None ⇒ per-style default). The halter strap's
    outer edge is a single smooth curve (gradual bust→strap flare) at any width. Vision
    estimates the category; `analyzer.py::_refine_strap_width` backfills it from the notes.
  - `elastic_hem`/`drawstring_hem` build a native **Hem Casing Band**; all shoulderless/
    open fronts add a **Front Facing**.
  The strap/tie/hem and neckline-descriptor (`v_neck`, `round_neck`) tokens are registered
  in `_PARAMETRIC_DETAILS`/`_TECHNIQUES` so the LLM fallback never emits duplicate strap or
  "neckline" pieces. Back-coverage inference is conservative: an unseen or merely
  *assumed*-open halter back defaults to `low_back`; `backless` needs a clearly open back or
  a `deep_v_split` front. A second safety net (`_refine_front_split`) upgrades a `plunge` to
  `deep_v_split` when the notes describe the front panels as open/separate (the model often
  mislabels a split centre front as a continuous plunge). See
  [pattern-piece-construction-notes.md](pattern-piece-construction-notes.md) for the full
  per-garment nuance reference.

- **Edge finishes (bindings & shaped facings)** — `finishings.py` adds the two edge
  treatments the engine previously could not express (every old "facing" was a flat
  rectangle and there was no binding at all):
  - `make_edge_binding()` builds a continuous bias strip sized to a known edge *run-length*
    (so it actually fits the neckline/armhole/hem), flagged for cut-from-contrast when the
    trim is a contrasting colour — this is the signature dark lip around a vest neckline.
  - `make_edge_facing()` (+ `make_armhole_facing` / `make_hem_facing`) samples an outline
    subpath (expanding any `CurveSegment`) and offsets each point toward an interior
    reference, so the facing *follows a curved armhole* instead of flattening to a rectangle.
  Both return a `PieceSpec` and are garment-agnostic. `path_length()` expands Bézier edges
  for accurate run-lengths.

- **Welt / besom pockets** — `pockets.py::make_welt_pocket()` is the single placeable welt
  builder (welt strip + pocket bag) with parametric opening width, welt height, bag depth and
  a placement note; `besom=True` gives the taller double-lip strip. Jackets now call it too
  (one implementation instead of the old hard-coded rectangles).

- **Vest garment (`GarmentType.VEST`)** — `vests.py::build_vest_block()` is a dedicated
  sleeveless upper-body block: Front + Back bodice, **never a sleeve**. It reuses the shirt
  boxy bodice maths (`shirts.py::_FIT_PARAMS`, the armscye `CurveSegment`, quarter
  measurements) and adds:
  - a **notched / split-V neckline** drafted as real outline geometry — a short near-vertical
    CF slit (`split_width` × `split_height`) that flares into a V, with an optional notch step
    (`notched_v`) vs a clean V (`split_v`);
  - optional contrast **bindings** (neckline/armhole/hem), **armhole/hem/neckline facings**,
    and lower-front **welt pockets**, all driven from the structured `binding` / `facings` /
    `welt_pockets` feature fields (with loose detail-token fallbacks).
  `engine.py::_generate_vest_pattern` parses the silhouette → fit style, merges the structured
  finishes with detail tokens (`_resolve_vest_finishes`), and serialises like every other
  garment. The vest's native detail tokens are registered in `_PARAMETRIC_DETAILS["vest"]`
  (`_VEST_DETAILS`) so the LLM fallback never duplicates a binding/facing/welt piece. Vision
  reports the new fields via `prompts.py` (`_EDGE_FINISH_NOTE`, gated by `has_edge_finishes`)
  with notes-based backfill (`analyzer.py::_infer_vest_finishes_from_notes`).

- **Garment shape system (silhouette/contour)** — `shaping.py` finally wires the post-build shape
  pipeline that `modifiers.py` only sketched (`apply_silhouette` was imported and never called). It
  mutates a panel's CONTOUR in place — mirroring `pleats.py::apply_pleats` — targeting edges by their
  `seamLabel` (`hem` / `side_seam` / `center_front`), so it is garment-agnostic. Vision returns one
  structured `ShapeFeature` (hem style + depth + waist taper + hem sweep); three interchangeable
  `shape_mode` strategies consume it so they can be compared apples-to-apples:
  - **`modifiers`** (default): composable named transforms — `reshape_hem` (`pointed` drops a CF apex,
    `curved_scoop`/`cutaway` swap the hem for a `CurveSegment`, `high_low` offsets CF-vs-side,
    `angled` slants it) + `apply_taper` (ramps side-seam x from −waist_taper at the waist to
    +hem_sweep at the hem) + `reshape_side_vent` (splits the lower side seam — upper stays sewn
    `side_seam`, lower becomes an unlabelled/open vent edge) + `apply_front_cut` (front only:
    sends it off-fold cut 2 and sweeps the lower CF away into a `cutaway`/`open_drape` opening;
    a wrap/surplice overlap stays `closed`).
  - **`warp`**: `warp_to_silhouette` remaps the side+hem subpath onto a normalized `SilhouettePath`
    hull scaled to the panel bbox, anchoring neckline/armhole/shoulder/CF-fold and clamping x ≥ 0 so
    the outline stays simple; a hull is synthesized from `ShapeFeature` when none is supplied.
  - **`fit_params`**: a coarse per-silhouette contour baked into the builder at draft time
    (`vests.py::_VEST_SHAPE_PARAMS`); `apply_shape` is a no-op post-build.
  `apply_shape` only touches the body panels (those carrying both `armhole` and `hem`); trim
  (bindings/facings/welts) is skipped. `engine.py::generate_pattern(features, measurements, shape_mode)`
  threads the mode from the `/api/generate` body into `_generate_vest_pattern` and the new
  `_generate_bodice_pattern` (which makes `GarmentType.BODICE` real instead of a placeholder by reusing
  the vest block). Vision exposes the `shape` object via `prompts.py` (`_SHAPE_NOTE`, gated by
  `has_shape`) with notes backfill (`analyzer.py::_infer_shape_from_notes`). The frontend AI-Assist
  modal carries a **Shape-mode toggle** (`Modifiers · Warp · Fit-params`) sent as `shape_mode`.

- **Asymmetric wrap fronts (topology, not an edge tweak)** — every other front is mirror-symmetric
  about a vertical CF, so a diagonal wrap (two *different* fronts) is structurally impossible for the
  edge modifiers. `AsymmetryFeature` (`front_style=asymmetric_wrap`, `wrap_side`, `overlap_cm`,
  `closure_drop_frac`) drives `vests.py::_asymmetric_fronts`, which drafts the front in a full-front
  frame (x: 0 = left side seam … FW = right side seam) and returns two non-mirrored panels: an
  **Overlap Front** (large wrap panel whose diagonal free edge is the visible closure) and an
  **Underlap Front** (the panel beneath). The closure edges are labelled `overlap_edge` /
  `underlap_edge` (distinct, single-piece) so `_compute_connections` never sews them as a seam;
  `wrap_side=left` reflects the construction about FW. `engine.py::_resolve_asymmetry` maps the field
  (with `asymmetric_wrap`/`wrap_front` detail fallbacks); `_resolve_collar` adds a **Mandarin / band
  stand collar** (`neckline=mandarin` or a `mandarin_collar` detail). Vision reports both via
  `prompts.py` (asymmetry object + note; `mandarin` neckline) with notes backfill
  (`analyzer.py::_infer_asymmetry_from_notes`). The `warp` mode additionally accepts a
  `silhouette_path.panels` map (a normalized hull per piece name) so each asymmetric panel can be
  warped to its own outline — the foundation for fully vision-driven, per-panel outlines.

---

## Novel-Piece Fallback (learned templates)

When the vision analysis emits a detail token no parametric builder handles
(`llm_fallback.detect_unsupported_details`, checked against the per-garment
`_PARAMETRIC_DETAILS` registry), the engine asks the LLM to describe the missing
piece as **size-parametric formulas**, not absolute coordinates
(`llm_fallback.generate_novel_pieces`). The result is saved as a `PieceTemplate`
in a JSON store (`learned_pieces.py`, `templates/learned.json`) and re-evaluated
locally for every future request — the parametric engine grows over time without
repeat LLM calls. A template is only persisted after it successfully applies, so
a bad formula can never poison the store.

`apply_template` assembles the evaluated formulas into a `PieceSpec` using one of
seven geometry primitives (`VALID_GEOMETRIES`; unknown values fall back to
rectangle):

| Geometry | Use | Dimension semantics |
|----------|-----|---------------------|
| `rectangle` | straps, ties, bands, casings | length × width, `grain_direction` picks the axis |
| `shaped_rectangle` | flaps, tabs, shaped belt ends | height × width; `end_shape` = pointed/rounded/angled/curved (reuses `make_patch_pocket`) |
| `trapezoid` | gores, panels wider at one end | height; bottom edge = width, top edge = `top_width_formula` (default width/2) |
| `godet` | flare inserts | side/slit length; hem width (clamped < 1.8×length); circular hem arc |
| `quarter_circle` | 90° annular flounce/ruffle | inner arc = attachment edge length **exactly**; width = flounce depth |
| `half_circle` | 180° flounce, cascade | as quarter_circle |
| `curved_band` | contoured collars/waistbands | band run × height; `curve_depth_formula` = arc rise (default 12% of run) |
| `custom` | any flat piece no primitive fits | `points`: 3–24 ordered vertices with formula coordinates (optional bezier `cp1x/cp1y/cp2x/cp2y` per vertex); closes implicitly; `attachment_edges` declares which edges carry `attachment_label` |

Arcs are emitted as ≤90° cubic beziers (`_arc_segments`) so they serialise
through the existing `CurveSegment` path; every non-rectangle piece is
normalised into the +x/+y quadrant before serialisation. The LLM prompt
documents when to choose each geometry (gathered ruffle = rectangle at 1.5–2.5×,
circular flounce = quarter/half circle at exactly 1×).

**Validation + repair (tier 3).** LLM output is never trusted blind
(`novel_validation.py` + `llm_fallback._generate_with_repair`):

- Every returned piece is checked for degenerate (<0.5 cm) or implausible
  (>250 cm) dimensions, near-zero area, and a self-intersecting outline
  (beziers sampled to a polyline).
- The engine passes real **edge run-lengths** into the prompt
  (`engine._edge_run_lengths`: per attachment label, the longest per-piece
  outline run — hem/waist/neckline/armhole/wrist/side_seam), and a circular
  flounce whose inner arc misses its declared attachment edge by >15% is
  rejected with the exact numbers.
- Rejections are re-prompted with the validation errors (2 repair rounds).
  On the final attempt an arc mismatch is salvaged by wrapping the formula in
  a scale factor (`(expr) * k` — still parametric); pieces that still fail are
  dropped, and if nothing survives a clearly-marked **placeholder rectangle**
  is emitted (never zero pieces while the provider is answering; provider
  failures still return nothing so offline generation is unchanged).
- A piece may declare `attachment_label`; `apply_template` puts that seamLabel
  on the geometry's intrinsic attachment edge(s) (top edge for the rectangular
  family, inner arc for flounces, both sides for a godet), and
  `_append_novel_pieces` **recomputes connections after appending** — so a hem
  flounce is genuinely sewn to the hem in the AssemblyView.

**Garment composition (tier 4).** Garment types with no dedicated block no
longer return an empty placeholder (`compositions.py`, called from
`generate_pattern` when `_generate_base` has no native generator):

1. **Static plans** route near-miss types onto existing builders with feature
   rewrites — `shorts` → trousers (length defaulted to shorts), `coat` → jacket
   (midi/maxi translated to knee), `tunic` → longline shirt, and
   `romper`/`jumpsuit` → shirt top + trouser bottom. No LLM call.
2. **The LLM planner** handles types without a static plan: it returns a
   constrained-JSON plan (1–3 components, builder names, whitelisted feature
   overrides, `join`), which is validated and re-prompted once with the
   errors before giving up.
3. The measurements-only **placeholder** is returned only when both fail.

Execution reuses the trusted per-garment generators for each component, offsets
the component layouts side by side, and relabels the joined edges (previous
component's `hem` + next component's `waist` → `waist_seam`, the dress
bodice/skirt convention) before recomputing connections — so a jumpsuit's top
is genuinely sewn to its trousers in the AssemblyView. `GarmentType` gained
`TUNIC`/`ROMPER`/`JUMPSUIT`, the vision vocab describes them with their
component builders' vocabulary, and `_PARAMETRIC_DETAILS` gives composed types
the union of their components' detail sets so the novel-piece fallback never
duplicates component pieces.

Malformed custom point lists (<3 points, missing coordinates, unsafe formulas)
raise clear ValueErrors that feed straight into the tier-3 repair re-prompt,
and the built outline passes through the same self-intersection/bounds checks
as every other geometry.

**Vision contours + feedback loop (tier 5).** For pieces the vocabulary cannot
name at all, the photo itself is the source:

- The vision prompt exposes a `piece_contours` escape hatch — a normalized
  outline polygon plus a scale hint (`width_frac` of a reference measurement)
  per unnameable piece. `POST /api/analyze` accepts `debug_force_contours`
  (surfaced as a dev-only checkbox in the AI modal) which makes the model trace
  EVERY visible piece, so the contour path can be exercised on any photo.
- `vision_contours.py` patternizes each contour: re-normalize (aspect
  preserved), Ramer-Douglas-Peucker simplification, symmetrize near-mirror
  shapes, snap near-axis edges straight, scale to cm, clamp, and validate with
  the tier-3 checks. **All tuning knobs are module constants at the top of the
  file** (`RDP_EPSILON_FRAC`, `SNAP_ANGLE_DEG`, `SYMMETRY_TOLERANCE`,
  `MIN_CONTOUR_CONFIDENCE`, width-frac/size clamps).
- Vision pieces are appended before the LLM fallback and their detail tokens
  are excluded from it, so one physical feature never yields two pieces.
- Every generated piece now carries `source` (`engine` / `template` / `llm` /
  `vision`); the canvas renders non-engine pieces amber with an "(AI draft)"
  label, and the Properties panel offers **Save as template** on drafts —
  `POST /api/templates` converts the user-corrected outline into a parametric
  custom template (coordinates stored as `reference * ratio` formulas) that
  REPLACES the AI's original guess for future generations.
- `TemplateStore.find` now matches normalized synonyms (plural stemming, token
  order, a small synonym map: `utility_pockets` hits a `cargo_pocket` template).

---

## LLM Provider Layer

The `backend/app/llm/` package decouples all AI calls from any single vendor. A
`LLMProvider` ABC (`base.py`) exposes `acomplete()` / `complete()` returning a
normalized `LLMResponse(text, truncated)`. Two implementations exist:
`anthropic_provider.py` (cloud Claude, text + vision) and `ollama_provider.py`
(local open-source models via httpx `/api/chat`). `factory.get_provider()` selects
one from the `LLM_PROVIDER` env var (default `anthropic`) and caches it; the
factory also centralizes the `[3, 8, 15]s` retry schedule and the shared JSON
parser. The three call sites — `vision/analyzer.py`, `patterns/instruction_generator.py`,
and `patterns/llm_fallback.py` — build prompts and validate output but delegate
the request to this layer. A single global provider serves all three, so running
on Ollama requires a vision-capable model (e.g. `qwen2.5vl:7b`) for `/analyze`.

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | Active | 2D canvas editor — draw, annotate, export |
| 2 | Planned | AI photo-to-pattern — LLM vision (Anthropic or Ollama) + parametric engine |

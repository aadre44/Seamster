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

## Piece library

The **▦ Lib** button in the left toolbar (Pattern tab) opens a drawer of ready-made pieces to drag onto the canvas:

- **Pockets** — chest (11 × 13), patch (rounded / angled / U-shaped), jeans back pocket (pointed), cargo, in-seam pocket bag.
- **Collars** — stand, shirt (point), mandarin, Peter Pan (cut on the fold); sized to your pattern's neckline when it has one.
- **Cuffs & bands** — shirt cuff and sleeve band (sized to the wrist), waistband (sized to the waist).
- **Plackets & flaps** — button placket, pocket flap, welt, belt loop, tie / sash.
- **Buttons** — 11 / 15 / 20 mm buttons and horizontal / vertical buttonholes. These are markings: dropped on a piece they belong to it, and they show on the 3D body.

Library pieces use the same names and edge labels as generated trims, so **Re-infer** in Assembly attaches them (collars to the neckline, cuffs to the wrist, pockets placed on their piece) and they appear on the 3D body. Presets live in `frontend/src/library/presets.ts`.

## Assembly View

The header tabs **Pattern | Assembly | 3D Body** switch the main view; the Pattern tab always takes you back to the editor. **Assembly** shows how the pieces connect (it is disabled until the canvas has pattern pieces).

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

Connections are computed automatically by the backend when generating a pattern and saved in the `.psnap` file, together with placements (pieces such as pockets applied onto another piece). Trims are included: collars go round the neckline, cuffs round the wrist, the fly facing and shield onto the left/right front, pocket bags into the side seam, and patch/welt pockets are placed on their host. **Re-infer** (Seams panel, needs the backend) works this out again for the current pieces — including hand-drawn ones — and keeps the seams you made yourself.

**Editing seams:** click an edge, then the edge on another piece it is sewn to, to add a seam. Click a seam's arc (or its row in the **Seams** panel) to edit it: drag the round handles to sew only part of an edge, pick the side of the body for cut-2 pieces, set the sewing direction, rename or delete it. Each seam shows whether its two sides match, are eased, or don't fit. Undo/redo work here too. The 3D drape sews exactly these seams, partial ones included. **Pieces** keeps the pieces in a fixed grid while you edit; **Laid flat** lays them open along their seams.

**Fly:** **Fly…** in the Seams panel attaches the fly facing and fly shield to the centre front automatically (facing on the wearer's left or right), the way a fly is constructed; the fly's J topstitching then shows on the 3D body. A fly piece dragged onto the front by hand offers the same fix.

**Placing pockets:** drag a piece (e.g. a patch pocket) onto the piece it goes on. Placed, it can be dragged to move, turned with its round handle, set to one side of the body or both, inside or outside, and its edges clicked to switch between stitched and open (the mouth is left open by default). Placements are saved in the `.psnap`. Details: [Docs/assembly.md](Docs/assembly.md).

---

## 3D Body View

The **🧍 3D Body** tab replaces the canvas with a 3D mannequin built from body measurements. It's available at any time, with or without a pattern. Click the **Pattern** tab to return to the editor.

- **Orbit** — drag to rotate, scroll to zoom, right-drag to pan.
- **Body panel** (top of the right sidebar while the view is open) — sliders for height, bust, underbust, waist, waist-to-hip, hip, neck, shoulder width, arm length, upper arm, wrist, inseam, thigh, knee, calf and ankle. The mannequin reshapes live as you drag.
- **Body** — Male (the default) or Female. A male body has a flat chest (the **Chest** measurement, no underbust/cup), broader shoulders, a straighter waist and hips, a lower waist line and a broader jaw, and starts from a man's default measurements (178 cm, chest 100, waist 86, shoulder 46).
- **Shape** — Hourglass / Rectangle / Pear / Apple changes the cross-section depths and the bust, belly and seat projection, not just the circumferences. For a male body the presets read Athletic / Rectangle / Triangle / Oval.
- **Where values come from** — a slider you move becomes a `custom` value. Fields you haven't set use the Measurements panel (tagged `measured`: bust, waist, hip, waist-to-hip, inseam, shoulder), otherwise a default. **Reset to measurements** clears your custom values.
- Your body stays as you set it when you open a file or generate a new pattern. It is not part of undo/redo, and is not yet saved in `.psnap`.

The mannequin is generated procedurally from anatomically profiled cross-sections (tape-fitted to your measurements, bust cup solved from bust vs underbust) joined into one smooth surface, meshed in a Web Worker, with studio lighting. A sculpted base body (Fusion 360) deformed to your measurements is the planned realism upgrade. three.js is loaded only when the view is first opened. **Garment on the body:** with a pattern loaded, the panel at the top right of the 3D view shows **Show garment**. It wraps the pattern onto the body: the centre edges sit on the centre line, side and shoulder seams meet, darts close, and on-fold and cut-2 pieces are mirrored. **Fit map** colours bands where the garment is *snug* (amber, no ease) or *tight* (red, fabric smaller than the body). The garment shows in one fabric colour with sewn seams drawn as lines (**Color by piece** tints each piece). Trims come along: collars, cuffs and waistbands continue from the edge they are sewn to; facings, the fly and pocket bags lie inside (drawn darker; **X-ray** makes the outer fabric see-through to show them); pockets sit on the piece they are placed on. Only pieces attached to nothing (e.g. belt loops) are listed as not shown. **Drape with gravity** (on by default) then settles the wrapped garment with a cloth simulation. Seams and darts are sewn, the fabric keeps its flat pattern lengths, and it collides with the body with friction. You watch it settle for a few seconds; changing the body or the pattern re-drapes. See **[Docs/3d-body.md](Docs/3d-body.md)**.

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

The **AI Assist** button in the header opens a three-step workflow:

1. **Upload photo** — select a garment type, then upload a JPEG/PNG front-view photo (back photo optional). The app calls `/api/analyze` which uses the configured LLM's vision API (Claude or a vision-capable Ollama model) to detect silhouette, waistband, closure, dart count, and details.
2. **Review & generate** — confirm or correct the detected features and enter your measurements, then click "Generate Pattern". The app calls `/api/generate` which runs the Aldrich parametric engine and returns a `.psnap` file that loads directly into the editor.
3. **Refine shapes from photo (optional, any time)** — after a photo-based generate the modal closes so the result can be inspected, and a persistent **Refine from Photo** button appears in the header (next to AI Assist). It opens a compact modal that sends the photo plus the **current canvas pieces** to `/api/refine`; the vision LLM returns corrected outlines (bezier curves allowed) only for pieces whose flat shape disagrees with the photo — e.g. a curved wrap edge the parametric block drew straight. Replacements are strictly validated (piece names, seam labels, size deltas, fold edges, self-intersection, and **structural seam lengths** — shoulder/armhole/side-seam/waist edges must stay within 12% of the draft so refined pieces still sew together); anything invalid is dropped, so the worst case is an unchanged pattern. Responses cut off at the token limit are salvaged piece-by-piece instead of failing silently. Reshaped pieces render amber as AI drafts. The button stays available (and repeatable) until the next AI generate replaces the photo context.

A **Dev — load saved analysis** mode lets you paste or load a saved analysis JSON response to skip the LLM call (useful for testing).

Supported garment types and fit styles:

| Type | Fit styles |
|------|-----------|
| **Skirt** | straight, pencil, a-line, flared, circle, gathered, pleated, wrap, trumpet, mermaid, tulip, tiered |
| **Shirt / Blouse** | slim, fitted, regular, relaxed, boxy, oversized, athletic, longline |
| **Trousers / Pants** | skinny, slim, cigarette, fitted, regular, relaxed, wide_leg, flared, bootcut, palazzo, jogger |
| **Dress** | shift, sheath, a-line, fit-and-flare, wrap, bodycon, empire |
| **Jacket / Blazer** | fitted, slim, regular, relaxed, boxy, oversized, moto, bomber, military, denim, anorak, varsity |
| **Vest** | slim, fitted, regular, relaxed, boxy, oversized, longline |
| **Bodice** | fitted, slim, boned, relaxed, wrap (fitted sleeveless block; shares the vest block + shape layer) |

Vest axes beyond silhouette (sleeveless upper-body block; never drafts a sleeve):

| Axis | Options |
|------|---------|
| **neckline** | `notched_v` (short CF slit stepping through a notch into a V), `split_v` (slit flaring into a clean V), plus `v_neck`, `crew`, `round`, `scoop`, `square`, `boat` |
| **binding** | continuous contrast **bias binding** wrapping any of `neckline` / `armhole` / `hem` (`BindingFeature` — edges + finished width + contrast flag) |
| **facings** | turned facing pieces that follow the edge for `armhole` / `hem` / `neckline` |
| **welt_pockets** | placeable bound/besom welt pockets (`WeltPocketFeature` — position, width, count, besom) |

Vest detail pieces generated on demand:

| Piece(s) | Triggered by |
|----------|-------------|
| Neckline / Armhole / Hem Binding | `binding` field, or `neckline_binding` / `contrast_binding` / `armhole_binding` / `hem_binding` detail |
| Armhole Facing (follows the armscye, cut ×4) | `facings: ["armhole"]` or `armhole_facing` detail |
| Hem Facing | `facings: ["hem"]` or `hem_facing` detail |
| Neckline Facing | `facings: ["neckline"]` or `neckline_facing` detail |
| Welt Strip + Pocket Bag | `welt_pockets` field, or `welt_pockets` / `besom_pockets` detail |

Edge bindings and shaped facings live in `backend/app/patterns/finishings.py` and are reusable by any garment; the welt/besom pocket builder is shared via `backend/app/patterns/pockets.py` (`make_welt_pocket`, also used by jackets).

### Garment shape modes (silhouette/contour)

Shape-aware garments (**vest**, **bodice**) can reshape the outline *contour* — the hem and side-seam — beyond the coarse fit styles. The vision step returns one structured `ShapeFeature` (hem style + depth + waist taper + hem sweep), and the **AI Assist modal exposes a Shape-mode toggle** that picks how the silhouette is generated, sent to `/api/generate` as `shape_mode`. The three strategies all consume the same detected shape so they can be compared apples-to-apples:

| Mode | How it works | Trade-off |
|------|-------------|-----------|
| `modifiers` (default) | A reusable post-build layer (`backend/app/patterns/shaping.py`) reshapes the outline by edge label — hem contour (`pointed`/`angled`/`curved_scoop`/`high_low`/`cutaway`) + taper/sweep + **side vents** + **front cutaway/open-drape**. | Composable, predictable, always sewable |
| `warp` | Remaps the side+hem subpath onto a normalized control-point hull (`SilhouettePath`), anchoring neckline/armhole/CF-fold. | Most flexible, experimental |
| `fit_params` | Bakes a coarse per-silhouette contour into the builder at draft time (`vests.py::_VEST_SHAPE_PARAMS`). | Simplest, can't do true contour |

Hem contours: `straight`, `pointed` (centre-front V point), `angled` (diagonal hem), `curved_scoop`, `high_low`, `cutaway` (rounded-open waistcoat front). Beyond the hem, the modifiers layer also opens the **lower side seam into a vent** (`side_vent_cm` — the upper seam stays sewn, the lower part is finished as an open vent) and cuts the **front open below the closure** (`front_cut`: `cutaway` / `open_drape` — the front goes off-fold, cut 2, and the lower centre-front sweeps away so the panels separate; a wrap/surplice *overlap* stays `closed`). The shape layer targets edges by their `seamLabel`, so it is garment-agnostic and other garments can adopt it.

**Asymmetric wrap fronts.** Symmetric edge modifiers cannot represent a diagonal wrap where the two fronts are *different* panels (e.g. a Chinese/Tang-style vest). The `asymmetry` feature (`front_style: asymmetric_wrap`, `wrap_side`, `overlap_cm`, `closure_drop_frac`) makes the vest/bodice builder emit two distinct, non-mirrored fronts — an **Overlap (wrap) Front** (the large panel whose free edge is the visible closure) and an **Underlap Front** (the smaller panel beneath) — instead of one mirror-symmetric front. The panels are drafted construction-consistent so the garment is wearable: both fronts carry the **same mirrored neckline curve** (symmetric neck hole; the collar sits evenly), the **shoulder seams, armscye curve, side seams and hem widths match the back exactly**, and the wrap edges are labelled distinctly so they're never auto-sewn as a seam. A **Mandarin / band stand collar** is available too (`neckline: mandarin` or a `mandarin_collar` detail) — its band is sized to the *measured* neck hole, as is the neckline binding. Both are detected from the photo and back-filled from the analysis notes.

**Per-panel warp (foundation).** The `warp` mode also accepts a `silhouette_path.panels` map (a normalized hull per piece name), so an asymmetric garment can warp each panel to its own outline — the groundwork for fully vision-driven outlines.

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

Optional detail pieces for other garments: side pocket bag, back welt pocket, kick-pleat facing, ruffle/tier strip, trouser belt-loop strip (`belt_loops`, count scales with waist).

### Patch pocket shapes

Patch and chest pockets are built with the correct **bottom edge** instead of a
plain rectangle. The vision step appends a shape token (with a notes-based
fallback) and the engine builds the matching geometry — shared across shirts,
jackets, skirts and blazers via `backend/app/patterns/pockets.py`:

| Token | Bottom shape |
|-------|-------------|
| _(none)_ | `square` — flat bottom |
| `pocket_pointed` | chevron / V-point at the centre (e.g. heritage tee chest pocket) |
| `pocket_rounded` | flat bottom with rounded lower corners |
| `pocket_angled` | 45° chamfered (hexagonal) lower corners |
| `pocket_curved` | smooth U-shaped bottom |

### Pleats

Pleats are handled for real: the analysis returns a structured `pleats` object
(`type`, `count`, `placement`, `depth_cm`) and the engine
(`backend/app/patterns/pleats.py`) **adds the fabric allowance** — each pleat
consumes `2×depth` (knife/accordion/pintuck) or `4×depth` (box/inverted box) —
**and draws the fold + placement markings** (fold lines render dashed; a tick
shows the fold direction). Supported placements per garment:

| Garment | Pleat handling |
|---------|----------------|
| **Skirt** | full-length knife/box/inverted pleats distributed across both panels (replaces the old cosmetic `pleated` flare) |
| **Trousers** | 1–2 front-waist pleats near the crease, released to the hip (replaces the front dart) |
| **Dress** | pleats in the Front/Back Skirt portion |
| **Shirt / Jacket** | centre-back action/box pleat for movement ease |

Legacy signals still work: the `pleated` skirt silhouette and a bare `pleats`
detail token are treated as "pleats present, auto-size everything".

### Construction topology (halter / backless / open front)

Three orthogonal axes — captured in the structured `construction` object the vision
step returns — let halter tops, backless designs, and plunging open fronts build
correctly instead of being forced into a closed shoulder-seam bodice:

| Axis | Values |
|------|--------|
| `strap_style` | `shoulder_seam` (default), `halter_neck`, `halter_tie`, `spaghetti_straps`, `wide_straps`, `one_shoulder`, `strapless`, `racerback` |
| `back_coverage` | `full` (default), `low_back`, `racer`, `backless` |
| `front_opening` | `closed` (default), `plunge`, `deep_v_split`, `keyhole`, `surplice`, `placket`, `wrap` |

**Any `strap_style` other than `shoulder_seam` is sleeveless and shoulderless** — no
sleeve and no shoulder seam are ever built (so a strappy top can't regress into a
sleeved blouse). A **halter** rises into an **integral neck strap**; **spaghetti /
wide / one-shoulder** build a strapless-style bodice **plus separate strap pieces**;
**strapless** has none. All add a **Front Facing**.

`front_opening` decides whether the front is split — *a deep V does not by itself
divide the front*:

- `closed`/`plunge` → **one continuous Front on the CF fold**; the deep V is a notch,
  the fabric is continuous below it (no centre-front seam).
- `deep_v_split` → the centre front is open down the middle. For a **halter** this is
  still **one continuous piece** cut on the fold at the **back-neck**: an open V from
  under the strap to the hem, the two panels joined *only* by the strap. For a
  shoulder-seam front it is two off-fold halves.

`back_coverage`: `backless` omits the Back Bodice (adds a **Waist Tie**); a
shoulderless top otherwise gets a **half-back band** (straight top edge below the
shoulder blades, bare shoulders). `elastic_hem`/`drawstring_hem` build a native **Hem
Casing Band**. The dress builder honours the same axes.

The vision layer reports `construction` directly, with a notes-based fallback
(`_infer_construction_from_notes`), and the prompt now insists a strap/halter top is
`sleeveless` with no shoulder seam. Because most halters cover the lower back, an
unseen or only *assumed*-open halter back defaults to `low_back` — `backless` is
reserved for a clearly open back or a `deep_v_split` front. Neckline-descriptor tokens
(`v_neck`, `round_neck`, …) never produce a piece.

> See **[Docs/pattern-piece-construction-notes.md](Docs/pattern-piece-construction-notes.md)**
> for the full per-garment construction nuances (the source of truth for these rules).

Requires a configured LLM provider (Anthropic or Ollama) in the backend environment.

---

## Architecture

```
Seamster/
├── frontend/               React 18 + TypeScript + Tailwind + Vite
│   └── src/
│       ├── api.ts                      Single API client — typed wrappers for all backend calls; base URL from VITE_API_URL (default /api via Vite proxy)
│       ├── components/
│       │   ├── Canvas.tsx              Main SVG canvas — all drawing tools, snapping, rendering
│       │   ├── Toolbar.tsx             Left tool-button column (8 tools + 3 toggles + help)
│       │   ├── HelpPanel.tsx           Tool reference modal (? button)
│       │   ├── PropertiesPanel.tsx     Right sidebar — element and piece editing
│       │   ├── MeasurementPanel.tsx    Body measurements with range validation
│       │   ├── AIAssistModal.tsx       Phase 2: photo upload + feature review + generate workflow
│       │   ├── InstructionsPanel.tsx   Sewing instructions drawer — sections, steps, tips
│       │   ├── AssemblyView.tsx        Assembly view — edit seams (click edge → edge, range handles), Pieces / Laid flat layouts
│       │   ├── assembly/geometry.ts    Layouts (shelf grid, laid-flat seam alignment), edge sampling for seam ranges
│       │   ├── assembly/seams.ts       Seam names, sewn lengths, match / ease / mismatch
│       │   ├── assembly/SeamsPanel.tsx Seams list + seam editor (range, side, direction, delete)
│       │   ├── PieceLibrary.tsx        Library drawer (drag presets onto the canvas)
│       │   ├── BodyModelView.tsx       3D body view (lazy-loaded) — react-three-fiber canvas, orbit controls, on-demand rendering
│       │   └── BodyCustomizationPanel.tsx  Body sliders + shape preset + reset (sidebar, 3D view only)
│       ├── three/
│       │   ├── bodyRegions.ts          Body fields/defaults, profile resolution, shape presets, ellipse math, landmark rings
│       │   ├── avatarBuilder.ts        Monotone-cubic ring smoothing + loft → avatar mesh arrays (no three import; unit-tested)
│       │   └── types.ts                BodyProfile, LoftRing, MeshData, AvatarData
│       ├── context/
│       │   └── EditorContext.tsx       Redux-style reducer; ~30 action types; 50-level undo stack
│       ├── snapping/
│       │   └── snapEngine.ts           Endpoint / midpoint / grid / angle snap with colour coding
│       ├── export/
│       │   ├── svgExport.ts            Client-side SVG export
│       │   └── pdfExport.ts            Backend-assisted tiled PDF (A4)
│       ├── library/
│       │   ├── presets.ts              Piece library presets (pockets, collars, cuffs, bands, flaps, buttons, buttonholes)
│       │   └── context.ts              Pattern neckline / waist / wrist the presets size themselves to
│       ├── utils/
│       │   ├── formulaEval.ts          Sandboxed expression parser (no eval) for parametric dims
│       │   ├── pieceTransforms.ts      Flip H/V, rotate, mirror-copy geometry
│       │   └── psnap.ts                .psnap read/write used by every save/open path
│       └── types/
│           └── index.ts                Element, Piece, SeamConnection, Measurement TypeScript interfaces
│
└── backend/                Python 3.12 + FastAPI
    └── app/
        ├── main.py                     FastAPI app, CORS config
        ├── api/export.py               POST /api/export/pdf — returns tiled PDF binary
        ├── api/analyze.py              POST /api/analyze — LLM vision → GarmentFeatures JSON
        ├── api/generate.py             POST /api/generate — parametric engine → .psnap JSON
        ├── api/attachments.py          POST /api/infer-attachments — seams, trim seams, pocket placements for any pattern
        ├── api/refine.py               POST /api/refine — photo + psnap → vision-reshaped psnap
        ├── api/instructions.py         POST /api/instructions — features+pieces → sewing instructions JSON
        ├── patterns/
        │   ├── geometry.py             Point, offset_polygon, cubic/quadratic bezier
        │   ├── pockets.py              Shared patch-pocket builder (square/rounded/angled/pointed/curved) + placeable welt/besom pocket (make_welt_pocket)
        │   ├── finishings.py           Reusable edge finishes: continuous bias bindings + shaped armhole/hem/neckline facings
        │   ├── pleats.py               Pleat geometry: PleatSpec, allowance rule, build_pleats, apply_pleats
        │   ├── skirts.py               Skirt block: 12 silhouettes, 6 lengths, 4 optional pieces (PieceSpec + DartSpec + PleatSpec)
        │   ├── shirts.py               Shirt/blouse block: 8 fit styles, 15 necklines, 9 sleeve types, halter/backless/open-front construction
        │   ├── trousers.py             Trouser/pants block: 11 fit styles, 4 rise styles, 5 lengths, optional pieces; back seat tilt, applied fly (straight CF + J Fly Facing + Fly Shield), interpolated knee/scaled ankle, 3-D cargo bellows pocket (bag + shaped flap + gusset/flat variants + leg placement marks)
        │   ├── dresses.py              Dress block: 7 silhouettes, 10 necklines, 6 sleeve types, 6 optional pieces
        │   ├── jackets.py              Jacket/blazer block: 12 fit styles, 5 lengths, 5 sleeve types, 2 collar-type axes, 2 breast-style options, 16 conditional pieces
        │   ├── vests.py                Sleeveless vest block: 7 fit styles, notched/split-V neckline, contrast bindings, armhole/hem facings, welt pockets
        │   ├── shaping.py              Garment-shape layer: hem contour + taper modifiers, control-point warp, mode dispatch (vest/bodice)
        │   ├── modifiers.py            Legacy silhouette modifiers (used by skirt tests only)
        │   ├── engine.py               generate_pattern() → full .psnap JSON dict; _compute_connections() auto-builds SeamConnection list from edge_labels
        │   ├── attachments.py          Trim seams (collar, cuff, fly, bags…) along host-edge paths with ranges; pocket placements; layers
        │   ├── instruction_generator.py  LLM call → structured sewing instructions JSON
        │   ├── llm_fallback.py         LLM-generated parametric pieces for unsupported details (template-cached, validate/repair loop, placeholder fallback)
        │   ├── learned_pieces.py       Template store + 7 formula-driven geometries (rectangle, shaped_rectangle, trapezoid, godet, quarter/half-circle flounce, curved_band)
        │   ├── novel_validation.py     Geometric checks for LLM pieces (dimension bounds, self-intersection, attachment-edge length)
        │   ├── compositions.py         Composed garments: shorts/coat/tunic/romper/jumpsuit built from existing blocks (static plans + LLM planner)
        │   └── vision_contours.py      Photo-contour patternizer: simplify/symmetrize/snap + scale, optional bezier curves (tunable constants at the top)
        ├── debug_trace.py              Most-recent AI run trace → backend/debug/last_run.json (analyze prompts/response/features + generate events/output + refine attempts/summary)
        ├── llm/                        Provider-agnostic LLM layer (Anthropic + Ollama)
        │   ├── base.py                 LLMProvider ABC, LLMResponse, common error hierarchy
        │   ├── anthropic_provider.py   Anthropic Claude implementation (text + vision)
        │   ├── ollama_provider.py      Local Ollama implementation via httpx /api/chat
        │   └── factory.py              get_provider() + shared retry & JSON-parse helpers
        ├── vision/
        │   ├── analyzer.py             LLM vision call + JSON parse (retry via llm layer)
        │   ├── refine.py               Photo refine pass: vision LLM edits drafted outlines (guards + repair loop + in-place splice)
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
- `undoStack`, `redoStack` — 50-level snapshots of `{elements, pieces, connections}`; drags collapse to one entry via `liveBase`, piece-property edits coalesce via `undoTag`
- `instructions` / `instructionsLoading` — sewing instructions state (null until generated)
- `lastFeatures` / `lastMeasurements` — the inputs used for the last generate call (used to regenerate instructions)
- `bodyProfile` — 3D avatar `{ overrides, shape }`; only user-set body values (the rest resolve from `measurements`, then defaults). Survives `LOAD_STATE`; not in undo history

### File format (`.psnap`)

JSON with top-level keys: `version`, `elements`, `pieces`, `measurements`, `connections`, `placements` (optional; plus `instructions`, `lastFeatures`, `lastMeasurements` when present). Every save path writes the same document (`frontend/src/utils/psnap.ts`).

- Each `line` element has `isFold: boolean` and `seamLabel: string` fields.
- Each `curve` element has a `seamLabel: string` field.
- `connections` is an array of `{ label, from: { pieceId, edgeId, range?, side? }, to: {…}, reversed?, source? }` objects (optional fields: see [Docs/assembly.md](Docs/assembly.md)) — the engine's stitch map, built from edge `seamLabel`s. A shared label alone is not enough; pairing depends on the kind of seam. **Construction seams** (`side_seam`, `shoulder`, `inseam`, `crotch`, `sleeve_seam`, `center_front/back`) join front↔back panels of one section and must match in length (±15% / 1.5 cm), so a bodice side seam never pairs with a skirt side seam. **Horizontal joins** (`waist_seam`, `yoke_seam`) pair same-side pieces (front bodice ↔ front skirt). **Openings** (`hem`, `neckline`, `armhole`, `waist`, `wrist`, novel attachment labels) pair a garment shell with a *different* shell (sleeve, collar, cuff, waistband, facing, flounce) and never front↔back, so hem↔hem is never a seam. Multi-edge seams (e.g. the trouser side seam, drawn as 4 segments per leg) are paired 1:1 in outline order — never as a cross-product — with reversed traversal detected by segment-length mismatch; each edge belongs to at most one connection per opposing piece.

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
| [Docs/3d-body.md](Docs/3d-body.md) | **3D body & garment fit** — procedural avatar (ellipse loft, landmark table, shape presets, monotone smoothing), body-profile resolution, rendering notes, tests, and the fit-preview / drape roadmap |
| [Docs/assembly.md](Docs/assembly.md) | **Assembly** — seam connections and placements data model, how seams are inferred and edited, how they reach the 3D drape |
| [Docs/pattern-piece-construction-notes.md](Docs/pattern-piece-construction-notes.md) | **Construction nuances per garment/piece** — on-fold vs cut-2, the strap/back/front-opening topology axes (halter split vs non-split, shoulderless = sleeveless), and the source of truth for piece-generation rules |

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
| `VITE_API_URL` | No | `/api` | **Frontend** (build-time) — backend API base URL. Unset = same-origin `/api`, proxied to `http://localhost:8000` by the Vite dev server. Set to e.g. `http://192.168.1.20:8000/api` for LAN/phone testing (remember to add that origin to `CORS_ORIGINS`) |

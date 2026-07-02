# Pattern Piece Construction Notes

A living reference of the **high-level construction considerations and design nuances**
the parametric engine must account for, per garment type and per piece. The goal is to
capture the subtle, easy-to-miss decisions (e.g. *a halter can have a deep V that splits
the front into two panels, or a deep V that does not split*) so they are not re-learned
each time.

This documents intent and edge cases. For the code, see `backend/app/patterns/` (one
builder per garment: `skirts.py`, `dresses.py`, `trousers.py`, `shirts.py`, `jackets.py`,
`vests.py`, plus shared `pockets.py` / `pleats.py` / `finishings.py`). For the data contract see
`backend/app/models/features.py`; for the vision vocabulary see
`backend/app/vision/prompts.py`.

---

## Global principles (apply to every piece)

- **Coordinate system.** 1 SVG unit = 1 cm. X increases rightward, Y downward. For bodices
  `y=0` is shoulder/nape level and `x=0` is the CF/CB fold or seam edge; for bottoms `y=0`
  is the waistline. Never mix px and cm.
- **On-fold vs cut-2.** A piece cut **on the fold** is symmetric about its CF/CB edge — that
  edge is a fold line, *not* a seam, and must be the **closing (last) edge** of the outline
  so the serializer marks it `isFold`. A piece that is **not** on the fold is cut as 2
  mirrored halves (`cut_qty=2`) with a real CF/CB seam. Choosing wrong creates a phantom
  centre seam (a recurring bug on plunge necklines) or, conversely, fuses two pieces that
  should be separate.
- **Seam labels drive assembly.** Every outline edge carries a `seamLabel`
  (`neckline`/`shoulder`/`armhole`/`side_seam`/`hem`/`center_front`/`center_back`/
  `waist_seam`/`sleeve_seam`/`wrist`/`inseam`/`crotch`…). Edges that share a label across
  two pieces become a sewing connection. Fold edges are skipped — never connect a fold.
- **Ease is intentional.** Wearing ease (and style ease) is baked into the block; the flat
  pattern is larger than the body. Fitted/slim styles suppress; boxy/oversized add.
- **Darts/pleats** are interior markings, not part of the cut outline. Darts shape a flat
  panel to a curved body; pleats need their fabric **allowance added** to the panel width,
  not just a marking (`pleats.py::pleat_unit_allowance` = 2×depth knife/accordion/pintuck,
  4×depth box/inverted box).
- **Detail tokens vs structured fields.** A detail token that names a *technique* or a
  *neckline descriptor* (e.g. `topstitching`, `v_neck`, `smocking`) must NOT generate a
  piece — register it so the LLM fallback does not invent one. Real extra pieces come from
  the parametric builder or the learned/LLM fallback.
- **Grainline** runs along the lengthwise grain (vertical on most body panels, along the
  long axis of bands/straps). It is advisory but should read sensibly.

---

## Construction topology for upper-body garments (the subtle axis)

Necklines alone cannot describe how a top is held up, how much back it has, or how the
centre front opens. Three **orthogonal** topology axes — plus a **`strap_width`** sizing
axis — (`models/features.py::Construction`) capture this; any combination can occur.

> **All of these apply to the same "tops" block.** `shirt` and `blouse` share one generator
> (`shirts.py::build_shirt_block`), and tanks, camis, halters, tube tops, etc. are all
> produced by it via the construction axes below — there is no separate builder per top type.
> The `garment_type` is mainly a **vision-priming hint** (it tunes the analyze vocab), not a
> structural fork. The dress builder honours the same axes for its bodice.

### `strap_style` — how the garment is held up
- **shoulder_seam** (default): ordinary garment seamed over the shoulders; *can* have
  sleeves.
- **halter_neck / halter_tie**: the front rises into a strap that goes **around/behind the
  neck**; **no shoulder seam**, **bare shoulders**. The strap is **integral** to the front
  piece, not separate.
- **spaghetti_straps / wide_straps**: thin / wide **separate** straps that sit **over the
  shoulders** (a tank/cami).
- **one_shoulder**: a single asymmetric strap.
- **strapless**: bare top edge, no straps.
- **racerback**: straps converge to a narrow back.

> **Halter vs tank — decided by the SUPPORT/ANCHOR POINT, not by how thin the straps are:**
> - A **halter** is supported at the **NECK**: the left and right straps connect to each
>   other behind/around the neck (the neck holds the top up), so **nothing crosses the
>   shoulders** and the shoulders are **bare** → `halter_neck`.
> - A **tank/cami** is supported at the **SHOULDERS**: each strap runs **over a shoulder**,
>   connecting the front to the back → `spaghetti_straps` / `wide_straps`.
>
> The model habitually calls any thin-strap sleeveless top a "halter," so the analyzer is
> strict: `_refine_strap_style` **keeps `halter_neck`/`halter_tie` only when the notes give
> positive neck-support evidence** (e.g. "behind the neck", "around the neck", "ties behind",
> "bare shoulders"); with explicit tank/over-shoulder language, or with **no** neck evidence
> at all, it downgrades to `spaghetti_straps` ("when unsure → tank"). It is skipped only when
> the neckline is explicitly `halter`.

> **Rule: any `strap_style` other than `shoulder_seam` is SLEEVELESS and SHOULDERLESS.**
> Never build a sleeve or a shoulder seam for a strappy/halter top, even if a stale
> `sleeve_length` says otherwise. Non-halter straps are emitted as **separate strap
> pieces**; the halter strap is part of the front.

> **Back height follows the strap style** (so the back side seam matches the front):
> a **halter** gets a LOW band back (at the underarm — bare upper back); a **tank**
> (spaghetti/wide/one-shoulder/racerback) gets a HIGHER band back at the upper back (covers
> the shoulder blades, straps reach over the shoulders) — *not* a low bandeau; **strapless**
> is a tube/bandeau at the same upper level as its front.

> **A spaghetti-strap top can never have a `full` back.** Thin straps can hold up at most a
> half back (`low_back`) — or none (`backless`). `analyzer.py::_clamp_spaghetti_back` clamps a
> `spaghetti_straps` + `full` to `low_back`; the prompt tells the model the same. (Note: any
> shoulderless back is already a half/band back geometrically — this keeps the *value* honest
> and rules out a full shouldered back.)

### `back_coverage` — how much back there is
- **full**: normal back. For a shoulderless top "full" still means **no shoulder seam** →
  a band back (flat top edge at the underarm).
- **low_back**: a covered **half back** to ~shoulder-blade level, bare shoulders.
- **racer**: narrow racer back.
- **backless**: no back panel at all — replace with a **waist tie** so the top stays on.

> When the back is not visible in the photo, **prefer `low_back`** (most halters cover the
> lower back). Reserve `backless` for a clearly open back, or when the front is a
> `deep_v_split` (those tops are usually backless). Do not assume backless from a halter neck.

### `front_opening` — the centre-front treatment (the user's example nuance)
- **closed**: closed CF.
- **plunge**: a deep V/U opening on a **single continuous front** — the V is just an
  opening; the fabric is **continuous below it**, so the front is **one piece cut on the
  fold** (no centre seam).
- **deep_v_split**: the centre front is open **all the way down**, so the front is **two
  panels**. For a halter this is **one continuous piece cut on the fold along the TOP
  (back-neck) edge** — one panel + its strap is drafted, and cutting on the top fold mirrors
  it over the neck so the two panels are joined **only by the strap** (the centre front is
  fully open below the strap). The fold belongs on that top back-neck seam, **not** down the
  side of the strap (a vertical centre fold would wrongly fuse the two panels along a long
  centre band). For a shoulder-seam garment a deep_v_split is an open/cardigan front cut as
  two off-fold halves.
- **keyhole / surplice / placket / wrap**: small CF cut-out / crossed wrap / buttoned
  placket / wrap-over.

> **The headline nuance:** *plunge ≠ split.* A deep neckline does not by itself divide the
> front. Only `deep_v_split` separates the panels. Conflating them creates an unwanted
> centre-front seam — or, worse, cuts a genuinely split front on the fold (no opening).

**Detecting split vs plunge (the vision step gets this wrong often).** Visual cues for a
`deep_v_split`: you can see **skin/body between two separate front panels**, the front edges
are **loose/open and do not meet**, or it is a **tie-front / wrap** that knots or crosses at
the centre. A `plunge` is a V cut into **one unbroken panel**. The analyzer applies a
safety net (`analyzer.py::_refine_front_split`): if the model says `plunge` but its own notes
describe open/separate panels, it upgrades to `deep_v_split` — because this is a defining
design detail that is easy to mislabel (and the model often contradicts itself, e.g. "panels
open at the centre … on a single continuous front").

### `strap_width` — how thick the strap is (detected per photo, not fixed)
- **thin** ≈ 2 cm (skinny / spaghetti) · **medium** ≈ 4 cm · **wide** ≈ 5–8 cm (a thick band
  the bust flares into). `None` ⇒ a per-style default (halter ≈ medium; spaghetti ≈ 2,
  wide_straps ≈ 5).
- Sizes **both** the integral halter strap **and** the separate spaghetti/wide strap pieces,
  so the piece matches the photo — a skinny-strap halter stays skinny; a wide one comes out
  wide. *Do not blanket-thicken every strap.*
- The halter strap's **outer edge is a single smooth curve** from the strap top down to the
  armscye, so the **bust flares gradually into the strap** (no abrupt corner) at any width.
- Vision estimates the category (judged relative to the body); `analyzer.py::_refine_strap_width`
  also infers it from notes ("skinny/spaghetti" → thin, "wide/thick/flares into" → wide).
- Mapping lives in `shirts.py::_strap_cm`; `_STRAP_CM = {thin: 2, medium: 4, wide: 7}`.

---

## Tops — Shirt / Blouse (`shirts.py`)

**Pieces:** Back Bodice + Front (Bodice) always; Sleeve unless sleeveless; conditional
Collar, Ribbed Collar Band, Cuff, Turtleneck/Mock band, Henley Placket, Chest Patch Pocket;
and construction-driven Front Facing, Waist Tie, Hem Casing Band, and separate Strap pieces.

**Fit styles:** slim, fitted, regular, relaxed, boxy, oversized, athletic, longline — drive
shoulder slope, armhole depth, waist suppression, and drop-shoulder.

**Necklines:** crew, round, scoop, v_neck, square, polo, boat, mandarin, turtleneck,
mock_turtleneck, henley, off_shoulder, keyhole, halter, strapless. Curved necklines use a
bezier; v_neck/halter plunge deep.

**Sleeves:** sleeveless, cap, short, flutter, three_quarter, bell, puff_short, long,
puff_long. Flared (flutter/bell) attach a wide hem to the armscye; puff gathers a wide cap.

**Nuances**
- **Halter (plunge/closed)** → ONE piece on the CF fold; the integral straps tie behind the
  neck; the deep V is a notch, fabric continuous below. Add a Front Facing.
- **Halter (deep_v_split)** → ONE continuous piece cut on the fold at the **back-neck**; the
  centre front is an open V from under the strap to the hem; the two panels join **only** via
  the strap. (This is the olive-halter case.)
- **Spaghetti / wide / one-shoulder / strapless** → shoulderless **band front** on the fold
  (top edge at the upper bust, dipping into a V for a plunge) + separate strap pieces
  (none for strapless). Always sleeveless.
- **Strap thickness is `strap_width`-driven** (thin/medium/wide → ≈2/4/7 cm), for both the
  halter strap and the tank strap pieces; the halter strap flares gradually (curved outer
  edge). Never blanket-thicken.
- **Back** for any shoulderless top → flat-top band (no shoulder seam) unless backless;
  halter back sits low (underarm), tank back sits higher (covers the shoulder blades, matches
  the front side seam); backless → no back + Waist Tie. A spaghetti top is **never `full`** —
  at most `low_back`.
- **Placket** (`button_placket`) shifts the CF outward and cuts the front off-fold.
- **elastic_hem / drawstring_hem** → a native **Hem Casing Band** (gathered hem), not a seam.
- Neckline descriptor tokens (`v_neck`, `round_neck`) must not spawn a "V_Neck" piece.

---

## Tops — Bodice (no builder yet)

`bodice` currently routes to the measurements-only placeholder. When implemented it should
reuse the shirt construction axes plus **boning channels**, **busk/lace-up closures**, and
**self-lining** (every corset/bustier panel is doubled). Cup seams (princess/panel lines)
matter more than darts.

---

## Dress (`dresses.py`)

**Pieces:** Front/Back Bodice + Front/Back Skirt always; Sleeve (or Spaghetti Strap when
`sleeve_length=spaghetti`); conditional Bodice Facing (strapless/halter), Collar, Belt/Sash,
Side Pocket Bag.

**Silhouettes:** shift, sheath, a_line, fit_and_flare, wrap, bodycon, empire (empire raises
the waist seam to under-bust). **Necklines** add sweetheart, halter, strapless, off_shoulder.

**Nuances**
- The bodice and skirt join at a **waist_seam**; empire moves it up. Wrap adds a CF overlap
  and cuts the front off-fold.
- Honors the same **construction axes** as shirts (halter/strapless/backless/plunge). A
  backless dress drops the **back bodice** but keeps the back skirt + a waist tie.
- A bust dart appears on fitted silhouettes; release it into gathers/pleats if the style
  calls for it.

---

## Skirt (`skirts.py`)

**Pieces:** Front + Back panels (or a single panel on the fold) + Waistband; conditional
side pocket bag, back welt pocket, kick-pleat facing, ruffle/tier strip, belt-loop strip.

**Silhouettes:** straight, pencil, a_line, flared, circle, gathered, pleated, wrap, trumpet,
mermaid, tulip, tiered. **Lengths:** micro…maxi.

**Nuances**
- **Waist shaping** is taken by darts (woven) or eased/elasticated (knit/elastic waistband).
- **Flare** is added at the hem side-seam (a_line/flared) or as a true radial sweep (circle,
  approximated as a wide panel to refine in the editor).
- **Pleated** is real fabric allowance + fold/placement markings, *not* the old cosmetic
  hem flare. **Wrap** adds a CF overlap and is not cut on the fold.
- **Waistband** types: straight, contoured (curved to the body), elastic/faced (no separate
  band piece). A kick pleat/vent needs its own facing/extension at the CB hem.

---

## Trousers / Pants / Shorts (`trousers.py`)

**Pieces:** Front Leg + Back Leg + Waistband; conditional fly facing, fly shield, front
pocket bag, back welt pocket, cargo pocket (bag + flap + optional gusset), cuff band,
ankle elastic, belt loops.

**Cargo (bellows) pocket** — a real 3-D pocket, not two flat rectangles. Three styles from
the detail token: **bellows** (default, pleated — the bag is cut `W + 4·depth` wide ×
`facing + H + 2·depth` tall and the side/bottom bellows folds, placement lines and the top
facing fold are drawn as interior marks; bottom corners rounded), **gusset** (flat bag +
a separate depth gusset strip), or **flat** (a flapped patch, the old behaviour). The
**flap** uses the shared shaped-bottom builder (square/rounded/angled/pointed/curved). The
Front Leg carries the pocket **placement outline + bartack ticks** at the top corners
(interior marks). Construction: make the flap, finish the opening, press the bellows,
topstitch the bag down leaving the top open, bartack the corners, then attach the flap —
all on the flat leg before closing the inseam/outseam.

**Fit:** straight, slim, skinny, cigarette, wide_leg, palazzo, bootcut, flared, jogger,
relaxed. **Rise:** low/mid/high/ultra-high. **Lengths:** full_length…shorts.

**Nuances**
- **Crotch curve** is a Bézier, not a corner; its depth scales with fit (shallow for skinny,
  deep for palazzo/jogger to allow sitting). Front and back curves differ (back is deeper).
- **Back seat tilt** — the back centre-back seam is **not vertical**: the CB waist corner
  leans toward the side (`back_tilt`, ~1.2–2.5 cm by fit) and rises above the side waist
  (`back_lift`, ~0.8–2.0 cm), so the CB seam is longer over the seat (room to sit/bend) and
  the back fits like a tailored trouser, not a pyjama. The back waist quarter is preserved
  along the now-slanted top edge, and the **back darts ride that slanted edge** (via the
  optional `DartSpec.baseline`). Tighter/active fits tilt more; palazzo/jogger tilt least.
- **Front fly (applied-facing model)** — for zip/button fly the **CF is cut straight**; a
  separate **J-shaped Fly Facing** is applied to the **left** front and a **Fly Shield**
  (underlap) backs the **right** front (both auto-emitted for any fly closure). The only
  thing marked on the leg is the **fly topstitch "J"** (`fly_topstitch`, interior, not a
  seam), `fly_ext` in from the CF (3.5 cm zip / 4.0 cm button) curving back to the CF at the
  bottom of the fly. The facing width tracks `fly_ext` (`fly_ext + 3.0`). Elastic-waist /
  side-zip have no fly pieces and no marks. *(An earlier build used a cut-on extension; it
  was replaced by this applied-facing model to avoid double-counting the fly fabric.)*
- **Leg silhouette** — the **knee is interpolated** between the thigh side-seam and the
  ankle (not an independent multiplier), so the side seam is smooth and never balloons out
  at the knee. **Ankle widths scale with the body** (`hip_qt × ankle_mult`, floored for
  small frames). A per-fit `knee_nip` pulls the knee in for **flared/bootcut** (slim knee,
  flares to the hem); wide_leg/palazzo are straight columns; tapered fits taper smoothly.
- **Rise** sets the waist height above the crotch; pair with the waistband/closure.
- **Pleated trousers** put 1–2 pleats near the crease, released by the hip (replacing the
  front dart). **Jogger/elastic** styles add an ankle band/elastic.
- Closures map to construction: zip fly + fly shield, button fly, side zip, or elastic
  (no fly). Shorts are the short-length case of the same block.
- **Interior marks** (`MarkSpec` on `PieceSpec`) are a shared, opt-in mechanism for
  non-sewn construction guides (fly fold/topstitch now; trouser crease line planned). They
  serialise as standalone interior elements and never form seam connections.

---

## Jacket / Blazer / Coat (`jackets.py`; coat → placeholder)

**Pieces always:** Back Bodice, Front Bodice (front is **cut off-fold** — the CF is the
opening/button edge), Sleeve. **Conditional:** Back Yoke, Collar, Front Facing, Patch/Welt
Pockets, Cuff Band, Hem Band, Hood, Lining (back+front), Belt Strap, Epaulet Tab.

**Fit:** fitted, slim, regular, relaxed, boxy, oversized, moto, bomber, military, denim,
anorak, varsity. **Collar sub-types:** notch_lapel, peak_lapel, shawl_collar, band_collar,
no_collar. **Breast:** single/double-breasted.

**Nuances**
- The **front is never on the fold** — it opens at CF for the closure; a **facing** finishes
  the lapel/CF edge (width depends on single vs double-breasted).
- A **two-piece tailored sleeve** (upper + under sleeve) is auto-enabled for close fits
  (fitted/slim/moto/military); roomy/casual jackets use a one-piece sleeve.
- **Rib trims** (cuff band, hem band) appear on bomber/varsity; **yoke** splits the back
  (denim/western). **Lining** doubles the body/sleeve pieces. **Hood**, **belt**, **epaulets**
  are outerwear extras.
- **Centre-back action/inverted pleat** adds movement ease (utility/trench/anorak).
- Coat is the long version; until it has a builder it routes to the measurements-only canvas.

---

## Vest (`vests.py`)

**Pieces always:** Front Bodice, Back Bodice — both **cut on the fold**, **never a sleeve**
(a vest is sleeveless by definition; the block never drafts one even if the analysis is
noisy). **Conditional:** Neckline/Armhole/Hem Binding, Armhole/Hem/Neckline Facing, Welt
Strip + Pocket Bag.

**Fit:** slim, fitted, regular, relaxed, boxy, oversized, longline (reuses the shirt
`_FIT_PARAMS` boxy maths — boxy = straight side seam, deep armhole, slight drop shoulder).

**Nuances**
- **Notched / split-V neckline** is a *shaped neckline edge on one continuous on-fold front*,
  NOT an opening to the hem (the panel is whole). Geometry: a short near-vertical CF **slit**
  (`split_width` × `split_height`) that flares into a V; `notched_v` adds a small outward
  **notch** step (collarless lapel-notch look), `split_v` is the clean V. The CF fold runs
  from the hem up to the bottom of the slit — keep it the closing edge so it serialises as a
  fold, never a seam.
- **Sleeveless armholes are finished, not sleeved** — bind OR face them, not both. The
  **armhole facing follows the armscye curve** (offset inward), it is not a flat rectangle.
- **Contrast binding** is the signature trim: a continuous bias strip sized to the actual
  edge **run-length** (neckline = 2× front-neck path + 2× back-neck; armhole/hem similar),
  flagged cut-from-contrast. It wraps the raw edge and shows as a thin lip on the right side —
  distinct from a facing (which turns fully inside). One reusable builder in `finishings.py`.
- **Welt pockets** on the lower front use the shared `pockets.make_welt_pocket` (parametric
  width; `besom=True` for double lips); `count` mirrors a symmetric pair.
- Finishes are driven by the structured `binding` / `facings` / `welt_pockets` fields, with
  loose detail-token fallbacks (`neckline_binding`, `armhole_facing`, `welt_pockets`, …) all
  registered in `_VEST_DETAILS` so the LLM fallback never duplicates them.

---

## Bodice (`engine.py::_generate_bodice_pattern`)

A fitted sleeveless bodice block. Reuses `build_vest_block` (shoulder seams, sleeveless armholes) with
a V/round neckline and the shared shape layer, so `GarmentType.BODICE` is a real pattern (Front + Back
bodice) rather than the old measurements-only placeholder. It is the second garment proving the shape
layer is garment-agnostic.

---

## Garment shape / contour (`shaping.py`) — the silhouette axis

The **outline contour** (hem + side seam) is a first-class, garment-agnostic concern, separate from the
pieces and trim. One detected `ShapeFeature` (hem style + depth + waist taper + hem sweep) drives three
interchangeable `shape_mode` strategies so they can be compared on the same garment:

- **`modifiers`** (default): reshape the outline *after* the block is drafted, targeting edges by
  `seamLabel` (mirrors `apply_pleats`). `reshape_hem` turns the straight `hem` edge into
  `pointed` / `angled` / `curved_scoop` / `high_low` / `cutaway`; `apply_taper` nips the side seam at
  the waist and sweeps/pegs it at the hem; `reshape_side_vent` opens the lower side seam into a vent;
  `apply_front_cut` opens/cuts away the lower centre-front. Composable and always sewable.
- **`warp`**: remap the side+hem subpath onto a normalized control-point hull (`SilhouettePath`),
  keeping the neckline/armhole/shoulder and the CF fold anchored. Flexible but experimental.
- **`fit_params`**: bake a coarse per-silhouette contour into the builder at draft time
  (`vests.py::_VEST_SHAPE_PARAMS`). Simplest; can't express true contour (no curved/pointed hem).

**Nuances**
- Hem styles act on the `hem` edge endpoints: `pointed` lowers the CF corner (mirrors to a centre V on
  the fold); `curved_scoop`/`cutaway` swap the CF corner for a `CurveSegment`; `high_low` offsets CF vs
  side; `angled` raises the side. No vertices are inserted (warp aside), so `edge_labels` stay valid.
- Only **body panels** (carrying both `armhole` and `hem`) are shaped/warped — trim pieces
  (bindings/facings/welts) are skipped so the contour change never deforms a binding strip.
- **Side vent**: the lower side seam is left open, not a separate piece. The seam is split at the
  vent point — the upper part keeps `side_seam` (so it still sews front↔back) and the lower part is
  relabelled to an empty (unconnected) edge, so `_compute_connections` leaves it open. Both front and
  back get the vent; finish each edge separately and bar-tack the vent top.
- **Front cut**: only the FRONT (has `center_front`, not `center_back`). It goes off the fold (cut 2)
  and the lower CF sweeps outward into a `cutaway`/`open_drape` curve so the panels separate at the
  hem. The two CF edges share `center_front` but belong to ONE piece (same `pieceId`), so they are
  never falsely auto-connected. A **wrap/surplice overlap is NOT a cut** — it stays `closed` (the
  fronts still meet, just overlapped).
- The shape layer is keyed purely on edge labels, so any garment that labels its `hem`/`side_seam`/
  `center_front` edges correctly can adopt it by calling `apply_shape` in its generator.

**Asymmetric wrap fronts (`vests.py::_asymmetric_fronts`) — a TOPOLOGY change, not an edge tweak**
- Every other front is mirror-symmetric about a vertical CF (cut on the fold or two mirrored halves),
  so a diagonal wrap where the two fronts are genuinely *different* panels is impossible with the
  symmetric edge modifiers. This is the gap behind Chinese/Tang-style vests.
- `front_style=asymmetric_wrap` drafts the front in a **full-front frame** (x: 0 = left side seam …
  FW = 2·chest_qt = right side seam; CF at the middle) and returns two **non-mirrored, cut-1** panels:
  an **Overlap Front** (the large wrap panel; its diagonal free edge is the visible closure crossing
  the body) and an **Underlap Front** (the smaller panel beneath). `wrap_side` reflects the whole
  construction; `overlap_cm` is how far the wrap crosses past CF; `closure_drop_frac` is where the
  diagonal lands (0 = underarm … 1 = hem).
- The wrap/closure edges are labelled `overlap_edge` / `underlap_edge` (distinct, and each lives in a
  single piece) so they are **never auto-connected** as a seam — the panels overlap, they don't join.
  The side seams stay `side_seam` and still connect to the back.
- A **Mandarin / band stand collar** pairs with these (parametric band, cut 2); driven by
  `neckline=mandarin` or a `mandarin_collar` detail.

---

## Shared detail pieces

- **Patch pocket** (`pockets.py`): one builder, bottom-edge shape selectable —
  square / rounded / angled / pointed / curved. Heritage/streetwear chest pockets are often
  pointed, not square.
- **Welt pocket** (`pockets.py::make_welt_pocket`): one placeable builder — welt strip + bag
  (no visible bag outside), parametric opening width / welt height / bag depth, `besom=True`
  for double lips. Shared by jackets and vests. **In-seam/slash**: a bag hidden in a seam
  (cut 4). **Cargo/bellows**: bag + button-down flap.
- **Edge binding / shaped facing** (`finishings.py`): a binding is a continuous bias strip
  sized to the edge run-length that wraps the raw edge (a visible, optionally contrast lip);
  a facing is a shaped band that follows the edge (offset inward) and turns fully inside.
  Reusable by any garment — currently the vest's neckline/armhole/hem finishes.
- **Bands/casings/ties/straps**: simple rectangles (waistband, cuff, collar band, rib trim,
  hem casing, waist tie, straps). Cut on fold when the band folds over (most), else flat;
  straps are cut in pairs (outer + lining) and turned.

---

## Checklist when adding/altering a piece

1. Is it cut **on the fold** or as **two halves**? Put the fold edge last; don't seam a fold.
2. Does a **deep neckline split** the panel, or is it a notch on one continuous piece?
3. Is the garment **shoulderless** (strap/halter/strapless)? Then sleeveless + no shoulder
   seam; emit separate straps unless it's a halter (integral) or strapless (none). Is it a
   **halter** (anchored at the neck, bare shoulders) or a **tank** (straps over the
   shoulders)? When unsure → tank. A spaghetti top is never `full`-backed.
4. Is the strap sized by **`strap_width`** (thin/med/wide), not hardcoded? Halter strap flares
   gradually (curved outer edge), not an abrupt skinny band.
5. Do the **shared seam labels** match the piece it sews to (lengths/labels)? For a shoulderless
   back, its top edge must sit at the same level the front side seam starts.
6. Does any **detail token** risk spawning a duplicate/junk piece? Register techniques and
   neckline descriptors so the fallback ignores them.
7. Did you add **pleat allowance** (not just a marking) where pleats are real?
8. Update `models/features.py`, `vision/prompts.py` vocab, and the registry together so the
   analyze → generate contract stays in sync (`test_parametric_registry_sync.py`).

# 3D Body & Garment Fit

The 3D view shows a measurement-driven body (a mannequin) that the user can resize and reshape. It is the base for putting the drafted pattern on that body. The work ships in three phases, each its own entry in `harness/FEATURES.json`:

| Phase | Feature id | Status |
|-------|-----------|--------|
| 1. Parametric body avatar + customization UI | `body-avatar-3d` | Done (procedural body; realism upgrade in progress, see below) |
| 2. Static fit preview: the current pattern wrapped onto the body, with a fit map | `garment-3d-fit-preview` | **Done** — see *Garment fit preview* |
| 3. Physics drape: position-based dynamics cloth, seams sewn, gravity, body collision with friction | `garment-3d-drape-simulation` | **Done** — see *Drape simulation* |

Everything runs in the browser, and no backend endpoint is involved.

> **Realism.** The current body is generated procedurally from measured cross-sections. It is accurate to the tape, but it still reads as a stylized dress form. Real anatomy (collarbones, deltoids, knees, how breasts sit on the ribcage) needs a sculpted base mesh. The chosen next step is a base body modelled in **Fusion 360**, deformed at runtime to the user's measurements; see *Next: sculpted base mesh* below. The measurement, tape-fitting, worker and rendering code here carries over unchanged.

---

## Libraries

| Package | License | Why |
|---------|---------|-----|
| `three` | MIT | WebGL scene graph, plus `OrbitControls` and `RoomEnvironment` from its examples |
| `@react-three/fiber` **v8** | MIT | Lets the scene be written as React components. v9 needs React 19; the app is on React 18. |
| `earcut` (phase 3) | ISC | Triangulates concave pattern pieces |

`@react-three/drei` is deliberately not used, because of its large dependency tree. `BodyModelView` is loaded with `React.lazy()`, so three.js sits in its own chunk (about 230 KB gzipped) and is fetched only when the view is first opened. Meshing runs in a separate Web Worker chunk (about 13 KB).

---

## Files

```
frontend/src/three/
  types.ts            BodyProfile, ResolvedBody, LoftRing (profiled cross-section), Lobe, MeshData
  bodyRegions.ts      Body fields + defaults, profile resolution, shape presets, landmark sections for
                      torso / legs / arms, arm A-pose frame, head + foot ellipsoids
  rings.ts            Section outline R(θ), tape length (convex hull), monotone-cubic interpolation
  bodySdf.ts          Signed distance field: swept section tubes + ellipsoids joined by smooth minimum
  surfaceNets.ts      Narrow-band surface-nets mesher with a Newton projection onto the surface
  avatarBuilder.ts    buildAvatar(body, cell) → mesh + landmarks
  avatarWorker.ts     Web Worker entry: builds the mesh off the UI thread
  useAvatarMesh.ts    Scheduler: coarse preview while dragging, then full resolution; one job in flight
  avatarBuilder.test.ts
  bodyQuery.ts        BodyQuery — the only interface garment code uses to ask about the body
                      (sections at a height, leg / arm sections, neck, shoulder-top height, SDF)
  pieceGeometry.ts    Piece outline → ordered labelled loop; row/column intersections; cdt2d mesh
  pieceClassifier.ts  Piece → body region (torso-upper / torso-lower / leg / sleeve / skip)
  garmentWrap.ts      placeGarment(): wraps each piece onto the body, darts, mirroring, ease
  sdfGrid.ts          Body distance field sampled on a narrow-band grid (fast collision lookups)
  clothSim.ts         Drape: PBD cloth (stretch/bend/stitch/weld/tether), Coulomb friction, collision
  garmentWorker.ts    Web Worker entry: placement, then a streamed, cancellable drape
  useGarmentPlacement.ts  Scheduler for the garment worker (placement blocks; drapes are superseded)
  clothSim.test.ts    Headless drape tests on the engine fixtures
  garmentWrap.test.ts + fixtures/*.psnap.json (real /api/generate outputs)
frontend/src/components/
  BodyModelView.tsx           Lazy 3D view: studio lighting, soft shadow, orbit camera, on-demand frames
  BodyCustomizationPanel.tsx  Body sliders + shape preset + reset (right sidebar, 3D view only)
```

---

## Body profile & measurement resolution

`EditorState.bodyProfile = { overrides, shape }` stores **only the values the user has set** on the Body panel. Each field resolves as:

```
override  ??  state.measurements[measurementKey]  ??  default     → clamped to [min, max]
```

Only true body measurements are mapped from the Measurements panel: `bust`, `waist`, `hip`, `waistToHip`, `inseam`, `shoulder`. `sleeveLength` is not treated as arm length. The panel tags each field `custom` (an override) or `measured` (from the Measurements panel). **Reset to measurements** clears the overrides and keeps the shape preset.

The profile belongs to the user, not the pattern:
- `LOAD_STATE` (open a `.psnap`, AI generate, refine) keeps it.
- It is not part of undo/redo.
- It is not saved in `.psnap` yet.

The 16 fields and their ranges are listed in `BODY_FIELDS` in `bodyRegions.ts`. Defaults describe a 168 cm body with bust 92, underbust 76, waist 74 and hip 98. Underbust is clamped to be no larger than bust.

---

## How the procedural body is built

### Cross-sections
Each landmark is a **profiled section**, not an ellipse. Its outline in the section plane (u = lateral, w = front) is:

```
R(θ) = superellipse(half-width a, front depth b, back depth `back`, exponent n)  +  Σ lobes
```

- **Superellipse:** `n` is above 2 on the torso, which gives the flatter, boxier sections of a real torso. The separate front and back depths make the sections asymmetric front to back.
- **Lobes:** rounded domes `amp·(1 − k²)^1.5` placed at fixed angles: breasts, shoulder blades, belly and buttocks on the torso; quadriceps and calf on the legs. The mirrored pairs keep the body symmetric.
- **Sizing:** a section is scaled so its **tape length**, the perimeter of its convex hull (what a tape measure reads, since it bridges hollows), equals the measurement.
- **Bust:** the chest wall is sized from the underbust (× 1.06). The breast projection is then solved by bisection so the tape over the apexes equals the bust measurement. The bust–underbust difference therefore becomes the cup.
- **Breast profile:** extra upper- and lower-bust sections give the breast its side-on shape.
- **Posture:** section centre z offsets give the spine its S-curve (upper back, chest forward, lumbar hollow, seat back). Shape presets (hourglass, rectangle, pear, apple) change the waist and hip depths, the belly and buttock projection, and the posture offsets.

### Levels
Levels are fractions of height, from adult proportions. Two are measured instead: the crotch sits at the **inseam**, and the hip at waist − **waist-to-hip**. The neck section continues up inside the head.
- **Legs** start at hip level, with the outer thigh just inside the hip line.
- **Arms** hang in an A-pose. The angle opens just enough (up to 55°) to keep a 3.5 cm gap from every torso section from the bust down.

### Interpolation
Between landmarks, every scalar (size, depths, exponent, centre, each lobe amplitude) follows its own **monotone cubic** (Fritsch–Carlson) over distance along the body. As a result, sections never bulge past their landmarks and never fold.

### Surface
The body is the zero set of a **signed distance field**:
- **Tubes:** the torso, each leg and each arm is a tube swept through densely sampled sections, with each section's outline tabulated at 128 angles.
- **Ellipsoids:** the head is a cranium plus a jaw; each foot is an ellipsoid, cut flat at the floor.
- **Blending:** parts are joined with a polynomial smooth minimum, with blend radii head 2.5, legs 4, feet 3 and arms 2.5 cm. This is what makes shoulders flow into arms and hips into legs. The arm blend radius is smaller than the arm clearance, so no measured section is fattened.
- **Symmetric order:** the smooth minimum isn't associative, so each left/right pair is blended together first.

### Mesh
The mesh is built with **surface nets**:
- It samples only a narrow band: 4³ blocks are probed at their centre and skipped when far from the surface.
- The x grid is symmetric about the centre line.
- Each vertex gets one Newton step onto the exact surface.
- The fine mesh (0.8 cm cells, about 37k vertices) takes about 1 s, so it runs in a **Web Worker**. While a slider is being dragged, a 2 cm preview is shown; the fine mesh follows once the body stops changing. Only one build is ever in flight.

---

## Rendering

The view uses a matte white material (`MeshStandardMaterial`, roughness 0.58). Lighting:
- soft reflections from three's procedural `RoomEnvironment`, via PMREM;
- a key light casting a soft (PCF) shadow onto an invisible shadow-only floor;
- a fill light and a rim light;
- a radial-gradient backdrop behind a transparent canvas.

Frames render on demand, when the camera moves or the mesh changes. React context doesn't cross into the r3f `<Canvas>` in fiber v8, so the body is resolved outside it and the geometry is passed in as props.

---

## Tests

`src/three/avatarBuilder.test.ts`:
- **Sizing:** the ellipse inverse; profile resolution; each measured section tapes to its measurement within 0.5%.
- **Shape:** the bust–underbust difference becomes breast projection, with a cleavage set back from the apexes; shape presets change the silhouette but not the measurements; changing the bust doesn't change the waist.
- **Robustness:** sections are strictly ordered at every slider extreme; smoothing never folds or overshoots; the arms clear the torso for extreme bodies.
- **Final surface:** tape measurements taken on the **final blended surface** match bust, waist and hip within 2%; the mesh has no holes and faces outward; it is mirror-symmetric, stands on the floor, and reaches its height; the neck and crotch are continuous; the build time is logged.

`src/context/EditorContext.test.ts` covers the profile actions, keeping the profile through `LOAD_STATE`, and the profile staying out of undo history.

---

## Garment fit preview (phase 2)

In the 3D view, **Show garment** places the current pattern on the body; **Fit map** colours bands where the garment is **snug** (amber, no ease) or **tight** (red, fabric smaller than the body). Placement runs in a Web Worker (`garmentWorker.ts`). Only the newest request is built; while it builds, a spinner shows in the panel.

### Body-agnostic by design
The garment code talks to the body only through **`BodyQuery`** (`bodyQuery.ts`):
- the tape outline (convex hull) of the body at any height, including both legs below the hips;
- a leg section, and an arm section along the arm axis;
- the neck section;
- the height of the shoulder top at any lateral position;
- the signed distance field.

The procedural body implements it today. A sculpted base mesh only needs to implement the same interface, for example by slicing the mesh.

### Classification (`pieceClassifier.ts`)
Classification uses seam labels first, then the piece name:
- `center_sleeve` or `sleeve_seam` → sleeve;
- `inseam` or `crotch` → leg;
- `shoulder` or `armhole` → upper torso (hangs from the shoulders);
- `side_seam` with `waist` or `waist_seam` → lower torso (hangs from the waist).

`center_back` marks a back piece. Trims (facings, bindings, pockets, collars, cuffs, flies, waistbands, yokes, straps and so on) are skipped and listed as "Not shown in 3D".

### Wrapping (`garmentWrap.ts`)
- **Normalise.** A piece's outline is chained into an ordered loop (curves flattened), then flipped if needed so the centre edge is on the left and the top is up. That's the engine's convention, and it undoes any flips made on the canvas.
- **Rows.** Each horizontal row of the piece is laid around the body's tape outline at the matching height:
  - The centre edge (fold, CF or CB) lands on the body's centre line, and the side seam on its side line. Front and back side seams therefore meet by construction.
  - Horizontal position is proportional: sewn distance from the centre ÷ the row's sewn width.
  - Vertical position is 1:1 with height, measured from the anchor.
- **Anchors.**
  - Upper-torso pieces hang from the high point of the shoulder, at the body's shoulder top beside the neck.
  - Lower-torso and leg pieces hang from the waist, at the top of the side seam.
  - A piece with both a shoulder and a waist seam (a dress bodice) is stretched so the waist seam sits at the body's waist.
- **Ease → stand-off.** At each height, the fabric loop (2 × (front width + back width)) is compared with the body's tape. The surplus becomes a radial stand-off of surplus ÷ 2π, plus a 0.35 cm gap, so flare and ease are visible. The ratio fabric ÷ body is the vertex's *ease*: below 0.97 is tight, below 1.0 snug.
- **Darts.** Interior dart legs (unlabelled line pairs sharing an apex, running mostly vertically) are closed. Their intake is removed from the row's width, and both legs map to the same body point.
- **Shoulders.** Within 7 cm of the shoulder seam, the fabric curves up over the shoulder, along a quarter ellipse, onto the ridge. Between the centre line and the neck point it goes around the base of the neck. Front and back shoulder seams therefore meet.
- **Trouser legs.** Above the crotch, a leg piece wraps a torso quadrant (CF/CB to side). Below it, it wraps the leg (inseam to side seam, through the front or back). The two are blended over ±4 cm.
- **Sleeves** run along the arm axis from the top of the shoulder cap. The fold lies on top of the arm and the sleeve seam underneath. The folded half becomes the other half of the same sleeve; cut 2 gives the other arm.
- **Mirroring.** On-fold and cut-2 torso and leg pieces are mirrored (x → −x) to the other side.
- **Push-out.** Any point closer than the gap to the skin is pushed out along the field gradient. The step is divided by the gradient magnitude, because blended regions have gradients weaker than 1.

### Tests (`garmentWrap.test.ts`)
The tests run against real engine outputs for skirt, trousers, shirt, dress and vest:
- **Classification:** body regions are recognised, and the trousers' fly facing and fly shield are skipped.
- **Seams:** every physically sewn side, shoulder and inseam seam lands together in 3D. Side seams and shoulders measure 0.00 cm; the inseam is within 1.1 cm. The dress waist seam lands at the body's waist height.
- **Darts and folds:** both legs of a dart map to the same line, and fold edges land on the centre plane.
- **Surface:** no fabric point is inside the body.
- **Mirroring:** copies are exact mirror images.
- **Fit:** an A-line hem stands further off the body than its waist, and a shrunken skirt is flagged tight.
- **Legs:** trouser legs wrap each leg.
- **Performance:** placement takes about 0.2–2 s per garment.

### What the fit map revealed (backend bugs — both fixed)
- **Darts double-counted.** In `skirts.py` (and the dress and trouser blocks), the waist edge is drawn at the waist quarter *and* darts sized at hip quarter − waist quarter are placed inside it. Sewn up, the waist is about 26 cm smaller than the body. **Fixed:** `split_waist_reduction()` in `skirts.py` now splits the reduction between darts (front: 40%, capped at 3 cm; back: 60%, capped at 6 cm; trousers: 35% / 2.5 cm and 60% / 5 cm) and side shaping. The waist edge is drawn at waist quarter + dart intake. A dress skirt's waist quarters now equal the bodice's sewn waist on each side, and `tests/test_waist_shaping.py` pins the invariant: sewn waist = target.
- **Spurious seam connections.** `_compute_connections` pairs *any* two edges with the same label: a dress bodice side seam with a skirt side seam, front and back armholes, even hem with hem. The 3D placement doesn't use connections. **Fixed:** pairing now depends on the kind of seam (construction / horizontal join / opening; see the README file-format section), with tests in `tests/test_connections.py`. Connections are a true stitch map for phase 3.

### Known limits (static preview)
- **Vertical mapping:** it doesn't follow surface curvature. The front length over the bust isn't lengthened, except where a waist seam anchors the piece.
- **Seam lengths:** there's no length matching between sewn edges of different lengths, such as eased sleeve caps.
- **Asymmetric pieces:** cut-1 non-fold pieces (for example the asymmetric wrap fronts) are placed once, on the right.
- **Skipped details:** horizontal (bust) darts, yokes and princess seams are not handled yet.

---

## Drape simulation (phase 3)

With **Drape with gravity** on (the default), the static wrap is the starting pose. From there a cloth simulation settles the garment into a natural hang. The worker streams a frame every 6 steps, so the garment visibly settles over about 2–4 s. The view only moves vertices in place; geometry is rebuilt only when the placement changes. Changing the body or the pattern restarts the placement and drape, and a drape still in progress is abandoned.

**Solver.** Position-based dynamics in the "small steps" form (Macklin et al. 2019): 16 substeps per 1/60 s step, one constraint pass each, 150 steps. It is hand-rolled, because a generic cloth library knows nothing about the pattern's seams. One particle array holds every copy of every piece.
- **Stretch:** every mesh edge keeps its **flat pattern length**. Compression is softer (0.4), so fabric can buckle into folds.
- **Strain limiting:** an extra pass pulls over-stretched edges back.
- **Bending:** soft (0.12) constraints between the far corners of neighbouring triangles.
- **Tethers:** long-range attachments (Kim et al. 2012). Each particle may be no farther from its nearest vertex on the edge its piece hangs from (shoulder / waist / armhole) than its flat distance plus 10%. There's no tether within 15 cm of the anchor. This carries the garment's weight to where it hangs.
- **Seams are welded:** every connection in the stitch map is sewn copy by copy on the same side of the body; a sleeve's front half is sewn to the front bodice and its back half to the back. Placement samples both sides of a seam **identically** (`conformSeamCounts`): edges joined by connections, transitively, share one vertex count, spread uniformly by arc length. A sleeve armhole joined to both bodice armholes therefore matches both. The seam's vertices are then welded 1:1, so the two sides share particles and **cannot open**. Eased seams gather evenly because matching is by arc-length fraction. An edge split by darts gets its count spread across its segments and is sewn as one chain. Constraint stitching remains only as a fallback if sampling ever differed; the tests assert it never happens. (Stitching alone left seams 0.5–1 cm open, which showed as visible cracks.)
- **Welds:** a piece's own seams between its mirrored copies (fold, CF/CB, crotch, sleeve underarm) and the two legs of each dart share particles one to one. A fold is continuous fabric, and welding leaves no hairline.
- **Darts:** darts are cut out of the mesh (`cutDarts`: their legs become edges) and sewn shut. That's what takes the dart intake out of the waist; with the wedge left in, a darted skirt slid down to the high hip.
- **Collision:** against a narrow-band grid of the body's distance field (`SdfGrid`: 1 cm cells, trilinear lookups), keeping the fabric 0.35 cm off the skin, and against the floor. Two contact passes per substep resolve corners where two contacts meet, such as foot and floor.
- **Friction:** Coulomb (static 0.9 / kinetic 0.6). Slip smaller than μs × the normal push is cancelled entirely. Without static friction, the push-out along a sloped surface ratchets a waistband down the hips.

**Placement changes made for draping.** The static wrap is the drape's starting pose, so two things changed in it:
- **Crotch curve:** it now runs *under* the body from the centre line to one crotch point, where front and back meet; before, it went around the front.
- **Garment mesh:** 2 cm spacing, coarser and so stiffer and faster.

**Results.** From the drape tests on real engine patterns:

| Garment | Particles | Time (test) | Stretch where the pattern fits: mean / 98th pct | Seams |
|---|---|---|---|---|
| Skirt (A-line, darts) | ~2000 | ~2 s | 0.34% / 3.0% | welded (0 gap) |
| Trousers (straight, darts) | ~3200 | ~4 s | 1.2% / 5.7% | welded (0 gap) |
| Shirt (regular, sleeves) | ~3600 | ~4 s | 0.37% / 3.2% | welded (0 gap) |
| Dress (a-line, darted skirt) | ~2000 | ~2 s | 0.37% / 3.2% | welded (0 gap) |

All four settle: kinetic energy falls by more than 4×. At least 99% of cloth ends up outside the body, none of it more than 1 cm inside. The skirt stays at the waist, trousers hang from the waist (they settle up to about 4 cm, onto their drafted crotch drop), and the shirt hangs from the shoulders.

**What the drape revealed.** A hip-length shirt drafted its hem at *waist* width, so it could not cover the hips. Fixed in `shirts.py` (`_hem_qt`): below the waist, the hem widens to the hip quarter + ease by hip level.

**Known limits.**
- **Crotch point:** the trouser crotch point is welded shut, but it sits between the thighs, which touch in this body model, so the fabric there is wedged against the body.
- **Full-length hems:** they wedge between the foot and the floor and stretch locally.
- **No self-collision:** layers (sleeve against bodice, overlap fronts) can pass through each other.
- **No fabric properties yet:** the stiffness and weight sliders are future work.
- **Too-small garments:** where a pattern is smaller than the body, the fabric strains and jitters instead of riding up. The fit map marks these areas red.

---

## Next: sculpted base mesh (Fusion 360)

A body modelled in Fusion 360 is exported as a mesh (OBJ, FBX or STL, converted to `.glb`) and loaded in place of the procedural surface. Fusion gives a single fixed body. To fit it to the user's measurements, the mesh will be **deformed at runtime rather than morphed**:
1. **Segment** the vertices into torso, arms and legs.
2. **Measure** the mesh with the same tape code (convex hull of horizontal slices) at each landmark level.
3. **Scale** each vertex radially about its section centre. The scale factor is interpolated between landmark levels so each slice's tape matches the target. Height scales the levels.

This keeps the sculpted anatomy and makes the tape accurate. Shape presets become section-shape targets rather than generated lobes.

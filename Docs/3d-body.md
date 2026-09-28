# 3D Body & Garment Fit

The 3D view shows a measurement-driven body (a mannequin) that the user can resize and reshape. It is the base for putting the drafted pattern on that body. The work ships in three phases, each its own entry in `harness/FEATURES.json`:

| Phase | Feature id | Status |
|-------|-----------|--------|
| 1. Parametric body avatar + customization UI | `body-avatar-3d` | **Done** |
| 2. Static fit preview: pattern pieces wrapped onto the body using `SeamConnection` topology | `garment-3d-fit-preview` | Planned |
| 3. Physics drape: position-based dynamics cloth, seams as stitching constraints, capsule body collision | `garment-3d-drape-simulation` | Planned |

Everything runs in the browser, and no backend endpoint is involved. That keeps slider changes live, the same way the 2D canvas recomputes parametric formulas as you type.

---

## Libraries

| Package | License | Why |
|---------|---------|-----|
| `three` | MIT | WebGL scene graph. Writing raw WebGL would take days, so the project rule is to use an established free library. |
| `@react-three/fiber` **v8** | MIT | Lets the scene be written as React components. v9 needs React 19; the app is on React 18. |
| `earcut` (phase 3) | ISC | Triangulates concave pattern pieces. three.js uses it internally too. |

`@react-three/drei` is deliberately **not** used. The only part we'd use is OrbitControls, and drei pulls in a large dependency tree. `three/examples/jsm/controls/OrbitControls.js` is used directly instead.

**Bundle:** `BodyModelView` is loaded with `React.lazy()`. three.js ends up in its own chunk (about 230 KB gzipped) that is fetched only when the 3D view is first opened. The main bundle carries only the small body-math module (`src/three/bodyRegions.ts`), which the side panel needs.

---

## Files

```
frontend/src/three/
  types.ts            BodyProfile, ResolvedBody, LoftRing, MeshData, AvatarData
  bodyRegions.ts      Body fields + defaults, profile resolution, shape presets, ellipse math,
                      landmark rings for torso / legs / arms / head, arm A-pose frame
  avatarBuilder.ts    Monotone-cubic ring smoothing, loft (tube + end caps), buildAvatar()
  avatarBuilder.test.ts
frontend/src/components/
  BodyModelView.tsx           Lazy 3D view: r3f <Canvas> (on-demand rendering), OrbitControls, lights
  BodyCustomizationPanel.tsx  Body sliders + shape preset + reset (right sidebar, 3D view only)
```

`avatarBuilder` returns plain typed arrays (`Float32Array` positions, `Uint32Array` indices) and never imports three. That makes the geometry testable in Vitest without WebGL. `BodyModelView` wraps the arrays in `BufferGeometry` and calls `computeVertexNormals()`.

---

## Body profile & measurement resolution

`EditorState.bodyProfile = { overrides, shape }` stores **only the values the user has set** on the Body panel. Each field resolves as:

```
override  ??  state.measurements[measurementKey]  ??  default     → clamped to [min, max]
```

Only true body measurements are mapped from the Measurements panel: `bust`, `waist`, `hip`, `waistToHip`, `inseam`, `shoulder`. `sleeveLength` is deliberately *not* treated as arm length, because a short sleeve isn't an arm. The panel tags each field as `custom` (an override) or `measured` (coming from the Measurements panel). **Reset to measurements** clears the overrides and keeps the shape preset.

The profile belongs to the user, not the pattern:
- `LOAD_STATE` (open a `.psnap`, AI generate, refine) keeps it.
- It is not part of `EditorSnapshot`, so undo/redo never changes it.
- It is not saved in `.psnap` yet. Persistence is deferred until the feature has proven itself.

| Field | Range (cm) | Default | From measurement |
|-------|-----------|---------|------------------|
| height | 140–210 | 168 | — |
| bust / underbust | 60–160 / 55–140 | 92 / 76 | `bust` / — |
| waist / waistToHip / hip | 45–150 / 10–35 / 60–170 | 74 / 20 / 98 | `waist` / `waistToHip` / `hip` |
| neck / shoulder | 28–50 / 30–55 | 36 / 39 | — / `shoulder` |
| armLength / upperArm / wrist | 45–75 / 20–50 / 12–22 | 58 / 29 / 16 | — |
| inseam / thigh / knee / calf / ankle | 60–95 / 40–85 / 28–50 / 25–50 / 18–32 | 77 / 56 / 37 / 36 / 23 | `inseam` / — |

Underbust is clamped to be no larger than bust.

---

## Avatar geometry: cross-section loft

The body is a set of **lofts**. Each loft is a tube through elliptical cross-sections called rings. A ring is `p(θ) = center + a·cosθ·u + b·sinθ·w`: `u` is the lateral axis, `w` is the front-back axis (+z = front), and +y is up. Units are cm, and the floor is at y = 0.

**Ellipse sizing.** Ramanujan's perimeter approximation is `P ≈ π[3(a+b) − √((3a+b)(a+3b))]`. With `b = r·a` it is linear in `a`, so a ring with circumference `C` and depth ratio `r` is solved in closed form: `a = C / (π·k(r))`, where `k(r) = 3(1+r) − √((3+r)(1+3r))`.

**Landmark heights.** These are fractions of height, using adult mannequin proportions:

| Level | y |
|-------|---|
| neck top / neck base | 0.872H / 0.835H |
| shoulder point | 0.812H |
| armpit | 0.75H |
| bust | 0.72H |
| underbust | 0.68H |
| waist | 0.62H |
| knee / calf / ankle | 0.285H / 0.215H / 0.05H |
| crotch | the **inseam** (clamped to 0.40H–0.52H) |
| hip | waist − **waistToHip** (clamped between crotch + 5 and waist − 8) |

**Torso rings.** From the top: neck top → neck base → trapezius (a sloped section, so the shoulder falls away from the neck instead of forming a flat shelf) → shoulder → armpit → bust → underbust → waist → hip → seat → crotch. The crotch section closes the torso between the legs.

**Legs.** Each leg starts *inside* the torso as a section smaller than the thigh, so the hips flow into the legs without a ledge. It continues thigh → mid-thigh → knee → calf → ankle → foot. The foot is an ellipse elongated front-to-back, closed to a point on the floor.

**Arms** hang in an A-pose:
- **Joint:** at the shoulder point, pushed out to the ribcage side if the chest is broader than the shoulder measurement.
- **Angle:** opens from 12° just far enough that the arm clears every torso section from the bust down, capped at 45°. Wide hips and an apple waist push the arms out.
- **Top:** rounded with hemisphere sections at 35° and 65°.
- **Hand:** palms face the thighs, so from the wrist down the wide axis runs front to back.

**Head:** an ellipsoid built from latitude rings. The crown is exactly at `height`.

**Shape presets** set, for each landmark, the depth ratio `b/a` (bust, underbust, waist, hip) and front/back projection offsets for the bust, belly (waist) and seat:

| Preset | waist `b/a` | belly `z` | seat `z` |
|--------|------------|-----------|----------|
| hourglass | 0.72 | 0 | −1.5 |
| rectangle | 0.78 | 0 | −0.8 |
| pear | 0.72 | 0 | −1.8 (hip `b/a` 0.66, the widest) |
| apple | 0.95 | +3.5 | −0.5 |

**Smoothing.** Between landmarks, `smoothRings` inserts rings using **monotone cubic (Fritsch–Carlson) Hermite interpolation**. Each of `a`, `b` and the centre x/y/z is interpolated separately, over distance along the body. The interpolant never overshoots the data. As a result:
- no section bulges past its neighbouring landmarks;
- height stays monotone down the torso, so rings can't fold;
- extremes such as the waist or belly come out rounded rather than pointed.

**Loft.** Consecutive rings are bridged with quads. The winding is chosen per ring pair from the sign of `(u × w) · (next − prev)`, so faces point outward whichever way a limb runs. The ends are closed with triangle fans to a cap point. Rings use 32 segments and 4 subdivisions per landmark span.

---

## Rendering

- `frameloop="demand"`: a frame is drawn only when OrbitControls fires `change` or a React prop changes, such as the geometry after a slider move. The view uses no CPU while idle.
- React context doesn't cross into the r3f `<Canvas>` in fiber v8. The avatar is therefore built *outside* the canvas from editor state, and the geometry is passed in as props.
- The camera is positioned once, from the initial height. Later height changes only re-aim the orbit target, so the view isn't yanked while the user drags a slider.
- Old geometries are disposed whenever they are rebuilt.

---

## Tests

`src/three/avatarBuilder.test.ts`:
- the ellipse inverse is exact;
- profile resolution order, including that a sleeve length is not used as arm length;
- sampled landmark rings are within 2% of the input bust, waist, hip and thigh;
- the whole mesh is mirror-symmetric about x = 0;
- the bounding box runs from 0 to `height`;
- the waist ring doesn't change when the bust changes;
- presets change waist depth and belly projection;
- torso rings are strictly ordered with positive axes at every slider extreme;
- smoothing never folds or overshoots;
- the arms clear the torso for wide-hip, narrow-shoulder and large-bust bodies;
- every part has valid indices.

`src/context/EditorContext.test.ts` covers the profile actions, keeping the profile through `LOAD_STATE`, and the profile not being in undo history.

---

## Phases 2–3 (planned)

- **Fit preview.** `pieceClassifier.ts` scores each piece's body region from its seam-label set plus keywords in its name. `garmentWrap.ts` maps each piece's flat (u, v) onto the matching body tube and mirrors on-fold pieces. It then rigidly aligns pieces along paired `SeamConnection` edges, the 3D version of `AssemblyView`'s edge alignment. Trims (bindings, facings, pockets, welts, interior marks) stay 2D-only.
- **Drape.** Hand-rolled position-based dynamics:
  - pieces are triangulated with earcut;
  - structural rest lengths are the flat-pattern distances, plus bending constraints;
  - paired seams are matched by arc length and become near-zero-length stitching constraints;
  - fold lines are pinned to the centre plane;
  - collision against capsules derived from the loft rings above.
- **Known limits.** Region classification is a heuristic, because `PieceSpec` has no body-region field. A later backend change could add one. Cut-2 pieces have no left/right distinction.
